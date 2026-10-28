#!/usr/bin/env python3
"""Tests for the web app relay (relay/relay.py) without Telegram: Ed25519 signatures with our own key instead of
Telegram's, and the phone and the Mac are real WebSocket connections to a real relay.

  ~/.local/share/pult/venv/bin/python tests/test_relay.py      (needs aiohttp and cryptography)
"""
import asyncio
import atexit
import base64
import hashlib
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import types
import unittest
import urllib.parse
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
TMP = Path(tempfile.mkdtemp(prefix="pult-relay-test-"))
atexit.register(shutil.rmtree, TMP, True)
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

    async def agent(self):
        """The Mac connects; the relay's first word is its hello (stage U3): whether it has the updater, its report, the
        files it holds."""
        mac = await self.http.ws_connect(self.url("/pult/agent"), headers={"Authorization": "Bearer s3cret"})
        hello = json.loads((await mac.receive(timeout=5)).data)
        self.assertEqual(hello["t"], "relay")
        return mac, hello

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

    def test_client_ip(self):
        # the phone's address as the web server saw it: nginx's X-Real-IP, else the last X-Forwarded-For hop — the one
        # Caddy appends; what comes before it the client wrote itself (review 2026-10-27, Т7)
        req = lambda h, remote="10.0.0.1": types.SimpleNamespace(headers=h, remote=remote)
        self.assertEqual(relay.client_ip(req({"X-Real-IP": " 203.0.113.9 ", "X-Forwarded-For": "1.1.1.1"})), "203.0.113.9")
        self.assertEqual(relay.client_ip(req({"X-Forwarded-For": "6.6.6.6, 198.51.100.7"})), "198.51.100.7")
        self.assertEqual(relay.client_ip(req({})), "10.0.0.1")
        self.assertEqual(relay.client_ip(req({}, None)), "")

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
        mac, hello = await self.agent()
        self.assertEqual((hello["can"], hello["upd"]), ([], None))                # no updater on this server
        self.assertEqual(hello["build"]["relay/relay.py"], relay.build()["relay/relay.py"])
        self.assertEqual(json.loads((await ws.receive(timeout=5)).data), {"t": "mac", "on": True})
        opened = json.loads((await mac.receive(timeout=5)).data)
        self.assertEqual(opened["t"], "open")
        self.assertIn("signature=", opened["init"])                  # the Mac checks the login with its own bot token
        self.assertEqual((opened["client"], opened["resume"]), ({"platform": "test", "version": "9"}, None))
        cid = opened["cid"]
        # stage U2: what the server holds, as git blob ids by path in Pult's repository — the Mac finds the commit
        # --no-filters: the bytes as they lie, as the relay reads them (Git for Windows would turn CRLF into LF first)
        b, git = opened["build"], lambda f: subprocess.run(["git", "hash-object", "--no-filters", str(ROOT / f)],
                                                          capture_output=True, text=True).stdout.strip()
        self.assertEqual((b["relay/relay.py"], b["relay/web/static/app.js"], b["relay/web/index.html"]),
                         (git("relay/relay.py"), git("relay/web/static/app.js"), git("relay/web/index.html")))
        self.assertFalse([k for k in b if "__pycache__" in k or k.endswith(".DS_Store")])
        await ws.send_str(json.dumps({"t": "req", "id": 1, "op": "overview"}))     # not forwarded before confirmation
        await mac.send_str(json.dumps({"t": "auth", "cid": cid, "ok": True}))
        self.assertEqual(json.loads((await ws.receive(timeout=5)).data), {"t": "ready"})
        # a window only asks: anything but a request stays at the relay — a window can't speak for it to the Mac
        # (a login of its own with a made-up address, an updater's report; review 2026-10-27, Б2)
        for odd in ({"t": "open", "init": "x", "ip": "203.0.113.9"}, {"t": "relay", "upd": {"state": "done"}},
                    {"t": "close"}, {"t": "auth", "ok": True}, [1], "req"):
            await ws.send_str(json.dumps(odd))
        await ws.send_str(json.dumps({"t": "req", "id": 2, "op": "overview"}))
        got = json.loads((await mac.receive(timeout=5)).data)
        self.assertEqual((got["t"], got["id"], got["cid"]), ("req", 2, cid))           # the first the Mac hears
        await mac.send_str(json.dumps({"t": "res", "id": 2, "cid": cid, "data": {"ok": 1}}))
        self.assertEqual(json.loads((await ws.receive(timeout=5)).data), {"t": "res", "id": 2, "data": {"ok": 1}})
        await mac.send_str(json.dumps({"t": "event", "kind": "turn"}))              # no cid: goes to every window
        self.assertEqual(json.loads((await ws.receive(timeout=5)).data)["kind"], "turn")
        await ws.close()
        self.assertEqual(json.loads((await mac.receive(timeout=5)).data), {"t": "close", "cid": cid})
        await mac.close()

    async def test_mac_denies(self):
        mac, _ = await self.agent()
        ws, m = await self.phone(init_data())
        self.assertTrue(m["mac"])
        cid = json.loads((await mac.receive(timeout=5)).data)["cid"]
        await mac.send_str(json.dumps({"t": "auth", "cid": cid, "ok": False, "why": "expired"}))
        self.assertEqual(json.loads((await ws.receive(timeout=5)).data), {"t": "denied", "by": "mac", "why": "expired"})
        await mac.close()

    async def test_resume_key(self):
        # the window's key and address reach the Mac; the Mac's next key reaches the window and is what the relay
        # hands the Mac when the Mac reconnects (it restarted: the window logs in again without a fresh initData)
        mac, _ = await self.agent()
        ws, m = await self.phone(init_data(), resume="k1", ip="203.0.113.7")
        opened = json.loads((await mac.receive(timeout=5)).data)
        self.assertEqual((opened["resume"], opened["ip"]), ("k1", "203.0.113.7"))
        await mac.send_str(json.dumps({"t": "auth", "cid": opened["cid"], "ok": True, "resume": "k2"}))
        self.assertEqual(json.loads((await ws.receive(timeout=5)).data), {"t": "ready", "resume": "k2"})
        await mac.close()
        # the window hears that the Mac went away, and since when (0.18.5) — in seconds, no clocks to compare
        self.assertEqual(json.loads((await ws.receive(timeout=5)).data), {"t": "mac", "on": False, "away": 0})
        late, h = await self.phone(init_data())                         # a window opened while the Mac is away
        self.assertEqual((h["t"], h["mac"], type(h.get("away"))), ("hello", False, int))
        await late.close()
        mac, _ = await self.agent()
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
                 for _ in range(relay.WAITING_MAX - relay.WAITING_PER_IP - 1)]
        w2, m = await self.phone(init_data(), ip="127.0.0.1")
        self.assertEqual(m["t"], "hello")
        # and no more than WAITING_MAX wait in all: each may bring a frame of up to 8 MB (review 2026-10-27, Б6)
        local.append(await self.http.ws_connect(self.url("/pult/ws"), headers={"X-Real-IP": "127.0.0.1"}))
        over = await self.http.ws_connect(self.url("/pult/ws"), headers={"X-Real-IP": "127.0.0.1"})
        self.assertEqual(((await over.receive(timeout=5)).type, over.close_code), (aiohttp.WSMsgType.CLOSE, 4429))
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


