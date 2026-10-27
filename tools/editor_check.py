"""The app's picture editor in headless Chrome over DevTools, on the stand: attach a four-colour picture (red, green /
blue, yellow), cut, turn, mirror, fix a proportion, cancel, Back — and check what the attachment became: its size and
the colour near each corner. Touches go through Chrome's touch emulation, as from a phone.
  HOLD=300 ~/.local/share/pult/venv/bin/python tools/stand.py > /tmp/stand.out &
  ~/.local/share/pult/venv/bin/python tools/editor_check.py "$(grep '^SESS ' /tmp/stand.out | cut -d' ' -f2)" [out_dir]
The NEW screen works as well. Screenshots of the editor go to out_dir (a temporary folder by default). Exit 1 on a
failed check. Selectors are by class and order, not by text: the stand runs in either language."""
import asyncio, base64, json, os, struct, subprocess, sys, tempfile, zlib
import aiohttp

URL = sys.argv[1]
OUT = sys.argv[2] if len(sys.argv) > 2 else tempfile.mkdtemp(prefix="pult-editor-")
import _cdp  # noqa: E402  (tools/_cdp.py: where Chrome is, free ports, a profile that goes — review 2026-10-27, Т9)
CHROME = _cdp.CHROME
PORT = _cdp.free_port()
RED, GREEN, BLUE, YELLOW = (255, 0, 0), (0, 255, 0), (0, 0, 255), (255, 255, 0)
RESET, CANCEL, DONE = ".ed-top .ed-b", ".ed-bar .ed-b:first-child", ".ed-b.ok"
TURN, MIRROR = ".ed-bar .ed-i:nth-child(2)", ".ed-bar .ed-i:nth-child(3)"
RATIO = ".ed-r:nth-child(%d)"          # 1 free, 2 original, 3 1:1, 4 4:3, 5 16:9

# the n-th thumbnail: its size and the colour near each corner and in the middle
PROBE = """(async () => {
  const im = document.querySelectorAll('.thumb img')[%d]; if (!im) return null;
  const i = new Image(); i.src = im.src; await i.decode();
  const c = document.createElement('canvas'); c.width = i.naturalWidth; c.height = i.naturalHeight;
  const g = c.getContext('2d'); g.drawImage(i, 0, 0);
  const at = (fx, fy) => Array.from(g.getImageData(Math.floor(fx * (c.width - 1)), Math.floor(fy * (c.height - 1)), 1, 1).data.slice(0, 3));
  return { w: c.width, h: c.height, tl: at(.1, .1), tr: at(.9, .1), bl: at(.1, .9), br: at(.9, .9), mid: at(.5, .5) };
})()"""
failures = []


