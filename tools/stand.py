"""Web app test stand: a local relay (127.0.0.1:18097) + the daemon with a fake Telegram and made-up sessions:
one working, one waiting for a permission, one waiting for an answer, jobs without Claude, a final result. Login
is signed with test keys (tests/test_web.py). Prints the screen URLs (HOME, SESS, USAGE, SETTINGS, NEW, PROJ, PROJECTS,
LOAD, NEWPROJ), stays up HOLD s.

  HOLD=300 ~/.local/share/pult/venv/bin/python tools/stand.py > /tmp/stand.out &
  ~/.local/share/pult/venv/bin/python tools/shot.py "$(grep ^HOME /tmp/stand.out | cut -d' ' -f2)" home.png 412 4 [dark]

Telegram passes initData in the URL after # (tgWebAppData=…); that is how the stand opens the app without Telegram.
STAND_STT=<folder> turns the microphone on: recordings are saved there instead of going to Groq, STAND_STT_OLD=1 makes
the computer refuse the recording's notes as one before 0.14.2 does. Usage is stubbed (38 % of the 5-hour window, 71 % of the week, a made-up week of work): the real request launches Claude Code. The data is made up and neutral — the screenshots go
into the public README: STAND_LANG=en|ru picks the texts, STAND_XSS=1 adds markup that must stay text, STAND_ASK2=1
gives the question a second one, a second session waiting for you and a permission older than it, STAND_ADVICE=1
makes it a question of several answers with Claude's advice among them (tools/advice_check.py), STAND_QUEUE=1 puts a turn in the queue (all places taken), STAND_UPD=ok|ready|busy|
wait|run|fail shows Settings → Pult and Home's line in that state (no installer ever runs) — with STAND_UPD=ready,
STAND_RESTART=answered|lost makes Install stop the stand's daemon as the real installer stops Pult: nothing answered
from the tap on, the link to the relay down for a second (lost: before the tap's own answer goes out), back, checking
itself for 4 s, then nothing newer (tools/update_check.py); STAND_PORT=<port> runs a second stand beside one already up. STAND_TICKS=<s> opens the first session in a tab that reads each message <s> s
later, as Claude Code does at its turn's next step — a message with "#gone" is dropped instead (tools/ticks_check.py).
STAND_FILES=1 gives the shop a real folder with made-up files and ends the chat with links to them (tools/fileview_check.py).
Settings' table of Pult's parts and Home's line always run on made-up facts — all fresh; STAND_PARTS=now|lag|bad|public:
all as in main with a new Claude Code downloaded; several parts behind (with STAND_UPD=ready for the computer); hooks
missing and tabs on an unverified Claude Code; someone with a clone of the public repository after a `git pull` (no
release row, no tab wrapper; STAND_UPD=ready) (tools/parts_check.py); STAND_PARTS=auto|auto_run|auto_fail — that clone
with the server's updater (stage U3): the server took the computer's release; is taking it; didn't take it and went back
STAND_TAGS=1 (stage T): a third project, a maker of 3D printers, fifteen tasks in every state, each with its section and
topic in the store (PROJT — its screen, SESST — its task that waits for you; tools/tags_check.py); T2 — Claude's offer to
merge two of its topics, on the project's tags screen. STAND_TAGJOB=1 with it: twelve earlier tasks without tags and a
made-up model — Claude sorts them on the first open, "Sort them again" makes the list anew (tags_check.py, its last part).
STAND_PARTS=check_run|check_fail|check_here|check_err (stage A): Pult's own check of a Claude Code version VS Code has
downloaded — running, failed at a step, passed, couldn't run; "Check again" passes in 3 s, no Claude (tools/vcheck_check.py).
STAND_HOMES=1 (stage Zh): the three made-up projects get real folders, so the Projects screen lists them (without it only the
printer's has one); STAND_PINS=blog,shop — these pinned, in that order, the last one the newest; STAND_HIDES=desk — hidden
(tools/pins_check.py).
STAND_COPY=1: the session that waits for you is open in a VS Code tab on a Claude Code Pult isn't checked on — its card
says "goes as a copy" before you type, and sending says why (tools/copy_check.py).
STAND_SECOND=1 (stage M, step 1): the shop is a git repository whose search the task changed, and Codex is a stand-in
(tests/fake_codex.py) that reads it for about five seconds and finds two things; the session that waits for you (SESS4)
offers "Second opinion · Codex" under its outcome (tools/second_check.py). STAND_SECOND=allowed — the shop already allowed.
STAND_VENDORS=1 (stage M, step 2): DeepSeek has a made-up key (GLM and Kimi none), a key's check passes "sk-…" without any
network, and a session ran on DeepSeek's model (SESSV) — its next turn runs now, from the app, on deepseek-v4-pro[1m];
the session that waits for you (SESS4) ran on DeepSeek too, the weekly report on Fable — the cards and rows name the model;
"Who does it" in New task, Settings → Other vendors (tools/vendors_check.py). STAND_REPORT=1: the weekly report hasn't
been put away — a plain report waits in "Your move" for "Got it" like any other (tools/gotit_check.py); without it (and
without STAND_ASK2) the owner has put it away. VS Code's settings and the tab switch are made up on every stand: the app
never reads this computer's."""
import asyncio, base64, hashlib, hmac, json, os, random, shutil, signal, sys, time, urllib.parse
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tests"))
import test_web as W  # noqa: E402  (keys, relay with the test key)
T, PW, pultd, relay = W.T, W.PW, W.pultd, W.relay
import pult_api  # noqa: E402
import pult_hook  # noqa: E402
import pult_parts  # noqa: E402
import pult_load as L  # noqa: E402
import pult_update as U  # noqa: E402
import pult_setup  # noqa: E402  (the Claude Code versions the wrapper is checked on)

# Pult's folder must be the tests' temporary one: pultd imported before test_pult set PULT_HOME keeps the real
# ~/.local/share/pult, and the stand would write its made-up install history there (it did, 2026-10-26)
import pult_tabcheck  # noqa: E402  (it deletes its own transcripts: the stand's must be the tests' folder too)
for _home in (pultd.HOME, U.HOME, pultd.CLAUDE_PROJECTS, pult_tabcheck.PROJECTS):
    if not Path(_home).resolve().is_relative_to(Path(T.TMP).resolve()):
        sys.exit("stand: Pult's folder is %s, not a temporary one — run tools/stand.py as a script of its own" % _home)
# stopped by a signal, as tools/check.py and the checks with stands of their own stop it: its temporary folder goes
# with it at once (a plain SIGTERM skipped that — one run of all checks left 36 — and the orderly way, the web
# server's cleanup, waits up to a minute for the connections still open)
signal.signal(signal.SIGTERM, lambda *a: (shutil.rmtree(T.TMP, ignore_errors=True), os._exit(0)))
from aiohttp import web  # noqa: E402

HOLD = float(os.environ.get("HOLD", "90"))
PORT = int(os.environ.get("STAND_PORT", "18097"))   # another one for a second stand at the same time
LANG = os.environ.get("STAND_LANG", "en")
SID2 = "22222222-2222-4222-8222-222222222222"
SID3 = "33333333-3333-4333-8333-333333333333"
SID4, SID5, SID6, SID7 = ("%s-4444-4444-8444-444444444444" % (c * 8) for c in "4567")
SIDV = "99999999-4444-4444-8444-444444444444"      # STAND_VENDORS=1: a session on DeepSeek's model
SHOP, DESK = "/Users/x/acme-shop", "/Users/x/support-desk"
PKEY2 = "-Users-x-support-desk"

# Made-up sessions in two languages. Nothing here may be about real projects: it ends up on the public page.
D = {
    "en": dict(
        title="Checkout: clearer error messages",
        ask="Make the checkout error messages clearer, following the examples in the design doc",
        ask_short="Make the checkout error messages clearer",
        look="Here's the design doc",
        read="I've read the checkout module. Now the tests: the new messages have to fit them.",
        summary="## Summary\n\nAll **27 tests** pass. What changed:\n\n- a declined card says why and what to do;\n"
                "- a timeout offers to try again.\n\n| case | before | after |\n|---|---|---|\n"
                "| declined | Error 402 | Card declined — try another card |\n| timeout | Error | Timed out — try again |\n\n"
                "```\nmake deploy-staging\n```\nPreview: [staging](https://example.com)",
        bg_done="Background command \"Run the end-to-end tests\" completed (exit code 0)",
        after_bg="The end-to-end tests passed too: card, timeout and retry all show the new messages.",
        now="Deploying to staging and checking the checkout page there.",
        cmd="make deploy-staging && git commit -qm 'Checkout: clearer errors'", cmd_desc="Deploy to staging and commit",
        tickets="Sort the new support tickets", question="Which tickets should I start with?", header="Order",
        opt1="Urgent", opt1d="due tonight", opt2="Oldest first",
        question2="Reply to the customers as well?", header2="Replies", opt3="Yes, briefly", opt4="No, only sort",
        question3="What else should I do with the tickets?", header3="Also", opt5="Reply briefly (Recommended)",
        opt6="Tag them in the CRM", opt7="Merge the duplicates (Recommended)",
        tickets_done="Sorted **12 tickets**: 3 urgent, 9 can wait. The list is in the report.",
        bg_run="Export the tickets to the CRM", bg_cmd="python scripts/export_tickets.py --to crm",
        job_last="epoch 27/40 · loss 0.31", user="Sam",
        s4_report="Typo-tolerant search is in. What I did:\n\n- the index keeps trigrams of every product name;\n"
                  "- a query with one or two typos still finds the product;\n- results are ranked by how close the match is.\n\n"
                  "Checked on last month's 500 most frequent queries: 97 % find what they found before, and 41 queries that "
                  "found nothing now find the right product. The slowest query takes 38 ms instead of 31 ms.\n\n"
                  "There are two ways to rank the results, and on short queries their first pages differ.",
        s4_title="Search: typo-tolerant results", s4_line="Typo-tolerant search works; two ways to rank the results",
        s4_need="Pick the ranking: by popularity or by closeness", s4_r1="By popularity", s4_r2="By closeness",
        s4_r3="Explain the difference", s5_title="Weekly support report",
        s5_line="The weekly report is ready: 48 tickets, 2 overdue", s6_title="Images: WebP thumbnails",
        s7_ask="Add a dark theme to the admin panel", s7_now="Colours are variables now; the tables and charts are next.",
        v_ask="Rename the admin theme's CSS variables to the new scheme",
        v_done="Renamed 14 variables in admin/theme.css; nothing else used the old names.",
        v_ask2="Now the same for the storefront's theme"),
    "ru": dict(
        title="Оформление заказа: понятные ошибки",
        ask="Сделай сообщения об ошибках при оплате понятнее, по примерам из макета",
        ask_short="Сделай сообщения об ошибках при оплате понятнее",
        look="Вот макет",
        read="Модуль оплаты прочитан. Теперь тесты: новые сообщения должны в них вписаться.",
        summary="## Итог\n\nВсе **27 тестов** зелёные. Что поменялось:\n\n- отказ по карте объясняет причину и что делать;\n"
                "- при тайм-ауте — предложение повторить.\n\n| случай | было | стало |\n|---|---|---|\n"
                "| отказ | Error 402 | Карта отклонена — попробуйте другую |\n| тайм-аут | Error | Не дождались ответа — повторите |\n\n"
                "```\nmake deploy-staging\n```\nПосмотреть: [стенд](https://example.com)",
        bg_done="Background command \"Прогон сквозных тестов\" completed (exit code 0)",
        after_bg="Сквозные тесты тоже прошли: отказ, тайм-аут и повтор показывают новые сообщения.",
        now="Выкладываю на стенд и проверяю там страницу оплаты.",
        cmd="make deploy-staging && git commit -qm 'Checkout: clearer errors'", cmd_desc="Выложить на стенд и закоммитить",
        tickets="Разбери новые заявки в поддержку", question="С каких заявок начать?", header="Порядок",
        opt1="Срочные", opt1d="до вечера", opt2="Сначала старые",
        question2="Отвечать ли клиентам?", header2="Ответы", opt3="Да, коротко", opt4="Нет, только разобрать",
        question3="Что ещё сделать с заявками?", header3="Ещё", opt5="Ответить коротко (Рекомендую)",
        opt6="Пометить в CRM", opt7="Объединить дубли (Рекомендую)",
        tickets_done="Разобрал **12 заявок**: 3 срочные, 9 подождут. Список — в отчёте.",
        bg_run="Выгрузка заявок в CRM", bg_cmd="python scripts/export_tickets.py --to crm",
        job_last="эпоха 27/40 · потери 0,31", user="Саша",
        s4_report="Поиск с опечатками готов. Что сделал:\n\n- индекс хранит триграммы названий товаров;\n"
                  "- запрос с одной-двумя опечатками всё равно находит товар;\n- результаты сортируются по близости совпадения.\n\n"
                  "Проверил на 500 самых частых запросах прошлого месяца: 97 % находят то же, что раньше, а 41 запрос, который "
                  "не находил ничего, теперь находит нужный товар. Самый медленный запрос — 38 мс вместо 31.\n\n"
                  "Сортировать можно двумя способами, и на коротких запросах первая страница у них разная.",
        s4_title="Поиск: опечатки", s4_line="Поиск с опечатками работает; есть два способа сортировки",
        s4_need="Выбери сортировку: по популярности или по точности", s4_r1="По популярности", s4_r2="По точности",
        s4_r3="Объясни разницу", s5_title="Отчёт поддержки за неделю",
        s5_line="Отчёт за неделю готов: 48 заявок, 2 просрочены", s6_title="Картинки: превью WebP",
        s7_ask="Сделай тёмную тему для админки", s7_now="Цвета вынесены в переменные; дальше — таблицы и графики.",
        v_ask="Переименуй CSS-переменные темы админки по новой схеме",
        v_done="Переименовал 14 переменных в admin/theme.css; старые имена больше нигде не используются.",
        v_ask2="Теперь то же для темы витрины"),
}[LANG if LANG in ("en", "ru") else "en"]


