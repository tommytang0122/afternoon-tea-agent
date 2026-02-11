---
title: 台北 Uber Eats 下午茶 Agent 設計稿
date: 2026-02-09
status: archived
superseded_by: docs/implementation-plan.md
tags:
  - kanjo-ai-assets
  - 架構方案
  - 技術實作
  - local-agent
  - ubereats
  - LLM
aliases:
  - UberEats 下午茶推薦設計
  - 台北地址外送篩選 Agent
---

# 台北 Uber Eats 下午茶 Agent 設計稿

> Archived 文件：此稿為 v1.0 設計，內容包含 SQLite / server / validator 等舊架構。  
> 目前以 `docs/implementation-plan.md` 與 `apps/ubereats-local-web/{crawler.py,classifier.py,pipeline.py}` 為準。

## 概述

本設計目標是建立一個**僅本地執行**的 AI agent，自動從 Uber Eats 取得「可外送到固定台北地址」的候選店家與品項，並輸出固定結果：
- `2` 種飲料
- `2` 種食物

每個品項需來自**不同店家**，且必須通過以下驗證：
- 範圍正確：店家確實可外送到指定地址
- 項目適合度正確：品項適合作為下午茶（由 LLM 語意判定）
- 金額正確：店家品項平均單價 `< 200` 新台幣（不含外送費/服務費）

輸出欄位固定包含：
- `商店名`
- `Uber Eats 店家頁連結`
- `Uber Eats 團購連結資訊`（優先自動建立；若無有效登入態則提供手動建立指引）

---

## 需求邊界

| 類別 | 規格 |
|-----|------|
| 執行環境 | 僅本地執行（不部署 GCP） |
| 地址來源 | `.env` 固定參數，不需手動輸入 |
| 候選池更新 | 每 `24` 小時更新一次 |
| 適合度判定 | LLM 語意分類 |
| 金額口徑 | 品項單價平均 `< 200`（不含外送費/服務費） |
| 輸出筆數 | 固定 `2` 飲料 + `2` 食物 |
| 店家重複 | 禁止，四筆必須不同店 |
| 不足處理 | 嚴格失敗，不放寬條件、不補位 |
| 團購連結策略 | 預設手動；若有有效登入態則自動建立 |

---

## 系統架構

### 元件清單

| 元件 | 功能 |
|-----|------|
| `scheduler` | 每 24 小時觸發候選池更新 |
| `crawler` | 抓取地址可外送店家、菜單品項、單價、店家連結 |
| `classifier` | 使用 LLM 判定下午茶適合度與理由 |
| `validator` | 二次驗證範圍/價格/分類證據 |
| `selector` | 從候選池選出 `2` 飲料 + `2` 食物且店家不重複 |
| `group-order-linker` | 建立團購連結或回傳手動建立資訊 |
| `storage` | SQLite 儲存結構化資料；`artifacts/` 保存審計證據 |

### 架構流程

```text
.env 固定地址
  -> [scheduler 每24h]
  -> [crawler 抓店家與品項]
  -> [classifier LLM判定下午茶適合度]
  -> [storage 寫入SQLite + artifacts]

查詢執行
  -> [selector 選2飲料+2食物 且不同店]
  -> [validator 即時重查]
  -> [group-order-linker 建立團購連結或手動指引]
  -> 輸出固定格式
```

---

## 資料模型

### `stores`

| 欄位 | 類型 | 說明 |
|-----|------|------|
| `store_id` | text | 店家唯一識別 |
| `name` | text | 商店名 |
| `store_url` | text | Uber Eats 店家頁連結 |
| `deliverable` | integer | 是否可外送到固定地址（0/1） |
| `last_checked_at` | datetime | 最近驗證時間 |

### `items`

| 欄位 | 類型 | 說明 |
|-----|------|------|
| `item_id` | text | 品項唯一識別 |
| `store_id` | text | 關聯店家 |
| `name` | text | 品項名稱 |
| `price_twd` | integer | 單價（TWD） |
| `currency` | text | 幣別，固定 `TWD` |

### `classifications`

| 欄位 | 類型 | 說明 |
|-----|------|------|
| `item_id` | text | 關聯品項 |
| `is_afternoon_tea` | integer | 是否適合下午茶（0/1） |
| `category` | text | `drink` 或 `food` |
| `score` | real | 適合度分數（0-1） |
| `reason` | text | LLM 判定理由 |
| `model` | text | LLM 模型名稱 |
| `classified_at` | datetime | 判定時間 |

### `evidence`

| 欄位 | 類型 | 說明 |
|-----|------|------|
| `entity_type` | text | `store` 或 `item` |
| `entity_id` | text | 對應 ID |
| `html_path` | text | 原始 HTML 路徑 |
| `screenshot_path` | text | 截圖路徑 |
| `captured_at` | datetime | 證據擷取時間 |

### `sessions`

| 欄位 | 類型 | 說明 |
|-----|------|------|
| `provider` | text | `ubereats` |
| `is_valid` | integer | 登入態是否有效 |
| `expires_at` | datetime | 估計到期時間 |
| `updated_at` | datetime | 更新時間 |

---

## 核心流程

### 1. 候選池更新（每日一次）

