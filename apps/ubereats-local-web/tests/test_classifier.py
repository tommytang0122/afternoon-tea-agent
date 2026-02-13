"""Unit tests for classifier.py with mocked Gemini API."""

import json
from unittest.mock import MagicMock, patch

import pytest


SAMPLE_CATEGORY_STORES = [
    {
        "name": "晨光咖啡",
        "url": "https://www.ubereats.com/tw/store/morning-coffee/abc123",
        "ue_category": "咖啡和茶",
    },
    {
        "name": "甜點角落",
        "url": "https://www.ubereats.com/tw/store/dessert-corner/def456",
        "ue_category": "烘焙食品",
    },
]

MOCK_CATEGORY_GEMINI_RESPONSE = {
    "stores": [
        {
            "name": "晨光咖啡",
            "type": "熱飲",
            "store_category": "飲料店",
            "tags": ["咖啡"],
            "url": "https://www.ubereats.com/tw/store/morning-coffee/abc123",
        },
        {
            "name": "甜點角落",
            "type": "甜食",
            "store_category": "甜點/烘焙",
            "tags": ["蛋糕"],
            "url": "https://www.ubereats.com/tw/store/dessert-corner/def456",
        },
    ]
}


def _make_mock_response(text: str):
    response = MagicMock()
    response.text = text
    return response


class TestClassifyStores:
    def test_returns_classified_stores(self, classifier_module):
        mock_client = MagicMock()
        mock_client.models.generate_content.return_value = _make_mock_response(
            json.dumps(MOCK_CATEGORY_GEMINI_RESPONSE, ensure_ascii=False)
        )

        with patch.object(classifier_module.genai, "Client", return_value=mock_client):
            result = classifier_module.classify_stores(
                SAMPLE_CATEGORY_STORES, api_key="fake-key"
            )

        assert result["store_count"] == 2
        assert len(result["stores"]) == 2
        assert result["stores"][0]["name"] == "晨光咖啡"
        assert result["stores"][0]["type"] == "熱飲"
        assert result["stores"][0]["store_category"] == "飲料店"
        assert result["generated_at"] is not None
        assert result["pipeline_mode"] == "category"

    def test_strips_markdown_fences(self, classifier_module):
        fenced = "```json\n" + json.dumps(MOCK_CATEGORY_GEMINI_RESPONSE, ensure_ascii=False) + "\n```"
        mock_client = MagicMock()
        mock_client.models.generate_content.return_value = _make_mock_response(fenced)

        with patch.object(classifier_module.genai, "Client", return_value=mock_client):
            result = classifier_module.classify_stores(
                SAMPLE_CATEGORY_STORES, api_key="fake-key"
            )

        assert result["store_count"] == 2

    def test_raises_without_api_key(self, classifier_module, monkeypatch):
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        with pytest.raises(ValueError, match="GEMINI_API_KEY"):
            classifier_module.classify_stores(SAMPLE_CATEGORY_STORES, api_key=None)


class TestRunClassification:
    def test_reads_and_writes_json(self, classifier_module, tmp_path):
        input_path = str(tmp_path / "raw_stores.json")
        output_path = str(tmp_path / "afternoon_tea.json")

        with open(input_path, "w", encoding="utf-8") as f:
            json.dump(SAMPLE_CATEGORY_STORES, f, ensure_ascii=False)

        mock_client = MagicMock()
        mock_client.models.generate_content.return_value = _make_mock_response(
            json.dumps(MOCK_CATEGORY_GEMINI_RESPONSE, ensure_ascii=False)
        )

        with patch.object(classifier_module.genai, "Client", return_value=mock_client):
            result = classifier_module.run_classification(
                input_path=input_path,
                output_path=output_path,
                api_key="fake-key",
            )

        assert result["store_count"] == 2

        with open(output_path, "r", encoding="utf-8") as f:
            saved = json.load(f)
        assert saved["store_count"] == 2
        assert len(saved["stores"]) == 2
