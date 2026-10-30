"""A second opinion from Codex (stage M, step 1), in headless Chrome over DevTools, on the stand with a stand-in Codex
(STAND_SECOND=1): the outcome of the session that waits for you offers "Second opinion · Codex"; the first tap in a project
asks whether its code may go to OpenAI — "no" leaves everything as it was, "yes" starts it; the card says Codex is
reading, for how long and how many commands, and can stop it; then two findings, each with its place — a tap opens the
file at that line; "Send to Claude" puts them into the session as your message and the card goes, the button comes back;
"Got it" puts a second review away without a word; the project's screen says other vendors may get its code, and
"Disallow" takes that back. The stand's output shows what the computer's journal says.
  STAND_SECOND=1 STAND_LANG=ru STAND_PORT=18161 HOLD=300 ~/.local/share/pult/venv/bin/python tools/stand.py > /tmp/stand.out &
  ~/.local/share/pult/venv/bin/python tools/second_check.py /tmp/stand.out [out_dir]
Screenshots go to out_dir (a temporary folder by default): the button, Codex reading, the findings (light and dark), the
file at its line, the project's line. Exit 1 on a failed check."""
import asyncio
import os
import sys
import tempfile

import _cdp

STAND = sys.argv[1]
URLS = _cdp.stand_urls(STAND, ("SESS4",))
OUT = sys.argv[2] if len(sys.argv) > 2 else tempfile.mkdtemp(prefix="pult-second-")
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


def journal():
    with open(STAND, encoding="utf-8", errors="replace") as f:
        return f.read()


