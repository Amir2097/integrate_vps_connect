#!/usr/bin/env bash
# Вызовы от root через sudo (одна строка в sudoers). Читает/пишет wg0.conf и удаляет .conf клиентов.
# Установка: sudo cp scripts/wg-backend-helper.sh /usr/local/bin/ && sudo chmod +x /usr/local/bin/wg-backend-helper.sh
# Sudoers: amir ALL=(root) NOPASSWD: /usr/local/bin/wg-backend-helper.sh
set -euo pipefail

WG_CONF="${WG_CONF:-/etc/wireguard/wg0.conf}"
WG_INTERFACE="${WG_INTERFACE:-wg0}"
WG_CLIENTS_DIR="${WG_CLIENTS_DIR:-/etc/wireguard/clients}"

die() { echo "[wg-backend-helper] $*" >&2; exit 1; }

case "${1:-}" in
  revoke-peer)
    PUBKEY="${2:-}"
    [ -n "$PUBKEY" ] || die "usage: $0 revoke-peer <client_public_key>"
    wg set "$WG_INTERFACE" peer "$PUBKEY" remove 2>/dev/null || true
    export PUBKEY WG_CONF
    python3 <<'PY'
import os
pubkey = os.environ["PUBKEY"].strip()
path = os.environ["WG_CONF"]
with open(path, encoding="utf-8", errors="replace") as f:
    text = f.read()
lines = text.splitlines()
out = []
i = 0
while i < len(lines):
    if lines[i].strip() == "[Peer]":
        block = [lines[i]]
        i += 1
        while i < len(lines) and not lines[i].strip().startswith("["):
            block.append(lines[i])
            i += 1
        block_pk = None
        for ln in block:
            s = ln.strip()
            if s.startswith("PublicKey"):
                _, _, v = s.partition("=")
                block_pk = v.strip()
                break
        if block_pk != pubkey:
            out.extend(block)
    else:
        out.append(lines[i])
        i += 1
new_text = "\n".join(out)
if text.endswith("\n"):
    if new_text and not new_text.endswith("\n"):
        new_text += "\n"
    elif not new_text:
        new_text = "\n"
with open(path, "w", encoding="utf-8") as f:
    f.write(new_text)
PY
    wg syncconf "$WG_INTERFACE" < <(wg-quick strip "$WG_INTERFACE")
    ;;
  rm-client-conf)
    NAME="${2:-}"
    [[ "$NAME" =~ ^[a-zA-Z0-9_.-]+$ ]] || die "invalid client name"
    rm -f "$WG_CLIENTS_DIR/${NAME}.conf"
    ;;
  append-peer)
    PUBKEY="${2:-}"
    ALLOWED="${3:-}"
    [ -n "$PUBKEY" ] && [ -n "$ALLOWED" ] || die "usage: $0 append-peer <pubkey> <allowed_ip_or_cidr>"
    [[ "$ALLOWED" == */* ]] || ALLOWED="${ALLOWED}/32"
    export PUBKEY ALLOWED WG_CONF
    python3 <<'PY'
import os
pubkey = os.environ["PUBKEY"].strip()
allowed = os.environ["ALLOWED"].strip()
path = os.environ["WG_CONF"]
with open(path, encoding="utf-8", errors="replace") as f:
    text = f.read()
lines = text.splitlines()
for i, line in enumerate(lines):
    s = line.strip()
    if s.startswith("PublicKey"):
        _, _, v = s.partition("=")
        if v.strip() == pubkey:
            raise SystemExit(0)
peer_block = "\n[Peer]\n# restored\nPublicKey = %s\nAllowedIPs = %s\n" % (pubkey, allowed)
new_text = text.rstrip() + peer_block
with open(path, "w", encoding="utf-8") as f:
    f.write(new_text)
    if not new_text.endswith("\n"):
        f.write("\n")
PY
    wg syncconf "$WG_INTERFACE" < <(wg-quick strip "$WG_INTERFACE")
    ;;
  *)
    die "usage: $0 revoke-peer <pubkey> | rm-client-conf <name> | append-peer <pubkey> <allowed_ip>"
    ;;
esac
