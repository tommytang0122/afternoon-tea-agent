import importlib.util
from pathlib import Path

import pytest

APP_DIR = Path(__file__).resolve().parents[1]


@pytest.fixture
def crawler_module():
    spec = importlib.util.spec_from_file_location(
        "crawler", APP_DIR / "crawler.py"
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def classifier_module():
    spec = importlib.util.spec_from_file_location(
        "classifier", APP_DIR / "classifier.py"
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module