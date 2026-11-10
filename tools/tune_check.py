"""A model's settings (stage M, step 6.5; Q170 (a), Q171 — all), in headless Chrome over DevTools, on the stand's stand-in
server: Resources → Local model → a model → «Настройки модели»: its system prompt from the model, the context lengths with
the card each takes (counted by the model's make), the card's room, the temperature, the fine tuning folded, «Все»
tools only from 64K; the owner's changes counted on «Сохранить · N», saved into the model — the list knows the new
context — and «Вернуть как было до Пульта» brings it back, the tools «Все» back to the five with 32K; a model without a
context takes one here and comes ticked; light and dark, 412 and 320 px.
  STAND_LOCAL=on STAND_LOCAL_MANY=1 STAND_LOCAL_SRV=1 STAND_HOMES=1 STAND_LANG=ru STAND_PORT=18183 HOLD=300 \\
    ~/.local/share/pult/venv/bin/python tools/stand.py > /tmp/stand.out &
  ~/.local/share/pult/venv/bin/python tools/tune_check.py /tmp/stand.out [out_dir]
Screenshots go to out_dir (a temporary folder by default). Exit 1 on a failed check."""
import asyncio
import os
import sys
import tempfile

import _cdp

STAND = sys.argv[1]
URLS = _cdp.stand_urls(STAND, ("USAGE",))
OUT = sys.argv[2] if len(sys.argv) > 2 else tempfile.mkdtemp(prefix="pult-tune-")
os.makedirs(OUT, exist_ok=True)
verdict = _cdp.Verdicts()
DARK = [{"name": "prefers-color-scheme", "value": "dark"}]
TAB = "[...document.querySelectorAll('.subtabs button')].find((b) => b.textContent === 'Своя модель')"
NAME = "[...document.querySelectorAll('.lp-nm')].find((b) => b.querySelector('b').textContent === %r)"
CTX = "[...document.querySelectorAll('.lm-ctx')].find((b) => b.querySelector('b').textContent === %r)"
SEG = "[...document.querySelectorAll('.lm .seg button')].find((b) => b.textContent === %r)"
NB = "\u00a0"


def journal():
    with open(STAND, encoding="utf-8", errors="replace") as f:
        return f.read()


async def said(pg):
    return await pg.js("window.__said.at(-1)") or ["", ""]


async def settings(pg, model):
    """The panel, the model's sheet, its settings."""
    await pg.js("location.hash = '#/usage'")
    await pg.until("!!" + TAB, 100)
    await pg.tap(TAB, wait=0.5)
    await pg.until("!!document.querySelector('.lp .lp-fam')", 100)
    await pg.tap(NAME % model, wait=0.5)
    await pg.tap("document.querySelector('.lm-in')", wait=0.6)
    return await pg.until("!!document.querySelector('.lm .lm-ctxs') && document.querySelector('.lm-t').textContent === %r" % model, 100)


