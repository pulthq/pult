"""A message to a session open on the computer without Pult's wrapper, in headless Chrome over DevTools, on the stand,
with real taps (a friend learned it goes as a copy only after typing a whole answer, and not why, 2026-10-26): the
"your move" card of such a session says "goes as a copy" before anything is typed, the other cards don't, and a tap
on it explains; an answer typed and sent asks about a copy and says why — here a tab on a Claude Code Pult isn't
checked on; "Cancel" sends nothing and keeps the words. The session's own screen says the same under its field, in
the explanation and when its message is sent.
  STAND_COPY=1 STAND_ASK2=1 STAND_LANG=ru STAND_PORT=18131 HOLD=300 ~/.local/share/pult/venv/bin/python tools/stand.py > /tmp/stand.out &
  ~/.local/share/pult/venv/bin/python tools/copy_check.py /tmp/stand.out [out_dir]
Screenshots go to out_dir (a temporary folder by default). Exit 1 on a failed check."""
import asyncio, base64, json, os, re, subprocess, sys, tempfile
import aiohttp

STAND_OUT = sys.argv[1]
URLS = dict(line.split(" ", 1) for line in open(STAND_OUT).read().split("\n") if line[:5] in ("HOME ", "SESS4"))
URLS = {k.strip(): v for k, v in URLS.items()}
OUT = sys.argv[2] if len(sys.argv) > 2 else tempfile.mkdtemp(prefix="pult-copy-")
os.makedirs(OUT, exist_ok=True)
import _cdp  # noqa: E402  (tools/_cdp.py: where Chrome is, free ports, a profile that goes — review 2026-10-27, Т9)
CHROME = _cdp.CHROME
PORT = _cdp.free_port()
COPY = re.compile(r"копией|as a copy")                    # "goes as a copy" under the field and on the card
WHY = re.compile(r"2\.1\.311.*(не проверен|hasn't been checked)", re.S)
ASK = re.compile(r"Продолжить копией|Continue as a copy")
S4 = re.compile(r"Поиск: опечатки|Search: typo-tolerant")   # the stand's session that waits for you (SID4)
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

            async def tap_at(expr):
                """A finger on the element's middle — not el.click(): what is on top there gets it."""
                r = await js("(() => { const el = %s; if (!el) return null; el.scrollIntoView({block: 'center'});"
                             " const b = el.getBoundingClientRect(); return [b.left + b.width / 2, b.top + b.height / 2]; })()" % expr)
                if not r:
                    raise RuntimeError("nothing to tap: " + expr)
                await cmd("Input.dispatchTouchEvent", type="touchStart", touchPoints=[{"x": r[0], "y": r[1]}])
                await cmd("Input.dispatchTouchEvent", type="touchEnd", touchPoints=[])
                await asyncio.sleep(0.5)

            async def type_into(expr, text):
                await js("(%s).focus()" % expr)
                await cmd("Input.insertText", text=text)
                await asyncio.sleep(0.2)

            async def open_url(url):
                await cmd("Page.navigate", url="about:blank")
                await cmd("Page.navigate", url=url)
                await asyncio.sleep(0.3)
                # the app asks through Telegram's own boxes when it runs in Telegram, else the browser's — catch both;
                # every question is answered "Cancel"
                await js("window.__said = []; window.alert = (s) => window.__said.push(['alert', String(s)]);"
                         " window.confirm = (s) => (window.__said.push(['confirm', String(s)]), false);"
                         " const w = window.Telegram && window.Telegram.WebApp; if (w) {"
                         " w.showAlert = (s) => window.__said.push(['alert', String(s)]);"
                         " w.showConfirm = (s, cb) => (window.__said.push(['confirm', String(s)]), cb(false)); }")

            async def said(wait=2.0):
                """What the app said since the last look — waiting a little for the first word. A miss tells why: the
                page reloaded under the check (its catchers gone) or nothing was said (1 run in 3 missed, 2026-10-27)."""
                for _ in range(int(wait / 0.1)):
                    got = await js("window.__said ? window.__said.splice(0) : null")
                    if got is None:
                        return [["lost", await js("JSON.stringify([location.href.slice(0, 60), "
                                                  "(performance.getEntriesByType('navigation')[0] || {}).type])")]]
                    if got:
                        return got
                    await asyncio.sleep(0.1)
                return []

            await cmd("Page.enable")
            await cmd("Runtime.enable")
            await cmd("Emulation.setDeviceMetricsOverride", width=412, height=860, deviceScaleFactor=2, mobile=True)
            await cmd("Emulation.setTouchEmulationEnabled", enabled=True, maxTouchPoints=5)

            # Home: the card of the session open in an unchecked tab
            await open_url(URLS["HOME"])
            verdict("Home shows the cards that wait for you", await until("document.querySelectorAll('.card.mine').length > 0", 150))
            cards = await js("[...document.querySelectorAll('.card.mine')].map((c) => [(c.querySelector('.c-title') || {}).textContent || '',"
                             " !!c.querySelector('.foot .link.copy'), (c.querySelector('.foot') || {}).textContent || ''])")
            marked = [c for c in cards if c[1]]
            verdict("one card says it goes as a copy — the session open in the tab", len(marked) == 1 and S4.search(marked[0][0])
                    and COPY.search(marked[0][2]), cards)
            others = [c for c in cards if not S4.search(c[0])]           # STAND_ASK2=1: another session waits, not open here
            verdict("the other cards don't", others and all(not c[1] and not COPY.search(c[2]) for c in others), cards)
            i = next(k for k, c in enumerate(cards) if c[1])
            card = "document.querySelectorAll('.card.mine')[%d]" % i
            await js("(%s).scrollIntoView({block: 'center'})" % card)
            await shot("1-card.png")
            await tap_at("(%s).querySelector('.foot .link.copy')" % card)
            got = await said()
            verdict("a tap on it explains", len(got) == 1 and got[0][0] == "alert" and re.search(r"открыта на компьютере|open on the computer", got[0][1]), got)
            words = "Проверь ещё раз на телефоне"
            await type_into("(%s).querySelector('.reply input')" % card, words)
            verdict("the answer is typed", await until("(%s).querySelector('.reply .btn.send')" % card), await js("(%s).querySelector('.reply input').value" % card))
            await tap_at("(%s).querySelector('.reply .btn.send')" % card)
            await asyncio.sleep(0.8)
            got = await said()
            verdict("sending asks about a copy and says why: a Claude Code Pult isn't checked on",
                    len(got) == 1 and got[0][0] == "confirm" and WHY.search(got[0][1]) and ASK.search(got[0][1]), got)
            verdict("\"Cancel\" keeps the words in the field", await js("(%s).querySelector('.reply input').value" % card) == words)

            # the session's own screen
            await open_url(URLS["SESS4"])
            verdict("the session opens", await until("!!document.querySelector('textarea')", 150))
            verdict("under the field: goes as a copy", await until("/копией|as a copy/.test((document.querySelector('.status .where') || {}).textContent || '')"),
                    await js("(document.querySelector('.status') || {}).textContent"))
            await shot("2-session.png")
            await tap_at("document.querySelector('.status .where')")
            sheet = await js("[...document.querySelectorAll('.card.pick .sheet-p')].map((p) => p.textContent)")
            verdict("its explanation says why and that a copy follows", bool(sheet) and WHY.search(sheet[0]) and COPY.search(sheet[0]), sheet)
            await shot("3-why.png")
            await tap_at("document.querySelector('.card.pick .x')")
            words2 = "А теперь из сессии"
            await type_into("document.querySelector('textarea')", words2)
            await tap_at("document.querySelector('.btn.send')")
            await asyncio.sleep(0.8)
            got = await said()
            verdict("sending from the session asks with the reason too",
                    len(got) == 1 and got[0][0] == "confirm" and WHY.search(got[0][1]) and ASK.search(got[0][1]), got)
            verdict("\"Cancel\" gives the words back to the field", await until("document.querySelector('textarea').value === %s" % json.dumps(words2)),
                    await js("document.querySelector('textarea').value"))
            drove = [ln for ln in open(STAND_OUT).read().split("\n") if ln.startswith("DRIVE") and ("Проверь ещё" in ln or "из сессии" in ln)]
            verdict("nothing went anywhere", not drove, drove)
            verdict("no script errors", not errors, errors)
    finally:
        p.kill()
    print("screenshots:", OUT)
    sys.exit(1 if failures else 0)


asyncio.run(main())
