#!/usr/bin/env python3
"""End-to-end pipeline: crawl Uber Eats → classify with Gemini → done.

Usage:
    python pipeline.py                    # run full pipeline
    python pipeline.py --skip-crawl       # skip crawling, only classify
    python pipeline.py --headed           # run crawler with visible browser
"""

import asyncio
import logging
import os
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent
DATASET_DIR = ROOT_DIR / "dataset"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("pipeline")


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


def run_pipeline(skip_crawl: bool = False, headed: bool = False) -> None:
    """Run the full data preprocessing pipeline."""
    load_dotenv(ROOT_DIR / ".env")

    raw_stores_path = str(DATASET_DIR / "raw_stores.json")
    afternoon_tea_path = str(DATASET_DIR / "afternoon_tea.json")

    # Step 1: Crawl
    if not skip_crawl:
        log.info("=== Step 1: Crawling Uber Eats ===")
        from crawler import crawl_stores

        address = os.getenv("UBER_EATS_TAIPEI_ADDRESS", "")
        if not address:
            sys.exit(
                "UBER_EATS_TAIPEI_ADDRESS is not set.\n"
                "Copy .env.example to .env and fill in your delivery address."
            )

        max_stores = int(os.getenv("MAX_STORES_PER_CRAWL", "30"))
        stores = asyncio.run(
            crawl_stores(
                address,
                output_path=raw_stores_path,
                headed=headed,
                max_stores=max_stores,
            )
        )
        log.info("Crawl complete: %d stores saved.", len(stores))
    else:
        log.info("=== Step 1: Skipped (--skip-crawl) ===")
        if not Path(raw_stores_path).exists():
            sys.exit(
                f"Cannot skip crawl: {raw_stores_path} does not exist.\n"
                "Run the pipeline without --skip-crawl first."
            )

    # Step 2: Classify
    log.info("=== Step 2: Classifying with Gemini API ===")
    from classifier import run_classification

    result = run_classification(
        input_path=raw_stores_path,
        output_path=afternoon_tea_path,
    )
    log.info("Classification complete: %d afternoon tea stores.",
             result["store_count"])

    log.info("=== Pipeline done ===")
    log.info("  raw_stores.json:     %s", raw_stores_path)
    log.info("  afternoon_tea.json:  %s", afternoon_tea_path)


def main() -> None:
    skip_crawl = "--skip-crawl" in sys.argv
    headed = "--headed" in sys.argv
    run_pipeline(skip_crawl=skip_crawl, headed=headed)


if __name__ == "__main__":
    main()
