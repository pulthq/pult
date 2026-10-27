"""Pult's own check of a Claude Code version VS Code has downloaded (stage A), in headless Chrome over DevTools, on the
stand, with real taps. A stand for each state (STAND_PARTS): the check running — "checking…", no line on Home; it
failed at a step — "failed", the step, "Check again", Home's line saying writing goes off once a window reloads;
"Check again" — "checking…", then passed: "checked here" and the tabs move to it after a reload; passed with the tabs
on it — "checked here"; couldn't check (not logged in) — why, when, "Check again". The switch in Settings. English
once, for keys left as keys.
  ~/.local/share/pult/venv/bin/python tools/vcheck_check.py [out_dir]
The facts are made up and the stand's "Check again" passes in 3 s without Claude; the check itself is
tests/test_pult.py (TabCheckTest) and `pult tab check` on a real Claude Code. Screenshots go to out_dir (a temporary
folder by default). Exit 1 on a failed check."""
import asyncio, base64, json, os, subprocess, sys, tempfile, time
from pathlib import Path
import aiohttp

REPO = Path(__file__).resolve().parent.parent
PY = sys.executable
OUT = sys.argv[1] if len(sys.argv) > 1 else tempfile.mkdtemp(prefix="pult-vcheck-")
os.makedirs(OUT, exist_ok=True)
import _cdp  # noqa: E402  (tools/_cdp.py: where Chrome is, free ports, a profile that goes — review 2026-10-27, Т9)
CHROME = _cdp.CHROME
PORT, STAND_PORT = _cdp.free_port(), os.environ.get("STAND_PORT") or str(_cdp.any_port())
failures = []


def verdict(name, ok, *info):
    print(("ok   " if ok else "FAIL ") + name, *info)
    if not ok:
        failures.append(name)


def stand(parts, lang="ru"):
    """A stand on these facts → (process, {name: url})."""
    out = Path(OUT) / ("stand-%s-%s.out" % (parts, lang))
    env = dict(os.environ, STAND_PARTS=parts, STAND_LANG=lang, STAND_PORT=STAND_PORT, HOLD="120")
    p = subprocess.Popen([PY, str(REPO / "tools" / "stand.py")], env=env, stdout=open(out, "w"), stderr=subprocess.DEVNULL)
    for _ in range(120):
        text = out.read_text() if out.exists() else ""
        if "\nHOME " in "\n" + text and "SETTINGS " in text:
            return p, dict(ln.split(" ", 1) for ln in text.splitlines() if ln[:5] in ("HOME ", "SETTI"))
        time.sleep(0.25)
    _cdp.stop(p)
    raise RuntimeError("the stand didn't come up (%s)" % parts)


