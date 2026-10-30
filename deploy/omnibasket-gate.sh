#!/usr/bin/env bash
# Public gate for the Omnibasket VM (root only).
#   closed : no 80/443, Caddy off.
#   soon   : 80/443 open, Caddy serves only the static "Coming soon" page (default until go-live).
#   live   : 80/443 open, Caddy proxies to the app on 127.0.0.1:8000 (go-live day, Adrian's call).
set -euo pipefail
mode="${1:-status}"
rule() { iptables "$1" INPUT -p tcp -m state --state NEW -m tcp --dport "$2" -j ACCEPT; }
ports_open() {
  for p in 80 443; do rule -C $p 2>/dev/null || iptables -I INPUT 5 -p tcp -m state --state NEW -m tcp --dport $p -j ACCEPT; done
  netfilter-persistent save >/dev/null 2>&1
}
use_caddyfile() {
  install -m 644 "$1" /etc/caddy/Caddyfile
  caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile >/dev/null
  systemctl enable caddy >/dev/null 2>&1
  systemctl is-active --quiet caddy && systemctl reload caddy || systemctl start caddy
}
case "$mode" in
  closed)
    for p in 80 443; do while rule -C $p 2>/dev/null; do rule -D $p; done; done
    netfilter-persistent save >/dev/null 2>&1
    systemctl disable --now caddy >/dev/null 2>&1 ;;
  soon) ports_open; use_caddyfile /etc/caddy/Caddyfile.soon ;;
  live) ports_open; use_caddyfile /etc/caddy/Caddyfile.live ;;
  status) ;;
  *) echo "usage: omnibasket-gate closed|soon|live|status" >&2; exit 2 ;;
esac
echo "caddy: $(systemctl is-active caddy || true)  omnibasket: $(systemctl is-active omnibasket || true)"
cmp -s /etc/caddy/Caddyfile /etc/caddy/Caddyfile.soon && echo "site: coming-soon page" || { cmp -s /etc/caddy/Caddyfile /etc/caddy/Caddyfile.live && echo "site: live app"; } || true
iptables -S INPUT | grep -E 'dport (80|443)' || echo "80/443: closed in iptables"
