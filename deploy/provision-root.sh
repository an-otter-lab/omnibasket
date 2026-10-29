#!/usr/bin/env bash
# Privileged one-time setup for the Omnibasket demo VM. Idempotent; run with sudo.
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive
SRC=/tmp/omnibasket-provision

# Ports 80/443: Oracle's Ubuntu image rejects everything but 22, so insert before the REJECT rule and persist.
for p in 80 443; do
  iptables -C INPUT -p tcp -m state --state NEW -m tcp --dport $p -j ACCEPT 2>/dev/null \
    || iptables -I INPUT 5 -p tcp -m state --state NEW -m tcp --dport $p -j ACCEPT
done
apt-get update -q
apt-get install -y -q iptables-persistent >/dev/null
netfilter-persistent save

# Packages: Python, Node (Ubuntu's 18.19 is enough for Angular 19), git, Caddy from its official repo.
apt-get install -y -q python3-venv python3-pip nodejs npm git debian-keyring debian-archive-keyring apt-transport-https curl >/dev/null
if ! command -v caddy >/dev/null; then
  curl -1sLf https://dl.cloudsmith.io/public/caddy/stable/gpg.key | gpg --dearmor --yes -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
  curl -1sLf https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt > /etc/apt/sources.list.d/caddy-stable.list
  apt-get update -q && apt-get install -y -q caddy >/dev/null
fi

# App user owning /opt/omnibasket. Orion logs in as this user (same Mac key as ubuntu), so it never needs sudo.
id omnibasket >/dev/null 2>&1 || useradd --system --create-home --home-dir /opt/omnibasket --shell /bin/bash omnibasket
install -d -o omnibasket -g omnibasket -m 700 /opt/omnibasket/.ssh
install -o omnibasket -g omnibasket -m 600 $SRC/mac_key.pub /opt/omnibasket/.ssh/authorized_keys
# Read-only GitHub deploy key, generated here; only the public half leaves the VM.
[ -f /opt/omnibasket/.ssh/id_ed25519 ] || sudo -u omnibasket ssh-keygen -q -t ed25519 -N '' -C omnibasket-vm-deploy -f /opt/omnibasket/.ssh/id_ed25519
sudo -u omnibasket bash -c 'grep -q github.com ~/.ssh/known_hosts 2>/dev/null || ssh-keyscan -t ed25519 github.com >> ~/.ssh/known_hosts 2>/dev/null'

# The deploy script restarts the service; allow exactly that and nothing else.
cat > /etc/sudoers.d/omnibasket <<'S'
omnibasket ALL=(root) NOPASSWD: /usr/bin/systemctl restart omnibasket, /usr/bin/systemctl is-active --quiet omnibasket, /usr/bin/systemctl reload caddy
S
chmod 440 /etc/sudoers.d/omnibasket && visudo -cf /etc/sudoers.d/omnibasket

# Service and proxy config from feat/g1-vm-deploy.
install -m 644 $SRC/omnibasket.service /etc/systemd/system/omnibasket.service
install -m 644 $SRC/Caddyfile /etc/caddy/Caddyfile
systemctl daemon-reload
systemctl enable omnibasket caddy >/dev/null 2>&1

# Chromium system libraries for Playwright's later live reads (the browser itself installs per user).
npx -y playwright@1.49.1 install-deps chromium >/dev/null 2>&1 || echo "WARN: playwright install-deps failed"

echo "--- done"; iptables -S INPUT | grep -E 'dport (80|443)'; caddy version; node --version; python3 --version
