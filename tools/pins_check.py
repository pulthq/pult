"""Rows that slide (stage Zh) in headless Chrome over DevTools, on the stand with STAND_TAGS=1 STAND_HOMES=1
STAND_PINS=blog,shop STAND_HIDES=desk: Projects lists the pinned first, the newest pin on top, each with its mark, and
folds the hidden at the bottom; a finger sliding a row to the left opens Pin, Hide and New task under it, a short slide
springs back, a tap on the open row closes it and opens nothing; the pin from the row puts the project on top at once;
Hide moves it into the fold, Show in the fold brings it back; New task opens the form with the project; the project's
header has the same pin as a button; the new task's list has the pinned first with the mark and no hidden; on Home a
task's row slides to Tags (the sheet opens) and a card of "Your move" to Got it. The stand's output shows what the
computer's journal says of each.
  STAND_TAGS=1 STAND_HOMES=1 STAND_PINS=blog,shop STAND_HIDES=desk STAND_LANG=ru STAND_PORT=18149 HOLD=300 ~/.local/share/pult/venv/bin/python tools/stand.py > /tmp/stand.out &
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
# the rows of list i: the name, the pin's mark, how far the row slid
ROWS = """JSON.stringify([...document.querySelectorAll('.list')[%d].querySelectorAll('.swr')].map((r) => {
  const tf = getComputedStyle(r.querySelector('.swr-in')).transform;
  return {n: (r.querySelector('.pn b') || {}).textContent, pin: !!r.querySelector('.ptail .ic-pin'),
          x: tf === 'none' ? 0 : new DOMMatrixReadOnly(tf).m41}; }))"""
ROW = "document.querySelectorAll('.list')[%d].querySelectorAll('.swr')[%d]"
ACTS = "JSON.stringify([...(%s).querySelectorAll('.swr-act span')].map((s) => s.textContent))"
FOLD = "(document.querySelector('h3.toggle') || {}).textContent || ''"


def journal():
    with open(STAND, encoding="utf-8", errors="replace") as f:
        return f.read()


async def slide(pg, expr, dx, steps=8):
    """A finger on the element's middle, dx to the side in steps, lifted."""
    r = await pg.js("(() => { const el = (%s); el.scrollIntoView({block: 'center'}); const b = el.getBoundingClientRect(); return [b.left + b.width / 2, b.top + b.height / 2]; })()" % expr)
    x, y = r
    await pg.cmd("Input.dispatchTouchEvent", type="touchStart", touchPoints=[{"x": x, "y": y}])
    for k in range(1, steps + 1):
        await pg.cmd("Input.dispatchTouchEvent", type="touchMove", touchPoints=[{"x": x + dx * k / steps, "y": y}])
        await asyncio.sleep(0.02)
    await pg.cmd("Input.dispatchTouchEvent", type="touchEnd", touchPoints=[])
    await asyncio.sleep(0.5)


async def tap_row(pg, expr):
    """A finger on the visible slice of an open row: its left edge plus a little — the name itself slid off the screen."""
    r = await pg.js("(() => { const el = (%s); el.scrollIntoView({block: 'center'}); const b = el.getBoundingClientRect(); return [b.left + 40, b.top + b.height / 2]; })()" % expr)
    await pg.cmd("Input.dispatchTouchEvent", type="touchStart", touchPoints=[{"x": r[0], "y": r[1]}])
    await pg.cmd("Input.dispatchTouchEvent", type="touchEnd", touchPoints=[])
    await asyncio.sleep(0.5)


async def rows(pg, i=0):
    v = await pg.js(ROWS % i)
    return json.loads(v) if v is not None else ["no rows: " + str(await pg.js("document.body.innerText.slice(0, 120)"))]


async def acts(pg, expr):
    return json.loads(await pg.js(ACTS % expr))


