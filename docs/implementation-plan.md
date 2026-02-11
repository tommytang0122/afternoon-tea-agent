# 下午茶 Agent — 產品需求文件 (PRD)

> 最後更新：2026-02-10

---

## 1. 問題陳述

每次用 Uber Eats 開團體訂單訂下午茶時，需要：
1. 手動瀏覽數十家店，判斷哪些適合下午茶
2. 比對價格、過濾正餐店（便當、火鍋等）
3. 挑選飲料和食物的搭配組合
4. 逐一開啟店家頁面複製連結

整個流程每次耗時 15-30 分鐘，且重複性極高。

---

## 2. 解決方案

兩階段架構，以 JSON 檔案作為中介格式：

| | 階段一：資料預處理 | 階段二：問答輸出 |
|---|---|---|
| **觸發** | `python pipeline.py` | 在 Claude Code CLI 直接對話 |
| **核心** | Playwright 爬蟲 + Gemini API 篩選 | Claude Code 讀 dataset JSON |
| **產出** | `dataset/*.json` | 終端回覆 + `history.jsonl` 紀錄 |
| **頻率** | 需要時手動執行 | 隨時對話 |

### 為何選此架構

- **不需 Web Server**：使用者本身就在 Claude Code CLI 工作，直接對話比開網頁更自然
- **JSON > SQLite**：LLM 友善格式，方便 Claude Code 直接讀取和推理
- **Gemini 一次篩選 > rule-based + LLM fallback**：減少分類邏輯複雜度，prompt 即規則

---

## 3. 系統流程

```
.env（台北地址 + Gemini API Key）
  │
  ▼
┌─────────────────────────────────────────────┐
│ python pipeline.py                          │
│                                             │
│  Step 1: Playwright 爬蟲                    │
│    Uber Eats → 蒐集店家 + 菜單              │
│    → dataset/raw_stores.json                │
│                                             │
│  Step 2: Gemini API 篩選                    │
│    raw_stores.json → 過濾 + 分類             │
│    → dataset/afternoon_tea.json             │
└─────────────────────────────────────────────┘
  │
  ▼
┌─────────────────────────────────────────────┐
│ Claude Code CLI 對話                        │
│                                             │
│  使用者：「甜食+冷飲」                        │
│  Claude：讀取 afternoon_tea.json             │
│          → 推薦 4 間不同店                    │
│          → append history.jsonl              │
└─────────────────────────────────────────────┘
```

---

## 4. 資料格式規格

### 4.1 `dataset/raw_stores.json` — 爬蟲原始輸出

```json
[
  {
    "name": "晨光咖啡",
    "category": "",
    "url": "https://www.ubereats.com/tw/store/morning-coffee/abc123",
    "menu_items": [
      {"name": "拿鐵", "price_twd": 120},
      {"name": "美式", "price_twd": 90}
    ],
    "avg_price": 105
  }
]
```

| 欄位 | 型別 | 說明 |
|------|------|------|
| `name` | string | 店名（從 Uber Eats 頁面擷取） |
| `category` | string | Uber Eats 分類標籤（爬蟲可能為空） |
| `url` | string | Uber Eats 店家頁面 URL |
| `menu_items` | array | 品項清單 `[{name, price_twd}]` |
| `avg_price` | integer | 所有品項平均價格（四捨五入至整數） |

### 4.2 `dataset/afternoon_tea.json` — Gemini 篩選後

```json
{
  "generated_at": "2026-02-10T12:00:00+00:00",
  "store_count": 18,
  "stores": [
    {
      "name": "晨光咖啡",
      "type": "熱飲",
      "tags": ["咖啡", "茶"],
      "url": "https://www.ubereats.com/tw/store/morning-coffee/abc123",
      "avg_price": 105,
      "top_items": ["拿鐵 $120", "美式 $90", "伯爵茶 $100"]
    }
  ]
}
```

| 欄位 | 型別 | 說明 |
|------|------|------|
| `generated_at` | ISO 8601 | 產生時間 |
| `store_count` | integer | 篩選後店家數 |
| `stores[].name` | string | 店名 |
| `stores[].type` | enum | `甜食` \| `鹹食` \| `冷飲` \| `熱飲` \| `其他` |
| `stores[].tags` | string[] | 輔助分類標籤 |
| `stores[].url` | string | Uber Eats 店家頁面 URL |
| `stores[].avg_price` | integer | 平均品項價格（TWD） |
| `stores[].top_items` | string[] | 最多 5 個代表品項（格式：`品名 $價格`） |

### 4.3 `dataset/history.jsonl` — 推薦紀錄

每行一筆 JSON：

```json
{"timestamp": "2026-02-10T15:30:00+08:00", "query": "甜食+冷飲", "result": [{"name": "甜點角落", "type": "甜食", "avg_price": 165, "url": "..."}]}
```

---

## 5. 元件規格

### 5.1 crawler.py — Playwright 爬蟲

**路徑**：`apps/ubereats-local-web/crawler.py`

**職責**：從 Uber Eats 爬取可外送店家與菜單，寫入 `dataset/raw_stores.json`。

