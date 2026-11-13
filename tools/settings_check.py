"""Settings as a menu of screens (review 2026-11-11, block 4; the owner's yes — Q181; Search since stage И, Q187), in
headless Chrome over DevTools, on the stand, with real taps: Settings opens as six rows — Notifications, Models and keys,
Search, Voice and language, Pult and its parts, Security — each saying what is set there now; nothing of the old scroll is on it; a row opens its
screen at an address of its own, Back returns to the menu; each screen holds its own things and none of another's; a
link from Telegram opens a screen at once; Home's line about an update leads to Pult's parts, not to the menu; the menu
says when parts are behind; an unknown name is the menu; nothing runs over the edge at 320 px.
  STAND_VENDORS=1 STAND_HOMES=1 STAND_UPD=ready STAND_PARTS=lag STAND_LANG=ru STAND_PORT=18641 HOLD=300 ~/.local/share/pult/venv/bin/python tools/stand.py > /tmp/stand.out &
  ~/.local/share/pult/venv/bin/python tools/settings_check.py /tmp/stand.out [out_dir]
Screenshots go to out_dir (a temporary folder by default). Exit 1 on a failed check."""
import asyncio
import os
import sys
import tempfile

import _cdp

URLS = _cdp.stand_urls(sys.argv[1], ("HOME", "SETTINGS", "SETP", "SETM", "SETC"))
OUT = sys.argv[2] if len(sys.argv) > 2 else tempfile.mkdtemp(prefix="pult-settings-")
os.makedirs(OUT, exist_ok=True)
verdict = _cdp.Verdicts()
NAMES = [("calls", "Уведомления"), ("models", "Модели и ключи"), ("search", "Поиск"), ("voice", "Голос и язык"),
         ("parts", "Пульт и его части"), ("safe", "Безопасность")]
ROWS = "[...document.querySelectorAll('.set-menu .set-row')]"
# what a screen holds: the language's two buttons, the table of parts, the vendors' heading, where you are, the logins
HAS = {"lang": "[...document.querySelectorAll('.seg button')].some((b) => b.textContent === 'Русский')",
       "table": "document.querySelectorAll('.part').length >= 5",
       "vendors": "[...document.querySelectorAll('h3')].some((h) => h.textContent === 'Другие производители')",
       "where": "!!document.querySelector('.modes .seg')",
       "logins": "[...document.querySelectorAll('button.link')].some((b) => b.textContent === 'Выйти везде')",
       "log": "!!document.querySelector('details.logbox')",
       "quiet": "[...document.querySelectorAll('.sw-row b')].some((b) => b.textContent === 'Тихие часы')",
       "search": "[...document.querySelectorAll('.sw-row b')].some((b) => b.textContent === 'Поиск по переписке')"}
OWN = {"calls": ("where", "quiet"), "models": ("vendors",), "search": ("search",), "voice": ("lang",), "parts": ("table", "log"),
       "safe": ("logins",)}


async def fresh(pg, url):
    """A fresh load: the stand's links differ only after #, and that alone would not reload the app."""
    await pg.open("about:blank")
    await pg.open(url)


