"""ComfyUI's models (stage M, step 6.7; Q188), in headless Chrome over DevTools, on the stand's stand-in gateway beside
ComfyUI (tools/stand.py, STAND_COMFY). Resources gets a fourth tab, «ComfyUI», all four in a phone's width: the server's
line (homelab · ComfyUI 0.44.0 · выключен); the disk — C:, 141 GB free, Ollama 17.9, ComfyUI 18.3, other models 8.7, all
models 44.9 of the cap 65, 60 GB kept; the card — ComfyUI off, starts by itself; the sets — Pictures: Z-Image-Turbo on the
disk with its star, FLUX.2 klein 4B «+4,4 ГБ»; Music: ACE-Step 1.5 Turbo «+10 ГБ». ACE-Step's card: what comes, the disk
after it, all models after it, the card — it ran on the owner's server, no «не запускалась»; «Скачать 10 ГБ» — the progress in the tab and on Home, then
«на сервере», the star its own; «Попробовать» — «Делаю…», a tune in a player, its time; Z-Image's — a picture; ComfyUI
running — «Освободить видеопамять», «Выключить ComfyUI»; FLUX.2 klein downloaded and made the main one, then removed — the
shared encoder stays; a download stopped. full — past the cap: FLUX's card and the local model's download say so, no
button. old — the first gateway: the tab says to install the new one. down — no tab. run — a download the computer
picked up after a restart: on Home at once. Light and dark.
  STAND_LOCAL=on STAND_LOCAL_MANY=1 STAND_LOCAL_SRV=1 STAND_COMFY=1 STAND_PULL_S=0.1 STAND_LANG=ru STAND_PORT=18181 HOLD=300 \\
    ~/.local/share/pult/venv/bin/python tools/stand.py > /tmp/stand.out &
  ~/.local/share/pult/venv/bin/python tools/comfy_check.py /tmp/stand.out [full|old|down|run] [out_dir]
Screenshots go to out_dir (a temporary folder by default). Exit 1 on a failed check."""
import asyncio
import os
import sys
import tempfile

import _cdp

STAND = sys.argv[1]
MODE = sys.argv[2] if len(sys.argv) > 2 and sys.argv[2] in ("full", "old", "down", "run") else "main"
rest = sys.argv[3:] if MODE != "main" else sys.argv[2:]
URLS = _cdp.stand_urls(STAND, ("USAGE", "HOME"))
OUT = rest[0] if rest else tempfile.mkdtemp(prefix="pult-comfy-")
os.makedirs(OUT, exist_ok=True)
verdict = _cdp.Verdicts()
SPY = _cdp.SPY
DARK = [{"name": "prefers-color-scheme", "value": "dark"}]
NB = "\u00a0"
TABS = "[...document.querySelectorAll('.subtabs button')].map((b) => b.textContent)"
TAB = "[...document.querySelectorAll('.subtabs button')].find((b) => b.textContent === 'ComfyUI')"
ROWS = ("[...document.querySelectorAll('.cf .lp-row')].map((r) => [r.querySelector('b').textContent, r.querySelector('.lp-sz').textContent,"
        " !!r.querySelector('.mstar.on'), r.querySelector('.lp-nm .dim').textContent])")
NAME = "[...document.querySelectorAll('.cf .lp-nm')].find((b) => b.querySelector('b').textContent === %r)"
SHEET = "(document.querySelector('.cf-sheet') || {}).innerText || ''"
BTN = "[...document.querySelectorAll('.cf-sheet .btn')].find((b) => b.textContent.trim().startsWith(%r))"
CARDBTN = "[...document.querySelectorAll('.cf .lp-card .btn')].find((b) => b.textContent.trim() === %r)"


def journal():
    with open(STAND, encoding="utf-8", errors="replace") as f:
        return f.read()


async def said(pg, text, tries=60):
    return await pg.until("window.__said.some((x) => x[1] === %r)" % text, tries)


