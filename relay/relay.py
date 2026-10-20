#!/usr/bin/env python3
"""Pult: the web app relay on the relay server. Connects the Telegram Mini App on the phone to the daemon on the Mac.

  phone ──wss /pult/ws──► relay ◄──wss /pult/agent── Mac (pultd connects by itself, using a shared secret)

Stores nothing: everything the app shows comes from the Mac at request time. Strangers are cut off before the Mac,
by Telegram's public signature (Ed25519, no bot token needed); the Mac checks the login again with its bot token and
decides how fresh it must be (a reconnect carries the Mac's one-time resume key, which passes through here).
Design and decisions: docs/project.html, the "Web app" section.
"""
import asyncio
import base64
import collections
import hashlib
import hmac
import ipaddress
import itertools
import json
import os
import re
import stat
import time
import urllib.parse
from pathlib import Path

from aiohttp import WSMsgType, web
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

PORT = int(os.environ.get("PULT_RELAY_PORT", "8097"))
SOCKET = os.environ.get("PULT_RELAY_SOCKET", "")   # a unix socket instead of the port: see listen()
SECRET = os.environ.get("PULT_RELAY_SECRET", "")
OWNER = int(os.environ.get("PULT_OWNER_ID", "0"))
BOT_ID = os.environ.get("PULT_BOT_ID", "")
WEB = Path(os.environ.get("PULT_WEB_DIR") or Path(__file__).resolve().parent / "web")
# The relay only keeps strangers out; the Mac decides how fresh a login must be (minutes for a new one, a resume key for
# a reconnect). An app window may live in Telegram for days and reconnect with the initData it was opened with
MAX_AGE = 7 * 24 * 3600
MAX_CLIENTS = 6            # app windows at once: the owner's phone and maybe Telegram on the Mac
HELLO_WAIT = 10            # s for a new connection to say who it is
WAITING_PER_IP = 3         # connections that haven't said who they are yet: per address and in all
WAITING_MAX = 30
# Telegram's public key for checking initData without the bot token ("Validating data for Third-Party Use")
TG_PUBLIC = bytes.fromhex("e7bf03a2fa4602af4580703d88dda5bb59f32ed8b02a56c187fe7d34caed242d")


def log(*a):
    print(time.strftime("%Y-%m-%d %H:%M:%S"), *a, flush=True)


def client_ip(request):
    """The phone's address as the web server saw it: X-Real-IP (nginx), else the last X-Forwarded-For hop (Caddy
    appends the real one; anything before it came from the client). The relay listens only for the web server."""
    real = request.headers.get("X-Real-IP")
    if real:
        return real.strip()[:64]
    fwd = request.headers.get("X-Forwarded-For")
    if fwd:
        return fwd.split(",")[-1].strip()[:64]
    return request.remote or ""


def known(ip):
    """A real address, not the web server's own hop: behind a TCP proxy that passes no client address (nginx stream
    without PROXY protocol) every phone looks like 127.0.0.1 — no per-address limit on that, or one stranger's
    three idle connections would lock everyone out."""
    try:
        return not ipaddress.ip_address(ip).is_loopback
    except ValueError:
        return False


def csp(importmap, host):
    """The page's Content-Security-Policy: scripts only from here and telegram.org (plus the import map, by its hash),
    connections only back here. A second line behind md.js: markup that slipped into the page can neither run nor
    send anything elsewhere. pult_web.page_csp repeats this to check what the server hands out."""
    digest = base64.b64encode(hashlib.sha256(importmap.encode()).digest()).decode()
    own = " wss://%s ws://%s" % (host, host) if re.fullmatch(r"[A-Za-z0-9.:\[\]-]{1,255}", host or "") else ""
    return "; ".join(["default-src 'self'", "script-src 'self' https://telegram.org 'sha256-%s'" % digest,
                      "style-src 'self' 'unsafe-inline'", "img-src 'self' data: blob:", "media-src 'self' data: blob:",
                      "connect-src 'self'" + own, "object-src 'none'", "base-uri 'none'", "form-action 'none'",
                      "frame-ancestors 'self' https://web.telegram.org https://*.telegram.org"])


def check_init(init):
    """Telegram initData → (signature valid, is the owner, fresh, fields without hash and signature)."""
    fields = dict(urllib.parse.parse_qsl(init or "", keep_blank_values=True))
    sig = fields.pop("signature", "")
    fields.pop("hash", None)
    ok = False
    if sig and BOT_ID:
        dcs = "%s:WebAppData\n" % BOT_ID + "\n".join("%s=%s" % (k, fields[k]) for k in sorted(fields))
        try:
            Ed25519PublicKey.from_public_bytes(TG_PUBLIC).verify(
                base64.urlsafe_b64decode(sig + "=" * (-len(sig) % 4)), dcs.encode())
            ok = True
        except Exception:
            ok = False
    try:
        uid = int(json.loads(fields.get("user") or "{}").get("id") or 0)
    except ValueError:
        uid = 0
    try:
        fresh = time.time() - int(fields.get("auth_date") or 0) < MAX_AGE
    except ValueError:
        fresh = False
    return ok, uid == OWNER and OWNER > 0, fresh, fields


