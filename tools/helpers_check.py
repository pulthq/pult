"""Helpers and commands in the background, seen while the turn runs (Q128, 2026-11-03), in headless Chrome over
DevTools, on the stand: the dark theme's turn has started two helpers and a command in the background — the daemon
lists them by their PostToolUse, not after the turn. Home's card in "Running now" and the session's "working…" say
"2 helpers, 1 command in the background"; a tap opens the sheet: each helper's type, model, steps and tokens, what it
does now — from its own record — and the command as before. The session's long line of names stays off while the
turn runs. On 412 and 320 px, light and dark.
  STAND_HELPERS=1 STAND_LANG=ru HOLD=300 ~/.local/share/pult/venv/bin/python tools/stand.py > /tmp/stand.out &
  ~/.local/share/pult/venv/bin/python tools/helpers_check.py /tmp/stand.out [out_dir]
Screenshots go to out_dir (a temporary folder by default). Exit 1 on a failed check."""
import asyncio
import os
import sys
import tempfile

import _cdp

URLS = _cdp.stand_urls(sys.argv[1], ("HOME", "SESS7"))
OUT = sys.argv[2] if len(sys.argv) > 2 else tempfile.mkdtemp(prefix="pult-helpers-")
os.makedirs(OUT, exist_ok=True)
verdict = _cdp.Verdicts()
LINE = "в фоне 2 помощника, 1 команда"
CARD = "[...document.querySelectorAll('.item.run')].find((c) => c.textContent.includes('Сделай тёмную тему'))"
TASKS = "[...document.querySelectorAll('.card.pick .task')]"


async def main():
    for width, dark in ((412, False), (320, True)):
        async with _cdp.Page(width=width) as pg:
            if dark:
                await pg.cmd("Emulation.setEmulatedMedia", features=[{"name": "prefers-color-scheme", "value": "dark"}])
            tag = "%d%s" % (width, " dark" if dark else "")
            await pg.open(URLS["HOME"])
            verdict("%s: Home's running card says what runs in the background" % tag,
                    await pg.until("(%s || {textContent: ''}).textContent.includes(%r)" % (CARD, LINE), 150),
                    await pg.js("(%s || {}).textContent" % CARD))
            await pg.shot(os.path.join(OUT, "home-%d%s.png" % (width, "-dark" if dark else "")))
            await pg.open("about:blank")            # the stand's links differ after "#" only: a page of its own
            await pg.open(URLS["SESS7"])
            verdict("%s: «working…» and beside it the helpers and the command" % tag,
                    await pg.until("(document.querySelector('.working') || {textContent: ''}).textContent.includes(%r)" % LINE, 150),
                    await pg.js("(document.querySelector('.working') || {}).textContent"))
            verdict("%s: no long line of names on top while the turn runs" % tag,
                    await pg.js("!document.querySelector('.sess-h .bg')"))
            verdict("%s: nothing wider than the screen" % tag,
                    await pg.js("document.documentElement.scrollWidth <= innerWidth"), await pg.js("document.documentElement.scrollWidth"))
            await pg.shot(os.path.join(OUT, "session-%d%s.png" % (width, "-dark" if dark else "")))
            await pg.tap("document.querySelector('.working .bg-n')")
            verdict("%s: a tap opens the sheet with the three" % tag, await pg.until(TASKS + ".length === 3", 80),
                    await pg.js(TASKS + ".length"))
            rows = await pg.js(TASKS + ".map((t) => t.innerText.replace(/\\s+/g, ' '))") or ["", "", ""]
            one, two, cmd = rows[0], rows[1], rows[2]
            verdict("%s: the first helper — Explore on Haiku, 14 steps, its tokens, reading line.js now" % tag,
                    all(x in one for x in ("помощник · Explore", "Haiku 5.5", "14 шагов", "41 тыс. токенов",
                                           "admin/charts/line.js")), one)
            verdict("%s: the second — general-purpose on Opus, 6 steps, searching --color- now" % tag,
                    all(x in two for x in ("помощник · general-purpose", "Opus 5.5", "6 шагов", "--color-")), two)
            verdict("%s: the command as before — its line, processor and memory" % tag,
                    all(x in cmd for x in ("команда", "npm run build", "Процессор", "Память")), cmd)
            await pg.shot(os.path.join(OUT, "sheet-%d%s.png" % (width, "-dark" if dark else "")))
            verdict("%s: no script errors" % tag, not pg.errors, pg.errors[:3])
    print("screenshots:", OUT)
    sys.exit(verdict.code())


asyncio.run(main())