async def tab(pg):
    await pg.open(URLS["USAGE"])
    ok = await pg.until("!!" + TAB, 150)
    verdict("Resources: a fourth tab «ComfyUI»", ok, await pg.js(TABS))
    if not ok:
        return False
    await pg.js(SPY)
    await pg.tap(TAB, wait=0.4)
    return await pg.until("!!document.querySelector('.cf')", 100)


async def sheet(pg, name):
    await pg.tap(NAME % name, wait=0.5)
    return await pg.until("(%s).includes(%r)" % (SHEET, name), 30)


async def close(pg):
    await pg.tap("document.querySelector('.cf-sheet .x')", wait=0.5)


async def flow(pg):
    verdict("… it opens the list", await tab(pg) and await pg.until("!!document.querySelector('.cf .lp-fam')", 100))
    fit = await pg.js("(() => { const t = document.querySelector('.subtabs'); return [t.scrollWidth, t.clientWidth]; })()")
    verdict("the four tabs fit a phone's width (412 px) — none hidden sideways", fit[0] <= fit[1], fit)
    line = await pg.js("document.querySelector('.cf .lp-srv .vl-at').textContent")
    verdict("the server's line: «homelab · ComfyUI 0.44.0 · выключен»", line == "homelab · ComfyUI 0.44.0 · выключен", line)
    disk = await pg.js("[...document.querySelectorAll('.cf .lp-card')][0].innerText")
    verdict("the disk: C:, 141 GB free; Ollama 17.9, ComfyUI 18.3, other models 8.7; all models 44.9 of the cap 65; 60 kept",
            all(x in disk for x in ("Диск C:", "свободно 141" + NB + "ГБ", "Ollama 17,9" + NB + "ГБ", "ComfyUI 18,3" + NB + "ГБ",
                                    "другие модели 8,7" + NB + "ГБ", "Все модели: 44,9" + NB + "ГБ из 65" + NB + "ГБ — потолок сервера.",
                                    "60" + NB + "ГБ диска держим свободными.")), disk)
    card = await pg.js("[...document.querySelectorAll('.cf .lp-card')][1].innerText")
    verdict("the card: 0.6 of 16 GB; ComfyUI off — it starts by itself, stops after 10 min", "занято 0,6" + NB + "ГБ из 16" + NB + "ГБ" in card
            and "ComfyUI выключен: включится сам с первой картинкой или песней и выключится через 10 мин тишины." in card, card)
    heads = await pg.js("[...document.querySelectorAll('.cf h3')].map((h) => h.textContent)")
    verdict("two parts: Pictures, Music", heads == ["Картинки", "Музыка"], heads)
    rows = await pg.js(ROWS)
    verdict("the sets: Z-Image on the disk with its star; FLUX.2 klein «+4,4 ГБ»; ACE-Step «+10 ГБ»", [r[:3] for r in rows] == [
        ["Z-Image-Turbo", "18,3" + NB + "ГБ", True], ["FLUX.2 klein 4B", "+4,4" + NB + "ГБ", False], ["ACE-Step 1.5 Turbo", "+10" + NB + "ГБ", False]], rows)
    verdict("… what each is: «основная · 6 млрд · 9 шагов · Apache-2.0», «песни со словами, мелодии · 2 млрд · MIT»",
            rows[0][3] == "основная · 6 млрд · 9" + NB + "шагов · Apache-2.0" and rows[2][3] == "песни со словами, мелодии · 2 млрд · MIT", rows)
    await pg.shot(os.path.join(OUT, "tab.png"))
    await pg.cmd("Emulation.setEmulatedMedia", features=DARK)
    await asyncio.sleep(0.3)
    await pg.shot(os.path.join(OUT, "tab-dark.png"))
    await pg.cmd("Emulation.setEmulatedMedia", features=[])
    # ACE-Step's card: what comes, the room after it, the card, not run here yet
    verdict("ACE-Step's card opens", await sheet(pg, "ACE-Step 1.5 Turbo"))
    s = await pg.js(SHEET)
    verdict("… «Музыка · песни со словами, мелодии · 2 млрд · 50+ языков · MIT», «ACE Studio, StepFun · январь 2026»",
            "Музыка · песни со словами, мелодии · 2 млрд · 50+ языков · MIT" in s and "ACE Studio, StepFun · январь 2026" in s, s)
    verdict("… «Скачать: 10 ГБ — веса модели 4,8 ГБ, текстовые энкодеры 4,9 ГБ, VAE 0,3 ГБ»",
            "Скачать: 10" + NB + "ГБ — веса модели 4,8" + NB + "ГБ, текстовые энкодеры 4,9" + NB + "ГБ, VAE 0,3" + NB + "ГБ." in s, s)
    verdict("… the disk after it 131 GB, all models 54.9 of 65, the card ≈ 10 of 16 — it fits; it ran on the owner's server — no «не запускалась»",
            "После — на диске останется 131" + NB + "ГБ (держим 60" + NB + "ГБ)." in s and "Все модели вместе: 54,9" + NB + "ГБ из 65" + NB + "ГБ" in s
            and "Видеокарта: ≈ 10" + NB + "ГБ из 16" + NB + "ГБ — влезет." in s and "ещё не запускалась" not in s, s)
    await pg.shot(os.path.join(OUT, "sheet-ace.png"))
    await pg.tap(BTN % "Скачать 10", wait=0.3)
    verdict("«Скачать 10 ГБ»: the card closes, the progress in the tab", await pg.until(
        "!document.querySelector('.cf-sheet') && !!document.querySelector('.cf .lp-pull')", 60))
    verdict("… the journal: it downloads", "comfy: ace-step-1.5-turbo downloads to the server" in journal(), journal()[-300:])
    await pg.js("document.querySelector('.cf .lp-pull').scrollIntoView({block: 'center'})")
    await pg.shot(os.path.join(OUT, "pull-run.png"))
    await pg.js("location.hash = '#/'")
    seen = await pg.until("!!document.querySelector('.lp-home') && document.querySelector('.lp-home b').textContent.startsWith('Скачивается ACE-Step 1.5 Turbo — ')", 40)
    if seen:
        await pg.shot(os.path.join(OUT, "home-pull.png"))
    verdict("Home: «Скачивается ACE-Step 1.5 Turbo — N %» while it runs", seen)
    verdict("… then «ACE-Step 1.5 Turbo на сервере», «Попробовать — в „Ресурсы → ComfyUI“»", await pg.until(
        "!!document.querySelector('.lp-home') && document.querySelector('.lp-home b').textContent === 'ACE-Step 1.5 Turbo на сервере'"
        " && document.querySelector('.lp-home .dim').textContent === 'Попробовать — в «Ресурсы → ComfyUI»'", 150))
    await pg.tap("document.querySelector('.lp-home')", wait=0.6)
    verdict("… a tap — the tab on its own page, «ComfyUI»", await pg.until(
        "location.hash === '#/comfy' && !!document.querySelector('h2') && document.querySelector('h2').textContent === 'ComfyUI' && !!document.querySelector('.cf .lp-fam')", 60))
    await pg.js(SPY)
    rows = await pg.js(ROWS)
    verdict("ACE-Step is on the disk: 10 GB, its own star — the only music model", rows[2][:3] == ["ACE-Step 1.5 Turbo", "10" + NB + "ГБ", True]
            and rows[2][3].startswith("основная"), rows)
    verdict("… the end in the tab: «на сервере — „Попробовать“ в её карточке»", "ACE-Step 1.5 Turbo на сервере — «Попробовать» в её карточке." in
            await pg.js("(document.querySelector('.cf-end') || {}).textContent || ''"))
    # the trial tune
    await sheet(pg, "ACE-Step 1.5 Turbo")
    await pg.tap(BTN % "Попробовать", wait=0.2)
    verdict("«Попробовать — пробная мелодия»: «Делаю… 0:0N», ComfyUI starts first", await pg.until(
        "(%s).includes('Делаю… 0:0') && (%s).includes('Сначала запускается ComfyUI')" % (SHEET, SHEET), 40))
    await pg.shot(os.path.join(OUT, "try-run.png"))
    verdict("… a tune in a player, its time and seed", await pg.until(
        "!!document.querySelector('.cf-sheet audio') && document.querySelector('.cf-sheet audio').src.startsWith('blob:')", 100))
    s = await pg.js(SHEET)
    verdict("… «69,6 с на сервере · зерно 381 (из них запуск ComfyUI — 31 с)»",
            "69,6 с на сервере · зерно 381 (из них запуск ComfyUI — 31 с)" in s, s)
    dur = await pg.until("document.querySelector('.cf-sheet audio').duration > 19", 50)
    verdict("… the player has the whole tune: 20 s", dur, await pg.js("document.querySelector('.cf-sheet audio').duration"))
    await pg.shot(os.path.join(OUT, "try-audio.png"))
    verdict("… the journal: the trial and its time", "comfy: a trial audio on ace-step-1.5-turbo" in journal()
            and "comfy: the trial on ace-step-1.5-turbo came in 69.6 s" in journal(), journal()[-400:])
    await close(pg)
    # ComfyUI running now: the server's line, the card's buttons
    line = await pg.js("document.querySelector('.cf .lp-srv .vl-at').textContent")
    verdict("the server's line: «… работает, модели в видеопамяти»", line == "homelab · ComfyUI 0.44.0 · работает, модели в видеопамяти", line)
    # the trial picture
    await sheet(pg, "Z-Image-Turbo")
    s = await pg.js(SHEET)
    verdict("Z-Image's card: on the disk 18.3 GB; the encoder shared with FLUX.2 klein; the main one",
            "На диске — 18,3" + NB + "ГБ." in s and "Общее с FLUX.2 klein 4B: текстовый энкодер" in s
            and "Основная: картинку без выбранной модели рисует она." in s and "ещё не запускалась" not in s, s)
    await pg.tap(BTN % "Попробовать", wait=0.2)
    verdict("«Попробовать — пробная картинка»: a picture, 512 px", await pg.until(
        "!!document.querySelector('.cf-sheet img.cf-pic') && document.querySelector('.cf-sheet img.cf-pic').naturalWidth === 512", 100))
    verdict("… its time: «4,1 с на сервере» — ComfyUI was running", "4,1 с на сервере · зерно 381" in await pg.js(SHEET)
            and "запуск ComfyUI" not in await pg.js(SHEET))
    await pg.shot(os.path.join(OUT, "try-image.png"))
    await close(pg)
    verdict("the last trial is in its own card — the tab says so", "Последняя проба — Z-Image-Turbo" in await pg.js(
        "(document.querySelector('.cf-last') || {}).textContent || ''"))
    await pg.tap(CARDBTN % "Освободить видеопамять", wait=0.3)
    verdict("«Освободить видеопамять»: «ComfyUI освободил видеопамять.»", await said(pg, "ComfyUI освободил видеопамять."))
    await pg.js("window.__yes = true")
    await pg.tap(CARDBTN % "Выключить ComfyUI", wait=0.3)
    verdict("«Выключить ComfyUI» asks first, then «ComfyUI выключен — видеокарта свободна.»", await said(pg, "ComfyUI выключен — видеокарта свободна.")
            and (await pg.js("window.__said.find((x) => x[0] === 'confirm')") or ["", ""])[1] == "Выключить ComfyUI сейчас? Видеопамять освободится сразу.",
            await pg.js("window.__said"))
    verdict("… the line says «выключен» again", await pg.until(
        "document.querySelector('.cf .lp-srv .vl-at').textContent === 'homelab · ComfyUI 0.44.0 · выключен'", 40))
    # FLUX.2 klein: downloaded, made the main one, removed — the shared encoder stays with Z-Image
    await sheet(pg, "FLUX.2 klein 4B")
    s = await pg.js(SHEET)
    verdict("FLUX's card: «Скачать: 4,4 ГБ — веса модели 4,1 ГБ, VAE 0,3 ГБ», «Уже есть: текстовый энкодер», shared with Z-Image; «ещё не запускалась»",
            "Скачать: 4,4" + NB + "ГБ — веса модели 4,1" + NB + "ГБ, VAE 0,3" + NB + "ГБ." in s and "Уже есть: текстовый энкодер." in s
            and "Общее с Z-Image-Turbo: текстовый энкодер" in s and "На этом сервере ещё не запускалась" in s, s)
    await pg.tap(BTN % "Скачать 4,4", wait=0.3)
    verdict("… downloaded: «+4,4 ГБ» → 10 ГБ on the disk, the encoder counted in", await pg.until(
        "[...document.querySelectorAll('.cf .lp-row')].some((r) => r.querySelector('b').textContent === 'FLUX.2 klein 4B' && r.querySelector('.lp-sz').textContent === '10\\u00a0ГБ')", 150))
    await pg.tap("(%s).closest('.lp-row').querySelector('.mstar')" % (NAME % "FLUX.2 klein 4B"), wait=0.5)
    rows = await pg.js(ROWS)
    verdict("its star: FLUX.2 klein is the main picture model now, Z-Image's star off", await pg.until(
        "!!(%s).closest('.lp-row').querySelector('.mstar.on') && !(%s).closest('.lp-row').querySelector('.mstar.on')" % (NAME % "FLUX.2 klein 4B", NAME % "Z-Image-Turbo"), 40), rows)
    verdict("… the journal: the main one", "comfy: flux2-klein-4b is the main one of its kind" in journal(), journal()[-300:])
    await sheet(pg, "FLUX.2 klein 4B")
    await pg.js("window.__yes = true")
    await pg.tap(BTN % "Удалить", wait=0.3)
    verdict("«Удалить — освободит 4,4 ГБ» asks: «Удалить FLUX.2 klein 4B с homelab? Освободится 4,4 ГБ.»",
            (await pg.js("window.__said.find((x) => x[0] === 'confirm' && x[1].startsWith('Удалить FLUX'))") or ["", ""])[1].startswith(
                "Удалить FLUX.2 klein 4B с homelab? Освободится 4,4" + NB + "ГБ."), await pg.js("window.__said"))
    verdict("… removed: «Удалено — на диске освободилось 4,4 ГБ.», «+4,4 ГБ» again, Z-Image main again", await said(pg, "Удалено — на диске освободилось 4,4 ГБ.")
            and await pg.until("(%s).closest('.lp-row').querySelector('.lp-sz').textContent === '+4,4\\u00a0ГБ'"
                               " && !!(%s).closest('.lp-row').querySelector('.mstar.on')" % (NAME % "FLUX.2 klein 4B", NAME % "Z-Image-Turbo"), 40))
    # a download stopped
    await sheet(pg, "FLUX.2 klein 4B")
    await pg.tap(BTN % "Скачать 4,4", wait=0.3)
    await pg.until("!!document.querySelector('.cf .lp-pull .btn')", 40)
    await pg.js("window.__yes = true")
    await pg.tap("document.querySelector('.cf .lp-pull .btn')", wait=0.3)
    verdict("«Остановить» asks, stops: «Скачивание FLUX.2 klein 4B остановлено — …»", await pg.until(
        "!document.querySelector('.cf .lp-pull') && (document.querySelector('.cf-end') || {}).textContent === "
        "'Скачивание FLUX.2 klein 4B остановлено — следующее продолжит с того же места.'", 60))
    verdict("… the journal: stopped by the owner", "comfy: the download stopped by the owner" in journal(), journal()[-300:])


