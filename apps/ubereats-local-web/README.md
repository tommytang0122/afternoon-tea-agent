# ubereats-local-web

此目錄保留舊名稱，但目前是「資料預處理 pipeline」而非 Web server。

## 目前功能

`pipeline.py` 會串接兩個步驟：

1. `crawler.py`：用 Playwright 爬取 Uber Eats 店家與菜單，輸出 `dataset/raw_stores.json`
2. `classifier.py`：呼叫 Gemini API 篩選下午茶店家，輸出 `dataset/afternoon_tea.json`

另外 `crawler.py` 支援「分類標籤模式」：

- 從首頁依 Uber 顯示順序抓取分類標籤
- 自動排除 `生鮮雜貨`
- 每個分類輸出獨立 JSON（僅包含 `name`、`url`）

## 使用方式

```bash
cd apps/ubereats-local-web
cp .env.example .env
# 編輯 .env：填入 UBER_EATS_TAIPEI_ADDRESS 與 GEMINI_API_KEY
```

完整執行（爬蟲 + 分類）：

```bash
python pipeline.py
```

只做分類（沿用既有 `raw_stores.json`）：

```bash
python pipeline.py --skip-crawl
```

可視化瀏覽器（除錯用）：

```bash
python pipeline.py --headed
```

只跑分類標籤爬蟲（不抓菜單）：

```bash
python crawler.py --by-category
```

指定每分類店家上限：

```bash
python crawler.py --by-category --max-per-category 120
```

可選：手動指定分類（覆蓋自動偵測）：

```bash
python crawler.py --by-category --categories 速食,早餐,咖啡
```

## 主要輸出

- `dataset/raw_stores.json`
- `dataset/afternoon_tea.json`
- `dataset/stores_by_category/*.json`（分類標籤模式）

`dataset/` 屬於執行時資料，不會提交到 git。

## 測試

```bash
pytest apps/ubereats-local-web/tests/
```
