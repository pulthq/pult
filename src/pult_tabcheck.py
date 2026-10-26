"""Pult: checks a Claude Code version VS Code has downloaded, on this computer, before a window reloads onto it (stage A).

The tab wrapper steps into a tab only on a version tab.json lists, and VS Code updates the extension by itself, nearly
every day: on an unchecked version a message from the phone to an open tab goes as a copy (a friend's tabs, up to ten
days, 2026-10-26). VS Code downloads a new version at once, but an open window keeps the old one until it reloads, so a
check in between keeps writing into tabs on. It runs what tests/probe_tab.py, probe_model.py, probe_effort.py and
probe_race.py check, on the new version's own claude and through Pult's installed wrapper:
  service — a utility command goes through the wrapper untouched;
  own     — the tab's own prompt: the wrapper introduces itself to the "daemon" and names the session;
  send    — a message from the "phone": Claude Code echoes it with our uuid (that is how a tab shows it), starts a turn
            and answers;
  model   — set_model through the wrapper: the next answer comes from the other model;
  effort  — apply_flag_settings through the wrapper: the next request's effort is the one asked, null goes back to the
            settings;
  race    — the PermissionRequest hook and the permission window race, and the first answer decides (every session
            relies on it, not only tabs: told when it fails; writing into tabs doesn't wait for it).
The Agent SDK stands in for the extension — it starts claude the way the extension does: stream-json both ways,
--replay-user-messages, --permission-prompt-tool=stdio — and a socket of the check's own for the daemon. Apart from
everything: a temporary folder, the user's settings and hooks unread (setting_sources), PULT_OFF=1 for the hook, and the
transcripts of the check's own sessions removed afterwards (the effort step reads its requests' effort there). What it
can't see is the tab's own window (the webview): that stays with a release's look at the extension's code, which can
block a version (pult_setup.TAB_BLOCKED). About a minute, about ten short requests on haiku and one on sonnet, one
claude process at a time.

The daemon runs it (pultctl.py tab check --json) when VS Code has downloaded a version tab.json doesn't list; the owner
by hand with `pult tab check` or "Check again" in the app. Needs the Agent SDK: Pult's own Python.
"""
import asyncio
import json
import os
import re
import shlex
import shutil
import tempfile
import time
import uuid
from pathlib import Path

STEPS = ("service", "own", "send", "model", "effort", "race")
TAB_STEPS = STEPS[:5]           # writing into tabs depends on these
WAIT = 90                       # s for one answer of the model
TOTAL = 300                     # s for the whole check (the daemon gives the process a little more)
SWITCH_WAIT = 10                # s for the wrapper to say a switch is done
PROJECTS = Path.home() / ".claude" / "projects"     # where Claude Code keeps transcripts (pultd.CLAUDE_PROJECTS)
LOGIN = re.compile(r"log ?in\b|authenticat|credential|api[ _-]?key|oauth|unauthori[sz]ed|\b401\b", re.I)
LIMIT = re.compile(r"usage limit|rate[ _-]?limit|limit reached|\b429\b|overloaded|\b529\b", re.I)
NET = re.compile(r"connect|network|timed? ?out|econn|enotfound|getaddrinfo|socket hang|unreachable|proxy", re.I)
HOOK = """import json, os, sys, time
d = json.load(sys.stdin)
open(os.environ["MARK"], "a").write("hook %.2f\\n" % time.time())
time.sleep(float(os.environ["HOOK_DELAY"]))
print(json.dumps({"hookSpecificOutput": {"hookEventName": "PermissionRequest", "decision": {"behavior": "allow"}}}))
"""


class Trouble(Exception):
    """claude couldn't answer at all — not logged in, a limit, the network: the check didn't happen, try later."""
    def __init__(self, kind, text=""):
        super().__init__(kind)
        self.kind, self.text = kind, text


def trouble(text):
    """Why claude couldn't answer, from its words: "login", "limit", "network"; None for anything else."""
    for kind, rx in (("login", LOGIN), ("limit", LIMIT), ("network", NET)):
        if rx.search(text or ""):
            return kind
    return None


