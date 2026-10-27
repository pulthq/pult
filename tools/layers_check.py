"""Layers over a screen (review 2026-10-27, П8), in headless Chrome over DevTools, on the stand, with real taps.
Home: a session's background task opens its sheet, and Telegram's Back shows while it is open — on Home it is hidden,
and the phone's own Back with no Back button closes the whole app; Telegram's Back closes the sheet and Home stays;
two quick taps on ✕ go back once (the second left the app). The session: the model menu is over the paperclip, Back
closes the menu only, two quick taps on ✕ leave the session where it is.
  STAND_TAGS=1 STAND_LANG=ru STAND_PORT=18141 HOLD=300 ~/.local/share/pult/venv/bin/python tools/stand.py > /tmp/stand.out &
  ~/.local/share/pult/venv/bin/python tools/layers_check.py /tmp/stand.out home
  STAND_LANG=ru STAND_PORT=18142 HOLD=300 ~/.local/share/pult/venv/bin/python tools/stand.py > /tmp/stand2.out &
  ~/.local/share/pult/venv/bin/python tools/layers_check.py /tmp/stand2.out session
(the session's part needs the plain stand: its SESS is a session with a field). Exit 1 on a failed check."""
import asyncio
import sys

import _cdp

URLS = _cdp.stand_urls(sys.argv[1], ("HOME", "SESS"))
PART = sys.argv[2]
verdict = _cdp.Verdicts()


async def main():
    async with _cdp.Page() as pg:
        bb = "Telegram.WebApp.BackButton.isVisible"
        if PART == "home":
            bg = "document.querySelector('.bg.tap, .chip.mute.tap')"
            await pg.open(URLS["HOME"])
            verdict("Home has a session with a background task", await pg.until("!!" + bg, 150))
            verdict("on Home Telegram's Back is hidden", await pg.js(bb) is False, await pg.js(bb))
            h0 = await pg.js("history.length")
            await pg.tap(bg)
            verdict("a tap on the background task opens its sheet", await pg.until("!!document.querySelector('.card.pick')"))
            verdict("with the sheet open Telegram's Back shows", await pg.js(bb) is True, await pg.js(bb))
            await pg.js("Telegram.WebView.receiveEvent('back_button_pressed')")
            verdict("Telegram's Back closes the sheet", await pg.until("!document.querySelector('.card.pick')"))
            await asyncio.sleep(0.3)
            verdict("... and stays on Home, its Back hidden again",
                    not await pg.js("/#\\/(s|p)\\//.test(location.hash)") and await pg.js(bb) is False, [await pg.js("location.hash"), await pg.js(bb)])
            await pg.tap(bg)
            await pg.until("!!document.querySelector('.card.pick .x')")
            await pg.js("(() => { const x = document.querySelector('.card.pick .x'); x.click(); x.click(); })()")   # before Back comes back
            await asyncio.sleep(0.8)
            verdict("two quick taps on ✕ close the sheet once — the app stays",
                    await pg.js("location.href.startsWith('http://127.0.0.1') && !document.querySelector('.card.pick')"), await pg.js("location.href"))
            verdict("... the history back by one step only", await pg.js("history.length") >= h0, [h0, await pg.js("history.length")])
            await pg.tap(bg)
            verdict("the sheet opens again", await pg.until("!!document.querySelector('.card.pick')"))
        else:
            await pg.open(URLS["SESS"])
            verdict("the session opens", await pg.until("!!document.querySelector('textarea')", 150))
            await asyncio.sleep(1)
            hash0 = await pg.js("location.hash")
            chip = "document.querySelector('.status .mchip')"
            verdict("the session has its model chip", await pg.until("!!" + chip), await pg.js("(document.querySelector('.status') || {}).textContent"))
            await pg.tap(chip)
            verdict("the model menu opens over the session", await pg.until("!!document.querySelector('.card.pick')"))
            hit = await pg.js("(() => { const c = document.querySelector('.clip'); if (!c) return null; const b = c.getBoundingClientRect();"
                              " const el = document.elementFromPoint(b.left + b.width / 2, b.top + b.height / 2); return el && (el.className || el.tagName); })()")
            verdict("under the menu the paperclip can't be tapped: the backdrop is over it", hit == "backdrop", hit)
            await pg.js("history.back()")
            verdict("Back closes the menu and leaves the session where it is",
                    await pg.until("!document.querySelector('.card.pick')") and await pg.js("location.hash") == hash0, await pg.js("location.hash"))
            await pg.tap(chip)
            await pg.until("!!document.querySelector('.card.pick .x')")
            await pg.js("(() => { const x = document.querySelector('.card.pick .x'); x.click(); x.click(); })()")
            await asyncio.sleep(0.8)
            verdict("two quick taps on ✕ close the menu, the session stays",
                    await pg.js("location.hash") == hash0 and not await pg.js("!!document.querySelector('.card.pick')"), await pg.js("location.hash"))
        verdict("no script errors", not pg.errors, pg.errors)
    sys.exit(verdict.code())


asyncio.run(main())
