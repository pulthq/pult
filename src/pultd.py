#!/usr/bin/env python3
"""Pult — Claude Code sessions on this computer, from Telegram.

The daemon (a per-user service: launchd on macOS, systemd --user on Linux). Three inputs:
  • a unix socket — session events from pult_hook.py (turn feed, result, permissions, questions);
  • Telegram — the owner's messages and button presses in a group with topics (topic = project);
  • the Agent SDK — sessions started or continued from Telegram.

Design and decisions: README.md at the repository root.
"""
import asyncio
import base64
import binascii
import collections
import importlib.util
import json
import os
import re
import secrets
import shlex
import shutil
import sqlite3
import sys
import time
import uuid
import zlib
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import httpx

import pult_attn as A
import pult_brief as B
import pult_hook
import pult_i18n as I
import pult_load as L
import pult_os
import pult_render as R
import pult_stt as STT
import pult_web as PW

HOME = Path(os.environ.get("PULT_HOME") or "~/.local/share/pult").expanduser()
ENV_FILE = Path(os.environ.get("PULT_ENV") or "~/.config/pult/env").expanduser()
SOCK = os.environ.get("PULT_SOCK") or str(HOME / "pult.sock")
HOOK_PY = os.environ.get("PULT_HOOK_PY") or sys.executable      # Pult's own Python: the hook needs nothing else
HOOK = str(HOME / "pult_hook.py")
CLAUDE_PROJECTS = Path("~/.claude/projects").expanduser()

SID_RE = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
SKIP_PREFIXES = ("-private-", "-tmp-", "-var-folders-")   # throwaway folders, not projects
AWAY_IDLE = 120          # idle here for longer than this (Pult.idle): the owner is away, notify with sound
EDIT_EVERY = 12          # s; edit a turn message no more often than this (Telegram's per-group limit)
MAX_RUNNING = 3          # turns from Telegram at once: Claude Code takes 250–450 MB each
MAX_DRIVEN = 5           # sessions from Telegram that hold a process
DRIVEN_IDLE = 20 * 60    # an idle session from Telegram is closed; it continues via resume
ASK_TIMEOUT = 6 * 3600   # how long to wait for a permission answer in a session from Telegram
FOCUS_IDLE = 2 * 3600   # a topic forgets its current session after this long without the owner's text there
VEHI = (10 * 60, 30 * 60, 60 * 60)   # long-turn milestones; with sound if the owner is away (decision 2026-10-16)
TICK = 60                # s; refresh "working N min" this often, even without events
NOW_LEN = 300            # characters of Claude's reply in the "now" line
STALE = 20 * 60          # s without events: check whether the session is alive (a tab may close without SessionEnd)
BRIEF_DIR = HOME / "brief"   # an empty folder the result-reading model runs in (pult_brief): no project, no settings
APP_ON = 45              # s: the app said "on screen" this recently — the owner is looking at it (stage V)
AWAY_LOCKABLE = 300      # s: where the screen lock can be read, away after this long without input (locked — at once)
PAGE_WAIT = 20           # s: a "your move" waits this long for the model's line before Telegram gets it
PAGE_OLD = 12 * 3600     # s: older outcomes are never paged (say, after a restart)
CATCH_GAP = 3600         # s: the app was closed this long — "While you were away" on the next open
CONTINUE = "Continue where you stopped: the usage limit has reset."   # said for the owner when the limit resets
USAGE_TTL = 60           # s to keep the usage answer: the app window is opened and refreshed often
LOAD_TTL = 4             # s to keep the snapshot of processes (~50 ms of ps): the app asks on every change
USAGE_EVERY = 15 * 60    # usage check for warnings, if there was work on the Mac
USAGE_NEAR_EVERY = 5 * 60   # …and near the threshold (from 70 %), more often
WARN_AT = (80, 95)       # % of a limit: a warning with sound in General (decision 2026-10-16)
UPLOAD_MAX = 6 * 1024 * 1024    # bytes of one picture sent from the app (the app shrinks them to ~200 KB first)
UPLOADS_MAX = 3                 # pictures per message
STT_MAX = 4 * 1024 * 1024       # bytes of one recording from the app (5 min at 32 kbit/s ≈ 1.2 MB; base64 must fit the 8 MB frame)
PERMISSION_MODE = os.environ.get("PULT_PERMISSION_MODE", "auto")
VERSION = "0.9.22"
LOG_FILE = Path(os.environ.get("PULT_LOG") or pult_os.LOG_DIR / "pult.log").expanduser()
SETTINGS = Path("~/.claude/settings.json").expanduser()
TAB_CONF = Path("~/.config/pult/tab.json").expanduser()          # tab wrapper: folders and verified versions
EDITOR_DIRS = pult_os.editor_dirs()     # VS Code and its forks (and their remote side): where the tab wrapper is set
EXT_DIRS = pult_os.extension_dirs()
TAB_CHECK_EVERY = 3600   # s; check whether a new Claude Code extension version is out
PREFS = {"vehi": True, "mode": "auto", "lang": None, "brief": False, "pager": None}   # owner prefs: milestones, location
# (auto/mac/phone), language, a model's line for each result, Telegram as a pager (None — on where the app is set up)
MODES = ("auto", "mac", "phone")
REPO_URL = os.environ.get("PULT_REPO_URL") or "https://github.com/pulthq/pult"   # where /feedback sends bugs and ideas
MODEL_RE = re.compile(r"[A-Za-z0-9][\w.\-\[\]]{0,63}")        # a model alias or id for a session from Telegram
EFFORTS = ("low", "medium", "high", "xhigh", "max")
KEEP = object()        # an api_model argument the app did not send: that half of the choice stays as it is


async def sdk_effort(client, effort):
    """Effort of a running SDK session: the apply_flag_settings control request (effortLevel in the flag layer, this
    process only; None — back to the settings). The Python SDK has no method for it yet, so its generic request is
    used; probe tests/probe_effort.py, Claude Code 2.1.301."""
    send = getattr(getattr(client, "_query", None), "_send_control_request", None)
    if send is None:
        raise RuntimeError("the SDK has no control requests")
    await send({"subtype": "apply_flag_settings", "settings": {"effortLevel": effort}})


def log(*a):
    print(time.strftime("%Y-%m-%d %H:%M:%S"), *a, flush=True)


def find_claude():
    """Claude Code for `claude agents`: PULT_CLAUDE_BIN, else `claude` on PATH (the native installer, Homebrew,
    npm), else the one inside the Agent SDK — it has the same command."""
    found = os.environ.get("PULT_CLAUDE_BIN") or shutil.which("claude")
    if found:
        return found
    spec = importlib.util.find_spec("claude_agent_sdk")
    for d in (spec.submodule_search_locations or []) if spec else []:
        p = os.path.join(d, "_bundled", "claude")
        if os.access(p, os.X_OK):
            return p
    return "claude"


CLAUDE_BIN = find_claude()


def load_env(path=ENV_FILE):
    env = {}
    try:
        for line in Path(path).read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip().strip("'\"")
    except FileNotFoundError:
        pass
    env.update({k: v for k, v in os.environ.items() if k.startswith("PULT_")})
    return env


def env_mtime():
    try:
        return ENV_FILE.stat().st_mtime
    except OSError:
        return None


def sanitize(path):
    return re.sub(r"[^a-zA-Z0-9]", "-", path)


def decode_pkey(pkey, root="/"):
    """Folder name ~/.claude/projects/<pkey> → the real path (by searching the disk; '-' is ambiguous)."""
    def walk(d, rest, depth):
        if depth > 10:
            return None
        try:
            entries = os.listdir(d)
        except OSError:
            return None
        for e in sorted(entries):
            s = sanitize(e)
            if rest == s:
                return os.path.join(d, e)
            if rest.startswith(s + "-") and os.path.isdir(os.path.join(d, e)):
                r = walk(os.path.join(d, e), rest[len(s) + 1:], depth + 1)
                if r:
                    return r
        return None
    return walk(root, pkey[1:], 0) if pkey.startswith("-") else None


def skip_pkey(pkey):
    return not pkey or pkey.startswith(SKIP_PREFIXES) or len(pkey) > 200


def command_of(text):
    t = (text or "").strip()
    if not t.startswith("/"):
        return None, t
    head, _, rest = t.partition(" ")
    return head.split("@")[0].lower(), rest.strip()


def _ts(s):
    try:
        return datetime.fromisoformat(str(s).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return 0.0


def last_reply(path, since=0.0, tail=512 * 1024):
    """Claude's last reply in the session transcript, no earlier than since — the "now" line of the turn message.
    The transcript is only read, and only from the end: session files can be ten megabytes or so."""
    try:
        with open(path, "rb") as f:
            f.seek(0, 2)
            f.seek(max(0, f.tell() - tail))
            data = f.read()
    except OSError:
        return None
    for line in reversed(data.split(b"\n")):
        if b'"assistant"' not in line:
            continue
        try:
            e = json.loads(line)
        except ValueError:
            continue
        if e.get("type") != "assistant" or e.get("isSidechain"):
            continue
        if since and _ts(e.get("timestamp")) < since:
            return None
        content = (e.get("message") or {}).get("content")
        if isinstance(content, str):
            text = content
        else:
            text = "\n".join(b.get("text", "") for b in content or [] if isinstance(b, dict) and b.get("type") == "text")
            if not text.strip() and e.get("thinkingDisplay") == "updates":
                # Claude's words about its progress (the tab's "summary" lines) are a reply too
                text = "\n".join(b.get("thinking", "") for b in content or []
                                 if isinstance(b, dict) and b.get("type") == "thinking")
        if text.strip():
            return text
    return None


CTX_RESERVE = 13000        # VS Code's context gauge: used ÷ (window − min(maxOutputTokens, 20000) − 13000) (webview 2.1.301)
CTX_OUT_CAP = 20000


def ctx_from_usage(model_usage, model=None):
    """The context window of a turn's main model from the result's modelUsage → (window, max output tokens), or None.
    The main model is the one named by system/init; without it — the entry that read the most."""
    mu = model_usage if isinstance(model_usage, dict) else {}
    entry = mu.get(model) if model else None
    if not isinstance(entry, dict):
        entry = max((v for v in mu.values() if isinstance(v, dict)), default=None,
                    key=lambda v: (v.get("inputTokens") or 0) + (v.get("cacheReadInputTokens") or 0))
    if not entry or not entry.get("contextWindow"):
        return None
    return int(entry["contextWindow"]), int(entry.get("maxOutputTokens") or 0)


def model_key(model):
    """A model id without its date: the transcript says claude-opus-5-5-20260301, the result's modelUsage may say
    claude-opus-5-5 — the same window."""
    return re.sub(r"-\d{8}$", "", str(model or ""))


def ctx_usable(window, max_out):
    """How much of the window counts as usable — the same number VS Code divides by."""
    return max(1, window - min(max_out, CTX_OUT_CAP) - CTX_RESERVE)


def image_kind(blob):
    """png / jpg / gif / webp by the first bytes of the file, else None: only pictures are taken from the app."""
    if blob[:8] == b"\x89PNG\r\n\x1a\n":
        return "png"
    if blob[:3] == b"\xff\xd8\xff":
        return "jpg"
    if blob[:6] in (b"GIF87a", b"GIF89a"):
        return "gif"
    if blob[:4] == b"RIFF" and blob[8:12] == b"WEBP":
        return "webp"
    return None


def prompt_started(path, tail=512 * 1024):
    """When the turn in progress began: the time of the owner's last prompt in the transcript. For a turn Pult
    learns about from its steps (Pult restarted mid-turn, a tab opened before Pult) — otherwise "working 14 s"
    after a restart. Messages absorbed mid-turn (queued_command) and tool results don't count."""
    try:
        with open(path, "rb") as f:
            f.seek(0, 2)
            f.seek(max(0, f.tell() - tail))
            data = f.read()
    except OSError:
        return None
    for line in reversed(data.split(b"\n")):
        if b'"user"' not in line:
            continue
        try:
            e = json.loads(line)
        except ValueError:
            continue
        if e.get("type") != "user" or e.get("isSidechain") or e.get("isMeta"):
            continue
        content = (e.get("message") or {}).get("content")
        blocks = content if isinstance(content, list) else [{"type": "text", "text": content or ""}]
        if any(isinstance(b, dict) and b.get("type") == "tool_result" for b in blocks):
            continue
        if any(isinstance(b, dict) and b.get("type") == "text" and b.get("text", "").strip() for b in blocks):
            return _ts(e.get("timestamp")) or None
    return None


def when(ts):
    """Format as "14:05", "yesterday 14:05" or "12.10 14:05" — when the session was active."""
    if not ts:
        return "—"
    t, now = time.localtime(ts), time.localtime()
    if t.tm_yday == now.tm_yday and t.tm_year == now.tm_year:
        return time.strftime("%H:%M", t)
    if time.localtime(ts + 86400).tm_yday == now.tm_yday:
        return I.T("when.yesterday", hm=time.strftime("%H:%M", t))
    return time.strftime("%d.%m %H:%M", t)


def pid_alive(pid):
    try:
        os.kill(int(pid), 0)
        return True
    except ProcessLookupError:
        return False
    except (PermissionError, ValueError, TypeError):
        return True


def vehi_marks():
    """Long-turn milestones: 10, 30, 60 min, then every hour."""
    yield from VEHI
    m = VEHI[-1]
    while True:
        m += 3600
        yield m


# ---------- Telegram ----------

class TgError(Exception):
    def __init__(self, method, desc, code=None, retry_after=None):
        super().__init__("%s: %s" % (method, desc))
        self.desc = str(desc or "")
        self.code = code
        self.retry_after = retry_after


class Tg:
    """Bot API. Through the proxy first if one is set (PULT_PROXY); if that fails, directly (and back again)."""

    def __init__(self, token, proxy=None, transport=None):
        self.base = "https://api.telegram.org/bot%s/" % token
        self.file_base = "https://api.telegram.org/file/bot%s/" % token
        t = httpx.Timeout(70, connect=10)
        if transport is not None:
            self.clients = [httpx.AsyncClient(transport=transport, timeout=t)]
        else:
            self.clients = ([httpx.AsyncClient(proxy=proxy, timeout=t)] if proxy else []) + \
                           [httpx.AsyncClient(timeout=t)]
        self.cur = 0

    async def _post(self, url, **kw):
        last = None
        for k in range(len(self.clients)):
            i = (self.cur + k) % len(self.clients)
            try:
                r = await self.clients[i].post(url, **kw)
            except (httpx.ConnectError, httpx.ProxyError, httpx.ConnectTimeout, httpx.ReadError) as e:
                last = e
                continue
            if i != self.cur:
                log("Telegram: route switched to", "proxy" if i == 0 and len(self.clients) > 1 else "direct")
                self.cur = i
            return r
        raise TgError(url.rsplit("/", 1)[-1], "no connection: %r" % last)

    async def call(self, method, files=None, timeout=None, **params):
        data = {}
        for k, v in params.items():
            if v is None:
                continue
            if isinstance(v, bool):
                v = "true" if v else "false"
            data[k] = json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else v
        r = await self._post(self.base + method, data=data, files=files,
                             timeout=timeout if timeout else httpx.USE_CLIENT_DEFAULT)
        j = r.json()
        if not j.get("ok"):
            raise TgError(method, j.get("description"), j.get("error_code"),
                          (j.get("parameters") or {}).get("retry_after"))
        return j["result"]

    async def download(self, file_id):
        info = await self.call("getFile", file_id=file_id)
        for k in range(len(self.clients)):
            i = (self.cur + k) % len(self.clients)
            try:
                r = await self.clients[i].get(self.file_base + info["file_path"], timeout=180)
                r.raise_for_status()
                return info["file_path"], r.content
            except httpx.HTTPError:
                continue
        raise TgError("getFile", "download failed")


class Outbox:
    """Everything posted to the group goes through this queue: Telegram lets ~20 messages a minute into a group,
    and edits count too. Questions and results go first; turn edits go last
    and are coalesced: only the latest state of a message is sent."""

    def __init__(self, rate=18, burst=5):
        self.q = asyncio.PriorityQueue()
        self.seq = 0
        self.per = 60.0 / rate
        self.burst = burst
        self.tokens = float(burst)
        self.t = time.monotonic()
        self.pause_until = 0.0
        self.edits = {}          # message_id → edit function with the latest text

    def _put(self, prio, fn, fut):
        self.seq += 1
        self.q.put_nowait((prio, self.seq, fn, fut))

    async def submit(self, prio, fn):
        fut = asyncio.get_running_loop().create_future()
        self._put(prio, fn, fut)
        return await fut

    def edit(self, key, fn, prio=8):
        fresh = key not in self.edits
        self.edits[key] = fn
        if fresh or prio < 8:
            self._put(prio, ("edit", key), None)

    async def _token(self):
        while True:
            now = time.monotonic()
            if now < self.pause_until:
                await asyncio.sleep(self.pause_until - now)
                continue
            self.tokens = min(self.burst, self.tokens + (now - self.t) / self.per)
            self.t = now
            if self.tokens >= 1:
                self.tokens -= 1
                return
            await asyncio.sleep((1 - self.tokens) * self.per)

    async def run(self):
        while True:
            prio, seq, fn, fut = await self.q.get()
            if isinstance(fn, tuple):
                fn = self.edits.pop(fn[1], None)
                if fn is None:
                    continue           # this message has already been superseded by a newer edit
            await self._token()
            try:
                res = await fn()
                if fut and not fut.done():
                    fut.set_result(res)
            except TgError as e:
                if e.retry_after:
                    log("Telegram asks to wait %s s" % e.retry_after)
                    self.pause_until = time.monotonic() + float(e.retry_after) + 0.5
                    self._put(prio, fn, fut)
                    continue
                if fut and not fut.done():
                    fut.set_exception(e)
                else:
                    log("Telegram:", e)
            except Exception as e:
                if fut and not fut.done():
                    fut.set_exception(e)
                else:
                    log("send failed:", repr(e))


# ---------- state ----------

SCHEMA = """
CREATE TABLE IF NOT EXISTS kv(k TEXT PRIMARY KEY, v TEXT);
CREATE TABLE IF NOT EXISTS topics(pkey TEXT PRIMARY KEY, path TEXT, name TEXT, thread INTEGER);
CREATE TABLE IF NOT EXISTS sessions(sid TEXT PRIMARY KEY, pkey TEXT, path TEXT, title TEXT,
    driven INTEGER DEFAULT 0, last_seen REAL);
CREATE TABLE IF NOT EXISTS msgs(msg INTEGER PRIMARY KEY, sid TEXT, kind TEXT, ts REAL);
"""


class Store:
    def __init__(self, path):
        self.db = sqlite3.connect(str(path), isolation_level=None)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)

    def get(self, k, default=None):
        r = self.db.execute("SELECT v FROM kv WHERE k=?", (k,)).fetchone()
        return json.loads(r["v"]) if r else default

    def put(self, k, v):
        self.db.execute("INSERT OR REPLACE INTO kv VALUES(?,?)", (k, json.dumps(v)))

    def topic(self, pkey):
        return self.db.execute("SELECT * FROM topics WHERE pkey=?", (pkey,)).fetchone()

    def topic_by_thread(self, thread):
        return self.db.execute("SELECT * FROM topics WHERE thread=?", (thread,)).fetchone()

    def set_topic(self, pkey, path, name, thread):
        self.db.execute("INSERT OR REPLACE INTO topics VALUES(?,?,?,?)", (pkey, path, name, thread))

    def session(self, sid):
        return self.db.execute("SELECT * FROM sessions WHERE sid=?", (sid,)).fetchone()

    def touch_session(self, sid, pkey, path=None, driven=None, title=None):
        cur = self.session(sid)
        if cur is None:
            self.db.execute("INSERT INTO sessions VALUES(?,?,?,?,?,?)",
                            (sid, pkey, path, title, int(bool(driven)), time.time()))
            return
        self.db.execute("UPDATE sessions SET pkey=?, path=coalesce(?,path), title=coalesce(?,title),"
                        " driven=max(driven,?), last_seen=? WHERE sid=?",
                        (pkey or cur["pkey"], path, title, int(bool(driven)), time.time(), sid))

    def map_msg(self, msg, sid, kind):
        self.db.execute("INSERT OR REPLACE INTO msgs VALUES(?,?,?,?)", (msg, sid, kind, time.time()))

    def msg(self, msg):
        return self.db.execute("SELECT * FROM msgs WHERE msg=?", (msg,)).fetchone()

    def prune(self, days=60):
        self.db.execute("DELETE FROM msgs WHERE ts < ?", (time.time() - days * 86400,))


