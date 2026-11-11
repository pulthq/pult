"""How full a task's context is, as a line along its card's bottom edge (the owner's idea, Q151–Q152), in headless Chrome
over DevTools, on the stand where the tasks' contexts are filled each its own way (STAND_CTX=1): the cards of "Your
move" — the question 33 %, the permission 72 %, the weekly report 13 %, the search 94 % — carry the card's own stripe on
along the bottom, as long as the context is used, the search's red; "Running now" — the dark theme 55 %, the task on
DeepSeek 8 % (its window is bigger), green, in place of the line between the rows; the task without Claude none; the
line takes no room and stays inside the card; it says the figure aloud; the project's screen the same; the task's own
screen has none (it says the number by the field). Light and dark, 412 and 320 px.
  STAND_VENDORS=1 STAND_HOMES=1 STAND_REPORT=1 STAND_CTX=1 STAND_LANG=ru STAND_PORT=18631 HOLD=300 ~/.local/share/pult/venv/bin/python tools/stand.py > /tmp/stand.out &
  ~/.local/share/pult/venv/bin/python tools/ctx_check.py /tmp/stand.out [out_dir]
Screenshots go to out_dir (a temporary folder by default). Exit 1 on a failed check."""
import asyncio
import json
import os
import sys
import tempfile

import _cdp

URLS = _cdp.stand_urls(sys.argv[1], ("HOME", "PROJ", "SESS"))
OUT = sys.argv[2] if len(sys.argv) > 2 else tempfile.mkdtemp(prefix="pult-ctx-")
os.makedirs(OUT, exist_ok=True)
verdict = _cdp.Verdicts()
# the stand's tasks (STAND_CTX=1, STAND_LANG=ru) and how full their contexts are: what Claude Code's gauge says — the
# last reply's tokens of the window less its room for the answer (167 000 of 200 000; DeepSeek's 753 432 of 786 432)
CARDS = (("С каких заявок начать?", 33), ("Оформление заказа", 72), ("Отчёт поддержки за неделю", 13), ("Поиск: опечатки", 94))
ROWS = (("Сделай тёмную тему для админки", 55), ("Переименуй CSS-переменные", 8))
JOB = "python train.py"
COLOURS = {"light": {"attn": "rgb(232, 137, 43)", "ok": "rgb(37, 122, 79)", "bad": "rgb(194, 59, 59)"},
           "dark": {"attn": "rgb(243, 166, 74)", "ok": "rgb(88, 192, 136)", "bad": "rgb(239, 106, 106)"}}

# a card or a row by its words → its line: where, how long, which colour, what it says aloud
LINE = """((sel, words) => { const c = [...document.querySelectorAll(sel)].find((x) => x.textContent.includes(words));
  if (!c) return null; const cx = c.querySelector(':scope > .cx'); if (!cx) return {line: false};
  const b = cx.getBoundingClientRect(), cb = c.getBoundingClientRect(), fill = getComputedStyle(cx, '::before');
  return {line: true, pct: Math.round(parseFloat(fill.width) * 100 / b.width), colour: fill.backgroundColor,
    bad: cx.classList.contains('bad'), label: cx.getAttribute('aria-label'), height: b.height,
    edge: Math.abs(b.bottom - cb.bottom) <= 1.5 && Math.abs(b.left - cb.left) <= 0.5 && b.right <= cb.right + 0.5,
    taken: getComputedStyle(cx).position === 'absolute', clipped: getComputedStyle(c).overflow === 'hidden' || !c.matches('.card'),
    last: c.lastElementChild === cx, whole: [c.closest('.swr'), c.closest('.list')].every((w) => !w || b.bottom <= w.getBoundingClientRect().bottom + 0.5)}; })"""


