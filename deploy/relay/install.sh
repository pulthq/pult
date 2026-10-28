#!/bin/bash
# Pult relay: install or update on a Linux server with systemd. Run as root from the Pult folder:
#   sudo bash deploy/relay/install.sh             # install, or update by hand from this folder
#   sudo bash deploy/relay/install.sh --auto      # the same, and from now on the server updates itself
#   sudo bash deploy/relay/install.sh --no-auto   # back to updating by hand
# What it does: a system user `pult` (the relay); /opt/pult-relay — the release in app/releases/, app/current pointing
# at it, a Python environment, .env with the secret (root, 600: systemd reads it, the relay never does); the
# pult-relay service on the socket /run/pult-relay/relay.sock — the web server's user joins the group pult to reach it
# (an install from before 0.18.7 keeps its port 127.0.0.1:8097). The web server (nginx or Caddy) and HTTPS stay
# yours — deploy/relay/README.md.
# --auto (stage U3): once the computer has installed a new release, this server takes the same one — from GitHub,
# never from the computer — under an account of its own, `pult-update`, which owns the relay's code and nothing else
# (update.py). Safe to re-run; an existing .env is never overwritten; a re-run keeps the updater on or off as it was.
set -euo pipefail
umask 022                      # the relay reads what root puts here, the Python environment too
SRC="$(cd "$(dirname "$0")/../.." && pwd)"
D=/opt/pult-relay
U=/var/lib/pult-relay-update
SD=/etc/systemd/system
UNITS="pult-relay-update.service pult-relay-update.path pult-relay-restart.service pult-relay-restart.path"
mode=keep
case "${1:-}" in
  --auto) mode=on ;;
  --no-auto) mode=off ;;
  "") ;;
  *) echo "Unknown option $1 — use --auto or --no-auto"; exit 2 ;;
esac

[ "$(id -u)" = 0 ] || { echo "Run it as root: sudo bash $0 ${1:-}"; exit 1; }
command -v systemctl >/dev/null || { echo "This script needs systemd."; exit 1; }
PY=$(command -v python3) || { echo "python3 (3.10+) is needed — Debian/Ubuntu: apt install python3 python3-venv"; exit 1; }
"$PY" -c 'import sys; sys.exit(sys.version_info < (3, 10))' || { echo "Python 3.10+ is needed, found $("$PY" -V)"; exit 1; }
if [ $mode = keep ]; then
  if systemctl is-enabled --quiet pult-relay-update.path 2>/dev/null; then mode=on; else mode=off; fi
fi
if [ $mode = on ]; then
  command -v git >/dev/null || { echo "The updater needs git — Debian/Ubuntu: apt install git"; exit 1; }
fi

# the release this folder holds: Pult's version, and the commit when it is a git checkout
VER=$(sed -n 's/^VERSION = "\(.*\)"$/\1/p' "$SRC/src/pultd.py" | head -1)
[ -n "$VER" ] || { echo "No Pult version in $SRC/src/pultd.py — run this from the Pult folder"; exit 1; }
COMMIT=$(git -C "$SRC" rev-parse HEAD 2>/dev/null || true)
NAME="v$VER-${COMMIT:0:7}"
[ -n "$COMMIT" ] || NAME="v$VER-local"
OWNER=root
[ $mode = on ] && OWNER=pult-update

getent group pult >/dev/null || groupadd --system pult
id pult >/dev/null 2>&1 || useradd --system --gid pult --home-dir /nonexistent --no-create-home --shell /usr/sbin/nologin pult
if [ $mode = on ]; then
  id pult-update >/dev/null 2>&1 || useradd --system --user-group --home-dir "$U" --no-create-home \
    --shell /usr/sbin/nologin pult-update
  install -d -o pult-update -g pult-update -m 755 "$U"
  [ -e "$U/lock" ] || install -o pult-update -g pult-update -m 644 /dev/null "$U/lock"
  exec 9>>"$U/lock"
  flock -w 900 9 || { echo "The updater is busy for 15 min — try again later"; exit 1; }   # not both at once
fi

