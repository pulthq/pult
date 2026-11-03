"""A picture pasted (⌘V / Ctrl+V) or dragged onto a message field comes in as if picked (Q127, 2026-11-03), in headless
Chrome over DevTools, on the stand, with the events a real paste and a real drop give a page: New task's "What to do",
New project's first task and a session's message field. A screenshot on the clipboard — a thumbnail under the field,
the words typed stay; words beside a picture (Word, Excel, Numbers put both) — the words go in, no thumbnail; words
alone — nothing new; a file dropped from the computer — a thumbnail; three at most, the fourth says so. Each paste with
more than words is told to the computer's log (api "paste").
  STAND_HOMES=1 STAND_LANG=ru HOLD=300 ~/.local/share/pult/venv/bin/python tools/stand.py > /tmp/stand.out &
  ~/.local/share/pult/venv/bin/python tools/paste_check.py /tmp/stand.out [out_dir]
Screenshots go to out_dir (a temporary folder by default). Exit 1 on a failed check."""
import asyncio
import os
import sys
import tempfile

import _cdp

URLS = _cdp.stand_urls(sys.argv[1], ("NEW", "NEWPROJ", "SESS"))
OUT = sys.argv[2] if len(sys.argv) > 2 else tempfile.mkdtemp(prefix="pult-paste-")
os.makedirs(OUT, exist_ok=True)
verdict = _cdp.Verdicts()
# a screenshot made on the page (no file on disk): a window with lines of text; and the app's requests to the
# computer, kept as they leave over the relay's socket
PREP = """(() => { window.__calls = []; const send = WebSocket.prototype.send;
  WebSocket.prototype.send = function (d) { try { const m = JSON.parse(d); if (m.t === "req") window.__calls.push(m); }
    catch (e) {} return send.call(this, d); };
  window.__shot = () => new Promise((ok) => { const c = document.createElement("canvas"); c.width = 1200; c.height = 760;
    const g = c.getContext("2d"); g.fillStyle = "#1e1f24"; g.fillRect(0, 0, 1200, 760); g.fillStyle = "#e6e6e6";
    g.font = "26px monospace"; for (let i = 0; i < 18; i++) g.fillText("line " + i + ": error during build", 30, 60 + i * 38);
    c.toBlob((b) => ok(new File([b], "image.png", { type: "image/png" })), "image/png"); });
  window.__paste = async (sel, words) => { const dt = new DataTransfer(); if (words !== "only") dt.items.add(await window.__shot());
    if (words) dt.setData("text/plain", words === "only" ? "просто слова" : words);
    const ev = new ClipboardEvent("paste", { clipboardData: dt, bubbles: true, cancelable: true });
    document.querySelector(sel).dispatchEvent(ev); return ev.defaultPrevented; };
  window.__drop = async (sel) => { const dt = new DataTransfer(); dt.items.add(await window.__shot());
    const ev = new DragEvent("drop", { dataTransfer: dt, bubbles: true, cancelable: true });
    document.querySelector(sel).dispatchEvent(ev); return ev.defaultPrevented; };
  return true; })()"""
THUMBS = "document.querySelectorAll('.thumb img').length"
TOAST = "(document.querySelector('.toast') || {}).textContent"


async def main():
    async with _cdp.Page() as pg:
        await pg.open(URLS["NEW"])
        verdict("New task is up", await pg.until("!!document.querySelector('.form textarea')", 150))
        await pg.js(PREP)
        await pg.js("(() => { const ta = document.querySelector('.form textarea'); const set = Object.getOwnPropertyDescriptor("
                    "HTMLTextAreaElement.prototype, 'value').set; set.call(ta, 'Почини сборку'); "
                    "ta.dispatchEvent(new Event('input', {bubbles: true})); })()")
        took = await pg.js("window.__paste('.form textarea')")
        verdict("⌘V with a screenshot: taken, a thumbnail under the field", took and await pg.until(THUMBS + " === 1", 50),
                took, await pg.js(THUMBS))
        verdict("... the words typed stay", await pg.js("document.querySelector('.form textarea').value") == "Почини сборку")
        call = await pg.js("window.__calls.find((c) => c.op === 'paste')")
        verdict("... and the paste is told to the computer's log", bool(call) and call.get("args", {}).get("n") == 1, call)
        await pg.shot(os.path.join(OUT, "new.png"))
        took = await pg.js("window.__paste('.form textarea', 'A1\\tB1')")
        await asyncio.sleep(0.4)
        verdict("words beside a picture (a spreadsheet): the words go in, no thumbnail", not took and await pg.js(THUMBS) == 1,
                took, await pg.js(THUMBS))
        n = await pg.js("window.__calls.length")
        took = await pg.js("window.__paste('.form textarea', 'only')")
        await asyncio.sleep(0.3)
        verdict("words alone: nothing new, nothing told", not took and await pg.js(THUMBS) == 1
                and await pg.js("window.__calls.length") == n, took)
        took = await pg.js("window.__drop('.form textarea')")
        verdict("a file dropped on the field: a thumbnail", took and await pg.until(THUMBS + " === 2", 50), await pg.js(THUMBS))
        await pg.js("window.__paste('.form textarea')")
        await pg.until(THUMBS + " === 3", 50)
        await pg.js("window.__paste('.form textarea')")
        verdict("three at most: the fourth says so", await pg.until(TOAST + " && " + TOAST + ".includes('Не больше 3')", 30)
                and await pg.js(THUMBS) == 3, await pg.js(TOAST), await pg.js(THUMBS))
        verdict("New task: no script errors", not pg.errors, pg.errors[:3])
    async with _cdp.Page() as pg:
        await pg.open(URLS["NEWPROJ"])
        verdict("New project is up", await pg.until("!!document.querySelector('.form textarea')", 150))
        await pg.js(PREP)
        ta = "[...document.querySelectorAll('.form textarea')].pop()"
        await pg.js("(() => { %s.classList.add('__task'); })()" % ta)
        took = await pg.js("window.__paste('.form textarea.__task')")
        verdict("New project's first task takes a pasted screenshot", took and await pg.until(THUMBS + " === 1", 50),
                await pg.js(THUMBS))
        verdict("New project: no script errors", not pg.errors, pg.errors[:3])
    async with _cdp.Page() as pg:
        await pg.open(URLS["SESS"])
        verdict("the session is up", await pg.until("!!document.querySelector('.composer textarea')", 150))
        await pg.js(PREP)
        took = await pg.js("window.__paste('.composer textarea')")
        verdict("a session's field takes a pasted screenshot, above the field", took
                and await pg.until("document.querySelectorAll('.composer .thumb img').length === 1", 50))
        verdict("... and Send is on with it alone", await pg.js("!document.querySelector('.composer .btn.send').disabled"))
        await pg.shot(os.path.join(OUT, "session.png"))
        verdict("session: no script errors", not pg.errors, pg.errors[:3])
    print("screenshots:", OUT)
    sys.exit(verdict.code())


asyncio.run(main())