async def lines(pg, where, width, theme):
    tint = COLOURS[theme]
    for words, pct in CARDS:
        x = await pg.js("%s('.zone-mine .card, .card.mine, .card.ask, .card.perm', %s)" % (LINE, json.dumps(words)))
        name = "%s %d px %s · «%s»" % (where, width, theme, words)
        if not verdict(name + ": a line along the card's bottom edge", bool(x and x.get("line")), x):
            continue
        verdict(name + ": as long as the context is used, %d %%" % pct, abs(x["pct"] - pct) <= 2, x["pct"])
        red = pct >= 90
        verdict(name + (": red — about to be compacted" if red else ": the card's own colour, the stripe's"),
                x["bad"] == red and x["colour"] == tint["bad" if red else "attn"], x["colour"], x["bad"])
        verdict(name + ": at the edge, inside the card, taking no room, its last thing, whole",
                x["edge"] and x["taken"] and x["clipped"] and x["last"] and x["whole"] and 2 <= x["height"] <= 4, x)
        verdict(name + ": says the figure aloud", x["label"] == "Контекст заполнен на %d %%" % pct, x["label"])
    for words, pct in ROWS:
        x = await pg.js("%s('.zone-run .item.run', %s)" % (LINE, json.dumps(words)))
        name = "%s %d px %s · «%s»" % (where, width, theme, words)
        if not verdict(name + ": a line under the row", bool(x and x.get("line")), x):
            continue
        verdict(name + ": %d %%, green, from the list's own bar, whole — nothing around it clips it" % pct,
                abs(x["pct"] - pct) <= 2 and x["colour"] == tint["ok"] and not x["bad"] and x["edge"] and x["whole"]
                and 1.5 <= x["height"] <= 3, x)


async def main():
    async with _cdp.Page() as pg:
        for width, theme in ((412, "light"), (412, "dark"), (320, "light")):
            await pg.cmd("Emulation.setDeviceMetricsOverride", width=width, height=860, deviceScaleFactor=2, mobile=True)
            await pg.cmd("Emulation.setEmulatedMedia", features=[{"name": "prefers-color-scheme", "value": theme}])
            await pg.open("about:blank")
            await pg.open(URLS["HOME"])
            verdict("Home %d px %s: up, with the cards of «Your move»" % (width, theme),
                    await pg.until("document.querySelectorAll('.zone-mine .cx').length >= 4", 150))
            await lines(pg, "Home", width, theme)
            if width == 412 and theme == "light":
                job = await pg.js("%s('.zone-run .item', %s)" % (LINE, json.dumps(JOB)))
                verdict("Home: the task without Claude has no line", job == {"line": False}, job)
            await pg.shot(os.path.join(OUT, "home-%d-%s.png" % (width, theme)))
        await pg.cmd("Emulation.setDeviceMetricsOverride", width=412, height=860, deviceScaleFactor=2, mobile=True)
        await pg.cmd("Emulation.setEmulatedMedia", features=[{"name": "prefers-color-scheme", "value": "light"}])
        await pg.open("about:blank")
        await pg.open(URLS["PROJ"])
        verdict("the project's screen: up", await pg.until("document.querySelectorAll('.zone-mine .cx').length >= 2", 150))
        for words, pct in (CARDS[1], CARDS[3]):
            x = await pg.js("%s('.zone-mine .card', %s)" % (LINE, json.dumps(words)))
            verdict("the project's screen · «%s»: the same line, %d %%" % (words, pct),
                    bool(x and x.get("line")) and abs(x["pct"] - pct) <= 2 and x["edge"], x)
        for words, pct in ROWS:
            x = await pg.js("%s('.zone-run .item.run', %s)" % (LINE, json.dumps(words)))
            verdict("the project's screen · «%s»: %d %% under the row, whole — the last row's too" % (words, pct),
                    bool(x and x.get("line")) and abs(x["pct"] - pct) <= 2 and x["whole"], x)
        await pg.shot(os.path.join(OUT, "project.png"))
        await pg.open("about:blank")
        await pg.open(URLS["SESS"])
        await pg.until("!!document.querySelector('.card.perm')", 150)
        verdict("the task's own screen: no line — the number is by its field",
                await pg.js("!document.querySelector('.cx') && !!document.querySelector('.card.perm')"))
        verdict("no script errors", not pg.errors, pg.errors)
    print("screenshots:", OUT)
    return verdict.code()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
