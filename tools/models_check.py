"""The model menus with Claude Code's own names (Q173), in headless Chrome over DevTools, on the stand, with real taps:
a session that would continue on the app's Claude Code — "Fable 5.2", "Opus 5.5", "Sonnet 5.5", "Haiku 5.5" on top and
the older ones under "Other versions"; a pick there says its version under the message field, "▸" while the last request
ran on another model; a VS Code tab on an older Claude Code (2.1.301 on the stand) — its own list: Fable 5.2 a row of its
own on top, "fable" — Fable 5.1 — among the others; New task and Settings → Model and effort the same, their fields with
the version. With `none` (a stand with STAND_CCM=none) — no list known yet: the four names without versions, as before.
  STAND_LANG=ru STAND_TAB=1 STAND_PORT=18133 HOLD=300 ~/.local/share/pult/venv/bin/python tools/stand.py > /tmp/stand.out &
  ~/.local/share/pult/venv/bin/python tools/models_check.py /tmp/stand.out [out_dir | none]
Screenshots go to out_dir (a temporary folder by default). Exit 1 on a failed check."""
import asyncio, base64, json, os, subprocess, sys, tempfile
import aiohttp

URLS = dict(line.split(" ", 1) for line in open(sys.argv[1]).read().split("\n") if line[:4] in ("SETT", "NEW ", "SESS"))
NONE = len(sys.argv) > 2 and sys.argv[2] == "none"
OUT = sys.argv[2] if len(sys.argv) > 2 and not NONE else tempfile.mkdtemp(prefix="pult-models-")
os.makedirs(OUT, exist_ok=True)
import _cdp  # noqa: E402  (tools/_cdp.py: where Chrome is, free ports, a profile that goes — review 2026-10-27, Т9)
CHROME = _cdp.CHROME
PORT = _cdp.free_port()
failures = []
MAIN = ["Fable 5.2", "Opus 5.5", "Sonnet 5.5", "Haiku 5.5"]
MORE = ["Fable 5.1", "Fable 5", "Opus 5", "Opus 4.8", "Opus 4.7", "Opus 4.6", "Sonnet 5", "Sonnet 4.6", "Haiku 4.5"]


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

            async def tap_in(sel, label):
                """A button of the open menu by its own words, the grey part aside: sel — '.pick-col' (the first is the
                model's) or '.pick-chips' (Other versions)."""
                r = await js("(() => { const c = document.querySelector('.card.pick %s'); if (!c) return null;"
                             " const el = [...c.querySelectorAll('.opt')].find((o) => o.firstChild && o.firstChild.textContent.trim() === %s);"
                             " if (!el) return null; el.scrollIntoView({block: 'nearest'}); const b = el.getBoundingClientRect();"
                             " return [b.left + b.width / 2, b.top + b.height / 2]; })()" % (sel, json.dumps(label)))
                if not r:
                    raise RuntimeError("no option %r in %s" % (label, sel))
                await tap_at(r)

            # the menu as words: the model column [words, on] and Other versions [words, on]
            col = ("[...document.querySelectorAll('.card.pick .pick-col')[0].querySelectorAll('.opt')].map((o) =>"
                   " [o.firstChild ? o.firstChild.textContent.trim() : '', o.classList.contains('on')])")
            more = ("[...document.querySelectorAll('.card.pick .pick-chips .opt')].map((o) => [o.textContent.trim(), o.classList.contains('on')])")
            chip = "(document.querySelector('.mchip span') || {}).textContent"
            last_field = "[...document.querySelectorAll('.form .field')].pop().textContent.trim()"

            async def goto(url):
                """A fresh load: the stand's links differ only after #, and that alone would not reload the app."""
                await cmd("Page.navigate", url="about:blank")
                await cmd("Page.navigate", url=url)

            async def session_menu(key):
                await goto(URLS[key])
                if not await until("!!document.querySelector('.mchip.on')", 150):
                    return False
                await tap(".mchip.on")
                return await until("!!document.querySelector('.card.pick .pick-col')")

            async def words(expr):
                return [w for w, _ in await js(expr)]

            async def picked(expr):
                return [w for w, on in await js(expr) if on]

            await cmd("Page.enable")
            await cmd("Runtime.enable")
            await cmd("Emulation.setDeviceMetricsOverride", width=412, height=860, deviceScaleFactor=2, mobile=True)
            await cmd("Emulation.setTouchEmulationEnabled", enabled=True, maxTouchPoints=5)

            if NONE:
                # no list known yet: as before Q173 — the four names, nothing under the columns
                verdict("the session's menu opens", await session_menu("SESS4"))
                got = await words(col)
                verdict("the four names without versions", got[1:] == ["Fable", "Opus", "Sonnet", "Haiku"], got)
                verdict("no Other versions", await js("!document.querySelector('.card.pick .pick-more')"))
                await tap_in(".pick-col", "Fable")
                verdict("Fable is picked; under the field — «Fable ▸»", await until("%s === 'Fable ▸'" % chip), await js(chip))
                await shot("1-none.png")
                await tap_in(".pick-col", (await words(col))[0])        # back to Default
                await until("!(%s).some(([w, on]) => w === 'Fable' && on)" % col)
                verdict("no script errors", not errors, errors)
                return

            # a session that would continue on the app's Claude Code: its list — "fable" is Fable 5.2 there
            verdict("the session's menu opens", await session_menu("SESS4"))
            got = await words(col)
            verdict("the model column: Default, then the four with versions", got[1:] == MAIN, got)
            got = await words(more)
            verdict("Other versions: the rest of Claude Code's list, newest first in each family", got == MORE, got)
            await tap_in(".pick-col", "Fable 5.2")
            verdict("Fable 5.2 is picked", await until("(%s).some(([w, on]) => w === 'Fable 5.2' && on)" % col))
            verdict("under the field — «Fable 5.2 ▸»: the last request ran on Opus 5.5",
                    await until("%s === 'Fable 5.2 ▸'" % chip), await js(chip))
            await shot("1-session-fable.png")
            await tap_in(".pick-chips", "Fable 5.1")
            verdict("Fable 5.1 from Other versions is picked, and only it",
                    await until("JSON.stringify(%s) === '[\"Fable 5.1\"]' && !(%s).some(([w, on]) => on && w !== '')" % (
                        "(%s).filter(([w, on]) => on).map(([w]) => w)" % more, col)), await picked(more), await picked(col))
            verdict("under the field — «Fable 5.1 ▸»", await until("%s === 'Fable 5.1 ▸'" % chip), await js(chip))
            await shot("2-session-more.png")
            await cmd("Emulation.setEmulatedMedia", features=[{"name": "prefers-color-scheme", "value": "dark"}])
            await shot("2-session-more-dark.png")
            await cmd("Emulation.setEmulatedMedia", features=[{"name": "prefers-color-scheme", "value": "light"}])
            await tap_in(".pick-col", "Opus 5.5")
            verdict("Opus 5.5 — the model the last request ran on: no «▸»", await until("%s === 'Opus 5.5'" % chip), await js(chip))
            await tap_in(".pick-col", (await words(col))[0])            # back to Default
            await until("(%s)[0][1]" % col)

            # a VS Code tab on an older Claude Code: its own list
            verdict("the tab's menu opens", await session_menu("SESS"))
            got = await words(col)
            verdict("the tab's column: Fable 5.2 on top there too (a row of its own)", got[1:] == MAIN, got)
            got = await words(more)
            verdict("…and Fable 5.1 among the others — the tab's «fable»", got == MORE, got)
            await tap_in(".pick-chips", "Fable 5.1")
            verdict("the tab takes Fable 5.1: under the field — «Fable 5.1 ▸»", await until("%s === 'Fable 5.1 ▸'" % chip), await js(chip))
            await shot("3-tab.png")
            await tap_in(".pick-col", (await words(col))[0])
            await until("(%s)[0][1]" % col)

            # a new task: the app's list; the field says the version
            await goto(URLS["NEW"])
            await until("document.querySelectorAll('.form .field').length >= 2", 150)
            await tap(".form .field", await js("document.querySelectorAll('.form .field').length - 1"))   # the model's: the last
            verdict("New task: its menu opens", await until("!!document.querySelector('.card.pick .pick-col')"))
            got = await words(col)
            verdict("…the four with versions, Other versions under them", got[1:] == MAIN and await words(more) == MORE, got)
            await tap_in(".pick-chips", "Haiku 4.5")
            await tap(".card.pick .x")
            await until("!document.querySelector('.card.pick')")
            got = await js(last_field)
            verdict("…its field says «Haiku 4.5 · …»", got.startswith("Haiku 4.5 · "), repr(got))
            await shot("4-new.png")

            # Settings → Model and effort: Pult's default, the same names
            await goto(URLS["SETTINGS"])
            hdr = "[...document.querySelectorAll('h3')].findIndex((e) => /Модель и раздумья|Model and effort/.test(e.textContent))"
            await until("%s >= 0" % hdr, 150)
            await js("document.querySelectorAll('h3')[%s].scrollIntoView({block: 'start'})" % hdr)
            await tap("h3 + .field")
            verdict("Settings: its menu opens", await until("!!document.querySelector('.card.pick .pick-col')"))
            got = await words(col)
            verdict("…the four with versions", got[1:] == MAIN, got)
            await tap_in(".pick-col", "Sonnet 5.5")
            await tap(".card.pick .x")
            await until("!document.querySelector('.card.pick')")
            field = ("(() => { const h = [...document.querySelectorAll('h3')].find((e) => /Модель и раздумья|Model and effort/.test(e.textContent));"
                     " const f = h && h.nextElementSibling; return f ? f.textContent.trim() : null; })()")
            got = await js(field)
            verdict("…the field says «Sonnet 5.5 · …»", (got or "").startswith("Sonnet 5.5 · "), repr(got))
            await js("document.querySelectorAll('h3')[%s].scrollIntoView({block: 'start'})" % hdr)
            await tap("h3 + .field")
            await until("!!document.querySelector('.card.pick .pick-col')")
            await tap_in(".pick-col", (await words(col))[0])          # back to Claude Code's settings
            await tap(".card.pick .x")
            verdict("no script errors", not errors, errors)
    finally:
        p.kill()
        print("screenshots:", OUT)
        sys.exit(1 if failures else 0)


asyncio.run(main())
