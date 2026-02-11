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
python pipeline.py             # full pipeline
python pipeline.py --skip-crawl  # only classify (uses existing raw_stores.json)
python pipeline.py --headed    # run crawler with visible browser

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

- **`apps/ubereats-local-web/crawler.py`** — Playwright 爬蟲，爬取 Uber Eats 店家與菜單，輸出 `dataset/raw_stores.json`
- **`apps/ubereats-local-web/classifier.py`** — 呼叫 Gemini API 篩選適合下午茶的店家，輸出 `dataset/afternoon_tea.json`
- **`apps/ubereats-local-web/pipeline.py`** — 一條龍 script：crawl → classify → done
- **`apps/ubereats-local-web/dataset/`** — 存放 JSON 資料檔（不 commit）

### 資料格式

**`dataset/raw_stores.json`** — 爬蟲原始資料：
```json
[{"name": "店名", "category": "", "url": "...", "menu_items": [{"name": "品名", "price_twd": 120}], "avg_price": 105}]
```

**`dataset/afternoon_tea.json`** — Gemini 篩選後：
```json
{"generated_at": "...", "store_count": 18, "stores": [{"name": "店名", "type": "熱飲", "tags": ["咖啡"], "url": "...", "avg_price": 105, "top_items": ["拿鐵 $120"]}]}
```

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
2. 根據使用者需求（如「甜食+冷飲」）從 dataset 中挑選：
   - 2 間符合第一種類型的店家
   - 2 間符合第二種類型的店家
   - 4 間必須不同店
   - 如果使用者沒有指定類型，預設選 2 甜食 + 2 飲料（冷飲或熱飲）
3. 回覆格式：

   🍰 甜食
   1. 店家名 | 甜食 | 平均 $XXX | URL
   2. 店家名 | 甜食 | 平均 $XXX | URL

   🧊 冷飲
   3. 店家名 | 冷飲 | 平均 $XXX | URL
   4. 店家名 | 冷飲 | 平均 $XXX | URL

4. 將推薦結果 append 到 `apps/ubereats-local-web/dataset/history.jsonl`
   格式：`{"timestamp": "...", "query": "使用者輸入", "result": [...]}`
