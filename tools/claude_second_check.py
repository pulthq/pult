"""Claude's second opinion on a task Codex did (stage M, M4.2; review 2026-11-11, block 6), in headless Chrome over
DevTools, on the stand (STAND_VENDORS=1 STAND_CLREVIEW=1: the support desk is Codex's project, a stand-in for Claude's
read-only session): the outcome of the Codex task offers "Second opinion · Claude"; the first tap in the project asks
whether its code may go to Anthropic — "no" leaves everything as it was, "yes" starts it; the card says Claude is
reading, with nothing but reading tools, and can be stopped; then its findings — the model's name, each with its place
and a tick; "Send to Codex" puts them into the task as your message; once Codex has answered, the button is "Check the
fixes · Claude" and the card says what is fixed and what is left; the project's settings say Claude may read its code,
and "Disallow" takes that back. The stand's output shows what the computer's journal says.
  STAND_VENDORS=1 STAND_CLREVIEW=1 STAND_LANG=ru STAND_PORT=18671 HOLD=300 ~/.local/share/pult/venv/bin/python tools/stand.py > /tmp/stand.out &
  ~/.local/share/pult/venv/bin/python tools/claude_second_check.py /tmp/stand.out [out_dir]
Screenshots go to out_dir (a temporary folder by default). Exit 1 on a failed check."""
import asyncio
import os
import sys
import tempfile

import _cdp

STAND = sys.argv[1]
URLS = _cdp.stand_urls(STAND, ("SESSC",))
OUT = sys.argv[2] if len(sys.argv) > 2 else tempfile.mkdtemp(prefix="pult-clsecond-")
os.makedirs(OUT, exist_ok=True)
verdict = _cdp.Verdicts()
# Telegram's confirm, and the browser's in its place: what it asked is kept, the answer is window.__yes
SPY = """(() => { window.__said = []; window.__yes = false;
  window.confirm = (s) => (window.__said.push(String(s)), window.__yes);
  const w = window.Telegram && window.Telegram.WebApp;
  if (w) w.showConfirm = (s, cb) => (window.__said.push(String(s)), cb(window.__yes));
  return true; })()"""
ASK = "document.querySelector('.card.outcome .sec-ask')"
CARD = "document.querySelector('.card.second')"
ITEMS = "document.querySelectorAll('.card.second .sec-list li').length"
SEND = CARD + ".querySelector('.foot .btn')"


def journal():
    with open(STAND, encoding="utf-8", errors="replace") as f:
        return f.read()


