"""The app's picture viewer in headless Chrome over DevTools, on the stand, with touches as from a phone: a picture in the
chat opens on the whole screen, a swipe goes to the next one, a double tap and two fingers zoom, a finger drags the
zoomed picture and its edges stay on the screen, a single tap hides the bars, a swipe down and Back close it. Before
sending, a thumbnail opens the viewer: Crop hands the picture to the editor, Remove takes it off, the last one closes
the viewer. Nothing is left in the history.
  HOLD=300 ~/.local/share/pult/venv/bin/python tools/stand.py > /tmp/stand.out &
  ~/.local/share/pult/venv/bin/python tools/viewer_check.py "$(grep '^SESS ' /tmp/stand.out | cut -d' ' -f2)" [out_dir]
Screenshots go to out_dir (a temporary folder by default). Exit 1 on a failed check. Selectors are by class and order,
not by text: the stand runs in either language."""
import asyncio, base64, json, os, re, struct, subprocess, sys, tempfile, zlib
import aiohttp

URL = sys.argv[1]
OUT = sys.argv[2] if len(sys.argv) > 2 else tempfile.mkdtemp(prefix="pult-viewer-")
os.makedirs(OUT, exist_ok=True)
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
PORT = 9338
W, H = 412, 860
failures = []


def verdict(name, ok, *info):
    print(("ok   " if ok else "FAIL ") + name, *info)
    if not ok:
        failures.append(name)


