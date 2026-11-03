"""One clock for a whole task (the owner, 2026-10-30: "if a task is paused on me, the time pauses"; Q117 a), in headless
Chrome over DevTools, on the stand: "Running now" says how long Claude has worked on the task in all — its earlier
turns too, not the last one from zero; the cards of "Your move" — the question, the permission, an outcome — carry the
same clock stopped, grey with the pause sign, beside the title, whole, the model's mark at the foot whole too, on
412 px and on 320 px; the task's own screen — the stopped clock on top, no "in N" of the last turn under the outcome.
  STAND_VENDORS=1 STAND_HOMES=1 STAND_REPORT=1 STAND_LANG=ru HOLD=300 ~/.local/share/pult/venv/bin/python tools/stand.py > /tmp/stand.out &
  ~/.local/share/pult/venv/bin/python tools/worktime_check.py /tmp/stand.out [out_dir]
The stand's made-up work before these turns (tools/stand.py): the dark theme 41 min, the weekly report 9, the search 52,
the checkout 18. Screenshots go to out_dir (a temporary folder by default). Exit 1 on a failed check."""
import asyncio, base64, json, os, re, subprocess, sys, tempfile
import aiohttp

URLS = dict(line.split(" ", 1) for line in open(sys.argv[1]).read().split("\n") if line[:5] in ("HOME ", "SESS4"))
OUT = sys.argv[2] if len(sys.argv) > 2 else tempfile.mkdtemp(prefix="pult-worktime-")
os.makedirs(OUT, exist_ok=True)
import _cdp  # noqa: E402  (tools/_cdp.py: where Chrome is, free ports, a profile that goes — review 2026-10-27, Т9)
CHROME = _cdp.CHROME
PORT = _cdp.free_port()
# the stand's tasks, STAND_LANG=ru: at work (41 min before its turn), waiting for you (52, 9), asking a permission (18)
RUN, SEARCH, REPORT, PERM = "Сделай тёмную тему для админки", "Поиск: опечатки", "Отчёт поддержки за неделю", "Оформление заказа"
failures = []


def verdict(name, ok, *info):
    print(("ok   " if ok else "FAIL ") + name, *info)
    if not ok:
        failures.append(name)


def minutes(text):
    """ "работает 47 мин" / "52 мин" / "1 ч 5 мин" → minutes, or None."""
    h = re.search(r"(\d+)\s*ч", text or "")
    m = re.search(r"(\d+)\s*мин", text or "")
    return (int(h.group(1)) * 60 if h else 0) + (int(m.group(1)) if m else 0) if h or m else None


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
                d = await cmd("Page.captureScreenshot", format="png", captureBeyondViewport=True)
                open(os.path.join(OUT, name), "wb").write(base64.b64decode(d["data"]))

            # a card of "Your move" by its title: its stopped clock — text, aria-label, whole, on the title's line at the
            # right end, inside the card — and the model's mark at its foot, whole
            card = ("(() => { const c = [...document.querySelectorAll('.card.mine, .card.perm, .card.ask')].find((x) =>"
                    " (x.querySelector('.c-title') || {textContent: ''}).textContent.includes(%s)); if (!c) return null;"
                    " const ch = c.querySelector('.c-title .chip.paused'), t = c.querySelector('.c-title'), go = c.querySelector('.c-title .c-go'),"
                    " llm = c.querySelector('.foot .llm'); if (!ch) return {chip: null};"
                    " const b = ch.getBoundingClientRect(), cb = c.getBoundingClientRect(), tb = t.getBoundingClientRect();"
                    " return {chip: ch.textContent.trim(), label: ch.getAttribute('aria-label'), whole: ch.scrollWidth <= ch.clientWidth + 1,"
                    " inside: b.right <= cb.right + 0.5 && b.left >= cb.left, line: b.top >= tb.top - 1 && b.bottom <= tb.bottom + 1,"
                    " right: !go || go.getBoundingClientRect().left - b.right < 12, icon: !!ch.querySelector('svg.ic-pause'),"
                    " llm: llm ? llm.textContent : null, llmWhole: !llm || llm.scrollWidth <= llm.clientWidth + 1}; })()")

            await cmd("Page.enable")
            await cmd("Runtime.enable")
            for width in (412, 320):
                await cmd("Emulation.setDeviceMetricsOverride", width=width, height=860, deviceScaleFactor=2, mobile=True)
                await cmd("Page.navigate", url="about:blank")
                await cmd("Page.navigate", url=URLS["HOME"])
                await until("!!document.querySelector('.card.mine .chip.paused')", 150)
                if width == 412:
                    run = await js("(() => { const r = [...document.querySelectorAll('.item.run')].find((x) => x.textContent.includes(%s));"
                                   " return r && r.querySelector('.chip.timer > span:not(.ghost)').textContent; })()" % json.dumps(RUN))
                    verdict("«Running now»: the task's whole work, not its last turn from zero (41 min before it)",
                            (minutes(run) or 0) >= 45, run)
                    verdict("… still the green «working» chip, not the stopped one", bool(run) and run.startswith("работает")
                            and await js("!document.querySelector('.item.run .chip.paused')"))
                for title, least, most in ((SEARCH, 52, 55), (REPORT, 9, 11), (PERM, 21, 30)):
                    c = await js(card % json.dumps(title))
                    verdict("%d px · «%s»: the clock stopped beside the title, %d min" % (width, title, least),
                            bool(c and c.get("chip")) and least <= (minutes(c["chip"]) or 0) <= most and c["icon"], c)
                    verdict("%d px · «%s»: whole, at the title's right end, inside the card; it says «… работы» aloud" % (width, title),
                            bool(c and c.get("chip")) and c["whole"] and c["inside"] and c["line"] and c["right"]
                            and (c["label"] or "").endswith("работы"), c)
                    if c and c.get("llm") is not None:
                        verdict("%d px · «%s»: the model at the foot stays whole" % (width, title), c["llmWhole"], c["llm"])
                await shot("home-%d.png" % width)
            # the task's own screen: the stopped clock on top, where «working» stands while it works; under the outcome
            # no more «in N» — the last turn's time with the wait in it (2026-10-30)
            await cmd("Emulation.setDeviceMetricsOverride", width=412, height=860, deviceScaleFactor=2, mobile=True)
            await cmd("Page.navigate", url="about:blank")
            await cmd("Page.navigate", url=URLS["SESS4"])
            await until("!!document.querySelector('.card.outcome')", 150)
            top = await js("(document.querySelector('.sess-h .chip.paused') || {textContent: null}).textContent")
            verdict("the session: the stopped clock on top, 52 min", 52 <= (minutes(top) or 0) <= 55, top)
            k = await js("(document.querySelector('.card.outcome .k') || {}).textContent")
            verdict("… and no «за N» under the outcome", bool(k) and " за " not in k and "ждёт тебя" in k, k)
            await shot("session.png")
            verdict("no script errors", not errors, errors)
    finally:
        p.kill()
    print("screenshots:", OUT)
    sys.exit(1 if failures else 0)


asyncio.run(main())