def png(path, w, h):
    rows = []
    for y in range(h):
        a, b = (RED, GREEN) if y < h // 2 else (BLUE, YELLOW)
        rows.append(b"\x00" + bytes(a) * (w // 2) + bytes(b) * (w - w // 2))
    chunk = lambda t, d: struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xffffffff)
    with open(path, "wb") as f:
        f.write(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
                + chunk(b"IDAT", zlib.compress(b"".join(rows), 9)) + chunk(b"IEND", b""))


def verdict(name, ok, *info):
    print(("ok   " if ok else "FAIL ") + name, *info)
    if not ok:
        failures.append(name)


def check(name, got, w, h, corners=None, all_=None, tol=4):
    near = lambda c, want: all(abs(a - b) <= 40 for a, b in zip(c, want))
    ok = bool(got) and abs(got["w"] - w) <= tol and abs(got["h"] - h) <= tol
    if ok and corners:
        ok = all(near(got[k], want) for k, want in zip(("tl", "tr", "bl", "br"), corners))
    if ok and all_:
        ok = all(near(got[k], all_) for k in ("tl", "tr", "bl", "br", "mid"))
    verdict(name, ok, got)


async def main():
    small, big = os.path.join(OUT, "quad-400.png"), os.path.join(OUT, "quad-3200.png")
    png(small, 400, 300)
    png(big, 3200, 2400)
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
                d = await cmd("Page.captureScreenshot", format="png")
                open(os.path.join(OUT, name), "wb").write(base64.b64decode(d["data"]))

            async def rect(sel):
                return await js("(() => { const r = document.querySelector(%s).getBoundingClientRect(); return {l: r.left, t: r.top, w: r.width, h: r.height}; })()" % json.dumps(sel))

            async def tap(sel):
                await js("document.querySelector(%s).click()" % json.dumps(sel))
                await asyncio.sleep(0.3)

            async def edit():                # the first thumbnail → the viewer → Crop, once the editor's picture is drawn
                await tap(".thumb-view")
                await until("!!document.querySelector('.viewer .v-bar')")
                await tap(".v-bar .v-b")
                await until("!!document.querySelector('.ed-stage canvas')")
                await asyncio.sleep(0.2)

            async def done():
                await tap(DONE)
                await until("!document.querySelector('.ed')")
                await asyncio.sleep(0.3)

            async def attach(path):
                doc = await cmd("DOM.getDocument", depth=-1, pierce=True)
                node = await cmd("DOM.querySelector", nodeId=doc["root"]["nodeId"], selector="input[type=file]")
                await cmd("DOM.setFileInputFiles", files=[path], nodeId=node["nodeId"])
                await until("document.querySelectorAll('.thumb').length", 150)
                await asyncio.sleep(0.3)

            async def drag(x0, y0, x1, y1, steps=8, mid_shot=None):
                await cmd("Input.dispatchTouchEvent", type="touchStart", touchPoints=[{"x": x0, "y": y0}])
                for i in range(1, steps + 1):
                    await cmd("Input.dispatchTouchEvent", type="touchMove",
                              touchPoints=[{"x": x0 + (x1 - x0) * i / steps, "y": y0 + (y1 - y0) * i / steps}])
                    await asyncio.sleep(0.02)
                if mid_shot:
                    await asyncio.sleep(0.1)
                    await shot(mid_shot)
                await cmd("Input.dispatchTouchEvent", type="touchEnd", touchPoints=[])
                await asyncio.sleep(0.15)

            async def corner_to_middle(corner):     # "se" or "nw" of the frame → the middle of the picture
                cv, fr = await rect(".ed-stage canvas"), await rect(".ed-frame")
                x0, y0 = (fr["l"] + fr["w"] - 2, fr["t"] + fr["h"] - 2) if corner == "se" else (fr["l"] + 2, fr["t"] + 2)
                return cv, (x0, y0, cv["l"] + cv["w"] / 2 + 1, cv["t"] + cv["h"] / 2 + 1)

            await cmd("Runtime.enable")
            await cmd("Emulation.setDeviceMetricsOverride", width=412, height=860, deviceScaleFactor=2, mobile=True)
            await cmd("Emulation.setTouchEmulationEnabled", enabled=True, maxTouchPoints=1)
            await cmd("Page.enable")
            await cmd("Page.navigate", url=URL)
            await asyncio.sleep(4)

            await attach(small)
            check("attached as is", await js(PROBE % 0), 400, 300, (RED, GREEN, BLUE, YELLOW))
            await shot("0-thumb.png")

            await edit()
            await shot("1-open.png")
            cv, line = await corner_to_middle("se")
            await drag(*line, mid_shot="2-drag.png")
            await done()
            check("cut to the red quarter", await js(PROBE % 0), 200, 150, all_=RED)

            # the last move merged into the lift: the frame still lands where the finger lifted
            await edit()
            await tap(RESET)
            cv, (x0, y0, x1, y1) = await corner_to_middle("se")
            await js("""(() => { const st = document.querySelector('.ed-stage');
              const ev = (type, x, y) => st.dispatchEvent(new PointerEvent(type, {pointerId: 7, clientX: x, clientY: y, bubbles: true, isPrimary: true, pointerType: 'touch'}));
              ev('pointerdown', %f, %f); ev('pointermove', %f, %f);
              return new Promise(ok => setTimeout(() => { ev('pointerup', %f, %f); ok(); }, 50)); })()"""
                     % (x0, y0, (x0 + x1) / 2, (y0 + y1) / 2, x1, y1))
            await asyncio.sleep(0.2)
            share = (await rect(".ed-frame"))["w"] / cv["w"]
            verdict("lift without the last move", abs(share - 0.5) < 0.02, round(share, 3))
            await done()

            await edit()
            share = (await rect(".ed-frame"))["w"] / (await rect(".ed-stage canvas"))["w"]
            verdict("reopened with its frame", share < 0.6, round(share, 3))
            await tap(TURN)
            await shot("3-turned.png")
            await done()
            check("the cut, turned left", await js(PROBE % 0), 150, 200, all_=RED)

            for name, steps, size, corners in (
                    ("mirrored", [MIRROR], (400, 300), (GREEN, RED, YELLOW, BLUE)),
                    ("turned left", [TURN], (300, 400), (GREEN, YELLOW, RED, BLUE)),
                    ("mirrored, then turned left", [MIRROR, TURN], (300, 400), (RED, BLUE, GREEN, YELLOW)),
                    ("mirrored, turned four times", [MIRROR, TURN, TURN, TURN, TURN], (400, 300), (GREEN, RED, YELLOW, BLUE)),
                    ("1:1", [RATIO % 3], (300, 300), (RED, GREEN, BLUE, YELLOW))):
                await edit()
                await tap(RESET)
                for st in steps:
                    await tap(st)
                await done()
                check(name, await js(PROBE % 0), *size, corners)

            # 16:9 on an upright picture is 9:16, and a corner keeps the proportion
            await edit()
            await tap(RESET)
            await tap(TURN)
            labels = await js("[...document.querySelectorAll('.ed-r')].map(b => b.textContent)")
            verdict("upright labels", labels[3:] == ["3:4", "9:16"], labels)
            await tap(RATIO % 5)
            fr = await rect(".ed-frame")
            await drag(fr["l"] + 2, fr["t"] + 2, fr["l"] + 60, fr["t"] + 30)
            await shot("4-ratio.png")
            await done()
            got = await js(PROBE % 0)
            verdict("9:16 kept", abs(got["w"] / got["h"] - 9 / 16) < 0.02, got["w"], got["h"])

            before = await js("document.querySelector('.thumb img').src")
            await edit()
            await tap(RESET)
            await tap(CANCEL)
            verdict("Cancel keeps the picture", not await js("!!document.querySelector('.ed')")
                    and await js("document.querySelector('.thumb img').src") == before)
            await edit()
            await js("history.back()")
            await asyncio.sleep(0.4)
            verdict("Back closes the editor, not the screen", not await js("!!document.querySelector('.ed')")
                    and await js("document.querySelectorAll('.thumb').length") == 1)

            # a quarter of a big picture is cut from the original: 1600 × 1200, not a quarter of the shrunk 1600 × 1200
            await tap(".thumb-x")
            await attach(big)
            check("big, as is → 1600", await js(PROBE % 0), 1600, 1200, (RED, GREEN, BLUE, YELLOW))
            await edit()
            cv, line = await corner_to_middle("nw")
            await drag(*line)
            await done()
            check("big, the yellow quarter at full size", await js(PROBE % 0), 1600, 1200, all_=YELLOW, tol=25)
            verdict("no page errors", not errors, errors)
    finally:
        p.terminate()
    print("screenshots:", OUT)
    print("FAILURES:", failures or "none")
    sys.exit(1 if failures else 0)


asyncio.run(main())
