"""The README's opening picture (stage D6): the computer with its Claude Code tab and the phone with the project's topic,
side by side. Claude asks for permission — the question is on both; a tap on Allow on the phone — the tab goes on; the
result comes to the topic; your next message from the phone lands in the tab as if typed there.

The phone's bubbles are Pult's own output: the daemon runs for real with a fake Telegram (the harness of
tests/test_pult.py), on the made-up project of tools/stand.py. The computer's window is a drawing of the tab — the
same lines, no real VS Code — so nothing of anyone's own projects can get in.

  STAND_LANG=ru ~/.local/share/pult/venv/bin/python tools/hero.py media/hero.ru.gif [dark]

The first frame is the moment of the question on both screens: GitHub shows only it when animations are paused.
Frames are drawn with tools/shot.py and joined with ffmpeg, like tools/chat_shot.py."""
import asyncio, html, os, subprocess, sys, tempfile, time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tests"))
import test_pult as T  # noqa: E402  (fake Telegram, the real hook, a temporary home)
pultd = T.pultd

LANG = os.environ.get("STAND_LANG", "en")
OUT = Path(sys.argv[1] if len(sys.argv) > 1 else "hero.%s.gif" % LANG).resolve()
DARK = len(sys.argv) > 2 and sys.argv[2] == "dark"
SHOP = "/Users/x/acme-shop"
W, H = 880, 520

D = {
    "en": dict(
        title="Checkout: clearer error messages", ask0="Make the checkout error messages clearer",
        summary="All **27 tests** pass: a declined card says why and what to do, a timeout offers to try again.",
        ask="Now deploy to staging", now="Deploying to staging and checking the checkout page there.",
        read="Read checkout/errors.py", cmd="make deploy-staging && git commit -qm 'Checkout: clearer errors'",
        cmd_desc="Deploy to staging and commit", ran="make deploy-staging · done",
        done="Deployed to staging: the checkout page shows the new messages for a declined card and a timeout. "
             "Committed as `Checkout: clearer errors`.",
        dlg="Run this command?", yes="Allow", no="Deny", win="acme-shop — Claude Code", me="You", bot="Pult",
        topic="acme-shop", group="Pult · topic", write="Message", now_word="now"),
    "ru": dict(
        title="Оформление заказа: понятные ошибки", ask0="Сделай сообщения об ошибках при оплате понятнее",
        summary="Все **27 тестов** зелёные: отказ по карте объясняет причину, при тайм-ауте — предложение повторить.",
        ask="Теперь выложи на стенд", now="Выкладываю на стенд и проверяю там страницу оплаты.",
        read="Read checkout/errors.py", cmd="make deploy-staging && git commit -qm 'Checkout: clearer errors'",
        cmd_desc="Выложить на стенд и закоммитить", ran="make deploy-staging · готово",
        done="Выложено на стенд: страница оплаты показывает новые сообщения об отказе карты и тайм-ауте. "
             "Коммит — `Checkout: clearer errors`.",
        dlg="Выполнить команду?", yes="Разрешить", no="Отклонить", win="acme-shop — Claude Code", me="Ты", bot="Пульт",
        topic="acme-shop", group="Пульт · тема", write="Сообщение", now_word="сейчас"),
}[LANG if LANG in ("en", "ru") else "en"]

THEME = (dict(bg="linear-gradient(135deg,#17233a,#221a12)", chat="#101820", bub="#1f2a36", me="#2b5278", ink="#e8edf3",
              mute="#8d9aab", name="#6ab2f2", btn="#26394d", btnink="#8fc6ff", bar="#17212b", line="#0b1218", code="#16202a")
         if DARK else
         dict(bg="linear-gradient(135deg,#e6eefb,#f7efe4)", chat="#e6ebf1", bub="#ffffff", me="#d9e8ff", ink="#1a1d22",
              mute="#8a93a0", name="#2f6fcf", btn="#eef2f7", btnink="#2f6fcf", bar="#ffffff", line="#dde3ea", code="#f0f2f5"))