**核心函式**：

| 函式 | 簽名 | 說明 |
|------|------|------|
| `set_delivery_address` | `async (page, address) → None` | 設定外送地址 |
| `collect_store_links` | `async (page, max_stores) → list[dict]` | 捲動 feed 蒐集店家連結 |
| `scrape_store_menu` | `async (page, store_url) → list[dict]` | 爬取單店菜單品項與價格 |
| `crawl_stores` | `async (address, output_path, headed, max_stores) → list[dict]` | 主流程：地址→店家→菜單→JSON |

**設計決策**：
- Headless 預設，`--headed` flag 供偵錯
- 每步隨機延遲 2-5 秒，模擬人類行為
- 最多 30 家店（透過 `MAX_STORES_PER_CRAWL` 設定）
- 兩層菜單解析策略：先找 `data-testid` item cards，fallback 掃描 `main` 文字
- `avg_price` 在寫入時即計算（非 Gemini 端計算）

**CLI 用法**：
```bash
python crawler.py              # headless
python crawler.py --headed     # 可見瀏覽器
```

### 5.2 classifier.py — Gemini API 篩選

**路徑**：`apps/ubereats-local-web/classifier.py`

**職責**：讀取 `raw_stores.json`，呼叫 Gemini API 篩選並分類，寫入 `dataset/afternoon_tea.json`。

**核心函式**：

| 函式 | 簽名 | 說明 |
|------|------|------|
| `classify_stores` | `(raw_stores, api_key) → dict` | 呼叫 Gemini API，回傳篩選結果 |
| `run_classification` | `(input_path, output_path, api_key) → dict` | 高階進入點：讀檔→分類→寫檔 |

**Gemini Prompt 規則**：
1. 過濾平均消費 > 200 TWD 的店
2. 判定每家店的主要類型（甜食/鹹食/冷飲/熱飲/其他）
3. 排除不適合下午茶的店（便當店、火鍋店等）
4. 為每店挑出最多 5 個代表品項
5. 只輸出 JSON，不加說明文字

**設計決策**：
- 使用 `gemini-2.5-flash`（分類任務不需要大模型）
- 自動剝除 markdown code fences（```` ```json ````）
- API Key 從 `GEMINI_API_KEY` 環境變數取得

**CLI 用法**：
```bash
python classifier.py
python classifier.py --input path/to/raw.json --output path/to/output.json
```

### 5.3 pipeline.py — 一條龍管線

**路徑**：`apps/ubereats-local-web/pipeline.py`

**職責**：串接 crawl → classify，一個指令完成資料預處理。

**核心函式**：

| 函式 | 簽名 | 說明 |
|------|------|------|
| `run_pipeline` | `(skip_crawl, headed) → None` | 執行完整管線 |

**CLI 用法**：
```bash
python pipeline.py                 # 完整管線
python pipeline.py --skip-crawl    # 跳過爬蟲，僅分類
python pipeline.py --headed        # 可見瀏覽器
```

### 5.4 Claude Code CLI — 問答推薦

**不需要寫新程式**。透過 `CLAUDE.md` 的 system prompt 指引 Claude Code：

1. 讀取 `dataset/afternoon_tea.json`
2. 根據使用者需求從 dataset 中挑選 4 間不同店
3. 回覆固定格式的推薦結果
4. 將結果 append 到 `dataset/history.jsonl`

**推薦邏輯**：
- 預設：2 甜食 + 2 飲料（冷飲或熱飲）
- 使用者可指定任意兩種類型組合（如「鹹食+冷飲」）
- 4 間店必須不同
- 所有店的 `avg_price ≤ 200`（已由 Gemini 預先篩選）

---

## 6. 專案結構

```
afternoon-tea-agent/
├── CLAUDE.md                              # Claude Code system prompt（含推薦指引）
├── AGENTS.md                              # 開發規範
├── README.md                              # 快速上手
├── requirements.txt                       # Python 依賴
├── .gitignore
├── docs/
│   ├── implementation-plan.md             # 本文件（PRD）
│   └── 2026-02-09-...-design.md           # 原始設計稿（歷史參考）
├── scripts/
│
└── apps/ubereats-local-web/
    ├── .env.example                       # 環境變數範本
    ├── crawler.py                         # Playwright 爬蟲
    ├── classifier.py                      # Gemini API 篩選
    ├── pipeline.py                        # 一條龍管線
    ├── dataset/                           # JSON 資料（不 commit）
    │   ├── .gitkeep
    │   ├── raw_stores.json                # 爬蟲原始輸出
    │   ├── afternoon_tea.json             # Gemini 篩選後
    │   └── history.jsonl                  # 推薦紀錄
    └── tests/
        ├── conftest.py                    # pytest fixtures
        ├── test_crawler.py                # 爬蟲測試（15 tests）
        ├── test_classifier.py             # 分類器測試（4 tests）
        └── test_pipeline.py               # 管線整合測試（1 test）
