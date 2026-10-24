"""Links to project files in Claude's words (stage F5) in headless Chrome over DevTools, on the stand with STAND_FILES=1,
with touches as from a phone: a page (.md) opens over the chat and its own link opens the next file over it, Back goes
one step down and the chat is where it was; a link to a line puts that line in the middle, marked; the folder in a file's
header lists it; a project's HTML page is drawn with no script running, and Text shows its source; a picture opens on
the whole screen with To Telegram; a folder lists its files; a file the app can't show, a secret and a file outside the
project say why. Nothing is left in the history.
  STAND_FILES=1 STAND_PORT=18131 HOLD=300 ~/.local/share/pult/venv/bin/python tools/stand.py > /tmp/stand.out &
  ~/.local/share/pult/venv/bin/python tools/fileview_check.py "$(grep '^SESS ' /tmp/stand.out | cut -d' ' -f2)" [out_dir]
Screenshots go to out_dir (a temporary folder by default). Exit 1 on a failed check. Selectors are by class and order,
not by text: the stand runs in either language."""
import asyncio, base64, json, os, subprocess, sys, tempfile
import aiohttp

URL = sys.argv[1]
OUT = sys.argv[2] if len(sys.argv) > 2 else tempfile.mkdtemp(prefix="pult-fileview-")
os.makedirs(OUT, exist_ok=True)
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
PORT = 9341
W, H = 412, 860
failures = []


def verdict(name, ok, *info):
    print(("ok   " if ok else "FAIL ") + name, *info)
    if not ok:
        failures.append(name)


# the file screens over the chat: how many, and the top one's title, kind and line count
STATE = """(() => { const fs = [...document.querySelectorAll('.fv')];
  const top = fs[fs.length - 1];
  return { n: fs.length, viewer: !!document.querySelector('.viewer'),
    title: top ? top.querySelector('.fv-h b').textContent : null,
    md: !!(top && top.querySelector('.fv-md')), code: top ? top.querySelectorAll('.fv-code .ln').length : 0,
    page: !!(top && top.querySelector('iframe.fv-page')), rows: top ? top.querySelectorAll('.fv-row').length : 0,
    empty: top && top.querySelector('.fv-body .empty') ? top.querySelector('.fv-body .empty').textContent : null,
    send: !!(top && top.querySelector('.fv-bar .btn')) };
})()"""


