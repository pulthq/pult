#!/usr/bin/env python3
"""Pult: the `pult` command — control without the agent. Standard library only: works even when Pult's
environment is broken (`python3 ~/.local/share/pult/pultctl.py …`). `pult help` lists the commands.

Installing, the setup, the service, the report and removal live in pult_setup.py; here — the commands themselves,
the status, the tab switch and `pult run`.
"""
import collections
import json
import os
import shlex
import subprocess
import sys
import time
import uuid
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import pult_i18n as I  # noqa: E402
import pult_setup as S  # noqa: E402
from pult_i18n import T  # noqa: E402

strip_ours = S.strip_ours            # kept here for older checks and scripts


def cmd_status():
    env = S.read_env()
    lbl = S.label()
    row = lambda key, val: print("%-11s %s" % (T(key), val))
    state, pid = S.service(lbl)
    row("cli.st.daemon", T("cli.st.running", state=state, pid=pid) if state else T("cli.st.not_loaded", label=lbl))
    row("cli.st.sock", T("cli.st.answers") if S.sock_ok() else T("cli.st.no"))
    hooks = S.hooks_installed()
    missing = [e for e in S.pult_hook.EVENTS if e not in hooks] if hooks else []     # a newer Pult added an event
    row("cli.st.hooks", ", ".join(hooks) + (T("cli.hooks.missing", events=", ".join(missing)) if missing else "")
        if hooks else T("cli.hooks.off"))
    row("cli.st.settings", S.tilde(S.ENV_FILE) if env.get("PULT_BOT_TOKEN") else T("cli.st.no_token"))
    if env.get("PULT_BOT_TOKEN"):
        routes = ([("cli.st.via_proxy", env["PULT_PROXY"])] if env.get("PULT_PROXY") else []) + [("cli.st.direct", "")]
        for name, proxy in routes:
            try:
                S.bot_call(env["PULT_BOT_TOKEN"], "getMe", proxy, http_timeout=15)
                row("cli.st.tg", T("cli.st.route_ok", route=T(name)))
            except (S.TgError, OSError) as e:
                row("cli.st.tg", T("cli.st.route_bad", route=T(name), why=e))
    row("cli.st.tabs", tab_state())
    row("cli.st.log", S.tilde(S.LOG))


def tab_state():
    """One line: whether the wrapper is in the VS Code settings, the off switch, folders and verified versions."""
    if not S.tab_wrapped():
        return T("cli.tab.not_wrapped")
    if S.TAB_OFF.exists():
        return T("cli.tab.off", path=S.tilde(S.TAB_OFF))
    conf = S.tab_conf()
    return T("cli.tab.on", folders=", ".join(conf.get("folders") or []) or T("cli.tab.none"),
             versions=", ".join(conf.get("versions") or []) or T("cli.tab.none"))


def cmd_tab(argv):
    if argv[:1] == ["setup"]:
        return S.cmd_tab_setup()
    if argv[:1] == ["off"]:
        S.TAB_OFF.parent.mkdir(parents=True, exist_ok=True)
        S.TAB_OFF.touch()
    elif argv[:1] == ["on"]:
        S.TAB_OFF.unlink(missing_ok=True)
    elif argv[:1] == ["allow"] and argv[1:2]:
        conf = S.tab_conf()
        conf["versions"] = sorted(set(conf.get("versions") or []) | {argv[1]}, key=S.vkey)
        S.TAB_CONF.parent.mkdir(parents=True, exist_ok=True)
        S.TAB_CONF.write_text(json.dumps(conf, ensure_ascii=False) + "\n", encoding="utf-8")
    print("%s %s" % (T("cli.st.tabs"), tab_state()))
    if argv[:1] in (["off"], ["on"], ["allow"]):
        print(T("cli.tab.next"))
    return 0


RUN_TICK = 30           # seconds; the last output line goes to the daemon at most this often


def tell(msg):
    """Task event to the daemon; no daemon — silently skip: the task runs without Pult too."""
    try:
        s = S.pult_os.link_connect(S.SOCK)
        s.sendall(json.dumps({"run": msg}, ensure_ascii=False).encode() + b"\n")
        s.close()
    except (OSError, ValueError):
        pass


def cmd_run(argv):
    """Runs the command as usual (output goes to the terminal) and reports start, progress and end to Pult.
    The exit code is the command's own. Interactive programs are better run without it: output goes via a pipe."""
    if "--" in argv:
        argv = argv[argv.index("--") + 1:]
    if not argv:
        print(T("cli.run.usage"))
        return 2
    rid = uuid.uuid4().hex[:8]
    line = subprocess.list2cmdline(argv) if os.name == "nt" else " ".join(shlex.quote(a) for a in argv)
    tell({"op": "start", "id": rid, "cmd": line, "cwd": os.getcwd(),
          "pid": os.getpid()})
    try:
        p = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    except OSError as e:
        print(T("cli.run.failed"), e, file=sys.stderr)
        tell({"op": "end", "id": rid, "code": 127, "tail": [str(e)]})
        return 127
    tail, part, tick = collections.deque(maxlen=40), b"", time.time()
    try:
        while True:
            chunk = os.read(p.stdout.fileno(), 65536)
            if not chunk:
                break
            sys.stdout.buffer.write(chunk)
            sys.stdout.buffer.flush()
            lines = (part + chunk).split(b"\n")
            part = lines.pop()
            # progress bars rewrite the line with \r — keep the line's last state
            tail.extend(x for x in (ln.split(b"\r")[-1].decode(errors="replace").rstrip()[-300:] for ln in lines) if x)
            if time.time() - tick >= RUN_TICK and tail:
                tell({"op": "tick", "id": rid, "last": tail[-1]})
                tick = time.time()
    except KeyboardInterrupt:
        pass                                   # the command got Ctrl+C too; wait for it to finish
    code = p.wait()
    if part.strip():
        tail.append(part.split(b"\r")[-1].decode(errors="replace").rstrip()[-300:])
    tell({"op": "end", "id": rid, "code": code, "tail": list(tail)[-30:]})
    return code


def main(argv):
    I.set_lang(S.cli_lang())
    cmd, rest = (argv[0] if argv else ""), argv[1:]
    if cmd == "status":
        cmd_status()
    elif cmd == "install":
        return S.cmd_install()
    elif cmd == "setup":
        return S.cmd_setup()
    elif cmd in ("start", "stop", "restart"):
        return S.cmd_service(cmd)
    elif cmd == "hooks" and rest[:1] in (["on"], ["off"]):
        S.hooks_set(rest[0] == "on")
    elif cmd == "hooks":
        print("%s %s" % (T("cli.st.hooks"), ", ".join(S.hooks_installed()) or T("cli.hooks.off")))
    elif cmd == "tab":
        return cmd_tab(rest)
    elif cmd == "app":
        return S.cmd_app(rest)
    elif cmd == "stt":
        return S.cmd_stt(rest)
    elif cmd == "run":
        return cmd_run(rest)
    elif cmd == "report":
        return S.cmd_report()
    elif cmd == "uninstall":
        return S.cmd_uninstall()
    else:
        print(T("cli.usage"))
        return 0 if cmd in ("", "help", "-h", "--help") else 2
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv[1:]))
    except KeyboardInterrupt:
        print()
        sys.exit(130)
