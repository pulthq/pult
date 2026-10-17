"""Pult: the daemon's web module — the connection to the relay server and data for the web app (stage 1B).

The daemon connects to the relay itself (wss …/pult/agent, with a shared secret) and keeps the connection open.
The app window on the phone comes in through the relay; the login is checked again here, with the bot key
(HMAC of initData). After that: app requests (overview, projects, session chat, actions) and live events.
Session transcripts are only read, in chunks from the end.
"""
import asyncio
import hashlib
import hmac
import json
import os
import re
import threading
import time
import urllib.parse
from datetime import datetime

import pult_render as R
from pult_i18n import T

MAX_AGE = 24 * 3600            # reject initData older than one day
RECONNECT = (1, 2, 5, 10, 30)  # seconds between attempts to connect to the relay server
PAGE = 1536 * 1024             # transcript bytes per chat chunk
TEXT_MAX = 20000               # characters of one message in the app
IO_MAX = 1500                  # characters of tool input and output

_NOISE = re.compile(r"<(system-reminder|ide_opened_file|ide_selection|ide_diagnostics)>.*?</\1>", re.S)


def log(*a):
    print(time.strftime("%Y-%m-%d %H:%M:%S"), "web:", *a, flush=True)


def why(e):
    """A short description of a connection error. Not repr: aiohttp errors carry the request headers, and the
    Mac's secret would end up in the log (happened 2026-10-16, the secret was rotated)."""
    status = getattr(e, "status", None)
    return "%s%s" % (type(e).__name__, " %s" % status if status else "")


def check_init(init, token, owners, now=None):
    """Telegram initData → (is the bot-key signature valid, user ID, reason if not).
    The check string includes every field except hash, the signature field (Bot API 8.0) included. In case
    Telegram computes it without that field, the second variant is accepted too, and the log says which matched."""
    fields = dict(urllib.parse.parse_qsl(init or "", keep_blank_values=True))
    got = fields.pop("hash", "")
    if not got or not token:
        return False, 0, "no signature"
    secret = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()

    def calc(fs):
        dcs = "\n".join("%s=%s" % (k, fs[k]) for k in sorted(fs))
        return hmac.new(secret, dcs.encode(), hashlib.sha256).hexdigest()
    if hmac.compare_digest(calc(fields), got):
        how = "with signature"
    elif "signature" in fields and hmac.compare_digest(calc({k: v for k, v in fields.items() if k != "signature"}), got):
        how = "without signature"
    else:
        return False, 0, "signature mismatch"
    try:
        uid = int(json.loads(fields.get("user") or "{}").get("id") or 0)
        age = (now or time.time()) - int(fields.get("auth_date") or 0)
    except ValueError:
        return False, 0, "broken fields"
    if uid not in owners:
        return False, uid, "not the owner"
    if age > MAX_AGE:
        return False, uid, "login expired"
    return True, uid, how


# ---------- session chat from the transcript ----------

def _text_of(content):
    if isinstance(content, str):
        return content
    return "\n".join(b.get("text", "") for b in content or [] if isinstance(b, dict) and b.get("type") == "text")


def _short(s, n):
    s = str(s or "")
    return s if len(s) <= n else s[:n - 1] + "…"


def inbox_name(path):
    """A path in the owner's inbox → what the app may ask for ("2026-10/app-1.jpg"), with a flag for pictures;
    a file elsewhere keeps only its name and can't be shown."""
    path = str(path)
    parts = path.replace("\\", "/").split("/")
    inside = len(parts) >= 3 and parts[-3] == "inbox"
    return {"name": "/".join(parts[-2:]) if inside else parts[-1], "image": R.is_image(path), "inbox": inside}


