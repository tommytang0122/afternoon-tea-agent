# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Uber Eats 下午茶推薦 agent。分兩階段運作：
1. **資料預處理 pipeline** — Playwright 爬蟲 + Gemini API 篩選，產出 `dataset/afternoon_tea.json`
2. **問答輸出** — 在 Claude Code CLI 直接對話，讀取 dataset 推薦店家

## Commands

```bash
# Setup
cd apps/ubereats-local-web
cp .env.example .env           # fill in UBER_EATS_TAIPEI_ADDRESS and GEMINI_API_KEY

# Run pipeline (crawl + classify)
python pipeline.py                                # category mode (default, fast)
python pipeline.py --legacy                       # legacy mode (crawl menus)
python pipeline.py --skip-crawl                   # only classify (uses existing raw_stores.json)
python pipeline.py --headed                       # run crawler with visible browser
python pipeline.py --categories "珍珠奶茶,咖啡和茶"  # specific categories only

# Tests
pytest apps/ubereats-local-web/tests/                      # all tests
pytest apps/ubereats-local-web/tests/test_crawler.py       # crawler tests
pytest apps/ubereats-local-web/tests/test_classifier.py    # classifier tests
pytest apps/ubereats-local-web/tests/test_pipeline.py      # pipeline tests
```

## Architecture

| 階段 | 觸發 | 核心 | 產出 |
|------|------|------|------|
| 資料預處理 | `python pipeline.py` | Playwright 爬蟲 + Gemini API | `dataset/*.json` |
| 問答輸出 | Claude Code CLI 對話 | Claude Code 讀 dataset JSON | 終端回覆 + history.jsonl |

### 檔案結構

- **`apps/ubereats-local-web/crawler.py`** — Playwright 爬蟲，預設按 UE 分類爬取店名+URL（category mode），也支援爬菜單（legacy mode）
- **`apps/ubereats-local-web/classifier.py`** — 呼叫 Gemini API 篩選適合下午茶的店家，輸出 `dataset/afternoon_tea.json`
- **`apps/ubereats-local-web/pipeline.py`** — 一條龍 script：crawl → classify → done
- **`apps/ubereats-local-web/dataset/`** — 存放 JSON 資料檔（不 commit）

### 資料格式

**`dataset/raw_stores.json`** — 爬蟲原始資料：

Category mode（預設）：
```json
[{"name": "店名", "url": "...", "ue_category": "珍珠奶茶"}]
```

Legacy mode（`--legacy`）：
```json
[{"name": "店名", "category": "", "url": "...", "menu_items": [{"name": "品名", "price_twd": 120}], "avg_price": 105}]
```

**`dataset/afternoon_tea.json`** — Gemini 篩選後：
```json
{"generated_at": "...", "pipeline_mode": "category", "store_count": 18, "stores": [{"name": "店名", "type": "冷飲", "store_category": "飲料店", "tags": ["手搖飲"], "url": "..."}]}
```

Legacy mode 時 stores 會額外包含 `avg_price` 和 `top_items`。

### 店家分類

每家店有兩個分類欄位：

**`type`**（品項類型）：`甜食` | `鹹食` | `冷飲` | `熱飲` | `其他`

**`store_category`**（店型，推薦時的主要選取依據）：

| store_category | 定義 | 圖示 |
|----------------|------|------|
| `飲料店` | 手搖飲、咖啡專賣 | 🧋 |
| `輕食/早午餐` | 吐司、三明治、貝果、早午餐 | 🥪 |
| `速食/炸物` | 炸雞、薯條、雞塊等鹹食零嘴 | 🍟 |
| `甜點/烘焙` | 蛋糕、派、甜品專賣 | 🍰 |

以下店型會被 Gemini 排除，不進入 `afternoon_tea.json`：
- `正餐主食`：便當、飯類、麵類
- 大賣場、超市、量販店

## Coding Conventions

- Python: PEP 8, 4-space indent, `snake_case` functions/variables, `UPPER_SNAKE_CASE` constants.
- Prefer descriptive names over abbreviations.
- Commits: imperative, concise subjects, one logical change per commit.

## Git Workflow

- **每次修改程式碼前必須先開 branch**，不直接在 main 上改。
- Branch 命名：`feat/描述`、`fix/描述`、`refactor/描述`。
- 完成後透過 PR 合併回 main。

## 下午茶推薦

當使用者詢問下午茶推薦時：
1. 讀取 `apps/ubereats-local-web/dataset/afternoon_tea.json`
2. 根據使用者需求，以 `store_category` 為主要選取依據：
   - 使用者指定兩種店型（如「輕食/早午餐+飲料店」）→ 每種各 2 間
   - 使用者只指定一種店型（如「飲料店」）→ 該店型 2 間 + 自動搭配另一店型 2 間
   - 使用者未指定 → 預設 2 間 `輕食/早午餐` + 2 間 `飲料店`
   - 使用者用口語（如「手搖飲」「炸物」）時，自動對應到正確的 store_category
   - 4 間必須不同店
3. 回覆格式（根據實際店型替換圖示和標題，有 avg_price 時顯示，沒有則省略）：

   🥪 輕食/早午餐
   1. 店家名 | 輕食/早午餐 | URL
   2. 店家名 | 輕食/早午餐 | URL

   🧋 飲料店
   3. 店家名 | 飲料店 | URL
   4. 店家名 | 飲料店 | URL

4. 將推薦結果 append 到 `apps/ubereats-local-web/dataset/history.jsonl`
   格式：`{"timestamp": "...", "query": "使用者輸入", "result": [...]}`
