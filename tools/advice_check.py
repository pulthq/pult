"""A question of several answers with Claude's advice among its options, in headless Chrome over DevTools, on the
stand, with real taps: the advised options ("(Recommended)") come checked and "Done" is on at once (the owner,
2026-10-27: advice takes one "Done", as a single choice takes one tap); a tap unchecks one; "Done" sends the rest —
what goes to the computer is read off the app's own socket — and the card says "Answer sent".
  STAND_ADVICE=1 STAND_LANG=ru STAND_PORT=18141 HOLD=300 ~/.local/share/pult/venv/bin/python tools/stand.py > /tmp/stand.out &
  ~/.local/share/pult/venv/bin/python tools/advice_check.py /tmp/stand.out [out_dir]
Screenshots go to out_dir (a temporary folder by default). Exit 1 on a failed check."""
import asyncio, base64, json, os, re, subprocess, sys, tempfile
import aiohttp

URLS = dict(line.split(" ", 1) for line in open(sys.argv[1]).read().split("\n") if line[:5] == "HOME ")
OUT = sys.argv[2] if len(sys.argv) > 2 else tempfile.mkdtemp(prefix="pult-advice-")
os.makedirs(OUT, exist_ok=True)
import _cdp  # noqa: E402  (tools/_cdp.py: where Chrome is, free ports, a profile that goes — review 2026-10-27, Т9)
CHROME = _cdp.CHROME
PORT = _cdp.free_port()
ADVICE = re.compile(r"\((?:recommended|recommend|рекомендую|рекомендуется|рекомендовано|рекоменд\.?)\)", re.I)   # pult_render.ADVICE_RE
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
                d = await cmd("Page.captureScreenshot", format="png")
                open(os.path.join(OUT, name), "wb").write(base64.b64decode(d["data"]))

            async def tap(sel, i=0):
                """A finger on the element's middle — not el.click(): what is on top there gets it."""
                r = await js("(() => { const el = document.querySelectorAll(%s)[%d]; if (!el) return null; el.scrollIntoView({block: 'center'});"
                             " const b = el.getBoundingClientRect(); return [b.left + b.width / 2, b.top + b.height / 2]; })()" % (json.dumps(sel), i))
                if not r:
                    raise RuntimeError("nothing to tap: " + sel)
                await cmd("Input.dispatchTouchEvent", type="touchStart", touchPoints=[{"x": r[0], "y": r[1]}])
                await cmd("Input.dispatchTouchEvent", type="touchEnd", touchPoints=[])
                await asyncio.sleep(0.5)

            await cmd("Page.enable")
            await cmd("Runtime.enable")
            await cmd("Emulation.setDeviceMetricsOverride", width=412, height=860, deviceScaleFactor=2, mobile=True)
            await cmd("Emulation.setTouchEmulationEnabled", enabled=True, maxTouchPoints=5)

            opts = "[...document.querySelectorAll('.card.ask .q:not(.done) .opt')].map((b) => [b.textContent.trim(), b.classList.contains('on')])"
            done = "document.querySelector('.card.ask .q:not(.done) > button.btn')"
            await cmd("Page.navigate", url=URLS["HOME"])
            verdict("Home shows the question with its three options", await until("%s.length === 3" % opts, 150), await js(opts))
            o = await js(opts)
            verdict("Claude's advice is checked, the rest isn't", o and all(on == bool(ADVICE.search(t)) for t, on in o)
                    and sum(on for _, on in o) == 2, o)
            verdict("\"Done\" is on at once", await js("!!%s && !%s.disabled" % (done, done)))
            checked = "getComputedStyle(document.querySelectorAll('.card.ask .q:not(.done) .opt')[%d]).backgroundColor"
            verdict("a checked option is filled, an unchecked one isn't", await js(checked % 0) != await js(checked % 1),
                    await js(checked % 0), await js(checked % 1))
            await js("document.querySelector('.card.ask').scrollIntoView({block: 'center'})")
            await shot("1-advice.png")
            await cmd("Emulation.setEmulatedMedia", features=[{"name": "prefers-color-scheme", "value": "dark"}])
            await asyncio.sleep(0.3)
            await shot("1-advice-dark.png")
            await cmd("Emulation.setEmulatedMedia", features=[{"name": "prefers-color-scheme", "value": "light"}])

            # what the app sends to the computer, off its own socket
            await js("(() => { window.__sent = []; const send = WebSocket.prototype.send; WebSocket.prototype.send = function (d) {"
                     " try { const m = JSON.parse(d); if (m.op === 'answer') window.__sent.push(m.args); } catch (e) {} return send.call(this, d); }; })()")
            first = o[0][0] if o else ""
            await tap(".card.ask .q:not(.done) .opt", 0)
            o2 = await js(opts)
            verdict("a tap unchecks a piece of advice", o2 and not o2[0][1] and o2[2][1], o2)
            await shot("2-unchecked.png")
            await tap(".card.ask .q:not(.done) > button.btn", 0)
            verdict("\"Done\" sends the answer", await until("window.__sent.length === 1"), await js("window.__sent"))
            sent = (await js("window.__sent") or [{}])[0]
            want = [t for t, on in (o2 or []) if on]
            verdict("the computer gets what is checked: the other piece of advice", sent.get("answers") == {"0": want}
                    and first not in json.dumps(sent, ensure_ascii=False), sent)
            verdict("the card says \"Answer sent\"", await until("!!document.querySelector('.card.rcpt')"))
            await shot("3-sent.png")
            verdict("no script errors", not errors, errors)
    finally:
        p.kill()
    print("screenshots:", OUT)
    sys.exit(1 if failures else 0)


asyncio.run(main())
