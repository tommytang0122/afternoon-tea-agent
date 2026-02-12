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

## 6. Category Chip 圖片未載入導致零寬度、無法點擊

**現象**：`_select_category_tag()` 的 `scrollIntoView` + `click` 方案在首個分類（速食）成功後，後續 4 個分類全部 timeout 失敗，即使 `data-testid` 選擇器確實找到了元素（`state="attached"` 通過）。

**原因**：Uber Eats 的 category chip 是 `<a>` 標籤，內容為圖片（非文字）。在 headless 模式下圖片不一定載入，導致：
- `inner_text()` 回傳空字串
- `bounding_box()` 顯示 `width: 0`（元素存在但無可見尺寸）
- Playwright 的 `click()` 要求元素 visible，零寬度元素被判定為不可見，永遠 timeout

```
Bounding box: {'x': 1029, 'y': 434, 'width': 0, 'height': 64}
→ width: 0，元素在 DOM 中但不可見
```

之前的 `scrollIntoView` 修正只解決了「元素在可視範圍外」的問題，但對「元素在 DOM 中但寬度為零」的情況無效。

**修正**：
- 不再嘗試點擊 chip，改為提取 `<a>` 標籤的 `href` 屬性
- 直接用 `page.goto(url)` 導航到該分類的搜尋頁面
- 保留 click 作為 fallback（當 href 不存在時）

```python
href = await locator.get_attribute("href")
if href:
    url = href if href.startswith("http") else f"{UBER_EATS_BASE}{href}"
    await page.goto(url, wait_until="domcontentloaded")
    await asyncio.sleep(_random_delay(2.0, 4.0))
    return True
# Fallback: try clicking if no href
await locator.click(timeout=5000)
```

**修正前 vs 修正後**：

| | 速食 | 早餐和早午餐 | 珍珠奶茶 | 咖啡和茶 | 烘焙食品 | 合計 |
|--|------|-------------|---------|---------|---------|------|
| 修正前（click） | 79 ✓ | ✗ | ✗ | ✗ | ✗ | 79 |
| 修正後（href 導航） | 79 ✓ | 79 ✓ | 81 ✓ | 79 ✓ | 79 ✓ | 288 |

**教訓**：
- 爬蟲不應依賴「點擊」來觸發導航。`<a>` 標籤自帶 `href`，直接讀取 href 並 `goto()` 比模擬點擊更可靠、更快
- Headless 模式下圖片行為與 headed 模式不同。圖片式 UI 元件（icon chip、image button）可能在 headless 下有零尺寸
- 遇到 `click timeout` 時，優先檢查 `bounding_box()` 和 `is_visible()` 來判斷是定位問題還是渲染問題

---

## 7. Gemini API 輸出截斷（JSON 不完整）

**現象**：爬蟲成功爬到 308 間店後，Gemini 分類步驟連續失敗，拋出 `JSONDecodeError: Unterminated string`。

**原因**：308 間店的完整 JSON 一次塞進 prompt，Gemini 需要回傳每間通過篩選的店的完整資訊（name, type, store_category, tags, url），輸出 token 數超過限制被截斷。即使加了 `max_output_tokens: 65536` 仍然不夠（thinking token 也佔配額）。

**修正**：
- 新增 `classify_stores_batch()` 函式，按 `ue_category` 欄位分組
- 每組（~60-80 間）獨立呼叫一次 `classify_stores()`
- 合併所有批次結果，按 URL 去重

```
raw_stores.json (308 間)
  ├─ 速食 (79) → Gemini call 1 → 27 stores ✓
  ├─ 早餐和早午餐 (72) → Gemini call 2 → 33 stores ✓
  ├─ 珍珠奶茶 (74) → Gemini call 3 → 69 stores ✓
  ├─ 咖啡和茶 (55) → Gemini call 4 → 53 stores ✓
  └─ 烘焙食品 (42) → Gemini call 5 → 45 stores ✓
  → 全部 FinishReason.STOP，無截斷
```

**教訓**：
- LLM API 的輸出有 token 上限，不能假設任意長度的 JSON 都能完整回傳
- 分批呼叫是最穩健的做法，即使犧牲一些 API call 數量
- 加入 `finish_reason` 日誌有助於快速判斷是截斷還是格式問題

---

## 8. 分類偶發爬到 0 間店

**現象**：5 個分類中，烘焙食品偶爾爬到 0 間店，但手動重試立刻就能爬到。

**原因**：category chip 的 href 導航到搜尋頁面後，店家列表可能因頁面載入時序問題尚未渲染完成，`collect_store_links_from_current_view()` 在 3 輪無新增後就停止滾動。

**修正**：
- 將爬取單一分類的邏輯抽成 `_crawl_one_category()` helper
- 第一輪爬完所有分類後，記錄回傳 0 筆的分類
- 全部爬完後統一重試 0 筆的分類一次
- 重試仍為 0 則 log warning 並放棄

```python
# 第一輪
empty_categories = []
for cat in crawlable:
    count = await _crawl_one_category(cat, ...)
    if count == 0:
        empty_categories.append(cat)

# 重試 0 筆的分類
if empty_categories:
    for cat in empty_categories:
        count = await _crawl_one_category(cat, ...)
        if count == 0:
            log.warning("Category %s still empty; giving up.", cat["label"])
```

**教訓**：
- 網頁爬蟲應預期偶發性失敗，在合理範圍內加入重試機制
- 重試時機選在「全部分類跑完後」而非「立即重試」，讓時間差增加成功機率
- 重試次數限制為 1 次，避免無限迴圈或觸發 rate limit

---

## 總結：爬蟲穩定性 Checklist

| 項目 | 建議 |
|------|------|
| Rate limit | 限制分類數量，加入隨機延遲 |
| 圖片式元素 | 優先用 href 導航，不依賴 click |
| 水平滾動 | 用 JS `scrollIntoView` 而非 Playwright 內建 scroll |
| SPA 導航 | 用 `networkidle` + 充足延遲 + 重試 |
| 動態分類 | Graceful degradation，不硬性依賴特定分類 |
| CLI 設計 | 提供語意明確的單一 flag |
| LLM 輸出 | 分批呼叫，避免單次輸出過長被截斷 |
| 偶發失敗 | 全部跑完後統一重試 0 筆的分類 |
