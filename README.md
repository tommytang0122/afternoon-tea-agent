# afternoon-tea-agent

Uber Eats 下午茶推薦 agent。自動爬取可外送店家、用 Gemini API 篩選適合下午茶的店，再透過 Claude Code CLI 對話推薦。

## Quick Start

```bash
# 安裝依賴
pip install -r requirements.txt
python -m playwright install chromium

# 設定環境變數
cd apps/ubereats-local-web
cp .env.example .env
# 編輯 .env，填入外送地址和 Gemini API Key

# 執行資料預處理 pipeline
python pipeline.py

# 在 Claude Code CLI 對話，輸入如「甜食+冷飲」即可取得推薦
```

## 架構

```
pipeline.py → crawler.py (Playwright) → dataset/raw_stores.json
            → classifier.py (Gemini)  → dataset/afternoon_tea.json

Claude Code CLI → 讀取 afternoon_tea.json → 推薦 4 間不同店
```

## 測試

```bash
pytest apps/ubereats-local-web/tests/
```

## 詳細規格

完整 PRD 請見：`docs/implementation-plan.md`
