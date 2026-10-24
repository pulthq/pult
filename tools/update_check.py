"""Installing an update from the app (stage U), in headless Chrome over DevTools, on the stand, with real taps: for
each state (STAND_UPD) a stand of its own comes up, and Settings → Pult and Home's line are checked. Nothing newer: no
line on Home, "up to date", the history opens. Ready: "Install" turns the block into "Installing…". Not now: what a
restart would cut off, "Install once they're free" → waiting, "Cancel" → back. Waiting, installing, didn't come up:
their own block and line. No script errors anywhere.
  ~/.local/share/pult/venv/bin/python tools/update_check.py [out_dir]
The stand never starts an installer (pult_update.spawn is a fake there); the real one is checked by tests/test_setup.py
and on a real service. The banner while the computer restarts is seen only with a real restart. Screenshots go to
out_dir (a temporary folder by default). Exit 1 on a failed check."""
import asyncio, base64, json, os, subprocess, sys, tempfile, time
from pathlib import Path
import aiohttp

REPO = Path(__file__).resolve().parent.parent
PY = sys.executable
OUT = sys.argv[1] if len(sys.argv) > 1 else tempfile.mkdtemp(prefix="pult-update-")
os.makedirs(OUT, exist_ok=True)
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
PORT, STAND_PORT = 9339, "18113"
failures = []


def verdict(name, ok, *info):
    print(("ok   " if ok else "FAIL ") + name, *info)
    if not ok:
        failures.append(name)


def stand(state):
    """A stand in this state → (process, {name: url})."""
    out = Path(OUT) / ("stand-%s.out" % state)
    env = dict(os.environ, STAND_UPD=state, STAND_LANG="ru", STAND_PORT=STAND_PORT, HOLD="120")
    p = subprocess.Popen([PY, str(REPO / "tools" / "stand.py")], env=env, stdout=open(out, "w"), stderr=subprocess.DEVNULL)
    for _ in range(120):
        text = out.read_text() if out.exists() else ""
        if "\nHOME " in "\n" + text and "SETTINGS " in text:
            return p, dict(ln.split(" ", 1) for ln in text.splitlines() if ln[:5] in ("HOME ", "SETTI"))
        time.sleep(0.25)
    p.kill()
    raise RuntimeError("the stand didn't come up (%s)" % state)


