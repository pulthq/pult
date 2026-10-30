"""Settings → Model and effort (Pult's own default for the sessions it starts), in headless Chrome over DevTools, on the
stand, with real taps: nothing set — "As in Claude Code's settings", and the menu shows in grey what those settings say
(the stand's made-up effort "high"); Opus and Extra high picked there stay after a reload; a new task then says
"Opus · Extra high" with nothing picked, and its menu shows the default in grey; the session's menu says whose default
"Default" is; back to "As in Claude Code" — as before.
  STAND_LANG=ru STAND_PORT=18131 HOLD=300 ~/.local/share/pult/venv/bin/python tools/stand.py > /tmp/stand.out &
  ~/.local/share/pult/venv/bin/python tools/choice_check.py /tmp/stand.out [out_dir]
Screenshots go to out_dir (a temporary folder by default). Exit 1 on a failed check."""
import asyncio, base64, json, os, subprocess, sys, tempfile
import aiohttp

URLS = dict(line.split(" ", 1) for line in open(sys.argv[1]).read().split("\n") if line[:4] in ("SETT", "NEW ", "SESS"))
OUT = sys.argv[2] if len(sys.argv) > 2 else tempfile.mkdtemp(prefix="pult-choice-")
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

            async def tap(sel, i=0):
                """A finger on the element's middle — not el.click(): what is on top there gets it."""
                r = await js("(() => { const el = document.querySelectorAll(%s)[%d]; if (!el) return null; el.scrollIntoView({block: 'nearest'});"
                             " const b = el.getBoundingClientRect(); return [b.left + b.width / 2, b.top + b.height / 2]; })()" % (json.dumps(sel), i))
                if not r:
                    raise RuntimeError("nothing to tap: " + sel)
                await tap_at(r)

            async def tap_opt(col, label):
                """An option of the open menu's column (0 — model, 1 — effort) by its own words, the grey part aside."""
                r = await js("(() => { const c = document.querySelectorAll('.card.pick .pick-col')[%d]; if (!c) return null;"
                             " const el = [...c.querySelectorAll('.opt')].find((o) => o.firstChild && o.firstChild.textContent.trim() === %s);"
                             " if (!el) return null; el.scrollIntoView({block: 'nearest'}); const b = el.getBoundingClientRect();"
                             " return [b.left + b.width / 2, b.top + b.height / 2]; })()" % (col, json.dumps(label)))
                if not r:
                    raise RuntimeError("no option %r in column %d" % (label, col))
                await tap_at(r)

            # the Settings block: its field, and the menu's options as [words, grey part, on]
            field = "(() => { const h = [...document.querySelectorAll('h3')].find((e) => /Модель и раздумья|Model and effort/.test(e.textContent));" \
                    " const f = h && h.nextElementSibling; return f && f.classList.contains('field') ? f.textContent.trim() : null; })()"
            opts = lambda col: ("[...document.querySelectorAll('.card.pick .pick-col')[%d].querySelectorAll('.opt')].map((o) =>"
                                " [o.firstChild ? o.firstChild.textContent.trim() : '', (o.querySelector('.dim') || {}).textContent || '',"
                                " o.classList.contains('on')])" % col)
            first = lambda col: "(%s)[0]" % opts(col)
            settings_field = "[...document.querySelectorAll('h3')].findIndex((e) => /Модель и раздумья|Model and effort/.test(e.textContent))"

            async def goto(url):
                """A fresh load: the stand's links differ only after #, and that alone would not reload the app."""
                await cmd("Page.navigate", url="about:blank")
                await cmd("Page.navigate", url=url)

            async def open_menu():
                """The block's heading at the top (the bottom bar would cover the field), then a tap on the field."""
                await js("document.querySelectorAll('h3')[%s].scrollIntoView({block: 'start'})" % settings_field)
                await tap("h3 + .field")
                return await until("!!document.querySelector('.card.pick .pick-col')")

            async def open_settings():
                await goto(URLS["SETTINGS"])
                return await until("%s !== null" % field, 150)

            await cmd("Page.enable")
            await cmd("Runtime.enable")
            await cmd("Emulation.setDeviceMetricsOverride", width=412, height=860, deviceScaleFactor=2, mobile=True)
            await cmd("Emulation.setTouchEmulationEnabled", enabled=True, maxTouchPoints=5)

            # nothing set: as Claude Code's settings say
            verdict("Settings has Model and effort", await open_settings())
            got = await js(field)
            verdict("…set to Claude Code's settings", got in ("Как в настройках Claude Code", "As in Claude Code's settings"), repr(got))
            await js("document.querySelectorAll('h3')[%s].scrollIntoView({block: 'start'})" % settings_field)
            await shot("1-settings.png")
            verdict("the menu opens", await open_menu())
            m0, e0 = await js(first(0)), await js(first(1))
            verdict("its first line is “As in Claude Code”, picked", m0[0] in ("Как в Claude Code", "As in Claude Code") and m0[2] and e0[2], m0, e0)
            verdict("…with Claude Code's effort in grey", e0[1] in ("Много", "High"), e0)
            verdict("…and no model in grey (the settings name none)", m0[1] == "", m0)
            await shot("2-menu.png")

            # Opus and Extra high: kept by the computer
            await tap_opt(0, "Opus")
            verdict("Opus is picked", await until("(%s).some(([w, g, on]) => w === 'Opus' && on)" % opts(0)))
            await tap_opt(1, "Очень много" if "Много" in e0[1] else "Extra high")
            verdict("Extra high is picked", await until("(%s).some(([w, g, on]) => /Очень много|Extra high/.test(w) && on)" % opts(1)))
            await shot("3-picked.png")
            await cmd("Emulation.setEmulatedMedia", features=[{"name": "prefers-color-scheme", "value": "dark"}])
            await shot("3-picked-dark.png")
            await cmd("Emulation.setEmulatedMedia", features=[{"name": "prefers-color-scheme", "value": "light"}])
            await tap(".card.pick .x")
            verdict("the menu closes", await until("!document.querySelector('.card.pick')"))
            want = ("Opus · Очень много", "Opus · Extra high")
            verdict("the field says it", await until("%s(%s)" % (json.dumps(list(want)) + ".includes", field)), await js(field))
            verdict("…after a reload too", await open_settings() and await js(field) in want, await js(field))

            # a new task: the default with nothing picked; its menu shows it in grey
            await goto(URLS["NEW"])
            await until("document.querySelectorAll('.form .field').length >= 2", 150)
            got = await js("[...document.querySelectorAll('.form .field')].pop().textContent.trim()")
            verdict("a new task starts with it", got in want, repr(got))
            await tap(".form .field", await js("document.querySelectorAll('.form .field').length - 1"))   # the model's: the last
            verdict("its menu opens", await until("!!document.querySelector('.card.pick .pick-col')"))
            m0, e0 = await js(first(0)), await js(first(1))
            verdict("…“Default”, with the default in grey", m0[0] in ("По умолчанию", "Default") and m0[1] == "Opus" and e0[1] in ("Очень много", "Extra high"), m0, e0)
            await shot("4-new.png")
            await tap_opt(0, "Sonnet")
            await tap(".card.pick .x")
            await until("!document.querySelector('.card.pick')")
            got = await js("[...document.querySelectorAll('.form .field')].pop().textContent.trim()")
            verdict("a pick of its own wins, the effort stays the default", got in ("Sonnet · Очень много", "Sonnet · Extra high"), repr(got))

            # the session's menu: whose default "Default" is
            for k in sorted(x for x in URLS if x.startswith("SESS")):
                await goto(URLS[k])
                if await until("!!document.querySelector('.mchip.on')", 60):
                    break
            if await js("!!document.querySelector('.mchip.on')"):
                await tap(".mchip.on")
                await until("!!document.querySelector('.card.pick .pick-col')")
                note = await js("[...document.querySelectorAll('.card.pick .dim.small')].map((e) => e.textContent).join(' ')")
                ours = await js("(() => { const t = document.querySelector('.card.pick').textContent; return /Настройках Пульта|Pult's Settings/.test(t); })()")
                verdict("the session's menu names whose default it is",
                        ours or "настройках Claude Code" in note or "Claude Code's settings" in note, repr(note))
                await shot("5-session.png")
            else:
                print("skip the session's menu: the model can't be picked in the stand's session")

            # back to Claude Code's settings
            await open_settings()
            await open_menu()
            await tap_opt(0, "Как в Claude Code" if "Как" in (await js(first(0)))[0] else "As in Claude Code")
            await until("(%s)[2]" % first(0))
            await tap_opt(1, "Как в Claude Code" if "Как" in (await js(first(1)))[0] else "As in Claude Code")
            await until("(%s)[2]" % first(1))
            await tap(".card.pick .x")
            await until("!document.querySelector('.card.pick')")
            got = await js(field)
            verdict("back to Claude Code's settings", got in ("Как в настройках Claude Code", "As in Claude Code's settings"), repr(got))
            verdict("no script errors", not errors, errors)
    finally:
        p.kill()
    print("screenshots:", OUT)
    sys.exit(1 if failures else 0)


asyncio.run(main())
