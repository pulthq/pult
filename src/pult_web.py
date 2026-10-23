"""Pult: the daemon's web module — the connection to the relay server and data for the web app (stage 1B).

The daemon connects to the relay itself (wss …/pult/agent, with a shared secret) and keeps the connection open.
The app window on the phone comes in through the relay; the login is checked again here, with the bot key
(HMAC of initData): a new login takes a fresh initData, a reconnect — the one-time key this Mac gave the window.
After that: app requests (overview, projects, session chat, actions) and live events.
Session transcripts are only read, in chunks from the end. The files the relay hands to the phone are checked
against what was deployed; while they differ, the app is closed.
"""
import asyncio
import base64
import hashlib
import hmac
import ipaddress
import json
import os
import re
import secrets
import threading
import time
import urllib.parse
from datetime import datetime

import pult_render as R
from pult_i18n import T

LOGIN_FRESH = 10 * 60          # s: a new login takes an initData at most this old (Telegram makes one on every open)
SIGNED_MAX = 7 * 24 * 3600     # s: an older initData still proves the owner's Telegram — together with a resume key
KEY_IDLE = 7 * 24 * 3600       # s: a resume key unused this long is dropped (that window has to be reopened)
KEY_GRACE = 60                 # s: a replaced key still works this long (a window's reconnect racing the Mac's)
KEYS_MAX = 20
LOGINS_MAX = 30                # the app's list of recent logins
NETS_MAX = 100                 # networks logins came from: a login from a new one is told in Telegram
GUARD_FIRST = 60               # s after start before the first check of the files the server hands out
GUARD_EVERY = 15 * 60          # s between the checks
GUARD_RECHECK = 90             # s: a difference is checked again before it counts (a deploy may be in progress)
APP_PATH = "/pult/"            # where the relay serves the app (relay.py)
# why a login was refused → the short code the app's list of logins shows in words
REFUSED = {"login expired": "expired", "resume key unknown or used up": "badkey", "not the owner": "stranger",
           "signature mismatch": "forged", "no signature": "forged", "broken fields": "forged"}
RECONNECT = (1, 2, 5, 10, 30)  # seconds between attempts to connect to the relay server
PAGE = 1536 * 1024             # transcript bytes per chat chunk
TEXT_MAX = 20000               # characters of one message in the app
IO_MAX = 1500                  # characters of tool input and output

_NOISE = re.compile(r"<(system-reminder|ide_opened_file|ide_selection|ide_diagnostics)>.*?</\1>", re.S)
# a picture Claude shows: a path into Pult's inbox in its reply (a screenshot, a mock-up it rendered). The app shows
# it under the message, the bare path leaves the text; only the inbox can be shown (api_inbox checks it again)
_SHOWN = re.compile(r"`?(/[^\s`'\"<>()\[\]]*/inbox/\d{4}-\d{2}/[\w.-]+\.(?:png|jpe?g|webp|gif))`?", re.I)


def log(*a):
    print(time.strftime("%Y-%m-%d %H:%M:%S"), "web:", *a, flush=True)


def why(e):
    """A short description of a connection error. Not repr: aiohttp errors carry the request headers, and the
    Mac's secret would end up in the log (happened 2026-10-16, the secret was rotated)."""
    status = getattr(e, "status", None)
    return "%s%s" % (type(e).__name__, " %s" % status if status else "")


def check_init(init, token, owners, now=None, max_age=LOGIN_FRESH):
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
    if age > max_age:
        return False, uid, "login expired"
    return True, uid, how


def init_age(init, now=None):
    """Seconds since Telegram made this initData (for the log: is it really fresh on every open)."""
    try:
        return int((now or time.time()) - int(dict(urllib.parse.parse_qsl(init or "")).get("auth_date") or 0))
    except ValueError:
        return None


