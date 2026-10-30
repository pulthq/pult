"""A task's state in colour (Q110–Q112, the owner, 2026-10-30: only the small grey heading of a section told a running
task, one that waits for them and history apart), in headless Chrome over DevTools, on the stand: "Running now" is a
green zone — its list tinted, a green bar on its left, its heading green with the dot; "Your move" a warm one — every
card tinted, a failed one red, the fields and choices in them plain; history stays plain, each row with a grey tick;
the button that puts a task away says "Проверено". Light and dark, a 320 px phone, a project's screen too.
  STAND_TAGS=1 STAND_ASK2=1 STAND_LANG=ru HOLD=300 ~/.local/share/pult/venv/bin/python tools/stand.py > /tmp/stand.out &
  ~/.local/share/pult/venv/bin/python tools/states_check.py /tmp/stand.out [out_dir]
Screenshots go to out_dir (a temporary folder by default). Exit 1 on a failed check."""
import asyncio, base64, json, os, subprocess, sys, tempfile
import aiohttp

URLS = dict(line.split(" ", 1) for line in open(sys.argv[1]).read().split("\n") if line[:5] in ("HOME ", "PROJT"))
OUT = sys.argv[2] if len(sys.argv) > 2 else tempfile.mkdtemp(prefix="pult-states-")
os.makedirs(OUT, exist_ok=True)
import _cdp  # noqa: E402  (tools/_cdp.py: where Chrome is, free ports, a profile that goes — review 2026-10-27, Т9)
CHROME = _cdp.CHROME
PORT = _cdp.free_port()
failures = []