def init(start):
    f = {"auth_date": str(int(time.time())), "chat_type": "supergroup", "chat_instance": "1", "start_param": start,
         "user": json.dumps({"id": T.OWNER, "first_name": D["user"]})}
    dcs = "777:WebAppData\n" + "\n".join("%s=%s" % (k, f[k]) for k in sorted(f))
    f["signature"] = base64.urlsafe_b64encode(W.KEY.sign(dcs.encode())).decode().rstrip("=")
    secret = hmac.new(b"WebAppData", W.TOKEN.encode(), hashlib.sha256).digest()
    f["hash"] = hmac.new(secret, "\n".join("%s=%s" % (k, f[k]) for k in sorted(f)).encode(), hashlib.sha256).hexdigest()
    return urllib.parse.urlencode(f)


def line(kind, content, ago=0):
    return json.dumps({"type": kind, "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime(time.time() - ago)),
                       "message": {"role": kind, "content": content}})


def aline(text, mid, out, ago=0):
    """A model reply with token counts — the session card and "today by project" count these."""
    return json.dumps({"type": "assistant", "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime(time.time() - ago)),
                       "message": {"id": mid, "model": "claude-opus-5-5", "role": "assistant",
                                   "content": [{"type": "text", "text": text}],
                                   "usage": {"input_tokens": 2, "cache_read_input_tokens": 120000, "output_tokens": out}}})


def week_of_work(root, now):
    """A made-up week for Resources (stage R): turns in three projects in the daytime, now and then two or three at
    once, an agent here and there, some on Fable. Seeded, so the screenshots repeat."""
    rnd = random.Random(7)
    iso = lambda ts: time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime(ts))
    homes = [Path(T.TP).parent, root / PKEY2, root / "-Users-x-blog"]
    for n in range(26):
        day = rnd.randrange(0, 7)
        start = now - day * 86400 - rnd.uniform(0.5, 14) * 3600
        if start > now - 1800:
            continue
        home, model = rnd.choice(homes[:2] * 3 + homes[2:]), "claude-fable-5-1" if rnd.random() < 0.2 else "claude-opus-5-5"
        sid = "%08x-0000-4000-8000-%012x" % (n, n)
        rows, ts = [json.dumps({"type": "user", "timestamp": iso(start), "message": {"role": "user", "content": "…"}})], start
        for k in range(rnd.randrange(8, 40)):
            ts += rnd.uniform(40, 240)
            if ts > now - 60:
                break
            rows.append(json.dumps({"type": "assistant", "timestamp": iso(ts), "message": {
                "id": "w%d-%d" % (n, k), "model": model, "role": "assistant", "content": [], "stop_reason": "tool_use",
                "usage": {"input_tokens": 3, "cache_read_input_tokens": rnd.randrange(40000, 160000),
                          "cache_creation_input_tokens": rnd.randrange(500, 6000), "output_tokens": rnd.randrange(200, 3000)}}}))
        rows.append(rows[-1].replace('"tool_use"', '"end_turn"').replace('"id": "w', '"id": "e'))
        (home / (sid + ".jsonl")).write_text("\n".join(rows) + "\n")
        if rnd.random() < 0.25:                           # an agent of that session
            (home / sid / "subagents").mkdir(parents=True, exist_ok=True)
            (home / sid / "subagents" / "agent-a.jsonl").write_text("\n".join(r.replace('"id": "w', '"id": "a') for r in rows[1:6]) + "\n")


def png_sample(w=320, h=200):
    """A small made-up picture for the owner's message: coloured bands, no real content."""
    import struct, zlib
    rows = b""
    for y in range(h):
        band = (y * 4) // h
        rgb = [(214, 226, 244), (122, 164, 220), (60, 110, 190), (34, 70, 140)][band]
        rows += b"\x00" + bytes(rgb) * w
    def chunk(t, b):
        return struct.pack(">I", len(b)) + t + b + struct.pack(">I", zlib.crc32(t + b) & 0xffffffff)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)) + \
        chunk(b"IDAT", zlib.compress(rows)) + chunk(b"IEND", b"")


def ev(name, sid, cwd=SHOP, **kw):
    folder = Path(T.TP).parent if cwd == SHOP else Path(T.TP).parent.parent / PKEY2
    return dict(hook_event_name=name, session_id=sid, transcript_path=str(folder / (sid + ".jsonl")), cwd=cwd, **kw)