def net_of(ip):
    """An address → its network, for "a login from a new place": IPv4 /24 ("203.0.113.x"), IPv6 /48. "" — unknown:
    the relay saw the web server's own hop (127.0.0.1), as behind a TCP proxy that passes no client address."""
    try:
        a = ipaddress.ip_address(str(ip or "").strip())
    except ValueError:
        return str(ip or "?")[:64]
    if a.version == 6 and a.ipv4_mapped:
        a = a.ipv4_mapped
    if a.is_loopback:
        return ""
    if a.version == 4:
        return ".".join(str(a).split(".")[:3]) + ".x"
    return str(ipaddress.ip_network("%s/48" % a, strict=False))


class Keys:
    """Resume keys. A window that reconnects (the network blinked, the Mac or the relay restarted) logs in with the
    key this Mac gave it at its last login, so a new login needs a fresh initData and an old one alone is worth
    nothing. A key works once: each use gives the next one (the old one lingers KEY_GRACE s for a racing
    reconnect). Only hashes are kept, in state.db: a restart of the daemon doesn't log the windows out."""

    def __init__(self, store):
        self.store = store

    @staticmethod
    def _h(key):
        return hashlib.sha256(str(key).encode()).hexdigest()

    def _live(self, now):
        keys = self.store.get("app_keys") or {}
        return {h: k for h, k in keys.items() if now - k.get("made", 0) < KEY_IDLE and k.get("dead", now + 1) > now}

    def issue(self, uid, now=None, keys=None):
        now = now or time.time()
        keys = self._live(now) if keys is None else keys
        key = secrets.token_urlsafe(32)
        keys[self._h(key)] = {"uid": uid, "made": now}
        if len(keys) > KEYS_MAX:
            keys = dict(sorted(keys.items(), key=lambda kv: -kv[1]["made"])[:KEYS_MAX])
        self.store.put("app_keys", keys)
        return key

    def use(self, key, uid, now=None):
        """The key a window brought → the next one, or None: unknown, used up, expired or not this user's."""
        now = now or time.time()
        keys = self._live(now)
        k = keys.get(self._h(key)) if isinstance(key, str) and key else None
        if not k or k.get("uid") != uid:
            return None
        k.setdefault("dead", now + KEY_GRACE)
        return self.issue(uid, now, keys)

    def drop_all(self):
        self.store.put("app_keys", {})


class Logins:
    """The app's recent logins, for the owner's eyes (Settings), and the networks they came from. A login from a
    network never seen before is worth a message in Telegram; the first login after an update only learns."""

    def __init__(self, store):
        self.store = store

    def note(self, ok, how, ip, client, now=None):
        """Remember a login attempt → True if it got in from a network that is new (and others were known)."""
        now = now or time.time()
        net = net_of(ip)
        rec = {"ts": now, "ok": bool(ok), "how": how, "net": net,
               "dev": " ".join(str(client.get(k) or "") for k in ("platform", "version")).strip()[:40]}
        self.store.put("app_logins", [rec] + (self.store.get("app_logins") or [])[:LOGINS_MAX - 1])
        if not ok or not net:
            return False                       # refused, or the address is unknown: nothing to learn or tell
        # 0.9.23 learned the web server's own hop ("127.0.0.x") as a network: dropped, so the first real one is
        # learned quietly instead of being "new"
        nets = {k: v for k, v in (self.store.get("app_nets") or {}).items() if not k.startswith("127.")}
        new = bool(nets) and net not in nets
        nets[net] = now
        if len(nets) > NETS_MAX:
            nets = dict(sorted(nets.items(), key=lambda kv: -kv[1])[:NETS_MAX])
        self.store.put("app_nets", nets)
        return new

    def recent(self):
        return self.store.get("app_logins") or []


# ---------- what the server hands to the phone ----------

def expected_page(template, files, v):
    """The page the relay builds from index.html (relay.Relay.index) for these app files → (page, import map)."""
    mods = sorted("%sstatic/%s" % (APP_PATH, f) for f in files if f.endswith(".js"))
    imap = json.dumps({"imports": {k: "%s?v=%s" % (k, v) for k in mods}})
    return template.replace("{{importmap}}", imap).replace("{{v}}", v), imap