def transcript_page(path, before=None, after=None, cwd=None, page=PAGE):
    """A chunk of the chat: from the end of the file, up to byte `before` (older) or from byte `after` (newer).
    → {"items": [...], "before": where to read older from, or None, "end": where to read newer from}.
    The last unfinished line is skipped: it will be completed and come with the next `after`."""
    try:
        with open(path, "rb") as f:
            f.seek(0, 2)
            size = f.tell()
            if after is not None:
                start, end = min(int(after), size), size
                if end - start > page:
                    return {"items": [], "before": None, "end": end, "reset": True}
            else:
                end = size if before is None else min(int(before), size)
                start = max(0, end - page)
            f.seek(start)
            data = f.read(end - start)
    except (OSError, ValueError):
        return {"items": [], "before": None, "end": None}
    if before is None:
        last = data.rfind(b"\n")
        end, data = start + last + 1, data[:last + 1]
    if start > 0 and after is None:
        cut = data.find(b"\n")
        start, data = start + cut + 1, data[cut + 1:]
    items, tools = [], {}
    for line in data.split(b"\n"):
        if not line.strip():
            continue
        try:
            e = json.loads(line)
        except ValueError:
            continue
        kind = e.get("type")
        if kind == "attachment":
            # a message that reached Claude in the middle of its turn (written while it was busy): Claude Code keeps
            # it as a queued_command attachment, not as a user message, and its own tab doesn't show it (2.1.301)
            att = e.get("attachment") if isinstance(e.get("attachment"), dict) else {}
            if att.get("type") == "queued_command" and att.get("commandMode", "prompt") == "prompt" \
                    and (att.get("origin") or {}).get("kind") == "human":
                text = _NOISE.sub("", _text_of(att.get("prompt"))).strip()
                if text:
                    clean, paths = R.attachments(text)
                    item = {"k": "user", "text": _short(clean, TEXT_MAX), "ts": e.get("timestamp"), "mid": True}
                    if paths:
                        item["att"] = [inbox_name(p) for p in paths]
                    items.append(item)
            continue
        if kind not in ("user", "assistant") or e.get("isSidechain") or e.get("isMeta"):
            continue
        ts = e.get("timestamp")
        content = (e.get("message") or {}).get("content")
        if kind == "user":
            blocks = content if isinstance(content, list) else []
            for b in blocks:
                if isinstance(b, dict) and b.get("type") == "tool_result":
                    out = b.get("content")
                    res = {"ok": not b.get("is_error"), "out": _short(_text_of(out) if not isinstance(out, str) else out,
                                                                     IO_MAX)}
                    t = tools.get(b.get("tool_use_id"))
                    if t is not None:
                        t.update(res)
                    else:
                        items.append(dict(res, k="result", id=b.get("tool_use_id"), ts=ts))
            text = _NOISE.sub("", _text_of(content)).strip()
            notes = R.task_notes(text)
            if notes:                    # not from the owner: Claude Code began a turn because a background task ended
                items.append({"k": "note", "text": R.task_notes_text(notes), "ts": ts})
            elif text and not text.startswith("<local-command-") and not text.startswith("<command-"):
                clean, paths = R.attachments(text)          # the path is for Claude; the person sees the picture
                item = {"k": "user", "text": _short(clean, TEXT_MAX), "ts": ts}
                if paths:
                    item["att"] = [inbox_name(p) for p in paths]
                items.append(item)
            continue
        for b in content if isinstance(content, list) else [{"type": "text", "text": content or ""}]:
            if not isinstance(b, dict):
                continue
            if b.get("type") == "text" and b.get("text", "").strip():
                items.append({"k": "text", "text": _short(b["text"], TEXT_MAX), "ts": ts})
            elif b.get("type") == "tool_use":
                inp = b.get("input") if isinstance(b.get("input"), dict) else {}
                t = {"k": "tool", "id": b.get("id"), "name": b.get("name"), "ts": ts,
                     "step": R.tool_step(b.get("name"), inp, cwd) or b.get("name"),
                     "input": _short(json.dumps(inp, ensure_ascii=False, indent=1), IO_MAX)}
                tools[b.get("id")] = t
                items.append(t)
    return {"items": items, "before": (start if start > 0 else None) if after is None else None, "end": end}


# ---------- subscription usage ----------

LIMIT_NAMES = {"session": "lim.session", "weekly_all": "lim.week", "weekly_scoped": "lim.week"}   # pult_i18n keys


def _iso(s):
    try:
        return datetime.fromisoformat(str(s).replace("Z", "+00:00")).timestamp()
    except (TypeError, ValueError):
        return None


def simplify_usage(r):
    """get_usage response (Claude Code, experimental — may change) → limits for the app and for
    warnings. Uses the generic `limits` list, so new kinds of limits show up on their own."""
    rl = (r or {}).get("rate_limits") or {}
    out = []
    for lim in rl.get("limits") or []:
        model = (((lim.get("scope") or {}).get("model")) or {}).get("display_name")
        kind = lim.get("kind")
        name = (T(LIMIT_NAMES[kind]) if kind in LIMIT_NAMES else kind or T("lim.other")) + (" · " + model if model else "")
        out.append({"kind": lim.get("kind"), "name": name, "percent": lim.get("percent") or 0,
                    "resets_at": _iso(lim.get("resets_at")), "severity": lim.get("severity"),
                    "active": bool(lim.get("is_active"))})
    if not out:                       # old response format: only the 5-hour window and the week
        for key, name in (("five_hour", T("lim.session")), ("seven_day", T("lim.week"))):
            w = rl.get(key)
            if w:
                out.append({"kind": key, "name": name, "percent": w.get("utilization") or 0,
                            "resets_at": _iso(w.get("resets_at")), "severity": None, "active": False})
    extra = rl.get("extra_usage") or {}
    rows = (rl.get("seven_day_breakdown") or {}).get("rows") or []
    return {"plan": (r or {}).get("subscription_type"), "limits": out, "ts": time.time(),
            "extra": {"enabled": bool(extra.get("is_enabled")), "used": extra.get("used_credits"),
                      "limit": extra.get("monthly_limit"), "currency": extra.get("currency")},
            "week_by": [{"name": x.get("display_name"), "percent": x.get("percent")} for x in rows if x.get("percent")]}