class Relay:
    def __init__(self):
        self.mac = None                     # connection to the Mac
        self.clients = {}                   # cid → phone connection (login confirmed by the Mac)
        self.pending = {}                   # cid → connection waiting for the Mac to confirm the login
        self.inits = {}                     # cid → what the window said (initData, resume key, address, client):
        self.ids = itertools.count(1)       # when the Mac reconnects, it checks the login again
        self.waiting = collections.Counter()    # address → connections that haven't said who they are yet

    async def to_mac(self, msg):
        if self.mac is not None and not self.mac.closed:
            await self.mac.send_str(json.dumps(msg, ensure_ascii=False))
            return True
        return False

    async def to_clients(self, msg, cid=None, waiting=False):
        """Send to app windows: one (cid) or all with a confirmed login; waiting=True adds pending ones too."""
        text = json.dumps(msg, ensure_ascii=False)
        targets = [self.clients.get(cid)] if cid else list(self.clients.values()) + \
            (list(self.pending.values()) if waiting else [])
        for ws in targets:
            if ws is not None and not ws.closed:
                try:
                    await ws.send_str(text)
                except ConnectionError:
                    pass

    # ----- phone -----

    async def ws_client(self, request):
        ws = web.WebSocketResponse(heartbeat=25, max_msg_size=8 * 1024 * 1024)   # a message may carry pictures
        await ws.prepare(request)
        ip = client_ip(request)
        if len(self.clients) + len(self.pending) >= MAX_CLIENTS or known(ip) and self.waiting[ip] >= WAITING_PER_IP \
                or sum(self.waiting.values()) >= WAITING_MAX:
            await ws.close(code=4429, message=b"too many")
            return ws
        cid = next(self.ids)
        self.waiting[ip] += 1
        said = False
        try:
            first = await ws.receive(timeout=HELLO_WAIT)
            said = self.unwait(ip)
            if first.type != WSMsgType.TEXT:
                return ws                              # gone (or not a word) before saying who it is
            hello = json.loads(first.data)
            ok, owner, fresh, fields = check_init(hello.get("init"))
            if not (ok and owner and fresh):
                # a stranger learns nothing about why; the owner's week-old window is told to reopen
                await ws.send_str(json.dumps({"t": "denied", "why": "expired"} if ok and owner else {"t": "denied"}))
                log("login rejected: signature %s, owner %s, fresh %s, %s" % (ok, owner, fresh, ip))
                return ws
            c = hello.get("client") or {}             # where the app is opened from; never the initData itself
            client = {"platform": str(c.get("platform") or "")[:20], "version": str(c.get("version") or "")[:20]}
            key = hello.get("resume")
            log("app window %d: %s %s, %s" % (cid, client["platform"], client["version"], ip))
            self.pending[cid] = ws
            self.inits[cid] = {"init": hello.get("init"), "ip": ip, "client": client,
                               "resume": key if isinstance(key, str) and len(key) <= 100 else None}
            mac = await self.to_mac(dict(self.inits[cid], t="open", cid=cid))
            await ws.send_str(json.dumps({"t": "hello", "cid": cid, "mac": mac}))
            async for m in ws:
                if m.type != WSMsgType.TEXT:
                    continue
                msg = json.loads(m.data)
                if cid not in self.clients:
                    continue                          # the Mac has not confirmed the login yet
                msg["cid"] = cid
                if not await self.to_mac(msg):
                    await ws.send_str(json.dumps({"t": "mac", "on": False}))
        except (asyncio.TimeoutError, ValueError, TypeError, AttributeError, ConnectionError) as e:
            log("phone %d: %r" % (cid, e))
        finally:
            if not said:
                self.unwait(ip)
            self.pending.pop(cid, None)
            self.clients.pop(cid, None)
            self.inits.pop(cid, None)
            await self.to_mac({"t": "close", "cid": cid})
        return ws

    def unwait(self, ip):
        self.waiting[ip] -= 1
        if self.waiting[ip] <= 0:
            del self.waiting[ip]
        return True

    # ----- Mac -----

    async def ws_agent(self, request):
        auth = request.headers.get("Authorization", "")
        if not SECRET or not hmac.compare_digest(auth, "Bearer " + SECRET):
            log("Mac: wrong secret from", request.headers.get("X-Real-IP") or request.remote)
            raise web.HTTPUnauthorized()
        ws = web.WebSocketResponse(heartbeat=25, max_msg_size=16 * 1024 * 1024)
        await ws.prepare(request)
        old, self.mac = self.mac, ws
        if old is not None and not old.closed:
            await old.close(code=4000, message=b"replaced")
        log("Mac connected")
        await self.to_clients({"t": "mac", "on": True}, waiting=True)
        for cid, cws in list(self.clients.items()):
            self.pending[cid] = self.clients.pop(cid)     # the new Mac knows no windows: let it check the login
        for cid in list(self.pending):
            if cid in self.inits:
                await self.to_mac(dict(self.inits[cid], t="open", cid=cid))
        try:
            async for m in ws:
                if m.type != WSMsgType.TEXT:
                    continue
                msg = json.loads(m.data)
                cid = msg.pop("cid", None)
                if msg.get("t") == "auth":
                    cws = self.pending.pop(cid, None)
                    if cws is None:
                        continue
                    if msg.get("ok"):
                        self.clients[cid] = cws
                        ready = {"t": "ready"}
                        if msg.get("resume"):                 # the next reconnect (or the Mac's) uses this key
                            self.inits[cid]["resume"] = ready["resume"] = msg["resume"]
                        await cws.send_str(json.dumps(ready))
                    else:
                        await cws.send_str(json.dumps({"t": "denied", "by": "mac", "why": msg.get("why")}))
                        await cws.close()
                    continue
                if msg.get("t") == "kick":                    # the Mac closes a window: the owner logged out everywhere
                    cws = self.clients.pop(cid, None) or self.pending.pop(cid, None)
                    if cws is not None and not cws.closed:
                        await cws.send_str(json.dumps({"t": "denied", "by": "mac", "why": msg.get("why")}))
                        await cws.close()
                    continue
                await self.to_clients(msg, cid)
        finally:
            if self.mac is ws:
                self.mac = None
                log("Mac disconnected")
                await self.to_clients({"t": "mac", "on": False}, waiting=True)
        return ws

    # ----- pages -----

    async def index(self, request):
        # ?v= in links to app files is the latest modification time, so after a deploy Telegram drops stale copies.
        # The modules app.js imports get it through an import map: their own links carry no ?v=, and Telegram kept
        # an old i18n.js under a new app.js (keys instead of words on the owner's phone, 0.9.9)
        files = [p for p in (WEB / "static").rglob("*") if p.is_file()]
        v = str(int(max((p.stat().st_mtime for p in files), default=0)))
        mods = {"/pult/static/%s" % p.relative_to(WEB / "static").as_posix(): None for p in files if p.suffix == ".js"}
        imap = json.dumps({"imports": {k: "%s?v=%s" % (k, v) for k in sorted(mods)}})
        page = (WEB / "index.html").read_text().replace("{{importmap}}", imap).replace("{{v}}", v)
        return web.Response(text=page, content_type="text/html", headers={
            "Cache-Control": "no-cache", "Content-Security-Policy": csp(imap, request.host)})

    async def health(self, request):
        # whether the Mac is connected — for the deploy scripts; how many windows are open is nobody's business
        return web.json_response({"ok": True, "mac": self.mac is not None and not self.mac.closed})


