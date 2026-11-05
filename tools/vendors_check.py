"""Other vendors' models inside Claude Code (stage M, steps 2 and 7.2), in headless Chrome over DevTools, on the stand with
a made-up DeepSeek key (STAND_VENDORS=1), where the shop is DeepSeek's project: New task's "Who does it" is the project's
model — DeepSeek in the shop, Claude in the support desk — and a tap on it opens the project's settings; the model field is
the project model's own — DeepSeek's models, Codex's model and levels once the blog is Codex's; the task starts with it.
Settings → Other vendors: the model of new projects — Claude, Codex or DeepSeek; DeepSeek's key is there, GLM's isn't; a
bad key is refused with the vendor's words, a good one taken; the list of models is saved. A session on DeepSeek's model
says so by the field — "DeepSeek · v4-pro", its name ending where Stop begins, on a narrow phone too — and its picker lists
only DeepSeek's models; Home's "Running now" says which model does each task (the owner, 2026-10-30); "Your move" too — an
outcome at its foot across from "Got it", a request on its top line before how long it waits (Q108) — and a finished
task's row at the right end of its second line (Q109), on 320 px too; a project's screen the same.
  STAND_VENDORS=1 STAND_HOMES=1 STAND_LANG=ru STAND_PORT=18171 HOLD=300 ~/.local/share/pult/venv/bin/python tools/stand.py > /tmp/stand.out &
  ~/.local/share/pult/venv/bin/python tools/vendors_check.py /tmp/stand.out [out_dir]
Screenshots go to out_dir (a temporary folder by default). Exit 1 on a failed check."""
import asyncio
import os
import sys
import tempfile

import _cdp

STAND = sys.argv[1]
URLS = _cdp.stand_urls(STAND, ("NEW",))
OUT = sys.argv[2] if len(sys.argv) > 2 else tempfile.mkdtemp(prefix="pult-vendors-")
os.makedirs(OUT, exist_ok=True)
verdict = _cdp.Verdicts()
SPY = _cdp.SPY
FIELD = "(() => [...document.querySelectorAll('.form .field')].find((b) => b.previousElementSibling && b.previousElementSibling.textContent.trim() === %r))()"
OPT = "[...document.querySelectorAll('.card.pick .opt')].find((b) => b.textContent.trim().startsWith(%r))"
SAID = "window.__said.at(-1)"


def journal():
    with open(STAND, encoding="utf-8", errors="replace") as f:
        return f.read()


async def said(pg):
    return await pg.js(SAID) or ["", ""]


