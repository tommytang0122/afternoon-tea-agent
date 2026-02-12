#!/usr/bin/env python3
"""Playwright crawler for Uber Eats Taiwan.

Supports two crawl modes:
1) Legacy mode: crawl store menus and write one raw_stores.json file.
2) Category mode: from feed homepage, discover and click category chips via
   `data-testid^="search-home-item-"` in page order,
   then save per-category minimal JSON files (name + URL only).

Usage:
    python crawler.py                                    # legacy mode
    python crawler.py --headed                           # legacy mode with visible browser
    python crawler.py --by-category                      # category mode
"""

import asyncio
import json
import logging
import os
import random
import re
import sys
from pathlib import Path
from typing import Sequence
from urllib.parse import unquote

try:
    from playwright.async_api import async_playwright, TimeoutError as PwTimeout
except ImportError:
    sys.exit(
        "playwright is required.  Install with:\n"
        "  pip install playwright && python -m playwright install chromium"
    )

ROOT_DIR = Path(__file__).resolve().parent
DATASET_DIR = ROOT_DIR / "dataset"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("crawler")

UBER_EATS_BASE = "https://www.ubereats.com"
FEED_URL = f"{UBER_EATS_BASE}/tw/feed"
CATEGORY_TESTID_PREFIX = "search-home-item-"
DEFAULT_CATEGORY_OUTPUT_DIR = DATASET_DIR / "stores_by_category"
EXCLUDED_CATEGORY_TAGS = {"生鮮雜貨"}

