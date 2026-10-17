"""Web app test stand: a local relay (127.0.0.1:18097) + the daemon with a fake Telegram and made-up sessions:
one working, one waiting for a permission, one waiting for an answer, jobs without Claude, a final result. Login
is signed with test keys (tests/test_web.py). Prints the screen URLs (HOME, SESS, USAGE, SETTINGS, NEW, PROJ, PROJECTS), stays up HOLD s.

  HOLD=300 ~/.local/share/pult/venv/bin/python tools/stand.py > /tmp/stand.out &
  ~/.local/share/pult/venv/bin/python tools/shot.py "$(grep ^HOME /tmp/stand.out | cut -d' ' -f2)" home.png 412 4 [dark]

Telegram passes initData in the URL after # (tgWebAppData=…); that is how the stand opens the app without Telegram.
Usage is stubbed (82 %): the real request launches Claude Code. The data is made up and neutral — the screenshots go
into the public README: STAND_LANG=en|ru picks the texts, STAND_XSS=1 adds markup that must stay text."""
import asyncio, base64, hashlib, hmac, json, os, sys, time, urllib.parse
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tests"))
import test_web as W  # noqa: E402  (keys, relay with the test key)
T, PW, pultd, relay = W.T, W.PW, W.pultd, W.relay
from aiohttp import web  # noqa: E402

HOLD = float(os.environ.get("HOLD", "90"))
LANG = os.environ.get("STAND_LANG", "en")
SID2 = "22222222-2222-4222-8222-222222222222"
SID3 = "33333333-3333-4333-8333-333333333333"
SHOP, DESK = "/Users/x/acme-shop", "/Users/x/support-desk"
PKEY2 = "-Users-x-support-desk"

# Made-up sessions in two languages. Nothing here may be about real projects: it ends up on the public page.
D = {
    "en": dict(
        title="Checkout: clearer error messages",
        ask="Make the checkout error messages clearer, following the examples in the design doc",
        ask_short="Make the checkout error messages clearer",
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
        tickets_done="Sorted **12 tickets**: 3 urgent, 9 can wait. The list is in the report.",
        bg_run="Export the tickets to the CRM",
        job_last="epoch 27/40 · loss 0.31", user="Sam"),
    "ru": dict(
        title="Оформление заказа: понятные ошибки",
        ask="Сделай сообщения об ошибках при оплате понятнее, по примерам из макета",
        ask_short="Сделай сообщения об ошибках при оплате понятнее",
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
        tickets_done="Разобрал **12 заявок**: 3 срочные, 9 подождут. Список — в отчёте.",
        bg_run="Выгрузка заявок в CRM",
        job_last="эпоха 27/40 · потери 0,31", user="Саша"),
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
                                   "usage": {"input_tokens": 2, "cache_read_input_tokens": 183000, "output_tokens": out}}})


def ev(name, sid, cwd=SHOP, **kw):
    folder = Path(T.TP).parent if cwd == SHOP else Path(T.TP).parent.parent / PKEY2
    return dict(hook_event_name=name, session_id=sid, transcript_path=str(folder / (sid + ".jsonl")), cwd=cwd, **kw)