```

---

## 7. 環境設定

### `.env.example`

```dotenv
# Crawler
UBER_EATS_TAIPEI_ADDRESS=台北市信義區信義路五段7號
MAX_STORES_PER_CRAWL=30

# Gemini API (for classifier)
GEMINI_API_KEY=your-gemini-api-key-here
```

### `requirements.txt`

```
pytest>=8.0,<9.0
pytest-asyncio>=0.23
playwright>=1.40
google-genai>=1.0
```

安裝步驟：
```bash
pip install -r requirements.txt
python -m playwright install chromium
```

---

## 8. 測試策略

### 測試矩陣

| 測試檔 | 測試數 | 類型 | 涵蓋範圍 |
|--------|--------|------|----------|
| `test_crawler.py` | 15 | Unit + Integration | URL 解析、價格解析、store link 蒐集、菜單爬取、JSON 輸出端到端 |
| `test_classifier.py` | 4 | Unit | Gemini API mock、markdown fence 處理、缺少 API Key 錯誤、檔案讀寫 |
| `test_pipeline.py` | 1 | Integration | `--skip-crawl` 模式下的管線串接 |

### 執行方式

```bash
# 全部測試
pytest apps/ubereats-local-web/tests/

# 個別模組
pytest apps/ubereats-local-web/tests/test_crawler.py
pytest apps/ubereats-local-web/tests/test_classifier.py
pytest apps/ubereats-local-web/tests/test_pipeline.py
```

### 測試設計原則

- **所有外部依賴均 mock**：Playwright、Gemini API 皆不實際呼叫
- **使用 `tmp_path`**：JSON 輸出檔寫入臨時目錄，不污染 dataset/
- **使用 `importlib` 動態載入**：避免模組 import 時的副作用
- **Async 測試**：使用 `pytest-asyncio` + `AsyncMock`

---

## 9. 與舊架構的差異

| 面向 | 舊架構（v1.0） | 新架構（v2.0） |
|------|----------------|----------------|
| 儲存 | SQLite（3 張表） | JSON 檔案（2 個 + history） |
| 分類 | rule-based + Claude API fallback | Gemini API 一次篩選 |
| 選取 | SQL 隨機 + Python 邏輯 (`pick_items`) | Claude Code 直接推理 |
| 介面 | Web UI（HTML/CSS/JS） | Claude Code CLI 對話 |
| Server | `http.server` stdlib | 不需要 |
| 排程 | 規劃中的 `scheduler.py` | 需要時手動跑 pipeline |
| 團購 | `group_order_url` 欄位 | 直接給 store URL |

### 已移除的檔案

| 檔案 | 原因 |
|------|------|
| `server.py` | 不再需要 HTTP server |
| `static/` (index.html, app.js, styles.css) | 不再需要前端 UI |
| `data/` | 不再用 SQLite |
| `tests/test_api.py` | server API 測試已無意義 |
| `tests/test_selection.py` | `pick_items()` 邏輯已移除 |

---

## 10. 風險與對策

| 風險 | 影響 | 對策 |
|------|------|------|
| Uber Eats 前端結構變動 | 爬蟲失效 | 用 `data-testid` / `aria-label` 定位；兩層 fallback 解析策略 |
| 自動化偵測封鎖 | 爬蟲被擋 | 隨機延遲 2-5 秒、User-Agent 偽裝、`--headed` 手動模式 |
| Gemini 分類不準 | 推薦不適當的店 | prompt 明確要求排除正餐店；使用者在 CLI 可即時回饋 |
| 可送達店家不足 | 無法推薦 4 家 | `afternoon_tea.json` 的 `store_count` 可預先檢查 |
| Gemini API 回傳非 JSON | 分類失敗 | 自動剝除 markdown code fences；json.loads 解析失敗時 raise |

---

## 11. 驗證清單

### 階段一驗證（資料預處理）

- [ ] `python pipeline.py` 執行無錯誤
- [ ] `dataset/raw_stores.json` 包含 ≥5 家店的完整資料
- [ ] `dataset/afternoon_tea.json` 只含適合下午茶且 avg_price ≤ 200 的店
- [ ] `afternoon_tea.json` 中每家店都有 `type`（甜食/鹹食/冷飲/熱飲/其他）
- [ ] `pytest apps/ubereats-local-web/tests/` 全部 20 tests 通過

### 階段二驗證（問答輸出）

- [ ] 在 Claude Code CLI 輸入「甜食+冷飲」，取得 4 間不同店的推薦
- [ ] 推薦的 URL 可正常開啟 Uber Eats 店家頁面
- [ ] `dataset/history.jsonl` 有對應紀錄寫入
- [ ] 輸入不同類型組合（如「鹹食+熱飲」）仍可正確推薦

---

## 12. 未來展望（不在目前範圍內）

- **自動排程**：定時執行 pipeline 更新 dataset
- **團購連結自動建立**：若有 Uber Eats 登入態，自動建立團購房
- **價格追蹤**：比對歷次 `raw_stores.json`，發現價格變動
- **多地址支援**：支援多個外送地址的候選池
- **Slack/LINE 整合**：推薦結果直接發送到群組