async def main():
    async with _cdp.Page() as pg:
        await fresh(pg, URLS["SETTINGS"])
        verdict("Settings opens as a menu", await pg.until("%s.length > 0" % ROWS, 150))
        rows = await pg.js("%s.map((r) => [r.dataset.set, r.querySelector('b').textContent, r.querySelector('.dim').textContent])" % ROWS)
        verdict("… six rows, in this order", [r[:2] for r in rows] == [list(n) for n in NAMES], rows)
        verdict("… each says what is set there now", all(r[2].strip() for r in rows), rows)
        said = {r[0]: r[2] for r in rows}
        verdict("… where you are, in Notifications' line", said.get("calls", "").startswith("Авто"), said.get("calls"))
        verdict("… whose models there are, in the models' line", said.get("models", "").startswith("Claude") and "DeepSeek" in said.get("models", ""),
                said.get("models"))
        verdict("… the language, in the voice's line", said.get("voice", "").startswith("Русский"), said.get("voice"))
        verdict("… parts behind are said in the menu, in the colour of a thing to do", await pg.until(
            "!!document.querySelector('.set-row[data-set=parts] .set-late') && /отстаёт: \\d/.test(document.querySelector('.set-row[data-set=parts] .set-late').textContent)", 100),
            await pg.js("document.querySelector('.set-row[data-set=parts] .dim').textContent"))
        old = [k for k in HAS if await pg.js(HAS[k])]
        verdict("… and nothing of the old scroll is on it", not old, old)
        tall = await pg.js("[document.documentElement.scrollHeight, innerHeight]")
        verdict("… the menu fits one screen", tall[0] <= tall[1], tall)
        await pg.shot(os.path.join(OUT, "menu.png"))

        for k, name in NAMES:
            await pg.tap("document.querySelector('.set-row[data-set=%s]')" % k)
            opened = await pg.until("location.hash === '#/settings/%s' && !!document.querySelector('.set-sub[data-set=%s]')" % (k, k), 100)
            if not verdict("«%s»: a tap opens its screen at an address of its own" % name, opened, await pg.js("location.hash")):
                await fresh(pg, URLS["SETTINGS"])
                await pg.until("%s.length > 0" % ROWS, 150)
                continue
            verdict("«%s»: its name on top" % name, await pg.js("document.querySelector('.set-sub h2').textContent") == name)
            for h in OWN[k]:
                verdict("«%s»: holds its own (%s)" % (name, h), await pg.until(HAS[h], 100))
            others = [h for h in HAS if h not in OWN[k] and await pg.js(HAS[h])]
            verdict("«%s»: and nothing of another screen" % name, not others, others)
            await pg.shot(os.path.join(OUT, k + ".png"))
            await pg.js("history.back()")
            verdict("«%s»: Back — the menu again" % name, await pg.until("location.hash === '#/settings' && %s.length === 6" % ROWS, 100),
                    await pg.js("location.hash"))

        # a link from Telegram opens a screen at once
        await fresh(pg, URLS["SETM"])
        verdict("a link to the models' screen opens it", await pg.until("location.hash === '#/settings/models' && " + HAS["vendors"], 150),
                await pg.js("location.hash"))
        await fresh(pg, URLS["SETC"])
        verdict("a link to Notifications opens it", await pg.until("location.hash === '#/settings/calls' && " + HAS["where"], 150),
                await pg.js("location.hash"))

        # Home's line about the update leads to Pult's parts
        await fresh(pg, URLS["HOME"])
        verdict("Home has the line about an update", await pg.until("!!document.querySelector('.upd-row')", 150))
        await pg.tap("document.querySelector('.upd-row')")
        verdict("… and it leads to Pult's parts, not to the menu", await pg.until("location.hash === '#/settings/parts' && " + HAS["table"], 100),
                await pg.js("location.hash"))
        await pg.js("history.back()")
        verdict("… Back from there — Home", await pg.until("!!document.querySelector('.upd-row') && !location.hash.includes('settings')", 100),
                await pg.js("location.hash"))
        # the gear — the menu
        await pg.tap("document.querySelector('a.gear')")
        verdict("the gear on Home opens the menu", await pg.until("location.hash === '#/settings' && %s.length === 6" % ROWS, 100))

        # a name there is no screen for: the menu
        await pg.js("location.hash = '#/settings/nothing'")
        verdict("an unknown name is the menu", await pg.until("%s.length === 6" % ROWS, 100))

        await pg.cmd("Emulation.setDeviceMetricsOverride", width=320, height=860, deviceScaleFactor=2, mobile=True)
        await asyncio.sleep(0.4)
        fits = await pg.js("[...document.querySelectorAll('.set-row, .set-row .set-x, .set-row svg')].every((e) => e.getBoundingClientRect().right <= innerWidth + 0.5)")
        verdict("320 px: nothing in the menu runs over the edge", fits)
        await pg.shot(os.path.join(OUT, "menu-320.png"))
        verdict("no script errors on the page", not pg.errors, pg.errors[:3])
    print("screenshots:", OUT)
    sys.exit(verdict.code())


asyncio.run(main())