def page_csp(importmap, host):
    """relay.csp, repeated here to check the header the server sends (a test keeps the two equal)."""
    digest = base64.b64encode(hashlib.sha256(importmap.encode()).digest()).decode()
    own = " wss://%s ws://%s" % (host, host) if re.fullmatch(r"[A-Za-z0-9.:\[\]-]{1,255}", host or "") else ""
    return "; ".join(["default-src 'self'", "script-src 'self' https://telegram.org 'sha256-%s'" % digest,
                      "style-src 'self' 'unsafe-inline'", "img-src 'self' data: blob:", "media-src 'self' data: blob:",
                      "connect-src 'self'" + own, "object-src 'none'", "base-uri 'none'", "form-action 'none'",
                      "frame-ancestors 'self' https://web.telegram.org https://*.telegram.org"])


def make_manifest(web_dir):
    """What a deploy puts on the server (relay/web): the page template and a hash of every app file. Written by the
    deploy script next to the daemon; the daemon compares what the server hands out with it."""
    static = web_dir / "static"
    files = {p.relative_to(static).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
             for p in sorted(static.rglob("*")) if p.is_file() and "__pycache__" not in p.parts and p.name != ".DS_Store"}
    return {"index": (web_dir / "index.html").read_text(), "files": files}


# ---------- session chat from the transcript ----------

def _text_of(content):
    if isinstance(content, str):
        return content
    return "\n".join(b.get("text", "") for b in content or [] if isinstance(b, dict) and b.get("type") == "text")


def _short(s, n):
    s = str(s or "")
    return s if len(s) <= n else s[:n - 1] + "…"