# ---------- session model, thinking, tokens ----------

class Stats:
    """Session model, effort, context and tokens from the transcript — reading only new data (the files are big)."""

    def __init__(self):
        self.files = {}
        self.lock = threading.Lock()           # two app windows may ask about the same session at once

    def get(self, path):
        with self.lock:
            return self._get(path)

    def _get(self, path):
        st = self.files.get(path)
        try:
            size = os.path.getsize(path)
        except OSError:
            return None
        if st is None or size < st["off"]:
            st = self.files[path] = {"off": 0, "model": None, "effort": None, "context": 0, "last_id": None,
                                     "turn": {"req": 0, "out": 0, "think": 0}, "sess": {"req": 0, "out": 0}}
        if size > st["off"]:
            with open(path, "rb") as f:
                f.seek(st["off"])
                data = f.read(size - st["off"])
            last = data.rfind(b"\n")
            if last >= 0:
                st["off"] += last + 1
                for line in data[:last].split(b"\n"):
                    self.feed(st, line)
        return {k: st[k] for k in ("model", "effort", "context", "turn", "sess")}

    @staticmethod
    def feed(st, line):
        if b'"assistant"' not in line and b'"user"' not in line:
            return
        try:
            e = json.loads(line)
        except ValueError:
            return
        if e.get("isSidechain") or e.get("isMeta"):
            return
        m = e.get("message") or {}
        if e.get("type") == "user":
            if _NOISE.sub("", _text_of(m.get("content"))).strip():      # a new prompt starts a new turn
                st["turn"] = {"req": 0, "out": 0, "think": 0}
            return
        if e.get("type") != "assistant" or m.get("id") == st["last_id"]:
            return                                    # one message is written as several lines
        u = m.get("usage")
        if not u:
            return                                    # no token data — not a model request
        st["last_id"] = m.get("id")
        st["model"] = m.get("model") or st["model"]
        st["effort"] = e.get("effort") or st["effort"]
        out = u.get("output_tokens") or 0
        # the same sum VS Code's context gauge uses (webview 2.1.301): input, cache and the reply itself
        st["context"] = (u.get("input_tokens") or 0) + (u.get("cache_read_input_tokens") or 0) + \
            (u.get("cache_creation_input_tokens") or 0) + out
        think = (u.get("output_tokens_details") or {}).get("thinking_tokens") or 0
        for k in ("turn", "sess"):
            st[k]["req"] += 1
            st[k]["out"] += out
        st["turn"]["think"] += think


class DayTokens:
    """Today's tokens per project across all transcripts on the Mac, reading only new data. The first pass reads
    everything modified today (measured 2026-10-16: 44 files, 155 MB — 0.25 s), after that only appended data.
    One model response is written as several lines, and a session copy repeats the original's lines, so we count
    by message.id."""

    def __init__(self, root, skip=lambda pkey: False):
        self.root = root
        self.skip = skip
        self.lock = threading.Lock()
        self.day = None
        self.off = {}                          # file → bytes already read
        self.seen = set()
        self.per = {}

    def get(self, now=None):
        with self.lock:
            return self._get(now or time.time())

    def _get(self, now):
        lt = time.localtime(now)
        midnight = time.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday, 0, 0, 0, 0, 0, -1))
        if self.day != midnight:
            # new day: keep the offsets — everything before them is from yesterday
            self.day, self.seen, self.per = midnight, set(), {}
        files = []
        for p in list(self.root.glob("*/*.jsonl")) + list(self.root.glob("*/*/subagents/*.jsonl")):
            pkey = p.relative_to(self.root).parts[0]
            try:
                st = p.stat()
            except OSError:
                continue
            if st.st_mtime >= midnight and not self.skip(pkey):
                files.append((st.st_mtime, str(p), pkey, st))
        for _, key, pkey, st in sorted(files):     # oldest first: a reply repeated in a session copy doesn't count
            off = self.off.get(key, 0)
            if st.st_size < off:
                off = 0                        # file was rewritten — message.id filters out repeats
            if st.st_size == off:
                continue
            try:
                with open(key, "rb") as f:
                    f.seek(off)
                    for line in f:
                        if not line.endswith(b"\n"):
                            break              # unfinished line — read the rest next time
                        off += len(line)
                        if b'"usage"' in line and b'"assistant"' in line:
                            self.feed(pkey, line, midnight)
            except OSError:
                pass
            self.off[key] = off
        rows = [dict(v, pkey=k) for k, v in self.per.items()]
        return {"day": midnight, "projects": sorted(rows, key=lambda r: -r["out"])}

    def feed(self, pkey, line, midnight):
        try:
            e = json.loads(line)
        except ValueError:
            return
        m = e.get("message") or {}
        u = m.get("usage")
        if e.get("type") != "assistant" or not u or (_iso(e.get("timestamp")) or 0) < midnight:
            return
        mid = m.get("id")
        if mid:
            if mid in self.seen:
                return
            self.seen.add(mid)
        d = self.per.setdefault(pkey, {"req": 0, "out": 0, "read": 0})
        d["req"] += 1
        d["out"] += u.get("output_tokens") or 0
        d["read"] += (u.get("input_tokens") or 0) + (u.get("cache_read_input_tokens") or 0) + \
            (u.get("cache_creation_input_tokens") or 0)