1. 載入 `.env` 地址並設定 Uber Eats 查詢上下文。
2. 抓取可外送店家清單與店家頁連結。
3. 抓取店家菜單品項與單價。
4. 以 LLM 判定每個品項是否屬於下午茶，並分類 `drink/food`。
5. 以店家維度計算 `avg_item_price = 所有品項單價平均`。
6. 僅保留 `deliverable=1` 且 `avg_item_price < 200` 的候選資料。
7. 保存 HTML/截圖證據至 `artifacts/`，同步寫入 SQLite。

### 2. 查詢與輸出（即時）

1. 從最新候選池讀取符合條件資料。
2. 依 `score` 由高到低排序，分別挑選飲料候選與食物候選。
3. 套用「店家不重複」約束，選出 `2` 飲料 + `2` 食物。
4. 對最終 4 筆執行即時重查（可送達、價格、分類證據存在）。
5. 生成團購連結資訊：
   - 若 `sessions.is_valid=1`，嘗試自動建立團購房連結。
   - 否則輸出手動建立團購指引。
6. 回傳固定格式。

---

## 驗證與失敗策略

### 驗證規則

| 驗證項 | 條件 | 不通過行為 |
|-------|------|-----------|
| 範圍正確 | `deliverable=1` 且 final 重查仍可送達 | 立即失敗 |
| 項目適合度正確 | `is_afternoon_tea=1` 且 `category` 正確 | 立即失敗 |
| 金額正確 | 店家 `avg_item_price < 200` 且 final 價格未變動超閾值 | 立即失敗 |
| 證據完整 | HTML/截圖與判定理由存在 | 立即失敗 |
| 組合完整 | 2 飲料 + 2 食物 + 4 家不同店 | 立即失敗 |

### 失敗代碼（範例）

| 代碼 | 說明 |
|-----|------|
| `INSUFFICIENT_DRINKS` | 飲料候選不足 2 筆 |
| `INSUFFICIENT_FOODS` | 食物候選不足 2 筆 |
| `STORE_DUPLICATION_CONFLICT` | 無法在不重複店家下湊滿 4 筆 |
| `DELIVERY_OUT_OF_RANGE` | 最終重查不在外送範圍 |
| `PRICE_MISMATCH` | 最終重查價格或平均單價不符 |
| `CLASSIFICATION_MISMATCH` | 分類結果不一致 |
| `EVIDENCE_MISSING` | 缺少審計證據 |

---

## 輸出格式（固定）

```json
{
  "address": "<from .env>",
  "generated_at": "2026-02-09T14:30:00+08:00",
  "result": {
    "drinks": [
      {
        "store_name": "A店",
        "item_name": "拿鐵",
        "ubereats_store_url": "https://www.ubereats.com/...",
        "group_order": {
          "mode": "auto_created",
          "url": "https://www.ubereats.com/group-orders/...",
          "note": ""
        }
      }
    ],
    "foods": [
      {
        "store_name": "B店",
        "item_name": "起司蛋糕",
        "ubereats_store_url": "https://www.ubereats.com/...",
        "group_order": {
          "mode": "manual_instruction",
          "url": "",
          "note": "開啟店家頁後點選『開始團購』建立連結"
        }
      }
    ]
  },
  "validation": {
    "range_ok": true,
    "suitability_ok": true,
    "price_ok": true,
    "audit_ready": true
  }
}
```

---

## `.env` 設定

```dotenv
UBER_EATS_TAIPEI_ADDRESS=台北市信義區市府路45號
CANDIDATE_REFRESH_HOURS=24
MAX_AVG_ITEM_PRICE_TWD=200
REQUIRED_DRINK_COUNT=2
REQUIRED_FOOD_COUNT=2
REQUIRE_DISTINCT_STORES=true
GROUP_ORDER_MODE=auto_if_logged_in
SQLITE_PATH=./data/ubereats_agent.db
ARTIFACTS_DIR=./artifacts
LLM_MODEL=<your-model-name>
LLM_API_KEY=<your-api-key>
```

---

## 測試計畫

| 測試層級 | 案例 | 驗收標準 |
|---------|------|---------|
| Unit | 平均單價計算 | 多品項店家平均值正確，單位為 TWD |
| Unit | 類別選擇器 | 可穩定選出 2 飲料 + 2 食物 |
| Unit | 去重邏輯 | 四筆結果無店家重複 |
| Integration | 候選池更新 | 每日流程可寫入 SQLite 與 artifacts |
| Integration | 最終重查 | 任一驗證失敗即整體失敗 |
| E2E | 成功路徑 | 輸出欄位完整含商店名與團購資訊 |
| E2E | 失敗路徑 | 不足 4 筆時回傳明確錯誤代碼 |

---

## 交付定義（Definition of Done）

- 本地可執行每日候選池更新。
- 查詢可穩定輸出固定格式：`2` 飲料 + `2` 食物。
- 四筆結果皆為不同店家，且每筆含商店名與兩種連結資訊。
- 三項驗證（範圍/適合度/金額）可審計且可重現。
- 任何不足情境皆嚴格失敗並提供原因碼。

---

## 相關連結

- [[skills/superpower/brainstorming/SKILL]]
- [[skills/obsidian/obsidian-markdown/SKILL]]
- [[skills/obsidian/obsidian-tommy-style/SKILL]]
