"""Your message's ticks (Q56), in headless Chrome over DevTools, on the stand, with real taps: a message sent while
Claude works is in the chat at once — the clock, then ✓ and "Claude will read it after the current step"; the field is
empty. When the tab reads it (the stand's STAND_TICKS s later: the transcript, then the hook) it is the chat's own
message, "during the turn", with ✓✓ — once, not twice. A message dropped before it was read is crossed out, with why;
a tap puts its words back in the field. Every message of yours in the chat has ✓✓.
  STAND_TICKS=4 STAND_LANG=ru HOLD=300 ~/.local/share/pult/venv/bin/python tools/stand.py > /tmp/stand.out &
  ~/.local/share/pult/venv/bin/python tools/ticks_check.py /tmp/stand.out [out_dir]
Screenshots go to out_dir (a temporary folder by default). Exit 1 on a failed check."""
import asyncio, base64, json, os, subprocess, sys, tempfile
import aiohttp

URLS = dict(line.split(" ", 1) for line in open(sys.argv[1]).read().split("\n") if line[:5] == "SESS ")
OUT = sys.argv[2] if len(sys.argv) > 2 else tempfile.mkdtemp(prefix="pult-ticks-")
os.makedirs(OUT, exist_ok=True)
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
PORT = 9338
failures = []


def verdict(name, ok, *info):
    print(("ok   " if ok else "FAIL ") + name, *info)
    if not ok:
        failures.append(name)


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

            async def tap(sel, i=0):
                """A finger on the element's middle — not el.click(): what is on top there gets it."""
                r = await js("(() => { const el = document.querySelectorAll(%s)[%d]; if (!el) return null; el.scrollIntoView({block: 'nearest'});"
                             " const b = el.getBoundingClientRect(); return [b.left + b.width / 2, b.top + b.height / 2]; })()" % (json.dumps(sel), i))
                if not r:
                    raise RuntimeError("nothing to tap: " + sel)
                await cmd("Input.dispatchTouchEvent", type="touchStart", touchPoints=[{"x": r[0], "y": r[1]}])
                await cmd("Input.dispatchTouchEvent", type="touchEnd", touchPoints=[])

            async def write(words):
                await js("(() => { const ta = document.querySelector('.composer textarea'); Object.getOwnPropertyDescriptor("
                         "HTMLTextAreaElement.prototype, 'value').set.call(ta, %s); ta.dispatchEvent(new Event('input', {bubbles: true})); })()"
                         % json.dumps(words))
                await until("!document.querySelector('.composer .btn.send').disabled")

            # the chat's own messages with these words, and those on their way
            mine = lambda w: "[...document.querySelectorAll('.msg.me:not(.out)')].filter((e) => e.textContent.includes(%s))" % json.dumps(w)
            way = lambda w, st="": "[...document.querySelectorAll('.msg.me.out%s')].filter((e) => e.textContent.includes(%s))" % (st, json.dumps(w))

            await cmd("Page.enable")
            await cmd("Runtime.enable")
            await cmd("Emulation.setDeviceMetricsOverride", width=412, height=860, deviceScaleFactor=2, mobile=True)
            await cmd("Emulation.setTouchEmulationEnabled", enabled=True, maxTouchPoints=5)
            await cmd("Page.navigate", url=URLS["SESS"])
            verdict("the session opens", await until("!!document.querySelector('.composer textarea')", 150))
            verdict("your messages in the chat have ✓✓",
                    await js("[...document.querySelectorAll('.msg.me')].length > 0 && [...document.querySelectorAll('.msg.me')]"
                             ".every((e) => e.querySelector('.tick.read'))"))

            # sent while Claude works: in the chat at once, then ✓ and why it waits
            w1 = "Проверь ещё и пустую корзину"
            await write(w1)
            await tap(".composer .btn.send")
            verdict("the message is in the chat at once", await until("%s.length === 1" % way(w1), 10))
            verdict("the field is empty", await js("document.querySelector('.composer textarea').value === ''"))
            verdict("✓ — the computer has it", await until("%s.length === 1 && !!%s[0].querySelector('.tick.sent')" % (way(w1, ".sent"), way(w1, ".sent")), 30))
            hint = await js("(document.querySelector('.out-hint') || {}).textContent || ''")
            verdict("it says Claude reads it after the current step", "после текущего шага" in hint or "after the current step" in hint, repr(hint))
            await js("window.scrollTo(0, document.documentElement.scrollHeight)")
            await shot("1-sent.png")
            # read at the tab's next step: the chat's own message, during the turn, ✓✓ — and only once
            verdict("✓✓ once Claude reads it", await until("%s.length === 0 && %s.length === 1" % (way(w1), mine(w1)), 100))
            got = await js("(() => { const e = %s[0]; return e ? [!!e.querySelector('.tick.read'), e.querySelector('.t').textContent] : null; })()" % mine(w1))
            verdict("…with ✓✓, during the turn", got and got[0] and ("во время хода" in got[1] or "during the turn" in got[1]), got)
            await asyncio.sleep(1.5)
            verdict("it is not shown twice", await js("%s.length === 0 && %s.length === 1" % (way(w1), mine(w1))))
            verdict("no hint left", await js("!document.querySelector('.out-hint')"))
            await js("window.scrollTo(0, document.documentElement.scrollHeight)")
            await shot("2-read.png")

            # dropped before it was read: crossed out, why; a tap puts the words back
            w2 = "Это не дойдёт #gone"
            await write(w2)
            await tap(".composer .btn.send")
            verdict("a dropped message is crossed out", await until("%s.length === 1" % way(w2, ".gone"), 100))
            why = await js("(document.querySelector('.out-hint.bad') || {}).textContent || ''")
            verdict("…with why", "Не дошло" in why or "Didn't reach" in why, repr(why))
            await js("window.scrollTo(0, document.documentElement.scrollHeight)")
            await shot("3-gone.png")
            await cmd("Emulation.setEmulatedMedia", features=[{"name": "prefers-color-scheme", "value": "dark"}])
            await shot("3-gone-dark.png")
            await cmd("Emulation.setEmulatedMedia", features=[{"name": "prefers-color-scheme", "value": "light"}])
            await tap(".msg.me.out.gone")
            verdict("a tap puts its words back in the field", await until("document.querySelector('.composer textarea').value === %s" % json.dumps(w2)))
            verdict("…and the crossed-out one goes", await until("%s.length === 0" % way(w2)))
            await shot("4-back.png")
            verdict("no script errors", not errors, errors)
    finally:
        p.kill()
    print("screenshots:", OUT)
    sys.exit(1 if failures else 0)


asyncio.run(main())
