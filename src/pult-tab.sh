#!/bin/sh
# Pult: Claude Code process wrapper for VS Code tabs (the claudeCode.claudeProcessWrapper setting).
# Off switch ~/.config/pult/tab-off present, or no Pult environment — Claude Code runs directly, tabs work as without Pult.
DIR=$(dirname "$0")
PY="$DIR/venv/bin/python"
TAB="$DIR/pult_tab.py"
if [ ! -e "$HOME/.config/pult/tab-off" ] && [ -x "$PY" ] && [ -r "$TAB" ]; then
  exec "$PY" "$TAB" "$@"
fi
exec "$@"