async def main():
    async with _cdp.Page() as pg:
        await pg.open(U["PROJECTS"])
        verdict("Projects lists three projects and folds the hidden one", await pg.until("document.querySelectorAll('.list')[0] && document.querySelectorAll('.list')[0].querySelectorAll('.swr').length >= 3", 200)
                and (await pg.js(FOLD)).startswith("Скрытые · 1"), await pg.js(FOLD))
        rs = await rows(pg)
        verdict("the pinned first, the newest pin on top, each with its mark; then the project that waits for you",
                [(r["n"], r["pin"]) for r in rs] == [("acme-shop", True), ("blog", True), ("Принтер", False)], rs)
        await pg.shot(os.path.join(OUT, "projects.png"))
        # a short slide springs back; a long one stays open on three buttons
        await slide(pg, ROW % (0, 2), -30)
        rs = await rows(pg)
        verdict("a short slide springs back", rs[2]["x"] == 0, rs[2])
        verdict("... and the journal says so", "swipe on a project's row sprang back" in journal())
        await slide(pg, ROW % (0, 2), -200)
        rs = await rows(pg)
        verdict("a long slide stays open on Pin, Hide and New task", rs[2]["x"] == -240 and await acts(pg, ROW % (0, 2)) == ["Закрепить", "Спрятать", "Новая задача"], rs[2], await acts(pg, ROW % (0, 2)))
        verdict("... and the journal says so", "swipe on a project's row opened on its action" in journal())
        await pg.shot(os.path.join(OUT, "swipe.png"))
        # a tap on the open row closes it and opens nothing
        await tap_row(pg, ROW % (0, 2))
        rs = await rows(pg)
        verdict("a tap on the open row closes it", rs[2]["x"] == 0, rs[2])
        verdict("... and opens nothing", await pg.js("location.hash") == "#/projects", await pg.js("location.hash"))
        # the pin from the row: on top at once, with the mark; the journal counts it as the swipe's
        await slide(pg, ROW % (0, 2), -200)
        await pg.tap("(%s).querySelectorAll('.swr-act')[0]" % (ROW % (0, 2)))
        verdict("the pin from the row puts the project on top", await pg.until(
            "document.querySelector('.list .swr .pn b').textContent === 'Принтер' && !!document.querySelector('.list .swr .ptail .ic-pin')", 30), await rows(pg))
        verdict("... the journal counts it as the swipe's", "project pinned via the swipe" in journal())
        # Hide from the row: into the fold, unpinned; Show in the fold brings it back
        await slide(pg, ROW % (0, 1), -200)
        await pg.tap("(%s).querySelectorAll('.swr-act')[1]" % (ROW % (0, 1)))
        verdict("Hide moves the project into the fold", await pg.until("document.querySelectorAll('.list')[0].querySelectorAll('.swr').length === 2", 30)
                and (await pg.js(FOLD)).startswith("Скрытые · 2"), await rows(pg), await pg.js(FOLD))
        verdict("... and the journal says so", "project hidden via the swipe" in journal())
        await pg.tap("document.querySelector('h3.toggle')")
        verdict("the fold opens on the hidden two, the one just hidden first", await pg.until("document.querySelectorAll('.list').length === 2", 30)
                and [r["n"] for r in await rows(pg, 1)] == ["acme-shop", "support-desk"], await rows(pg, 1))
        await slide(pg, ROW % (1, 0), -120)
        verdict("a hidden row slides to Show alone", await acts(pg, ROW % (1, 0)) == ["Показать"], await acts(pg, ROW % (1, 0)))
        await pg.shot(os.path.join(OUT, "hidden.png"))
        await pg.tap("(%s).querySelector('.swr-act')" % (ROW % (1, 0)))
        verdict("Show brings it back to the list, unpinned", await pg.until("document.querySelectorAll('.list')[0].querySelectorAll('.swr').length === 3", 30)
                and [(r["n"], r["pin"]) for r in await rows(pg)] == [("Принтер", True), ("blog", True), ("acme-shop", False)]
                and (await pg.js(FOLD)).startswith("Скрытые · 1"), await rows(pg), await pg.js(FOLD))
        verdict("... and the journal says so", "project shown again via the swipe" in journal())
        # New task from the row: the form with that project
        await slide(pg, ROW % (0, 2), -200)
        await pg.tap("(%s).querySelectorAll('.swr-act')[2]" % (ROW % (0, 2)))
        verdict("New task opens the form with the project", await pg.until("location.hash.startsWith('#/new?pkey=') && !!document.querySelector('.form .field span')", 50)
                and await pg.js("document.querySelector('.form .field span').textContent") == "acme-shop", await pg.js("location.hash"))
        # the project's header: the same pin as a button — the printer, pinned from its row, is the first row
        await pg.js("location.hash = '#/projects'")
        verdict("back to Projects", await pg.until("document.querySelectorAll('.list .swr').length >= 3", 100))
        await pg.tap("(%s).querySelector('.pn b')" % (ROW % (0, 0)))
        verdict("the project's header has the pin, on", await pg.until("!!document.querySelector('.ph .pinb.on')", 100),
                await pg.js("location.hash + ' | ' + document.body.innerText.slice(0, 100).replace(/\\n/g, ' / ')"), pg.errors)
        await pg.tap("document.querySelector('.ph .pinb')")
        verdict("a tap unpins", await pg.until("document.querySelector('.ph .pinb') && !document.querySelector('.ph .pinb.on')", 30))
        verdict("... the journal counts it as the button's", "project unpinned via the button" in journal())
        await pg.tap("document.querySelector('.ph .pinb')")
        verdict("a tap pins again", await pg.until("!!document.querySelector('.ph .pinb.on')", 30))
        await pg.shot(os.path.join(OUT, "header.png"))
        # the new task's list: the pinned first, the newest on top, with the mark; no hidden
        await pg.js("location.hash = '#/new'")
        verdict("the new task's form", await pg.until("!!document.querySelector('.form .field')", 100))
        await pg.tap("document.querySelector('.form .field')")
        verdict("its list opens", await pg.until("document.querySelectorAll('.card.pick .opt').length > 2", 30))
        opts = json.loads(await pg.js("JSON.stringify([...document.querySelectorAll('.card.pick .opt')].filter((o) => !o.classList.contains('add')).map((o) => [o.firstChild.textContent, !!o.querySelector('.opt-pin')]))"))
        verdict("the pinned first in the list, the newest on top, with the mark; the hidden one is not there",
                opts == [["Принтер", True], ["blog", True], ["acme-shop", False]], opts)
        await pg.shot(os.path.join(OUT, "list.png"))
        # Home: a task's row slides to Tags, a card of "Your move" to Got it; a hidden project's block is off the board
        await pg.js("location.hash = '#/'")
        verdict("Home with a running task and a card of yours", await pg.until("!!document.querySelector('.item.run') && !!document.querySelector('.swr.card-sw')", 100))
        run = "document.querySelector('.item.run').closest('.swr')"
        await slide(pg, run, -120)
        verdict("a task's row slides to Tags", await acts(pg, run) == ["Теги"], await acts(pg, run))
        verdict("... and the journal says so", "swipe on a task's row opened on its action" in journal())
        await pg.tap("(%s).querySelector('.swr-act')" % run)
        verdict("Tags opens the task's sheet", await pg.until("!!document.querySelector('.tagpick')", 30))
        await pg.shot(os.path.join(OUT, "tags.png"))
        await pg.tap("document.querySelector('.tagpick .x')")
        verdict("... which closes", await pg.until("!document.querySelector('.tagpick')", 30))
        n = await pg.js("document.querySelectorAll('.swr.card-sw').length")
        card = "document.querySelector('.swr.card-sw')"
        await slide(pg, "(%s).querySelector('.card-h')" % card, -120)       # from the card's header: a slide from its field stays the field's
        verdict("a card of yours slides to Got it", await acts(pg, card) == ["Понятно"], await acts(pg, card))
        verdict("... and the journal says so", "swipe on a card opened on its action" in journal())
        await pg.shot(os.path.join(OUT, "card.png"))
        await pg.tap("(%s).querySelector('.swr-act')" % card)
        verdict("Got it takes the card away", await pg.until("document.querySelectorAll('.swr.card-sw').length === %d" % (n - 1), 30))
        names = json.loads(await pg.js("JSON.stringify([...document.querySelectorAll('.list.proj .pn b')].map((b) => b.textContent))"))
        verdict("the hidden project's block is off the board", "support-desk" not in names, names)
        verdict("no script errors", not pg.errors, pg.errors)
    print("screenshots:", OUT)
    return verdict.code()


sys.exit(asyncio.run(main()))