class RelayUpdaterTest(unittest.IsolatedAsyncioTestCase):
    """Stage U3, the relay's part: the computer's release goes to want.json (right form only, not too often), never to
    the windows; the updater's report goes to the computer."""

    async def asyncSetUp(self):
        self.dir = Path(tempfile.mkdtemp(prefix="pult-relay-state-", dir=TMP))
        self.status = self.dir / "status.json"
        self.keep = (relay.STATE, relay.UPDATER, relay.STATUS_EVERY)
        relay.STATE, relay.UPDATER, relay.STATUS_EVERY = str(self.dir), str(self.status), 0.2
        self.srv = TestServer(relay.app())
        await self.srv.start_server()
        self.http = aiohttp.ClientSession()

    async def asyncTearDown(self):
        await self.http.close()
        await self.srv.close()
        relay.STATE, relay.UPDATER, relay.STATUS_EVERY = self.keep

    def test_want_form_and_pace(self):
        r, sha = relay.Relay(), "a" * 40
        self.assertFalse(r.want({"tag": "v0.18.0", "commit": "abc"}, now=1000))            # not a commit
        self.assertFalse(r.want({"tag": "0.18.0", "commit": sha}, now=1000))               # not a tag
        self.assertFalse(r.want({"tag": "v0.18.0; rm -rf /", "commit": sha}, now=1000))
        self.assertFalse(r.want({"tag": ["v0.18.0"], "commit": sha}, now=1000))
        self.assertFalse((self.dir / "want.json").exists())
        self.assertTrue(r.want({"tag": "v0.18.0", "commit": sha, "extra": "x"}, now=1000))
        self.assertEqual(json.loads((self.dir / "want.json").read_text()), {"tag": "v0.18.0", "commit": sha, "ts": 1000})
        self.assertFalse(r.want({"tag": "v0.18.1", "commit": "b" * 40}, now=1005))         # too soon after the last
        self.assertTrue(r.want({"tag": "v0.18.1", "commit": "b" * 40}, now=1011))
        self.assertFalse(r.want({"tag": "v0.18.1", "commit": "b" * 40}, now=1100))         # the same one: later
        self.assertTrue(r.want({"tag": "v0.18.1", "commit": "b" * 40}, now=1011 + relay.WANT_REFRESH))
        # the owner's "try again": the same one at once (still not more often than WANT_EVERY), with this server's clock
        later = 1011 + relay.WANT_REFRESH + 20
        self.assertFalse(r.want({"tag": "v0.18.1", "commit": "b" * 40, "retry": "yes"}, now=later))   # only True counts
        self.assertTrue(r.want({"tag": "v0.18.1", "commit": "b" * 40, "retry": True}, now=later))
        self.assertEqual(json.loads((self.dir / "want.json").read_text())["retry"], later)
        relay.STATE = ""
        self.assertFalse(relay.Relay().want({"tag": "v0.18.0", "commit": sha}, now=1))      # no updater here

    def test_status_fields(self):
        self.assertIsNone(relay.updater_status())
        self.status.write_text(json.dumps({"state": "done", "tag": "v0.18.1", "have": "v0.18.1", "ts": 5, "back": False,
                                           "detail": "x" * 1000, "token": "secret", "why": None}))
        st = relay.updater_status()
        self.assertEqual((st["state"], st["tag"], st["ts"], st["back"], len(st["detail"])), ("done", "v0.18.1", 5, False, 300))
        self.assertNotIn("token", st)
        # the updater's own files (0.18.6): blob ids or None pass, anything else stays here
        self.status.write_text(json.dumps({"state": "done", "self": {"deploy/relay/update.py": "a" * 40, "deploy/relay/x": None,
                                                                     "deploy/relay/y": "not a blob", "z": 7}}))
        self.assertEqual(relay.updater_status()["self"], {"deploy/relay/update.py": "a" * 40, "deploy/relay/x": None})
        self.status.write_text("[1, 2]")
        self.assertIsNone(relay.updater_status())

    async def test_hello_want_report(self):
        self.status.write_text(json.dumps({"state": "idle", "have": "v0.18.0", "ts": 1}))
        mac = await self.http.ws_connect(str(self.srv.make_url("/pult/agent")), headers={"Authorization": "Bearer s3cret"})
        hello = json.loads((await mac.receive(timeout=5)).data)
        self.assertEqual((hello["t"], hello["can"], hello["upd"]), ("relay", ["want"], {"state": "idle", "have": "v0.18.0", "ts": 1}))
        ws = await self.http.ws_connect(str(self.srv.make_url("/pult/ws")))
        await ws.send_str(json.dumps({"t": "hello", "init": init_data()}))
        self.assertEqual(json.loads((await ws.receive(timeout=5)).data)["t"], "hello")
        cid = json.loads((await mac.receive(timeout=5)).data)["cid"]
        await mac.send_str(json.dumps({"t": "auth", "cid": cid, "ok": True}))
        self.assertEqual(json.loads((await ws.receive(timeout=5)).data), {"t": "ready"})
        await mac.send_str(json.dumps({"t": "want", "tag": "v0.18.1", "commit": "c" * 40}))
        for _ in range(50):
            if (self.dir / "want.json").exists():
                break
            await asyncio.sleep(0.05)
        self.assertEqual(json.loads((self.dir / "want.json").read_text())["tag"], "v0.18.1")
        # the updater reports: the Mac hears it; the window heard nothing of the want nor of the report
        self.status.write_text(json.dumps({"state": "run", "step": "fetch", "tag": "v0.18.1", "have": "v0.18.0", "ts": 2}))
        got = json.loads((await mac.receive(timeout=5)).data)
        self.assertEqual((got["t"], got["upd"]["state"], got["upd"]["step"]), ("relay", "run", "fetch"))
        with self.assertRaises(asyncio.TimeoutError):
            await ws.receive(timeout=0.5)
        await ws.close()
        await mac.close()


