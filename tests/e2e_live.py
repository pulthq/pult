"""Live Pult test: a real Claude (haiku) via the SDK, a fake Telegram.

Run (uses a little of the subscription, ~70 s):
  ~/.local/share/pult/venv/bin/python tests/e2e_live.py


A new session from "Telegram" → permission via a button → question via buttons → result;
continuing the same session; a fork of a session "open on the Mac";
a background command — "in the background" in the result, the load view finds its process, a turn when it ends,
the next prompt with its own result; that result is the owner's move on Home until the session is opened.
With Telegram as a pager: a task from the app makes no turn or result message; its question is paged once.
A message from the app mid-turn reaches Claude in that turn, and the app shows it as written mid-turn.
"""
import asyncio, json, os, shutil, sys, tempfile, time, urllib.parse
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent / "src"
TMP = Path(tempfile.mkdtemp(prefix="pult-e2e-"))   # outside the repo: transcripts won't land in its project
os.environ.update(PULT_HOME=str(TMP / "home"), PULT_SOCK="/tmp/pult-e2e-%d.sock" % os.getpid(), PULT_ENV=str(TMP / "env"))
(TMP / "home").mkdir()
shutil.copy(SRC / "pult_hook.py", TMP / "home" / "pult_hook.py")
sys.path.insert(0, str(SRC))
import httpx
import pultd

PROJ = TMP / "proj"
PROJ.mkdir()
pultd.SKIP_PREFIXES = ()
pultd.PERMISSION_MODE = "default"
pultd.EDIT_EVERY = 0.5
CHAT, OWNER = -100500, 42

calls = []
nid = [2000]


def handler(req):
    m = req.url.path.rsplit("/", 1)[-1]
    ct = req.headers.get("content-type", "")
    d = {k: v[0] for k, v in urllib.parse.parse_qs(req.content.decode()).items()} if ct.startswith("application/x-www") else {}
    calls.append((m, d))
    nid[0] += 1
    res = {"message_thread_id": 9} if m == "createForumTopic" else {"message_id": nid[0]} if m.startswith("send") else True
    return httpx.Response(200, json={"ok": True, "result": res})


def buttons(prefix, after=0):
    out = []
    for m, d in calls[after:]:
        if "reply_markup" in d:
            for row in json.loads(d["reply_markup"]).get("inline_keyboard", []):
                out += [b["callback_data"] for b in row if b["callback_data"].startswith(prefix)]
    return out


def texts(after=0, method="sendMessage"):
    return [d.get("text", "") for m, d in calls[after:] if m == method]


async def until(cond, timeout=180, what=""):
    t = time.monotonic()
    while not cond():
        if time.monotonic() - t > timeout:
            raise AssertionError("не дождался: " + what)
        await asyncio.sleep(0.2)


orig_options = pultd.Driven.options


def options(self):
    o = orig_options(self)
    o.model = "claude-haiku-5-5"
    return o


pultd.Driven.options = options


