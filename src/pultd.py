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
import functools
import hmac
import importlib.util
import json
import os
import re
import secrets
import shlex
import shutil
import sqlite3
import sys
import tempfile
import time
import uuid
import zlib
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import httpx

import pult_attn as A
import pult_brief as B
import pult_files as F
import pult_hook
import pult_i18n as I
import pult_load as L
import pult_new as N
import pult_os
import pult_render as R
import pult_spend as S
import pult_stt as STT
import pult_tags as G
import pult_update as U
import pult_web as PW

HOME = Path(os.environ.get("PULT_HOME") or "~/.local/share/pult").expanduser()
ENV_FILE = Path(os.environ.get("PULT_ENV") or "~/.config/pult/env").expanduser()
SOCK = os.environ.get("PULT_SOCK") or str(HOME / "pult.sock")
HOOK_PY = os.environ.get("PULT_HOOK_PY") or (
    # Windows: the base pythonw, not the venv's — the venv's python is a redirector that would be the hook's parent
    # instead of claude, and a console program would open a console window for every hook call
    str(Path(getattr(sys, "_base_executable", sys.executable)).with_name("pythonw.exe")) if os.name == "nt"
    else sys.executable)                                      # Pult's own Python: the hook needs nothing else
SEPS = os.sep + "/"                                           # trailing separators of a folder path: / (Windows: \ and /)
HOOK = str(HOME / "pult_hook.py")
CLAUDE_PROJECTS = Path("~/.claude/projects").expanduser()

SID_RE = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
SKIP_PREFIXES = ("-private-", "-tmp-", "-var-folders-")   # throwaway folders, not projects
AWAY_IDLE = 120          # idle here for longer than this (Pult.idle): the owner is away, notify with sound
EDIT_EVERY = 12          # s; edit a turn message no more often than this (Telegram's per-group limit)
MAX_RUNNING = 3          # turns from Telegram at once: Claude Code takes 250–450 MB each
MAX_DRIVEN = 5           # sessions from Telegram that hold a process
DRIVEN_IDLE = 20 * 60    # an idle session from Telegram is closed; it continues via resume
RESULT_GRACE = 3.0       # s after a turn's result for its Stop hook; an interrupted turn gets none and is closed then
ASK_TIMEOUT = 6 * 3600   # how long to wait for a permission answer in a session from Telegram
# the longest line of the Claude process's stream: a picture Claude reads comes in it twice (the result and
# tool_use_result), and the SDK's own 1 MB cut off a session at one ~470 KB screenshot (2026-10-21)
SDK_LINE_MAX = 64 * 1024 * 1024
FOCUS_IDLE = 2 * 3600   # a topic forgets its current session after this long without the owner's text there
VEHI = (10 * 60, 30 * 60, 60 * 60)   # long-turn milestones; with sound if the owner is away (decision 2026-10-16)
TICK = 60                # s; refresh "working N min" this often, even without events
NOW_LEN = 300            # characters of Claude's reply in the "now" line
YOU_LEN = 160            # characters of the owner's prompt in a result's head (one message per turn)
STALE = 20 * 60          # s without events: check whether the session is alive (a tab may close without SessionEnd)
OUT_READ = 30            # s a message just read stays in the outbox: the app shows it until the transcript has it
OUT_GONE = 10 * 60       # s a message that didn't reach Claude stays in the outbox: the app shows it crossed out
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
SPEND_COLORS = 5         # projects with a colour of their own on the spend screen; the rest are "other"
TURNS_KEPT = 50                 # turns with files kept per session (stage F4)
UPLOAD_MAX = 6 * 1024 * 1024    # bytes of one picture sent from the app (the app shrinks them to ~200 KB first)
UPLOADS_MAX = 3                 # pictures per message
ALBUM_WAIT = 2.0                # s after an album's last file: Telegram sends its files as separate messages
STT_WORDS_MAX = 280             # characters of the owner's own words for Whisper: with the sentence, within Groq's 896 bytes
STT_MAX = 4 * 1024 * 1024       # bytes of one recording from the app (5 min at 32 kbit/s ≈ 1.2 MB; base64 must fit the 8 MB frame)
PERMISSION_MODE = os.environ.get("PULT_PERMISSION_MODE", "auto")
VERSION = "0.17.2"
LOG_FILE = Path(os.environ.get("PULT_LOG") or pult_os.LOG_DIR / "pult.log").expanduser()
SETTINGS = Path("~/.claude/settings.json").expanduser()
TAB_CONF = Path("~/.config/pult/tab.json").expanduser()          # tab wrapper: folders and verified versions
NEW_ROOT = Path.home()   # a new project and the folder picker stay inside this (stage S)
EDITOR_DIRS = pult_os.editor_dirs()     # VS Code and its forks (and their remote side): where the tab wrapper is set
TAB_FILE = "pult-tab.exe" if os.name == "nt" else "pult-tab.sh"   # what claudeCode.claudeProcessWrapper points at
EXT_DIRS = pult_os.extension_dirs()
TAB_CHECK_EVERY = 3600   # s; check whether a new Claude Code extension version is out
TG_REACH = (2, 30)       # s; at start, the first and the longest pause between tries to reach Telegram
MENU_CHECK_EVERY = 1800  # s; the app button in the owner's chat is still ours (only the token's holder can change it)
CONFLICT_WARN_EVERY = 6 * 3600   # s; "someone else reads this bot" at most this often
WEB_MANIFEST = HOME / "web-manifest.json"   # what the last deploy put on the relay (written by the deploy script)
PREFS = {"vehi": True, "mode": "auto", "lang": None, "brief": False, "pager": None, "pace": S.PACE_LOW,
         "model": None, "effort": None}   # owner prefs:
# milestones, location (auto/mac/phone), language, a model's line for each result, Telegram as a pager (None — on where the
# app is set up), the % at a limit's reset that is still "on pace" (stage R), the model and the effort for sessions Pult
# starts when the session has no choice of its own (None — Claude Code's settings; VS Code tabs keep theirs)
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


def vnum(v):
    """"2.1.310" → (2, 1, 310), for sorting versions; anything else sorts first."""
    try:
        return tuple(int(x) for x in str(v).split("."))
    except ValueError:
        return ()


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
        for name in ("claude.exe", "claude") if os.name == "nt" else ("claude",):
            p = os.path.join(d, "_bundled", name)
            if os.path.isfile(p) and os.access(p, os.X_OK):
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
    """Folder name ~/.claude/projects/<pkey> → the real path (by searching the disk; '-' is ambiguous). Windows:
    the drive letter first, and names in any case (VS Code may give claude the folder as c:\\…)."""
    fold = str.lower if os.name == "nt" else str

    def walk(d, rest, depth):
        if depth > 10:
            return None
        try:
            entries = os.listdir(d)
        except OSError:
            return None
        for e in sorted(entries):
            s = fold(sanitize(e))
            if fold(rest) == s:
                return os.path.join(d, e)
            if fold(rest).startswith(s + "-") and os.path.isdir(os.path.join(d, e)):
                r = walk(os.path.join(d, e), rest[len(s) + 1:], depth + 1)
                if r:
                    return r
        return None
    if os.name == "nt":
        m = re.match(r"([A-Za-z])--(.*)$", pkey)          # C:\Users\x\proj → C--Users-x-proj
        return walk(m.group(1).upper() + ":\\", m.group(2), 0) if m else None
    return walk(root, pkey[1:], 0) if pkey.startswith("-") else None


def injected_hooks(windows=os.name == "nt"):
    """The hooks Pult puts into the sessions it runs. They run beside the global hook, which stays silent there: this
    one says it is the injected one with PULT_INJECTED=1 in front of the shell command — on Windows, where hooks run
    in exec form without a shell, with --injected among the arguments."""
    if windows:
        return pult_hook.hooks_config(HOOK_PY, [HOOK, "--injected"])
    return pult_hook.hooks_config("PULT_INJECTED=1 %s %s" % (shlex.quote(HOOK_PY), shlex.quote(HOOK)))


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


image_kind = F.image_kind                # png / jpg / gif / webp by the first bytes, else None


def prompt_started(path, owner=False, tail=512 * 1024):
    """When the turn in progress began: the time of the last prompt in the transcript. For a turn Pult learns about
    from its steps (Pult restarted mid-turn, a tab opened before Pult) — otherwise "working 14 s" after a restart.
    Messages absorbed mid-turn (queued_command) and tool results don't count. owner=True — the owner's own prompt
    only, not a turn Claude Code started itself (a background task or subagent reported back: an origin)."""
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
        if owner and e.get("origin"):
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
    return pult_os.pid_alive(pid)            # not os.kill(pid, 0): on Windows that ends the process


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
CREATE TABLE IF NOT EXISTS usage_log(ts REAL, kind TEXT, pct REAL, resets REAL);
CREATE INDEX IF NOT EXISTS usage_log_ts ON usage_log(ts);
CREATE TABLE IF NOT EXISTS turns(id INTEGER PRIMARY KEY, sid TEXT, pkey TEXT, start REAL, ts REAL, dur REAL,
    n INTEGER, files TEXT);
CREATE INDEX IF NOT EXISTS turns_sid ON turns(sid, id);
CREATE TABLE IF NOT EXISTS tag_secs(pkey TEXT, name TEXT, color INTEGER, own INTEGER DEFAULT 0, ts REAL,
    PRIMARY KEY(pkey, name));
CREATE TABLE IF NOT EXISTS tag_topics(pkey TEXT, sec TEXT, name TEXT, own INTEGER DEFAULT 0, ts REAL,
    PRIMARY KEY(pkey, sec, name));
