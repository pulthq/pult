"""Task tags (stage T) in headless Chrome over DevTools, on the stand, with real taps: the printer's project shows each
task's section and topic and the bar of its sections; a tap on a section narrows every list to it (the earlier ones
open by themselves) and shows its topics, a tap on a topic narrows further, "All" brings everything back; a task's
sheet changes its topic (saved by the computer: still there after a reload), takes a new topic by name, and gives the
choice back to Claude; Home's cards carry the tags on their top line, beside the project — the running ones show their
title whole, what was asked and what Claude says (0.17.3). The project's tags screen (T2): Claude's offer to merge, the
sections with their tasks, a new topic kept, a section renamed, recoloured, hidden and back, a topic merged.
  STAND_TAGS=1 STAND_LANG=ru STAND_PORT=18151 HOLD=300 ~/.local/share/pult/venv/bin/python tools/stand.py > /tmp/stand.out &
  ~/.local/share/pult/venv/bin/python tools/tags_check.py /tmp/stand.out [out_dir]
Screenshots go to out_dir (a temporary folder by default); TAGS_DARK=1 — in the phone's dark theme. A stand with
STAND_TAGJOB=1 too (a made-up model) — only the part where Claude sorts the earlier tasks and "Sort them again".
Exit 1 on a failed check."""
import asyncio, base64, json, os, subprocess, sys, tempfile
import aiohttp

