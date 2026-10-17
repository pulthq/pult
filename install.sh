#!/bin/bash
# Pult: install or update on this Mac. Safe to re-run.
#   ./install.sh
# Code → ~/.local/share/pult/ (PULT_HOME), a Python environment with the Agent SDK, the `pult` command in ~/.local/bin,
# a launchd service. Then `pult install` takes over: in a terminal it starts the setup if Pult isn't set up yet.
# Python 3.10+ is looked for in Homebrew, python.org and PATH; PULT_PYTHON=/path/to/python3 picks one.
set -euo pipefail

SRC="$(cd "$(dirname "$0")" && pwd)"
DST="${PULT_HOME:-$HOME/.local/share/pult}"

ru() { defaults read -g AppleLanguages 2>/dev/null | sed -n 2p | grep -q '"ru'; }
say() { if ru; then echo "$2"; else echo "$1"; fi; }

if [ "$(uname)" != Darwin ]; then
  say "Pult runs on macOS for now; Linux and Windows are in progress." \
      "Пока Пульт работает только на macOS; Linux и Windows — в работе."
  exit 1
fi

good() { [ -x "$1" ] && "$1" -c 'import sys; sys.exit(not (3, 10) <= sys.version_info[:2] < (4, 0))' 2>/dev/null; }

find_python() {
  if [ -n "${PULT_PYTHON:-}" ]; then
    good "$PULT_PYTHON" && { echo "$PULT_PYTHON"; return 0; }
    return 1
  fi
  # 3.12 first: every dependency has ready-made wheels for it
  for v in 3.12 3.13 3.11 3.10 3.14; do
    for d in /opt/homebrew/bin /usr/local/bin "/Library/Frameworks/Python.framework/Versions/$v/bin"; do
      good "$d/python$v" && { echo "$d/python$v"; return 0; }
    done
    p=$(command -v "python$v" 2>/dev/null) && good "$p" && { echo "$p"; return 0; }
  done
  # not /usr/bin/python3: it is 3.9, and without the Command Line Tools running it opens an Xcode install dialog
  p=$(command -v python3 2>/dev/null) && [ "$p" != /usr/bin/python3 ] && good "$p" && { echo "$p"; return 0; }
  return 1
}

mkdir -p "$DST" "$HOME/Library/Logs"
chmod 700 "$DST"

if ! good "$DST/venv/bin/python"; then
  if ! PY=$(find_python); then
    say "Pult needs Python 3.10 or newer. Install it with Homebrew (https://brew.sh): brew install python@3.12 — then run ./install.sh again." \
        "Пульту нужен Python 3.10 или новее. Поставь через Homebrew (https://brew.sh): brew install python@3.12 — и снова ./install.sh."
    exit 1
  fi
  rm -rf "$DST/venv"                  # left over from a Python that is gone
  say "Python: $PY" "Python: $PY"
  "$PY" -m venv "$DST/venv"
fi

cp "$SRC"/src/pultd.py "$SRC"/src/pult_hook.py "$SRC"/src/pult_render.py "$SRC"/src/pult_web.py "$SRC"/src/pult_i18n.py \
   "$SRC"/src/pult_setup.py "$SRC"/src/pultctl.py "$SRC"/requirements.txt "$DST"/
# VS Code tab wrapper: takes effect only after the claudeCode.claudeProcessWrapper setting (pult tab setup)
cp "$SRC"/src/pult_tab.py "$SRC"/src/pult-tab.sh "$DST"/
chmod 755 "$DST"/pult_tab.py "$DST"/pult-tab.sh

say "Installing dependencies…" "Ставлю зависимости…"
"$DST/venv/bin/pip" install -q --disable-pip-version-check -r "$DST/requirements.txt"

exec "$DST/venv/bin/python" "$DST/pultctl.py" install