# Afternoon-tea-relevant categories with their stable data-testid values.
AFTERNOON_TEA_CATEGORIES = {
    "速食": "search-home-item-速食",
    "早餐和早午餐": "search-home-item-早餐和早午餐",
    "珍珠奶茶": "search-home-item-珍珠奶茶",
    "咖啡和茶": "search-home-item-咖啡和茶",
    "烘焙食品": "search-home-item-烘焙食品",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _random_delay(lo: float = 2.0, hi: float = 5.0) -> float:
    return random.uniform(lo, hi)


def _extract_store_id_from_url(url: str) -> str | None:
    """Return the base64url store UUID from a /tw/store/{slug}/{id} URL."""
    match = re.search(r"/tw/store/[^/]+/([A-Za-z0-9_-]{20,})", url)
    return match.group(1) if match else None


def _extract_store_slug(url: str) -> str:
    """Return the human-readable slug portion of a store URL."""
    match = re.search(r"/tw/store/([^/]+)/", url)
    if match:
        return unquote(match.group(1))
    return ""


def _build_store_url(slug: str, store_id: str) -> str:
    return f"{UBER_EATS_BASE}/tw/store/{slug}/{store_id}"


def _absolute_store_url(href: str) -> str:
    if href.startswith("http://") or href.startswith("https://"):
        return href
    if href.startswith("/"):
        return f"{UBER_EATS_BASE}{href}"
    return f"{UBER_EATS_BASE}/{href}"


def _sanitize_filename(text: str) -> str:
    name = text.strip()
    name = re.sub(r"[<>:\"/\\|?*]+", "_", name)
    name = re.sub(r"\s+", "_", name)
    return name or "category"


def _parse_category_list(raw_categories: str) -> list[str]:
    categories = [part.strip() for part in raw_categories.split(",")]
    return [c for c in categories if c]


def _is_usable_category_label(label: str) -> bool:
    text = re.sub(r"\s+", "", label.strip())
    return bool(text) and text not in EXCLUDED_CATEGORY_TAGS


def _parse_price(text: str) -> int | None:
    """Extract integer TWD price from strings like '$120' or 'NT$120'."""
    match = re.search(r"\$\s*(\d[\d,]*)", text)
    if match:
        return int(match.group(1).replace(",", ""))
    return None


# ---------------------------------------------------------------------------
# Playwright: set delivery address
# ---------------------------------------------------------------------------

async def set_delivery_address(page, address: str) -> None:
    """Navigate to Uber Eats and set the delivery address."""
    log.info("Navigating to Uber Eats TW feed …")
    await page.goto(FEED_URL, wait_until="domcontentloaded")
    await asyncio.sleep(_random_delay(3, 6))

    address_btn = page.locator(
        "[data-testid='address-option-current'], "
        "button:has-text('輸入外送地址'), "
        "a[href*='delivery-details']"
    ).first
    try:
        await address_btn.wait_for(state="visible", timeout=8000)
        await address_btn.click()
        await asyncio.sleep(_random_delay())
    except PwTimeout:
        log.info("No address prompt found, trying direct navigation …")

    await page.goto(
        f"{UBER_EATS_BASE}/tw/delivery-details?entryPoint=feed-enter-address",
        wait_until="domcontentloaded",
    )
    await asyncio.sleep(_random_delay())

    address_input = page.locator(
        "input[aria-label*='地址'], "
        "input[placeholder*='地址'], "
        "input[data-testid*='address'], "
        "input[type='text']"
    ).first
    await address_input.wait_for(state="visible", timeout=10000)
    await address_input.fill("")
    await address_input.type(address, delay=80)
    await asyncio.sleep(_random_delay(2, 4))

    suggestion = page.locator(
        "[data-testid*='suggestion'], "
        "[role='option'], "
        "li:has-text('台')"
    ).first
    try:
        await suggestion.wait_for(state="visible", timeout=8000)
        await suggestion.click()
    except PwTimeout:
        log.warning("No address suggestion dropdown found; pressing Enter.")
        await address_input.press("Enter")

    await asyncio.sleep(_random_delay(3, 5))

    confirm_btn = page.locator(
        "button:has-text('儲存'), "
        "button:has-text('確認'), "
        "button:has-text('Save'), "
        "[data-testid*='save']"
    ).first
    try:
        await confirm_btn.wait_for(state="visible", timeout=5000)
        await confirm_btn.click()
        await asyncio.sleep(_random_delay())
    except PwTimeout:
        log.info("No save/confirm button; address may already be set.")

    log.info("Address set to: %s", address)


# ---------------------------------------------------------------------------
# Playwright: collect store links from the feed
# ---------------------------------------------------------------------------

async def collect_store_links(page, max_stores: int) -> list[dict]:
    """Scroll the feed and collect up to *max_stores* store links."""
    log.info("Collecting store links (max %d) …", max_stores)
    await page.goto(FEED_URL, wait_until="domcontentloaded")
    await asyncio.sleep(_random_delay(3, 5))

    stores: dict[str, dict] = {}
    max_scroll_rounds = 20
    prev_count = 0
    stale_rounds = 0

    for _ in range(max_scroll_rounds):
        if len(stores) >= max_stores:
            break

        links = await page.locator("a[href*='/tw/store/']").all()
        for link in links:
            href = await link.get_attribute("href") or ""
            sid = _extract_store_id_from_url(href)
            if sid and sid not in stores:
                name = (await link.inner_text()).strip().split("\n")[0]
                slug = _extract_store_slug(href)
                stores[sid] = {
                    "store_id": sid,
                    "name": name or slug,
                    "slug": slug,
                    "url": _build_store_url(slug, sid),
                }
            if len(stores) >= max_stores:
                break

        if len(stores) == prev_count:
            stale_rounds += 1
            if stale_rounds >= 3:
                log.info("No new stores after 3 scroll rounds; stopping.")
                break
        else:
            stale_rounds = 0
        prev_count = len(stores)

        await page.evaluate("window.scrollBy(0, window.innerHeight)")
        await asyncio.sleep(_random_delay(1.5, 3.0))

    result = list(stores.values())[:max_stores]
    log.info("Collected %d store links.", len(result))
    return result


async def collect_store_links_from_current_view(page, max_stores: int) -> list[dict]:
    """Collect up to *max_stores* links from the current feed view."""
    stores: dict[str, dict] = {}
    max_scroll_rounds = 20
    prev_count = 0
    stale_rounds = 0

    for _ in range(max_scroll_rounds):
        if len(stores) >= max_stores:
            break

        links = await page.locator("a[href*='/tw/store/']").all()
        for link in links:
            href = await link.get_attribute("href") or ""
            abs_url = _absolute_store_url(href)
            sid = _extract_store_id_from_url(abs_url)
            if not sid:
                continue

            if sid not in stores:
                name = (await link.inner_text()).strip().split("\n")[0]
                stores[sid] = {
                    "store_id": sid,
                    "name": name or _extract_store_slug(abs_url),
                    "url": abs_url,
                }

            if len(stores) >= max_stores:
                break

        if len(stores) == prev_count:
            stale_rounds += 1
            if stale_rounds >= 3:
                break
        else:
            stale_rounds = 0
        prev_count = len(stores)

        await page.evaluate("window.scrollBy(0, window.innerHeight)")
        await asyncio.sleep(_random_delay(1.0, 2.5))

    return list(stores.values())[:max_stores]


async def _select_category_tag(page, category_testid: str,
                               category_label: str = "") -> bool:
    """Navigate to a category by extracting its href from the chip element.

    Category chips on Uber Eats are <a> tags with image content that may
    render with zero width in headless mode, making them unclickable.
    Instead of clicking, we extract the href and navigate directly.
    """
    # Wait for any chip to appear first (confirms feed is loaded)
    try:
        await page.locator(
            f"[data-testid^='{CATEGORY_TESTID_PREFIX}']"
        ).first.wait_for(state="attached", timeout=15000)
    except Exception:
        log.warning("No category chips appeared on feed page.")
        return False

    # Try data-testid first, then fallback to text-based selectors
    selectors = [f"[data-testid='{category_testid}']"]
    if category_label:
        selectors.extend([
            f"a:has-text('{category_label}')",
            f"[role='tab']:has-text('{category_label}')",
        ])

    for selector in selectors:
        locator = page.locator(selector).first
        try:
            await locator.wait_for(state="attached", timeout=8000)
            # Extract href and navigate directly (chips may be invisible
            # due to unloaded images yielding zero width).
            href = await locator.get_attribute("href")
            if href:
                url = href if href.startswith("http") else f"{UBER_EATS_BASE}{href}"
                await page.goto(url, wait_until="domcontentloaded")
                await asyncio.sleep(_random_delay(2.0, 4.0))
                return True
            # Fallback: try clicking if no href
            await locator.evaluate(
                "el => el.scrollIntoView({behavior:'instant',block:'nearest',inline:'center'})"
            )
            await asyncio.sleep(0.5)
            await locator.click(timeout=5000)
            await asyncio.sleep(_random_delay(1.0, 2.0))
            return True
        except Exception:
            continue

    return False


async def discover_category_tags_from_feed(page) -> list[dict]:
    """Discover category chips by data-testid in feed order."""
    await page.goto(FEED_URL, wait_until="domcontentloaded")
    await asyncio.sleep(_random_delay(2.0, 4.0))

    chips = await page.locator(
        f"[data-testid^='{CATEGORY_TESTID_PREFIX}']"
    ).all()

    seen_testids: set[str] = set()
    seen_labels: set[str] = set()
    ordered: list[dict] = []
    for idx, chip in enumerate(chips, 1):
        testid = (await chip.get_attribute("data-testid") or "").strip()
        if not testid or not testid.startswith(CATEGORY_TESTID_PREFIX):
            continue
        if testid in seen_testids:
            continue
        try:
            text = (await chip.inner_text()).strip().split("\n")[0]
        except Exception:
            continue
        label = re.sub(r"\s+", "", text)
        if not label:
            label = re.sub(
                r"\s+",
                "",
                testid.removeprefix(CATEGORY_TESTID_PREFIX),
            )
        if not _is_usable_category_label(label):
            continue
        if label in seen_labels:
            continue
        seen_testids.add(testid)
        seen_labels.add(label)
        ordered.append({
            "order": idx,
            "label": label,
            "testid": testid,
        })

    return ordered


def _minimal_store_records(store_links: list[dict],
                           ue_category: str = "") -> list[dict]:
    seen_urls: set[str] = set()
    result: list[dict] = []
    for store in store_links:
        url = (store.get("url") or "").strip()
        name = (store.get("name") or "").strip()
        if not url or url in seen_urls:
            continue
        seen_urls.add(url)
        record: dict = {"name": name, "url": url}
        if ue_category:
            record["ue_category"] = ue_category
        result.append(record)
    return result


def merge_category_stores(categorized: dict[str, list[dict]]) -> list[dict]:
    """Merge per-category stores into a deduplicated flat list."""
    seen_urls: set[str] = set()
    merged: list[dict] = []
    for stores in categorized.values():
        for store in stores:
            url = store.get("url", "")
            if url and url not in seen_urls:
                seen_urls.add(url)
                merged.append(store)
    return merged


# ---------------------------------------------------------------------------
# Playwright: scrape a single store menu
# ---------------------------------------------------------------------------

async def scrape_store_menu(page, store_url: str) -> list[dict]:
    """Visit a store page and extract menu items with prices."""
    await page.goto(store_url, wait_until="domcontentloaded")
    await asyncio.sleep(_random_delay(2, 4))

    for _ in range(5):
        await page.evaluate("window.scrollBy(0, window.innerHeight)")
        await asyncio.sleep(_random_delay(0.8, 1.5))

    items: list[dict] = []
    seen: set[str] = set()

    item_cards = await page.locator(
        "[data-testid*='store-item'], "
        "[data-testid*='menu-item'], "
        "li[class*='item'], "
        "a[href*='?mod=quickView']"
    ).all()

    if item_cards:
        for card in item_cards:
            text = (await card.inner_text()).strip()
            lines = [l.strip() for l in text.split("\n") if l.strip()]
            if len(lines) < 2:
                continue
            name = lines[0]
            price = None
            for line in lines[1:]:
                price = _parse_price(line)
                if price is not None:
                    break
            if name and price and name not in seen:
                seen.add(name)
                items.append({"name": name, "price_twd": price})

    if not items:
        all_text = await page.locator("main").inner_text()
        blocks = all_text.split("\n")
        i = 0
        while i < len(blocks) - 1:
            candidate_name = blocks[i].strip()
            if (not candidate_name or len(candidate_name) > 80
                    or _parse_price(candidate_name) is not None):
                i += 1
                continue
            for j in range(i + 1, min(i + 4, len(blocks))):
                price = _parse_price(blocks[j])
                if price is not None and candidate_name not in seen:
                    seen.add(candidate_name)
                    items.append({"name": candidate_name, "price_twd": price})
                    break
            i += 1

    return items


# ---------------------------------------------------------------------------
# Main crawl orchestrator
# ---------------------------------------------------------------------------

async def crawl_stores(address: str, output_path: str | None = None,
                       headed: bool = False,
                       max_stores: int = 30) -> list[dict]:
    """Main entry point: crawl Uber Eats and write raw_stores.json.

    Returns the list of store dicts written to the file.
    """
    if output_path is None:
        output_path = str(DATASET_DIR / "raw_stores.json")

    stores_data: list[dict] = []

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=not headed,
            args=["--disable-blink-features=AutomationControlled"],
        )
        context = await browser.new_context(
            locale="zh-TW",
            timezone_id="Asia/Taipei",
            viewport={"width": 1280, "height": 800},
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/123.0.0.0 Safari/537.36"
            ),
        )
        page = await context.new_page()

        try:
            await set_delivery_address(page, address)
            store_links = await collect_store_links(page, max_stores)

            for idx, store_info in enumerate(store_links, 1):
                name = store_info["name"]
                url = store_info["url"]

                log.info("[%d/%d] Scraping: %s", idx, len(store_links), name)
                try:
                    menu_items = await scrape_store_menu(page, url)
                except Exception as exc:
                    log.warning("Failed to scrape %s: %s", name, exc)
                    continue

                if not menu_items:
                    log.info("  No items found for %s; skipping.", name)
                    continue

                prices = [item["price_twd"] for item in menu_items]
                avg_price = round(sum(prices) / len(prices))

                stores_data.append({
                    "name": name,
                    "category": "",
                    "url": url,
                    "menu_items": menu_items,
                    "avg_price": avg_price,
                })
                log.info("  Found %d items for %s (avg $%d).",
                         len(menu_items), name, avg_price)

                await asyncio.sleep(_random_delay())

        finally:
            await browser.close()

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(stores_data, f, ensure_ascii=False, indent=2)

    log.info("Wrote %d stores to %s", len(stores_data), output_path)
    return stores_data


