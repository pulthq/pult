#!/usr/bin/env python3
"""Tests for the web app relay (relay/relay.py) without Telegram: Ed25519 signatures with our own key instead of
Telegram's, and the phone and the Mac are real WebSocket connections to a real relay.

  ~/.local/share/pult/venv/bin/python tests/test_relay.py      (needs aiohttp and cryptography)
"""
import asyncio
import base64
import hashlib
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.parse
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TMP = Path(tempfile.mkdtemp(prefix="pult-relay-test-"))
os.environ.update(PULT_RELAY_SECRET="s3cret", PULT_OWNER_ID="42", PULT_BOT_ID="777",
                  PULT_WEB_DIR=str(ROOT / "relay" / "web"))
sys.path.insert(0, str(ROOT / "relay"))

import aiohttp  # noqa: E402
from aiohttp.test_utils import TestServer  # noqa: E402
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey  # noqa: E402
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat  # noqa: E402

import relay  # noqa: E402

KEY = Ed25519PrivateKey.generate()
relay.TG_PUBLIC = KEY.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)


def init_data(uid=42, age=0, tamper=False, start="home"):
    """initData signed the way Telegram signs it for validation without the bot token."""
    fields = {"auth_date": str(int(time.time() - age)), "query_id": "AAA", "start_param": start,
              "user": json.dumps({"id": uid, "first_name": "D"})}
    dcs = "777:WebAppData\n" + "\n".join("%s=%s" % (k, fields[k]) for k in sorted(fields))
    sig = base64.urlsafe_b64encode(KEY.sign(dcs.encode())).decode().rstrip("=")
    if tamper:
        fields["user"] = json.dumps({"id": uid, "first_name": "X"})
    return urllib.parse.urlencode(dict(fields, signature=sig, hash="ab" * 32))


class RelayTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.srv = TestServer(relay.app())
        await self.srv.start_server()
        self.http = aiohttp.ClientSession()

    async def asyncTearDown(self):
        await self.http.close()
        await self.srv.close()

    def url(self, path):
        return str(self.srv.make_url(path))

    async def phone(self, init, resume=None, ip=None):
        ws = await self.http.ws_connect(self.url("/pult/ws"), headers={"X-Real-IP": ip} if ip else None)
        await ws.send_str(json.dumps({"t": "hello", "init": init, "resume": resume,
                                      "client": {"platform": "test", "version": "9"}}))
        return ws, json.loads((await ws.receive(timeout=5)).data)

    def test_check_init(self):
        self.assertEqual(relay.check_init(init_data())[:3], (True, True, True))
        self.assertEqual(relay.check_init(init_data(tamper=True))[:3], (False, True, True))   # forged
        self.assertEqual(relay.check_init(init_data(uid=5))[:3], (True, False, True))          # not the owner
        self.assertEqual(relay.check_init(init_data(age=2 * 86400))[:3], (True, True, True))   # the Mac decides
        self.assertEqual(relay.check_init(init_data(age=8 * 86400))[:3], (True, True, False))  # stale
        self.assertEqual(relay.check_init("")[:3], (False, False, False))

    async def test_page_and_health(self):
        async with self.http.get(self.url("/pult/")) as r:
            self.assertEqual(r.status, 200)
            page = await r.text()
            self.assertIn("<title>Pult</title>", page)
        # every module the app imports gets the deploy's ?v= through the import map, not only app.js
        imap = json.loads(page.split('<script type="importmap">')[1].split("</script>")[0])["imports"]
        v = page.split("app.js?v=")[1].split('"')[0]
        for name in ("i18n.js", "md.js", "app.js"):
            self.assertEqual(imap["/pult/static/" + name], "/pult/static/%s?v=%s" % (name, v))
        async with self.http.get(self.url("/pult/static/i18n.js")) as r:
            self.assertEqual((r.status, r.headers.get("Cache-Control")), (200, "no-cache"))
        async with self.http.get(self.url("/pult/healthz")) as r:
            self.assertEqual(await r.json(), {"ok": True, "mac": False})       # not how many windows are open
        # the page's CSP: scripts only from here, telegram.org and the import map by its hash; connections only here
        async with self.http.get(self.url("/pult/")) as r:
            policy = r.headers["Content-Security-Policy"]
        raw = page.split('<script type="importmap">')[1].split("</script>")[0]
        self.assertIn("'sha256-%s'" % base64.b64encode(hashlib.sha256(raw.encode()).digest()).decode(), policy)
        self.assertIn("script-src 'self' https://telegram.org ", policy)
        self.assertIn("connect-src 'self' wss://%s" % self.srv.make_url("/").host, policy)
        self.assertNotIn("unsafe-eval", policy)
        self.assertNotIn("wss://", relay.csp(raw, "evil.example\r\nX: y"))   # a strange Host header adds nothing

    async def test_strangers(self):
        # a stranger learns nothing about why; only the owner's own week-old window is told to reopen
        ws, m = await self.phone(init_data(tamper=True))
        self.assertEqual(m, {"t": "denied"})
        ws, m = await self.phone(init_data(uid=5))
        self.assertEqual(m, {"t": "denied"})
        ws, m = await self.phone(init_data(age=8 * 86400))
        self.assertEqual(m, {"t": "denied", "why": "expired"})
        with self.assertRaises(aiohttp.WSServerHandshakeError):
            await self.http.ws_connect(self.url("/pult/agent"), headers={"Authorization": "Bearer wrong"})
        self.assertNotIn("init", m)                                              # a refusal never echoes the login

    async def test_pipe(self):
        # the phone comes before the Mac and waits; the Mac connects, checks the login; then messages flow both ways
        ws, m = await self.phone(init_data())
        self.assertEqual((m["t"], m["mac"]), ("hello", False))
        mac = await self.http.ws_connect(self.url("/pult/agent"), headers={"Authorization": "Bearer s3cret"})
        self.assertEqual(json.loads((await ws.receive(timeout=5)).data), {"t": "mac", "on": True})
        opened = json.loads((await mac.receive(timeout=5)).data)
        self.assertEqual(opened["t"], "open")
        self.assertIn("signature=", opened["init"])                  # the Mac checks the login with its own bot token
        self.assertEqual((opened["client"], opened["resume"]), ({"platform": "test", "version": "9"}, None))
        cid = opened["cid"]
        # stage U2: what the server holds, as git blob ids by path in Pult's repository — the Mac finds the commit
        b, git = opened["build"], lambda f: subprocess.run(["git", "hash-object", str(ROOT / f)], capture_output=True,
                                                          text=True).stdout.strip()
        self.assertEqual((b["relay/relay.py"], b["relay/web/static/app.js"], b["relay/web/index.html"]),
                         (git("relay/relay.py"), git("relay/web/static/app.js"), git("relay/web/index.html")))
        self.assertFalse([k for k in b if "__pycache__" in k or k.endswith(".DS_Store")])
        await ws.send_str(json.dumps({"t": "req", "id": 1, "op": "overview"}))     # not forwarded before confirmation
        await mac.send_str(json.dumps({"t": "auth", "cid": cid, "ok": True}))
        self.assertEqual(json.loads((await ws.receive(timeout=5)).data), {"t": "ready"})
        await ws.send_str(json.dumps({"t": "req", "id": 2, "op": "overview"}))
        got = json.loads((await mac.receive(timeout=5)).data)
        self.assertEqual((got["id"], got["cid"]), (2, cid))
        await mac.send_str(json.dumps({"t": "res", "id": 2, "cid": cid, "data": {"ok": 1}}))
        self.assertEqual(json.loads((await ws.receive(timeout=5)).data), {"t": "res", "id": 2, "data": {"ok": 1}})
        await mac.send_str(json.dumps({"t": "event", "kind": "turn"}))              # no cid: goes to every window
        self.assertEqual(json.loads((await ws.receive(timeout=5)).data)["kind"], "turn")
        await ws.close()
        self.assertEqual(json.loads((await mac.receive(timeout=5)).data), {"t": "close", "cid": cid})
        await mac.close()

    async def test_mac_denies(self):
        mac = await self.http.ws_connect(self.url("/pult/agent"), headers={"Authorization": "Bearer s3cret"})
        ws, m = await self.phone(init_data())
        self.assertTrue(m["mac"])
        cid = json.loads((await mac.receive(timeout=5)).data)["cid"]
        await mac.send_str(json.dumps({"t": "auth", "cid": cid, "ok": False, "why": "expired"}))
        self.assertEqual(json.loads((await ws.receive(timeout=5)).data), {"t": "denied", "by": "mac", "why": "expired"})
        await mac.close()

    async def test_resume_key(self):
        # the window's key and address reach the Mac; the Mac's next key reaches the window and is what the relay
        # hands the Mac when the Mac reconnects (it restarted: the window logs in again without a fresh initData)
        mac = await self.http.ws_connect(self.url("/pult/agent"), headers={"Authorization": "Bearer s3cret"})
        ws, m = await self.phone(init_data(), resume="k1", ip="203.0.113.7")
        opened = json.loads((await mac.receive(timeout=5)).data)
        self.assertEqual((opened["resume"], opened["ip"]), ("k1", "203.0.113.7"))
        await mac.send_str(json.dumps({"t": "auth", "cid": opened["cid"], "ok": True, "resume": "k2"}))
        self.assertEqual(json.loads((await ws.receive(timeout=5)).data), {"t": "ready", "resume": "k2"})
        await mac.close()
        self.assertEqual(json.loads((await ws.receive(timeout=5)).data), {"t": "mac", "on": False})
        mac = await self.http.ws_connect(self.url("/pult/agent"), headers={"Authorization": "Bearer s3cret"})
        again = json.loads((await mac.receive(timeout=5)).data)
        self.assertEqual((again["t"], again["cid"], again["resume"]), ("open", opened["cid"], "k2"))
        # the owner logged out everywhere: the Mac closes the window
        await mac.send_str(json.dumps({"t": "auth", "cid": opened["cid"], "ok": True, "resume": "k3"}))
        while json.loads((await ws.receive(timeout=5)).data).get("t") != "ready":
            pass
        await mac.send_str(json.dumps({"t": "kick", "cid": opened["cid"], "why": "out"}))
        self.assertEqual(json.loads((await ws.receive(timeout=5)).data), {"t": "denied", "by": "mac", "why": "out"})
        self.assertEqual((await ws.receive(timeout=5)).type, aiohttp.WSMsgType.CLOSE)
        await mac.close()

    async def test_waiting_cap(self):
        # connections that don't say who they are: at most WAITING_PER_IP from one address hold a place
        held = [await self.http.ws_connect(self.url("/pult/ws"), headers={"X-Real-IP": "198.51.100.1"})
                for _ in range(relay.WAITING_PER_IP)]
        extra = await self.http.ws_connect(self.url("/pult/ws"), headers={"X-Real-IP": "198.51.100.1"})
        self.assertEqual((await extra.receive(timeout=5)).type, aiohttp.WSMsgType.CLOSE)
        self.assertEqual(extra.close_code, 4429)
        ws, m = await self.phone(init_data(), ip="198.51.100.2")                  # another address gets in
        self.assertEqual(m["t"], "hello")
        # behind a proxy that hides the client every phone is 127.0.0.1: only the overall limit applies
        local = [await self.http.ws_connect(self.url("/pult/ws"), headers={"X-Real-IP": "127.0.0.1"})
                 for _ in range(relay.WAITING_PER_IP)]
        w2, m = await self.phone(init_data(), ip="127.0.0.1")
        self.assertEqual(m["t"], "hello")
        self.assertFalse(relay.known("::1") or relay.known("") or relay.known("garbage"))
        for h in held + local + [ws, w2]:
            await h.close()

    @unittest.skipIf(os.name == "nt", "the relay runs on a Linux server; Windows has no unix sockets in Python")
    async def test_unix_socket(self):
        """PULT_RELAY_SOCKET: the relay listens on a socket, a socket left by a crash is replaced, other files stay."""
        self.assertEqual(relay.listen(), {"host": "127.0.0.1", "port": relay.PORT})
        path = TMP / "relay.sock"
        s = socket.socket(socket.AF_UNIX)
        s.bind(str(path))                              # a socket left behind by a crash
        s.close()
        relay.SOCKET = str(path)
        try:
            where = relay.listen()
            self.assertEqual(where, {"path": str(path)})
            self.assertFalse(path.exists())
            runner = aiohttp.web.AppRunner(relay.app())
            await runner.setup()
            await aiohttp.web.UnixSite(runner, where["path"]).start()
            async with aiohttp.ClientSession(connector=aiohttp.UnixConnector(path=str(path))) as http:
                async with http.get("http://relay/pult/healthz") as r:
                    self.assertEqual((await r.json())["ok"], True)
            await runner.cleanup()
            path.unlink(missing_ok=True)
            path.write_text("not a socket")
            relay.listen()
            self.assertEqual(path.read_text(), "not a socket")
        finally:
            relay.SOCKET = ""
            path.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main(verbosity=1)