async def full_flow(pg):
    verdict("the tab opens", await tab(pg) and await pg.until("!!document.querySelector('.cf .lp-fam')", 100))
    verdict("FLUX's card opens", await sheet(pg, "FLUX.2 klein 4B"))
    s = await pg.js(SHEET)
    verdict("… past the cap: «заняли бы 65,6 ГБ — больше потолка сервера 65 ГБ», the button off",
            "Все модели вместе заняли бы 65,6" + NB + "ГБ — больше потолка сервера 65" + NB + "ГБ." in s
            and await pg.js("(%s).disabled" % (BTN % "Скачать")), s)
    await pg.shot(os.path.join(OUT, "full-flux.png"))
    await close(pg)
    # the local model's own download: the same cap
    await pg.tap("[...document.querySelectorAll('.subtabs button')].find((b) => b.textContent === 'Своя модель')", wait=0.5)
    await pg.until("!!document.querySelector('.lp .keyrow input')", 60)
    await pg.js("(() => { const i = document.querySelector('.lp .keyrow input'); const set = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set;"
                " set.call(i, 'qwen3.5:14b'); i.dispatchEvent(new Event('input', {bubbles: true})); })()")
    await pg.tap("document.querySelector('.lp .keyrow .btn')", wait=0.2)
    verdict("Local model's download: «заняли бы 70,3 ГБ — больше потолка сервера 65 ГБ», the button off", await pg.until(
        "!!document.querySelector('.lp-look') && document.querySelector('.lp-look').innerText.includes('Все модели вместе заняли бы 70,3\\u00a0ГБ — больше потолка сервера 65\\u00a0ГБ')"
        " && document.querySelector('.lp-look .btn').disabled", 60), await pg.js("(document.querySelector('.lp-look') || {}).innerText"))
    await pg.shot(os.path.join(OUT, "full-local.png"))


