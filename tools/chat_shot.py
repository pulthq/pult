"""A picture of a project topic for the README: the messages Pult sends, drawn as chat bubbles.

The daemon runs for real with a fake Telegram (the harness of tests/test_pult.py) on the same made-up project as
tools/stand.py: a finished turn, the owner's next message, the turn running with Claude's words, and a permission
request with its buttons. The bubbles are a plain rendering of Pult's own output — not a Telegram screenshot — so
the README never shows real projects and the picture follows the code.

  STAND_LANG=ru ~/.local/share/pult/venv/bin/python tools/chat_shot.py media/chat.ru.png
"""
import asyncio, html, json, os, subprocess, sys, tempfile, time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tests"))
import test_pult as T  # noqa: E402  (fake Telegram, the real hook, a temporary home)
pultd = T.pultd

LANG = os.environ.get("STAND_LANG", "en")
OUT = Path(sys.argv[1] if len(sys.argv) > 1 else "chat.%s.png" % LANG).resolve()
SHOP = "/Users/x/acme-shop"

D = {
    "en": dict(
        title="Checkout: clearer error messages",
        ask="Make the checkout error messages clearer",
        summary="All **27 tests** pass. What changed:\n\n- a declined card says why and what to do;\n"
                "- a timeout offers to try again.",
        ask2="Now deploy to staging",
        now="Deploying to staging and checking the checkout page there.",
        cmd="make deploy-staging && git commit -qm 'Checkout: clearer errors'", cmd_desc="Deploy to staging and commit",
        me="You", bot="Pult", topic="acme-shop"),
    "ru": dict(
        title="Оформление заказа: понятные ошибки",
        ask="Сделай сообщения об ошибках при оплате понятнее",
        summary="Все **27 тестов** зелёные. Что поменялось:\n\n- отказ по карте объясняет причину и что делать;\n"
                "- при тайм-ауте — предложение повторить.",
        ask2="Теперь выложи на стенд",
        now="Выкладываю на стенд и проверяю там страницу оплаты.",
        cmd="make deploy-staging && git commit -qm 'Checkout: clearer errors'", cmd_desc="Выложить на стенд и закоммитить",
        me="Ты", bot="Пульт", topic="acme-shop"),
}[LANG if LANG in ("en", "ru") else "en"]

CSS = """
* { box-sizing: border-box; }
body { margin: 0; background: #e6ebf1; font: 15px/1.4 -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; color: #1a1d22; }
.chat { width: 412px; padding: 10px 10px 14px; }
.topic { text-align: center; color: #5b6472; font-size: 13px; font-weight: 600; margin: 4px 0 10px; }
.msg { position: relative; max-width: 360px; margin: 8px 0; padding: 8px 12px 8px; border-radius: 14px; background: #fff;
  box-shadow: 0 1px 1px rgba(0,0,0,.06); overflow-wrap: anywhere; }
.msg.me { margin-left: auto; background: #d9e8ff; border-bottom-right-radius: 4px; }
.msg.bot { border-bottom-left-radius: 4px; }
.name { color: #2f6fcf; font-size: 13px; font-weight: 600; margin-bottom: 2px; }
.body { white-space: pre-wrap; }
.body pre { background: #f0f2f5; border-radius: 8px; padding: 7px 9px; margin: 6px 0 2px; font: 12.5px/1.4 ui-monospace, Menlo, monospace; white-space: pre-wrap; }
.body code { font: 13px ui-monospace, Menlo, monospace; background: #f0f2f5; border-radius: 4px; padding: 0 3px; }
.time { text-align: right; color: #8a93a0; font-size: 11.5px; margin-top: 2px; }
.kb { margin: 8px -6px -4px; }
.row { display: flex; gap: 4px; margin-top: 4px; }
.btn { flex: 1; text-align: center; background: #eef2f7; color: #2f6fcf; border-radius: 8px; padding: 7px 6px; font-size: 13.5px; font-weight: 500;
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
"""


def bubble(kind, body_html, when, name=None, buttons=None):
    kb = ""
    if buttons:
        rows = "".join('<div class="row">%s</div>' % "".join('<span class="btn">%s</span>' % html.escape(b["text"]) for b in row)
                       for row in buttons)
        kb = '<div class="kb">%s</div>' % rows
    return '<div class="msg %s">%s<div class="body">%s</div><div class="time">%s</div>%s</div>' % (
        kind, '<div class="name">%s</div>' % html.escape(name) if name else "", body_html, when, kb)


