"""Installing an update from the app, live on this Mac: a second Pult runs as a real launchd service beside the
owner's — its own folder, label, socket and log, a made-up bot token (Telegram refuses it, nothing is sent anywhere),
a local relay with the test keys — and the app runs in headless Chrome with real taps:
  1. install.sh from a clone of this repository (the current branch, as committed): history "terminal", Settings
     "up to date";
  2. a commit that bumps the version: "ready" → Install. The installer outlives the restart of its own service, the
     new daemon comes up, the app says "installing" while the computer is away and comes back "up to date" on the new
     version; history "app";
  3. a commit that can't start (an import that fails): Install → the old version comes back by itself. "Didn't come
     up", the reason and the error; history "failed"; the service runs the old version again.
Everything goes at the end: the service, its file in ~/Library/LaunchAgents, the folders. ~5 min; while it runs, one
more daemon (~100 MB) and a venv (~200 MB on disk).
  ~/.local/share/pult/venv/bin/python tools/update_live.py [--keep]
The owner's Pult is never touched: another label, folder and socket. Exit 1 on a failed check."""
import asyncio, base64, hashlib, hmac, json, os, shutil, subprocess, sys, tempfile, time, urllib.parse
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
LABEL = "io.github.pulthq.pult-livetest"
import _cdp  # noqa: E402  (tools/_cdp.py: where Chrome is, free ports, a profile that goes — review 2026-10-27, Т9)
RELAY_PORT, CDP_PORT = _cdp.any_port(), _cdp.free_port()
CHROME = _cdp.CHROME
failures = []


def verdict(name, ok, *info):
    print(("ok   " if ok else "FAIL ") + name, *info, flush=True)
    if not ok:
        failures.append(name)


def relay_main(port):
    """--relay: only the relay, with the test keys (tests/test_web.py), and the app's links signed for the owner."""
    sys.path.insert(0, str(REPO / "tests"))
    import test_web as W
    from aiohttp import web
    import relay

    def init(start):
        f = {"auth_date": str(int(time.time())), "chat_type": "supergroup", "chat_instance": "1", "start_param": start,
             "user": json.dumps({"id": W.T.OWNER, "first_name": "Live"})}
        dcs = "777:WebAppData\n" + "\n".join("%s=%s" % (k, f[k]) for k in sorted(f))
        f["signature"] = base64.urlsafe_b64encode(W.KEY.sign(dcs.encode())).decode().rstrip("=")
        secret = hmac.new(b"WebAppData", W.TOKEN.encode(), hashlib.sha256).digest()
        f["hash"] = hmac.new(secret, "\n".join("%s=%s" % (k, f[k]) for k in sorted(f)).encode(), hashlib.sha256).hexdigest()
        return urllib.parse.urlencode(f)
    for name, start in (("HOME", "home"), ("SETTINGS", "settings")):
        print("%s http://127.0.0.1:%d/pult/#tgWebAppData=%s&tgWebAppVersion=8.0&tgWebAppPlatform=android"
              % (name, port, urllib.parse.quote(init(start))), flush=True)
    print("TOKEN", W.TOKEN, "OWNER", W.T.OWNER, flush=True)
    web.run_app(relay.app(), host="127.0.0.1", port=port, print=None)


def git(repo, *a):
    return subprocess.run(["git", "-C", str(repo), "-c", "user.email=live@example.com", "-c", "user.name=Live", *a],
                          check=True, capture_output=True, text=True).stdout.strip()


