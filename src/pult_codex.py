"""A second opinion from Codex (stage M, step 1; Q104–Q107): OpenAI's coding agent, on the owner's ChatGPT subscription,
reads what a task changed and writes its findings — in a read-only sandbox, asking nothing, changing nothing. Pult talks
to Codex's own program through its app-server protocol: JSON-RPC over stdio, one message per line, no "jsonrpc" field
(schema: `codex app-server generate-json-schema --out <folder>`; the protocol is marked experimental). The parts:
  • where Codex is and which version (find, version), and whether Pult may use it: a version VERIFIED lists, or one
    whose own schema still has what Pult uses (schema_ok) — ChatGPT.app updates its Codex by itself, alpha builds often;
  • what the task was (task_facts — the owner's words, Claude's last report, the files its edit tools wrote, from the
    transcript; git_base — the commit the folder stood at when the task began);
  • what Codex is told (instructions) and how its answer reads (parse — "[P1] title — file:lines" and the text);
  • one review (review): initialize → account/read → thread/start → review/start → its items → turn/completed;
  • what "Send to Claude" says in the session (message).
Standard library only; the daemon runs one review at a time (pult_api.api_second). The probe before it (2026-10-30,
Codex 0.148.0-alpha.9 from ChatGPT.app): the app-server from launchd's bare environment answers in 2–4 s with ~100–125 MB;
a review of a small change took 91 s, up to 339 MB and 7 processes, 4 % of the 5-hour window of Plus. Design:
docs/project.html, stage M.
"""
import asyncio
import collections
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path

import pult_render as R
import pult_web as PW

VERIFIED = ("0.148.0-alpha.9",)     # Codex versions a live review went through (2026-10-30); others — schema_ok
# where Codex lives when the PATH doesn't have it: ChatGPT.app carries its own (macOS); npm, Homebrew, a user's bin
APP = ("/Applications/ChatGPT.app/Contents/Resources/codex", "~/Applications/ChatGPT.app/Contents/Resources/codex")
MORE_PATH = ("/opt/homebrew/bin", "/usr/local/bin", "~/.local/bin", "~/.npm-global/bin", "~/.bun/bin")
EDIT_TOOLS = {"Edit": "file_path", "MultiEdit": "file_path", "Write": "file_path", "NotebookEdit": "notebook_path"}
EMPTY_TREE = "4b825dc642cb6eb9a060e54bf8d69288fbee4904"    # git's empty tree: "since the start" in a repository born later
ASK_MAX = 4000          # characters of the owner's first message for Codex
LATER_MAX = 600         # …of each later one, the last LATER_N of them
LATER_N = 12
REPORT_MAX = 4000       # …of Claude's last report
FILES_MAX = 60          # files named, at most
ANSWER = 30             # s for an answer before the review itself starts
TIMEOUT = 15 * 60       # s for the whole review (the probe's took 91 s)
LINE_MAX = 16 << 20     # bytes of one message from Codex: a command's whole output rides in its item
LANG_NAMES = {"en": "English", "ru": "Russian"}


class CodexError(Exception):
    """A review that didn't happen or didn't end. kind: "missing" (no Codex here), "start" (it didn't start or answer),
    "login" (not signed in to ChatGPT), "limit" (the subscription's limit), "timeout", "failed" (anything else)."""
    def __init__(self, kind, text=""):
        super().__init__(text or kind)
        self.kind, self.text = kind, str(text or "")


# ---------- where Codex is, which one, whether Pult may use it ----------

def find(env=None):
    """The Codex program to run, or None: PULT_CODEX when set (the tests and the stand give their own), else codex on
    the PATH or in the usual places of npm and Homebrew, else the one inside ChatGPT.app."""
    env = os.environ if env is None else env
    own = env.get("PULT_CODEX")
    if own:
        p = os.path.expanduser(own)
        return p if os.path.isfile(p) and os.access(p, os.X_OK) else None
    path = os.pathsep.join([env.get("PATH") or ""] + [os.path.expanduser(x) for x in MORE_PATH])
    p = shutil.which("codex", path=path)
    if p:
        return p
    if sys.platform == "darwin":
        for a in APP:
            a = os.path.expanduser(a)
            if os.path.isfile(a) and os.access(a, os.X_OK):
                return a
    return None