CSS = """
* { box-sizing: border-box; }
html, body { margin: 0; background: transparent; }
body { font: 15px/1.4 -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; }
.stage { position: relative; width: %(W)dpx; height: %(H)dpx; border-radius: 22px; overflow: hidden; background: %(bg)s; }
/* the computer: a drawing of the Claude Code tab */
.win { position: absolute; left: 26px; top: 34px; width: 548px; height: 452px; border-radius: 12px; overflow: hidden;
  background: #1e1f24; box-shadow: 0 18px 44px rgba(0,0,0,.28); color: #d6d9e0; }
.tb { height: 32px; display: flex; align-items: center; gap: 7px; padding: 0 12px; background: #2a2c32; font-size: 12.5px; color: #a7acb7; }
.tb i { width: 11px; height: 11px; border-radius: 50%%; background: #ff5f57; } .tb i:nth-child(2) { background: #febc2e; } .tb i:nth-child(3) { background: #28c840; }
.tb span { margin-left: 10px; }
.pane { position: absolute; left: 0; right: 0; top: 32px; bottom: 0; padding: 16px 40px 16px 18px; display: flex; flex-direction: column; justify-content: flex-end; gap: 10px; }
.u { align-self: flex-end; max-width: 80%%; background: #2f3644; border-radius: 10px; padding: 7px 11px; color: #eef1f6; }
.c { color: #d6d9e0; }
.c b { color: #fff; }
.tool { font: 13px/1.4 ui-monospace, Menlo, monospace; color: #9aa3b2; }
.tool::before { content: "● "; color: #6fbf73; }
.tool.wait::before { color: #e8a33b; }
.dlg { border: 1px solid #4a4f5c; border-radius: 10px; padding: 10px 12px; background: #24262c; }
.dlg .h { font-weight: 600; color: #fff; margin-bottom: 6px; }
.dlg code { display: block; font: 12.5px/1.4 ui-monospace, Menlo, monospace; color: #cfd6e4; background: #191a1f; border-radius: 6px; padding: 6px 8px; }
.dlg .b { display: flex; gap: 8px; margin-top: 9px; }
.dlg .b span { padding: 5px 12px; border-radius: 7px; background: #3a3f4b; color: #e6e9ef; font-size: 13.5px; }
.dlg .b span:first-child { background: #3b6fd6; color: #fff; }
.caret { display: inline-block; width: 8px; height: 15px; background: #8fb4ff; vertical-align: -2px; margin-left: 2px; }
/* the phone: the project's topic */
.ph { position: absolute; right: 28px; top: 18px; width: 300px; height: 484px; border-radius: 36px; background: #121317;
  padding: 9px; box-shadow: 0 22px 48px rgba(0,0,0,.32); }
.scr { position: relative; width: 100%%; height: 100%%; border-radius: 28px; overflow: hidden; display: flex; flex-direction: column; background: %(chat)s; }
.bar { flex: none; display: flex; align-items: center; gap: 10px; padding: 12px 14px 9px; background: %(bar)s; border-bottom: 1px solid %(line)s; color: %(ink)s; }
.bar b { display: block; font-size: 14.5px; } .bar span { font-size: 11.5px; color: %(mute)s; }
.chat { flex: 1; display: flex; flex-direction: column; justify-content: flex-end; gap: 6px; padding: 0 8px 8px; overflow: hidden; }
.msg { flex: none; max-width: 92%%; padding: 6px 9px 5px; border-radius: 12px; background: %(bub)s; color: %(ink)s; font-size: 12.5px;
  line-height: 1.35; overflow-wrap: anywhere; border-bottom-left-radius: 4px; }
.msg.me { margin-left: auto; background: %(me)s; border-bottom-left-radius: 12px; border-bottom-right-radius: 4px; }
.msg .n { color: %(name)s; font-size: 11.5px; font-weight: 600; }
.msg pre { font: 11px/1.35 ui-monospace, Menlo, monospace; background: %(code)s; border-radius: 6px; padding: 4px 6px; margin: 4px 0 1px; white-space: pre-wrap; }
.msg code { font: 11.5px ui-monospace, Menlo, monospace; }
.msg blockquote { margin: 4px 0 0; padding: 1px 0 1px 7px; border-left: 2.5px solid %(name)s; max-height: 3.9em; overflow: hidden; }
.msg .t { text-align: right; color: %(mute)s; font-size: 10px; }
.kb { display: flex; flex-direction: column; gap: 3px; margin: 5px -4px -2px; }
.kb div { display: flex; gap: 3px; }
.kb span { flex: 1; text-align: center; background: %(btn)s; color: %(btnink)s; border-radius: 7px; padding: 5px 3px; font-size: 11.5px; font-weight: 600;
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis; position: relative; }
.kb span.tap::after { content: ""; position: absolute; left: 50%%; top: 50%%; width: 34px; height: 34px; margin: -17px 0 0 -17px; border-radius: 50%%;
  background: rgba(47,111,207,.28); box-shadow: 0 0 0 5px rgba(47,111,207,.14); }
.cmp { flex: none; margin: 0 8px 10px; background: %(bub)s; color: %(mute)s; border-radius: 16px; padding: 7px 12px; font-size: 13px; }
.push { position: absolute; top: 7px; left: 7px; right: 7px; background: %(bub)s; color: %(ink)s; border-radius: 14px; padding: 8px 10px;
  box-shadow: 0 6px 20px rgba(10,20,40,.28); font-size: 12px; line-height: 1.3; }
.push .a { color: %(mute)s; font-size: 10.5px; margin-bottom: 2px; }
.push b { display: block; }
""" % dict(THEME, W=W, H=H)