async def main(keep):
    sys.path.insert(0, str(REPO / "src"))
    import pult_os
    if pult_os.KIND != "mac":
        print("macOS only for now (launchd); Linux: tests/probe_update.py in the lima VM")
        return 2
    T = Path(tempfile.mkdtemp(prefix="pult-live-"))
    home, repo, log = T / "home", T / "repo", T / "logs" / "pult.log"
    env = dict(os.environ, PULT_HOME=str(home), PULT_ENV=str(T / "env"), PULT_SOCK=str(home / "pult.sock"),
               PULT_LOG=str(log), PULT_LANG="ru")
    for k in ("PULT_DRIVEN", "PULT_FORCE", "PULT_SRC", "PULT_UPDATER"):
        env.pop(k, None)
    svc = pult_os.service_manager()
    relay = chrome = None
    print("folder:", T, flush=True)
    try:
        # the relay first: its links carry the token and the owner the daemon must have
        relay = subprocess.Popen([sys.executable, __file__, "--relay", str(RELAY_PORT)], stdout=subprocess.PIPE, text=True,
                                 stderr=subprocess.DEVNULL)
        urls, token, owner = {}, None, None
        while len(urls) < 2 or not token:
            ln = relay.stdout.readline()
            if not ln:
                raise RuntimeError("the relay didn't start")
            if ln.startswith("TOKEN"):
                _, token, _, owner = ln.split()
            else:
                k, v = ln.split(" ", 1)
                urls[k] = v.strip()
        (T / "logs").mkdir(parents=True)
        (T / "env").write_text("PULT_BOT_TOKEN=%s\nPULT_ALLOWED_USER_IDS=%s\nPULT_LABEL=%s\nPULT_RELAY_URL=ws://127.0.0.1:%d/pult/agent\n"
                               "PULT_RELAY_SECRET=s3cret\n" % (token, owner, LABEL, RELAY_PORT))
        os.chmod(T / "env", 0o600)
        subprocess.run(["git", "clone", "-q", "--branch", git(REPO, "rev-parse", "--abbrev-ref", "HEAD"), str(REPO), str(repo)], check=True)
        home.mkdir()
        subprocess.run([sys.executable, "-c", "import pult_setup as S; S.sput(chat=-1001)"], cwd=repo / "src", env=env, check=True)

        # 1. install.sh, as the owner does
        p = subprocess.run(["bash", str(repo / "install.sh")], env=env, stdin=subprocess.DEVNULL, capture_output=True, text=True)
        verdict("install.sh from the clone", p.returncode == 0, (p.stdout + p.stderr)[-300:])
        U = lambda name: json.loads((home / name).read_text()) if (home / name).exists() else {}
        verdict("its record: the folder and the commit", U("installed.json").get("commit") == git(repo, "rev-parse", "HEAD")
                and U("installed.json").get("src") == str(repo))
        verdict("history: terminal", [h["how"] for h in json.loads((home / "installs.json").read_text())] == ["terminal"])

        async def health(version=None, wait=90):
            end = time.time() + wait
            while time.time() < end:
                h = U("health.json")
                if h.get("relay") and (version is None or h.get("version") == version):
                    return h
                await asyncio.sleep(1)
            return U("health.json")
        v0 = (await health()).get("version")
        verdict("the test daemon is up and reached the relay", bool(v0), U("health.json"))

        prof = _cdp.profile()
        chrome = subprocess.Popen([CHROME, "--headless=new", "--disable-gpu", "--hide-scrollbars", "--remote-debugging-port=%d" % CDP_PORT,
                                   "--user-data-dir=" + prof, "--no-first-run", "about:blank"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        import aiohttp
        async with aiohttp.ClientSession() as s:
            for _ in range(50):
                try:
                    async with s.get("http://127.0.0.1:%d/json/list" % CDP_PORT) as r:
                        tabs = [x for x in await r.json() if x.get("type") == "page"]
                        if tabs:
                            break
                except aiohttp.ClientError:
                    pass
                await asyncio.sleep(0.2)
            ws = await s.ws_connect(tabs[0]["webSocketDebuggerUrl"], max_msg_size=64 * 1024 * 1024)
            n, errors = 0, []

            async def cmd(method, **params):
                nonlocal n
                n += 1
                await ws.send_str(json.dumps({"id": n, "method": method, "params": params}))
                while True:
                    m = json.loads((await ws.receive()).data)
                    if m.get("method") == "Runtime.exceptionThrown":
                        errors.append(m["params"]["exceptionDetails"].get("exception", {}).get("description"))
                    if m.get("id") == n:
                        return m.get("result", {})

            async def js(expr):
                r = await cmd("Runtime.evaluate", expression=expr, returnByValue=True, awaitPromise=True)
                return None if "exceptionDetails" in r else r["result"].get("value")

            async def until(expr, wait):
                end = time.time() + wait
                while time.time() < end:
                    if await js(expr):
                        return True
                    await asyncio.sleep(0.5)
                return False

            async def settings():
                await cmd("Page.navigate", url="about:blank")
                await asyncio.sleep(0.3)
                await cmd("Page.navigate", url=urls["SETTINGS"])

            async def tap():
                """A real tap on the block's main button (Install)."""
                box = await js("""(() => { const b = document.querySelector('.upg .btn.wide:not(.ghost)');
                    if (!b) return null; b.scrollIntoView({block: 'center'}); const r = b.getBoundingClientRect();
                    return [r.x + r.width / 2, r.y + r.height / 2]; })()""")
                for kind in ("mousePressed", "mouseReleased") if box else ():
                    await cmd("Input.dispatchMouseEvent", type=kind, x=box[0], y=box[1], button="left", clickCount=1)
                return bool(box)

            async def shot(name):
                Path(T, name + ".png").write_bytes(base64.b64decode((await cmd("Page.captureScreenshot", format="png"))["data"]))

            await cmd("Runtime.enable")
            await cmd("Page.enable")
            await cmd("Emulation.setDeviceMetricsOverride", width=412, height=900, deviceScaleFactor=2, mobile=True)
            card = "document.querySelector('.card.upg')"
            state = lambda st: "(%s && %s.className.includes('upd-s-%s'))" % (card, card, st)
            text = card + ".textContent"
            await settings()
            verdict("Settings: up to date", await until(state("ok"), 30), await js(card + " && " + card + ".className"))
            await shot("1-ok")

            # 2. a commit with a new version → Install
            pultd = repo / "src" / "pultd.py"
            v1 = v0 + "-live1"
            pultd.write_text(pultd.read_text().replace('VERSION = "%s"' % v0, 'VERSION = "%s"' % v1, 1))
            git(repo, "commit", "-qam", "Live 1: a new version")
            await settings()
            verdict("a new commit: ready", await until(state("ready"), 40), await js(text))
            await shot("2-ready")
            t0 = time.time()
            verdict("Install → installing", await tap() and await until(state("run"), 15))
            banner = await until("/Ставлю обновление|Installing the update/.test((document.querySelector('.banner') || {}).textContent || '')", 40)
            verdict("while the computer restarts the banner says installing", banner,
                    await js("(document.querySelector('.banner') || {}).textContent"))
            await shot("3-banner")
            verdict("back up to date on the new version", await until(state("ok") + " && " + text + ".includes(%s)" % json.dumps(v1), 150),
                    "%.0f s" % (time.time() - t0), await js(card + " && " + text))
            await shot("4-installed")
            h = await health(v1, 5)
            verdict("the service runs the new version", h.get("version") == v1, h.get("version"))
            hist = json.loads((home / "installs.json").read_text())
            verdict("history: app, ok", (hist[0]["how"], hist[0]["ok"], hist[0]["to"]) == ("app", True, v1), hist[0])
            verdict("the installer's log is next to the service's", (T / "logs" / "pult-update.log").exists())

            # 3. a commit that can't start → the old version comes back
            v2 = v0 + "-live2"
            src = pultd.read_text().replace('VERSION = "%s"' % v1, 'VERSION = "%s"' % v2, 1)
            src = src.replace("import pult_web as PW\n", "import pult_web as PW\nimport pult_live_missing  # the live check: this version can't start\n", 1)
            pultd.write_text(src)
            git(repo, "commit", "-qam", "Live 2: can't start")
            await settings()
            verdict("a broken commit: ready", await until(state("ready"), 40))
            t0 = time.time()
            verdict("Install → installing", await tap() and await until(state("run"), 15))
            got = await until(state("fail"), 240)
            body = await js(card + " && " + text) or ""
            verdict("the old version is back: didn't come up, with the error", got and v2 in body and "pult_live_missing" in body,
                    "%.0f s" % (time.time() - t0), body[:300])
            await shot("5-failed")
            h = await health(v1, 30)
            verdict("the service runs the old version again", h.get("version") == v1, h.get("version"))
            hist = json.loads((home / "installs.json").read_text())
            # either way it didn't come up: two restarts seen ("restarts"), or a version so broken that launchd never shows
            # its process before it falls ("no_start" — what this Mac gives since at least 2026-10-27)
            verdict("history: failed, why", (hist[0]["ok"], hist[0]["to"]) == (False, v2)
                    and hist[0].get("why") in ("restarts", "no_start"), hist[0])
            end = time.time() + 20                         # the restored daemon tells General within its 5 s tick
            while time.time() < end and U("update.json").get("reported") is not True:
                await asyncio.sleep(1)
            await asyncio.sleep(2)
            tried = [ln for ln in log.read_text().splitlines()[-40:] if "sendMessage" in ln]
            verdict("General was told (a refused token: the try is in the log)", U("update.json").get("reported") is True
                    and bool(tried), tried[-1:] or U("update.json"))
            verdict("no script errors", not errors, errors[:3])
        return 1 if failures else 0
    finally:
        for p in (chrome, relay):
            if p:
                p.kill()
        svc.stop(LABEL)
        svc.remove(LABEL)
        for _ in range(20):                                # launchd's bootout is asynchronous
            if svc.state(LABEL)[0] is None:
                break
            time.sleep(0.5)
        print("the test service removed:", svc.state(LABEL)[0] is None, flush=True)
        if keep:
            print("kept:", T)
        else:
            shutil.rmtree(T, ignore_errors=True)


if __name__ == "__main__":
    if len(sys.argv) > 2 and sys.argv[1] == "--relay":
        relay_main(int(sys.argv[2]))
    else:
        sys.exit(asyncio.run(main("--keep" in sys.argv)))
