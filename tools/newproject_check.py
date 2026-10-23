"""The app's "New project" screen (stage S) in headless Chrome over DevTools, on the stand: the folder's name follows
the title, the place is picked level by level, a place outside the tabs' folders says so, "with a description" makes
the project and starts its first turn, a taken name is refused, a clone link names the folder; the ways in from "+"
and from Projects.
  STAND_LANG=ru HOLD=300 ~/.local/share/pult/venv/bin/python tools/stand.py > /tmp/stand.out &
  ~/.local/share/pult/venv/bin/python tools/newproject_check.py "$(grep '^NEWPROJ ' /tmp/stand.out | cut -d' ' -f2)" [out_dir]
Run it on a fresh stand: the stand's made-up home keeps what the check made. Screenshots go to out_dir (a temporary
folder by default). Exit 1 on a failed check. The stand runs in either language; the titles typed here are Russian on
purpose — that is what the folder's name is made from."""
import asyncio, base64, json, os, subprocess, sys, tempfile
import aiohttp

URL = sys.argv[1]
OUT = sys.argv[2] if len(sys.argv) > 2 else tempfile.mkdtemp(prefix="pult-newproject-")
os.makedirs(OUT, exist_ok=True)
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
PORT = 9335
failures = []


def verdict(name, ok, *info):
    print(("ok   " if ok else "FAIL ") + name, *info)
    if not ok:
        failures.append(name)


