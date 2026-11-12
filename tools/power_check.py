"""The machine on Home and in Resources (2026-11-12), on the stand in headless Chrome. No real accounts or tasks.
Run through tools/check.py power (STAND_LANG=ru). Home's top: the limit apart from the machine — its processor, memory
and power — nothing cut on a 320 px phone; the stand's battery moved through its states (api_stand_power); each tile
leads to its own tab; the machine's tab is named after it and has the power card; Settings → Pult and its parts
renames the machine; the offline banner says its name. Screenshots at 320 and 412 px use only made-up data.
"""
import asyncio
import os
import sys

import _cdp

# the strip fits: nothing sticks out of it, no label or value is cut
# — and each column stays inside its own tile: what sticks out of one hides under the next (the gear), 2026-11-12
FITS = """(() => { const h = document.querySelector('.where-h'); if (!h) return false;
  const cut = [...h.querySelectorAll('.tl-l, .tl-v')].filter((e) => e.scrollWidth > e.clientWidth + 1);
  const out = [...h.querySelectorAll('.tl-c')].filter((c) => { const t = c.closest('.where-b').getBoundingClientRect(),
    r = c.getBoundingClientRect(); return r.right > t.right - 6 || r.left < t.left + 6; });
  return h.scrollWidth <= h.clientWidth + 1 && h.getBoundingClientRect().right <= innerWidth && !cut.length && !out.length; })()"""
# one line: every tile on the same row
ONE_ROW = """(() => { const b = [...document.querySelectorAll('.where-h > *')].map((e) => e.getBoundingClientRect().top);
  return b.length > 1 && b.every((t) => Math.abs(t - b[0]) < 2); })()"""
POWER = "(document.querySelector('.where .tl-power') || {}).textContent || ''"
TAB = "(document.querySelector('.subtabs button[aria-selected=\"true\"]') || {}).textContent || ''"


async def home(page):
    """Home afresh: it reads the overview when it opens."""
    await page.js("location.hash = '#/projects'")
    await asyncio.sleep(0.3)
    await page.js("location.hash = '#/'")
    return await page.until("!!document.querySelector('.where .top-load')")


async def battery(page, spec):
    await page.js("healthConn.api('stand_power', {spec: '%s'})" % spec)
    return await home(page)


