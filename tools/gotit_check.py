"""Every finished task waits for "Got it" (the owner, 2026-10-30: "I want to send every session I start to the checked
ones myself"), in headless Chrome over DevTools, on the stand, with real taps: a plain report — the model's "only a
report" — is a card of "Your move", not a row with a tick; opening its session doesn't put it away; the outcome at the end
of the chat offers "Got it", though nothing is needed; the tap puts it away — off "Your move", a row of its project.
  STAND_REPORT=1 STAND_LANG=ru HOLD=300 ~/.local/share/pult/venv/bin/python tools/stand.py > /tmp/stand.out &
  ~/.local/share/pult/venv/bin/python tools/gotit_check.py /tmp/stand.out [out_dir]
Screenshots go to out_dir (a temporary folder by default). Exit 1 on a failed check."""
import asyncio, base64, json, os, subprocess, sys, tempfile
import aiohttp

URLS = dict(line.split(" ", 1) for line in open(sys.argv[1]).read().split("\n") if line[:5] == "HOME ")
OUT = sys.argv[2] if len(sys.argv) > 2 else tempfile.mkdtemp(prefix="pult-gotit-")
os.makedirs(OUT, exist_ok=True)
import _cdp  # noqa: E402  (tools/_cdp.py: where Chrome is, free ports, a profile that goes — review 2026-10-27, Т9)
CHROME = _cdp.CHROME
PORT = _cdp.free_port()
TITLE = "Отчёт поддержки за неделю"           # the stand's weekly report (tools/stand.py, s5_title), STAND_LANG=ru
failures = []


def verdict(name, ok, *info):
    print(("ok   " if ok else "FAIL ") + name, *info)
    if not ok:
        failures.append(name)


async def main():
    prof = _cdp.profile()
    p = subprocess.Popen([CHROME, "--headless=new", "--disable-gpu", "--hide-scrollbars", "--remote-debugging-port=%d" % PORT,
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

            async def until(expr, tries=100):
                for _ in range(tries):
                    if await js(expr):
                        return True
                    await asyncio.sleep(0.1)
                return False

            async def shot(name):
                d = await cmd("Page.captureScreenshot", format="png", captureBeyondViewport=True)
                open(os.path.join(OUT, name), "wb").write(base64.b64decode(d["data"]))

            async def tap(expr):
                """A finger on the element's middle — not el.click(): what is on top there gets it."""
                r = await js("(() => { const el = %s; if (!el) return null; el.scrollIntoView({block: 'center'});"
                             " const b = el.getBoundingClientRect(); return [b.left + b.width / 2, b.top + b.height / 2]; })()" % expr)
                if not r:
                    raise RuntimeError("nothing to tap: " + expr)
                await cmd("Input.dispatchTouchEvent", type="touchStart", touchPoints=[{"x": r[0], "y": r[1]}])
                await cmd("Input.dispatchTouchEvent", type="touchEnd", touchPoints=[])
                await asyncio.sleep(0.5)

            await cmd("Page.enable")
            await cmd("Runtime.enable")
            await cmd("Emulation.setDeviceMetricsOverride", width=412, height=860, deviceScaleFactor=2, mobile=True)
            await cmd("Emulation.setTouchEmulationEnabled", enabled=True, maxTouchPoints=5)

            card = "[...document.querySelectorAll('.card.mine')].find((c) => (c.querySelector('.c-title') || {textContent: ''}).textContent.includes(%s))" % json.dumps(TITLE)
            row = "[...document.querySelectorAll('.item.brow')].find((r) => r.textContent.includes(%s))" % json.dumps(TITLE)
            got = "[...document.querySelectorAll('.card.outcome .foot button.link')].find((b) => !b.classList.contains('sec-ask'))"
            await cmd("Page.navigate", url=URLS["HOME"])
            verdict("a plain report is a card of «Your move»", await until("!!(%s)" % card, 150),
                    await js("[...document.querySelectorAll('.card.mine .c-title')].map((t) => t.textContent)"))
            verdict("… not a row with a tick on the board", await js("!(%s)" % row))
            await shot("1-home-report-waits.png")
            await tap("(%s).querySelector('.card-h')" % card)
            verdict("its header opens the session", await until("location.hash.startsWith('#/s/') && !!document.querySelector('.composer')", 150),
                    await js("location.hash"))
            verdict("the outcome at the end offers «Got it», though nothing is needed", await until("!!(%s)" % got, 100),
                    await js("(document.querySelector('.card.outcome') || {}).innerText"))
            verdict("… it waits for you: the card says so", await js("!!document.querySelector('.card.outcome.mine')"))
            await shot("2-session-got-it.png")
            sess = await js("location.href")
            await cmd("Page.navigate", url="about:blank")
            await cmd("Page.navigate", url=URLS["HOME"])
            verdict("opened and left: still in «Your move»", await until("!!(%s)" % card, 150))
            await cmd("Page.navigate", url="about:blank")
            await cmd("Page.navigate", url=sess)
            await until("!!(%s)" % got, 150)
            await tap(got)
            verdict("«Got it» there turns into a quiet tick", await until("!(%s) && !!document.querySelector('.card.outcome .foot .dim')" % got, 50),
                    await js("(document.querySelector('.card.outcome .foot') || {}).innerText"))
            await shot("3-session-put-away.png")
            await cmd("Page.navigate", url="about:blank")
            await cmd("Page.navigate", url=URLS["HOME"])
            await until("!!document.querySelector('.card.mine')", 150)
            verdict("put away: off «Your move»", await until("!(%s)" % card, 50))
            verdict("… a row of its project now", await until("!!(%s)" % row, 50))
            await shot("4-home-put-away.png")
            verdict("no script errors", not errors, errors)
    finally:
        p.kill()
    print("screenshots:", OUT)
    sys.exit(1 if failures else 0)


asyncio.run(main())
