"""What a message is written with, in headless Chrome over DevTools, on the stand, with real taps: a picture and a file
are two pickers — the new task form shows both buttons, the composer's paperclip opens a menu of the two; each opens the
system's picker with its own filter (pictures only / any file), a picked picture lands as a thumbnail and the menu is
gone. And a session read from its end keeps the project, the session and its state in a bar at the top; scrolled back
to the header, the bar goes. A session has no tab bar: Home is in its header and in the bar, and a session started from
the form replaces the form in the history — Back leads where the form was opened from.
  STAND_LANG=ru HOLD=300 ~/.local/share/pult/venv/bin/python tools/stand.py > /tmp/stand.out &
  ~/.local/share/pult/venv/bin/python tools/compose_check.py /tmp/stand.out [out_dir]
Chrome is not Telegram: whether a phone's gallery or file manager comes back with the file is seen only on the phone.
Screenshots go to out_dir (a temporary folder by default). Exit 1 on a failed check."""
import asyncio, base64, json, os, struct, subprocess, sys, tempfile, zlib
import aiohttp

URLS = dict(line.split(" ", 1) for line in open(sys.argv[1]).read().split("\n") if line[:4] in ("NEW ", "SESS"))
OUT = sys.argv[2] if len(sys.argv) > 2 else tempfile.mkdtemp(prefix="pult-compose-")
os.makedirs(OUT, exist_ok=True)
import _cdp  # noqa: E402  (tools/_cdp.py: where Chrome is, free ports, a profile that goes — review 2026-10-27, Т9)
CHROME = _cdp.CHROME
PORT = _cdp.free_port()
failures = []


def verdict(name, ok, *info):
    print(("ok   " if ok else "FAIL ") + name, *info)
    if not ok:
        failures.append(name)


def png(path):
    rows = b"".join(b"\x00" + bytes((60, 120, 200)) * 40 for _ in range(30))
    chunk = lambda t, d: struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xffffffff)
    with open(path, "wb") as f:
        f.write(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 40, 30, 8, 2, 0, 0, 0))
                + chunk(b"IDAT", zlib.compress(rows)) + chunk(b"IEND", b""))


