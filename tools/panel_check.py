"""One's own model's panel (stage M, step 6.4; Q165–Q168), in headless Chrome over DevTools, on the stand's stand-in
server and the reader beside it. Resources gets a third tab, «Своя модель»: the server's line (homelab, Ollama 0.40.14);
the disk — C:, 150 GB free of 2 TB, the models 17.9 GB — and the room for new ones with 60 GB kept; the card — 0.6 of
16 GB, nothing in memory; the models by their weights — a base with its size, its copy with a context under it «+0 ГБ»,
the ticks and the star; a model's sheet says what removing it gives back — 0 for a base whose copy holds the weights;
qwen3.5:4b removed — 3.3 GB back; a download — the look (its size, the room after it, the card), then its progress in
the panel and on Home, «Остановить», and a finished one in the list with «Сделать копию с 32 тыс.»; a download that
would leave less than 60 GB has no button. Settings' card is a line with the way in. busy — gemma4-32k in memory: the
card splits the others' share and the model's, «Выгрузить» frees it. Light and dark.
  STAND_LOCAL=on STAND_LOCAL_MANY=1 STAND_LOCAL_SRV=1 STAND_PULL_S=0.1 STAND_HOMES=1 STAND_LANG=ru STAND_PORT=18173 HOLD=300 \\
    ~/.local/share/pult/venv/bin/python tools/stand.py > /tmp/stand.out &
  ~/.local/share/pult/venv/bin/python tools/panel_check.py /tmp/stand.out [out_dir]
  (STAND_LOCAL_SRV=busy: tools/panel_check.py /tmp/stand.out busy [out_dir])
Screenshots go to out_dir (a temporary folder by default). Exit 1 on a failed check."""
import asyncio
import os
import sys
import tempfile

import _cdp

STAND = sys.argv[1]
BUSY = len(sys.argv) > 2 and sys.argv[2] == "busy"
rest = sys.argv[3:] if BUSY else sys.argv[2:]
URLS = _cdp.stand_urls(STAND, ("USAGE",))
OUT = rest[0] if rest else tempfile.mkdtemp(prefix="pult-panel-")
os.makedirs(OUT, exist_ok=True)
verdict = _cdp.Verdicts()
SPY = _cdp.SPY
DARK = [{"name": "prefers-color-scheme", "value": "dark"}]
TAB = "[...document.querySelectorAll('.subtabs button')].find((b) => b.textContent === 'Своя модель')"
FAMS = ("[...document.querySelectorAll('.lp-fam')].map((f) => [...f.querySelectorAll('.lp-row')].filter((r) => r.querySelector('b'))"
        ".map((r) => [r.querySelector('b').textContent, r.querySelector('.lp-sz').textContent, r.classList.contains('on'), !!r.querySelector('.mstar.on')]))")
NAME = "[...document.querySelectorAll('.lp-nm')].find((b) => b.querySelector('b').textContent === %r)"
TYPE = ("(() => { const i = document.querySelector('.lp .keyrow input'); const set = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set;"
        " set.call(i, %r); i.dispatchEvent(new Event('input', {bubbles: true})); return true; })()")
NB = " "


def journal():
    with open(STAND, encoding="utf-8", errors="replace") as f:
        return f.read()


async def said(pg):
    return await pg.js("window.__said.at(-1)") or ["", ""]


async def panel(pg):
    await pg.open(URLS["USAGE"])
    verdict("Resources: a third tab «Своя модель»", await pg.until("!!" + TAB, 150),
            await pg.js("[...document.querySelectorAll('.subtabs button')].map((b) => b.textContent)"))
    await pg.js(SPY)
    await pg.tap(TAB, wait=0.4)
    return await pg.until("!!document.querySelector('.lp .lp-fam')", 100)


