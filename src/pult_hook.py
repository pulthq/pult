#!/usr/bin/env python3
"""Pult: Claude Code hook — forwards session events to the pultd daemon over a unix socket.

Installed into ~/.claude/settings.json by `pult hooks on`. Standard library only:
it runs on every event of every session and must start fast.

The main rule: the hook never gets in the way of a session. No daemon, no socket, any error —
exit 0 with no output, and Claude Code behaves as if there were no hook.

PermissionRequest waits for the daemon's answer (the daemon asks in Telegram). The permission dialog
in VS Code is open at the same time: whoever answers first decides. A Telegram answer that arrives
after the one given on the Mac is ignored by Claude Code (verified 2026-10-15).
"""
import json
import os
import socket
import sys

SOCK = os.environ.get("PULT_SOCK") or os.path.expanduser("~/.local/share/pult/pult.sock")
TRACKED = {"claude-vscode", "cli"}       # `claude -p` (sdk-cli) and other SDK runs are skipped

EVENTS = ["SessionStart", "UserPromptSubmit", "PostToolUse", "PostToolUseFailure",
          "Stop", "SessionEnd", "PermissionRequest"]
WAIT_TIMEOUT = 6 * 3600 + 60             # wait up to 6 h for a Telegram answer; the Mac dialog stays open meanwhile


def hooks_config(command):
    """The hooks block for settings.json: both the global one (pult hooks on) and the one for Telegram sessions."""
    out = {}
    for ev in EVENTS:
        h = {"type": "command", "command": command,
             "timeout": WAIT_TIMEOUT if ev == "PermissionRequest" else 10}
        out[ev] = [{"matcher": "*", "hooks": [h]}] if ev in ("PostToolUse", "PostToolUseFailure",
                                                             "PermissionRequest") else [{"hooks": [h]}]
    return out


def wanted():
    if os.environ.get("PULT_OFF") == "1":
        return False
    if os.environ.get("PULT_DRIVEN") == "1":
        # the session was started by Pult itself: its events come from the hook Pult injected into it,
        # and the global hook stays silent to avoid duplicates
        return os.environ.get("PULT_INJECTED") == "1"
    return os.environ.get("CLAUDE_CODE_ENTRYPOINT", "") in TRACKED


def main():
    if not wanted():
        return
    ev = json.loads(sys.stdin.buffer.read().decode("utf-8", errors="replace") or "{}")   # UTF-8 on every system
    wait = ev.get("hook_event_name") == "PermissionRequest"
    msg = {"event": ev, "pid": os.getppid(), "entry": os.environ.get("CLAUDE_CODE_ENTRYPOINT", ""),
           "driven": os.environ.get("PULT_DRIVEN") == "1", "wait": wait}
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.settimeout(1.0)
    s.connect(SOCK)
    s.sendall(json.dumps(msg, ensure_ascii=False).encode() + b"\n")
    if not wait:
        return
    s.settimeout(None)
    buf = b""
    while not buf.endswith(b"\n"):
        chunk = s.recv(65536)
        if not chunk:
            return
        buf += chunk
    out = json.loads(buf).get("output")
    if out:
        sys.stdout.buffer.write(json.dumps(out, ensure_ascii=False).encode())
        sys.stdout.buffer.flush()


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass
    sys.exit(0)
