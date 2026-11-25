#!/bin/bash
# Pult's gateway beside ComfyUI (stage M, step 6.7): install, update or remove it on the computer ComfyUI runs on —
# Linux, or WSL with systemd. Run as root from the Pult folder there (or with these three files copied anywhere):
#   sudo bash deploy/comfy-gate/install.sh --user NAME [options]
#   sudo bash deploy/comfy-gate/install.sh --remove
# Options (each kept from the last install when not given again):
#   --user NAME          who runs it — the owner of ComfyUI's folders (required the first time)
#   --comfy DIR          ComfyUI's program — the folder with main.py (default: ~NAME/llm/comfyui/current)
#   --python PATH        the Python with ComfyUI's libraries (default: DIR/../venv/bin/python, else DIR/venv/bin/python)
#   --base DIR           ComfyUI's --base-directory: models/, output/ (default: ~NAME/llm/comfyui/data when it is there,
#                        else none — the models in DIR/models)
#   --port N             the gateway's port on 127.0.0.1 (default 8190)
#   --keep GB            the disk keeps this much free after a download (default 60)
#   --cap GB             all models together, at most — ComfyUI's, Ollama's and --also's (default: none)
#   --also DIR[:DIR]     more models' folders that count under the cap (llama.cpp's, say)
#   --replace UNIT       stop and disable a service that holds the same port (the gateway this one grew from, say)
# What it does: /usr/local/lib/pult-comfy-gate/ (comfy_gate.py and sets.json, the verified list), its settings in
# /etc/default/pult-comfy-gate, the service pult-comfy-gate — 127.0.0.1 only, this computer; reach it through the ssh
# tunnel to Pult's computer as Ollama's port goes (-L 127.0.0.1:8190:127.0.0.1:8190). Safe to re-run: it updates the
# gateway and its list and keeps the rest. A new list in Pult reaches the server only this way.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
LIB=/usr/local/lib/pult-comfy-gate
UNIT=/etc/systemd/system/pult-comfy-gate.service
CONF=/etc/default/pult-comfy-gate
WHO="" COMFY="" PY="" BASE="" PORT="" KEEP="" CAP="" ALSO="" REPLACE="" REMOVE=0
while [ $# -gt 0 ]; do
  case "$1" in
    --user) WHO="${2:-}"; shift 2 ;;
    --comfy) COMFY="${2:-}"; shift 2 ;;
    --python) PY="${2:-}"; shift 2 ;;
    --base) BASE="${2:-}"; shift 2 ;;
    --port) PORT="${2:-}"; shift 2 ;;
    --keep) KEEP="${2:-}"; shift 2 ;;
    --cap) CAP="${2:-}"; shift 2 ;;
    --also) ALSO="${2:-}"; shift 2 ;;
    --replace) REPLACE="${2:-}"; shift 2 ;;
    --remove) REMOVE=1; shift ;;
    *) echo "Unknown option $1 — see the top of $0"; exit 2 ;;
  esac
done
[ "$(id -u)" = 0 ] || { echo "Run it as root: sudo bash $0 $*"; exit 1; }
command -v systemctl >/dev/null || { echo "This needs systemd (in WSL: [boot] systemd=true in /etc/wsl.conf)."; exit 1; }

if [ "$REMOVE" = 1 ]; then
  systemctl disable --now pult-comfy-gate 2>/dev/null || true
  rm -f "$UNIT" "$CONF"
  rm -rf "$LIB"
  systemctl daemon-reload
  echo "Removed: the gateway, its service and its settings. ComfyUI's models stay where they are."
  exit 0
fi

# what the last install said, for each option not given now
if [ -f "$CONF" ]; then
  was() { sed -n "s/^$1=//p" "$CONF" | head -1; }
  WHO=${WHO:-$(sed -n 's/^# user=//p' "$CONF" | head -1)}
  COMFY=${COMFY:-$(was COMFY_DIR)}; PY=${PY:-$(was COMFY_PY)}; BASE=${BASE:-$(was COMFY_BASE)}
  PORT=${PORT:-$(was GATE_PORT)}; KEEP=${KEEP:-$(was GATE_KEEP_GB)}; CAP=${CAP:-$(was GATE_CAP_GB)}
  ALSO=${ALSO:-$(was GATE_ALSO)}
fi
[ -n "$WHO" ] || { echo "Who runs it? --user NAME (the owner of ComfyUI's folders)"; exit 2; }
id "$WHO" >/dev/null 2>&1 || { echo "No user $WHO here."; exit 1; }
H=$(getent passwd "$WHO" | cut -d: -f6)
COMFY=${COMFY:-$H/llm/comfyui/current}
[ -f "$COMFY/main.py" ] || { echo "No ComfyUI in $COMFY (main.py) — --comfy DIR"; exit 1; }
if [ -z "$PY" ]; then
  for c in "$COMFY/../venv/bin/python" "$COMFY/venv/bin/python"; do [ -x "$c" ] && { PY=$(cd "$(dirname "$c")" && pwd)/python; break; }; done
