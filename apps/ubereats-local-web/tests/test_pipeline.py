"""Integration tests for pipeline.py."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


SAMPLE_CATEGORY_STORES = [
    {
        "name": "晨光咖啡",
        "url": "https://www.ubereats.com/tw/store/morning-coffee/abc123",
        "ue_category": "咖啡和茶",
    },
]

SAMPLE_LEGACY_STORES = [
    {
        "name": "晨光咖啡",
        "category": "咖啡",
        "url": "https://www.ubereats.com/tw/store/morning-coffee/abc123",
        "menu_items": [{"name": "拿鐵", "price_twd": 120}],
        "avg_price": 120,
    },
]

MOCK_CLASSIFIED = {
    "stores": [
        {
            "name": "晨光咖啡",
            "type": "熱飲",
            "store_category": "飲料店",
            "tags": ["咖啡"],
            "url": "https://www.ubereats.com/tw/store/morning-coffee/abc123",
        },
    ]
}


def _load_pipeline_module(monkeypatch):
    import importlib.util
    from pathlib import Path

    monkeypatch.setenv("GEMINI_API_KEY", "fake-key")

    pipeline_path = Path(__file__).resolve().parents[1] / "pipeline.py"
    spec = importlib.util.spec_from_file_location("pipeline", pipeline_path)
    pipeline_mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(pipeline_mod)
    return pipeline_mod


def test_pipeline_skip_crawl(tmp_path, monkeypatch):
    """Test pipeline with --skip-crawl: reads existing raw_stores.json."""
    pipeline_mod = _load_pipeline_module(monkeypatch)

    dataset_dir = tmp_path / "dataset"
    dataset_dir.mkdir()
    raw_path = dataset_dir / "raw_stores.json"
    raw_path.write_text(
        json.dumps(SAMPLE_CATEGORY_STORES, ensure_ascii=False), encoding="utf-8"
    )

    monkeypatch.setattr(pipeline_mod, "DATASET_DIR", dataset_dir)

    mock_classify = MagicMock(return_value={
        "generated_at": "2026-02-10T12:00:00Z",
        "pipeline_mode": "category",
        "store_count": 1,
        "stores": MOCK_CLASSIFIED["stores"],
    })

    with patch.dict("sys.modules", {"classifier": MagicMock(
        run_classification=mock_classify
    )}):
        pipeline_mod.run_pipeline(skip_crawl=True, headed=False)

    mock_classify.assert_called_once()
    call_kwargs = mock_classify.call_args
    assert "raw_stores.json" in str(call_kwargs)


def test_pipeline_skip_crawl_legacy_format(tmp_path, monkeypatch):
    """Test --skip-crawl with legacy raw_stores.json (has menu_items)."""
    pipeline_mod = _load_pipeline_module(monkeypatch)

    dataset_dir = tmp_path / "dataset"
    dataset_dir.mkdir()
    raw_path = dataset_dir / "raw_stores.json"
    raw_path.write_text(
        json.dumps(SAMPLE_LEGACY_STORES, ensure_ascii=False), encoding="utf-8"
    )

    monkeypatch.setattr(pipeline_mod, "DATASET_DIR", dataset_dir)

    mock_classify = MagicMock(return_value={
        "generated_at": "2026-02-10T12:00:00Z",
        "pipeline_mode": "full",
        "store_count": 1,
        "stores": MOCK_CLASSIFIED["stores"],
    })

    with patch.dict("sys.modules", {"classifier": MagicMock(
        run_classification=mock_classify
    )}):
        pipeline_mod.run_pipeline(skip_crawl=True, headed=False, legacy=True)

    mock_classify.assert_called_once()
