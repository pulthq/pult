"""Live Pult test: a real Claude (haiku) via the SDK, a fake Telegram.

Run (uses a little of the subscription, ~90 s):
  ~/.local/share/pult/venv/bin/python tests/e2e_live.py


A new session from "Telegram" → permission via a button → question via buttons → result;
continuing the same session; a fork of a session "open on the Mac";
a background command — "in the background" in the result, the load view finds its process, a turn when it ends,
the next prompt with its own result; that result is the owner's move on Home — opened, too — until "Got it".
With Telegram as a pager: a task from the app makes no turn or result message; its question is paged once.
A message from the app mid-turn reaches Claude in that turn, the app shows it as written mid-turn, its ticks say read.
Stop from the app closes the interrupted turn, though Claude Code sends no Stop hook for it.
A new project "with a description" (stage S): git, its topic by the title, a first turn that writes CLAUDE.md.
A file made in a session goes to the project's topic with `pult send`, and the turn's outcome lists it (stage F).
With the model on, a new task gets its section and topic as soon as its request is in, and again with the result (stage T);
the first open of the project sorts its earlier tasks without tags, in a batch (T2).
A task on another vendor's model (stage M, step 2): a stand-in for DeepSeek on this computer gets the session's requests with
Pult's key and never the subscription's token; the outcome comes; the transcript names the vendor's model, and so does its
row — Claude's session's row its real model, and so does the owner's move on Home.
"""
import asyncio, json, os, shutil, sys, tempfile, time, urllib.parse
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent / "src"
TMP = Path(tempfile.mkdtemp(prefix="pult-e2e-"))   # outside the repo: transcripts won't land in its project
os.environ.update(PULT_HOME=str(TMP / "home"), PULT_SOCK=str(TMP / "pult.sock") if os.name == "nt" else "/tmp/pult-e2e-%d.sock" % os.getpid(), PULT_ENV=str(TMP / "env"))
(TMP / "home").mkdir()
shutil.copy(SRC / "pult_hook.py", TMP / "home" / "pult_hook.py")
sys.path.insert(0, str(SRC))
import httpx
import pult_api
import pult_driven
import pultd