URLS = dict(line.split(" ", 1) for line in open(sys.argv[1]).read().split("\n") if line[:5] in ("PROJT", "SESST", "HOME ", "TAGJO"))
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

            async def calm():
                """The toast of the last change gone — a frame without it."""
                await until("!document.querySelector('.toast')", 40)

            async def goto(url):
                """A fresh load: the stand's links differ only after #, and that alone would not reload the app."""
                await cmd("Page.navigate", url="about:blank")
                await cmd("Page.navigate", url=url)

            # the rows' titles on the project's screen; each row's tags as [section, topic]
            row_tags = ("[...document.querySelectorAll('.project .card.mine, .project .item.brow, .project .item.run')].map((r) =>"
                        " [...r.querySelectorAll('.tagc')].map((t) => t.textContent.trim()))")
            bar = lambda sub: ("[...document.querySelectorAll('.tagbar%s .tagf')].map((b) => [b.firstChild && b.firstChild.nodeType === 3 ?"
                               " b.firstChild.textContent.trim() : b.textContent.replace(/\\d+$/, '').trim(), b.classList.contains('on')])" % (".sub" if sub else ":not(.sub)"))

            async def job_part():
                """STAND_TAGJOB=1 (T2, a made-up model): the project's first open — Claude sorts its earlier tasks by
                itself, "N of M" under the bar, every one with its section after; "Sort them again" on its tags screen —
                asked first, the list made anew, the tasks sorted again, the owner's own tags kept."""
                await goto(URLS["PROJT"])
                verdict("the first open: Claude sorts the earlier tasks, its line under the bar",
                        await until("/\\d/.test((document.querySelector('.project .tidy-run') || {}).textContent || '')", 150))
                ru = await js("document.documentElement.lang") == "ru"
                await shot("12-job.png")
                verdict("…the line goes when they are sorted", await until("!document.querySelector('.project .tidy-run')", 300))
                await js("document.querySelector('.project h3.toggle').click()")
                ok = await until("document.querySelectorAll('.project .item.brow.rest').length >= 20")
                rows = await js("[...document.querySelectorAll('.project .item.brow.rest')].map((r) => r.querySelectorAll('.tagc').length)")
                verdict("…every earlier task has its section", ok and all(n >= 1 for n in rows), rows)
                await js("document.querySelector('.project h3.toggle').scrollIntoView({block: 'start'})")
                await shot("13-sorted.png")
                await js("window.__said = []; window.confirm = (s) => (window.__said.push(String(s)), true);"
                         " const w = window.Telegram && window.Telegram.WebApp; if (w) w.showConfirm = (s, cb) => (window.__said.push(String(s)), cb(true));")
                await tap_text(".tagrow .tagf.edit", "")
                verdict("the tags screen: Sort them again, the model on", await until("!!document.querySelector('.tagscr .tbtns .btn:not([disabled])')", 100))
                await js("document.querySelector('.tagscr .tbtns .btn').click()")
                verdict("…asked first", await until("window.__said.length === 1"), await js("window.__said"))
                verdict("…Claude makes the list anew", await until("/…/.test((document.querySelector('.tagscr .tidy-run') || {}).textContent || '')", 60))
                await shot("14-resort.png")
                verdict("…then sorts the tasks, N of M", await until("/\\d/.test((document.querySelector('.tagscr .tidy-run') || {}).textContent || '')", 100))
                await shot("15-resorting.png")
                verdict("…done", await until("!document.querySelector('.tagscr .tidy-run')", 300))
                names = await js("[...document.querySelectorAll('.tagscr .list .trow:not(.hid) .tn')].map((n) => n.textContent.trim())")
                new_docs, old_docs = ("Инструкции", "Документы") if ru else ("Manuals", "Docs")
                verdict("…the new list's name, and the owner's own section kept", new_docs in names and old_docs in names, names)
                await shot("16-resorted.png")
                verdict("no errors in the page", not errors, errors)

            await cmd("Page.enable")
            await cmd("Runtime.enable")
            await cmd("Emulation.setDeviceMetricsOverride", width=412, height=860, deviceScaleFactor=2, mobile=True)
            await cmd("Emulation.setTouchEmulationEnabled", enabled=True, maxTouchPoints=5)
            if os.environ.get("TAGS_DARK") == "1":           # the phone's dark theme: frames for the owner in both
                await cmd("Emulation.setEmulatedMedia", features=[{"name": "prefers-color-scheme", "value": "dark"}])

            if "TAGJOB" in URLS:
                await job_part()
                return
            # the project: every task with its two tags; the bar of sections, "All" on
            await goto(URLS["PROJT"])
            verdict("the project's tag bar", await until("!!document.querySelector('.tagbar .tagf')", 150))
            ru = await js("document.documentElement.lang") == "ru"
            newt = "Термопаста" if ru else "Thermal paste"                # a topic of the owner's, by name
            edge = await js("(() => { const e = document.querySelector('.tagrow .tagf.edit').getBoundingClientRect();"
                            " return e.left >= 0 && e.right <= innerWidth; })()")
            verdict("…the way to the project's tags in sight, however many sections", edge)
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
                     " set.call(i, %s); i.dispatchEvent(new Event('input', {bubbles: true})); })()" % json.dumps(newt))
            await js("document.querySelector('.tagnew .btn').click()")
            verdict("a new topic by name", await until("[...document.querySelectorAll('.sess-tags .tagc')].map((t) => t.textContent)[1] === %s" % json.dumps(newt)))
            await shot("4-new-topic.png")
            await goto(URLS["SESST"])
            verdict("…kept by the computer after a reload", await until("[...document.querySelectorAll('.sess-tags .tagc')].map((t) => t.textContent)[1] === %s" % json.dumps(newt), 150))
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

            # T2: the project's tags — from the bar's last button: Claude's offer on top, every section with its tasks,
            # the busiest first; the topic Claude has just made dashed, "Keep" makes it plain; the offer taken — two
            # topics are one; a section renamed (to a name taken — asked to merge), recoloured, hidden and back; a
            # topic merged through its own sheet. Everything by taps, as the computer keeps it after a reload
            await goto(URLS["PROJT"])
            await until("!!document.querySelector('.tagrow .tagf.edit')", 150)
            ru = await js("document.documentElement.lang") == "ru"
            await js("window.__said = []; window.__yes = true; window.alert = (s) => window.__said.push(String(s));"
                     " window.confirm = (s) => (window.__said.push(String(s)), window.__yes);"
                     " const w = window.Telegram && window.Telegram.WebApp; if (w) { w.showAlert = (s) => window.__said.push(String(s));"
                     " w.showConfirm = (s, cb) => (window.__said.push(String(s)), cb(window.__yes)); }")
            await tap_text(".tagrow .tagf.edit", "")
            verdict("the bar's last button opens the project's tags",
                    await until("location.hash.startsWith('#/tags/') && document.querySelectorAll('.tagscr .list .trow').length >= 5", 100))
            rows_js = ("[...document.querySelectorAll('.tagscr .list .trow:not(.hid)')].map((r) => [r.querySelector('.tn').textContent.trim(),"
                       " +r.querySelector('.cnt-n').textContent, [...r.querySelectorAll('.ttops .tagc')].map((c) => c.firstChild.textContent.trim()),"
                       " getComputedStyle(r).getPropertyValue('--th').trim()])")
            rows = await js(rows_js)
            verdict("every section with its tasks, the busiest first", sum(r[1] for r in rows) == 15
                    and [r[1] for r in rows] == sorted([r[1] for r in rows], reverse=True), [(r[0], r[1]) for r in rows])
            sug = await js("[...document.querySelectorAll('.card.tsug')].map((c) => c.textContent)")
            verdict("Claude's offer to merge two topics, on top", len(sug) == 1 and "Wi-Fi" in sug[0], sug)
            fresh = await js("[...document.querySelectorAll('.tagscr .ttops .tagc.fresh')].map((c) => c.textContent.trim())")
            verdict("the topic Claude has just made: dashed, with its line", len(fresh) == 1 and await js("!!document.querySelector('.trow .tfresh')"), fresh)
            await shot("6-tags.png")
            await js("document.querySelector('.trow .tfresh .link').click()")              # Keep
            verdict("…Keep makes it plain", await until("!document.querySelector('.tagscr .tagc.fresh') && !document.querySelector('.trow .tfresh')"))
            await tap_text(".card.tsug .btn", "")                                           # Merge
            has_wifi = "[...document.querySelectorAll('.tagscr .ttops .tagc')].some((c) => c.firstChild.textContent.trim() === 'Wi-Fi')"
            verdict("the offer taken: the two topics are one", await until("!document.querySelector('.card.tsug') && !(%s)" % has_wifi))
            async def open_row(name):
                """A section's row open, its actions under it — tapped only if it isn't open already (a tap folds it)."""
                if not await js("(() => { const r = document.querySelector('.trow.open'); return !!r && r.querySelector('.tn').textContent.trim() === %s; })()"
                                % json.dumps(name)):
                    await tap_text(".tagscr .trow-h", name)
                return await until("!!document.querySelector('.trow.open .tacts')")

            # the last section: its actions, then a name of its own
            last = rows[-1][0]
            new = "Руководства" if ru else "Manuals"
            verdict("a section opens its actions", await open_row(last))
            await calm()
            await shot("7-actions.png")
            await js("document.querySelector('.trow.open .tacts .link:nth-child(1)').click()")       # Rename
            verdict("…the rename sheet, the name in its field", await until("(document.querySelector('.tagsheet .tagnew input') || {}).value === %s" % json.dumps(last)))
            set_name = ("(() => { const i = document.querySelector('.tagsheet .tagnew input'); const set = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,"
                        " 'value').set; set.call(i, %s); i.dispatchEvent(new Event('input', {bubbles: true})); })()")
            await js(set_name % json.dumps(rows[0][0].lower()))                                # a name another section has
            await js("window.__yes = false; window.__said = []")
            await js("document.querySelector('.tagsheet .tagnew .btn').click()")
            verdict("a name taken: asked to merge, nothing changed unasked", await until("window.__said.length === 1")
                    and await until("!!document.querySelector('.tagsheet .tagnew input')") and last in [r[0] for r in await js(rows_js)], await js("window.__said"))
            await js("window.__yes = true")
            await js(set_name % json.dumps(new))
            await js("document.querySelector('.tagsheet .tagnew .btn').click()")
            verdict("renamed, the sheet closed", await until("!document.querySelector('.tagsheet') && (%s).some((r) => r[0] === %s)" % (rows_js, json.dumps(new))))
            await open_row(new)
            await js("document.querySelector('.trow.open .tacts .link:nth-child(2)').click()")       # Colour
            verdict("the colour sheet: eight", await until("document.querySelectorAll('.tagsheet .swatch').length === 8"))
            await calm()
            await shot("8-colour.png")
            await js("document.querySelectorAll('.tagsheet .swatch')[5].click()")
            verdict("…a new colour", await until("(%s).find((r) => r[0] === %s)[3] === '190'" % (rows_js, json.dumps(new))))
            # hidden: gone from the list and the project's bar, in its own group; back from there
            await open_row(new)
            await js("document.querySelector('.trow.open .tacts .link:nth-child(4)').click()")       # Hide
            verdict("hidden: out of the list, in the folded group", await until("!(%s).some((r) => r[0] === %s) && !!document.querySelector('.tagscr h3.toggle')" % (rows_js, json.dumps(new))))
            await js("history.back()")
            verdict("…and not in the project's bar", await until("!!document.querySelector('.project .tagbar') && ![...document.querySelectorAll('.tagbar .tagf')]"
                                                               ".some((b) => b.textContent.startsWith(%s))" % json.dumps(new)))
            await js("history.forward()")
            await until("!!document.querySelector('.tagscr h3.toggle')")
            await js("document.querySelector('.tagscr h3.toggle').click()")
            await until("!!document.querySelector('.trow.hid .link')")
            await calm()
            await shot("9-hidden.png")
            await js("document.querySelector('.trow.hid .link').click()")                     # Show again
            verdict("…back in the list", await until("(%s).some((r) => r[0] === %s) && !document.querySelector('.trow.hid')" % (rows_js, json.dumps(new))))
            # a topic's own sheet: merge it into another topic of its section
            two = next(r for r in await js(rows_js) if len(r[2]) >= 2)
            await tap_text(".tagscr .ttops .tagc", two[2][0])
            verdict("a topic's sheet", await until("document.querySelectorAll('.tagsheet .opt').length >= 3"))
            await js("[...document.querySelectorAll('.tagsheet .opt')].find((o) => /Слить|Merge/.test(o.textContent)).click()")
            verdict("…merge into: the topics of its section first", await until("(document.querySelector('.tagsheet .pick-t') || {}).textContent === %s" % json.dumps(two[0])))
            await calm()
            await shot("10-merge.png")
            await tap_text(".tagsheet .pills .tagf", two[2][1])
            verdict("…merged", await until("(%s).find((r) => r[0] === %s)[2].indexOf(%s) < 0" % (rows_js, json.dumps(two[0]), json.dumps(two[2][0]))))
            await goto(URLS["PROJT"])
            await until("!!document.querySelector('.tagrow .tagf.edit')", 150)
            await tap_text(".tagrow .tagf.edit", "")
            await until("document.querySelectorAll('.tagscr .list .trow').length >= 5", 100)
            after = await js(rows_js)
            verdict("the computer keeps it all after a reload", any(r[0] == new and r[3] == "190" for r in after)
                    and not any("Wi-Fi" in r[2] or two[2][0] in r[2] for r in after) and sum(r[1] for r in after) == 15, [(r[0], r[1], r[2]) for r in after])
            await shot("11-after.png")
            verdict("no errors in the page", not errors, errors)
    finally:
        p.terminate()


asyncio.run(main())
print("screenshots:", OUT)
sys.exit(1 if failures else 0)