# ---------- connection to the relay ----------

class Web:
    def __init__(self, pult, url, secret, token, owners, proxy=None):
        self.p = pult
        self.url = url
        self.secret = secret
        self.token = token
        self.owners = owners
        self.proxy = proxy
        self.ws = None
        self.clients = set()
        self.how = None                # which signature variant matched — a fact for the project doc

    @property
    def on(self):
        return self.ws is not None and not self.ws.closed and bool(self.clients)

    async def run(self):
        import aiohttp
        attempt, fails = 0, 0
        async with aiohttp.ClientSession() as http:
            while True:
                for proxy in ([self.proxy] if self.proxy else []) + [None]:
                    try:
                        async with http.ws_connect(self.url, proxy=proxy, heartbeat=25, max_msg_size=8 * 1024 * 1024,
                                                   headers={"Authorization": "Bearer " + self.secret},
                                                   timeout=aiohttp.ClientWSTimeout(ws_close=10)) as ws:
                            self.ws, attempt = ws, 0
                            log("connected to the relay%s" % (" via proxy" if proxy else " directly"))
                            fails = 0
                            async for m in ws:
                                if m.type == aiohttp.WSMsgType.TEXT:
                                    await self.on_msg(json.loads(m.data))
                            log("relay connection closed")
                            break
                    except (aiohttp.ClientError, asyncio.TimeoutError, OSError, ValueError) as e:
                        fails += 1
                        if fails in (1, 10) or fails % 100 == 0:
                            log("can't connect to the relay (%d): %s" % (fails, why(e)))
                    finally:
                        self.ws = None
                        self.clients.clear()
                await asyncio.sleep(RECONNECT[min(attempt, len(RECONNECT) - 1)])
                attempt += 1

    async def send(self, msg):
        if self.ws is not None and not self.ws.closed:
            try:
                await self.ws.send_str(json.dumps(msg, ensure_ascii=False))
            except (ConnectionError, RuntimeError):
                pass

    def emit(self, kind, **data):
        """Event for every open app window: turn progress, prompt, result."""
        if self.on:
            asyncio.ensure_future(self.send(dict(data, t="event", kind=kind)))

    async def on_msg(self, msg):
        t, cid = msg.get("t"), msg.get("cid")
        if t == "open":
            ok, uid, how = check_init(msg.get("init"), self.token, self.owners)
            if ok and how != self.how:
                self.how = how
                log("app login: bot-key signature matched %s" % how)
            if not ok:
                log("app login rejected: %s (%s)" % (how, uid))
            else:
                self.clients.add(cid)
            await self.send({"t": "auth", "cid": cid, "ok": ok})
        elif t == "close":
            self.clients.discard(cid)
        elif t == "req" and cid in self.clients:
            asyncio.ensure_future(self.answer(cid, msg))

    async def answer(self, cid, msg):
        rid, op = msg.get("id"), msg.get("op")
        fn = getattr(self.p, "api_" + str(op), None)
        try:
            if fn is None:
                raise ValueError(T("err.no_request", op=op))
            data = await fn(**(msg.get("args") or {}))
            await self.send({"t": "res", "cid": cid, "id": rid, "data": data})
        except Exception as e:
            log("request %s: %r" % (op, e))
            await self.send({"t": "res", "cid": cid, "id": rid, "error": str(e)[:300]})