async def main():
    urls = _cdp.stand_urls(sys.argv[1])
    out = sys.argv[2]
    os.makedirs(out, exist_ok=True)
    verdict = _cdp.Verdicts()
    async with _cdp.Page(width=320) as page:
        await page.open(urls["HOME"])
        ok = await page.until("!!document.querySelector('.where .top-load')")
        await page.js("(async () => { window.healthConn = await import('/pult/static/core/conn.js'); })()")
        verdict("Home: the limit and the machine in tiles of their own, no mode on the strip", ok and await page.js(
            "!!document.querySelector('.where .top-lim') && !document.querySelector('.where .modes')"
            " && !document.querySelector('.where').textContent.includes('Авто')"))
        verdict("the machine's tile: processor, memory and the battery with its charge", await page.js(
            "!!document.querySelector('.where .tl-cpu') && !!document.querySelector('.where .tl-mem')"
            " && !!document.querySelector('.where .tl-power .ic-battery')") and "76" in (await page.js(POWER) or ""),
            await page.js(POWER))
        verdict("320 px: nothing cut on the strip (on the battery)", await page.js(FITS))
        verdict("320 px: the machine's tile on a line of its own", not await page.js(ONE_ROW))
        await page.shot(os.path.join(out, "home-battery-320.png"))
        await battery(page, "batt:19")
        verdict("20 % and under: the charge turns yellow", await page.until("!!document.querySelector('.where .tl-power .tl-v.warn')"))
        await battery(page, "batt:9")
        verdict("10 % and under: red", await page.until("!!document.querySelector('.where .tl-power .tl-v.bad')"))
        await page.shot(os.path.join(out, "home-battery-low-320.png"))
        await battery(page, "ac:100")
        verdict("plugged in: the plug and «от сети», no per cent", await page.until(
            "!!document.querySelector('.where .tl-power .ic-plug')") and "от сети" in (await page.js(POWER) or "")
            and "%" not in (await page.js(POWER) or ""), await page.js(POWER))
        verdict("320 px: nothing cut on the strip (plugged in)", await page.js(FITS))
        await page.shot(os.path.join(out, "home-plugged-320.png"))
        await battery(page, "none")
        verdict("no battery (a server, a desktop): no power column", await page.until(
            "!document.querySelector('.where .tl-power') && !!document.querySelector('.where .tl-mem')"))
        await battery(page, "batt:76")
        await page.until("!!document.querySelector('.where .tl-power .ic-battery')")
        await page.tap("document.querySelector('.where .top-load')")
        verdict("the machine's tile opens its tab, named after it", await page.until(TAB + " === 'MacBook Pro'"), await page.js(TAB))
        card = "(document.querySelector('.lim.pw') || {}).textContent || ''"
        verdict("the power card: the charge, the estimate, cycles and capacity", await page.until(
            card + ".includes('76 %') && " + card + ".includes('осталось ~4 ч 18 мин')"
            " && " + card + ".includes('аккумулятор: 143 цикла · ёмкость 94 % от новой')"), await page.js(card))
        await page.shot(os.path.join(out, "resources-machine-320.png"))
        await home(page)
        await page.tap("document.querySelector('.where .top-lim')")
        verdict("the limit's tile opens Limits", await page.until(TAB + " === 'Лимиты'"), await page.js(TAB))
        await page.js("location.hash = '#/settings/parts'")
        row = "(document.querySelector('.mname') || {}).textContent || ''"
        verdict("Settings → Pult and its parts: this machine by the system's name", await page.until(
            row + ".includes('MacBook Pro') && " + row + ".includes('Имя из системы')"), await page.js(row))
        # the table of Pult's parts comes above the row a moment later and moves it: tap once it stands
        await page.until("!!document.querySelector('.parts-t')", tries=100)
        await asyncio.sleep(0.5)
        for _ in range(3):
            await page.tap("[...document.querySelectorAll('.mname button')].find((b) => b.textContent === 'Переименовать')")
            if await page.until("!!document.querySelector('.mname input')", tries=20):
                break
        verdict("«Переименовать» opens the name for editing", await page.js("!!document.querySelector('.mname input')"))
        await page.js("(() => { const i = document.querySelector('.mname input'); i.value = 'Студия';"
                      " i.dispatchEvent(new Event('input', {bubbles: true})); })()")
        await page.tap("[...document.querySelectorAll('.mname button')].find((b) => b.textContent === 'Сохранить')")
        verdict("renamed: the owner's name and the system's under it", await page.until(
            row + ".includes('Студия') && " + row + ".includes('из системы — MacBook Pro')"), await page.js(row))
        await page.shot(os.path.join(out, "settings-machine-320.png"))
        await page.js("location.hash = '#/usage'")
        verdict("the machine's tab has the new name", await page.until(
            "[...document.querySelectorAll('.subtabs button')].some((b) => b.textContent === 'Студия')"))
        await page.js("healthConn.conn.ready = false; healthConn.conn.state = 'nomac'; healthConn.emit('conn')")
        verdict("offline: the banner names the machine", await page.until(
            "(document.querySelector('.banner.nomac') || {}).textContent?.includes('Студия не на связи')"))
        await page.shot(os.path.join(out, "banner-machine-320.png"))
        await page.js("healthConn.api('prefs', {machine: ''})")
        verdict("no script errors", not page.errors, page.errors)
    for width in (360, 412):                            # one line from 360 px, the owner's phone is 412
        async with _cdp.Page(width=width) as page:
            await page.open(urls["HOME"])
            await page.until("!!document.querySelector('.where .top-load')")
            await page.js("(async () => { window.healthConn = await import('/pult/static/core/conn.js'); })()")
            verdict("%d px: one line, nothing cut (on the battery)" % width, await page.js(FITS) and await page.js(ONE_ROW))
            await page.shot(os.path.join(out, "home-battery-%d.png" % width))
            await battery(page, "ac:100")
            await page.until("!!document.querySelector('.where .tl-power .ic-plug')")
            verdict("%d px: one line, nothing cut (plugged in)" % width, await page.js(FITS) and await page.js(ONE_ROW))
            await page.shot(os.path.join(out, "home-plugged-%d.png" % width))
            await battery(page, "batt:76")
            verdict("no script errors at %d px" % width, not page.errors, page.errors)
    async with _cdp.Page(width=412) as page:            # the pictures at a common phone's width
        await page.open(urls["HOME"])
        await page.until("!!document.querySelector('.where .top-load')")
        await page.tap("document.querySelector('.where .top-load')")
        await page.until("!!document.querySelector('.lim.pw')")
        await page.shot(os.path.join(out, "resources-machine-412.png"))
        verdict("no script errors at 412 px", not page.errors, page.errors)
    print("screenshots:", out)
    return 1 if verdict.failures else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