async def main():
    prof = tempfile.mkdtemp(prefix="cdp-")
    p = subprocess.Popen([CHROME, "--headless=new", "--disable-gpu", "--hide-scrollbars", "--remote-debugging-port=%d" % PORT,
                          "--user-data-dir=" + prof, "--no-first-run", "--window-size=412,915", "about:blank"],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
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

            async def tap(expr):            # an element found by a JS expression
                await js("(%s).click()" % expr)
                await asyncio.sleep(0.3)

            async def type_into(expr, text):
                await js("(%s).focus()" % expr)
                await cmd("Input.insertText", text=text)
                await asyncio.sleep(0.2)

            val = lambda expr: js("(%s).value" % expr)
            TITLE, FOLDER = "document.querySelectorAll('main input')[0]", "document.querySelectorAll('main input')[1]"
            PLACE = "document.querySelector('main .field')"
            HOW = "document.querySelectorAll('main .opt')[%d]"
            GO = "document.querySelector('main .btn.wide')"
            SHEET = "document.querySelector('.card.pick')"

            await cmd("Page.enable")
            await cmd("Runtime.enable")
            await cmd("Emulation.setDeviceMetricsOverride", width=412, height=915, deviceScaleFactor=2, mobile=True)
            await cmd("Page.navigate", url=URL)
            ok = await until("location.hash === '#/newproject' && !!document.querySelector('main h2') && "
                             "/~/.test(document.querySelector('main .field') ? document.querySelector('main .field').textContent : '')")
            verdict("the screen opens from the start parameter, the place is ~/Documents", ok and "~/Documents" in await js(PLACE + ".textContent"))
            # the app asks through Telegram's own boxes when it runs in Telegram, else the browser's — catch both
            await js("window.__alerts = []; window.alert = (s) => window.__alerts.push(String(s)); window.confirm = () => true; "
                     "const w = window.Telegram && window.Telegram.WebApp; if (w) { w.showAlert = (s) => window.__alerts.push(String(s)); "
                     "w.showConfirm = (s, cb) => cb(true); }")
            verdict("Create is off with nothing typed", await js(GO + ".disabled"))
            await type_into(TITLE, "Дача у моря")
            verdict("the folder follows the title", await until("(%s).value === 'dacha_u_morya'" % FOLDER), await val(FOLDER))
            await shot("1-typed.png")
            # the place: up, into Code, chosen — outside the tabs' folders, the screen says so
            await tap(PLACE)
            verdict("the picker opens in ~/Documents with its folders", await until(
                "(() => { const c = %s; return c && /~\\/Documents/.test(c.textContent) && /acme-shop/.test(c.textContent) && /support-desk/.test(c.textContent); })()" % SHEET))
            await shot("2-picker.png")
            await tap("document.querySelector('.card.pick .opt.up')")
            verdict("up leads home", await until("(() => { const h = document.querySelector('.card.pick .path'); return h && h.textContent === '~'; })()"))
            await tap("[...document.querySelectorAll('.card.pick .opt')].find((b) => /Code/.test(b.textContent))")
            verdict("into Code", await until("document.querySelector('.card.pick .path').textContent === '~/Code'"))
            await tap("document.querySelector('.card.pick .btn')")
            verdict("chosen: the field shows ~/Code, the tabs note shows",
                    await until("!document.querySelector('.card.pick') && /~\\/Code/.test(document.querySelector('main .field').textContent) && !!document.querySelector('.np-hint')"))
            await tap(HOW % 1)
            verdict("with a description: its field instead of the task", await until(
                "document.querySelectorAll('main textarea').length === 1 && document.querySelectorAll('main .opt.on').length === 1 && "
                "document.querySelectorAll('main .opt')[1].classList.contains('on')"))
            verdict("Create waits for the description", await js(GO + ".disabled"))
            await type_into("document.querySelector('main textarea')", "Учёт дел по даче: посадки, полив, покупки.")
            await shot("3-ready.png")
            await tap(GO)
            verdict("created: the app goes to the first turn's session", await until("location.hash.startsWith('#/s/')", 50),
                    await js("location.hash"), await js("window.__alerts"))
            # the same name in the same place: a clear refusal, nothing made
            await js("location.hash = '#/newproject'")
            await until("!!document.querySelector('main h2') && /~\\/Code/.test(document.querySelector('main .field').textContent)")
            verdict("the place is remembered", "~/Code" in await js(PLACE + ".textContent"))
            await js("window.__alerts = []")
            await type_into(TITLE, "Дача у моря")
            await until("(%s).value === 'dacha_u_morya'" % FOLDER)
            await tap(GO)
            await until("window.__alerts.length > 0", 50)
            await shot("5-taken.png")
            alerts = await js("window.__alerts")
            verdict("a taken name is refused", bool(alerts) and "dacha_u_morya" in alerts[0] and location_new(await js("location.hash")), alerts)
            # a clone link names the folder when there is no title (nothing is cloned here)
            await js("location.hash = '#/projects'")
            await until("!!document.querySelector('main .stick .btn')")
            verdict("Projects has a way in", True)
            await tap("document.querySelector('main .stick .btn')")
            await until("location.hash === '#/newproject' && !!document.querySelector('main h2')")
            await tap(HOW % 2)
            await until("document.querySelectorAll('main input').length === 3")
            await type_into("document.querySelectorAll('main input')[2]", "git@github.com:example/Shop-API.git")
            verdict("an untitled clone takes the repository's name", await until("(%s).value === 'Shop-API'" % FOLDER), await val(FOLDER))
            verdict("Create is on for a clone without a title", not await js(GO + ".disabled"))
            await shot("4-clone.png")
            # "+": the project picker starts with "New project"
            await js("location.hash = '#/new'")
            await until("!!document.querySelector('main .field')")
            await tap("document.querySelector('main .field')")
            verdict("+ has New project first", await until("(() => { const b = document.querySelector('.card.pick .opt'); return b && b.classList.contains('add'); })()"))
            await tap("document.querySelector('.card.pick .opt.add')")
            verdict("and it leads to the screen", await until("location.hash === '#/newproject'"))
            verdict("no script errors", not errors, errors)
    finally:
        p.kill()
    print("screenshots:", OUT)
    sys.exit(1 if failures else 0)


def location_new(h):
    return h == "#/newproject"


asyncio.run(main())
