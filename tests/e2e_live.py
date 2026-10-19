"""Live Pult test: a real Claude (haiku) via the SDK, a fake Telegram.

Run (uses a little of the subscription, ~40 s):
  ~/.local/share/pult/venv/bin/python tests/e2e_live.py


A new session from "Telegram" → permission via a button → question via buttons → result;
continuing the same session; a fork of a session "open on the Mac";
a background command — "in the background" in the result, the load view finds its process, a turn when it ends,
the next prompt with its own result.
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
    server = await asyncio.start_unix_server(p.handle_conn, path=os.environ["PULT_SOCK"])
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
    mark2 = len(calls)
    await p.continue_session(sid4, "Reply with one word: PONG", None, None)
    await until(lambda: done(mark2), what="итог следующего запроса")
    await until(lambda: not p.driven[sid4].busy, what="сессия свободна")
    log("следующий запрос:", done(mark2)[0].replace("\n", " | "), "· bg процесса:", p.driven[sid4].bg)
    assert "PONG" in done(mark2)[0].upper(), "the result of another turn"
    log("тем создано:", len([1 for m, _ in calls if m == "createForumTopic"]), "· вызовов Telegram:", len(calls))
    for d in list(p.driven.values()):
        d.task.cancel()
    await asyncio.sleep(1)
    server.close()


asyncio.run(main())
shutil.rmtree(TMP, ignore_errors=True)
