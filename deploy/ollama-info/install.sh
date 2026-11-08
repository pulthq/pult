#!/bin/bash
# Pult's reader beside Ollama (stage M, step 6.4): install, update or remove it on the computer Ollama runs on — Linux,
# or WSL with systemd. Run as root from the Pult folder there:
#   sudo bash deploy/ollama-info/install.sh [--name homelab] [--port 11436]
#   sudo bash deploy/ollama-info/install.sh --remove
# What it does: /usr/local/lib/pult-ollama-info/ollama-info.py (the reader, Python's standard library only), the socket
# ollama-info.socket on 127.0.0.1:<port> — this computer only — and ollama-info@.service, which systemd starts for each
# connection: one JSON answer (the disk's room, the card's memory), then it exits; nothing stays in memory between
# requests. It runs as Ollama's own user (`ollama`, when there is one; else a user systemd makes for the moment).
# Then forward the port to Pult's computer the way Ollama's port goes — the same ssh tunnel with one more -L
# 127.0.0.1:11436:127.0.0.1:11436. Safe to re-run: it updates the reader and keeps the rest.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
LIB=/usr/local/lib/pult-ollama-info
SD=/etc/systemd/system
CONF=/etc/default/pult-ollama-info
NAME=""
PORT=11436
REMOVE=0
while [ $# -gt 0 ]; do
  case "$1" in
    --name) NAME="${2:-}"; shift 2 ;;
    --port) PORT="${2:-}"; shift 2 ;;
    --remove) REMOVE=1; shift ;;
    *) echo "Unknown option $1 — use --name NAME, --port PORT or --remove"; exit 2 ;;
  esac
done
[ "$(id -u)" = 0 ] || { echo "Run it as root: sudo bash $0 $*"; exit 1; }
command -v systemctl >/dev/null || { echo "This needs systemd (in WSL: [boot] systemd=true in /etc/wsl.conf)."; exit 1; }
case "$PORT" in ''|*[!0-9]*) echo "The port is a number: --port 11436"; exit 2 ;; esac
case "$NAME" in *[!A-Za-z0-9._-]*) echo "The name: letters, digits, dot, dash, underscore"; exit 2 ;; esac

if [ "$REMOVE" = 1 ]; then
  systemctl disable --now ollama-info.socket 2>/dev/null || true
  rm -f "$SD/ollama-info.socket" "$SD/ollama-info@.service" "$CONF"
  rm -rf "$LIB"
  systemctl daemon-reload
  echo "Removed: the reader, its socket and its settings. Take its -L out of the tunnel too."
  exit 0
fi

command -v python3 >/dev/null || { echo "This needs python3."; exit 1; }
install -d -m 755 "$LIB"
install -m 755 "$HERE/ollama-info.py" "$LIB/ollama-info.py"
if [ -n "$NAME" ] || [ ! -f "$CONF" ]; then
  printf 'PULT_INFO_NAME=%s\n' "$NAME" > "$CONF"            # empty: the host's own name
  chmod 644 "$CONF"
fi
if id ollama >/dev/null 2>&1; then
  WHO="User=ollama"                                         # it reads Ollama's folder and the card, as Ollama does
else
  WHO="DynamicUser=yes"
fi
cat > "$SD/ollama-info.socket" <<UNIT
[Unit]
Description=Pult's reader beside Ollama: the disk's room and the card's memory, this computer only

[Socket]
ListenStream=127.0.0.1:$PORT
Accept=yes
MaxConnections=4

[Install]
WantedBy=sockets.target
UNIT
cat > "$SD/ollama-info@.service" <<UNIT
[Unit]
Description=Pult's reader beside Ollama: one answer
CollectMode=inactive-or-failed

[Service]
ExecStart=/usr/bin/python3 -I $LIB/ollama-info.py
StandardInput=socket
StandardOutput=socket
StandardError=journal
EnvironmentFile=-$CONF
$WHO
NoNewPrivileges=yes
ProtectSystem=strict
ProtectHome=read-only
PrivateTmp=yes
MemoryMax=64M
CPUQuota=50%
Nice=10
RuntimeMaxSec=20
UNIT
systemctl daemon-reload
systemctl enable ollama-info.socket >/dev/null 2>&1
systemctl restart ollama-info.socket
sleep 1
# the check: what Pult will read
if out=$(python3 -I - "$PORT" <<'PY'
import json, socket, sys
s = socket.create_connection(("127.0.0.1", int(sys.argv[1])), timeout=15)
s.sendall(b"GET / HTTP/1.0\r\n\r\n")
data = b""
while True:
    chunk = s.recv(65536)
    if not chunk:
        break
    data += chunk
d = json.loads(data.split(b"\r\n\r\n", 1)[1])
disk, gpu = d.get("disk") or {}, (d.get("gpu") or [{}])[0]
print("%s: disk %s — %.1f GB free of %.1f; card %s — %d MiB of %d taken" % (
    d.get("name"), disk.get("label", "?"), disk.get("free", 0) / 1e9, disk.get("total", 0) / 1e9,
    gpu.get("name", "none"), gpu.get("used", 0) // 1048576, gpu.get("total", 0) // 1048576))
PY
); then
  echo "The reader answers on 127.0.0.1:$PORT — $out"
else
  echo "The reader doesn't answer on 127.0.0.1:$PORT. Its journal: journalctl -u 'ollama-info@*' -n 20" >&2
  exit 1
fi
