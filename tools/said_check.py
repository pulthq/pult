"""Search over everything (stage И, step И1 — Q187) in headless Chrome over DevTools, on the stand with STAND_SEARCH=1,
with touches as from a phone: a word said only inside tasks — "In what was said", two tasks, the word marked, a
document; "Only my words" leaves the owner's places alone; "N more places" shows the rest; a place opens its task right
there — the message marked, the word in it too, in the middle of the screen — and going down brings the rest of the
chat in chunks until its end, then the chat is as always; Back — the same list; a document opens on the line with the
word; Settings → Search shows what the index holds, "Build again" asks first, turning it off asks too.
  STAND_SEARCH=1 STAND_LANG=ru STAND_PORT=18161 HOLD=300 ~/.local/share/pult/venv/bin/python tools/stand.py > /tmp/stand.out &
  ~/.local/share/pult/venv/bin/python tools/said_check.py /tmp/stand.out [out_dir]
Screenshots go to out_dir (a temporary folder by default); SAID_DARK=1 — in the phone's dark theme. Exit 1 on a failed
check. Selectors are by class and order, not by text: the stand runs in either language."""
import asyncio, base64, json, os, subprocess, sys, tempfile
import aiohttp

LINES = dict(line.split(" ", 1) for line in open(sys.argv[1]).read().split("\n") if " " in line)
OUT = sys.argv[2] if len(sys.argv) > 2 else tempfile.mkdtemp(prefix="pult-said-")
os.makedirs(OUT, exist_ok=True)
WORD, SIDS = LINES["SEARCHWORD"].strip(), LINES["SEARCHSID"].strip()
import _cdp  # noqa: E402  (tools/_cdp.py: where Chrome is, free ports, a profile that goes — review 2026-10-27, Т9)
CHROME = _cdp.CHROME
PORT = _cdp.free_port()
W, H = 412, 860
failures = []


def verdict(name, ok, *info):
    print(("ok   " if ok else "FAIL ") + name, *info)
    if not ok:
        failures.append(name)