CREATE TABLE IF NOT EXISTS session_tags(sid TEXT PRIMARY KEY, pkey TEXT, sec TEXT, topic TEXT, own INTEGER DEFAULT 0,
    ts REAL);
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

    # ----- task tags (stage T, pult_tags): the project's sections and topics, and each session's two -----

    def tag_vocab(self, pkey):
        """The project's tags: [{n, c, own, ts, topics: [{n, own, ts}]}] — sections in the order they were made (c is
        that order: their colour in the app), each with its topics in theirs."""
        secs = [{"n": r["name"], "c": r["color"], "own": bool(r["own"]), "ts": r["ts"], "topics": []}
                for r in self.db.execute("SELECT * FROM tag_secs WHERE pkey=? ORDER BY color, ts", (pkey,))]
        by = {s["n"]: s for s in secs}
        for r in self.db.execute("SELECT * FROM tag_topics WHERE pkey=? ORDER BY ts, name", (pkey,)):
            if r["sec"] in by:
                by[r["sec"]]["topics"].append({"n": r["name"], "own": bool(r["own"]), "ts": r["ts"]})
        return secs

    def tag_add(self, pkey, sec, topic=None, own=False, ts=None):
        """A section, and a topic in it, into the project's list unless they are there; own — the owner picked or made
        them: they are never "new" again."""
        ts = ts or time.time()
        if self.db.execute("SELECT 1 FROM tag_secs WHERE pkey=? AND name=?", (pkey, sec)).fetchone():
            if own:
                self.db.execute("UPDATE tag_secs SET own=1 WHERE pkey=? AND name=?", (pkey, sec))
        else:
            c = self.db.execute("SELECT coalesce(max(color) + 1, 0) FROM tag_secs WHERE pkey=?", (pkey,)).fetchone()[0]
            self.db.execute("INSERT INTO tag_secs VALUES(?,?,?,?,?)", (pkey, sec, c, int(own), ts))
        if not topic:
            return
        if self.db.execute("SELECT 1 FROM tag_topics WHERE pkey=? AND sec=? AND name=?", (pkey, sec, topic)).fetchone():
            if own:
                self.db.execute("UPDATE tag_topics SET own=1 WHERE pkey=? AND sec=? AND name=?", (pkey, sec, topic))
        else:
            self.db.execute("INSERT INTO tag_topics VALUES(?,?,?,?,?)", (pkey, sec, topic, int(own), ts))

    def session_tag(self, sid):
        return self.db.execute("SELECT * FROM session_tags WHERE sid=?", (sid,)).fetchone()

    def set_session_tag(self, sid, pkey, sec, topic, own):
        self.db.execute("INSERT OR REPLACE INTO session_tags VALUES(?,?,?,?,?,?)",
                        (sid, pkey, sec, topic, int(bool(own)), time.time()))

    def tag_uses(self, pkey):
        """How many sessions have each section and each topic: {(sec, None): n, (sec, topic): n}."""
        out = {}
        for r in self.db.execute("SELECT sec, topic, count(*) n FROM session_tags WHERE pkey=? AND sec IS NOT NULL "
                                 "GROUP BY sec, topic", (pkey,)):
            out[(r["sec"], None)] = out.get((r["sec"], None), 0) + r["n"]
            if r["topic"]:
                out[(r["sec"], r["topic"])] = r["n"]
        return out

    def map_msg(self, msg, sid, kind):
        self.db.execute("INSERT OR REPLACE INTO msgs VALUES(?,?,?,?)", (msg, sid, kind, time.time()))

    def msg(self, msg):
        return self.db.execute("SELECT * FROM msgs WHERE msg=?", (msg,)).fetchone()

    def log_usage(self, u):
        """Every get_usage reading, each limit: the points the spend curve passes through (stage R)."""
        rows = [(u["ts"], x["kind"], x["percent"], x["resets_at"]) for x in u.get("limits") or [] if x.get("kind")]
        self.db.executemany("INSERT INTO usage_log VALUES(?,?,?,?)", rows)

    def usage_log(self, since):
        return [tuple(r) for r in self.db.execute("SELECT ts, kind, pct, resets FROM usage_log WHERE ts >= ? ORDER BY ts", (since,))]

    def add_turn(self, sid, pkey, start, dur, files, n):
        """A turn that made or changed files (stage F4): its files stay viewable after the next turn. → its id."""
        cur = self.db.execute("INSERT INTO turns(sid, pkey, start, ts, dur, n, files) VALUES(?,?,?,?,?,?,?)",
                              (sid, pkey, start, time.time(), dur, n, json.dumps(files, ensure_ascii=False)))
        self.db.execute("DELETE FROM turns WHERE sid=? AND id NOT IN (SELECT id FROM turns WHERE sid=? ORDER BY id DESC "
                        "LIMIT ?)", (sid, sid, TURNS_KEPT))
        return cur.lastrowid

    def turn(self, sid, tid=None):
        """A session's turn with files (the latest one when tid is None), with the ids of the one before and after."""
        r = (self.db.execute("SELECT * FROM turns WHERE sid=? AND id=?", (sid, tid)) if tid is not None else
             self.db.execute("SELECT * FROM turns WHERE sid=? ORDER BY id DESC LIMIT 1", (sid,))).fetchone()
        if not r:
            return None
        near = lambda q: (self.db.execute(q, (sid, r["id"])).fetchone() or [None])[0]
        return dict(r, files=json.loads(r["files"] or "[]"),
                    prev=near("SELECT max(id) FROM turns WHERE sid=? AND id<?"),
                    next=near("SELECT min(id) FROM turns WHERE sid=? AND id>?"))

    def prune(self, days=60):
        self.db.execute("DELETE FROM msgs WHERE ts < ?", (time.time() - days * 86400,))
        self.db.execute("DELETE FROM usage_log WHERE ts < ?", (time.time() - days * 86400,))
        self.db.execute("DELETE FROM turns WHERE ts < ?", (time.time() - days * 86400,))


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
        self.vehi_ids = []        # the milestones' messages: removed when the result comes (one message per turn)
        self.note = None          # the turn was started by Claude itself: "⚙️ Background task finished …"
        self.here = False         # the owner typed the prompt at this computer (not from Telegram or the app)
        self.prompt_id = None     # Claude Code's id of the turn: a message absorbed into it comes with the same one
        self.ask = None           # the owner's request as written, wherever it came from (prompt — only when typed here)


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
        self.closed = None        # (note, answers) once decided: a message still on its way gets the same line on arrival
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
        self.run = None           # when the owner's prompt set the work going: turns Claude starts by itself (its
                                  # background task or subagent reported back) go on with it — "working 27 min"
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
        self.want_model = model       # the owner's choice for this session (None — Pult's default, else Claude Code's settings)
        self.want_effort = effort
        self.q = asyncio.Queue()
        self.client = None
        self.asking = False       # the query is sent, no result in the SDK stream yet
        self.result = asyncio.Event()
        self.bg = set()           # the process's background tasks: while they run, the process is not closed
        self.model = None         # the main model, from system/init: picks the entry in the result's modelUsage
        self.queued = None        # since when a message waits for a place among the MAX_RUNNING turns
        self.waiting = None       # that message's words, for the app and the topic
        self.jump = asyncio.Event()       # "Start now": this turn goes over the limit, once
        self.dropped = asyncio.Event()    # Stop while it waits: the message goes
        self.queue_msg = None     # the topic's "⏳ in the queue" message, removed once the turn starts
        self.task = asyncio.create_task(self.run())

    @property
    def busy(self):
        """A turn is running — our own query, or one Claude Code started itself when a background task finished —
        or a message waits in the queue for one."""
        return self.running or self.queued is not None

    @property
    def running(self):
        lv = self.d.live.get(self.sid)
        return self.asking or bool(lv and lv.turn)

    async def slot(self, text, origin):
        """A place among the MAX_RUNNING turns from Telegram and the app → True (taken: give it back), False (over the
        limit: "Start now"), None (Stop while it waited: the message is dropped). While it waits the session is "in
        the queue" — in the app, and in the topic when the message came from Telegram. A queue nobody could see made
        a 4th question look dead: it waited 4 minutes, the owner sent it again, it ran twice (2026-10-23)."""
        sem = self.d.run_sem
        if not sem.locked():
            await sem.acquire()
            return True
        self.queued, self.waiting = time.time(), R.short(R.prompt_text(text), 300)
        self.jump.clear()
        self.dropped.clear()
        log("Telegram session %s: in the queue, %d turns run" % (self.sid[:8], MAX_RUNNING))
        await self.d.queue_shown(self, origin)
        take = asyncio.ensure_future(sem.acquire())
        jump, drop = asyncio.ensure_future(self.jump.wait()), asyncio.ensure_future(self.dropped.wait())
        try:
            await asyncio.wait({take, jump, drop}, return_when=asyncio.FIRST_COMPLETED)
        finally:
            jump.cancel()
            drop.cancel()
            if not take.done():
                take.cancel()
            await asyncio.gather(take, jump, drop, return_exceptions=True)
            got = take.done() and not take.cancelled() and take.exception() is None
            waited = time.time() - self.queued
            self.queued = self.waiting = None
            if self.dropped.is_set() and got:
                sem.release()
            await self.d.queue_gone(self)
        how = "dropped" if self.dropped.is_set() else "a place came" if got else "started over the limit"
        log("Telegram session %s: out of the queue after %d s — %s" % (self.sid[:8], waited, how))
        return None if self.dropped.is_set() else got

    async def say(self, text, origin):
        """A message for this session. During our query's turn it goes straight to Claude Code, which reads it at the
        turn's next step, as in a VS Code tab (a queued_command, absorbed_mid_turn — tests/probe_midturn.py, 2.1.300);
        held here until the result, "stop, wrong project" reached Claude only after a 10-minute turn (2026-10-21).
        A turn that ends before its next step runs the message as a turn of its own — Claude Code does that itself."""
        if self.client and self.asking:
            try:
                await self.client.query(text)
                if origin:
                    self.d.expect[self.sid] = origin  # the turn's result answers the latest message
                return
            except Exception as e:                    # the process is going away: the loop will see it
                log("Telegram session %s: a message mid-turn: %r" % (self.sid[:8], e))
        self.q.put_nowait((text, origin))

    async def stop(self):
        """Stop means stop: messages still waiting here are dropped, so the interrupt doesn't start the next turn
        (2026-10-21: each tap on Stop let one more waiting "stop, wrong project" start a turn). → how many dropped."""
        items = []
        while not self.q.empty():
            items.append(self.q.get_nowait())
        if None in items:
            self.q.put_nowait(None)              # the process has ended: the loop still has to see that
        dropped = len([x for x in items if x is not None])
        for x in items:
            if x is not None:
                self.d.out_set(self.sid, "gone", x[0])
        lv = self.d.live.get(self.sid)
        if self.queued is not None:              # the message waiting for a place goes too
            self.dropped.set()
            dropped += 1
            if not (lv and lv.turn):
                return dropped                   # no turn runs: nothing to interrupt
        if self.client:
            await self.client.interrupt()
        return dropped

    async def _wait_hook(self, tool, inp, ctx):
        # The decision arrives via the PermissionRequest hook (buttons in Telegram) and cancels this call.
        from claude_agent_sdk import PermissionResultDeny
        await asyncio.sleep(ASK_TIMEOUT)
        return PermissionResultDeny(message="No answer from Telegram within %d h" % (ASK_TIMEOUT // 3600))

    def options(self):
        from claude_agent_sdk import ClaudeAgentOptions
        hooks = injected_hooks()
        # system_prompt — Claude Code's standard one: without it the SDK starts the session with an empty system
        # prompt, and Claude behaves differently than in the VS Code tab (seen 2026-10-15)
        kw = dict(cwd=self.path, system_prompt={"type": "preset", "preset": "claude_code"},
                  permission_mode=PERMISSION_MODE, can_use_tool=self._wait_hook,
                  setting_sources=["user", "project", "local"], settings=json.dumps({"hooks": hooks}),
                  # entrypoint: the SDK sets sdk-py, and VS Code hides sdk-* sessions from its list (a filter
                  # in extension 2.1.300). Without a terminal, Claude Code itself turns cli into sdk-cli;
                  # claude-vscode is kept: the session shows up in the Claude tab and can be continued on the Mac
                  env={"PULT_DRIVEN": "1", "PULT_SOCK": SOCK, "CLAUDE_CODE_ENTRYPOINT": "claude-vscode"},
                  max_buffer_size=SDK_LINE_MAX, stderr=lambda s: None)
        model, effort = self.d.wanted(getattr(self, "want_model", None), getattr(self, "want_effort", None))
        if model:
            kw["model"] = model
        if effort:
            kw["effort"] = effort
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
                    self.d.result_seen(self.sid)
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
                        took = await self.slot(text, origin)
                        if took is None:
                            self.d.out_set(self.sid, "gone", text)       # Stop while it waited for a place
                            continue
                        try:
                            self.result.clear()
                            self.d.expect[self.sid] = origin
                            try:
                                await c.query(text)
                                self.asking = True       # only now: a message sent sooner must not overtake this one
                                await self.result.wait()
                            finally:
                                self.asking = False
                                self.d.expect.pop(self.sid, None)
                        finally:
                            if took:
                                self.d.run_sem.release()
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
            self.d.out_gone_all(self.sid)


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
        self.outbox = {}               # sid → the owner's messages on their way to Claude: the app's ticks (Q56)
        self.offers = {}               # button token → data (session copy, open a session, project)
        self.decided_msgs = {}         # messages whose choice was made with a button: a second tap does nothing
        self.req_by_rid = {}
        self.req_by_msg = {}
        self.topic_locks = {}
        self.cards_seen = set()        # topics whose card was checked since start (Pult.topic_card)
        self.run_sem = asyncio.Semaphore(MAX_RUNNING)
        self.jobs = {}                 # job id → a clone for a new project in progress (stage S)
        self.held = {}                 # topic → files that came without words, waiting for the owner's next message (stage F)
        self.albums = {}               # media_group_id → an album's files being gathered (stage F)
        self._idle = (0.0, None)
        self.here_seen = time.monotonic()   # the owner's last action in a session here (Pult.idle)
        self._agents = (0.0, [])
        self._procs = (0.0, None)
        self.web = None                # pult_web.Web — the web app, if a relay is configured
        self.stats = PW.Stats()        # model, thinking, session tokens — for the app
        self.spend = S.Spend(CLAUDE_PROJECTS, skip_pkey)   # the week's transcripts in 5-min slots: the spend curve, today by project
        self._spend = (0.0, None)      # the last Resources view, for the Home strip
        self._pnames = {}              # pkey → a project's name for the spend screen (decode_pkey walks the disk)
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
        self.t_start = time.time()
        self.health = {}               # reached Telegram / the app's server — health.json, for the installer (stage U)
        self._upd = (0.0, None)        # what the source folder has (pult_update.check), kept a minute
        self.upd_wait = None           # the owner asked to install once Pult's sessions are free: since when
        self._parts = (0.0, None, None)  # the source folder against what's installed and served (stage U2): time, key, facts
        self._cc = (0.0, None)         # Claude Code on this computer (cc_facts), kept half a minute

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

    # ----- the owner's messages on their way to Claude: the ticks (decision Q56) -----
    # Claude Code reads a message sent while it works only at the turn's next step (absorbed_mid_turn), up to a minute
    # later; the app showed nothing until then (the owner, 2026-10-24). A message here is "sent" once Claude Code or
    # Pult's queue has it, "read" when its UserPromptSubmit comes — one per message, in the order sent, also when two
    # are read at one step (probe_midturn.py two, 2.1.300) — and "gone" if Stop drops it or the process ends first

    def out_add(self, sid, body, tg=None, react=None):
        """body — the words as they go to Claude; tg, react — the Telegram message and the reaction it got (✍ — the
        session was busy: 👀 once Claude reads it). → the message's id for the app."""
        now = time.time()
        box = [o for o in self.outbox.get(sid) or []
               if o["st"] == "sent" or now - o["at"] < (OUT_READ if o["st"] == "read" else OUT_GONE)]
        o = {"id": secrets.token_hex(4), "body": body, "ts": now, "at": now, "st": "sent", "tg": tg, "react": react}
        self.outbox[sid] = box + [o]
        self.changed(sid)
        return o["id"]

    def out_drop(self, sid, oid):
        """The hand-off failed: the app says so itself, and the words stay in its field."""
        self.outbox[sid] = [o for o in self.outbox.get(sid) or [] if o["id"] != oid]

    def out_set(self, sid, st, body=None):
        """The first message still on its way — with these words, when given — is read or gone → it, or None."""
        for o in self.outbox.get(sid) or []:
            if o["st"] == "sent" and (body is None or o["body"].strip() == str(body).strip()):
                o["st"], o["at"] = st, time.time()
                if st == "read" and o["tg"] and o["react"] == "✍":
                    asyncio.create_task(self.react(o["tg"], "👀"))
                self.changed(sid)
                return o
        return None

    def out_gone_all(self, sid):
        """The session's process or tab is gone: what hadn't reached Claude won't."""
        while self.out_set(sid, "gone"):
            pass

    def out_view(self, sid):
        """For the session screen: each message as the transcript will show it, with its id and state."""
        now = time.time()
        return [dict(PW.user_item(PW.user_text(o["body"]), o["ts"]), id=o["id"], st=o["st"])
                for o in self.outbox.get(sid) or []
                if o["st"] == "sent" or now - o["at"] < (OUT_READ if o["st"] == "read" else OUT_GONE)]

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
        return os.path.basename(path.rstrip(SEPS)) if path else pkey.lstrip("-")

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
            name = (row and row["name"]) or self.project_name(pkey, path)       # a new project's title (stage S)
            # the icon in the project's own colour — the app's tile for it is the same (existing topics keep theirs:
            # editForumTopic can't change a colour)
            res = await self.out.submit(1, lambda: self.tg.call("createForumTopic", chat_id=self.chat,
                                                                 name=name[:128], icon_color=R.topic_color(name)))
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
        focus = self.focus_of(pkey)
        if focus:
            title = R.short(self.session_label(focus), 60)
            text = self.t("card.focus", name=I.q(R.esc(title))) + "\n" + text
            sig += "|%s:%08x" % (focus[:8], zlib.crc32(title.encode()))
        # stage V: the pinned bar shows who works and who waits — and Telegram shows only the card's first line there, so
        # the status goes above the topic's current session (under it, it was hidden whenever the topic had one)
        status = self._status.get(pkey) if buttons and self.pager() else None
        if status:
            text = "<b>%s</b>\n%s" % (R.esc(status), text)
            sig += "|" + status
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
                   sid=None, kind=None, here=None, urgent=False):
        """To the topic of project pkey (creating it if missing) or, if here is given, to where the
        owner wrote: a topic id, 0 — General. urgent: with sound even when the owner is at the computer (security)."""
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
                          disable_notification=not notify or self.mode() == "mac" and not urgent,   # at the Mac — silent
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

    async def send_long(self, pkey, header, md, *, notify, sid, reply_to=None, prio=3, kind="result", files_row=None):
        """A long Claude reply. With the app connected: the beginning in the chat and "Read in full" (the whole
        text in the app). Without it: 3500-character chunks, up to six chunks without a file (~20k characters), since
        a file is awkward to read on a phone; beyond that, the first five chunks and the whole text as a file."""
        chunks = R.split_md(md)
        ids = []
        if len(chunks) > 1 and sid and self.app_live():
            rest = len(md) - len(chunks[0])
            ids.append(await self.send(pkey, header + "\n" + R.folded_html(chunks[0]) +
                                       self.t("long.more", n=rest), notify=notify, sid=sid, kind=kind,
                                       prio=prio, reply_to=reply_to, buttons=[self.app_row(sid, self.t("btn.read_all"))] +
                                       ([files_row] if files_row else [])))
            return ids
        if len(chunks) > 6:
            for i, ch in enumerate(chunks[:5]):
                ids.append(await self.send(pkey, (header + "\n" if i == 0 else "") + R.folded_html(ch),
                                           notify=notify and i == 0, sid=sid, kind=kind, prio=prio,
                                           reply_to=reply_to if i == 0 else None))
            ids.append(await self.send_doc(pkey, md, "%s.md" % (sid or "text")[:8],
                                           self.t("doc.caption", n=len(md)), sid=sid))
            return ids
        for i, ch in enumerate(chunks):
            last = i == len(chunks) - 1
            ids.append(await self.send(pkey, (header + "\n" if i == 0 else "") + R.folded_html(ch),
                                       notify=notify and i == 0, sid=sid, kind=kind, prio=prio,
                                       reply_to=reply_to if i == 0 else None,
                                       # the turn's files and Details side by side: both open the app
                                       buttons=([files_row + (self.app_row(sid) or [])] if files_row else self.with_app(None, sid)) if last and sid else None))
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
                os.path.basename((lv.cwd or "").rstrip(SEPS)) or lv.pkey.rsplit("-", 1)[-1] or self.t("session.default"))

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

    def start_turn(self, lv, prompt=None, reply_to=None, note=None, pid=None):
        t = lv.turn = Turn(prompt, reply_to)
        t.note, t.prompt_id = note, pid
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
            # a turn another one took the place of (two events at once each started one) is nobody's: nothing would
            # ever end it, and this loop would go on for good (2026-10-24: two such turns, a log line a minute for hours)
            if not t.done and lv.turn is not t:
                log("turn %s: a newer turn took its place — closing" % lv.sid[:8])
                self.finish_turn(lv, "⏹", t)
            elif not t.done and not await self.alive(lv, t):
                log("turn %s: the session is gone from the Mac — closing" % lv.sid[:8])
                self.finish_turn(lv, "⏹", t)
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
            t.vehi_ids.append(await self.send(lv.pkey, text, reply_to=t.msg, notify=True, prio=2, sid=lv.sid, kind="vehi",
                                              buttons=[[{"text": self.t("btn.mute"), "callback_data": "m:" + tok}] +
                                                       (self.app_row(lv.sid) or [])]))

    def result_seen(self, sid):
        """A turn's result in the SDK stream of Pult's own session. An interrupted turn gets no Stop hook, only the
        result (error_during_execution — tests/probe_midturn.py stop, 2.1.300): the turn stayed "working", and with it
        the session's idle process was never closed (2026-10-21, a session after Stop). If no hook has closed the turn
        RESULT_GRACE s later, it is closed here as interrupted."""
        lv = self.live.get(sid)
        t = lv.turn if lv else None
        if t and not t.done:
            asyncio.get_running_loop().call_later(RESULT_GRACE, self._close_unended, lv, t)

    def _close_unended(self, lv, t):
        if lv.turn is t and not t.done:
            log("turn %s: a result without Stop (interrupted) — closing" % lv.sid[:8])
            self.finish_turn(lv, "⏹")

    def finish_turn(self, lv, mark, t=None):
        """Ends the session's turn — or t, a turn of its that is no longer the session's own."""
        t = t or lv.turn
        if t and not t.done:
            t.done = (mark, time.time())
            t.changed.set()
            if t.vehi:
                t.vehi.cancel()
        if lv.turn is t:
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
            # processes don't write to the same session; a running turn is not interrupted (a message still in the
            # queue goes: the session is the Mac's now)
            if not dr.running:
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
        if name == "UserPromptSubmit" and lv.turn and ev.get("prompt_id") and ev["prompt_id"] == lv.turn.prompt_id:
            # a message absorbed into the running turn — the owner's, sent mid-turn (Driven.say, a busy tab), or another
            # session's SendMessage: Claude Code gives it a UserPromptSubmit of its own, but with the running turn's
            # prompt_id (tests/probe_midturn.py, 2.1.300 and 2.1.301). The turn and its "working N" go on: each such
            # message used to end the turn and start one from zero (2026-10-24: sessions writing to each other showed
            # "working 28 s" 19 min into a turn). The turn's result answers the latest message from Telegram
            lv.turn.reply_to = self.expect.get(sid) or lv.turn.reply_to
            lv.turn.last = time.time()
            self.changed(sid)      # the app re-reads the session now: the message is in the transcript, read by Claude
            self.out_set(sid, "read", ev.get("prompt"))
        elif name == "UserPromptSubmit":
            self.resolve_all(lv, self.t("req.decided_mac"))
            self.finish_turn(lv, "⏹")
            notes = R.task_notes(ev.get("prompt"))
            # a new turn: the last outcome is behind; the owner's prompt (not a background task's note) answered it
            self.mark_seen(sid, None if notes else ev.get("prompt"))
            await self.refresh_title(lv)
            if notes:
                # the turn was started by Claude Code itself (a background task finished); it's not the owner's prompt
                for n in notes:
                    n["what"] = n["what"] or next((b.get("description") or b.get("command") for b in lv.bg
                                                   if b.get("id") == n["id"]), None) or self.t("task.default")
                ended = {n["id"] for n in notes}
                lv.bg = [b for b in lv.bg if b.get("id") not in ended]
                t = self.start_turn(lv, note=R.task_notes_text(notes), pid=ev.get("prompt_id"))
                lv.run = lv.run or t.started
            else:
                origin = self.expect.get(sid)
                sent = self.tab_expect.get(sid)
                if not origin and sent and sent[1].strip() == (ev.get("prompt") or "").strip():
                    origin = self.tab_expect.pop(sid)[0]       # written from Telegram into the tab
                lv.title = lv.title or R.short(R.attachments(ev.get("prompt"))[0], 60) or None
                if not origin:
                    self.seen_here(lv)                         # typed here
                t = self.start_turn(lv, None if origin else ev.get("prompt"), reply_to=origin, pid=ev.get("prompt_id"))
                t.here = not origin and not lv.driven
                t.ask = ev.get("prompt")
                lv.run = t.started
                self.out_set(sid, "read", ev.get("prompt"))
                self.tags_on_prompt(lv, ev.get("prompt"))
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
                # read before the turn appears, so the app never sees it without its start and its run's
                began, own = await asyncio.to_thread(
                    lambda p: (prompt_started(p), prompt_started(p, owner=True)), lv.transcript) \
                    if lv.transcript else (None, None)
                t = self.start_turn(lv, pid=ev.get("prompt_id"))
                if began and began < t.started:
                    t.started = began              # the turn began before Pult saw it (a restart mid-turn)
                    t.changed.set()
                lv.run = lv.run or min(own or t.started, t.started)
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
            self.out_gone_all(sid)
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
        files, n = await self.files_of_turn(lv, t)
        tf = None
        if files:                                  # kept: the files stay viewable after the next turn (stage F4)
            tid = self.store.add_turn(lv.sid, lv.pkey, t.started, (t.done[1] - t.started) if t.done else None, files, n)
            tf = {"id": tid, "n": n, "size": sum(f["size"] for f in files)}
        self.outcome(lv, t, text, fail, seen=bool(t and t.here) and not await self.away(), files=tf)
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
        you = ""
        if not self.pager() and t and t.msg:
            # one message per turn without the app as well: the result takes the turn message's place (it said the
            # same title and time — three times with the quote); what was asked moves into the result's head when
            # there is no message of the owner's to reply to (typed at the computer, or Claude's own turn)
            asyncio.create_task(self.drop(t.msg))
            reply_to = sent[0] if sent and sent[0] else t.reply_to
            if not reply_to and t.prompt:
                you = self.t("turn.you", text=R.esc(I.q(R.short(R.prompt_text(t.prompt), YOU_LEN)))) + "\n"
            elif not reply_to and t.note:
                you = "<i>%s</i>\n" % R.esc(t.note)
        for mid in (t.vehi_ids if t else []):
            if mid:
                asyncio.create_task(self.drop(mid))
        await self.send_long(lv.pkey, "%s %s%s\n%s%s" % ("⚠️" if fail else "✅", self.head(lv), when, you,
                                                          R.esc(bg) + "\n" if bg else ""), text,
                             notify=notify, sid=lv.sid, reply_to=reply_to,
                             files_row=self.files_row(lv.sid, tf) if tf else None)

    # ----- whose move (stage V): each session's last outcome, the model's line, the Home board -----

    def fail_text(self, code):
        """The API error that ended a turn, for a human: StopFailure's error (2.1.301 knows rate_limit, overloaded,
        server_error, authentication_failed, billing_error, invalid_request, max_output_tokens, model_not_found)."""
        key = "fail." + code
        return self.t(key) if key in I.S else self.t("fail.other", code=R.esc(code))

    def outcome(self, lv, t, text, fail=None, seen=False, files=None):
        """A turn ended: remember how (pult_attn) and, if the owner allowed it, let the model read the result.
        seen — the owner typed this turn here and is still at the computer: they watched it end; files — the turn's
        files as kept ({id, n, size}), or None."""
        waits = not lv.bg                                  # nothing else runs: the next step is the owner's
        line = self.fail_text(fail) if fail else B.first_sentence(text)
        dur = (t.done[1] - t.started) if t and t.done else None
        rec = self.attn.finished(lv.sid, lv.pkey, dur, R.plain(text, 600), line, waits, fail=fail, seen=seen)
        if files:
            rec["turn_files"] = files                      # {id, n, size}: the app's line to the turn's files (stage F4)
            self.attn.save()
        self.changed(lv.sid)
        if not fail and text.strip() and self.prefs()["brief"]:
            bg = [b.get("description") or b.get("command") or "" for b in lv.bg]
            asyncio.create_task(self.brief_result(lv, rec["ts"], (t.ask or t.prompt) if t else None, text, bg, waits,
                                                  since=t.started if t else 0.0))

    async def drop(self, mid):
        """Delete one of Pult's messages (Telegram allows it for 48 h); a refusal only goes to the log."""
        try:
            await self.out.submit(6, lambda: self.tg.call("deleteMessage", chat_id=self.chat, message_id=mid))
        except TgError as e:
            log("message %s not deleted: %s" % (mid, e))

    def mark_seen(self, sid, said=None):
        """The owner saw a session's outcome (opened it, answered it, "Got it", a new turn): it rests, and a call
        about it in Telegram folds into "✔️ … · line" without buttons. said — their answer, from wherever it came:
        the call shows it too."""
        r = self.attn.rec.get(sid)
        fresh = self.attn.seen(sid)
        said = R.short(R.prompt_text(said), 80) if said else ""
        if r and r.get("page") and (fresh or said):
            self.fold_page(sid, r, R.esc(I.q(said)) if said else None)
        if fresh:
            self.changed(sid)
        return fresh

    def fold_page(self, sid, r, mark=None):
        """A call in Telegram the owner has dealt with: one line "✔️ title · line" without buttons; with mark (HTML) —
        "→ what they answered or decided", and the call stays so for good."""
        lv = self.live.get(sid) or self.stub(sid, r["pkey"])
        text = "✔️ <b>%s</b> · %s" % (R.esc(lv.title or self.title(lv)), R.esc(r["line"] or ""))
        self.edit(r["page"], text + ("\n→ " + mark if mark else ""), [], prio=3 if mark else 6)
        if mark:
            r["page"] = None
            self.attn.save()

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
        text = "%s <b>%s</b>\n%s" % ("⚠️" if r.get("fail") else "🟠", R.esc(lv.title or self.title(lv)), R.esc(r["line"] or ""))
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
        self.mark_seen(sid, replies[i])
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
        r = self.attn.rec.get(sid)
        if r and r.get("page"):                    # from the call's button or from the app — decided either way
            self.fold_page(sid, r, R.esc(self.t("note.resume", hm=time.strftime("%H:%M", time.localtime(at)))))
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
        work = sum(1 for r in rows if r["state"] in ("work", "bg", "queue"))
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

    async def brief_result(self, lv, ts, prompt, text, bg, waits, since=0.0):
        """The model's line for a finished turn (pult_brief: haiku, the owner's subscription), one request at a
        time; a newer outcome of the same session makes the request moot. The same request reads the task's tags
        (stage T) — unless they are the owner's: theirs are final. since — the turn's start: its files are a hint."""
        async with self.brief_sem:
            r = self.attn.rec.get(lv.sid)
            if not r or r["ts"] != ts:
                return
            BRIEF_DIR.mkdir(parents=True, exist_ok=True)
            tags = await self.tag_ctx(lv, since)
            b = await B.brief(R.prompt_text(prompt) if prompt else None, text, bg, self.lang(), BRIEF_DIR, tags=tags)
            if b is None:
                log("brief %s: no answer from the model — the first sentence stays" % lv.sid[:8])
                return
            if tags is not None and b.get("tags"):
                self.tags_set(lv, b["tags"])
            if self.attn.briefed(lv.sid, ts, b, waits):
                self.changed(lv.sid)

    # ----- task tags (stage T): a section of the project and a topic in it; the model keeps them, the owner corrects -----

    async def tag_ctx(self, lv, since=0.0, force=False):
        """What the model needs for a task's tags — pult_tags.context's arguments: the project, its list, the task's
        current tags, the files its steps worked with since `since`, the top folders while the list is short — or None:
        the owner's own tags are final (force — their hashtag asks the model to place it anyway), and projects Pult
        doesn't show get none."""
        cur = self.store.session_tag(lv.sid)
        if skip_pkey(lv.pkey) or (cur and cur["own"] and not force):
            return None
        vocab = self.store.tag_vocab(lv.pkey)
        root = self.project_path(lv.pkey, lv.cwd)
        paths = await asyncio.to_thread(G.turn_paths, lv.transcript, since, root) if lv.transcript else []
        dirs = await asyncio.to_thread(G.hints, root) if root and len(vocab) < G.HINT_UNDER else []
        row = self.store.session(lv.sid)
        return {"project": self.project_label(lv.pkey), "vocab": vocab, "paths": paths, "dirs": dirs,
                "cur": {"sec": cur["sec"], "topic": cur["topic"]} if cur and cur["sec"] else None,
                "title": lv.title or (row["title"] if row else None)}

    def tags_set(self, lv, got, own=False):
        """A task's tags — the model's, or (own) the owner's — placed in the project's list (pult_tags.place: the
        list's own spelling, its limits); the model never overwrites the owner's. → whether anything changed."""
        got = G.parse(got)                       # names as shown, whatever the model wrote
        cur = self.store.session_tag(lv.sid)
        if got is None or (cur and cur["own"] and not own):
            return False
        was = {"sec": cur["sec"], "topic": cur["topic"]} if cur and cur["sec"] else None
        at = G.place(self.store.tag_vocab(lv.pkey), got, was)
        if at is None:
            return False
        sec, topic = at[0], at[1]
        if was == {"sec": sec, "topic": topic} and (own == bool(cur["own"])):
            return False
        self.store.tag_add(lv.pkey, sec, topic, own=own)
        self.store.set_session_tag(lv.sid, lv.pkey, sec, topic, own)
        log("tags %s: %s%s%s" % (lv.sid[:8], sec, " / " + topic if topic else "", " (the owner's)" if own else ""))
        self.changed(lv.sid)
        return True

    def tags_on_prompt(self, lv, prompt):
        """A new request from the owner (stage T). Their hashtags set the task's tags at once, as theirs; a word that
        is not in the project's list goes to the model, which places it. A task without tags gets them from the model
        as soon as its request is in: a turn may run for an hour, and "Running now" needs them already."""
        if skip_pkey(lv.pkey):
            return
        text = R.prompt_text(prompt)
        words = G.hashtags(text)
        if words and self.tag_by_owner(lv, words):
            return
        cur = self.store.session_tag(lv.sid)
        if self.prefs()["brief"] and (words or not (cur and cur["sec"])):
            asyncio.create_task(self.tag_task(lv, text, own=words[0] if words else None))

    def tag_by_owner(self, lv, words):
        """The owner's hashtags → the task's tags, theirs: a section or a topic of the project's list, by name. A word
        not in the list: with the model it is left to tag_task (False); without it, it becomes a section of its own."""
        vocab = self.store.tag_vocab(lv.pkey)
        for w in words:
            f = G.find(vocab, w)
            if f and f[0] == "topic":
                self.tags_set(lv, {"sec": f[1]["n"], "topic": f[2]["n"]}, own=True)
                return True
            if f:
                cur = self.store.session_tag(lv.sid)
                self.tags_set(lv, {"sec": f[1]["n"], "topic": cur["topic"] if cur and cur["sec"] == f[1]["n"] else None}, own=True)
                return True
        if self.prefs()["brief"]:
            return False
        sec = G.norm(words[0], G.SEC_LEN)
        if not sec:
            return False
        self.store.tag_add(lv.pkey, sec, None, own=True)
        self.store.set_session_tag(lv.sid, lv.pkey, sec, None, True)
        self.changed(lv.sid)
        return True

    async def tag_task(self, lv, prompt, own=None, reply=None):
        """The model's tags for a task from its request (and reply, if any), one request at a time with the result
        lines; own — the owner's hashtag that is not in the project's list: the model places it, and the tags are the
        owner's."""
        async with self.brief_sem:
            ctx = await self.tag_ctx(lv, force=bool(own))
            if ctx is None:
                return
            BRIEF_DIR.mkdir(parents=True, exist_ok=True)
            reply = reply or (self.attn.rec.get(lv.sid) or {}).get("line")      # how the task's last turn ended, if any
            got = await G.tag(G.request(prompt=prompt, reply=reply, own=own, **ctx), self.lang(), BRIEF_DIR)
            if got is None:
                log("tags %s: no answer from the model" % lv.sid[:8])
                return
            if own and G.key(own) not in (G.key(got["sec"]), G.key(got.get("topic"))):
                got["topic"] = G.norm(own, G.TOPIC_LEN)       # the owner's word stays, wherever the model put the task
            self.tags_set(lv, got, own=bool(own))

    def tags_of(self, sid, cache=None):
        """A session's tags for the app: its section and its topic — [{n, c, k: "sec"|"topic", fresh}], coloured by
        the section's place in the project's list; [] without tags. cache — {pkey: (list, uses)} across one answer."""
        r = self.store.session_tag(sid)
        if not r or not r["sec"]:
            return []
        cache = {} if cache is None else cache
        if r["pkey"] not in cache:
            cache[r["pkey"]] = (self.store.tag_vocab(r["pkey"]), self.store.tag_uses(r["pkey"]))
        vocab, uses = cache[r["pkey"]]
        s = next((x for x in vocab if x["n"] == r["sec"]), None)
        if s is None:
            return []
        now = time.time()
        out = [{"n": s["n"], "c": s["c"], "k": "sec", "fresh": G.is_fresh(s, uses.get((s["n"], None), 0), now)}]
        t = next((x for x in s["topics"] if x["n"] == r["topic"]), None) if r["topic"] else None
        if t:
            out.append({"n": t["n"], "c": s["c"], "k": "topic", "fresh": G.is_fresh(t, uses.get((s["n"], t["n"]), 0), now)})
        return out

    def tag_list(self, pkey, sids=None):
        """The project's sections for the app — [{n, c, cnt, fresh, topics: [{n, cnt, fresh}]}]. With sids — what a
        screen shows: cnt counts those sessions, only the sections and topics they have, the most used first (the tag
        bar); without — the whole list in its order, cnt over every task (the sheet that corrects a task's tags)."""
        vocab, uses, now = self.store.tag_vocab(pkey), self.store.tag_uses(pkey), time.time()
        have = None
        if sids is not None:
            have = {}
            for sid in set(sids):
                r = self.store.session_tag(sid)
                if r and r["sec"] and r["pkey"] == pkey:
                    have[(r["sec"], None)] = have.get((r["sec"], None), 0) + 1
                    if r["topic"]:
                        have[(r["sec"], r["topic"])] = have.get((r["sec"], r["topic"]), 0) + 1
        out = []
        for s in vocab:
            cnt = (have if have is not None else uses).get((s["n"], None), 0)
            tops = [{"n": t["n"], "cnt": (have if have is not None else uses).get((s["n"], t["n"]), 0),
                     "fresh": G.is_fresh(t, uses.get((s["n"], t["n"]), 0), now)} for t in s["topics"]]
            if have is not None:
                if not cnt:
                    continue
                tops = [t for t in tops if t["cnt"]]
            out.append({"n": s["n"], "c": s["c"], "cnt": cnt, "fresh": G.is_fresh(s, uses.get((s["n"], None), 0), now),
                        "topics": tops})
        if have is not None:
            out.sort(key=lambda g: (-g["cnt"], g["c"]))
        return out

    async def api_tag(self, sid, sec=None, topic=None, auto=False):
        """The owner's tags for a task (stage T): a section, and a topic in it if any — from the project's list or new
        (the limits are the model's, not the owner's); final: the model never changes them. auto — back to Claude:
        the model reads the task again, from its title and its last outcome."""
        if not re.fullmatch(r"[0-9a-fA-F-]{36}", str(sid or "")):
            raise ValueError(self.t("err.bad_sid"))
        lv = self.live.get(sid) or self.stub(sid)
        if not lv.pkey or skip_pkey(lv.pkey):
            raise ValueError(self.t("err.no_project"))
        cur = self.store.session_tag(sid)
        if auto:
            if cur and cur["own"]:
                self.store.set_session_tag(sid, lv.pkey, cur["sec"], cur["topic"], False)
                log("tags %s: back to Claude" % sid[:8])
            if self.prefs()["brief"]:
                rec = self.attn.rec.get(sid) or {}
                asyncio.create_task(self.tag_task(lv, lv.title or "", reply=rec.get("line")))
        else:
            name = G.norm(sec, G.SEC_LEN)
            if not name:
                raise ValueError(self.t("tags.e.name"))
            s = next((x for x in self.store.tag_vocab(lv.pkey) if G.key(x["n"]) == G.key(name)), None)
            name = s["n"] if s else name
            tp = G.norm(topic, G.TOPIC_LEN) if topic else None
            t = next((x for x in s["topics"] if G.key(x["n"]) == G.key(tp)), None) if s and tp else None
            tp = t["n"] if t else tp
            self.store.tag_add(lv.pkey, name, tp, own=True)
            self.store.set_session_tag(sid, lv.pkey, name, tp, True)
            log("tags %s: %s%s (the owner's)" % (sid[:8], name, " / " + tp if tp else ""))
        self.changed(sid)
        return {"tags": self.tags_of(sid), "tagset": self.tag_list(lv.pkey), "auto": bool(auto)}

    # ----- tasks without Claude: pult run -- command -----

    def pkey_for_cwd(self, cwd):
        """The topic of the project whose folder the task runs in (the most nested one), otherwise General (None)."""
        best = None
        cwd = os.path.normcase(os.path.realpath(cwd or os.sep))     # /var → /private/var; Windows: any case
        for r in self.store.db.execute("SELECT pkey, path FROM topics WHERE path IS NOT NULL"):
            p = os.path.normcase(os.path.realpath(r["path"])).rstrip(os.sep)
            if (cwd == p or cwd.startswith(p + os.sep)) and (best is None or len(p) > len(best[1])):
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
                    if req.closed:             # decided while this one was on its way
                        self.close_req_msgs(req, *req.closed, only=[(m, i)])
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
            if req.closed:                     # decided while it was on its way: the buttons go at once
                self.close_req_msgs(req, *req.closed, only=[(m, None)])

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
        # tapped right here in Telegram: no need to say where; from the app — said
        place = "" if where == "tg" else self.t("where." + where)
        for_claude = {"tg": "Telegram", "app": "the Pult app"}.get(where, where)
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

    def close_req_msgs(self, req, note, answers=None, only=None):
        """The request's messages say how it was decided, without buttons. A message still being sent when the decision
        came (a tap, the computer's dialog or the app in that moment) is closed as soon as its id is known — only."""
        req.closed = (note, answers)
        lv = self.live.get(req.sid)
        for m, i in only or req.msgs:
            if i is not None:
                q = (req.inp.get("questions") or [])[i]
                got = (answers or {}).get(q.get("question")) or ", ".join(req.chosen.get(i, []))
                text = "%s%s\n%s%s" % (self.req_head(req, "❓"), R.question_text(q, req.chosen.get(i), done=True),
                                       "→ <b>%s</b> · " % R.esc(got) if got else "", R.esc(note))
            elif req.kind == "plan":
                text = self.req_head(req, "📋") + self.t("plan.decided", note=R.esc(note))
            else:                                  # decided: one line — the command was shown while it waited
                text = "%s%s → <b>%s</b>" % (self.req_head(req, "✋"),
                                             R.permission_line(req.tool, req.inp, lv.cwd if lv else None), R.esc(note))
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
        elif data == "k:out":
            if self.web:
                await self.web.logout_all()
                self.mark_choice(cq.get("message"), data, self.t("mark.logged_out", hm=time.strftime("%H:%M")))
            note = self.t("note.logged_out")
        elif data.startswith("h:"):
            sec = data[2:]
            text = self.t("help") if sec == "main" else self.help_section(sec)
            self.edit((cq.get("message") or {}).get("message_id"), text, self.help_buttons(sec), prio=1)
        elif data.startswith("r:") and data.count(":") == 2:
            _, sid, i = data.split(":")
            note = await self.on_reply_button(sid, int(i)) if i.isdigit() else self.t("note.stale")
        elif data.startswith("j:"):
            res = await self.api_jump(data[2:])
            note = self.t("note.jump") if res["ok"] else res["note"]
        elif data.startswith("z:"):
            try:
                at = (await self.api_resume_at(data[2:], 0))["at"]
                note = self.t("note.resume", hm=time.strftime("%H:%M", time.localtime(at)))
            except ValueError as e:
                note = str(e)
        elif data.startswith(("s:", "f:", "o:", "t:")):
            cm = cq.get("message") or {}
            note = await self.on_offer(data, cm.get("message_thread_id") if cm.get("is_topic_message") else 0, cm)
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

    def mark_choice(self, cm, data, label=None):
        """A choice made with a button (cm — the message, as the button's callback brings it): the message keeps
        its text, says "→ what was picked" (the tapped button's words, unless label says it) and loses its buttons —
        the chat shows what was done, and nothing in it can be done twice."""
        mid = (cm or {}).get("message_id")
        if not mid:
            return
        if len(self.decided_msgs) > 500:
            for k in list(self.decided_msgs)[:250]:
                del self.decided_msgs[k]
        self.decided_msgs[mid] = True
        if label is None:
            label = next((b.get("text") for row in (cm.get("reply_markup") or {}).get("inline_keyboard") or []
                          for b in row if b.get("callback_data") == data), None)
        if cm.get("text"):           # an old message Telegram no longer hands over keeps its text and buttons
            self.edit(mid, R.entities_html(cm["text"], cm.get("entities")) +
                      ("\n→ <b>%s</b>" % R.esc(label) if label else ""), [], prio=3)

    async def on_offer(self, data, here=0, cm=None):
        kind, tok = data.split(":", 1)
        if (cm or {}).get("message_id") in self.decided_msgs:
            return self.t("note.decided")       # one of its other buttons was tapped already
        o = self.offers.pop(tok, None)
        if not o:
            return self.t("note.stale_retry")
        note = await self.use_offer(kind, o, here)
        if kind in ("t", "f") or kind == "o" and o[0] != "open":
            self.mark_choice(cm, data)          # a menu (projects to open, sessions to look at) stays a menu
        return note

    async def use_offer(self, kind, o, here):
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
            fresh = cmd == "/new" or here in self.new_next
            if m.get("photo") or m.get("document"):
                gid = m.get("media_group_id")
                album = self.album_start(gid, mid, topic, thread, here) if gid else None
                marks = await self.take_files(m, topic, here)
                if album is not None:
                    # an album: Telegram sends its files as separate messages, the caption on one of them — they are
                    # gathered and go on once (stage F)
                    self.album_add(gid, album, marks, body, mid, rep_id, fresh)
                    return
                if not body.strip():
                    self.hold(here, marks, mid)            # files without words wait for the owner's next message (Q39)
                    return
                body += marks
            body = self.with_held(here, body)
            if not body.strip():
                return
            self.new_next.discard(here)
            await self.route(topic, thread, here, body, mid, rep_id, fresh)

    async def route(self, topic, thread, here, body, mid, rep_id, fresh):
        """The owner's words (with their files) go to a session: a reply — to the session it replies to; /new — to a new
        one; else the topic's current session or the question where; outside a project — which project."""
        row = self.store.msg(rep_id) if rep_id else None
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

    # ----- files from the owner (stage F) -----

    async def take_files(self, m, topic, here):
        """A file or a photo from Telegram → the project's inbox/<date>/ under its own name (a photo: "photo-<time>.jpg");
        outside a project topic — Pult's own inbox. Returns the marks for Claude's text: the path, or a line about a file
        Telegram won't hand over (over 20 MB) — the owner is told that in the topic as well."""
        if m.get("document"):
            f = m["document"]
            name = F.safe_name(f.get("file_name"), "file")
        else:
            f = m["photo"][-1]
            name = "photo-%s.jpg" % time.strftime("%H%M%S")
        size = f.get("file_size") or 0
        if size > F.TG_GET_MAX:
            mb = round(size / 2 ** 20)
            await self.send(None, self.t("files.big", name=R.esc(name), mb=mb), reply_to=m["message_id"], here=here)
            return "\n\n[A file from Telegram did not come: %s, %d MB — Telegram hands bots files up to 20 MB]" % (name, mb)
        try:
            _, blob = await self.tg.download(f["file_id"])
        except TgError as e:
            return "\n\n[An attachment from Telegram failed to download: %s — %s]" % (name, e)
        project = topic["path"] if topic and topic["path"] and os.path.isdir(topic["path"]) else None
        folder = F.drop_dir(project) if project else str(HOME / "inbox" / time.strftime("%Y-%m"))

        def save():
            os.makedirs(folder, exist_ok=True)
            if project:
                F.exclude_inbox(project)
            p = F.unique(folder, name)
            with open(p, "xb") as out:
                out.write(blob)
            return p
        p = await asyncio.to_thread(save)
        log("file from Telegram: %s (%s)" % (p, F.size_text(len(blob))))
        return "\n\n[Attachment from Telegram: %s]" % p

    def hold(self, here, marks, mid):
        """Files that came without words (decision Q39): they wait for the owner's next message in this topic, F.HOLD
        at most, and go with it; nothing comes — they just stay in the project. A reaction says they arrived."""
        h = self.held.get(here)
        if not h or time.time() - h["t"] > F.HOLD:
            h = self.held[here] = {"marks": "", "t": 0}
        h["marks"] += marks
        h["t"] = time.time()
        asyncio.create_task(self.react(mid, "👌"))

    def with_held(self, here, body):
        h = self.held.pop(here, None)
        if not h or not body.strip() or time.time() - h["t"] > F.HOLD:
            return body
        return body + h["marks"]

    def album_start(self, gid, mid, topic, thread, here):
        """An album's file is about to download: the album knows it before, so a slow download doesn't let the album go
        without it. Returns the album's generation for album_add."""
        a = self.albums.get(gid)
        if not a:
            a = self.albums[gid] = {"marks": "", "body": "", "mid": mid, "topic": topic, "thread": thread, "here": here,
                                    "rep": None, "fresh": False, "gen": 0}
        a["gen"] += 1
        return a["gen"]

    def album_add(self, gid, gen, marks, body, mid, rep_id, fresh):
        a = self.albums.get(gid)
        if not a:
            return
        a["marks"] += marks
        if body.strip() and not a["body"]:                     # the caption rides on one of the album's messages
            a["body"], a["mid"], a["rep"], a["fresh"] = body, mid, rep_id, fresh
        asyncio.create_task(self.album_go(gid, a["gen"]))

    async def album_go(self, gid, gen):
        await asyncio.sleep(ALBUM_WAIT)
        a = self.albums.get(gid)
        if not a or a["gen"] != gen:
            return                                             # another file of the album came meanwhile
        del self.albums[gid]
        if not a["body"].strip():
            self.hold(a["here"], a["marks"], a["mid"])
            return
        body = self.with_held(a["here"], a["body"] + a["marks"])
        if a["fresh"]:
            self.new_next.discard(a["here"])
        await self.route(a["topic"], a["thread"], a["here"], body, a["mid"], a["rep"], a["fresh"])

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

    # ----- voice: words from a recording (pult_stt — Groq Whisper) -----

    def make_stt(self):
        key = (self.env.get("PULT_STT_KEY") or "").strip()
        return STT.Stt(key, proxy=self.env.get("PULT_PROXY") or None,
                       model=(self.env.get("PULT_STT_MODEL") or "").strip() or None) if key else None

    def refresh_stt(self):
        """A key set or removed with `pult stt` while the daemon runs: the settings file changed — read the voice
        settings again. Nothing else is reloaded this way."""
        mt = env_mtime()
        if mt == self._env_mt:
            return
        self._env_mt = mt
        fresh = load_env()
        for k in ("PULT_STT_KEY", "PULT_STT_LANG", "PULT_STT_MODEL"):
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
        return {"on": bool(self.stt), "lang": self.stt_lang() or "auto", "words": self.store.get("stt_words") or ""}

    def stt_prompt(self):
        """What Whisper is told before the recording: a sentence in the language spoken, with the terms people say
        to Claude, and the owner's own words (Settings → Voice input) — so they come out spelled right and punctuated
        (Whisper follows the prompt's style). Folder names stay out: nobody says my_api_v2 aloud. The words go
        last, nearest the recording; the whole is cut to what Groq takes (pult_stt.fit)."""
        words = self.store.get("stt_words") or ""
        return STT.fit(self.t("stt.prompt") + (" " + self.t("stt.prompt.words", words=words) if words else ""))

    async def hear(self, blob, kind):
        """A recording → its words. Raises pult_stt.SttError — "no key" and "nothing heard" included."""
        self.refresh_stt()
        if not self.stt:
            raise STT.SttError("stt.nokey")
        text = await self.stt.transcribe(blob, kind, language=self.stt_lang(), prompt=self.stt_prompt())
        text, cut = STT.scrub(text)
        if cut:
            log("voice: Whisper's phantom cut off: %s" % " | ".join(cut))
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

    def with_uploads(self, text, files, project=None):
        """Pictures sent from the app (base64) go to ~/.local/share/pult/inbox/ and Claude gets the path; with a project,
        other files (a pdf, a deck — stage F) go to its inbox/<date>/ under their own names, like files from Telegram.
        At most UPLOADS_MAX of UPLOAD_MAX each; the rest is dropped. Nothing left to send — an error, as for an empty
        message."""
        text = (text or "").strip()
        paths = []
        for f in (files or [])[:UPLOADS_MAX]:
            try:
                blob = base64.b64decode(str((f or {}).get("data") or ""), validate=True)
            except (ValueError, binascii.Error):
                continue
            kind = image_kind(blob)
            if not blob or len(blob) > UPLOAD_MAX:
                continue
            if not kind:
                if project and os.path.isdir(project) and (f or {}).get("name"):
                    folder = F.drop_dir(project)
                    os.makedirs(folder, exist_ok=True)
                    F.exclude_inbox(project)
                    p = F.unique(folder, F.safe_name(f["name"]))
                    with open(p, "xb") as out:
                        out.write(blob)
                    paths.append(p)
                continue
            d = HOME / "inbox" / time.strftime("%Y-%m")
            d.mkdir(parents=True, exist_ok=True)
            p = d / ("app-%d-%s.%s" % (int(time.time() * 1000), secrets.token_hex(2), kind))
            p.write_bytes(blob)
            paths.append(p)
        if paths:
            text = (text or "Have a look at the attachment.") + \
                "".join("\n\n[Attachment from the Pult app: %s]" % p for p in paths)
            log("files from the app: %d" % len(paths))
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
            mark = "✍" if dr.busy else "👀"
            await self.react(origin, mark)
            self.out_add(sid, text, tg=origin, react=mark)
            await dr.say(text, origin if quote else None)
            return
        tab = self.tab_for(sid)
        if tab:
            # open in a tab with Pult's wrapper: write straight into it (stage 2)
            mark = "✍" if sid in self.live and self.live[sid].turn else "👀"
            self.out_add(sid, text, tg=origin, react=mark)
            await self.to_tab(tab, text, origin if quote else None)
            await self.react(origin, mark)
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

    def wanted(self, model, effort):
        """The model and the effort a session Pult runs starts with: its own choice, else the default from Settings
        (each half on its own); None — what Claude Code's settings say."""
        p = self.prefs()
        return model or p["model"], effort or p["effort"]

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
        self.out_add(sid, text, tg=origin, react="👀")
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
                            caps=set(hello.get("caps") or []),      # an older wrapper (before 0.9.8) sends none
                            own=hello["self"] if "self" in hello else False)   # its file's blob; False — before 0.16
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
        wrapped = bool(pult_os.files_with(EDITOR_DIRS, TAB_FILE))
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
            lines.append("\n<b>%s</b>" % R.esc(os.path.basename(cwd.rstrip(SEPS)) or cwd))
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
        # a topic's project with no transcripts yet — one made from the phone (stage S): by its folder's time
        seen = {k for _, k, _ in out}
        for pkey, path in known.items():
            if pkey not in seen and not skip_pkey(pkey) and os.path.isdir(path):
                out.append((os.stat(path).st_mtime, pkey, path))
        return sorted(out, reverse=True)

    async def cmd_projects(self, here, mode, pending=None, reply_to=None):
        """Project buttons. mode: open — give a link to the topic; new — start a session with the text from
        General; bind — bind a topic the owner created and start a session in it."""
        rows = []
        known = {r["pkey"]: r["path"] for r in self.store.db.execute("SELECT pkey, path FROM topics") if r["path"]}
        for _, pkey, path in (await asyncio.to_thread(self.list_projects, known))[:20]:
            tok = self.offer((mode, pkey, path, pending))
            rows.append([{"text": self.project_name(pkey, path), "callback_data": "o:" + tok}])
        text = self.t("projects." + mode) if rows else self.t("projects.none")
        if mode == "new" and self.app_url():        # a project that doesn't exist yet — made in the app (stage S)
            rows.append([{"text": self.t("projects.create"), "url": self.app_url(start="newproject")}])
        await self.send(None, text, buttons=rows, here=here, reply_to=reply_to)

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
        rows = [[{"text": ("✔️ " if k == m else "") + self.t("mode.%s.btn" % k), "callback_data": "w:" + k} for k in MODES]]
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
            return self.t("help.trouble", log=R.esc("~" + log_path[len(home):] if log_path.startswith(home + os.sep)
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
        if not dr or not dr.client or not dr.busy and dr.q.empty():
            key = "stop.how" if rep_id or not topic else "stop.tab" if sid and self.tab_for(sid) else "stop.none"
            await self.send(None, self.t(key), here=here)
            return
        if await dr.stop():
            log("stop: session %s, waiting messages dropped" % sid[:8])
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

    def files_row(self, sid, tf):
        """"📎 Files (N)" under a result: the app's screen of that very turn's files (stage F4)."""
        url = self.app_url(start="f_%s_%d" % (sid, tf["id"]))
        return [{"text": self.t("btn.files", n=tf["n"]), "url": url}] if url else None

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

    @staticmethod
    def bg_since(lv):
        """Since when the session's background tasks run, as far as Pult saw: the first sight of the oldest still
        running; None — none runs."""
        seen = [lv.bg_seen.get(b.get("id")) for b in lv.bg]
        return min([s for s in seen if s], default=None)

    def queued(self, sid):
        """Since when the session's message waits in the queue (Driven.slot), or None."""
        dr = self.driven.get(sid)
        return dr.queued if dr else None

    def live_item(self, lv):
        t = lv.turn
        q = self.queued(lv.sid)
        return {"sid": lv.sid, "title": self.title(lv), "project": self.project_label(lv.pkey), "pkey": lv.pkey,
                "driven": lv.driven, "state": "ask" if lv.pending else "work" if t else "queue" if q else "idle",
                "queued": q, "waiting": self.driven[lv.sid].waiting if q else None, "slots": MAX_RUNNING,
                "started": t.started if t else None, "run": (lv.run or t.started) if t else None, "prompt": R.short(R.prompt_text(t.prompt), 300) if t and t.prompt else None,
                "note": t.note if t else None, "now": R.plain(t.now, NOW_LEN) if t and t.now else None,
                "bg": [R.short(b.get("description") or b.get("command") or self.t("task.default"), 80) for b in lv.bg],
                "bg_since": self.bg_since(lv), "tab": bool(self.tab_for(lv.sid))}

    def req_item(self, req):
        lv = self.live.get(req.sid) or self.stub(req.sid)
        d = {"rid": req.rid, "sid": req.sid, "kind": req.kind, "tool": req.tool, "title": self.title(lv),
             "project": self.project_label(lv.pkey), "suggest": bool(req.suggestions), "since": req.ts}
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
        if not found and row and row["pkey"] and sid in self.driven:
            # a session Pult has just started: Claude Code writes its file a moment later, and the app opens the
            # new session at once — an empty chat for now, not "not found" (2026-10-21)
            return str(CLAUDE_PROJECTS / row["pkey"] / (sid + ".jsonl")), lv
        if not found:
            raise ValueError(self.t("err.no_transcript"))
        return str(found), lv

    async def api_overview(self):
        agents = await self.agents()
        idle = await self.idle()
        shown = {sid for sid, lv in self.live.items() if lv.turn or lv.pending or lv.bg or self.queued(sid)}
        opened = []
        for a in agents:
            sid = a.get("sessionId")
            if sid and sid not in shown:
                lv = self.live.get(sid) or self.stub(sid, sanitize(a.get("cwd") or ""))
                opened.append(dict(self.live_item(lv), project=os.path.basename((a.get("cwd") or "").rstrip(SEPS))))
        load = await self.load_state()
        return {"mac": {"idle": idle, "away": await self.away(), "mode": self.mode()}, "now": time.time(),
                "lang": self.lang(), "load": self.load_sum(load[2], load[3]) if load else None,
                "live": [self.live_item(self.live[s]) for s in shown],
                "pending": [self.req_item(r) for r in self.req_by_rid.values() if not r.fut.done()],
                "open": opened, "recent": list(self.recent),
                "jobs": [self.job_item(j) for j in self.jobs.values()] + [self.job_item(j) for j in self.jobs_done],
                "update": await self.update_row(), **await self.board(agents)}

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
        rows, tagged = [], {}
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
            q = self.queued(sid)
            st = A.state(pending, t is not None, lv.bg or (sid in self.driven and self.driven[sid].bg), rec or None, q)
            since = min(getattr(r, "ts", 0) or time.time() for r in pending) if pending else (lv.run or t.started) if t \
                else q if st == "queue" else (st == "bg" and self.bg_since(lv)) or rec.get("ts")
            line = (R.plain(t.now, NOW_LEN) if t.now else R.short(R.prompt_text(t.prompt), 160) if t.prompt
                    else t.note or "") if t else R.short(self.driven[sid].waiting or "", 160) if st == "queue" \
                else rec.get("line") or ""
            # on the board a session sits under its project: its own title, or its first prompt, never the project again
            rows.append({"sid": sid, "pkey": lv.pkey, "title": lv.title or self.title(lv), "state": st, "since": since,
                         "ts": rec.get("ts"), "line": line, "need": rec.get("need") or "", "replies": rec.get("replies") or [],
                         "fail": rec.get("fail"), "resume": self.attn.resume.get(sid),
                         "dur": rec.get("dur"), "driven": sid in self.driven, "tab": bool(self.tab_for(sid)),
                         "open": sid in opened, "model": bool(rec.get("model")),
                         "bg": [R.short(b.get("description") or b.get("command") or self.t("task.default"), 80) for b in lv.bg],
                         "cwd": lv.cwd, "tags": self.tags_of(sid, tagged)})
        return rows

    def name_of(self, pkey, rows=()):
        """A project's name: its topic's, else its folder's."""
        cwd = next((r["cwd"] for r in rows if r.get("cwd")), None) or self.project_path(pkey)
        return self.project_label(pkey) if self.store.topic(pkey) else \
            os.path.basename((cwd or "").rstrip(SEPS)) or self.project_label(pkey)

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
                             "work": sum(1 for r in rs if r["state"] in ("work", "bg", "queue")),
                             "mine": sum(1 for r in rs if r["state"] in A.MINE), "turns": turns, "secs": secs})
        mine = A.sort_rows([dict(r, project=p["name"]) for p in projects for r in p["rows_all"] if r["state"] in ("you", "fail")])
        projects = A.sort_projects(projects)
        for p in projects:
            del p["rows_all"]
        return {"board": projects, "mine": mine, "brief": self.prefs()["brief"], "reset": self.limit_reset(),
                "usage_pct": self.limit_pct(), "usage_top": await self.spend_top(), "catchup": self.catchup(),
                "stt": self.stt_state()["on"],
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
        live = A.sort_rows([r for r in rows if r["state"] in ("work", "bg", "queue")])
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
            known, tagged = {r["sid"]: r for r in rows}, {}
            for x in items:
                if x.session_id in shown:
                    continue
                r = known.get(x.session_id) or {}
                earlier.append({"sid": x.session_id, "title": R.short(x.custom_title or x.summary or "—", 80),
                                "last": x.last_modified / 1000, "line": r.get("line") or "", "open": bool(r.get("open")),
                                "driven": x.session_id in self.driven, "tags": self.tags_of(x.session_id, tagged)})
        turns, secs = self.attn.day_of(pkey)
        return {"pkey": pkey, "name": self.name_of(pkey, rows), "path": path, "pending": pending, "mine": mine,
                "live": live, "today": today, "earlier": earlier, "turns": turns, "secs": secs,
                "reset": self.limit_reset(), "stt": self.stt_state()["on"],
                "tagset": self.tag_list(pkey, list(shown) + [x["sid"] for x in earlier])}

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
                    project=self.project_label(lv.pkey) if known else os.path.basename((cwd or "").rstrip(SEPS))
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
        # stt: the app shows the microphone only with a key; create: this daemon makes new projects (stage S);
        # choice: the default model and effort from Settings, what a new task starts with when nothing is picked
        p = self.prefs()
        return {"projects": out, "stt": self.stt_state()["on"], "create": True,
                "choice": {"model": p["model"], "effort": p["effort"]}}

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
            outcome = {k: rec.get(k) for k in ("line", "need", "replies", "fail", "ts", "dur", "turn_files")}
            outcome.update(state=A.state(pending, False, lv.bg, rec), resume=self.attn.resume.get(sid),
                           reset=self.limit_reset() if rec.get("fail") == "rate_limit" else None)
        # the owner opened it: its outcome no longer calls them — unless it waits for their decision (the model named
        # what is needed) or broke off: reading isn't deciding, so that stays "your move" until they answer, write
        # to the session or press "Got it" (the owner, 2026-10-20)
        if not (rec and (rec.get("fail") or (rec.get("you") and rec.get("need")))):
            self.mark_seen(sid)
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
        # what "Default" means here: Pult's own from Settings for a session Pult runs or would resume, Claude Code's for a tab
        pref = self.prefs()
        dflt = {"model": pref["model"], "effort": pref["effort"]} if ours else None
        # the session's own title, as on the board (its first prompt until it has a name), the project beside it
        own = self.store.session_tag(sid)
        return {"sid": sid, "title": lv.title or self.title(lv), "project": self.project_label(lv.pkey), "pkey": lv.pkey,
                "outcome": outcome, "tags": self.tags_of(sid), "tagset": self.tag_list(lv.pkey),
                "tag_auto": not (own and own["own"]),
                "live": live, "page": page, "stats": stats, "choice": self.choice.get(sid) or {}, "switch": switch,
                "switch_effort": switch_effort, "default": dflt, "stt": self.stt_state()["on"],
                "ctx": {"window": ctx[0], "max_out": ctx[1], "usable": ctx_usable(ctx[0], ctx[1])} if ctx else None,
                "pending": [self.req_item(r) for r in lv.pending.values() if not r.fut.done()],
                "out": self.out_view(sid)}

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
        tab = self.tab_for(sid)
        if sid in self.driven:
            how = "session"
        elif tab:
            how = "tab"
        else:
            seen = sid in self.live and not self.live[sid].driven and self.live[sid].turn is not None
            how = "fork" if seen or any(a.get("sessionId") == sid for a in await self.agents()) else "resume"
            if how == "fork" and not fork:
                return {"ok": False, "need": "fork"}
        body = self.with_uploads(text, files, self.session_project(sid)[1])
        oid = None
        if how == "session":
            oid = self.out_add(sid, body)          # before the hand-off: its hook may come before we are back
            try:
                await self.driven[sid].say(body, None)
            except Exception:
                self.out_drop(sid, oid)
                raise
        elif how == "tab":
            oid = self.out_add(sid, body)
            try:
                await self.to_tab(tab, body, None)
            except Exception:
                self.out_drop(sid, oid)
                raise
        else:
            # a resumed session (or a copy — a new session) gets its message into the outbox in drive()
            await self.drive(sid, cwd, body, None, resume=sid if how == "resume" else None, fork=how == "fork", pkey=pkey)
            if how == "resume":
                oid = next((o["id"] for o in reversed(self.outbox.get(sid) or []) if o["body"] == body), None)
        self.mark_seen(sid, body)                  # answered: the outcome is behind, and a call about it says with what
        return {"ok": True, "how": how, "out": oid}

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
        await self.drive(sid, path, self.with_uploads(text, files, path), None, pkey=pkey, model=model, effort=effort)
        return {"ok": True, "sid": sid}

    # ----- a new project from the phone (stage S) -----

    @staticmethod
    def tilde(path):
        root = os.path.realpath(NEW_ROOT)
        return "~" + path[len(root):] if path == root or path.startswith(root.rstrip(os.sep) + os.sep) else path

    def new_parent(self):
        """Where the picker opens: the place the last project went into, else ~/Documents, else home."""
        for p in (self.store.get("new_parent"), str(NEW_ROOT / "Documents"), str(NEW_ROOT)):
            if p and os.path.isdir(p) and N.inside(p, NEW_ROOT):
                return os.path.realpath(p)
        return str(NEW_ROOT)

    def place(self, path):
        """A folder the owner picked: an existing one inside NEW_ROOT, links followed; else a refusal."""
        p = os.path.realpath(os.path.expanduser(path)) if path else self.new_parent()
        if not (os.path.isdir(p) and N.inside(p, NEW_ROOT)):
            raise ValueError(self.t("new.err.where"))
        return p

    @staticmethod
    def tab_folder(path):
        """Does writing into VS Code tabs cover this folder (the wrapper's list); None — the wrapper isn't set up."""
        try:
            folders = json.loads(TAB_CONF.read_text(encoding="utf-8")).get("folders") or []
        except (OSError, ValueError, AttributeError):
            return None
        return any(N.inside(path, os.path.expanduser(f)) for f in folders)

    async def api_dirs(self, path=None, into=None):
        """The folder picker of a new project: the folders in one place (into — one of them, a step down), a step up,
        whether tabs are covered there."""
        p = self.place(path)
        if into is not None:
            if into not in await asyncio.to_thread(N.dirs, p):
                raise ValueError(self.t("new.err.where"))
            p = self.place(os.path.join(p, into))
        root = os.path.realpath(NEW_ROOT)
        return {"path": p, "show": self.tilde(p), "up": None if p == root else os.path.dirname(p),
                "dirs": await asyncio.to_thread(N.dirs, p), "tabs": self.tab_folder(p)}

    async def api_folder(self, title=None, link=None):
        """The folder's name the app shows under the title as it is typed: from the title, else from a clone link."""
        if (title or "").strip():
            return {"name": N.folder_name(title)}
        src = N.repo(link)
        return {"name": src[1] if src and not N.bad_name(src[1]) else ""}

    def key_taken(self, pkey, dest):
        """Another folder already answers to this project key (Claude Code turns every character but Latin letters
        and digits into "-"): its path, else None. A key of a folder that is gone is free — it was this path or none."""
        row = self.store.topic(pkey)
        if row and row["path"] and row["path"] != dest and os.path.isdir(row["path"]):
            return row["path"]
        if (CLAUDE_PROJECTS / pkey).is_dir():
            other = decode_pkey(pkey)
            if other and other != dest and os.path.isdir(other):
                return other
        return None

    async def api_create(self, title=None, name=None, parent=None, how="empty", about=None, link=None, text=None,
                         files=None, model=None, effort=None, big=False):
        """A new project: a folder with git (how=empty), the same with a first turn that writes CLAUDE.md from the
        owner's description (describe), or a clone (clone — a job, the app asks api_job). Its topic in the group
        comes at once, named by the title; a first task starts a session there, as "+" does. Nothing that exists
        is touched: a taken folder or project key is a refusal."""
        title, about, text = (title or "").strip(), (about or "").strip(), (text or "").strip()
        given = title                   # a clone without a title: the folder keeps the repository's name as it is
        if how not in ("empty", "describe", "clone"):
            raise ValueError(self.t("err.no_request", op="create"))
        src = None
        if how == "clone":
            src = N.repo(link)
            if not src:
                raise ValueError(self.t("new.err.link"))
            title = title or src[1]
            if not shutil.which("git"):
                raise ValueError(self.t("new.err.git"))
        if how == "describe" and not about:
            raise ValueError(self.t("new.err.about"))
        if not title:
            raise ValueError(self.t("new.err.title"))
        name = (name or "").strip() or (await self.api_folder(given, link if how == "clone" else None))["name"]
        if N.bad_name(name):
            raise ValueError(self.t("new.err.name"))
        model, effort = self.check_choice(model, effort)
        parent = self.place(parent)
        dest = os.path.join(parent, name)
        if os.path.lexists(dest):
            raise ValueError(self.t("new.err.exists", name=name))
        pkey = sanitize(dest)
        other = self.key_taken(pkey, dest)
        if other:
            raise ValueError(self.t("new.err.key", other=self.tilde(other)))
        # the first turn's words, once the folder is there: a file from the app goes into the new project's inbox
        first = ((lambda: N.describe_prompt(title, about)) if how == "describe" else
                 (lambda: self.with_uploads(text, files, dest)) if text or files else None)
        done = lambda git: self.project_made(pkey, dest, title, parent, how, first, model, effort, git)
        if how == "clone":
            if not big:
                mb = await self.repo_mb(src[2])
                if mb and mb > N.BIG_MB:
                    return {"big": mb}
            jid = secrets.token_hex(6)
            self.jobs = {k: j for k, j in self.jobs.items() if time.time() - j["t0"] < 3600}
            self.jobs[jid] = {"state": "run", "t0": time.time(), "step": None, "name": name}
            log("new project: cloning %s into %s" % (src[0], dest))
            asyncio.create_task(self.clone(jid, src[0], dest, done))
            return {"job": jid}
        os.mkdir(dest)
        return await done(await self.git_init(dest))

    async def api_job(self, job):
        j = self.jobs.get(str(job))
        if not j:
            raise ValueError(self.t("new.err.job"))
        return dict({k: v for k, v in j.items() if k != "t0"}, sec=int(time.time() - j["t0"]))

    async def git_init(self, dest):
        """An empty git repository in a new project; False — no git here (the folder stays, the app says so)."""
        if not shutil.which("git"):
            return False
        try:
            p = await asyncio.create_subprocess_exec("git", "init", "-q", dest, stdin=asyncio.subprocess.DEVNULL,
                                                     stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE)
            _, err = await asyncio.wait_for(p.communicate(), 30)
        except (OSError, asyncio.TimeoutError) as e:
            log("new project: git init: %r" % e)
            return False
        if p.returncode:
            log("new project: git init: %s" % err.decode(errors="replace").strip()[-200:])
        return p.returncode == 0

    async def repo_mb(self, slug):
        """A GitHub repository's size in MB before a clone (gh with the owner's login, else the public API); None —
        unknown (another host, no network): cloned without asking."""
        if not slug:
            return None
        kb = None
        if shutil.which("gh"):
            out = (await self._run("gh", "api", "repos/" + slug, "--jq", ".size", timeout=10)).strip()
            kb = int(out) if out.isdigit() else None
        if kb is None:
            def public():
                import urllib.request
                with urllib.request.urlopen("https://api.github.com/repos/" + slug, timeout=8) as r:
                    return json.loads(r.read()).get("size")
            try:
                kb = await asyncio.to_thread(public)
            except Exception:
                return None
        return round(kb / 1024) if isinstance(kb, int) else None

    async def clone(self, jid, url, dest, done):
        """git clone of a new project, at a lower priority, for N.CLONE_LIMIT at most; its progress goes to the job.
        A failed clone removes what it made itself; one stopped by the limit is removed here — the folder did not
        exist before (api_create checked), so it is Pult's own."""
        job = self.jobs[jid]
        cmd = ["git", "clone", "--progress", "--", url, dest]
        if os.name != "nt" and shutil.which("nice"):
            cmd = ["nice", "-n", "10"] + cmd
        env = dict(os.environ, GIT_TERMINAL_PROMPT="0", GCM_INTERACTIVE="never")
        tail = ""
        try:
            p = await asyncio.create_subprocess_exec(*cmd, stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.DEVNULL,
                                                     stderr=asyncio.subprocess.PIPE, env=env)

            async def pump():
                nonlocal tail
                while True:
                    b = await p.stderr.read(4096)
                    if not b:
                        return
                    tail = (tail + b.decode(errors="replace"))[-4000:]
                    job["step"] = N.progress(tail) or job["step"]
            try:
                await asyncio.wait_for(asyncio.gather(pump(), p.wait()), N.CLONE_LIMIT)
            except asyncio.TimeoutError:
                p.kill()
                await p.wait()
                await asyncio.to_thread(shutil.rmtree, dest, True)
                log("new project: clone stopped after %d s: %s" % (N.CLONE_LIMIT, url))
                job.update(state="fail", error=self.t("new.err.slow", min=N.CLONE_LIMIT // 60))
                return
            if p.returncode:
                why = [ln.strip() for ln in re.split(r"[\r\n]+", tail) if ln.strip().startswith(("fatal:", "error:"))]
                log("new project: clone failed: %s" % (why[-1] if why else p.returncode))
                job.update(state="fail", error=self.t("new.err.clone", why=(why[-1] if why else "git %s" % p.returncode)[:200]))
                return
            job.update(state="done", **await done(True))
        except Exception as e:
            log("new project: clone: %r" % e)
            job.update(state="fail", error=self.t("new.err.clone", why=type(e).__name__))

    async def project_made(self, pkey, dest, title, parent, how, first, model, effort, git):
        """The folder is there: remember the project under its title, open its topic, start the first turn."""
        row = self.store.topic(pkey)
        self.store.set_topic(pkey, dest, title, row["thread"] if row and row["path"] == dest else None)
        self.store.put("new_parent", parent)
        log("new project: %s (%s%s)" % (dest, how, "" if git else ", no git"))
        try:
            await self.thread_for(pkey, dest)
        except Exception as e:
            log("new project: topic: %r" % e)
        self.changed(None)
        out = {"pkey": pkey, "git": git}
        try:
            first = first() if first else None
        except ValueError:
            first = None                                   # nothing of the first turn survived (only a broken file)
        if first:
            sid = str(uuid.uuid4())
            if how == "describe":
                self.live_of(sid, pkey).title = self.t("new.describe.session")
            await self.drive(sid, dest, first, None, pkey=pkey, model=model, effort=effort)
            out["sid"] = sid
        return out

    async def api_model(self, sid, model=KEEP, effort=KEEP):
        """The model and/or the effort of a session — whichever the app sent ("" — back to the default: Pult's from
        Settings for a session Pult runs, Claude Code's settings for a tab). A session Pult runs switches at once (SDK
        set_model, apply_flag_settings), a resting or closed one starts with the choice next time; a VS Code tab with
        Pult's wrapper switches through the wrapper."""
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
            dm, de = self.wanted(m, e)              # "" — Pult's default, if Settings has one
            if model is not KEEP:
                await dr.client.set_model(dm)
                dr.want_model = m
            if effort is not KEEP:
                dr.want_effort = e                  # a restart takes it anyway (--effort)
                try:
                    await sdk_effort(dr.client, de)
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
            try:
                self.store.log_usage(self._usage)
            except Exception as e:
                log("usage log:", repr(e))
            return self._usage

    async def api_inbox(self, name, pkey=None):
        """A picture from the owner's inbox for the app's chat: <month>/<file> inside Pult's own inbox folder (the app's
        screenshots, Telegram photos outside a project), or with pkey <date>/<file> inside that project's inbox/ (files
        from Telegram, stage F); only real images."""
        if pkey:
            root = self.project_path(pkey)
            if not root or not re.fullmatch(r"\d{4}-\d{2}-\d{2}/[^/\\]{1,%d}" % F.NAME_MAX, str(name or "")):
                raise ValueError(self.t("err.no_request", op="inbox"))
            base = Path(root) / F.INBOX
        else:
            if not re.fullmatch(r"\d{4}-\d{2}/[\w.-]{1,80}", str(name or "")):
                raise ValueError(self.t("err.no_request", op="inbox"))
            base = HOME / "inbox"
        p = (base / name).resolve()
        if not str(p).startswith(str(base.resolve()) + os.sep) or not p.is_file() or p.stat().st_size > UPLOAD_MAX:
            raise ValueError(self.t("err.no_transcript"))
        blob = await asyncio.to_thread(p.read_bytes)
        kind = image_kind(blob)
        if not kind:
            raise ValueError(self.t("err.no_transcript"))
        return {"kind": kind, "data": base64.b64encode(blob).decode()}

    # ----- files to the owner (stage F) -----

    def session_project(self, sid):
        """A session's project: (pkey, its folder), or (None, None) if Pult doesn't know the session or the folder is gone."""
        row, lv = self.store.session(sid), self.live.get(sid)
        pkey = (lv and lv.pkey) or (row and row["pkey"])
        path = self.project_path(pkey) if pkey else None
        return (pkey, path) if path and os.path.isdir(path) else (None, None)

    async def on_send(self, msg):
        """`pult send` — a command Claude ran in a session: the files go to that session's project topic. The session is
        the one Claude Code names in the command's environment (CLAUDE_CODE_SESSION_ID — probe_sessionctx.py)."""
        sid = str(msg.get("sid") or "")
        pkey, project = self.session_project(sid) if SID_RE.fullmatch(sid) else (None, None)
        if not project:
            return {"error": self.t("send.err.session")}
        paths = [str(p) for p in (msg.get("paths") or []) if p]
        if not paths:
            return {"error": self.t("cli.send.usage")}
        if len(paths) > F.SEND_MANY:
            return {"error": self.t("send.err.many", n=F.SEND_MANY)}
        res = await self.send_files(sid, pkey, project, paths, msg.get("caption"))
        res.pop("paths", None)
        return res

    async def api_send_files(self, sid, paths, zip=False):
        """The app's "To Telegram" on the screen of a turn's files (paths inside the project): the same checks as pult
        send. zip — as one archive; more than SEND_MANY files always go as one (decision Q44)."""
        pkey, project = self.session_project(sid) if SID_RE.fullmatch(sid or "") else (None, None)
        if not project:
            raise ValueError(self.t("send.err.session"))
        paths = [os.path.join(project, str(p)) for p in (paths or []) if p]
        if zip or len(paths) > F.SEND_MANY:
            res = await self.send_zip(sid, pkey, project, paths[:F.TURN_FILES_MAX])
        else:
            res = await self.send_files(sid, pkey, project, paths)
        if not res["sent"]:
            raise ValueError("; ".join("%s — %s" % (n, why) for n, why in res["refused"]) or self.t("send.err.nothing"))
        root = os.path.realpath(project)
        res["sent"] = [os.path.relpath(p, root) for p in res.pop("paths")]       # the app marks them by their paths
        return res

    async def api_turn_files(self, sid, turn=None):
        """The screen of a turn's files (stage F4): a session's turn that made or changed files — the latest one, or
        the one asked — each file as it is now (gone, or its size today), and the turns before and after it."""
        if not SID_RE.fullmatch(sid or ""):
            raise ValueError(self.t("send.err.session"))
        r = self.store.turn(sid, int(turn) if turn not in (None, "") else None)
        if not r:
            return {"id": None, "files": []}
        project = self.project_path(r["pkey"])
        files = []
        for f in r["files"]:
            p = os.path.join(project, f["p"]) if project else None
            files.append(dict(f, size=os.path.getsize(p), gone=False) if p and os.path.isfile(p) else dict(f, gone=True))
        row = self.store.session(sid)
        return {"id": r["id"], "start": r["start"], "ts": r["ts"], "dur": r["dur"], "n": r["n"], "files": files,
                "prev": r["prev"], "next": r["next"], "project": self.project_label(r["pkey"]),
                "title": (row["title"] if row else None) or ""}

    async def api_file(self, sid, p="", base=""):
        """A project's file or folder for the app's screen — a link in Claude's words tapped there (stage F5). p — the
        path as the link gives it, from the project's folder or, with base, from the folder of the project file whose
        page the link sits in. The rule is Telegram's: inside the project, nothing like keys or settings. → {p: the path
        inside the project ("" — its folder), kind: dir | pic | md | html | text | other, and entries | data | text}."""
        pkey, project = self.session_project(sid) if SID_RE.fullmatch(sid or "") else (None, None)
        if not project:
            raise ValueError(self.t("send.err.session"))
        path = F.link_target(project, p, base)
        why = F.why_not_show(path, project)
        if why:
            raise ValueError(self.t(why))
        root, real = os.path.realpath(project), os.path.realpath(path)
        rel = "" if real == root else os.path.relpath(real, root).replace(os.sep, "/")
        head = {"p": rel, "project": self.project_label(pkey)}
        if os.path.isdir(real):
            entries, n = await asyncio.to_thread(F.show_dir, real)
            return dict(head, kind="dir", entries=entries, n=n)
        got = await asyncio.to_thread(F.show_file, real)
        if "data" in got:
            got["data"] = base64.b64encode(got["data"]).decode()
        return dict(head, **got)

    def check_send(self, project, paths):
        """Each file checked for Telegram (pult_files.why_not_send): inside the project, not like a secret, 1 byte to
        50 MB. → (real paths that may go, [[name, why]] of those that may not)."""
        ok, refused = [], []
        for p in paths:
            why = F.why_not_send(p, project)
            if why:
                refused.append([os.path.basename(p), self.t(why, mb=F.TG_SEND_MAX // 2 ** 20)])
            else:
                ok.append(os.path.realpath(p))
        return ok, refused

    async def send_zip(self, sid, pkey, project, paths):
        """A project's files as one zip to its topic (stage F4): the same checks for each file, the folders inside the
        project kept; packed in the system's temporary folder and gone after. → like send_files, plus "zip": its name."""
        ok, refused = self.check_send(project, paths)
        name = F.zip_name(project)
        if not ok:
            return {"sent": [], "paths": [], "refused": refused}
        raw = sum(os.path.getsize(p) for p in ok)
        if raw > F.ZIP_RAW_MAX:
            return {"sent": [], "paths": [], "refused": refused + [[name, self.t("send.err.zip_raw", mb=round(raw / 2 ** 20),
                                                                      max=F.ZIP_RAW_MAX // 2 ** 20)]]}
        tmp = tempfile.mkdtemp(prefix="pult-zip-")
        try:
            dest = os.path.join(tmp, name)
            size = await asyncio.to_thread(F.make_zip, project, ok, dest, F.TG_SEND_MAX)
            if size is None:
                return {"sent": [], "paths": [], "refused": refused + [[name, self.t("send.err.zip_big", mb=F.TG_SEND_MAX // 2 ** 20)]]}
            res = await self.send_docs(sid, pkey, [dest], self.t("send.zip.caption", n=len(ok)))
            if not res["sent"]:
                return {"sent": [], "paths": [], "refused": refused + res["refused"]}
            log("archive to Telegram: %s, %d files (%s) from %s" % (name, len(ok), F.size_text(size), sid[:8]))
            return {"sent": [os.path.basename(p) for p in ok], "paths": ok, "zip": name, "refused": refused}
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    async def send_files(self, sid, pkey, project, paths, caption=None):
        """A project's files to its topic, each a document, the caption under the first; replying to the turn that runs.
        Every file is checked first (check_send). → {"sent": [names], "refused": [[name, why]]}; every file sent is logged."""
        ok, refused = self.check_send(project, paths)
        if not ok:
            return {"sent": [], "paths": [], "refused": refused}
        res = await self.send_docs(sid, pkey, ok, caption)
        return dict(res, refused=refused + res["refused"])

    async def send_docs(self, sid, pkey, paths, caption=None):
        """Files (already checked) to a project's topic, each a document. → {"sent": [names], "paths": [those sent],
        "refused": [[name, why]]}."""
        sent, done, refused = [], [], []
        thread = await self.thread_for(pkey)
        lv = self.live.get(sid)
        notify = await self.loud(bool(lv and lv.driven))
        reply_to = lv.turn.msg if lv and lv.turn and lv.turn.msg else None
        cap = R.short(str(caption).strip(), 1000) if caption and str(caption).strip() else None
        for i, p in enumerate(paths):
            blob = await asyncio.to_thread(Path(p).read_bytes)
            name = os.path.basename(p)
            params = dict(chat_id=self.chat, message_thread_id=thread, caption=cap if i == 0 else None,
                          disable_notification=not notify)
            if reply_to:
                params["reply_parameters"] = {"message_id": reply_to, "allow_sending_without_reply": True}
            try:
                res = await self.out.submit(3, lambda n=name, b=blob, kw=params: self.tg.call(
                    "sendDocument", files={"document": (n, b)}, timeout=300, **kw))
            except TgError as e:
                refused.append([name, self.t("send.err.tg", why=R.short(str(e), 200))])
                continue
            self.store.map_msg(res["message_id"], sid, "doc")         # a reply to the file goes to the session
            sent.append(name)
            done.append(p)
            log("file to Telegram: %s (%s) from %s" % (p, F.size_text(len(blob)), sid[:8]))
        return {"sent": sent, "paths": done, "refused": refused}

    async def files_of_turn(self, lv, t):
        """The project's files the turn made or changed (pult_files.turn_files), for its outcome: (files, how many in
        all); ([], 0) when unknown."""
        if t is None or not getattr(t, "started", None):
            return [], 0
        project = self.project_path(lv.pkey)
        if not project or not os.path.isdir(project):
            return [], 0
        try:
            return await asyncio.to_thread(F.turn_files, project, t.started, time.time())
        except Exception as e:
            log("turn files: %r" % e)
            return [], 0

    async def api_stt(self, data, mime=None, notes=None):
        """A recording from the app → its words (the app puts them into the message field). Nothing is kept. notes —
        how the recording went, from the app's level meter, for the log: whether the start of the words got lost."""
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
        log("voice from the app: %d KB%s → %d characters (%s)" % (len(blob) // 1024, self.stt_notes(notes), len(text),
                                                                  getattr(self.stt, "model", "?")))
        return {"text": text}

    @staticmethod
    def stt_notes(n):
        """The app's figures of one recording as a piece of the log line; anything odd is left out. secs — its
        length; asked — ms the phone took to give the microphone when the app asked for it anew (Telegram on Android
        asks the owner every time: then the tap's time is the owner's); ready — ms from the microphone given (the tap,
        when it was kept) until sound came; voice — ms from then until the first loud window (0: the
        owner was already speaking, the start may be lost); first — the loudest dB in that first second; peak — the
        loudest overall."""
        if not isinstance(n, dict):
            return ""
        num = lambda k, lo, hi: n.get(k) if isinstance(n.get(k), (int, float)) and lo <= n[k] <= hi else None
        out = []
        if num("secs", 0, 3600) is not None:
            out.append("%.0f s" % n["secs"])
        asked = num("asked", 0, 600000) is not None
        if asked:
            out.append("microphone asked anew: %.1f s" % (n["asked"] / 1000))
        if num("ready", 0, 60000) is not None:
            out.append("sound %.2f s after %s" % (n["ready"] / 1000, "it" if asked else "the tap"))
        if num("voice", 0, 3600000) is not None:
            out.append("voice from +%.1f s" % (n["voice"] / 1000))
        elif n.get("voice") is None and "voice" in n:
            out.append("no voice heard")
        if num("first", -200, 10) is not None:
            out.append("first second %.0f dB" % n["first"])
        if num("peak", -200, 10) is not None:
            out.append("loudest %.0f dB" % n["peak"])
        return ", " + ", ".join(out) if out else ""

    async def api_stt_words(self, words=""):
        """The owner's own words for Whisper (Settings → Voice input): names and terms, comma-separated; "" clears."""
        w = ", ".join(x for x in (" ".join(p.split()) for p in re.split(r"[,;\n]", str(words or ""))) if x)
        if len(w) > STT_WORDS_MAX:                                    # whole words only
            w = w[:STT_WORDS_MAX]
            w = w[:max(w.rfind(","), w.rfind(" "))].rstrip(" ,")
        self.store.put("stt_words", w)
        log("voice input: own words %s" % ("set (%d characters)" % len(w) if w else "cleared"))
        return {"words": w}

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
        d = await asyncio.to_thread(self.spend.today)
        for r in d["projects"]:
            r["name"] = await self.spend_name(r["pkey"])
        return d

    async def spend_name(self, pkey):
        if pkey not in self._pnames:
            path = None if self.store.topic(pkey) else await asyncio.to_thread(decode_pkey, pkey)
            self._pnames[pkey] = self.project_name(pkey, path) if path else self.project_label(pkey)
        return self._pnames[pkey]

    async def spend_view(self, u):
        """The Resources screen (stage R) from a usage reading: the curve, pace and forecast of the 5-hour window
        and the week, who spent them. Named projects and their colours: a project keeps its colour (one of COLORS
        slots), the five biggest of a view get one — a slot goes to a project not seen for longest."""
        known = self.store.get("spend_known") or {}
        log_ = self.store.usage_log(time.time() - 8 * 86400)
        v = await asyncio.to_thread(self.spend.view, u, log_, None, self.prefs()["pace"], known)
        self.store.put("spend_known", v.pop("known"))
        colors = self.store.get("spend_colors") or {}        # pkey → [slot, last time it was among the five]
        now = time.time()
        for lim in v["limits"]:
            top = [p for p, _, _ in lim["projects"][:SPEND_COLORS]]
            for pkey in top:
                if pkey in colors:
                    colors[pkey][1] = now
            for pkey in top:
                if pkey not in colors:
                    taken = {c[0]: k for k, c in colors.items()}
                    free = [i for i in range(SPEND_COLORS) if i not in taken]
                    if not free:          # the slot of the project longest out of the five, not one shown now
                        old = min((k for k in colors if k not in top), key=lambda k: colors[k][1], default=None)
                        if old is None:
                            continue
                        free = [colors.pop(old)[0]]
                    colors[pkey] = [free[0], now]
            lim["projects"] = [{"name": await self.spend_name(p), "pct": round(c, 2), "sh": sh,
                                "color": colors[p][0] if p in colors and p in top else None} for p, c, sh in lim["projects"]]
        self.store.put("spend_colors", colors)
        v["others"] = [{"name": x["name"], "percent": x["percent"], "resets_at": x["resets_at"]}
                       for x in u["limits"] if x["kind"] not in S.WINDOWS]
        v["shares"] = u.get("shares") or []
        factor = v.pop("factor")
        v.pop("per_sh_w")
        v.update(plan=u.get("plan"), ts=u.get("ts"), extra=u.get("extra"), fable_x=round(factor.get("fable") or 0, 1))
        self._spend = (time.time(), v)
        return v

    async def api_spend(self, force=False):
        """Resources (stage R): get_usage (kept a minute, `force` — anew) and the transcripts."""
        return await self.spend_view(await self.usage(bool(force)))

    async def spend_top(self):
        """The limit the Home strip shows — the one that runs out first, else the fuller one: from the last usage
        reading, no new request; the view is kept a minute."""
        at, v = self._spend
        if self._usage and (v is None or time.time() - at > 60):
            try:
                v = await self.spend_view(self._usage)
            except Exception as e:
                log("spend:", repr(e))
        lim = next((x for x in (v or {}).get("limits") or [] if x["key"] == v.get("top")), None)
        return {"key": lim["key"], "pct": lim["used"], "state": lim["state"]} if lim else None

    async def usage_watch(self):
        """Limit warnings: at 80 % and 95 %, a message with sound in General, once per window."""
        try:
            await asyncio.to_thread(self.spend.update)      # the first pass over the week's transcripts, ~2 s, not in a request
        except Exception as e:
            log("spend:", repr(e))
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
        hooks = self.hooks_on()
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
                "stt": self.stt_state(), "cc": self.cc_choice(),
                "log": [x for x in lines if "Bearer" not in x][-40:]}

    @staticmethod
    def cc_choice():
        """The model and the effort Claude Code's user settings name — what "As in Claude Code's settings" means.
        Only read: these settings are the owner's; a project's own settings may still override them."""
        try:
            s = json.loads(SETTINGS.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {"model": None, "effort": None}
        model, effort = s.get("model"), s.get("effortLevel")
        return {"model": model if isinstance(model, str) and MODEL_RE.fullmatch(model) else None,
                "effort": effort if effort in EFFORTS else None}

    async def api_prefs(self, **kw):
        cur = self.prefs()
        for k, v in kw.items():
            if k in ("vehi", "brief", "pager") and isinstance(v, bool) or k == "mode" and v in MODES or k == "lang" and v in I.LANGS \
                    or k == "pace" and v in S.PACES:
                cur[k] = v
            elif k in ("model", "effort") and (v is None or isinstance(v, str)):
                m, e = self.check_choice(v if k == "model" else None, v if k == "effort" else None)
                cur[k] = m if k == "model" else e         # "" — back to Claude Code's settings
        self.store.put("prefs", cur)
        if "mode" in kw:
            await self.set_mode(cur["mode"])
        log("settings from the app:", cur)
        return cur

    async def api_logins(self):
        """The app's recent logins (Settings → Logins) and whether the app is closed by the file check."""
        if not self.web:
            return {"logins": [], "locked": None}
        return {"logins": self.web.logins.recent(), "locked": self.web.locked}

    async def api_logout_all(self):
        if self.web:
            asyncio.ensure_future(self.web.logout_all())
        return {"ok": True}

    async def login_alert(self, net, client, via):
        """An app login from a network never seen before: told with sound, with a way to log everyone out."""
        dev = " ".join(str(client.get(k) or "") for k in ("platform", "version")).strip() or "?"
        await self.send(None, self.t("login.new", net=R.esc(net), dev=R.esc(dev), how=self.t("login.via." + via)),
                        notify=True, urgent=True, prio=1,
                        buttons=[[{"text": self.t("btn.logout_all"), "callback_data": "k:out"}]])

    async def files_alert(self, bad):
        """The app files on the server differ from the deploy (the app is closed) — or match again ([])."""
        if bad:
            await self.send(None, self.t("files.differ", files=R.esc(", ".join(bad[:6]))), notify=True, urgent=True, prio=1)
        else:
            await self.send(None, self.t("files.match"), notify=True, prio=1)

    async def conflict(self, desc):
        """getUpdates answered 409: someone else reads this bot — a second Pult on the same token, or the token has
        leaked. A webhook on Pult's token is never ours (Pult only polls): it is removed. Told at most every 6 h."""
        now = time.time()
        self.conflicts = [x for x in getattr(self, "conflicts", []) if now - x < 120] + [now]
        hook = "webhook" in desc.lower()
        if hook:
            try:
                await self.tg.call("deleteWebhook")
                log("someone had set a webhook on this bot — removed")
            except TgError as e:
                log("deleteWebhook:", e)
        if (hook or len(self.conflicts) >= 3) and now - (self.store.get("conflict_warned") or 0) > CONFLICT_WARN_EVERY:
            self.store.put("conflict_warned", now)
            await self.send(None, self.t("tg.conflict.hook" if hook else "tg.conflict"), notify=True, urgent=True, prio=1)

    async def menu_watch(self):
        while True:
            await asyncio.sleep(MENU_CHECK_EVERY)
            try:
                if await self.setup_menu_button():
                    log("the app button in the owner's chat was changed by someone else — put back")
                    await self.send(None, self.t("menu.changed"), notify=True, urgent=True, prio=1)
            except Exception as e:
                log("app button check:", repr(e))

    async def api_stop(self, sid):
        dr = self.driven.get(sid)
        if not dr or not dr.client:
            return {"ok": False, "note": self.t("stop.only_driven")}
        if await dr.stop():
            log("stop: session %s, waiting messages dropped" % sid[:8])
        return {"ok": True}

    async def api_jump(self, sid):
        """"Start now": a turn waiting in the queue goes over the MAX_RUNNING limit, once."""
        dr = self.driven.get(sid)
        if not dr or dr.queued is None:
            return {"ok": False, "note": self.t("note.not_queued")}
        dr.jump.set()
        return {"ok": True}

    async def queue_shown(self, dr, origin):
        """A message waits for a place among the MAX_RUNNING turns: the app shows the session in the queue; a message
        from the topic is answered there, with "Start now"."""
        self.changed(dr.sid)
        if not origin:
            return
        lv = self.live.get(dr.sid) or self.stub(dr.sid)
        text = "⏳ %s · %s\n%s" % (self.head(lv), self.t("queue.state"), self.t("queue.why", n=MAX_RUNNING))
        rows = [[{"text": self.t("btn.jump"), "callback_data": "j:" + dr.sid}] + (self.app_row(dr.sid) or [])]
        try:
            dr.queue_msg = await self.send(lv.pkey, text, reply_to=origin, buttons=rows, sid=dr.sid, kind="queue")
        except TgError as e:
            log("the queue's message not sent: %s" % e)

    async def queue_gone(self, dr):
        """Out of the queue — the turn starts, or Stop dropped it: the topic's message goes (one message per turn)."""
        self.changed(dr.sid)
        mid, dr.queue_msg = dr.queue_msg, None
        if mid:
            asyncio.create_task(self.drop(mid))

    # ----- loops -----

    # ----- updating Pult from its folder (stage U) -----

    def note_health(self, **kw):
        """health.json: this daemon is up, and whether it has reached Telegram and the app's server. The installer
        counts an update in only once the new daemon has said so (pult_update.Installer.healthy)."""
        self.health.update(kw)
        try:
            U.write(U.HEALTH, dict(self.health, pid=os.getpid(), version=VERSION, started=self.t_start))
        except OSError as e:
            log("health.json:", e)

    async def update_check(self, age=60):
        """What the source folder has (pult_update.check), at most `age` s old: it takes a few short git commands, and
        the app asks again on every change it hears of."""
        t, v = self._upd
        if v is None or time.monotonic() - t >= age:
            v = await asyncio.to_thread(U.check)
            self._upd = (time.monotonic(), v)
        return v

    async def update_view(self, age=60):
        """The app's "Pult" block. state: ok — nothing newer; ready — a commit to install; busy — one, but a restart
        would cut Pult's own sessions off (busy_report); wait — the owner asked to install once they are free; run —
        installing; fail — this commit didn't come up (the old version is back); na — no way here (no git source,
        Windows). The history goes with every state."""
        hist = [{k: h.get(k) for k in ("ts", "from", "to", "how", "ok", "why")} for h in U.history()[:10]]
        v = {"have": VERSION, "hist": hist, "state": "ok"}
        run = U.running()
        if run:
            return dict(v, state="run", next=run.get("to"), step=run.get("step"))
        if pult_os.KIND == "windows":
            return dict(v, state="na", why="windows")          # not yet (Q53): install.ps1
        c = await self.update_check(age)
        if not c.get("repo"):
            return dict(v, state="na", why="norepo")
        home = str(Path.home())
        v.update(dir="~" + c["repo"][len(home):] if c["repo"].startswith(home + os.sep) else c["repo"], commit=c.get("short"))
        if not c.get("ready"):
            return v
        v.update(next=c["version"], news=c["news"])
        if c.get("failed"):
            st = U.read(U.STATUS, {}) or {}
            return dict(v, state="fail", why=st.get("why"), detail=st.get("detail"), back=bool(st.get("back")),
                        back_ok=st.get("back_ok", True))
        busy = [{"project": b["project"], "title": b["title"], "turn": b["turn"], "n": b["n"]} for b in self.busy_report()]
        return dict(v, busy=busy, state="wait" if self.upd_wait else "busy" if busy else "ready")

    async def update_row(self):
        """Home's line about an update — only while there is something to do or to know."""
        try:
            v = await self.update_view()
        except Exception as e:
            log("update:", repr(e))
            return None
        broken = await self.broken()
        if v["state"] in ("ok", "na") and not broken:
            return None
        row = {"state": v["state"], "have": v["have"], "next": v.get("next"), "back": v.get("back"),
               "left": len(v.get("busy") or [])}
        if broken:
            row["broken"] = broken              # stage U2: Home says what doesn't work, not only what to install
        return row

    def emit_update(self):
        if self.web:
            self.web.emit("update")

    async def api_update(self):
        return await self.update_view(10)

    async def api_update_go(self):
        """"Install": only what the view says is ready, from the folder install.sh wrote down — the phone sends the
        tap and nothing else (no arguments: an extra one fails the call)."""
        v = await self.update_view(0)
        if v["state"] != "ready":
            raise ValueError(self.t("upd.cant.busy" if v["state"] in ("busy", "wait") else "upd.cant"))
        await self.update_start("app")
        return await self.update_view()

    async def api_update_wait(self):
        """"Install once they're free": update_tick starts it when no session of Pult's own runs."""
        v = await self.update_view(0)
        if v["state"] not in ("busy", "ready", "wait"):
            raise ValueError(self.t("upd.cant"))
        if not self.upd_wait:
            self.upd_wait = time.time()
            log("update: %s goes in once Pult's sessions are free" % v.get("next"))
        self.emit_update()
        return await self.update_view()

    async def api_update_cancel(self):
        if self.upd_wait:
            log("update: no longer waiting")
        self.upd_wait = None
        self.emit_update()
        return await self.update_view()

    async def update_start(self, how):
        """The installer, outside this service (pult_update.spawn): it stops this daemon, so "installing" is written
        first — the next daemon and the app read it from update.json."""
        c = await self.update_check()
        self.upd_wait = None
        U.write(U.STATUS, {"state": "run", "step": "start", "commit": c["head"], "from": VERSION, "to": c["version"],
                           "how": how, "ts": time.time(), "pid": None})
        log("update: installing %s (%s) — %s" % (c["version"], c["short"], how))
        ok = await asyncio.to_thread(U.spawn, c["head"], how, sys.executable)
        if not ok:
            U.write(U.STATUS, {"state": "fail", "why": "spawn", "commit": c["head"], "from": VERSION, "to": c["version"],
                               "back": False, "reported": True, "ts": time.time()})
            self._upd = (0.0, None)
            raise ValueError(self.t("upd.cant.spawn"))
        self.emit_update()

    async def update_watch(self):
        """Every 5 s (stage U): install once Pult's sessions are free, when the owner asked to; say once, in General,
        that an update didn't come up."""
        while True:
            await asyncio.sleep(5)
            try:
                await self.update_tick()
            except Exception as e:
                log("update:", repr(e))

    async def update_tick(self):
        st = U.read(U.STATUS, {}) or {}
        if st.get("state") == "fail" and st.get("reported") is False:
            st["reported"] = True
            U.write(U.STATUS, st)
            why = self.t("upd.why." + str(st.get("why")))
            if why.startswith("upd.why."):
                why = str(st.get("why"))
            await self.send(None, self.t("upd.failed" if st.get("back") else "upd.failed.kept", to=R.esc(str(st.get("to"))),
                                         back=R.esc(VERSION), why=R.esc(why)), notify=True, prio=1)
            self._upd = (0.0, None)
            self.emit_update()
        if self.upd_wait:
            v = await self.update_view()
            if v["state"] == "wait" and not v.get("busy"):
                await self.update_start("app_wait")
            elif v["state"] not in ("wait", "run"):
                self.upd_wait = None             # nothing to install any more (installed from the terminal, say)
                self.emit_update()

    # ----- every part of Pult against main (stage U2) -----

    def hooks_on(self):
        """The events Pult's hook is set for in Claude Code's settings."""
        hooks = []
        try:
            for ev, groups in (json.loads(SETTINGS.read_text(encoding="utf-8")).get("hooks") or {}).items():
                if any("pult_hook.py" in str(h.get("command", "")) for g in groups for h in g.get("hooks", [])):
                    hooks.append(ev)
        except (OSError, ValueError, AttributeError, TypeError):
            pass
        return sorted(hooks)

    @staticmethod
    @functools.cache
    def sdk_versions():
        """The Agent SDK the sessions from the app run on, and the Claude Code it carries — the same till a restart
        (reading the package's metadata takes ~0.4 s the first time: called in a thread)."""
        try:
            import importlib.metadata
            sdk = importlib.metadata.version("claude-agent-sdk")
        except Exception:
            sdk = None
        try:
            from claude_agent_sdk._cli_version import __cli_version__ as cli
        except Exception:
            cli = None
        return sdk, cli

    async def cc_facts(self, age=30):
        """Claude Code on this computer: the extension versions VS Code runs now (by their processes, and the tabs with
        the wrapper), the newest one it has downloaded, the ones the wrapper is verified on (tab.json), whether the
        wrapper is set up at all. A tab on an unverified version runs without the wrapper — writing into it is off."""
        t, v = self._cc
        if v is not None and time.monotonic() - t < age:
            return v
        snap = await self.snapshot()
        running = {t.version for t in self.tabs.values() if t.version}
        for pr in ((snap or [{}])[0] or {}).values():
            m = re.search(r"anthropic\.claude-code-(\d+(?:\.\d+)+)", pr.get("cmd") or "")
            if m and pr.get("mine", True):
                running.add(m.group(1))
        try:
            verified = json.loads(TAB_CONF.read_text(encoding="utf-8")).get("versions") or []
        except (OSError, ValueError, AttributeError):
            verified = []
        wrapped = bool(await asyncio.to_thread(pult_os.files_with, EDITOR_DIRS, TAB_FILE))
        sdk, cli = await asyncio.to_thread(self.sdk_versions)
        v = {"running": sorted(running, key=vnum), "verified": sorted(verified, key=vnum), "wrapped": wrapped,
             "newest": await asyncio.to_thread(pult_os.newest_extension, EXT_DIRS), "sdk": sdk, "cli": cli}
        self._cc = (time.monotonic(), v)
        return v

    async def broken(self):
        """What doesn't work for want of an update, for Home's line: some hook events missing (all off is the owner's
        choice — `pult hooks off`), tabs on a Claude Code the wrapper isn't verified on."""
        out = []
        on = self.hooks_on()
        missing = [e for e in pult_hook.EVENTS if e not in on]
        if on and missing:
            out.append({"k": "hooks", "missing": missing})
        cc = await self.cc_facts()
        off = [v for v in cc["running"] if v not in cc["verified"]] if cc["wrapped"] else []
        if off:
            out.append({"k": "cc", "v": off[-1]})
        return out

    def tab_facts(self):
        """The tabs with Pult's wrapper: the project, and whether its wrapper is the installed one — True, False (an
        older one, or one before 0.16 that doesn't say), None (it couldn't tell)."""
        now = {U.blob(HOME / "pult_tab.py"), U.blob(HOME / "pult_tab.py", lf=True)} - {None}
        out = []
        for t in list(self.tabs.values()):
            lv = self.live.get(t.sid) if t.sid else None
            name = self.name_of(lv.pkey) if lv and lv.pkey else os.path.basename((t.cwd or "").rstrip(SEPS)) or "?"
            own = getattr(t, "own", False)
            out.append({"project": name, "same": None if own is None else bool(own) and own in now})
        return out

    async def git_facts(self, age=60):
        """The source folder against what is installed and served: the computer's lag, the commit the relay server's
        copy was made from, the CHANGELOG — a few short git commands, kept `age` s per HEAD and relay build."""
        c = await self.update_check(age)
        repo, head = c.get("repo"), c.get("head")
        if not repo or not head:
            return {"repo": None}
        build = self.web.build if self.web else None
        key = (head, json.dumps(build, sort_keys=True) if build else None)
        t, k, v = self._parts
        if v is not None and k == key and time.monotonic() - t < age:
            return v
        v = await asyncio.to_thread(self.git_parts, repo, head, build)
        self._parts = (time.monotonic(), key, v)
        return v

    @staticmethod
    def git_parts(repo, head, build):
        m = U.read(U.MANIFEST, {}) or {}
        out = {"repo": repo, "head": head, "branch": U.git(repo, "rev-parse", "--abbrev-ref", "HEAD"),
               "mac": U.behind(repo, m.get("commit"), head, U.TREE),
               "gh": U.changelog(repo, head) if U.makes_releases(repo, head) else None}   # only where releases are made
        for part, paths in U.PARTS.items():
            files = {p: b for p, b in (build or {}).items() if any(p == x or p.startswith(x + "/") for x in paths)}
            out[part] = U.built_from(repo, head, files, paths) if files else None
            out[part + "_told"] = bool(files)
        return out

    async def parts_facts(self):
        """Everything the table is made of, in one go (the stand puts made-up facts here)."""
        return {"upd": await self.update_view(), "git": await self.git_facts(), "relay": bool(self.web),
                "tabs": self.tab_facts(), "hooks": self.hooks_on(), "cc": await self.cc_facts()}

    @staticmethod
    def parts_rows(f):
        """The table "Pult and its parts" (Settings): one row per part — k, st (ok · warn — can be brought up to date ·
        bad — something doesn't work · attn — worth a look · info — to know, or not known), have (what is there) and
        what the app says about it. The phone's own copy is the app's row: only it knows which one it runs."""
        g, upd = f["git"], f["upd"]
        rows = []
        lag_mac = g.get("mac") or {}
        n = lag_mac.get("n") if upd["state"] not in ("ok", "na") else 0
        rows.append({"k": "mac", "st": {"ok": "ok", "na": "info", "fail": "bad"}.get(upd["state"], "warn"),
                     "have": upd["have"], "n": n, "since": lag_mac.get("since"), "upd": upd})
        if f["relay"]:
            for part in ("web", "relay"):
                b = g.get(part)
                if b:
                    rows.append({"k": part, "st": "warn" if b["n"] else "ok", "have": b["ts"], "commit": b["commit"][:7],
                                 "n": b["n"], "since": b["since"], "news": b["news"]})
                else:
                    why = "norepo" if not g.get("repo") else "other" if g.get(part + "_told") else "old"
                    rows.append({"k": part, "st": "info", "why": why})
        tabs, cc = f["tabs"], f["cc"]
        if tabs or cc["wrapped"]:
            old = sorted({t["project"] for t in tabs if t["same"] is False})
            rows.append({"k": "tabs", "st": "warn" if old else "ok", "have": len(tabs), "old": old,
                         "n_old": sum(t["same"] is False for t in tabs),
                         "unknown": sum(t["same"] is None for t in tabs)})
        on = f["hooks"]
        missing = [e for e in pult_hook.EVENTS if e not in on]
        rows.append({"k": "hooks", "st": "bad" if missing else "ok", "have": len(on), "all": len(pult_hook.EVENTS),
                     "missing": missing})
        off = [v for v in cc["running"] if v not in cc["verified"]] if cc["wrapped"] else []
        fresh = cc["newest"] if cc["wrapped"] and cc["newest"] and cc["newest"] not in cc["verified"] \
            and cc["newest"] not in cc["running"] else None
        rows.append({"k": "cc", "st": "bad" if off else "attn" if fresh else "ok" if cc["wrapped"] else "info",
                     "have": (cc["running"] or [cc["newest"]])[-1], "off": off, "fresh": fresh,
                     "verified": cc["verified"][-1] if cc["verified"] else None, "wrapped": cc["wrapped"],
                     "sdk": cc["sdk"], "cli": cc["cli"]})
        gh = g.get("gh")
        if gh and gh.get("last"):
            rows.append({"k": "gh", "st": "info" if gh["waiting"] else "ok", "have": gh["last"], "date": gh["date"],
                         "waiting": gh["waiting"]})
        return rows

    async def api_parts(self):
        """Settings → "Pult and its parts": the table, the source folder's HEAD it was checked against, and when."""
        f = await self.parts_facts()
        head = (f["git"].get("head") or "")[:7] or None
        return {"head": head, "branch": f["git"].get("branch"), "at": time.time(), "rows": self.parts_rows(f)}

    def busy_report(self):
        """What stopping the daemon would cut off (`pult busy`, a restart asks first): Pult's own sessions — their
        claude is the daemon's child — with a turn running, prompts queued or background tasks, subagents too. A
        session whose turn has ended may still have them (2026-10-20: a restart killed a background subagent that
        way). Tabs live in VS Code and survive a restart; `pult run` tasks are processes of their own."""
        out = []
        for sid, d in list(self.driven.items()):
            lv = self.live.get(sid)
            bg = [R.short(b.get("description") or b.get("command") or self.t("task.default"), 80) for b in (lv.bg if lv else [])]
            n = max(len(d.bg), len(bg))
            turn = d.busy or not d.q.empty()
            if turn or n:
                out.append({"sid": sid, "title": self.title(lv) if lv else sid[:8],
                            "project": self.name_of(lv.pkey) if lv else "", "turn": turn, "bg": bg, "n": n})
        return out

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
            if msg.get("op") == "send":                   # pult send (stage F)
                res = await self.on_send(msg)
                writer.write((json.dumps(res, ensure_ascii=False) + "\n").encode())
                await writer.drain()
                return
            if msg.get("op") == "busy":
                writer.write((json.dumps({"busy": self.busy_report()}, ensure_ascii=False) + "\n").encode())
                await writer.drain()
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
                if e.code == 409:
                    try:
                        await self.conflict(e.desc)
                    except Exception as e2:
                        log("409 alert:", repr(e2))
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

    async def telegram_start(self):
        """Telegram may be out of reach for a while at start: after logging in to Windows the VPN comes up later
        (2026-10-21: 20 s, the first time 13 min), and the bot's menu and the first messages failed one by one and
        were never tried again. Here the bot's menu, the panel, the version notice and reading updates wait until
        Telegram first answers. The app, the tabs and the hooks don't wait for it."""
        t0, delay, said = time.monotonic(), TG_REACH[0], False
        while True:
            try:
                await self.tg.call("getMe")
                break
            except TgError as e:
                if e.code is not None:
                    break                  # Telegram answered (a revoked token…): what follows reports it
                why = e
            except (httpx.HTTPError, ValueError) as e:
                why = e
            if not said:
                log("Telegram out of reach, waiting:", why)
                said = True
            await asyncio.sleep(delay)
            delay = min(delay * 2, TG_REACH[1])
        if said:
            log("Telegram reachable after %d s" % (time.monotonic() - t0))
        self.note_health(telegram=True)
        await self.setup_commands()
        await asyncio.gather(self.poll(), self.tab_version_watch(), self.ensure_panel(), self.menu_watch())

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
        app — Telegram's default, the command list. → True if it had to be put back: rechecked every
        MENU_CHECK_EVERY, because whoever holds the token could point it at their own page and get a real login."""
        url = self.app_web_url()
        want = {"type": "web_app", "text": self.t("menu.app"), "web_app": {"url": url}} if url else {"type": "default"}
        changed = False
        for uid in sorted(self.allowed):
            try:
                cur = await self.tg.call("getChatMenuButton", chat_id=uid)
                if cur != want:
                    await self.tg.call("setChatMenuButton", chat_id=uid, **({"menu_button": want} if url else {}))
                    # only the kind and the address matter: the label follows Pult's language
                    cur = cur if isinstance(cur, dict) else {}
                    changed = changed or cur.get("type") != want["type"] or \
                        (cur.get("web_app") or {}).get("url") != (want.get("web_app") or {}).get("url")
            except TgError as e:
                log("menu button:", e)
        return changed


LINK_LIMIT = 8 * 1024 * 1024      # the longest line on the link


async def start_link(handle, path):
    """The daemon's end of the link (pult_os.link_connect is the other end): a unix socket with mode 600, or on
    Windows (and with PULT_LINK=tcp) 127.0.0.1 on a free port — the port, a fresh key and the pid go into the link
    file, mode 600 (Windows: the user's own folder). A connection that doesn't open with the key is dropped."""
    if not pult_os.link_tcp():
        try:
            os.unlink(path)
        except FileNotFoundError:
            pass
        server = await asyncio.start_unix_server(handle, path=path, limit=LINK_LIMIT)
        os.chmod(path, 0o600)
        return server
    key = secrets.token_urlsafe(32).encode()

    async def keyed(reader, writer):
        try:
            line = await asyncio.wait_for(reader.readline(), 5)
        except (asyncio.TimeoutError, ConnectionError, ValueError):
            line = b""
        if not hmac.compare_digest(line.rstrip(b"\r\n"), key):
            writer.close()
            return
        await handle(reader, writer)
    server = await asyncio.start_server(keyed, "127.0.0.1", 0, limit=LINK_LIMIT)
    tmp = path + ".tmp"
    try:
        os.unlink(tmp)
    except FileNotFoundError:
        pass
    with os.fdopen(os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "w", encoding="utf-8") as f:
        json.dump({"port": server.sockets[0].getsockname()[1], "key": key.decode(), "pid": os.getpid()}, f)
    os.replace(tmp, path)
    return server


async def open_link(path):
    """The client's end for asyncio (checks, probes): (reader, writer), the key already sent."""
    if not pult_os.link_tcp():
        return await asyncio.open_unix_connection(path, limit=LINK_LIMIT)
    link = json.loads(Path(path).read_text(encoding="utf-8"))
    r, w = await asyncio.open_connection("127.0.0.1", int(link["port"]), limit=LINK_LIMIT)
    w.write(link["key"].encode() + b"\n")
    return r, w


def windows_service():
    """Windows, under pythonw from the Task Scheduler: no console, so the log is the daemon's own file, and the
    programs it starts (claude for sessions from Telegram, the result-line model) get no console window either —
    as when the VS Code extension starts claude (windowsHide)."""
    if sys.stdout is None:
        LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        sys.stdout = sys.stderr = open(LOG_FILE, "a", encoding="utf-8", buffering=1)
    import subprocess
    if getattr(subprocess.Popen.__init__, "pult_no_window", False):
        return
    init = subprocess.Popen.__init__

    def no_window(self, *a, **kw):
        kw["creationflags"] = kw.get("creationflags", 0) | subprocess.CREATE_NO_WINDOW
        init(self, *a, **kw)
    no_window.pult_no_window = True
    subprocess.Popen.__init__ = no_window


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
    server = await start_link(p.handle_conn, SOCK)
    log("Pult started; group:", p.chat, "; link: 127.0.0.1:%d" % server.sockets[0].getsockname()[1]
        if pult_os.link_tcp() else "; socket: " + SOCK)
    # the panel is sent via the message queue, so it must run alongside it, or startup hangs (seen 2026-10-16, 0.6.0)
    jobs = [p.out.run(), p.telegram_start(), p.usage_watch(), p.attention_watch(), p.update_watch()]
    if env.get("PULT_RELAY_URL") and env.get("PULT_RELAY_SECRET"):
        p.web = PW.Web(p, env["PULT_RELAY_URL"], env["PULT_RELAY_SECRET"], token, p.allowed,
                       proxy=env.get("PULT_PROXY") or None, manifest=WEB_MANIFEST)
        jobs += [p.web.run(), p.web.guard()]
    p.note_health(telegram=False, relay=False if p.web else None)     # None: no app server to reach
    async with server:
        await asyncio.gather(*jobs)


if __name__ == "__main__":
    if os.name == "nt":
        windows_service()
    try:
        asyncio.run(amain())
    except KeyboardInterrupt:
        pass