def version(path, timeout=15):
    """"codex-cli 0.148.0-alpha.9" → "0.148.0-alpha.9"; None if it doesn't say."""
    try:
        out = subprocess.run([path, "--version"], capture_output=True, text=True, timeout=timeout,
                             stdin=subprocess.DEVNULL).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    m = re.search(r"(\d+\.\d+\.\d+[\w.+-]*)", out or "")
    return m.group(1) if m else None


def _walk(x):
    yield x
    if isinstance(x, dict):
        for v in x.values():
            yield from _walk(v)
    elif isinstance(x, list):
        for v in x:
            yield from _walk(v)


def _methods(doc):
    """The method names a schema's messages may carry (each variant's "method": {"enum": [...]})."""
    out = set()
    for n in _walk(doc):
        if isinstance(n, dict) and isinstance(n.get("properties"), dict):
            m = n["properties"].get("method")
            if isinstance(m, dict):
                out.update(x for x in m.get("enum") or [] if isinstance(x, str))
    return out


def _variant(doc, kind, field):
    """Whether a schema has an object of type `kind` (its "type": {"enum": [kind]}) with the property `field`."""
    for n in _walk(doc):
        if isinstance(n, dict) and isinstance(n.get("properties"), dict):
            t = n["properties"].get("type")
            if isinstance(t, dict) and t.get("enum") == [kind] and field in n["properties"]:
                return True
    return False


def _enum_has(doc, name, value):
    """Whether the definition `name` of a schema lets `value` be one of its strings."""
    node = (doc.get("definitions") or {}).get(name) if isinstance(doc, dict) else None
    return any(isinstance(n, dict) and value in (n.get("enum") or []) for n in _walk(node or {}))


def schema_ok(path, timeout=90):
    """Whether this Codex's protocol still has everything a review uses — for a version VERIFIED doesn't list. Codex
    writes its own schema (a few hundred files, a second or two); → (True, "") or (False, what is missing)."""
    with tempfile.TemporaryDirectory(prefix="pult-codex-") as d:
        try:
            r = subprocess.run([path, "app-server", "generate-json-schema", "--out", d], capture_output=True,
                               text=True, timeout=timeout, stdin=subprocess.DEVNULL)
        except (OSError, subprocess.SubprocessError) as e:
            return False, "no schema: %s" % e
        if r.returncode != 0:
            return False, "no schema: exit %d" % r.returncode
        docs = {}
        for f in Path(d).rglob("*.json"):
            try:
                docs.setdefault(f.stem, json.loads(f.read_text(encoding="utf-8")))
            except (OSError, ValueError):
                continue
    missing = []
    client, notes = _methods(docs.get("ClientRequest") or {}), _methods(docs.get("ServerNotification") or {})
    missing += sorted({"initialize", "account/read", "thread/start", "review/start"} - client)
    missing += sorted({"item/completed", "turn/completed"} - notes)
    if not _variant(docs.get("ReviewStartParams") or {}, "custom", "instructions"):
        missing.append("review/start custom")
    if not _variant(docs.get("ItemCompletedNotification") or {}, "exitedReviewMode", "review"):
        missing.append("exitedReviewMode")
    ts = docs.get("ThreadStartParams") or {}
    if not {"cwd", "sandbox", "approvalPolicy"} <= set(ts.get("properties") or {}):
        missing.append("thread/start fields")
    elif not _enum_has(ts, "SandboxMode", "read-only") or not _enum_has(ts, "AskForApproval", "never"):
        missing.append("read-only, never")
    return (not missing), ", ".join(missing)


# ---------- what the task was ----------