async def main():
    async with _cdp.Page() as pg:
        await pg.open(URLS["NEW"])
        verdict("New task has «Кто делает»", await pg.until("!!" + FIELD % "Кто делает", 150))
        await pg.js(SPY)
        # the shop is DeepSeek's (stage M, 7.2): its tasks go to DeepSeek, no choice per task
        await pg.tap(FIELD % "Проект")
        await pg.tap(OPT % "acme-shop", wait=0.6)
        who = await pg.js("(%s).textContent" % (FIELD % "Кто делает"))
        verdict("… the shop's model: DeepSeek, the project's", who.startswith("DeepSeek") and "модель проекта «acme-shop»" in who, who)
        model = await pg.js("(%s).textContent" % (FIELD % "Модель DeepSeek"))
        verdict("the model field is DeepSeek's", model and model.strip().startswith("deepseek-flash[1m]"), model)
        about = await pg.js("document.querySelector('.form .btn.wide').nextElementSibling.textContent")
        verdict("… and the words under it say where it runs", "на модели DeepSeek" in about and "в VS Code её нет" in about, about)
        await pg.shot(os.path.join(OUT, "who.png"))
        # the support desk is Claude's
        await pg.tap(FIELD % "Проект")
        await pg.tap(OPT % "support-desk", wait=0.6)
        who = await pg.js("(%s).textContent" % (FIELD % "Кто делает"))
        verdict("… the desk's: Claude", who.startswith("Claude") and "модель проекта «support-desk»" in who, who)
        verdict("… its model field is Claude's", await pg.js("!!" + FIELD % "Модель и раздумья"))
        # "Who does it" leads to the project's settings, where its model is changed (Q143): the blog — nothing runs
        # there — becomes Codex's
        await pg.tap(FIELD % "Проект")
        await pg.tap(OPT % "blog", wait=0.6)
        await pg.tap(FIELD % "Кто делает", wait=0.8)
        verdict("a tap on «Кто делает» opens the project's settings", await pg.until(
            "location.hash.startsWith('#/ps/') && !!document.querySelector('.psets .ps-model')", 100), await pg.js("location.hash"))
        await pg.js(SPY)
        await pg.js("window.__yes = true")
        await pg.tap("document.querySelector('.psets .ps-model')", wait=0.6)
        await pg.tap(OPT % "Codex", wait=1.0)
        s = await said(pg)
        verdict("… Codex for the blog: asked first, where the code goes", s[0] == "confirm" and "уйдёт в OpenAI" in s[1], s)
        verdict("… and taken", await pg.until("document.querySelector('.psets .ps-model b').textContent === 'Codex'", 50)
                and "its model claude → codex" in journal(), journal()[-300:])
        await pg.js("location.hash = '#/new?pkey=' + encodeURIComponent('-Users-x-blog')")
        await pg.until("!!" + FIELD % "Кто делает", 150)
        who = await pg.js("(%s).textContent" % (FIELD % "Кто делает"))
        verdict("New task in the blog: Codex, the project's model", who.startswith("Codex"), who)
        # Codex's own model and level of effort (M4.1; the owner, 2026-10-31: "selectable effort, like Claude's")
        model = await pg.js("(%s).textContent" % (FIELD % "Модель Codex"))
        verdict("… the field shows its model and the model's own default level", model and model.strip().startswith("GPT-5.6-Sol · Мало"), model)
        await pg.tap(FIELD % "Модель Codex", wait=0.6)
        cols = await pg.js("[...document.querySelectorAll('.card.pick .pick-col')].map((c) => [...c.querySelectorAll('.opt')].map((b) => b.textContent.trim()))")
        verdict("… its picker: its models, and its levels — Ultra too", bool(cols) and cols[0][:2] == ["GPT-5.6-Sol", "GPT-5.6-Mini"]
                and "Ультра" in cols[1] and cols[1][0].startswith("По умолчанию"), cols)
        await pg.tap("[...document.querySelectorAll('.card.pick .pick-col')][1].querySelectorAll('.opt')[3]", wait=0.5)
        await pg.shot(os.path.join(OUT, "codex-pick.png"))
        await pg.tap("document.querySelector('.card.pick .x')", wait=0.5)
        model = await pg.js("(%s).textContent" % (FIELD % "Модель Codex"))
        verdict("… the level picked shows in the field", model and model.strip() == "GPT-5.6-Sol · Много", model)
        # back in the shop: another of DeepSeek's models, then the task
        await pg.tap(FIELD % "Проект")
        await pg.tap(OPT % "acme-shop", wait=0.6)
        await pg.tap(FIELD % "Модель DeepSeek", wait=0.6)
        await pg.tap(OPT % "deepseek-v4-pro[1m]", wait=0.6)
        verdict("a model of DeepSeek's list can be picked", (await pg.js("(%s).textContent" % (FIELD % "Модель DeepSeek"))).strip().startswith("deepseek-v4-pro[1m]"))
        await pg.js("const ta = document.querySelector('.form textarea'); const set = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value').set;"
                    " set.call(ta, 'Переименуй переменные темы'); ta.dispatchEvent(new Event('input', {bubbles: true})); true")
        await pg.shot(os.path.join(OUT, "new-task.png"))
        await pg.cmd("Emulation.setEmulatedMedia", features=[{"name": "prefers-color-scheme", "value": "dark"}])
        await asyncio.sleep(0.3)
        await pg.shot(os.path.join(OUT, "new-task-dark.png"))
        await pg.cmd("Emulation.setEmulatedMedia", features=[])
        await pg.tap("document.querySelector('.form .btn.wide')", wait=1.0)
        verdict("the task starts with DeepSeek and its model", "vendor=deepseek model=deepseek-v4-pro[1m]" in journal(), journal()[-300:])

        # Settings → Other vendors (within the app, as a tap there: the stand's link would only change the hash)
        await pg.js("location.hash = '#/settings'")
        verdict("Settings has «Другие производители»", await pg.until("[...document.querySelectorAll('h3')].some((h) => h.textContent === 'Другие производители')", 150))
        await pg.js(SPY)
        # the model of new projects (Q147): Claude, Codex (here), or a vendor with its key
        seg = await pg.js("[...document.querySelectorAll('.vend-all button')].map((b) => [b.textContent, b.classList.contains('on')])")
        verdict("«Модель новых проектов»: Claude (on), Codex and DeepSeek, which has a key", seg == [["Claude", True], ["Codex", False], ["DeepSeek", False]], seg)
        verdict("… its label", "Модель новых проектов" in await pg.js("document.querySelector('.vend-all-h').textContent"))
        await pg.tap("[...document.querySelectorAll('.vend-all button')].find((b) => b.textContent === 'DeepSeek')", wait=0.8)
        verdict("… DeepSeek for new projects", await pg.until("document.querySelector('.vend-all button.on').textContent === 'DeepSeek'", 30)
                and "получит эту модель" in await pg.js("document.querySelector('.vend-all-t').textContent")
                and "new projects get deepseek" in journal(), journal()[-200:])
        await pg.js("document.querySelector('.vend-all').scrollIntoView({block: 'center'})")
        await asyncio.sleep(0.3)
        await pg.shot(os.path.join(OUT, "settings-all.png"))
        VEND = "[...document.querySelectorAll('.item.vend')].find((x) => x.querySelector('b').textContent === %r)"
        st = await pg.js("[...document.querySelectorAll('.item.vend')].map((x) => x.querySelector('.vend-st').textContent)")
        verdict("DeepSeek's key is there, GLM's and Kimi's aren't; the local model is off", st == ["ключ есть", "нет ключа", "нет ключа", "выключена"], st)
        typed = ("(() => { const i = (%s).querySelector('input[type=password]'); const set = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set;"
                 " set.call(i, %%r); i.dispatchEvent(new Event('input', {bubbles: true})); return true; })()" % (VEND % "GLM"))
        await pg.js(typed % "not-a-good-key-000000")
        await pg.tap("(%s).querySelector('.keyrow .btn')" % (VEND % "GLM"), wait=1.0)
        s = await said(pg)
        verdict("a bad key is refused with the vendor's words", s[0] == "alert" and "GLM не принял ключ" in s[1] and "made up" in s[1], s)
        await pg.js(typed % "sk-made-up-good-key-000000")
        await pg.tap("(%s).querySelector('.keyrow .btn')" % (VEND % "GLM"), wait=1.0)
        s = await said(pg)
        verdict("a good one is taken", s[0] == "alert" and "GLM принял ключ" in s[1], s)
        verdict("… and shows as there", await pg.until("(%s).querySelector('.vend-st').textContent === 'ключ есть'" % (VEND % "GLM"), 30))
        verdict("… and the computer never says the key", "sk-made-up-good-key" not in journal() and "vendor glm: key set" in journal())
        models = ("(() => { const i = [...(%s).querySelectorAll('input')].at(-1); const set = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set;"
                  " set.call(i, 'glm-4.7, glm-4.5-air'); i.dispatchEvent(new Event('input', {bubbles: true})); return true; })()" % (VEND % "GLM"))
        await pg.js(models)
        await pg.tap("[...(%s).querySelectorAll('.keyrow .btn')].at(-1)" % (VEND % "GLM"), wait=1.0)
        verdict("the list of models is saved", "vendor glm: models glm-4.7, glm-4.5-air" in journal())
        await pg.js("(%s).scrollIntoView({block: 'start'})" % (VEND % "DeepSeek"))
        await asyncio.sleep(0.3)
        await pg.shot(os.path.join(OUT, "settings.png"))

        # a session on DeepSeek's model: its next turn runs now, from the app, on deepseek-v4-pro[1m]
        await pg.js("location.hash = '#/s/99999999-4444-4444-8444-444444444444'")
        verdict("a DeepSeek session says so by the field, the vendor's name not twice, no [1m]",
                await pg.until("!!document.querySelector('.mchip') && document.querySelector('.mchip').textContent.trim() === 'DeepSeek · v4-pro'", 150),
                await pg.js("document.querySelector('.mchip') && document.querySelector('.mchip').textContent"))
        verdict("… no effort dots", not await pg.js("!!document.querySelector('.mchip .dots')"))
        # the owner, 2026-10-30: "DeepSeek · deepseek-v4-pro[1m]" ran on under Stop — the name ends where Stop begins,
        # on a narrow phone too, where it ends in "…"
        apart = ("(() => { const s = document.querySelector('.ctl .btn.danger'), m = document.querySelector('.mchip'); if (!s || !m) return null;"
                 " return [m, ...m.children].every((x) => x.getBoundingClientRect().right <= s.getBoundingClientRect().left + 0.5); })()")
        verdict("… the model's name ends where Stop begins", await pg.until(apart, 30), await pg.js("document.querySelector('.mchip').outerHTML"))
        await pg.cmd("Emulation.setDeviceMetricsOverride", width=320, height=860, deviceScaleFactor=2, mobile=True)
        await asyncio.sleep(0.4)
        verdict("… on a narrow phone too", await pg.js(apart) and await pg.js("document.querySelector('.mchip > span').textContent.trim() === 'DeepSeek · v4-pro'"))
        await pg.shot(os.path.join(OUT, "session-320.png"))
        await pg.cmd("Emulation.setDeviceMetricsOverride", width=412, height=860, deviceScaleFactor=2, mobile=True)
        await asyncio.sleep(0.4)
        await pg.tap("document.querySelector('.mchip')", wait=0.6)
        opts = await pg.js("[...document.querySelectorAll('.composer .card.pick .opt')].map((b) => b.textContent.trim())")
        verdict("its picker lists only DeepSeek's models", opts == ["deepseek-flash[1m]", "deepseek-flash", "deepseek-v4-pro[1m]"], opts)
        await pg.shot(os.path.join(OUT, "session.png"))

        # Home: "Running now" says which model does each task, at the right end of its top line, beside the project
        # (the owner, 2026-10-30: two tasks running, one of them on DeepSeek — which is which?)
        await pg.js("location.hash = '#/'")
        await pg.until("document.querySelectorAll('.item.run .llm').length >= 2", 150)
        runs = await pg.js("[...document.querySelectorAll('.item.run')].map((r) => [r.querySelector('.run-t').textContent.trim(),"
                           " (r.querySelector('.llm') || {}).textContent || ''])")
        verdict("Running now: the DeepSeek task says «DeepSeek · v4-pro», the Claude one its model",
                any(m == "DeepSeek · v4-pro" and t.startswith("Переименуй") for t, m in runs) and any(m == "Opus 5.5" for t, m in runs), runs)
        top = await pg.js("[...document.querySelectorAll('.item.run .llm')].every((m) => { const r = m.closest('.item.run').getBoundingClientRect(),"
                          " w = m.parentElement.querySelector('.run-w'), b = m.getBoundingClientRect(); if (!w) return true;"
                          " const p = w.getBoundingClientRect(); return b.right <= r.right && b.left >= p.right && Math.abs(b.top - p.top) < 4; })")
        verdict("… on the top line's right end, beside the project", top)
        # Q108: the cards of "Your move" name the model too — the outcome's at its foot, across from "Got it" (on its top
        # line it pushed the tags out), a request's on its top line before how long it waits; Q109: a finished task's
        # row at the right end of its second line (the owner, 2026-10-30)
        await pg.until("!!document.querySelector('.card.mine .foot .llm')", 100)
        await pg.shot(os.path.join(OUT, "home.png"))
        mine = await pg.js("[...document.querySelectorAll('.card.mine')].map((c) => [c.querySelector('.c-title').textContent.trim(),"
                           " (c.querySelector('.foot .llm') || {}).textContent || '', !!c.querySelector('.c-proj .llm')])")
        verdict("Your move: the outcome on DeepSeek says «DeepSeek · v4-pro» at its foot, never on its top line",
                any(m == "DeepSeek · v4-pro" for _, m, _ in mine) and not any(top for _, _, top in mine), mine)
        foot = ("[...document.querySelectorAll('.card.mine .foot .llm')].every((m) => { const c = m.closest('.card'), g = m.closest('.foot').querySelector(':scope > .link'),"
                " t = c.querySelector('.c-title').getBoundingClientRect(), b = m.getBoundingClientRect(), k = g.getBoundingClientRect();"
                " return Math.abs(b.left - t.left) < 1.5 && b.right <= k.left - 8 && Math.abs(b.bottom - k.bottom) < 4; })")
        verdict("… at the foot's left edge, on the line of «Got it», short of it", await pg.js(foot))
        reqs = await pg.js("[...document.querySelectorAll('.card:not(.mine) .c-proj .llm')].map((m) => { const w = m.parentElement.querySelector('.c-wait'),"
                           " b = m.getBoundingClientRect(), k = w.getBoundingClientRect(); return [m.textContent, b.right <= k.left && Math.abs(b.top - k.top) < 4]; })")
        verdict("a request says its model on the top line, before how long it waits", len(reqs) >= 2 and all(m == "Opus 5.5" and ok for m, ok in reqs), reqs)
        rows = ("[...document.querySelectorAll('.brow .ln-row .llm')].map((m) => { const r = m.closest('.brow').getBoundingClientRect(),"
                " h = m.closest('.brow').querySelector('.item-h').getBoundingClientRect(), b = m.getBoundingClientRect();"
                " return [m.textContent, Math.abs(r.right - 14 - b.right) < 2 && b.top >= h.bottom - 1]; })")
        got = await pg.js(rows)
        verdict("a finished task's row: «Fable 5.1» at the right end of its second line", any(m == "Fable 5.1" and ok for m, ok in got) and all(ok for _, ok in got), got)
        await pg.cmd("Emulation.setDeviceMetricsOverride", width=320, height=860, deviceScaleFactor=2, mobile=True)
        await asyncio.sleep(0.4)
        narrow = await pg.js(foot) and all(ok for _, ok in await pg.js(rows))
        wait = await pg.js("[...document.querySelectorAll('.card .c-wait')].every((w) => w.getBoundingClientRect().right <= w.closest('.card').getBoundingClientRect().right)")
        verdict("… on a narrow phone too: nothing runs over «Got it», the waiting time or the row's edge", narrow and wait)
        # a request's model there is whole or gone — never "Opus 5…" — and the project's name keeps one line (320 px
        # cut the one and broke the other in two)
        whole = await pg.js("[...document.querySelectorAll('.card:not(.mine) .c-right')].map((g) => { const m = g.querySelector('.llm'),"
                            " p = g.closest('.c-proj').querySelector(':scope > span:not(.c-right):not(.av)'), b = m && m.getBoundingClientRect(), k = g.getBoundingClientRect();"
                            " return [m ? (b.top - k.top < 2 ? (m.scrollWidth <= m.clientWidth ? 'whole' : 'cut') : b.top - k.top >= 19 ? 'gone' : 'half') : 'none',"
                            " p ? p.getBoundingClientRect().height < 24 : true]; })")
        verdict("… a request's model whole or gone, the project's name on one line", len(whole) >= 2 and all(m in ("whole", "gone") and one for m, one in whole), whole)
        await pg.shot(os.path.join(OUT, "home-320.png"))
        await pg.cmd("Emulation.setDeviceMetricsOverride", width=412, height=860, deviceScaleFactor=2, mobile=True)
        await asyncio.sleep(0.4)
        # a project's screen: its "Waiting for you" says the same
        await pg.js("location.hash = '#/p/' + encodeURIComponent('-Users-x-proj')")     # the shop's: the tests' project key
        await pg.until("!!document.querySelector('.project .card.mine .foot .llm')", 100)
        proj = await pg.js("[(document.querySelector('.project .card.mine .foot .llm') || {}).textContent,"
                           " (document.querySelector('.project .card:not(.mine) .c-proj .llm') || {}).textContent]")
        verdict("a project's screen: the outcome's foot and the request's top line name the model", proj == ["DeepSeek · v4-pro", "Opus 5.5"], proj)
        await pg.shot(os.path.join(OUT, "project.png"))
        verdict("no script errors on the page", not pg.errors, pg.errors)
    print("screenshots:", OUT)
    sys.exit(verdict.code())


asyncio.run(main())
