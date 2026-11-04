"""A project belongs to one model (stage M, step 7.2), in headless Chrome over DevTools, on the stand where the shop is
DeepSeek's and busy (STAND_VENDORS=1), the support desk DeepSeek's too, its weekly report — Claude's — waiting
(STAND_DESK=deepseek STAND_REPORT=1), the blog Claude's, nothing running there: the project's screen names its model under
the name, has a gear to its settings and says when Claude works in it on the computer though the project is another
model's (Q144). The settings page: the model — a change waits while anything runs, the sheet and a tap say what; the helper
Claude haiku — off with DeepSeek, on asks what it costs the isolation (Q142); the topic — "Request and outcome" or "Only
“done”" (Q145); the review; tags, pin, hide. The blog's model changed to DeepSeek: GLM without a key says where to add one,
the change says where the code goes and what the helper does — "no" changes nothing, "yes" does. The desk's report is read
only: "Your move" has no answer under it; Claude's task in the shop — its screen no field, but "read only" and the way to
the settings (Q148).
New project: the model of new projects by default, another picked asks where the code goes. Light and dark, 412 and 320 px.
  STAND_VENDORS=1 STAND_HOMES=1 STAND_REPORT=1 STAND_DESK=deepseek STAND_LANG=ru STAND_PORT=18173 HOLD=300 ~/.local/share/pult/venv/bin/python tools/stand.py > /tmp/stand.out &
  ~/.local/share/pult/venv/bin/python tools/projset_check.py /tmp/stand.out [out_dir]
Screenshots go to out_dir (a temporary folder by default). Exit 1 on a failed check."""
import asyncio
import os
import sys
import tempfile

import _cdp

STAND = sys.argv[1]
URLS = _cdp.stand_urls(STAND, ("PROJ",))
OUT = sys.argv[2] if len(sys.argv) > 2 else tempfile.mkdtemp(prefix="pult-projset-")
os.makedirs(OUT, exist_ok=True)
verdict = _cdp.Verdicts()
SPY = """(() => { window.__said = []; window.__yes = false;
  window.alert = (s) => { window.__said.push(['alert', String(s)]); };
  window.confirm = (s) => (window.__said.push(['confirm', String(s)]), window.__yes);
  const w = window.Telegram && window.Telegram.WebApp;
  if (w) { w.showAlert = (s, cb) => { window.__said.push(['alert', String(s)]); cb && cb(); };
           w.showConfirm = (s, cb) => (window.__said.push(['confirm', String(s)]), cb(window.__yes)); }
  return true; })()"""
OPT = "[...document.querySelectorAll('.card.pick .opt')].find((b) => b.textContent.trim().startsWith(%r))"
MODEL = "document.querySelector('.psets .ps-model')"
NOW = "document.querySelector('.psets .ps-model b').textContent"
SW = "document.querySelector('.psets .sw-h')"
TOPIC = "[...document.querySelectorAll('.psets .ps-topic button')]"
BLOG = "'-Users-x-blog'"
DARK = [{"name": "prefers-color-scheme", "value": "dark"}]


def journal():
    with open(STAND, encoding="utf-8", errors="replace") as f:
        return f.read()


async def said(pg):
    return await pg.js("window.__said.at(-1)") or ["", ""]


async def settings(pg, pkey):
    await pg.js("location.hash = '#/ps/' + encodeURIComponent(%s)" % pkey)
    ok = await pg.until("!!%s && location.hash.includes(%s)" % (MODEL, repr("/ps/")), 150)
    await pg.js(SPY)
    return ok


async def both(pg, name):
    await pg.shot(os.path.join(OUT, name + ".png"))
    await pg.cmd("Emulation.setEmulatedMedia", features=DARK)
    await asyncio.sleep(0.3)
    await pg.shot(os.path.join(OUT, name + "-dark.png"))
    await pg.cmd("Emulation.setEmulatedMedia", features=[])