def version_of(path):
    """…/anthropic.claude-code-2.1.310-darwin-arm64/resources/native-binary/claude → "2.1.310" (pult_tab.version_of)."""
    for part in re.split(r"[\\/]", str(path)):
        if part.startswith("anthropic.claude-code-"):
            return part[len("anthropic.claude-code-"):].split("-")[0]
    return None


def binaries(dirs):
    """{version: its claude} for each Claude Code extension VS Code keeps in dirs (pult_os.extension_dirs)."""
    out = {}
    exe = "claude.exe" if os.name == "nt" else "claude"
    for d in dirs:
        for p in Path(d).glob("anthropic.claude-code-*"):
            b = p / "resources" / "native-binary" / exe
            v = version_of(p)
            if v and b.is_file():
                out.setdefault(v, b)
    return out


def vkey(v):
    try:
        return tuple(int(x) for x in str(v).split("."))
    except ValueError:
        return (0,)


def spawner(tmp, wrapper, cli, py):
    """What the extension runs with claudeProcessWrapper set — <wrapper> <its own claude> <arguments> — as one program
    for the SDK's cli_path. Windows: a launcher with the wrapper inside, as the install makes pult-tab.exe."""
    if os.name == "nt":
        import pult_setup
        return pult_setup.make_exe(tmp / "ext-spawn.exe", pult_setup.base_pythonw(), {
            "pult_tab.py": Path(wrapper).read_bytes(),
            "__main__.py": "import sys\nsys.argv[1:1] = [%r]\nimport pult_tab\npult_tab.entry()\n" % str(cli)})
    p = tmp / "ext-spawn.sh"
    p.write_text('#!/bin/sh\nexec %s %s %s "$@"\n' % (shlex.quote(str(py)), shlex.quote(str(wrapper)), shlex.quote(str(cli))))
    p.chmod(0o755)
    return p


def efforts(sid):
    """The effort of each model request of a session, from its transcript, in order."""
    out, ids = [], set()
    for f in PROJECTS.glob("*/%s.jsonl" % sid):
        for line in f.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                e = json.loads(line)
            except ValueError:
                continue
            m = e.get("message") or {}
            if e.get("type") == "assistant" and m.get("usage") and m.get("id") not in ids:
                ids.add(m.get("id"))
                out.append(e.get("effort"))
    return out


def forget(sids):
    """The check's own sessions out of Claude Code's history: their transcripts, and their folders once empty. Only
    sessions this check started, all in its temporary folder — nobody else's."""
    for sid in sids:
        for f in PROJECTS.glob("*/%s.jsonl" % sid):
            folder = f.parent
            f.unlink(missing_ok=True)
            shutil.rmtree(folder / sid, ignore_errors=True)
            try:
                folder.rmdir()
            except OSError:
                pass