def inbox_name(path):
    """A path the owner sent → what the app may ask for, with a flag for pictures: "2026-10/app-1.jpg" in Pult's own
    inbox; "2026-10-23/plan.png" and the project's key in a project's inbox/ (files from Telegram, stage F). A file
    elsewhere keeps only its name and can't be shown."""
    path = str(path)
    parts = path.replace("\\", "/").split("/")
    out = {"name": parts[-1], "image": R.is_image(path), "inbox": False}
    if len(parts) >= 4 and parts[-3] == "inbox":
        if re.fullmatch(r"\d{4}-\d{2}", parts[-2]):
            out.update(name="/".join(parts[-2:]), inbox=True)
        elif re.fullmatch(r"\d{4}-\d{2}-\d{2}", parts[-2]):
            out.update(name="/".join(parts[-2:]), inbox=True, pkey=re.sub(r"[^a-zA-Z0-9]", "-", "/".join(parts[:-3])))
    return out


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
            # it as a queued_command attachment, not as a user message, and its own tab doesn't show it (2.1.301).
            # A tab marks it origin human; a session through the SDK has no origin at all (probe_midturn.py, 2.1.300)
            att = e.get("attachment") if isinstance(e.get("attachment"), dict) else {}
            origin = att.get("origin")
            if att.get("type") == "queued_command" and att.get("commandMode", "prompt") == "prompt" \
                    and (origin is None or isinstance(origin, dict) and origin.get("kind") == "human"):
                text = _NOISE.sub("", _text_of(att.get("prompt"))).strip()
                if text and not R.task_notes(text):
                    clean, paths = R.attachments(text)
                    item = {"k": "user", "text": _short(clean, TEXT_MAX), "ts": e.get("timestamp"), "mid": True}
                    if R.is_spoken(text):
                        item["voice"] = True
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
                if R.is_spoken(text):
                    item["voice"] = True
                if paths:
                    item["att"] = [inbox_name(p) for p in paths]
                items.append(item)
            continue
        # Claude's own words about its progress between steps: the transcript marks the entry thinkingDisplay
        # "updates", the VS Code tab shows it as "summary" (2.1.296–2.1.301, from the tab and from the SDK alike).
        # Plain thinking stays private; only the words leave, never the block's signature
        updates = e.get("thinkingDisplay") == "updates"
        for b in content if isinstance(content, list) else [{"type": "text", "text": content or ""}]:
            if not isinstance(b, dict):
                continue
            if b.get("type") == "text" and b.get("text", "").strip():
                shown = _SHOWN.findall(b["text"])
                item = {"k": "text", "text": _short(_SHOWN.sub("", b["text"]) if shown else b["text"], TEXT_MAX), "ts": ts}
                if shown:
                    item["att"] = [inbox_name(p) for p in dict.fromkeys(shown)]
                items.append(item)
            elif updates and b.get("type") == "thinking" and (b.get("thinking") or "").strip():
                items.append({"k": "update", "text": _short(b["thinking"].strip(), TEXT_MAX), "ts": ts})
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
    # a model's own share of the week (Fable): used and allowed, in % of the whole week — fits its factor (stage R)
    shares = []
    raw = rl.get("limits") or []
    for s in rl.get("weekly_scoped_shares") or []:
        i = s.get("limit_index")
        lim = raw[i] if isinstance(i, int) and 0 <= i < len(raw) else {}
        model = (((lim.get("scope") or {}).get("model")) or {}).get("display_name")
        if model and s.get("used_percent_of_weekly") is not None:
            shares.append({"name": model, "used": s.get("used_percent_of_weekly"), "allow": s.get("allowance_percent_of_weekly")})
    return {"plan": (r or {}).get("subscription_type"), "limits": out, "ts": time.time(), "shares": shares,
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


# ---------- connection to the relay ----------

class Web:
    def __init__(self, pult, url, secret, token, owners, proxy=None, manifest=None):
        self.p = pult
        self.url = url
        self.secret = secret
        self.token = token
        self.owners = owners
        self.proxy = proxy
        self.manifest = manifest       # Path of what the last deploy put on the server (None — no file check)
        self.ws = None
        self.clients = set()
        self.how = None                # which signature variant matched — a fact for the project doc
        self.keys = Keys(pult.store)
        self.logins = Logins(pult.store)
        self.locked = None             # what differs on the server, while the app is closed because of it
        self.checked = False           # the files have matched at least once (said in the log once)

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
            await self.login(cid, msg)
        elif t == "close":
            self.clients.discard(cid)
        elif t == "req" and cid in self.clients:
            asyncio.ensure_future(self.answer(cid, msg))

    async def login(self, cid, msg):
        """A window asks to log in: a fresh initData (a new open of the app) or an older one plus the resume key this
        Mac gave that window. Either way the window gets the next key; the attempt goes to the logins list."""
        init, ip = msg.get("init"), str(msg.get("ip") or "")
        client = msg.get("client") if isinstance(msg.get("client"), dict) else {}
        ok, uid, how = check_init(init, self.token, self.owners)
        key, via = None, "open"
        if ok:
            if how != self.how:
                self.how = how
                log("app login: bot-key signature matched %s" % how)
            key = self.keys.issue(uid)
        elif how == "login expired" and msg.get("resume"):
            # an old initData still proves it's the owner's Telegram; what lets the reconnect in is this Mac's key
            signed, uid, _ = check_init(init, self.token, self.owners, max_age=SIGNED_MAX)
            key = self.keys.use(msg["resume"], uid) if signed else None
            ok, via, how = bool(key), "key", "resume key" if key else "resume key unknown or used up"
        why = None
        if ok and self.locked:
            ok, key, how, why = False, None, "the app is closed: the server hands out other files", "locked"
        elif not ok and how in ("login expired", "resume key unknown or used up"):
            why = "expired"
        age = init_age(init)
        log("app login %s: %s, %s, %s (initData %s s old)" % ("ok" if ok else "rejected", how, net_of(ip) or "address unknown",
                                                             client.get("platform") or "?", age))
        new_net = self.logins.note(ok, via if ok else "locked" if why == "locked" else REFUSED.get(how, "forged"), ip, client)
        if ok:
            self.clients.add(cid)
        reply = {"t": "auth", "cid": cid, "ok": ok}
        if key:
            reply["resume"] = key
        if why:
            reply["why"] = why
        await self.send(reply)
        if new_net:
            await self.p.login_alert(net_of(ip), client, via)

    async def kick_all(self, why):
        """Close every app window (logged out everywhere; the app closed by the file check)."""
        for cid in list(self.clients):
            await self.send({"t": "kick", "cid": cid, "why": why})
        self.clients.clear()

    async def logout_all(self):
        """Every resume key is dropped and every window closed: from now on only a fresh open of the app gets in."""
        self.keys.drop_all()
        log("app: logged out everywhere")
        await asyncio.sleep(0.3)               # the answer to the window that asked goes out first
        await self.kick_all("out")

    # ----- what the server hands to the phone -----

    def app_base(self):
        """wss://host/pult/agent → https://host/pult/ (http for a ws:// relay — the test stand)."""
        u = urllib.parse.urlsplit(self.url)
        return "%s://%s%s" % ("https" if u.scheme == "wss" else "http", u.netloc, APP_PATH)

    async def check_files(self, http):
        """→ what the server hands out differently from the last deploy ([] — all the same), or None: no manifest,
        or the server couldn't be asked (that is not a difference)."""
        try:
            man = json.loads(self.manifest.read_text()) if self.manifest else None
        except (OSError, ValueError):
            man = None
        if not man:
            return None
        base = self.app_base()
        # what Telegram on a phone looks like: a server that hands the Mac other files than the phone gets them too
        ua = {"User-Agent": "Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 "
                            "Mobile Safari/537.36 Telegram-Android/11.0"}
        import aiohttp
        try:
            for proxy in ([self.proxy] if self.proxy else []) + [None]:
                try:
                    async with http.get(base, proxy=proxy, headers=ua, timeout=aiohttp.ClientTimeout(total=30)) as r:
                        page, csps = await r.text(), r.headers.getall("Content-Security-Policy", [])
                    break
                except (aiohttp.ClientError, asyncio.TimeoutError, OSError):
                    if proxy is None:
                        raise
            m = re.search(re.escape(APP_PATH) + r"static/app\.js\?v=(\d+)", page)
            want, imap = expected_page(man["index"], man["files"], m.group(1) if m else "?")
            bad = [] if page == want else ["index.html"]
            if page_csp(imap, urllib.parse.urlsplit(base).netloc) not in csps:
                bad.append("Content-Security-Policy")
            for rel, sha in sorted(man["files"].items()):
                async with http.get("%sstatic/%s?v=%s" % (base, rel, m.group(1) if m else ""), proxy=proxy, headers=ua,
                                    timeout=aiohttp.ClientTimeout(total=30)) as r:
                    if r.status != 200 or hashlib.sha256(await r.read()).hexdigest() != sha:
                        bad.append(rel)
            return bad
        except (aiohttp.ClientError, asyncio.TimeoutError, OSError) as e:
            log("app files check: the server didn't answer (%s)" % why(e))
            return None

    async def guard(self):
        """Every GUARD_EVERY: the files the server hands out = the last deploy. A difference that holds after
        GUARD_RECHECK closes the app — logins refused, windows closed — and is told in Telegram: whoever changed the
        app on the server would otherwise run in the owner's window. Opens again by itself once the files match."""
        import aiohttp
        await asyncio.sleep(GUARD_FIRST)
        async with aiohttp.ClientSession() as http:
            while True:
                try:
                    await self.guard_once(http)
                except Exception as e:
                    log("app files check:", repr(e))
                await asyncio.sleep(GUARD_EVERY)

    async def guard_once(self, http):
        bad = await self.check_files(http)
        if bad == [] and not self.checked:
            self.checked = True
            log("app files on the server match the deploy")
        if bad and not self.locked:
            await asyncio.sleep(GUARD_RECHECK)
            again = await self.check_files(http)
            if again:
                self.locked = ", ".join(again)
                log("app files on the server differ from the deploy: %s — the app is closed" % self.locked)
                await self.kick_all("locked")
                await self.p.files_alert(again)
        elif bad == [] and self.locked:
            log("app files on the server match the deploy again — the app is open")
            self.locked = None
            await self.p.files_alert([])

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