PROJ = TMP / "proj"
PROJ.mkdir()
pultd.SKIP_PREFIXES = ()
pult_driven.PERMISSION_MODE = "default"
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
                out += [b["callback_data"] for b in row if b.get("callback_data", "").startswith(prefix)]
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
    if "ANTHROPIC_BASE_URL" not in (o.env or {}):      # another vendor's session keeps its own model (stage M, step 2)
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
    begin = time.time()
    await p.drive(sid4, str(PROJ), "This is a test of background commands. Your first action must be a call to the Bash "
                  "tool with command `sleep 8; echo bg-done` and the parameter run_in_background: true. After the tool "
                  "call returns, do not wait or check on it: reply with one word, STARTED. Later, when you are notified "
                  "that the background command finished, reply with one word: FINISHED.", origin=40)
    await until(lambda: buttons("p:", mark) or done(mark), what="разрешение или итог")
    if buttons("p:", mark):                     # sleep may be allowed in the owner's settings — then there is no button
        await p.on_callback({"id": "c4", "from": {"id": OWNER}, "data": "p:%s:y" % buttons("p:", mark)[0].split(":")[1]})
    await until(lambda: done(mark), what="итог с фоном")
    work1 = p.work_total(sid4)                   # the task's clock after its first turn (2026-10-30)
    log("итог с фоном:", done(mark)[0].replace("\n", " | "))
    assert "⚙️ Still running in the background" in done(mark)[0], "no “in the background” line"
    # the load view finds that command among the computer's processes, under this session's claude (0.9.16)
    ld = await p.api_load(sid=sid4)
    log("нагрузка:", ld.get("session") and {k: ld["session"][k] for k in ("pid", "cpu", "mem", "n")},
        [(x["type"], x.get("found"), x.get("cmd") or x.get("what")) for x in ld.get("tasks", [])],
        "· pid из хука:", p.live[sid4].pid)
    if os.name == "nt":                         # the load view is empty on Windows so far (project doc, K2)
        assert not ld["ok"], "Windows has a load view now: check this step there"
    else:
        assert ld["ok"] and ld["session"] and ld["tasks"] and ld["tasks"][0].get("found"), "background command not found"
    await until(lambda: len(done(mark)) >= 2, what="итог хода по концу фоновой задачи")
    note = [t for t in texts(mark) if "Background task" in t and not t.startswith("✅")]
    log("ход по фону:", note[-1].replace("\n", " | ") if note else "НЕТ", "· итог:", done(mark)[1].replace("\n", " | "))
    assert note and "task-notification" not in "".join(texts(mark)), "the background-task turn is shown wrong"
    # one clock for the task: Claude's own turn goes on from the first one's work, without the background sleep between
    await until(lambda: p.live[sid4].turn is None, what="ход по фону закрыт")
    work2, wall = p.work_total(sid4), time.time() - begin
    log("часы задачи: после первого хода %.1f с · после хода по фону %.1f с · с запроса прошло %.1f с" % (work1, work2, wall))
    assert work1 < work2 < wall - 5, "the task's clock: Claude's own turn restarted it, or the background sleep is in it"
    mark2 = len(calls)
    await p.continue_session(sid4, "Reply with one word: PONG", None, None)
    await until(lambda: done(mark2), what="итог следующего запроса")
    await until(lambda: not p.driven[sid4].busy, what="сессия свободна")
    log("следующий запрос:", done(mark2)[0].replace("\n", " | "), "· bg процесса:", p.driven[sid4].bg)
    assert "PONG" in done(mark2)[0].upper(), "the result of another turn"
    log("часы задачи после следующего запроса: %.1f с" % p.work_total(sid4))
    assert p.work_total(sid4) > work2, "the owner's next prompt started the task's clock from zero"
    # whose move (stage V): a real Stop leaves an outcome; nothing runs after PONG — the owner's move, with the
    # result's first sentence as its line; opening the session doesn't put it away, "Got it" does (2026-10-30)
    ov = await p.api_overview()
    mine = {r["sid"]: (r["state"], r["line"], r.get("llm")) for r in ov["mine"]}
    log("твой ход:", mine.get(sid4), "· проектов на доске:", len(ov["board"]))
    assert mine.get(sid4) and mine[sid4][0] == "you" and "PONG" in mine[sid4][1].upper(), "no outcome for a real turn"
    # its card names the model that did it (Q108): the real transcript's own
    assert mine[sid4][2] and str(mine[sid4][2].get("model")).startswith("claude-") and "vendor" not in mine[sid4][2], "the owner's move doesn't say the model"
    await p.api_session(sid4)
    assert sid4 in {r["sid"] for r in (await p.api_overview())["mine"]}, "opening the session put it away"
    await p.api_seen(sid4)
    assert sid4 not in {r["sid"] for r in (await p.api_overview())["mine"]}, "Got it didn't put it away"
    # which model does it, for its row on Home (2026-10-30): the real transcript's own
    llm4 = (await p.row_stats(sid4))[1]
    log("модель в строке:", llm4)
    assert llm4 and str(llm4.get("model")).startswith("claude-") and "vendor" not in llm4, "the row doesn't say Claude's model"
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
    mine5 = lambda: [t for t in texts(mark3) if t.startswith("🟠 <b>Reply with exactly")]   # earlier sessions wait too
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
    await until(lambda: p.driven.get(sid6) and p.driven[sid6].asking and p.live.get(sid6) and p.live[sid6].turn,
                what="долгий ход")
    turn6 = p.live[sid6].turn
    await asyncio.sleep(8)
    r = await p.api_send(sid6, "Stop the test now: make no more tool calls and reply with one word: HALTED.")
    await until(lambda: (p.attn.rec.get(sid6) or {}).get("ts"), what="итог долгого хода")
    path6 = p.transcript_of(sid6)[0]
    rows = [json.loads(x) for x in Path(path6).read_text(encoding="utf-8").splitlines() if x.strip()]
    bash = [b for e in rows if e.get("type") == "assistant" for b in (e.get("message") or {}).get("content") or []
            if isinstance(b, dict) and b.get("type") == "tool_use"]
    mid = [i for i in pultd.PW.transcript_page(path6)["items"] if i.get("mid")]
    log("посреди хода:", r.get("how"), "· шагов:", len(bash), "· в приложении:", [i["text"][:30] for i in mid])
    assert r.get("how") == "session" and 0 < len(bash) < 5, "the message waited for the turn's end"
    assert len(mid) == 1 and "HALTED" in mid[0]["text"], "the app doesn't show the message written mid-turn"
    # the absorbed message has a UserPromptSubmit of its own, with the turn's prompt_id: the turn goes on, and "working
    # N" counts from the first prompt (2026-10-24: "working 28 s" 19 min into a turn) — the task's clock is that turn
    log("посреди хода: тот же ход —", p.live[sid6].turn in (None, turn6), "· закрыт:", turn6.done and turn6.done[0],
        "· часы задачи %.1f с, ход %.1f с" % (p.work_total(sid6), turn6.work()))
    assert turn6.done and turn6.done[0] == "✔️" and abs(p.work_total(sid6) - turn6.work()) < 2, "the mid-turn message started a turn"
    # its ticks (Q56): sent → read by its own UserPromptSubmit, at the step Claude read it
    out6 = [o for o in p.outbox.get(sid6) or [] if o["id"] == r.get("out")]
    log("галочки:", out6 and out6[0]["st"], "· прочитано через %.1f с" % (out6[0]["at"] - out6[0]["ts"]) if out6 else "")
    assert out6 and out6[0]["st"] == "read", "the mid-turn message wasn't marked read"
    # Stop from the app: an interrupted turn gets no Stop hook, only its result — Pult closes the turn itself, so the
    # session doesn't stay "working" and its process can go idle (2026-10-21, a session after Stop)
    sid7 = (await p.api_new(pkey5, "This is a test of a long turn. Call the Bash tool with command `sleep 4; echo step N` "
                            "for N = 1, 2, 3, 4, 5 - one call at a time. Then reply with one word: DONE."))["sid"]
    await until(lambda: p.driven.get(sid7) and p.driven[sid7].asking and p.live.get(sid7) and p.live[sid7].turn,
                what="долгий ход для «Стопа»")
    await asyncio.sleep(6)
    turn7 = p.live[sid7].turn
    assert (await p.api_stop(sid7))["ok"]
    await until(lambda: not p.driven[sid7].busy, timeout=20, what="ход закрыт после «Стопа»")
    log("стоп:", turn7.done and turn7.done[0], "· сессия занята:", p.driven[sid7].busy)
    assert turn7.done and turn7.done[0] == "⏹", "the interrupted turn wasn't closed"
    # files (stage F): a session of Pult's makes a file and sends it with `pult send` — the command finds its session by
    # Claude Code's environment and the file lands in the project's topic; the turn's outcome lists the file
    docs = len([1 for m, _ in calls if m == "sendDocument"])
    send = "PULT_SOCK=%s %s %s send report.md -m 'From the test'" % (os.environ["PULT_SOCK"], sys.executable, SRC / "pultctl.py")
    sid9 = (await p.api_new(pkey5, "Write the file report.md in the current folder with one line: Hello from the test. "
                            "Then run exactly this with the Bash tool: " + send + " — and reply with one word: SENT."))["sid"]
    mark9, t9 = len(calls), time.monotonic()
    while not (p.attn.rec.get(sid9) or {}).get("ts"):
        for b in buttons("p:", mark9):
            mark9 = len(calls)
            await p.on_callback({"id": "c9", "from": {"id": OWNER}, "data": "p:%s:y" % b.split(":")[1]})
        assert time.monotonic() - t9 < 180, "не дождался: итог хода с файлом"
        await asyncio.sleep(0.3)
    sent9 = [d for m, d in calls if m == "sendDocument"][docs:]
    kept9 = [f["p"] for f in (p.store.turn(sid9) or {}).get("files") or []]
    log("файл в теме:", len(sent9), "· файлы хода:", kept9, p.attn.rec[sid9].get("turn_files"))
    assert sent9 and (PROJ / "report.md").exists(), "pult send didn't deliver the file"
    assert "report.md" in kept9, "the turn's files miss report.md"
    # a new project from the phone (stage S): a folder made a moment ago gets git, a topic named by its title and a
    # first turn that writes CLAUDE.md from the description (permission mode here is "default": Write asks)
    pult_api.NEW_ROOT = TMP
    mark, t8 = len(calls), time.monotonic()
    r8 = await p.api_create("Дача у моря", how="describe", about="Учёт дел по даче: посадки и полив. Пока только записи.",
                            parent=str(TMP))
    while not (p.attn.rec.get(r8["sid"]) or {}).get("ts"):
        for b in buttons("p:", mark):
            mark = len(calls)
            await p.on_callback({"id": "c8", "from": {"id": OWNER}, "data": "p:%s:y" % b.split(":")[1]})
        assert time.monotonic() - t8 < 180, "не дождался: итог нового проекта"
        await asyncio.sleep(0.3)
    md = Path(os.path.realpath(TMP), "dacha_u_morya", "CLAUDE.md")
    topic8 = [d.get("name") for m, d in calls if m == "createForumTopic"][-1]
    log("новый проект: git", r8["git"], "· CLAUDE.md", md.exists() and md.stat().st_size, "· тема", topic8,
        "· сессия", p.live[r8["sid"]].title)
    assert md.exists() and (md.parent / ".git").is_dir() and topic8 == "Дача у моря", "the new project isn't complete"
    # task tags (stage T): with the model on, a new task gets its section and topic from the model as soon as its
    # request is in, and the result line's call brings them again when its turn ends
    await p.api_prefs(brief=True)
    sid10 = "aaaaaaaa-0000-4000-8000-000000000010"
    await p.drive(sid10, str(PROJ), "Reply with one short line, no tools: which is warmer for a beach holiday, "
                  "Sochi or Murmansk?", origin=1)
    await until(lambda: p.store.session_tag(sid10) is not None, what="теги задачи на старте")
    r10 = p.store.session_tag(sid10)
    log("теги на старте:", r10["sec"], "/", r10["topic"], "· свой:", r10["own"])
    await until(lambda: (p.attn.rec.get(sid10) or {}).get("model"), what="строка итога с тегами")
    r10 = p.store.session_tag(sid10)
    log("теги после хода:", r10["sec"], "/", r10["topic"], "· строка:", p.attn.rec[sid10]["line"],
        "· раздел в списке:", [s["n"] for s in p.store.tag_vocab(r10["pkey"])])
    assert r10["sec"] and not r10["own"] and not any(c in r10["sec"] for c in "/\\"), "no tags from the model"
    # the project's earlier tasks (stage T, T2; Q93): the ones from before the model was on have no tags — the first
    # open of the project sorts them by itself, the real model in a batch, from the SDK's list of the folder's sessions
    from claude_agent_sdk import list_sessions
    pk10 = r10["pkey"]
    bare = [s.session_id for s in list_sessions(str(PROJ), 200) if not (p.store.session_tag(s.session_id) or {"sec": None})["sec"]]
    await p.api_project(pk10)
    await until(lambda: pk10 not in p.tag_jobs, what="прежние задачи с тегами")
    got = [(p.store.session_tag(s) or {"sec": None})["sec"] for s in bare]
    log("прежние задачи:", len(bare), "без тегов → с тегами", sum(1 for g in got if g), "·",
        [(p.store.session_tag(s)["sec"], p.store.session_tag(s)["topic"]) for s in bare if p.store.session_tag(s)][:4])
    assert bare and all(got) and p.store.get("tags.old." + pk10), "the earlier tasks weren't sorted"
    # another vendor's model inside Claude Code (stage M, step 2): a stand-in for DeepSeek on this computer — the
    # session's real Claude Code asks it with the key Pult gave it, never the subscription's token; the outcome comes
    # like Claude's, and the transcript names the vendor's model
    import pult_vendors as V
    from aiohttp import web
    asked = []

    async def stand_in(req):
        body = await req.json() if req.method == "POST" else {}
        sysp = body.get("system")
        sysp = sysp if isinstance(sysp, str) else " ".join(b.get("text", "") for b in sysp or [] if isinstance(b, dict))
        asked.append({"path": req.path, "x": req.headers.get("x-api-key"), "auth": req.headers.get("authorization") or "",
                      "model": body.get("model"), "sys": sysp[:160], "max": body.get("max_tokens"),
                      "tools": len(body.get("tools") or [])})
        if not req.path.endswith("/messages"):
            return web.json_response({"input_tokens": 9} if req.path.endswith("count_tokens") else {}, status=200)
        resp = web.StreamResponse(headers={"Content-Type": "text/event-stream"})
        await resp.prepare(req)
        model = body.get("model") or "?"
        for ev, data in (("message_start", {"type": "message_start", "message": {"id": "msg_x", "type": "message", "role": "assistant",
                                            "model": model, "content": [], "stop_reason": None, "stop_sequence": None,
                                            "usage": {"input_tokens": 12, "output_tokens": 1}}}),
                         ("content_block_start", {"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}}),
                         ("content_block_delta", {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "PONG"}}),
                         ("content_block_stop", {"type": "content_block_stop", "index": 0}),
                         ("message_delta", {"type": "message_delta", "delta": {"stop_reason": "end_turn", "stop_sequence": None},
                                            "usage": {"output_tokens": 2}}),
                         ("message_stop", {"type": "message_stop"})):
            await resp.write(("event: %s\ndata: %s\n\n" % (ev, json.dumps(data))).encode())
        await resp.write_eof()
        return resp
    app = web.Application()
    app.router.add_route("*", "/{tail:.*}", stand_in)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    V.PRESETS["deepseek"]["url"] = "http://127.0.0.1:%d" % site._server.sockets[0].getsockname()[1]   # never DeepSeek here
    key = "stand-in-key-0123456789abcdef"
    p.env[V.key_name("deepseek")] = key
    await p.api_vendors_ok(pkey5, True)
    sid11 = (await p.api_new(pkey5, "Reply with one word: PONG.", vendor="deepseek"))["sid"]
    await until(lambda: (p.attn.rec.get(sid11) or {}).get("ts"), what="итог сессии на модели DeepSeek")
    models = sorted({a["model"] for a in asked if a["model"]})
    tr = Path(p.transcript_of(sid11)[0]).read_text()
    log("DeepSeek (подставной): запросов", len(asked), "· модели", models, "· ключ только наш:",
        all(a["x"] == key for a in asked if a["path"].endswith("/messages")), "· итог:", p.attn.rec[sid11]["line"])
    assert asked and all(a["x"] == key and "sk-ant" not in a["auth"] for a in asked if a["path"].endswith("/messages")), \
        "another credential reached the vendor"
    for a in asked:
        log("   ", a["model"], "max", a["max"], "tools", a["tools"], "·", a["sys"][:120].replace("\n", " "))
    log("   в транскрипте модели:", sorted({json.loads(x).get("message", {}).get("model") for x in tr.splitlines()
                                            if '"assistant"' in x} - {None}))
    assert "deepseek-flash" in models and '"model":"deepseek-flash"' in tr.replace(" ", ""), "the vendor's model isn't in the transcript"
    assert p.store.vendor_of(sid11) == "deepseek"
    llm11 = (await p.row_stats(sid11))[1]
    log("модель в строке:", llm11)
    assert llm11 and llm11.get("vendor") == "DeepSeek" and llm11["model"].startswith("deepseek-flash"), "the row doesn't say the vendor's model"
    await runner.cleanup()
    log("тем создано:", len([1 for m, _ in calls if m == "createForumTopic"]), "· вызовов Telegram:", len(calls))
    for d in list(p.driven.values()):
        d.task.cancel()
    await asyncio.sleep(1)
    server.close()


asyncio.run(main())
shutil.rmtree(TMP, ignore_errors=True)
