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
gives the question a second one, a second session waiting for you and a permission older than it, STAND_QUEUE=1 puts a turn in the queue (all places taken), STAND_UPD=ok|ready|busy|
wait|run|fail shows Settings → Pult and Home's line in that state (no installer ever runs), STAND_PORT=<port> runs a
second stand beside one already up. STAND_TICKS=<s> opens the first session in a tab that reads each message <s> s
later, as Claude Code does at its turn's next step — a message with "#gone" is dropped instead (tools/ticks_check.py).
STAND_FILES=1 gives the shop a real folder with made-up files and ends the chat with links to them (tools/fileview_check.py)."""
import asyncio, base64, hashlib, hmac, json, os, random, sys, time, urllib.parse
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tests"))
import test_web as W  # noqa: E402  (keys, relay with the test key)
T, PW, pultd, relay = W.T, W.PW, W.pultd, W.relay
import pult_load as L  # noqa: E402
from aiohttp import web  # noqa: E402

HOLD = float(os.environ.get("HOLD", "90"))
PORT = int(os.environ.get("STAND_PORT", "18097"))   # another one for a second stand at the same time
LANG = os.environ.get("STAND_LANG", "en")
SID2 = "22222222-2222-4222-8222-222222222222"
SID3 = "33333333-3333-4333-8333-333333333333"
SID4, SID5, SID6, SID7 = ("%s-4444-4444-8444-444444444444" % (c * 8) for c in "4567")
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
        s7_ask="Add a dark theme to the admin panel", s7_now="Colours are variables now; the tables and charts are next."),
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
        s7_ask="Сделай тёмную тему для админки", s7_now="Цвета вынесены в переменные; дальше — таблицы и графики."),
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


async def main():
    pultd.CLAUDE_PROJECTS = Path(T.TP).parent.parent      # made-up transcripts only: never the Mac's own sessions
    fake = T.FakeTg()
    tg = pultd.Tg("T", transport=T.httpx.MockTransport(fake.handler))
    store = pultd.Store(T.TMP / "harness.db")
    store.put("chat", T.CHAT)
    store.put("lang_tg", LANG)                                   # the language of the bot and the app
    store.set_topic(T.PKEY, SHOP, "acme-shop", 77)
    store.set_topic(PKEY2, DESK, "support-desk", 78)
    if os.environ.get("STAND_FILES") == "1":                 # stage F5: links in Claude's words open the project's files
        store.set_topic(T.PKEY, str(shop_files()), "acme-shop", 77)
    p = pultd.Pult({"PULT_ALLOWED_USER_IDS": str(T.OWNER), "PULT_FORCE_AWAY": "1"}, tg, store)
    p.out = pultd.Outbox(rate=60000, burst=1000)
    p._agents = (time.monotonic() + 1e6, [{"sessionId": SID3, "cwd": "/Users/x/blog"}])
    pultd.EDIT_EVERY = 0.2
    # stage S: a made-up home folder for "New project" (the stand's temp folder, listed like a real one); the first
    # turn of a new project is not started — the stand never runs Claude
    home = T.TMP / "stand-home"
    for d in ("Documents/acme-shop", "Documents/support-desk", "Code"):
        (home / d).mkdir(parents=True, exist_ok=True)
    pultd.NEW_ROOT, pultd.SKIP_PREFIXES = home, ("-nothing-",)
    pultd.TAB_CONF = T.TMP / "stand-tab.json"
    pultd.TAB_CONF.write_text(json.dumps({"folders": [str(home / "Documents")]}))

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
    if upd:
        import pult_update as U
        nums = [int(x) for x in pultd.VERSION.split(".")]
        nxt = "%d.%d.%d" % (nums[0], nums[1], nums[2] + 1)
        head = "5e1f0a2" + "c" * 33
        U.check = lambda manifest=None: {
            "repo": str(Path.home() / "pult"), "head": head, "short": head[:7], "ready": upd != "ok", "version": nxt,
            "news": ["Pult %s: install an update from the app" % nxt, "Settings: what was installed, when and from where"],
            "failed": upd == "fail"}
        U.spawn = lambda commit, how, python=None: U.write(U.STATUS, {        # never a real installer here
            "state": "run", "step": "check", "to": nxt, "ts": time.time(), "pid": os.getpid()}) or True
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
    # whose move (stage V): a session that ended and needs you, one that only reported, one resting since morning;
    # the lines are what the result-reading model would write
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

    async def stand_new(pkey, text, files=None, model=None, effort=None):   # a new task never launches Claude here
        print("NEWTASK", pkey, json.dumps(text, ensure_ascii=False), flush=True)
        return {"ok": True, "sid": T.SID}
    p.api_new = stand_new
    store.touch_session(SID5, PKEY2, path=DESK, title=D["s5_title"])
    r = p.attn.finished(SID5, PKEY2, 300, D["s5_line"], D["s5_line"], waits=True, now=time.time() - 600)
    # STAND_ASK2=1: it waits for you as well — two in "your move", ten and twenty-five minutes (tools/ask_check.py)
    p.attn.briefed(SID5, r["ts"], {"line": D["s5_line"], "you": os.environ.get("STAND_ASK2") == "1", "need": ""}, True)
    if os.environ.get("STAND_ASK2") == "1":            # the permission waits fifteen minutes: between the two sessions
        for q_ in p.req_by_rid.values():
            if q_.tool == "Bash":
                q_.ts -= 900
    store.touch_session(SID6, T.PKEY, path=SHOP, title=D["s6_title"])
    p.attn.finished(SID6, T.PKEY, 200, "…", "…", waits=True, seen=True, now=time.time() - 5 * 3600)
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
    p._agents = (time.monotonic() + 1e6, [{"sessionId": SID3, "cwd": "/Users/x/blog", "pid": 3001}])
    p.live[T.SID].pid, p.live[SID2].pid = 1001, 2001
    print("LOAD http://127.0.0.1:%d/pult/#tgWebAppData=%s&tgWebAppVersion=8.0&tgWebAppPlatform=android" %
          (PORT, urllib.parse.quote(init("load"))), flush=True)
    print("SETTINGS http://127.0.0.1:%d/pult/#tgWebAppData=%s&tgWebAppVersion=8.0&tgWebAppPlatform=android" %
          (PORT, urllib.parse.quote(init("settings"))), flush=True)
    print("HOME http://127.0.0.1:%d/pult/#tgWebAppData=%s&tgWebAppVersion=8.0&tgWebAppPlatform=android" %
          (PORT, urllib.parse.quote(init("home"))), flush=True)
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