# ---------- the release ----------
install -d -o root -g root -m 755 "$D"
install -d -m 755 "$D/app" "$D/app/releases"
R="$D/app/releases/$NAME"
prev=$(readlink -f "$D/app/current" 2>/dev/null || true)
rm -rf "$R.new"
mkdir "$R.new"
cp "$SRC/relay/relay.py" "$SRC/relay/requirements.txt" "$R.new/"
cp -r "$SRC/relay/web" "$R.new/web"
find "$R.new" \( -name __pycache__ -o -name .DS_Store \) -prune -exec rm -rf {} +
[ "$prev" = "$R" ] && prev=""
rm -rf "$R"
mv "$R.new" "$R"
[ -x "$D/venv/bin/python" ] || "$PY" -m venv "$D/venv"        # Debian/Ubuntu need python3-venv for this
"$D/venv/bin/pip" install -q --disable-pip-version-check --require-hashes -r "$R/requirements.txt"
ln -sfn "releases/$NAME" "$D/app/.current.new"
mv -T "$D/app/.current.new" "$D/app/current"
# before Pult 0.18 the release lay right in /opt/pult-relay
rm -rf "$D/relay.py" "$D/requirements.txt" "$D/web" "$D/__pycache__"
# releases: the one that runs and the one before it stay
for r in "$D"/app/releases/*; do
  [ -d "$r" ] || continue
  [ "$(readlink -f "$r")" = "$R" ] || [ "$(readlink -f "$r")" = "$prev" ] || rm -rf "$r"
done
chown -R "$OWNER:$OWNER" "$D/app" "$D/venv"
chmod -R u=rwX,go=rX "$D/app"

if [ ! -f "$D/.env" ]; then
  (umask 077; cat > "$D/.env" <<'EOF'
# The three lines `pult app` prints on the computer:
PULT_RELAY_SECRET=
PULT_OWNER_ID=
PULT_BOT_ID=
# where the relay listens: a socket only it and the web server can enter (remove the line for 127.0.0.1:8097)
PULT_RELAY_SOCKET=/run/pult-relay/relay.sock
EOF
  )
fi
chown root:root "$D/.env"
chmod 600 "$D/.env"

# ---------- systemd ----------
install -m 644 "$SRC/deploy/relay/pult-relay.service" "$SD/pult-relay.service"
sock=$(sed -n 's/^PULT_RELAY_SOCKET=//p' "$D/.env" | tail -1 | tr -d "\"'")
port=$(sed -n 's/^PULT_RELAY_PORT=//p' "$D/.env" | tail -1 | tr -d "\"'")
if [ -n "$sock" ]; then HEALTH="unix:$sock"; else HEALTH="http://127.0.0.1:${port:-8097}/pult/healthz"; fi
# on the socket: the web server's user joins the group pult — /run/pult-relay lets in only the relay and that group
web=""
if [ -n "$sock" ]; then
  for w in www-data caddy nginx http; do
    id "$w" >/dev/null 2>&1 || continue
    case " $(id -nG "$w") " in
      *" pult "*) ;;
      *) usermod -aG pult "$w"; web="$web $w" ;;
    esac
  done
fi
if [ $mode = on ]; then
  install -d -m 755 /usr/local/lib/pult-relay "$SD/pult-relay.service.d" "$SD/pult-relay-update.service.d"
  install -m 755 "$SRC/deploy/relay/update.py" /usr/local/lib/pult-relay/update.py
  for u in $UNITS; do install -m 644 "$SRC/deploy/relay/$u" "$SD/$u"; done
  install -m 644 "$SRC/deploy/relay/pult-relay-update.conf" "$SD/pult-relay.service.d/update.conf"
  printf '[Service]\nEnvironment=PULT_UPDATE_HEALTH=%s\n' "$HEALTH" > "$SD/pult-relay-update.service.d/health.conf"
  # what runs here now: the updater never puts an older release in; a release that failed may be tried again
  printf '{"tag": "v%s", "commit": "%s", "ts": %s}\n' "$VER" "$COMMIT" "$(date +%s)" > "$U/installed.json"
  chown pult-update:pult-update "$U/installed.json"
  rm -f "$U/failed.json"
else
  systemctl disable --now pult-relay-update.path pult-relay-restart.path >/dev/null 2>&1 || true
  for u in $UNITS; do rm -f "$SD/$u"; done
  rm -f "$SD/pult-relay.service.d/update.conf" "$SD/pult-relay-update.service.d/health.conf"
fi
systemctl daemon-reload
systemctl enable pult-relay >/dev/null 2>&1
[ $mode = on ] && systemctl enable --now pult-relay-update.path pult-relay-restart.path >/dev/null 2>&1

if grep -q '^PULT_RELAY_SECRET=.' "$D/.env"; then
  systemctl restart pult-relay
  sleep 2
  systemctl is-active pult-relay
  if [ -n "$sock" ]; then curl -s --max-time 5 --unix-socket "$sock" http://relay/pult/healthz
  else curl -s --max-time 5 "$HEALTH"; fi
  echo
else
  echo "Installed. Now put the three lines from \`pult app\` into $D/.env, then: systemctl restart pult-relay"
fi
[ -n "$web" ] && echo "Added to the group pult:$web — reload the web server, so that it reaches $sock."
# the updater's report names the updater and services that run here: the ones just put in, at once — not at the next
# release (it waits for the lock this script holds to its end)
if [ $mode = on ]; then systemctl start --no-block pult-relay-update.service || true; fi
if [ $mode = on ]; then
  echo "Pult $VER. From now on this server takes each release your computer installs, from GitHub (journalctl -u pult-relay-update)."
else
  echo "Pult $VER. To have this server update itself after your computer: sudo bash $0 --auto"
fi
