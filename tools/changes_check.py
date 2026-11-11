"""What a task changed (review 2026-11-11, block 5: the view alone), in headless Chrome over DevTools, on the stand whose
shop is a git repository the task changed every way git knows (STAND_SECOND=allowed STAND_CHANGES=1): under the outcome
of the session that waits for you — "Changes: 4 files +a −b"; a tap opens the list — the task's own four files (an edited
one, a renamed one with its earlier name, a new one), and folded under them what else changed in the folder (a removed
file, a binary one, one like keys — locked, another task's notes); a file opens its change line by line over the screen —
removed and added lines with their signs, how many unchanged lines lie between two pieces, "Whole file" and back; Back
returns to the list as it was; a binary file says so and opens as it is; a finding of Codex's second opinion opens the
change at its line — the whole file when the pieces don't hold that line, the file as it is when it didn't change.
  STAND_SECOND=allowed STAND_CHANGES=1 STAND_LANG=ru STAND_PORT=18171 HOLD=300 ~/.local/share/pult/venv/bin/python tools/stand.py > /tmp/stand.out &
  ~/.local/share/pult/venv/bin/python tools/changes_check.py /tmp/stand.out [out_dir]
Screenshots go to out_dir (a temporary folder by default). Exit 1 on a failed check."""
import asyncio
import os
import sys
import tempfile

import _cdp

STAND = sys.argv[1]
URLS = _cdp.stand_urls(STAND, ("SESS4",))
OUT = sys.argv[2] if len(sys.argv) > 2 else tempfile.mkdtemp(prefix="pult-changes-")
os.makedirs(OUT, exist_ok=True)
verdict = _cdp.Verdicts()
LINE = "document.querySelector('.card.outcome .chgline')"
ROWS = "[...document.querySelectorAll('.chg-list:not(.rest) .chg-row')].map((r) => r.innerText.replace(/\\s+/g, ' ').trim())"
REST = "[...document.querySelectorAll('.chg-list.rest .chg-row')].map((r) => r.innerText.replace(/\\s+/g, ' ').trim())"
DF = "document.querySelector('.fv.df')"
TOP = "[...document.querySelectorAll('.fv.df')].pop()"
COUNT = "((sel) => document.querySelectorAll(sel).length)"


def row(name, rest=False):
    return ("[...document.querySelectorAll('.chg-list%s .chg-row')].find((r) => r.querySelector('b').textContent === '%s')"
            % (".rest" if rest else ":not(.rest)", name))


def journal():
    with open(STAND, encoding="utf-8", errors="replace") as f:
        return f.read()


