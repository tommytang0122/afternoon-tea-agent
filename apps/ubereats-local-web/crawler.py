#!/usr/bin/env python3
"""Playwright crawler for Uber Eats Taiwan.

Navigates to Uber Eats, sets a delivery address, collects deliverable
stores, scrapes their menus, and writes everything to a JSON file.

Usage:
    python crawler.py              # headless (default)
    python crawler.py --headed     # visible browser for debugging
"""

import asyncio
import json
import logging
import os
import random
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
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

    max_stores = int(os.getenv("MAX_STORES_PER_CRAWL", "30"))
    headed = "--headed" in sys.argv

    asyncio.run(crawl_stores(address, headed=headed, max_stores=max_stores))


if __name__ == "__main__":
    main()
