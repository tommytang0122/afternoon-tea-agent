#!/usr/bin/env python3
"""Classify raw store data into afternoon tea candidates using Gemini API.

Reads raw_stores.json (category mode), calls Gemini to filter and categorize
stores, and writes afternoon_tea.json.

Usage:
    python classifier.py
    python classifier.py --input dataset/raw_stores.json --output dataset/afternoon_tea.json
"""

import json
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

try:
    from google import genai
except ImportError:
    sys.exit(
        "google-genai is required.  Install with:\n"
        "  pip install google-genai"
    )

from prompts import CLASSIFICATION_PROMPT

ROOT_DIR = Path(__file__).resolve().parent
DATASET_DIR = ROOT_DIR / "dataset"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("classifier")

GEMINI_MODEL = "gemini-2.5-flash"


def classify_stores(raw_stores: list[dict],
                    api_key: str | None = None) -> dict:
    """Call Gemini API to classify raw stores into afternoon tea candidates.

    Args:
        raw_stores: List of store dicts from raw_stores.json.
        api_key: Gemini API key. Falls back to GEMINI_API_KEY env var.

    Returns:
        Dict with generated_at, store_count, pipeline_mode, and stores fields.
    """
    if api_key is None:
        api_key = os.getenv("GEMINI_API_KEY", "")
    if not api_key:
        raise ValueError(
            "GEMINI_API_KEY is not set. "
            "Set it in .env or pass it as an argument."
        )

    client = genai.Client(api_key=api_key)

    prompt = CLASSIFICATION_PROMPT + json.dumps(raw_stores, ensure_ascii=False)

    log.info("Calling Gemini API (%s) with %d stores …",
             GEMINI_MODEL, len(raw_stores))

    response = client.models.generate_content(
        model=GEMINI_MODEL,
        contents=prompt,
        config={"max_output_tokens": 65536},
    )

    # Log finish reason to diagnose truncation
    if response.candidates:
        fr = response.candidates[0].finish_reason
        log.info("Gemini finish_reason: %s", fr)

    response_text = response.text.strip()
    # Strip markdown code fences if present
    if response_text.startswith("```"):
        lines = response_text.split("\n")
        lines = [l for l in lines if not l.strip().startswith("```")]
        response_text = "\n".join(lines)

    result = json.loads(response_text)

    stores = result.get("stores", [])
    output = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "pipeline_mode": "category",
        "store_count": len(stores),
        "stores": stores,
    }

    log.info("Gemini returned %d afternoon tea stores.", len(stores))
    return output


def classify_stores_batch(raw_stores: list[dict],
                          api_key: str | None = None) -> dict:
    """Classify stores in batches grouped by ``ue_category``.

    Splits *raw_stores* by their ``ue_category`` field and calls
    :func:`classify_stores` once per group.  Results are merged and
    deduplicated by URL.
    """
    groups: dict[str, list[dict]] = {}
    for store in raw_stores:
        key = store.get("ue_category", "")
        groups.setdefault(key, []).append(store)

    all_stores: list[dict] = []
    seen_urls: set[str] = set()

    for idx, (category, batch) in enumerate(groups.items(), 1):
        label = category or "(未分類)"
        log.info("[%d/%d] Classifying batch: %s (%d stores)",
                 idx, len(groups), label, len(batch))

        result = classify_stores(batch, api_key=api_key)

        for store in result.get("stores", []):
            url = store.get("url", "")
            if url and url not in seen_urls:
                seen_urls.add(url)
                all_stores.append(store)

    output = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "pipeline_mode": "category",
        "store_count": len(all_stores),
        "stores": all_stores,
    }
    log.info("Batch classification done: %d afternoon tea stores total.",
             len(all_stores))
    return output


def run_classification(input_path: str | None = None,
                       output_path: str | None = None,
                       api_key: str | None = None) -> dict:
    """Read raw_stores.json, classify, and write afternoon_tea.json."""
    if input_path is None:
        input_path = str(DATASET_DIR / "raw_stores.json")
    if output_path is None:
        output_path = str(DATASET_DIR / "afternoon_tea.json")

    with open(input_path, "r", encoding="utf-8") as f:
        raw_stores = json.load(f)

    log.info("Loaded %d stores from %s", len(raw_stores), input_path)

    result = classify_stores_batch(raw_stores, api_key=api_key)

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    log.info("Wrote %d stores to %s", result["store_count"], output_path)
    return result


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

    input_path = None
    output_path = None
    args = sys.argv[1:]
    i = 0
    while i < len(args):
        if args[i] == "--input" and i + 1 < len(args):
            input_path = args[i + 1]
            i += 2
        elif args[i] == "--output" and i + 1 < len(args):
            output_path = args[i + 1]
            i += 2
        else:
            i += 1

    run_classification(input_path=input_path, output_path=output_path)


if __name__ == "__main__":
    main()