async def crawl_stores_by_category(
    address: str,
    output_dir: str | None = None,
    categories: Sequence[str] | None = None,
    headed: bool = False,
    max_stores_per_category: int = 80,
    afternoon_tea_only: bool = False,
) -> dict[str, list[dict]]:
    """Crawl by category chips (feed order) and write per-category minimal JSON.

    When *afternoon_tea_only* is True, only crawl categories listed in
    AFTERNOON_TEA_CATEGORIES instead of discovering all available chips.
    """
    if output_dir is None:
        output_dir = str(DEFAULT_CATEGORY_OUTPUT_DIR)

    output_root = Path(output_dir)
    output_root.mkdir(parents=True, exist_ok=True)

    # Clear stale per-category files from previous runs
    for old_file in output_root.glob("*.json"):
        old_file.unlink()

    categorized: dict[str, list[dict]] = {}

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=not headed,
            args=["--disable-blink-features=AutomationControlled"],
        )
        context = await browser.new_context(
            locale="zh-TW",
            timezone_id="Asia/Taipei",
            viewport={"width": 1280, "height": 800},
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/123.0.0.0 Safari/537.36"
            ),
        )
        page = await context.new_page()

        try:
            await set_delivery_address(page, address)

            if afternoon_tea_only and not categories:
                # Use predefined afternoon tea categories without discovery
                categories_to_crawl = [
                    {"label": label, "testid": testid}
                    for label, testid in AFTERNOON_TEA_CATEGORIES.items()
                ]
                log.info("Afternoon tea mode: crawling %d predefined categories.",
                         len(categories_to_crawl))
            else:
                discovered_categories = await discover_category_tags_from_feed(page)
                if not discovered_categories:
                    log.warning("No category chips discovered; nothing to crawl.")

                categories_to_crawl = discovered_categories
                if categories:
                    requested = {re.sub(r"\s+", "", c) for c in categories if c.strip()}
                    categories_to_crawl = [
                        c for c in discovered_categories if c["label"] in requested
                    ]
                    found = {c["label"] for c in categories_to_crawl}
                    missing = sorted(requested - found)
                    for label in missing:
                        log.warning("Requested category not found on feed: %s", label)

            async def _crawl_one_category(
                category_info: dict, idx: int, total: int,
            ) -> int:
                """Crawl a single category. Returns number of stores found."""
                category = category_info["label"]
                category_testid = category_info["testid"]

                log.info("[%d/%d] Crawling category: %s", idx, total, category)

                await page.goto(FEED_URL, wait_until="networkidle")
                await asyncio.sleep(_random_delay(3.0, 5.0))

                if not await _select_category_tag(
                    page, category_testid, category_label=category
                ):
                    log.info("Retrying category %s after reload …", category)
                    await page.reload(wait_until="networkidle")
                    await asyncio.sleep(_random_delay(3.0, 5.0))
                    if not await _select_category_tag(
                        page, category_testid, category_label=category
                    ):
                        log.warning("Category chip not found: %s (%s)",
                                    category, category_testid)
                        return 0

                stores = await collect_store_links_from_current_view(
                    page, max_stores=max_stores_per_category
                )
                minimal_stores = _minimal_store_records(
                    stores, ue_category=category
                )
                categorized[category] = minimal_stores

                filename = f"{idx:02d}_{_sanitize_filename(category)}.json"
                file_path = output_root / filename
                with open(file_path, "w", encoding="utf-8") as f:
                    json.dump(minimal_stores, f, ensure_ascii=False, indent=2)

                log.info("Saved %d stores to %s", len(minimal_stores), file_path)
                await asyncio.sleep(_random_delay(1.0, 2.5))
                return len(minimal_stores)

            # First pass
            crawlable = [
                c for c in categories_to_crawl
                if c["label"] not in EXCLUDED_CATEGORY_TAGS
            ]
            empty_categories: list[dict] = []
            for output_idx, cat_info in enumerate(crawlable, 1):
                count = await _crawl_one_category(
                    cat_info, output_idx, len(crawlable)
                )
                if count == 0:
                    empty_categories.append(cat_info)

            # Retry categories that returned 0 stores
            if empty_categories:
                labels = ", ".join(c["label"] for c in empty_categories)
                log.info("Retrying %d empty categories: %s",
                         len(empty_categories), labels)
                for cat_info in empty_categories:
                    idx = next(
                        i for i, c in enumerate(crawlable, 1)
                        if c["label"] == cat_info["label"]
                    )
                    count = await _crawl_one_category(
                        cat_info, idx, len(crawlable)
                    )
                    if count == 0:
                        log.warning("Category %s still empty after retry; "
                                    "giving up.", cat_info["label"])

        finally:
            await browser.close()

    return categorized


