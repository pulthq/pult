#!/usr/bin/env python3
"""Pult tests without Telegram or Claude: a fake Bot API, a real socket and the real hook.

  ~/.local/share/pult/venv/bin/python tests/test_pult.py
"""
import asyncio
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import types
import unittest
from unittest import mock
import urllib.parse
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent / "src"
TMP = Path(tempfile.mkdtemp(prefix="pult-test-"))
os.environ.update(PULT_HOME=str(TMP), PULT_SOCK=str(TMP / "s.sock"), PULT_ENV=str(TMP / "env"))
sys.path.insert(0, str(HERE))

import httpx  # noqa: E402

import pult_hook  # noqa: E402
import pult_i18n as I  # noqa: E402
import pult_os  # noqa: E402
import pult_render as R  # noqa: E402
import pultd  # noqa: E402

I.set_lang("ru")          # the original checks are in Russian; English ones — EnglishTest
CHAT, OWNER, SID = -100123, 42, "11111111-2222-3333-4444-555555555555"
PKEY = "-Users-x-proj"
TP = str(TMP / "projects" / PKEY / (SID + ".jsonl"))


class FakeTg:
    def __init__(self):
        self.calls = []
        self.next_id = 1000
        self.dead_threads = set()      # topics deleted in Telegram: sending there fails

    def handler(self, req):
        method = req.url.path.rsplit("/", 1)[-1]
        ctype = req.headers.get("content-type", "")
        data = {k: v[0] for k, v in urllib.parse.parse_qs(req.content.decode()).items()} \
            if ctype.startswith("application/x-www-form-urlencoded") else {}
        self.calls.append((method, data))
        self.next_id += 1
        if method == "sendMessage" and data.get("message_thread_id") in self.dead_threads:
            return httpx.Response(400, json={"ok": False, "error_code": 400,
                                             "description": "Bad Request: message thread not found"})
        if method == "createForumTopic":
            res = {"message_thread_id": 77, "name": data.get("name")}
        elif method in ("sendMessage", "sendDocument"):
            res = {"message_id": self.next_id}
        else:
            res = True
        return httpx.Response(200, json={"ok": True, "result": res})

    def of(self, method):
        return [d for m, d in self.calls if m == method]

    def buttons(self, prefix):
        out = []
        for m, d in self.calls:
            if m in ("sendMessage", "editMessageText") and "reply_markup" in d:
                for row in json.loads(d["reply_markup"]).get("inline_keyboard", []):
                    out += [b["callback_data"] for b in row if b.get("callback_data", "").startswith(prefix)]
        return out


async def run_hook(ev, entry="claude-vscode", extra_env=None, wait=True):
    env = dict(os.environ, CLAUDE_CODE_ENTRYPOINT=entry, **(extra_env or {}))
    env.pop("PULT_DRIVEN", None)
    p = await asyncio.create_subprocess_exec(sys.executable, str(HERE / "pult_hook.py"), env=env,
                                             stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE)
    p.stdin.write(json.dumps(ev, ensure_ascii=False).encode())          # as Claude Code sends it: raw UTF-8
    p.stdin.close()
    if not wait:
        return p
    out = await p.stdout.read()
    await p.wait()
    return out.decode()