async def flow(pg):
    await pg.open(URLS["USAGE"])
    verdict("Resources: «Своя модель»", await pg.until("!!" + TAB, 150))
    await pg.js(_cdp.SPY)
    await pg.tap(TAB, wait=0.5)
    await pg.until("!!document.querySelector('.lp .lp-fam')", 100)
    await pg.tap(NAME % "gemma4-32k", wait=0.5)
    row = await pg.js("(document.querySelector('.lm-in') || {}).innerText || ''")
    verdict("the model's sheet: «Настройки модели — промпт, контекст, температура»", "Настройки модели" in row and "промпт, контекст, температура" in row, row)
    await pg.shot(os.path.join(OUT, "sheet.png"))
    await pg.tap("document.querySelector('.lm-in')", wait=0.6)
    verdict("… a tap: its settings on a page of their own", await pg.until(
        "location.hash === '#/lm/gemma4-32k' && !!document.querySelector('.lm .lm-ctxs')", 100), await pg.js("location.hash"))
    sub = await pg.js("document.querySelector('.lm-sub').textContent")
    verdict("«на homelab · 8 ГБ · 11,9 млрд»", sub == "на homelab · 8" + NB + "ГБ · 11,9 млрд", sub)
    sysp = await pg.js("[document.querySelector('.lm-sys').value, document.querySelector('.lm-n').textContent]")
    verdict("the system prompt — the model's own, «127 / 4000»", sysp[0].startswith("Отвечай по-русски, коротко и по делу.") and sysp[1] == "127" + NB + "/" + NB + "4000", sysp)
    ctxs = await pg.js("[...document.querySelectorAll('.lm-ctx')].map((b) => [b.querySelector('b').textContent, b.querySelector('span').textContent, b.classList.contains('on')])")
    verdict("the contexts 16–256K with the card each takes; 32K is the model's: ≈ 9,5 ГБ, as the measure", [c[0] for c in ctxs] == [
        "16 тыс.", "32 тыс.", "64 тыс.", "128 тыс.", "256 тыс."] and ctxs[1] == ["32 тыс.", "≈" + NB + "9,5" + NB + "ГБ", True], ctxs)
    note = await pg.js("document.querySelector('.lm-ctxs').nextElementSibling.textContent")
    verdict("… «Модели на ней доступно 15 ГБ»", note.endswith("Модели на ней доступно 15" + NB + "ГБ."), note)
    temp = await pg.js("[document.querySelector('.lm-val').textContent, document.querySelector('.lm-fine-h').innerText]")
    verdict("the temperature 1; the fine tuning folded into one line", temp[0] == "1" and "top_k 64 · top_p 0,95 · min_p 0" in temp[1], temp)
    tools = await pg.js("[(%s).classList.contains('on'), (%s).disabled, document.querySelectorAll('.lm .lm-note')[1].textContent]" % (SEG % "5 основных", SEG % "Все"))
    verdict("tools: the five; «Все» off with 32K — «Все — при контексте от 64 тыс.»", tools[0] and tools[1] and tools[2].startswith("Все — при контексте от 64 тыс."), tools)
    verdict("«Сохранить» off: nothing changed", await pg.js("document.querySelector('.lm-save').disabled"))
    await pg.js("window.scrollTo(0, 0)")
    await pg.shot(os.path.join(OUT, "tune.png"))
    await pg.tap("document.querySelector('.lm-fine-h')", wait=0.4)
    rows = await pg.js("[...document.querySelectorAll('.lm-p')].map((r) => [r.querySelector('b').textContent, r.querySelector('input').value, r.classList.contains('def')])")
    verdict("the fine tuning open: five, the ones the Modelfile doesn't set — grey", rows == [
        ["top_k", "64", False], ["top_p", "0,95", False], ["min_p", "0", True], ["repeat_penalty", "1", True], ["presence_penalty", "0", True]], rows)
    await pg.js("document.querySelector('.lm-h').scrollIntoView({block: 'start'})")
    await asyncio.sleep(0.3)
    await pg.shot(os.path.join(OUT, "tune-fine.png"))
    # the owner's changes: 64K, a cooler temperature, all the tools, the card freed after a turn
    await pg.tap(CTX % "64 тыс.", wait=0.3)
    await pg.js("(() => { const i = document.querySelector('.lm-range'); Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set.call(i, '0.6');"
                " i.dispatchEvent(new Event('input', {bubbles: true})); return true; })()")
    verdict("… 64K: «Все» on now", await pg.until("!(%s).disabled" % (SEG % "Все"), 20))
    await pg.tap(SEG % "Все", wait=0.2)
    await pg.tap(SEG % "Освобождать сразу", wait=0.2)
    btn = await pg.js("document.querySelector('.lm-save').textContent")
    verdict("«Сохранить · 4» counts the changes", btn == "Сохранить · 4", btn)
    await pg.js("document.querySelector('.lm-save').scrollIntoView({block: 'center'})")
    await asyncio.sleep(0.2)
    await pg.shot(os.path.join(OUT, "tune-edit.png"))
    await pg.tap("document.querySelector('.lm-save')", wait=0.3)
    verdict("saved: «Сохранено в gemma4-32k: новые задачи — с этими настройками…»", await pg.until(
        "(window.__said.at(-1) || [])[1] && window.__said.at(-1)[1].startsWith('Сохранено в gemma4-32k: новые задачи')", 60), await said(pg))
    verdict("… the journal: into the model, the temperature and the context", "local model: gemma4-32k — settings saved in the model: temperature 0.6, num_ctx 65536"
            in journal(), journal()[-400:])
    after = await pg.js("[document.querySelector('.lm-save').disabled, !!document.querySelector('.lm-was'), (%s).classList.contains('on'),"
                        " (%s).classList.contains('on'), (%s).classList.contains('on')]" % (CTX % "64 тыс.", SEG % "Все", SEG % "Освобождать сразу"))
    verdict("… as saved: 64K, «Все», «Освобождать сразу»; «Вернуть как было до Пульта» there", after == [True, True, True, True, True], after)
    await pg.js("document.querySelector('.lm-was').scrollIntoView({block: 'center'})")
    await asyncio.sleep(0.2)
    await pg.shot(os.path.join(OUT, "tune-saved.png"))
    await pg.cmd("Emulation.setEmulatedMedia", features=DARK)
    await pg.js("window.scrollTo(0, 0)")
    await asyncio.sleep(0.3)
    await pg.shot(os.path.join(OUT, "tune-dark.png"))
    await pg.cmd("Emulation.setEmulatedMedia", features=[])
    # back: the panel knows the new context
    await pg.js("history.back()")
    verdict("Back: the panel — gemma4-32k now «64 тыс.»", await pg.until(
        "!!(%s) && (%s).querySelector('.dim').textContent.startsWith('64 тыс.')" % (NAME % "gemma4-32k", NAME % "gemma4-32k"), 100))
    # back as it was
    verdict("its settings again", await settings(pg, "gemma4-32k"))
    await pg.js("window.__yes = true")
    await pg.tap("document.querySelector('.lm-was')", wait=0.3)
    q = (await pg.js("window.__said.filter((x) => x[0] === 'confirm').at(-1)") or ["", ""])[1]
    verdict("«Вернуть как было до Пульта» asks first", q.startswith("Вернуть gemma4-32k как была до первой правки в Пульте?"), q)
    verdict("… «gemma4-32k — снова как была до правок в Пульте.»", await pg.until(
        "(window.__said.at(-1) || [])[1] === 'gemma4-32k — снова как была до правок в Пульте.'", 60), await said(pg))
    back = await pg.js("[(%s).classList.contains('on'), document.querySelector('.lm-val').textContent, (%s).classList.contains('on'), !!document.querySelector('.lm-was')]"
                       % (CTX % "32 тыс.", SEG % "5 основных"))
    verdict("… 32K and the temperature 1 again, the five tools (all need 64K), nothing to go back to", back == [True, "1", True, False], back)
    verdict("… the journal says so", "local model: gemma4-32k is back as it was before Pult changed it" in journal(), journal()[-300:])
    # a model without a context: it takes one here, and comes ticked
    verdict("qwen3.5:4b's settings", await settings(pg, "qwen3.5:4b"))
    note = await pg.js("document.querySelector('.lm-ctxs').nextElementSibling.textContent")
    verdict("«Не задана — задачи модель не берёт. Выбери длину — и возьмёт.»", note == "Не задана — задачи модель не берёт. Выбери длину — и возьмёт.", note)
    await pg.tap(CTX % "32 тыс.", wait=0.2)
    await pg.tap("document.querySelector('.lm-save')", wait=0.3)
    await pg.until("(window.__said.at(-1) || [])[1] && window.__said.at(-1)[1].startsWith('Сохранено в qwen3.5:4b')", 60)
    await pg.js("history.back()")
    verdict("… the panel: qwen3.5:4b with 32K, ticked", await pg.until(
        "!!(%s) && (%s).closest('.lp-row').classList.contains('on') && (%s).querySelector('.dim').textContent.startsWith('32 тыс.')"
        % (NAME % "qwen3.5:4b", NAME % "qwen3.5:4b", NAME % "qwen3.5:4b"), 100))
    # a phone of 320 px: nothing past the edge
    await pg.cmd("Emulation.setDeviceMetricsOverride", width=320, height=740, deviceScaleFactor=2, mobile=True)
    verdict("320 px: the settings fit", await settings(pg, "gemma4-32k"))
    wide = await pg.js("[document.documentElement.scrollWidth, innerWidth]")
    verdict("… no line past the edge", wide[0] <= wide[1], wide)
    await pg.shot(os.path.join(OUT, "tune-320.png"))


async def main():
    async with _cdp.Page() as pg:
        await flow(pg)
        verdict("no script errors on the page", not pg.errors, pg.errors)
    print("screenshots:", OUT)
    sys.exit(verdict.code())


asyncio.run(main())