async def main():
    async with _cdp.Page() as pg:
        await pg.open(URLS["SESSC"])
        verdict("the outcome of Codex's task offers a second opinion", await pg.until("!!" + ASK, 150),
                await pg.js("document.querySelector('.card.outcome') && document.querySelector('.card.outcome').innerText"))
        verdict("... Claude's", await pg.js(ASK + ".textContent.trim()") == "Второе мнение · Claude", await pg.js(ASK + ".textContent"))
        await pg.shot(os.path.join(OUT, "button.png"))
        await pg.js(SPY)
        await asyncio.sleep(0.8)

        # the first tap in the project asks whether its code may go to Anthropic; "no" changes nothing
        await pg.tap(ASK, wait=0.8)
        said = await pg.js("window.__said")
        verdict("the first tap asks whether the project may go to Anthropic", len(said) == 1 and "Anthropic" in said[0]
                and "OpenAI" not in said[0] and "«support-desk»" in said[0] and "Спрашиваю один раз" in said[0], said)
        verdict("... the question fits Telegram's window", len(said) == 1 and len(said[0]) <= 256, said and len(said[0]))
        verdict("... «no» starts nothing", not await pg.js("!!" + CARD) and await pg.js("!!" + ASK) and "CLREVIEW asked" not in journal())

        # "yes": the project is allowed, Claude reads — for how long, how many looks, a way to stop it
        await pg.js("window.__yes = true")
        await pg.tap(ASK, wait=0.3)
        verdict("«yes» starts it: Claude is reading", await pg.until(
            CARD + " && " + CARD + ".classList.contains('run') && " + CARD + ".textContent.includes('Claude читает изменения задачи')", 50),
                await pg.js(CARD + " && " + CARD + ".innerText"))
        verdict("... with nothing but reading tools, it says", "только инструменты чтения" in await pg.js(CARD + ".innerText"))
        verdict("... asked once", len(await pg.js("window.__said")) == 2)
        verdict("... the journal says Claude may read the project", "may be read by Claude for a second opinion" in journal())
        verdict("... how many times it looked into the files", await pg.until(CARD + ".textContent.includes('к файлам')", 40),
                await pg.js(CARD + ".innerText"))
        verdict("... and a way to stop it", await pg.js(CARD + ".querySelector('.foot .link').textContent.trim()") == "Остановить")
        await pg.shot(os.path.join(OUT, "reading.png"))
        verdict("... told the task in Codex's folder, the changes in its words", "CLREVIEW asked in support-desk" in journal()
                and "review · has the diff: True" in journal(), journal()[-300:])

        # its findings: two, each with its place and a tick; the head names Claude's model
        verdict("two findings come", await pg.until(ITEMS + " === 2", 120), await pg.js(CARD + " && " + CARD + ".innerText"))
        head = await pg.js(CARD + ".querySelector('.k').textContent")
        verdict("... the head: Claude, its model, how long", "Второе мнение · Claude" in head and "Sonnet 5.5" in head, head)
        first = await pg.js(CARD + ".querySelector('.sec-list li').innerText")
        verdict("... the first: its priority, title, place, text", first.startswith("P1") and "Здравствуйте, None" in first
                and "replies/templates.py:6-7" in first and "из формы" in first, first)
        verdict("... each with a tick", await pg.js("document.querySelectorAll('.card.second .sec-pick[aria-checked=true]').length") == 2)
        verdict("... no line of Codex's plan window", "Окно Codex" not in await pg.js(CARD + ".innerText"))
        verdict("... the button names the doer — Codex", await pg.js(SEND + ".textContent.trim()") == "Отправить Codex",
                await pg.js(SEND + ".textContent"))
        verdict("... and the journal says who read it", "Claude (claude-sonnet-5-5), 2 findings" in journal())
        await pg.js(CARD + ".scrollIntoView({block: 'end'}); window.scrollBy(0, 400)")
        await asyncio.sleep(0.6)
        await pg.shot(os.path.join(OUT, "findings.png"))

        # a finding's place opens the file's change at that line
        await pg.tap(CARD + ".querySelector('.sec-at .flink')", wait=1.0)
        verdict("the place opens the file's change at its line", await pg.until(
            "!!document.querySelector('.fv.df .dl.hit') && document.querySelector('.fv.df .dl.hit .n').textContent === '6'", 50),
                await pg.js("document.querySelector('.fv') && document.querySelector('.fv').innerText.slice(0, 200)"))
        await pg.tap("document.querySelector('.fv-b')", wait=0.6)

        # "Send to Codex": into the task as your message — Codex takes a turn — and then the fixes can be checked
        await pg.tap(SEND, wait=1.0)
        verdict("«Send to Codex» sends the findings into the task",
                "A second opinion from Claude (claude-sonnet-5-5)" in journal() and "sent to Codex (2 findings of 2)" in journal(), journal()[-600:])
        verdict("... Codex has answered: the button asks Claude to check the fixes", await pg.until(
            "!" + CARD + " && !!" + ASK + " && " + ASK + ".textContent.trim() === 'Проверить исправления · Claude'", 200),
                await pg.js(ASK + " && " + ASK + ".textContent"))
        await asyncio.sleep(0.8)
        await pg.tap(ASK, wait=0.3)
        verdict("a tap: Claude checks the fixes against its findings", await pg.until(
            CARD + " && " + CARD + ".classList.contains('run') && " + CARD + ".textContent.includes('Claude сверяет исправления')", 50),
                await pg.js(CARD + " && " + CARD + ".innerText"))
        verdict("its answer comes", await pg.until(ITEMS + " === 2 && !!document.querySelector('.card.second .sec-st')", 120),
                await pg.js(CARD + " && " + CARD + ".innerText"))
        verdict("... the head: a check of the fixes by Claude", "Проверка исправлений · Claude" in await pg.js(CARD + ".querySelector('.k').textContent"))
        verdict("... how many of each", await pg.js(CARD + ".querySelector('.o-l b').textContent") == "1 осталось · 1 исправлено",
                await pg.js(CARD + ".querySelector('.o-l').textContent"))
        verdict("... only what is left can go — to Codex", await pg.js(SEND + ".textContent.trim()") == "Отправить Codex · 1",
                await pg.js(SEND + ".textContent"))
        verdict("... asked as a check, with the changes", "check · has the diff: True" in journal())
        await pg.js(CARD + ".scrollIntoView({block: 'end'}); window.scrollBy(0, 400)")
        await asyncio.sleep(0.6)
        await pg.shot(os.path.join(OUT, "check.png"))
        await pg.tap(CARD + ".querySelector('.foot .link')", wait=0.8)
        verdict("«Got it» puts the check away", await pg.until("!" + CARD, 50))

        # the project's settings: Claude may read its code for a second opinion — and "Disallow" takes that back
        await pg.js("location.hash = '#/ps/' + encodeURIComponent('-Users-x-support-desk')")
        verdict("the project's settings say Claude may read its code", await pg.until("!!document.querySelector('.psets .vline')", 150)
                and "Claude может читать код проекта для второго мнения" in await pg.js("document.querySelector('.psets .vline').textContent"),
                await pg.js("(document.querySelector('.psets') || {}).innerText"))
        verdict("... and that Claude gives it where Codex does the tasks", "второе мнение на них даёт Claude" in
                await pg.js("document.querySelector('.psets .ps-review').textContent"))
        await pg.shot(os.path.join(OUT, "project.png"))
        await pg.tap("document.querySelector('.psets .vline .link')", wait=0.8)
        verdict("... «Disallow» takes it back", not await pg.js("!!document.querySelector('.psets .vline')")
                and "is read by Claude no more" in journal())
        verdict("no script errors on the page", not pg.errors, pg.errors)
    print("screenshots:", OUT)
    sys.exit(verdict.code())


asyncio.run(main())