def tline(kind, text=None, ago=0.0, side=False, tool=False):
    content = [{"type": "tool_use", "name": "Read", "input": {}}] if tool else [{"type": "text", "text": text}]
    return json.dumps({"type": kind, "isSidechain": side, "message": {"role": kind, "content": content},
                       "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime(time.time() - ago))})


def ev(name, **kw):
    return dict(hook_event_name=name, session_id=SID, transcript_path=TP, cwd="/Users/x/proj", **kw)


async def until(cond, timeout=5):
    t = time.monotonic()
    while not cond():
        if time.monotonic() - t > timeout:
            raise AssertionError("не дождался")
        await asyncio.sleep(0.02)


class RenderTest(unittest.TestCase):
    def test_md(self):
        h = R.md_to_html("# Итог\n**жирно** и `код` <тег>\n```py\nx = 1 < 2\n```\n[сайт](https://a.b) [файл](src/a.py)")
        self.assertIn("<b>Итог</b>", h)
        self.assertIn("<code>код</code>", h)
        self.assertIn("&lt;тег&gt;", h)
        self.assertIn("<pre>x = 1 &lt; 2</pre>", h)
        self.assertIn('<a href="https://a.b">сайт</a>', h)
        self.assertIn("файл (<code>src/a.py</code>)", h)

    def test_table(self):
        h = R.md_to_html("до\n| a | b |\n|---|---|\n| 1 | 2 |\nпосле")
        self.assertIn("<pre>| a | b |", h)
        self.assertIn("после", h)

    def test_split_keeps_code(self):
        md = "абзац\n\n```\n" + "\n".join("строка %d" % i for i in range(900)) + "\n```\n\nконец"
        chunks = R.split_md(md)
        self.assertGreater(len(chunks), 2)
        for c in chunks:
            self.assertLessEqual(len(c), R.CHUNK)
            self.assertEqual(c.count("```") % 2, 0, c[:80])

    def test_steps(self):
        self.assertEqual(R.tool_step("Read", {"file_path": "/Users/x/proj/a/b.md"}, "/Users/x/proj"), "📖 a/b.md")
        self.assertEqual(R.tool_step("Bash", {"command": "ls", "description": "Список"}), "⌘ Список")
        self.assertIsNone(R.tool_step("TodoWrite", {}))
        self.assertTrue(R.tool_step("Bash", {"command": "x"}, failed=True).startswith("⚠️"))
        self.assertTrue(R.tool_step("Read", {"file_path": "a"}, sub=True).startswith("↳"))
        self.assertEqual(R.steps_word(1), "1 шаг")
        self.assertEqual(R.steps_word(3), "3 шага")
        self.assertEqual(R.steps_word(11), "11 шагов")
        self.assertEqual(R.steps_word(22), "22 шага")

    def test_human(self):
        self.assertEqual(R.human_dur(40), "40 с")
        self.assertEqual(R.human_dur(360), "6 мин")
        self.assertEqual(R.human_dur(3600), "1 ч")
        self.assertEqual(R.human_dur(3900), "1 ч 5 мин")
        self.assertEqual(R.plain("## Итог\n- **жирно** и `код` [файл](src/a.py)\n```\nx\n```", 100),
                         "Итог жирно и код файл …")

    def test_permission_text(self):
        t = R.permission_text("Bash", {"command": "ls -la", "description": "Список файлов"})
        self.assertIn("Выполнить команду: <b>«Список файлов»</b>", t)
        self.assertIn("<pre>ls -la</pre>", t)                                     # the command is always shown
        t = R.permission_text("Edit", {"file_path": "/p/a.py", "old_string": "x = 1", "new_string": "x = 2\ny = 3"}, "/p")
        self.assertIn("Изменить файл <code>a.py</code> (+2 −1)", t)
        self.assertIn("− x = 1", t)
        self.assertIn("+ y = 3", t)
        t = R.permission_text("Write", {"file_path": str(TMP / "нет.txt"), "content": "a\nb"})
        self.assertIn("Создать файл", t)
        self.assertIn("2 строки", t)
        self.assertIn("Искать в интернете", R.permission_text("WebSearch", {"query": "погода"}))
        self.assertIn("Вызвать <b>tg: send</b>", R.permission_text("mcp__tg__send", {"a": 1}))

    def test_attachments(self):
        # the path under the owner's message is for Claude; a person sees "📎 снимок", and the title stays clean
        text = "тест\n\n[Attachment from the Pult app: /Users/x/.local/share/pult/inbox/2026-10/app-1.jpg]"
        self.assertEqual(R.attachments(text), ("тест", ["/Users/x/.local/share/pult/inbox/2026-10/app-1.jpg"]))
        self.assertEqual(R.prompt_text(text), "тест 📎 снимок")
        self.assertEqual(R.prompt_text("Have a look at the attachment.\n\n[Attachment from Telegram: /a/inbox/2026-10/5.pdf]"), "📎 файл")
        self.assertEqual(R.prompt_text("просто текст"), "просто текст")
        self.assertEqual(R.md_to_html("[CHANGELOG.md](CHANGELOG.md) и [journal.md](docs/journal.md)"),
                         "<code>CHANGELOG.md</code> и <code>docs/journal.md</code>")

    def test_answers(self):
        qs = [{"question": "Q1"}, {"question": "Q2"}]
        self.assertEqual(R.answers_for(qs, {0: ["A"], 1: ["B", "C"]}), {"Q1": "A", "Q2": "B, C"})

    def test_task_notes(self):
        # what the "prompt" of a turn started by Claude Code itself looks like (probe 2026-10-16, 2.1.301)
        one = lambda i, st, what: ("<task-notification>\n<task-id>%s</task-id>\n<tool-use-id>t</tool-use-id>\n"
                                   "<output-file>/tmp/%s.output</output-file>\n<status>%s</status>\n<summary>Background "
                                   "command \"%s\" completed (exit code 1)</summary>\n</task-notification>" % (i, i, st, what))
        notes = R.task_notes(one("b1", "failed", 'Ждать "ответ" сервера'))
        self.assertEqual(notes, [{"id": "b1", "status": "failed", "what": 'Ждать "ответ" сервера'}])
        self.assertEqual(R.task_notes_text(notes), '⚙️ Не удалась фоновая задача «Ждать "ответ" сервера»')
        two = R.task_notes(one("b1", "completed", "А") + "\n" + one("b2", "completed", "Б"))
        self.assertEqual(R.task_notes_text(two), "⚙️ Закончились фоновые задачи: «А», «Б»")
        self.assertEqual(R.task_notes("Посмотри <task-notification> в логе"), [])     # a prompt typed by a human
        self.assertEqual(R.bg_text([]), "")
        self.assertEqual(R.bg_text([{"id": "b1", "status": "running", "description": "Сборка"}]),
                         "⚙️ В фоне ещё идёт: «Сборка»")
        many = [{"id": str(i), "status": "running", "description": "з%d" % i} for i in range(5)]
        self.assertEqual(R.bg_text(many + [{"id": "x", "status": "completed", "description": "старая"}]),
                         "⚙️ В фоне ещё 5: «з0», «з1», «з2» и ещё 2")


class EnglishTest(unittest.TestCase):
    """English is the default language; the original checks above run in Russian."""

    def setUp(self):
        I.set_lang("en")

    def tearDown(self):
        I.set_lang("ru")

    def test_render(self):
        self.assertEqual(R.human_dur(40), "40 s")
        self.assertEqual(R.human_dur(3900), "1 h 5 min")
        self.assertEqual(R.steps_word(1), "1 step")
        self.assertEqual(R.steps_word(3), "3 steps")
        t = R.permission_text("Bash", {"command": "ls -la", "description": "List files"})
        self.assertIn("Run a command: <b>“List files”</b>", t)
        t = R.permission_text("Edit", {"file_path": "/p/a.py", "old_string": "x = 1", "new_string": "x = 2\ny = 3"}, "/p")
        self.assertIn("Edit file <code>a.py</code> (+2 −1)", t)
        self.assertIn("Search the web: <b>“weather”</b>", R.permission_text("WebSearch", {"query": "weather"}))
        self.assertIn("pick an option", R.question_text({"question": "Q", "options": [{"label": "A"}]}))
        self.assertEqual(R.bg_text([{"id": "b1", "status": "running", "description": "Build"}]),
                         "⚙️ Still running in the background: “Build”")
        notes = [{"id": "b1", "status": "failed", "what": "Build"}]
        self.assertEqual(R.task_notes_text(notes), "⚙️ Background task failed: “Build”")
        now = time.time()
        self.assertRegex(R.reset_text(now + 2 * 3600 + 630, now), r"^at \d\d:\d\d \(in 2 h 10 min\)$")

    def test_i18n_complete(self):
        # every string has both languages, and the same {placeholders} in each
        import re as _re
        for k, v in I.S.items():
            self.assertEqual(set(v), set(I.LANGS), k)
            ph = [sorted(_re.findall(r"\{(\w+)\}", v[lang])) for lang in I.LANGS]
            self.assertEqual(ph[0], ph[1], k)
        for k, v in I.P.items():
            self.assertEqual((len(v["en"]), len(v["ru"])), (2, 3), k)


class HelpersTest(unittest.TestCase):
    def test_decode_pkey(self):
        root = TMP / "fs"
        (root / "Users" / "x y" / "my_proj").mkdir(parents=True)
        (root / "Users" / "x y" / "my").mkdir(parents=True)
        self.assertEqual(pultd.decode_pkey(pultd.sanitize("/Users/x y/my_proj"), str(root)),
                         str(root / "Users" / "x y" / "my_proj"))
        self.assertIsNone(pultd.decode_pkey("-Users-nobody-x", str(root)))

    def test_last_reply(self):
        p = TMP / "tr.jsonl"
        p.write_text("\n".join([tline("user", "запрос", ago=100), tline("assistant", "старое", ago=90),
                                tline("user", "ещё", ago=10), tline("assistant", "сейчас делаю", ago=5),
                                tline("assistant", tool=True, ago=4), tline("assistant", "субагент", side=True)]) + "\n")
        self.assertEqual(pultd.last_reply(str(p), time.time() - 20), "сейчас делаю")
        self.assertIsNone(pultd.last_reply(str(p), time.time() - 1))          # Claude has said nothing yet in this turn
        self.assertIsNone(pultd.last_reply(str(TMP / "нет.jsonl")))
        self.assertEqual(list(zip(range(5), pultd.vehi_marks()))[-1][1], pultd.VEHI[-1] + 2 * 3600)

    def test_skip(self):
        self.assertTrue(pultd.skip_pkey("-private-tmp-claude-501-x"))
        self.assertFalse(pultd.skip_pkey("-Users-alex-Documents-project"))

    def test_hook_filter(self):
        old = dict(os.environ)
        try:
            for entry, driven, injected, want in [("claude-vscode", None, None, True), ("cli", None, None, True),
                                                  ("sdk-cli", None, None, False), ("sdk-py", "1", None, False),
                                                  ("sdk-py", "1", "1", True)]:
                os.environ["CLAUDE_CODE_ENTRYPOINT"] = entry
                for k, v in (("PULT_DRIVEN", driven), ("PULT_INJECTED", injected)):
                    os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)
                self.assertEqual(pult_hook.wanted(), want, entry)
        finally:
            os.environ.clear()
            os.environ.update(old)

    def test_injected_hook_command(self):
        # the hook Pult injects into its own sessions runs through a shell: paths with spaces stay whole
        with mock.patch.object(pultd, "HOOK_PY", "/x y/venv/bin/python"), \
                mock.patch.object(pultd, "HOOK", "/x y/pult_hook.py"):
            me = types.SimpleNamespace(path="/x", sid=SID, resume=None, fork=False, _wait_hook=None)
            opts = pultd.Driven.options(me)
        cmd = json.loads(opts.settings)["hooks"]["Stop"][0]["hooks"][0]["command"]
        self.assertEqual(cmd, "PULT_INJECTED=1 '/x y/venv/bin/python' '/x y/pult_hook.py'")

    def test_input_idle(self):
        v = pult_os.input_idle()
        if pult_os.KIND == "mac":
            self.assertIsInstance(v, float)
        with mock.patch.object(pult_os.subprocess, "run", side_effect=FileNotFoundError):
            self.assertIsNone(pult_os.input_idle())                 # no ioreg (or no such system): "don't know"

    def test_linux_idle(self):
        # GNOME tells milliseconds, KDE (the freedesktop screensaver) seconds; a server — "don't know"
        answers = {"org.gnome.Mutter.IdleMonitor": "(uint64 4500,)\n", "org.freedesktop.ScreenSaver": "(uint32 7,)\n"}
        calls = []

        def fake_run(*cmd, timeout=5):
            calls.append(cmd[0])
            return answers.get(cmd[cmd.index("--dest") + 1]) if cmd[0] == "gdbus" else None
        with mock.patch.object(pult_os, "KIND", "linux"), mock.patch.object(pult_os, "run", fake_run), \
                mock.patch.object(pult_os.shutil, "which", lambda n: "/usr/bin/" + n), \
                mock.patch.dict(os.environ, {"DISPLAY": "", "WAYLAND_DISPLAY": ""}):
            self.assertEqual(pult_os.input_idle(), 4.5)
            self.assertEqual(pult_os.idle_source(), "gnome")
            del answers["org.gnome.Mutter.IdleMonitor"]
            self.assertEqual(pult_os.input_idle(), 7.0)
            calls.clear()
            self.assertEqual(pult_os.input_idle(), 7.0)
            self.assertEqual(len(calls), 1)                          # the way that answered is asked first
            answers.clear()
            self.assertIsNone(pult_os.input_idle())
            self.assertEqual(pult_os.idle_source(), "none")
        # dbus-send instead of gdbus
        with mock.patch.object(pult_os, "KIND", "linux"), \
                mock.patch.object(pult_os, "run", lambda *c, timeout=5: "method return\n   uint64 2000\n"
                                  if "--dest=org.gnome.Mutter.IdleMonitor" in c else None), \
                mock.patch.object(pult_os.shutil, "which", lambda n: "/usr/bin/dbus-send" if n == "dbus-send" else None):
            self.assertEqual(pult_os.input_idle(), 2.0)

    def test_x11_query_alone(self):
        # the X11 query runs in a separate Python: without a screen it just fails, and the caller says "don't know"
        r = subprocess.run([sys.executable, "-I", pult_os.__file__, "x11-idle"], capture_output=True, text=True,
                           env=dict(os.environ, DISPLAY=""), timeout=20)
        self.assertEqual((r.returncode, r.stdout), (1, ""))
        with mock.patch.dict(os.environ, {"DISPLAY": ":0", "WAYLAND_DISPLAY": "", "XDG_SESSION_TYPE": "x11"}), \
                mock.patch.object(pult_os, "run", lambda *c, timeout=5: None):
            self.assertIsNone(pult_os._x11())
        with mock.patch.dict(os.environ, {"DISPLAY": ":0", "WAYLAND_DISPLAY": "wayland-0"}):
            self.assertIsNone(pult_os._x11())                          # Wayland: X sees only its own windows

    def test_system_lang(self):
        with mock.patch.object(pult_os, "KIND", "linux"):
            for env, want in (({"LANGUAGE": "ru:en", "LANG": "en_US.UTF-8"}, "ru"), ({"LC_ALL": "C.UTF-8", "LANG": "ru_RU.UTF-8"}, "ru"),
                              ({"LANG": "de_DE.UTF-8"}, "de"), ({"LANG": "C"}, ""), ({}, "")):
                clean = {k: "" for k in ("LANGUAGE", "LC_ALL", "LC_MESSAGES", "LANG")}
                with mock.patch.dict(os.environ, dict(clean, **env)):
                    self.assertEqual(pult_os.system_lang(), want, env)
        self.assertTrue(pult_os.describe())

    def test_hooks_config(self):
        c = pult_hook.hooks_config("CMD")
        self.assertEqual(set(c), set(pult_hook.EVENTS))
        self.assertEqual(c["PermissionRequest"][0]["matcher"], "*")
        self.assertGreater(c["PermissionRequest"][0]["hooks"][0]["timeout"], 3600)
        self.assertNotIn("matcher", c["Stop"][0])

    def test_hook_without_daemon(self):
        async def go():
            t = time.monotonic()
            out = await run_hook(ev("PermissionRequest", tool_name="Bash", tool_input={"command": "ls"}),
                                 extra_env={"PULT_SOCK": str(TMP / "нет.sock")})
            return out, time.monotonic() - t
        out, dt = asyncio.run(go())
        self.assertEqual(out, "")
        self.assertLess(dt, 3)

    def test_ctl_strip(self):
        import pultctl
        hooks = {"PreToolUse": [{"matcher": "Bash", "hooks": [{"type": "command", "command": "guard.sh"}]}],
                 "Stop": [{"hooks": [{"type": "command", "command": "python3 /x/pult_hook.py"}]}]}
        self.assertEqual(pultctl.strip_ours(hooks), {"PreToolUse": hooks["PreToolUse"]})


def intro_id(fake, data):
    """The message_id the fake gave a sendMessage call (ids go up by one per call, starting at 1001)."""
    return 1001 + next(i for i, (m, d) in enumerate(fake.calls) if d is data)


class DaemonTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.fake = FakeTg()
        tg = pultd.Tg("T", transport=httpx.MockTransport(self.fake.handler))
        db = TMP / ("state-%s.db" % self._testMethodName)
        self.store = pultd.Store(db)
        self.store.put("chat", CHAT)
        self.store.put("lang_tg", "ru")
        self.store.set_topic(PKEY, "/Users/x/proj", "proj", None)
        self.p = pultd.Pult({"PULT_ALLOWED_USER_IDS": str(OWNER), "PULT_FORCE_AWAY": "1"}, tg, self.store)
        self.p.out = pultd.Outbox(rate=60000, burst=1000)
        self.p._agents = (time.monotonic() + 1e6, [])
        pultd.EDIT_EVERY = 0.05
        try:
            os.unlink(os.environ["PULT_SOCK"])
        except FileNotFoundError:
            pass
        self.server = await asyncio.start_unix_server(self.p.handle_conn, path=os.environ["PULT_SOCK"])
        self.tasks = [asyncio.create_task(self.p.out.run())]

    async def asyncTearDown(self):
        I.set_lang("ru")
        for t in self.tasks:
            t.cancel()
        self.server.close()

    def texts(self, method="sendMessage"):
        return [d.get("text", "") for d in self.fake.of(method)]

    def sent(self):
        return self.texts() + self.texts("editMessageText")

    async def test_topic_cards(self):
        # the app is set up: a new topic's intro carries one button into the app on the project's screen and is
        # pinned (Telegram shows the button in the topic's pinned bar); an older topic gets its card once, the
        # first time Pult writes there; a new app link edits the card
        self.p.env.update(PULT_APP_LINK="https://t.me/b/pult", PULT_RELAY_URL="wss://h.example/pult/agent")
        await self.p.send(PKEY, "первое")
        intro = next(d for d in self.fake.of("sendMessage") if "📂" in d["text"])
        btn = json.loads(intro["reply_markup"])["inline_keyboard"]
        self.assertEqual(btn, [[{"text": "📱 Пульт", "url": "https://t.me/b/pult?startapp=p_" + PKEY}]])
        self.assertEqual([d["message_id"] for d in self.fake.of("pinChatMessage")], [str(intro_id(self.fake, intro))])
        self.assertEqual(self.texts()[-1], "первое")                                # the card comes first
        await self.p.send(PKEY, "второе")
        self.assertEqual(len(self.fake.of("pinChatMessage")), 1)
        # older topics, from before the cards: on start each gets its card, once; a deleted one is remembered
        self.store.set_topic("-Users-x-old", "/Users/x/old", "old", 55)
        self.store.set_topic("-Users-x-gone", "/Users/x/gone", "gone", 66)
        self.fake.dead_threads.add("66")
        await self.p.ensure_cards()
        self.assertEqual(len(self.fake.of("pinChatMessage")), 2)
        self.assertEqual(self.p.store.get("cards")["66"], [None, "ru|https://t.me/b/pult?startapp=p_-Users-x-gone", False])
        await self.p.send("-Users-x-old", "в старую тему")
        self.p.cards_seen.clear()                                                   # a restart
        await self.p.ensure_cards()
        await asyncio.sleep(0.05)
        self.assertEqual(len([t for t in self.texts() if "📂 <b>old</b>" in t]), 1)
        self.assertEqual(len([d for d in self.fake.of("sendMessage") if d.get("message_thread_id") == "66"]), 1)
        # the app moved: after a restart the cards are edited, not posted again
        self.p.env["PULT_APP_LINK"] = "https://t.me/b/app2"
        self.p.cards_seen.clear()
        await self.p.ensure_cards()
        await until(lambda: any("app2" in d.get("reply_markup", "") for d in self.fake.of("editMessageText")))
        self.assertEqual(len([t for t in self.texts() if "📂 <b>old</b>" in t]), 1)
        self.assertEqual(len(self.fake.of("pinChatMessage")), 2)
        # a topic bound later (/bind) gets its card the first time Pult writes there
        self.store.set_topic("-Users-x-bound", "/Users/x/bound", "bound", 88)
        await self.p.send("-Users-x-bound", "первое в привязанной")
        await until(lambda: len(self.fake.of("pinChatMessage")) == 3)
        # a long path: the start parameter would not fit — the list of projects
        self.assertEqual(self.p.project_start("-" + "x" * 70), "projects")

    async def test_topic_card_without_app(self):
        # no app: a new topic gets its intro as before — no button, not pinned; older topics are left alone
        await self.p.send(PKEY, "первое")
        intro = next(d for d in self.fake.of("sendMessage") if "📂" in d["text"])
        self.assertNotIn("reply_markup", intro)
        self.store.set_topic("-Users-x-old", "/Users/x/old", "old", 55)
        await self.p.ensure_cards()
        await self.p.send("-Users-x-old", "в старую тему")
        await asyncio.sleep(0.05)
        self.assertEqual(self.fake.of("pinChatMessage"), [])
        self.assertEqual(len([t for t in self.texts() if "📂" in t]), 1)

    async def test_menu_button(self):
        # the private chat with the bot: the app button next to the message field; without the app — the default
        self.p.env.update(PULT_APP_LINK="https://t.me/b/pult", PULT_RELAY_URL="wss://h.example/pult/agent")
        await self.p.setup_menu_button()
        mb = json.loads(self.fake.of("setChatMenuButton")[-1]["menu_button"])
        self.assertEqual(mb, {"type": "web_app", "text": "Пульт", "web_app": {"url": "https://h.example/pult/"}})
        self.assertEqual(self.fake.of("setChatMenuButton")[-1]["chat_id"], str(OWNER))
        self.p.env.pop("PULT_APP_LINK")
        await self.p.setup_menu_button()
        self.assertNotIn("menu_button", self.fake.of("setChatMenuButton")[-1])

    async def test_turn_feed(self):
        Path(TP).parent.mkdir(parents=True, exist_ok=True)
        Path(TP).write_text(tline("user", "старый запрос", ago=300) + "\n" + tline("assistant", "старая реплика", ago=290) + "\n")
        await run_hook(ev("SessionStart", source="startup"))
        await run_hook(ev("UserPromptSubmit", prompt="Сделай отчёт по продажам"))
        await asyncio.sleep(0.05)
        with open(TP, "a") as f:
            f.write(tline("assistant", "Читаю **файлы** с продажами за `октябрь`") + "\n")
        for f in ("a.md", "b.md", "c.md"):
            await run_hook(ev("PostToolUse", tool_name="Read", tool_input={"file_path": "/Users/x/proj/" + f}))
        await until(lambda: any("💬 Читаю файлы с продажами за октябрь" in t for t in self.texts("editMessageText")))
        await run_hook(ev("Stop", last_assistant_message="Готово: **отчёт** собран"))
        await until(lambda: any("Готово" in t for t in self.texts()))
        self.assertEqual(len(self.fake.of("createForumTopic")), 1)
        self.assertIn("📂", self.texts()[0])                     # intro message of the new topic
        turn = next(t for t in self.texts() if "Сделай отчёт" in t)
        self.assertIn("⏳ <b>proj</b> · работает", turn)          # named after the project: no session title yet
        self.assertIn("<i>Ты: «Сделай отчёт по продажам»</i>", turn)
        self.assertNotIn("старая реплика", "".join(self.sent()))   # a reply from the previous turn is not "now"
        await until(lambda: any("✔️ <b>proj</b> · готово за" in t for t in self.texts("editMessageText")))
        self.assertNotIn("💬", self.texts("editMessageText")[-1])   # done — no "now" line
        result = self.fake.of("sendMessage")[-1]
        self.assertTrue(result["text"].startswith("✅ <b>proj</b> · готово за "), result["text"])
        self.assertIn("<b>отчёт</b>", result["text"])
        self.assertEqual(result["message_thread_id"], "77")
        self.assertEqual(result["disable_notification"], "false")      # the Mac is idle — with sound
        self.assertEqual(self.store.msg(int(json.loads(result["reply_parameters"])["message_id"]))["sid"], SID)
        for t in self.sent():                                            # no session ids, no paths, no steps
            self.assertNotIn("#s", t)
            self.assertNotIn("a.md", t)

    def test_title(self):
        lv = self.p.live_of(SID, PKEY)
        lv.title = "продолжаем"                        # without a title, Claude Code names the session after the prompt
        self.assertEqual(self.p.title(lv), "proj")
        lv.title, lv.named = "Отчёт по продажам", True
        self.assertEqual(self.p.title(lv), "Отчёт по продажам")

    async def test_stale_turn(self):
        lv = self.p.live_of(SID, PKEY)
        t = self.p.start_turn(lv, "задача")
        self.assertTrue(await self.p.alive(lv, t))
        t.last -= pultd.STALE + 1                                    # 20 min of silence
        self.p._agents = (time.monotonic() + 1e6, [])
        self.assertTrue(await self.p.alive(lv, t))                   # no agent list — leave the turn alone
        self.p._agents = (time.monotonic() + 1e6, [{"sessionId": SID}])
        self.assertTrue(await self.p.alive(lv, t))                   # the tab is open, a long command is running
        self.p._agents = (time.monotonic() + 1e6, [{"sessionId": "другая"}])
        self.assertFalse(await self.p.alive(lv, t))                  # the tab was closed without SessionEnd
        t.changed.set()
        await until(lambda: t.done)
        self.assertEqual(t.done[0], "⏹")

    async def run_cli(self, *cmd, cwd=None, sock=None):
        env = dict(os.environ, PULT_SOCK=sock or os.environ["PULT_SOCK"])
        p = await asyncio.create_subprocess_exec(sys.executable, str(HERE / "pultctl.py"), "run", "--", *cmd, cwd=cwd,
                                                 env=env, stdout=asyncio.subprocess.PIPE)
        out = await p.stdout.read()
        return await p.wait(), out.decode()

    async def test_run_job(self):
        proj = TMP / "runproj"
        (proj / "sub").mkdir(parents=True, exist_ok=True)
        self.store.set_topic("-runproj", str(proj), "runproj", 55)
        code, out = await self.run_cli(sys.executable, "-c", "print('шаг 1'); print('шаг 2'); import sys; sys.exit(3)",
                                       cwd=str(proj / "sub"))
        self.assertEqual(code, 3)                                     # the command's exit code is passed through
        self.assertIn("шаг 2", out)                                # output goes to the terminal, as without the wrapper
        await until(lambda: any("❌" in t for t in self.texts()))
        start = next(d for d in self.fake.of("sendMessage") if d["text"].startswith("⚙️"))
        end = next(d for d in self.fake.of("sendMessage") if d["text"].startswith("❌"))
        self.assertEqual(start["message_thread_id"], "55")            # project topic is picked by the job's folder
        self.assertIn("ошибка, код 3", end["text"])
        self.assertIn("шаг 2", end["text"])                           # tail of the output
        self.assertIn("reply_parameters", end)
        job = self.p.jobs_done[0]
        self.assertEqual((job.code, job.tail[-1]), (3, "шаг 2"))
        # without the daemon the command runs as usual
        code, out = await self.run_cli(sys.executable, "-c", "print('сам')", sock=str(TMP / "нет.sock"))
        self.assertEqual((code, out.strip()), (0, "сам"))

    async def test_run_job_killed(self):
        old = pultd.TICK
        pultd.TICK = 0.05
        try:
            await self.p.on_run({"op": "start", "id": "dead0001", "cmd": "sleep 999", "cwd": "/нигде", "pid": 999999})
            self.assertNotIn("message_thread_id", self.fake.of("sendMessage")[-1])   # not a project — goes to "General"
            await until(lambda: not self.p.jobs)
            self.assertIsNone(self.p.jobs_done[0].code)                           # the wrapper was killed — interrupted
            await until(lambda: any("прервана" in t for t in self.texts("editMessageText")))
        finally:
            pultd.TICK = old

    async def test_prefs(self):
        self.assertEqual(self.p.prefs(), {"vehi": True, "mode": "auto", "lang": None})
        self.p.env["PULT_FORCE_AWAY"] = "0"                                           # you are at the Mac
        self.assertFalse(await self.p.loud())
        self.assertTrue(await self.p.loud(driven=True))                     # auto: a session from Telegram — with sound
        res = await self.p.api_prefs(mode="phone", vehi="да", lang="xx", evil=True)  # garbage is rejected
        self.assertEqual(res, {"vehi": True, "mode": "phone", "lang": None})
        self.assertTrue(await self.p.loud())                                      # "with the phone" — always with sound
        await self.p.api_prefs(mode="mac")
        self.p.env["PULT_FORCE_AWAY"] = "1"
        self.assertFalse(await self.p.loud(driven=True))                             # "at the Mac" — never
        self.store.put("prefs", {"vehi": True, "sound_at_mac": True})                # settings from before 0.6
        self.assertEqual(self.p.mode(), "phone")
        s = await self.p.api_settings()
        self.assertEqual(s["version"], pultd.VERSION)
        self.assertTrue(all("Bearer" not in x for x in s["log"]))

    async def test_modes_and_help(self):
        # "where am I" mode: the command, panel buttons, the pinned panel; "at the Mac" — everything arrives, silently
        base = {"from": {"id": OWNER, "language_code": "ru"}, "chat": {"id": CHAT}}
        await self.p.on_message(dict(base, message_id=1, text="/mode"))
        panel = self.fake.of("sendMessage")[-1]
        self.assertIn("уведомления: <b>🔄 Авто</b>", panel["text"])            # language comes from the owner's Telegram
        self.assertTrue(self.fake.of("pinChatMessage"))
        pinned = self.fake.of("pinChatMessage")[-1]["message_id"]
        self.assertEqual(self.store.get("panel"), int(pinned))                       # it is the panel that gets pinned
        n = len(self.fake.of("editMessageText"))
        await self.p.ensure_panel()                                                 # on startup: refresh, don't re-post
        await until(lambda: len(self.fake.of("editMessageText")) > n)
        self.assertEqual(int(self.fake.of("editMessageText")[-1]["message_id"]), self.store.get("panel"))
        await self.p.on_message(dict(base, message_id=2, text="/phone"))
        self.assertEqual(self.p.mode(), "phone")
        await self.p.on_message(dict(base, message_id=2, text="/mac"))                # the old name still works
        self.assertEqual(self.p.mode(), "mac")
        await self.p.set_mode("auto")
        await self.p.on_message(dict(base, message_id=2, text="/desk"))
        self.assertEqual(self.p.mode(), "mac")
        await self.p.notice(SID, "важное")                                          # explicit sound — still silent
        await until(lambda: any("важное" in d.get("text", "") for d in self.fake.of("sendMessage")))
        self.assertEqual(self.fake.of("sendMessage")[-1]["disable_notification"], "true")
        await self.p.on_callback({"id": "c", "from": {"id": OWNER}, "data": "w:phone", "message": {"message_id": 999}})
        self.assertEqual(self.p.mode(), "phone")
        await until(lambda: any("✓ 📱 Телефон" in d.get("reply_markup", "") for d in self.fake.of("editMessageText")))
        # help: sections as buttons; a section opens by editing the same message
        await self.p.on_message(dict(base, message_id=3, text="/help"))
        h = self.fake.of("sendMessage")[-1]
        self.assertIn("Выбери раздел", h["text"])
        self.assertIn("h:notify", h["reply_markup"])
        await self.p.on_callback({"id": "c2", "from": {"id": OWNER}, "data": "h:onoff", "message": {"message_id": 1000}})
        await until(lambda: any("pult tab off" in d.get("text", "") for d in self.fake.of("editMessageText")))
        self.assertIn("pult stop", self.fake.of("editMessageText")[-1]["text"])
        await self.p.on_callback({"id": "c3", "from": {"id": OWNER}, "data": "h:trouble", "message": {"message_id": 1000}})
        await until(lambda: "Журнал:" in self.fake.of("editMessageText")[-1].get("text", ""))
        self.assertIn("<code>%s</code>" % str(pultd.LOG_FILE).replace(str(Path.home()) + "/", "~/", 1),
                      self.fake.of("editMessageText")[-1]["text"])                    # this system's log
        await self.p.api_prefs(lang="en")                                            # language chosen in the settings
        await self.p.on_message(dict(base, message_id=4, text="/help"))
        self.assertIn("Pick a topic", self.fake.of("sendMessage")[-1]["text"])
        await self.p.on_message(dict(base, message_id=5, text="/feedback"))
        self.assertIn("https://github.com/pulthq/pult/issues", self.fake.of("sendMessage")[-1]["text"])
        # command menu — English by default, plus Russian
        await self.p.setup_commands()
        menus = self.fake.of("setMyCommands")
        self.assertEqual([d.get("language_code") for d in menus], [None, "ru"])
        self.assertIn('"desk"', menus[0]["commands"])
        self.assertNotIn('"mac"', menus[0]["commands"])
        self.assertTrue(json.loads(menus[0]["commands"])[0]["command"] == "new")       # the most used come first

    async def test_idle_without_the_system(self):
        # where the system can't tell keyboard and mouse idle (servers, remote sessions), "away" comes from the
        # owner's own actions in sessions here: a prompt typed, a permission answered
        self.p.env.pop("PULT_FORCE_AWAY", None)
        with mock.patch.object(pult_os, "input_idle", lambda: None):
            self.assertFalse(await self.p.away())                                   # just started: assume here
            self.p.here_seen -= pultd.AWAY_IDLE + 1
            self.assertTrue(await self.p.away())
            ov = await self.p.api_overview()
            self.assertTrue(ov["mac"]["away"])
            self.assertGreater(ov["mac"]["idle"], pultd.AWAY_IDLE)
            await run_hook(ev("SessionStart", source="startup"))
            await run_hook(ev("UserPromptSubmit", prompt="Сделай отчёт"))           # typed here
            await until(lambda: time.monotonic() - self.p.here_seen < 5)
            self.assertFalse(await self.p.away())

    async def test_private_chat(self):
        # the owner's private chat with the bot: /bind there explains the group; anything else says where to write
        dm = {"from": {"id": OWNER, "language_code": "ru"}, "chat": {"id": OWNER, "type": "private"}}
        await self.p.on_message(dict(dm, message_id=1, text="/bind"))
        self.assertEqual(self.texts()[-1], I.T("bind.private", "ru"))
        self.assertEqual(self.store.get("chat"), CHAT)                              # the group stays bound
        await self.p.on_message(dict(dm, message_id=2, text="привет"))
        self.assertEqual(self.texts()[-1], I.T("private.elsewhere", "ru"))
        self.assertIn("https://t.me/c/123/1", self.fake.of("sendMessage")[-1]["reply_markup"])   # a button into the group
        self.p.chat = None                                                          # no group yet — how to make one
        await self.p.on_message(dict(dm, message_id=3, text="привет"))
        self.assertEqual(self.texts()[-1], I.T("bind.private", "ru"))
        self.assertNotIn("reply_markup", self.fake.of("sendMessage")[-1])

    async def test_context_window(self):
        # the context window comes from a turn's result (modelUsage): the wrapper taps it for tabs, Driven.read for
        # sessions from Telegram; the app gets the window and the usable part, as VS Code counts it
        import pult_tab
        mu = {"claude-haiku-4-5": {"inputTokens": 5, "cacheReadInputTokens": 0, "contextWindow": 200000, "maxOutputTokens": 32000},
              "claude-opus-5-5": {"inputTokens": 3000, "cacheReadInputTokens": 150000, "contextWindow": 1000000, "maxOutputTokens": 64000}}
        self.assertEqual(pultd.ctx_from_usage(mu, "claude-haiku-4-5"), (200000, 32000))
        self.assertEqual(pultd.ctx_from_usage(mu, None), (1000000, 64000))             # the one that read the most
        self.assertIsNone(pultd.ctx_from_usage({"m": {"inputTokens": 1}}, "m"))
        self.assertEqual(pult_tab.ctx_from_result({"type": "result", "modelUsage": mu}, "claude-haiku-4-5"), (200000, 32000))
        self.assertIsNone(pult_tab.ctx_from_result({"type": "assistant", "modelUsage": mu}))
        self.assertEqual(pultd.ctx_usable(200000, 32000), 167000)                       # 200k − 20k − 13k, like VS Code
        self.store.touch_session(SID, PKEY, path="/Users/x/proj")
        self.p.live_of(SID, PKEY).transcript = TP
        Path(TP).parent.mkdir(parents=True, exist_ok=True)
        Path(TP).write_text("")
        r, w = await asyncio.open_unix_connection(os.environ["PULT_SOCK"])
        w.write(('{"op": "hello", "pid": 4343, "cwd": "/Users/x/proj", "sid": "%s", "version": "2.1.301"}\n'
                 '{"op": "ctx", "window": 200000, "max_out": 32000}\n' % SID).encode())
        await w.drain()
        await until(lambda: self.p.ctx.get(SID) == [200000, 32000])
        self.assertEqual(self.store.get("ctx")[SID], [200000, 32000])                   # survives a restart
        self.assertEqual((await self.p.api_session(SID))["ctx"], {"window": 200000, "max_out": 32000, "usable": 167000})
        w.close()

    async def test_inbox(self):
        # the app may fetch pictures from Pult's inbox only: a real image by its month/name, nothing outside
        import base64
        d = TMP / "inbox" / "2026-10"
        d.mkdir(parents=True, exist_ok=True)
        (d / "app-1.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"\0" * 8)
        (d / "note.txt").write_text("secret")
        got = await self.p.api_inbox("2026-10/app-1.png")
        self.assertEqual((got["kind"], base64.b64decode(got["data"])[:4]), ("png", b"\x89PNG"))
        for bad in ("2026-10/note.txt", "../env", "2026-10/../../env", "/etc/passwd", ""):
            with self.assertRaises(ValueError, msg=bad):
                await self.p.api_inbox(bad)

    async def test_app_uploads(self):
        # a screenshot from the app: saved like a Telegram attachment, Claude gets the path; anything that isn't a
        # picture is dropped; a picture alone is a message; nothing usable — an empty message
        import base64
        from types import SimpleNamespace
        self.store.touch_session(SID, PKEY, path="/Users/x/proj", driven=True)
        self.p.live_of(SID, PKEY).transcript = TP
        q = asyncio.Queue()
        self.p.driven[SID] = SimpleNamespace(q=q, busy=False, bg=set(), client=None, task=SimpleNamespace(cancel=lambda: None))
        png = base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"\0" * 20).decode()
        bad = base64.b64encode(b"#!/bin/sh\nrm -rf /\n").decode()
        res = await self.p.api_send(SID, "Look", files=[{"name": "a.png", "data": png}, {"name": "x.sh", "data": bad}, {"data": "%%%"}])
        self.assertEqual(res, {"ok": True, "how": "session"})
        text, _ = q.get_nowait()
        self.assertTrue(text.startswith("Look\n\n[Attachment from the Pult app: "), text)
        path = text.split(": ", 1)[1].rstrip("]")
        self.assertTrue(path.startswith(str(TMP / "inbox")) and path.endswith(".png"), path)
        self.assertEqual(Path(path).read_bytes()[:4], b"\x89PNG")
        self.assertEqual(text.count("[Attachment"), 1)
        with self.assertRaises(ValueError):
            await self.p.api_send(SID, "", files=[{"data": bad}])
        await self.p.api_send(SID, "", files=[{"data": png}])
        self.assertTrue(q.get_nowait()[0].startswith("Have a look at the attachment."))
        with mock.patch.object(self.p, "drive", mock.AsyncMock()) as drive:
            self.store.set_topic(PKEY, str(TMP), "proj", 77)
            await self.p.api_new(PKEY, "Fix this", files=[{"data": png}])
            self.assertIn("[Attachment from the Pult app: ", drive.call_args.args[2])

    async def test_new_and_stop_from_menu(self):
        # a tap in the command menu sends a bare /new or /stop: /new — the next text in the topic starts a new session;
        # /stop — the topic's current session from Telegram, no reply needed
        from types import SimpleNamespace
        self.store.set_topic(PKEY, "/Users/x/proj", "proj", 77)
        base = {"from": {"id": OWNER}, "chat": {"id": CHAT}, "message_thread_id": 77, "is_topic_message": True}
        with mock.patch.object(self.p, "drive", mock.AsyncMock()) as drive:
            await self.p.on_message(dict(base, message_id=1, text="/new"))
            self.assertIn("Напиши задачу", self.texts()[-1])
            drive.assert_not_called()
            await self.p.on_message(dict(base, message_id=2, text="Собери отчёт"))
            drive.assert_called_once()
            self.assertEqual(drive.call_args.args[2:4], ("Собери отчёт", 2))      # a new session, no "which session?"
            self.assertFalse(self.fake.buttons("t:"))
            self.assertEqual(self.p.new_next, set())
            await self.p.on_message({"from": {"id": OWNER}, "chat": {"id": CHAT}, "message_id": 3, "text": "/new"})
            self.assertIn("спрошу, в каком проекте", self.texts()[-1])            # General: no project to start in
        await self.p.on_message(dict(base, message_id=4, text="/stop"))
        self.assertIn("Прерывать нечего", self.texts()[-1])
        stopped = []
        self.store.touch_session(SID, PKEY, path="/Users/x/proj", driven=True)
        self.p.driven[SID] = SimpleNamespace(busy=True, bg=set(), q=asyncio.Queue(), task=SimpleNamespace(cancel=lambda: None),
                                             client=SimpleNamespace(interrupt=mock.AsyncMock(side_effect=lambda: stopped.append(1))))
        self.p.set_focus(PKEY, SID)
        await self.p.on_message(dict(base, message_id=5, text="/stop"))
        self.assertEqual(stopped, [1])
        self.assertEqual(self.fake.of("setMessageReaction")[-1]["message_id"], "5")
        # a reply to one's own message continues the same session; an idle session from Telegram reacts 👀 at once
        self.p.driven[SID].busy = False
        await self.p.on_message(dict(base, message_id=6, text="ещё раз"))
        self.assertEqual(self.store.msg(6)["sid"], SID)
        self.assertIn('"👀"', self.fake.of("setMessageReaction")[-1]["reaction"])
        await self.p.on_message(dict(base, message_id=7, text="и ещё", reply_to_message={"message_id": 6}))
        self.assertEqual(self.p.driven[SID].q.qsize(), 2)

    async def test_vehi(self):
        old = pultd.VEHI
        pultd.VEHI = (0.3, 0.8)
        try:
            await run_hook(ev("UserPromptSubmit", prompt="Долгая задача"))
            await until(lambda: any("работает уже" in t for t in self.texts()))
            vehi = next(d for d in self.fake.of("sendMessage") if "работает уже" in d["text"])
            self.assertEqual(vehi["disable_notification"], "false")        # the owner is away — with sound
            self.assertIn("reply_parameters", vehi)                        # as a reply to the turn message
            tok = self.fake.buttons("m:")[0]
            await self.p.on_callback({"id": "v", "from": {"id": OWNER}, "data": tok,
                                      "message": {"message_id": 1, "text": vehi["text"]}})
            self.assertTrue(self.p.live[SID].turn.muted)
            await until(lambda: any("🔕" in t for t in self.texts("editMessageText")))
            await asyncio.sleep(0.8)
            self.assertEqual(len([t for t in self.texts() if "работает уже" in t]), 1)   # no more milestones after 🔕
        finally:
            pultd.VEHI = old
            await run_hook(ev("Stop", last_assistant_message="ок"))

    async def test_handover_to_mac(self):
        # a session from Telegram was opened in VS Code — Pult closes its own idle process
        from types import SimpleNamespace
        cancelled = []
        self.p.driven[SID] = SimpleNamespace(busy=False, bg=set(), task=SimpleNamespace(cancel=lambda: cancelled.append(1)))
        await run_hook(ev("SessionStart", source="resume"))
        self.assertEqual(cancelled, [1])
        self.assertFalse(self.p.live[SID].driven)
        # a background task lived in Pult's process and was closed with it; the owner is told which one
        self.p.live[SID].bg = [{"id": "b1", "description": "Сборка"}]
        self.p.driven[SID] = SimpleNamespace(busy=False, bg={"b1"}, task=SimpleNamespace(cancel=lambda: cancelled.append(2)))
        await run_hook(ev("UserPromptSubmit", prompt="на Маке"))
        self.assertEqual(cancelled, [1, 2])
        await until(lambda: any("фоновые задачи остановлены" in t and "«Сборка»" in t for t in self.texts()))
        self.assertEqual(self.p.live[SID].bg, [])

    async def test_background_tasks(self):
        # turn over, its background command still running → a line in the result; once it ends, Claude starts a turn
        await run_hook(ev("UserPromptSubmit", prompt="Собери проект в фоне"))
        await run_hook(ev("PostToolUse", tool_name="Bash", tool_input={"command": "make", "run_in_background": True}))
        await run_hook(ev("Stop", last_assistant_message="Запустил сборку",
                          background_tasks=[{"id": "b7", "type": "shell", "status": "running",
                                             "description": "Сборка проекта", "command": "make"}]))
        await until(lambda: any(t.startswith("✅") for t in self.texts()))
        res = next(t for t in self.texts() if t.startswith("✅"))
        self.assertIn("\n⚙️ В фоне ещё идёт: «Сборка проекта»\n", res)
        ov = await self.p.api_overview()
        self.assertEqual([s["bg"] for s in ov["live"]], [["Сборка проекта"]])  # in "Running" — with the background task
        n = len(self.texts())
        note = ("<task-notification>\n<task-id>b7</task-id>\n<tool-use-id>toolu_1</tool-use-id>\n<output-file>/tmp/x"
                "</output-file>\n<status>completed</status>\n<summary>Background command \"Сборка проекта\" completed "
                "(exit code 0)</summary>\n</task-notification>")
        await run_hook(ev("UserPromptSubmit", prompt=note))
        await until(lambda: len(self.texts()) > n)
        turn = self.texts()[n]
        self.assertIn("<i>⚙️ Закончилась фоновая задача «Сборка проекта»</i>", turn)
        self.assertNotIn("Ты:", turn)
        self.assertNotIn("task-notification", "".join(self.sent()))
        self.assertEqual(self.p.live[SID].bg, [])
        self.assertEqual(self.p.live_item(self.p.live[SID])["note"], "⚙️ Закончилась фоновая задача «Сборка проекта»")
        await run_hook(ev("Stop", last_assistant_message="Сборка прошла", background_tasks=[]))
        await until(lambda: any(t.startswith("✅") and "Сборка прошла" in t for t in self.texts()))
        self.assertNotIn("В фоне", self.texts()[-1])
        self.assertNotIn("task-notification", self.p.live[SID].title or "")

    async def test_tab(self):
        # a VS Code tab with Pult's wrapper introduced itself and reported its session → replies from Telegram and
        # from the app go straight into it; the turn for that message replies to the owner's message
        self.store.touch_session(SID, PKEY, path="/Users/x/proj")
        self.store.set_topic(PKEY, "/Users/x/proj", "proj", 77)
        r, w = await asyncio.open_unix_connection(os.environ["PULT_SOCK"])
        w.write(b'{"op": "hello", "pid": 4242, "cwd": "/Users/x/proj", "sid": null, "version": "2.1.301"}\n')
        w.write(('{"op": "sid", "sid": "%s"}\n' % SID).encode())
        await w.drain()
        await until(lambda: self.p.tab_for(SID))
        self.p._agents = (time.monotonic() + 1e6, [{"sessionId": SID, "cwd": "/Users/x/proj"}])   # open on the Mac
        await self.p.continue_session(SID, "Проверь логи", 55, 77)
        got = json.loads(await asyncio.wait_for(r.readline(), 3))
        self.assertEqual((got["op"], got["text"]), ("send", "Проверь логи"))
        self.assertFalse(self.fake.buttons("f:"))                    # not a fork — straight into the tab
        await run_hook(ev("UserPromptSubmit", prompt="Проверь логи"))
        await until(lambda: self.fake.of("sendMessage"))
        turn = self.fake.of("sendMessage")[-1]
        self.assertEqual(json.loads(turn["reply_parameters"])["message_id"], 55)
        self.assertNotIn("Ты:", turn["text"])
        self.assertEqual(self.store.msg(55)["sid"], SID)
        self.assertTrue(self.p.live_item(self.p.live[SID])["tab"])
        await self.p.ask_target(self.store.topic(PKEY), "Ещё вопрос", 56, 77)    # "where to": this session is 💻
        kb = json.loads(self.fake.of("sendMessage")[-1]["reply_markup"])["inline_keyboard"]
        self.assertTrue(kb[0][0]["text"].startswith("💻 "), kb)
        self.assertEqual(await self.p.api_send(SID, "Ещё"), {"ok": True, "how": "tab"})
        self.assertEqual(json.loads(await asyncio.wait_for(r.readline(), 3))["text"], "Ещё")
        # a message into a busy tab: Claude Code absorbs it into the running turn without a UserPromptSubmit and the
        # tab doesn't show it (2.1.301) — the turn's result replies to that message in Telegram
        await self.p.continue_session(SID, "А меня обновил?", 57, 77)
        self.assertEqual(json.loads(await asyncio.wait_for(r.readline(), 3))["text"], "А меня обновил?")
        await run_hook(ev("Stop", last_assistant_message="Да, обновил"))
        await until(lambda: any("Да, обновил" in d.get("text", "") for d in self.fake.of("sendMessage")))
        res = next(d for d in self.fake.of("sendMessage") if "Да, обновил" in d["text"])
        self.assertEqual(json.loads(res["reply_parameters"])["message_id"], 57)
        self.assertNotIn(SID, self.p.tab_expect)
        w.close()
        await until(lambda: not self.p.tabs)                       # the tab was closed — it can no longer be written to
        self.assertEqual(await self.p.api_send(SID, "снова"), {"ok": False, "need": "fork"})

    async def test_topic_focus(self):
        # text in a project topic: the only open tab — no question; then the topic remembers its session; two open
        # tabs after 2 h of quiet — the question, once; a closed tab is forgotten; the pinned card shows 🎯
        SID2 = "22222222-3333-4444-5555-666666666666"
        self.p.env.update(PULT_APP_LINK="https://t.me/b/pult", PULT_RELAY_URL="wss://h.example/pult/agent")
        self.store.set_topic(PKEY, "/Users/x/proj", "proj", 77)
        for sid, title in ((SID, "Отчёт"), (SID2, "Тесты")):
            self.store.touch_session(sid, PKEY, path="/Users/x/proj", title=title)
        base = {"from": {"id": OWNER}, "chat": {"id": CHAT}, "message_thread_id": 77, "is_topic_message": True}

        async def tab(pid, sid):
            r, w = await asyncio.open_unix_connection(os.environ["PULT_SOCK"])
            w.write(('{"op": "hello", "pid": %d, "cwd": "/Users/x/proj", "sid": "%s", "version": "2.1.301"}\n'
                     % (pid, sid)).encode())
            await w.drain()
            await until(lambda: self.p.tab_for(sid))
            return r, w
        r1, w1 = await tab(4001, SID)
        await self.p.on_message(dict(base, message_id=10, text="Проверь логи"))
        self.assertEqual(json.loads(await asyncio.wait_for(r1.readline(), 3))["text"], "Проверь логи")
        self.assertFalse(self.fake.buttons("t:"))                                   # no "where to"
        self.assertTrue(any("→ «Отчёт». Текст в этой теме дальше идёт туда же" in t for t in self.texts()))
        await until(lambda: any("🎯 Сейчас: «Отчёт»" in t for t in self.sent()))      # the card says it
        r2, w2 = await tab(4002, SID2)                                              # a second tab opens
        await self.p.on_message(dict(base, message_id=11, text="И ошибки"))
        self.assertEqual(json.loads(await asyncio.wait_for(r1.readline(), 3))["text"], "И ошибки")
        await asyncio.sleep(0.05)
        self.assertEqual(len([t for t in self.texts() if t.startswith("→")]), 1)       # said once, not on every text
        # two hours of quiet: two open tabs — ask, once
        focus = self.store.get("focus")
        focus[PKEY][1] -= pultd.FOCUS_IDLE + 1
        self.store.put("focus", focus)
        await self.p.on_message(dict(base, message_id=12, text="Теперь тесты"))
        await until(lambda: any("Запомню выбор" in t for t in self.texts()))
        choice = next(b for b in self.fake.buttons("t:") if self.p.offers[b[2:]][0] == "sess"
                      and self.p.offers[b[2:]][1] == SID2)
        await self.p.on_offer(choice, 77)
        self.assertEqual(json.loads(await asyncio.wait_for(r2.readline(), 3))["text"], "Теперь тесты")
        await self.p.on_message(dict(base, message_id=13, text="И покрытие"))
        self.assertEqual(json.loads(await asyncio.wait_for(r2.readline(), 3))["text"], "И покрытие")
        # the chosen tab closes: forgotten; the only open tab left takes the text again
        w2.close()
        await until(lambda: not self.p.tab_for(SID2))
        self.assertIsNone(self.p.focus_of(PKEY))
        await self.p.on_message(dict(base, message_id=14, text="Вернёмся к логам"))
        self.assertEqual(json.loads(await asyncio.wait_for(r1.readline(), 3))["text"], "Вернёмся к логам")
        # a reply to another session's message switches the topic to it
        self.store.map_msg(500, SID2, "msg")
        self.p._agents = (time.monotonic() + 1e6, [])
        with mock.patch.object(self.p, "drive", mock.AsyncMock()):
            await self.p.on_message(dict(base, message_id=15, text="продолжи", reply_to_message={"message_id": 500}))
        self.assertEqual(self.p.focus_of(PKEY), SID2)
        w1.close()

    async def test_tab_version(self):
        # a new extension is out — the owner is told once that writing into tabs on it awaits verification
        ext = TMP / "ext"
        for v in ("2.1.9", "2.1.301", "2.1.30"):
            (ext / ("anthropic.claude-code-%s-darwin-arm64" % v)).mkdir(parents=True, exist_ok=True)
        server = TMP / "ext-server"                                   # the server side of Remote-SSH counts too
        (server / "anthropic.claude-code-2.1.300-linux-x64").mkdir(parents=True, exist_ok=True)
        self.assertEqual(pult_os.newest_extension([ext, server]), "2.1.301")
        conf, vs = TMP / "tabv.json", TMP / "vscode" / "User" / "settings.json"
        conf.write_text('{"folders": ["~/Documents"], "versions": ["2.1.300"]}')
        vs.parent.mkdir(parents=True, exist_ok=True)
        vs.write_text('{\n  // настройки\n  "claudeCode.claudeProcessWrapper": "/x/pult-tab.sh",\n}')
        old = (pultd.TAB_CONF, pultd.EDITOR_DIRS, pultd.EXT_DIRS)
        pultd.TAB_CONF, pultd.EDITOR_DIRS, pultd.EXT_DIRS = conf, [TMP / "nothing", vs.parent], [ext, server]
        try:
            await self.p.tab_version_check()
            await self.p.tab_version_check()
            await until(lambda: self.fake.of("sendMessage"))
            warn = [t for t in self.texts() if "Вышло обновление Claude Code" in t]
            self.assertEqual(len(warn), 1)
            self.assertIn("<b>2.1.301</b>", warn[0])
            conf.write_text('{"folders": ["~/Documents"], "versions": ["2.1.301"]}')
            self.store.put("tab_warned", None)
            await self.p.tab_version_check()                            # a verified version — silence
            await asyncio.sleep(0.1)
            self.assertEqual(len([t for t in self.texts() if "Вышло обновление" in t]), 1)
        finally:
            pultd.TAB_CONF, pultd.EDITOR_DIRS, pultd.EXT_DIRS = old

    def test_tab_wrapper_rules(self):
        import pult_tab
        v = "/x/anthropic.claude-code-2.1.301-darwin-arm64/resources/native-binary/claude"
        self.assertEqual(pult_tab.version_of(v), "2.1.301")
        conf = {"folders": [str(TMP / "sandbox")], "versions": ["2.1.301"]}
        (TMP / "sandbox" / "sub").mkdir(parents=True, exist_ok=True)
        chat = [v, "--output-format", "stream-json", "--input-format", "stream-json", "--verbose"]
        self.assertIsNone(pult_tab.why_direct(chat, conf, str(TMP / "sandbox" / "sub")))
        self.assertEqual(pult_tab.why_direct(chat, conf, str(TMP)), "folder not in the list")
        self.assertEqual(pult_tab.why_direct([v, "--claude-in-chrome-mcp"], conf, str(TMP / "sandbox")), "not a chat session")
        self.assertIn("version", pult_tab.why_direct([v.replace("301", "302")] + chat[1:], conf, str(TMP / "sandbox")))
        # no daemon — the wrapper still passes data byte for byte and exits with claude's exit code
        fake = TMP / "anthropic.claude-code-2.1.301-darwin-arm64" / "claude"
        fake.parent.mkdir(exist_ok=True)
        fake.write_text("#!/bin/sh\ncat\nexit 3\n")
        fake.chmod(0o755)
        (TMP / "tab.json").write_text(json.dumps(conf))
        data = "".join('{"type":"user","n":%d,"t":"%s"}\n' % (i, "ж" * i) for i in range(300)).encode()
        p = subprocess.run([sys.executable, str(HERE / "pult_tab.py"), str(fake), "--input-format",
                            "stream-json", "--output-format", "stream-json"], input=data, capture_output=True,
                           cwd=str(TMP / "sandbox"), timeout=20,
                           env=dict(os.environ, PULT_TAB_CONF=str(TMP / "tab.json"), PULT_SOCK=str(TMP / "нет.sock")))
        self.assertEqual((p.stdout, p.returncode), (data, 3))
        old, pult_tab.OFF = pult_tab.OFF, str(TMP / "tab-off")
        try:
            Path(pult_tab.OFF).touch()
            self.assertEqual(pult_tab.why_direct(chat, conf, str(TMP / "sandbox")), "switched off")
        finally:
            pult_tab.OFF = old

    async def test_english_turn(self):
        # the owner's Telegram is in English — a turn and its result in English
        self.store.put("lang_tg", "en")
        await run_hook(ev("UserPromptSubmit", prompt="Build the report"))
        await run_hook(ev("Stop", last_assistant_message="Done: **report** built"))
        await until(lambda: any(t.startswith("✅") for t in self.texts()))
        turn = next(t for t in self.texts() if "Build the report" in t)
        self.assertIn("<i>You: “Build the report”</i>", turn)
        self.assertIn(" · done", next(t for t in self.texts() if t.startswith("✅")))
        await self.p.on_message({"from": {"id": OWNER}, "chat": {"id": CHAT}, "message_id": 9, "text": "/help"})
        self.assertIn("Pick a topic", self.fake.of("sendMessage")[-1]["text"])
        # a message from Telegram in another language (the phone vs the computer) doesn't switch the bot
        await self.p.on_message({"from": {"id": OWNER, "language_code": "ru"}, "chat": {"id": CHAT}, "message_id": 10,
                                 "text": "/help"})
        self.assertIn("Pick a topic", self.fake.of("sendMessage")[-1]["text"])
        self.store.put("lang_tg", None)                                   # not known yet: the first message sets it
        await self.p.on_message({"from": {"id": OWNER, "language_code": "ru"}, "chat": {"id": CHAT}, "message_id": 11,
                                 "text": "/help"})
        self.assertIn("Выбери раздел", self.fake.of("sendMessage")[-1]["text"])

    async def test_today(self):
        # today's tokens: project name is the topic, else the folder, and if the folder is gone, the key's tail
        root = TMP / "today"
        for i, pkey in enumerate((PKEY, "-Users-nobody-gone-proj2")):
            (root / pkey).mkdir(parents=True, exist_ok=True)
            (root / pkey / "s.jsonl").write_text(json.dumps({
                "type": "assistant", "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime()),
                "message": {"id": "m%d" % i, "usage": {"output_tokens": 5 + i}}}) + "\n")
        self.p.day_tokens = pultd.PW.DayTokens(root, pultd.skip_pkey)
        d = await self.p.api_today()
        self.assertEqual([(r["name"], r["out"]) for r in d["projects"]], [("proj2", 6), ("proj", 5)])

    async def test_driven_stream(self):
        # a session from Telegram: the SDK stream is read in full, so the result of a turn Claude started itself
        # does not go to the next prompt; while a background task runs, the idle process is not closed
        from claude_agent_sdk import ResultMessage, SystemMessage
        import claude_agent_sdk
        res = lambda: ResultMessage(subtype="success", duration_ms=1, duration_api_ms=1, is_error=False, num_turns=1,
                                    session_id=SID, result="ok")
        bg = lambda ids: SystemMessage("background_tasks_changed", {"tasks": [{"task_id": i} for i in ids]})

        class FakeClient:
            def __init__(self, options):
                self.out = asyncio.Queue()
                self.sent = []

            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                closed.append(1)

            async def query(self, text):
                self.sent.append(text)
                stream.append(self)
                if text == "фон":
                    self.out.put_nowait(bg(["b1"]))
                self.out.put_nowait(res())

            async def receive_messages(self):
                while True:
                    yield await self.out.get()

        closed, stream = [], []
        old = (claude_agent_sdk.ClaudeSDKClient, pultd.DRIVEN_IDLE)
        claude_agent_sdk.ClaudeSDKClient, pultd.DRIVEN_IDLE = FakeClient, 0.3
        try:
            d = pultd.Driven(self.p, SID, "/Users/x/proj")
            d.q.put_nowait(("фон", None))
            await until(lambda: stream and not d.asking and d.bg == {"b1"})
            c = stream[0]
            c.out.put_nowait(res())                    # a turn started by Claude itself: a background task ended
            await asyncio.sleep(0.05)
            self.assertTrue(c.out.empty())             # the result is read at once, not by the next prompt
            await asyncio.sleep(0.5)                   # longer than DRIVEN_IDLE, but a background task is running
            self.assertEqual(closed, [])
            d.q.put_nowait(("дальше", None))
            await until(lambda: len(c.sent) == 2 and not d.asking)
            c.out.put_nowait(bg([]))
            await until(lambda: closed, timeout=3)     # no background tasks — the idle process is closed
        finally:
            claude_agent_sdk.ClaudeSDKClient, pultd.DRIVEN_IDLE = old

    async def test_ignores_automation_and_tmp(self):
        await run_hook(ev("UserPromptSubmit", prompt="cron"), entry="sdk-cli")
        tmp_ev = ev("UserPromptSubmit", prompt="tmp")
        tmp_ev["transcript_path"] = "/x/-private-tmp-a/%s.jsonl" % SID
        await run_hook(tmp_ev)
        await asyncio.sleep(0.2)
        self.assertEqual(self.fake.calls, [])

    async def test_permission_allow(self):
        proc = await run_hook(ev("PermissionRequest", tool_name="Bash", tool_input={"command": "git push"},
                                 permission_suggestions=[{"type": "addRules"}]), wait=False)
        await until(lambda: self.fake.buttons("p:"))
        self.assertIn("git push", self.texts()[-1])
        rid = self.fake.buttons("p:")[0].split(":")[1]
        await self.p.on_callback({"id": "1", "from": {"id": 999}, "data": "p:%s:y" % rid})   # a stranger
        self.assertFalse(self.p.req_by_rid[rid].fut.done())
        await self.p.on_callback({"id": "2", "from": {"id": OWNER}, "data": "p:%s:a" % rid})
        out = json.loads((await proc.stdout.read()).decode())
        d = out["hookSpecificOutput"]["decision"]
        self.assertEqual(d["behavior"], "allow")
        self.assertEqual(d["updatedPermissions"], [{"type": "addRules"}])
        await until(lambda: any("разрешено и запомнено" in t for t in self.texts("editMessageText")))

    async def test_permission_deny_by_reply(self):
        # a hook whose console isn't UTF-8 (Windows uses the system code page) still reads and writes UTF-8
        proc = await run_hook(ev("PermissionRequest", tool_name="Bash", tool_input={"command": "rm -rf сборка"}),
                              wait=False, extra_env={"PYTHONIOENCODING": "latin-1"})
        await until(lambda: self.p.req_by_msg)
        self.assertIn("rm -rf сборка", self.texts()[-1])
        msg_id = next(iter(self.p.req_by_msg))
        await self.p.on_message({"message_id": 5, "from": {"id": OWNER}, "chat": {"id": CHAT}, "text": "не надо, сначала бэкап",
                                 "message_thread_id": 77, "is_topic_message": True,
                                 "reply_to_message": {"message_id": msg_id}})
        d = json.loads((await proc.stdout.read()).decode())["hookSpecificOutput"]["decision"]
        self.assertEqual(d["behavior"], "deny")
        self.assertIn("сначала бэкап", d["message"])

    async def test_question(self):
        qs = [{"question": "Какой цвет?", "header": "Цвет", "multiSelect": False,
               "options": [{"label": "Красный"}, {"label": "Синий"}]},
              {"question": "Что ещё?", "header": "Ещё", "multiSelect": True,
               "options": [{"label": "A"}, {"label": "B"}, {"label": "C"}]}]
        proc = await run_hook(ev("PermissionRequest", tool_name="AskUserQuestion", tool_input={"questions": qs}),
                              wait=False)
        await until(lambda: len([b for b in self.fake.buttons("q:") if b.endswith(":ok")]) == 1)
        rid = self.fake.buttons("q:")[0].split(":")[1]
        for data in ("q:%s:0:1", "q:%s:1:0", "q:%s:1:2", "q:%s:1:2", "q:%s:1:1", "q:%s:1:ok"):
            await self.p.on_callback({"id": "x", "from": {"id": OWNER}, "data": data % rid})
        d = json.loads((await proc.stdout.read()).decode())["hookSpecificOutput"]["decision"]
        self.assertEqual(d["updatedInput"]["answers"], {"Какой цвет?": "Синий", "Что ещё?": "A, B"})
        self.assertEqual(d["updatedInput"]["questions"], qs)

    async def test_answered_on_mac(self):
        inp = {"command": "make deploy"}
        proc = await run_hook(ev("PermissionRequest", tool_name="Bash", tool_input=inp), wait=False)
        await until(lambda: self.p.req_by_msg)
        await run_hook(ev("PostToolUse", tool_name="Bash", tool_input=inp))
        self.assertEqual((await proc.stdout.read()).decode(), "")
        await until(lambda: any("разрешено на компьютере" in t for t in self.texts("editMessageText")))

    async def test_hook_killed(self):
        proc = await run_hook(ev("PermissionRequest", tool_name="Write", tool_input={"file_path": "/a"}), wait=False)
        await until(lambda: self.p.req_by_msg)
        proc.kill()
        await proc.wait()
        await until(lambda: any("решено на компьютере" in t for t in self.texts("editMessageText")))
        self.assertEqual(self.p.req_by_rid, {})

    async def test_projects(self):
        # the project list is built in a separate thread — SQLite must not be used from there (bug of 2026-10-15)
        base = TMP / "claude-projects"
        (base / PKEY).mkdir(parents=True, exist_ok=True)
        (base / PKEY / "a.jsonl").write_text("{}")
        (base / "-private-tmp-x").mkdir(exist_ok=True)
        (base / "-private-tmp-x" / "b.jsonl").write_text("{}")
        real = TMP / "real-proj"
        real.mkdir(exist_ok=True)
        self.store.set_topic(PKEY, str(real), "proj", None)
        old, pultd.CLAUDE_PROJECTS = pultd.CLAUDE_PROJECTS, base
        try:
            await self.p.on_message({"message_id": 1, "from": {"id": OWNER}, "chat": {"id": CHAT}, "text": "/projects"})
        finally:
            pultd.CLAUDE_PROJECTS = old
        self.assertEqual(len(self.fake.buttons("o:")), 1)
        tok = self.fake.buttons("o:")[0][2:]
        self.assertEqual(self.p.offers[tok], ("open", PKEY, str(real), None))
        self.assertNotIn("message_thread_id", self.fake.of("sendMessage")[-1])        # the reply goes to "General"
        note = await self.p.on_offer("o:" + tok, 0)
        self.assertEqual(note, "real-proj")
        self.assertEqual(len(self.fake.of("createForumTopic")), 1)
        self.assertIn("t.me/c/123/77", self.fake.of("sendMessage")[-1]["text"])        # link to the topic

    async def test_general_and_own_topic(self):
        # text in "General" and in a topic the owner created is not lost: pick a project → run
        real = TMP / "real-proj2"
        real.mkdir(exist_ok=True)
        base = TMP / "claude-projects2"
        (base / PKEY).mkdir(parents=True, exist_ok=True)
        (base / PKEY / "a.jsonl").write_text("{}")
        self.store.set_topic(PKEY, str(real), "proj", 77)
        runs = []

        async def drive(sid, path, text, origin, **kw):
            runs.append((path, text, origin, kw.get("quote", True)))
        self.p.drive = drive
        old, pultd.CLAUDE_PROJECTS = pultd.CLAUDE_PROJECTS, base
        try:
            await self.p.on_message({"message_id": 20, "from": {"id": OWNER}, "chat": {"id": CHAT}, "text": "Проверь логи"})
            tok = self.fake.buttons("o:")[-1][2:]
            self.assertEqual(self.p.offers[tok][0], "new")
            await self.p.on_offer("o:" + tok, 0)
            self.assertEqual(runs[-1], (str(real), "Проверь логи", 20, False))
            self.assertIn("Запустил", self.fake.of("sendMessage")[-1]["text"])
            # the owner's own topic 900, not bound to a project
            await self.p.on_message({"message_id": 21, "from": {"id": OWNER}, "chat": {"id": CHAT}, "text": "Ещё задача",
                                     "message_thread_id": 900, "is_topic_message": True})
            self.assertEqual(self.fake.of("sendMessage")[-1]["message_thread_id"], "900")
            tok = self.fake.buttons("o:")[-1][2:]
            self.assertEqual(self.p.offers[tok][0], "bind")
            await self.p.on_offer("o:" + tok, 900)
            self.assertEqual(self.store.topic(PKEY)["thread"], 900)
            self.assertEqual(runs[-1], (str(real), "Ещё задача", 21, True))
        finally:
            pultd.CLAUDE_PROJECTS = old

    def test_system_prompt(self):
        from types import SimpleNamespace
        d = SimpleNamespace(path="/x", resume=None, fork=False, sid="s", _wait_hook=None)
        o = pultd.Driven.options(d)
        self.assertEqual(o.system_prompt, {"type": "preset", "preset": "claude_code"})
        self.assertEqual(o.env["CLAUDE_CODE_ENTRYPOINT"], "claude-vscode")        # otherwise VS Code hides the session
        self.assertEqual(o.setting_sources, ["user", "project", "local"])

    async def test_routing(self):
        calls = []

        async def drive(sid, path, text, origin, **kw):
            calls.append(("drive", path, text))

        self.p.drive = drive
        base = {"from": {"id": OWNER}, "chat": {"id": CHAT}, "message_thread_id": 77, "is_topic_message": True}
        self.store.set_topic(PKEY, "/Users/x/proj", "proj", 77)
        # plain text in a project topic — first the "where to" question (reply_to is the "topic created" notice)
        self.store.touch_session(SID, PKEY, path="/Users/x/proj", title="Отчёт")
        await self.p.on_message(dict(base, message_id=10, text="Новая задача",
                                     reply_to_message={"message_id": 77, "forum_topic_created": {}}))
        self.assertEqual(calls, [])
        opts = [self.p.offers[b[2:]] for b in self.fake.buttons("t:")]
        self.assertEqual([o[0] for o in opts], ["sess", "new"])
        self.assertEqual(opts[0][1], SID)
        await self.p.on_offer("t:" + self.fake.buttons("t:")[-1][2:], 77)
        self.assertEqual(calls[-1], ("drive", "/Users/x/proj", "Новая задача"))
        # /new — a new session right away
        await self.p.on_message(dict(base, message_id=14, text="/new Ещё задача"))
        self.assertEqual(calls[-1], ("drive", "/Users/x/proj", "Ещё задача"))
        calls.clear()
        # a stranger — silence
        await self.p.on_message(dict(base, message_id=11, text="взлом", **{"from": {"id": 5}}))
        self.assertEqual(len(calls), 0)
        # a reply to a message of a session open on the Mac — a fork is offered
        self.store.touch_session(SID, PKEY, path="/Users/x/proj")
        self.store.map_msg(500, SID, "result")
        self.p._agents = (time.monotonic() + 1e6, [{"sessionId": SID, "cwd": "/Users/x/proj"}])
        await self.p.on_message(dict(base, message_id=12, text="продолжи", reply_to_message={"message_id": 500}))
        self.assertTrue(self.fake.buttons("f:"))
        tok = self.fake.buttons("f:")[0][2:]
        self.assertEqual(self.p.offers[tok][:3], (SID, "/Users/x/proj", "продолжи"))
        # the session is closed on the Mac — the same session is continued
        self.p._agents = (time.monotonic() + 1e6, [])
        seen = []

        async def drive2(sid, path, text, origin, resume=None, fork=False, pkey=None, **kw):
            seen.append((sid, resume, fork, kw.get("quote")))
        self.p.drive = drive2
        await self.p.on_message(dict(base, message_id=13, text="ещё", reply_to_message={"message_id": 500}))
        self.assertEqual(seen[-1], (SID, SID, False, True))


if __name__ == "__main__":
    try:
        unittest.main(verbosity=1)
    finally:
        shutil.rmtree(TMP, ignore_errors=True)
