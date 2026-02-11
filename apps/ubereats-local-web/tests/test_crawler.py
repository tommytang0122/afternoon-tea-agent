"""Unit tests for crawler.py with mocked Playwright and JSON output."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Pure function tests
# ---------------------------------------------------------------------------

class TestExtractStoreIdFromUrl:
    def test_standard_url(self, crawler_module):
        url = "https://www.ubereats.com/tw/store/mui-mui/n_9V8YWoTcu1l5YTxLP1Ow"
        assert crawler_module._extract_store_id_from_url(url) == "n_9V8YWoTcu1l5YTxLP1Ow"

    def test_chinese_slug(self, crawler_module):
        url = "https://www.ubereats.com/tw/store/%E6%80%9D%E6%98%A5/3FBDOEvAR1-5w_0z5ZKb3w"
        assert crawler_module._extract_store_id_from_url(url) == "3FBDOEvAR1-5w_0z5ZKb3w"

    def test_no_match(self, crawler_module):
        assert crawler_module._extract_store_id_from_url("https://example.com") is None

    def test_partial_url(self, crawler_module):
        url = "/tw/store/some-store/ABCDEF1234567890abcdef"
        assert crawler_module._extract_store_id_from_url(url) == "ABCDEF1234567890abcdef"


class TestExtractStoreSlug:
    def test_english_slug(self, crawler_module):
        url = "https://www.ubereats.com/tw/store/mui-mui/abc123"
        assert crawler_module._extract_store_slug(url) == "mui-mui"

    def test_encoded_chinese(self, crawler_module):
        url = "https://www.ubereats.com/tw/store/%E6%80%9D%E6%98%A5/abc123"
        assert crawler_module._extract_store_slug(url) == "思春"


class TestParsePrice:
    def test_simple_dollar(self, crawler_module):
        assert crawler_module._parse_price("$120") == 120

    def test_nt_dollar(self, crawler_module):
        assert crawler_module._parse_price("NT$350") == 350

    def test_with_comma(self, crawler_module):
        assert crawler_module._parse_price("$1,200") == 1200

    def test_no_price(self, crawler_module):
        assert crawler_module._parse_price("免費送") is None

    def test_dollar_with_space(self, crawler_module):
        assert crawler_module._parse_price("$ 85") == 85


# ---------------------------------------------------------------------------
# Async crawl tests (mocked Playwright)
# ---------------------------------------------------------------------------

def _make_mock_link(href: str, text: str):
    link = AsyncMock()
    link.get_attribute = AsyncMock(return_value=href)
    link.inner_text = AsyncMock(return_value=text)
    return link


def _make_mock_page():
    page = AsyncMock()
    page.goto = AsyncMock()
    page.evaluate = AsyncMock()
    page.locator = MagicMock()
    return page


@pytest.mark.asyncio
async def test_collect_store_links(crawler_module):
    page = _make_mock_page()

    links = [
        _make_mock_link(
            "https://www.ubereats.com/tw/store/cafe-a/AAAA1111BBBB2222cccc",
            "Cafe A\nDelivery 30 min",
        ),
        _make_mock_link(
            "https://www.ubereats.com/tw/store/tea-b/DDDD3333EEEE4444ffff",
            "Tea B",
        ),
    ]

    locator_mock = MagicMock()
    locator_mock.all = AsyncMock(return_value=links)
    page.locator.return_value = locator_mock

    result = await crawler_module.collect_store_links(page, max_stores=5)

    assert len(result) == 2
    assert result[0]["store_id"] == "AAAA1111BBBB2222cccc"
    assert result[0]["name"] == "Cafe A"
    assert result[1]["store_id"] == "DDDD3333EEEE4444ffff"


@pytest.mark.asyncio
async def test_scrape_store_menu_with_item_cards(crawler_module):
    page = _make_mock_page()

    card1 = AsyncMock()
    card1.inner_text = AsyncMock(return_value="拿鐵\n$120\n熱賣")
    card2 = AsyncMock()
    card2.inner_text = AsyncMock(return_value="抹茶蛋糕\nNT$180\n限量")

    item_locator = MagicMock()
    item_locator.all = AsyncMock(return_value=[card1, card2])

    page.locator.return_value = item_locator

    items = await crawler_module.scrape_store_menu(
        page, "https://www.ubereats.com/tw/store/test/abc123"
    )

    assert len(items) == 2
    assert items[0]["name"] == "拿鐵"
    assert items[0]["price_twd"] == 120
    assert items[1]["name"] == "抹茶蛋糕"
    assert items[1]["price_twd"] == 180


@pytest.mark.asyncio
async def test_scrape_store_menu_fallback(crawler_module):
    """When item cards are not found, fallback to scanning main text."""
    page = _make_mock_page()

    empty_locator = MagicMock()
    empty_locator.all = AsyncMock(return_value=[])

    main_locator = MagicMock()
    main_locator.inner_text = AsyncMock(
        return_value="珍珠奶茶\n$75\n紅茶拿鐵\n$90\n"
    )

    call_count = 0
    def side_effect(selector):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return empty_locator
        return main_locator

    page.locator = MagicMock(side_effect=side_effect)

    items = await crawler_module.scrape_store_menu(
        page, "https://www.ubereats.com/tw/store/test/abc123"
    )

    assert len(items) == 2
    assert items[0]["name"] == "珍珠奶茶"
    assert items[0]["price_twd"] == 75


@pytest.mark.asyncio
async def test_crawl_stores_writes_json(crawler_module, tmp_path, monkeypatch):
    """Full crawl with mocked Playwright writes JSON output."""

    mock_page = _make_mock_page()
    mock_browser = AsyncMock()
    mock_context = AsyncMock()
    mock_context.new_page = AsyncMock(return_value=mock_page)
    mock_browser.new_context = AsyncMock(return_value=mock_context)

    mock_pw_instance = AsyncMock()
    mock_pw_instance.chromium.launch = AsyncMock(return_value=mock_browser)

    mock_pw = AsyncMock()
    mock_pw.__aenter__ = AsyncMock(return_value=mock_pw_instance)
    mock_pw.__aexit__ = AsyncMock(return_value=None)

    # set_delivery_address mocks
    address_btn = AsyncMock()
    address_btn.wait_for = AsyncMock(
        side_effect=crawler_module.PwTimeout("no btn")
    )
    address_input = AsyncMock()
    address_input.wait_for = AsyncMock()
    address_input.fill = AsyncMock()
    address_input.type = AsyncMock()
    address_input.press = AsyncMock()
    suggestion = AsyncMock()
    suggestion.wait_for = AsyncMock(
        side_effect=crawler_module.PwTimeout("no sug")
    )
    confirm_btn = AsyncMock()
    confirm_btn.wait_for = AsyncMock(
        side_effect=crawler_module.PwTimeout("no confirm")
    )

    # collect_store_links mocks
    store_links = [
        _make_mock_link(
            "https://www.ubereats.com/tw/store/cafe-a/AAAA1111BBBB2222cccc",
            "Cafe A",
        ),
        _make_mock_link(
            "https://www.ubereats.com/tw/store/tea-house/DDDD3333EEEE4444ffff",
            "茶之家",
        ),
    ]
    store_locator = MagicMock()
    store_locator.all = AsyncMock(return_value=store_links)

    # scrape_store_menu mocks
    menu_card_1 = AsyncMock()
    menu_card_1.inner_text = AsyncMock(return_value="拿鐵\n$120")
    menu_card_2 = AsyncMock()
    menu_card_2.inner_text = AsyncMock(return_value="抹茶\n$90")
    menu_locator = MagicMock()
    menu_locator.all = AsyncMock(return_value=[menu_card_1, menu_card_2])

    def locator_dispatch(selector):
        if "address-option" in selector or "輸入外送地址" in selector:
            return MagicMock(first=address_btn)
        if "aria-label" in selector or "placeholder" in selector:
            return MagicMock(first=address_input)
        if "suggestion" in selector or "option" in selector:
            return MagicMock(first=suggestion)
        if "儲存" in selector or "確認" in selector:
            return MagicMock(first=confirm_btn)
        if "/tw/store/" in selector:
            return store_locator
        return menu_locator

    mock_page.locator = MagicMock(side_effect=locator_dispatch)

    monkeypatch.setattr(crawler_module, "_random_delay", lambda *a, **k: 0.01)

    output_path = str(tmp_path / "raw_stores.json")

    with patch.object(crawler_module, "async_playwright", return_value=mock_pw):
        result = await crawler_module.crawl_stores(
            address="台北市信義區",
            output_path=output_path,
            max_stores=2,
        )

    assert len(result) == 2
    assert result[0]["name"] == "Cafe A"
    assert result[0]["avg_price"] == 105  # (120 + 90) / 2
    assert len(result[0]["menu_items"]) == 2

    # Verify JSON file was written
    with open(output_path, "r", encoding="utf-8") as f:
        saved = json.load(f)
    assert len(saved) == 2
    assert saved[0]["name"] == "Cafe A"
