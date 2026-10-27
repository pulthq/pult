"""Files in the app (stage F) in headless Chrome over DevTools, on the stand: the outcome's line to the turn's files;
their screen — nothing ticked, a deleted file can't be, one goes alone, all of them only as one archive, ‹ to the
turn before; a document in the message field is a chip with its name, a picture stays a thumbnail; a document over
the app's limit is refused.
  STAND_LANG=ru HOLD=300 ~/.local/share/pult/venv/bin/python tools/stand.py > /tmp/stand.out &
  ~/.local/share/pult/venv/bin/python tools/files_check.py "$(grep '^SESS4 ' /tmp/stand.out | cut -d' ' -f2)" [out_dir]
Screenshots go to out_dir (a temporary folder by default). Exit 1 on a failed check. Selectors are by class and order,
not by text: the stand runs in either language."""
import asyncio, base64, json, os, subprocess, sys, tempfile, zlib, struct
import aiohttp

URL = sys.argv[1]
OUT = sys.argv[2] if len(sys.argv) > 2 else tempfile.mkdtemp(prefix="pult-files-")
os.makedirs(OUT, exist_ok=True)
import _cdp  # noqa: E402  (tools/_cdp.py: where Chrome is, free ports, a profile that goes — review 2026-10-27, Т9)
CHROME = _cdp.CHROME
PORT = _cdp.free_port()
failures = []


def verdict(name, ok, *info):
    print(("ok   " if ok else "FAIL ") + name, *info)
    if not ok:
        failures.append(name)


def png(path):
    rows = b"".join(b"\x00" + bytes((200, 60, 60)) * 40 for _ in range(30))
    chunk = lambda t, d: struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xffffffff)
    with open(path, "wb") as f:
        f.write(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 40, 30, 8, 2, 0, 0, 0))
                + chunk(b"IDAT", zlib.compress(rows)) + chunk(b"IEND", b""))


async def main():
    doc, pic, big = os.path.join(OUT, "смета.pdf"), os.path.join(OUT, "pic.png"), os.path.join(OUT, "huge.pdf")
    open(doc, "wb").write(b"%PDF-1.7 made up")
    png(pic)
    with open(big, "wb") as f:
        f.truncate(6 * 1024 * 1024)
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

            async def attach(path):
                doc_ = await cmd("DOM.getDocument", depth=-1, pierce=True)
                node = await cmd("DOM.querySelector", nodeId=doc_["root"]["nodeId"], selector="input[type=file]")
                await cmd("DOM.setFileInputFiles", files=[path], nodeId=node["nodeId"])
                await asyncio.sleep(0.6)

            alerts = ("window.__alerts = []; window.alert = (s) => window.__alerts.push(String(s)); "
                      "const w = window.Telegram && window.Telegram.WebApp; if (w) w.showAlert = (s) => window.__alerts.push(String(s));")
            await cmd("Page.enable")
            await cmd("Runtime.enable")
            await cmd("Emulation.setDeviceMetricsOverride", width=412, height=915, deviceScaleFactor=2, mobile=True)
            await cmd("Page.navigate", url=URL)
            ok = await until("!!document.querySelector('.tfline')", 150)
            line = await js("(document.querySelector('.tfline') || {}).textContent")
            verdict("the outcome has one line to the turn's files", ok and "112" in (line or ""), line)
            await js(alerts)
            await js("window.scrollTo(0, document.documentElement.scrollHeight)")
            await shot("1-line.png")
            await js("document.querySelector('.tfline').click()")
            verdict("its screen lists the twelve files under All", await until("document.querySelectorAll('.tf-row').length === 13", 100),
                    await js("document.querySelectorAll('.tf-row').length"))
            verdict("the list says it was cut", await js("/112/.test(document.querySelector('.tfs > .small').textContent)"))
            btn = "document.querySelector('.tf-go .btn')"
            verdict("nothing ticked, the button is off", await js("[...document.querySelectorAll('.tf-row input')].every((i) => !i.checked) && %s.disabled" % btn))
            verdict("the deleted file can't be ticked", await js("document.querySelector('.tf-row.gone input').disabled"))
            await shot("2-screen.png")
            await js("document.querySelectorAll('.tf-row')[1].click()")
            verdict("one ticked: the button counts it, the archive is a choice", await until("!%s.disabled && /\\(1\\)/.test(%s.textContent) && !document.querySelector('.tf-zip input').disabled" % (btn, btn)))
            await js("%s.click()" % btn)
            verdict("it goes alone and is marked sent", await until("document.querySelectorAll('.tf-ok').length === 1 && !document.querySelector('.tf-zip input').checked"))
            await js("document.querySelector('.tf-all').click()")
            verdict("All ticks the eleven that are there; over ten — only as an archive",
                    await until("/\\(11\\)/.test(%s.textContent) && document.querySelector('.tf-zip input').checked && document.querySelector('.tf-zip input').disabled" % btn))
            await shot("3-all.png")
            await js("%s.click()" % btn)
            verdict("they go as one archive", await until("/\\.zip/.test((document.querySelector('.tf-note') || {}).textContent || '') && document.querySelectorAll('.tf-ok').length === 11"))
            await shot("4-zip.png")
            await js("document.querySelector('.tf-nav .nv').click()")
            verdict("‹ shows the turn before: two files, ticks gone, nothing earlier",
                    await until("document.querySelectorAll('.tf-row').length === 3 && !document.querySelectorAll('.tf-ok').length && document.querySelector('.tf-nav .nv').disabled"))
            verdict("› leads back", await js("!document.querySelectorAll('.tf-nav .nv')[1].disabled"))
            await shot("5-before.png")
            await js("history.back()")
            await until("!!document.querySelector('.tfline')", 100)
            # the message field: a document is a chip with its name, a picture a thumbnail, a too big document refused
            await attach(doc)
            verdict("a document is a chip with its name", await until("(() => { const c = document.querySelector('.thumb.doc .doc-n'); return c && /смета\\.pdf/.test(c.textContent); })()"))
            await attach(pic)
            verdict("a picture stays a thumbnail", await until("!!document.querySelector('.thumb:not(.doc) img')"))
            await attach(big)
            verdict("a document over 5 MB is refused", await until("window.__alerts.length === 1 && /huge\\.pdf/.test(window.__alerts[0])"), await js("window.__alerts"))
            verdict("two attachments stay", await js("document.querySelectorAll('.thumb').length") == 2)
            await shot("3-attached.png")
            await js("document.querySelector('.thumb.doc .thumb-x').click()")
            verdict("the document is removed", await until("!document.querySelector('.thumb.doc')"))
            verdict("no script errors", not errors, errors)
    finally:
        p.kill()
    print("screenshots:", OUT)
    sys.exit(1 if failures else 0)


asyncio.run(main())