async def main():
    async with _cdp.Page() as pg:
        await pg.open(URLS["SESS4"])
        # the line under the outcome: the task's own files, the lines added and removed
        verdict("the outcome has the line of changes", await pg.until("!!" + LINE, 150),
                await pg.js("document.querySelector('.card.outcome') && document.querySelector('.card.outcome').innerText"))
        line = (await pg.js(LINE + ".innerText") or "").replace("\n", " ")
        verdict("... «Изменения: 4 файла» with the lines added and removed", "Изменения: 4 файла" in line and "+41" in line and "−3" in line, line)
        await pg.js(LINE + ".scrollIntoView({block: 'center'})")
        await pg.shot(os.path.join(OUT, "line.png"))

        # the list: the task's own first; the rest of the folder folded under them
        await pg.tap(LINE, wait=0.5)
        verdict("a tap opens the list", await pg.until("location.hash.startsWith('#/c/') && " + COUNT + "('.chg-list .chg-row') === 4", 100),
                await pg.js("document.querySelector('main').innerText"))
        head = await pg.js("document.querySelector('.chg-h').innerText")
        verdict("... its head: the project, the task, since when, how much", "Изменения" in head and "acme-shop" in head
                and "с начала задачи" in head and "4 файла" in head and "+41" in head, head)
        rows = await pg.js(ROWS)
        verdict("... four files of the task, by path", [r.split(" ")[0] for r in rows] == ["index.py", "query.py", "ranking.py", "test_fuzzy.py"], rows)
        verdict("... an edited one with its lines", rows[0].startswith("index.py · search") and "+14" in rows[0] and "−1" in rows[0], rows[0])
        verdict("... a renamed one with its earlier name", "был search/rank_old.py" in rows[2] and "переименован" in rows[2], rows[2])
        verdict("... a new one says so", "+13" in rows[3] and "новый" in rows[3] and "tests" in rows[3], rows[3])
        more = await pg.js("document.querySelector('.chg-more') && document.querySelector('.chg-more').innerText")
        verdict("... what else changed in the folder is folded", more and "Ещё изменилось в папке: 4" in more
                and "Командами или другими задачами" in more and not await pg.js(COUNT + "('.chg-list.rest')"), more)
        verdict("... the journal says what was counted", "4 of the task's files (+41 −3), 4 more in the folder" in journal(), journal()[-400:])
        await pg.shot(os.path.join(OUT, "list.png"))
        await pg.tap("document.querySelector('.chg-more')", wait=0.4)
        rest = await pg.js(REST)
        verdict("... open: a removed file, a binary one, one like keys, another task's", len(rest) == 4
                and any(r.startswith("legacy.py") and "удалён" in r and "−2" in r for r in rest)
                and any(r.startswith("logo.bin") and "двоичный" in r for r in rest)
                and any(r.startswith("notes.md") and "+1" in r for r in rest), rest)
        verdict("... the one like keys is locked", await pg.js("(() => { const r = %s; return r.disabled && !!r.querySelector('.ic'); })()" % row(".env", True)))
        await pg.shot(os.path.join(OUT, "list-open.png"))
        await pg.cmd("Emulation.setEmulatedMedia", features=[{"name": "prefers-color-scheme", "value": "dark"}])
        await asyncio.sleep(0.3)
        await pg.shot(os.path.join(OUT, "list-dark.png"))
        await pg.cmd("Emulation.setEmulatedMedia", features=[])

        # one file line by line, over the screen
        await pg.tap(row("index.py"), wait=0.3)
        verdict("a file opens its change line by line", await pg.until("!!" + DF + " && " + COUNT + "('.fv.df .dl.a') === 14", 100),
                await pg.js(DF + " && " + DF + ".innerText.slice(0, 300)"))
        head = await pg.js(DF + ".querySelector('.fv-h').innerText")
        verdict("... its head: the name, the folder, the lines", "index.py" in head and "search" in head and "+14" in head and "−1" in head, head)
        first = await pg.js("[...document.querySelectorAll('.fv.df .dl')].slice(0, 3).map((r) => [r.className, r.querySelector('.s') ? r.querySelector('.s').textContent : '', r.innerText])")
        verdict("... a removed line with «−», then the added one with «+»", first[0][0] == "dl d" and first[0][1] == "−" and "The product index." in first[0][2]
                and first[1][0] == "dl a" and first[1][1] == "+" and "typo-tolerant" in first[1][2], first)
        gap = await pg.js("(() => { const g = document.querySelector('.fv.df .dl.gap'); return g && g.textContent; })()")
        verdict("... how many unchanged lines lie between two pieces", gap == "38 строк без правок", gap)
        await pg.shot(os.path.join(OUT, "diff.png"))
        await pg.cmd("Emulation.setEmulatedMedia", features=[{"name": "prefers-color-scheme", "value": "dark"}])
        await asyncio.sleep(0.3)
        await pg.shot(os.path.join(OUT, "diff-dark.png"))
        await pg.cmd("Emulation.setEmulatedMedia", features=[])
        chip = DF + ".querySelector('.fv-t')"
        verdict("... «Весь файл» is offered", await pg.js(chip + " && " + chip + ".textContent") == "Весь файл")
        await pg.tap(chip, wait=0.3)
        verdict("... and shows every line, the changes in place", await pg.until(
            chip + " && " + chip + ".textContent === 'Только правки' && !document.querySelector('.fv.df .dl.gap') && "
            + COUNT + "('.fv.df .dl') === 59 && " + COUNT + "('.fv.df .dl.a') === 14", 100), await pg.js(COUNT + "('.fv.df .dl')"))
        await pg.shot(os.path.join(OUT, "diff-full.png"))
        await pg.tap(chip, wait=0.3)
        verdict("... «Только правки» folds it back", await pg.until("!!document.querySelector('.fv.df .dl.gap')", 100))
        await pg.tap(DF + ".querySelector('.fv-b')", wait=0.6)
        verdict("Back returns to the list as it was", not await pg.js("!!" + DF) and await pg.js(COUNT + "('.chg-list.rest .chg-row')") == 4
                and await pg.js("location.hash.startsWith('#/c/')"))

        # a new file: every line added, whole already; a removed one: every line removed, nothing to open
        await pg.tap(row("test_fuzzy.py"), wait=0.3)
        verdict("a new file: every line added, no «Весь файл»", await pg.until(COUNT + "('.fv.df .dl.a') === 13", 100)
                and await pg.js(COUNT + "('.fv.df .dl')") == 13 and not await pg.js("!!" + chip)
                and "новый" in await pg.js(DF + ".querySelector('.fv-h').innerText"), await pg.js(DF + " && " + DF + ".innerText.slice(0, 200)"))
        await pg.tap(DF + ".querySelector('.fv-b')", wait=0.6)
        await pg.tap(row("legacy.py", True), wait=0.3)
        verdict("a removed file: every line removed, nothing to open", await pg.until(COUNT + "('.fv.df .dl.d') === 2", 100)
                and not await pg.js("!!" + DF + ".querySelector('.fv-bar')"), await pg.js(DF + " && " + DF + ".innerText.slice(0, 200)"))
        await pg.tap(DF + ".querySelector('.fv-b')", wait=0.6)
        await pg.tap(row("ranking.py"), wait=0.3)
        verdict("a renamed file: its change against its earlier name", await pg.until(COUNT + "('.fv.df .dl.a') === 1", 100)
                and await pg.js(COUNT + "('.fv.df .dl.d')") == 1 and "был search/rank_old.py" in await pg.js(DF + ".querySelector('.fv-h').innerText"),
                await pg.js(DF + " && " + DF + ".innerText.slice(0, 300)"))
        await pg.tap(DF + ".querySelector('.fv-b')", wait=0.6)

        # a binary file says so, and opens as it is
        await pg.tap(row("logo.bin", True), wait=0.3)
        verdict("a binary file says there are no lines to compare", await pg.until(
            "!!" + DF + " && " + DF + ".innerText.includes('Двоичный файл')", 100), await pg.js(DF + " && " + DF + ".innerText"))
        await pg.tap(DF + ".querySelector('.fv-bar .btn')", wait=0.3)
        verdict("... «Открыть файл» opens it as it is, over the change", await pg.until(
            "document.querySelectorAll('.fv').length === 2 && !!document.querySelector('.fv:not(.df) .fv-h') && "
            "document.querySelector('.fv:not(.df) .fv-h b').textContent === 'logo.bin'", 100))
        await pg.tap("document.querySelector('.fv:not(.df) .fv-b')", wait=0.6)
        verdict("... Back closes the file, the change stays", await pg.js("document.querySelectorAll('.fv').length") == 1 and await pg.js("!!" + DF))
        await pg.tap(DF + ".querySelector('.fv-b')", wait=0.6)

        # a second opinion's findings open the change at their lines
        await pg.js("history.back()")
        ask = "document.querySelector('.card.outcome .sec-ask')"
        items = "document.querySelectorAll('.card.second .sec-list li')"
        verdict("back in the task", await pg.until("location.hash.startsWith('#/s/') && (!!" + ask + " || " + items + ".length > 0)", 100),
                await pg.js("[location.hash, document.querySelector('main').innerText.slice(-300)]"))
        if not await pg.js(items + ".length"):                 # a stand this check already ran on has the findings
            await pg.tap(ask, wait=0.3)
        verdict("Codex's three findings come", await pg.until(items + ".length === 3", 200))
        await asyncio.sleep(0.8)                               # the card has just come and the chat goes to its end: let it stand
        place = lambda n: items + "[%d].querySelector('.sec-at .flink')" % n       # noqa: E731
        await pg.tap(place(0), wait=0.3)
        verdict("a finding's place opens the change at its line — the whole file, as the pieces don't hold it",
                await pg.until("!!document.querySelector('.fv.df .dl.hit') && " + chip + ".textContent === 'Только правки'", 100),
                await pg.js(DF + " && " + DF + ".innerText.slice(0, 200)"))
        seen = "(() => { const b = document.querySelector('.fv.df .dl.hit').getBoundingClientRect(); return b.top > 60 && b.bottom < innerHeight - 60; })()"
        hit = await pg.js("(() => { const h = document.querySelector('.fv.df .dl.hit'); return [h.querySelector('.n').textContent, h.innerText]; })()")
        verdict("... line 41, marked and in sight", hit[0] == "41" and "def add(product):" in hit[1] and await pg.until(seen, 30), hit)
        await pg.shot(os.path.join(OUT, "finding.png"))
        await pg.tap(DF + ".querySelector('.fv-b')", wait=0.6)
        await pg.tap(place(1), wait=0.3)
        verdict("a line inside a piece: the pieces alone", await pg.until("!!document.querySelector('.fv.df .dl.hit')", 100)
                and await pg.js("document.querySelector('.fv.df .dl.hit .n').textContent") == "12"
                and await pg.js("document.querySelector('.fv.df .dl.hit').classList.contains('a')")
                and await pg.js(chip + ".textContent") == "Весь файл", await pg.js(DF + " && " + DF + ".innerText.slice(0, 200)"))
        await pg.tap(DF + ".querySelector('.fv-b')", wait=0.6)
        await pg.tap(place(2), wait=0.3)
        verdict("a file the task didn't change opens as it is, at the line", await pg.until(
            "!document.querySelector('.fv.df') && !!document.querySelector('.fv .ln.hit#L1')", 100),
            await pg.js("document.querySelector('.fv') && document.querySelector('.fv').innerText.slice(0, 200)"))
        await pg.tap("document.querySelector('.fv-b')", wait=0.6)
        verdict("... Back closes it", not await pg.js("!!document.querySelector('.fv')"))
        verdict("no script errors on the page", not pg.errors, pg.errors)
    print("screenshots:", OUT)
    sys.exit(verdict.code())


asyncio.run(main())
