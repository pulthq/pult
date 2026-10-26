#!/usr/bin/env python3
"""Pult: the `pult` command — control without the agent. Standard library only: works even when Pult's
environment is broken (`python3 ~/.local/share/pult/pultctl.py …`). `pult help` lists the commands.

Installing, the setup, the service, the report and removal live in pult_setup.py; here — the commands themselves,
the status, the tab switch, `pult run` and `pult send`.
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


def cmd_tab_check(args):
    """pult tab check [VERSION | path to claude] [--json] [--dry]: Pult checks a Claude Code version on this computer
    (stage A, pult_tabcheck) — the newest one VS Code has downloaded when none is named — and allows it for the tabs
    when it passes. --json: the report as one line, for the daemon; --dry: tab.json is left as it was."""
    import asyncio
    import pult_tabcheck as C
    as_json, dry = "--json" in args, "--dry" in args
    rest = [a for a in args if not a.startswith("--")]
    found = C.binaries(S.EXT_DIRS)
    if rest and os.path.isfile(rest[0]):
        cli, v = Path(rest[0]), C.version_of(rest[0])
    else:
        v = rest[0] if rest else max(found, key=C.vkey, default=None)
        cli = found.get(v)

    def done(rep, text, code):
        if as_json:
            print(json.dumps(rep, ensure_ascii=False))
        else:
            print(text)
            if dry:
                print(T("cli.check.dry"))
        return code
    if not cli or not v:
        return done({"version": v, "ok": None, "race": None, "error": "nobinary", "steps": [], "ts": time.time()},
                    T("cli.check.none", v=v or "?"), 2)
    if v in S.TAB_BLOCKED:
        rep = {"version": v, "ok": False, "race": None, "error": None, "ts": time.time(),
               "steps": [{"k": "blocked", "ok": False, "s": 0, "note": "a Pult release blocks this version"}]}
        if not dry:
            S.tab_checked(v, rep)
        return done(rep, T("cli.check.blocked", v=v), 1)
    say = None
    if not as_json:
        print(T("cli.check.start", v=v), flush=True)
        say = lambda k, ok, note="": print("  %s %s%s" % ({True: "✓", False: "✗"}.get(ok, "·"), T("tab.step." + k),  # noqa: E731
                                                          " — " + note if note and ok is not True else ""), flush=True)
    try:
        rep = asyncio.run(asyncio.wait_for(C.run(cli, S.HOME / "pult_tab.py", sys.executable, say), C.TOTAL))
    except asyncio.TimeoutError:
        rep = {"version": v, "ok": None, "race": None, "error": "timeout", "steps": [], "ts": time.time()}
    if not dry:
        S.tab_checked(v, rep)
    if rep.get("error"):
        return done(rep, T("cli.check.err", v=v, why=T("check.why." + rep["error"])), 2)
    step = next((x["k"] for x in rep["steps"] if x.get("ok") is False and x["k"] != "race"), None)
    text = T("cli.check.ok", v=v) if rep["ok"] else T("cli.check.fail", v=v, step=T("tab.step." + (step or "own")))
    if rep.get("race") is False:
        text += "\n" + T("cli.check.race", v=v)
    return done(rep, text, 0 if rep["ok"] else 1)


def cmd_tab(argv):
    if argv[:1] == ["setup"]:
        return S.cmd_tab_setup()
    if argv[:1] == ["check"]:
        return cmd_tab_check(argv[1:])
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


def cmd_send(argv):
    """pult send FILE… [-m CAPTION]: files to the owner's phone, into the Telegram topic of the project the Claude
    session works in. Claude runs it; Claude Code names the session in the command's environment
    (CLAUDE_CODE_SESSION_ID), and the daemon checks every file (pult_files.why_not_send)."""
    caption, files, i = None, [], 0
    while i < len(argv):
        if argv[i] in ("-m", "--message") and i + 1 < len(argv):
            caption, i = argv[i + 1], i + 2
            continue
        files.append(argv[i])
        i += 1
    if not files:
        print(T("cli.send.usage"))
        return 2
    sid = os.environ.get("CLAUDE_CODE_SESSION_ID", "")
    if not sid:
        print(T("cli.send.nosession"), file=sys.stderr)
        return 2
    msg = {"op": "send", "sid": sid, "paths": [os.path.abspath(f) for f in files], "caption": caption}
    try:
        s = S.pult_os.link_connect(S.SOCK)
        s.settimeout(900)                       # up to ten files of 50 MB through Telegram's queue
        s.sendall(json.dumps(msg, ensure_ascii=False).encode() + b"\n")
        buf = b""
        while not buf.endswith(b"\n"):
            chunk = s.recv(65536)
            if not chunk:
                break
            buf += chunk
        s.close()
        res = json.loads(buf.decode("utf-8") or "{}")
    except (OSError, ValueError):
        print(T("cli.send.nodaemon"), file=sys.stderr)
        return 1
    if not res:                                 # a daemon from before 0.13 takes it for a hook event and says nothing
        print(T("cli.send.old"), file=sys.stderr)
        return 1
    if res.get("error"):
        print(res["error"], file=sys.stderr)
        return 1
    for n in res.get("sent") or []:
        print(T("cli.send.sent", name=n))
    for n, why in res.get("refused") or []:
        print(T("cli.send.refused", name=n, why=why), file=sys.stderr)
    return 0 if res.get("sent") and not res.get("refused") else 1


def utf8_pipes():
    """Output into a pipe speaks UTF-8, as Claude Code reads a command's output. On Windows a pipe gets the system's code
    page (cp1252, cp1251), and Russian words or a file's name stopped `pult send` midway — after the file was sent
    (Actions, 2026-10-23). A console keeps its own way of writing."""
    for stream in (sys.stdout, sys.stderr):
        enc = (getattr(stream, "encoding", "") or "").lower().replace("-", "")
        if hasattr(stream, "reconfigure") and enc != "utf8" and not stream.isatty():
            stream.reconfigure(encoding="utf-8", errors="replace")


def main(argv):
    utf8_pipes()
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
    elif cmd == "send":
        return cmd_send(rest)
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
