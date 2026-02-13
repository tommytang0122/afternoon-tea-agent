import importlib.util
import sys
from pathlib import Path

import pytest

APP_DIR = Path(__file__).resolve().parents[1]

# Ensure app dir is on sys.path so intra-package imports (e.g. prompts) work
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))


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
