"""One's own model through Ollama (stage M, steps 6 and 7.2), in headless Chrome over DevTools, on the stand's stand-in
server. STAND_LOCAL=1 — off: a project's settings list "Local model" grey, a tap says where to turn it on; Settings → Other
vendors has its card — off, the address filled in — another computer's address is refused, a silent one says nothing
answers, the usual one finds Ollama 0.40.14: gemma4-32k fits (its 32K context), the two without a context set don't; it is
on: the card is a line with the way into the panel (stage M, step 6.4) — there its models by their weights: gemma4-32k
ticked and the main one under gemma4:12b; qwen3.5:4b gets "Make a copy with 32K", made by the stand-in server and ticked;
the star moves, a tick off stays off after "Check again"; the server's line opens the address's field; no reader beside
this Ollama — a line says so; "Turn off" there; the model of new projects can be it. The project's settings: its row says
"on your computer · gemma4-32k, free", a change to it asks where the code goes — it stays home — and takes; New task there
says so, the words under the form too, the task starts on it. "Turn off" turns it off, the project keeps it. Light and dark.
STAND_LOCAL=down — the shop is its project, on, but the server is silent: "Your move" names the model at the card's foot —
"Local · gemma4-32k" — and a new task on it isn't started: it says why, and nothing starts with Claude in its place (Q143);
Settings' own look at the server finds it silent: a line in the card, the model stays on; the panel says why and keeps the
list of the last check.
  STAND_LOCAL=1 STAND_HOMES=1 STAND_LANG=ru STAND_PORT=18172 HOLD=300 ~/.local/share/pult/venv/bin/python tools/stand.py > /tmp/stand.out &
  ~/.local/share/pult/venv/bin/python tools/local_check.py /tmp/stand.out [out_dir]
  (STAND_LOCAL=down: tools/local_check.py /tmp/stand.out down [out_dir])
Screenshots go to out_dir (a temporary folder by default). Exit 1 on a failed check."""
import asyncio
import json
import os
import sys
import tempfile

import _cdp

STAND = sys.argv[1]
DOWN = len(sys.argv) > 2 and sys.argv[2] == "down"
rest = sys.argv[3:] if DOWN else sys.argv[2:]
URLS = _cdp.stand_urls(STAND, ("NEW", "HOME"))
OUT = rest[0] if rest else tempfile.mkdtemp(prefix="pult-local-")
os.makedirs(OUT, exist_ok=True)
verdict = _cdp.Verdicts()
SPY = _cdp.SPY
FIELD = "(() => [...document.querySelectorAll('.form .field')].find((b) => b.previousElementSibling && b.previousElementSibling.textContent.trim() === %r))()"
OPT = "[...document.querySelectorAll('.card.pick .opt')].find((b) => b.textContent.trim().startsWith(%r))"
CARD = "[...document.querySelectorAll('.item.vend')].find((x) => x.querySelector('b').textContent === 'Своя модель')"
TYPE = ("(() => { const i = (%s).querySelector('.keyrow input'); const set = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set;"
        " set.call(i, %%r); i.dispatchEvent(new Event('input', {bubbles: true})); return true; })()" % CARD)
CHECK = "(%s).querySelector('.keyrow .btn')" % CARD
FAMS = ("[...document.querySelectorAll('.lp-fam')].map((f) => [...f.querySelectorAll('.lp-row')].filter((r) => r.querySelector('b'))"
        ".map((r) => [r.querySelector('b').textContent, r.querySelector('.lp-sz').textContent, r.classList.contains('on'), !!r.querySelector('.mstar.on')]))")
DARK = [{"name": "prefers-color-scheme", "value": "dark"}]


def journal():
    with open(STAND, encoding="utf-8", errors="replace") as f:
        return f.read()


async def said(pg):
    return await pg.js("window.__said.at(-1)") or ["", ""]


BLOG = "'-Users-x-blog'"
MODEL = "document.querySelector('.psets .ps-model')"


async def pick_shop(pg):
    await pg.tap(FIELD % "Проект")
    await pg.tap(OPT % "acme-shop", wait=0.6)


async def blog_settings(pg):
    await pg.js("location.hash = '#/ps/' + encodeURIComponent(%s)" % BLOG)
    await pg.until("!!" + MODEL, 150)
    await pg.js(SPY)


