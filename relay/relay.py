#!/usr/bin/env python3
"""Pult: the web app relay on the relay server. Connects the Telegram Mini App on the phone to the daemon on the Mac.

  phone ──wss /pult/ws──► relay ◄──wss /pult/agent── Mac (pultd connects by itself, using a shared secret)

Stores nothing: everything the app shows comes from the Mac at request time. Strangers are cut off before the Mac,
by Telegram's public signature (Ed25519, no bot token needed); the Mac checks the login again with its bot token.
Design and decisions: docs/project.html, the "Web app" section.
"""
import asyncio
import base64
import hmac
import itertools
import json
import os
import time
import urllib.parse
from pathlib import Path

from aiohttp import WSMsgType, web
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

PORT = int(os.environ.get("PULT_RELAY_PORT", "8097"))
SECRET = os.environ.get("PULT_RELAY_SECRET", "")
OWNER = int(os.environ.get("PULT_OWNER_ID", "0"))
BOT_ID = os.environ.get("PULT_BOT_ID", "")
WEB = Path(os.environ.get("PULT_WEB_DIR") or Path(__file__).resolve().parent / "web")
MAX_AGE = 24 * 3600        # initData older than a day is rejected: Telegram issues a fresh one on every open
MAX_CLIENTS = 6            # app windows at once: the owner's phone and maybe Telegram on the Mac
# Telegram's public key for checking initData without the bot token ("Validating data for Third-Party Use")
TG_PUBLIC = bytes.fromhex("e7bf03a2fa4602af4580703d88dda5bb59f32ed8b02a56c187fe7d34caed242d")


def log(*a):
    print(time.strftime("%Y-%m-%d %H:%M:%S"), *a, flush=True)


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
        self.inits = {}                     # cid → initData: when the Mac reconnects, it checks the login again
        self.ids = itertools.count(1)

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
        if len(self.clients) + len(self.pending) >= MAX_CLIENTS:
            await ws.close(code=4429, message=b"too many")
            return ws
        cid = next(self.ids)
        try:
            first = await ws.receive(timeout=15)
            hello = json.loads(first.data) if first.type == WSMsgType.TEXT else {}
            ok, owner, fresh, fields = check_init(hello.get("init"))
            if not (ok and owner and fresh):
                await ws.send_str(json.dumps({"t": "denied", "signature_ok": ok, "owner": owner, "fresh": fresh}))
                log("login rejected: signature %s, owner %s, fresh %s" % (ok, owner, fresh))
                return ws
            c = hello.get("client") or {}             # where the app is opened from; never the initData itself
            log("app window %d: %s %s" % (cid, str(c.get("platform"))[:20], str(c.get("version"))[:20]))
            self.pending[cid] = ws
            self.inits[cid] = hello.get("init")
            mac = await self.to_mac({"t": "open", "cid": cid, "init": hello.get("init")})
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
        except (asyncio.TimeoutError, ValueError, TypeError) as e:
            log("phone %d: %r" % (cid, e))
        finally:
            self.pending.pop(cid, None)
            self.clients.pop(cid, None)
            self.inits.pop(cid, None)
            await self.to_mac({"t": "close", "cid": cid})
        return ws

    # ----- Mac -----

    async def ws_agent(self, request):
        auth = request.headers.get("Authorization", "")
        if not SECRET or not hmac.compare_digest(auth, "Bearer " + SECRET):
            log("Mac: wrong secret from", request.remote)
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
            await self.to_mac({"t": "open", "cid": cid, "init": self.inits.get(cid)})
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
                        await cws.send_str(json.dumps({"t": "ready"}))
                    else:
                        await cws.send_str(json.dumps({"t": "denied", "by": "mac"}))
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
        # ?v= in links to app files is the latest modification time, so after a deploy Telegram drops stale copies
        files = [p for p in (WEB / "static").rglob("*") if p.is_file()]
        v = str(int(max((p.stat().st_mtime for p in files), default=0)))
        return web.Response(text=(WEB / "index.html").read_text().replace("{{v}}", v), content_type="text/html",
                            headers={"Cache-Control": "no-cache"})

    async def health(self, request):
        return web.json_response({"ok": True, "mac": self.mac is not None and not self.mac.closed,
                                  "clients": len(self.clients)})


def app():
    r = Relay()
    a = web.Application(client_max_size=64 * 1024)
    a.router.add_get("/pult/", r.index)
    a.router.add_get("/pult/healthz", r.health)
    a.router.add_get("/pult/ws", r.ws_client)
    a.router.add_get("/pult/agent", r.ws_agent)
    (WEB / "static").mkdir(parents=True, exist_ok=True)
    a.router.add_static("/pult/static/", WEB / "static", show_index=False)
    return a


if __name__ == "__main__":
    log("Pult relay: 127.0.0.1:%d, bot %s, owner %s, Mac %s" % (PORT, BOT_ID or "?", OWNER or "?",
                                                                          "by secret" if SECRET else "NO SECRET"))
    # restart on deploy is fast: don't wait for live WebSockets, the Mac and the windows reconnect by themselves
    web.run_app(app(), host="127.0.0.1", port=PORT, print=None, access_log=None, shutdown_timeout=2)
