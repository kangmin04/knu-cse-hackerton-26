# KNU CSE Hackathon 2026

Team repository for the Kyungpook National University School of Computer Science and Engineering hackathon (development period until 2026-11-24 12:00). Theme: services that CSE students need.

## Structure
- `experiments/`, `samples/` — Experiment scripts and samples. Work on them **only on the test branch**; do not push them to main. Not subject to lint.
- `.venv/` — Local virtual environment (never commit)

## Development Commands
- Dependencies: use `uv` (`uv venv`, `uv pip install ...`)
- Lint: `uvx ruff check .`
- Format: `uvx ruff format .`
- A hook runs ruff automatically whenever a `.py` file is edited (except in experiments)

## Collaboration Rules
- Do not push directly to main. Branch → PR → merge after review. The user merges themselves.
- Branch names: `feat/…`, `fix/…`, `docs/…`
- Commit and PR titles follow conventional commit: `feat:`, `fix:`, `docs:`, `test:`, `chore:`, `ci:`, `refactor:`
- Never commit `.env` or API keys. List only the variable names in `.env.example`.

## Code Style
- Python 3.11, line length 100, configured in `pyproject.toml`
- Comments and documentation are written in Korean