# ---------- live session state ----------

class Turn:
    def __init__(self, prompt=None, reply_to=None):
        self.started = self.last = time.time()
        self.prompt = prompt
        self.reply_to = reply_to
        self.n = 0
        self.msg = None
        self.created = asyncio.get_running_loop().create_future()
        self.changed = asyncio.Event()
        self.done = None          # (icon, time) when the turn ended
        self.now = None           # Claude's latest reply in this turn
        self.muted = False        # 🔕 — no milestones until the turn ends
        self.vehi = None
        self.note = None          # the turn was started by Claude itself: "⚙️ Background task finished …"
        self.here = False         # the owner typed the prompt at this computer (not from Telegram or the app)


class Req:
    """An open permission request or question — waits for a button in Telegram or an answer on the Mac."""

    def __init__(self, sid, tool, inp, suggestions):
        self.rid = secrets.token_hex(4)
        self.sid = sid
        self.tool = tool
        self.inp = inp if isinstance(inp, dict) else {}
        self.suggestions = suggestions or []
        self.kind = "ask" if tool == "AskUserQuestion" else "plan" if tool == "ExitPlanMode" else "perm"
        self.fut = asyncio.get_running_loop().create_future()
        self.msgs = []            # [(message_id, question index or None)]
        self.chosen = {}          # question → [answers]
        self.picks = {}           # multi-select question → checked options
        self.ts = time.time()     # since when it waits for the owner
        self.paged = False        # posted to Telegram (as a pager, only when the owner is neither in the app nor here)


class Live:
    def __init__(self, sid, pkey):
        self.sid = sid
        self.pkey = pkey
        self.cwd = None
        self.title = None
        self.named = False        # title is a real name (set by the user or by Claude Code), not the prompt
        self.transcript = None
        self.driven = False
        self.turn = None
        self.pending = {}
        self.bg = []              # background tasks still running after the turn (background_tasks in Stop)
        self.bg_seen = {}         # task id → when Pult first saw it running
        self.pid = None           # the session's claude process: the hook's parent (probe_load.py)


class Job:
    """A task without Claude — `pult run -- command`."""

    def __init__(self, rid, cmd, cwd, pid, pkey):
        self.rid, self.cmd, self.cwd, self.pid, self.pkey = rid, cmd, cwd, pid, pkey
        self.started = time.time()
        self.last = None              # last line of output
        self.code = None
        self.ended = None
        self.tail = []
        self.msg = None
        self.muted = False
        self.watch = None


def same_input(a, b):
    a = {k: v for k, v in (a or {}).items() if k != "answers"}
    b = {k: v for k, v in (b or {}).items() if k != "answers"}
    return json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)


# ---------- sessions from Telegram ----------

