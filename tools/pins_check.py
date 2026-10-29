"""Pinned projects (stage Zh) in headless Chrome over DevTools, on the stand with STAND_TAGS=1 STAND_HOMES=1
STAND_PINS=blog,shop: Projects lists the pinned first, the newest pin on top, each with its mark; a finger sliding a
row to the left opens "Pin" under it, a short slide springs back, a tap on the open row closes it and opens nothing;
the pin from the row puts the project on top at once; the project's header has the same pin as a button; the new
task's list has the pinned first with the mark. The stand's output shows what the computer's journal says of each.
  STAND_TAGS=1 STAND_HOMES=1 STAND_PINS=blog,shop STAND_LANG=ru STAND_PORT=18149 HOLD=300 ~/.local/share/pult/venv/bin/python tools/stand.py > /tmp/stand.out &
  ~/.local/share/pult/venv/bin/python tools/pins_check.py /tmp/stand.out [out_dir]
Screenshots go to out_dir (a temporary folder by default). Exit 1 on a failed check."""
import asyncio
import json
import os
import sys
import tempfile

import _cdp

STAND = sys.argv[1]
OUT = sys.argv[2] if len(sys.argv) > 2 else tempfile.mkdtemp(prefix="pult-pins-")
os.makedirs(OUT, exist_ok=True)
U = _cdp.stand_urls(STAND)
verdict = _cdp.Verdicts()
ROWS = """JSON.stringify([...document.querySelectorAll('.swr')].map((r) => ({
  n: r.querySelector('.pn b').textContent, pin: !!r.querySelector('.ptail .ic-pin'),
  x: new DOMMatrixReadOnly(getComputedStyle(r.querySelector('.swr-in')).transform).m41 })))"""
ROW = "document.querySelectorAll('.swr')[%d]"


def journal():
    with open(STAND, encoding="utf-8", errors="replace") as f:
        return f.read()


async def slide(pg, i, dx, steps=8):
    """A finger on row i's middle, dx to the side in steps, lifted."""
    r = await pg.js("(() => { const b = %s.getBoundingClientRect(); return [b.left + b.width / 2, b.top + b.height / 2]; })()" % (ROW % i))
    x, y = r
    await pg.cmd("Input.dispatchTouchEvent", type="touchStart", touchPoints=[{"x": x, "y": y}])
    for k in range(1, steps + 1):
        await pg.cmd("Input.dispatchTouchEvent", type="touchMove", touchPoints=[{"x": x + dx * k / steps, "y": y}])
        await asyncio.sleep(0.02)
    await pg.cmd("Input.dispatchTouchEvent", type="touchEnd", touchPoints=[])
    await asyncio.sleep(0.5)


async def rows(pg):
    return json.loads(await pg.js(ROWS))


async def main():
    async with _cdp.Page() as pg:
        await pg.open(U["PROJECTS"])
        verdict("Projects lists four projects", await pg.until("document.querySelectorAll('.swr').length >= 4", 200))
        rs = await rows(pg)
        verdict("the pinned first, the newest pin on top, each with its mark; then the project that waits for you",
                [(r["n"], r["pin"]) for r in rs[:3]] == [("acme-shop", True), ("blog", True), ("Принтер", False)], rs)
        await pg.shot(os.path.join(OUT, "projects.png"))
        # a short slide springs back; a long one stays open on "Pin"
        await slide(pg, 2, -30)
        rs = await rows(pg)
        verdict("a short slide springs back", rs[2]["x"] == 0, rs[2])
        verdict("... and the journal says so", "swipe on a project's row sprang back" in journal())
        await slide(pg, 2, -120)
        rs = await rows(pg)
        act = await pg.js("(%s).querySelector('.swr-act').textContent" % (ROW % 2))
        verdict("a long slide stays open on the action", rs[2]["x"] == -92 and act == "Закрепить", rs[2], act)
        verdict("... and the journal says so", "swipe on a project's row opened on its action" in journal())
        await pg.shot(os.path.join(OUT, "swipe.png"))
        # a tap on the open row closes it and opens nothing
        await pg.tap("(%s).querySelector('.pn b')" % (ROW % 2))
        rs = await rows(pg)
        verdict("a tap on the open row closes it", rs[2]["x"] == 0, rs[2])
        verdict("... and opens nothing", await pg.js("location.hash") == "#/projects", await pg.js("location.hash"))
        # the pin from the row: on top at once, with the mark; the journal counts it as the swipe's
        await slide(pg, 2, -120)
        await pg.tap("(%s).querySelector('.swr-act')" % (ROW % 2))
        verdict("the pin from the row puts the project on top", await pg.until(
            "document.querySelector('.swr .pn b').textContent === 'Принтер' && !!document.querySelector('.swr .ptail .ic-pin')", 30), await rows(pg))
        verdict("... the journal counts it as the swipe's", "project pinned via the swipe" in journal())
        await pg.shot(os.path.join(OUT, "pinned.png"))
        # the project's header: the same pin as a button — acme-shop, pinned, is the second row now
        await pg.tap("(%s).querySelector('.pn b')" % (ROW % 1))
        verdict("the project's header has the pin, on", await pg.until("!!document.querySelector('.ph .pinb.on')", 100))
        await pg.tap("document.querySelector('.ph .pinb')")
        verdict("a tap unpins", await pg.until("document.querySelector('.ph .pinb') && !document.querySelector('.ph .pinb.on')", 30))
        verdict("... the journal counts it as the button's", "project unpinned via the button" in journal())
        await pg.tap("document.querySelector('.ph .pinb')")
        verdict("a tap pins again", await pg.until("!!document.querySelector('.ph .pinb.on')", 30))
        await pg.shot(os.path.join(OUT, "header.png"))
        # the new task's list: the pinned first, with the mark — acme-shop pinned just now is the newest
        await pg.js("location.hash = '#/new'")
        verdict("the new task's form", await pg.until("!!document.querySelector('.form .field')", 100))
        await pg.tap("document.querySelector('.form .field')")
        verdict("its list opens", await pg.until("document.querySelectorAll('.card.pick .opt').length > 3", 30))
        opts = json.loads(await pg.js("JSON.stringify([...document.querySelectorAll('.card.pick .opt')].filter((o) => !o.classList.contains('add')).map((o) => [o.firstChild.textContent, !!o.querySelector('.opt-pin')]))"))
        verdict("the pinned first in the list, the newest on top, with the mark", opts[:3] == [["acme-shop", True], ["Принтер", True], ["blog", True]] and all(not p for _, p in opts[3:]), opts)
        await pg.shot(os.path.join(OUT, "list.png"))
        verdict("no script errors", not pg.errors, pg.errors)
    print("screenshots:", OUT)
    return verdict.code()


sys.exit(asyncio.run(main()))