def _epoch(ts):
    try:
        return datetime.fromisoformat(str(ts).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def _inside(p, cwd):
    """A path the task wrote, as Codex should read it: from the folder when it is inside, else as it is."""
    if not cwd or not os.path.isabs(p):
        return p
    root = os.path.realpath(cwd)
    real = os.path.realpath(p)
    return os.path.relpath(real, root).replace(os.sep, "/") if real == root or real.startswith(root + os.sep) else p


def task_facts(path, cwd=None):
    """What a task was, from its transcript: t0 — when it began (epoch; None for an empty one); asks — the owner's
    messages in order (Claude Code's reminders and commands left out, as the app shows them); report — Claude's last
    words; files — what its edit tools wrote (Edit, MultiEdit, Write, NotebookEdit), in the order first written, from
    the folder when inside it. A subagent's own steps are not here: git sees what they changed."""
    t0, asks, report, files = None, [], "", {}
    try:
        f = open(path, "rb")
    except OSError:
        return {"t0": None, "asks": [], "report": "", "files": []}
    with f:
        for line in f:
            try:
                e = json.loads(line)
            except ValueError:
                continue
            if not isinstance(e, dict):
                continue
            if t0 is None and e.get("timestamp"):
                t0 = _epoch(e["timestamp"])
            kind = e.get("type")
            if kind == "attachment":           # a message read in the middle of a turn (pult_web.transcript_page)
                att = e.get("attachment") if isinstance(e.get("attachment"), dict) else {}
                if att.get("type") == "queued_command" and att.get("commandMode", "prompt") == "prompt":
                    text = PW.user_text(att.get("prompt"))
                    if text and not R.task_notes(text):
                        asks.append(text)
                continue
            if kind not in ("user", "assistant") or e.get("isSidechain") or e.get("isMeta"):
                continue
            content = (e.get("message") or {}).get("content")
            if kind == "user":
                if isinstance(content, list) and any(isinstance(b, dict) and b.get("type") == "tool_result" for b in content):
                    continue
                text = PW.user_text(content)
                if text and not text.startswith(("<local-command-", "<command-")) and not R.task_notes(text):
                    asks.append(text)
                continue
            for b in content if isinstance(content, list) else [{"type": "text", "text": content or ""}]:
                if not isinstance(b, dict):
                    continue
                if b.get("type") == "text" and (b.get("text") or "").strip():
                    report = b["text"].strip()
                elif b.get("type") == "tool_use" and b.get("name") in EDIT_TOOLS:
                    inp = b.get("input") if isinstance(b.get("input"), dict) else {}
                    p = inp.get(EDIT_TOOLS[b["name"]])
                    if isinstance(p, str) and p:
                        files.setdefault(_inside(p, cwd), None)
    return {"t0": t0, "asks": asks, "report": report, "files": list(files)}


def git_base(cwd, t0):
    """The commit the folder stood at when the task began — the newest one before t0 on HEAD's first-parent line —
    → its id; EMPTY_TREE when every commit came later (or there is none yet); None when the folder isn't in git."""
    def git(*a):
        return subprocess.run(["git", "-C", cwd, *a], capture_output=True, text=True, timeout=20,
                              stdin=subprocess.DEVNULL)
    try:
        r = git("rev-parse", "--is-inside-work-tree")
        if r.returncode != 0 or r.stdout.strip() != "true":
            return None
        if t0 is None:
            return EMPTY_TREE
        r = git("rev-list", "-n", "1", "--first-parent", "--before=%d" % int(t0), "HEAD")
    except (OSError, subprocess.SubprocessError):
        return None
    return (r.stdout.strip() if r.returncode == 0 else "") or EMPTY_TREE


def _cut(s, n):
    s = str(s or "").strip()
    return s if len(s) <= n else s[:n - 1].rstrip() + "…"


def instructions(facts, base, lang="en", rules=False):
    """What Codex is told: the task in the owner's words, Claude's report, what changed and how to see it, what to
    report and in which language. Without the request and the report a second opinion argues with the task's own
    decisions — the probe's one finding did (2026-10-30) — so both go, and what they call deliberate isn't a finding.
    base — git_base's answer; rules — the folder has a CLAUDE.md (Codex itself reads only AGENTS.md)."""
    asks = facts.get("asks") or []
    parts = ["You are giving a second opinion on a task another coding agent (Claude Code) has just done in this folder. "
             "Read what it changed and report real problems only. Change nothing."]
    if asks:
        parts.append('The task, in the owner\'s words:\n"""\n%s\n"""' % _cut(asks[0], ASK_MAX))
        later = asks[1:][-LATER_N:]
        if later:
            parts.append("The owner's later messages in the same task, oldest first:\n" +
                         "\n".join("- " + _cut(a, LATER_MAX).replace("\n", " ") for a in later))
    if facts.get("report"):
        parts.append('Claude\'s report at the end:\n"""\n%s\n"""' % _cut(facts["report"], REPORT_MAX))
    files = facts.get("files") or []
    named = ", ".join(files[:FILES_MAX]) + (" and %d more" % (len(files) - FILES_MAX) if len(files) > FILES_MAX else "")
    if base:
        since = "the folder's first commit" if base == EMPTY_TREE else "commit %s" % base[:12]
        what = ("What changed: everything since %s, when the task began — `git diff %s -- .` (committed and not yet), "
                "and new files not in git yet (`git status --short -- .`)." % (since, base))
        if files:
            what += (" Claude's edit tools wrote these files: %s; commands may have changed more. Other sessions may "
                     "work in this folder at the same time: a change that touches none of the task's files is likely "
                     "theirs — leave it out." % named)
    elif files:
        what = ("This folder is not in git, so there is no history: the task wrote these files — read them as they are "
                "now: %s." % named)
    else:
        what = "This folder is not in git, and the task's own files are unknown: judge by the request and the report."
    parts.append(what)
    if rules:
        parts.append("The project's rules for agents are in CLAUDE.md: what it and the documents it points to record as "
                     "decided is deliberate.")
    parts.append("Report bugs, broken cases, regressions, security holes, and what the request asked for but the change "
                 "misses. Not style, not taste. What the owner's words or Claude's report call deliberate is not a "
                 "finding. For each finding: the file and lines, what breaks, how to fix it. Write in %s."
                 % LANG_NAMES.get(lang, "English"))
    return "\n\n".join(parts)


# ---------- Codex's answer ----------

_HEAD = re.compile(r"^(?:Full review comments|Review comments?):[ \t]*$", re.M)
_ITEM = re.compile(r"^- (?:\[[ xX]\] )?(?P<title>.*) — (?P<file>.+?):(?P<a>\d+)(?:-(?P<b>\d+))?[ \t]*$")   # the last " — "
_BARE = re.compile(r"^- (?:\[[ xX]\] )?(?P<title>.*?)[ \t]*$")                                          # no place given
_PRIO = re.compile(r"^\[(P[0-3])\]\s*")


def parse(text, cwd=None):
    """Codex's review as it writes it — its overall words, then "Review comment:" or "Full review comments:" and one
    "- [P2] title — /path/file:12-14" per finding with its text two spaces in (codex-rs, review_format) — →
    {"summary", "items": [{"prio" ("P0"–"P3" or ""), "title", "file" (from the folder when inside it, or None), "line",
    "end", "body"}]}. Words it didn't shape so stay whole in the summary."""
    text = str(text or "").strip()
    m = _HEAD.search(text)
    if not m:
        return {"summary": text, "items": []}
    items, cur = [], None
    for line in text[m.end():].split("\n"):
        g = (_ITEM.match(line) or _BARE.match(line)) if line.startswith("- ") else None
        if g:
            title, at = g.group("title").strip(), g.groupdict()
            p = _PRIO.match(title)
            cur = {"prio": p.group(1) if p else "", "title": title[p.end():] if p else title,
                   "file": _inside(at["file"], cwd) if at.get("file") else None,
                   "line": int(at["a"]) if at.get("a") else None, "end": int(at["b"]) if at.get("b") else None,
                   "body": []}
            items.append(cur)
        elif cur is not None:
            cur["body"].append(line[2:] if line.startswith("  ") else line)
    for it in items:
        it["body"] = "\n".join(it["body"]).strip()
    return {"summary": text[:m.start()].strip(), "items": items}


def where(it):
    """"search/index.py:41-58" — a finding's place as people write it; "" without one."""
    if not it.get("file"):
        return ""
    if it.get("line") is None:
        return it["file"]
    end = it.get("end")
    return "%s:%d" % (it["file"], it["line"]) + ("-%d" % end if end and end != it["line"] else "")


def message(items, model=None):
    """What "Send to Claude" says in the session: what to do with the findings, then each as Codex wrote it — in
    English like Pult's other words to Claude; the findings stay in the language they came in."""
    lines = ["A second opinion from Codex%s on this task's changes. Check each point: fix what is real, and say which "
             "ones are deliberate and why." % (" (%s)" % model if model else ""), ""]
    for n, it in enumerate(items, 1):
        loc = where(it)
        lines.append("%d. %s%s%s" % (n, "[%s] " % it["prio"] if it.get("prio") else "", it.get("title") or "",
                                     " — " + loc if loc else ""))
        lines += ["   " + b if b.strip() else "" for b in (it.get("body") or "").split("\n")]
    return "\n".join(lines).rstrip()


def window(limits):
    """account/rateLimits/read → the windows a review spent from: [{"pct", "mins", "reset"}], the shorter first."""
    rl = (limits or {}).get("rateLimits") or {}
    out = []
    for k in ("primary", "secondary"):
        w = rl.get(k)
        if isinstance(w, dict) and w.get("usedPercent") is not None:
            out.append({"pct": w.get("usedPercent"), "mins": w.get("windowDurationMins"), "reset": w.get("resetsAt")})
    return sorted(out, key=lambda w: w["mins"] or 0)


# ---------- one review over the app-server protocol ----------

class AppServer:
    """One `codex app-server` process: requests with their answers, notifications in a queue (None — it ended). A
    request of the server's own — an approval, a question — is declined: a review asks nothing, and nothing may hang
    waiting for an answer that never comes."""

    def __init__(self, proc):
        self.p = proc
        self.n = 0
        self.wait = {}
        self.events = asyncio.Queue()
        self.asked = []                    # the server's own requests, declined (the journal says which)
        self.err = collections.deque(maxlen=12)
        self.tasks = []

    @classmethod
    async def start(cls, path, cwd, env):
        try:
            p = await asyncio.create_subprocess_exec(path, "app-server", stdin=asyncio.subprocess.PIPE,
                                                     stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
                                                     cwd=cwd, env=env, limit=LINE_MAX)
        except OSError as e:
            raise CodexError("start", str(e))
        s = cls(p)
        s.tasks = [asyncio.create_task(s._read()), asyncio.create_task(s._read_err())]
        return s

    async def _read(self):
        try:
            while True:
                try:
                    line = await self.p.stdout.readline()
                except ValueError:             # longer than LINE_MAX: that one message is lost, not the review
                    continue
                if not line:
                    break
                try:
                    m = json.loads(line)
                except ValueError:
                    continue
                if not isinstance(m, dict):
                    continue
                if "method" in m and "id" in m:
                    self.asked.append(str(m.get("method")))
                    try:
                        await self.send({"id": m["id"], "error": {"code": -32601, "message": "Pult's review asks nothing"}})
                    except CodexError:
                        break
                elif "id" in m:
                    fut = self.wait.pop(m["id"], None)
                    if fut is not None and not fut.done():
                        fut.set_result(m)
                elif "method" in m:
                    self.events.put_nowait(m)
        except (ConnectionError, asyncio.CancelledError):
            pass
        finally:
            for fut in self.wait.values():
                if not fut.done():
                    fut.set_exception(CodexError("start", "Codex stopped: " + self.tail()))
            self.wait.clear()
            self.events.put_nowait(None)

    async def _read_err(self):
        try:
            while True:
                line = await self.p.stderr.readline()
                if not line:
                    break
                s = line.decode(errors="replace").strip()
                if s:
                    self.err.append(s)
        except (ValueError, ConnectionError, asyncio.CancelledError):
            pass

    def tail(self):
        return " | ".join(self.err)[-400:]

    async def send(self, m):
        try:
            self.p.stdin.write((json.dumps(m, ensure_ascii=False) + "\n").encode())
            await self.p.stdin.drain()
        except (ConnectionError, RuntimeError) as e:
            raise CodexError("start", "Codex stopped: %s %s" % (e, self.tail()))

    async def request(self, method, params, timeout=ANSWER):
        self.n += 1
        i, fut = self.n, asyncio.get_running_loop().create_future()
        self.wait[i] = fut
        await self.send({"id": i, "method": method, "params": params})
        try:
            m = await asyncio.wait_for(fut, timeout)
        except asyncio.TimeoutError:
            self.wait.pop(i, None)
            raise CodexError("start", "no answer to %s in %d s" % (method, timeout))
        if "error" in m:
            e = m.get("error") or {}
            raise CodexError(kind_of(e), "%s: %s" % (method, e.get("message") or e))
        return m.get("result") or {}

    async def close(self):
        """stdin closed — the app-server ends by itself and takes its commands with it; then a signal; then a kill."""
        try:
            self.p.stdin.close()
        except (OSError, RuntimeError):
            pass
        for stop in (None, self.p.terminate, self.p.kill):
            if stop is not None:
                try:
                    stop()
                except ProcessLookupError:
                    break
            try:
                await asyncio.wait_for(self.p.wait(), 3)
                break
            except asyncio.TimeoutError:
                continue
        for t in self.tasks:
            t.cancel()


def kind_of(err):
    """A Codex error → CodexError's kind: its codexErrorInfo when it has one, else its words."""
    info = (err or {}).get("codexErrorInfo") if isinstance(err, dict) else None
    if info == "usageLimitExceeded":
        return "limit"
    if info == "unauthorized":
        return "login"
    words = str((err or {}).get("message") if isinstance(err, dict) else err or "")
    if re.search(r"log ?in|sign ?in|unauthori[sz]ed|\b401\b", words, re.I):
        return "login"
    if re.search(r"usage limit|rate limit|\b429\b", words, re.I):
        return "limit"
    return "failed"


async def review(path, cwd, instructions_text, env=None, on_step=None, timeout=TIMEOUT, client="0"):
    """One second opinion: Codex in `cwd`, a read-only sandbox, no approvals asked; on_step(n) after each command it
    ran. → {"text", "model", "effort", "limits", "asked"}. Raises CodexError; cancelled — Codex is stopped."""
    s = await AppServer.start(path, cwd, env)
    loop = asyncio.get_running_loop()
    try:
        await s.request("initialize", {"clientInfo": {"name": "pult", "title": "Pult", "version": client}})
        await s.send({"method": "initialized"})
        acc = await s.request("account/read", {})
        if not acc.get("account"):
            raise CodexError("login", "not signed in")
        th = await s.request("thread/start", {"cwd": cwd, "sandbox": "read-only", "approvalPolicy": "never"})
        tid = (th.get("thread") or {}).get("id")
        if not tid:
            raise CodexError("failed", "thread/start gave no thread")
        await s.request("review/start", {"threadId": tid, "delivery": "inline",
                                         "target": {"type": "custom", "instructions": instructions_text}})
        text, said, err, steps = None, None, None, 0
        end = loop.time() + timeout
        while True:
            try:
                m = await asyncio.wait_for(s.events.get(), max(1.0, end - loop.time()))
            except asyncio.TimeoutError:
                raise CodexError("timeout", "no end in %d min" % (timeout // 60))
            if m is None:
                raise CodexError("failed", "Codex stopped: " + s.tail())
            prm = m.get("params") if isinstance(m.get("params"), dict) else {}
            if prm.get("threadId") not in (None, tid):
                continue
            meth = m.get("method")
            if meth == "item/completed":
                it = prm.get("item") if isinstance(prm.get("item"), dict) else {}
                if it.get("type") == "exitedReviewMode":
                    text = it.get("review")
                elif it.get("type") == "agentMessage" and it.get("text"):
                    said = it["text"]
                elif it.get("type") == "commandExecution":
                    steps += 1
                    if on_step:
                        on_step(steps)
            elif meth == "error" and not prm.get("willRetry"):
                err = prm.get("error")
            elif meth == "turn/completed":
                turn = prm.get("turn") if isinstance(prm.get("turn"), dict) else {}
                if turn.get("status") == "completed" and (text or said):
                    break
                e = turn.get("error") or err or {"message": turn.get("status") or "failed"}
                raise CodexError(kind_of(e), (e.get("message") if isinstance(e, dict) else str(e)) or "failed")
        try:
            limits = window(await s.request("account/rateLimits/read", None, timeout=10))
        except CodexError:
            limits = []
        return {"text": text if text is not None else said, "model": th.get("model"),
                "effort": th.get("reasoningEffort"), "limits": limits, "asked": list(s.asked)}
    finally:
        await s.close()