async def narrow(pg, name):
    """At 320 px: nothing runs over the screen's edge."""
    await pg.cmd("Emulation.setDeviceMetricsOverride", width=320, height=860, deviceScaleFactor=2, mobile=True)
    await asyncio.sleep(0.4)
    fits = await pg.js("[...document.querySelectorAll('.psets .field, .psets .seg button, .psets .item, .psets .vline')]"
                       ".every((e) => e.getBoundingClientRect().right <= innerWidth + 0.5)")
    await pg.shot(os.path.join(OUT, name + "-320.png"))
    await pg.cmd("Emulation.setDeviceMetricsOverride", width=412, height=860, deviceScaleFactor=2, mobile=True)
    await asyncio.sleep(0.4)
    return fits


async def main():
    async with _cdp.Page() as pg:
        # the shop's screen: its model under the name, the gear, Claude working in it on the computer
        await pg.open(URLS["PROJ"])
        verdict("the project's screen names its model under its name", await pg.until(
            "!!document.querySelector('.ph .ph-model') && document.querySelector('.ph .ph-model').textContent.startsWith('Модель: DeepSeek')", 150),
            await pg.js("(document.querySelector('.ph .ph-model') || {}).textContent"))
        verdict("… has a gear beside the pin", await pg.js("!!document.querySelector('.ph .gearb') && !!document.querySelector('.ph .pinb:not(.gearb)')"))
        warn = await pg.js("(document.querySelector('.project .vline.warn') || {}).textContent || ''")
        verdict("… and says Claude works in it on the computer, outside its isolation (Q144)", "работает Claude" in warn and "DeepSeek" in warn, warn)
        verdict("… the old line «Код проекта можно отдавать…» is gone from it", not await pg.js(
            "[...document.querySelectorAll('.project .vline')].some((v) => v.textContent.includes('Код проекта можно отдавать'))"))
        await both(pg, "project")
        await pg.tap("document.querySelector('.ph .gearb')", wait=0.8)
        verdict("the gear opens the project's settings", await pg.until("!!" + MODEL + " && location.hash.startsWith('#/ps/')", 100))
        await pg.js(SPY)
        verdict("… «Настройки проекта» over the project's name", await pg.js(
            "document.querySelector('.psets .ph h2').textContent === 'Настройки проекта' && document.querySelector('.psets .ph .sum').textContent === 'acme-shop'"))
        m = await pg.js("%s.textContent" % MODEL)
        verdict("… the model: DeepSeek and its main model", m.strip() == "DeepSeek · deepseek-flash[1m]", m)
        busy = await pg.js("document.querySelector('.psets .ps-busy') && document.querySelector('.psets .ps-busy').textContent")
        verdict("… something runs in it: the change can't be now, it says what", bool(busy) and busy.startswith("Сейчас сменить нельзя: в проекте идут «"), busy)
        h = await pg.js("[%s.getAttribute('aria-checked'), %s.closest('.item').querySelector('.dim').textContent]" % (SW, SW))
        verdict("… the helper Claude haiku is off with DeepSeek, and says what it would cost", h[0] == "false" and "Выключен: строка итога — первая фраза ответа" in h[1], h)
        seg = await pg.js("%s.map((b) => [b.textContent, b.classList.contains('on')])" % TOPIC)
        verdict("… the topic: «Запрос и итог» (on) or «Только «готово»»", seg == [["Запрос и итог", True], ["Только «готово»", False]], seg)
        rev = await pg.js("document.querySelector('.psets .ps-review').textContent")
        verdict("… the review: only by your tap, what the reviewer sees", "только по твоему касанию" in rev and "не переписку и память" in rev, rev)
        rows = await pg.js("[...document.querySelectorAll('.psets .ps-row')].map((r) => r.textContent.trim())")
        verdict("… the project's tags, pin and hide", rows == ["Теги проекта", "Закрепить", "Спрятать"], rows)
        await both(pg, "settings-shop")
        verdict("… on 320 px nothing runs over the edge", await narrow(pg, "settings-shop"))
        # the change while something runs: the sheet says it, a tap too
        await pg.tap(MODEL, wait=0.6)
        names = await pg.js("[...document.querySelectorAll('.card.pick.who .opt')].map((b) => [b.firstChild.textContent, b.classList.contains('on'), b.classList.contains('vo-off')])")
        verdict("the sheet: every model, DeepSeek ticked, GLM and Kimi and one's own grey",
                names == [["Claude", False, False], ["Codex", False, False], ["DeepSeek", True, False], ["GLM", False, True], ["Kimi", False, True],
                          ["Своя модель", False, True]], names)
        verdict("… on top of it — why it can't change now", (await pg.js("(document.querySelector('.card.pick.who .pick-why') || {}).textContent") or "").startswith("Сейчас сменить нельзя"))
        await pg.shot(os.path.join(OUT, "sheet-busy.png"))
        await pg.tap(OPT % "Claude", wait=0.6)
        s = await said(pg)
        verdict("… a tap on Claude: not now, what runs", s[0] == "alert" and s[1].startswith("Сейчас сменить нельзя: в проекте идут «"), s)
        verdict("… nothing changed", await pg.js(NOW) == "DeepSeek" and "its model deepseek" not in journal())
        await pg.tap("document.querySelector('.card.pick .x')", wait=0.4)
        # the helper on: asked what it costs — "no" keeps it off, "yes" turns it on
        await pg.tap(SW, wait=0.6)
        s = await said(pg)
        verdict("the helper on asks: the tasks' words go to Anthropic", s[0] == "confirm" and "уходить в Anthropic" in s[1] and "изоляция проекта нарушится" in s[1], s)
        verdict("… «no» keeps it off", await pg.js("%s.getAttribute('aria-checked')" % SW) == "false")
        await pg.js("window.__yes = true")
        await pg.tap(SW, wait=0.8)
        verdict("… «yes» — on, and it says the isolation is broken", await pg.until(
            "%s.getAttribute('aria-checked') === 'true' && %s.closest('.item').querySelector('.dim').textContent.includes('изоляция проекта нарушена')" % (SW, SW), 50)
            and "the helper Claude haiku on" in journal())
        await pg.tap(TOPIC + "[1]", wait=0.8)
        verdict("the topic: «Только «готово»» — on, what it means", await pg.until(TOPIC + "[1].classList.contains('on')", 50)
                and "Слова задачи в Telegram не уходят" in await pg.js("document.querySelector('.psets .ps-topic').nextElementSibling.textContent")
                and "its topic gets only “done”" in journal())
        await both(pg, "settings-shop-on")

        # the blog: Claude's, nothing runs — its model changes
        verdict("the blog's settings", await settings(pg, BLOG))
        m = await pg.js("%s.textContent" % MODEL)
        verdict("… Claude, your subscription", m.startswith("Claude") and "твоя подписка" in m, m)
        verdict("… nothing runs: it can be changed", not await pg.js("!!document.querySelector('.psets .ps-busy')")
                and "Сменить можно, когда в проекте ничего не идёт" in await pg.js("%s.nextElementSibling.textContent" % MODEL))
        h = await pg.js("[%s.getAttribute('aria-checked'), %s.closest('.item').querySelector('.dim').textContent]" % (SW, SW))
        verdict("… the helper on with Claude", h[0] == "true" and "по твоей подписке" in h[1], h)
        await both(pg, "settings-blog")
        await pg.tap(MODEL, wait=0.6)
        await pg.tap(OPT % "GLM", wait=0.6)
        s = await said(pg)
        verdict("GLM without a key says where to add one", s[0] == "alert" and "ключа ещё нет" in s[1] and "Другие производители" in s[1], s)
        await pg.tap(OPT % "DeepSeek", wait=0.8)              # the sheet stays open after the word on GLM
        s = await said(pg)
        verdict("DeepSeek: asked first — the code goes to it, Claude's conversations stay, the helper turns off",
                s[0] == "confirm" and "Сменить модель проекта на «DeepSeek»?" in s[1] and "его код уйдёт в DeepSeek" in s[1]
                and "Переписка и память модели «Claude» останутся у неё" in s[1] and "Помощник Claude haiku выключится" in s[1], s)
        verdict("… «no» changes nothing", await pg.js(NOW) == "Claude" and "its model claude → deepseek" not in journal())
        await pg.js("window.__yes = true")
        await pg.tap(MODEL, wait=0.6)
        await pg.tap(OPT % "DeepSeek", wait=1.0)
        verdict("… «yes» — DeepSeek, the helper off", await pg.until(NOW + " === 'DeepSeek' && %s.getAttribute('aria-checked') === 'false'" % SW, 50)
                and "its model claude → deepseek" in journal(), journal()[-300:])
        await pg.shot(os.path.join(OUT, "settings-blog-deepseek.png"))

        # the desk's report — Claude's, in a project of DeepSeek — is read only: no answer from "Your move"
        await pg.js("location.hash = '#/'")
        await pg.until("!!document.querySelector('.card.mine')", 150)
        card = "[...document.querySelectorAll('.card.mine')].find((c) => c.querySelector('.ro-l'))"
        verdict("Your move: Claude's task in a project of DeepSeek is read only — no answer under it",
                await pg.until("!!(%s)" % card, 100) and not await pg.js("!!(%s).querySelector('.own, .reply, textarea, input')" % card),
                await pg.js("[...document.querySelectorAll('.card.mine')].map((c) => c.textContent.slice(0, 80))"))
        verdict("… «Проверено» still puts it away", await pg.js("!!(%s).querySelector('.foot .link')" % card))
        await pg.js("(%s).scrollIntoView({block: 'center'})" % card)
        await asyncio.sleep(0.3)
        await both(pg, "home-ro")
        await pg.js("location.hash = '#/s/11111111-2222-3333-4444-555555555555'")      # the shop's Claude task (the stand's SESS)
        verdict("the shop's Claude task: read only, no field, the way to the settings", await pg.until("!!document.querySelector('.ro-bar')", 150)
                and not await pg.js("!!document.querySelector('.composer textarea')"))
        ro = await pg.js("document.querySelector('.ro-bar').textContent")
        verdict("… it says whose task it was and whose the project is", "«Claude» — только для чтения" in ro and "«DeepSeek»" in ro, ro)
        await both(pg, "session-ro")
        await pg.tap("document.querySelector('.ro-bar .link')", wait=0.8)
        verdict("… «Настройки» opens the project's settings", await pg.until("location.hash.startsWith('#/ps/') && !!" + MODEL, 100))

        # a new project: the model of new projects by default, another one asks where the code goes
        await pg.js("location.hash = '#/newproject'")
        FIELD = "[...document.querySelectorAll('.form .field')].find((b) => b.previousElementSibling && b.previousElementSibling.textContent.trim() === 'Модель проекта')"
        verdict("New project has «Модель проекта» — Claude by default", await pg.until(
            "!!(%s) && (%s).textContent.startsWith('Claude')" % (FIELD, FIELD), 150))
        await pg.js(SPY)
        await pg.tap(FIELD, wait=0.6)
        await pg.tap(OPT % "DeepSeek", wait=0.8)
        s = await said(pg)
        verdict("… DeepSeek asks: the code goes to it", s[0] == "confirm" and "Код проекта уйдёт в DeepSeek" in s[1], s)
        await pg.js("window.__yes = true")
        await pg.tap(OPT % "DeepSeek", wait=0.8)
        verdict("… «yes» picks it", await pg.until("(%s).textContent.startsWith('DeepSeek')" % FIELD, 50))
        await both(pg, "newproject")
        verdict("no script errors on the page", not pg.errors, pg.errors)
    print("screenshots:", OUT)
    sys.exit(verdict.code())


asyncio.run(main())
