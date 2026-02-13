#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
APP_DIR="$PROJECT_ROOT/apps/ubereats-local-web"

PASSED=0
FAILED=0
RESULTS=()

run_stage() {
    local stage_name="$1"
    shift
    echo ""
    echo "========================================"
    echo "  $stage_name"
    echo "========================================"
    if "$@"; then
        RESULTS+=("PASSED  $stage_name")
        PASSED=$((PASSED + 1))
    else
        RESULTS+=("FAILED  $stage_name")
        FAILED=$((FAILED + 1))
        echo ""
        echo "ABORT: $stage_name failed."
        print_summary
        exit 1
    fi
}

print_summary() {
    echo ""
    echo "========================================"
    echo "  Regression Test Summary"
    echo "========================================"
    for r in "${RESULTS[@]}"; do
        echo "  $r"
    done
    echo ""
    if [ "$FAILED" -eq 0 ]; then
        echo "  ALL $PASSED STAGES PASSED"
    else
        echo "  $FAILED STAGE(S) FAILED"
    fi
    echo "========================================"
}

# ── Stage 1: Unit Tests ──────────────────────────────────────────────
run_stage "Stage 1: Unit Tests" \
    python3 -m pytest "$APP_DIR/tests/" -v --ignore="$APP_DIR/tests/test_dataset_schema.py"

# ── Stage 2: Module Import Check ─────────────────────────────────────
stage2_imports() {
    cd "$APP_DIR"
    echo "  Checking prompts..."
    python3 -c "from prompts import CLASSIFICATION_PROMPT; print(f'  OK: CLASSIFICATION_PROMPT ({len(CLASSIFICATION_PROMPT)} chars)')"
    echo "  Checking classifier..."
    python3 -c "from classifier import classify_stores, classify_stores_batch, run_classification; print('  OK: classify_stores, classify_stores_batch, run_classification')"
    echo "  Checking crawler..."
    python3 -c "from crawler import crawl_stores_by_category, merge_category_stores; print('  OK: crawl_stores_by_category, merge_category_stores')"
    echo "  Checking pipeline..."
    python3 -c "from pipeline import run_pipeline; print('  OK: run_pipeline')"
    cd "$PROJECT_ROOT"
}
run_stage "Stage 2: Module Import Check" stage2_imports

# ── Stage 3: Dataset Schema Validation ────────────────────────────────
run_stage "Stage 3: Dataset Schema Validation" \
    python3 -m pytest "$APP_DIR/tests/test_dataset_schema.py" -v

# ── Stage 4: Dead Code / Legacy Reference Scan ───────────────────────
stage4_dead_code() {
    local found=0
    local patterns=(
        "--legacy"
        "menu_items"
        "crawl_stores[^_]"
        "legacy_mode"
        "use_legacy"
    )
    echo "  Scanning for legacy references in Python files..."
    for pattern in "${patterns[@]}"; do
        if grep -rn --include="*.py" "$pattern" "$APP_DIR" \
            --exclude-dir=__pycache__ \
            --exclude-dir=.git \
            --exclude="test_dataset_schema.py" \
            --exclude="regression_test.sh" 2>/dev/null; then
            echo "  FOUND legacy reference: $pattern"
            found=1
        fi
    done
    if [ "$found" -eq 1 ]; then
        echo "  Legacy references detected!"
        return 1
    else
        echo "  No legacy references found."
        return 0
    fi
}
run_stage "Stage 4: Dead Code / Legacy Reference Scan" stage4_dead_code

# ── Summary ───────────────────────────────────────────────────────────
print_summary
