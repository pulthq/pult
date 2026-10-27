"""A question of several parts, in headless Chrome over DevTools, on the stand, with real taps: an answer to one part
keeps the card, that part shows its answer and the next one waits; the screen opened again shows the same (the
computer keeps the answers); the last part closes the card with "Answer sent", which stays 3 s with a bar running out,
though the computer drops the request at once — on Home and in a session (a permission there). And "your move" is one
line by time, questions and permissions among the sessions that wait: the freshest on top, the longest at the bottom.
  STAND_ASK2=1 STAND_LANG=ru HOLD=300 ~/.local/share/pult/venv/bin/python tools/stand.py > /tmp/stand.out &
  ~/.local/share/pult/venv/bin/python tools/ask_check.py /tmp/stand.out [out_dir]
Screenshots go to out_dir (a temporary folder by default). Exit 1 on a failed check."""
import asyncio, base64, json, os, re, subprocess, sys, tempfile, time
import aiohttp

URLS = dict(line.split(" ", 1) for line in open(sys.argv[1]).read().split("\n") if line[:5] in ("HOME ", "SESS "))
OUT = sys.argv[2] if len(sys.argv) > 2 else tempfile.mkdtemp(prefix="pult-ask-")
os.makedirs(OUT, exist_ok=True)
import _cdp  # noqa: E402  (tools/_cdp.py: where Chrome is, free ports, a profile that goes — review 2026-10-27, Т9)
CHROME = _cdp.CHROME
PORT = _cdp.free_port()
failures = []


def minutes(text):
    """ "ждёт 1 ч 13 мин" / "waits 25 min" → minutes."""
    h = re.search(r"(\d+)\s*(?:ч|h)\b", text)
    m = re.search(r"(\d+)\s*(?:мин|min)", text)
    return (int(h.group(1)) if h else 0) * 60 + (int(m.group(1)) if m else 0)


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

            async def linger(where, t0):
                """ "Answer sent" stays 3 s from the tap with a bar running out under it, then goes."""
                bar = await js("(() => { const b = document.querySelector('.card.rcpt .rcpt-bar'); return b && getComputedStyle(b).animationDuration; })()")
                verdict(where + ": a bar under the line runs 3 s", bar == "3s", bar)
                await asyncio.sleep(max(0, t0 + 2.5 - time.time()))
                verdict(where + ": still there at 2.5 s, though the computer dropped it", await js("!!document.querySelector('.card.rcpt')"))
                await asyncio.sleep(max(0, t0 + 3.6 - time.time()))
                verdict(where + ": gone by 3.6 s", await until("!document.querySelector('.card.rcpt')", 10))

            card = "document.querySelector('.card.ask')"
            state = ("(() => { const c = %s; if (!c) return null; return {done: c.querySelectorAll('.q.done').length,"
                     " open: c.querySelectorAll('.q:not(.done)').length, opts: c.querySelectorAll('.q:not(.done) .opt').length}; })()" % card)
            await cmd("Page.navigate", url=URLS["HOME"])
            verdict("Home shows a question of two parts", await until("(%s || {}).open === 2" % state, 150), await js(state))
            await shot("1-two.png")
            cards = await js("[...document.querySelectorAll('.card.ask, .card.perm, .card.mine')].map((c) =>"
                             " [c.classList.contains('ask') ? 'ask' : c.classList.contains('perm') ? 'perm' : 'mine',"
                             " (c.querySelector('.c-wait') || {}).textContent || ''])")
            kinds, waits = [k for k, _ in cards], [minutes(w) for _, w in cards]
            verdict("your move in one line by time: the question, a session, the permission, a session",
                    kinds == ["ask", "mine", "perm", "mine"], cards)
            verdict("every card says how long it waits, the freshest on top", all(w for _, w in cards) and waits == sorted(waits), waits)
            await tap(".card.ask .q:not(.done) .opt", 0)
            verdict("an answer to the first part keeps the card", await until("(%s || {}).done === 1" % state), await js(state))
            s = await js(state)
            verdict("the second part waits with its options", s and s["open"] == 1 and s["opts"] == 2, s)
            verdict("no \"Answer sent\" yet", await js("!document.querySelector('.card.rcpt')"))
            await asyncio.sleep(1.5)                # the list comes back from the computer: still the same
            s = await js(state)
            verdict("after the list's refresh still one answered, one waiting", s and s["done"] == 1 and s["open"] == 1, s)
            await shot("2-first-answered.png")

            await cmd("Page.navigate", url="about:blank")
            await cmd("Page.navigate", url=URLS["HOME"])
            verdict("opened again: the computer kept the first answer", await until("(%s || {}).done === 1" % state, 150), await js(state))
            await tap(".card.ask .q:not(.done) .opt", 1)
            t0 = time.time() - 0.5                  # tap() waits half a second after the finger
            verdict("the last part closes the card with \"Answer sent\"", await until("!!document.querySelector('.card.rcpt')"))
            await shot("3-sent.png")
            await linger("Home", t0)

            # a session: the permission it waits for, answered right there
            await cmd("Page.navigate", url="about:blank")
            await cmd("Page.navigate", url=URLS["SESS"])
            verdict("the session shows its permission", await until("!!document.querySelector('.card.perm .btn')", 150))
            await tap(".card.perm .btn", 0)
            t0 = time.time() - 0.5
            verdict("Allow turns the card into \"Allowed\"", await until("!!document.querySelector('.card.rcpt')"))
            await linger("the session", t0)
            verdict("no script errors", not errors, errors)
    finally:
        p.kill()
    print("screenshots:", OUT)
    sys.exit(1 if failures else 0)


asyncio.run(main())
