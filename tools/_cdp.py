"""What the checks in Chrome share (review 2026-10-27, Т9).

Where Chrome is; a free port for its DevTools — two checks at once (2–3 sessions often work in this folder) took the
same fixed one, and the second talked to the first one's Chrome; a profile that goes when the check ends (1 300 of
them were left in the temporary folder, 6.5 GB); a free port for a stand a check raises itself. And the small harness
a new check uses: Chrome with one page, `cmd`/`js`/`until`/`tap`, verdicts.

  CHROME=<path>   another Chrome (on Linux google-chrome or chromium is found on PATH)
  CDP_PORT=<n>    DevTools on a port of your choosing
"""
import asyncio
import atexit
import os
import shutil
import socket
import subprocess
import tempfile
import time

MAC_CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"


def find_chrome():
    if os.environ.get("CHROME"):
        return os.environ["CHROME"]
    if os.path.exists(MAC_CHROME):
        return MAC_CHROME
    for name in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser"):
        found = shutil.which(name)
        if found:
            return found
    return MAC_CHROME                 # where it was looked for: the error to start it names it


CHROME = find_chrome()


def any_port():
    """A port nobody listens on now — for a stand a check raises itself."""
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def free_port():
    """DevTools' port: CDP_PORT when set, else a free one."""
    return int(os.environ["CDP_PORT"]) if os.environ.get("CDP_PORT") else any_port()


def _gone(path):
    for _ in range(10):               # Chrome may still be writing a moment after it was killed
        shutil.rmtree(path, ignore_errors=True)
        if not os.path.exists(path):
            return
        time.sleep(0.2)


def profile():
    """A Chrome profile folder of its own, removed when the check ends."""
    d = tempfile.mkdtemp(prefix="cdp-")
    atexit.register(_gone, d)
    return d


def stop(proc, wait=10):
    """A stand stopped its own way — SIGTERM: it removes its temporary folder and leaves at once (tools/stand.py);
    killed only when it doesn't. A plain kill left the folder behind."""
    proc.terminate()
    try:
        proc.wait(wait)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(5)


class Verdicts:
    """ok / FAIL lines, and the exit code: 1 when any check failed."""

    def __init__(self):
        self.failures = []

    def __call__(self, name, ok, *info):
        print(("ok   " if ok else "FAIL ") + name, *([] if ok else info), flush=True)
        if not ok:
            self.failures.append(name)
        return ok

    def code(self):
        return 1 if self.failures else 0


class Page:
    """Headless Chrome with one page, over DevTools: `async with Page() as pg: await pg.open(url)`. Script errors on
    the page are kept in `errors`."""

    def __init__(self, width=412, height=860, scale=2, touch=True):
        self.size, self.touch = (width, height, scale), touch
        self.port, self.errors, self.n = free_port(), [], 0

    async def __aenter__(self):
        import aiohttp
        self.proc = subprocess.Popen([CHROME, "--headless=new", "--disable-gpu", "--hide-scrollbars", "--no-first-run",
                                      "--remote-debugging-port=%d" % self.port, "--user-data-dir=" + profile(),
                                      "about:blank"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.http = aiohttp.ClientSession()
        tabs = []
        for _ in range(100):
            try:
                async with self.http.get("http://127.0.0.1:%d/json/list" % self.port) as r:
                    tabs = [t for t in await r.json() if t.get("type") == "page"]
                if tabs:
                    break
            except aiohttp.ClientError:
                pass
            await asyncio.sleep(0.1)
        if not tabs:
            await self.__aexit__()
            raise RuntimeError("Chrome didn't come up: %s" % CHROME)
        self.ws = await self.http.ws_connect(tabs[0]["webSocketDebuggerUrl"], max_msg_size=64 << 20)
        await self.cmd("Page.enable")
        await self.cmd("Runtime.enable")
        w, h, k = self.size
        await self.cmd("Emulation.setDeviceMetricsOverride", width=w, height=h, deviceScaleFactor=k, mobile=self.touch)
        if self.touch:
            await self.cmd("Emulation.setTouchEmulationEnabled", enabled=True, maxTouchPoints=5)
        return self

    async def __aexit__(self, *exc):
        try:
            if getattr(self, "ws", None) is not None:
                await self.ws.close()
            await self.http.close()
        finally:
            self.proc.kill()
            self.proc.wait(10)

    async def cmd(self, method, **params):
        self.n += 1
        me = self.n
        await self.ws.send_json({"id": me, "method": method, "params": params})
        while True:
            m = await self.ws.receive_json()
            if m.get("method") == "Runtime.exceptionThrown":
                self.errors.append(m["params"]["exceptionDetails"].get("exception", {}).get("description"))
            if m.get("id") == me:
                return m.get("result", {})

    async def js(self, expr):
        r = await self.cmd("Runtime.evaluate", expression=expr, returnByValue=True, awaitPromise=True)
        return r.get("result", {}).get("value")

    async def until(self, expr, tries=60, every=0.1):
        for _ in range(tries):
            if await self.js(expr):
                return True
            await asyncio.sleep(every)
        return False

    async def open(self, url):
        await self.cmd("Page.navigate", url=url)

    async def tap(self, expr, wait=0.4):
        """A finger on the element's middle — not el.click(): what is on top there gets it."""
        r = await self.js("(() => { const el = %s; if (!el) return null; el.scrollIntoView({block: 'center'});"
                          " const b = el.getBoundingClientRect(); return [b.left + b.width / 2, b.top + b.height / 2]; })()" % expr)
        if not r:
            raise RuntimeError("nothing to tap: " + expr)
        await self.cmd("Input.dispatchTouchEvent", type="touchStart", touchPoints=[{"x": r[0], "y": r[1]}])
        await self.cmd("Input.dispatchTouchEvent", type="touchEnd", touchPoints=[])
        await asyncio.sleep(wait)

    async def shot(self, path):
        import base64
        d = await self.cmd("Page.captureScreenshot", format="png")
        with open(path, "wb") as f:
            f.write(base64.b64decode(d["data"]))


def stand_urls(path, names=None):
    """The stand's printed lines ("HOME http://…") → {name: url}."""
    with open(path, encoding="utf-8") as f:
        rows = [ln.split(" ", 1) for ln in f.read().split("\n") if " http" in ln]
    return {k: v for k, v in rows if names is None or k in names}
