# 爬蟲踩坑檢討報告

> 日期：2026-02-11
> 分支：`feat/category-based-crawler`

---

## 1. Uber Eats Rate Limiting (`too_many_requests`)

**現象**：用 `--by-category` 爬全部 19 個分類，爬到第 13 個時收到 `bd.error.too_many_requests` 錯誤，瀏覽器被封鎖。

**原因**：每個分類都要 `page.goto(FEED_URL)` 重新載入 + 滾動收集店家連結，19 個分類在短時間內產生大量請求。

**修正**：
- 新增 `AFTERNOON_TEA_CATEGORIES` 常數，只定義 5 個下午茶相關分類（速食、早餐和早午餐、珍珠奶茶、咖啡和茶、烘焙食品）
- 新增 `--afternoon-tea` CLI flag 和 `afternoon_tea_only` 參數，跳過不相關分類
- Pipeline 預設使用 `afternoon_tea_only=True`

**教訓**：爬蟲設計時應考慮 rate limit，預設只爬必要的分類，避免一次爬太多觸發封鎖。

---

## 2. Category Chip 橫向滾動問題

**現象**：`discover_category_tags_from_feed()` 能成功找到 19 個分類 chip（用 `locator.all()`），但 `_select_category_tag()` 點擊時只有前幾個成功，後面的全部 timeout。

**原因**：Uber Eats 的分類 chip bar 是**水平滾動容器**。`locator.all()` 能找到所有 DOM 元素（含不可見的），但 `wait_for(state="visible")` 會 timeout，因為元素在可視範圍外。Playwright 的 `scroll_into_view_if_needed()` 只處理垂直滾動，對水平滾動容器內的元素無效。

**修正**：
- 改用 `wait_for(state="attached")` 取代 `state="visible"`（只要 DOM 中存在即可）
- 用 JavaScript `el.scrollIntoView({behavior:'instant', block:'nearest', inline:'center'})` 直接操作水平滾動
- 等待 0.5 秒讓滾動完成後再 click

```python
await locator.evaluate(
    "el => el.scrollIntoView({behavior:'instant',block:'nearest',inline:'center'})"
)
await asyncio.sleep(0.5)
await locator.click(timeout=5000)
```

**教訓**：Playwright 的內建 scroll 方法不一定能處理所有滾動容器。遇到水平滾動的 UI 元件，需要用 `evaluate()` 直接呼叫瀏覽器原生的 `scrollIntoView()`。

---

## 3. SPA 導航後 Chip Bar 未重置

**現象**：成功爬完第一個分類（速食）後，`page.goto(FEED_URL)` 回到首頁，但接下來的分類 chip 全部找不到（包含 scrollIntoView 修正後仍然失敗）。

**原因**：Uber Eats 是 SPA（Single Page Application），`page.goto(FEED_URL)` 用 `wait_until="domcontentloaded"` 時，DOM 骨架已建好但分類 chip 尚未從 API 載入。前端路由可能保留了前一個分類的篩選狀態。

**修正**：
- `wait_until="domcontentloaded"` → `wait_until="networkidle"`（等所有網路請求完成）
- 加長隨機延遲 `_random_delay(3.0, 5.0)`
- 在 `_select_category_tag` 開頭加入「等任意 chip 出現」的 guard（`timeout=15000`）
- 加入重試機制：第一次找不到 chip 時 `page.reload(wait_until="networkidle")` 後再試一次

```python
# 第一次嘗試
if not await _select_category_tag(page, testid, label):
    # 重試
    await page.reload(wait_until="networkidle")
    await asyncio.sleep(_random_delay(3.0, 5.0))
    if not await _select_category_tag(page, testid, label):
        log.warning("Category chip not found: %s", label)
        continue
```

**教訓**：SPA 頁面的 `goto` 不等於傳統的完整頁面載入。必須用 `networkidle` 等待策略，並為動態載入的元素加入充足的等待時間和重試機制。

---

## 4. `data-testid` 分類名稱的地區/時段差異

**現象**：`docs/claude-web-analysis.md` 記載的分類包含「烘焙食品」，但實際 discovery 找到的 19 個分類中沒有「速食」和「烘焙食品」；反而它們在 `--afternoon-tea` 模式下（跳過 discovery）卻能成功被點擊。

**原因**：Uber Eats 的分類 chip 列表是**動態的**，會因以下因素改變：
- 時段（早餐時段 vs 下午 vs 晚餐）
- 地區（不同外送地址看到不同分類）
- A/B 測試（不同 session 可能看到不同 UI）

`AFTERNOON_TEA_CATEGORIES` 中的 5 個分類不保證每次都存在。

**處理**：
- `afternoon_tea_only` 模式跳過 discovery，直接用預定義的 testid 嘗試點擊
- 找不到的分類會被跳過並記錄 warning，不會中斷整個爬蟲
- 未來可考慮在 `.env` 中讓使用者自訂分類列表

**教訓**：不要假設網站的分類是固定的。爬蟲應該對「分類不存在」的情況做 graceful degradation，而非硬性依賴特定分類。

---

## 5. `--by-category` vs `--afternoon-tea` 混淆

**現象**：第一次測試時跑了 `python3 crawler.py --by-category --headed`，結果爬了全部 19 個分類而非只爬 5 個下午茶分類。

**原因**：`--by-category` 是通用的分類爬蟲模式，不帶 `afternoon_tea_only` 預設值。只有 `--afternoon-tea` 或透過 `pipeline.py` 才會自動限制為 5 個分類。

**修正**：新增 `--afternoon-tea` CLI flag，自動設定 `by_category=True` + `afternoon_tea_only=True`。

**教訓**：CLI flag 的語意要明確。使用者期望「只爬下午茶」時不應該需要組合多個 flag。提供一個語意清楚的單一 flag 比要求使用者理解內部機制更好。

---

## 總結：爬蟲穩定性 Checklist

| 項目 | 建議 |
|------|------|
| Rate limit | 限制分類數量，加入隨機延遲 |
| 水平滾動 | 用 JS `scrollIntoView` 而非 Playwright 內建 scroll |
| SPA 導航 | 用 `networkidle` + 充足延遲 + 重試 |
| 動態分類 | Graceful degradation，不硬性依賴特定分類 |
| CLI 設計 | 提供語意明確的單一 flag |
