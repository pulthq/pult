"""Task tags (stage T) in headless Chrome over DevTools, on the stand, with real taps: the printer's project shows each
task's section and topic and the bar of its sections; a tap on a section narrows every list to it (the earlier ones
open by themselves) and shows its topics, a tap on a topic narrows further, "All" brings everything back; a task's
sheet changes its topic (saved by the computer: still there after a reload), takes a new topic by name, and gives the
choice back to Claude; Home's cards carry the tags on their top line, beside the project — the running ones show their
title whole, what was asked and what Claude says (0.17.3).
  STAND_TAGS=1 STAND_LANG=ru STAND_PORT=18151 HOLD=300 ~/.local/share/pult/venv/bin/python tools/stand.py > /tmp/stand.out &
  ~/.local/share/pult/venv/bin/python tools/tags_check.py /tmp/stand.out [out_dir]
Screenshots go to out_dir (a temporary folder by default). Exit 1 on a failed check."""
import asyncio, base64, json, os, subprocess, sys, tempfile
import aiohttp

URLS = dict(line.split(" ", 1) for line in open(sys.argv[1]).read().split("\n") if line[:5] in ("PROJT", "SESST", "HOME "))
URLS = {k.strip(): v.strip() for k, v in URLS.items()}
OUT = sys.argv[2] if len(sys.argv) > 2 else tempfile.mkdtemp(prefix="pult-tags-")
os.makedirs(OUT, exist_ok=True)
import _cdp  # noqa: E402  (tools/_cdp.py: where Chrome is, free ports, a profile that goes — review 2026-10-27, Т9)
CHROME = _cdp.CHROME
PORT = _cdp.free_port()
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

            async def tap_at(r):
                await cmd("Input.dispatchTouchEvent", type="touchStart", touchPoints=[{"x": r[0], "y": r[1]}])
                await cmd("Input.dispatchTouchEvent", type="touchEnd", touchPoints=[])

            async def tap_text(sel, text):
                """A finger on the middle of the element under sel whose own words start with text."""
                r = await js("(() => { const el = [...document.querySelectorAll(%s)].find((e) => e.textContent.trim().startsWith(%s));"
                             " if (!el) return null; el.scrollIntoView({block: 'center', inline: 'center'});"
                             " const b = el.getBoundingClientRect(); return [b.left + b.width / 2, b.top + b.height / 2]; })()"
                             % (json.dumps(sel), json.dumps(text)))
                if not r:
                    raise RuntimeError("nothing to tap: %s %r" % (sel, text))
                await tap_at(r)

            async def goto(url):
                """A fresh load: the stand's links differ only after #, and that alone would not reload the app."""
                await cmd("Page.navigate", url="about:blank")
                await cmd("Page.navigate", url=url)

            # the rows' titles on the project's screen; each row's tags as [section, topic]
            row_tags = ("[...document.querySelectorAll('.project .card.mine, .project .item.brow, .project .item.run')].map((r) =>"
                        " [...r.querySelectorAll('.tagc')].map((t) => t.textContent.trim()))")
            bar = lambda sub: ("[...document.querySelectorAll('.tagbar%s .tagf')].map((b) => [b.firstChild && b.firstChild.nodeType === 3 ?"
                               " b.firstChild.textContent.trim() : b.textContent.replace(/\\d+$/, '').trim(), b.classList.contains('on')])" % (".sub" if sub else ":not(.sub)"))

            await cmd("Page.enable")
            await cmd("Runtime.enable")
            await cmd("Emulation.setDeviceMetricsOverride", width=412, height=860, deviceScaleFactor=2, mobile=True)
            await cmd("Emulation.setTouchEmulationEnabled", enabled=True, maxTouchPoints=5)

            # the project: every task with its two tags; the bar of sections, "All" on
            await goto(URLS["PROJT"])
            verdict("the project's tag bar", await until("!!document.querySelector('.tagbar .tagf')", 150))
            tags = await js(row_tags)
            verdict("every task on screen has a section and a topic", tags and all(len(t) == 2 for t in tags), tags)
            b0 = await js(bar(False))
            verdict("…the bar starts with All, on", b0[0][1] and len(b0) >= 5, b0[:3])
            fresh = await js("document.querySelectorAll('.project .tagc.fresh, .project .tagf.fresh').length")
            verdict("…no dashes in the lists (a new tag is dashed only in the sheet)", fresh == 0, fresh)
            await shot("1-project.png")

            # a section: every list narrowed, its topics in a second row, the earlier ones open
            sec = b0[2][0]                                   # the second section by count — not the first, to be sure
            await tap_text(".tagbar:not(.sub) .tagf", sec)
            verdict("a section narrows the lists", await until("(%s).every((t) => t[0] === %s)" % (row_tags, json.dumps(sec))))
            n_sec = len(await js(row_tags))
            verdict("…to its tasks, the earlier ones open", n_sec >= 2 and await js("!!document.querySelector('h3.toggle .chev.open')"), n_sec)
            sub = await js(bar(True))
            verdict("…and its topics show in a second row", len(sub) >= 2 and sub[0][1], sub)
            await shot("2-section.png")
            top = sub[1][0]
            await tap_text(".tagbar.sub .tagf", top)
            verdict("a topic narrows further", await until("(%s).length === 1 && (%s)[0][1] === %s" % (row_tags, row_tags, json.dumps(top))))
            await tap_text(".tagbar:not(.sub) .tagf", b0[0][0])
            verdict("All brings everything back", await until("(%s).length > %d && !document.querySelector('.tagbar.sub')" % (row_tags, n_sec)))

            # the task's sheet: another topic, saved; a new topic; back to Claude
            await goto(URLS["SESST"])
            verdict("the task's tags under its title", await until("document.querySelectorAll('.sess-tags .tagc').length === 2", 150))
            before = await js("[...document.querySelectorAll('.sess-tags .tagc')].map((t) => t.textContent)")
            await js("document.querySelector('.sess-tags').click()")
            verdict("the sheet opens", await until("!!document.querySelector('.tagpick')"))
            verdict("…Claude picks them, at first", await js("document.querySelector('.tagpick .opt.auto').classList.contains('on')"))
            other = await js("[...document.querySelectorAll('.tagpick .pills .tagf.topic')].map((b) => b.textContent.trim()).find((x) => x !== %s)" % json.dumps(before[1]))
            await shot("3-sheet.png")
            await tap_text(".tagpick .pills .tagf.topic", other)
            verdict("another topic is saved", await until("[...document.querySelectorAll('.sess-tags .tagc')].map((t) => t.textContent)[1] === %s" % json.dumps(other)))
            verdict("…and the choice is the owner's now", await until("!document.querySelector('.tagpick .opt.auto').classList.contains('on')"))
            await js("[...document.querySelectorAll('.tagpick .pills .tagf.add')].pop().click()")   # the topics' "New topic"
            verdict("a field for a new topic", await until("!!document.querySelector('.tagnew input')"))
            await js("(() => { const i = document.querySelector('.tagnew input'); const set = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set;"
                     " set.call(i, 'Термопаста'); i.dispatchEvent(new Event('input', {bubbles: true})); })()")
            await js("document.querySelector('.tagnew .btn').click()")
            verdict("a new topic by name", await until("[...document.querySelectorAll('.sess-tags .tagc')].map((t) => t.textContent)[1] === 'Термопаста'"))
            await shot("4-new-topic.png")
            await goto(URLS["SESST"])
            verdict("…kept by the computer after a reload", await until("[...document.querySelectorAll('.sess-tags .tagc')].map((t) => t.textContent)[1] === 'Термопаста'", 150))
            await js("document.querySelector('.sess-tags').click()")
            await until("!!document.querySelector('.tagpick')")
            await js("document.querySelector('.tagpick .opt.auto').click()")
            verdict("back to Claude", await until("document.querySelector('.tagpick .opt.auto').classList.contains('on')"))

            # Home: what runs and what waits carry the tags on their top line, beside the project — never in front of the
            # words: there they ate the one line of a running task (2026-10-26); a tag that doesn't fit is left out
            # whole, and the project's name stays on one line (squeezed into a column of letters once — 0.17.2)
            await goto(URLS["HOME"])
            verdict("Home's rows have tags", await until("document.querySelectorAll('.item.run .tagc, .item.brow .tagc').length >= 4", 150))
            run = await js("[...document.querySelectorAll('.item.run')].map((r) => { const t = r.querySelector('.run-t'), cs = getComputedStyle(t);"
                           " return {title: t.textContent.trim(), lines: Math.round(t.getBoundingClientRect().height / parseFloat(cs.lineHeight)),"
                           " cut: t.scrollHeight > t.clientHeight + 1, ask: (r.querySelector('.run-ask') || {}).textContent || '',"
                           " now: (r.querySelector('.run-now') || {}).textContent || '', top: !!r.querySelector('.run-w .tagc'),"
                           " inWords: !!r.querySelector('.run-ask .tagc, .run-now .tagc, .run-t .tagc')}; })")
            verdict("Running now: every title whole, two lines at most", run and all(x["lines"] <= 2 and not x["cut"] for x in run), run)
            follow = [x for x in run if x["ask"] and x["now"]]
            verdict("…a later turn: what you asked, then what Claude says", len(follow) >= 1 and follow[0]["ask"].startswith(("Ты: ", "You: ")), follow)
            verdict("…a turn Claude hasn't spoken in yet: what you asked", any(x["ask"] and not x["now"] for x in run), run)
            verdict("…the tags on the top line, none in front of the words", any(x["top"] for x in run) and not any(x["inWords"] for x in run), run)
            whole = await js("[...document.querySelectorAll('.run-w')].every((w) => { const b = w.getBoundingClientRect();"
                             " return [...w.querySelectorAll('.tagc')].every((t) => { const r = t.getBoundingClientRect();"
                             " return r.top >= b.bottom - 1 || r.right <= b.right + 0.5; }); })")
            verdict("…a tag that doesn't fit is left out whole", whole)
            card = await js("(() => { const c = [...document.querySelectorAll('.card.mine')].find((x) => x.querySelector('.tagc') && x.querySelector('.run-p'));"
                            " if (!c) return null; const n = c.querySelector('.run-p').getBoundingClientRect(), t = c.querySelector('.tagc');"
                            " return [n.height, !!t.closest('.c-proj'), !!t.closest('.ln, .now')]; })()")
            verdict("a your-move card: the project's name on one line, the tags beside it, the line whole",
                    card is not None and card[0] < 24 and card[1] and not card[2], card)
            await shot("5-home.png")
            verdict("no errors in the page", not errors, errors)
    finally:
        p.terminate()
    print("screenshots:", OUT)
    sys.exit(1 if failures else 0)


asyncio.run(main())