# STAND_TAGS=1 (stage T): a third project — a maker of 3D printers — with fifteen tasks in every state, each with its
# section and topic as Claude would have given them (made two days ago; one topic a moment ago — the app draws it
# dashed); the shop's and the desk's tasks get a section and a topic too. The tags go into the store: the daemon's own
# code hands them to the app (tools/tags_check.py)
TAGS_D = {
    "en": dict(
        name="Printer", secs=["Firmware", "Frame", "Electronics", "Marketing", "Slicer", "Extruder", "Docs"],
        merge=["Wi-Fi", "Network updates"], docs=("Docs", "Manuals", "Manual"),
        untagged=["Bed levelling after a spring swap", "Network updates: a rollback", "Strength of the frame at 2 kg",
                  "Mounts for the end stops", "Power from 24 V", "Cooling the drivers", "Profiles for ABS",
                  "Nozzles of hardened steel", "Sensors on the door: a pause", "Customers abroad: shipping",
                  "Trade show in Berlin: the stand", "Assembly of the Z axis, chapter 4", "Manual for users, part 2"],
        shop=[("Checkout", "Errors"), ("Search", "Typos"), ("Images", "Thumbnails"), ("Admin", "Dark theme")],
        desk=[("Tickets", "Sorting"), ("Reports", "Weekly")],
        tasks=[
            dict(st="you", ago=1500, tag=("Electronics", "Drivers"), title="Why the layers shift after three hours of printing",
                 line="The X driver overheats; there are two ways to fix it", need="Pick: lower the motor current or add a heatsink",
                 replies=["Lower the current", "Add a heatsink", "Explain the difference"]),
            dict(st="work", ago=660, tag=("Extruder", "Sensors"), title="Add a filament runout sensor",
                 ask="And if the filament runs out mid-layer, does the print stop at once or finish the layer?",
                 now="At once: the firmware pauses mid-layer and parks the nozzle at the edge so it doesn't melt the part. "
                     "Now checking that after a reload the print goes on from the same point.", edit="firmware/runout.c"),
            dict(st="work", ago=240, tag=("Marketing", "Trade show"), fresh=True, title="Prepare the trade show page",
                 ask="Add a table: how the new model beats the old one — speed, noise, price", edit="marketing/show/page.md"),
            dict(st="bg", ago=900, tag=("Frame", "Strength"), title="Run a strength check on the frame",
                 line="The frame simulation under 40 kg is running; the outcome when it ends", bg="Frame strength simulation",
                 bg_cmd="python sim/frame_fea.py --load 40"),
            dict(st="idle", ago=2400, tag=("Electronics", "Power"), title="Power board: reverse polarity protection",
                 line="Added a diode and a fuse; the schematic and the parts list are updated"),
            dict(st="idle", ago=4200, tag=("Slicer", "Profiles"), title="A PETG profile for the slicer",
                 line="The profile is ready: 240 °C, 30 % fan, a clean test print"),
            dict(st="idle", ago=7800, tag=("Frame", "Mounts"), title="A display mount on the frame",
                 line="The mount is redrawn and prints without supports"),
            dict(st="old", ago=86400 + 3600, tag=("Marketing", "Customers"), title="Answers to customers' common questions"),
            dict(st="old", ago=86400 + 9000, tag=("Firmware", "Levelling"), title="25-point bed levelling"),
            dict(st="old", ago=2 * 86400, tag=("Extruder", "Nozzles"), title="A 0.6 mm nozzle: flow settings"),
            dict(st="old", ago=3 * 86400, tag=("Firmware", "Wi-Fi"), title="Firmware updates over Wi-Fi"),
            dict(st="old", ago=3 * 86400 + 7200, tag=("Docs", "Assembly"), title="Assembly guide, chapter 3"),
            dict(st="old", ago=4 * 86400, tag=("Electronics", "Cooling"), title="The board fan is noisy"),
            dict(st="old", ago=5 * 86400, tag=("Frame", "Purchasing"), title="Compare prices for 2020 extrusions"),
            dict(st="old", ago=6 * 86400, tag=("Firmware", "Network updates"), title="Over-the-air firmware: the signature check")]),
    "ru": dict(
        name="Принтер", secs=["Прошивка", "Корпус", "Электроника", "Маркетинг", "Слайсер", "Экструдер", "Документы"],
        merge=["Wi-Fi", "Обновление по сети"], docs=("Документы", "Инструкции", "Руководство"),
        untagged=["Калибровка стола после замены пружин", "Обновление прошивки: откат версии", "Прочность рамы при печати 2 кг",
                  "Крепления концевиков", "Питание от 24 В", "Охлаждение драйверов", "Профили для ABS",
                  "Сопла из закалённой стали", "Датчики двери: пауза", "Покупатели из Казахстана: доставка",
                  "Выставка в Москве: стенд", "Сборка оси Z, глава 4", "Руководство пользователя, раздел 2"],
        shop=[("Оплата", "Ошибки"), ("Поиск", "Опечатки"), ("Картинки", "Превью"), ("Админка", "Тёмная тема")],
        desk=[("Заявки", "Разбор"), ("Отчёты", "Неделя")],
        tasks=[
            dict(st="you", ago=1500, tag=("Электроника", "Драйверы"), title="Почему слой съезжает на третьем часу печати",
                 line="Причина — перегрев драйвера оси X; есть два способа это убрать",
                 need="Выбери: снизить ток мотора или поставить радиатор",
                 replies=["Снизить ток", "Поставить радиатор", "Объясни разницу"]),
            dict(st="work", ago=660, tag=("Экструдер", "Датчики"), title="Добавь датчик конца филамента",
                 ask="А если филамент кончится посреди слоя — печать встанет сразу или доделает слой?",
                 now="Встанет сразу: прошивка ставит паузу посреди слоя и уводит сопло к краю, чтобы не оплавить деталь. "
                     "Сейчас проверяю, что после заправки печать продолжится с той же точки.", edit="firmware/runout.c"),
            dict(st="work", ago=240, tag=("Маркетинг", "Выставка"), fresh=True, title="Подготовь страницу к выставке",
                 ask="Добавь таблицу: чем новая модель лучше прошлой — скорость, шум, цена", edit="marketing/show/page.md"),
            dict(st="bg", ago=900, tag=("Корпус", "Прочность"), title="Посчитай раму на прочность",
                 line="Запустил расчёт рамы под нагрузкой 40 кг; итог — по готовности", bg="Расчёт прочности рамы",
                 bg_cmd="python sim/frame_fea.py --load 40"),
            dict(st="idle", ago=2400, tag=("Электроника", "Питание"), title="Схема питания: защита от переполюсовки",
                 line="Добавил диод и предохранитель; схема и список деталей обновлены"),
            dict(st="idle", ago=4200, tag=("Слайсер", "Профили"), title="Профиль PETG для слайсера",
                 line="Профиль готов: 240 °C, обдув 30 %, пробник без паутины"),
            dict(st="idle", ago=7800, tag=("Корпус", "Крепления"), title="Крепление дисплея на раму",
                 line="Крепление перерисовано, печатается без поддержек"),
            dict(st="old", ago=86400 + 3600, tag=("Маркетинг", "Покупатели"), title="Ответы на частые вопросы покупателей"),
            dict(st="old", ago=86400 + 9000, tag=("Прошивка", "Калибровка"), title="Калибровка стола по 25 точкам"),
            dict(st="old", ago=2 * 86400, tag=("Экструдер", "Сопла"), title="Сопло 0,6 мм: настройки потока"),
            dict(st="old", ago=3 * 86400, tag=("Прошивка", "Wi-Fi"), title="Обновление прошивки по Wi-Fi"),
            dict(st="old", ago=3 * 86400 + 7200, tag=("Документы", "Сборка"), title="Инструкция по сборке, глава 3"),
            dict(st="old", ago=4 * 86400, tag=("Электроника", "Охлаждение"), title="Вентилятор платы шумит"),
            dict(st="old", ago=5 * 86400, tag=("Корпус", "Закупки"), title="Сравни цены на профиль 2020"),
            dict(st="old", ago=6 * 86400, tag=("Прошивка", "Обновление по сети"), title="Прошивка по воздуху: проверка подписи")]),
}[LANG if LANG in ("en", "ru") else "en"]



async def stand_tags(p, store, projects):
    """The printer's project, its tasks and every task's tags in the store. → the printer's pkey and its task ids."""
    G = TAGS_D
    root = Path(os.environ["PULT_HOME"]).parent / "printer"
    for m in ("firmware", "frame", "electronics", "marketing", "slicer", "extruder", "docs"):
        (root / m).mkdir(parents=True, exist_ok=True)
    (root / "README.md").write_text("# %s\n" % G["name"])
    path = str(root)
    pk = pultd.sanitize(path)
    folder = projects / pk
    folder.mkdir(parents=True, exist_ok=True)
    store.set_topic(pk, path, G["name"], 9001)

    def evp(name, sid, **kw):
        return dict(hook_event_name=name, session_id=sid, transcript_path=str(folder / (sid + ".jsonl")), cwd=path, **kw)
    sids = []
    for n, x in enumerate(G["tasks"]):
        sid = "%08x-7777-4777-8777-%012x" % (0x70000000 + n, n)
        sids.append(sid)
        x["sid"] = sid
        now = time.time()
        rows = [line("user", x["title"], ago=x["ago"])]
        if x.get("line"):
            rows.append(aline(x["line"] + ".", "t%d" % n, 900, ago=max(0, x["ago"] - 300)))
        f = folder / (sid + ".jsonl")
        f.write_text("\n".join(rows) + "\n")
        if x["st"] == "old":
            os.utime(f, (now - x["ago"] + 600, now - x["ago"] + 600))
            continue
        store.touch_session(sid, pk, path=path, title=x["title"])
        if x["st"] == "work":
            with f.open("a") as fh:
                if x.get("ask"):                   # a later turn of the task: the owner's follow-up, not its title
                    fh.write(line("user", x["ask"], ago=x["ago"]) + "\n")
                if x.get("now"):                   # without it: the turn has just begun, Claude hasn't said a word yet
                    fh.write(aline(x["now"], "w%d" % n, 1200) + "\n")
            await T.run_hook(evp("UserPromptSubmit", sid, prompt=x.get("ask") or x["title"]))
            await T.run_hook(evp("PostToolUse", sid, tool_name="Edit", tool_input={"file_path": path + "/" + x["edit"]}))
            p.live[sid].turn.started -= x["ago"]
            p.live[sid].run = p.live[sid].turn.started
            p.live[sid].title, p.live[sid].named = x["title"], True
        elif x["st"] == "bg":
            await T.run_hook(evp("UserPromptSubmit", sid, prompt=x["title"]))
            await T.run_hook(evp("Stop", sid, last_assistant_message=x["line"],
                                 background_tasks=[{"id": "bt%d" % n, "type": "shell", "status": "running",
                                                    "description": x["bg"], "command": x["bg_cmd"]}]))
            p.live[sid].title, p.live[sid].named = x["title"], True
        else:
            r = p.attn.finished(sid, pk, 600, x["line"], x["line"], waits=True, now=now - x["ago"])
            p.attn.briefed(sid, r["ts"], {"line": x["line"], "you": x["st"] == "you", "need": x.get("need") or "",
                                          "replies": x.get("replies") or []}, True)
            if x["st"] == "idle":
                p.attn.seen(sid)                   # the owner has put it away: "Got it" (2026-10-30)
    # the earlier tasks: the SDK lists a project's sessions from the real ~/.claude/projects, which the stand never
    # touches — so for the printer's folder the list is made up here, the same fields
    import claude_agent_sdk
    from types import SimpleNamespace
    real_list = claude_agent_sdk.list_sessions
    # every task of the printer, the latest first, as the SDK lists a folder's sessions — the project's screen shows
    # the ones it doesn't show elsewhere as the earlier ones; the batches of T2 take any without tags
    olds = [SimpleNamespace(session_id=x["sid"], custom_title=None, summary=x["title"], first_prompt=x["title"],
                            last_modified=(time.time() - x["ago"]) * 1000) for x in sorted(G["tasks"], key=lambda x: x["ago"])]
    if os.environ.get("STAND_TAGJOB"):          # T2: earlier tasks Pult never tagged — Claude sorts them on the first open
        for n, title in enumerate(G["untagged"]):
            sid = "%08x-7777-4777-8777-%012x" % (0x71000000 + n, n)
            (folder / (sid + ".jsonl")).write_text(line("user", title, ago=8 * 86400 + n * 3600) + "\n" +
                                                   aline(title + ".", "u%d" % n, 600, ago=8 * 86400 + n * 3600 - 60) + "\n")
            olds.append(SimpleNamespace(session_id=sid, custom_title=None, summary=title, first_prompt=title,
                                        last_modified=(time.time() - 8 * 86400 - n * 3600) * 1000))
        olds.sort(key=lambda x: -x.last_modified)

    def list_sessions(directory=None, limit=None, *a, **kw):
        if directory and os.path.realpath(directory) == os.path.realpath(path):
            return olds[:limit]
        return real_list(directory, limit, *a, **kw)
    claude_agent_sdk.list_sessions = list_sessions
    # the tags: sections first, in their order (that is their colour), then each task's topic
    old = time.time() - 2 * 86400
    shop = {T.SID: G["shop"][0], SID4: G["shop"][1], SID6: G["shop"][2], SID7: G["shop"][3]}
    desk = {SID2: G["desk"][0], SID5: G["desk"][1]}
    for pkey, secs in ((pk, G["secs"]), (T.PKEY, [s for s, _ in G["shop"]]), (PKEY2, [s for s, _ in G["desk"]])):
        for s in secs:
            store.tag_add(pkey, s, None, ts=old)
    tasks = [(x["sid"], pk, x["tag"], x.get("fresh")) for x in G["tasks"]] + \
        [(sid, T.PKEY, tg, False) for sid, tg in shop.items()] + [(sid, PKEY2, tg, False) for sid, tg in desk.items()]
    for sid, pkey, (s, tp), fresh in tasks:
        store.tag_add(pkey, s, tp, ts=None if fresh else old)
        store.set_session_tag(sid, pkey, s, tp, False)
    # T2: Claude's offer to merge two topics of the firmware that name the same thing — its answer as it would come
    # (the model never runs on the stand); the project's tags screen shows it on top
    tidy = {"pairs": [{"a": {"sec": G["secs"][0], "topic": G["merge"][0]}, "keep": {"sec": G["secs"][0], "topic": G["merge"][1]}}]}
    store.put("tags.tidy." + pk, {"sig": "", "ts": time.time(), "raw": tidy})
    if os.environ.get("STAND_TAGJOB"):
        await stand_tagjob(p, store, pk, tidy, [x["sid"] for x in G["tasks"] if x["tag"][0] == G["docs"][0]])
    return pk, sids