async def main():
    async with _cdp.Page() as pg:
        await pg.open(URLS["SESS4"])
        verdict("the outcome offers a second opinion", await pg.until("!!" + ASK, 150),
                await pg.js("document.querySelector('.card.outcome') && document.querySelector('.card.outcome').innerText"))
        verdict("... in Codex's words", await pg.js(ASK + ".textContent.trim()") == "Второе мнение · Codex",
                await pg.js(ASK + ".textContent"))
        await pg.shot(os.path.join(OUT, "button.png"))
        await pg.js(SPY)

        # the first tap in the project asks whether its code may go to OpenAI; "no" changes nothing
        await pg.tap(ASK, wait=0.8)
        said = await pg.js("window.__said")
        verdict("the first tap asks whether the project may go to OpenAI", len(said) == 1 and "OpenAI" in said[0]
                and "«acme-shop»" in said[0] and "Спрашиваю один раз" in said[0], said)
        verdict("... «no» starts nothing", not await pg.js("!!" + CARD) and await pg.js("!!" + ASK)
                and "second opinion" not in journal())

        # "yes": the project is allowed, Codex reads — for how long, how many commands, a way to stop it
        await pg.js("window.__yes = true")
        await pg.tap(ASK, wait=0.3)
        verdict("«yes» starts it: Codex is reading", await pg.until(CARD + " && " + CARD + ".classList.contains('run')"
                                                                  + " && " + CARD + ".textContent.includes('Codex читает изменения задачи')", 50),
                await pg.js(CARD + " && " + CARD + ".innerText"))
        verdict("... asked once", len(await pg.js("window.__said")) == 2)
        verdict("... the button is gone while it reads", not await pg.js("!!" + ASK))
        verdict("... the journal says the project may go to other vendors", "may go to other vendors" in journal())
        verdict("... how many commands it ran", await pg.until(CARD + ".textContent.includes('команд')", 40),
                await pg.js(CARD + ".innerText"))
        verdict("... and a way to stop it", await pg.js(CARD + ".querySelector('.foot .link').textContent.trim()") == "Остановить")
        await pg.shot(os.path.join(OUT, "reading.png"))

        # its findings: two, each with its place; the card's head names the model and how long it took
        verdict("two findings come", await pg.until(ITEMS + " === 2", 120), await pg.js(CARD + " && " + CARD + ".innerText"))
        head = await pg.js(CARD + ".querySelector('.k').textContent")
        verdict("... the head: Codex, its model, how long", "Второе мнение · Codex" in head and "GPT-5.6-Sol" in head
                and ("с" in head), head)
        line = await pg.js(CARD + ".querySelector('.o-l').textContent")
        verdict("... «2 замечания» and Codex's own words", line.startswith("2 замечания") and "заболят два места" in line, line)
        first = await pg.js(CARD + ".querySelector('.sec-list li').innerText")
        verdict("... the first: its priority, title, place, text", first.startswith("P1") and "Пересобирайте только триграммы" in first
                and "search/index.py:41-58" in first and "40 тыс." in first, first)
        verdict("... the window Codex spent from", "Окно Codex на 5 ч: занято 12 %" in await pg.js(CARD + ".innerText"))
        verdict("... and the journal says so", "2 findings, 4 commands" in journal())
        await pg.shot(os.path.join(OUT, "findings.png"))
        await pg.cmd("Emulation.setEmulatedMedia", features=[{"name": "prefers-color-scheme", "value": "dark"}])
        await asyncio.sleep(0.3)
        await pg.shot(os.path.join(OUT, "findings-dark.png"))
        await pg.cmd("Emulation.setEmulatedMedia", features=[])

        # a finding's place opens the file at that line
        await pg.tap(CARD + ".querySelector('.sec-at .flink')", wait=1.0)
        verdict("the place opens the file at its line", await pg.until("!!document.querySelector('.fv .ln.hit#L41')", 50),
                await pg.js("document.querySelector('.fv') && document.querySelector('.fv').innerText.slice(0, 200)"))
        await pg.shot(os.path.join(OUT, "file.png"))
        await pg.tap("document.querySelector('.fv-b')", wait=0.6)
        verdict("... Back closes it", not await pg.js("!!document.querySelector('.fv')"))

        # "Send to Claude": into the session as your message; the card goes, the button is back
        await pg.tap(CARD + ".querySelector('.foot .btn')", wait=1.0)
        verdict("«Send to Claude» sends the findings into the session",
                "DRIVE" in journal() and "A second opinion from Codex (gpt-5.6-sol)" in journal(), journal()[-600:])
        verdict("... the card goes and the button is back", await pg.until("!" + CARD + " && !!" + ASK, 50))
        verdict("... and the journal says so", "sent to Claude (2 findings)" in journal())

        # a second review asks no more; "Got it" puts it away without a word to Claude
        await pg.tap(ASK, wait=0.3)
        verdict("a second review asks no more", len(await pg.js("window.__said")) == 2 and await pg.until("!!" + CARD, 50))
        verdict("... its findings come", await pg.until(ITEMS + " === 2", 120))
        n = journal().count("DRIVE")
        await pg.tap(CARD + ".querySelector('.foot .link')", wait=0.8)
        verdict("«Got it» puts it away without a word to Claude", await pg.until("!" + CARD, 30) and journal().count("DRIVE") == n)

        # the project's screen: other vendors may get its code — and "Disallow" takes that back
        await pg.js("location.hash = '#/p/' + encodeURIComponent('-Users-x-proj')")     # within the app, as a tap there
        verdict("the project says other vendors may get its code", await pg.until("!!document.querySelector('.vline')", 150)
                and "Код проекта можно отдавать другим производителям" in await pg.js("document.querySelector('.vline').textContent"))
        await pg.shot(os.path.join(OUT, "project.png"))
        await pg.tap("document.querySelector('.vline .link')", wait=0.8)
        verdict("... «Disallow» takes it back", not await pg.js("!!document.querySelector('.vline')")
                and "stays with Claude only" in journal())
        verdict("no script errors on the page", not pg.errors, pg.errors)
    print("screenshots:", OUT)
    sys.exit(verdict.code())


asyncio.run(main())