# what the search shows: the groups of places, their places and who said them, the documents, the marks
FOUND = """(() => { const cards = [...document.querySelectorAll('.said:not(.doc)')];
  return { cards: cards.length, places: cards.map((c) => c.querySelectorAll('.said-p').length),
    who: cards.map((c) => [...c.querySelectorAll('.said-who')].map((w) => w.textContent.trim())),
    marks: document.querySelectorAll('.said-p mark').length, docs: document.querySelectorAll('.said.doc').length,
    heads: [...document.querySelectorAll('.find ~ h3, main h3')].map((h) => h.textContent.trim()),
    chips: [...document.querySelectorAll('.find-chips .chip')].map((c) => c.className.includes('on')) };
})()"""


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

            async def tap(sel, k=0, wait=0.35):         # a finger on the element, in sight first
                await js("document.querySelectorAll(%s)[%d].scrollIntoView({block: 'center'})" % (json.dumps(sel), k))
                await asyncio.sleep(0.15)
                x, y = await js("(() => { const r = document.querySelectorAll(%s)[%d].getBoundingClientRect(); return [r.left + Math.min(r.width / 2, 60), r.top + r.height / 2]; })()"
                                % (json.dumps(sel), k))
                await cmd("Input.dispatchTouchEvent", type="touchStart", touchPoints=[{"x": x, "y": y, "id": 0}])
                await cmd("Input.dispatchTouchEvent", type="touchEnd", touchPoints=[])
                await asyncio.sleep(wait)

            async def typed(text):
                await js("(() => { const el = document.querySelector('.find-f input'); Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set.call(el, %s);"
                         " el.dispatchEvent(new Event('input', { bubbles: true })); })()" % json.dumps(text))

            await cmd("Runtime.enable")
            await cmd("Emulation.setDeviceMetricsOverride", width=W, height=H, deviceScaleFactor=2, mobile=True)
            await cmd("Emulation.setTouchEmulationEnabled", enabled=True, maxTouchPoints=2)
            if os.environ.get("SAID_DARK") == "1":
                await cmd("Emulation.setEmulatedMedia", features=[{"name": "prefers-color-scheme", "value": "dark"}])
            await cmd("Page.enable")
            await cmd("Page.navigate", url=LINES["PROJECTS"].strip())
            verdict("Projects has its search field", await until("!!document.querySelector('.find-f input')", 150))

            # a word said only inside tasks: two tasks, the word marked, a document
            await typed(WORD)
            ok = await until("document.querySelectorAll('.said:not(.doc)').length === 2 && document.querySelectorAll('.said.doc').length === 1", 80)
            f = await js(FOUND)
            verdict("the word is found in what was said: two tasks, and a document", ok, f)
            verdict("…the word marked in every piece", f["marks"] >= 3, f["marks"])
            verdict("…no task has it in its title: no list of titles", await js("!document.querySelector('.found .brow')"))
            verdict("…Everything / Only my words, Everything on", f["chips"] == [True, False], f["chips"])
            await shot("1-found.png")

            # Only my words: the owner's places alone, no documents
            await tap(".find-chips .chip", 1, wait=0.2)
            ok = await until("document.querySelectorAll('.find-chips .chip')[1].classList.contains('on') && !document.querySelector('.said.doc')"
                             " && document.querySelectorAll('.said:not(.doc)').length === 2 && !document.querySelector('[data-wait]')", 80)
            f = await js(FOUND)
            mine = {w for ws in f["who"] for w in ws}
            verdict("Only my words: the owner's places alone", ok and f["cards"] == 2 and len(mine) == 1, f)
            await shot("2-mine.png")
            await tap(".find-chips .chip", 0, wait=0.2)
            await until("document.querySelectorAll('.said.doc').length === 1", 80)

            # the long task: its other place behind "N more places"
            k = await js("[...document.querySelectorAll('.said:not(.doc)')].findIndex((c) => !!c.querySelector('.said-more'))")
            verdict("a task with two places offers the other one", k is not None and k >= 0, k)
            await tap(".said:not(.doc) .said-more", 0, wait=0.3)
            f = await js(FOUND)
            verdict("…shown under it", f["places"][k] == 2, f["places"])

            # a place opens its task right there: the message marked, the word in it, in the middle of the screen
            first = await js("[...document.querySelectorAll('.said:not(.doc) .said-p')].indexOf(document.querySelectorAll('.said:not(.doc)')[%d].querySelector('.said-p'))" % k)
            await tap(".said:not(.doc) .said-p", first, wait=0.2)
            ok = await until("!!document.querySelector('.msg.hit')", 150)
            verdict("a place opens its task", ok and await js("location.hash.startsWith('#/s/%s?at=')" % SIDS), await js("location.hash"))
            await asyncio.sleep(0.6)
            r = await js("(() => { const r = document.querySelector('.msg.hit').getBoundingClientRect(); return [Math.round(r.top), Math.round(r.bottom)]; })()") if ok else None
            verdict("…the place in sight", ok and 0 <= r[0] and r[1] <= H, r)
            verdict("…the word marked in it", ok and await js("document.querySelectorAll('.msg.hit mark').length >= 1"))
            verdict("…earlier messages above it", await js("document.querySelectorAll('.msg').length > 20"), await js("document.querySelectorAll('.msg').length"))
            verdict("…and a way down: the next chunk, To the end", await js("!!document.querySelector('.link.later') && !!document.querySelector('.tobottom.toend')"))
            await shot("3-place.png")
            # going down brings the rest in chunks, until the end — then the chat is as always
            before = await js("document.querySelectorAll('.msg').length")
            for _ in range(30):
                await js("window.scrollTo(0, document.documentElement.scrollHeight)")
                await asyncio.sleep(0.4)
                if await js("!document.querySelector('.link.later')"):
                    break
            after = await js("document.querySelectorAll('.msg').length")
            verdict("going down brings the rest of the chat, to its end", await js("!document.querySelector('.link.later') && !document.querySelector('.tobottom.toend')") and after > before, before, after)
            await shot("4-end.png")

            # Back: the same list, the same word
            await js("history.back()")
            ok = await until("(document.querySelector('.find-f input') || {}).value === %s && document.querySelectorAll('.said').length === 3" % json.dumps(WORD), 80)
            verdict("Back: the same list", ok, await js(FOUND))

            # a document opens on the line with the word
            await tap(".said.doc", 0, wait=0.2)
            ok = await until("!!document.querySelector('.fv .ln.hit')", 80)
            hit = await js("(() => { const l = document.querySelector('.fv .ln.hit'); return l ? [l.id, l.textContent] : null; })()")
            verdict("a document opens on the line with the word", ok and hit and hit[0] == "L3" and WORD in hit[1].lower(), hit)
            verdict("…by its project, without To Telegram (that goes from a task)", await js("!document.querySelector('.fv .fv-bar .btn')"))
            await shot("5-doc.png")
            await js("history.back()")
            await until("!document.querySelector('.fv')", 50)

            # Settings → Search: what the index holds; Build again asks; turning it off asks too
            await cmd("Page.navigate", url="about:blank")      # the same page with another start: loaded anew, not a jump
            await asyncio.sleep(0.3)
            await cmd("Page.navigate", url=LINES["SETS"].strip())
            ok = await until("!!document.querySelector('.search-st button.link')", 150)
            st = await js("(() => { const s = document.querySelector('.set-sub [role=switch]'); return [s && s.getAttribute('aria-checked'), document.querySelector('.search-st') ? document.querySelector('.search-st').textContent : null]; })()")
            verdict("Settings → Search: on, what the index holds", ok and st[0] == "true" and any(c.isdigit() for c in st[1] or ""), st)
            await shot("6-settings.png")
            await js("window.__said = []; window.__yes = true; window.confirm = (s) => (window.__said.push(String(s)), window.__yes);"
                     " const w = window.Telegram && window.Telegram.WebApp;"
                     " if (w) w.showConfirm = (s, cb) => (window.__said.push(String(s)), cb(window.__yes));")
            await tap(".search-st button.link", 0, wait=0.5)
            ok = await until("window.__said.length === 1 && !!document.querySelector('.search-st')", 80)
            verdict("Build again asks first, then builds", ok, await js("window.__said"))
            await js("window.__yes = false")
            await tap(".set-sub [role=switch]", 0, wait=0.5)
            verdict("turning it off asks — and a no leaves it on", await js("window.__said.length === 2 && document.querySelector('.set-sub [role=switch]').getAttribute('aria-checked') === 'true'"))
            verdict("no errors on the page", not errors, errors[:3])
    finally:
        p.kill()
    print("screenshots:", OUT)
    sys.exit(1 if failures else 0)


asyncio.run(main())
