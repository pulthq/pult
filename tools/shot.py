"""Screenshot a page in headless Chrome over DevTools: phone width, wait for the data, capture the whole page.
  python tools/shot.py URL out.png [width] [wait_s] [dark]
SHOT_HEIGHT=860 — one phone screen instead of the whole page (the README pictures).
SHOT_FIT=.chat — cut the picture at the bottom edge of that element (a page shorter than the window).
SHOT_JS="document.querySelector('.mchip').click()" — run on the loaded page before the picture (open a menu).
SHOT_AFTER=12 — seconds to wait after SHOT_JS (1 by default): for what it starts to come back (a second opinion).
SHOT_CLEAR=1 — a transparent background where the page has none (pictures composed for the README).
Not --screenshot with --virtual-time-budget: the app holds a WebSocket open, the page never "settles", and Chrome
hangs. Only a type=page tab is used: the first one in the list is sometimes an internal one (Omnibox Popup)."""
import asyncio, base64, json, os, subprocess, sys
import aiohttp

URL, OUT = sys.argv[1], sys.argv[2]
W = int(sys.argv[3]) if len(sys.argv) > 3 else 412
WAIT = float(sys.argv[4]) if len(sys.argv) > 4 else 4
DARK = len(sys.argv) > 5 and sys.argv[5] == "dark"
HEIGHT = int(os.environ.get("SHOT_HEIGHT") or 0)
FIT = os.environ.get("SHOT_FIT")
JS = os.environ.get("SHOT_JS")
AFTER = float(os.environ.get("SHOT_AFTER") or 1)
CLEAR = os.environ.get("SHOT_CLEAR") == "1"
import _cdp  # noqa: E402  (tools/_cdp.py: where Chrome is, free ports, a profile that goes — review 2026-10-27, Т9)
CHROME = _cdp.CHROME
PORT = _cdp.free_port()


async def main():
    prof = _cdp.profile()
    p = subprocess.Popen([CHROME, "--headless=new", "--disable-gpu", "--hide-scrollbars", "--remote-debugging-port=%d" % PORT, "--user-data-dir=" + prof,
                          "--no-first-run", "about:blank"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
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
            n = 0

            async def cmd(method, **params):
                nonlocal n
                n += 1
                await ws.send_str(json.dumps({"id": n, "method": method, "params": params}))
                while True:
                    m = json.loads((await ws.receive()).data)
                    if m.get("id") == n:
                        return m.get("result", {})
            await cmd("Emulation.setDeviceMetricsOverride", width=W, height=900, deviceScaleFactor=2, mobile=True)
            if CLEAR:
                await cmd("Emulation.setDefaultBackgroundColorOverride", color={"r": 0, "g": 0, "b": 0, "a": 0})
            if DARK:
                await cmd("Emulation.setEmulatedMedia", features=[{"name": "prefers-color-scheme", "value": "dark"}])
            await cmd("Page.enable")
            await cmd("Page.navigate", url=URL)
            await asyncio.sleep(WAIT)
            expr = ("Math.ceil(document.querySelector(%s).getBoundingClientRect().bottom + window.scrollY)" % json.dumps(FIT)
                    if FIT else "document.documentElement.scrollHeight")
            h = (await cmd("Runtime.evaluate", expression=expr, returnByValue=True))["result"]["value"]
            await cmd("Emulation.setDeviceMetricsOverride", width=W, height=HEIGHT or min(int(h), 4000), deviceScaleFactor=2, mobile=True)
            await cmd("Runtime.evaluate", expression="window.scrollTo(0, 0)")
            await asyncio.sleep(0.5)
            if JS:                       # after the window got its final size: a scroll or a click stays put
                await cmd("Runtime.evaluate", expression=JS)
                await asyncio.sleep(AFTER)
            shot = await cmd("Page.captureScreenshot", format="png")
            open(OUT, "wb").write(base64.b64decode(shot["data"]))
            log = (await cmd("Runtime.evaluate", expression="document.querySelector('.banner') ? document.querySelector('.banner').textContent : 'ok'", returnByValue=True))
            print("captured", OUT, "height", h, "· banner:", log["result"].get("value"))
    finally:
        p.terminate()

asyncio.run(main())