async def main():
    pic = os.path.join(OUT, "screenshot.png")
    png(pic)
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
            n, errors, choosers = 0, [], []

            async def cmd(method, **params):
                nonlocal n
                n += 1
                await ws.send_str(json.dumps({"id": n, "method": method, "params": params}))
                while True:
                    m = json.loads((await ws.receive()).data)
                    if m.get("method") == "Runtime.exceptionThrown":
                        errors.append(m["params"]["exceptionDetails"].get("exception", {}).get("description"))
                    if m.get("method") == "Page.fileChooserOpened":
                        choosers.append(m["params"])
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

            async def tap(sel, i=0):
                """A finger on the element's middle — not el.click(): what is on top there gets it."""
                r = await js("(() => { const el = document.querySelectorAll(%s)[%d]; if (!el) return null; el.scrollIntoView({block: 'nearest'});"
                             " const b = el.getBoundingClientRect(); return [b.left + b.width / 2, b.top + b.height / 2]; })()" % (json.dumps(sel), i))
                if not r:
                    raise RuntimeError("nothing to tap: " + sel)
                await cmd("Input.dispatchTouchEvent", type="touchStart", touchPoints=[{"x": r[0], "y": r[1]}])
                await cmd("Input.dispatchTouchEvent", type="touchEnd", touchPoints=[])
                await asyncio.sleep(0.5)

            async def chooser():
                """The picker the last tap opened: its input's filter, '' for any file; None — none opened."""
                await js("1")
                if not choosers:
                    return None
                c = choosers.pop()
                obj = await cmd("DOM.resolveNode", backendNodeId=c["backendNodeId"])
                r = await cmd("Runtime.callFunctionOn", objectId=obj["object"]["objectId"], returnByValue=True,
                              functionDeclaration="function () { return this.accept; }")
                return {"accept": r["result"]["value"], "multiple": c["mode"] == "selectMultiple", "node": c["backendNodeId"]}

            await cmd("Page.enable")
            await cmd("Runtime.enable")
            await cmd("DOM.enable")
            await cmd("Emulation.setDeviceMetricsOverride", width=412, height=860, deviceScaleFactor=2, mobile=True)
            await cmd("Emulation.setTouchEmulationEnabled", enabled=True, maxTouchPoints=5)
            await cmd("Page.setInterceptFileChooserDialog", enabled=True)

            # the new task form: two buttons side by side
            await cmd("Page.navigate", url=URLS["NEW"])
            verdict("the form shows two pickers", await until("document.querySelectorAll('.attach-row label.clip').length === 2", 150))
            await shot("1-new.png")
            await tap(".attach-row label.clip", 0)
            c = await chooser()
            verdict("Picture opens a picker of pictures", c and c["accept"] == "image/*" and c["multiple"], c)
            await cmd("DOM.setFileInputFiles", files=[pic], backendNodeId=c["node"])
            verdict("the picked picture is a thumbnail", await until("!!document.querySelector('.thumb:not(.doc) img')"))
            await tap(".attach-row label.clip", 1)
            c = await chooser()
            verdict("File opens a picker of any file", c and c["accept"] == "" and c["multiple"], c)
            await shot("2-new-picked.png")

            # the composer: the paperclip opens a menu of the two
            await cmd("Page.navigate", url="about:blank")
            await cmd("Page.navigate", url=URLS["SESS"])
            verdict("the session shows the paperclip", await until("!!document.querySelector('.composer .attach button.clip')", 150))
            await tap(".composer .attach button.clip")
            verdict("a tap opens the menu, no picker yet", await until("document.querySelectorAll('.attach-menu .opt').length === 2") and not choosers)
            await shot("3-menu.png")
            await tap(".attach-menu .opt", 0)
            c = await chooser()
            verdict("Picture opens a picker of pictures", c and c["accept"] == "image/*", c)
            verdict("the menu is gone", await until("!document.querySelector('.attach-menu')"))
            await cmd("DOM.setFileInputFiles", files=[pic], backendNodeId=c["node"])
            verdict("the picked picture is a thumbnail", await until("!!document.querySelector('.composer .thumb:not(.doc) img')"))
            await tap(".composer .attach button.clip")
            await until("!!document.querySelector('.attach-menu')")
            await tap(".attach-menu .opt", 1)
            c = await chooser()
            verdict("File opens a picker of any file", c and c["accept"] == "", c)
            await tap(".composer .attach button.clip")
            await until("!!document.querySelector('.attach-menu')")
            await tap(".backdrop")
            verdict("a tap beside the menu closes it", await until("!document.querySelector('.attach-menu')"))
            verdict("the history entry went with it", await js("!(history.state && history.state.overlay)"))

            # where you are: the session read from its end
            await js("window.scrollTo(0, document.documentElement.scrollHeight)")
            ok = await until("!!document.querySelector('.where-bar')")
            bar = await js("(document.querySelector('.where-bar') || {}).textContent || ''")
            head = await js("[document.querySelector('.sess-h h2').textContent, document.querySelector('.crumb') ? document.querySelector('.crumb').textContent : '']")
            verdict("at the end a bar shows the project and the session", ok and head[0] in bar and head[1] in bar, repr(bar))
            verdict("the bar is at the top of the screen", await js("Math.round(document.querySelector('.sess-top').getBoundingClientRect().top) === 0"))
            await shot("4-where.png")
            # earlier history loads by itself as the top comes near and keeps the place being read, so one scroll up
            # doesn't reach the header of a long session: up again until all of it is in (the check used to catch the
            # moment before the load — a race, 2026-10-27); then the header is on screen and the bar goes
            for _ in range(40):
                await js("window.scrollTo(0, 0)")
                if await until("!document.querySelector('.earlier')", 15):
                    break
            await js("window.scrollTo(0, 0)")
            verdict("at the header the bar goes", await until("!document.querySelector('.where-bar')"))

            # home from a session: it has no tab bar — the header and the bar have the way straight there
            home_on = "(document.querySelector('nav.tabs a.on') || {}).getAttribute && document.querySelector('nav.tabs a.on').getAttribute('href') === '#/' && !document.querySelector('.session')"
            size = await js("(() => { const h = document.querySelector('.sess-h a.home-l'); if (!h) return null; const b = h.getBoundingClientRect(); return [b.width, b.height]; })()")
            verdict("the header has Home, finger-sized", size and min(size) >= 36, size)
            await shot("5-head.png")
            await js("window.scrollTo(0, document.documentElement.scrollHeight)")
            await until("!!document.querySelector('.where-bar a.home-l')")
            await shot("6-where-home.png")
            proj = await js("document.querySelector('.sess-h .crumb').getAttribute('href')")
            await tap(".where-bar a.home-l")
            verdict("Home in the bar leads home", await until(home_on))
            # a session started from the form: Back skips the form, it is done with — the stand's projects are made-up
            # paths, the form lists none, so the form comes from a project's "New task"; the stand answers it itself
            await js("location.hash = %s" % json.dumps(proj))
            await until("!!document.querySelector('.stick .btn.wide')")
            await tap(".stick .btn.wide")
            await until("!!document.querySelector('.form textarea')")
            await js("(() => { const ta = document.querySelector('.form textarea'); Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value').set.call(ta, 'check'); ta.dispatchEvent(new Event('input', {bubbles: true})); })()")
            await until("!document.querySelector('.form > .btn.wide').disabled")
            await tap(".form > .btn.wide")
            verdict("the started session opens", await until("location.hash.startsWith('#/s/') && !!document.querySelector('.sess-h a.home-l')", 150))
            await shot("7-started.png")
            await js("history.back()")
            verdict("Back from it leads to the project, not to the form",
                    await until("location.hash === %s && !document.querySelector('.form')" % json.dumps(proj)), await js("location.hash"))
            verdict("no script errors", not errors, errors)
    finally:
        p.kill()
    print("screenshots:", OUT)
    sys.exit(1 if failures else 0)


asyncio.run(main())
