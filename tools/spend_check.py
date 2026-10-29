"""Resources → the plan's limits in headless Chrome over DevTools, on the stand: "what spent it" — the project's colour
mark is a small square on the name's line, in the colour of its part of the bar above; the chart's legend — two small
squares and a short line. v0.18.15–19 drew the marks as circles as wide as the project's name: the tags' colour sheet
took the same class, `.swatch`, and its round 100 % wide buttons won (2026-10-28).
  STAND_LANG=ru STAND_PORT=18147 HOLD=300 ~/.local/share/pult/venv/bin/python tools/stand.py > /tmp/stand.out &
  ~/.local/share/pult/venv/bin/python tools/spend_check.py "$(grep '^USAGE ' /tmp/stand.out | cut -d' ' -f2)" [out_dir]
Screenshots go to out_dir (a temporary folder by default). Exit 1 on a failed check."""
import asyncio
import json
import os
import sys
import tempfile

import _cdp

URL = sys.argv[1]
OUT = sys.argv[2] if len(sys.argv) > 2 else tempfile.mkdtemp(prefix="pult-spend-")
os.makedirs(OUT, exist_ok=True)
verdict = _cdp.Verdicts()
# each row: its name, its mark's box and colour, the row's height; the bar's parts' colours in order
ROWS = """JSON.stringify([...document.querySelectorAll('.card.spent .prow')].map((r) => {
  const m = r.querySelector('.swatch'), b = m.getBoundingClientRect();
  return {n: r.querySelector('span').textContent, w: b.width, h: b.height, row: r.getBoundingClientRect().height,
          c: getComputedStyle(m).backgroundColor}; }))"""
BAR = "JSON.stringify([...document.querySelectorAll('.card.spent .stack i')].map((i) => getComputedStyle(i).backgroundColor))"
LEGEND = """JSON.stringify([...document.querySelectorAll('.sp-leg .swatch')].map((m) => {
  const b = m.getBoundingClientRect(); return {line: m.classList.contains('line'), w: b.width, h: b.height}; }))"""


async def main():
    async with _cdp.Page() as pg:
        await pg.open(URL)
        verdict("Resources shows what spent the limit", await pg.until("document.querySelectorAll('.card.spent .prow').length > 1", 200))
        rows, bar = json.loads(await pg.js(ROWS)), json.loads(await pg.js(BAR))
        verdict("each project's mark is a small square, whatever its name", all(r["w"] <= 12 and r["w"] == r["h"] for r in rows),
                [(r["n"], round(r["w"]), round(r["h"])) for r in rows])
        verdict("... on the name's line", all(r["row"] < 40 for r in rows), [(r["n"], round(r["row"])) for r in rows])
        verdict("... in the colour of its part of the bar", [r["c"] for r in rows] == bar, [r["c"] for r in rows], bar)
        await pg.js("document.querySelector('.card.spent').scrollIntoView({block: 'center'})")
        await asyncio.sleep(0.3)
        await pg.shot(os.path.join(OUT, "spent.png"))
        leg = json.loads(await pg.js(LEGEND))
        verdict("the chart's legend: sessions and agents — small squares", [m for m in leg if not m["line"]] != []
                and all(m["w"] <= 12 and m["w"] == m["h"] for m in leg if not m["line"]), leg)
        verdict("... the even pace — a short line", any(m["line"] for m in leg)
                and all(m["w"] <= 12 and m["h"] <= 3 for m in leg if m["line"]), leg)
        await pg.js("document.querySelector('.sp-leg').scrollIntoView({block: 'center'})")
        await asyncio.sleep(0.3)
        await pg.shot(os.path.join(OUT, "legend.png"))
        verdict("no script errors", not pg.errors, pg.errors)
    print("screenshots:", OUT)
    return verdict.code()


sys.exit(asyncio.run(main()))
