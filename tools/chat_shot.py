"""A picture of a project topic for the README: the messages Pult sends, drawn as chat bubbles.

The daemon runs for real with a fake Telegram (the harness of tests/test_pult.py) on the same made-up project as
tools/stand.py: a finished turn, the owner's next message, the turn running with Claude's words, and a permission
request with its buttons. The bubbles are a plain rendering of Pult's own output — not a Telegram screenshot — so
the README never shows real projects and the picture follows the code.

  STAND_LANG=ru ~/.local/share/pult/venv/bin/python tools/chat_shot.py chat.ru.png
  STAND_LANG=ru ~/.local/share/pult/venv/bin/python tools/chat_shot.py demo.ru.gif

A .gif is the topic's animation (the README's opening picture until stage D6; now tools/hero.py draws that, with the
computer's tab next to the phone): the same run, frame by frame, on a phone-sized screen — the
result of a turn, your next message, Claude at work, a permission request with the phone's notification, a tap on
Allow, the turn going on, its result. Frames are drawn with tools/shot.py and joined with ffmpeg.
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
        done2="Deployed to staging: the checkout page shows the new messages for a declined card and a timeout. "
              "Committed as `Checkout: clearer errors`.",
        me="You", bot="Pult", topic="acme-shop", group="Pult · topic", write="Message", now_word="now"),
    "ru": dict(
        title="Оформление заказа: понятные ошибки",
        ask="Сделай сообщения об ошибках при оплате понятнее",
        summary="Все **27 тестов** зелёные. Что поменялось:\n\n- отказ по карте объясняет причину и что делать;\n"
                "- при тайм-ауте — предложение повторить.",
        ask2="Теперь выложи на стенд",
        now="Выкладываю на стенд и проверяю там страницу оплаты.",
        cmd="make deploy-staging && git commit -qm 'Checkout: clearer errors'", cmd_desc="Выложить на стенд и закоммитить",
        done2="Выложено на стенд: страница оплаты показывает новые сообщения об отказе карты и тайм-ауте. "
              "Коммит — `Checkout: clearer errors`.",
        me="Ты", bot="Пульт", topic="acme-shop", group="Пульт · тема", write="Сообщение", now_word="сейчас"),
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
# the animation's phone screen: a topic's header, the chat pinned to the bottom, the message field; a notification
PHONE_CSS = """
.phone { position: relative; width: 390px; height: 700px; display: flex; flex-direction: column; background: #e6ebf1; overflow: hidden; }
.bar { flex: none; display: flex; align-items: center; gap: 14px; padding: 10px 14px; background: #fff; border-bottom: 1px solid #dde3ea; }
.back { font-size: 22px; color: #6b7480; }
.ttl b { display: block; font-size: 16px; }
.ttl span { font-size: 12.5px; color: #8a93a0; }
.phone .chat { flex: 1; width: auto; display: flex; flex-direction: column; justify-content: flex-end; overflow: hidden; padding: 0 10px 8px; }
.phone .msg { flex: none; }
.compose { flex: none; display: flex; align-items: center; gap: 10px; padding: 9px 12px; background: #fff; border-top: 1px solid #dde3ea; color: #9aa3ae; }
.compose .in { flex: 1; background: #f0f2f5; border-radius: 18px; padding: 8px 14px; font-size: 15px; }
.push { position: absolute; top: 8px; left: 8px; right: 8px; background: #fff; border-radius: 16px; padding: 10px 13px;
  box-shadow: 0 6px 22px rgba(20,30,50,.22); font-size: 13.5px; }
.push .app { display: flex; align-items: center; gap: 7px; color: #6b7480; font-size: 12px; margin-bottom: 3px; }
.push .ico { width: 18px; height: 18px; border-radius: 5px; background: #2aa3e0; color: #fff; font-size: 11px; font-weight: 700;
  display: flex; align-items: center; justify-content: center; }
.push b { display: block; }
.btn.tap { background: #cfe0f7; position: relative; overflow: visible; }
.btn.tap::after { content: ""; position: absolute; left: 50%; top: 50%; width: 44px; height: 44px; margin: -22px 0 0 -22px; border-radius: 50%;
  background: rgba(47,111,207,.25); box-shadow: 0 0 0 6px rgba(47,111,207,.12); }
"""


def bubble(kind, body_html, when, name=None, buttons=None):
    kb = ""
    if buttons:
        rows = "".join('<div class="row">%s</div>' % "".join('<span class="btn">%s</span>' % html.escape(b["text"]) for b in row)
                       for row in buttons)
        kb = '<div class="kb">%s</div>' % rows
    return '<div class="msg %s">%s<div class="body">%s</div><div class="time">%s</div>%s</div>' % (
        kind, '<div class="name">%s</div>' % html.escape(name) if name else "", body_html, when, kb)


def state(fake):
    """Every message as it stands now: sends in order, edits applied, deleted ones gone — a turn's "⏳ working" message
    leaves when its result comes (FakeTg numbers the calls from 1001)."""
    msgs, order = {}, []
    for k, (m, d) in enumerate(fake.calls):
        mid = 1000 + k + 1
        kb = json.loads(d["reply_markup"])["inline_keyboard"] if d.get("reply_markup") else None
        if m == "sendMessage":
            msgs[mid] = dict(text=d.get("text", ""), kb=kb)
            order.append(mid)
        elif m == "editMessageText" and int(d["message_id"]) in msgs:
            msgs[int(d["message_id"])] = dict(text=d.get("text", ""), kb=kb)
        elif m == "deleteMessage" and int(d["message_id"]) in msgs:
            order.remove(int(d["message_id"]))
    return [dict(msgs[mid], mid=mid) for mid in order]


def phone(parts, push=None):
    """A frame of the animation: the topic's screen with these bubbles, and a notification on top if any."""
    note = ('<div class="push"><div class="app"><span class="ico">✈</span>Telegram · %s</div><b>%s</b>%s</div>' % push) if push else ""
    return ('<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">'
            '<style>%s%s</style><div class="phone"><div class="bar"><span class="back">←</span><div class="ttl"><b>%s</b>'
            '<span>%s</span></div></div><div class="chat">%s</div><div class="compose"><span class="in">%s</span>'
            '<span>🎤</span></div>%s</div>' % (CSS, PHONE_CSS, html.escape(D["topic"]), html.escape(D["group"]),
                                                  "".join(parts), html.escape(D["write"]), note))


def gif(frames, out):
    """[(html, seconds)] → an animated GIF: each frame drawn at phone size, then joined with one shared palette."""
    tmp = Path(tempfile.mkdtemp(prefix="demo-gif-"))
    lines = []
    for i, (page, secs) in enumerate(frames):
        src, png = tmp / ("f%02d.html" % i), tmp / ("f%02d.png" % i)
        src.write_text(page, encoding="utf-8")
        subprocess.run([sys.executable, str(REPO / "tools" / "shot.py"), src.as_uri(), str(png), "390", "1"], check=True,
                       env=dict(os.environ, SHOT_HEIGHT="700"), stdout=subprocess.DEVNULL)
        lines += ["file '%s'" % png, "duration %s" % secs]
    lines.append("file '%s'" % (tmp / ("f%02d.png" % (len(frames) - 1))))       # the concat demuxer drops the last duration
    (tmp / "list.txt").write_text("\n".join(lines) + "\n")
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "concat", "-safe", "0", "-i", str(tmp / "list.txt"),
                    "-vf", "scale=600:-1:flags=lanczos,split[a][b];[a]palettegen=max_colors=256:stats_mode=full[p];"
                           "[b][p]paletteuse=dither=none", "-fps_mode", "vfr", "-loop", "0", str(out)], check=True)


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

    st = state(fake)
    msgs = {m["mid"]: m for m in st}
    result = next(m["mid"] for m in st if m["text"].startswith("✅"))
    turn2 = next(m["mid"] for m in st if m["text"].startswith("⏳") and "💬" in m["text"])
    perm = next(m["mid"] for m in st if m["text"].startswith("✋"))
    t0 = time.time()
    hm = lambda ago: time.strftime("%H:%M", time.localtime(t0 - ago))
    if OUT.suffix == ".gif":
        await animate(p, fake, msgs, result, turn2, perm, hm)
        sock.close()
        return
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


async def animate(p, fake, msgs, result, turn2, perm, hm):
    """The README's opening animation, from the run above: the frames up to the permission request come from the
    messages as they stand, then Allow is pressed for real and the turn finishes."""
    me = lambda: bubble("me", html.escape(D["ask2"]), hm(6 * 60 + 20))
    ask = bubble("me", html.escape(D["ask"]), hm(26 * 60))           # the task this turn finished: fills the first frame
    bot = lambda m, ago, kb=None, tap=False: bubble("bot", m["text"], hm(ago), D["bot"], kb).replace(
        '<span class="btn">', '<span class="btn tap">', 1) if tap else bubble("bot", m["text"], hm(ago), D["bot"], kb)
    first = ask + bot(msgs[result], 14 * 60)
    working = bot(msgs[turn2], 6 * 60)
    asking = msgs[perm]
    push = (D["now_word"], html.escape(asking["text"].split("\n")[0].replace("<b>", "").replace("</b>", "")),
            html.escape(D["cmd_desc"]))
    frames = [
        (phone([first]), 1.6),
        (phone([first, me()]), 1.3),
        (phone([first, me(), working]), 2.0),
        (phone([first, me(), working, bot(asking, 20, asking["kb"])], push), 2.6),
        (phone([first, me(), working, bot(asking, 20, asking["kb"])]), 0.9),
        (phone([first, me(), working, bot(asking, 20, asking["kb"], tap=True)]), 0.7),
    ]
    rid = fake.buttons("p:")[0].split(":")[1]
    await p.on_callback({"id": "a", "from": {"id": T.OWNER}, "data": "p:%s:y" % rid,
                         "message": {"message_id": perm}})
    await T.run_hook(T.ev("PostToolUse", tool_name="Bash", tool_input={"command": D["cmd"], "description": D["cmd_desc"]}))
    await asyncio.sleep(0.4)
    now = {m["mid"]: m for m in state(fake)}
    frames.append((phone([first, me(), bot(now[turn2], 6 * 60), bot(now[perm], 20, now[perm]["kb"])]), 1.6))
    await T.run_hook(T.ev("Stop", last_assistant_message=D["done2"]))
    await T.until(lambda: sum(1 for m in state(fake) if m["text"].startswith("✅")) >= 2)
    await asyncio.sleep(0.3)
    end = state(fake)
    now = {m["mid"]: m for m in end}
    done = [m for m in end if m["text"].startswith("✅")][-1]
    last = [bot(now[turn2], 6 * 60)] if turn2 in now else []           # one message per turn: the result took its place
    frames.append((phone([first, me()] + last + [bot(now[perm], 20, now[perm]["kb"]), bot(done, 0)]), 3.4))
    gif(frames, OUT)
    print("animation", OUT, "%.0f KB" % (OUT.stat().st_size / 1024))


asyncio.run(main())
