# Repository Guidelines

## Project Structure & Module Organization
- `apps/ubereats-local-web/` contains the runnable local app.
- `apps/ubereats-local-web/crawler.py` is the Playwright crawler that scrapes Uber Eats stores and menus into `dataset/raw_stores.json`.
- `apps/ubereats-local-web/classifier.py` calls Gemini API to filter and categorize stores into `dataset/afternoon_tea.json`.
- `apps/ubereats-local-web/pipeline.py` orchestrates crawl → classify in one command.
- `apps/ubereats-local-web/dataset/` holds runtime JSON data files (not committed).
- `docs/` stores the PRD and historical design docs.

## Build, Test, and Development Commands
- `pip install -r requirements.txt` installs all Python dependencies.
- `python -m playwright install chromium` installs the browser for crawling.
- `cd apps/ubereats-local-web && cp .env.example .env` creates local runtime configuration.
- `python pipeline.py` runs the full data preprocessing pipeline (crawl + classify).
- `python pipeline.py --skip-crawl` skips crawling and only runs classification.
- `pytest apps/ubereats-local-web/tests/` runs all tests (20 tests).

## Coding Style & Naming Conventions
- Python: follow PEP 8, 4-space indentation, `snake_case` for functions/variables, `UPPER_SNAKE_CASE` for constants.
- Prefer descriptive filenames and avoid abbreviations (e.g., `classify_stores`, not `cls_stores`).

## Testing Guidelines
- All tests live under `apps/ubereats-local-web/tests/` using `test_*.py` naming.
- External dependencies (Playwright, Gemini API) are always mocked in tests.
- Use `tmp_path` for file I/O tests to avoid polluting `dataset/`.
- Use `importlib` dynamic loading for module fixtures to avoid import-time side effects.

## Commit & Pull Request Guidelines
- Follow concise, imperative commit subjects (e.g., "Rewrite crawler for JSON output").
- Keep commits scoped (one logical change per commit) and include context in the body when behavior changes.
- PRs should include: summary, affected paths, and verification steps.

## Security & Configuration Tips
- Keep secrets (`GEMINI_API_KEY`) and machine-specific settings in `.env`; never commit filled `.env` files.
- JSON files in `dataset/` are local runtime state, not source-controlled artifacts.
