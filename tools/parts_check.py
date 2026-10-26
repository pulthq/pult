"""Every part of Pult in one table (stage U2), in headless Chrome over DevTools, on the stand, with real taps. A stand
for each set of made-up facts (STAND_PARTS): all as in main with a new Claude Code downloaded — "worth a look", no
line on Home; several parts behind — the computer's row open with Install, the app's row with what's new and who
deploys it, the tabs and the hooks, Home's line; things that don't work — Home's line in red, "not from main",
"unknown"; someone with a clone of the public repository — no release row, no tabs row, no words for the owner alone,
how to have the server update itself; that clone with the server's updater (stage U3) — the server took the release,
is taking it (Home's line), didn't take it (why, what runs); the switch for GitHub. Then this phone's copy: the server
starts handing out a newer app (a file's time moves), the row says so, Home's line too, and "Refresh the app" reloads
the page into the current copy — while something is typed; with nothing typed the copy reloads by itself (stage U3).
English once, for keys left as keys.
  ~/.local/share/pult/venv/bin/python tools/parts_check.py [out_dir]
The facts are made up (the stand never shows this computer's Claude Code or hooks); the daemon's real ones are checked
by tests/test_pult.py and by eye on the Mac. Screenshots go to out_dir (a temporary folder by default). Exit 1 on a
failed check."""
import asyncio, base64, json, os, subprocess, sys, tempfile, time
from pathlib import Path
import aiohttp

REPO = Path(__file__).resolve().parent.parent
PY = sys.executable
OUT = sys.argv[1] if len(sys.argv) > 1 else tempfile.mkdtemp(prefix="pult-parts-")
os.makedirs(OUT, exist_ok=True)
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
PORT, STAND_PORT = int(os.environ.get("CDP_PORT") or 9341), os.environ.get("STAND_PORT") or "18117"
TOUCH = REPO / "relay" / "web" / "static" / "md.js"     # its time moves: the server's page names a newer copy
failures = []


def verdict(name, ok, *info):
    print(("ok   " if ok else "FAIL ") + name, *info)
    if not ok:
        failures.append(name)


def stand(parts, lang="ru", upd=None):
    """A stand on these facts → (process, {name: url})."""
    out = Path(OUT) / ("stand-%s-%s.out" % (parts, lang))
    env = dict(os.environ, STAND_PARTS=parts, STAND_LANG=lang, STAND_PORT=STAND_PORT, HOLD="120")
    if upd:
        env["STAND_UPD"] = upd
    p = subprocess.Popen([PY, str(REPO / "tools" / "stand.py")], env=env, stdout=open(out, "w"), stderr=subprocess.DEVNULL)
    for _ in range(120):
        text = out.read_text() if out.exists() else ""
        if "\nHOME " in "\n" + text and "SETTINGS " in text:
            return p, dict(ln.split(" ", 1) for ln in text.splitlines() if ln[:5] in ("HOME ", "SETTI"))
        time.sleep(0.25)
    p.kill()
    raise RuntimeError("the stand didn't come up (%s)" % parts)


