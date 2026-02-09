# ubereats-local-web

本地 `localhost` 前端，按鈕隨機抽出 `2` 食物 + `2` 飲料（不同店家），並產生可複製文字：

`商店名+ubereat團購表單`

## 啟動方式

1. 進入目錄

```bash
cd apps/ubereats-local-web
```

2. 複製環境變數

```bash
cp .env.example .env
```

3. 可選：先建立 demo 資料

```bash
python3 server.py --seed-demo
```

4. 啟動服務

```bash
python3 server.py
```

5. 開啟瀏覽器

- `http://127.0.0.1:8080`

## API

- `GET /api/random-selection`

成功回傳 `result.drinks`、`result.foods` 與 `copy_text`。

## 資料庫假設

- `stores`
- `items`
- `classifications`

系統會自動建立上述表。若你已有既有資料庫，可直接把 `.env` 的 `SQLITE_PATH` 指向你的檔案。