def msg(kind, body, when, kb=None, tap=False):
    rows = ""
    if kb:
        rows = '<div class="kb">%s</div>' % "".join(
            "<div>%s</div>" % "".join('<span%s>%s</span>' % (' class="tap"' if tap and i == 0 and j == 0 else "", html.escape(b["text"]))
                                      for j, b in enumerate(row)) for i, row in enumerate(kb))
    name = '<div class="n">%s</div>' % html.escape(D["bot"]) if kind == "bot" else ""
    return '<div class="msg %s">%s%s<div class="t">%s</div>%s</div>' % (kind, name, body.replace("\n", "<br>"), when, rows)


def frame(tab, chat, push=None):
    """One frame: the tab's lines on the left, the topic's bubbles on the right, a notification on top if any."""
    note = ('<div class="push"><div class="a">Telegram · %s</div><b>%s</b>%s</div>' % push) if push else ""
    return ('<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width"><style>%s</style>'
            '<div class="stage"><div class="win"><div class="tb"><i></i><i></i><i></i><span>%s</span></div><div class="pane">%s</div></div>'
            '<div class="ph"><div class="scr"><div class="bar"><div><b>%s</b><span>%s</span></div></div><div class="chat">%s</div>'
            '<div class="cmp">%s</div>%s</div></div></div>' % (CSS, html.escape(D["win"]), "".join(tab), html.escape(D["topic"]),
                                                                html.escape(D["group"]), "".join(chat), html.escape(D["write"]), note))


def gif(frames, out):
    tmp = Path(tempfile.mkdtemp(prefix="hero-"))
    lines = []
    for i, (page, secs) in enumerate(frames):
        src, png = tmp / ("f%02d.html" % i), tmp / ("f%02d.png" % i)
        src.write_text(page, encoding="utf-8")
        subprocess.run([sys.executable, str(REPO / "tools" / "shot.py"), src.as_uri(), str(png), str(W), "1"], check=True,
                       env=dict(os.environ, SHOT_HEIGHT=str(H), SHOT_CLEAR="1"), stdout=subprocess.DEVNULL)
        lines += ["file '%s'" % png, "duration %s" % secs]
        if i == 0:
            first = png
    lines.append("file '%s'" % (tmp / ("f%02d.png" % (len(frames) - 1))))
    (tmp / "list.txt").write_text("\n".join(lines) + "\n")
    # 2× drawn, shown at 880: sharp on a laptop's screen; one palette for the whole run keeps it small
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "concat", "-safe", "0", "-i", str(tmp / "list.txt"),
                    "-vf", "scale=%d:-1:flags=lanczos,split[a][b];[a]palettegen=max_colors=256:stats_mode=full:reserve_transparent=1[p];"
                           "[b][p]paletteuse=dither=none:alpha_threshold=128" % W, "-fps_mode", "vfr", "-loop", "0", str(out)], check=True)
    return first