async def old_flow(pg):
    verdict("the tab opens", await tab(pg))
    text = await pg.js("document.querySelector('.cf').innerText")
    verdict("the first gateway: «рисует, но моделями не управляет», the command to install the new one",
            "На сервере первый шлюз: рисует, но моделями не управляет." in text
            and await pg.js("document.querySelector('.cf-cmd').textContent") == "sudo bash deploy/comfy-gate/install.sh --user ИМЯ --replace СТАРАЯ", text)
    await pg.shot(os.path.join(OUT, "old.png"))


async def down_flow(pg):
    await pg.open(URLS["USAGE"])
    await pg.until("!!document.querySelector('.subtabs button')", 100)
    await asyncio.sleep(2)
    verdict("nothing answers at the gateway's port: no tab", "ComfyUI" not in await pg.js(TABS), await pg.js(TABS))


async def run_flow(pg):
    await pg.open(URLS["HOME"])
    verdict("Home at once: «Скачивается ACE-Step 1.5 Turbo — N %» — the computer picked the download up", await pg.until(
        "!!document.querySelector('.lp-home') && /^Скачивается ACE-Step 1.5 Turbo — \\d+\\u00a0%$/.test(document.querySelector('.lp-home b').textContent)", 100),
        await pg.js("(document.querySelector('.lp-home') || {}).innerText"))
    verdict("… the journal: watching it again", "comfy: the gateway downloads ace-step-1.5-turbo — watching it again" in journal())
    await pg.shot(os.path.join(OUT, "run-home.png"))


async def main():
    async with _cdp.Page() as pg:
        await {"main": flow, "full": full_flow, "old": old_flow, "down": down_flow, "run": run_flow}[MODE](pg)
        verdict("no script errors on the page", not pg.errors, pg.errors)
    print("screenshots:", OUT)
    sys.exit(verdict.code())


asyncio.run(main())