async def main():
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

            async def back(wait=0.5):
                await js("history.back()")
                await asyncio.sleep(wait)

            async def link(k, wait=0.2):                # the k-th file link of the chat's last reply, tapped
                await js("document.querySelectorAll('.msg .md a.flink')[%d].scrollIntoView({block: 'center'})" % k)
                await asyncio.sleep(0.2)
                y = await js("scrollY")
                await tap(".msg .md a.flink", k, wait)
                return y

            await cmd("Runtime.enable")
            await cmd("Emulation.setDeviceMetricsOverride", width=W, height=H, deviceScaleFactor=2, mobile=True)
            await cmd("Emulation.setTouchEmulationEnabled", enabled=True, maxTouchPoints=2)
            await cmd("Page.enable")
            await cmd("Page.navigate", url=URL)
            ok = await until("document.querySelectorAll('.msg .md a.flink').length >= 8", 150)
            verdict("the reply's file links are taps", ok, await js("document.querySelectorAll('.msg .md a.flink').length"))
            verdict("…with no address to follow", await js("[...document.querySelectorAll('a.flink')].every(a => !a.hasAttribute('href'))"))
            await js("window.__ran = false; addEventListener('message', () => { window.__ran = true; })")
            await asyncio.sleep(0.5)
            await shot("0-chat.png")

            # a page: README.md over the chat, its own link opens errors.py over it; Back, Back — the chat where it was
            y0 = await link(0)
            ok = await until("!!document.querySelector('.fv .fv-md h4')")
            s = await st()
            verdict("README.md opens over the chat as a page", ok and s["n"] == 1 and s["title"] == "README.md", s)
            verdict("…in the history: Back closes it", await in_history())
            verdict("…with To Telegram", s["send"])
            await shot("1-readme.png")
            await tap(".fv .fv-md a.flink", 1, wait=0.2)
            ok = await until("document.querySelectorAll('.fv').length === 2 && document.querySelectorAll('.fv')[1].querySelectorAll('.ln').length > 40")
            s = await st()
            verdict("a link inside the page opens the next file over it", ok and s["title"] == "errors.py", s)
            await shot("2-code.png")
            await back()
            s = await st()
            verdict("Back: one step down, the page again", s["n"] == 1 and s["md"], s)
            await back()
            s = await st()
            verdict("Back again: the chat, where it was", s["n"] == 0 and abs(await js("scrollY") - y0) < 4, s, await js("scrollY"), y0)
            verdict("…nothing left in the history", not await in_history())

            # a link to a line: that line in the middle of the screen, marked
            await link(1)
            ok = await until("!!document.querySelector('.fv .ln.hit')")
            r = await js("(() => { const r = document.querySelector('.fv .ln.hit').getBoundingClientRect(); return [r.top, r.bottom, document.querySelector('.fv .ln.hit').id]; })()") if ok else None
            verdict("errors.py:12 marks line 12", ok and r[2] == "L12", r)
            verdict("…in the middle of the screen", ok and H * 0.25 < r[0] < H * 0.75, r)
            await shot("3-line.png")
            # the folder in the header lists it
            await tap(".fv .fv-dir", 0, wait=0.2)
            ok = await until("document.querySelectorAll('.fv').length === 2 && document.querySelectorAll('.fv')[1].querySelectorAll('.fv-row').length > 0")
            s = await st()
            verdict("the folder in the header lists the folder", ok and s["title"] == "checkout" and s["rows"] == 1, s)
            await back()
            await back()

            # a project's HTML page: drawn, no script ran; Text shows its source
            await link(2)
            ok = await until("!!document.querySelector('.fv iframe.fv-page')")
            await asyncio.sleep(0.8)
            verdict("design.html is drawn as a page", ok and await js("document.querySelector('iframe.fv-page').getAttribute('sandbox')") == "")
            verdict("…and its script didn't run", not await js("window.__ran"))
            await shot("4-html.png")
            await tap(".fv .fv-t", 0, wait=0.3)
            s = await st()
            verdict("Text shows its source", s["code"] >= 1 and await js("document.querySelector('.fv .ln .c').textContent.startsWith('<!doctype')"), s)
            await back()

            # a picture: on the whole screen, To Telegram sends it to the topic
            await link(3)
            ok = await until("!!document.querySelector('.viewer .v-pic img') && document.querySelector('.viewer .v-pic img').naturalWidth > 0")
            verdict("screen.png opens on the whole screen", ok and await js("document.querySelector('.viewer img').naturalWidth") == 320)
            verdict("…with To Telegram", await js("!!document.querySelector('.viewer .v-bar .v-b')"))
            await shot("5-picture.png")
            await tap(".viewer .v-bar .v-b", 0, wait=0.2)
            ok = await until("!!document.querySelector('.toast')", 50)
            verdict("To Telegram sends it: a note", ok)
            await back()
            verdict("Back closes the picture", (await st())["viewer"] is False and not await in_history())

            # a folder: its files; a picture in it opens over the list
            await link(4)
            ok = await until("document.querySelectorAll('.fv .fv-row').length === 1")
            verdict("media/ lists its files", ok, await st())
            await shot("6-folder.png")
            await tap(".fv .fv-row", 0, wait=0.2)
            ok = await until("!!document.querySelector('.viewer .v-pic img') && document.querySelector('.viewer .v-pic img').naturalWidth > 0")
            verdict("a picture in the list opens on the whole screen", ok)
            await back()
            s = await st()
            verdict("Back: the list again", s["n"] == 1 and s["rows"] == 1 and not s["viewer"], s)
            await back()

            # what the app doesn't show: says why
            for k, name, want in ((5, "export.bin", "send"), (6, ".env", "secret"), (7, "hosts", "outside")):
                await link(k)
                ok = await until("!!document.querySelector('.fv .fv-body .empty') && !/…$/.test(document.querySelector('.fv .fv-body .empty').textContent)")
                s = await st()
                verdict("%s says why it isn't shown" % name, ok and s["empty"] and (s["send"] if want == "send" else not s["send"]), s)
                await shot("7-%s.png" % name.strip("."))
                await back()
            verdict("nothing left over the chat or in the history", (await st())["n"] == 0 and not await in_history())
            verdict("no errors on the page", not errors, errors[:3])
    finally:
        p.kill()
    print("screenshots:", OUT)
    sys.exit(1 if failures else 0)


asyncio.run(main())