# a colour as the page paints it, [r, g, b] — a canvas reads any CSS colour (color-mix gives color(srgb …))
RGB = """const rgb = (c) => { const x = document.createElement('canvas').getContext('2d'); x.fillStyle = c; x.fillRect(0, 0, 1, 1);
  return [...x.getImageData(0, 0, 1, 1).data].slice(0, 3); };
const bg = (el) => rgb(getComputedStyle(el).backgroundColor), fg = (el) => rgb(getComputedStyle(el).color);
const same = (a, b) => a.every((v, i) => Math.abs(v - b[i]) <= 2);
const base = () => rgb(getComputedStyle(document.documentElement).getPropertyValue('--card-base').trim());
// which way a colour leans from the plain card: a dark card is bluish itself, so the channels' shifts tell, not their sizes
const lean = (c) => { const b = base(); return c.map((v, i) => v - b[i]); };
const green = (c) => { const [r, g, b] = lean(c); return g > r + 2 && g > b + 2; };
const warm = (c) => { const [r, g, b] = lean(c); return r > g + 2 && g > b + 2; };
const red = (c) => { const [r, g, b] = lean(c); return r > g + 5 && r > b + 5; };"""


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
                r = await cmd("Runtime.evaluate", expression="(() => { %s\nreturn (%s); })()" % (RGB, expr), returnByValue=True, awaitPromise=True)
                if "exceptionDetails" in r:
                    raise RuntimeError(r["exceptionDetails"])
                return r["result"].get("value")

            async def until(expr, tries=100):
                for _ in range(tries):
                    if await js(expr):
                        return True
                    await asyncio.sleep(0.1)
                return False

            async def shot(name, at=None):
                if at:
                    await js("(document.querySelector(%s).scrollIntoView(), window.scrollBy(0, -10), 1)" % json.dumps(at))
                    await asyncio.sleep(0.3)
                d = await cmd("Page.captureScreenshot", format="png")
                open(os.path.join(OUT, name), "wb").write(base64.b64decode(d["data"]))

            async def width(w):
                await cmd("Emulation.setDeviceMetricsOverride", width=w, height=860, deviceScaleFactor=2, mobile=True)

            async def home(dark):
                await cmd("Emulation.setEmulatedMedia", features=[{"name": "prefers-color-scheme", "value": "dark" if dark else "light"}])
                await cmd("Page.navigate", url="about:blank")
                await cmd("Page.navigate", url=URLS["HOME"])
                return await until("!!document.querySelector('.zone-mine .card.mine') && !!document.querySelector('.zone-run .list')", 150)

            await cmd("Page.enable")
            await cmd("Runtime.enable")
            await width(412)
            for dark in (False, True):
                k = "dark" if dark else "light"
                verdict("%s: Home shows the zones" % k, await home(dark))
                plain = await js("bg(document.querySelector('.list.proj'))")
                run = await js("bg(document.querySelector('.zone-run .list .swr-in') || document.querySelector('.zone-run .list'))")
                verdict("%s: a running task's row is green" % k, await js("green(%s) && !same(%s, %s)" % (run, run, plain)), run, plain)
                verdict("%s: … a green bar on the list's left" % k, await js(
                    "(() => { const b = getComputedStyle(document.querySelector('.zone-run > .list'), '::before'); return b.width === '4px' &&"
                    " same(rgb(b.backgroundColor), rgb(getComputedStyle(document.documentElement).getPropertyValue('--ok').trim())); })()"))
                verdict("%s: … it stays under what lies over the list (its own layer)" % k,
                        await js("getComputedStyle(document.querySelector('.zone-run > .list')).isolation === 'isolate'"))
                verdict("%s: the heading «Идёт сейчас» green, with the dot" % k, await js(
                    "green(fg(document.querySelector('.zone-run > h3'))) && !!document.querySelector('.zone-run > h3 .dot.work')"),
                    await js("fg(document.querySelector('.zone-run > h3'))"))
                cards = await js("[...document.querySelectorAll('.zone-mine .card')].map((c) => [c.className, bg(c)])")
                verdict("%s: every card of «Твой ход» is warm" % k, len(cards) >= 3 and all([await js("warm(%s)" % json.dumps(c[1])) for c in cards]), cards)
                verdict("%s: … questions and permissions too" % k, await js("!!document.querySelector('.zone-mine .card.ask') && !!document.querySelector('.zone-mine .card.perm')"))
                verdict("%s: the heading «Твой ход» warm, with the dot" % k, await js(
                    "warm(fg(document.querySelector('.zone-mine > h3'))) && !!document.querySelector('.zone-mine > h3 .dot.attn')"))
                fields = await js("[...document.querySelectorAll('.zone-mine .reply input, .zone-mine .own input, .zone-mine .q .opt:not(.on), .zone-mine .qr:not(.wait) button')].map((e) => bg(e))")
                verdict("%s: fields and choices in the cards stay plain to read" % k, len(fields) >= 4 and all([await js("same(%s, base())" % json.dumps(f)) for f in fields]),
                        len(fields), await js("base()"))
                verdict("%s: history stays plain" % k, await js("same(%s, base())" % json.dumps(plain)), plain)
                rows = await js("[...document.querySelectorAll('.list.proj .brow.rest')].map((r) => [r.querySelector('.item-h b').textContent.trim(), !!r.querySelector('.item-h b > .st-ic.chk:first-child')])")
                verdict("%s: every row of history starts with the grey tick" % k, len(rows) >= 2 and all(r[1] for r in rows), rows)
                verdict("%s: … the tick is grey, the colour of the row" % k, await js(
                    "(() => { const t = document.querySelector('.list.proj .brow.rest .st-ic.chk'); return same(fg(t), fg(t.closest('b'))); })()"))
                verdict("%s: a running task has no tick" % k, await js("!document.querySelector('.zone-run .st-ic.chk')"))
                verdict("%s: the button that puts a task away says «Проверено»" % k, await js(
                    "[...document.querySelectorAll('.zone-mine .card.mine .foot .link')].some((b) => b.textContent.trim() === 'Проверено')"),
                    await js("[...document.querySelectorAll('.zone-mine .card.mine .foot .link')].map((b) => b.textContent.trim())"))
                await shot("1-%s-running.png" % k)
                await shot("2-%s-your-move.png" % k, ".zone-mine")
                await shot("3-%s-history.png" % k, ".list.proj .brow.rest")
                # a turn that failed: its card red, not warm — the same rule the stand has no failing task for
                verdict("%s: a failed task's card is red" % k, await js(
                    "(() => { const c = document.querySelector('.zone-mine .card.mine'); c.classList.add('fail'); const v = bg(c); c.classList.remove('fail'); return red(v); })()"))
            # a 320 px phone: the zones' colour costs no width — nothing runs past the screen
            await cmd("Emulation.setEmulatedMedia", features=[{"name": "prefers-color-scheme", "value": "light"}])
            await width(320)
            await home(False)
            verdict("320 px: nothing runs past the screen", await js("document.documentElement.scrollWidth <= 320"), await js("document.documentElement.scrollWidth"))
            await shot("4-light-320.png", ".zone-mine")
            await width(412)
            # a project's screen: the same zones; today's and the earlier tasks are history with the tick
            await cmd("Page.navigate", url="about:blank")
            await cmd("Page.navigate", url=URLS["PROJT"])
            verdict("project: «Ждёт тебя» is the warm zone, «Идёт» the green one",
                    await until("!!document.querySelector('.project .zone-mine .card') && !!document.querySelector('.project .zone-run .list')", 150))
            verdict("project: its headings carry the dots", await js(
                "!!document.querySelector('.project .zone-mine > h3 .dot.attn') && !!document.querySelector('.project .zone-run > h3 .dot.work')"))
            today = await js("[...document.querySelectorAll('.project .brow.rest')].map((r) => !!r.querySelector('.st-ic.chk'))")
            verdict("project: today's tasks carry the tick", len(today) >= 1 and all(today), today)
            await shot("5-project.png")
            if await js("!!document.querySelector('.project h3.toggle')"):
                await js("(document.querySelector('.project h3.toggle').click(), 1)")
                await asyncio.sleep(0.5)
                earlier = await js("[...document.querySelectorAll('.project .list .item.brow.rest')].map((r) => !!r.querySelector('.st-ic.chk'))")
                verdict("project: the earlier tasks carry it too", len(earlier) >= 1 and all(earlier), earlier)
            verdict("no script errors", not errors, errors)
    finally:
        p.kill()
    print("screenshots:", OUT)
    sys.exit(1 if failures else 0)


asyncio.run(main())
