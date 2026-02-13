"""Validate the schema of dataset/afternoon_tea.json."""

import json
from pathlib import Path

import pytest

DATASET_PATH = Path(__file__).parent.parent / "dataset" / "afternoon_tea.json"

pytestmark = pytest.mark.skipif(
    not DATASET_PATH.exists(),
    reason="dataset/afternoon_tea.json not found, skipping schema tests",
)

VALID_TYPES = {"甜食", "鹹食", "冷飲", "熱飲", "其他"}
VALID_STORE_CATEGORIES = {"飲料店", "甜點/烘焙", "輕食/早午餐", "速食/炸物"}
STORE_REQUIRED_FIELDS = {"name", "type", "store_category", "tags", "url"}


@pytest.fixture(scope="module")
def dataset():
    with open(DATASET_PATH, encoding="utf-8") as f:
        return json.load(f)


def test_top_level_fields(dataset):
    for field in ("generated_at", "pipeline_mode", "store_count", "stores"):
        assert field in dataset, f"Missing top-level field: {field}"


def test_pipeline_mode_is_category(dataset):
    assert dataset["pipeline_mode"] == "category"


def test_store_count_matches(dataset):
    assert dataset["store_count"] == len(dataset["stores"])


def test_store_required_fields(dataset):
    for i, store in enumerate(dataset["stores"]):
        missing = STORE_REQUIRED_FIELDS - store.keys()
        assert not missing, f"Store [{i}] {store.get('name', '?')} missing fields: {missing}"


def test_store_type_values(dataset):
    for i, store in enumerate(dataset["stores"]):
        assert store["type"] in VALID_TYPES, (
            f"Store [{i}] {store['name']} has invalid type: {store['type']}"
        )


def test_store_category_values(dataset):
    for i, store in enumerate(dataset["stores"]):
        assert store["store_category"] in VALID_STORE_CATEGORIES, (
            f"Store [{i}] {store['name']} has invalid store_category: {store['store_category']}"
        )


def test_no_duplicate_urls(dataset):
    urls = [s["url"] for s in dataset["stores"]]
    duplicates = [u for u in urls if urls.count(u) > 1]
    assert not duplicates, f"Duplicate URLs found: {set(duplicates)}"


def test_urls_are_uber_eats(dataset):
    prefix = "https://www.ubereats.com/tw/store/"
    for i, store in enumerate(dataset["stores"]):
        assert store["url"].startswith(prefix), (
            f"Store [{i}] {store['name']} URL doesn't start with {prefix}: {store['url']}"
        )
