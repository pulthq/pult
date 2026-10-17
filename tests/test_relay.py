#!/usr/bin/env python3
"""Tests for the web app relay (relay/relay.py) without Telegram: Ed25519 signatures with our own key instead of
Telegram's, and the phone and the Mac are real WebSocket connections to a real relay.

  ~/.local/share/pult/venv/bin/python tests/test_relay.py      (needs aiohttp and cryptography)
"""
import asyncio
import base64
import json
import os
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

    async def phone(self, init):
        ws = await self.http.ws_connect(self.url("/pult/ws"))
        await ws.send_str(json.dumps({"t": "hello", "init": init, "client": {"platform": "test", "version": "9"}}))
        return ws, json.loads((await ws.receive(timeout=5)).data)

    def test_check_init(self):
        self.assertEqual(relay.check_init(init_data())[:3], (True, True, True))
        self.assertEqual(relay.check_init(init_data(tamper=True))[:3], (False, True, True))   # forged
        self.assertEqual(relay.check_init(init_data(uid=5))[:3], (True, False, True))          # not the owner
        self.assertEqual(relay.check_init(init_data(age=2 * 86400))[:3], (True, True, False))  # stale
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
            self.assertEqual((await r.json())["mac"], False)

    async def test_strangers(self):
        ws, m = await self.phone(init_data(tamper=True))
        self.assertEqual(m["t"], "denied")
        self.assertFalse(m["signature_ok"])
        ws, m = await self.phone(init_data(uid=5))
        self.assertEqual((m["t"], m["owner"]), ("denied", False))
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
        cid = opened["cid"]
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
        await mac.send_str(json.dumps({"t": "auth", "cid": cid, "ok": False}))
        self.assertEqual(json.loads((await ws.receive(timeout=5)).data), {"t": "denied", "by": "mac"})
        await mac.close()


if __name__ == "__main__":
    unittest.main(verbosity=1)