async def flow(pg):
    verdict("… it opens the panel", await panel(pg))
    line = await pg.js("document.querySelector('.lp-srv .vl-at').textContent")
    verdict("the server's line: «homelab · Ollama 0.40.14 · проверено …»", line.startswith("homelab · Ollama 0.40.14 · проверено "), line)
    disk = await pg.js("[...document.querySelectorAll('.lp-card')][0].innerText")
    verdict("the disk: C:, 150 GB free, the rest 1.9 TB, the models 17.9 GB, of 2 TB", all(x in disk for x in (
        "Диск C:", "свободно 150" + NB + "ГБ", "прочее 1,9" + NB + "ТБ", "модели 17,9" + NB + "ГБ", "из 2" + NB + "ТБ")), disk)
    verdict("… the room for new models: about 90 GB, 60 GB kept free", "Под новые модели — ещё около 90" + NB + "ГБ: 60" + NB + "ГБ держим свободными." in disk, disk)
    card = await pg.js("[...document.querySelectorAll('.lp-card')][1].innerText")
    verdict("the card: 0.6 of 16 GB taken — other programs; nothing in memory", "занято 0,6" + NB + "ГБ из 16" + NB + "ГБ" in card
            and "другие программы 0,6" + NB + "ГБ" in card and "Моделей в памяти нет" in card, card)
    head = await pg.js("document.querySelector('.lp-mh').textContent")
    verdict("«Модели на homelab» — 17.9 GB on the disk, not ollama list's 32.5", head == "Модели на homelab17,9" + NB + "ГБ", head)
    fams = await pg.js(FAMS)
    verdict("the models by their weights: a base with its size, its copy under it «+0 ГБ», ticked; the star on qwen9b-32k", fams == [
        [["gemma4:12b", "8" + NB + "ГБ", False, False], ["gemma4-32k", "+0 ГБ", True, False]],
        [["qwen3.5:9b", "6,6" + NB + "ГБ", False, False], ["qwen9b-32k", "+0 ГБ", True, True]],
        [["qwen3.5:4b", "3,3" + NB + "ГБ", False, False]]], fams)
    verdict("… qwen3.5:4b, without a copy, has «Сделать копию с 32 тыс.» in the list",
            (await pg.js("(document.querySelector('.lp-mk .mmake') || {}).textContent || ''")).strip() == "Сделать копию с 32 тыс.")
    await pg.shot(os.path.join(OUT, "panel.png"))
    await pg.cmd("Emulation.setEmulatedMedia", features=DARK)
    await asyncio.sleep(0.3)
    await pg.shot(os.path.join(OUT, "panel-dark.png"))
    await pg.cmd("Emulation.setEmulatedMedia", features=[])
    # a model's sheet: what removing it gives back
    await pg.tap(NAME % "gemma4:12b", wait=0.5)
    sheet = await pg.js("document.querySelector('.lp-sheet').innerText")
    verdict("gemma4:12b's sheet: its weights shared with gemma4-32k — «Удалить — освободит 0 ГБ»", "Веса общие с gemma4-32k" in sheet
            and "Удалить — освободит 0" + NB + "ГБ" in sheet, sheet)
    await pg.shot(os.path.join(OUT, "sheet-shared.png"))
    await pg.tap("document.querySelector('.lp-sheet .x')", wait=0.5)
    verdict("… ✕ closes it", not await pg.js("!!document.querySelector('.lp-sheet')"))
    await pg.tap(NAME % "qwen3.5:4b", wait=0.5)
    sheet = await pg.js("document.querySelector('.lp-sheet').innerText")
    verdict("qwen3.5:4b's: its own weights — 3.3 GB back; «Сделать копию» there too", "Веса только её: удаление освободит 3,3" + NB + "ГБ" in sheet
            and "Сделать копию с 32 тыс." in sheet, sheet)
    await pg.js("window.__yes = true")
    await pg.tap("document.querySelector('.lp-sheet .btn.danger')", wait=0.3)
    verdict("«Удалить» asks first, says what comes back", (await pg.js("window.__said.find((x) => x[0] === 'confirm')") or ["", ""])[1].startswith(
        "Удалить qwen3.5:4b с homelab? Освободится 3,3" + NB + "ГБ."), await pg.js("window.__said"))
    verdict("… removed: «на диске освободилось 3,3 ГБ», its family gone", await pg.until(
        "window.__said.some((x) => x[1] === 'qwen3.5:4b удалена — на диске освободилось 3,3 ГБ.') && document.querySelectorAll('.lp-fam').length === 2", 60),
        await pg.js("window.__said"))
    verdict("… the computer's journal says so", "local model: qwen3.5:4b removed from the server" in journal(), journal()[-300:])
    # a download: the look, the progress — here and on Home — «Остановить»; then one to the end
    await pg.js(TYPE % "qwen3.5:14b")
    await pg.tap("document.querySelector('.lp .keyrow .btn')", wait=0.2)
    verdict("«Проверить»: its size, the room after it, the card — it fits", await pg.until("!!document.querySelector('.lp-look')", 50))
    look = await pg.js("document.querySelector('.lp-look').innerText")
    verdict("… «qwen3.5:14b — 9,1 ГБ», «останется 140 ГБ», «около 10 ГБ видеопамяти из 16 ГБ — влезет»", "qwen3.5:14b — 9,1" + NB + "ГБ" in look
            and "После — на диске останется 140" + NB + "ГБ." in look and "займёт около 10" + NB + "ГБ видеопамяти из 16" + NB + "ГБ — влезет" in look, look)
    await pg.shot(os.path.join(OUT, "pull-look.png"))
    await pg.tap("document.querySelector('.lp-look .btn')", wait=0.6)
    verdict("«Скачать»: its progress in the panel, «Остановить»", await pg.until("!!document.querySelector('.lp-pull')", 50))
    await pg.js("document.querySelector('.lp-pull').scrollIntoView({block: 'center'})")
    await pg.shot(os.path.join(OUT, "pull-run.png"))
    verdict("… the journal: it downloads", "local model: qwen3.5:14b downloads to the server" in journal(), journal()[-300:])
    await pg.js("window.__yes = true")
    await pg.tap("document.querySelector('.lp-pull .btn')", wait=0.3)
    verdict("«Остановить» asks, stops: «… продолжит с того же места»", await pg.until(
        "!document.querySelector('.lp-pull') && [...document.querySelectorAll('.lp-note')].some((n) => n.textContent.startsWith('Скачивание qwen3.5:14b остановлено'))", 60))
    verdict("… the journal: stopped by the owner", "the download of qwen3.5:14b stopped by the owner" in journal(), journal()[-300:])
    await pg.js(TYPE % "qwen3.5:14b")
    await pg.tap("document.querySelector('.lp .keyrow .btn')", wait=0.2)
    await pg.until("!!document.querySelector('.lp-look .btn')", 50)
    await pg.tap("document.querySelector('.lp-look .btn')", wait=0.3)
    # Home's line while it runs (STAND_PULL_S=0.1: three seconds)
    await pg.js("location.hash = '#/'")
    seen = await pg.until("!!document.querySelector('.lp-home') && document.querySelector('.lp-home b').textContent.startsWith('Скачивается qwen3.5:14b — ')", 30)
    if seen:
        await pg.shot(os.path.join(OUT, "home-pull.png"))
    verdict("Home: «Скачивается qwen3.5:14b — N %» while it runs", seen)
    verdict("… then «qwen3.5:14b скачана», a tap — the panel", await pg.until(
        "!!document.querySelector('.lp-home') && document.querySelector('.lp-home b').textContent === 'qwen3.5:14b скачана'", 100))
    await pg.tap("document.querySelector('.lp-home')", wait=0.6)
    verdict("… the panel on its own page: «Своя модель», the new model with «Сделать копию с 32 тыс.»", await pg.until(
        "location.hash === '#/local' && !!document.querySelector('h2') && document.querySelector('h2').textContent === 'Своя модель'"
        " && [...document.querySelectorAll('.lp-fam')].some((f) => f.querySelector('b').textContent === 'qwen3.5:14b' && !!f.querySelector('.mmake'))", 60))
    # no room: 60 GB stay free — a model that would leave less has no button
    await pg.js(SPY)
    await pg.js(TYPE % "qwen3.5:122b")
    await pg.tap("document.querySelector('.lp .keyrow .btn')", wait=0.2)
    await pg.until("!!document.querySelector('.lp-look')", 50)
    look = await pg.js("[document.querySelector('.lp-look').innerText, document.querySelector('.lp-look .btn').disabled]")
    verdict("a model that leaves less than 60 GB: «сначала убери модель», the button off", "держим 60" + NB + "ГБ — сначала убери модель" in look[0] and look[1], look)
    # Settings' card: a line with the way in
    await pg.js("location.hash = '#/settings/models'")
    card = "[...document.querySelectorAll('.item.vend')].find((x) => x.querySelector('b').textContent === 'Своя модель')"
    verdict("Settings: «Своя модель — включена», «Основная — qwen9b-32k, ещё 1 в выборе задачи.», «Модели, диск и видеокарта»", await pg.until(
        "!!(%s) && (%s).querySelector('.vl-sum').textContent === 'Основная — qwen9b-32k, ещё 1 в выборе задачи.'"
        " && (%s).querySelector('.vl-open').textContent === 'Модели, диск и видеокарта'" % (card, card, card), 150))
    await pg.js("(%s).scrollIntoView({block: 'center'})" % card)
    await asyncio.sleep(0.3)
    await pg.shot(os.path.join(OUT, "settings-card.png"))


