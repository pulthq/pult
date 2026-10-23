#!/usr/bin/env python3
"""Pult: Claude Code hook — forwards session events to the pultd daemon over its link: a unix socket, or on
Windows 127.0.0.1 with the port and the key from the link file (pult_os.link_connect, repeated here).

Installed into ~/.claude/settings.json by `pult hooks on`. Standard library only:
it runs on every event of every session and must start fast. On Windows it runs in exec form — pythonw and this
file as arguments, no shell — and `--injected` stands for PULT_INJECTED=1 (an environment prefix is shell syntax).

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

SOCK = next((a[len("--sock="):] for a in sys.argv[1:] if a.startswith("--sock=")), None) \
    or os.environ.get("PULT_SOCK") or os.path.expanduser("~/.local/share/pult/pult.sock")
TRACKED = {"claude-vscode", "cli"}       # `claude -p` (sdk-cli) and other SDK runs are skipped

EVENTS = ["SessionStart", "UserPromptSubmit", "PostToolUse", "PostToolUseFailure",
          "Stop", "StopFailure", "SessionEnd", "PermissionRequest"]     # StopFailure: an API error ended the turn
WAIT_TIMEOUT = 6 * 3600 + 60             # wait up to 6 h for a Telegram answer; the Mac dialog stays open meanwhile
# what a session learns at its start (and again after a resume or a compaction) while Pult runs: how to hand the owner
# a file (stage F). SessionStart's additionalContext reaches the model — probe tests/probe_sessionctx.py, 2.1.300/2.1.301
CONTEXT = ("Pult, a Telegram remote for Claude Code, runs on this computer. When the owner asks for a file, or the task "
           "is to hand them one, send it to their phone with `pult send <file>... [-m \"caption\"]`: it arrives in this "
           "project's Telegram topic. Only files inside this project's folder, up to 50 MB each. Files the owner sends "
           "from Telegram are saved in this project's inbox/<date>/ folder.")


def hooks_config(command, args=None):
    """The hooks block for settings.json: both the global one (pult hooks on) and the one for Telegram sessions.
    With args — exec form: Claude Code starts command with these arguments, no shell (Windows)."""
    out = {}
    for ev in EVENTS:
        h = {"type": "command", "command": command}
        if args is not None:
            h["args"] = list(args)
        h["timeout"] = WAIT_TIMEOUT if ev == "PermissionRequest" else 10
        out[ev] = [{"matcher": "*", "hooks": [h]}] if ev in ("PostToolUse", "PostToolUseFailure",
                                                             "PermissionRequest") else [{"hooks": [h]}]
    return out


def wanted():
    if os.environ.get("PULT_OFF") == "1":
        return False
    if os.environ.get("PULT_DRIVEN") == "1":
        # the session was started by Pult itself: its events come from the hook Pult injected into it,
        # and the global hook stays silent to avoid duplicates
        return os.environ.get("PULT_INJECTED") == "1" or "--injected" in sys.argv[1:]
    return os.environ.get("CLAUDE_CODE_ENTRYPOINT", "") in TRACKED


def connect():
    if os.name != "nt" and os.environ.get("PULT_LINK") != "tcp":
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.settimeout(1.0)
        s.connect(SOCK)
        return s
    with open(SOCK, encoding="utf-8") as f:
        link = json.load(f)
    s = socket.create_connection(("127.0.0.1", int(link["port"])), timeout=1.0)
    s.sendall(str(link["key"]).encode() + b"\n")
    return s


def main():
    if not wanted():
        return
    ev = json.loads(sys.stdin.buffer.read().decode("utf-8", errors="replace") or "{}")   # UTF-8 on every system
    wait = ev.get("hook_event_name") == "PermissionRequest"
    msg = {"event": ev, "pid": os.getppid(), "entry": os.environ.get("CLAUDE_CODE_ENTRYPOINT", ""),
           "driven": os.environ.get("PULT_DRIVEN") == "1", "wait": wait}
    s = connect()
    s.sendall(json.dumps(msg, ensure_ascii=False).encode() + b"\n")
    if ev.get("hook_event_name") == "SessionStart":          # only now: the daemon took the event, so Pult runs
        sys.stdout.buffer.write(json.dumps({"hookSpecificOutput": {"hookEventName": "SessionStart",
                                                                   "additionalContext": CONTEXT}}).encode())
        sys.stdout.buffer.flush()
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
