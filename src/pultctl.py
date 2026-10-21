#!/usr/bin/env python3
"""Pult: the `pult` command — control without the agent. Standard library only: works even when Pult's
environment is broken (`python3 ~/.local/share/pult/pultctl.py …`). `pult help` lists the commands.

Installing, the setup, the service, the report and removal live in pult_setup.py; here — the commands themselves,
the status, the tab switch and `pult run`.
"""
import codecs
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
    for w in S.wrapper_warnings():
        print("  " + w.replace("\n", "\n  "))
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


def odd(text):
    """UTF-8 a legacy code page makes by chance: cp866 "шаг" is E8 A0 A3, valid UTF-8 for "蠣". Real output keeps to
    two-byte letters and the symbols of U+2000–U+2BFF (dashes, arrows, box drawing, progress bars)."""
    return any(0x800 <= ord(c) < 0x2000 or 0x2C00 <= ord(c) < 0xFE00 for c in text)


def decode_out(data, cp=None):
    """A command's output as text: UTF-8 when it is (Python under `pult run`, git, node), else the console's code page
    cp — what console programs write on Windows (cp866 on a Russian one); unreadable bytes become �."""
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return data.decode(cp or "utf-8", errors="replace")
    return data.decode(cp, errors="replace") if cp and cp != "utf-8" and odd(text) else text


def last_state(line, cp=None):
    """What a line of output shows in the end: after the last \\r that rewrote it, without the \\r of \\r\\n."""
    return decode_out(line.rstrip(b"\r").split(b"\r")[-1], cp).rstrip()[-300:]


def screen_writer(cp):
    """How the output reaches the screen: bytes as they come, except a Windows console (cp set), which would read
    them in its own code page — there they go as text, UTF-8 or that code page; a chunk may end mid-letter, the
    decoder keeps it for the next one."""
    if cp is None or not sys.stdout.isatty():
        def write(chunk):
            sys.stdout.buffer.write(chunk)
            sys.stdout.buffer.flush()
        return write
    dec = codecs.getincrementaldecoder("utf-8")()

    def write(chunk):
        nonlocal dec
        try:
            text = dec.decode(chunk)
            if cp != "utf-8" and odd(text):
                raise UnicodeDecodeError("utf-8", chunk, 0, len(chunk), "a legacy code page")
        except UnicodeDecodeError:
            dec = codecs.getincrementaldecoder("utf-8")()
            text = chunk.decode(cp, errors="replace")
        sys.stdout.write(text)
        sys.stdout.flush()
    return write


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
    cp, env = S.pult_os.console_encoding(), None
    if cp:          # Windows: Python writes to a pipe in the system's code page (cp1251) — ask it for UTF-8
        env = dict(os.environ)
        env.setdefault("PYTHONIOENCODING", "utf-8")
    try:
        p = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=env)
    except OSError as e:
        print(T("cli.run.failed"), e, file=sys.stderr)
        tell({"op": "end", "id": rid, "code": 127, "tail": [str(e)]})
        return 127
    tail, part, tick = collections.deque(maxlen=40), b"", time.time()
    show = screen_writer(cp)
    try:
        while True:
            chunk = os.read(p.stdout.fileno(), 65536)
            if not chunk:
                break
            show(chunk)
            lines = (part + chunk).split(b"\n")
            part = lines.pop()
            # progress bars rewrite the line with \r — keep the line's last state; a line's own \r (Windows ends lines
            # with \r\n) is not a rewrite
            tail.extend(x for x in (last_state(ln, cp) for ln in lines) if x)
            if time.time() - tick >= RUN_TICK and tail:
                tell({"op": "tick", "id": rid, "last": tail[-1]})
                tick = time.time()
    except KeyboardInterrupt:
        pass                                   # the command got Ctrl+C too; wait for it to finish
    code = p.wait()
    if part.strip():
        tail.append(last_state(part, cp))
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
    elif cmd == "busy":
        return S.cmd_busy()
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