async def busy_flow(pg):
    verdict("the panel opens", await panel(pg))
    card = await pg.js("[...document.querySelectorAll('.lp-card')][1].innerText")
    verdict("the card: 10 of 16 GB — other programs 0.6, gemma4-32k ≈ 9.6; it unloads by itself at …", "занято 10" + NB + "ГБ из 16" + NB + "ГБ" in card
            and "другие программы 0,6" + NB + "ГБ" in card and "gemma4-32k ≈" + NB + "9,6" + NB + "ГБ" in card
            and "gemma4-32k в памяти — выгрузится в " in card, card)
    verdict("… its row says «в памяти»", "в памяти" in await pg.js("(%s).closest('.lp-row').innerText" % (NAME % "gemma4-32k")))
    await pg.shot(os.path.join(OUT, "busy.png"))
    await pg.tap("document.querySelector('.lp-mem .btn')", wait=0.6)
    s = await said(pg)
    verdict("«Выгрузить»: «gemma4-32k выгружена из видеопамяти.»", s[1] == "gemma4-32k выгружена из видеопамяти.", s)
    verdict("… nothing in memory now", await pg.until("[...document.querySelectorAll('.lp-card')][1].innerText.includes('Моделей в памяти нет')", 50))
    verdict("… the journal says so", "local model: gemma4-32k unloaded from the card" in journal(), journal()[-300:])


async def main():
    async with _cdp.Page() as pg:
        await (busy_flow(pg) if BUSY else flow(pg))
        verdict("no script errors on the page", not pg.errors, pg.errors)
    print("screenshots:", OUT)
    sys.exit(verdict.code())


asyncio.run(main())