async def off_flow(pg):
    await pg.open(URLS["NEW"])
    await pg.until("!!" + FIELD % "Кто делает", 150)
    await blog_settings(pg)
    await pg.tap(MODEL, wait=0.6)
    row = await pg.js("(() => { const b = %s; return b ? [b.textContent.trim(), b.classList.contains('vo-off')] : null; })()" % (OPT % "Своя модель"))
    verdict("the project's models list «Своя модель», grey while it is off", bool(row) and row[1] and "выключена — включи в «Настройки → Модели и ключи»" in row[0], row)
    await pg.shot(os.path.join(OUT, "who-off.png"))
    await pg.tap(OPT % "Своя модель", wait=0.6)
    s = await said(pg)
    verdict("… a tap says where to turn it on", s[0] == "alert" and "«Настройки → Модели и ключи»" in s[1], s)
    await pg.tap("document.querySelector('.card.pick .x')", wait=0.4)

    # Settings → Other vendors → Local model
    await pg.js("location.hash = '#/settings/models'")
    verdict("Settings has the local model's card", await pg.until("!!(%s)" % CARD, 150))
    await pg.js(SPY)
    await pg.js("(%s).scrollIntoView({block: 'center'})" % CARD)
    await asyncio.sleep(0.3)
    st = await pg.js("[(%s).querySelector('.vend-st').textContent, (%s).querySelector('.keyrow input').value, (%s).textContent]" % (CARD, CARD, CHECK))
    verdict("… off, the usual address filled in, «Проверить и включить»", st == ["выключена", "http://127.0.0.1:11434", "Проверить и включить"], st)
    verdict("… no key field: it needs none", not await pg.js("!!(%s).querySelector('input[type=password]')" % CARD))
    whole = await pg.js("(() => { const i = (%s).querySelector('.keyrow input'); return i.scrollWidth <= i.clientWidth; })()" % CARD)
    verdict("… the address shows whole, the button under it", whole)
    await pg.shot(os.path.join(OUT, "settings-off.png"))
    await pg.js(TYPE % "http://10.20.10.5:11434")
    await pg.tap(CHECK, wait=1.0)
    s = await said(pg)
    verdict("another computer's address is refused", s[0] == "alert" and "Только адрес самого этого компьютера" in s[1], s)
    await pg.js(TYPE % "http://127.0.0.1:11500")
    await pg.tap(CHECK, wait=1.0)
    s = await said(pg)
    verdict("a silent address: nothing answers there", s[0] == "alert" and "никто не отвечает" in s[1] and "туннель" in s[1], s)
    await pg.js(TYPE % "http://127.0.0.1:11434")
    await pg.tap(CHECK, wait=1.0)
    s = await said(pg)
    verdict("the usual one: on — Ollama 0.40.14, one model fits, a task gets gemma4-32k with 32K",
            s[0] == "alert" and "Включена: Ollama 0.40.14" in s[1] and "подходящих моделей — 1" in s[1] and "gemma4-32k" in s[1] and "32K" in s[1], s)
    verdict("… the card says on", await pg.until("(%s).querySelector('.vend-st').textContent === 'включена'" % CARD, 30))
    # on, the card is a line with the way into the panel (stage M, step 6.4; Q165): the list, the copy, the star, the
    # address and «Выключить» live there — Resources → Local model, or #/local from here
    verdict("… the card: «Основная — gemma4-32k.» and «Модели, диск и видеокарта»", await pg.until(
        "!!(%s).querySelector('.vl-sum') && (%s).querySelector('.vl-sum').textContent === 'Основная — gemma4-32k.'"
        " && (%s).querySelector('.vl-open').textContent === 'Модели, диск и видеокарта'" % (CARD, CARD, CARD), 30))
    verdict("… the computer's journal says what it found", "vendor local: http://127.0.0.1:11434 — Ollama 0.40.14, models gemma4-32k (32768)" in journal(), journal()[-400:])
    await pg.js("(%s).scrollIntoView({block: 'center'})" % CARD)
    await asyncio.sleep(0.3)
    await pg.shot(os.path.join(OUT, "settings-on.png"))
    await pg.tap("(%s).querySelector('.vl-open')" % CARD, wait=0.6)
    verdict("… the way in opens the panel", await pg.until("location.hash === '#/local' && !!document.querySelector('.lp .lp-fam')", 60))
    await pg.js(SPY)
    line = await pg.js("document.querySelector('.lp-srv .vl-at').textContent")
    # no reader beside Ollama, so no name: Ollama itself — «сервер» is the app's server's word only (2026-11-12)
    verdict("the panel's line: «Ollama · 0.40.14 · проверено …», no address field", line.startswith("Ollama · 0.40.14 · проверено ")
            and not await pg.js("!!document.querySelector('.lp .keyrow input[inputmode=url]')"), line)
    noinfo = await pg.js("(document.querySelector('.lp-noinfo') || {}).textContent || ''")
    verdict("no reader beside this Ollama: «Сколько места на диске и что в видеокарте, Ollama не говорит…»",
            noinfo.startswith("Сколько места на диске и что в видеокарте, Ollama не говорит"), noinfo)
    verdict("the list by weights: gemma4-32k — ticked, the main one, under gemma4:12b; qwen3.5:4b alone", await pg.until(
        "JSON.stringify(%s) === %r" % (FAMS, json.dumps([[["gemma4:12b", "8\u00a0ГБ", False, False], ["gemma4-32k", "+0 ГБ", True, True]],
                                                       [["qwen3.5:4b", "3,3\u00a0ГБ", False, False]]], ensure_ascii=False, separators=(",", ":"))), 30),
        await pg.js(FAMS))
    await pg.tap("document.querySelector('.lp-row.fit .lp-box')", wait=0.6)
    s = await said(pg)
    verdict("the only tick stays: «Хотя бы одна модель…» — or turn it off", s[0] == "alert" and "Хотя бы одна модель" in s[1] and "выключи" in s[1], s)
    await pg.tap("document.querySelector('.lp-mk .mmake')", wait=0.3)
    verdict("«Сделать копию с 32 тыс.»: «Делаю…» while the server makes it", "Делаю" in (await pg.js("(document.querySelector('.lp-mk .mmake') || {}).textContent") or ""))
    verdict("… done: the copy under qwen3.5:4b, ticked", await pg.until(
        "JSON.stringify(%s) === %r" % (FAMS, json.dumps([[["gemma4:12b", "8\u00a0ГБ", False, False], ["gemma4-32k", "+0 ГБ", True, True]],
                                                       [["qwen3.5:4b", "3,3\u00a0ГБ", False, False], ["qwen3.5-4b-32k", "+0 ГБ", True, False]]],
                                                      ensure_ascii=False, separators=(",", ":"))), 50), await pg.js(FAMS))
    s = await said(pg)
    verdict("… and says so", s[0] == "alert" and "Готово: qwen3.5-4b-32k — qwen3.5:4b с контекстом 32K" in s[1], s)
    verdict("… the computer's journal: made from qwen3.5:4b with 32768", "vendor local: qwen3.5-4b-32k made from qwen3.5:4b with the context 32768" in journal(), journal()[-400:])
    await pg.shot(os.path.join(OUT, "panel-copied.png"))
    # the star moves to the copy and back; a tick off stays off after the next check
    star = "[...document.querySelectorAll('.lp-row.fit')].find((r) => r.querySelector('b').textContent === %r).querySelector(%r)"
    await pg.tap(star % ("qwen3.5-4b-32k", ".mstar"), wait=1.0)
    verdict("the star: the copy is the main one", "vendor local: models qwen3.5-4b-32k, gemma4-32k" in journal(), journal()[-300:])
    await pg.tap(star % ("gemma4-32k", ".mstar"), wait=1.0)
    await pg.tap(star % ("qwen3.5-4b-32k", ".lp-box"), wait=1.0)
    verdict("… back to gemma4-32k; the copy's tick off", "vendor local: models gemma4-32k, the helpers' gemma4-32k" in journal(), journal()[-300:])
    await pg.tap("document.querySelector('.lp-srv .vl-re')", wait=1.2)
    verdict("«Проверить снова»: the copy stays unticked", await pg.until(
        "JSON.stringify(%s) === %r" % (FAMS, json.dumps([[["gemma4:12b", "8\u00a0ГБ", False, False], ["gemma4-32k", "+0 ГБ", True, True]],
                                                       [["qwen3.5:4b", "3,3\u00a0ГБ", False, False], ["qwen3.5-4b-32k", "+0 ГБ", False, False]]],
                                                      ensure_ascii=False, separators=(",", ":"))), 30), await pg.js(FAMS))
    await pg.tap("document.querySelector('.lp-srv .vl-at')", wait=0.4)
    verdict("a tap on the line opens the address field", await pg.js("document.querySelector('.lp .keyrow input').value") == "http://127.0.0.1:11434")
    await pg.shot(os.path.join(OUT, "panel-on.png"))
    await pg.cmd("Emulation.setEmulatedMedia", features=DARK)
    await asyncio.sleep(0.3)
    await pg.shot(os.path.join(OUT, "panel-on-dark.png"))
    await pg.cmd("Emulation.setEmulatedMedia", features=[])
    await pg.js("location.hash = '#/settings/models'")
    await pg.until("!!(%s)" % CARD, 150)
    # Settings opens at once with what it showed last and then catches up (review 2026-11-11, FE12): wait for the new
    await pg.until("[...document.querySelectorAll('.vend-all button')].some((b) => b.textContent === 'Своя')", 60)
    seg = await pg.js("[...document.querySelectorAll('.vend-all button')].map((b) => b.textContent)")
    verdict("the model of new projects can be it now", "Своя" in seg, seg)

    # the blog gets it — nothing runs there: asked where the code goes — it stays home
    await blog_settings(pg)
    await pg.tap(MODEL, wait=0.6)
    row = await pg.js("(() => { const b = %s; return [b.textContent.trim(), b.classList.contains('vo-off')]; })()" % (OPT % "Своя модель"))
    verdict("the project's models: «на твоём компьютере · gemma4-32k, бесплатно», not grey", "на твоём компьютере · gemma4-32k, бесплатно" in row[0] and not row[1], row)
    await pg.shot(os.path.join(OUT, "who-on.png"))
    await pg.js("window.__yes = true")
    await pg.tap(OPT % "Своя модель", wait=0.8)
    s = await said(pg)
    verdict("… the change asks, and says the code stays on your computers", s[0] == "confirm" and "код останется на твоих компьютерах" in s[1], s)
    verdict("… and takes", await pg.until("document.querySelector('.psets .ps-model b').textContent === 'Своя модель'", 50)
            and "its model claude → local" in journal(), journal()[-300:])
    # New task there: on it
    await pg.js("location.hash = '#/new?pkey=' + encodeURIComponent(%s)" % BLOG)
    await pg.until("!!" + FIELD % "Кто делает", 150)
    await pg.js(SPY)
    who = await pg.js("(%s).textContent" % (FIELD % "Кто делает"))
    verdict("New task in it: «Своя модель», the project's", who.startswith("Своя модель") and "модель проекта «blog»" in who, who)
    model = await pg.js("(%s).textContent" % (FIELD % "Модель"))
    verdict("… the model field: gemma4-32k", (model or "").startswith("gemma4-32k"), model)
    about = await pg.js("[...document.querySelectorAll('.form > .dim.small')].map((d) => d.textContent).join(' ')")
    verdict("… the words under the form: free, the code stays home, five tools", "бесплатно, код не уходит из дома" in about and "пять инструментов" in about, about)
    await pg.js("document.querySelector('.form textarea').focus()")
    await pg.cmd("Input.insertText", text="Поправь опечатки в README")
    await asyncio.sleep(0.3)
    await pg.shot(os.path.join(OUT, "new-task.png"))
    await pg.cmd("Emulation.setEmulatedMedia", features=DARK)
    await asyncio.sleep(0.3)
    await pg.shot(os.path.join(OUT, "new-task-dark.png"))
    await pg.cmd("Emulation.setEmulatedMedia", features=[])
    await pg.tap("document.querySelector('.form .btn.wide')", wait=1.0)
    verdict("the task starts on it", "vendor=local" in journal(), journal()[-300:])

    # turned off again — in the panel: the project keeps its model, its tasks wait for it
    await pg.js("location.hash = '#/local'")
    await pg.until("!!document.querySelector('.lp .vl-foot .link')", 150)
    await pg.js(SPY)
    await pg.tap("document.querySelector('.lp .vl-foot .link')", wait=1.0)
    s = await said(pg)
    verdict("«Выключить»: off, the tasks of its projects won't start; the panel says it is off", s[0] == "alert" and "задачи её проектов не начнутся" in s[1]
            and await pg.until("[...document.querySelectorAll('.lp .vl-down')].some((x) => x.textContent.startsWith('Своя модель выключена'))", 30), s)
    await pg.js("location.hash = '#/settings/models'")
    verdict("… Settings' card: off, the address and «Проверить и включить» again", await pg.until(
        "!!(%s) && (%s).querySelector('.vend-st').textContent === 'выключена' && !!(%s).querySelector('.keyrow input')" % (CARD, CARD, CARD), 100))
    await blog_settings(pg)
    verdict("… the blog keeps it, and says it can't work now", await pg.until(
        "document.querySelector('.psets .ps-model b').textContent === 'Своя модель' && !!document.querySelector('.psets .pick-why')", 50))


