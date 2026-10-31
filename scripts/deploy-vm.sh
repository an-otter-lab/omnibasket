#!/usr/bin/env bash
set -euo pipefail
# From the Mac: copy the search index (gitignored, about 240 MB) when the Mac's copy is newer, then run this
# same script on the VM. The VM's META_API_KEY comes from /etc/omnibasket/env, never from here (D3).
if [ "$(uname)" = "Darwin" ]; then
  VM="${VM:-omnibasket@vm.example.com}"
  KEY="${KEY:-$HOME/.config/omnibasket/omnibasket_oci}"
  ROOT="$(cd "$(dirname "$0")/.." && pwd)"
  ssh -i "$KEY" "$VM" mkdir -p /opt/omnibasket/data/index
  rsync -u --partial -e "ssh -i $KEY" "$ROOT/data/index/books.sqlite3" "$VM:/opt/omnibasket/data/index/"
  exec ssh -i "$KEY" "$VM" "cd /opt/omnibasket && git fetch -q origin main && git checkout -q main && git pull -q --ff-only origin main && scripts/deploy-vm.sh"
fi
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