async def stand_tagjob(p, store, pk, tidy, docs_sids):
    """STAND_TAGJOB=1 (T2): the model on — a made-up one, slow enough to see "N of M": a batch puts each task under the
    first topic of the list whose first letters its title has; "Sort them again" makes the printer's list anew, its
    docs section under a new name with a topic of its own; the docs task is the owner's — it keeps its tags."""
    G = TAGS_D
    for sid in docs_sids:                                   # the owner tagged it: "Sort them again" leaves it
        r = store.session_tag(sid)
        store.tag_add(pk, r["sec"], r["topic"], own=True)
        store.set_session_tag(sid, pk, r["sec"], r["topic"], True)

    def listed(text):
        out = []
        for ln in text.split("<project_tags>")[1].split("</project_tags>")[0].strip().split("\n"):
            if ln.startswith("- "):
                sec, _, tops = ln[2:].partition(": ")
                out.append((sec, [t for t in tops.split(", ") if t]))
        return out

    async def batch(text, lang, cwd):
        await asyncio.sleep(2.5)
        vocab, got = listed(text), []
        for i, title in __import__("re").findall(r'<task id="(\d+)">\n<title>(.*?)</title>', text):
            low = title.lower()
            hit = next(((s, t) for s, ts in vocab for t in ts if t.lower()[:5] in low), None)
            got.append({"id": i, "sec": hit[0] if hit else vocab[0][0], "topic": hit[1] if hit else ""})
        return {"tasks": got}

    async def make_list(text, lang, cwd):
        await asyncio.sleep(2)
        old = {s["n"]: [t["n"] for t in s["topics"]] for s in store.tag_vocab(pk)}
        return {"secs": [{"n": s, "topics": old.get(s, [])} if s != G["docs"][0] else {"n": G["docs"][1], "topics": [G["docs"][2]]}
                         for s in G["secs"]]}

    async def nothing(*a, **kw):
        return None

    async def tidy_answer(text, lang, cwd):
        return tidy
    pultd.G.batch, pultd.G.make_list, pultd.G.tidy, pultd.G.tag, pultd.B.brief = batch, make_list, tidy_answer, nothing, nothing
    await p.api_prefs(brief=True)


# STAND_FILES=1: the shop's own folder, made up, and the last reply's links into it — a page, a line of code, a project
# page, a picture, a folder, a file the app can't show, a secret and a file outside the project
FILE_LINKS = {"en": "Files: [README.md](README.md) · [errors.py:12](checkout/errors.py#L12) · [design.html](docs/design.html) · "
                    "[screen.png](media/screen.png) · [media/](media/) · [export.bin](data/export.bin) · [.env](.env) · [hosts](/etc/hosts)",
              "ru": "Файлы: [README.md](README.md) · [errors.py:12](checkout/errors.py#L12) · [design.html](docs/design.html) · "
                    "[screen.png](media/screen.png) · [media/](media/) · [export.bin](data/export.bin) · [.env](.env) · [hosts](/etc/hosts)"}


def shop_files():
    root = Path(os.environ["PULT_HOME"]).parent / "acme-shop"
    for d in ("checkout", "docs", "media", "data"):
        (root / d).mkdir(parents=True, exist_ok=True)
    (root / "README.md").write_text("# Acme shop\n\nThe checkout lives in [checkout/](checkout/), its error texts in "
                                    "[errors.py](checkout/errors.py).\n\n- **cards** — Visa, Mastercard\n- **timeouts** — 30 s\n\n"
                                    "```\nmake test\n```\n")
    (root / "checkout" / "errors.py").write_text("".join(
        ["\"\"\"Checkout errors: what the customer reads.\"\"\"\n", "\n"]
        + ["ERR_%d = \"Something went wrong (%d)\"\n" % (i, i) for i in range(1, 10)]
        + ["DECLINED = \"Card declined — try another card\"\n", "TIMEOUT = \"Timed out — try again\"\n"]
        + ["# a long line that has to wrap on a phone: " + "lorem ipsum " * 12 + "\n"]
        + ["X_%d = %d\n" % (i, i) for i in range(40)]))
    (root / "docs" / "design.html").write_text("<!doctype html><style>body{font:16px sans-serif;padding:12px}h1{color:#2a78d6}</style>"
                                              "<h1>Checkout design</h1><p>Errors say why and what to do.</p>"
                                              "<script>parent.postMessage('ran', '*')</script>")
    (root / "media" / "screen.png").write_bytes(png_sample())
    (root / "data" / "export.bin").write_bytes(bytes(range(256)) * 4)
    (root / ".env").write_text("TOKEN=made-up\n")
    return root


# STAND_SECOND=1 (stage M, step 1): the shop's search as it was before the task (a commit three hours old) and as the task
# left it; Codex's made-up answer about it, in the stand's language
SECOND_REVIEW = {
    "en": ("Typo-tolerant search works; two places will hurt on a big catalogue.\n\nFull review comments:\n\n"
           "- [P1] Rebuild only the new product's trigrams — {cwd}/search/index.py:41-58\n"
           "  The whole index is rebuilt on every new product: with 40,000 products that is a couple of seconds without "
           "writes. Add the new product's trigrams instead.\n\n"
           "- [P2] Skip typo search for one or two letters — {cwd}/search/query.py:12-12\n"
           "  A query of one or two letters returns half the catalogue: search with typos only from three characters, "
           "and add a test for `q(\"ab\")`."),
    "ru": ("Поиск с опечатками работает; на большом каталоге заболят два места.\n\nFull review comments:\n\n"
           "- [P1] Пересобирайте только триграммы нового товара — {cwd}/search/index.py:41-58\n"
           "  Индекс пересобирается целиком на каждый новый товар: на 40 тыс. товаров это пара секунд без записи. "
           "Хватит дописывать триграммы одного товара.\n\n"
           "- [P2] Не ищите с опечатками по одной-двум буквам — {cwd}/search/query.py:12-12\n"
           "  Запрос из одной-двух букв вернёт полкаталога: искать с опечатками только от трёх символов — и тест на "
           "`q(\"ab\")`."),
}


def shop_repo():
    """The shop as a git repository: its search before the task, committed three hours ago, and the task's change — in
    the stand's own temporary folder, gone with it (the system's temporary folder is shared by every stand)."""
    import subprocess
    root = T.TMP / "acme-shop"
    (root / "search").mkdir(parents=True, exist_ok=True)
    when = int(time.time() - 3 * 3600)
    env = dict(os.environ, GIT_AUTHOR_DATE="@%d" % when, GIT_COMMITTER_DATE="@%d" % when)
    (root / "search" / "index.py").write_text('"""The product index."""\n\nINDEX = {}\n')
    (root / "search" / "query.py").write_text('"""A search query."""\n')
    for cmd in (["init", "-q"], ["config", "user.email", "stand@example.invalid"], ["config", "user.name", "stand"],
                ["config", "commit.gpgsign", "false"], ["add", "-A"], ["commit", "-qm", "search: exact names"]):
        subprocess.run(["git", "-C", str(root), *cmd], check=True, env=env, capture_output=True)
    (root / "search" / "index.py").write_text("".join(
        ['"""The product index: trigrams of every name, for typo-tolerant search."""\n', "\n", "INDEX = {}\n", "\n"]
        + ["# the trigram table, part %d\n" % i for i in range(1, 37)]
        + ["def add(product):\n", "    INDEX.clear()\n", "    for p in catalogue():\n",
           "        for g in trigrams(p.name):\n", "            INDEX.setdefault(g, set()).add(p.id)\n"]
        + ["    # rebuilt whole, line %d\n" % i for i in range(1, 14)]))
    (root / "search" / "query.py").write_text("".join(
        ['"""A search query, with typos."""\n', "\n"] + ["# step %d\n" % i for i in range(1, 10)]
        + ["def q(text):\n", "    return fuzzy(text)\n"]))
    return root