async def main():
    prof = _cdp.profile()
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
                await cmd("Page.navigate", url="about:blank")
                await cmd("Page.navigate", url=url)
                await asyncio.sleep(0.3)
                await js("window.__said = []; window.alert = (s) => window.__said.push(String(s));"
                         " const w = window.Telegram && window.Telegram.WebApp; if (w) w.showAlert = (s) => window.__said.push(String(s));")

            async def shot(name):
                d = await cmd("Page.captureScreenshot", format="png")
                Path(OUT, name + ".png").write_bytes(base64.b64decode(d["data"]))

            async def tap_at(expr):
                box = await js("""(() => { const b = %s; if (!b) return null; b.scrollIntoView({block: 'center'});
                    const r = b.getBoundingClientRect(); return [r.x + r.width / 2, r.y + r.height / 2]; })()""" % expr)
                if not box:
                    return False
                await cmd("Input.dispatchTouchEvent", type="touchStart", touchPoints=[{"x": box[0], "y": box[1]}])
                await cmd("Input.dispatchTouchEvent", type="touchEnd", touchPoints=[])
                await asyncio.sleep(0.4)
                return True

            row = "document.querySelector('.part[data-k=cc]')"
            chip = lambda: js(row + "?.querySelector('.pchip')?.textContent || ''")
            more = lambda: js(row + "?.querySelector('.part-x')?.textContent || ''")
            again = row + "?.querySelector('.part-x .btn')"

            async def settings(urls):
                await open_(urls["SETTINGS"])
                ok = await until("document.querySelectorAll('.part').length >= 5", 150)
                if ok and not await js(row + "?.classList.contains('open')"):
                    await tap_at(row + "?.querySelector('.part-r')")
                    await until(row + "?.classList.contains('open')")
                return ok

            async def home(urls):
                await open_(urls["HOME"])
                await until("document.querySelector('.where')", 150)
                await asyncio.sleep(0.8)
                return await js("document.querySelector('.upd-row')?.textContent || ''")

            await cmd("Page.enable")
            await cmd("Runtime.enable")
            await cmd("Emulation.setDeviceMetricsOverride", width=412, height=900, deviceScaleFactor=2, mobile=True)
            await cmd("Emulation.setTouchEmulationEnabled", enabled=True, maxTouchPoints=5)

            # 1. the check is running
            proc, urls = stand("check_run")
            try:
                line = await home(urls)
                verdict("running: no line about Claude Code on Home", "Claude Code" not in line, line)
                verdict("running: the table", await settings(urls))
                verdict("running: the chip says checking", "проверяется" in await chip(), await chip())
                verdict("running: the row says it's being checked here", "Пульт проверяет Claude Code 2.1.311" in await more(), await more())
                verdict("running: no button meanwhile", not await js(again))
                await shot("1-running")
            finally:
                _cdp.stop(proc)

            # 2. it failed at a step; Home warns; "Check again" — checking, then passed
            proc, urls = stand("check_fail")
            try:
                line = await home(urls)
                verdict("failed: Home's line says writing goes off once a window reloads",
                        "2.1.311 не прошёл проверку" in line and "после перезагрузки окна" in line, line)
                await shot("2-home-failed")
                verdict("failed: the table", await settings(urls))
                verdict("failed: the chip", "не прошёл" in await chip(), await chip())
                text = await more()
                verdict("failed: the row names the step", "не прошёл проверку здесь" in text and "смена модели" in text, text)
                verdict("failed: Check again", "Проверить снова" in (await js(again + "?.textContent") or ""))
                await shot("3-failed")
                await tap_at(again)
                verdict("Check again: checking at once", await until(row + "?.querySelector('.pchip')?.textContent.includes('проверяется')", 30), await chip())
                verdict("Check again: passed in a few seconds — checked here",
                        await until(row + "?.querySelector('.part-x')?.textContent.includes('проверен на этом компьютере')", 80), await more())
                verdict("passed: the tabs move to it after a reload", "после перезагрузки окна" in await more(), await more())
                verdict("passed: no button any more", not await js(again))
                await shot("4-again-passed")
            finally:
                _cdp.stop(proc)

            # 3. passed, the tabs run it
            proc, urls = stand("check_here")
            try:
                verdict("here: the table", await settings(urls))
                verdict("here: the chip says checked here", "проверен здесь" in await chip(), await chip())
                verdict("here: the row says when", "2.1.311 проверен на этом компьютере" in await more(), await more())
                await shot("5-here")
            finally:
                _cdp.stop(proc)

            # 4. couldn't check
            proc, urls = stand("check_err")
            try:
                verdict("couldn't: the table", await settings(urls))
                text = await more()
                verdict("couldn't: why and when, tried again in an hour",
                        "не удалось" in text and "нет входа в Claude" in text and "через час" in text, text)
                verdict("couldn't: Check now / again", bool(await js(again)))
                await shot("6-couldnt")
                # the switch in Settings
                sw = "[...document.querySelectorAll('.sw-row')].find((r) => r.textContent.includes('Проверять новые версии'))"
                verdict("Settings: the switch is there and on", await js("(%s)?.querySelector('.sw-h')?.getAttribute('aria-checked')" % sw) == "true")
                await tap_at("(%s)?.querySelector('.sw-h')" % sw)
                verdict("Settings: a tap turns it off", await until("(%s)?.querySelector('.sw-h')?.getAttribute('aria-checked') === 'false'" % sw, 30))
                await shot("7-switch")
            finally:
                _cdp.stop(proc)

            # 5. English, for keys left as keys
            proc, urls = stand("check_fail", "en")
            try:
                await settings(urls)
                text = await more() + await chip()
                verdict("English: no key left as a key", "pt.cc." not in text and "tab.step." not in text and "check.why." not in text, text)
                verdict("English: the step in words", "switching the model" in text, text)
            finally:
                _cdp.stop(proc)
            verdict("no script errors", not errors, errors)
    finally:
        chrome.kill()
    print("screenshots:", OUT)
    sys.exit(1 if failures else 0)


asyncio.run(main())
