#!/usr/bin/env python3
"""Classify raw store data into afternoon tea candidates using Gemini API.

Reads raw_stores.json, calls Gemini to filter and categorize stores,
and writes afternoon_tea.json.

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

ROOT_DIR = Path(__file__).resolve().parent
DATASET_DIR = ROOT_DIR / "dataset"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("classifier")

GEMINI_MODEL = "gemini-2.5-flash"

CLASSIFICATION_PROMPT = """\
你是一個下午茶推薦助手。以下是從 Uber Eats 爬取的店家資料（JSON 格式）。

請你：
1. 先排除「大賣場、超市、量販、生鮮雜貨型商店」，例如：Costco、家樂福、全聯、Uber Eats 優市。
2. 過濾掉平均消費 > 200 TWD 的店。
3. 判定每家店的下午茶推薦類型 `type`，只能是以下其中一種：「甜食」「鹹食」「冷飲」「熱飲」「其他」。
4. 判定每家店的主要店型 `store_category`，只能是以下 5 類其中一種：
   - 「飲料店」
   - 「甜點/烘焙」
   - 「輕食/早午餐」
   - 「速食/炸物」
   - 「正餐主食」
5. 判定是否適合下午茶（排除便當店、火鍋店、重正餐導向店家等）。
6. 為每家店挑出最多 5 個代表性品項（格式：品名 $價格）。

請只輸出 JSON，不要加任何說明文字。格式如下：
{
  "stores": [
    {
      "name": "店名",
      "type": "甜食|鹹食|冷飲|熱飲|其他",
      "store_category": "飲料店|甜點/烘焙|輕食/早午餐|速食/炸物|正餐主食",
      "tags": ["標籤1", "標籤2"],
      "url": "原始 URL",
      "avg_price": 數字,
      "top_items": ["品名 $價格", "品名 $價格"]
    }
  ]
}

以下是店家資料：
"""

CATEGORY_CLASSIFICATION_PROMPT = """\
你是一個下午茶推薦助手。以下是從 Uber Eats 爬取的店家資料（JSON 格式），
每筆包含店名、URL、以及 Uber Eats 的原始分類（ue_category）。

請你：
1. 排除「大賣場、超市、量販、生鮮雜貨型商店」，例如：Costco、家樂福、全聯、Uber Eats 優市。
2. 排除明顯不適合下午茶的店（便當店、火鍋店、重正餐導向店家等）。
3. 判定每家店的下午茶推薦類型 `type`，只能是以下其中一種：「甜食」「鹹食」「冷飲」「熱飲」「其他」。
4. 判定每家店的主要店型 `store_category`，只能是以下 5 類其中一種：
   - 「飲料店」
   - 「甜點/烘焙」
   - 「輕食/早午餐」
   - 「速食/炸物」
   - 「正餐主食」
5. 為每家店加上相關 tags。

請只輸出 JSON，不要加任何說明文字。格式如下：
{
  "stores": [
    {
      "name": "店名",
      "type": "甜食|鹹食|冷飲|熱飲|其他",
      "store_category": "飲料店|甜點/烘焙|輕食/早午餐|速食/炸物|正餐主食",
      "tags": ["標籤1", "標籤2"],
      "url": "原始 URL"
    }
  ]
}

以下是店家資料：
"""


def classify_stores(raw_stores: list[dict],
                    api_key: str | None = None) -> dict:
    """Call Gemini API to classify raw stores into afternoon tea candidates.

    Auto-detects mode: if stores have ``menu_items``, uses the full prompt
    (legacy mode); otherwise uses the category-aware prompt.

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

    has_menu = any("menu_items" in s for s in raw_stores)
    if has_menu:
        prompt_template = CLASSIFICATION_PROMPT
        pipeline_mode = "full"
    else:
        prompt_template = CATEGORY_CLASSIFICATION_PROMPT
        pipeline_mode = "category"

    client = genai.Client(api_key=api_key)

    prompt = prompt_template + json.dumps(raw_stores, ensure_ascii=False)

    log.info("Calling Gemini API (%s) with %d stores [mode=%s] …",
             GEMINI_MODEL, len(raw_stores), pipeline_mode)

    response = client.models.generate_content(
        model=GEMINI_MODEL,
        contents=prompt,
    )

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
        "pipeline_mode": pipeline_mode,
        "store_count": len(stores),
        "stores": stores,
    }

    log.info("Gemini returned %d afternoon tea stores.", len(stores))
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

    result = classify_stores(raw_stores, api_key=api_key)

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