async def main():
    pultd.CLAUDE_PROJECTS = Path(T.TP).parent.parent      # made-up transcripts only: never the Mac's own sessions
    fake = T.FakeTg()
    tg = pultd.Tg("T", transport=T.httpx.MockTransport(fake.handler))
    store = pultd.Store(T.TMP / "harness.db")
    store.put("chat", T.CHAT)
    store.put("lang_tg", LANG)                                   # the language of the bot and the app
    store.set_topic(T.PKEY, SHOP, "acme-shop", 77)
    store.set_topic(PKEY2, DESK, "support-desk", 78)
    if os.environ.get("STAND_HOMES") == "1":                 # stage Zh: real folders — the Projects screen lists only those
        for pk, name in ((T.PKEY, "acme-shop"), (PKEY2, "support-desk"), ("-Users-x-blog", "blog")):
            home = Path(os.environ["PULT_HOME"]).parent / name
            home.mkdir(parents=True, exist_ok=True)
            store.set_topic(pk, str(home), name, {T.PKEY: 77, PKEY2: 78}.get(pk, 79))
    for i, n in enumerate([x for x in os.environ.get("STAND_PINS", "").split(",") if x]):   # stage Zh: pinned, the last the newest
        pk = {"shop": T.PKEY, "desk": PKEY2, "blog": "-Users-x-blog"}.get(n)
        if pk:
            store.set_pin(pk, True)
            store.db.execute("UPDATE pins SET ts=? WHERE pkey=?", (1e9 + i, pk))
    for n in [x for x in os.environ.get("STAND_HIDES", "").split(",") if x]:            # stage Zh, step 2: hidden projects
        pk = {"shop": T.PKEY, "desk": PKEY2, "blog": "-Users-x-blog"}.get(n)
        if pk:
            store.set_hide(pk, True)
    if os.environ.get("STAND_FILES") == "1":                 # stage F5: links in Claude's words open the project's files
        store.set_topic(T.PKEY, str(shop_files()), "acme-shop", 77)
    second = os.environ.get("STAND_SECOND")
    if second:                                               # stage M: the shop's search changed, and Codex reads it
        store.set_topic(T.PKEY, str(shop_repo()), "acme-shop", 77)
        import fake_codex
        conf = T.TMP / "stand-codex.json"
        conf.write_text(json.dumps({"wait": 5, "steps": 4, "review": SECOND_REVIEW[LANG]}))
        codex = fake_codex.launcher(str(T.TMP), str(conf))
        if second == "allowed":
            store.put("vendors.ok", {T.PKEY: time.time()})
    p = pultd.Pult({"PULT_ALLOWED_USER_IDS": str(T.OWNER), "PULT_FORCE_AWAY": "1"}, tg, store)
    # Codex is the stand-in or none: this computer's own (ChatGPT.app) is never read here, as VS Code's settings aren't
    p.env["PULT_CODEX"] = codex if second else str(T.TMP / "no-codex")
    p.out = pultd.Outbox(rate=60000, burst=1000)
    p._agents = (time.monotonic() + 1e6, [{"sessionId": SID3, "cwd": "/Users/x/blog"}])
    pultd.EDIT_EVERY = 0.2
    # stage S: a made-up home folder for "New project" (the stand's temp folder, listed like a real one); the first
    # turn of a new project is not started — the stand never runs Claude
    home = T.TMP / "stand-home"
    for d in ("Documents/acme-shop", "Documents/support-desk", "Code"):
        (home / d).mkdir(parents=True, exist_ok=True)
    pult_api.NEW_ROOT, pultd.SKIP_PREFIXES = home, ("-nothing-",)
    pultd.TAB_CONF = T.TMP / "stand-tab.json"
    pultd.TAB_CONF.write_text(json.dumps({"folders": [str(home / "Documents"), "/Users/x"],
                                          "versions": list(pult_setup.TAB_VERIFIED)}))
    # VS Code with Pult's wrapper line and the tab switch — made up: why a message goes as a copy is read from them
    pultd.TAB_OFF = T.TMP / "stand-tab-off"
    pult_parts.EXT_DIRS = [T.TMP / "stand-extensions"]                 # nor its Claude Code extensions
    pultd.EDITOR_DIRS = [T.TMP / "stand-vscode" / "User"]
    pultd.EDITOR_DIRS[0].mkdir(parents=True, exist_ok=True)
    (pultd.EDITOR_DIRS[0] / "settings.json").write_text(json.dumps({
        "claudeCode.claudeProcessWrapper": "/Users/x/.local/share/pult/" + pultd.TAB_FILE}))
    # Claude Code's settings, made up — never this computer's: Pult's hook on every event and the effort "high", which
    # Settings → Model and effort shows under "As in Claude Code"
    pultd.SETTINGS = T.TMP / "stand-settings.json"
    pultd.SETTINGS.write_text(json.dumps({"effortLevel": "high", "hooks": {
        e: [{"hooks": [{"type": "command", "command": "pult_hook.py"}]}] for e in pult_hook.EVENTS}}))

    async def no_drive(sid, path, text, *a, **kw):
        print("DRIVE", path, json.dumps(text[:80], ensure_ascii=False), flush=True)
    p.drive = no_drive
    sock = await asyncio.start_unix_server(p.handle_conn, path=os.environ["PULT_SOCK"])
    runner = web.AppRunner(relay.app())
    await runner.setup()
    await web.TCPSite(runner, "127.0.0.1", PORT).start()
    async def fake_usage(force=False):
        r = W.usage_reply(session=38, week=71, fable=44, share=22)
        for lim in r["rate_limits"]["limits"]:                 # resets in the future, as in real life
            ahead = 2 * 3600 + 600 if lim["kind"] == "session" else 1 * 86400 + 20 * 3600
            lim["resets_at"] = time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime(time.time() + ahead))
        return PW.simplify_usage(r)
    p.usage = fake_usage
    upd = os.environ.get("STAND_UPD")      # stage U: Settings → Pult and Home's line in one state (tools/update_check.py)
    clone = (os.environ.get("STAND_PARTS") or "") in ("public", "auto", "auto_run", "auto_fail", "auto_self")   # stage U3
    if upd:
        import pult_update as U
        nums = [int(x) for x in pultd.VERSION.split(".")]
        nxt = "%d.%d.%d" % (nums[0], nums[1], nums[2] + 1)
        head = "5e1f0a2" + "c" * 33
        U.check = lambda manifest=None: {
            "repo": str(Path.home() / "pult"), "head": head, "short": head[:7], "ready": upd != "ok", "version": nxt,
            "tag": "v" + nxt if clone else None,
            "news": ["Pult %s: install an update from the app" % nxt, "Settings: what was installed, when and from where"],
            "failed": upd == "fail"}
        U.spawn = lambda commit, how, python=None: U.write(U.STATUS, {        # never a real installer here
            "state": "run", "step": "check", "to": nxt, "ts": time.time(), "pid": os.getpid()}) or True
        # STAND_RESTART: Install does to the stand what the real installer does to the daemon that started it — a
        # request on its way dies with that daemon, the link drops about a second after the tap, a new daemon comes
        # back (2026-10-27: a stale Install stayed on screen and was tapped twice; the banner was red for an install)
        restart = os.environ.get("STAND_RESTART")
        dead, installed = [False], [False]
        if restart:
            loop, fake_check = asyncio.get_running_loop(), U.check
            U.check = lambda manifest=None: dict(fake_check(manifest), ready=not installed[0])

            async def drop():
                if p.web.ws is not None:
                    await p.web.ws.close()

            async def comes_back():
                if restart != "lost":
                    await asyncio.sleep(0.6)
                    await drop()
                await asyncio.sleep(0.5)
                dead[0], p._upd = False, (0.0, None)        # the new daemon: pult_web is back on the relay by itself
                U.write(U.STATUS, {"state": "run", "step": "check", "to": nxt, "ts": time.time(), "pid": os.getpid()})
                await asyncio.sleep(4.5)
                installed[0], p._upd = True, (0.0, None)
                U.write(U.STATUS, {"state": "done", "to": nxt, "ts": time.time()})
                p.web.emit("update", state="ok")

            def restart_spawn(commit, how, python=None):     # in a worker thread, as the real one
                U.write(U.STATUS, {"state": "run", "step": "stop", "to": nxt, "ts": time.time(), "pid": os.getpid()})
                dead[0] = True
                if restart == "lost":
                    asyncio.run_coroutine_threadsafe(drop(), loop).result(5)
                asyncio.run_coroutine_threadsafe(comes_back(), loop)
                return True
            U.spawn = restart_spawn
        cut = [{"sid": T.SID, "title": D["title"], "project": "acme-shop", "turn": True, "bg": [], "n": 0},
               {"sid": SID3, "title": D["bg_run"], "project": "support-desk", "turn": False, "bg": [D["bg_run"]], "n": 1}]
        if upd in ("busy", "wait"):
            p.busy_report = lambda: cut[:2 if upd == "busy" else 1]
        if upd == "wait":
            p.upd_wait = time.time()
        if upd == "run":
            U.spawn(head, "app")
        if upd == "fail":
            U.write(U.STATUS, {"state": "fail", "why": "restarts", "detail": "ModuleNotFoundError: No module named 'pult_upd'",
                               "back": True, "back_ok": True, "commit": head, "to": nxt, "reported": True, "ts": time.time()})
        now, have = time.time(), pultd.VERSION
        prev = "%d.%d.%d" % (nums[0], nums[1], max(0, nums[2] - 1))
        U.write(U.HISTORY, [
            {"ts": now - 1500, "from": prev, "to": have, "how": "terminal", "ok": True},
            {"ts": now - 26 * 3600, "from": "0.13.1", "to": prev, "how": "app_wait", "ok": True},
            {"ts": now - 27 * 3600, "from": "0.13.1", "to": prev, "how": "app", "ok": False, "why": "restarts"},
            {"ts": now - 28 * 3600, "from": "0.13.0", "to": "0.13.1", "how": "app", "ok": True},
            {"ts": now - 50 * 3600, "from": "0.12.0", "to": "0.13.0", "how": "terminal", "ok": True}])
    # stage U2: Settings' parts table, always on made-up facts — never this computer's own Claude Code or hooks
    parts = os.environ.get("STAND_PARTS") or "fresh"
    if parts:
        now = time.time()
        sha = lambda c: c + "0" * (40 - len(c))
        lag = lambda n, h, news: {"n": n, "since": now - h * 3600 if n else None, "news": news[:n]}
        calm = {"git": {"mac": lag(0, 0, []), "web": dict(lag(0, 0, []), commit=sha("57e5646"), ts=now - 6 * 3600),
                        "relay": dict(lag(0, 0, []), commit=sha("4680b38"), ts=now - 5 * 86400),
                        "gh": {"last": pultd.VERSION, "date": time.strftime("%Y-%m-%d", time.localtime(now - 86400)), "waiting": 0}},
                "tabs": [True] * 3, "missing": []}
        facts = {
            "fresh": {"git": {"mac": lag(0, 0, []), "web": dict(lag(0, 0, []), commit=sha("57e5646"), ts=now - 6 * 3600),
                              "relay": dict(lag(0, 0, []), commit=sha("4680b38"), ts=now - 5 * 86400),
                              "gh": {"last": pultd.VERSION, "date": time.strftime("%Y-%m-%d", time.localtime(now - 86400)), "waiting": 0}},
                      "tabs": [True] * 3, "missing": [], "cc": (["2.1.301"], ["2.1.301"], "2.1.301")},
            "now": {"git": {"mac": lag(0, 0, []), "web": dict(lag(0, 0, []), commit=sha("57e5646"), ts=now - 6 * 3600),
                            "relay": dict(lag(0, 0, []), commit=sha("4680b38"), ts=now - 5 * 86400),
                            "gh": {"last": pultd.VERSION, "date": time.strftime("%Y-%m-%d", time.localtime(now - 86400)), "waiting": 1}},
                    "tabs": [True] * 14, "missing": [], "cc": (["2.1.301"], ["2.1.301"], "2.1.310")},
            "lag": {"git": {"mac": lag(2, 5, ["Every part of Pult in one table", "The tab wrapper names its own version"]),
                            "web": dict(lag(3, 2, ["Settings: the parts table", "Home: one line for every update",
                                                   "Phone: Refresh when the server has a newer app"]), commit=sha("57e5646"), ts=now - 9 * 3600),
                            "relay": dict(lag(0, 0, []), commit=sha("4680b38"), ts=now - 5 * 86400),
                            "gh": {"last": pultd.VERSION, "date": time.strftime("%Y-%m-%d", time.localtime(now - 86400)), "waiting": 4}},
                    "tabs": [True] * 12 + [False] * 2, "missing": ["StopFailure"], "cc": (["2.1.310"], ["2.1.301", "2.1.310"], "2.1.310")},
            # someone with a clone of the public repository, after a `git pull`: no release of their own to make, no
            # wrapper in the tabs; the computer and their server one release behind
            "public": {"git": {"mac": lag(1, 3, ["Pult 0.16.1"]), "web": dict(lag(1, 3, ["Pult 0.16.1"]), commit=sha("e5f2b10"), ts=now - 9 * 86400),
                               "relay": dict(lag(1, 3, ["Pult 0.16.1"]), commit=sha("e5f2b10"), ts=now - 9 * 86400), "gh": None},
                       "tabs": [], "missing": [], "cc": (["2.1.310"], ["2.1.301"], "2.1.310"), "wrapped": False},
            # stage U3: that clone with the server's updater — it took the computer's release; is taking it; didn't
            "auto": {"git": {"mac": lag(0, 0, []), "web": dict(lag(0, 0, []), commit=sha("e5f2b10"), ts=now - 300),
                             "relay": dict(lag(0, 0, []), commit=sha("e5f2b10"), ts=now - 300), "gh": None},
                     "tabs": [], "missing": [], "cc": (["2.1.310"], ["2.1.301", "2.1.310"], "2.1.310"), "wrapped": False,
                     "srv": {"state": "done", "tag": "v" + pultd.VERSION, "have": "v" + pultd.VERSION, "from": "v0.16.2", "ts": now - 300}},
            "auto_run": {"git": {"mac": lag(0, 0, []), "web": dict(lag(1, 1, ["Pult " + pultd.VERSION]), commit=sha("e5f2b10"), ts=now - 9 * 86400),
                                 "relay": dict(lag(1, 1, ["Pult " + pultd.VERSION]), commit=sha("e5f2b10"), ts=now - 9 * 86400), "gh": None},
                         "tabs": [], "missing": [], "cc": (["2.1.310"], ["2.1.301", "2.1.310"], "2.1.310"), "wrapped": False,
                         "srv": {"state": "run", "step": "fetch", "tag": "v" + pultd.VERSION, "have": "v0.16.2", "ts": now - 4}},
            # its code is the release's, its updater isn't: install.sh once, there (review 2026-10-27, У5)
            "auto_self": {"git": {"mac": lag(0, 0, []), "web": dict(lag(0, 0, []), commit=sha("e5f2b10"), ts=now - 300),
                                  "relay": dict(lag(0, 0, []), commit=sha("e5f2b10"), ts=now - 300), "gh": None},
                          "tabs": [], "missing": [], "cc": (["2.1.310"], ["2.1.301", "2.1.310"], "2.1.310"), "wrapped": False,
                          "srv": {"state": "done", "tag": "v" + pultd.VERSION, "have": "v" + pultd.VERSION, "ts": now - 300,
                                  "self": {"deploy/relay/update.py": sha("0ld")}}},
            "auto_fail": {"git": {"mac": lag(0, 0, []), "web": dict(lag(1, 1, ["Pult " + pultd.VERSION]), commit=sha("e5f2b10"), ts=now - 9 * 86400),
                                  "relay": dict(lag(1, 1, ["Pult " + pultd.VERSION]), commit=sha("e5f2b10"), ts=now - 9 * 86400), "gh": None},
                          "tabs": [], "missing": [], "cc": (["2.1.310"], ["2.1.301", "2.1.310"], "2.1.310"), "wrapped": False,
                          "srv": {"state": "fail", "why": "no_start", "detail": "ModuleNotFoundError: No module named 'multidict'",
                                  "back": True, "back_ok": True, "tag": "v" + pultd.VERSION, "have": "v0.16.2", "ts": now - 600}},
            # stage A: Pult's own check of a Claude Code version VS Code has downloaded (tools/vcheck_check.py) — running
            # now; failed at a step; passed (the tabs run it since); couldn't check
            "check_run": dict(calm, cc=(["2.1.310"], ["2.1.301", "2.1.310"], "2.1.311"), checking="2.1.311"),
            "check_fail": dict(calm, cc=(["2.1.310"], ["2.1.301", "2.1.310"], "2.1.311"), checked={
                "2.1.311": {"ts": now - 1500, "ok": False, "race": True, "error": None, "step": "model"}}),
            "check_here": dict(calm, cc=(["2.1.311"], ["2.1.301", "2.1.310", "2.1.311"], "2.1.311"), checked={
                "2.1.311": {"ts": now - 7200, "ok": True, "race": True, "error": None, "step": None}}),
            "check_err": dict(calm, cc=(["2.1.310"], ["2.1.301", "2.1.310"], "2.1.311"), checked={
                "2.1.311": {"ts": now - 600, "ok": None, "race": None, "error": "login", "step": None}}),
            "bad": {"git": {"mac": lag(0, 0, []), "web": None, "web_told": True, "relay": None,
                            "gh": {"last": pultd.VERSION, "date": time.strftime("%Y-%m-%d"), "waiting": 0}},
                    "tabs": [True] * 3 + [None], "missing": ["StopFailure", "PreCompact"], "cc": (["2.1.301", "2.1.310"], ["2.1.301"], "2.1.310")},
        }[parts]
        g = dict(facts["git"], repo=str(Path.home() / "pult"), head=sha("a41c9e2"), branch="main", release=clone)
        if clone:                     # stage U3: the relay's server says whether it has the updater, and its report
            own = {"deploy/relay/update.py": sha("ab12cd3")}           # the updater the release has, and the server too —
            g["srv_files"] = own                                       # unless the facts say otherwise (auto_self)
            srv = dict(facts["srv"], self=facts["srv"].get("self", own)) if facts.get("srv") else None
            p.srv = {"can": ["want"] if "srv" in facts else [], "upd": srv}
            pult_parts.U.release_mode = lambda repo, head: "origin"  # the module the parts read: U is local to this function
            p.gh.update(at=now - 140, ok=True)

            async def stand_said(msg):              # the stand's own relay has no updater: its hello must not count
                return None
            p.relay_said = stand_said
        names = ["acme-shop", "support-desk", "blog", "notes"]
        tabs = [{"project": names[i % 3] if same is not False else names[1 + i % 2], "same": same} for i, same in enumerate(facts["tabs"])]
        hooks = [e for e in pult_hook.EVENTS if e not in facts["missing"]]
        running, verified, newest = facts["cc"]
        wrapped = facts.get("wrapped", True)
        cc = {"running": running, "verified": verified, "newest": newest, "wrapped": wrapped, "sdk": "0.2.167", "cli": "2.1.300",
              "checked": dict(facts.get("checked") or {}), "checking": facts.get("checking"), "auto": True}

        async def stand_facts():
            return {"upd": await p.update_view(), "git": g, "relay": True, "tabs": tabs, "hooks": hooks, "cc": cc, "srv": p.srv}

        async def stand_broken():
            fail = lambda v: (cc["checked"].get(v) or {}).get("ok") is False and not cc["checked"][v].get("error")  # noqa: E731
            off = [v for v in running if v not in verified and v != cc["checking"]] if wrapped else []
            nxt = [v for v in [newest] if wrapped and v not in verified and v not in running and fail(v)]
            return ([{"k": "hooks", "missing": facts["missing"]}] if facts["missing"] else []) + \
                ([{"k": "cc", "v": off[-1], "fail": fail(off[-1])}] if off else
                 [{"k": "cc", "v": nxt[0], "fail": True, "next": True}] if nxt else [])

        async def stand_tab_check():                 # "Check again": a made-up check that passes in 3 s, no Claude
            v = next((x for x in running if x not in verified), None) or (newest if newest not in verified else None)
            if not v:
                return {"ok": False, "note": p.t("tab.check.nothing")}
            print("CHECK", v, flush=True)
            cc["checking"] = v

            async def done():
                await asyncio.sleep(3)
                cc["checking"] = None
                cc["checked"][v] = {"ts": time.time(), "ok": True, "race": True, "error": None, "step": None}
                verified.append(v)
                if p.web:
                    p.web.emit("update")
            asyncio.ensure_future(done())
            return {"ok": True, "v": v}
        p.parts_facts, p.broken, p.api_tab_check = stand_facts, stand_broken, stand_tab_check
    if os.environ.get("STAND_STT"):        # the microphone (tools/voice_check.py): recordings land in that folder, no Groq
        keep = Path(os.environ["STAND_STT"])

        class StandStt:
            model = "stand"

            async def transcribe(self, blob, kind, language=None, prompt=None):
                n = len(list(keep.glob("rec-*"))) + 1
                (keep / ("rec-%d.%s" % (n, pultd.STT.ext_of(kind) or "bin"))).write_bytes(blob)
                return "recording %d heard" % n
        p.stt, p.refresh_stt = StandStt(), lambda: None
        if os.environ.get("STAND_STT_OLD") == "1":                  # a computer before 0.14.2: no notes with the recording
            new_stt = p.api_stt

            async def old_stt(data, mime=None):
                return await new_stt(data, mime)
            p.api_stt = old_stt
    p.web = PW.Web(p, "ws://127.0.0.1:%d/pult/agent" % PORT, "s3cret", W.TOKEN, {T.OWNER})
    if upd and os.environ.get("STAND_RESTART"):
        answer = p.web.answer

        async def answer_gone(cid, msg):          # a daemon that is gone answers nothing (STAND_RESTART)
            if dead[0]:
                await asyncio.Event().wait()
            return await answer(cid, msg)
        p.web.answer = answer_gone
    asyncio.create_task(p.out.run())
    asyncio.create_task(p.web.run())

    d = Path(T.TP).parent
    d.mkdir(parents=True, exist_ok=True)
    (d.parent / PKEY2).mkdir(parents=True, exist_ok=True)
    summary = D["summary"] + ("\n<script>alert(1)</script>" if os.environ.get("STAND_XSS") == "1" else "")
    pic = Path(os.environ["PULT_HOME"]) / "inbox" / "2026-10" / "app-stand.png"
    pic.parent.mkdir(parents=True, exist_ok=True)
    pic.write_bytes(png_sample())
    # STAND_LONG=1: a long history in small pages — for scrolling up through it (the earlier part loads by itself)
    long = [x for k in range(40) for x in (line("user", "#%d %s" % (k, D["ask"]), ago=200000 - k * 600),
                                            aline("#%d %s" % (k, D["read"]), "old%d" % k, 300, ago=199900 - k * 600))] \
        if os.environ.get("STAND_LONG") else []
    if long:
        PW.transcript_page.__defaults__ = (None, None, None, 6000)
    (d / (T.SID + ".jsonl")).write_text("\n".join(long + [
        line("user", D["ask"], ago=86400),
        line("user", D["look"] + "\n\n[Attachment from the Pult app: %s]\n\n[Attachment from the Pult app: %s]" % (pic, pic), ago=86300),
        json.dumps({"type": "assistant", "effort": "xhigh", "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime()),
                    "message": {"id": "u1", "model": "claude-opus-5-5", "role": "assistant", "content": [],
                                "usage": {"input_tokens": 2, "cache_read_input_tokens": 120000, "cache_creation_input_tokens": 900,
                                          "output_tokens": 9800, "output_tokens_details": {"thinking_tokens": 4100}}}}),
        line("assistant", [{"type": "text", "text": D["read"]}]),
        line("assistant", [{"type": "tool_use", "id": "a1", "name": "Read", "input": {"file_path": SHOP + "/tests/test_checkout.py"}}]),
        line("user", [{"type": "tool_result", "tool_use_id": "a1", "content": "import pytest\n…"}]),
        line("assistant", [{"type": "tool_use", "id": "a2", "name": "Edit", "input": {"file_path": SHOP + "/checkout/errors.py", "old_string": "a", "new_string": "b"}}]),
        line("user", [{"type": "tool_result", "tool_use_id": "a2", "content": "ok"}]),
        line("assistant", [{"type": "tool_use", "id": "a3", "name": "Bash", "input": {"command": "pytest tests", "description": "Run all tests"}}]),
        line("user", [{"type": "tool_result", "tool_use_id": "a3", "content": "FAILED (failures=1)", "is_error": True}]),
        line("assistant", [{"type": "text", "text": summary}]),
        line("user", "<task-notification>\n<task-id>b1</task-id>\n<status>completed</status>\n<summary>%s</summary>\n"
                     "</task-notification>" % D["bg_done"]),
        aline(D["after_bg"] + ("\n\n" + FILE_LINKS[LANG] if os.environ.get("STAND_FILES") == "1" else ""), "u5", 1400),
    ]) + "\n")
    store.touch_session(T.SID, T.PKEY, path=SHOP, title=D["title"])
    p.set_ctx(T.SID, 200000, 32000, model="claude-opus-5-5")        # the context gauge, as a turn's result reports it
    if os.environ.get("STAND_TAB") or os.environ.get("STAND_TICKS"):   # the session open in a VS Code tab with Pult's
        # wrapper (STAND_TAB=old — 0.9.8's)
        caps = ["model", "ctx"] if os.environ.get("STAND_TAB") == "old" else ["model", "ctx", "control"]
        tab_r, tab_w = await asyncio.open_unix_connection(os.environ["PULT_SOCK"])
        tab_w.write((json.dumps({"op": "hello", "pid": os.getpid(), "cwd": SHOP, "sid": T.SID, "version": "2.1.301",
                                 "caps": caps}) + "\n").encode())
        await tab_w.drain()
    await T.run_hook(ev("SessionStart", T.SID))
    await T.run_hook(ev("UserPromptSubmit", T.SID, prompt=D["ask_short"], prompt_id="stand-p1"))
    p.live[T.SID].title, p.live[T.SID].named = D["title"], True
    if os.environ.get("STAND_TICKS"):     # the tab reads a message at its turn's next step: the transcript, then the hook
        wait = float(os.environ["STAND_TICKS"])

        async def absorb(text):
            await asyncio.sleep(wait)
            if "#gone" in text:           # Stop dropped it before Claude read it
                p.out_set(T.SID, "gone", text)
                return
            with (d / (T.SID + ".jsonl")).open("a") as f:
                f.write(json.dumps({"type": "attachment", "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime()),
                                    "attachment": {"type": "queued_command", "prompt": text, "commandMode": "prompt",
                                                   "origin": {"kind": "human"}}}, ensure_ascii=False) + "\n")
            await T.run_hook(ev("UserPromptSubmit", T.SID, prompt=text, prompt_id="stand-p1"))

        async def tab_read():
            while line_ := await tab_r.readline():
                m = json.loads(line_)
                if m.get("op") == "send":
                    print("TAB", json.dumps(m["text"], ensure_ascii=False), flush=True)
                    asyncio.create_task(absorb(m["text"]))
        asyncio.create_task(tab_read())
    with (d / (T.SID + ".jsonl")).open("a") as f:
        f.write(aline(D["now"], "u6", 900) + "\n")
    await T.run_hook(ev("PostToolUse", T.SID, tool_name="Read", tool_input={"file_path": SHOP + "/checkout/errors.py"}))
    p.live[T.SID].turn.started -= 380
    p.live[T.SID].run = p.live[T.SID].turn.started        # "working N" counts from the owner's prompt
    await T.run_hook(ev("PermissionRequest", T.SID, tool_name="Bash",
                        tool_input={"command": D["cmd"], "description": D["cmd_desc"]},
                        permission_suggestions=[{"type": "addRules"}]), wait=False)
    q = {"questions": [{"question": D["question"], "header": D["header"], "multiSelect": False,
                        "options": [{"label": D["opt1"], "description": D["opt1d"]}, {"label": D["opt2"]}]}]}
    if os.environ.get("STAND_ASK2") == "1":            # two questions in one: answered one by one (tools/ask_check.py)
        q["questions"].append({"question": D["question2"], "header": D["header2"], "multiSelect": False,
                               "options": [{"label": D["opt3"]}, {"label": D["opt4"]}]})
    if os.environ.get("STAND_ADVICE") == "1":          # several answers, Claude's advice checked (tools/advice_check.py)
        q = {"questions": [{"question": D["question3"], "header": D["header3"], "multiSelect": True,
                            "options": [{"label": D["opt5"]}, {"label": D["opt6"]}, {"label": D["opt7"]}]}]}
    (d.parent / PKEY2 / (SID2 + ".jsonl")).write_text(line("user", D["tickets"]) + "\n" +
                                                      aline(D["tickets_done"], "t1", 3100) + "\n")
    blog = d.parent / "-Users-x-blog"                  # a third project: only "today by project" sees it
    blog.mkdir(parents=True, exist_ok=True)
    (blog / (SID3 + ".jsonl")).write_text("\n".join(aline("…", "b%d" % i, 700, ago=60 * i) for i in range(4)) + "\n")
    week_of_work(d.parent, time.time())
    p.spend = pultd.S.Spend(d.parent, pultd.skip_pkey)        # the stand's transcripts, never the Mac's own
    await T.run_hook(ev("UserPromptSubmit", SID2, cwd=DESK, prompt=D["tickets"]))
    await T.run_hook(ev("PermissionRequest", SID2, cwd=DESK, tool_name="AskUserQuestion", tool_input=q), wait=False)
    await T.run_hook(ev("Stop", SID2, cwd=DESK, last_assistant_message=D["tickets_done"],
                        background_tasks=[{"id": "b2", "type": "shell", "status": "running", "description": D["bg_run"],
                                           "command": D["bg_cmd"]}]))
    await asyncio.sleep(0.3)
    await T.run_hook(ev("PermissionRequest", SID2, cwd=DESK, tool_name="AskUserQuestion", tool_input=q), wait=False)
    await p.on_run({"op": "start", "id": "j1", "cmd": "python train.py --epochs 40", "cwd": SHOP, "pid": os.getpid()})
    p.jobs["j1"].started -= 1500
    p.jobs["j1"].last = D["job_last"]
    await p.on_run({"op": "start", "id": "j2", "cmd": "npm run build", "cwd": SHOP, "pid": os.getpid()})
    await p.on_run({"op": "end", "id": "j2", "code": 1, "tail": ["src/cart.ts(12,5): error TS2322", "Found 1 error."]})
    # whose move (stage V): a session that ended and needs you, one that reported and you put away, one resting since
    # morning; the lines are what the result-reading model would write
    store.touch_session(SID4, T.PKEY, path=SHOP, title=D["s4_title"])
    (d / (SID4 + ".jsonl")).write_text("\n".join([       # its chat: a long report (folded), then the question
        line("user", D["s4_title"], ago=2500),
        aline(D["s4_report"], "s4a", 2000, ago=2000),
        aline(D["s4_line"] + ". " + D["s4_need"] + "?", "s4b", 600, ago=1500)]) + "\n")
    r = p.attn.finished(SID4, T.PKEY, 840, D["s4_line"], D["s4_line"], waits=True, now=time.time() - 1500)
    p.attn.briefed(SID4, r["ts"], {"line": D["s4_line"], "you": True, "need": D["s4_need"],
                                   "replies": [D["s4_r1"], D["s4_r2"], D["s4_r3"]]}, True)
    # stage F4: an earlier turn made two files, the last one twelve (one deleted since); "To Telegram" is answered
    # here — the stand's projects are made-up paths, so the files are said to be there
    store.add_turn(SID4, T.PKEY, r["ts"] - 3600 - 600, 600, [
        {"p": "reports/search-ranking.pdf", "size": 182000, "mt": r["ts"] - 3700},
        {"p": "search-options.pptx", "size": 2400000, "mt": r["ts"] - 3900}], 2)
    made = [{"p": "reports/search-%02d.png" % i, "size": 90000 + 7000 * i, "mt": r["ts"] - 30 * i} for i in range(1, 10)]
    made = [{"p": "search-summary.docx", "size": 48000, "mt": r["ts"] - 10},
            {"p": "drafts/old-plan.md", "size": 3100, "mt": r["ts"] - 20}] + made + [
            {"p": "search/ranking.py", "size": 12400, "mt": r["ts"] - 400}]
    tid = store.add_turn(SID4, T.PKEY, r["ts"] - 840, 840, made, 112)
    r["turn_files"] = {"id": tid, "n": 112, "size": sum(f["size"] for f in made)}
    real_turn_files = p.api_turn_files

    async def stand_turn_files(sid, turn=None):
        got = await real_turn_files(sid, turn)
        for f in got.get("files") or []:
            f["gone"] = f["p"] == "drafts/old-plan.md"
        return got

    async def stand_send(sid, paths, zip=False):
        print("SEND", sid[:8], json.dumps(paths), "zip" if zip or len(paths) > 10 else "", flush=True)
        return {"sent": paths, "zip": "acme-shop-2026-10-23-1240.zip" if zip or len(paths) > 10 else None, "refused": []}
    p.api_turn_files, p.api_send_files = stand_turn_files, stand_send

    async def stand_new(pkey, text, files=None, model=None, effort=None, vendor=None):   # never launches Claude here
        if vendor not in (None, "claude"):
            p.vendor_for_new(pkey, vendor)            # the computer's own checks: the project allowed, the key there
        print("NEWTASK", pkey, json.dumps(text, ensure_ascii=False), "vendor=%s model=%s" % (vendor, model), flush=True)
        return {"ok": True, "sid": T.SID}
    p.api_new = stand_new
    if os.environ.get("STAND_VENDORS") == "1":         # stage M, step 2: a made-up key, and a session on DeepSeek's model
        import pult_vendors as V
        p.env[V.key_name("deepseek")] = "stand-made-up-key-0000000000"

        async def stand_check(prof, key, proxy=None, transport=None):   # never a vendor's network here: "sk-…" passes
            if key.startswith("sk-"):
                return prof["models"][1].replace("[1m]", "") if len(prof["models"]) > 1 else prof["models"][0]
            raise V.VendorError("key", "Authentication Fails (made up)")
        V.check_key = stand_check
        store.touch_session(SIDV, T.PKEY, path=SHOP, title=D["v_ask"])
        store.set_vendor(SIDV, "deepseek")
        vline = json.loads(aline(D["v_done"], "sv1", 420, ago=900))
        vline["message"]["model"] = "deepseek-flash"
        (d / (SIDV + ".jsonl")).write_text(line("user", D["v_ask"], ago=1200) + "\n" + json.dumps(vline) + "\n")
        r = p.attn.finished(SIDV, T.PKEY, 300, D["v_done"], D["v_done"], waits=True, now=time.time() - 900)
        p.attn.seen(SIDV)
        store.add_turn(SIDV, T.PKEY, r["ts"] - 300, 300, [{"p": "admin/theme.css", "size": 8200, "mt": r["ts"] - 60}], 1)
        # and its next turn runs now, from the app, on the model picked for it — the owner's case (2026-10-30): "Running
        # now" says which model does it, and the model's long name under the field gives way to Stop
        p.set_choice(SIDV, "deepseek-v4-pro[1m]")
        with (d / (SIDV + ".jsonl")).open("a") as f:
            f.write(line("user", D["v_ask2"], ago=50) + "\n")
        await T.run_hook(ev("UserPromptSubmit", SIDV, prompt=D["v_ask2"]))
        await T.run_hook(ev("PostToolUse", SIDV, tool_name="Read", tool_input={"file_path": SHOP + "/storefront/theme.css"}))
        for _ in range(100):                          # the hooks are the daemon's to take in, a moment later
            if SIDV in p.live and p.live[SIDV].turn:
                break
            await asyncio.sleep(0.05)
        p.live[SIDV].driven = True                    # a hook from the app's own session would say so itself
        p.live[SIDV].turn.started -= 50
        p.live[SIDV].run = p.live[SIDV].turn.started
        # the session that waits for you ran on DeepSeek too: its card in "Your move" names the model at its foot (Q108)
        store.set_vendor(SID4, "deepseek")
        p.set_choice(SID4, "deepseek-v4-pro[1m]")
    store.touch_session(SID5, PKEY2, path=DESK, title=D["s5_title"])
    if os.environ.get("STAND_VENDORS") == "1" or os.environ.get("STAND_REPORT") == "1":   # its chat: the ask, the report
        fl = json.loads(aline(D["s5_line"] + ".", "s5", 900, ago=600))
        if os.environ.get("STAND_VENDORS") == "1":     # the weekly report was Fable's: its row on the board says so (Q109)
            fl["message"]["model"] = "claude-fable-5-1"
        (d.parent / PKEY2 / (SID5 + ".jsonl")).write_text(line("user", D["s5_title"], ago=900) + "\n" + json.dumps(fl) + "\n")
    r = p.attn.finished(SID5, PKEY2, 300, D["s5_line"], D["s5_line"], waits=True, now=time.time() - 600)
    # STAND_ASK2=1: it waits for you as well — two in "your move", ten and twenty-five minutes (tools/ask_check.py);
    # STAND_REPORT=1: it waits as the model's "only a report" (tools/gotit_check.py); else the owner has put it away
    p.attn.briefed(SID5, r["ts"], {"line": D["s5_line"], "you": os.environ.get("STAND_ASK2") == "1", "need": ""}, True)
    if os.environ.get("STAND_ASK2") != "1" and os.environ.get("STAND_REPORT") != "1":
        p.attn.seen(SID5)                              # "Got it"
    if os.environ.get("STAND_ASK2") == "1":            # the permission waits fifteen minutes: between the two sessions
        for q_ in p.req_by_rid.values():
            if q_.tool == "Bash":
                q_.ts -= 900
    store.touch_session(SID6, T.PKEY, path=SHOP, title=D["s6_title"])
    p.attn.finished(SID6, T.PKEY, 200, "…", "…", waits=True, now=time.time() - 5 * 3600)
    p.attn.seen(SID6)
    p.attn.day = {"d": pultd.A.today(), "p": {T.PKEY: [14, 7300], PKEY2: [5, 1900]}}
    p.catch_from = time.time() - 2 * 3600 - 600       # "While you were away": the app was last open two hours ago
    p._usage = await fake_usage()                      # the quiet top line reads the last usage, no request
    # and one more at work in the first project, Claude's latest line under it
    (d / (SID7 + ".jsonl")).write_text(line("user", D["s7_ask"], ago=400) + "\n" + aline(D["s7_now"], "s7", 2100) + "\n")
    store.touch_session(SID7, T.PKEY, path=SHOP, title=D["s7_ask"])
    await T.run_hook(ev("UserPromptSubmit", SID7, prompt=D["s7_ask"]))
    await T.run_hook(ev("PostToolUse", SID7, tool_name="Edit", tool_input={"file_path": SHOP + "/admin/theme.css"}))
    p.live[SID7].turn.started -= 400
    p.live[SID7].run = p.live[SID7].turn.started
    p.set_ctx(SID7, 200000, 32000, model="claude-opus-5-5")
    if os.environ.get("STAND_QUEUE") == "1":          # all places taken: a turn of the third session waits in the queue
        import claude_agent_sdk

        class Silent:                                  # Claude Code that never answers: only the queue is seen here
            def __init__(self, options):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                pass

            async def query(self, text):
                print("QUERY", json.dumps(text, ensure_ascii=False), flush=True)

            async def interrupt(self):
                pass

            async def receive_messages(self):
                await asyncio.Event().wait()
                yield
        claude_agent_sdk.ClaudeSDKClient = Silent
        for _ in range(pultd.MAX_RUNNING):
            await p.run_sem.acquire()
        p.live_of(SID6, T.PKEY).driven = True
        dr = p.driven[SID6] = pultd.Driven(p, SID6, SHOP)
        dr.q.put_nowait((D["s6_title"], None))
        await asyncio.sleep(0.3)
        dr.queued -= 130                              # it has waited two minutes
    # the load on the computer: made-up processes for the stand's sessions — the Mac's own are never read here
    await asyncio.sleep(0.5)                  # the hooks above are in: each set its session's process to the stand's
    claude = "/Users/x/.vscode/extensions/anthropic.claude-code-2.1.301-darwin-arm64/resources/native-binary/claude"
    def proc(ppid, cmd, cpu, mb, ago, cpu_time, peak_mb=None):
        return {"ppid": ppid, "cmd": cmd, "cpu": cpu, "mem": mb << 20, "peak": (peak_mb or mb) << 20,
                "cpu_time": cpu_time, "started": time.time() - ago, "mine": True}
    def shell(ppid, c, ago):
        return proc(ppid, "/bin/zsh -c source /Users/x/.claude/shell-snapshots/s.sh 2>/dev/null || true && " +
                    L.quoted(c) + " < /dev/null && pwd -P >| /tmp/claude-1a2b-cwd", 0.0, 1, ago, 0.1)
    procs = {1001: proc(1, claude, 6.0, 310, 3 * 3600, 240), 1002: shell(1001, "pytest tests/e2e -n 4", 380),
             1003: proc(1002, "python -m pytest tests/e2e -n 4", 180.0, 640, 379, 610, 900),
             1004: proc(1001, "node /Users/x/.mcp/browser/server.js", 9.0, 220, 3 * 3600, 95),
             2001: proc(1, claude, 1.5, 260, 2 * 3600, 120), 2002: shell(2001, D["bg_cmd"], 1500),
             2003: proc(2002, D["bg_cmd"], 96.0, 180, 1499, 1380, 410),
             3001: proc(1, claude, 0.2, 170, 26 * 3600, 60)}
    p._procs = (time.monotonic() + 1e6, (procs, {"cores": 8, "cpu": 41.0, "mem_total": 16 << 30,
                                                 "mem_used": int(10.4 * (1 << 30)), "load": 3.6}))
    agents = [{"sessionId": SID3, "cwd": "/Users/x/blog", "pid": 3001}]
    if os.environ.get("STAND_COPY") == "1":     # the session waiting for you, open in a tab on an unchecked Claude Code
        procs[4001] = proc(1, claude.replace("2.1.301", "2.1.311"), 0.3, 240, 5400, 40)
        agents.append({"sessionId": SID4, "cwd": SHOP, "pid": 4001})
    p._agents = (time.monotonic() + 1e6, agents)
    p.live[T.SID].pid, p.live[SID2].pid = 1001, 2001
    if os.environ.get("STAND_TAGS"):
        tag_pk, tag_sids = await stand_tags(p, store, d.parent)
        print("PROJT http://127.0.0.1:%d/pult/#tgWebAppData=%s&tgWebAppVersion=8.0&tgWebAppPlatform=android" %
              (PORT, urllib.parse.quote(init("p_" + tag_pk))), flush=True)        # the printer's project
        print("SESST http://127.0.0.1:%d/pult/#tgWebAppData=%s&tgWebAppVersion=8.0&tgWebAppPlatform=android" %
              (PORT, urllib.parse.quote(init("s_" + tag_sids[0]))), flush=True)   # its task that waits for you
        print("TAGPK", tag_pk, flush=True)
        if os.environ.get("STAND_TAGJOB"):
            print("TAGJOB 1", flush=True)
    print("LOAD http://127.0.0.1:%d/pult/#tgWebAppData=%s&tgWebAppVersion=8.0&tgWebAppPlatform=android" %
          (PORT, urllib.parse.quote(init("load"))), flush=True)
    print("SETTINGS http://127.0.0.1:%d/pult/#tgWebAppData=%s&tgWebAppVersion=8.0&tgWebAppPlatform=android" %
          (PORT, urllib.parse.quote(init("settings"))), flush=True)
    print("HOME http://127.0.0.1:%d/pult/#tgWebAppData=%s&tgWebAppVersion=8.0&tgWebAppPlatform=android" %
          (PORT, urllib.parse.quote(init("home"))), flush=True)
    # opened as the bot's menu button and Pult's plain links open it: no start parameter
    print("PLAIN http://127.0.0.1:%d/pult/#tgWebAppData=%s&tgWebAppVersion=8.0&tgWebAppPlatform=android" %
          (PORT, urllib.parse.quote(init(""))), flush=True)
    print("USAGE http://127.0.0.1:%d/pult/#tgWebAppData=%s&tgWebAppVersion=8.0&tgWebAppPlatform=android" %
          (PORT, urllib.parse.quote(init("usage"))), flush=True)
    print("SESS http://127.0.0.1:%d/pult/#tgWebAppData=%s&tgWebAppVersion=8.0&tgWebAppPlatform=android" %
          (PORT, urllib.parse.quote(init("s_" + T.SID))), flush=True)
    print("NEW http://127.0.0.1:%d/pult/#tgWebAppData=%s&tgWebAppVersion=8.0&tgWebAppPlatform=android" %
          (PORT, urllib.parse.quote(init("new"))), flush=True)
    print("PROJ http://127.0.0.1:%d/pult/#tgWebAppData=%s&tgWebAppVersion=8.0&tgWebAppPlatform=android" %
          (PORT, urllib.parse.quote(init("p_" + T.PKEY))), flush=True)       # a project topic's pinned card
    print("SESS4 http://127.0.0.1:%d/pult/#tgWebAppData=%s&tgWebAppVersion=8.0&tgWebAppPlatform=android" %
          (PORT, urllib.parse.quote(init("s_" + SID4))), flush=True)       # a session that waits for you: its outcome card
    if os.environ.get("STAND_VENDORS") == "1":
        print("SESSV http://127.0.0.1:%d/pult/#tgWebAppData=%s&tgWebAppVersion=8.0&tgWebAppPlatform=android" %
              (PORT, urllib.parse.quote(init("s_" + SIDV))), flush=True)   # a session on DeepSeek's model
    print("PROJECTS http://127.0.0.1:%d/pult/#tgWebAppData=%s&tgWebAppVersion=8.0&tgWebAppPlatform=android" %
          (PORT, urllib.parse.quote(init("projects"))), flush=True)
    print("NEWPROJ http://127.0.0.1:%d/pult/#tgWebAppData=%s&tgWebAppVersion=8.0&tgWebAppPlatform=android" %
          (PORT, urllib.parse.quote(init("newproject"))), flush=True)
    if os.environ.get("STAND_DUMP") == "1":            # what went to Telegram — the README's examples come from here
        await asyncio.sleep(2)
        for m, d in fake.calls:
            if m in ("sendMessage", "editMessageText"):
                print("TG", m, json.dumps(d.get("text"), ensure_ascii=False), flush=True)
    await asyncio.sleep(HOLD)
    sock.close()
    await runner.cleanup()

asyncio.run(main())