async def main():
    pultd.CLAUDE_PROJECTS = Path(T.TP).parent.parent      # made-up transcripts only: never the Mac's own sessions
    fake = T.FakeTg()
    tg = pultd.Tg("T", transport=T.httpx.MockTransport(fake.handler))
    store = pultd.Store(T.TMP / "harness.db")
    store.put("chat", T.CHAT)
    store.put("lang_tg", LANG)                                   # the language of the bot and the app
    store.set_topic(T.PKEY, SHOP, "acme-shop", 77)
    store.set_topic(PKEY2, DESK, "support-desk", 78)
    p = pultd.Pult({"PULT_ALLOWED_USER_IDS": str(T.OWNER), "PULT_FORCE_AWAY": "1"}, tg, store)
    p.out = pultd.Outbox(rate=60000, burst=1000)
    p._agents = (time.monotonic() + 1e6, [{"sessionId": SID3, "cwd": "/Users/x/blog"}])
    pultd.EDIT_EVERY = 0.2
    sock = await asyncio.start_unix_server(p.handle_conn, path=os.environ["PULT_SOCK"])
    runner = web.AppRunner(relay.app())
    await runner.setup()
    await web.TCPSite(runner, "127.0.0.1", 18097).start()
    async def fake_usage(force=False):
        r = W.usage_reply(session=82, week=41, fable=3)
        for lim in r["rate_limits"]["limits"]:                 # resets in the future, as in real life
            ahead = 2 * 3600 + 600 if lim["kind"] == "session" else 3 * 86400 + 5 * 3600
            lim["resets_at"] = time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime(time.time() + ahead))
        return PW.simplify_usage(r)
    p.usage = fake_usage
    p.web = PW.Web(p, "ws://127.0.0.1:18097/pult/agent", "s3cret", W.TOKEN, {T.OWNER})
    asyncio.create_task(p.out.run())
    asyncio.create_task(p.web.run())

    d = Path(T.TP).parent
    d.mkdir(parents=True, exist_ok=True)
    (d.parent / PKEY2).mkdir(parents=True, exist_ok=True)
    summary = D["summary"] + ("\n<script>alert(1)</script>" if os.environ.get("STAND_XSS") == "1" else "")
    (d / (T.SID + ".jsonl")).write_text("\n".join([
        line("user", D["ask"], ago=86400),
        json.dumps({"type": "assistant", "effort": "xhigh", "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime()),
                    "message": {"id": "u1", "model": "claude-opus-5-5", "role": "assistant", "content": [],
                                "usage": {"input_tokens": 2, "cache_read_input_tokens": 182000, "cache_creation_input_tokens": 900,
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
        aline(D["after_bg"], "u5", 1400),
    ]) + "\n")
    store.touch_session(T.SID, T.PKEY, path=SHOP, title=D["title"])
    await T.run_hook(ev("SessionStart", T.SID))
    await T.run_hook(ev("UserPromptSubmit", T.SID, prompt=D["ask_short"]))
    p.live[T.SID].title, p.live[T.SID].named = D["title"], True
    with (d / (T.SID + ".jsonl")).open("a") as f:
        f.write(aline(D["now"], "u6", 900) + "\n")
    await T.run_hook(ev("PostToolUse", T.SID, tool_name="Read", tool_input={"file_path": SHOP + "/checkout/errors.py"}))
    p.live[T.SID].turn.started -= 380
    await T.run_hook(ev("PermissionRequest", T.SID, tool_name="Bash",
                        tool_input={"command": D["cmd"], "description": D["cmd_desc"]},
                        permission_suggestions=[{"type": "addRules"}]), wait=False)
    q = {"questions": [{"question": D["question"], "header": D["header"], "multiSelect": False,
                        "options": [{"label": D["opt1"], "description": D["opt1d"]}, {"label": D["opt2"]}]}]}
    (d.parent / PKEY2 / (SID2 + ".jsonl")).write_text(line("user", D["tickets"]) + "\n" +
                                                      aline(D["tickets_done"], "t1", 3100) + "\n")
    blog = d.parent / "-Users-x-blog"                  # a third project: only "today by project" sees it
    blog.mkdir(parents=True, exist_ok=True)
    (blog / (SID3 + ".jsonl")).write_text("\n".join(aline("…", "b%d" % i, 700, ago=60 * i) for i in range(4)) + "\n")
    p.day_tokens = PW.DayTokens(d.parent, pultd.skip_pkey)     # the stand's transcripts, never the Mac's own
    await T.run_hook(ev("UserPromptSubmit", SID2, cwd=DESK, prompt=D["tickets"]))
    await T.run_hook(ev("PermissionRequest", SID2, cwd=DESK, tool_name="AskUserQuestion", tool_input=q), wait=False)
    await T.run_hook(ev("Stop", SID2, cwd=DESK, last_assistant_message=D["tickets_done"],
                        background_tasks=[{"id": "b2", "type": "shell", "status": "running", "description": D["bg_run"]}]))
    await asyncio.sleep(0.3)
    await T.run_hook(ev("PermissionRequest", SID2, cwd=DESK, tool_name="AskUserQuestion", tool_input=q), wait=False)
    await p.on_run({"op": "start", "id": "j1", "cmd": "python train.py --epochs 40", "cwd": SHOP, "pid": os.getpid()})
    p.jobs["j1"].started -= 1500
    p.jobs["j1"].last = D["job_last"]
    await p.on_run({"op": "start", "id": "j2", "cmd": "npm run build", "cwd": SHOP, "pid": os.getpid()})
    await p.on_run({"op": "end", "id": "j2", "code": 1, "tail": ["src/cart.ts(12,5): error TS2322", "Found 1 error."]})
    print("SETTINGS http://127.0.0.1:18097/pult/#tgWebAppData=%s&tgWebAppVersion=8.0&tgWebAppPlatform=android" %
          urllib.parse.quote(init("settings")), flush=True)
    print("HOME http://127.0.0.1:18097/pult/#tgWebAppData=%s&tgWebAppVersion=8.0&tgWebAppPlatform=android" %
          urllib.parse.quote(init("home")), flush=True)
    print("USAGE http://127.0.0.1:18097/pult/#tgWebAppData=%s&tgWebAppVersion=8.0&tgWebAppPlatform=android" %
          urllib.parse.quote(init("usage")), flush=True)
    print("SESS http://127.0.0.1:18097/pult/#tgWebAppData=%s&tgWebAppVersion=8.0&tgWebAppPlatform=android" %
          urllib.parse.quote(init("s_" + T.SID)), flush=True)
    print("NEW http://127.0.0.1:18097/pult/#tgWebAppData=%s&tgWebAppVersion=8.0&tgWebAppPlatform=android" %
          urllib.parse.quote(init("new")), flush=True)
    print("PROJ http://127.0.0.1:18097/pult/#tgWebAppData=%s&tgWebAppVersion=8.0&tgWebAppPlatform=android" %
          urllib.parse.quote(init("p_" + T.PKEY)), flush=True)       # a project topic's pinned card
    print("PROJECTS http://127.0.0.1:18097/pult/#tgWebAppData=%s&tgWebAppVersion=8.0&tgWebAppPlatform=android" %
          urllib.parse.quote(init("projects")), flush=True)
    if os.environ.get("STAND_DUMP") == "1":            # what went to Telegram — the README's examples come from here
        await asyncio.sleep(2)
        for m, d in fake.calls:
            if m in ("sendMessage", "editMessageText"):
                print("TG", m, json.dumps(d.get("text"), ensure_ascii=False), flush=True)
    await asyncio.sleep(HOLD)
    sock.close()
    await runner.cleanup()

asyncio.run(main())