async def main():
    prof = tempfile.mkdtemp(prefix="cdp-")
    chrome = subprocess.Popen([CHROME, "--headless=new", "--disable-gpu", "--hide-scrollbars", "--remote-debugging-port=%d" % PORT,
                               "--user-data-dir=" + prof, "--no-first-run", "about:blank"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        async with aiohttp.ClientSession() as s:
            for _ in range(50):
                try:
                    async with s.get("http://127.0.0.1:%d/json/list" % PORT) as r:
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
                        if "error" in m:
                            raise RuntimeError("%s: %s" % (method, m["error"]))
                        return m.get("result", {})

            async def js(expr):
                r = await cmd("Runtime.evaluate", expression=expr, returnByValue=True, awaitPromise=True)
                if "exceptionDetails" in r:
                    raise RuntimeError(r["exceptionDetails"])
                return r["result"].get("value")

            async def until(expr, tries=80):
                for _ in range(tries):
                    if await js(expr):
                        return True
                    await asyncio.sleep(0.1)
                return False

            async def open_(url):
                await cmd("Page.navigate", url=url)
                await asyncio.sleep(0.3)

            async def shot(name):
                data = (await cmd("Page.captureScreenshot", format="png"))["data"]
                Path(OUT, name + ".png").write_bytes(base64.b64decode(data))

            async def tap(text):
                """A real tap on the button with this text, in the Pult block."""
                box = await js("""(() => { const b = [...document.querySelectorAll('.upg button')].find(b => b.textContent.includes(%s));
                    if (!b) return null; b.scrollIntoView({block: 'center'}); const r = b.getBoundingClientRect();
                    return [r.x + r.width / 2, r.y + r.height / 2]; })()""" % json.dumps(text))
                if not box:
                    return False
                for kind in ("mousePressed", "mouseReleased"):
                    await cmd("Input.dispatchMouseEvent", type=kind, x=box[0], y=box[1], button="left", clickCount=1)
                return True

            await cmd("Runtime.enable")
            await cmd("Page.enable")
            await cmd("Emulation.setDeviceMetricsOverride", width=412, height=900, deviceScaleFactor=2, mobile=True)
            card = "document.querySelector('.card.upg')"
            row = "document.querySelector('.upd-row')"
            for state in ("ok", "ready", "busy", "wait", "run", "fail"):
                proc, urls = stand(state)
                try:
                    await open_("about:blank")             # a new stand: a new page (only the part after # would differ)
                    # Home first: the line, and a tap on it leads to Settings
                    await open_(urls["HOME"])
                    await until("document.querySelector('.where')")
                    await asyncio.sleep(0.6)
                    line = await js(row + " && " + row + ".textContent")
                    cls = await js(row + " && " + row + ".className") or ""
                    want = {"ok": None, "ready": "Готова", "busy": "сейчас нельзя: идут 2", "wait": "осталось 1", "run": "Ставлю",
                            "fail": "не поднялась"}[state]
                    if want is None:
                        verdict("ok: no line on Home", line is None, line)
                        await open_("about:blank")         # the Settings link differs from Home's only after #
                        await open_(urls["SETTINGS"])
                    else:
                        verdict("%s: Home's line" % state, want in (line or "") and
                                (("attn" in cls) if state in ("busy", "wait") else ("bad" in cls) if state == "fail" else True),
                                line, cls)
                        await shot("home-" + state)
                        await js(row + ".click()")
                        verdict("%s: the line leads to Settings" % state, await until("location.hash === '#/settings'"))
                    got = await until(card + " && " + card + ".className.includes('upd-s-')")
                    cls = await js(card + " && " + card + ".className")
                    verdict("%s: Settings shows the Pult block" % state, got and ("upd-s-" + state) in (cls or ""), cls)
                    text = await js(card + ".textContent") if got else ""        # not innerText: headings are upper-cased by CSS
                    await shot("settings-" + state)
                    if state == "ok":
                        verdict("ok: up to date, checked against the folder", "новее нет" in text and "~/pult" in text, text[:120])
                        await js("document.querySelector('.upd-hist summary').click()")
                        rows = await js("document.querySelectorAll('.upd-hist .login').length")
                        hist = await js("document.querySelector('.upd-hist').textContent")
                        verdict("ok: the history opens — five installs, where from", rows == 5 and "терминал" in hist
                                and "приложение, когда освободились" in hist and "не поднялась" in hist, rows)
                        await shot("settings-ok-history")
                    elif state == "ready":
                        verdict("ready: what's new and the button", "Что нового" in text and "Поставить 0." in text, text[:160])
                        verdict("ready: Install → installing", await tap("Поставить 0.")
                                and await until(card + ".className.includes('upd-s-run')"))
                        await shot("settings-ready-tapped")
                    elif state == "busy":
                        who = await js("document.querySelectorAll('.upd-who').length")
                        verdict("busy: what a restart would cut off", who == 2 and "Перезапуск оборвёт 2" in text
                                and "Не тронет вкладки" in text, who)
                        verdict("busy: once they're free → waiting", await tap("когда освободятся")
                                and await until(card + ".className.includes('upd-s-wait')"))
                        await shot("settings-busy-tapped")
                        verdict("busy: Cancel → back", await tap("Отменить") and await until(card + ".className.includes('upd-s-busy')"))
                    elif state == "wait":
                        verdict("wait: one left, Cancel", "Осталось 1" in text and "Отменить" in text, text[:160])
                    elif state == "run":
                        verdict("run: installing, the steps", "Ставлю 0." in text and "на случай отката" in text, text[:160])
                    elif state == "fail":
                        verdict("fail: rolled back, why, the error", "откат" in text and "падает при запуске" in text
                                and "ModuleNotFoundError" in text and "больше не предлагаю" in text, text[:200])
                finally:
                    proc.kill()
                    proc.wait()
            verdict("no script errors", not errors, errors[:3])
    finally:
        chrome.kill()
    print("screenshots:", OUT)
    sys.exit(1 if failures else 0)


asyncio.run(main())
