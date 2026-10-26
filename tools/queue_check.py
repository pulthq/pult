"""A turn in the queue, in headless Chrome over DevTools, on the stand started with STAND_QUEUE=1 (all places taken, a
message of a third session waits): Home counts it apart in "Running now", its row has the amber "in the queue" chip;
the session shows the chip at the top, the card with why and "Start now", and Stop; "Start now" sends the message to
Claude over the limit and the card goes.
  STAND_QUEUE=1 HOLD=300 ~/.local/share/pult/venv/bin/python tools/stand.py > /tmp/stand.out &
  ~/.local/share/pult/venv/bin/python tools/queue_check.py /tmp/stand.out [out_dir]
Screenshots go to out_dir (a temporary folder by default). Exit 1 on a failed check. Selectors are by class, not by
text, except the stand's own words: the stand runs in either language."""
import asyncio, base64, json, os, subprocess, sys, tempfile, time
import aiohttp

STAND = sys.argv[1]
URLS = dict(line.split(" ", 1) for line in open(STAND).read().split("\n") if line.startswith("HOME "))
OUT = sys.argv[2] if len(sys.argv) > 2 else tempfile.mkdtemp(prefix="pult-queue-")
os.makedirs(OUT, exist_ok=True)
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
PORT = 9339
SID6 = "66666666-4444-4444-8444-444444444444"
failures = []


def verdict(name, ok, *info):
    print(("ok   " if ok else "FAIL ") + name, *info)
    if not ok:
        failures.append(name)


async def main():
    prof = tempfile.mkdtemp(prefix="cdp-")
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

            await cmd("Runtime.enable")
            await cmd("Emulation.setDeviceMetricsOverride", width=412, height=860, deviceScaleFactor=2, mobile=True)
            await cmd("Page.enable")
            await cmd("Page.navigate", url=URLS["HOME"])
            await until("document.querySelectorAll('h3').length > 1", 150)
            await asyncio.sleep(0.5)

            # Home: the queued session in "Running now", counted apart, with its amber chip
            h3 = await js("document.querySelector('h3').textContent")
            verdict("Running now counts the queue apart", " · " in h3 and h3.count("·") == 2, h3)
            row = await js("""(() => { const r = [...document.querySelectorAll('.list')[0].querySelectorAll('.run')]
              .find(b => b.querySelector('.chip.warn')); return r && { chip: r.querySelector('.chip.warn').textContent,
              last: r === [...r.parentNode.querySelectorAll('.run')].pop(), clock: !!r.querySelector('.st-ic svg'),
              ask: (r.querySelector('.run-ask') || {}).textContent || '', title: r.querySelector('.run-t').textContent.trim() }; })()""")
            verdict("its row has the amber chip with the time", row and any(c.isdigit() for c in row["chip"]), row)
            verdict("…below the ones working", row and row["last"])
            # the stand's queued message starts its session: the title says it already, no "You: …" repeats it
            verdict("…its message once: the title says it", row and row["title"] and not row["ask"], row)
            await shot("1-home.png")

            # the session: the chip at the top, the card with why and Start now, and Stop
            await js("location.hash = '#/s/%s'" % SID6)
            ok = await until("!!document.querySelector('.card.queue')", 150)
            verdict("the session shows the queue card", ok)
            verdict("…the chip at the top", await js("!!document.querySelector('.sess-h .chip.warn')"))
            verdict("…and Stop", await js("!!document.querySelector('.composer .btn.danger')"))
            await shot("2-session.png")
            before = open(STAND).read().count("\nQUERY ")
            await js("document.querySelector('.card.queue .btn').click()")
            ok = await until("!document.querySelector('.card.queue')", 100)
            verdict("Start now: the card goes", ok)
            for _ in range(30):
                if open(STAND).read().count("\nQUERY ") > before:
                    break
                await asyncio.sleep(0.1)
            verdict("…and the message goes to Claude", open(STAND).read().count("\nQUERY ") > before)
            await asyncio.sleep(0.3)
            await shot("3-started.png")
            verdict("no errors on the page", not errors, errors[:3])
    finally:
        p.kill()
    print("screenshots:", OUT)
    sys.exit(1 if failures else 0)


asyncio.run(main())