async def down_flow(pg):
    await pg.open(URLS["HOME"])
    await pg.until("!!document.querySelector('.card.mine .foot .llm')", 150)
    marks = await pg.js("[...document.querySelectorAll('.card.mine .foot .llm')].map((m) => m.textContent)")
    verdict("Your move: the outcome on the local model says «Своя · gemma4-32k» at its foot", "Своя · gemma4-32k" in marks, marks)
    await pg.js("[...document.querySelectorAll('.card.mine .foot .llm')].find((m) => m.textContent === 'Своя · gemma4-32k')"
                ".closest('.card').scrollIntoView({block: 'center'})")
    await asyncio.sleep(0.3)
    await pg.shot(os.path.join(OUT, "home.png"))
    await pg.cmd("Emulation.setEmulatedMedia", features=DARK)
    await asyncio.sleep(0.3)
    await pg.shot(os.path.join(OUT, "home-dark.png"))
    await pg.cmd("Emulation.setEmulatedMedia", features=[])
    await pg.js("location.hash = '#/new'")
    await pg.until("!!" + FIELD % "Кто делает", 150)
    await pg.js(SPY)
    await pick_shop(pg)
    who = await pg.js("(%s).textContent" % (FIELD % "Кто делает"))
    verdict("New task in the shop: its model, «Своя модель»", who.startswith("Своя модель"), who)
    await pg.js("document.querySelector('.form textarea').focus()")
    await pg.cmd("Input.insertText", text="Поправь опечатки в README")
    await pg.js("window.__yes = true")
    await pg.tap("document.querySelector('.form .btn.wide')", wait=1.0)
    s = await said(pg)
    verdict("the server is silent: the task isn't started, it says why", s[0] == "alert"
            and "не отвечает по адресу http://127.0.0.1:11434" in s[1], s)
    verdict("… and offers no Claude in its place (Q143)", "с Claude" not in s[1] and not await pg.js("window.__said.some((x) => x[0] === 'confirm')"), s)
    verdict("… nothing started", "NEWTASK" not in journal())
    # Settings: the look as they open finds the server silent — a line in the card; it stays on
    await pg.js("location.hash = '#/settings/models'")
    verdict("Settings: «Ollama сейчас не отвечает — список с проверки в …»", await pg.until(
        "!!(%s) && !!(%s).querySelector('.vl-down') && (%s).querySelector('.vl-down').textContent.startsWith('Ollama сейчас не отвечает — список с проверки в ')"
        % (CARD, CARD, CARD), 100))
    verdict("… it stays on", await pg.js("(%s).querySelector('.vend-st').textContent" % CARD) == "включена")
    verdict("… the computer's journal: a look, not a check", "didn't pass (a look) — net" in journal(), journal()[-300:])
    await pg.js("(%s).scrollIntoView({block: 'center'})" % CARD)
    await asyncio.sleep(0.3)
    await pg.shot(os.path.join(OUT, "settings-down.png"))
    # the panel: why, and the list of the last check
    await pg.tap("(%s).querySelector('.vl-open')" % CARD, wait=0.6)
    verdict("the panel: «По адресу … никто не отвечает…», the list of the last check", await pg.until(
        "!!document.querySelector('.lp .vl-down') && document.querySelector('.lp .vl-down').textContent.includes('никто не отвечает')"
        " && JSON.stringify(%s) === %r" % (FAMS, json.dumps([[["gemma4:12b", "8\u00a0ГБ", False, False], ["gemma4-32k", "+0 ГБ", True, True]],
                                                          [["qwen3.5:4b", "3,3\u00a0ГБ", False, False]]], ensure_ascii=False, separators=(",", ":"))), 60),
        await pg.js(FAMS))
    await pg.shot(os.path.join(OUT, "panel-down.png"))


async def main():
    async with _cdp.Page() as pg:
        await (down_flow(pg) if DOWN else off_flow(pg))
        verdict("no script errors on the page", not pg.errors, pg.errors)
    print("screenshots:", OUT)
    sys.exit(verdict.code())


asyncio.run(main())