fi
[ -n "$PY" ] && [ -x "$PY" ] || { echo "No Python for ComfyUI — --python PATH"; exit 1; }
if [ -z "$BASE" ] && [ -d "$H/llm/comfyui/data/models" ]; then BASE=$H/llm/comfyui/data; fi
PORT=${PORT:-8190}; KEEP=${KEEP:-60}; CAP=${CAP:-0}
case "$PORT" in ''|*[!0-9]*) echo "The port is a number: --port 8190"; exit 2 ;; esac
case "$KEEP$CAP" in *[!0-9.]*) echo "--keep and --cap are gigabytes: --keep 60 --cap 65"; exit 2 ;; esac
for v in "$COMFY" "$PY" "$BASE" "$ALSO"; do
  case "$v" in *[!A-Za-z0-9._/:~-]*) echo "A path with odd characters: $v"; exit 2 ;; esac
done
command -v python3 >/dev/null || { echo "This needs python3."; exit 1; }
python3 -I "$HERE/comfy_gate.py" --check >/dev/null || { echo "The list $HERE/sets.json doesn't pass the gateway's check."; exit 1; }

if [ -n "$REPLACE" ]; then
  case "$REPLACE" in *[!A-Za-z0-9@._-]*) echo "--replace takes a service's name"; exit 2 ;; esac
  if systemctl list-unit-files "$REPLACE.service" >/dev/null 2>&1 && systemctl cat "$REPLACE.service" >/dev/null 2>&1; then
    systemctl disable --now "$REPLACE" >/dev/null 2>&1 || true
    echo "Stopped and disabled $REPLACE (its files stay; sudo systemctl enable --now $REPLACE brings it back)."
  fi
fi
if ss -ltnH "sport = :$PORT" 2>/dev/null | grep -q . && ! systemctl is-active --quiet pult-comfy-gate; then
  echo "Port $PORT is taken by something else — --replace UNIT, or --port N."
  exit 1
fi

install -d -m 755 "$LIB"
install -m 644 "$HERE/comfy_gate.py" "$LIB/comfy_gate.py"
install -m 644 "$HERE/sets.json" "$LIB/sets.json"
cat > "$CONF" <<EOF
# Pult's gateway beside ComfyUI — written by deploy/comfy-gate/install.sh; re-run it to change
# user=$WHO
COMFY_DIR=$COMFY
COMFY_PY=$PY
COMFY_BASE=$BASE
GATE_PORT=$PORT
GATE_KEEP_GB=$KEEP
GATE_CAP_GB=$CAP
GATE_ALSO=$ALSO
GATE_STATE=$H/.local/state/pult-comfy-gate
EOF
chmod 644 "$CONF"
cat > "$UNIT" <<EOF
# Pult's gateway beside ComfyUI: pictures and music, the models from Pult's verified list; ComfyUI only while there is
# work. Installed by deploy/comfy-gate/install.sh from Pult.
[Unit]
Description=Pult's gateway beside ComfyUI, 127.0.0.1:$PORT
After=network-online.target ollama.service
Wants=network-online.target

[Service]
User=$WHO
WorkingDirectory=$H
EnvironmentFile=$CONF
ExecStart=/usr/bin/python3 -I $LIB/comfy_gate.py
Restart=on-failure
RestartSec=10
# The neighbours: last in the queue for the processor and the disk; the first to go when memory runs out — not Ollama
Nice=10
IOSchedulingClass=best-effort
IOSchedulingPriority=7
MemoryHigh=7G
MemoryMax=8G
OOMScoreAdjust=500
TimeoutStopSec=60

[Install]
WantedBy=multi-user.target
EOF
systemctl daemon-reload
systemctl enable pult-comfy-gate >/dev/null 2>&1
systemctl restart pult-comfy-gate
for _ in $(seq 1 20); do
  if out=$(python3 -I - "$PORT" <<'PY'
import json, sys, urllib.request
o = urllib.request.build_opener(urllib.request.ProxyHandler({}))
d = json.loads(o.open("http://127.0.0.1:%s/models" % sys.argv[1], timeout=5).read())
have = [s["name"] for s in d["sets"] if s["ready"]]
print("v%d, ComfyUI %s; on the disk: %s; the disk %s free" % (d["v"], d["comfy"]["version"] or "?", ", ".join(have) or "none",
      "%.0f GB" % (d["disk"]["free"] / 1e9) if d.get("disk") else "?"))
PY
  ); then
    echo "The gateway answers on 127.0.0.1:$PORT — $out"
    exit 0
  fi
  sleep 1
done
echo "The gateway doesn't answer on 127.0.0.1:$PORT. Its journal: journalctl -u pult-comfy-gate -n 30" >&2
exit 1
