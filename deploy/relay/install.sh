#!/bin/bash
# Pult relay: install or update on a Linux server with systemd. Run as root from the Pult folder:
#   sudo bash deploy/relay/install.sh
# What it does: a system user `pult`, /opt/pult-relay (relay.py, web/, a Python environment), the pult-relay
# service on 127.0.0.1:8097. The web server (nginx or Caddy) and HTTPS stay yours — deploy/relay/README.md.
# Safe to re-run; an existing .env is never overwritten.
set -euo pipefail
SRC="$(cd "$(dirname "$0")/../.." && pwd)"
D=/opt/pult-relay

[ "$(id -u)" = 0 ] || { echo "Run it as root: sudo bash $0"; exit 1; }
command -v systemctl >/dev/null || { echo "This script needs systemd."; exit 1; }
PY=$(command -v python3) || { echo "python3 (3.10+) is needed — Debian/Ubuntu: apt install python3 python3-venv"; exit 1; }
"$PY" -c 'import sys; sys.exit(sys.version_info < (3, 10))' || { echo "Python 3.10+ is needed, found $("$PY" -V)"; exit 1; }

id pult >/dev/null 2>&1 || useradd --system --home-dir "$D" --shell /usr/sbin/nologin pult
mkdir -p "$D"
cp "$SRC/relay/relay.py" "$SRC/relay/requirements.txt" "$D/"
rm -rf "$D/web"
cp -r "$SRC/relay/web" "$D/web"
[ -x "$D/venv/bin/python" ] || "$PY" -m venv "$D/venv"        # Debian/Ubuntu need python3-venv for this
"$D/venv/bin/pip" install -q --disable-pip-version-check -r "$D/requirements.txt"

if [ ! -f "$D/.env" ]; then
  (umask 077; cat > "$D/.env" <<'EOF'
# The three lines `pult app` prints on the Mac:
PULT_RELAY_SECRET=
PULT_OWNER_ID=
PULT_BOT_ID=
EOF
  )
fi
chown -R pult: "$D"
chmod 600 "$D/.env"

install -m 644 "$SRC/deploy/relay/pult-relay.service" /etc/systemd/system/pult-relay.service
systemctl daemon-reload
systemctl enable pult-relay >/dev/null 2>&1

if grep -q '^PULT_RELAY_SECRET=.' "$D/.env"; then
  systemctl restart pult-relay
  sleep 2
  systemctl is-active pult-relay
  curl -s --max-time 5 http://127.0.0.1:8097/pult/healthz; echo
else
  echo "Installed. Now put the three lines from \`pult app\` into $D/.env, then: systemctl restart pult-relay"
fi
