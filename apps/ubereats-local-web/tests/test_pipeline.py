"""Integration tests for pipeline.py."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


SAMPLE_RAW_STORES = [
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
            "tags": ["咖啡"],
            "url": "https://www.ubereats.com/tw/store/morning-coffee/abc123",
            "avg_price": 120,
            "top_items": ["拿鐵 $120"],
        },
    ]
}


def test_pipeline_skip_crawl(tmp_path, monkeypatch):
    """Test pipeline with --skip-crawl: reads existing raw_stores.json."""
    import importlib.util
    from pathlib import Path

    # Write raw_stores.json so skip-crawl can find it
    dataset_dir = tmp_path / "dataset"
    dataset_dir.mkdir()
    raw_path = dataset_dir / "raw_stores.json"
    raw_path.write_text(
        json.dumps(SAMPLE_RAW_STORES, ensure_ascii=False), encoding="utf-8"
    )

    # Load pipeline module
    pipeline_path = Path(__file__).resolve().parents[1] / "pipeline.py"
    spec = importlib.util.spec_from_file_location("pipeline", pipeline_path)
    pipeline_mod = importlib.util.module_from_spec(spec)

    # Override DATASET_DIR before exec
    monkeypatch.setenv("GEMINI_API_KEY", "fake-key")

    spec.loader.exec_module(pipeline_mod)

    # Patch DATASET_DIR and the classifier import
    monkeypatch.setattr(pipeline_mod, "DATASET_DIR", dataset_dir)

    mock_classify = MagicMock(return_value={
        "generated_at": "2026-02-10T12:00:00Z",
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
