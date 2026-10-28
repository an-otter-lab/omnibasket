#!/usr/bin/env bash
# One command for a fresh clone: install, seed the page cache, build the UI, serve API + UI.
set -euo pipefail
cd "$(dirname "$0")/.."

if ! command -v uv >/dev/null 2>&1; then
  echo "uv is required (https://docs.astral.sh/uv/)." >&2
  exit 1
fi
if ! command -v npm >/dev/null 2>&1; then
  echo "npm is required to build the UI." >&2
  exit 1
fi

if [[ ! -d .venv ]]; then
  uv venv --python 3.12 .venv
fi
uv pip install --python .venv/bin/python -r requirements.txt

(cd ui && npm ci && npm run build)

PYTHONPATH=. .venv/bin/python scripts/seed_cache.py
exec .venv/bin/python -m uvicorn api.app:app --app-dir . --host 127.0.0.1 --port 8000