async def main():
    fake = T.FakeTg()
    tg = pultd.Tg("T", transport=T.httpx.MockTransport(fake.handler))
    store = pultd.Store(T.TMP / "chat-shot.db")
    store.put("chat", T.CHAT)
    store.put("lang_tg", LANG)
    store.set_topic(T.PKEY, SHOP, D["topic"], 77)
    p = pultd.Pult({"PULT_ALLOWED_USER_IDS": str(T.OWNER), "PULT_FORCE_AWAY": "1"}, tg, store)
    p.out = pultd.Outbox(rate=60000, burst=1000)
    p._agents = (time.monotonic() + 1e6, [])
    pultd.EDIT_EVERY = 0.1
    sock = await asyncio.start_unix_server(p.handle_conn, path=os.environ["PULT_SOCK"])
    asyncio.create_task(p.out.run())
    Path(T.TP).parent.mkdir(parents=True, exist_ok=True)
    Path(T.TP).write_text("")

    # 1. a finished turn: its result with Claude's summary
    await T.run_hook(T.ev("SessionStart", source="startup"))
    await T.run_hook(T.ev("UserPromptSubmit", prompt=D["ask"]))
    await T.until(lambda: p.live[T.SID].turn and p.live[T.SID].turn.msg)
    p.live[T.SID].title, p.live[T.SID].named = D["title"], True
    p.live[T.SID].turn.started -= 12 * 60
    await T.run_hook(T.ev("Stop", last_assistant_message=D["summary"]))
    await T.until(lambda: any(t.startswith("✅") for t in [d.get("text", "") for d in fake.of("sendMessage")]))
    first_turn = p.live[T.SID].turn  # None now; the finished turn's message is edited to ✔️ — not in the picture

    # 2. the owner's next message starts a turn; Claude's words show up in it; then a permission request
    n_before = len(fake.calls)
    await T.run_hook(T.ev("UserPromptSubmit", prompt=D["ask2"]))
    await T.until(lambda: p.live[T.SID].turn and p.live[T.SID].turn.msg)
    p.live[T.SID].turn.started -= 6 * 60
    with open(T.TP, "a") as f:
        f.write(T.tline("assistant", D["now"]) + "\n")
    await T.run_hook(T.ev("PostToolUse", tool_name="Read", tool_input={"file_path": SHOP + "/checkout/errors.py"}))
    await T.until(lambda: any("💬" in d.get("text", "") for d in fake.of("editMessageText")))
    await T.run_hook(T.ev("PermissionRequest", tool_name="Bash", tool_input={"command": D["cmd"], "description": D["cmd_desc"]},
                          permission_suggestions=[{"type": "addRules"}]), wait=False)
    await T.until(lambda: fake.buttons("p:"))
    await asyncio.sleep(0.3)

    # the final state of every message: sends in order, edits applied (FakeTg numbers the calls from 1001)
    msgs, order = {}, []
    for k, (m, d) in enumerate(fake.calls):
        mid = 1000 + k + 1
        if m == "sendMessage":
            msgs[mid] = dict(text=d.get("text", ""), kb=json.loads(d["reply_markup"])["inline_keyboard"] if d.get("reply_markup") else None)
            order.append(mid)
        elif m == "editMessageText" and int(d["message_id"]) in msgs:
            msgs[int(d["message_id"])] = dict(text=d.get("text", ""), kb=json.loads(d["reply_markup"])["inline_keyboard"] if d.get("reply_markup") else None)
    result = next(mid for mid in order if msgs[mid]["text"].startswith("✅"))
    turn2 = next(mid for mid in order if msgs[mid]["text"].startswith("⏳") and "💬" in msgs[mid]["text"])
    perm = next(mid for mid in order if msgs[mid]["text"].startswith("✋"))
    t0 = time.time()
    hm = lambda ago: time.strftime("%H:%M", time.localtime(t0 - ago))
    parts = [
        '<div class="topic">📂 %s</div>' % html.escape(D["topic"]),
        bubble("bot", msgs[result]["text"], hm(14 * 60), D["bot"]),
        bubble("me", html.escape(D["ask2"]), hm(6 * 60 + 20)),
        bubble("bot", msgs[turn2]["text"], hm(6 * 60), D["bot"]),
        bubble("bot", msgs[perm]["text"], hm(20), D["bot"], msgs[perm]["kb"]),
    ]
    page = ('<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">'
            '<style>%s</style><div class="chat">%s</div>' % (CSS, "".join(parts)))
    tmp = Path(tempfile.mkdtemp(prefix="chat-shot-")) / ("chat.%s.html" % LANG)
    tmp.write_text(page, encoding="utf-8")
    subprocess.run([sys.executable, str(REPO / "tools" / "shot.py"), tmp.as_uri(), str(OUT), "412", "1.5"], check=True,
                   env=dict(os.environ, SHOT_FIT=".chat"))
    sock.close()


asyncio.run(main())