class Driven:
    """A session Pult drives through the Agent SDK: new, continued or a copy (fork)."""

    def __init__(self, d, sid, path, resume=None, fork=False, model=None, effort=None):
        self.d = d
        self.sid = sid
        self.path = path
        self.resume = resume
        self.fork = fork
        self.want_model = model       # the owner's choice for this session (None — Claude Code's settings)
        self.want_effort = effort
        self.q = asyncio.Queue()
        self.client = None
        self.asking = False       # the query is sent, no result in the SDK stream yet
        self.result = asyncio.Event()
        self.bg = set()           # the process's background tasks: while they run, the process is not closed
        self.model = None         # the main model, from system/init: picks the entry in the result's modelUsage
        self.task = asyncio.create_task(self.run())

    @property
    def busy(self):
        """A turn is running — our own query, or one Claude Code started itself when a background task finished."""
        lv = self.d.live.get(self.sid)
        return self.asking or bool(lv and lv.turn)

    async def _wait_hook(self, tool, inp, ctx):
        # The decision arrives via the PermissionRequest hook (buttons in Telegram) and cancels this call.
        from claude_agent_sdk import PermissionResultDeny
        await asyncio.sleep(ASK_TIMEOUT)
        return PermissionResultDeny(message="No answer from Telegram within %d h" % (ASK_TIMEOUT // 3600))

    def options(self):
        from claude_agent_sdk import ClaudeAgentOptions
        hooks = pult_hook.hooks_config("PULT_INJECTED=1 %s %s" % (shlex.quote(HOOK_PY), shlex.quote(HOOK)))
        # system_prompt — Claude Code's standard one: without it the SDK starts the session with an empty system
        # prompt, and Claude behaves differently than in the VS Code tab (seen 2026-10-15)
        kw = dict(cwd=self.path, system_prompt={"type": "preset", "preset": "claude_code"},
                  permission_mode=PERMISSION_MODE, can_use_tool=self._wait_hook,
                  setting_sources=["user", "project", "local"], settings=json.dumps({"hooks": hooks}),
                  # entrypoint: the SDK sets sdk-py, and VS Code hides sdk-* sessions from its list (a filter
                  # in extension 2.1.300). Without a terminal, Claude Code itself turns cli into sdk-cli;
                  # claude-vscode is kept: the session shows up in the Claude tab and can be continued on the Mac
                  env={"PULT_DRIVEN": "1", "PULT_SOCK": SOCK, "CLAUDE_CODE_ENTRYPOINT": "claude-vscode"},
                  stderr=lambda s: None)
        if getattr(self, "want_model", None):
            kw["model"] = self.want_model
        if getattr(self, "want_effort", None):
            kw["effort"] = self.want_effort
        if self.resume:
            kw["resume"] = self.resume
        if self.fork:
            kw["fork_session"] = True
        if not self.resume or self.fork:
            kw["session_id"] = self.sid
        return ClaudeAgentOptions(**kw)

    async def read(self, c):
        """The whole SDK stream, not just up to our query's result: when a background task finishes, Claude Code
        starts a turn by itself, and its result would otherwise go to the next query (probe 2026-10-16, 2.1.301)."""
        from claude_agent_sdk import ResultMessage, SystemMessage
        try:
            async for m in c.receive_messages():
                if isinstance(m, ResultMessage):
                    if m.is_error:
                        await self.d.notice(self.sid, self.d.t("err.turn", err=R.esc(R.short(m.result or m.subtype, 600))),
                                            self.d.expect.get(self.sid))
                    ctx = ctx_from_usage(m.model_usage, self.model)
                    if ctx:
                        self.d.set_ctx(self.sid, *ctx, model=self.model)
                    self.result.set()
                elif isinstance(m, SystemMessage) and m.subtype == "init":
                    self.model = m.data.get("model") or self.model
                elif isinstance(m, SystemMessage) and m.subtype == "background_tasks_changed":
                    self.bg = {t.get("task_id") for t in m.data.get("tasks") or [] if isinstance(t, dict)}
        finally:
            self.result.set()                    # the process has ended, so the query doesn't wait forever
            self.q.put_nowait(None)

    async def run(self):
        from claude_agent_sdk import ClaudeSDKClient
        try:
            async with ClaudeSDKClient(options=self.options()) as c:
                self.client = c
                reader = asyncio.create_task(self.read(c))
                try:
                    while True:
                        try:
                            item = await asyncio.wait_for(self.q.get(), timeout=DRIVEN_IDLE)
                        except asyncio.TimeoutError:
                            if self.busy or self.bg:
                                continue         # a background task lives as long as the process
                            break
                        if item is None:
                            break
                        text, origin = item
                        async with self.d.run_sem:
                            self.asking = True
                            self.result.clear()
                            self.d.expect[self.sid] = origin
                            try:
                                await c.query(text)
                                await self.result.wait()
                            finally:
                                self.asking = False
                                self.d.expect.pop(self.sid, None)
                finally:
                    reader.cancel()
                if reader.done() and not reader.cancelled():
                    if reader.exception():
                        raise reader.exception()
                    log("Telegram session %s: the Claude process exited by itself" % self.sid[:8])
        except Exception as e:
            log("Telegram session %s crashed: %r" % (self.sid[:8], e))
            await self.d.notice(self.sid, self.d.t("err.session", err=R.esc(R.short(repr(e), 600))))
        finally:
            self.d.driven.pop(self.sid, None)
            self.client = None


# ---------- daemon ----------

class Pult:
    def __init__(self, env, tg, store):
        self.env = env
        self.tg = tg
        self.store = store
        self.allowed = {int(x) for x in re.split(r"[,\s]+", env.get("PULT_ALLOWED_USER_IDS", "")) if x.strip()}
        self.chat = store.get("chat")
        self.out = Outbox()
        self.live = {}
        self.driven = {}
        self.expect = {}               # sid → the owner's message the turn replies to
        self.tabs = {}                 # wrapper pid → a VS Code tab we can write into (stage 2)
        self.tab_expect = {}           # sid → (owner's message, text) sent into the tab
        self.offers = {}               # button token → data (session copy, open a session, project)
        self.req_by_rid = {}
        self.req_by_msg = {}
        self.topic_locks = {}
        self.cards_seen = set()        # topics whose card was checked since start (Pult.topic_card)
        self.run_sem = asyncio.Semaphore(MAX_RUNNING)
        self._idle = (0.0, None)
        self.here_seen = time.monotonic()   # the owner's last action in a session here (Pult.idle)
        self._agents = (0.0, [])
        self._procs = (0.0, None)
        self.web = None                # pult_web.Web — the web app, if a relay is configured
        self.stats = PW.Stats()        # model, thinking, session tokens — for the app
        self.day_tokens = PW.DayTokens(CLAUDE_PROJECTS, skip_pkey)   # today's tokens per project
        self.activity = 0.0            # time of the last session event: without work, usage doesn't grow
        self._usage = None
        self._usage_lock = asyncio.Lock()
        self.recent = collections.deque(maxlen=20)   # latest results — for the app's Home screen
        self.attn = A.Attn(store)      # whose move: each session's last outcome and whether the owner has seen it
        for r in self.attn.rec.values():
            r.setdefault("paged", True)    # outcomes from before this start were announced then: no burst of calls now
        self.brief_sem = asyncio.Semaphore(1)        # the result-reading model: one request at a time
        self.app_on, self.app_vis = 0.0, False       # the app's last "on screen" and whether it is visible now
        self.app_seen = store.get("app_seen") or 0.0     # the app was last on the screen (kept across restarts)
        self.catch_from = store.get("catch_from")    # "While you were away" counts from here during this visit
        self._locked = (0.0, None)
        self._status = {}                           # pkey → the first line of its topic's pinned card (cards_status)
        self.jobs = {}                 # tasks without Claude: running
        self.jobs_done = collections.deque(maxlen=10)
        self.new_next = set()          # topics where a bare /new was sent: the next text there starts a new session
        self.ctx = store.get("ctx") or {}   # sid → [context window, max output tokens], from each turn's result
        self.ctx_model = store.get("ctx_model") or {}   # model → the same: a session that hasn't reported yet borrows it
        self.choice = store.get("choice") or {}         # sid → {"model", "effort"} the owner picked for a session from Telegram
        self._env_mt = env_mtime()     # the settings file as of now: a key added later by `pult stt` is picked up (refresh_stt)
        self.stt = self.make_stt()     # pult_stt.Stt when PULT_STT_KEY is set — voice input

    # ----- this computer's environment -----

    async def _run(self, *cmd, timeout=10):
        try:
            p = await asyncio.create_subprocess_exec(*cmd, stdout=asyncio.subprocess.PIPE,
                                                     stderr=asyncio.subprocess.DEVNULL)
        except OSError:
            return ""
        try:
            out, _ = await asyncio.wait_for(p.communicate(), timeout)
        except asyncio.TimeoutError:
            p.kill()
            return ""
        return out.decode(errors="replace")

    async def input_idle(self):
        """Seconds without keyboard and mouse input here, or None if the system can't tell; asked every 5 s at most."""
        t, v = self._idle
        if time.monotonic() - t < 5:
            return v
        v = await asyncio.to_thread(pult_os.input_idle)
        self._idle = (time.monotonic(), v)
        return v

    async def idle(self):
        """How long the owner hasn't used this computer: keyboard and mouse, where the system tells; otherwise the
        time since their last action in a session here — a prompt typed, a permission answered (or Pult's start)."""
        v = await self.input_idle()
        return v if v is not None else time.monotonic() - self.here_seen

    def seen_here(self, lv):
        if not lv.driven:
            self.here_seen = time.monotonic()

    async def screen_locked(self):
        """The screen is locked: True / False, or None where the system can't tell (pult_os); asked every 5 s at most."""
        t, v = self._locked
        if time.monotonic() - t < 5:
            return v
        v = await asyncio.to_thread(pult_os.screen_locked)
        self._locked = (time.monotonic(), v)
        return v

    async def away(self):
        """The owner is away from this computer: the screen is locked, or no keyboard and mouse for a while — 2 min,
        or 5 min where the lock can be read (someone watching Claude work without touching anything is still here:
        the owner's remark 2026-10-18, Q20); without input data — no action of theirs in a session for 2 min."""
        if "PULT_FORCE_AWAY" in self.env:
            return self.env["PULT_FORCE_AWAY"] == "1"
        locked = await self.screen_locked()
        if locked:
            return True
        idle = await self.input_idle()
        if idle is None:
            return time.monotonic() - self.here_seen >= AWAY_IDLE
        return idle >= (AWAY_LOCKABLE if locked is False else AWAY_IDLE)

    async def where(self):
        """Where the owner is (stage V): "app" — the app is on their screen, "mac" — at this computer, "away"."""
        if self.app_vis and time.time() - self.app_on < APP_ON:
            return "app"
        return "away" if await self.away() else "mac"

    def pager(self):
        """Telegram as a pager (stage V, Q22 «а»): new messages only for "your move" the owner doesn't see and for their
        own dialog in a topic. On by default where the app is set up; without the app Telegram is the only screen and
        keeps the whole feed."""
        v = self.prefs()["pager"]
        return bool(self.app_web_url()) if v is None else bool(v)

    async def page_now(self):
        """Whether a "your move" goes to Telegram now: 📱 always, 💻 never, 🔄 only when the owner is neither in the
        app nor at the computer."""
        m = self.mode()
        if m != "auto":
            return m == "phone"
        return await self.where() == "away"

    def prefs(self):
        stored = self.store.get("prefs") or {}
        if "mode" not in stored and stored.get("sound_at_mac"):
            stored = dict(stored, mode="phone")       # before 0.6: "sound at the Mac too" is the same as "on my phone"
        return dict(PREFS, **{k: v for k, v in stored.items() if k in PREFS})

    def mode(self):
        m = self.prefs()["mode"]
        return m if m in MODES else "auto"

    def lang(self):
        """The language of messages: chosen in the settings, otherwise the owner's Telegram language. Also makes it
        the current language for rendering (pult_render uses pult_i18n's current language)."""
        lang = self.prefs()["lang"] or self.store.get("lang_tg") or "en"
        I.set_lang(lang)
        return lang

    def t(self, key, **kw):
        return I.T(key, self.lang(), **kw)

    async def loud(self, driven=False):
        """Whether to use sound. The owner's mode: 💻 at my Mac — never, 📱 on my phone — always, 🔄 auto — if the
        session is from Telegram or the owner is away from the Mac. Messages arrive in any mode; only sound changes."""
        mode = self.mode()
        if mode != "auto":
            return mode == "phone"
        return driven or await self.away()

    async def agents(self):
        """Sessions open on the Mac right now (VS Code tabs, terminals) — `claude agents --json`."""
        t, v = self._agents
        if time.monotonic() - t < 3:
            return v
        try:
            v = json.loads(await self._run(CLAUDE_BIN, "agents", "--json", timeout=15) or "[]")
        except ValueError:
            v = []
        self._agents = (time.monotonic(), v)
        return v

    # ----- projects and topics -----

    def project_path(self, pkey, hint=None):
        row = self.store.topic(pkey)
        if row and row["path"]:
            return row["path"]
        if hint and sanitize(hint) == pkey:
            return hint
        return decode_pkey(pkey)

    def project_name(self, pkey, path):
        return os.path.basename(path.rstrip("/")) if path else pkey.lstrip("-")

    async def thread_for(self, pkey, path=None):
        row = self.store.topic(pkey)
        if row and row["thread"]:
            return row["thread"]
        lock = self.topic_locks.setdefault(pkey, asyncio.Lock())
        async with lock:
            row = self.store.topic(pkey)
            if row and row["thread"]:
                return row["thread"]
            path = path or self.project_path(pkey)
            name = self.project_name(pkey, path)
            res = await self.out.submit(1, lambda: self.tg.call("createForumTopic", chat_id=self.chat,
                                                                 name=name[:128]))
            thread = res["message_thread_id"]
            self.store.set_topic(pkey, path, name, thread)
            log("topic created:", name)
            self.cards_seen.add(thread)
            await self.topic_card(pkey, thread, new=True)
            return thread

    def project_start(self, pkey):
        """The app's start parameter for a project's screen. Telegram allows 64 characters [A-Za-z0-9_-]; a longer
        one opens the list of projects."""
        start = "p_" + pkey
        return start if len(start) <= 64 and re.fullmatch(r"[A-Za-z0-9_-]+", start) else "projects"

    def card_buttons(self, pkey):
        url = self.app_url(start=self.project_start(pkey))
        return [[{"text": self.t("card.app"), "url": url}]] if url else None

    async def topic_card(self, pkey, thread, new=False):
        """A project topic's card: its intro with one button into the app on this project's screen, pinned in the
        topic — Telegram shows that button right in the topic's pinned bar, one tap from anywhere in the topic
        (owner's check 2026-10-17; a button next to the message field exists only in a private chat with the bot).
        Posted with a new topic, and into every older topic when Pult starts (ensure_cards) or first writes there;
        edited when the language or the app link changes. Without the app, a new topic gets the intro alone, unpinned.
        A topic Telegram refuses (deleted) is remembered and not tried again until the language or the link changes."""
        row = self.store.topic(pkey)
        name, path = (row["name"], row["path"]) if row else (pkey, None)
        text = self.t("topic.intro", name=R.esc(name), path=R.esc(path or "?"))
        buttons = self.card_buttons(pkey)
        sig = "%s|%s" % (self.lang(), buttons[0][0]["url"] if buttons else "")
        status = self._status.get(pkey) if buttons and self.pager() else None
        if status:                                  # stage V: the pinned bar shows who works and who waits
            text = "<b>%s</b>\n%s" % (R.esc(status), text)
            sig += "|" + status
        focus = self.focus_of(pkey)
        if focus:
            title = R.short(self.session_label(focus), 60)
            text = self.t("card.focus", name=I.q(R.esc(title))) + "\n" + text
            sig += "|%s:%08x" % (focus[:8], zlib.crc32(title.encode()))
        cards = self.store.get("cards") or {}
        entry = cards.get(str(thread))
        mid, old, pinned = entry or (None, None, False)
        if entry and old == sig:
            return
        if mid:
            self.edit(mid, text, buttons, prio=7)
        elif buttons or new:
            mid = await self.send(None, text, here=thread, buttons=buttons, prio=1 if new else 7)
            if not mid:
                pinned = False                 # Telegram refused: remember, so every start doesn't try again
        else:
            return
        if mid and buttons and not pinned:
            try:
                await self.out.submit(1 if new else 7, lambda: self.tg.call(
                    "pinChatMessage", chat_id=self.chat, message_id=mid, disable_notification=True))
                pinned = True
            except TgError as e:
                log("card not pinned:", e)
        cards = self.store.get("cards") or {}
        cards[str(thread)] = [mid, sig, pinned]
        self.store.put("cards", cards)

    async def ensure_cards(self):
        """On start: every project topic gets its card (only with the app set up). One by one, behind other messages."""
        for row in self.store.db.execute("SELECT pkey, thread FROM topics WHERE thread IS NOT NULL").fetchall():
            if row["thread"] in self.cards_seen:
                continue
            self.cards_seen.add(row["thread"])
            try:
                await self.topic_card(row["pkey"], row["thread"])
            except Exception as e:
                log("topic card:", repr(e))

    def card_check(self, pkey, thread):
        """Once per start for each topic Pult writes into: its card is there and up to date (in the background)."""
        if thread in self.cards_seen:
            return
        self.cards_seen.add(thread)

        async def go():
            try:
                await self.topic_card(pkey, thread)
            except Exception as e:
                log("topic card:", repr(e))
        asyncio.create_task(go())

    # ----- sending -----

    def topic_link(self, thread):
        chat = str(self.chat or "")
        return "https://t.me/c/%s/%d" % (chat[4:], thread) if chat.startswith("-100") and thread else None

    def group_link(self):
        """The group's General topic (its thread id is 1) — for the way back from the private chat with the bot."""
        return self.topic_link(1)

    async def send(self, pkey, text, *, reply_to=None, buttons=None, notify=False, prio=5,
                   sid=None, kind=None, here=None):
        """To the topic of project pkey (creating it if missing) or, if here is given, to where the
        owner wrote: a topic id, 0 — General."""
        if not self.chat:
            return None
        for attempt in (0, 1):
            if here is not None:
                thread = here or None
            else:
                thread = await self.thread_for(pkey) if pkey else None
                if thread:
                    self.card_check(pkey, thread)
            params = dict(chat_id=self.chat, text=text, parse_mode="HTML",
                          disable_notification=not notify or self.mode() == "mac",   # at the Mac, everything is silent
                          link_preview_options={"is_disabled": True})
            if thread:
                params["message_thread_id"] = thread
            if reply_to:
                params["reply_parameters"] = {"message_id": reply_to, "allow_sending_without_reply": True}
            if buttons:
                params["reply_markup"] = {"inline_keyboard": buttons}

            async def go(p=params):
                try:
                    return await self.tg.call("sendMessage", **p)
                except TgError as e:
                    if "parse" in e.desc.lower() or "entit" in e.desc.lower():
                        q = dict(p, text=R.html_to_plain(p["text"])[:R.TG_LIMIT])
                        q.pop("parse_mode")
                        return await self.tg.call("sendMessage", **q)
                    raise
            try:
                res = await self.out.submit(prio, go)
            except TgError as e:
                if attempt == 0 and pkey and here is None and "thread" in e.desc.lower():
                    log("topic is gone, creating it again:", pkey)
                    self.store.db.execute("DELETE FROM topics WHERE pkey=?", (pkey,))
                    continue
                log("not sent:", e)
                return None
            if sid:
                self.store.map_msg(res["message_id"], sid, kind or "msg")
            return res["message_id"]

    def edit(self, msg, text, buttons=None, prio=8):
        if not msg:
            return
        params = dict(chat_id=self.chat, message_id=msg, text=text, parse_mode="HTML",
                      link_preview_options={"is_disabled": True},
                      reply_markup={"inline_keyboard": buttons or []})

        async def go():
            try:
                return await self.tg.call("editMessageText", **params)
            except TgError as e:
                d = e.desc.lower()
                if "not modified" in d or "not found" in d:
                    return None
                if "parse" in d or "entit" in d:
                    q = dict(params, text=R.html_to_plain(text)[:R.TG_LIMIT])
                    q.pop("parse_mode")
                    return await self.tg.call("editMessageText", **q)
                raise
        self.out.edit(msg, go, prio)

    async def send_long(self, pkey, header, md, *, notify, sid, reply_to=None, prio=3, kind="result"):
        """A long Claude reply. With the app connected: the beginning in the chat and "Read in full" (the whole
        text in the app). Without it: 3500-character chunks, up to six chunks without a file (~20k characters), since
        a file is awkward to read on a phone; beyond that, the first five chunks and the whole text as a file."""
        chunks = R.split_md(md)
        ids = []
        if len(chunks) > 1 and sid and self.app_live():
            rest = len(md) - len(chunks[0])
            ids.append(await self.send(pkey, header + "\n" + R.md_to_html(chunks[0]) +
                                       self.t("long.more", n=rest), notify=notify, sid=sid, kind=kind,
                                       prio=prio, reply_to=reply_to, buttons=[self.app_row(sid, self.t("btn.read_all"))]))
            return ids
        if len(chunks) > 6:
            for i, ch in enumerate(chunks[:5]):
                ids.append(await self.send(pkey, (header + "\n" if i == 0 else "") + R.md_to_html(ch),
                                           notify=notify and i == 0, sid=sid, kind=kind, prio=prio,
                                           reply_to=reply_to if i == 0 else None))
            ids.append(await self.send_doc(pkey, md, "%s.md" % (sid or "text")[:8],
                                           self.t("doc.caption", n=len(md)), sid=sid))
            return ids
        for i, ch in enumerate(chunks):
            last = i == len(chunks) - 1
            ids.append(await self.send(pkey, (header + "\n" if i == 0 else "") + R.md_to_html(ch),
                                       notify=notify and i == 0, sid=sid, kind=kind, prio=prio,
                                       reply_to=reply_to if i == 0 else None,
                                       buttons=self.with_app(None, sid) if last and sid else None))
        return ids

    async def send_doc(self, pkey, text, name, caption, sid=None):
        thread = await self.thread_for(pkey) if pkey else None

        async def go():
            return await self.tg.call("sendDocument", files={"document": (name, text.encode())},
                                      chat_id=self.chat, message_thread_id=thread, caption=caption,
                                      disable_notification=True)
        try:
            res = await self.out.submit(4, go)
        except TgError as e:
            log("file not sent:", e)
            return None
        if sid:
            self.store.map_msg(res["message_id"], sid, "doc")
        return res["message_id"]

    async def notice(self, sid, text, reply_to=None):
        row = self.store.session(sid)
        pkey = row["pkey"] if row else None
        await self.send(pkey, "%s\n%s" % (self.head(self.live.get(sid) or self.stub(sid)), text),
                        reply_to=reply_to, notify=True, prio=2,
                        sid=sid, kind="notice")

    # ----- events from hooks -----

    def live_of(self, sid, pkey):
        lv = self.live.get(sid)
        if lv is None:
            lv = self.live[sid] = self.stub(sid, pkey)
        return lv

    def stub(self, sid, pkey=None):
        """A session from the database — for the header, without adding it to the live ones."""
        row = self.store.session(sid)
        lv = Live(sid, pkey or (row["pkey"] if row else ""))
        lv.title = row["title"] if row else None
        return lv

    async def refresh_title(self, lv):
        try:
            from claude_agent_sdk import get_session_info
            path = self.project_path(lv.pkey, lv.cwd)
            info = await asyncio.to_thread(get_session_info, lv.sid, path)
            if info:
                # custom_title — a name set by the user or made up by Claude Code; summary without it is
                # the last prompt ("let's continue"), no good for a title (SDK 0.2.167)
                t = info.custom_title or info.summary or info.first_prompt
                if t:
                    lv.title = R.short(t, 60)
                    lv.named = bool(info.custom_title)
                    self.store.touch_session(lv.sid, lv.pkey, title=lv.title)
        except Exception as e:
            log("session title not read:", repr(e))

    def title(self, lv):
        """What to call the session for a human: its name, or the project until it has one. A prompt used as the
        name ("let's continue", the start of a task) is not repeated — it is shown right next to it anyway."""
        if lv.named and lv.title:
            return lv.title
        row = self.store.topic(lv.pkey)
        return (row["name"] if row and row["name"] else
                os.path.basename((lv.cwd or "").rstrip("/")) or lv.pkey.rsplit("-", 1)[-1] or self.t("session.default"))

    def head(self, lv):
        return "<b>%s</b>" % R.esc(self.title(lv))

    def render_turn(self, lv, t):
        """"⏳ title · working 6 min" → "✔️ title · done in 6 min" (or ⏹ interrupted). The icon comes first, so the
        state is readable in a topic full of messages; under a minute the seconds are not counted aloud."""
        secs = (time.time() if not t.done else t.done[1]) - t.started
        dur = R.human_dur(secs)
        if t.done:
            icon, state = t.done[0], self.t({"✔️": "turn.done", "⚠️": "turn.failed"}.get(t.done[0], "turn.stopped"), dur=dur)
        else:
            icon, state = "⏳", self.t("turn.running", dur=dur) if secs >= 60 else self.t("turn.fresh")
        lines = ["%s %s · %s" % (icon, self.head(lv), state)]
        if t.prompt:
            lines.append(self.t("turn.you", text=R.esc(I.q(R.short(R.prompt_text(t.prompt), 300)))))
        elif t.note:
            lines.append("<i>%s</i>" % R.esc(t.note))
        if t.now and not t.done:
            lines += ["", "💬 " + R.esc(R.plain(t.now, NOW_LEN))]
        return "\n".join(lines)

    def start_turn(self, lv, prompt=None, reply_to=None, note=None):
        t = lv.turn = Turn(prompt, reply_to)
        t.note = note
        asyncio.create_task(self.turn_updater(lv, t))
        t.vehi = asyncio.create_task(self.vehi(lv, t))
        self.changed(lv.sid)
        return t

    async def refresh_now(self, lv, t):
        if lv.transcript:
            now = await asyncio.to_thread(last_reply, lv.transcript, t.started - 1)
            t.now = now or t.now

    async def turn_updater(self, lv, t):
        # as a pager (stage V) Telegram gets a turn message only for the owner's own dialog in a topic — a turn that
        # answers their message there; the rest is in the app and on the computer. The loop runs either way: it closes
        # a turn whose session is gone and keeps the app's "now" line fresh
        quiet = self.pager() and not t.reply_to
        try:
            text = self.render_turn(lv, t)
            if not quiet:
                t.msg = await self.send(lv.pkey, text, reply_to=t.reply_to, sid=lv.sid, kind="turn", prio=4,
                                        buttons=self.with_app(None, lv.sid))
            shown = text
        finally:
            if not t.created.done():
                t.created.set_result(t.msg)
        while t.msg or quiet:
            try:
                # even without events: "working N min" must keep ticking while a long command runs
                await asyncio.wait_for(t.changed.wait(), TICK)
            except asyncio.TimeoutError:
                pass
            t.changed.clear()
            if not t.done and not await self.alive(lv, t):
                log("turn %s: the session is gone from the Mac — closing" % lv.sid[:8])
                self.finish_turn(lv, "⏹")
            if not t.done:
                await asyncio.sleep(EDIT_EVERY)
                await self.refresh_now(lv, t)
            text = self.render_turn(lv, t)
            if text != shown:
                if t.msg:
                    self.edit(t.msg, text, self.with_app(None, lv.sid), prio=8 if not t.done else 4)
                shown = text
                self.changed(lv.sid)
            if t.done:
                break

    async def alive(self, lv, t):
        """A turn without events for longer than STALE — is the session alive? Otherwise a dead turn would edit its
        message forever and ring milestones. An empty `claude agents` list means we don't know (the command may
        have failed): treat the session as alive."""
        if time.time() - t.last < STALE or lv.sid in self.driven:
            return True
        agents = await self.agents()
        return not agents or any(a.get("sessionId") == lv.sid for a in agents)

    async def vehi(self, lv, t):
        """A long turn: at milestones, a short message with sound if the owner is away from the Mac or the
        session is from Telegram. At the Mac the owner sees the tab anyway, so stay quiet."""
        if self.pager():
            return                                 # stage V: the app shows how long it runs; Telegram doesn't ring
        for mark in vehi_marks():
            if t.started + mark < time.time() - 5:
                continue                           # already passed when Pult learned of the turn: no burst of reminders
            await asyncio.sleep(max(0.0, t.started + mark - time.time()))
            if t.done or t.muted:
                return
            if not self.prefs()["vehi"] or not await self.loud(lv.driven):
                continue
            if not await self.alive(lv, t):
                return
            await self.refresh_now(lv, t)
            text = self.t("vehi", head=self.head(lv), dur=R.human_dur(mark))
            if t.now:
                text += "\n💬 " + R.esc(R.plain(t.now, NOW_LEN))
            tok = self.offer(("mute", t, text))
            await self.send(lv.pkey, text, reply_to=t.msg, notify=True, prio=2, sid=lv.sid, kind="vehi",
                            buttons=[[{"text": self.t("btn.mute"), "callback_data": "m:" + tok}] +
                                     (self.app_row(lv.sid) or [])])

    def finish_turn(self, lv, mark):
        t = lv.turn
        if t and not t.done:
            t.done = (mark, time.time())
            t.changed.set()
            if t.vehi:
                t.vehi.cancel()
        lv.turn = None
        self.changed(lv.sid)
        return t

    async def on_hook(self, msg, reader, writer):
        ev = msg.get("event") or {}
        name = ev.get("hook_event_name")
        sid = ev.get("session_id")
        pkey = Path(ev.get("transcript_path") or "").parent.name or sanitize(ev.get("cwd") or "")
        if not sid or skip_pkey(pkey) or not self.chat:
            return None
        self.activity = time.time()
        lv = self.live_of(sid, pkey)
        lv.driven = bool(msg.get("driven"))     # who drives the session now: Pult or the Mac
        lv.pid = msg.get("pid") or lv.pid
        lv.transcript = ev.get("transcript_path") or lv.transcript
        dr = self.driven.get(sid)
        if dr and not lv.driven:
            # a session from Telegram was opened on the Mac: Pult releases its process so that two
            # processes don't write to the same session; a running turn is not interrupted
            if not dr.busy:
                dr.task.cancel()
                log("session %s moved to the Mac — Pult's process closed" % sid[:8])
                if dr.bg:
                    # the background tasks lived in Pult's process and closed with it
                    names = ", ".join(I.q(R.short(b.get("description") or self.t("task.default"), 60)) for b in lv.bg)
                    asyncio.create_task(self.notice(sid, self.t("bg.closed", names=": " + R.esc(names) if names else "")))
                    lv.bg = []
        if name == "SessionStart" or lv.cwd is None:
            lv.cwd = lv.cwd or ev.get("cwd")
            path = self.project_path(pkey, ev.get("cwd"))
            self.store.touch_session(sid, pkey, path=path, driven=lv.driven)
            if not self.store.topic(pkey) and path:
                self.store.set_topic(pkey, path, self.project_name(pkey, path), None)
        if name in ("UserPromptSubmit", "Stop", "StopFailure"):
            self.store.touch_session(sid, pkey)          # the topic's recent sessions, for the "where to send" question
        if name == "UserPromptSubmit":
            self.resolve_all(lv, self.t("req.decided_mac"))
            self.finish_turn(lv, "⏹")
            self.mark_seen(sid)                                # a new turn: the last outcome is behind
            await self.refresh_title(lv)
            notes = R.task_notes(ev.get("prompt"))
            if notes:
                # the turn was started by Claude Code itself (a background task finished); it's not the owner's prompt
                ended = {n["id"] for n in notes}
                lv.bg = [b for b in lv.bg if b.get("id") not in ended]
                self.start_turn(lv, note=R.task_notes_text(notes))
            else:
                origin = self.expect.get(sid)
                sent = self.tab_expect.get(sid)
                if not origin and sent and sent[1].strip() == (ev.get("prompt") or "").strip():
                    origin = self.tab_expect.pop(sid)[0]       # written from Telegram into the tab
                lv.title = lv.title or R.short(R.attachments(ev.get("prompt"))[0], 60) or None
                if not origin:
                    self.seen_here(lv)                         # typed here
                t = self.start_turn(lv, None if origin else ev.get("prompt"), reply_to=origin)
                t.here = not origin and not lv.driven
        elif name in ("PostToolUse", "PostToolUseFailure"):
            tool, inp = ev.get("tool_name"), ev.get("tool_input")
            for r in list(lv.pending.values()):
                if r.tool == tool and same_input(r.inp, inp):
                    self.seen_here(lv)
                    self.resolve_elsewhere(r, self.t("req.answered_mac" if r.kind == "ask" else "req.allowed_mac"),
                                           inp)
            if lv.turn is None:
                if lv.title is None:
                    await self.refresh_title(lv)
                began = await asyncio.to_thread(prompt_started, lv.transcript) if lv.transcript else None
                t = self.start_turn(lv)
                if began and began < t.started:
                    t.started = began              # the turn began before Pult saw it (a restart mid-turn)
                    t.changed.set()
            t = lv.turn
            t.n += 1
            t.last = time.time()
            t.changed.set()
        elif name == "Stop":
            self.resolve_all(lv, self.t("req.decided_mac"))
            if "background_tasks" in ev:                 # the field exists since Claude Code 2.1.30x (probe 2026-10-16)
                lv.bg = [b for b in ev.get("background_tasks") or [] if isinstance(b, dict)]
                now = time.time()
                lv.bg_seen = {b.get("id"): lv.bg_seen.get(b.get("id"), now) for b in lv.bg}
            t = self.finish_turn(lv, "✔️")
            asyncio.create_task(self.post_result(lv, t, ev.get("last_assistant_message") or "", R.bg_text(lv.bg)))
        elif name == "StopFailure":
            # an API error ended the turn (rate limit, sign-in, overload…): Claude Code sends this instead of Stop
            # (2.1.301, probe 2026-10-20 — fields error, error_details, last_assistant_message)
            self.resolve_all(lv, self.t("req.decided_mac"))
            t = self.finish_turn(lv, "⚠️")
            asyncio.create_task(self.post_result(lv, t, ev.get("last_assistant_message") or "",
                                                 fail=str(ev.get("error") or "unknown")))
        elif name == "SessionEnd":
            self.resolve_all(lv, self.t("req.session_closed"))
            self.finish_turn(lv, "⏹")
            self.live.pop(sid, None)
            if not lv.driven:                  # a session from Telegram only rests: Pult closes its idle process
                self.clear_focus(sid)
        elif name == "PermissionRequest":
            return await self.on_permission(lv, ev, reader)
        return None

    async def post_result(self, lv, t, text, bg="", fail=None):
        """bg — the line "⚙️ Still running in the background: …" under the result header: Claude has finished the
        turn, but its background task is still running; when it ends, Claude starts a new turn by itself.
        fail — the API error that ended the turn (StopFailure)."""
        if t is not None:
            await t.created
        notify = await self.loud(lv.driven)
        self.outcome(lv, t, text, fail, seen=bool(t and t.here) and not await self.away())
        reply_to = t.msg if t else None
        # a message written from Telegram into a tab that was busy: Claude Code absorbs it into the running turn
        # (queued_command, absorbed_mid_turn — 2.1.301, 2026-10-18) and the tab doesn't show it, so no UserPromptSubmit
        # ever claims it; the turn's result replies to that message instead, so the answer finds the question
        sent = self.tab_expect.pop(lv.sid, None)
        if sent and sent[0]:
            reply_to = sent[0]
        if not text.strip():
            text = self.t("result.empty")
        when = self.t("result.done_in", dur=R.human_dur(t.done[1] - t.started)) if t and t.done else self.t("result.done")
        if fail:
            when = " · " + R.esc(self.fail_text(fail))
        self.recent.appendleft({"sid": lv.sid, "title": self.title(lv), "project": self.project_label(lv.pkey),
                                "ts": time.time(), "dur": (t.done[1] - t.started) if t and t.done else None,
                                "text": R.plain(text, 400)})
        self.changed(lv.sid)
        if self.pager():
            if not (t and t.reply_to) and not (sent and sent[0]):
                return                         # not a dialog in a topic: the app has it, a "your move" gets paged
            if t and t.msg:                    # one message per turn: the answer takes the place of the turn message
                asyncio.create_task(self.drop(t.msg))
            reply_to = sent[0] if sent and sent[0] else t.reply_to        # under the owner's own message
            r = self.attn.rec.get(lv.sid)
            if r:
                r["paged"] = True              # the answer itself is the call
                self.attn.save()
        await self.send_long(lv.pkey, "%s %s%s\n%s" % ("⚠️" if fail else "✅", self.head(lv), when,
                                                        R.esc(bg) + "\n" if bg else ""), text,
                             notify=notify, sid=lv.sid, reply_to=reply_to)

    # ----- whose move (stage V): each session's last outcome, the model's line, the Home board -----

    def fail_text(self, code):
        """The API error that ended a turn, for a human: StopFailure's error (2.1.301 knows rate_limit, overloaded,
        server_error, authentication_failed, billing_error, invalid_request, max_output_tokens, model_not_found)."""
        key = "fail." + code
        return self.t(key) if key in I.S else self.t("fail.other", code=R.esc(code))

    def outcome(self, lv, t, text, fail=None, seen=False):
        """A turn ended: remember how (pult_attn) and, if the owner allowed it, let the model read the result.
        seen — the owner typed this turn here and is still at the computer: they watched it end."""
        waits = not lv.bg                                  # nothing else runs: the next step is the owner's
        line = self.fail_text(fail) if fail else B.first_sentence(text)
        dur = (t.done[1] - t.started) if t and t.done else None
        rec = self.attn.finished(lv.sid, lv.pkey, dur, R.plain(text, 600), line, waits, fail=fail, seen=seen)
        self.changed(lv.sid)
        if not fail and text.strip() and self.prefs()["brief"]:
            bg = [b.get("description") or b.get("command") or "" for b in lv.bg]
            asyncio.create_task(self.brief_result(lv, rec["ts"], t.prompt if t else None, text, bg, waits))

    async def drop(self, mid):
        """Delete one of Pult's messages (Telegram allows it for 48 h); a refusal only goes to the log."""
        try:
            await self.out.submit(6, lambda: self.tg.call("deleteMessage", chat_id=self.chat, message_id=mid))
        except TgError as e:
            log("message %s not deleted: %s" % (mid, e))

    def mark_seen(self, sid):
        """The owner saw a session's outcome (opened it, answered it, "Got it", a new turn): it rests, and a call
        about it in Telegram folds into "✓ … · line" without buttons."""
        r = self.attn.rec.get(sid)
        if not self.attn.seen(sid):
            return False
        if r and r.get("page"):
            lv = self.live.get(sid) or self.stub(sid, r["pkey"])
            self.edit(r["page"], "✓ <b>%s</b> · %s" % (R.esc(lv.title or self.title(lv)), R.esc(r["line"] or "")), [], prio=6)
        self.changed(sid)
        return True

    async def attention_watch(self):
        """Every 10 s (stage V): say "continue" where the usage limit has reset, call the owner in Telegram about a
        "your move" they don't see, keep the topics' pinned cards showing who works and who waits."""
        n = 0
        while True:
            await asyncio.sleep(10)
            n += 1
            try:
                await self.presence_check()
                await self.resume_due()
                if self.pager() and self.chat:
                    await self.page_due()
                    if n % 6 == 0:
                        await self.cards_status()
            except Exception as e:
                log("attention:", repr(e))

    async def page_due(self):
        """Telegram as a pager: requests and outcomes that wait for the owner and that they can't see — not in the app,
        not at the computer (page_now). An outcome waits up to PAGE_WAIT for the model's line, so the call says
        what is needed and offers the ready replies; "only a report" is never paged."""
        if not await self.page_now():
            return
        for req in list(self.req_by_rid.values()):
            if not req.fut.done() and not req.paged:
                await self.post_request(self.live.get(req.sid) or self.stub(req.sid), req, True)
        now = time.time()
        for sid, r in list(self.attn.rec.items()):
            if r.get("seen") or r.get("paged") or not (r.get("you") or r.get("fail")) or now - r["ts"] > PAGE_OLD:
                continue
            if not r.get("fail") and self.prefs()["brief"] and not r.get("model") and now - r["ts"] < PAGE_WAIT:
                continue
            lv = self.live.get(sid)
            if lv and (lv.turn or lv.pending):
                continue                                   # it has moved on
            await self.page(sid, r)

    async def page(self, sid, r):
        """One call in the project's topic: what came out, what is needed, ready replies (or "continue after the
        reset"), the way into the app right at that session. With sound: the owner isn't looking."""
        lv = self.live.get(sid) or self.stub(sid, r["pkey"])
        text = "%s <b>%s</b>\n%s" % ("⚠️" if r.get("fail") else "🔴", R.esc(lv.title or self.title(lv)), R.esc(r["line"] or ""))
        if r.get("need"):
            text += "\n<b>%s</b>" % R.esc(r["need"])
        rows = []
        replies = r.get("replies") or []
        for i in range(0, len(replies), 2):
            rows.append([{"text": x, "callback_data": "r:%s:%d" % (sid, i + k)} for k, x in enumerate(replies[i:i + 2])])
        if r.get("fail") == "rate_limit":
            at = self.limit_reset()
            rows.append([{"text": self.t("btn.resume", hm=time.strftime("%H:%M", time.localtime(at))) if at
                          else self.t("btn.resume_after"), "callback_data": "z:" + sid}])
        m = await self.send(r["pkey"], text, buttons=self.with_app(rows or None, sid), notify=True, prio=2, sid=sid,
                            kind="page")
        r["paged"], r["page"] = True, m
        self.attn.save()
        log("page %s: %s" % (sid[:8], "fail" if r.get("fail") else "your move"))

    async def on_reply_button(self, sid, i):
        """A ready reply tapped under a call in Telegram: it goes into the session as the owner's message."""
        r = self.attn.rec.get(sid) or {}
        replies = r.get("replies") or []
        if not (0 <= i < len(replies)):
            return self.t("note.stale")
        res = await self.api_send(sid, replies[i])
        if res.get("need") == "fork":
            return self.t("note.reply_open")
        if r.get("page"):
            lv = self.live.get(sid) or self.stub(sid, r["pkey"])
            self.edit(r["page"], "✓ <b>%s</b> · %s\n→ %s" % (R.esc(lv.title or self.title(lv)), R.esc(r["line"] or ""),
                                                            R.esc(I.q(replies[i]))), [], prio=3)
            r["page"] = None
            self.attn.save()
        return self.t("note.reply_sent")

    async def api_resume_at(self, sid, at=None):
        """"Continue when the usage limit resets": at that time (a minute after it) Pult says CONTINUE in the session,
        the way the owner's own message would go; at=None cancels. at=0 — the 5-hour window's reset, as last read."""
        if not SID_RE.fullmatch(sid or ""):
            raise ValueError(self.t("err.bad_sid"))
        if at is None:
            self.attn.resume.pop(sid, None)
            self.attn.save()
            self.changed(sid)
            return {"ok": True, "at": None}
        at = float(at or 0) or self.limit_reset()
        if not at:
            try:
                await self.usage(force=True)
            except Exception as e:
                log("usage for the reset time:", repr(e))
            at = self.limit_reset()
        if not at:
            raise ValueError(self.t("err.no_reset"))
        at = max(at, time.time()) + 60
        self.attn.resume[sid] = at
        self.attn.save()
        self.changed(sid)
        log("continue %s at %s" % (sid[:8], time.strftime("%H:%M", time.localtime(at))))
        return {"ok": True, "at": at}

    async def resume_due(self):
        now = time.time()
        for sid, at in list(self.attn.resume.items()):
            if at > now:
                continue
            self.attn.resume.pop(sid, None)
            self.attn.save()
            try:
                res = await self.api_send(sid, CONTINUE)
                log("continue %s after the reset: %s" % (sid[:8], res.get("how") or res.get("need")))
            except Exception as e:
                log("continue %s after the reset failed: %r" % (sid[:8], e))

    def card_status(self, pkey, rows):
        """The first line of a topic's pinned card (stage V): who works, who waits since when — the topic's pinned bar
        shows it; editing it never rings."""
        work = sum(1 for r in rows if r["state"] in ("work", "bg"))
        mine = [r for r in rows if r["state"] in A.MINE]
        parts = [self.t("card.st.work", n=work)] if work else []
        if mine:
            since = min(r["since"] or time.time() for r in mine)
            parts.append(self.t("card.st.mine", n=len(mine), hm=time.strftime("%H:%M", time.localtime(since))))
        return " · ".join(parts) or self.t("card.st.quiet")

    async def cards_status(self):
        """The pinned cards follow their projects (only edits that change something; at most once a minute)."""
        by = {}
        for r in self.session_rows(await self.agents()):
            by.setdefault(r["pkey"], []).append(r)
        self._status = {pkey: self.card_status(pkey, rows) for pkey, rows in by.items()}
        for row in self.store.db.execute("SELECT pkey, thread FROM topics WHERE thread IS NOT NULL").fetchall():
            try:
                await self.topic_card(row["pkey"], row["thread"])
            except Exception as e:
                log("topic card:", repr(e))

    async def presence_check(self):
        """The app stopped saying "on screen" without a word (Telegram closed it, the phone froze its page): after
        APP_ON s it counts as off the screen. The log tells which way it went — the Android check of stage V."""
        if self.app_vis and time.time() - self.app_on > APP_ON:
            await self.api_presence(False, quiet=True)

    async def api_presence(self, on=True, quiet=False):
        """The app is on the owner's screen (or not): where to call them (stage V). A visit after a long break opens
        "While you were away"; the end of the visit closes it."""
        now = time.time()
        if on:
            if not self.app_vis:
                log("app: on the screen")
                if self.app_seen and now - self.app_seen > CATCH_GAP:
                    self.catch_from = self.app_seen
                    self.store.put("catch_from", self.catch_from)
            self.app_vis, self.app_on = True, now
            if now - self.app_seen > 60:
                self.store.put("app_seen", now)
            self.app_seen = now
        elif self.app_vis:
            log("app: no word for %d s — off the screen" % APP_ON if quiet else "app: off the screen")
            self.app_vis = False
            self.store.put("app_seen", now)
            self.app_seen = now
            if self.catch_from:
                self.catch_from = None
                self.store.put("catch_from", None)
        return {"ok": True}

    async def api_catchup_off(self):
        self.catch_from = None
        self.store.put("catch_from", None)
        return {"ok": True}

    def catchup(self):
        """"While you were away": the turns since the app was last on the screen, what is done, what waits for the
        owner now, the latest line per project."""
        if not self.catch_from:
            return None
        es = self.attn.since(self.catch_from)
        if not es:
            return None
        last = {}
        for e in es:
            last[e[1]] = e
        lines = []
        for pkey, e in sorted(last.items(), key=lambda x: -x[1][0])[:4]:
            r = self.attn.rec.get(e[2]) or {}
            lines.append({"pkey": pkey, "name": self.name_of(pkey), "line": e[3],
                          "you": bool(e[4] and not r.get("seen")), "fail": e[5]})
        return {"from": self.catch_from, "turns": len(es), "projects": len(last),
                "done": sum(1 for e in es if not e[4] and not e[5]), "lines": lines,
                "mine": sum(1 for r in self.attn.rec.values() if not r["seen"] and (r["you"] or r["fail"]))}

    def limit_pct(self):
        """The 5-hour window, % used, from the last usage reading (no new request), or None."""
        for lim in (self._usage or {}).get("limits") or []:
            if lim.get("kind") in ("session", "five_hour"):
                return lim.get("percent")
        return None

    async def brief_result(self, lv, ts, prompt, text, bg, waits):
        """The model's line for a finished turn (pult_brief: haiku, the owner's subscription), one request at a
        time; a newer outcome of the same session makes the request moot."""
        async with self.brief_sem:
            r = self.attn.rec.get(lv.sid)
            if not r or r["ts"] != ts:
                return
            BRIEF_DIR.mkdir(parents=True, exist_ok=True)
            b = await B.brief(R.prompt_text(prompt) if prompt else None, text, bg, self.lang(), BRIEF_DIR)
            if b is None:
                log("brief %s: no answer from the model — the first sentence stays" % lv.sid[:8])
            elif self.attn.briefed(lv.sid, ts, b, waits):
                self.changed(lv.sid)

    # ----- tasks without Claude: pult run -- command -----

    def pkey_for_cwd(self, cwd):
        """The topic of the project whose folder the task runs in (the most nested one), otherwise General (None)."""
        best = None
        cwd = os.path.realpath(cwd or "/")          # /var → /private/var and other symlinks
        for r in self.store.db.execute("SELECT pkey, path FROM topics WHERE path IS NOT NULL"):
            p = os.path.realpath(r["path"]).rstrip("/")
            if (cwd == p or cwd.startswith(p + "/")) and (best is None or len(p) > len(best[1])):
                best = (r["pkey"], p)
        return best[0] if best else None

    def render_job(self, j, final=False):
        """The task message: "⚙️ command · running 6 min" and the last line of output; final — the result "✅ / ❌"."""
        cmd = "<b>%s</b>" % R.esc(R.short(j.cmd, 90))
        if j.ended is None:
            secs = time.time() - j.started
            text = self.t("job.running", cmd=cmd, dur=R.human_dur(secs)) if secs >= 60 else self.t("job.fresh", cmd=cmd)
            return text + ("\n<code>%s</code>" % R.esc(R.short(j.last, 200)) if j.last else "")
        took = R.human_dur(j.ended - j.started)
        if j.code == 0:
            return self.t("job.done.final" if final else "job.done", cmd=cmd, dur=took)
        why = self.t("job.killed") if j.code is None else self.t("job.code", code=j.code)
        return self.t("job.fail.final" if final else "job.fail", cmd=cmd, why=why, dur=took)

    async def job_send(self, j, text, **kw):
        if j.pkey:
            return await self.send(j.pkey, text, **kw)
        return await self.send(None, text, here=0, **kw)

    async def on_run(self, m):
        rid, op = str(m.get("id") or ""), m.get("op")
        j = self.jobs.get(rid)
        if op == "start" and rid and j is None:
            cwd = str(m.get("cwd") or "")
            j = self.jobs[rid] = Job(rid, str(m.get("cmd") or "?"), cwd, m.get("pid"), self.pkey_for_cwd(cwd))
            log("job %s: %s · %s" % (rid, R.short(j.cmd, 80), cwd))
            j.msg = await self.job_send(j, self.render_job(j), prio=4)
            j.watch = asyncio.create_task(self.job_watch(j))
        elif op == "tick" and j:
            j.last = str(m.get("last") or "")
            self.edit(j.msg, self.render_job(j))
        elif op == "end" and j:
            self.finish_job(j, m.get("code"), m.get("tail") or [])
            notify = await self.loud()
            text = self.render_job(j, final=True)
            tail = [str(x) for x in j.tail[-15:]]
            if tail and j.code != 0:
                text += "\n<pre>%s</pre>" % R.esc(R.short_block("\n".join(tail), 2500))
            elif tail:
                text += "\n<code>%s</code>" % R.esc(R.short(tail[-1], 200))
            await self.job_send(j, text, reply_to=j.msg, notify=notify, prio=3)
        else:
            return
        self.changed()

    def finish_job(self, j, code, tail):
        if j.ended is not None:
            return
        j.code, j.tail, j.ended = code, list(tail), time.time()
        if j.watch:
            j.watch.cancel()
        self.jobs.pop(j.rid, None)
        self.jobs_done.appendleft(j)
        self.edit(j.msg, self.render_job(j), prio=4)
        log("job %s: end, code %s" % (j.rid, code))

    async def job_watch(self, j):
        """Every minute: "running N min" in the message; milestones if the owner is away; if the wrapper was killed
        without reporting the end, the task is closed as interrupted."""
        marks = vehi_marks()
        mark = next(marks)
        while j.ended is None:
            await asyncio.sleep(TICK)
            if j.pid and not pid_alive(j.pid):
                self.finish_job(j, None, j.tail)
                self.changed()
                return
            self.edit(j.msg, self.render_job(j))
            if time.time() - j.started >= mark:
                if not j.muted and self.prefs()["vehi"] and await self.loud():
                    await self.job_send(j, self.t("job.vehi", cmd=R.esc(R.short(j.cmd, 90)), dur=R.human_dur(mark)),
                                        reply_to=j.msg, notify=True, prio=2)
                mark = next(marks)

    def job_item(self, j):
        return {"id": j.rid, "cmd": j.cmd, "cwd": j.cwd, "project": self.project_label(j.pkey) if j.pkey else None,
                "started": j.started, "ended": j.ended, "code": j.code, "last": j.last, "tail": j.tail[-30:]}

    # ----- permissions and questions -----

    async def on_permission(self, lv, ev, reader):
        req = Req(lv.sid, ev.get("tool_name"), ev.get("tool_input"), ev.get("permission_suggestions"))
        lv.pending[req.rid] = req
        self.req_by_rid[req.rid] = req
        notify = await self.loud(lv.driven)
        self.changed(lv.sid)
        try:
            await self.post_request(lv, req, notify)
            eof = asyncio.create_task(reader.read())
            await asyncio.wait({req.fut, eof}, return_when=asyncio.FIRST_COMPLETED)
            eof.cancel()
            if not req.fut.done():
                self.seen_here(lv)                             # the dialog here was answered first
                self.resolve_elsewhere(req, self.t("req.decided_mac"))
            return req.fut.result()
        finally:
            lv.pending.pop(req.rid, None)
            self.req_by_rid.pop(req.rid, None)
            for m, _ in req.msgs:
                self.req_by_msg.pop(m, None)

    async def post_request(self, lv, req, notify):
        if self.pager() and not await self.page_now():
            return              # the app and the computer show it; posted later if the owner leaves while it waits
        req.paged = True
        rid = req.rid
        if req.kind == "ask":
            for i, q in enumerate(req.inp.get("questions") or []):
                m = await self.send(lv.pkey, self.req_head(req, "❓", self.t("req.asks")) + R.question_text(q),
                                    buttons=self.with_app(self.q_buttons(req, i), lv.sid), notify=notify and i == 0, prio=0,
                                    sid=lv.sid, kind="ask")
                if m:
                    req.msgs.append((m, i))
                    self.req_by_msg[m] = (req, i)
            return
        if req.kind == "plan":
            plan = str(req.inp.get("plan") or "")
            body = R.md_to_html(plan if len(plan) <= 3000 else plan[:3000] + "…")
            text = self.req_head(req, "📋", self.t("req.plan")) + body
            buttons = [[{"text": self.t("btn.approve"), "callback_data": "p:%s:y" % rid},
                        {"text": self.t("btn.reject_plan"), "callback_data": "p:%s:n" % rid}]]
            if len(plan) > 3000:
                await self.send_doc(lv.pkey, plan, "plan-%s.md" % lv.sid[:8], self.t("plan.full"), sid=lv.sid)
        else:
            text = self.req_head(req, "✋", self.t("req.perm")) + \
                R.permission_text(req.tool, req.inp, lv.cwd)
            row = [{"text": self.t("btn.allow"), "callback_data": "p:%s:y" % rid},
                   {"text": self.t("btn.deny"), "callback_data": "p:%s:n" % rid}]
            buttons = [row]
            if req.suggestions:
                buttons.append([{"text": self.t("btn.always"), "callback_data": "p:%s:a" % rid}])
        text += self.t("perm.reply_hint")
        buttons = self.with_app(buttons, lv.sid)
        m = await self.send(lv.pkey, text, buttons=buttons, notify=notify, prio=0, sid=lv.sid, kind="perm")
        if m:
            req.msgs.append((m, None))
            self.req_by_msg[m] = (req, None)

    def q_buttons(self, req, i):
        q = (req.inp.get("questions") or [])[i]
        picks = req.picks.get(i, [])
        rows = []
        for k, o in enumerate(q.get("options") or []):
            label = o.get("label") or "?"
            if q.get("multiSelect"):
                label = ("☑️ " if label in picks else "▫️ ") + label
            rows.append([{"text": R.short(label, 60), "callback_data": "q:%s:%d:%d" % (req.rid, i, k)}])
        if q.get("multiSelect"):
            rows.append([{"text": self.t("btn.done"), "callback_data": "q:%s:%d:ok" % (req.rid, i)}])
        return rows

    def act(self, req, act, where="tg", text=None):
        """A decision on a permission request or a plan — a chat button or the app (where: "tg" / "app").
        None — accepted. What Claude reads is in English; what the owner reads — in the owner's language."""
        if not req or req.fut.done():
            return self.t("note.decided")
        plan = req.kind == "plan"
        place, for_claude = self.t("where." + where), {"tg": "Telegram", "app": "the Pult app"}.get(where, where)
        if act == "y":
            self.decide(req, {"behavior": "allow"}, self.t("dec.approved" if plan else "dec.allowed", where=place))
        elif act == "a" and req.suggestions:
            self.decide(req, {"behavior": "allow", "updatedPermissions": req.suggestions}, self.t("dec.always"))
        elif act == "n":
            if text:
                self.decide(req, {"behavior": "deny", "message": "The owner replied from %s: %s" % (for_claude, text)},
                            self.t("dec.denied_note", text=R.short(text, 80)))
            else:
                self.decide(req, {"behavior": "deny", "message": "The owner declined from %s." % for_claude},
                            self.t("dec.rejected_plan") if plan else self.t("dec.denied", where=place))
        else:
            return self.t("note.unclear")
        return None

    def decide(self, req, decision, note):
        if req.fut.done():
            return
        req.fut.set_result({"output": {"hookSpecificOutput": {"hookEventName": "PermissionRequest",
                                                              "decision": decision}}})
        log("%s #s%s: %s — %s" % (req.tool, req.sid[:8], decision.get("behavior"), note))
        self.close_req_msgs(req, note)

    def req_head(self, req, icon, what=None):
        lv = self.live.get(req.sid) or self.stub(req.sid)
        return "%s %s%s\n" % (icon, self.head(lv), " · " + what if what else "")

    def close_req_msgs(self, req, note, answers=None):
        lv = self.live.get(req.sid)
        for m, i in req.msgs:
            if i is not None:
                q = (req.inp.get("questions") or [])[i]
                got = (answers or {}).get(q.get("question")) or ", ".join(req.chosen.get(i, []))
                text = "%s%s\n%s%s" % (self.req_head(req, "❓"), R.question_text(q, req.chosen.get(i), done=True),
                                       "→ <b>%s</b> · " % R.esc(got) if got else "", R.esc(note))
            elif req.kind == "plan":
                text = self.req_head(req, "📋") + self.t("plan.decided", note=R.esc(note))
            else:
                text = "%s%s\n<b>%s</b>" % (self.req_head(req, "✋"),
                                            R.permission_text(req.tool, req.inp, lv.cwd if lv else None), R.esc(note))
            self.edit(m, text, [], prio=3)
        self.changed(req.sid)

    def resolve_elsewhere(self, req, note, inp=None):
        if req.fut.done():
            return
        req.fut.set_result({"output": None})
        log("%s #s%s: %s" % (req.tool, req.sid[:8], note))
        self.close_req_msgs(req, "✔️ " + note, (inp or {}).get("answers"))

    def resolve_all(self, lv, note):
        for r in list(lv.pending.values()):
            self.resolve_elsewhere(r, note)

    def answer_question(self, req, i, values):
        req.chosen[i] = values
        qs = req.inp.get("questions") or []
        m = next((m for m, k in req.msgs if k == i), None)
        if m:
            self.edit(m, "%s%s\n→ <b>%s</b>" % (self.req_head(req, "❓"), R.question_text(qs[i], values, done=True),
                                               R.esc(", ".join(values))), [], prio=3)
        self.changed(req.sid)
        if len(req.chosen) == len(qs) and not req.fut.done():
            ans = R.answers_for(qs, req.chosen)
            req.fut.set_result({"output": {"hookSpecificOutput": {"hookEventName": "PermissionRequest",
                                "decision": {"behavior": "allow",
                                             "updatedInput": {"questions": qs, "answers": ans}}}}})
            log("%s #s%s: answered from Telegram — %s" % (req.tool, req.sid[:8], "; ".join(ans.values())))

    # ----- Telegram: buttons -----

    async def on_callback(self, cq):
        uid = (cq.get("from") or {}).get("id")
        data = cq.get("data") or ""
        note = None
        if uid not in self.allowed:
            note = self.t("note.denied")
        elif data.startswith("p:"):
            _, rid, act = data.split(":")
            note = self.act(self.req_by_rid.get(rid), act)
        elif data.startswith("q:"):
            _, rid, i, k = data.split(":")
            req, i = self.req_by_rid.get(rid), int(i)
            if not req or req.fut.done():
                note = self.t("note.decided")
            else:
                q = (req.inp.get("questions") or [])[i]
                opts = [o.get("label") for o in q.get("options") or []]
                if k == "ok":
                    if req.picks.get(i):
                        self.answer_question(req, i, req.picks[i])
                    else:
                        note = self.t("note.pick_one")
                elif q.get("multiSelect"):
                    p = req.picks.setdefault(i, [])
                    lab = opts[int(k)]
                    p.remove(lab) if lab in p else p.append(lab)
                    m = next((m for m, kk in req.msgs if kk == i), None)
                    self.edit(m, self.req_head(req, "❓", self.t("req.asks")) + R.question_text(q, p),
                              self.with_app(self.q_buttons(req, i), req.sid), prio=1)
                else:
                    self.answer_question(req, i, [opts[int(k)]])
        elif data.startswith("m:"):
            o = self.offers.get(data[2:])
            if not o:
                note = self.t("note.stale")
            else:
                o[1].muted = True
                self.edit((cq.get("message") or {}).get("message_id"),
                          o[2] + self.t("vehi.muted"), [], prio=3)
                note = self.t("note.muted")
        elif data.startswith("w:") and data[2:] in MODES:
            await self.set_mode(data[2:])
            mid = (cq.get("message") or {}).get("message_id")
            if mid and mid != self.store.get("panel"):
                self.edit(mid, self.panel_text(), self.panel_buttons(), prio=1)
            note = self.t("mode.set", mode=self.t("mode." + data[2:]))
        elif data.startswith("h:"):
            sec = data[2:]
            text = self.t("help") if sec == "main" else self.help_section(sec)
            self.edit((cq.get("message") or {}).get("message_id"), text, self.help_buttons(sec), prio=1)
        elif data.startswith("r:") and data.count(":") == 2:
            _, sid, i = data.split(":")
            note = await self.on_reply_button(sid, int(i)) if i.isdigit() else self.t("note.stale")
        elif data.startswith("z:"):
            try:
                at = (await self.api_resume_at(data[2:], 0))["at"]
                note = self.t("note.resume", hm=time.strftime("%H:%M", time.localtime(at)))
            except ValueError as e:
                note = str(e)
        elif data.startswith(("s:", "f:", "o:", "t:")):
            cm = cq.get("message") or {}
            note = await self.on_offer(data, cm.get("message_thread_id") if cm.get("is_topic_message") else 0)
        log("button %s from %s → %s" % (data[:14], uid, note or "ok"))
        try:
            await self.tg.call("answerCallbackQuery", callback_query_id=cq["id"], text=note)
        except TgError:
            pass

    def offer(self, value):
        """A button that refers to stored data: Telegram's callback_data is at most 64 bytes."""
        if len(self.offers) > 500:
            for k in list(self.offers)[:250]:
                del self.offers[k]
        tok = secrets.token_hex(4)
        self.offers[tok] = value
        return tok

    async def on_offer(self, data, here=0):
        kind, tok = data.split(":", 1)
        o = self.offers.pop(tok, None)
        if not o:
            return self.t("note.stale_retry")
        if kind == "o":
            mode, pkey, path, pending = o
            name = self.project_name(pkey, path)
            if mode == "bind":
                body, origin, uthread = pending
                old = self.store.topic(pkey)
                self.store.set_topic(pkey, path, name, uthread)
                log("topic %s bound to project %s (was %s)" % (uthread, name, old["thread"] if old else None))
                await self.send(None, self.t("topic.bound", name=R.esc(name), path=R.esc(path)), here=uthread)
                await self.drive(str(uuid.uuid4()), path, body, origin, pkey=pkey)
                return self.t("note.bound", name=name)
            thread = await self.thread_for(pkey, path)
            link = self.topic_link(thread)
            title = '<a href="%s">%s</a>' % (link, R.esc(name)) if link else "<b>%s</b>" % R.esc(name)
            if mode == "new":
                body, origin = pending
                await self.drive(str(uuid.uuid4()), path, body, origin, pkey=pkey, quote=False, here=here)
                await self.send(None, self.t("started.in", title=title), here=here,
                                reply_to=origin)
                return self.t("note.starting_in", name=name)
            await self.send(None, self.t("topic.link", title=title), here=here)
            return name
        if kind == "s":
            pkey, path, sid = o
            await self.session_card(pkey, path, sid)
            return None
        if kind == "t":
            if o[0] == "sess":
                _, sid, body, origin, ohere = o
                await self.continue_session(sid, body, origin, ohere)
                return self.t("note.sending_to", name=I.q(R.short(self.title(self.live.get(sid) or self.stub(sid)), 40)))
            _, path, pkey, body, origin = o
            await self.drive(str(uuid.uuid4()), path, body, origin, pkey=pkey)
            return self.t("note.new_session")
        if kind == "f":
            sid, path, text, origin, quote, fhere = o
            await self.drive(sid, path, text, origin, fork=True, quote=quote, here=fhere)
            return self.t("note.starting_copy")
        return None

    # ----- Telegram: messages -----

    async def on_message(self, m):
        uid = (m.get("from") or {}).get("id")
        chat = (m.get("chat") or {}).get("id")
        text = m.get("text") or m.get("caption") or ""
        cmd, rest = command_of(text)
        if uid not in self.allowed:
            return
        if (m.get("from") or {}).get("language_code") and not self.store.get("lang_tg"):
            # only the first time: Telegram on the phone and on the computer may speak different languages, and the
            # bot must not switch with every device (seen 2026-10-17); later — the app's settings
            self.store.put("lang_tg", I.lang_of(m["from"]["language_code"]))
        private = (m.get("chat") or {}).get("type") == "private"
        if cmd == "/bind":
            if not (m.get("chat") or {}).get("is_forum"):
                await self.tg.call("sendMessage", chat_id=chat,
                                   text=self.t("bind.private" if private else "bind.need_forum"))
                return
            self.chat = chat
            self.store.put("chat", chat)
            await self.send(None, self.t("help"), here=0, buttons=self.help_buttons())
            await self.post_panel(0)
            log("group bound:", chat)
            return
        if chat != self.chat:
            if private:                        # no group yet — how to make one; otherwise — where to write, with a way there
                link = self.group_link() if self.chat else None
                await self.tg.call("sendMessage", chat_id=chat,
                                   text=self.t("private.elsewhere" if self.chat else "bind.private"),
                                   reply_markup={"inline_keyboard": [[{"text": self.t("btn.group"), "url": link}]]}
                                   if link else None)
            return
        thread = m.get("message_thread_id") if m.get("is_topic_message") else None
        here = thread or 0
        mid = m["message_id"]
        rep = m.get("reply_to_message") or {}
        rep_id = rep.get("message_id") if rep and rep.get("message_id") != thread and not rep.get("forum_topic_created") else None
        topic = self.store.topic_by_thread(thread) if thread else None
        log("← %s: %s" % (("topic " + topic["name"]) if topic else ("topic %s (not bound)" % thread) if thread
                          else "General", R.short(text, 80) or "[attachment]"))
        spoken = m.get("voice") or m.get("audio") or m.get("video_note")
        heard = None
        if spoken and (not cmd or cmd == "/new"):
            # a voice message (an audio file, a video note): its words go on exactly as typed text would
            heard = await self.hear_message(spoken, mid, here)
            if heard is None:
                return
            if cmd == "/new":
                rest = (rest + "\n\n" + heard) if rest else heard
            else:
                text = (text + "\n\n" + heard) if text else heard       # a caption first, then the words

        if cmd in ("/start", "/help"):
            await self.send(None, self.t("help"), here=here, buttons=self.help_buttons())
        elif cmd in ("/mode", "/app"):
            await self.post_panel(here)
        elif cmd in ("/auto", "/desk", "/mac", "/phone"):
            await self.set_mode("mac" if cmd == "/desk" else cmd[1:])     # /mac — the name before 0.8.3
            await self.send(None, self.panel_text(), here=here, buttons=self.panel_buttons())
        elif cmd == "/feedback":
            await self.send(None, self.t("feedback", url=REPO_URL + "/issues") if REPO_URL
                            else self.t("feedback.none"), here=here)
        elif cmd == "/status":
            await self.cmd_status(here)
        elif cmd == "/projects":
            await self.cmd_projects(here, "open")
        elif cmd == "/sessions":
            await self.cmd_sessions(topic, here)
        elif cmd == "/stop":
            await self.cmd_stop(rep_id, here, topic, mid)
        elif cmd == "/new" and not rest and not (m.get("photo") or m.get("document") or spoken):
            # a bare /new — a tap in the command menu: the next text in this topic starts a new session
            if topic and topic["path"]:
                self.new_next.add(here)
            await self.send(None, self.t("new.next" if topic and topic["path"] else "new.general"),
                            reply_to=mid, here=here)
        elif rep_id and rep_id in self.req_by_msg:
            req, i = self.req_by_msg[rep_id]
            if req.fut.done():
                await self.send(None, self.t("q.already"), reply_to=mid, here=here)
            elif i is not None:
                self.answer_question(req, i, [text.strip()])
            else:
                self.act(req, "n", text=text.strip())
        elif cmd and cmd != "/new":
            await self.send(None, self.t("cmd.unknown"), reply_to=mid, here=here)
        else:
            body = rest if cmd == "/new" else text
            if heard:
                body = R.spoken_body(body)       # Claude is told the words were spoken: misheard words are to be expected
            body = await self.with_attachments(m, body)
            if not body.strip():
                return
            row = self.store.msg(rep_id) if rep_id else None
            fresh = cmd == "/new" or here in self.new_next
            self.new_next.discard(here)
            if row:
                await self.continue_session(row["sid"], body, mid, here)
            elif topic and topic["path"] and fresh:
                await self.drive(str(uuid.uuid4()), topic["path"], body, mid, pkey=topic["pkey"])
            elif topic and topic["path"]:
                await self.to_topic(topic, body, mid, here)
            elif thread:
                await self.cmd_projects(here, "bind", (body, mid, thread), reply_to=mid)
            else:
                await self.cmd_projects(here, "new", (body, mid), reply_to=mid)

    async def to_topic(self, topic, body, origin, here):
        """Text in a project topic that is not a reply and not /new. It goes without a question to the topic's current
        session (the owner chose it: a button, a reply, /new — remembered until it closes or FOCUS_IDLE passes), or
        to the only session of the project that can be written into right now (a tab with Pult's wrapper, a session
        from Telegram). Otherwise — ask (decision 2026-10-17: both rules; "do it" of 10-16 went to a new session, these
        go to the one the owner is watching). The first time a topic picks a session by itself, Pult says so once;
        after that the reaction on the message and the turn replying to it are enough (0.9.4)."""
        pkey = topic["pkey"]
        target, first = self.focus_of(pkey), False
        if not target:
            open_ = self.open_writable(pkey)
            target, first = (open_[0], True) if len(open_) == 1 else (None, False)
        if not target:
            await self.ask_target(topic, body, origin, here)
            return
        await self.continue_session(target, body, origin, here)
        if first:
            name = I.q(R.esc(R.short(self.session_label(target), 50)))
            await self.send(None, self.t("focus.first", name=name), reply_to=origin, here=here)

    def open_writable(self, pkey):
        """Sessions of the project that a message reaches right now: tabs with Pult's wrapper, sessions from Telegram."""
        out = []
        for t in self.tabs.values():
            if t.sid and (self.session_pkey(t.sid) or sanitize(t.cwd or "")) == pkey and t.sid not in out:
                out.append(t.sid)
        for sid in self.driven:
            if self.session_pkey(sid) == pkey and sid not in out:
                out.append(sid)
        return out

    def session_label(self, sid):
        """Which session of the topic it is: its name or first prompt (as on the "where to" buttons) — not the
        project's name, which all sessions of a topic share."""
        lv = self.live.get(sid) or self.stub(sid)
        return lv.title or self.t("session.default")

    def session_pkey(self, sid):
        row = self.store.session(sid)
        return row["pkey"] if row else None

    def focus_of(self, pkey):
        f = (self.store.get("focus") or {}).get(pkey)
        return f[0] if f and time.time() - f[1] < FOCUS_IDLE else None

    def set_focus(self, pkey, sid):
        """The topic's current session: plain text in the topic goes there. Shown in the topic's card."""
        if not pkey or not sid:
            return
        focus = self.store.get("focus") or {}
        changed = (focus.get(pkey) or [None])[0] != sid
        focus[pkey] = [sid, time.time()]
        self.store.put("focus", focus)
        if changed:
            self.card_refresh(pkey)

    def clear_focus(self, sid):
        """The session closed: its topics have no current session any more."""
        focus = self.store.get("focus") or {}
        gone = [k for k, v in focus.items() if v[0] == sid]
        if not gone:
            return
        for k in gone:
            del focus[k]
        self.store.put("focus", focus)
        for k in gone:
            self.card_refresh(k)

    def card_refresh(self, pkey):
        row = self.store.topic(pkey)
        if not (row and row["thread"]):
            return

        async def go():
            try:
                await self.topic_card(pkey, row["thread"])
            except Exception as e:
                log("topic card:", repr(e))
        asyncio.create_task(go())

    async def ask_target(self, topic, body, origin, here):
        """Text in a project topic that is not a reply: which session is it for? Don't start a new one right away —
        the owner watches one session's turn in the topic and writes as if to it (2026-10-16: "do it" went to a new
        session without context, and that one set about reorganizing another project)."""
        rows = []
        live = {a.get("sessionId") for a in await self.agents()}
        tabbed = {t.sid for t in self.tabs.values() if t.sid}
        for r in self.store.db.execute("SELECT sid, title, last_seen FROM sessions WHERE pkey=? "
                                       "ORDER BY last_seen DESC LIMIT 4", (topic["pkey"],)).fetchall():
            sid = r["sid"]
            lv = self.live.get(sid)
            mark = "📱" if sid in self.driven else "💻" if sid in tabbed else "🖥" if sid in live else "▫️"
            title = (lv.title if lv else None) or r["title"] or self.t("session.default")
            tok = self.offer(("sess", sid, body, origin, here))
            rows.append([{"text": "%s %s · %s" % (mark, R.short(title, 36), when(r["last_seen"])),
                          "callback_data": "t:" + tok}])
        tok = self.offer(("new", topic["path"], topic["pkey"], body, origin))
        rows.append([{"text": self.t("btn.new_session"), "callback_data": "t:" + tok}])
        await self.send(None, self.t("where.ask"), buttons=rows,
                        reply_to=origin, here=here)

    async def with_attachments(self, m, text):
        """Photos and files from Telegram go to ~/.local/share/pult/inbox/; the path goes into the text for Claude."""
        f = None
        if m.get("photo"):
            f = (m["photo"][-1]["file_id"], "jpg")
        elif m.get("document"):
            name = m["document"].get("file_name") or "file"
            f = (m["document"]["file_id"], name.rsplit(".", 1)[-1][:8] if "." in name else "bin")
        if not f:
            return text
        try:
            _, blob = await self.tg.download(f[0])
        except TgError as e:
            return text + "\n\n[An attachment from Telegram failed to download: %s]" % e
        d = HOME / "inbox" / time.strftime("%Y-%m")
        d.mkdir(parents=True, exist_ok=True)
        p = d / ("%d.%s" % (m["message_id"], re.sub(r"[^\w]", "", f[1]) or "bin"))
        p.write_bytes(blob)
        return (text or "Have a look at the attachment.") + "\n\n[Attachment from Telegram: %s]" % p

    # ----- voice: words from a recording (pult_stt — Groq Whisper) -----

    def make_stt(self):
        key = (self.env.get("PULT_STT_KEY") or "").strip()
        return STT.Stt(key, proxy=self.env.get("PULT_PROXY") or None) if key else None

    def refresh_stt(self):
        """A key set or removed with `pult stt` while the daemon runs: the settings file changed — read the voice
        settings again. Nothing else is reloaded this way."""
        mt = env_mtime()
        if mt == self._env_mt:
            return
        self._env_mt = mt
        fresh = load_env()
        for k in ("PULT_STT_KEY", "PULT_STT_LANG"):
            if fresh.get(k):
                self.env[k] = fresh[k]
            else:
                self.env.pop(k, None)
        self.stt = self.make_stt()
        log("voice input: %s (the settings file changed)" % ("on" if self.stt else "off"))

    def stt_lang(self):
        """The language Whisper is told: Pult's own, unless PULT_STT_LANG says otherwise ("auto" — let it guess)."""
        v = (self.env.get("PULT_STT_LANG") or "").strip().lower()
        if v == "auto":
            return None
        return v if re.fullmatch(r"[a-z]{2}", v) else self.lang()

    def stt_state(self):
        self.refresh_stt()
        return {"on": bool(self.stt), "lang": self.stt_lang() or "auto"}

    def stt_prompt(self):
        """Vocabulary for Whisper: Pult's terms and the project names, with punctuation — so the words come out
        spelled right and punctuated (Whisper follows the prompt's style)."""
        names = [r["name"] for r in self.store.db.execute(
            "SELECT name FROM topics WHERE name IS NOT NULL ORDER BY name LIMIT 30").fetchall()]
        return self.t("stt.prompt", projects=", ".join(names) or "—")

    async def hear(self, blob, kind):
        """A recording → its words. Raises pult_stt.SttError — "no key" and "nothing heard" included."""
        self.refresh_stt()
        if not self.stt:
            raise STT.SttError("stt.nokey")
        text = await self.stt.transcribe(blob, kind, language=self.stt_lang(), prompt=self.stt_prompt())
        if not text:
            raise STT.SttError("stt.empty")
        return text

    def stt_why(self, e):
        """An SttError in the owner's words."""
        return self.t(e.key, **e.kw) if e.key in I.S else str(e)

    async def hear_message(self, spoken, mid, here):
        """A voice message from Telegram → its words, or None after telling the owner why not (a reply to it).
        The file is downloaded into memory and kept nowhere."""
        try:
            self.refresh_stt()
            if not self.stt:
                raise STT.SttError("stt.nokey")
            if (spoken.get("file_size") or 0) > STT.MAX_BYTES:
                raise STT.SttError("stt.e.big")
            name, blob = await self.tg.download(spoken["file_id"])
            text = await self.hear(blob, spoken.get("mime_type") or name)
        except (TgError, STT.SttError) as e:
            why = self.stt_why(e) if isinstance(e, STT.SttError) else R.esc(str(e))
            await self.send(None, why if why.startswith("🎤") else self.t("stt.failed", err=why),
                            reply_to=mid, here=here)
            return None
        log("🎤 %s s → %s" % (spoken.get("duration") or "?", R.short(text, 80)))
        return text

    def set_ctx(self, sid, window, max_out, model=None):
        """A turn's result said how big the session's context window is: remembered for the app's context gauge —
        for the session, and for the model, so that other sessions on it show the gauge before their own first result."""
        if not sid or not window:
            return
        val = [int(window), int(max_out or 0)]
        if model and self.ctx_model.get(model_key(model)) != val:
            self.ctx_model[model_key(model)] = val
            self.store.put("ctx_model", self.ctx_model)
        if self.ctx.get(sid) == val:
            return
        self.ctx[sid] = val
        if len(self.ctx) > 300:
            for k in list(self.ctx)[:100]:
                del self.ctx[k]
        self.store.put("ctx", self.ctx)
        self.changed(sid)

    def ctx_of(self, sid, model=None):
        """The session's context window, or the window known for its model."""
        return self.ctx.get(sid) or (self.ctx_model.get(model_key(model)) if model else None)

    def with_uploads(self, text, files):
        """Pictures sent from the app (base64) go to ~/.local/share/pult/inbox/, like attachments from Telegram, and
        Claude gets the path. Only real images by their first bytes, at most UPLOADS_MAX of UPLOAD_MAX each; the rest
        is dropped. Nothing left to send — an error, as for an empty message."""
        text = (text or "").strip()
        paths = []
        for f in (files or [])[:UPLOADS_MAX]:
            try:
                blob = base64.b64decode(str((f or {}).get("data") or ""), validate=True)
            except (ValueError, binascii.Error):
                continue
            kind = image_kind(blob)
            if not kind or len(blob) > UPLOAD_MAX:
                continue
            d = HOME / "inbox" / time.strftime("%Y-%m")
            d.mkdir(parents=True, exist_ok=True)
            p = d / ("app-%d-%s.%s" % (int(time.time() * 1000), secrets.token_hex(2), kind))
            p.write_bytes(blob)
            paths.append(p)
        if paths:
            text = (text or "Have a look at the attachment.") + \
                "".join("\n\n[Attachment from the Pult app: %s]" % p for p in paths)
            log("pictures from the app: %d" % len(paths))
        if not text:
            raise ValueError(self.t("err.empty"))
        return text

    # ----- starting and continuing -----

    async def continue_session(self, sid, text, origin, here):
        row = self.store.session(sid)
        pkey = row["pkey"] if row else None
        path = (row["path"] if row else None) or (self.project_path(pkey) if pkey else None)
        if not path:
            await self.send(None, self.t("err.no_folder"), reply_to=origin, here=here)
            return
        self.set_focus(pkey, sid)
        if origin:
            self.store.map_msg(origin, sid, "owner")     # a reply to one's own message continues the same session
        trow = self.store.topic(pkey)
        quote = bool(trow and trow["thread"] == here)    # a reply in the same topic the session lives in
        if sid in self.driven:
            dr = self.driven[sid]
            dr.q.put_nowait((text, origin if quote else None))
            await self.react(origin, "✍" if dr.busy else "👀")
            return
        tab = self.tab_for(sid)
        if tab:
            # open in a tab with Pult's wrapper: write straight into it (stage 2)
            await self.to_tab(tab, text, origin if quote else None)
            await self.react(origin, "✍" if sid in self.live and self.live[sid].turn else "👀")
            return
        # open on the Mac: `claude agents` says so (research preview), or it sent events
        # and there was no SessionEnd; the second sign backs up the first in case the command goes away
        seen = sid in self.live and not self.live[sid].driven
        if seen or any(a.get("sessionId") == sid for a in await self.agents()):
            tok = self.offer((sid, path, text, origin, quote, here))
            await self.send(None, self.t("fork.offer"), reply_to=origin, here=here,
                            buttons=[[{"text": self.t("btn.fork"), "callback_data": "f:" + tok}]])
            return
        await self.drive(sid, path, text, origin, resume=sid, pkey=pkey, quote=quote, here=here)

    def set_choice(self, sid, model=None, effort=None):
        """The owner's model and effort for a session from Telegram; kept, so a resume starts the same way."""
        cur = dict(self.choice.get(sid) or {})
        if model is not None:
            cur["model"] = model or None
        if effort is not None:
            cur["effort"] = effort or None
        cur = {k: v for k, v in cur.items() if v}
        if cur:
            self.choice[sid] = cur
        else:
            self.choice.pop(sid, None)
        if len(self.choice) > 300:
            for k in list(self.choice)[:100]:
                del self.choice[k]
        self.store.put("choice", self.choice)

    async def drive(self, sid, path, text, origin, resume=None, fork=False, pkey=None, quote=True, here=None,
                    model=None, effort=None):
        """quote=False — the owner's message is in another topic (General): the turn doesn't reply to it
        but shows the prompt itself. here — where the owner wrote (for a refusal); the project topic by default.
        model, effort — the owner's choice for a new session; a resumed one keeps what was chosen for it."""
        pkey = pkey or sanitize(path)
        if fork:
            resume, sid = sid, str(uuid.uuid4())
        if model or effort:
            self.set_choice(sid, model, effort)
        choice = self.choice.get(sid) or {}
        if len(self.driven) >= MAX_DRIVEN:
            idle = [d for d in self.driven.values() if not d.busy and d.q.empty() and not d.bg]
            if not idle:
                await self.send(pkey, self.t("busy.driven", n=len(self.driven), sessions=I.plural(len(self.driven), "session")),
                                reply_to=origin, here=here)
                return
            idle[0].task.cancel()
        self.store.touch_session(sid, pkey, path=path, driven=True)
        self.set_focus(pkey, sid)
        if origin:
            self.store.map_msg(origin, sid, "owner")
        lv = self.live_of(sid, pkey)
        lv.driven, lv.cwd = True, path
        lv.title = lv.title or R.short(R.attachments(text)[0], 60) or None
        dr = self.driven[sid] = Driven(self, sid, path, resume=resume, fork=fork,
                                       model=choice.get("model"), effort=choice.get("effort"))
        dr.q.put_nowait((text, origin if quote else None))
        await self.react(origin, "👀")
        log("Telegram session:", sid[:8], "fork" if fork else "resume" if resume else "new", path)

    # ----- VS Code tabs with Pult's wrapper (stage 2) -----

    async def on_tab(self, hello, reader, writer):
        """The tab wrapper (pult_tab.py) keeps a connection open while the tab is alive: it reports the session id
        and accepts messages for it. If the connection drops, the tab works as usual but can't be written into."""
        t = SimpleNamespace(pid=hello.get("pid"), cwd=hello.get("cwd"), sid=hello.get("sid"),
                            version=hello.get("version"), writer=writer,
                            caps=set(hello.get("caps") or []))      # an older wrapper (before 0.9.8) sends none
        self.tabs[t.pid] = t
        log("tab with the wrapper: pid %s, %s, Claude Code %s" % (t.pid, t.cwd, t.version))
        try:
            while True:
                line = await reader.readline()
                if not line:
                    break
                m = json.loads(line)
                if m.get("op") == "sid":
                    t.sid = m.get("sid")
                    self.changed(t.sid)
                elif m.get("op") == "ctx" and t.sid:          # the wrapper saw a turn's result: the context window
                    self.set_ctx(t.sid, m.get("window"), m.get("max_out") or 0, model=m.get("model"))
        finally:
            if self.tabs.get(t.pid) is t:
                del self.tabs[t.pid]
            if t.sid:
                self.clear_focus(t.sid)
            log("tab with the wrapper closed: pid %s" % t.pid)

    async def tab_version_watch(self):
        while True:
            try:
                await self.tab_version_check()
            except Exception as e:
                log("version check for tabs:", repr(e))
            await asyncio.sleep(TAB_CHECK_EVERY)

    async def tab_version_check(self):
        """A new Claude Code extension version is out: the tab wrapper injects nothing on it until the version is
        verified (tests/probe_tab.py, probe_race.py → pult tab allow). The owner is told about it once."""
        try:
            conf = json.loads(TAB_CONF.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        wrapped = bool(pult_os.files_with(EDITOR_DIRS, "pult-tab.sh"))
        v = pult_os.newest_extension(EXT_DIRS)
        if not wrapped or not v or v in (conf.get("versions") or []) or self.store.get("tab_warned") == v:
            return
        self.store.put("tab_warned", v)
        log("Claude Code extension %s is not verified — writing into tabs is off on it" % v)
        await self.send(None, self.t("tab.update", v=R.esc(v)), notify=True)

    def tab_for(self, sid):
        return next((t for t in self.tabs.values() if sid and t.sid == sid), None)

    async def to_tab(self, tab, text, origin):
        self.tab_expect[tab.sid] = (origin, text)
        if origin:
            self.store.map_msg(origin, tab.sid, "owner")
        tab.writer.write((json.dumps({"op": "send", "text": text, "uuid": str(uuid.uuid4())},
                                     ensure_ascii=False) + "\n").encode())
        await tab.writer.drain()
        log("message to a tab:", tab.sid[:8])

    async def react(self, msg, emoji):
        if not msg:
            return
        try:
            await self.tg.call("setMessageReaction", chat_id=self.chat, message_id=msg,
                               reaction=[{"type": "emoji", "emoji": emoji}])
        except TgError:
            pass

    # ----- commands -----

    async def cmd_status(self, here):
        agents = await self.agents()
        idle = await self.idle()
        by = {}
        for a in agents:
            if a.get("sessionId") not in self.driven:
                by.setdefault(a.get("cwd") or "?", []).append(a)
        for sid, dr in self.driven.items():
            by.setdefault(dr.path, []).append({"sessionId": sid, "status": "busy" if dr.busy else "idle",
                                               "driven": True})
        lines = [self.t("status.head", state=self.t("status.at_mac") if idle < AWAY_IDLE else
                        self.t("status.idle", dur=R.human_dur(idle)))]
        if not by:
            lines.append(self.t("status.none"))
        for cwd, items in sorted(by.items()):
            lines.append("\n<b>%s</b>" % R.esc(os.path.basename(cwd.rstrip("/")) or cwd))
            for a in items:
                sid = a.get("sessionId") or ""
                lv = self.live.get(sid)
                if lv and lv.pending:
                    st = self.t("status.ask")
                elif a.get("status") == "busy" or (lv and lv.turn):
                    st = self.t("status.work") + (" %s" % R.human_dur(time.time() - lv.turn.started) if lv and lv.turn else "")
                else:
                    st = self.t("status.idle_sess")
                row = self.store.session(sid)
                title = (lv.title if lv else None) or (row["title"] if row else None) or a.get("name") or self.t("session.default")
                lines.append("%s %s — %s" % ("📱" if a.get("driven") else "🖥", R.esc(R.short(title, 50)), st))
        await self.send(None, "\n".join(lines), here=here)

    @staticmethod
    def list_projects(known):
        """Projects with transcripts, most recent first. Runs in a separate thread, so it doesn't touch the database:
        the known topic paths are passed in known."""
        out = []
        for d in CLAUDE_PROJECTS.iterdir() if CLAUDE_PROJECTS.exists() else []:
            if skip_pkey(d.name):
                continue
            files = list(d.glob("*.jsonl"))
            if not files:
                continue
            path = known.get(d.name) or decode_pkey(d.name)
            if path and os.path.isdir(path):
                out.append((max(f.stat().st_mtime for f in files), d.name, path))
        return sorted(out, reverse=True)

    async def cmd_projects(self, here, mode, pending=None, reply_to=None):
        """Project buttons. mode: open — give a link to the topic; new — start a session with the text from
        General; bind — bind a topic the owner created and start a session in it."""
        rows = []
        known = {r["pkey"]: r["path"] for r in self.store.db.execute("SELECT pkey, path FROM topics") if r["path"]}
        for _, pkey, path in (await asyncio.to_thread(self.list_projects, known))[:20]:
            tok = self.offer((mode, pkey, path, pending))
            rows.append([{"text": self.project_name(pkey, path), "callback_data": "o:" + tok}])
        text = self.t("projects." + mode)
        await self.send(None, text if rows else self.t("projects.none"), buttons=rows,
                        here=here, reply_to=reply_to)

    async def cmd_sessions(self, topic, here):
        if not topic or not topic["path"]:
            await self.send(None, self.t("sessions.where"), here=here)
            return
        from claude_agent_sdk import list_sessions
        items = await asyncio.to_thread(list_sessions, topic["path"], 10)
        live = {a.get("sessionId") for a in await self.agents()}
        rows = []
        for s in items:
            tok = self.offer((topic["pkey"], topic["path"], s.session_id))
            mark = "📱" if s.session_id in self.driven else "🖥" if s.session_id in live else "▫️"
            rows.append([{"text": "%s %s · %s" % (mark, R.short(s.custom_title or s.summary or "—", 36),
                                                  when(s.last_modified / 1000)),
                          "callback_data": "s:" + tok}])
        await self.send(topic["pkey"], self.t("sessions.list") if rows else self.t("sessions.none"),
                        buttons=rows)

    async def session_card(self, pkey, path, sid):
        from claude_agent_sdk import get_session_info, get_session_messages
        info = await asyncio.to_thread(get_session_info, sid, path)
        msgs = await asyncio.to_thread(get_session_messages, sid, path)
        last = ""
        for sm in reversed(msgs):
            if sm.type != "assistant":
                continue
            content = (sm.message or {}).get("content")
            if isinstance(content, str):
                last = content
            else:
                last = "\n".join(b.get("text", "") for b in content or [] if isinstance(b, dict) and b.get("type") == "text")
            if last.strip():
                break
        title = (info.custom_title or info.summary) if info else self.t("session.default")
        self.store.touch_session(sid, pkey, path=path, title=R.short(title, 60))
        md = last if len(last) <= 3000 else "…" + last[-3000:]
        await self.send(pkey, self.t("card", title=R.esc(R.short(title, 80)),
                                     body=R.md_to_html(md) if md else self.t("card.empty")),
                        sid=sid, kind="card")

    # ----- the "where am I" panel and help -----

    def panel_text(self):
        m = self.mode()
        return self.t("panel", mode=self.t("mode." + m), about=self.t("mode.%s.%s" % (m, "pager" if self.pager() else "about"))) + \
            (self.t("panel.app") if self.app_url() else "")

    def panel_buttons(self):
        m = self.mode()
        rows = [[{"text": ("✓ " if k == m else "") + self.t("mode.%s.btn" % k), "callback_data": "w:" + k} for k in MODES]]
        if self.app_url():
            rows.append([{"text": self.t("panel.open"), "url": self.app_url()}])
        return rows

    async def post_panel(self, here):
        """Pult's panel: notification mode buttons and the way into the app. In General, pin it (unpin the old one)."""
        mid = await self.send(None, self.panel_text(), here=here, buttons=self.panel_buttons())
        if mid and not here:
            old = self.store.get("panel")
            try:
                await self.tg.call("pinChatMessage", chat_id=self.chat, message_id=mid, disable_notification=True)
                if old and old != mid:
                    await self.tg.call("unpinChatMessage", chat_id=self.chat, message_id=old)
            except TgError as e:
                log("pin failed:", e)
            self.store.put("panel", mid)
        return mid

    async def ensure_panel(self):
        """No panel yet (a new group or Pult before 0.6): post it and pin it once. There is one — refresh its text
        and buttons on startup: the language, the mode or the app link may have changed."""
        if not self.chat:
            return
        if self.store.get("welcome"):        # the group was just bound by `pult setup`: help first, as after /bind
            self.store.put("welcome", False)
            await self.send(None, self.t("help"), here=0, buttons=self.help_buttons())
        if not self.store.get("panel"):
            await self.post_panel(0)
        else:
            self.edit(self.store.get("panel"), self.panel_text(), self.panel_buttons(), prio=6)
        await self.ensure_cards()

    async def set_mode(self, mode):
        cur = self.prefs()
        cur["mode"] = mode
        self.store.put("prefs", cur)
        log("notification mode:", mode)
        panel = self.store.get("panel")
        if panel:
            self.edit(panel, self.panel_text(), self.panel_buttons(), prio=1)
        self.changed()

    HELP_SECTIONS = ("start", "notify", "write", "app", "onoff", "trouble")

    def help_section(self, sec):
        if sec == "app":
            return self.t("help.app") + ("" if self.app_url() else self.t("help.app.off"))
        if sec == "onoff":
            return self.t("help.onoff")
        if sec == "trouble":
            home = str(Path.home())
            log_path = str(LOG_FILE)
            return self.t("help.trouble", log=R.esc("~" + log_path[len(home):] if log_path.startswith(home + "/")
                                                    else log_path))
        return self.t("help." + sec) if sec in self.HELP_SECTIONS else self.t("help")

    def help_buttons(self, cur="main"):
        btn = lambda k: {"text": self.t("help.btn." + k), "callback_data": "h:" + k}
        rows = [[btn(a), btn(b)] for a, b in zip(self.HELP_SECTIONS[::2], self.HELP_SECTIONS[1::2])]
        if cur != "main":
            rows.append([{"text": self.t("help.btn.back"), "callback_data": "h:main"}])
        return rows

    async def cmd_stop(self, rep_id, here, topic=None, mid=None):
        """/stop as a reply — that session; in a project topic without a reply — the topic's current session, or the
        only session from Telegram in the project (0.9.4: a tap in the command menu sends a bare /stop)."""
        row = self.store.msg(rep_id) if rep_id else None
        sid = row["sid"] if row else None
        if not sid and topic:
            sid = self.focus_of(topic["pkey"])
            if not sid:
                ours = [s for s in self.driven if self.session_pkey(s) == topic["pkey"]]
                sid = ours[0] if len(ours) == 1 else None
        dr = self.driven.get(sid) if sid else None
        if not dr or not dr.client or not dr.busy:
            key = "stop.how" if rep_id or not topic else "stop.tab" if sid and self.tab_for(sid) else "stop.none"
            await self.send(None, self.t(key), here=here)
            return
        await dr.client.interrupt()
        await self.react(rep_id or mid, "🫡")

    # ----- web app (stage 1B): app window requests via pult_web -----

    def app_url(self, sid=None, start=None):
        """Link to the app (a Direct Link Mini App): in a Telegram group only such link buttons work,
        web_app buttons only in a private chat with the bot (verified 2026-10-16)."""
        link = self.env.get("PULT_APP_LINK")
        if not link:
            return None
        start = "s_" + sid if sid else start
        return link + ("?startapp=" + start if start else "")

    def app_row(self, sid, label=None):
        url = self.app_url(sid)
        return [{"text": label or self.t("btn.details"), "url": url}] if url else None

    def with_app(self, rows, sid, label=None):
        row = self.app_row(sid, label)
        return (rows or []) + [row] if row else rows

    def app_live(self):
        return bool(self.web and self.web.ws is not None and self.app_url())

    def changed(self, sid=None):
        """Something changed: app windows re-read the overview and the open session."""
        if self.web:
            self.web.emit("change", sid=sid)

    def project_label(self, pkey):
        row = self.store.topic(pkey)
        return row["name"] if row and row["name"] else (pkey or "").rsplit("-", 1)[-1]

    def live_item(self, lv):
        t = lv.turn
        return {"sid": lv.sid, "title": self.title(lv), "project": self.project_label(lv.pkey), "pkey": lv.pkey,
                "driven": lv.driven, "state": "ask" if lv.pending else "work" if t else "idle",
                "started": t.started if t else None, "prompt": R.short(R.prompt_text(t.prompt), 300) if t and t.prompt else None,
                "note": t.note if t else None, "now": R.plain(t.now, NOW_LEN) if t and t.now else None,
                "bg": [R.short(b.get("description") or b.get("command") or self.t("task.default"), 80) for b in lv.bg],
                "tab": bool(self.tab_for(lv.sid))}

    def req_item(self, req):
        lv = self.live.get(req.sid) or self.stub(req.sid)
        d = {"rid": req.rid, "sid": req.sid, "kind": req.kind, "tool": req.tool, "title": self.title(lv),
             "project": self.project_label(lv.pkey), "suggest": bool(req.suggestions)}
        if req.kind == "ask":
            d["questions"] = req.inp.get("questions") or []
            d["chosen"] = {str(i): v for i, v in req.chosen.items()}
        elif req.kind == "plan":
            d["plan"] = str(req.inp.get("plan") or "")[:20000]
        else:
            d["html"] = R.permission_text(req.tool, req.inp, lv.cwd)     # everything is escaped in R
        return d

    def transcript_of(self, sid):
        if not SID_RE.fullmatch(sid or ""):
            raise ValueError(self.t("err.bad_sid"))
        lv = self.live.get(sid)
        if lv and lv.transcript:
            return lv.transcript, lv
        row = self.store.session(sid)
        if row and row["pkey"]:
            p = CLAUDE_PROJECTS / row["pkey"] / (sid + ".jsonl")
            if p.exists():
                return str(p), lv
        found = next(CLAUDE_PROJECTS.glob("*/%s.jsonl" % sid), None)
        if not found:
            raise ValueError(self.t("err.no_transcript"))
        return str(found), lv

    async def api_overview(self):
        agents = await self.agents()
        idle = await self.idle()
        shown = {sid for sid, lv in self.live.items() if lv.turn or lv.pending or lv.bg}
        opened = []
        for a in agents:
            sid = a.get("sessionId")
            if sid and sid not in shown:
                lv = self.live.get(sid) or self.stub(sid, sanitize(a.get("cwd") or ""))
                opened.append(dict(self.live_item(lv), project=os.path.basename((a.get("cwd") or "").rstrip("/"))))
        load = await self.load_state()
        return {"mac": {"idle": idle, "away": await self.away(), "mode": self.mode()}, "now": time.time(),
                "lang": self.lang(), "load": self.load_sum(load[2], load[3]) if load else None,
                "live": [self.live_item(self.live[s]) for s in shown],
                "pending": [self.req_item(r) for r in self.req_by_rid.values() if not r.fut.done()],
                "open": opened, "recent": list(self.recent),
                "jobs": [self.job_item(j) for j in self.jobs.values()] + [self.job_item(j) for j in self.jobs_done],
                **await self.board(agents)}

    async def api_seen(self, sid):
        """"Got it" on a card of "Your move": the outcome is seen without opening the session."""
        self.mark_seen(sid)
        return {"ok": True}

    async def ctx_pct(self, sid):
        """How full the session's context is, % — the number VS Code shows; None if unknown."""
        try:
            path, _ = self.transcript_of(sid)
        except ValueError:
            return None
        st = await asyncio.to_thread(self.stats.get, path)
        ctx = self.ctx_of(sid, (st or {}).get("model"))
        if not st or not st.get("context") or not ctx:
            return None
        return min(100, round(st["context"] * 100 / ctx_usable(ctx[0], ctx[1])))

    def session_rows(self, agents):
        """Every session worth a look — running, waiting, open on the computer, or with an outcome in the last days
        (pult_attn.KEEP) — one row each: its state (pult_attn.state), a line (what it does now or how its last turn
        ended), what the owner has to do, ready replies, the times."""
        opened = {a.get("sessionId"): a for a in agents if a.get("sessionId")}
        sids = set(self.live) | set(self.driven) | set(opened) | set(self.attn.rec)
        rows = []
        for sid in sids:
            rec = self.attn.rec.get(sid) or {}
            lv = self.live.get(sid)
            if lv is None:
                row = self.store.session(sid)
                cwd = (opened.get(sid) or {}).get("cwd")
                lv = self.stub(sid, rec.get("pkey") or (row["pkey"] if row else None) or sanitize(cwd or ""))
                lv.cwd = cwd or (row["path"] if row else None)
            if skip_pkey(lv.pkey):
                continue
            t = lv.turn
            pending = [r for r in lv.pending.values() if not r.fut.done()]
            st = A.state(pending, t is not None, lv.bg or (sid in self.driven and self.driven[sid].bg), rec or None)
            since = min(getattr(r, "ts", 0) or time.time() for r in pending) if pending else t.started if t else rec.get("ts")
            line = (R.plain(t.now, NOW_LEN) if t.now else R.short(R.prompt_text(t.prompt), 160) if t.prompt
                    else t.note or "") if t else rec.get("line") or ""
            # on the board a session sits under its project: its own title, or its first prompt, never the project again
            rows.append({"sid": sid, "pkey": lv.pkey, "title": lv.title or self.title(lv), "state": st, "since": since,
                         "ts": rec.get("ts"), "line": line, "need": rec.get("need") or "", "replies": rec.get("replies") or [],
                         "fail": rec.get("fail"), "resume": self.attn.resume.get(sid),
                         "dur": rec.get("dur"), "driven": sid in self.driven, "tab": bool(self.tab_for(sid)),
                         "open": sid in opened, "model": bool(rec.get("model")),
                         "bg": [R.short(b.get("description") or b.get("command") or self.t("task.default"), 80) for b in lv.bg],
                         "cwd": lv.cwd})
        return rows

    def name_of(self, pkey, rows=()):
        """A project's name: its topic's, else its folder's."""
        cwd = next((r["cwd"] for r in rows if r.get("cwd")), None) or self.project_path(pkey)
        return self.project_label(pkey) if self.store.topic(pkey) else \
            os.path.basename((cwd or "").rstrip("/")) or self.project_label(pkey)

    def limit_reset(self):
        """When the 5-hour usage window resets, from the last usage reading (no new request), or None."""
        for lim in (self._usage or {}).get("limits") or []:
            if lim.get("kind") in ("session", "five_hour") and lim.get("resets_at"):
                return lim["resets_at"]
        return None

    async def board(self, agents):
        """The Home board (stage V): every session worth a look grouped by project; and "mine": the outcomes that
        wait for the owner. Requests waiting for an answer are not repeated here: the app shows them as answerable
        cards (overview.pending)."""
        now = time.time()
        by = {}
        for r in self.session_rows(agents):
            by.setdefault(r["pkey"], []).append(r)
        projects = []
        for pkey, rs in by.items():
            turns, secs = self.attn.day_of(pkey)
            shown = [r for r in A.sort_rows(rs) if r["state"] not in A.MINE and not A.resting(r, now)]
            for r in shown:
                r["ctx"] = await self.ctx_pct(r["sid"])
            projects.append({"pkey": pkey, "name": self.name_of(pkey, rs), "rows": shown, "rows_all": rs,
                             "resting": sum(1 for r in rs if A.resting(r, now)),
                             "work": sum(1 for r in rs if r["state"] in ("work", "bg")),
                             "mine": sum(1 for r in rs if r["state"] in A.MINE), "turns": turns, "secs": secs})
        mine = A.sort_rows([dict(r, project=p["name"]) for p in projects for r in p["rows_all"] if r["state"] in ("you", "fail")])
        projects = A.sort_projects(projects)
        for p in projects:
            del p["rows_all"]
        return {"board": projects, "mine": mine, "brief": self.prefs()["brief"], "reset": self.limit_reset(),
                "usage_pct": self.limit_pct(), "catchup": self.catchup(), "stt": self.stt_state()["on"],
                "pager": self.pager()}

    async def api_project(self, pkey):
        """A project's screen — its board, large: what waits for the owner (requests to answer here, sessions that
        need them), what runs, today's outcomes, then the earlier sessions."""
        rows = [r for r in self.session_rows(await self.agents()) if r["pkey"] == pkey]
        path = self.project_path(pkey) or next((r["cwd"] for r in rows if r["cwd"]), None)
        if not path and not rows:
            raise ValueError(self.t("err.no_project"))
        midnight = time.mktime(time.localtime()[:3] + (0, 0, 0, 0, 0, -1))
        pending = [self.req_item(r) for r in self.req_by_rid.values()
                   if not r.fut.done() and (self.live.get(r.sid) or self.stub(r.sid)).pkey == pkey]
        mine = A.sort_rows([r for r in rows if r["state"] in ("you", "fail")])
        live = A.sort_rows([r for r in rows if r["state"] in ("work", "bg")])
        today = sorted([r for r in rows if r["state"] in ("done", "idle") and (r["ts"] or 0) >= midnight],
                       key=lambda r: -(r["ts"] or 0))
        for r in live + today:
            r["ctx"] = await self.ctx_pct(r["sid"])
        shown = {r["sid"] for r in mine + live + today} | {r["sid"] for r in pending}
        earlier = []
        if path and os.path.isdir(path):
            from claude_agent_sdk import list_sessions
            try:
                items = await asyncio.to_thread(list_sessions, path, 40)
            except Exception as e:
                log("project sessions not listed:", repr(e))
                items = []
            known = {r["sid"]: r for r in rows}
            for x in items:
                if x.session_id in shown:
                    continue
                r = known.get(x.session_id) or {}
                earlier.append({"sid": x.session_id, "title": R.short(x.custom_title or x.summary or "—", 80),
                                "last": x.last_modified / 1000, "line": r.get("line") or "", "open": bool(r.get("open")),
                                "driven": x.session_id in self.driven})
        turns, secs = self.attn.day_of(pkey)
        return {"pkey": pkey, "name": self.name_of(pkey, rows), "path": path, "pending": pending, "mine": mine,
                "live": live, "today": today, "earlier": earlier, "turns": turns, "secs": secs,
                "reset": self.limit_reset(), "stt": self.stt_state()["on"]}

    # ----- the load on the computer: the processor and memory Claude's sessions take -----

    async def snapshot(self):
        """Every process and the computer as a whole (pult_os.processes), kept LOAD_TTL s; None — the system can't
        tell."""
        t, v = self._procs
        if time.monotonic() - t < LOAD_TTL:
            return v
        v = await asyncio.to_thread(pult_os.processes)
        self._procs = (time.monotonic(), v)
        return v

    async def claude_roots(self, procs):
        """sid → (claude's pid, folder) for each session with a process here: `claude agents` lists VS Code tabs,
        terminals and Pult's own sessions (probe_load.py); the hook's parent and Pult's own children cover a miss."""
        roots = {}
        for a in await self.agents():
            sid, pid = a.get("sessionId"), a.get("pid")
            if sid and pid in procs and sid not in roots:
                roots[sid] = (pid, a.get("cwd"))
        for sid, lv in self.live.items():
            if sid not in roots and lv.pid in procs and L.is_claude(procs[lv.pid]["cmd"]):
                roots[sid] = (lv.pid, lv.cwd)
        me = os.getpid()
        for pid, d in procs.items():
            sid = L.session_arg(d["cmd"]) if d["ppid"] == me and L.is_claude(d["cmd"]) else None
            if sid and sid not in roots:
                roots[sid] = (pid, getattr(self.driven.get(sid), "path", None))
        return roots

    def load_row(self, sid, pid, cwd, procs, kids, cores):
        lv = self.live.get(sid)
        if lv is None:
            lv = self.stub(sid, self.session_pkey(sid) or sanitize(cwd or ""))
            lv.cwd = cwd
        known = self.store.topic(lv.pkey)
        return dict(L.session(procs, pid, kids, cores, lv.bg), sid=sid, title=self.title(lv),
                    project=self.project_label(lv.pkey) if known else os.path.basename((cwd or "").rstrip("/"))
                    or self.project_label(lv.pkey),
                    state="ask" if lv.pending else "work" if lv.turn else "bg" if lv.bg else "idle",
                    driven=sid in self.driven)

    async def load_state(self):
        """(procs, kids, machine, rows — one per session, the busiest first), or None where the system can't tell."""
        snap = await self.snapshot()
        if not snap:
            return None
        procs, mac = snap
        kids = L.children(procs)
        rows = [self.load_row(sid, pid, cwd, procs, kids, mac["cores"])
                for sid, (pid, cwd) in (await self.claude_roots(procs)).items()]
        rows.sort(key=lambda r: (-r["cpu"], -r["mem"]))
        return procs, kids, mac, rows

    @staticmethod
    def load_sum(mac, rows):
        return {"cpu": round(mac["cpu"], 1), "cores": mac["cores"], "load": round(mac["load"], 1),
                "mem_used": mac["mem_used"], "mem_total": mac["mem_total"],
                "claude": {"n": len(rows), "cpu": round(sum(r["cpu"] for r in rows), 1),
                           "mem": sum(r["mem"] for r in rows)}}

    async def api_load(self, sid=None):
        """The load view: the computer and every session on it; with sid — that session and its background tasks."""
        st = await self.load_state()
        if not st:
            return {"ok": False}
        procs, kids, mac, rows = st
        out = {"ok": True, "mac": self.load_sum(mac, rows), "now": time.time()}
        if not sid:
            return dict(out, sessions=rows)
        row = next((r for r in rows if r["sid"] == sid), None)
        lv, used = self.live.get(sid), set()
        tasks = [L.task(procs, row and row["pid"], kids, mac["cores"], b, lv.bg_seen.get(b.get("id")), used)
                 for b in (lv.bg if lv else [])]
        return dict(out, session=row, tasks=tasks)

    async def project_counts(self):
        """Per project: sessions open right now (on the computer or from Telegram), working, waiting for an answer."""
        by = {}

        def add(pkey, sid, work, ask):
            if not pkey or not sid:
                return
            d = by.setdefault(pkey, {"open": set(), "work": set(), "ask": set()})
            d["open"].add(sid)
            if work:
                d["work"].add(sid)
            if ask:
                d["ask"].add(sid)
        for a in await self.agents():
            sid = a.get("sessionId")
            lv = self.live.get(sid)
            add(self.session_pkey(sid) or sanitize(a.get("cwd") or ""), sid,
                a.get("status") == "busy" or bool(lv and lv.turn), bool(lv and lv.pending))
        for sid, dr in self.driven.items():
            lv = self.live.get(sid)
            add(self.session_pkey(sid) or sanitize(dr.path), sid, dr.busy, bool(lv and lv.pending))
        for sid, lv in self.live.items():
            if lv.turn or lv.pending:                 # a tab mid-turn counts even if `claude agents` missed it
                add(lv.pkey, sid, bool(lv.turn), bool(lv.pending))
        return {k: {n: len(v[n]) for n in ("open", "work", "ask")} for k, v in by.items()}

    async def api_projects(self):
        known = {r["pkey"]: r["path"] for r in self.store.db.execute("SELECT pkey, path FROM topics") if r["path"]}
        counts = await self.project_counts()
        by = {}
        for r in self.session_rows(await self.agents()):
            by.setdefault(r["pkey"], []).append(r)
        out = []
        for mtime, pkey, path in (await asyncio.to_thread(self.list_projects, known))[:40]:
            c = counts.get(pkey) or {}
            rs = by.get(pkey) or []
            last = max((r for r in rs if r["ts"]), key=lambda r: r["ts"], default=None)
            out.append({"pkey": pkey, "name": self.project_label(pkey) if pkey in known else self.project_name(pkey, path),
                        "path": path, "last": mtime, "open": c.get("open", 0), "work": c.get("work", 0), "ask": c.get("ask", 0),
                        "mine": sum(1 for r in rs if r["state"] in A.MINE), "line": last["line"] if last else "",
                        "turns": self.attn.day_of(pkey)[0]})
        # what needs you first, then what works, then what is open, then by recency
        out.sort(key=lambda r: (-(r["mine"] > 0), -(r["work"] + r["ask"] > 0), -(r["open"] > 0), -r["last"]))
        return {"projects": out, "stt": self.stt_state()["on"]}      # stt: the app shows the microphone only with a key

    async def api_sessions(self, pkey):
        path = self.project_path(pkey)
        if not path:
            raise ValueError(self.t("err.no_project"))
        from claude_agent_sdk import list_sessions
        items = await asyncio.to_thread(list_sessions, path, 30)
        live = {a.get("sessionId") for a in await self.agents()}
        return {"pkey": pkey, "name": self.project_label(pkey), "sessions": [
            {"sid": s.session_id, "title": R.short(s.custom_title or s.summary or "—", 80), "named": bool(s.custom_title),
             "last": s.last_modified / 1000, "open": s.session_id in live, "driven": s.session_id in self.driven}
            for s in items]}

    async def api_session(self, sid, before=None, after=None):
        path, lv = self.transcript_of(sid)
        row = self.store.session(sid)
        lv = lv or self.stub(sid, row["pkey"] if row else Path(path).parent.name)
        # the session's last outcome, as the owner found it (before opening it marks it seen): the app shows it at
        # the end of the chat — what came out, what is needed, ready replies — until the next turn
        rec = self.attn.rec.get(sid)
        pending = [r for r in lv.pending.values() if not r.fut.done()]
        outcome = None
        if rec and lv.turn is None:
            outcome = {k: rec.get(k) for k in ("line", "need", "replies", "fail", "ts", "dur")}
            outcome.update(state=A.state(pending, False, lv.bg, rec), resume=self.attn.resume.get(sid),
                           reset=self.limit_reset() if rec.get("fail") == "rate_limit" else None)
        self.mark_seen(sid)                        # the owner opened it: its outcome no longer calls them
        page = await asyncio.to_thread(PW.transcript_page, path, before, after, lv.cwd)
        stats = await asyncio.to_thread(self.stats.get, path)
        live = self.live_item(lv)
        # open on the computer without Pult's wrapper: a message from here goes as a copy — the app says so up front
        seen = sid in self.live and not lv.driven and lv.turn is not None
        live["open"] = (seen or any(a.get("sessionId") == sid for a in await self.agents())) \
            and not live["tab"] and sid not in self.driven
        ctx = self.ctx_of(sid, (stats or {}).get("model"))
        # the model can be picked from here: a session Pult runs, a tab with Pult's wrapper, or a closed session that
        # Pult would resume; only a session open on the computer without the wrapper keeps its own
        tab = self.tab_for(sid)
        ours = sid in self.driven or not (live["open"] or live["tab"])
        switch = ours or (tab is not None and "model" in tab.caps)
        switch_effort = ours or (tab is not None and "control" in tab.caps)       # a wrapper from 0.9.9 on
        # the session's own title, as on the board (its first prompt until it has a name), the project beside it
        return {"sid": sid, "title": lv.title or self.title(lv), "project": self.project_label(lv.pkey), "pkey": lv.pkey,
                "outcome": outcome,
                "live": live, "page": page, "stats": stats, "choice": self.choice.get(sid) or {}, "switch": switch,
                "switch_effort": switch_effort, "stt": self.stt_state()["on"],
                "ctx": {"window": ctx[0], "max_out": ctx[1], "usable": ctx_usable(ctx[0], ctx[1])} if ctx else None,
                "pending": [self.req_item(r) for r in lv.pending.values() if not r.fut.done()]}

    async def api_answer(self, rid, act=None, answers=None, text=None):
        req = self.req_by_rid.get(rid)
        if not req or req.fut.done():
            return {"ok": False, "note": self.t("note.decided")}
        if req.kind == "ask":
            qs = req.inp.get("questions") or []
            for i, vals in (answers or {}).items():
                i = int(i)
                if 0 <= i < len(qs) and vals:
                    self.answer_question(req, i, [str(v) for v in vals])
            return {"ok": True}
        note = self.act(req, act, "app", text=(text or "").strip() or None)
        return {"ok": note is None, "note": note}

    async def api_send(self, sid, text, fork=False, files=None):
        """files — pictures from the app's composer; they are saved only once the way is known (a "fork?" answer
        makes the app ask and send again)."""
        text = (text or "").strip()
        if not text and not files:
            raise ValueError(self.t("err.empty"))
        path, lv = self.transcript_of(sid)
        row = self.store.session(sid)
        pkey = row["pkey"] if row else Path(path).parent.name
        cwd = (row["path"] if row else None) or self.project_path(pkey)
        if not cwd:
            raise ValueError(self.t("err.no_folder_short"))
        self.mark_seen(sid)                        # answered from a card: the outcome is behind
        if sid in self.driven:
            self.driven[sid].q.put_nowait((self.with_uploads(text, files), None))
            return {"ok": True, "how": "session"}
        tab = self.tab_for(sid)
        if tab:
            await self.to_tab(tab, self.with_uploads(text, files), None)
            return {"ok": True, "how": "tab"}
        seen = sid in self.live and not self.live[sid].driven and self.live[sid].turn is not None
        if seen or any(a.get("sessionId") == sid for a in await self.agents()):
            if not fork:
                return {"ok": False, "need": "fork"}
            await self.drive(sid, cwd, self.with_uploads(text, files), None, fork=True, pkey=pkey)
            return {"ok": True, "how": "fork"}
        await self.drive(sid, cwd, self.with_uploads(text, files), None, resume=sid, pkey=pkey)
        return {"ok": True, "how": "resume"}

    @staticmethod
    def check_choice(model, effort):
        model = (model or "").strip() or None
        effort = (effort or "").strip() or None
        if model and not MODEL_RE.fullmatch(model) or effort and effort not in EFFORTS:
            raise ValueError("bad model or effort")
        return model, effort

    async def api_new(self, pkey, text, files=None, model=None, effort=None):
        text = (text or "").strip()
        path = self.project_path(pkey)
        if not (text or files) or not path or not os.path.isdir(path):
            raise ValueError(self.t("err.need_project_text"))
        model, effort = self.check_choice(model, effort)
        sid = str(uuid.uuid4())
        await self.drive(sid, path, self.with_uploads(text, files), None, pkey=pkey, model=model, effort=effort)
        return {"ok": True, "sid": sid}

    async def api_model(self, sid, model=KEEP, effort=KEEP):
        """The model and/or the effort of a session — whichever the app sent ("" — back to the settings). A session
        Pult runs switches at once (SDK set_model, apply_flag_settings), a resting or closed one starts with the
        choice next time; a VS Code tab with Pult's wrapper switches through the wrapper."""
        if not SID_RE.fullmatch(sid or ""):
            raise ValueError(self.t("err.bad_sid"))
        if model is KEEP and effort is KEEP:
            raise ValueError("no model or effort")
        m, e = self.check_choice(None if model is KEEP else model, None if effort is KEEP else effort)
        dr = self.driven.get(sid)
        tab = None if dr else self.tab_for(sid)
        # a VS Code tab: the wrapper sends the requests the tab's own controls end in (set_model — probe_model.py)
        # or ones that touch this process only (effortLevel in the flag layer — probe_effort.py); a wrapper older
        # than the request can't, and the choice isn't kept then — it would show a level the tab doesn't have
        if tab and (model is not KEEP and "model" not in tab.caps or effort is not KEEP and "control" not in tab.caps):
            raise ValueError(self.t("err.old_wrapper"))
        self.set_choice(sid, None if model is KEEP else m or "", None if effort is KEEP else e or "")
        live = False
        if dr and dr.client:
            live = True
            if model is not KEEP:
                await dr.client.set_model(m)
                dr.want_model = m
            if effort is not KEEP:
                dr.want_effort = e                  # a restart takes it anyway (--effort)
                try:
                    await sdk_effort(dr.client, e)
                except Exception as x:
                    log("effort for %s: not switched live: %s" % (sid[:8], type(x).__name__))
                    live = False
        elif tab:
            if model is not KEEP:
                tab.writer.write((json.dumps({"op": "model", "model": m}) + "\n").encode())
            if effort is not KEEP:
                req = {"subtype": "apply_flag_settings", "settings": {"effortLevel": e}}
                tab.writer.write((json.dumps({"op": "control", "request": req}) + "\n").encode())
            await tab.writer.drain()
            live = True
        said = ([] if model is KEEP else ["model " + (m or "default")]) + ([] if effort is KEEP else ["effort " + (e or "default")])
        log("choice for %s: %s (%s)" % (sid[:8], ", ".join(said), "live" if live else "next start"))
        self.changed(sid)
        return {"ok": True, "live": live, "choice": self.choice.get(sid) or {}}

    async def usage(self, force=False):
        """Subscription usage: the get_usage control request to Claude Code — no model request, ~1.5 s.
        The request is experimental (marked "may change" in the VS Code extension): if it breaks, the Usage screen
        shows an error and everything else keeps working."""
        async with self._usage_lock:
            if not force and self._usage and time.time() - self._usage["ts"] < USAGE_TTL:
                return self._usage
            from claude_agent_sdk import ClaudeAgentOptions, ClaudeSDKClient
            o = ClaudeAgentOptions(cwd=str(HOME), setting_sources=[], env={"PULT_OFF": "1"}, stderr=lambda s: None)

            async def ask():
                async with ClaudeSDKClient(options=o) as c:
                    return await c._query._send_control_request({"subtype": "get_usage"}, timeout=30)
            self._usage = PW.simplify_usage(await asyncio.wait_for(ask(), 60))
            return self._usage

    async def api_inbox(self, name):
        """A picture from the owner's inbox (Telegram photos, the app's screenshots) for the app's chat: only
        <month>/<file> inside Pult's own inbox folder, and only real images."""
        if not re.fullmatch(r"\d{4}-\d{2}/[\w.-]{1,80}", str(name or "")):
            raise ValueError(self.t("err.no_request", op="inbox"))
        p = (HOME / "inbox" / name).resolve()
        if not str(p).startswith(str((HOME / "inbox").resolve()) + os.sep) or not p.is_file() or p.stat().st_size > UPLOAD_MAX:
            raise ValueError(self.t("err.no_transcript"))
        blob = await asyncio.to_thread(p.read_bytes)
        kind = image_kind(blob)
        if not kind:
            raise ValueError(self.t("err.no_transcript"))
        return {"kind": kind, "data": base64.b64encode(blob).decode()}

    async def api_stt(self, data, mime=None):
        """A recording from the app → its words (the app puts them into the message field). Nothing is kept."""
        try:
            blob = base64.b64decode(str(data or ""), validate=True)
        except (ValueError, binascii.Error):
            raise ValueError(self.t("stt.e.format", kind="?")) from None
        if not blob or len(blob) > STT_MAX:
            raise ValueError(self.t("stt.e.big"))
        try:
            text = await self.hear(blob, mime or "audio/webm")
        except STT.SttError as e:
            raise ValueError(self.stt_why(e)) from None
        log("voice from the app: %d KB → %d characters" % (len(blob) // 1024, len(text)))
        return {"text": text}

    async def api_stt_key(self, key=""):
        """The Groq key from the app's settings: checked with Groq, then written to the settings file on this
        computer (never into state the app can read back); "" removes it. Takes effect at once."""
        key = str(key or "").strip()
        if key:
            if not re.fullmatch(STT.KEY_CHARS, key):
                raise ValueError(self.t("stt.e.key"))
            try:
                await STT.Stt(key, proxy=self.env.get("PULT_PROXY") or None).check()
            except STT.SttError as e:
                raise ValueError(self.stt_why(e)) from None
        from pult_setup import write_env           # the same careful writer the command line uses
        write_env(PULT_STT_KEY=key or None)
        self._env_mt = env_mtime()
        if key:
            self.env["PULT_STT_KEY"] = key
        else:
            self.env.pop("PULT_STT_KEY", None)
        self.stt = self.make_stt()
        log("voice input from the app: key %s" % ("set" if key else "removed"))
        return {"on": bool(self.stt)}

    async def api_lang(self):
        """The language of the bot and the app — the app asks right after connecting, on any screen."""
        return self.lang()

    async def api_usage(self, force=False):
        return await self.usage(bool(force))

    async def api_today(self):
        """Today's tokens per project, for the Usage screen; kept apart from get_usage, since that one may break."""
        d = await asyncio.to_thread(self.day_tokens.get)
        for r in d["projects"]:
            path = None if self.store.topic(r["pkey"]) else await asyncio.to_thread(decode_pkey, r["pkey"])
            r["name"] = self.project_name(r["pkey"], path) if path else self.project_label(r["pkey"])
        return d

    async def usage_watch(self):
        """Limit warnings: at 80 % and 95 %, a message with sound in General, once per window."""
        last = 0.0
        while True:
            await asyncio.sleep(60)
            near = self._usage and any(x["percent"] >= 70 for x in self._usage["limits"])
            if time.time() - last < (USAGE_NEAR_EVERY if near else USAGE_EVERY) or self.activity < last:
                continue
            last = time.time()
            try:
                await self.warn_usage(await self.usage(force=True))
            except Exception as e:
                log("usage not received:", type(e).__name__)

    async def warn_usage(self, u):
        warned = self.store.get("usage_warned", [])
        for lim in u["limits"]:
            hit = max((w for w in WARN_AT if lim["percent"] >= w), default=None)
            key = "%s:%s:%d:%s" % (lim["kind"], lim["name"], int(lim["resets_at"] or 0) // 3600, hit)
            if hit is None or key in warned:
                continue
            warned.append(key)
            others = [x for x in u["limits"] if x is not lim and x["kind"] != lim["kind"]]
            text = self.t("usage.warn", name=R.esc(lim["name"]), pct=lim["percent"], reset=R.reset_text(lim["resets_at"]))
            if others:
                text += "\n" + R.esc(" · ".join("%s — %d %%" % (x["name"], x["percent"]) for x in others))
            url = self.app_url(start="usage")
            await self.send(None, text, here=0, notify=True, prio=1,
                            buttons=[[{"text": self.t("btn.usage"), "url": url}]] if url else None)
            log("limit warning:", lim["name"], lim["percent"])
        self.store.put("usage_warned", warned[-50:])

    async def api_settings(self):
        hooks = []
        try:
            for ev, groups in (json.loads(SETTINGS.read_text(encoding="utf-8")).get("hooks") or {}).items():
                if any("pult_hook.py" in str(h.get("command", "")) for g in groups for h in g.get("hooks", [])):
                    hooks.append(ev)
        except (OSError, ValueError):
            pass
        try:
            with LOG_FILE.open("rb") as f:
                f.seek(0, 2)
                f.seek(max(0, f.tell() - 16000))
                lines = f.read().decode(errors="replace").splitlines()[1:]
        except OSError:
            lines = []
        idle = await self.idle()
        return {"version": VERSION, "prefs": dict(self.prefs(), lang=self.lang(), pager=self.pager()), "hooks": sorted(hooks),
                "hooks_missing": [e for e in pult_hook.EVENTS if e not in hooks] if hooks else [],
                "mac": {"idle": idle, "away": await self.away(), "mode": self.mode()},
                "telegram": "proxy" if len(self.tg.clients) > 1 and self.tg.cur == 0 else "direct",
                "stt": self.stt_state(),
                "log": [x for x in lines if "Bearer" not in x][-40:]}

    async def api_prefs(self, **kw):
        cur = self.prefs()
        for k, v in kw.items():
            if k in ("vehi", "brief", "pager") and isinstance(v, bool) or k == "mode" and v in MODES or k == "lang" and v in I.LANGS:
                cur[k] = v
        self.store.put("prefs", cur)
        if "mode" in kw:
            await self.set_mode(cur["mode"])
        log("settings from the app:", cur)
        return cur

    async def api_stop(self, sid):
        dr = self.driven.get(sid)
        if not dr or not dr.client:
            return {"ok": False, "note": self.t("stop.only_driven")}
        await dr.client.interrupt()
        return {"ok": True}

    # ----- loops -----

    async def handle_conn(self, reader, writer):
        try:
            line = await reader.readline()
            if not line:
                return
            msg = json.loads(line)
            if "run" in msg:
                await self.on_run(msg["run"])
                return
            if msg.get("op") == "hello":
                await self.on_tab(msg, reader, writer)
                return
            res = await self.on_hook(msg, reader, writer)
            if msg.get("wait"):
                writer.write((json.dumps(res or {"output": None}, ensure_ascii=False) + "\n").encode())
                await writer.drain()
        except ConnectionError:
            pass                       # the hook has gone: answered on the Mac, or the session closed
        except Exception as e:
            log("hook event not handled:", repr(e))
        finally:
            try:
                writer.close()
            except Exception:
                pass

    async def poll(self):
        offset = self.store.get("offset", 0)
        while True:
            try:
                ups = await self.tg.call("getUpdates", offset=offset, timeout=50,
                                         allowed_updates=["message", "callback_query"])
            except TgError as e:
                log("getUpdates:", e, "(409 — someone else is reading this token)" if e.code == 409 else "")
                await asyncio.sleep(15 if e.code == 409 else 5)
                continue
            except Exception as e:
                log("getUpdates:", repr(e))
                await asyncio.sleep(5)
                continue
            for u in ups:
                offset = u["update_id"] + 1
                self.store.put("offset", offset)
                try:
                    if "callback_query" in u:
                        await self.on_callback(u["callback_query"])
                    elif "message" in u:
                        await self.on_message(u["message"])
                except Exception as e:
                    log("update %s not handled: %r" % (u.get("update_id"), e))

    async def setup_commands(self):
        for lang in I.LANGS:
            cmds = [{"command": c, "description": I.T("cmd." + c, lang)} for c in I.COMMANDS]
            try:
                await self.tg.call("setMyCommands", commands=cmds, language_code=None if lang == "en" else lang)
            except TgError as e:
                log("setMyCommands:", e)
        await self.setup_menu_button()

    def app_web_url(self):
        """The app's own address (the relay serves it): wss://host/path/agent → https://host/path/."""
        u = self.env.get("PULT_RELAY_URL") or ""
        if not (self.env.get("PULT_APP_LINK") and u.startswith("wss://") and u.endswith("/agent")):
            return None
        return "https://" + u[len("wss://"):-len("agent")]

    async def setup_menu_button(self):
        """The owner's private chat with the bot: the app button next to the message field (Telegram has such a
        button only in private chats, so in the group the way in is the topic cards and the panel). Without the
        app — Telegram's default, the command list."""
        url = self.app_web_url()
        want = {"type": "web_app", "text": self.t("menu.app"), "web_app": {"url": url}} if url else {"type": "default"}
        for uid in sorted(self.allowed):
            try:
                if await self.tg.call("getChatMenuButton", chat_id=uid) != want:
                    await self.tg.call("setChatMenuButton", chat_id=uid, **({"menu_button": want} if url else {}))
            except TgError as e:
                log("menu button:", e)


async def amain():
    env = load_env()
    token = env.get("PULT_BOT_TOKEN")
    if not token:
        log("no PULT_BOT_TOKEN in", ENV_FILE)
        sys.exit(2)
    HOME.mkdir(parents=True, exist_ok=True)
    os.chmod(HOME, 0o700)
    __import__("claude_agent_sdk")   # up front: the first import takes ~0.4 s, better not in the middle of events
    tg = Tg(token, proxy=env.get("PULT_PROXY") or None)
    store = Store(HOME / "state.db")
    store.prune()
    p = Pult(env, tg, store)
    if not p.allowed:
        log("no PULT_ALLOWED_USER_IDS — letting nobody in")
    try:
        os.unlink(SOCK)
    except FileNotFoundError:
        pass
    server = await asyncio.start_unix_server(p.handle_conn, path=SOCK, limit=8 * 1024 * 1024)
    os.chmod(SOCK, 0o600)
    log("Pult started; group:", p.chat, "; socket:", SOCK)
    await p.setup_commands()
    # the panel is sent via the message queue, so it must run alongside it, or startup hangs (seen 2026-10-16, 0.6.0)
    jobs = [p.out.run(), p.poll(), p.usage_watch(), p.tab_version_watch(), p.ensure_panel(), p.attention_watch()]
    if env.get("PULT_RELAY_URL") and env.get("PULT_RELAY_SECRET"):
        p.web = PW.Web(p, env["PULT_RELAY_URL"], env["PULT_RELAY_SECRET"], token, p.allowed,
                       proxy=env.get("PULT_PROXY") or None)
        jobs.append(p.web.run())
    async with server:
        await asyncio.gather(*jobs)


if __name__ == "__main__":
    try:
        asyncio.run(amain())
    except KeyboardInterrupt:
        pass