def png(path, w, h):
    rows = b"".join(b"\x00" + b"".join(bytes((255, 0, 0) if x < w // 2 else (0, 0, 255)) for x in range(w)) for _ in range(h))
    chunk = lambda t, d: struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xffffffff)
    with open(path, "wb") as f:
        f.write(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
                + chunk(b"IDAT", zlib.compress(rows)) + chunk(b"IEND", b""))


# the viewer's state: open, counter, the current picture's zoom and shift, its size on the screen, the bars hidden
STATE = """(() => { const v = document.querySelector('.viewer');
  if (!v) return null;
  const pics = [...v.querySelectorAll('.v-pic')];
  const cur = pics.find(p => /translate3d\\(0px/.test(p.style.transform)) || null;
  const img = cur && cur.querySelector('img');
  const m = img && /translate\\((-?[\\d.]+)px, ?(-?[\\d.]+)px\\) scale\\(([\\d.]+)\\)/.exec(img.style.transform);
  const r = img && img.getBoundingClientRect();
  const n = v.querySelector('.v-n');
  return { n: n ? n.textContent : null, bare: v.classList.contains('bare'), bar: !!v.querySelector('.v-bar'),
    x: m ? +m[1] : 0, y: m ? +m[2] : 0, s: m ? +m[3] : 1, r: r && { l: r.left, t: r.top, w: r.width, h: r.height } };
})()"""


async def main():
    pic = os.path.join(OUT, "halves.png")
    png(pic, 400, 300)
    prof = tempfile.mkdtemp(prefix="cdp-")
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
                d = await cmd("Page.captureScreenshot", format="png")
                open(os.path.join(OUT, name), "wb").write(base64.b64decode(d["data"]))

            async def center(sel, k=0):
                return await js("(() => { const r = document.querySelectorAll(%s)[%d].getBoundingClientRect(); return [r.left + r.width / 2, r.top + r.height / 2]; })()"
                                % (json.dumps(sel), k))

            async def touch(kind, pts):
                await cmd("Input.dispatchTouchEvent", type=kind, touchPoints=[{"x": x, "y": y, "id": i} for i, (x, y) in pts])

            async def tap_at(x, y):
                await touch("touchStart", [(0, (x, y))])
                await touch("touchEnd", [])

            async def tap(sel, k=0, wait=0.35):         # a finger, not .click(): the viewer listens to the pointer
                await tap_at(*await center(sel, k))
                await asyncio.sleep(wait)

            async def swipe(x0, y0, x1, y1, steps=10, dt=0.02):
                await touch("touchStart", [(0, (x0, y0))])
                for i in range(1, steps + 1):
                    await touch("touchMove", [(0, (x0 + (x1 - x0) * i / steps, y0 + (y1 - y0) * i / steps))])
                    await asyncio.sleep(dt)
                await touch("touchEnd", [])
                await asyncio.sleep(0.4)

            async def pinch(cx, cy, d0, d1, steps=10):
                a = lambda d: [(0, (cx - d / 2, cy)), (1, (cx + d / 2, cy))]
                await touch("touchStart", a(d0))
                for i in range(1, steps + 1):
                    await touch("touchMove", a(d0 + (d1 - d0) * i / steps))
                    await asyncio.sleep(0.02)
                await touch("touchEnd", [])
                await asyncio.sleep(0.4)

            st = lambda: js(STATE)
            in_history = lambda: js("!!(history.state && history.state.overlay)")

            await cmd("Runtime.enable")
            await cmd("Emulation.setDeviceMetricsOverride", width=W, height=H, deviceScaleFactor=2, mobile=True)
            await cmd("Emulation.setTouchEmulationEnabled", enabled=True, maxTouchPoints=2)
            await cmd("Page.enable")
            await cmd("Page.navigate", url=URL)
            await until("document.querySelectorAll('.msg img.att').length >= 2", 150)
            await asyncio.sleep(0.5)
            await js("document.querySelector('.msg img.att').scrollIntoView({block: 'center'})")
            await asyncio.sleep(0.3)

            # the chat: a picture opens on the whole screen, with the other picture of the message
            await tap(".msg img.att")
            ok = await until("!!document.querySelector('.viewer .v-pic img') && document.querySelector('.viewer .v-pic img').naturalWidth > 0")
            await asyncio.sleep(0.3)
            v = await st()
            verdict("a tap on a picture in the chat opens the viewer", ok and v, v and v["n"])
            verdict("two pictures of the message: 1 / 2", v and v["n"] == "1 / 2")
            verdict("the picture fills the screen's width", v and v["r"] and abs(v["r"]["w"] - W) < 2, v and v["r"])
            verdict("in the history: Back closes it", await in_history())
            await shot("1-open.png")

            await swipe(W * 0.8, H / 2, W * 0.15, H / 2)
            v = await st()
            verdict("a swipe left goes to the next one", v and v["n"] == "2 / 2", v and v["n"])
            await swipe(W * 0.8, H / 2, W * 0.15, H / 2)
            verdict("no further than the last", (await st())["n"] == "2 / 2")
            await swipe(W * 0.2, H / 2, W * 0.85, H / 2)
            verdict("a swipe right goes back", (await st())["n"] == "1 / 2")
            await until("document.querySelector('.viewer .v-pic img') && document.querySelector('.viewer .v-pic img').naturalWidth > 0")

            # a double tap zooms in there and back out
            await tap_at(W * 0.25, H / 2)
            await asyncio.sleep(0.08)
            await tap_at(W * 0.25, H / 2)
            await asyncio.sleep(0.4)
            v = await st()
            verdict("a double tap zooms in", v["s"] > 2, v["s"])
            verdict("…around the finger: the left half comes to the middle", v["x"] > 100, v["x"])
            await shot("2-double-tap.png")
            await tap_at(W / 2, H / 2)
            await asyncio.sleep(0.08)
            await tap_at(W / 2, H / 2)
            await asyncio.sleep(0.4)
            v = await st()
            verdict("a second double tap zooms back out", v["s"] == 1 and v["x"] == 0, v["s"], v["x"])

            # two fingers zoom; a finger drags the zoomed picture, its edges stay on the screen
            await pinch(W / 2, H / 2, 80, 280)
            v = await st()
            verdict("two fingers apart zoom in", v["s"] > 2.5, v["s"])
            await swipe(W / 2, H / 2, W / 2 + 2000, H / 2 + 2000, steps=20, dt=0.01)
            v = await st()
            verdict("a drag moves the zoomed picture to its edge, no further", v["r"]["l"] <= 0.5 and v["r"]["l"] > -1,
                    round(v["r"]["l"], 1), round(v["x"], 1))
            verdict("a zoomed picture doesn't page", v["n"] == "1 / 2")
            await shot("3-pinch-drag.png")
            await pinch(W / 2, H / 2, 300, 40)
            v = await st()
            verdict("two fingers together: back to its own size, in the middle", v["s"] == 1 and v["x"] == 0 and v["y"] == 0, v["s"], v["x"])

            # a single tap hides the bars and shows them again
            await tap_at(W / 2, H / 2)
            await asyncio.sleep(0.5)
            verdict("a single tap hides the bars", (await st())["bare"])
            await tap_at(W / 2, H / 2)
            await asyncio.sleep(0.5)
            verdict("…and brings them back", not (await st())["bare"])

            # a short pull down springs back; a long one closes
            await swipe(W / 2, H / 2, W / 2, H / 2 + 50, steps=5)
            verdict("a short pull down springs back", await st() is not None)
            await swipe(W / 2, H / 2, W / 2, H / 2 + 300)
            verdict("a swipe down closes", await st() is None)
            await asyncio.sleep(0.3)
            verdict("…and leaves nothing in the history", not await in_history())

            await tap(".msg img.att", 1)
            await until("!!document.querySelector('.viewer')")
            verdict("the second picture opens as 2 / 2", (await st())["n"] == "2 / 2")
            await js("history.back()")
            await asyncio.sleep(0.4)
            verdict("Back closes it", await st() is None)
            verdict("…and the session stays", "#/s/" in await js("location.hash"))

            # before sending: a thumbnail opens the viewer with Crop and Remove
            doc = await cmd("DOM.getDocument", depth=-1, pierce=True)
            node = await cmd("DOM.querySelector", nodeId=doc["root"]["nodeId"], selector="input[type=file]")
            await cmd("DOM.setFileInputFiles", files=[pic, pic], nodeId=node["nodeId"])
            await until("document.querySelectorAll('.thumb').length === 2", 150)
            await asyncio.sleep(0.3)
            await tap(".thumb-view", 1)
            await until("!!document.querySelector('.viewer .v-bar')")
            v = await st()
            verdict("a thumbnail opens the viewer at its picture", v and v["n"] == "2 / 2", v and v["n"])
            verdict("…with Crop and Remove", v and v["bar"])
            await shot("4-before-sending.png")

            await tap(".v-bar .v-b", 0, wait=0.6)
            ok = await until("!!document.querySelector('.ed-stage canvas')")
            verdict("Crop opens the editor in its place", ok and await st() is None)
            verdict("…once in the history", await js("history.state && history.state.overlay") is True)
            await shot("5-crop.png")
            await tap(".ed-bar .ed-b:first-child", wait=0.5)
            verdict("Cancel goes back to the message", await js("!document.querySelector('.ed') && !document.querySelector('.viewer')"))
            verdict("…and leaves nothing in the history", not await in_history())

            await tap(".thumb-view", 0)
            await until("!!document.querySelector('.viewer .v-bar')")
            await tap(".v-bar .v-b", 1)
            v = await st()
            verdict("Remove takes the picture off, the viewer stays on the other", v and v["n"] is None
                    and await js("document.querySelectorAll('.thumb').length") == 1, v and v["n"])
            await tap(".v-bar .v-b", 1, wait=0.5)
            verdict("removing the last one closes the viewer", await st() is None
                    and await js("document.querySelectorAll('.thumb').length") == 0)
            verdict("…and leaves nothing in the history", not await in_history())
            await shot("6-after.png")
            verdict("no errors on the page", not errors, errors[:3])
    finally:
        p.kill()
    print("screenshots:", OUT)
    sys.exit(1 if failures else 0)


asyncio.run(main())