async def main():
    tg = pultd.Tg("T", transport=httpx.MockTransport(handler))
    store = pultd.Store(TMP / "home" / "state.db")
    store.put("chat", CHAT)
    p = pultd.Pult({"PULT_ALLOWED_USER_IDS": str(OWNER), "PULT_FORCE_AWAY": "1"}, tg, store)
    p.out = pultd.Outbox(rate=6000, burst=100)
    p._agents = (time.monotonic() + 1e6, [])
    server = await pultd.start_link(p.handle_conn, os.environ["PULT_SOCK"])
    asyncio.create_task(p.out.run())
    t0 = time.monotonic()
    log = lambda *a: print("%6.1f" % (time.monotonic() - t0), *a, flush=True)

    # 1. a new session
    sid = "aaaaaaaa-0000-4000-8000-000000000001"
    await p.drive(sid, str(PROJ), "Step 1: run `echo hi > x.txt` with the Bash tool. Step 2: use AskUserQuestion to ask "
                  "my favorite color, options Red and Blue (in that order). Step 3: reply with one short line: did the "
                  "command run, and which color I picked.", origin=1)
    await until(lambda: buttons("p:"), what="кнопка разрешения")
    log("разрешение:", texts()[-1].split("\n")[1:3])
    rid = buttons("p:")[0].split(":")[1]
    await p.on_callback({"id": "c1", "from": {"id": OWNER}, "data": "p:%s:y" % rid})
    await until(lambda: buttons("q:"), what="кнопки вопроса")
    rid = buttons("q:")[0].split(":")[1]
    log("вопрос:", texts()[-1].split("\n")[1])
    await p.on_callback({"id": "c2", "from": {"id": OWNER}, "data": "q:%s:0:1" % rid})
    await until(lambda: any(t.startswith("✅") for t in texts()), what="итог")
    log("итог:", [t for t in texts() if t.startswith("✅")][-1])
    log("x.txt:", (PROJ / "x.txt").exists())
    turn = texts()[0]
    log("ход:", turn.replace("\n", " | "))
    edits = texts(method="editMessageText")
    log("последняя правка хода:", [e for e in edits if "✔️" in e][-1:])

    # 2. continue the same session by replying to the result
    mark = len(calls)
    row = store.db.execute("SELECT msg FROM msgs WHERE sid=? AND kind='result' ORDER BY ts DESC", (sid,)).fetchone()
    await p.on_message({"message_id": 30, "from": {"id": OWNER}, "chat": {"id": CHAT}, "message_thread_id": 9,
                        "is_topic_message": True, "text": "Which color did I pick? Answer with one word.",
                        "reply_to_message": {"message_id": row["msg"]}})
    await until(lambda: any(t.startswith("✅") for t in texts(mark)), what="итог продолжения")
    log("продолжение:", [t for t in texts(mark) if t.startswith("✅")][-1])

    # 3. a session "open on the Mac" → fork
    while sid in p.driven:                       # close the process as if the session moved to VS Code
        p.driven[sid].task.cancel()
        await asyncio.sleep(0.5)
    p._agents = (time.monotonic() + 1e6, [{"sessionId": sid, "cwd": str(PROJ)}])
    mark = len(calls)
    await p.on_message({"message_id": 31, "from": {"id": OWNER}, "chat": {"id": CHAT}, "message_thread_id": 9,
                        "is_topic_message": True, "text": "Repeat the color once more, one word.",
                        "reply_to_message": {"message_id": row["msg"]}})
    await until(lambda: buttons("f:", mark), what="предложение копии")
    await p.on_callback({"id": "c3", "from": {"id": OWNER}, "data": buttons("f:", mark)[0]})
    await until(lambda: any(t.startswith("✅") for t in texts(mark)), what="итог копии")
    fork_sids = [s for s in p.live if s != sid]
    log("копия:", [t for t in texts(mark) if t.startswith("✅")][-1], "· новая сессия:", fork_sids)

    # 4. background command: "in the background" in the result → Claude starts a turn itself when it ends → the next
    #    prompt gets its own result, not that turn's
    sid4 = "aaaaaaaa-0000-4000-8000-000000000004"
    mark = len(calls)
    done = lambda after: [t for t in texts(after) if t.startswith("✅")]
    await p.drive(sid4, str(PROJ), "This is a test of background commands. Your first action must be a call to the Bash "
                  "tool with command `sleep 8; echo bg-done` and the parameter run_in_background: true. After the tool "
                  "call returns, do not wait or check on it: reply with one word, STARTED. Later, when you are notified "
                  "that the background command finished, reply with one word: FINISHED.", origin=40)
    await until(lambda: buttons("p:", mark) or done(mark), what="разрешение или итог")
    if buttons("p:", mark):                     # sleep may be allowed in the owner's settings — then there is no button
        await p.on_callback({"id": "c4", "from": {"id": OWNER}, "data": "p:%s:y" % buttons("p:", mark)[0].split(":")[1]})
    await until(lambda: done(mark), what="итог с фоном")
    run = p.live[sid4].run                       # the owner's prompt set the work going: "working N" counts from it
    log("итог с фоном:", done(mark)[0].replace("\n", " | "))
    assert "⚙️ Still running in the background" in done(mark)[0], "no “in the background” line"
    # the load view finds that command among the computer's processes, under this session's claude (0.9.16)
    ld = await p.api_load(sid=sid4)
    log("нагрузка:", ld.get("session") and {k: ld["session"][k] for k in ("pid", "cpu", "mem", "n")},
        [(x["type"], x.get("found"), x.get("cmd") or x.get("what")) for x in ld.get("tasks", [])],
        "· pid из хука:", p.live[sid4].pid)
    assert ld["ok"] and ld["session"] and ld["tasks"] and ld["tasks"][0].get("found"), "background command not found"
    await until(lambda: len(done(mark)) >= 2, what="итог хода по концу фоновой задачи")
    note = [t for t in texts(mark) if "Background task" in t and not t.startswith("✅")]
    log("ход по фону:", note[-1].replace("\n", " | ") if note else "НЕТ", "· итог:", done(mark)[1].replace("\n", " | "))
    assert note and "task-notification" not in "".join(texts(mark)), "the background-task turn is shown wrong"
    log("начало захода:", run, "· после хода по фону:", p.live[sid4].run)
    assert run and p.live[sid4].run == run, "Claude's own turn restarted the owner's run"
    mark2 = len(calls)
    await p.continue_session(sid4, "Reply with one word: PONG", None, None)
    await until(lambda: done(mark2), what="итог следующего запроса")
    await until(lambda: not p.driven[sid4].busy, what="сессия свободна")
    log("следующий запрос:", done(mark2)[0].replace("\n", " | "), "· bg процесса:", p.driven[sid4].bg)
    assert "PONG" in done(mark2)[0].upper(), "the result of another turn"
    assert p.live[sid4].run > run, "the owner's next prompt didn't start a new run"
    # whose move (stage V): a real Stop leaves an outcome; nothing runs after PONG and nobody opened it — the owner's
    # move, with the result's first sentence as its line; opening the session puts it to rest
    ov = await p.api_overview()
    mine = {r["sid"]: (r["state"], r["line"]) for r in ov["mine"]}
    log("твой ход:", mine.get(sid4), "· проектов на доске:", len(ov["board"]))
    assert mine.get(sid4) and mine[sid4][0] == "you" and "PONG" in mine[sid4][1].upper(), "no outcome for a real turn"
    await p.api_session(sid4)
    assert sid4 not in {r["sid"] for r in (await p.api_overview())["mine"]}, "opening the session didn't put it to rest"
    # Telegram as a pager (stage V): a task from the app gets no turn or result message; Claude's question to the
    # owner, who is away, comes once — the session's title, the line, the way into the app
    p.env.update(PULT_APP_LINK="https://t.me/b/pult", PULT_RELAY_URL="wss://h.example/pult/agent")
    pkey5 = pultd.sanitize(str(PROJ))
    store.set_topic(pkey5, str(PROJ), "proj", 9)
    mark3 = len(calls)
    sid5 = (await p.api_new(pkey5, "Reply with exactly one line: a yes/no question asking me whether to continue."))["sid"]
    await until(lambda: (p.attn.rec.get(sid5) or {}).get("ts"), what="итог задачи из приложения")
    quiet = [t for t in texts(mark3) if t.startswith(("⏳", "✅"))]
    await p.page_due()
    mine5 = lambda: [t for t in texts(mark3) if t.startswith("🔴 <b>Reply with exactly")]   # earlier sessions wait too
    page = mine5()
    log("пейджер: ход и итог в Telegram —", len(quiet), "· вызов:", page[-1].replace("\n", " | ") if page else "НЕТ")
    assert not quiet and len(page) == 1, "the pager posted the wrong things"
    await p.page_due()
    assert len(mine5()) == 1, "paged twice"
    # a message from the app while Pult's own session works reaches Claude in the same turn, at its next step — not
    # after the result (2026-10-21: "stop, wrong project" waited out a 10-minute turn); the app shows it mid-turn
    sid6 = (await p.api_new(pkey5, "This is a test of a long turn. Call the Bash tool with command `sleep 4; echo step N` "
                            "for N = 1, 2, 3, 4, 5 - one call at a time, waiting for each to finish. Then reply with one "
                            "word: DONE. If a new message from the user comes in meanwhile, follow it instead."))["sid"]
    await until(lambda: p.driven.get(sid6) and p.driven[sid6].asking, what="долгий ход")
    await asyncio.sleep(8)
    r = await p.api_send(sid6, "Stop the test now: make no more tool calls and reply with one word: HALTED.")
    await until(lambda: (p.attn.rec.get(sid6) or {}).get("ts"), what="итог долгого хода")
    path6 = p.transcript_of(sid6)[0]
    rows = [json.loads(x) for x in Path(path6).read_text().splitlines() if x.strip()]
    bash = [b for e in rows if e.get("type") == "assistant" for b in (e.get("message") or {}).get("content") or []
            if isinstance(b, dict) and b.get("type") == "tool_use"]
    mid = [i for i in pultd.PW.transcript_page(path6)["items"] if i.get("mid")]
    log("посреди хода:", r.get("how"), "· шагов:", len(bash), "· в приложении:", [i["text"][:30] for i in mid])
    assert r.get("how") == "session" and 0 < len(bash) < 5, "the message waited for the turn's end"
    assert len(mid) == 1 and "HALTED" in mid[0]["text"], "the app doesn't show the message written mid-turn"
    log("тем создано:", len([1 for m, _ in calls if m == "createForumTopic"]), "· вызовов Telegram:", len(calls))
    for d in list(p.driven.values()):
        d.task.cancel()
    await asyncio.sleep(1)
    server.close()


asyncio.run(main())
shutil.rmtree(TMP, ignore_errors=True)