class Check:
    def __init__(self, cli, wrapper, py, say):
        self.cli, self.wrapper, self.py, self.say = Path(cli), Path(wrapper), py, say
        self.v = version_of(cli)
        self.tmp = Path(tempfile.mkdtemp(prefix="pult-check-"))
        self.sids = set()
        self.steps = []
        self.runs = 0                                   # tab sessions so far: each gets a folder of its own

    def step(self, k, ok, t0, note=""):
        ok = bool(ok)
        self.steps.append({"k": k, "ok": ok, "s": round(time.monotonic() - t0, 1), "note": str(note)[:200]})
        self.say(k, ok, note)
        return ok

    # ---- service: a utility command through the wrapper

    async def service(self, spawn, env):
        t0 = time.monotonic()
        p = await asyncio.create_subprocess_exec(str(spawn), "--version", stdout=asyncio.subprocess.PIPE,
                                                 stderr=asyncio.subprocess.PIPE, env=dict(os.environ, **env))
        try:
            out, err = await asyncio.wait_for(p.communicate(), 30)
        except asyncio.TimeoutError:
            p.kill()
            return self.step("service", False, t0, "no answer in 30 s")
        text = (out or b"").decode(errors="replace").strip()
        return self.step("service", self.v in text, t0, text[:80] or (err or b"").decode(errors="replace")[:120])

    # ---- own, send, model, effort: one session through the wrapper, the way a tab runs

    async def tab(self):
        """The four steps of one tab session; True when all passed. Trouble when claude couldn't answer at all."""
        from claude_agent_sdk import (AssistantMessage, ClaudeAgentOptions, ClaudeSDKClient, PermissionResultAllow,
                                      ResultMessage, SystemMessage, TextBlock, UserMessage)
        from pultd import start_link
        self.runs += 1
        run = self.tmp / ("tab-%d" % self.runs)
        proj = run / "proj"
        (proj / ".claude").mkdir(parents=True)
        (proj / ".claude" / "settings.json").write_text(json.dumps({"effortLevel": "medium"}))
        conf, log = run / "tab.json", run / "tab.log"
        conf.write_text(json.dumps({"folders": [str(proj)], "versions": [self.v]}))
        # a unix socket's path is at most 104 bytes: a long temporary folder gets a short name of its own
        sock = str(run / "d.sock") if len(str(run / "d.sock")) < 100 else "/tmp/pult-check-%d.sock" % os.getpid()
        env = {"PULT_TAB_CONF": str(conf), "PULT_SOCK": sock, "PULT_OFF": "1", "PULT_TAB_LOG": str(log)}
        spawn = spawner(run, self.wrapper, self.cli, self.py)
        if not await self.service(spawn, env):
            return False
        tabs, seen, err = [], [], []

        async def daemon(reader, writer):
            try:
                hello = json.loads(await reader.readline())
            except ValueError:
                return
            t = {"hello": hello, "sid": hello.get("sid"), "w": writer}
            tabs.append(t)
            try:
                while line := await reader.readline():
                    m = json.loads(line)
                    if m.get("op") == "sid":
                        t["sid"] = m.get("sid")
            except (ConnectionError, ValueError):
                pass

        async def allow(tool, inp, ctx):
            return PermissionResultAllow()

        def results():
            return [x for x in seen if x[0] == "result"]

        async def answer(n):
            t = time.monotonic()
            while len(results()) < n:
                if time.monotonic() - t > WAIT:
                    raise asyncio.TimeoutError
                await asyncio.sleep(0.1)
            r = results()[n - 1]
            if r[2]:                                    # an error instead of an answer
                kind = trouble(r[3] + " " + " ".join(err[-20:]))
                if kind:
                    raise Trouble(kind, r[3])
            return r

        async def said(word, n):
            """The wrapper's own log: a switch it was told to make is done (or not, in SWITCH_WAIT s)."""
            t = time.monotonic()
            while time.monotonic() - t < SWITCH_WAIT:
                if log.exists() and log.read_text(encoding="utf-8", errors="replace").count(word) >= n:
                    return True
                await asyncio.sleep(0.2)
            return False

        async def tell(tab, msg):
            tab["w"].write((json.dumps(msg) + "\n").encode())
            await tab["w"].drain()

        server = await start_link(daemon, sock)
        t0 = time.monotonic()
        opts = ClaudeAgentOptions(cli_path=str(spawn), cwd=str(proj), model="haiku", permission_mode="default",
                                  can_use_tool=allow, setting_sources=["project"], env=env, stderr=err.append,
                                  extra_args={"replay-user-messages": None})
        ok = True
        try:
            async with ClaudeSDKClient(options=opts) as c:
                async def read():
                    async for m in c.receive_messages():
                        if isinstance(m, SystemMessage) and m.subtype == "init":
                            seen.append(("init", (m.data or {}).get("session_id")))
                        elif isinstance(m, UserMessage):
                            text = m.content if isinstance(m.content, str) else " ".join(
                                getattr(b, "text", "") for b in m.content if isinstance(b, TextBlock))
                            seen.append(("user", text, getattr(m, "uuid", None)))
                        elif isinstance(m, AssistantMessage):
                            seen.append(("assistant", m.model or ""))
                        elif isinstance(m, ResultMessage):
                            self.sids.add(m.session_id)
                            seen.append(("result", m.session_id, bool(m.is_error), str(m.result or "")))
                reader = asyncio.create_task(read())
                try:
                    t0 = time.monotonic()
                    await c.query("Reply with exactly one word: ONE")
                    r = await answer(1)
                    for _ in range(50):                    # the wrapper names the session after its system/init
                        if tabs and tabs[0]["sid"] == r[1]:
                            break
                        await asyncio.sleep(0.1)
                    ok &= self.step("own", not r[2] and tabs and tabs[0]["sid"] == r[1], t0,
                                    "" if tabs else "the wrapper didn't come to the daemon")
                    if not tabs:
                        return False
                    tab = tabs[0]

                    t0, n, uid = time.monotonic(), len(seen), str(uuid.uuid4())
                    await tell(tab, {"op": "send", "text": "Reply with exactly one word: TWO", "uuid": uid})
                    r = await answer(2)
                    new = seen[n:]
                    echo = any(x[0] == "user" and x[2] == uid for x in new)
                    began = any(x[0] == "init" for x in new)
                    ok &= self.step("send", echo and began and not r[2], t0,
                                    "" if echo and began else "echo %s, turn %s" % (echo, began))

                    t0 = time.monotonic()
                    await tell(tab, {"op": "model", "model": "sonnet"})
                    switched = await said("model switched", 1)
                    await c.query("Reply with exactly one word: THREE")
                    await answer(3)
                    model = next((x[1] for x in reversed(seen) if x[0] == "assistant"), "")
                    ok &= self.step("model", "sonnet" in model.lower(), t0, model if switched else model + ", no word from the wrapper")
                    await tell(tab, {"op": "model", "model": "haiku"})
                    await said("model switched", 2)

                    t0, got = time.monotonic(), []
                    for k, (level, word, want) in enumerate((("low", "FOUR", "low"), (None, "FIVE", "medium"))):
                        await tell(tab, {"op": "control", "request": {"subtype": "apply_flag_settings",
                                                                       "settings": {"effortLevel": level}}})
                        await said("apply_flag_settings done", k + 1)
                        await c.query("Reply with exactly one word: " + word)
                        r = await answer(4 + k)
                        for _ in range(50):                # the transcript is written a moment after the answer
                            e = efforts(r[1])
                            if len(e) >= 4 + k:
                                break
                            await asyncio.sleep(0.1)
                        got.append((e or [None])[-1])
                    ok &= self.step("effort", got == ["low", "medium"], t0, " → ".join(map(str, got)))
                finally:
                    reader.cancel()
        except asyncio.TimeoutError:
            done = {s["k"] for s in self.steps}
            k = next((k for k in TAB_STEPS[1:] if k not in done), "effort")
            kind = trouble(" ".join(err[-20:]))
            if kind:
                raise Trouble(kind, " ".join(err[-3:]))
            return self.step(k, False, t0, "no answer in %d s" % WAIT)
        except Trouble:
            raise
        except Exception as e:                          # the SDK couldn't start claude, or lost it
            kind = trouble(repr(e) + " " + " ".join(err[-20:]))
            if kind:
                raise Trouble(kind, repr(e))
            done = {s["k"] for s in self.steps}
            k = next((k for k in TAB_STEPS[1:] if k not in done), "effort")
            return self.step(k, False, time.monotonic(), "%s: %s" % (type(e).__name__, str(e)[:120]))
        finally:
            server.close()
        return ok

    # ---- race: the PermissionRequest hook and the window, without the wrapper (every session has both)

    async def race(self):
        """True — the first answer decides both ways; False — it doesn't; None — not clear (the model didn't call the
        tool, or Windows: its hooks run another way, and this hook command was never tried there)."""
        from claude_agent_sdk import ClaudeAgentOptions, ClaudeSDKClient, PermissionResultDeny, ResultMessage
        if os.name == "nt":
            self.steps.append({"k": "race", "ok": None, "s": 0, "note": "not checked on Windows"})
            return None
        hook = self.tmp / "hook.py"
        hook.write_text(HOOK)
        t_all = time.monotonic()
        verdicts, notes = [], []
        # A: the window says no in 0.5 s, the hook yes in 6 s → nothing runs; B: the hook yes in 0.5 s, the window no in
        # 8 s → the command runs at once and the late "no" changes nothing
        for name, hook_delay, window_delay, runs in (("A", 6, 0.5, False), ("B", 0.5, 8, True)):
            cwd = self.tmp / ("race-" + name)
            cwd.mkdir()
            mark = self.tmp / (name + ".mark")
            t = {}

            async def window(tool, inp, ctx, t=t, delay=window_delay):
                t.setdefault("window", time.time())
                await asyncio.sleep(delay)
                return PermissionResultDeny(message="Pult's check: the window says no")

            hooks = {"PermissionRequest": [{"matcher": "*", "hooks": [
                {"type": "command", "command": "%s %s" % (shlex.quote(self.py), shlex.quote(str(hook))), "timeout": 60}]}]}
            opts = ClaudeAgentOptions(cli_path=str(self.cli), cwd=str(cwd), model="haiku", permission_mode="default",
                                      can_use_tool=window, setting_sources=[], settings=json.dumps({"hooks": hooks}),
                                      env={"MARK": str(mark), "HOOK_DELAY": str(hook_delay), "PULT_OFF": "1",
                                           "PULT_SOCK": str(self.tmp / "none")}, stderr=lambda s: None)
            t0 = time.time()
            async with ClaudeSDKClient(options=opts) as c:
                await c.query("Run exactly this with the Bash tool: `echo hi > x.txt`. Do not retry if it is denied. "
                              "Then reply with one word: DONE or DENIED.")
                async for m in c.receive_response():
                    if isinstance(m, ResultMessage):
                        self.sids.add(m.session_id)
                        if m.is_error and trouble(str(m.result)):
                            raise Trouble(trouble(str(m.result)), str(m.result))
            await asyncio.sleep(max(0, window_delay + 1 - (time.time() - t0)))     # let the late answer try its worst
            asked = mark.exists() or "window" in t
            ran = (cwd / "x.txt").exists()
            if not asked:
                verdicts.append(None)
                notes.append("%s: no tool call" % name)
            else:
                verdicts.append(ran == runs)
                notes.append("%s: %s" % (name, "ran" if ran else "didn't run"))
        ok = None if None in verdicts else all(verdicts)
        self.steps.append({"k": "race", "ok": ok, "s": round(time.monotonic() - t_all, 1), "note": ", ".join(notes)})
        self.say("race", ok, ", ".join(notes))
        return ok


