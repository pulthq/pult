#!/bin/bash
# Pult: install or update on this computer (macOS or Linux). Safe to re-run.
#   ./install.sh
# Code → ~/.local/share/pult/ (PULT_HOME), a Python environment with the Agent SDK, the `pult` command in ~/.local/bin,
# a service (launchd on macOS, systemd --user on Linux). Then `pult install` takes over: in a terminal it starts the
# setup if Pult isn't set up yet.
# Python 3.10+ is looked for in Homebrew, python.org and PATH; PULT_PYTHON=/path/to/python3 picks one.
set -euo pipefail

SRC="$(cd "$(dirname "$0")" && pwd)"
DST="${PULT_HOME:-$HOME/.local/share/pult}"
OS="$(uname)"

ru() {
  if [ "$OS" = Darwin ]; then
    defaults read -g AppleLanguages 2>/dev/null | sed -n 2p | grep -q '"ru'
  else
    # the order gettext reads them in; C and POSIX say nothing about the language
    local v="${LANGUAGE:-}"; v="${v%%:*}"
    for x in "$v" "${LC_ALL:-}" "${LC_MESSAGES:-}" "${LANG:-}"; do
      case "$x" in ""|C|C.*|POSIX) continue ;; ru*) return 0 ;; *) return 1 ;; esac
    done
    return 1
  fi
}
say() { if ru; then echo "$2"; else echo "$1"; fi; }

if [ "$OS" != Darwin ] && [ "$OS" != Linux ]; then
  say "Pult runs on macOS and Linux for now; Windows is in progress." \
      "Пока Пульт работает на macOS и Linux; Windows — в работе."
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
    if [ "$OS" = Darwin ]; then
      for d in /opt/homebrew/bin /usr/local/bin "/Library/Frameworks/Python.framework/Versions/$v/bin"; do
        good "$d/python$v" && { echo "$d/python$v"; return 0; }
      done
    fi
    p=$(command -v "python$v" 2>/dev/null) && good "$p" && { echo "$p"; return 0; }
  done
  # on a Mac not /usr/bin/python3: it is 3.9, and without the Command Line Tools running it opens an Xcode dialog
  p=$(command -v python3 2>/dev/null) && { [ "$OS" != Darwin ] || [ "$p" != /usr/bin/python3 ]; } && good "$p" \
    && { echo "$p"; return 0; }
  return 1
}

no_python() {
  if [ "$OS" = Darwin ]; then
    say "Pult needs Python 3.10 or newer. Install it with Homebrew (https://brew.sh): brew install python@3.12 — then run ./install.sh again." \
        "Пульту нужен Python 3.10 или новее. Поставь через Homebrew (https://brew.sh): brew install python@3.12 — и снова ./install.sh."
  else
    say "Pult needs Python 3.10 or newer, with venv. Debian or Ubuntu: sudo apt update && sudo apt install python3 python3-venv; Fedora: sudo dnf install python3; Arch: sudo pacman -S python — then run ./install.sh again." \
        "Пульту нужен Python 3.10 или новее, с venv. Debian или Ubuntu: sudo apt update && sudo apt install python3 python3-venv; Fedora: sudo dnf install python3; Arch: sudo pacman -S python — и снова ./install.sh."
  fi
}

mkdir -p "$DST"
chmod 700 "$DST"

if ! good "$DST/venv/bin/python"; then
  if ! PY=$(find_python); then
    no_python
    exit 1
  fi
  if ! "$PY" -c 'import ensurepip, venv' 2>/dev/null; then
    # Debian and Ubuntu ship venv separately, versioned like the Python itself
    V=$("$PY" -c 'import sys; print("%d.%d" % sys.version_info[:2])')
    say "Python $V has no venv module. Debian or Ubuntu: sudo apt update && sudo apt install python$V-venv — then run ./install.sh again." \
        "У Python $V нет модуля venv. Debian или Ubuntu: sudo apt update && sudo apt install python$V-venv — и снова ./install.sh."
    exit 1
  fi
  rm -rf "$DST/venv"                  # left over from a Python that is gone
  say "Python: $PY" "Python: $PY"
  "$PY" -m venv "$DST/venv"
fi

cp "$SRC"/src/pultd.py "$SRC"/src/pult_hook.py "$SRC"/src/pult_render.py "$SRC"/src/pult_web.py "$SRC"/src/pult_i18n.py "$SRC"/src/pult_stt.py \
   "$SRC"/src/pult_load.py "$SRC"/src/pult_attn.py "$SRC"/src/pult_brief.py "$SRC"/src/pult_os.py "$SRC"/src/pult_setup.py "$SRC"/src/pultctl.py "$SRC"/requirements.txt "$DST"/
# VS Code tab wrapper: takes effect only after the claudeCode.claudeProcessWrapper setting (pult tab setup)
cp "$SRC"/src/pult_tab.py "$SRC"/src/pult-tab.sh "$DST"/
chmod 755 "$DST"/pult_tab.py "$DST"/pult-tab.sh

say "Installing dependencies…" "Ставлю зависимости…"
"$DST/venv/bin/pip" install -q --disable-pip-version-check -r "$DST/requirements.txt"

exec "$DST/venv/bin/python" "$DST/pultctl.py" install
