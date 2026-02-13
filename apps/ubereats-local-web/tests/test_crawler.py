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


class TestCategoryModeHelpers:
    def test_parse_category_list(self, crawler_module):
        assert crawler_module._parse_category_list(
            "速食, 早餐, ,咖啡"
        ) == ["速食", "早餐", "咖啡"]

    def test_sanitize_filename(self, crawler_module):
        assert crawler_module._sanitize_filename("輕食/早午餐") == "輕食_早午餐"
        assert crawler_module._sanitize_filename("  ") == "category"

    def test_minimal_store_records_dedup(self, crawler_module):
        result = crawler_module._minimal_store_records([
            {"name": "A", "url": "https://example.com/a"},
            {"name": "A2", "url": "https://example.com/a"},  # duplicate URL
            {"name": "B", "url": "https://example.com/b"},
            {"name": "C", "url": ""},  # invalid URL
        ])
        assert result == [
            {"name": "A", "url": "https://example.com/a"},
            {"name": "B", "url": "https://example.com/b"},
        ]

    def test_minimal_store_records_with_ue_category(self, crawler_module):
        result = crawler_module._minimal_store_records(
            [{"name": "Tea Shop", "url": "https://example.com/tea"}],
            ue_category="珍珠奶茶",
        )
        assert result == [
            {"name": "Tea Shop", "url": "https://example.com/tea", "ue_category": "珍珠奶茶"},
        ]

    def test_minimal_store_records_no_ue_category_when_empty(self, crawler_module):
        result = crawler_module._minimal_store_records(
            [{"name": "Shop", "url": "https://example.com/s"}],
        )
        assert "ue_category" not in result[0]


class TestMergeCategoryStores:
    def test_merge_dedup_by_url(self, crawler_module):
        categorized = {
            "咖啡和茶": [
                {"name": "A", "url": "https://example.com/a", "ue_category": "咖啡和茶"},
                {"name": "B", "url": "https://example.com/b", "ue_category": "咖啡和茶"},
            ],
            "速食": [
                {"name": "A dup", "url": "https://example.com/a", "ue_category": "速食"},
                {"name": "C", "url": "https://example.com/c", "ue_category": "速食"},
            ],
        }
        result = crawler_module.merge_category_stores(categorized)
        assert len(result) == 3
        urls = [s["url"] for s in result]
        assert urls == [
            "https://example.com/a",
            "https://example.com/b",
            "https://example.com/c",
        ]

    def test_merge_empty(self, crawler_module):
        assert crawler_module.merge_category_stores({}) == []

    def test_is_usable_category_label(self, crawler_module):
        assert crawler_module._is_usable_category_label("速食")
        assert not crawler_module._is_usable_category_label("生鮮雜貨")
        assert crawler_module._is_usable_category_label("Uber One")
        assert not crawler_module._is_usable_category_label("  ")


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
async def test_crawl_stores_by_category_writes_per_category_json(
    crawler_module, tmp_path, monkeypatch
):
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

    first_category_links = [
        {"name": "Cafe A", "url": "https://www.ubereats.com/tw/store/cafe-a/AAAA1111BBBB2222cccc"},
        {"name": "Cafe A duplicate", "url": "https://www.ubereats.com/tw/store/cafe-a/AAAA1111BBBB2222cccc"},
        {"name": "Tea B", "url": "https://www.ubereats.com/tw/store/tea-b/DDDD3333EEEE4444ffff"},
    ]
    second_category_links = [
        {"name": "Burger C", "url": "https://www.ubereats.com/tw/store/burger-c/ZZZZ1111YYYY2222xxxx"},
    ]

    monkeypatch.setattr(crawler_module, "_random_delay", lambda *a, **k: 0.01)

    with (
        patch.object(crawler_module, "async_playwright", return_value=mock_pw),
        patch.object(crawler_module, "set_delivery_address", AsyncMock()),
        patch.object(
            crawler_module,
            "discover_category_tags_from_feed",
            AsyncMock(return_value=[
                {"order": 1, "label": "咖啡", "testid": "search-home-item-咖啡和茶"},
                {"order": 2, "label": "速食", "testid": "search-home-item-速食"},
            ]),
        ),
        patch.object(crawler_module, "_select_category_tag", AsyncMock(return_value=True)),
        patch.object(
            crawler_module,
            "collect_store_links_from_current_view",
            AsyncMock(side_effect=[first_category_links, second_category_links]),
        ),
    ):
        result = await crawler_module.crawl_stores_by_category(
            address="台北市信義區",
            output_dir=str(tmp_path),
            categories=["咖啡", "速食"],
            max_stores_per_category=10,
        )

    assert set(result.keys()) == {"咖啡", "速食"}
    assert len(result["咖啡"]) == 2  # deduplicated by URL
    assert len(result["速食"]) == 1

    file_a = tmp_path / "01_咖啡.json"
    file_b = tmp_path / "02_速食.json"
    assert file_a.exists()
    assert file_b.exists()

    with open(file_a, "r", encoding="utf-8") as f:
        saved_a = json.load(f)
    with open(file_b, "r", encoding="utf-8") as f:
        saved_b = json.load(f)

    assert saved_a == result["咖啡"]
    assert saved_b == result["速食"]
    assert set(saved_a[0].keys()) == {"name", "url", "ue_category"}
    assert saved_a[0]["ue_category"] == "咖啡"