# ---------------------------------------------------------------------------
# .env loader
# ---------------------------------------------------------------------------

def load_dotenv(dotenv_path: Path) -> None:
    if not dotenv_path.exists():
        return
    for raw_line in dotenv_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    load_dotenv(ROOT_DIR / ".env")

    address = os.getenv("UBER_EATS_TAIPEI_ADDRESS", "")
    if not address:
        sys.exit(
            "UBER_EATS_TAIPEI_ADDRESS is not set.\n"
            "Copy .env.example to .env and fill in your delivery address."
        )

    headed = False
    by_category = False
    afternoon_tea = False
    categories_arg: str | None = None
    output_path: str | None = None
    output_dir: str | None = None
    max_stores: int | None = None
    max_per_category: int | None = None

    args = sys.argv[1:]
    i = 0
    while i < len(args):
        arg = args[i]
        if arg == "--headed":
            headed = True
            i += 1
        elif arg in ("--by-category", "--category-mode"):
            by_category = True
            i += 1
        elif arg == "--afternoon-tea":
            by_category = True
            afternoon_tea = True
            i += 1
        elif arg == "--categories" and i + 1 < len(args):
            categories_arg = args[i + 1]
            i += 2
        elif arg == "--output" and i + 1 < len(args):
            output_path = args[i + 1]
            i += 2
        elif arg == "--output-dir" and i + 1 < len(args):
            output_dir = args[i + 1]
            i += 2
        elif arg == "--max-stores" and i + 1 < len(args):
            max_stores = int(args[i + 1])
            i += 2
        elif arg == "--max-per-category" and i + 1 < len(args):
            max_per_category = int(args[i + 1])
            i += 2
        else:
            i += 1

    if by_category:
        categories: list[str] | None = None
        if categories_arg:
            categories = _parse_category_list(categories_arg)
            categories = [c for c in categories if c not in EXCLUDED_CATEGORY_TAGS]
            if not categories:
                categories = None

        if max_per_category is None:
            max_per_category = int(os.getenv("MAX_STORES_PER_CATEGORY", "80"))

        asyncio.run(crawl_stores_by_category(
            address=address,
            output_dir=output_dir,
            categories=categories,
            headed=headed,
            max_stores_per_category=max_per_category,
            afternoon_tea_only=afternoon_tea,
        ))
        return

    if max_stores is None:
        max_stores = int(os.getenv("MAX_STORES_PER_CRAWL", "30"))

    asyncio.run(crawl_stores(
        address=address,
        output_path=output_path,
        headed=headed,
        max_stores=max_stores,
    ))


if __name__ == "__main__":
    main()