async def run(cli, wrapper, py, say=None):
    """The check of one claude binary: {"version", "ok" (writing into tabs works through the wrapper; None — couldn't
    check), "race" (True, False, None — not clear), "error" (login, limit, network, timeout, crash — or None), "steps":
    [{"k", "ok", "s", "note"}], "ts"}. A failed tab step gets a second try in a fresh session before it counts — one
    odd answer of the model is not a broken Claude Code."""
    ch = Check(cli, wrapper, py, say or (lambda *a: None))
    rep = {"version": ch.v, "ok": None, "race": None, "error": None, "steps": ch.steps, "ts": time.time()}
    try:
        ok = await ch.tab()
        if not ok:
            first = list(ch.steps)
            ch.steps.clear()
            ch.say("again", None)
            ok = await ch.tab()
            if not ok:
                rep["first"] = first
        rep["ok"] = bool(ok)
        rep["race"] = await ch.race()
    except Trouble as e:
        rep["error"], rep["note"] = e.kind, e.text[:200]
    except asyncio.CancelledError:
        rep["error"] = "timeout"
        raise
    except Exception as e:
        rep["error"], rep["note"] = "crash", ("%s: %s" % (type(e).__name__, e))[:200]
    finally:
        forget(ch.sids)
        shutil.rmtree(ch.tmp, ignore_errors=True)
    return rep