@pytest.mark.asyncio
async def test_crawl_stores_by_category_discovers_feed_order_and_skips_fresh_grocery(
    crawler_module, tmp_path, monkeypatch
):
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

    monkeypatch.setattr(crawler_module, "_random_delay", lambda *a, **k: 0.01)

    discovered = [
        {"order": 1, "label": "速食", "testid": "search-home-item-速食"},
        {"order": 2, "label": "生鮮雜貨", "testid": "search-home-item-生鮮雜貨"},
        {"order": 3, "label": "早餐", "testid": "search-home-item-早餐和早午餐"},
    ]
    link_sets = [
        [{"name": "Fast A", "url": "https://www.ubereats.com/tw/store/fast-a/AAAA1111BBBB2222cccc"}],
        [{"name": "Brunch B", "url": "https://www.ubereats.com/tw/store/brunch-b/DDDD3333EEEE4444ffff"}],
    ]

    with (
        patch.object(crawler_module, "async_playwright", return_value=mock_pw),
        patch.object(crawler_module, "set_delivery_address", AsyncMock()),
        patch.object(crawler_module, "discover_category_tags_from_feed", AsyncMock(return_value=discovered)),
        patch.object(crawler_module, "_select_category_tag", AsyncMock(return_value=True)),
        patch.object(
            crawler_module,
            "collect_store_links_from_current_view",
            AsyncMock(side_effect=link_sets),
        ),
    ):
        result = await crawler_module.crawl_stores_by_category(
            address="台北市信義區",
            output_dir=str(tmp_path),
            categories=None,  # force auto-discovery
            max_stores_per_category=10,
        )

    assert list(result.keys()) == ["速食", "早餐"]
    assert (tmp_path / "01_速食.json").exists()
    assert (tmp_path / "02_早餐.json").exists()
    assert not (tmp_path / "02_生鮮雜貨.json").exists()


@pytest.mark.asyncio
async def test_crawl_stores_by_category_afternoon_tea_only(
    crawler_module, tmp_path, monkeypatch
):
    """afternoon_tea_only=True skips discovery and uses AFTERNOON_TEA_CATEGORIES."""
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

    monkeypatch.setattr(crawler_module, "_random_delay", lambda *a, **k: 0.01)

    link_sets = [
        [{"name": f"Store {i}", "url": f"https://example.com/store-{i}"}]
        for i in range(len(crawler_module.AFTERNOON_TEA_CATEGORIES))
    ]

    discover_mock = AsyncMock()

    with (
        patch.object(crawler_module, "async_playwright", return_value=mock_pw),
        patch.object(crawler_module, "set_delivery_address", AsyncMock()),
        patch.object(crawler_module, "discover_category_tags_from_feed", discover_mock),
        patch.object(crawler_module, "_select_category_tag", AsyncMock(return_value=True)),
        patch.object(
            crawler_module,
            "collect_store_links_from_current_view",
            AsyncMock(side_effect=link_sets),
        ),
    ):
        result = await crawler_module.crawl_stores_by_category(
            address="台北市信義區",
            output_dir=str(tmp_path),
            afternoon_tea_only=True,
            max_stores_per_category=10,
        )

    # Should NOT call discover_category_tags_from_feed
    discover_mock.assert_not_called()
    assert len(result) == len(crawler_module.AFTERNOON_TEA_CATEGORIES)


@pytest.mark.asyncio
async def test_discover_category_tags_from_feed_uses_search_home_testid(
    crawler_module, monkeypatch
):
    page = _make_mock_page()
    monkeypatch.setattr(crawler_module, "_random_delay", lambda *a, **k: 0.01)

    chip1 = AsyncMock()
    chip1.get_attribute = AsyncMock(return_value="search-home-item-咖啡和茶")
    chip1.inner_text = AsyncMock(return_value="咖啡和茶")

    chip2 = AsyncMock()
    chip2.get_attribute = AsyncMock(return_value="search-home-item-生鮮雜貨")
    chip2.inner_text = AsyncMock(return_value="生鮮雜貨")

    chip3 = AsyncMock()
    chip3.get_attribute = AsyncMock(return_value="search-home-item-速食")
    chip3.inner_text = AsyncMock(return_value="速食")

    locator = MagicMock()
    locator.all = AsyncMock(return_value=[chip1, chip2, chip3])
    page.locator = MagicMock(return_value=locator)

    result = await crawler_module.discover_category_tags_from_feed(page)

    assert result == [
        {"order": 1, "label": "咖啡和茶", "testid": "search-home-item-咖啡和茶"},
        {"order": 3, "label": "速食", "testid": "search-home-item-速食"},
    ]
