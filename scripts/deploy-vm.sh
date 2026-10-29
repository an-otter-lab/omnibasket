#!/usr/bin/env bash
set -euo pipefail
APP_DIR="${APP_DIR:-/opt/omnibasket}"
SERVICE="${SERVICE:-omnibasket}"
cd "$APP_DIR"
git fetch origin main
git checkout main
git pull --ff-only origin main
python3 -m venv --upgrade .venv
.venv/bin/pip install --disable-pip-version-check -r requirements.txt
(cd ui && npm ci && npm run build)
PYTHONPATH=. .venv/bin/python scripts/seed_cache.py
sudo systemctl restart "$SERVICE"
sudo systemctl is-active --quiet "$SERVICE"
echo "Deployed $(git rev-parse --short HEAD)"