def git(cwd, *args, env=None):
    p = subprocess.run(["git", "-C", str(cwd), "-c", "user.name=t", "-c", "user.email=t@t", *args], capture_output=True,
                       text=True, env=dict(os.environ, GIT_TERMINAL_PROMPT="0", **(env or {})))
    if p.returncode:
        raise AssertionError("git %s: %s" % (" ".join(args), p.stderr))
    return p.stdout.strip()


@unittest.skipIf(os.name == "nt", "the updater runs on a Linux server")
class UpdaterTest(unittest.TestCase):
    """Stage U3, the server's updater (deploy/relay/update.py) with real git: a repository of our own stands for
    github.com/pulthq/pult; systemd and the relay's health are made up."""

    @classmethod
    def setUpClass(cls):
        import importlib.util
        spec = importlib.util.spec_from_file_location("pult_relay_update", ROOT / "deploy" / "relay" / "update.py")
        cls.M = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.M)
        # "GitHub": three releases in main, one tag beside it, a file outside relay/ the updater must not fetch
        o = cls.origin = Path(tempfile.mkdtemp(prefix="pult-gh-", dir=TMP))
        git(o, "init", "-q", "-b", "main")
        git(o, "config", "uploadpack.allowFilter", "true")
        git(o, "config", "uploadpack.allowAnySHA1InWant", "true")
        cls.shas = {}

        def release(tag, relay_py, reqs="aiohttp>=3.10\n", app="// app\n"):
            (o / "relay" / "web" / "static").mkdir(parents=True, exist_ok=True)
            (o / "relay" / "relay.py").write_text(relay_py)
            (o / "relay" / "requirements.txt").write_text(reqs)
            (o / "relay" / "web" / "index.html").write_text("<title>Pult</title>\n")
            (o / "relay" / "web" / "static" / "app.js").write_text(app)
            (o / "media").mkdir(exist_ok=True)
            (o / "media" / "big.bin").write_bytes(os.urandom(64 * 1024))       # outside relay/
            git(o, "add", "-A")
            git(o, "commit", "-q", "-m", "Pult " + tag)
            git(o, "tag", "-a", tag, "-m", tag)
            cls.shas[tag] = git(o, "rev-parse", "HEAD")
        release("v0.18.0", "print('v0.18.0')\n")
        release("v0.18.1", "print('v0.18.1')\n", app="// app 1\n")
        release("v0.18.2", "print('v0.18.2')\n", reqs="aiohttp>=3.11\n")
        git(o, "checkout", "-q", "-b", "side")
        release("v0.18.3", "print('side')\n")                                # a tag, but not in main
        git(o, "checkout", "-q", "main")

    def setUp(self):
        M = self.M
        d = Path(tempfile.mkdtemp(prefix="pult-upd-", dir=TMP))
        M.HOME, M.APP, M.VENV, M.WANT = d / "home", d / "app", d / "venv", d / "state" / "want.json"
        M.REPO, M.MAC_WAIT, M.UP_WAIT = str(self.origin), 3, 5
        for p in (M.HOME, M.APP / "releases", M.VENV / "bin", M.WANT.parent):
            p.mkdir(parents=True)
        pip = M.VENV / "bin" / "pip"            # records what it was asked to install
        pip.write_text("#!/bin/sh\necho \"$@\" >> %s\n" % (d / "pip.log"))
        pip.chmod(0o755)
        self.pip_log = d / "pip.log"
        # what install.sh left: v0.18.0 runs
        first = M.APP / "releases" / ("v0.18.0-" + self.shas["v0.18.0"][:7])
        (first / "web").mkdir(parents=True)
        (first / "relay.py").write_text("print('v0.18.0')\n")
        (first / "requirements.txt").write_text("aiohttp>=3.10\n")
        os.symlink(os.path.relpath(first, M.APP), M.APP / "current")
        (M.HOME / "installed.json").write_text(json.dumps({"tag": "v0.18.0", "commit": self.shas["v0.18.0"]}))
        self.first = first

    def updater(self, bad=(), mac=True, loops=()):
        """An updater whose relay comes up unless `current` is one of the `bad` releases."""
        M = self.M
        test = self

        class Fake(M.Updater):
            pid = 100
            clock = 0.0

            def service(self):
                # systemd takes a restart a moment after the file changes: the first look still sees the relay before
                # it; a restart asked for starts the count of restarts anew; a release in `loops` exits at start, and
                # systemd restarts it again and again
                if test.pending:
                    test.pending = False
                    before = {"pid": Fake.pid, "state": "active", "restarts": test.n}
                    Fake.pid += 1
                    test.n, test.running = 0, M.APP.joinpath("current").resolve().name
                    return before
                if any(test.running.startswith(b) for b in test.loops):
                    test.n += 1
                return {"pid": Fake.pid, "state": "active", "restarts": test.n}

            def restart(self):
                test.pending = True
                test.restarts.append(M.APP.joinpath("current").resolve().name)

            def health(self):
                cur = M.APP.joinpath("current").resolve().name
                return None if any(cur.startswith(b) for b in bad) else {"ok": True, "mac": mac}

            def sleep(self, s):
                Fake.clock += s

            def now(self):
                return Fake.clock
        self.restarts, self.loops, self.pending, self.n = [], loops, False, 0
        self.running = M.APP.joinpath("current").resolve().name
        return Fake()

    def want(self, tag, commit=None):
        self.M.WANT.write_text(json.dumps({"tag": tag, "commit": commit or self.shas[tag], "ts": 1}))

    def status(self):
        return json.loads((self.M.HOME / "status.json").read_text())

    def test_takes_the_release_from_github(self):
        M, u = self.M, self.updater()
        self.want("v0.18.1")
        self.assertEqual(u.run(), 0)
        st = self.status()
        self.assertEqual((st["state"], st["have"], st["from"]), ("done", "v0.18.1", "v0.18.0"))
        cur = (M.APP / "current").resolve()
        self.assertEqual(cur.name, "v0.18.1-" + self.shas["v0.18.1"][:7])
        self.assertEqual(os.readlink(M.APP / "current"), "releases/" + cur.name)        # relative: the folder may move
        self.assertEqual((cur / "relay.py").read_text(), "print('v0.18.1')\n")
        self.assertEqual((cur / "web" / "static" / "app.js").read_text(), "// app 1\n")
        self.assertEqual(sorted(p.name for p in (M.APP / "releases").iterdir()), sorted([cur.name, self.first.name]))
        self.assertEqual(json.loads((M.HOME / "installed.json").read_text())["commit"], self.shas["v0.18.1"])
        self.assertEqual(self.restarts, [cur.name])
        self.assertFalse(self.pip_log.exists())                    # the same requirements: no pip
        # only the relay's files came: the one outside relay/ is not in the cache
        blob = git(self.origin, "rev-parse", "v0.18.1:media/big.bin")
        p = subprocess.run(["git", "--git-dir", str(M.HOME / "cache.git"), "cat-file", "-e", blob],
                           capture_output=True, env=dict(os.environ, GIT_NO_LAZY_FETCH="1"))
        self.assertNotEqual(p.returncode, 0)
        # the next release asks for other requirements: pip with them; the release before the last goes away
        self.want("v0.18.2")
        u.run()
        self.assertEqual(self.status()["state"], "done")
        self.assertIn("requirements.txt", self.pip_log.read_text())
        self.assertEqual(len(list((M.APP / "releases").iterdir())), 2)
        self.assertNotIn(self.first.name, [p.name for p in (M.APP / "releases").iterdir()])

    def test_only_official_and_never_back(self):
        M, u = self.M, self.updater()
        before = (M.APP / "current").resolve()
        for tag, commit, why in (("v0.18.1", self.shas["v0.18.2"], "not_official"),     # the tag is another commit
                                 ("v0.18.3", None, "not_official"),                     # not in main
                                 ("v0.19.0", "d" * 40, "not_official")):                # no such release
            self.want(tag, commit)
            u.run()
            st = self.status()
            self.assertEqual((st["state"], st["why"]), ("refused", why), tag)
            self.assertEqual((M.APP / "current").resolve(), before)
        self.want("v0.18.2")
        u.run()
        self.want("v0.18.1")                                          # older than what runs now
        u.run()
        self.assertEqual((self.status()["state"], self.status()["why"]), ("refused", "older"))
        self.assertTrue((M.APP / "current").resolve().name.startswith("v0.18.2"))
        self.want("v0.18.2")                                          # what runs: nothing to do
        u.run()
        self.assertEqual(self.status()["state"], "idle")

    def test_back_when_it_does_not_come_up(self):
        M, u = self.M, self.updater(bad=("v0.18.1",))
        self.want("v0.18.1")
        u.run()
        st = self.status()
        self.assertEqual((st["state"], st["why"], st["back"], st["back_ok"]), ("fail", "no_start", True, True))
        self.assertEqual((M.APP / "current").resolve(), self.first.resolve())
        self.assertEqual(json.loads((M.HOME / "installed.json").read_text())["tag"], "v0.18.0")
        self.assertEqual(len(self.restarts), 2)                       # there and back
        u.run()                                                       # the same release again: not tried
        self.assertEqual(len(self.restarts), 2)
        self.assertEqual(self.status()["state"], "fail")
        self.want("v0.18.2")                                          # a newer one is
        u.run()
        self.assertEqual(self.status()["state"], "done")

    def test_back_at_once_when_it_keeps_exiting(self):
        # systemd restarts a relay that exits at start again and again: no need to wait the full minute and a half
        M, u = self.M, self.updater(bad=("v0.18.1",), loops=("v0.18.1",))
        self.want("v0.18.1")
        u.run()
        st = self.status()
        # and going back counts as fine: the count of the release that failed doesn't hold against the old one
        self.assertEqual((st["state"], st["why"], st["back"], st["back_ok"]), ("fail", "no_start", True, True))
        self.assertIn("systemd restarted it", st["detail"])
        self.assertLess(type(u).clock, 5)
        self.assertEqual((M.APP / "current").resolve(), self.first.resolve())

    def test_its_own_looks(self):
        # what the other tests stand in for (review 2026-10-27, Т7): `systemctl show` read field by field, the relay's
        # healthz over TCP and over a Unix socket, a second run waits for the first, want.json changed on the way
        M = self.M
        u = M.Updater()
        with mock.patch.object(M.subprocess, "run", lambda *a, **k: types.SimpleNamespace(stdout="MainPID=123\nActiveState=active\nNRestarts=2\n")):
            self.assertEqual(u.service(), {"pid": 123, "state": "active", "restarts": 2})
        with mock.patch.object(M.subprocess, "run", lambda *a, **k: types.SimpleNamespace(stdout="MainPID=\nActiveState=failed\njunk\n")):
            self.assertEqual(u.service(), {"pid": 0, "state": "failed", "restarts": 0})
        with mock.patch.object(M.subprocess, "run", mock.Mock(side_effect=OSError("no systemctl"))):
            self.assertEqual(u.service(), {})
        import http.server
        import socketserver
        answer = {"code": 200, "body": b'{"ok": true, "mac": false}'}

        class H(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(answer["code"])
                self.send_header("Content-Length", str(len(answer["body"])))
                self.end_headers()
                self.wfile.write(answer["body"])

            def address_string(self):
                return "local"

            def log_message(self, *a):
                pass
        srv = http.server.HTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        sock = str(Path(tempfile.mkdtemp(prefix="pult-sock-", dir="/tmp")) / "relay.sock")      # a short path: sun_path

        class U(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
            daemon_threads = True
        usrv = U(sock, H)
        threading.Thread(target=usrv.serve_forever, daemon=True).start()
        try:
            for where in ("http://127.0.0.1:%d/pult/healthz" % srv.server_address[1], "unix:" + sock):
                with mock.patch.object(M, "HEALTH", where):
                    answer.update(code=200, body=b'{"ok": true, "mac": false}')
                    self.assertEqual(u.health(), {"ok": True, "mac": False}, where)
                    answer.update(code=502)
                    self.assertIsNone(u.health(), where)
                    answer.update(code=200, body=b"<html>")
                    self.assertIsNone(u.health(), where)
        finally:
            srv.shutdown()
            srv.server_close()
            usrv.shutdown()
            usrv.server_close()
            shutil.rmtree(Path(sock).parent, ignore_errors=True)
        with mock.patch.object(M, "HEALTH", "http://127.0.0.1:%d/pult/healthz" % srv.server_address[1]):
            self.assertIsNone(u.health())                                  # nobody there
        # a second run while the lock is taken — another run, or install.sh to its end: it waits its turn, then looks
        # (it left at once, and a want.json the relay wrote meanwhile went unread — a live server, 2026-10-28)
        import fcntl
        seen, naps = [], []
        u.once = lambda: seen.append("once") or {}
        held = open(M.HOME / "lock", "w")
        fcntl.flock(held, fcntl.LOCK_EX)

        def nap(s):
            naps.append(s)
            if len(naps) == 3:
                held.close()                         # the other one is done
        u.sleep = nap
        self.assertEqual(u.run(), 0)
        self.assertEqual(len(naps), 3)
        self.assertIn("once", seen)
        del u.sleep
        # taken for good: it gives up after LOCK_WAIT (on a clock of its own here) and leaves want.json for its next change
        seen.clear()
        clock = [0.0]
        u.now, u.sleep = (lambda: clock[0]), (lambda s: clock.__setitem__(0, clock[0] + s))
        with open(M.HOME / "lock", "w") as held:
            fcntl.flock(held, fcntl.LOCK_EX)
            self.assertEqual(u.run(), 0)
            self.assertEqual(seen, [])
            self.assertGreaterEqual(clock[0], M.LOCK_WAIT)
        del u.now, u.sleep
        # want.json changed while it ran: one more look; it keeps changing — at most ROUNDS
        self.want("v0.18.1")

        def once():
            seen.append("once")
            w = json.loads(M.WANT.read_text())
            if len(seen) == 1:
                self.want("v0.18.2")
            return w
        u.once = once
        self.assertEqual(u.run(), 0)
        self.assertEqual(len(seen), 2)
        seen.clear()

        def restless():
            seen.append("once")
            w = json.loads(M.WANT.read_text())
            M.WANT.write_text(json.dumps(dict(w, ts=w["ts"] + 1)))
            return w
        u.once = restless
        u.run()
        self.assertEqual(len(seen), M.ROUNDS)

    def test_its_own_files(self):
        # every report says which updater and services this server has — git's blob ids, as the computer's clone
        # has them for the release — so a release that changed them can say install.sh is due (review 2026-10-27, У5)
        M = self.M
        units = Path(tempfile.mkdtemp(prefix="pult-units-", dir=TMP))
        (units / "pult-relay.service").write_text("[Unit]\n")
        with mock.patch.object(M, "UNITS", units), mock.patch.dict(M.OWN, {
                "deploy/relay/pult-relay.service": units / "pult-relay.service",
                "deploy/relay/pult-relay-update.path": units / "pult-relay-update.path"}):
            own = M.own_files()
            u = self.updater()
            u.status(state="idle", have="v0.18.0")
        self.assertEqual(own["deploy/relay/pult-relay.service"], git(units, "hash-object", str(units / "pult-relay.service")))
        self.assertEqual(own["deploy/relay/update.py"], git(ROOT, "hash-object", str(ROOT / "deploy" / "relay" / "update.py")))
        self.assertIsNone(own["deploy/relay/pult-relay-update.path"])
        self.assertEqual(sorted(own), sorted(M.OWN))
        self.assertEqual(self.status()["self"], own)

    def test_computer_away_after_the_switch(self):
        # the computer didn't come back in the minute and a half after the switch (asleep, its network blinked) — not
        # surely the release's fault: tried again on the computer's next word, NO_MAC_TRIES times in all, then failed
        # here for good; the owner's "try again" (stamped by the relay) starts the count anew (0.18.5)
        M = self.M
        first = self.first.resolve()

        def look(extra=None, back=True):
            u = self.updater()
            u.health = lambda: {"ok": True, "mac": not back or M.APP.joinpath("current").resolve() == first}
            M.WANT.write_text(json.dumps(dict({"tag": "v0.18.1", "commit": self.shas["v0.18.1"], "ts": 1}, **(extra or {}))))
            u.run()
            return self.status()
        for _ in range(M.NO_MAC_TRIES - 1):
            st = look()
            self.assertEqual((st["state"], st["why"], st["back"], st["back_ok"]), ("fail", "no_mac_retry", True, True))
        self.assertEqual(look()["why"], "no_mac")                       # the last try: failed here
        self.assertEqual((M.APP / "current").resolve(), first)
        look()                                                          # the same word again: not tried
        self.assertEqual(self.restarts, [])
        st = look({"retry": 10 ** 9})                                   # the owner asks: tried anew, counted anew
        self.assertEqual(st["why"], "no_mac_retry")
        st = look(back=False)                                           # the computer is back this time
        self.assertEqual((st["state"], st["tag"]), ("done", "v0.18.1"))
        self.assertEqual(json.loads((M.HOME / "installed.json").read_text())["tag"], "v0.18.1")
        # a failure written before 0.18.5 (the reason alone) still counts as final
        (M.HOME / "failed.json").write_text(json.dumps({"v0.18.2 %s" % self.shas["v0.18.2"]: "no_start"}))
        u = self.updater()
        self.want("v0.18.2")
        u.run()
        self.assertEqual(self.restarts, [])

    def test_no_computer_no_network(self):
        M = self.M
        u = self.updater(mac=False)                                   # the computer isn't connected: later
        self.want("v0.18.1")
        u.run()
        st = self.status()
        self.assertEqual((st["state"], st["why"], st["back"]), ("fail", "no_mac_before", False))
        self.assertEqual((M.APP / "current").resolve(), self.first.resolve())
        self.assertFalse((M.HOME / "failed.json").exists())          # tried again on the next word
        M.REPO = str(self.origin) + "-gone"
        (M.HOME / "status.json").unlink()
        import shutil
        shutil.rmtree(M.HOME / "cache.git")
        self.updater().run()
        self.assertEqual((self.status()["state"], self.status()["why"]), ("fail", "network"))
        self.assertFalse((M.HOME / "failed.json").exists())

    def test_its_report_follows_its_own_files(self):
        # install.sh put in another updater or services, and the report still named the old ones: Settings kept asking
        # for install.sh after it ran, until the next release (a live server, 2026-10-28). The next run names those that
        # run now — the rest of the report as it was, its time too: the computer tells each report once, by its time
        M = self.M
        self.updater().run()                                          # no word from the computer yet: no report
        self.assertFalse((M.HOME / "status.json").exists())
        old = {"state": "done", "tag": "v0.18.0", "commit": self.shas["v0.18.0"], "have": "v0.18.0", "ts": 7,
               "self": dict.fromkeys(M.OWN, "0" * 40)}
        M.write(M.HOME / "status.json", old)
        self.want("v0.18.0")
        self.updater().run()
        st = self.status()
        self.assertEqual(st["self"], M.own_files())
        self.assertEqual(dict(st, self=None), dict(old, self=None))
        text = (M.HOME / "status.json").read_text()
        self.updater().run()                                          # nothing changed since: the report stays
        self.assertEqual((M.HOME / "status.json").read_text(), text)

    def test_it_enters_the_relays_socket(self):
        # on a socket the relay's /run/pult-relay lets in only the relay's group, and the updater asks there whether the
        # relay is up and the computer connected: outside the group it never heard, and refused every release with "the
        # computer isn't connected" (a live server, 2026-10-28)
        def unit(name):
            text = (ROOT / "deploy" / "relay" / name).read_text(encoding="utf-8")
            return dict(ln.split("=", 1) for ln in text.splitlines() if "=" in ln and not ln.startswith("#"))
        relay_unit, upd = unit("pult-relay.service"), unit("pult-relay-update.service")
        self.assertEqual((relay_unit["RuntimeDirectory"], relay_unit["RuntimeDirectoryMode"]), ("pult-relay", "0750"))
        self.assertIn(relay_unit["Group"], upd.get("SupplementaryGroups", "").split())


if __name__ == "__main__":
    unittest.main(verbosity=1)