async def main():
    prof = tempfile.mkdtemp(prefix="cdp-")
    chrome = subprocess.Popen([CHROME, "--headless=new", "--disable-gpu", "--hide-scrollbars", "--remote-debugging-port=%d" % PORT,
                               "--user-data-dir=" + prof, "--no-first-run", "about:blank"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    mtime = TOUCH.stat().st_mtime
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

            async def until(expr, tries=80):
                for _ in range(tries):
                    if await js(expr):
                        return True
                    await asyncio.sleep(0.1)
                return False

            async def open_(url):
                await cmd("Page.navigate", url=url)
                await asyncio.sleep(0.3)

            async def shot(name):
                data = (await cmd("Page.captureScreenshot", format="png", captureBeyondViewport=True))["data"]
                Path(OUT, name + ".png").write_bytes(base64.b64decode(data))

            async def tap_at(expr):
                box = await js("""(() => { const b = %s; if (!b) return null; b.scrollIntoView({block: 'center'});
                    const r = b.getBoundingClientRect(); return [r.x + r.width / 2, r.y + r.height / 2]; })()""" % expr)
                if not box:
                    return False
                for kind in ("mousePressed", "mouseReleased"):
                    await cmd("Input.dispatchMouseEvent", type=kind, x=box[0], y=box[1], button="left", clickCount=1)
                return True

            row = lambda k: "document.querySelector('.part[data-k=%s]')" % k
            chip = lambda k: js(row(k) + "?.querySelector('.pchip')?.textContent")
            more = lambda k: js(row(k) + "?.querySelector('.part-x')?.textContent || ''")

            async def tap_row(k):
                ok = await tap_at(row(k) + "?.querySelector('.part-r')")
                return ok and await until(row(k) + "?.classList.contains('open')")

            async def settings(urls):
                await open_("about:blank")
                await open_(urls["SETTINGS"])
                return await until("document.querySelectorAll('.part').length >= 5")

            async def home(urls):
                await open_("about:blank")
                await open_(urls["HOME"])
                await until("document.querySelector('.where')")
                await asyncio.sleep(0.8)
                line = await js("document.querySelector('.upd-row')?.textContent || null")
                return line, await js("document.querySelector('.upd-row')?.className || ''")

            await cmd("Runtime.enable")
            await cmd("Page.enable")
            await cmd("Emulation.setDeviceMetricsOverride", width=412, height=900, deviceScaleFactor=2, mobile=True)
            head = "document.querySelector('.parts .upd-h')?.textContent"

            # 1. all as in main; a new Claude Code is downloaded but not in use yet
            proc, urls = stand("now")
            try:
                line, _ = await home(urls)
                verdict("now: no line on Home", line is None, line)
                verdict("now: the table", await settings(urls))
                verdict("now: all as in main, one worth a look", "Всё как в main" in (await js(head) or "")
                        and "на заметку: 1" in (await js(head) or ""), await js(head))
                verdict("now: eight rows, the phone among them", await js("document.querySelectorAll('.part').length") == 8
                        and await chip("phone") == "свежая", await chip("phone"))
                verdict("now: Claude Code — to check", await chip("cc") == "проверить", await chip("cc"))
                verdict("now: a tap opens it — what's downloaded and how to allow it", await tap_row("cc")
                        and "2.1.310" in await more("cc") and "pult tab allow 2.1.310" in await more("cc"), (await more("cc"))[:120])
                verdict("now: GitHub — one waits for a release", await chip("gh") == "к выпуску: 1", await chip("gh"))
                await shot("now")
            finally:
                proc.kill()
                proc.wait()

            # 2. several parts behind
            proc, urls = stand("lag", upd="ready")
            try:
                line, cls = await home(urls)
                verdict("lag: Home — update the computer, a hook missing", (line or "").startswith("Обновить: компьютер")
                        and "StopFailure" in line and "bad" in cls, line, cls)
                await shot("lag-home")
                verdict("lag: the table", await settings(urls))
                verdict("lag: four of eight to update", "Обновить: 4 из 8" in (await js(head) or ""), await js(head))
                verdict("lag: the computer's row stands open, with Install",
                        await js(row("mac") + "?.classList.contains('open')") and "Поставить 0." in await more("mac")
                        and "2\u00a0коммита, с" in await more("mac"), (await more("mac"))[:120])
                await shot("lag")
                verdict("lag: the app — three commits behind", await chip("web") == "−3 коммита", await chip("web"))
                text = await more("web") if await tap_row("web") else ""
                verdict("lag: what's new on the server and how to deploy it",
                        await js(row("web") + ".querySelectorAll('.upd-news li').length") == 3 and "выложить приложение заново" in text, text[:160])
                await shot("lag-web")
                verdict("lag: the relay as in main", await chip("relay") == "как в main", await chip("relay"))
                text = await more("tabs") if await tap_row("tabs") else ""
                verdict("lag: two tabs on an older wrapper, where", await chip("tabs") == "старых: 2" and "Reload Window" in text
                        and ("support-desk" in text or "blog" in text), await chip("tabs"), text[:120])
                text = await more("hooks") if await tap_row("hooks") else ""
                verdict("lag: a hook missing — which, and who", await chip("hooks") == "нет 1" and "StopFailure" in text
                        and "pult hooks on" in text, text[:120])
                await shot("lag-hooks")
            finally:
                proc.kill()
                proc.wait()

            # 3. what doesn't work
            proc, urls = stand("bad")
            try:
                line, cls = await home(urls)
                verdict("bad: Home — the hooks, and writing into tabs is off", (line or "").startswith("Нет хуков: StopFailure, PreCompact")
                        and "Запись во вкладки выключена" in line and "bad" in cls, line, cls)
                verdict("bad: the table", await settings(urls))
                verdict("bad: the app — not from main; the relay — unknown",
                        await chip("web") == "не из main" and await chip("relay") == "не знаю", await chip("web"), await chip("relay"))
                text = await more("web") if await tap_row("web") else ""
                verdict("bad: why not from main", "незакоммиченного" in text, text[:120])
                text = await more("cc") if await tap_row("cc") else ""
                verdict("bad: Claude Code not verified — writing is off", await chip("cc") == "не проверен" and "выключена" in text, text[:120])
                text = await more("tabs") if await tap_row("tabs") else ""
                verdict("bad: a tab that couldn't tell its wrapper", "Не смогли назвать обёртку: 1" in text
                        and "все на установленной" not in text, text[:120])
                await shot("bad")
            finally:
                proc.kill()
                proc.wait()

            # 4. someone with a clone of the public repository: no release of their own, no wrapper; the words are theirs too
            proc, urls = stand("public", upd="ready")
            try:
                verdict("public: the table", await settings(urls))
                rows = await js("[...document.querySelectorAll('.part')].map(r => r.dataset.k).join(' ')")
                verdict("public: no release row, no tabs row", rows == "mac web relay phone hooks cc", rows)
                verdict("public: Claude Code — no wrapper", await chip("cc") == "без обёртки", await chip("cc"))
                text = await more("web") if await tap_row("web") else ""
                verdict("public: how to bring their server up to date", "deploy/relay/install.sh" in text and "агент" not in text, text[:160])
                verdict("public: how to have it update itself", "install.sh --auto" in text, text[:160])
                await tap_row("cc")
                text = await js("document.querySelector('.parts').textContent")
                verdict("public: nothing written for the owner alone", not any(w in text for w in ("агент", "по твоему")), text[:120])
                await shot("public")
            finally:
                proc.kill()
                proc.wait()

            # 4a. that clone with the server's updater (stage U3): it took the computer's release; the install block says
            # the server follows; the switch for GitHub
            proc, urls = stand("auto", upd="ready")
            try:
                verdict("auto: the table", await settings(urls))
                verdict("auto: the install block — the server takes the same release", "сервер приложения сам возьмёт тот же выпуск"
                        in await more("mac"), (await more("mac"))[:200])
                verdict("auto: the app as in main", await chip("web") == "как в main", await chip("web"))
                text = await more("web") if await tap_row("web") else ""
                verdict("auto: it updates itself, took the release", "Обновляется сам вслед за компьютером" in text and "Взял v" in text, text[:200])
                sw = await js("[...document.querySelectorAll('.sw-row')].map(r => r.textContent).find(x => x.includes('GitHub')) || null")
                verdict("auto: the switch for GitHub, when it last looked", bool(sw) and "Каждые 5 минут" in sw and "последний раз" in sw, sw)
                await shot("auto")
            finally:
                proc.kill()
                proc.wait()
            proc, urls = stand("auto_run", upd="ok")
            try:
                line, _ = await home(urls)
                verdict("auto_run: Home — the server takes it", (line or "").startswith("Сервер приложения ставит v"), line)
                verdict("auto_run: the table", await settings(urls))
                verdict("auto_run: the app's chip", (await chip("web") or "").startswith("ставит v"), await chip("web"))
                text = await more("web") if await tap_row("web") else ""
                verdict("auto_run: the step", "качает с GitHub" in text, text[:200])
                await shot("auto-run")
            finally:
                proc.kill()
                proc.wait()
            proc, urls = stand("auto_fail", upd="ok")
            try:
                line, _ = await home(urls)
                verdict("auto_fail: no line on Home (the old one works)", line is None, line)
                verdict("auto_fail: the table", await settings(urls))
                verdict("auto_fail: the app's chip", (await chip("web") or "").startswith("не взял v"), await chip("web"))
                text = await more("web") if await tap_row("web") else ""
                verdict("auto_fail: why and what runs", "посредник не запустился" in text and "работает v0.16.2" in text
                        and "ModuleNotFoundError" in text, text[:200])
                await shot("auto-fail")
            finally:
                proc.kill()
                proc.wait()

            # 5. this phone's copy: the server starts handing out a newer one; "Refresh the app" brings it
            proc, urls = stand("fresh")
            try:
                verdict("phone: the table", await settings(urls))
                verdict("phone: the copy is current", await chip("phone") == "свежая", await chip("phone"))
                # something typed: the copy doesn't reload by itself (stage U3), the row and the button do it
                await js("document.body.insertAdjacentHTML('beforeend', '<input id=__draft value=draft>')")
                os.utime(TOUCH, (time.time(), time.time() + 120))
                await js("location.hash = '#/'")
                await asyncio.sleep(0.5)
                await js("location.hash = '#/settings'")                 # Settings asks the server again
                verdict("phone: a newer copy on the server", await until(row("phone") + "?.querySelector('.pchip')?.textContent === 'есть новее'"),
                        await chip("phone"))
                await js("location.hash = '#/'")
                verdict("phone: Home — update the phone", await until("(document.querySelector('.upd-row')?.textContent || '').includes('Обновить: телефон')"),
                        await js("document.querySelector('.upd-row')?.textContent || null"))
                await js("location.hash = '#/settings'")
                await until("document.querySelectorAll('.part').length >= 5")
                text = await more("phone") if await tap_row("phone") else ""
                verdict("phone: which copy, which the server has, the button", "Обновить приложение" in text, text[:120])
                await shot("phone")
                await js("window.__before_reload = 1")
                await tap_at(row("phone") + "?.querySelector('.part-x .btn')")
                verdict("phone: Refresh reloads the page", await until("window.__before_reload === undefined", 100))
                verdict("phone: the table again, the copy current", await until("document.querySelectorAll('.part').length >= 5", 150)
                        and await until(row("phone") + "?.querySelector('.pchip')?.textContent === 'свежая'"), await chip("phone"))
                # nothing typed: the server hands out a newer copy — this one reloads by itself, a few seconds later
                await js("window.__before_reload = 1")
                os.utime(TOUCH, (time.time(), time.time() + 240))
                await js("location.hash = '#/'")
                await asyncio.sleep(0.5)
                await js("location.hash = '#/settings'")
                verdict("phone: with nothing typed it reloads by itself", await until("window.__before_reload === undefined", 250))
                verdict("phone: and the copy is current", await until("document.querySelectorAll('.part').length >= 5", 150)
                        and await until(row("phone") + "?.querySelector('.pchip')?.textContent === 'свежая'"), await chip("phone"))
            finally:
                os.utime(TOUCH, (mtime, mtime))
                proc.kill()
                proc.wait()

            # 6. English: no key left as a key
            proc, urls = stand("lag", lang="en", upd="ready")
            try:
                verdict("en: the table", await settings(urls))
                for k in ("web", "tabs", "hooks", "cc", "gh"):
                    await tap_row(k)
                text = await js("document.querySelector('.parts').textContent")
                verdict("en: To update, no keys as text", "To update: 4 of 8" in text and "pt." not in text and "upd." not in text,
                        text[:160])
                await shot("en")
            finally:
                proc.kill()
                proc.wait()
            verdict("no script errors", not errors, errors[:3])
    finally:
        os.utime(TOUCH, (mtime, mtime))
        chrome.kill()
    print("screenshots:", OUT)
    sys.exit(1 if failures else 0)


asyncio.run(main())