def app():
    r = Relay()
    a = web.Application(client_max_size=64 * 1024)
    a.router.add_get("/pult/", r.index)
    a.router.add_get("/pult/healthz", r.health)
    a.router.add_get("/pult/ws", r.ws_client)
    a.router.add_get("/pult/agent", r.ws_agent)
    (WEB / "static").mkdir(parents=True, exist_ok=True)
    a.router.add_static("/pult/static/", WEB / "static", show_index=False)

    async def revalidate(request, response):
        # app files: the phone asks every time whether its copy is current (a 304 if it is) instead of guessing
        if request.path.startswith("/pult/static/"):
            response.headers["Cache-Control"] = "no-cache"
    a.on_response_prepare.append(revalidate)
    return a


def listen():
    """Where to listen: the port on 127.0.0.1, or a unix socket when PULT_RELAY_SOCKET is set. On a server shared
    with other programs, any of them can take a free port while the relay restarts, and the web server would hand
    the phone that program's page; a socket in a folder only the relay and the web server can enter can't be taken.
    A socket left by a crash is removed; any other file at that path is left alone (binding then fails)."""
    if not SOCKET:
        return {"host": "127.0.0.1", "port": PORT}
    try:
        if stat.S_ISSOCK(os.lstat(SOCKET).st_mode):
            os.unlink(SOCKET)
    except FileNotFoundError:
        pass
    return {"path": SOCKET}


if __name__ == "__main__":
    where = listen()
    log("Pult relay: %s, bot %s, owner %s, Mac %s" % (where.get("path") or "127.0.0.1:%d" % PORT, BOT_ID or "?",
                                                      OWNER or "?", "by secret" if SECRET else "NO SECRET"))
    # restart on deploy is fast: don't wait for live WebSockets, the Mac and the windows reconnect by themselves
    web.run_app(app(), **where, print=None, access_log=None, shutdown_timeout=2)