async def run():
    """Pult's own messages for the story: the earlier result, the turn, the permission request, its decision, the result."""
    fake = T.FakeTg()
    tg = pultd.Tg("T", transport=T.httpx.MockTransport(fake.handler))
    store = pultd.Store(T.TMP / "hero.db")
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
    sent = lambda: [d.get("text", "") for d in fake.of("sendMessage")]
    await T.run_hook(T.ev("SessionStart", source="startup"))
    await T.run_hook(T.ev("UserPromptSubmit", prompt=D["ask0"]))
    await T.until(lambda: p.live[T.SID].turn and p.live[T.SID].turn.msg)
    p.live[T.SID].title, p.live[T.SID].named = D["title"], True
    p.live[T.SID].turn.started -= 12 * 60
    await T.run_hook(T.ev("Stop", last_assistant_message=D["summary"]))
    await T.until(lambda: any(t.startswith("✅") for t in sent()))
    # the next turn as if written from the phone: its result replies to that message, no "You: …" line in it
    await T.run_hook(T.ev("UserPromptSubmit", prompt=D["ask"]))
    await T.until(lambda: p.live[T.SID].turn and p.live[T.SID].turn.msg)
    turn = p.live[T.SID].turn
    turn.prompt, turn.reply_to, turn.started = None, 1, turn.started - 6 * 60
    await T.run_hook(T.ev("PermissionRequest", tool_name="Bash", tool_input={"command": D["cmd"], "description": D["cmd_desc"]},
                          permission_suggestions=[{"type": "addRules"}]), wait=False)
    await T.until(lambda: fake.buttons("p:"))
    perm = next(d for d in fake.of("sendMessage") if d["text"].startswith("✋"))
    asking = (perm["text"], T.json.loads(perm["reply_markup"])["inline_keyboard"])
    rid = fake.buttons("p:")[0].split(":")[1]
    await p.on_callback({"id": "a", "from": {"id": T.OWNER}, "data": "p:%s:y" % rid})
    await T.until(lambda: any(d.get("text", "").startswith("✋") for d in fake.of("editMessageText")))
    decided = [d["text"] for d in fake.of("editMessageText") if d.get("text", "").startswith("✋")][-1]
    await T.run_hook(T.ev("PostToolUse", tool_name="Bash", tool_input={"command": D["cmd"], "description": D["cmd_desc"]}))
    await T.run_hook(T.ev("Stop", last_assistant_message=D["done"]))
    await T.until(lambda: sum(1 for t in sent() if t.startswith("✅")) >= 2)
    first, result = [t for t in sent() if t.startswith("✅")][:2]
    sock.close()
    return first, asking, decided, result


def main():
    first, (ask_text, kb), decided, result = asyncio.run(run())
    t0 = time.time()
    hm = lambda ago: time.strftime("%H:%M", time.localtime(t0 - ago))
    md = lambda s: pultd.R.md_to_html(s)
    me = msg("me", html.escape(D["ask"]), hm(6 * 60 + 20))
    earlier = msg("bot", first, hm(14 * 60))
    tab_head = ['<div class="u">%s</div>' % html.escape(D["ask"]), '<div class="c">%s</div>' % html.escape(D["now"]),
                '<div class="tool">%s</div>' % html.escape(D["read"])]
    dialog = ('<div class="dlg"><div class="h">%s</div><code>%s</code><div class="b"><span>%s</span><span>%s</span></div></div>'
              % (html.escape(D["dlg"]), html.escape(D["cmd"]), html.escape(D["yes"]), html.escape(D["no"])))
    ran = '<div class="tool">Bash · %s</div>' % html.escape(D["ran"])
    push = (D["now_word"], html.escape(ask_text.split("\n")[0].replace("<b>", "").replace("</b>", "")), html.escape(D["cmd_desc"]))
    frames = [
        # the question, on both screens at once — the first frame, what GitHub shows when animations are paused
        (frame(tab_head + [dialog], [earlier, me, msg("bot", ask_text, hm(20), kb)], push), 2.6),
        (frame(tab_head + [dialog], [earlier, me, msg("bot", ask_text, hm(20), kb)]), 0.9),
        (frame(tab_head + [dialog], [earlier, me, msg("bot", ask_text, hm(20), kb, tap=True)]), 0.7),
        # allowed from the phone: the tab goes on by itself
        (frame(tab_head + [ran, '<div class="c">%s<span class="caret"></span></div>' % html.escape(D["now"])],
               [earlier, me, msg("bot", decided, hm(20))]), 1.6),
        (frame(tab_head + [ran, '<div class="c">%s</div>' % md(D["done"])], [earlier, me, msg("bot", decided, hm(20)), msg("bot", result, hm(0))]), 3.4),
        # the next message from the phone: it lands in the tab as if typed there
        (frame(['<div class="c">%s</div>' % md(D["done"]), '<div class="u">%s<span class="caret"></span></div>' % html.escape(D["ask"])],
               [msg("bot", decided, hm(20)), msg("bot", result, hm(1)), msg("me", html.escape(D["ask"]), hm(0))]), 1.8),
    ]
    still = gif(frames, OUT)
    png = OUT.with_suffix(".png")
    subprocess.run(["sips", "-Z", str(W), str(still), "--out", str(png)], check=True, stdout=subprocess.DEVNULL)
    print("hero", OUT, "%.0f KB" % (OUT.stat().st_size / 1024), "· first frame", png.name)


if __name__ == "__main__":
    main()
