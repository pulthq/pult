#!/usr/bin/env python3
"""Pult tests without Telegram or Claude: a fake Bot API, a real socket and the real hook.

  ~/.local/share/pult/venv/bin/python tests/test_pult.py
"""
import asyncio
import gc
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
import warnings
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent / "src"
TMP = Path(tempfile.mkdtemp(prefix="pult-test-"))
os.environ.update(PULT_HOME=str(TMP), PULT_SOCK=str(TMP / "s.sock"), PULT_ENV=str(TMP / "env"))
sys.path.insert(0, str(HERE))

import httpx  # noqa: E402

import pult_attn as A  # noqa: E402
import pult_brief as B  # noqa: E402
import pult_hook  # noqa: E402
import pult_i18n as I  # noqa: E402
import pult_load as L  # noqa: E402
import pult_os  # noqa: E402
import pult_render as R  # noqa: E402
import pult_stt as STT  # noqa: E402
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
        self.file_bytes = b"OggS" + b"\0" * 40      # what getFile + download hand out (a voice message)
        self.menu_button = {"type": "default"}       # the app button in the owner's chat

    def handler(self, req):
        if "/file/bot" in req.url.path:          # a download of the path getFile gave
            return httpx.Response(200, content=self.file_bytes)
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
        elif method == "getFile":
            res = {"file_id": data.get("file_id"), "file_path": "voice/file_7.oga", "file_size": len(self.file_bytes)}
        elif method in ("sendMessage", "sendDocument"):
            res = {"message_id": self.next_id}
        elif method == "getChatMenuButton":
            res = self.menu_button
        elif method == "setChatMenuButton":
            self.menu_button = json.loads(data["menu_button"]) if "menu_button" in data else {"type": "default"}
            res = True
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


# What runs without Python's UTF-8 mode in real use — the hook, the tab wrapper, a command under `pult run` — runs so
# here too, whatever the environment (CI turns it on for the rest): a system code page (cp1251) must not break them
def plain_env(**kw):
    env = dict(os.environ, **kw)
    env.pop("PYTHONUTF8", None)
    return env


# the hook runs on the base Python, as Pult installs it: a venv's python.exe on Windows is a launcher that starts the
# real one as its child, and the hook would see the launcher as its parent instead of the claude that started it
HOOK_PY = getattr(sys, "_base_executable", sys.executable) if os.name == "nt" else sys.executable


async def run_hook(ev, entry="claude-vscode", extra_env=None, wait=True):
    env = plain_env(CLAUDE_CODE_ENTRYPOINT=entry, **(extra_env or {}))
    env.pop("PULT_DRIVEN", None)
    p = await asyncio.create_subprocess_exec(HOOK_PY, str(HERE / "pult_hook.py"), env=env,
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


ECHO = ("import os, sys\nif os.name == 'nt':\n    import msvcrt\n    msvcrt.setmode(0, os.O_BINARY)\n"
        "    msvcrt.setmode(1, os.O_BINARY)\nsys.stdout.buffer.write(sys.stdin.buffer.read())\nsys.stdout.flush()\n"
        "sys.exit(3)\n")                     # a claude that echoes its input and exits with 3


def fake_claude(folder, script):
    """A stand-in for claude in folder that runs this Python script: on macOS and Linux a script with #!, on Windows
    an .exe made the way pult-tab.exe is (the wrapper starts claude without a shell, and Windows starts only .exe)."""
    folder.mkdir(parents=True, exist_ok=True)
    if os.name == "nt":
        import pult_setup
        return pult_setup.make_exe(folder / "claude.exe", pult_setup.base_pythonw(), {"__main__.py": script})
    p = folder / "claude"
    p.write_text("#!%s\n%s" % (sys.executable, script), encoding="utf-8")
    p.chmod(0o755)
    return p


# a claude that speaks the SDK's stream: answers control requests, and on a prompt sends a tool result with a 1 MB
# picture (in the message and again in tool_use_result, as Claude Code does — a 2 MB line) and the turn's result
BIG_LINE = r'''import json, os, sys
if "-v" in sys.argv:
    print("2.1.301")
    sys.exit(0)
if os.name == "nt":
    import msvcrt
    msvcrt.setmode(0, os.O_BINARY)
    msvcrt.setmode(1, os.O_BINARY)
def out(m):
    sys.stdout.buffer.write(json.dumps(m).encode() + b"\n")
    sys.stdout.flush()
for line in sys.stdin.buffer:
    m = json.loads(line)
    if m.get("type") == "control_request":
        out({"type": "control_response", "response": {"subtype": "success", "request_id": m["request_id"], "response": {}}})
    elif m.get("type") == "user":
        pic = "A" * (1024 * 1024)
        out({"type": "user", "uuid": "u1", "session_id": "s", "parent_tool_use_id": None,
             "message": {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "t1", "content": [
                 {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": pic}}]}]},
             "tool_use_result": {"type": "image", "file": {"base64": pic}}})
        out({"type": "result", "subtype": "success", "duration_ms": 1, "duration_api_ms": 1, "is_error": False,
             "num_turns": 1, "session_id": "s", "result": "ok"})
'''


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
        self.assertEqual(R.human_dur(40), "40 сек")
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

    def test_spoken(self):
        # words that came by voice: a marker for Claude, 🎤 for people; it lives alongside attachment markers
        body = R.spoken_body("сделай деплой")
        self.assertTrue(R.is_spoken(body) and body.endswith("]"), body)
        self.assertEqual(R.attachments(body), ("сделай деплой", []))
        self.assertEqual(R.prompt_text(body), "🎤 сделай деплой")
        both = body + "\n\n[Attachment from Telegram: /a/inbox/2026-10/5.jpg]"
        self.assertEqual(R.prompt_text(both), "🎤 сделай деплой 📎 снимок")
        self.assertFalse(R.is_spoken("plain"))

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
        # a subagent's own report (SubagentHandback): in both forms seen, the queue's and the transcript's
        hb = '<agent-message from="a4137">\n[Subagent hand-back] The text below is the final report of a subagent'
        self.assertEqual(R.task_notes(hb), [{"id": "a4137", "status": "completed", "what": ""}])
        self.assertEqual(R.task_notes("Another Claude session sent a message: " + hb)[0]["id"], "a4137")
        self.assertEqual(R.task_notes('Ответь на <agent-message from="x"> в логе'), [])
        self.assertEqual(R.bg_text([]), "")
        self.assertEqual(R.bg_text([{"id": "b1", "status": "running", "description": "Сборка"}]),
                         "⚙️ В фоне ещё идёт: «Сборка»")
        many = [{"id": str(i), "status": "running", "description": "з%d" % i} for i in range(5)]
        self.assertEqual(R.bg_text(many + [{"id": "x", "status": "completed", "description": "старая"}]),
                         "⚙️ В фоне ещё 5: «з0», «з1», «з2» и ещё 2")

    def test_entities_html(self):
        # a message as a button's callback brings it (offsets in UTF-16: the emoji takes two) back into its HTML
        text = "Копией 😀 <да> & ссылка\nкод"
        ents = [{"type": "bold", "offset": 0, "length": 6}, {"type": "italic", "offset": 0, "length": 6},
                {"type": "text_link", "offset": 17, "length": 6, "url": 'https://x.y/?a=1&b="2"'},
                {"type": "pre", "offset": 24, "length": 3, "language": "py"}, {"type": "url", "offset": 0, "length": 3},
                {"type": "bold", "offset": 3, "length": 0}]
        self.assertEqual(R.entities_html(text, ents),
                         '<b><i>Копией</i></b> 😀 &lt;да&gt; &amp; <a href="https://x.y/?a=1&amp;b=&quot;2&quot;">ссылка</a>'
                         '\n<pre><code class="language-py">код</code></pre>')
        self.assertEqual(R.entities_html("a 😀 b", [{"type": "code", "offset": 5, "length": 1}]), "a 😀 <code>b</code>")
        self.assertEqual(R.entities_html("x", None), "x")


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
    def test_children_of_an_ancestor(self):
        # asked from inside a session Pult started, the daemon's children include the asker's own claude: macOS
        # pgrep leaves out the asker's ancestors unless told otherwise (seen 2026-10-20 — `pult busy` saw nothing)
        self.assertIn(os.getpid(), pult_os.children(os.getppid()))

    @unittest.skipIf(os.name == "nt", "a drive letter on Windows: WindowsTest.test_project_folder")
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
        # Claude's line about its progress (thinkingDisplay "updates") is the "now" line too; plain thinking is not
        upd = json.dumps({"type": "assistant", "thinkingDisplay": "updates", "timestamp": time.strftime(
            "%Y-%m-%dT%H:%M:%S.000Z", time.gmtime(time.time() - 2)), "message": {"role": "assistant", "content": [
                {"type": "thinking", "thinking": "Смотрю журнал", "signature": "SIG"}]}}, ensure_ascii=False)
        with open(p, "a") as f:
            f.write(upd + "\n" + upd.replace('"thinkingDisplay": "updates", ', "").replace("Смотрю журнал", "private") + "\n")
        self.assertEqual(pultd.last_reply(str(p), time.time() - 20), "Смотрю журнал")
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
        h = json.loads(opts.settings)["hooks"]["Stop"][0]["hooks"][0]
        if os.name == "nt":                          # exec form: no shell to read an environment prefix
            self.assertEqual((h["command"], h["args"]), ("/x y/venv/bin/python", ["/x y/pult_hook.py", "--injected"]))
        else:
            self.assertEqual(h["command"], "PULT_INJECTED=1 '/x y/venv/bin/python' '/x y/pult_hook.py'")
        with mock.patch.object(pultd, "HOOK_PY", r"C:\Py\pythonw.exe"), mock.patch.object(pultd, "HOOK", r"C:\P\pult_hook.py"):
            h = pultd.injected_hooks(windows=True)["PermissionRequest"][0]["hooks"][0]
        self.assertEqual(list(h), ["type", "command", "args", "timeout"])
        self.assertEqual(h["args"], [r"C:\P\pult_hook.py", "--injected"])

    def test_injected_flag(self):
        # Windows: the injected hook says so with an argument (no shell for PULT_INJECTED=1); the global one is quiet
        with mock.patch.dict(os.environ, {"CLAUDE_CODE_ENTRYPOINT": "sdk-py", "PULT_DRIVEN": "1"}):
            os.environ.pop("PULT_INJECTED", None)
            with mock.patch.object(sys, "argv", ["pult_hook.py"]):
                self.assertFalse(pult_hook.wanted())
            with mock.patch.object(sys, "argv", ["pult_hook.py", "--injected"]):
                self.assertTrue(pult_hook.wanted())

    def test_pid_alive(self):
        # Windows: os.kill(pid, 0) ends the process — the check must only look
        p = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
        try:
            self.assertTrue(pultd.pid_alive(p.pid))
            self.assertIn(p.pid, pult_os.children(os.getpid()))
            time.sleep(0.3)
            self.assertIsNone(p.poll())                               # still running
        finally:
            p.kill()
            p.wait()
        self.assertFalse(pult_os.pid_alive(p.pid))
        self.assertTrue(pult_os.pid_alive(os.getpid()))
        self.assertTrue(pult_os.pid_alive("not a pid"))              # unknown is not "gone"

    def test_input_idle(self):
        v = pult_os.input_idle()
        if pult_os.KIND == "mac":
            self.assertIsInstance(v, float)
        if pult_os.KIND == "windows":                               # GetLastInputInfo: no program to run
            self.assertTrue(v is None or v >= 0)
            return
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
        self.assertNotIn("matcher", c["StopFailure"][0])            # an API error ended the turn (stage V)

    def test_make_exe(self):
        # a Windows program the way pip makes them: the launcher, "#!<python>", a zip with __main__.py right after
        import zipfile
        import pult_setup as S
        (TMP / "exe").mkdir(exist_ok=True)
        p = S.make_exe(TMP / "exe" / "x.exe", "C:/Py thon/pythonw.exe", {"__main__.py": "print(1)", "m.py": "x = 1"})
        data = p.read_bytes()
        self.assertTrue(data.startswith(b"MZ"))
        self.assertIn(b'#!"C:/Py thon/pythonw.exe"\nPK\x03\x04', data)          # quoted: the path has a space
        with zipfile.ZipFile(p) as z:
            self.assertEqual((z.read("__main__.py"), z.read("m.py")), (b"print(1)", b"x = 1"))
        S.make_exe(p, "C:/Py/pythonw.exe", {"__main__.py": "print(2)"})          # made again over the same file
        with zipfile.ZipFile(p) as z:
            self.assertEqual(z.read("__main__.py"), b"print(2)")
        self.assertEqual(sorted(x.name for x in p.parent.iterdir()), ["x.exe"])

    def test_hooks_config_exec_form(self):
        # Windows: exec form — the program and its arguments, no shell
        c = pult_hook.hooks_config("C:/Py/pythonw.exe", ["C:/P/pult_hook.py"])
        h = c["PermissionRequest"][0]["hooks"][0]
        self.assertEqual((h["command"], h["args"]), ("C:/Py/pythonw.exe", ["C:/P/pult_hook.py"]))
        self.assertNotIn("args", pult_hook.hooks_config("CMD")["Stop"][0]["hooks"][0])

    def test_hook_without_daemon(self):
        async def go():
            t = time.monotonic()
            out = await run_hook(ev("PermissionRequest", tool_name="Bash", tool_input={"command": "ls"}),
                                 extra_env={"PULT_SOCK": str(TMP / "нет.sock")})
            return out, time.monotonic() - t
        out, dt = asyncio.run(go())
        self.assertEqual(out, "")
        self.assertLess(dt, 3)

    def test_run_line_state(self):
        # pult run: a progress bar rewrites its line with \r — the last state counts; Windows ends a line with \r\n
        import pultctl
        self.assertEqual(pultctl.last_state("шаг 1\r".encode()), "шаг 1")
        self.assertEqual(pultctl.last_state(b"10%\r50%\r100%"), "100%")
        self.assertEqual(pultctl.last_state(b"10%\r100%\r\r"), "100%")
        # a console program on a Russian Windows writes cp866: read in the console's code page, UTF-8 still first
        self.assertEqual(pultctl.last_state("шаг 2\r".encode("cp866"), "cp866"), "шаг 2")
        self.assertEqual(pultctl.last_state("шаг 3".encode(), "cp866"), "шаг 3")
        self.assertEqual(pultctl.decode_out(b"\xff ok"), "\ufffd ok")
        self.assertEqual(pultctl.decode_out("█▌ 50 % — готово ✓".encode(), "cp866"), "█▌ 50 % — готово ✓")   # real UTF-8

    def test_ctl_strip(self):
        import pultctl
        hooks = {"PreToolUse": [{"matcher": "Bash", "hooks": [{"type": "command", "command": "guard.sh"}]}],
                 "Stop": [{"hooks": [{"type": "command", "command": "python3 /x/pult_hook.py"}]}]}
        self.assertEqual(pultctl.strip_ours(hooks), {"PreToolUse": hooks["PreToolUse"]})


def intro_id(fake, data):
    """The message_id the fake gave a sendMessage call (ids go up by one per call, starting at 1001)."""
    return 1001 + next(i for i, (m, d) in enumerate(fake.calls) if d is data)


CLAUDE = "/x/native-binary/claude --output-format stream-json"
HEAVY = 'python3 heavy.py --name "it\'s"'


def fproc(ppid, cmd, cpu=0.0, mem=10 << 20, peak=None, cpu_time=1.0, ago=600):
    return {"ppid": ppid, "cmd": cmd, "cpu": cpu, "mem": mem, "peak": peak, "cpu_time": cpu_time,
            "started": time.time() - ago, "mine": True}


def fshell(ppid, cmd, **kw):
    # a command of Claude's, as Claude Code 2.1.301 starts it (tests/probe_load.py)
    return fproc(ppid, "/bin/zsh -c source /u/.claude/shell-snapshots/s.sh 2>/dev/null || true && " + L.quoted(cmd)
                 + " < /dev/null && pwd -P >| /tmp/claude-ab12-cwd", **kw)


def fprocs():
    """A session (claude 100) with a background command and its heavy child, a command of a turn, an MCP server
    that hardly does anything and a busy one; another session (claude 200) resting."""
    return {100: fproc(1, CLAUDE, cpu=4.0, mem=300 << 20, cpu_time=50.0, ago=7200),
            101: fshell(100, HEAVY, ago=900), 102: fproc(101, "python3 heavy.py", cpu=100.0, mem=1 << 30,
                                                     peak=3 << 29, cpu_time=600.0, ago=899),
            103: fproc(100, "node /opt/mcp/quiet.js"), 104: fproc(100, "node /secret/server.js --token abc", cpu=20.0),
            105: fshell(100, "ls -la", ago=1),
            200: fproc(1, CLAUDE, cpu=0.1, mem=150 << 20, ago=86400)}


class LinkTest(unittest.IsolatedAsyncioTestCase):
    """The daemon's link the Windows way — 127.0.0.1, a port, a key in the link file — on every system (PULT_LINK)."""

    async def test_tcp_link(self):
        import pult_tab
        path = str(TMP / "link-test.sock")
        got = []

        async def handle(reader, writer):
            got.append(await reader.readline())
            writer.write(b"ok\n")
            await writer.drain()
            writer.close()

        def sync(connect):
            sock = connect()
            try:
                sock.settimeout(5)
                sock.sendall(b'{"b": 1}\n')
                return sock.recv(16)
            finally:
                sock.close()
        with mock.patch.dict(os.environ, {"PULT_LINK": "tcp"}):
            server = await pultd.start_link(handle, path)
            try:
                link = json.loads(Path(path).read_text(encoding="utf-8"))
                self.assertEqual((sorted(link), link["pid"]), (["key", "pid", "port"], os.getpid()))
                if os.name != "nt":
                    self.assertEqual(os.stat(path).st_mode & 0o777, 0o600)
                r, w = await pultd.open_link(path)
                w.write(b'{"a": 1}\n')
                await w.drain()
                self.assertEqual(await asyncio.wait_for(r.readline(), 5), b"ok\n")
                w.close()
                # without the key: dropped before the handler sees a byte
                r, w = await asyncio.open_connection("127.0.0.1", link["port"])
                w.write(b'not-the-key\n{"a": 2}\n')
                await w.drain()
                self.assertEqual(await asyncio.wait_for(r.read(), 5), b"")
                w.close()
                # the blocking clients: pult_os (the pult command, install) and the hook's and the wrapper's own copies
                with mock.patch.object(pult_hook, "SOCK", path), mock.patch.object(pult_tab, "SOCK", path):
                    for name, connect in (("pult_os", lambda: pult_os.link_connect(path)),
                                          ("hook", pult_hook.connect), ("tab", pult_tab.connect)):
                        self.assertEqual(await asyncio.to_thread(sync, connect), b"ok\n", name)
                self.assertEqual(got, [b'{"a": 1}\n'] + [b'{"b": 1}\n'] * 3)
            finally:
                server.close()
                await server.wait_closed()
        # a broken link file is "no daemon", not a crash
        Path(path).write_text("{}", encoding="utf-8")
        with mock.patch.dict(os.environ, {"PULT_LINK": "tcp"}):
            with self.assertRaises(ValueError):
                pult_os.link_connect(path)


@unittest.skipUnless(os.name == "nt", "Windows")
class WindowsTest(unittest.IsolatedAsyncioTestCase):
    """What only a real Windows shows: programs made from pip's launcher, pipes byte for byte, the job object that
    ends claude with its tab, the hook on pythonw, the system calls. The wrapper is started as the VS Code extension
    starts it: pipes and windowsHide (CREATE_NO_WINDOW)."""

    def setUp(self):
        import pult_setup
        self.S = pult_setup
        self.d = Path(tempfile.mkdtemp(prefix="win-", dir=str(TMP)))
        self.tab = pult_setup.make_exe(self.d / "pult-tab.exe", pult_setup.base_pythonw(), {
            "pult_tab.py": (HERE / "pult_tab.py").read_bytes(), "__main__.py": pult_setup.TAB_MAIN})
        self.env = dict(os.environ, PULT_TAB_CONF=str(self.d / "tab.json"), PULT_SOCK=str(self.d / "no.sock"),
                        PULT_TAB_LOG=str(self.d / "tab.log"))
        self.claude_dir = self.d / "anthropic.claude-code-2.1.301-win32-x64"

    def conf(self, proxy):
        """proxy — the wrapper stays in between (the folder and the version are listed); else it runs claude as is."""
        c = self.d / "tab.json"
        if proxy:
            c.write_text(json.dumps({"folders": [str(self.d)], "versions": ["2.1.301"]}), encoding="utf-8")
        else:
            c.unlink(missing_ok=True)

    def argv(self, claude):
        return [str(self.tab), str(claude), "--input-format", "stream-json", "--output-format", "stream-json"]

    def test_bytes_through(self):
        claude = fake_claude(self.claude_dir, ECHO)
        data = "".join('{"type":"user","n":%d,"t":"%s"}\n' % (i, "ж" * i) for i in range(200)).encode() \
            + b"a\r\nb\x1a c\n"                                     # no \n → \r\n, and ^Z is not an end
        for proxy in (False, True):
            self.conf(proxy)
            p = subprocess.run(self.argv(claude), input=data, capture_output=True, timeout=60, cwd=str(self.d),
                               env=self.env, creationflags=subprocess.CREATE_NO_WINDOW)
            self.assertEqual((p.stdout, p.returncode), (data, 3), "proxy" if proxy else "direct")

    def test_claude_ends_with_the_tab(self):
        # the extension closes a tab by killing the program it started — no signal on Windows; claude must go too
        pid_file = self.d / "claude.pid"
        claude = fake_claude(self.claude_dir, "import os, time\nopen(%r, 'w').write(str(os.getpid()))\n"
                                              "time.sleep(120)\n" % str(pid_file))
        for proxy in (False, True):
            self.conf(proxy)
            pid_file.unlink(missing_ok=True)
            p = subprocess.Popen(self.argv(claude), stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                 stderr=subprocess.PIPE, cwd=str(self.d), env=self.env,
                                 creationflags=subprocess.CREATE_NO_WINDOW)
            pid = None
            try:
                end = time.monotonic() + 30
                while not (pid_file.exists() and pid_file.read_text()) and time.monotonic() < end:
                    time.sleep(0.2)
                pid = int(pid_file.read_text())
                self.assertTrue(pult_os.pid_alive(pid))
                p.kill()
                p.wait(10)
                end = time.monotonic() + 10
                while pult_os.pid_alive(pid) and time.monotonic() < end:
                    time.sleep(0.2)
                self.assertFalse(pult_os.pid_alive(pid), "proxy" if proxy else "direct")
            finally:
                if pid and pult_os.pid_alive(pid):
                    pult_os.kill(pid)
                for f in (p.stdin, p.stdout, p.stderr):
                    f.close()

    async def test_hook_on_pythonw(self):
        # the hook runs on pythonw in exec form: stdin and stdout are pipes, no console; the answer comes back whole
        path = str(self.d / "h.sock")

        async def daemon(reader, writer):
            msg = json.loads(await reader.readline())
            writer.write((json.dumps({"output": {"got": msg["event"]["hook_event_name"], "ж": "ё"}},
                                     ensure_ascii=False) + "\n").encode())
            await writer.drain()
            writer.close()
        server = await pultd.start_link(daemon, path)
        try:
            env = dict(os.environ, CLAUDE_CODE_ENTRYPOINT="claude-vscode", PULT_SOCK=path)
            env.pop("PULT_DRIVEN", None)
            p = await asyncio.create_subprocess_exec(
                str(self.S.base_pythonw()), str(HERE / "pult_hook.py"), env=env, stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE, creationflags=subprocess.CREATE_NO_WINDOW)
            out, _ = await asyncio.wait_for(p.communicate(json.dumps(ev("PermissionRequest", tool_name="Bash"),
                                                                     ensure_ascii=False).encode()), 30)
            self.assertEqual((json.loads(out.decode()), p.returncode), ({"got": "PermissionRequest", "ж": "ё"}, 0))
        finally:
            server.close()
            await server.wait_closed()

    def test_system(self):
        self.assertTrue(pult_os.describe().startswith("Windows "))
        # the task's user is the account itself, even where USERDOMAIN says WORKGROUP (an ssh session)
        me = subprocess.run(["whoami"], capture_output=True, text=True).stdout.strip()
        self.assertEqual(pult_os.Schtasks.user().lower(), me.lower())
        self.assertIsInstance(pult_os.system_lang(), str)
        self.assertEqual(pult_os.win_procs()[os.getpid()][1].lower(), os.path.basename(sys.executable).lower())
        v = pult_os.win_idle()
        self.assertTrue(v is None or v >= 0)
        self.assertIn(pult_os.win_locked(), (None, True, False))
        self.assertIsInstance(pult_os.service_manager(), pult_os.Schtasks)
        self.assertEqual(R.under(r"c:/users/A/proj/x.py", "C:\\Users\\a\\proj"), "x.py")    # either slash, any case

    def test_project_folder(self):
        # ~/.claude/projects/C--Users-…: the drive first, then the folders; a lower-case drive letter too
        where = self.d / "Проект A" / "sub dir"
        where.mkdir(parents=True)
        path = str(where.resolve())
        self.assertEqual(pultd.decode_pkey(pultd.sanitize(path)), path)
        self.assertEqual(pultd.decode_pkey(pultd.sanitize(path[0].lower() + path[1:])), path)


class LoadTest(unittest.TestCase):
    def test_ps_rows(self):
        # macOS ps: a comma as the decimal mark (a locale), days in the elapsed time, minutes past 60 in the processor
        # time, a newline in the arguments written as \012; a line that isn't a process is skipped
        out = ("  100     1   501  12,5  2048 04-08:00:09 222:47.19 /x/claude --a\n"
               "  101   100   501   0.0   512    02:03   0:00.01 /bin/sh -c echo a\\012b\n  oops\n")
        rows = pult_os.ps_rows(out, 1e6, 501)
        self.assertEqual(sorted(rows), [100, 101])
        self.assertEqual((rows[100]["cpu"], rows[100]["mem"], rows[100]["mine"]), (12.5, 2048 * 1024, True))
        self.assertAlmostEqual(rows[100]["cpu_time"], 222 * 60 + 47.19)
        self.assertAlmostEqual(rows[100]["started"], 1e6 - (4 * 86400 + 8 * 3600 + 9))
        self.assertEqual(rows[101]["cmd"], "/bin/sh -c echo a\nb")
        self.assertEqual(pult_os.clock("1:02:03"), 3723)

    def test_session(self):
        procs = fprocs()
        kids = L.children(procs)
        s = L.session(procs, 100, kids, 8, [{"id": "b1", "type": "shell", "command": HEAVY}])
        self.assertEqual((s["cpu"], s["cores"], s["n"]), (round(124 / 8, 1), 1.2, 6))
        self.assertFalse(s["idle"])
        heavy, mcp, ls = s["cmds"]                        # the busiest first; the quiet MCP server is not listed
        self.assertEqual((heavy["text"], heavy["bg"], heavy["claude"], heavy["cpu"]), (HEAVY, "b1", True, 12.5))
        self.assertEqual(heavy["cpu_time"], 601)
        self.assertEqual((mcp["text"], mcp["claude"]), ("node server.js", False))     # no arguments: they may hold keys
        self.assertEqual((ls["text"], ls["bg"]), ("ls -la", None))
        self.assertTrue(L.session(procs, 200, kids, 8)["idle"])
        # the same command quoted another way is still found; a command that isn't running is not
        procs[106] = fshell(100, "echo   'all done'")
        self.assertEqual(L.find(procs, 100, L.children(procs), 'echo "all done"'), 106)
        self.assertIsNone(L.find(procs, 100, kids, "make all"))

    def test_task(self):
        procs = fprocs()
        kids = L.children(procs)
        b = {"id": "b1", "type": "shell", "description": "Тяжёлый расчёт", "command": HEAVY}
        x = L.task(procs, 100, kids, 8, b, seen=5.0)
        self.assertEqual((x["what"], x["cmd"], x["found"]), ("Тяжёлый расчёт", HEAVY, True))
        self.assertEqual(x["since"], procs[101]["started"])          # the process's own start, not when Pult saw it
        self.assertEqual((x["cpu"], x["cores"], x["mem"], x["peak"]), (12.5, 1.0, (10 << 20) + (1 << 30),
                                                                       (10 << 20) + (3 << 29)))
        self.assertEqual(x["cpu_time"], 601)
        self.assertFalse(L.task(procs, 100, kids, 8, dict(b, command="make all"))["found"])
        sub = L.task(procs, 100, kids, 8, {"id": "a1", "type": "subagent", "description": "Обзор кода"}, seen=5.0)
        self.assertEqual((sub["remote"], sub["since"], sub["what"]), (True, 5.0, "Обзор кода"))

    def test_claude_args(self):
        self.assertTrue(L.is_claude(CLAUDE))
        self.assertFalse(L.is_claude("/x/claude-code/node x"))
        self.assertEqual(L.session_arg(CLAUDE + " --resume=" + SID), SID)
        self.assertEqual(L.session_arg(CLAUDE + " --session-id " + SID + " --x"), SID)
        self.assertIsNone(L.session_arg(CLAUDE))
        self.assertIsNone(L.bash_command("/bin/sh -c eval 'x'"))     # eval, but not Claude's shell


class AttnTest(unittest.TestCase):
    """Whose move (pult_attn) and the model's reading of a result (pult_brief) — without the daemon."""

    class Store(dict):
        def put(self, k, v):
            self[k] = json.loads(json.dumps(v))

    def test_state(self):
        rec = {"seen": False, "you": True, "fail": None}
        self.assertEqual(A.state(["q"], True, [], rec), "ask")             # a question beats everything
        self.assertEqual(A.state([], True, [], rec), "work")
        self.assertEqual(A.state([], False, [{"id": "b"}], rec), "bg")     # Claude goes on by itself
        self.assertEqual(A.state([], False, [], rec), "you")
        self.assertEqual(A.state([], False, [], dict(rec, you=False)), "done")
        self.assertEqual(A.state([], False, [], dict(rec, fail="rate_limit")), "fail")
        self.assertEqual(A.state([], False, [{"id": "b"}], dict(rec, fail="rate_limit")), "fail")
        self.assertEqual(A.state([], False, [], dict(rec, seen=True)), "idle")
        self.assertEqual(A.state([], False, [], None), "idle")

    def test_outcomes(self):
        st = self.Store()
        a = A.Attn(st)
        r = a.finished("s1", "-p", 30, "Готово.", "Готово.", waits=True)
        self.assertEqual((r["you"], r["seen"], r["model"]), (True, False, False))
        self.assertIsNone(a.briefed("s1", r["ts"] - 1, {"line": "x", "you": False, "need": ""}, True))   # an older result
        a.briefed("s1", r["ts"], {"line": "Отчёт готов", "you": False, "need": ""}, True)
        self.assertEqual(A.state([], False, [], a.rec["s1"]), "done")
        a.briefed("s1", r["ts"], {"line": "Нужен выбор", "you": True, "need": "Выбери А или Б"}, True)
        self.assertEqual((a.rec["s1"]["need"], A.state([], False, [], a.rec["s1"])), ("Выбери А или Б", "you"))
        r2 = a.finished("s2", "-p", 10, "Жду ревью.", "Жду ревью.", waits=False)       # a background task runs
        a.briefed("s2", r2["ts"], {"line": "Жду ревью", "you": True, "need": "?"}, False)
        self.assertEqual((a.rec["s2"]["you"], a.rec["s2"]["need"]), (False, ""))
        self.assertTrue(a.seen("s1"))
        self.assertFalse(a.seen("s1"))                                               # once
        self.assertEqual(a.day_of("-p"), [2, 40])
        b = A.Attn(st)                                                                # a restart keeps it all
        self.assertTrue(b.rec["s1"]["seen"])
        self.assertEqual(b.day_of("-p"), [2, 40])
        b.finished("s3", "-p", 5, "", "", True, now=time.time() + A.KEEP + 10)       # three days later: old ones go
        self.assertEqual(set(b.rec), {"s3"})
        self.assertEqual([e[2] for e in b.log], ["s3"])                               # the log forgets the same way

    def test_log_and_replies(self):
        a = A.Attn(self.Store())
        r = a.finished("s1", "-p", 30, "", "Готово.", waits=True, now=1000)
        a.finished("s2", "-q", 10, "", "Отчёт.", waits=False, now=1010)
        a.briefed("s1", r["ts"], {"line": "Два варианта", "you": True, "need": "Выбери", "replies": ["А", "Б"]}, True)
        self.assertEqual(a.rec["s1"]["replies"], ["А", "Б"])
        self.assertEqual([(e[2], e[3], e[4]) for e in a.since(999)], [("s1", "Два варианта", True), ("s2", "Отчёт.", False)])
        self.assertEqual(a.since(1005), [a.log[1]])
        a.resume["s1"] = 2000
        a.finished("s1", "-p", 5, "", "Дальше.", waits=True, now=1020)               # a new outcome: the old plan is moot
        self.assertNotIn("s1", a.resume)

    def test_order(self):
        rows = [{"state": "idle", "ts": 5}, {"state": "work", "since": 9}, {"state": "you", "since": 7},
                {"state": "you", "since": 3}, {"state": "done", "ts": 8}, {"state": "fail", "since": 6}]
        self.assertEqual([(r["state"], r.get("since") or r.get("ts")) for r in A.sort_rows(rows)],
                         [("fail", 6), ("you", 3), ("you", 7), ("work", 9), ("done", 8), ("idle", 5)])
        self.assertTrue(A.resting({"state": "idle", "ts": time.time() - A.RECENT - 1}))
        self.assertFalse(A.resting({"state": "idle", "ts": time.time()}))
        self.assertFalse(A.resting({"state": "done", "ts": 0}))

    def test_brief_parse(self):
        res = types.SimpleNamespace(is_error=False, structured_output={"line": "  Готово:  всё  ", "you": False, "need": "x"})
        self.assertEqual(B.parse(res), {"line": "Готово: всё", "you": False, "need": "", "replies": []})
        res = types.SimpleNamespace(is_error=False, structured_output=None,
                                    result='Вот: {"line": "Нужен ключ", "you": true, "need": "pult stt"}')
        self.assertEqual(B.parse(res), {"line": "Нужен ключ", "you": True, "need": "pult stt", "replies": []})
        for bad in (None, types.SimpleNamespace(is_error=True), types.SimpleNamespace(is_error=False, structured_output={"line": "", "you": True}),
                    types.SimpleNamespace(is_error=False, structured_output={"line": "a", "you": "да"}, result="")):
            self.assertIsNone(B.parse(bad))
        self.assertLessEqual(len(B.parse(types.SimpleNamespace(is_error=False, structured_output={"line": "я" * 300, "you": False, "need": ""}))["line"]), B.KEEP_MAX)
        # a line a little over the asked length stays whole; a much longer one ends after a whole word
        line = "Проверка блокировки прошла: Пульт зовёт туда, где ты. Оба случая подтверждены вживую, факт записан в документ."
        self.assertEqual(B.parse(types.SimpleNamespace(is_error=False, structured_output={"line": line, "you": False, "need": ""}))["line"], line)
        self.assertEqual(B.clip("один два три четыре пять шесть", 20), "один два три четыре…")   # ends at a word: kept
        self.assertEqual(B.clip("один два три четыре пять", 17), "один два три…")                 # inside a word: back
        self.assertEqual(B.first_sentence("**Готово.** Отчёт `report.md` собран. Дальше…"), "Готово.")
        self.assertEqual(B.first_sentence("```\ncode\n```\nНет точки"), "Нет точки")
        req = B.request("сделай", "н" * 4000 + "КОНЕЦ" + "к" * 4000, ["Сборка"])
        self.assertNotIn("КОНЕЦ", req)                                  # a long message: its start and its end
        self.assertIn("…", req)
        self.assertTrue(req.rstrip().endswith("</background_tasks_running>"))
        self.assertLess(len(req), B.REPLY_MAX + 1000)
        res = types.SimpleNamespace(is_error=False, structured_output={"line": "Два варианта", "you": True, "need": "Выбери",
                                    "replies": ["А — в памяти", "А — в памяти", "  ", "Б — " + "в" * 80, "В", "Г"]})
        self.assertEqual(B.parse(res)["replies"], ["А — в памяти", "Б — " + "в" * 35 + "…", "В"])   # clipped, no repeats, three
        res.structured_output["you"] = False
        self.assertEqual(B.parse(res)["replies"], [])                     # only when Claude waits for the owner
        o = B.options("ru", TMP)
        self.assertEqual((o.model, o.tools, o.setting_sources), ("haiku", [], []))
        self.assertIn("Russian", o.system_prompt)
        self.assertIn("no-session-persistence", o.extra_args)


class SttTest(unittest.IsolatedAsyncioTestCase):
    """pult_stt: the Groq client on a fake transport — the request, the words, the errors, the proxy fallback."""

    @staticmethod
    def handler(status=200, body=None, raise_=None):
        seen = []

        def h(req):
            seen.append(req)
            if raise_:
                raise raise_
            return httpx.Response(status, json=body if body is not None else {"text": "  сделай   деплой "})
        return seen, httpx.MockTransport(h)

    async def test_transcribe(self):
        seen, tr = self.handler()
        stt = STT.Stt("gsk_test_key_0123456789", transport=tr)
        text = await stt.transcribe(b"OggS" + b"\0" * 50, "audio/ogg", language="ru", prompt="Пульт, деплой.")
        self.assertEqual(text, "сделай деплой")
        req = seen[0]
        self.assertEqual((req.method, str(req.url)), ("POST", STT.BASE + "audio/transcriptions"))
        self.assertEqual(req.headers["authorization"], "Bearer gsk_test_key_0123456789")
        for part in (b'name="model"\r\n\r\n' + STT.MODEL.encode(), b'name="language"\r\n\r\nru',
                     "Пульт, деплой.".encode(), b'filename="voice.ogg"', b"OggS"):
            self.assertIn(part, req.content)
        # the MIME types the app and Telegram report → the container name Groq understands
        self.assertEqual([STT.ext_of(x) for x in ("audio/webm;codecs=opus", "audio/mp4", "voice/file_3.oga", "audio/ogg",
                                                  "x.mp3", "text/plain", None)],
                         ["webm", "m4a", "ogg", "ogg", "mp3", None, None])

    async def test_errors(self):
        async def err(**kw):
            _, tr = self.handler(**kw)
            with self.assertRaises(STT.SttError) as cm:
                await STT.Stt("k" * 24, transport=tr).transcribe(b"x" * 10, "audio/webm")
            return cm.exception
        self.assertEqual((await err(status=401, body={"error": {"message": "Invalid API Key"}})).key, "stt.e.key")
        self.assertEqual((await err(status=429, body={})).key, "stt.e.limit")
        self.assertEqual((await err(status=413, body={})).key, "stt.e.big")
        e = await err(status=400, body={"error": {"message": "file too short"}})
        self.assertEqual((e.key, e.kw), ("stt.e.groq", {"msg": "file too short"}))
        e = await err(raise_=httpx.ConnectError("boom"))
        self.assertEqual((e.key, e.kw), ("stt.e.net", {"why": "ConnectError"}))
        with self.assertRaises(STT.SttError) as cm:
            await STT.Stt("k" * 24, transport=self.handler()[1]).transcribe(b"x", "text/plain")
        self.assertEqual(cm.exception.key, "stt.e.format")
        with self.assertRaises(STT.SttError) as cm:
            await STT.Stt("k" * 24, transport=self.handler()[1]).transcribe(b"x" * (STT.MAX_BYTES + 1), "audio/ogg")
        self.assertEqual(cm.exception.key, "stt.e.big")
        for k in ("stt.e.key", "stt.e.limit", "stt.e.big", "stt.e.groq", "stt.e.net", "stt.e.format"):
            self.assertIn(k, I.S)                                   # every reason has words in both languages

    async def test_proxy_fallback(self):
        # the proxy route fails → the direct one answers and stays the first choice afterwards
        _, dead = self.handler(raise_=httpx.ProxyError("no proxy"))
        seen, alive = self.handler(status=200, body={"data": []})
        stt = STT.Stt("k" * 24, transport=[dead, alive])
        await stt.check()
        self.assertEqual((stt.cur, len(seen)), (1, 1))
        await stt.check()
        self.assertEqual(len(seen), 2)


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
        self.server = await pultd.start_link(self.p.handle_conn, os.environ["PULT_SOCK"])
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
        # rechecked: only whoever holds the bot token can point it elsewhere — put back and told; a label in another
        # language is just fixed
        self.assertFalse(await self.p.setup_menu_button())
        self.fake.menu_button = dict(mb, web_app={"url": "https://evil.example/"})
        self.assertTrue(await self.p.setup_menu_button())
        self.assertEqual(self.fake.menu_button, mb)
        self.fake.menu_button = dict(mb, text="Pult")
        self.assertFalse(await self.p.setup_menu_button())
        self.assertEqual(self.fake.menu_button, mb)
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

    async def test_turn_started_before_pult(self):
        # Pult restarted mid-turn (or a tab was open before it): the first step it sees starts the turn, and the
        # start time comes from the owner's prompt in the transcript, not from that step
        Path(TP).parent.mkdir(parents=True, exist_ok=True)
        Path(TP).write_text(tline("user", "Долгая задача", ago=600) + "\n" + tline("assistant", "Читаю", ago=590) + "\n" +
                            json.dumps({"type": "user", "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime(time.time() - 300)),
                                        "message": {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "t1", "content": "ok"}]}}) + "\n")
        self.assertAlmostEqual(pultd.prompt_started(TP), time.time() - 600, delta=5)
        await run_hook(ev("SessionStart", source="startup"))
        await run_hook(ev("PostToolUse", tool_name="Read", tool_input={"file_path": "/Users/x/proj/a.md"}))
        await until(lambda: self.p.live[SID].turn and self.p.live[SID].turn.msg)
        self.assertAlmostEqual(self.p.live[SID].turn.started, time.time() - 600, delta=5)
        await until(lambda: any("работает 10 мин" in t for t in self.sent()))
        await run_hook(ev("Stop", last_assistant_message="ок"))

    async def test_run_started_before_pult(self):
        # the same mid-turn, in a turn Claude started itself (its background task reported back): the turn begins at
        # that report, the owner's work — at their own prompt; an origin marks what Claude Code wrote itself
        Path(TP).parent.mkdir(parents=True, exist_ok=True)
        auto = json.loads(tline("user", "<task-notification>\n<task-id>b1</task-id>\n</task-notification>", ago=120))
        auto["origin"] = {"kind": "task-notification"}
        Path(TP).write_text(tline("user", "Собери и проверь", ago=900) + "\n" + json.dumps(auto) + "\n")
        self.assertAlmostEqual(pultd.prompt_started(TP), time.time() - 120, delta=5)
        self.assertAlmostEqual(pultd.prompt_started(TP, owner=True), time.time() - 900, delta=5)
        await run_hook(ev("SessionStart", source="startup"))
        await run_hook(ev("PostToolUse", tool_name="Read", tool_input={"file_path": "/Users/x/proj/a.md"}))
        await until(lambda: self.p.live[SID].turn)
        self.assertAlmostEqual(self.p.live[SID].turn.started, time.time() - 120, delta=5)
        self.assertAlmostEqual(self.p.live_item(self.p.live[SID])["run"], time.time() - 900, delta=5)
        await run_hook(ev("Stop", last_assistant_message="ок"))

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
        env = plain_env(PULT_SOCK=sock or os.environ["PULT_SOCK"])            # pult.cmd gives -X utf8 to itself only
        p = await asyncio.create_subprocess_exec(sys.executable, *(["-X", "utf8"] if os.name == "nt" else []),
                                                 str(HERE / "pultctl.py"), "run", "--", *cmd, cwd=cwd,
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
        self.assertEqual(self.p.prefs(), {"vehi": True, "mode": "auto", "lang": None, "brief": False, "pager": None})
        self.p.env["PULT_FORCE_AWAY"] = "0"                                           # you are at the Mac
        self.assertFalse(await self.p.loud())
        self.assertTrue(await self.p.loud(driven=True))                     # auto: a session from Telegram — with sound
        res = await self.p.api_prefs(mode="phone", vehi="да", lang="xx", brief="да", evil=True)  # garbage is rejected
        self.assertEqual(res, {"vehi": True, "mode": "phone", "lang": None, "brief": False, "pager": None})
        self.assertTrue((await self.p.api_prefs(brief=True))["brief"])
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
        self.assertIn("<code>%s</code>" % str(pultd.LOG_FILE).replace(str(Path.home()) + os.sep, "~" + os.sep, 1),
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
        r, w = await pultd.open_link(os.environ["PULT_SOCK"])
        w.write(('{"op": "hello", "pid": 4343, "cwd": "/Users/x/proj", "sid": "%s", "version": "2.1.301"}\n'
                 '{"op": "ctx", "window": 200000, "max_out": 32000}\n' % SID).encode())
        await w.drain()
        await until(lambda: self.p.ctx.get(SID) == [200000, 32000])
        self.assertEqual(self.store.get("ctx")[SID], [200000, 32000])                   # survives a restart
        self.assertEqual((await self.p.api_session(SID))["ctx"], {"window": 200000, "max_out": 32000, "usable": 167000})
        w.close()
        # another session on the same model (the transcript's dated id) borrows the window before its own result
        SID2 = "22222222-3333-4444-5555-666666666666"
        self.p.set_ctx(SID, 200000, 32000, model="claude-opus-5-5")
        tp2 = str(Path(TP).parent / (SID2 + ".jsonl"))
        Path(tp2).write_text(json.dumps({"type": "assistant", "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime()),
                                         "message": {"id": "m1", "model": "claude-opus-5-5-20260301", "role": "assistant", "content": [],
                                                     "usage": {"input_tokens": 10, "output_tokens": 5}}}) + "\n")
        self.store.touch_session(SID2, PKEY, path="/Users/x/proj")
        self.p.live_of(SID2, PKEY).transcript = tp2
        self.assertEqual((await self.p.api_session(SID2))["ctx"]["window"], 200000)
        self.assertEqual(self.store.get("ctx_model"), {"claude-opus-5-5": [200000, 32000]})

    async def test_model_choice(self):
        # the model and effort for a session from Telegram: picked for a new task, switched live on a running one
        # (SDK set_model), kept for a resume; a VS Code tab keeps its own
        import claude_agent_sdk
        from types import SimpleNamespace
        with mock.patch.object(self.p, "drive", mock.AsyncMock()) as drive:
            self.store.set_topic(PKEY, str(TMP), "proj", 77)
            await self.p.api_new(PKEY, "Fix this", model="opus", effort="high")
            self.assertEqual((drive.call_args.kwargs["model"], drive.call_args.kwargs["effort"]), ("opus", "high"))
            with self.assertRaises(ValueError):
                await self.p.api_new(PKEY, "Fix this", model="opus; rm -rf", effort="high")
            with self.assertRaises(ValueError):
                await self.p.api_new(PKEY, "Fix this", effort="turbo")
        self.store.touch_session(SID, PKEY, path="/Users/x/proj", driven=True)
        self.p.live_of(SID, PKEY).transcript = TP
        Path(TP).parent.mkdir(parents=True, exist_ok=True)
        Path(TP).write_text("")
        control = mock.AsyncMock(return_value={})
        client = SimpleNamespace(set_model=mock.AsyncMock(), _query=SimpleNamespace(_send_control_request=control))
        self.p.driven[SID] = SimpleNamespace(busy=False, bg=set(), q=asyncio.Queue(), client=client, want_model=None,
                                             want_effort=None, task=SimpleNamespace(cancel=lambda: None))
        res = await self.p.api_model(SID, "sonnet")
        client.set_model.assert_awaited_once_with("sonnet")
        self.assertEqual((res["live"], res["choice"]), (True, {"model": "sonnet"}))
        self.assertEqual(self.store.get("choice")[SID], {"model": "sonnet"})
        info = await self.p.api_session(SID)
        self.assertEqual((info["choice"], info["switch"], info["switch_effort"]), ({"model": "sonnet"}, True, True))
        # the effort on its own: the model stays; live through apply_flag_settings (probe_effort.py)
        res = await self.p.api_model(SID, effort="low")
        control.assert_awaited_once_with({"subtype": "apply_flag_settings", "settings": {"effortLevel": "low"}})
        self.assertEqual((res["live"], res["choice"]), (True, {"model": "sonnet", "effort": "low"}))
        self.assertEqual(client.set_model.await_count, 1)
        with self.assertRaises(ValueError):
            await self.p.api_model(SID, effort="turbo")
        with self.assertRaises(ValueError):
            await self.p.api_model(SID)
        await self.p.api_model(SID, "")                                            # back to the settings' default
        client.set_model.assert_awaited_with(None)
        self.assertEqual(self.store.get("choice")[SID], {"effort": "low"})
        await self.p.api_model(SID, effort="")
        control.assert_awaited_with({"subtype": "apply_flag_settings", "settings": {"effortLevel": None}})
        self.assertNotIn(SID, self.store.get("choice"))
        # an SDK without control requests: the choice is kept for the next start, not switched live
        self.p.driven[SID].client = SimpleNamespace(set_model=mock.AsyncMock())
        self.assertFalse((await self.p.api_model(SID, effort="high"))["live"])
        self.assertEqual(self.store.get("choice")[SID], {"effort": "high"})
        self.p.set_choice(SID, "", "")
        # a VS Code tab with the wrapper: the wrapper gets the request (probe_model.py: it switches the tab)
        del self.p.driven[SID]
        r, w = await pultd.open_link(os.environ["PULT_SOCK"])
        w.write(('{"op": "hello", "pid": 4545, "cwd": "/Users/x/proj", "sid": "%s", "version": "2.1.301"}\n' % SID).encode())
        await w.drain()
        await until(lambda: self.p.tab_for(SID))
        info = await self.p.api_session(SID)
        self.assertEqual((info["switch"], info["switch_effort"]), (False, False))   # an old wrapper: no way to switch
        with self.assertRaises(ValueError):
            await self.p.api_model(SID, "haiku")
        w.close()
        await until(lambda: not self.p.tab_for(SID))
        # a 0.9.8 wrapper: the model, not the effort — and a refused effort isn't kept as the choice
        r, w = await pultd.open_link(os.environ["PULT_SOCK"])
        w.write(('{"op": "hello", "pid": 4546, "cwd": "/Users/x/proj", "sid": "%s", "version": "2.1.301", "caps": ["model", "ctx"]}\n' % SID).encode())
        await w.drain()
        await until(lambda: self.p.tab_for(SID))
        res = await self.p.api_model(SID, "haiku")
        self.assertEqual(json.loads(await asyncio.wait_for(r.readline(), 3)), {"op": "model", "model": "haiku"})
        info = await self.p.api_session(SID)
        self.assertTrue(res["live"] and info["switch"])
        self.assertFalse(info["switch_effort"])
        with self.assertRaises(ValueError):
            await self.p.api_model(SID, effort="max")
        self.assertEqual(self.store.get("choice")[SID], {"model": "haiku"})
        w.close()
        await until(lambda: not self.p.tab_for(SID))
        # a wrapper from 0.9.9: the effort goes as a control request for this process only
        r, w = await pultd.open_link(os.environ["PULT_SOCK"])
        w.write(('{"op": "hello", "pid": 4547, "cwd": "/Users/x/proj", "sid": "%s", "version": "2.1.301", "caps": ["model", "ctx", "control"]}\n' % SID).encode())
        await w.drain()
        await until(lambda: self.p.tab_for(SID))
        self.assertTrue((await self.p.api_session(SID))["switch_effort"])
        res = await self.p.api_model(SID, effort="max")
        self.assertEqual(json.loads(await asyncio.wait_for(r.readline(), 3)),
                         {"op": "control", "request": {"subtype": "apply_flag_settings", "settings": {"effortLevel": "max"}}})
        self.assertEqual((res["live"], res["choice"]), (True, {"model": "haiku", "effort": "max"}))
        w.close()
        # a resume starts with the choice; a fake SDK client so the process isn't really started
        class Fake:
            def __init__(self, options): self.options = options
            async def __aenter__(self): return self
            async def __aexit__(self, *a): pass
            async def receive_messages(self):
                return
                yield
        self.p.driven.pop(SID, None)
        self.p.set_choice(SID, "opus", "xhigh")
        old = claude_agent_sdk.ClaudeSDKClient
        claude_agent_sdk.ClaudeSDKClient = Fake
        try:
            d = pultd.Driven(self.p, SID, "/Users/x/proj", resume=SID, model="opus", effort="xhigh")
            o = d.options()
            self.assertEqual((o.model, o.effort, o.resume), ("opus", "xhigh", SID))
            d.task.cancel()
        finally:
            claude_agent_sdk.ClaudeSDKClient = old

    async def test_driven_big_line(self):
        # a picture Claude reads comes in the stream's line twice: one ~470 KB screenshot made a line over the SDK's
        # own 1 MB limit, and a session from the app crashed in its first turn (2026-10-21). Through the real SDK,
        # with a stand-in claude: a 2 MB line passes, and with the SDK's default the same line still cuts it off
        fake = str(fake_claude(TMP / "claude-big-line", BIG_LINE))

        class D(pultd.Driven):
            def options(self):
                o = super().options()
                o.cli_path = fake
                return o

        d = D(self.p, SID, str(TMP))
        d.q.put_nowait(("глянь", None))
        await until(lambda: d.result.is_set() and not d.asking, timeout=20)
        await asyncio.sleep(0.3)
        self.assertFalse(d.task.done())               # the turn ended with its result, the session is alive
        d.q.put_nowait(None)
        await asyncio.wait_for(d.task, 10)
        old, pultd.SDK_LINE_MAX = pultd.SDK_LINE_MAX, 1024 * 1024
        try:
            d = D(self.p, SID, str(TMP))
            d.q.put_nowait(("глянь", None))
            await asyncio.wait_for(d.task, 20)        # the old limit: the reader fails and the session ends
            # after a reader error the SDK ends the process but leaves its stdout pipe to the garbage collector:
            # collect while the loop still runs (in the daemon the collector does it in its own time)
            del d
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", ResourceWarning)
                gc.collect()
                await asyncio.sleep(0.1)
                gc.collect()
        finally:
            pultd.SDK_LINE_MAX = old

    async def test_new_session_before_transcript(self):
        # the app opens a new session at once, before Claude Code has written its file: an empty chat, not
        # "transcript not found" (2026-10-21); without a process of Pult's own a missing file is still an error
        from types import SimpleNamespace
        base = TMP / "claude-projects-fresh"
        (base / PKEY).mkdir(parents=True, exist_ok=True)
        SID2 = "22222222-3333-4444-5555-666666666666"
        self.store.touch_session(SID2, PKEY, path="/Users/x/proj", driven=True)
        old, pultd.CLAUDE_PROJECTS = pultd.CLAUDE_PROJECTS, base
        try:
            with self.assertRaises(ValueError):
                await self.p.api_session(SID2)
            self.p.live_of(SID2, PKEY).driven = True
            self.p.driven[SID2] = SimpleNamespace(busy=True, bg=set(), q=asyncio.Queue(), client=None,
                                                  task=SimpleNamespace(cancel=lambda: None))
            info = await self.p.api_session(SID2)
            self.assertEqual((info["sid"], info["page"]["items"], info["page"]["end"]), (SID2, [], None))
            # the file appears: the next read finds it
            (base / PKEY / (SID2 + ".jsonl")).write_text(json.dumps(
                {"type": "user", "message": {"role": "user", "content": "глянь"}, "timestamp": "2026-10-21T14:00:03.000Z"}) + "\n")
            info = await self.p.api_session(SID2)
            self.assertEqual([i.get("text") for i in info["page"]["items"]], ["глянь"])
        finally:
            pultd.CLAUDE_PROJECTS = old
            self.p.driven.pop(SID2, None)

    async def test_project_counts(self):
        # the app's project list: open sessions, working, waiting — from `claude agents`, Pult's own sessions and
        # live turns; active projects come first
        from types import SimpleNamespace
        base = TMP / "claude-projects-counts"
        for pkey in (PKEY, "-Users-x-other"):
            (base / pkey).mkdir(parents=True, exist_ok=True)
            (base / pkey / "a.jsonl").write_text("{}")
        fs = TMP / "fs-counts"
        for name in ("proj", "other"):
            (fs / name).mkdir(parents=True, exist_ok=True)            # the list keeps only folders that exist
        os.utime(base / "-Users-x-other" / "a.jsonl", (time.time() + 100, time.time() + 100))   # the most recent
        self.store.set_topic(PKEY, str(fs / "proj"), "proj", None)
        self.store.set_topic("-Users-x-other", str(fs / "other"), "other", None)
        SID2 = "22222222-3333-4444-5555-666666666666"
        self.store.touch_session(SID2, PKEY, path="/Users/x/proj", driven=True)
        self.p._agents = (time.monotonic() + 1e6, [{"sessionId": SID, "cwd": "/Users/x/proj", "status": "idle"}])
        self.p.driven[SID2] = SimpleNamespace(busy=True, bg=set(), q=asyncio.Queue(), path="/Users/x/proj", client=None,
                                              task=SimpleNamespace(cancel=lambda: None))
        lv = self.p.live_of(SID, PKEY)
        lv.pending["r1"] = SimpleNamespace(fut=asyncio.get_running_loop().create_future())
        old = pultd.CLAUDE_PROJECTS
        pultd.CLAUDE_PROJECTS = base
        try:
            rows = (await self.p.api_projects())["projects"]
        finally:
            pultd.CLAUDE_PROJECTS = old
        self.assertEqual([(r["pkey"], r["open"], r["work"], r["ask"]) for r in rows],
                         [(PKEY, 2, 1, 1), ("-Users-x-other", 0, 0, 0)])            # active first, despite recency

    async def test_voice_message(self):
        # a voice message in a project topic: downloaded, recognized, and on it goes as typed text would — with the
        # voice marker for Claude; nothing heard, no key, too big — one line back and nothing starts
        class FakeStt:
            def __init__(self):
                self.calls, self.text = [], "сделай деплой"

            async def transcribe(self, blob, kind, language=None, prompt=None):
                self.calls.append((blob, kind, language, prompt))
                return self.text
        self.p.stt = stt = FakeStt()
        self.store.set_topic(PKEY, "/Users/x/proj", "proj", 77)
        base = {"from": {"id": OWNER}, "chat": {"id": CHAT}, "message_thread_id": 77, "is_topic_message": True}
        voice = {"voice": {"file_id": "AwAC", "duration": 4, "mime_type": "audio/ogg", "file_size": 44}}
        with mock.patch.object(self.p, "drive", mock.AsyncMock()) as drive:
            await self.p.on_message(dict(base, message_id=21, text="/new"))     # bare /new: the next message starts a session
            await self.p.on_message(dict(base, message_id=22, **voice))
            drive.assert_called_once()
            body = drive.call_args.args[2]
        self.assertTrue(body.startswith("сделай деплой\n\n[Spoken message"), body)
        self.assertEqual(R.prompt_text(body), "🎤 сделай деплой")
        blob, kind, language, prompt = stt.calls[0]
        self.assertEqual((blob[:4], kind, language), (b"OggS", "audio/ogg", "ru"))
        self.assertIn("proj", prompt)                           # the project names help Whisper spell them
        self.assertIn("Пульт", prompt)
        self.assertEqual(self.fake.of("getFile")[0]["file_id"], "AwAC")
        stt.text = ""
        with mock.patch.object(self.p, "drive", mock.AsyncMock()) as drive:
            await self.p.on_message(dict(base, message_id=23, **voice))
            drive.assert_not_called()
        self.assertEqual(self.texts()[-1], I.T("stt.empty", "ru"))
        self.assertEqual(json.loads(self.fake.of("sendMessage")[-1]["reply_parameters"])["message_id"], 23)
        self.p.stt = None
        await self.p.on_message(dict(base, message_id=24, **voice))
        self.assertIn("Голосовой ввод выключен", self.texts()[-1])
        self.p.stt = stt
        await self.p.on_message(dict(base, message_id=25, voice=dict(voice["voice"], file_size=30 * 1024 * 1024)))
        self.assertIn("слишком большая", self.texts()[-1])
        self.assertEqual(len(self.fake.of("getFile")), 2)       # no key, too big — nothing was downloaded

    async def test_api_stt(self):
        # a recording from the app → words; nothing heard, junk, no key — an error in words
        import base64

        class FakeStt:
            async def transcribe(self, blob, kind, language=None, prompt=None):
                return "привет мир" if blob.startswith(b"\x1aE\xdf\xa3") else ""
        self.p.stt = FakeStt()
        webm = base64.b64encode(b"\x1aE\xdf\xa3" + b"\0" * 30).decode()
        self.assertEqual(await self.p.api_stt(webm, "audio/webm;codecs=opus"), {"text": "привет мир"})
        with self.assertRaises(ValueError) as cm:
            await self.p.api_stt(base64.b64encode(b"\0" * 30).decode(), "audio/webm")
        self.assertEqual(str(cm.exception), I.T("stt.empty", "ru"))
        with self.assertRaises(ValueError):
            await self.p.api_stt("%%%", "audio/webm")
        self.p.stt = None
        with self.assertRaises(ValueError) as cm:
            await self.p.api_stt(webm, "audio/webm")
        self.assertIn("pult stt", str(cm.exception))
        self.assertEqual(self.p.stt_state(), {"on": False, "lang": "ru"})
        # the app shows the microphone only when there is a key: the flag rides with the projects (and the session)
        with mock.patch.object(self.p, "list_projects", lambda known: []):
            self.assertEqual(await self.p.api_projects(), {"projects": [], "stt": False})
            self.p.stt = FakeStt()
            self.assertTrue((await self.p.api_projects())["stt"])

    async def test_api_stt_key(self):
        # the key from the app's settings: checked with Groq, written to the settings file (600), in force at once;
        # "" removes it; a key written by `pult stt` while the daemon runs is noticed by the file's time
        env = Path(os.environ["PULT_ENV"])
        env.write_text("PULT_BOT_TOKEN=T\n")
        good = "gsk_" + "a" * 40
        with mock.patch.object(STT.Stt, "check", mock.AsyncMock()) as check:
            self.assertEqual(await self.p.api_stt_key(good), {"on": True})
        check.assert_awaited_once()
        self.assertIn("PULT_STT_KEY=" + good, env.read_text())
        self.assertIn("PULT_BOT_TOKEN=T", env.read_text())
        if os.name != "nt":                                           # Windows: the user's own folder keeps it private
            self.assertEqual(env.stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.p.stt.key, good)
        with mock.patch.object(STT.Stt, "check", mock.AsyncMock(side_effect=STT.SttError("stt.e.key"))):
            with self.assertRaises(ValueError) as cm:
                await self.p.api_stt_key("gsk_" + "b" * 40)
        self.assertEqual(str(cm.exception), I.T("stt.e.key", "ru"))
        self.assertIn("PULT_STT_KEY=" + good, env.read_text())          # the old key stays
        with self.assertRaises(ValueError):
            await self.p.api_stt_key("short")
        self.assertEqual(await self.p.api_stt_key(""), {"on": False})
        self.assertNotIn("PULT_STT_KEY", env.read_text())
        self.assertIsNone(self.p.stt)
        env.write_text("PULT_BOT_TOKEN=T\nPULT_STT_KEY=gsk_%s\nPULT_STT_LANG=auto\n" % ("c" * 40))
        os.utime(env, (time.time() + 5, time.time() + 5))               # the time surely differs
        self.assertEqual(self.p.stt_state(), {"on": True, "lang": "auto"})
        self.assertEqual(self.p.stt.key, "gsk_" + "c" * 40)
        env.unlink()
        self.p.stt_state()                                              # gone again — off, no error
        self.assertIsNone(self.p.stt)

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
        dr = self.p.driven[SID] = SimpleNamespace(q=q, busy=False, asking=False, bg=set(), client=None,
                                                  task=SimpleNamespace(cancel=lambda: None))
        dr.say = types.MethodType(pultd.Driven.say, dr)
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
        dr = self.p.driven[SID] = SimpleNamespace(
            busy=True, asking=False, sid=SID, d=self.p, bg=set(), q=asyncio.Queue(), task=SimpleNamespace(cancel=lambda: None),
            client=SimpleNamespace(interrupt=mock.AsyncMock(side_effect=lambda: stopped.append(1))))
        dr.say, dr.stop = types.MethodType(pultd.Driven.say, dr), types.MethodType(pultd.Driven.stop, dr)
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
        await until(lambda: SID in self.p.live and self.p.live[SID].turn)
        run0 = self.p.live[SID].run                                 # the owner's prompt sets the work going
        self.assertEqual(run0, self.p.live[SID].turn.started)
        await run_hook(ev("PostToolUse", tool_name="Bash", tool_input={"command": "make", "run_in_background": True}))
        await run_hook(ev("Stop", last_assistant_message="Запустил сборку",
                          background_tasks=[{"id": "b7", "type": "shell", "status": "running",
                                             "description": "Сборка проекта", "command": "make"}]))
        await until(lambda: any(t.startswith("✅") for t in self.texts()))
        res = next(t for t in self.texts() if t.startswith("✅"))
        self.assertIn("\n⚙️ В фоне ещё идёт: «Сборка проекта»\n", res)
        ov = await self.p.api_overview()
        self.assertEqual([s["bg"] for s in ov["live"]], [["Сборка проекта"]])  # in "Running" — with the background task
        self.assertEqual(ov["live"][0]["bg_since"], self.p.live[SID].bg_seen["b7"])  # "background 3 min" counts from here
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
        # Claude's own turn goes on with the owner's work: "working N" counts from their prompt, not from this turn
        self.assertGreater(self.p.live[SID].turn.started, run0)
        self.assertEqual(self.p.live_item(self.p.live[SID])["run"], run0)
        ov = await self.p.api_overview()
        self.assertEqual([(r["state"], r["since"]) for r in ov["board"][0]["rows"]], [("work", run0)])
        await run_hook(ev("Stop", last_assistant_message="Сборка прошла", background_tasks=[]))
        await until(lambda: any(t.startswith("✅") and "Сборка прошла" in t for t in self.texts()))
        self.assertNotIn("В фоне", self.texts()[-1])
        self.assertNotIn("task-notification", self.p.live[SID].title or "")
        # a subagent hands its report back itself: also Claude's own turn, not "You: Another Claude session…"
        await run_hook(ev("UserPromptSubmit", prompt="Позови ревьюера"))
        # the hook may be done before the daemon has read it (Windows, over TCP): wait for the turn it starts
        await until(lambda: self.p.live[SID].turn and self.p.live[SID].turn.prompt == "Позови ревьюера")
        run1 = self.p.live[SID].run
        self.assertGreater(run1, run0)                              # a new prompt of the owner — a new run
        await run_hook(ev("Stop", last_assistant_message="Ревьюер смотрит", background_tasks=[
            {"id": "a9", "type": "subagent", "status": "running", "description": "Ревью правки"}]))
        await until(lambda: any(t.startswith("✅") and "Ревьюер смотрит" in t for t in self.texts()))
        n = len(self.texts())
        await run_hook(ev("UserPromptSubmit", prompt='Another Claude session sent a message: <agent-message from="a9">\n'
                                                     "[Subagent hand-back] The text below is the final report"))
        await until(lambda: len(self.texts()) > n)
        self.assertIn("<i>⚙️ Закончилась фоновая задача «Ревью правки»</i>", self.texts()[n])
        self.assertNotIn("agent-message", "".join(self.sent()))
        self.assertEqual((self.p.live[SID].bg, self.p.live[SID].run), ([], run1))

    async def test_whose_move(self):
        # stage V: a turn typed here ends while the owner is away → "Your move" with the result's first sentence;
        # opening the session puts it to rest; at the computer it is seen at once; a background task — Claude's
        # move; an API error — a failure; "Got it"; the model's line (when allowed) can say "only a report"
        self.p._procs = (time.monotonic() + 1e6, None)
        Path(TP).parent.mkdir(parents=True, exist_ok=True)
        Path(TP).write_text(tline("user", "Сделай отчёт") + "\n" + tline("assistant", "Отчёт готов.") + "\n")
        await run_hook(ev("SessionStart", source="startup"))
        await run_hook(ev("UserPromptSubmit", prompt="Сделай отчёт"))
        await run_hook(ev("Stop", last_assistant_message="**Отчёт готов.** Какой формат дальше — PDF или таблица?"))
        await until(lambda: SID in self.p.attn.rec)
        ov = await self.p.api_overview()
        self.assertEqual([(r["sid"], r["state"], r["line"]) for r in ov["mine"]], [(SID, "you", "Отчёт готов.")])
        proj = ov["board"][0]
        self.assertEqual((proj["name"], proj["mine"], proj["rows"], proj["turns"]), ("proj", 1, [], 1))
        await self.p.api_session(SID)                                                # opened in the app → seen
        ov = await self.p.api_overview()
        self.assertEqual(ov["mine"], [])
        self.assertEqual([(r["state"], r["line"]) for r in ov["board"][0]["rows"]], [("idle", "Отчёт готов.")])
        # at the computer: the owner watched the turn end
        self.p.env["PULT_FORCE_AWAY"] = "0"
        await run_hook(ev("UserPromptSubmit", prompt="Ещё раз"))
        await run_hook(ev("Stop", last_assistant_message="Сделано."))
        await until(lambda: self.p.attn.day_of(PKEY)[0] == 2)
        self.assertEqual((await self.p.api_overview())["mine"], [])
        self.p.env["PULT_FORCE_AWAY"] = "1"
        # a background task still runs: Claude goes on by itself
        await run_hook(ev("UserPromptSubmit", prompt="Собери в фоне"))
        await run_hook(ev("Stop", last_assistant_message="Запустил сборку.", background_tasks=[
            {"id": "b1", "type": "shell", "status": "running", "description": "Сборка", "command": "make"}]))
        await until(lambda: self.p.attn.day_of(PKEY)[0] == 3)
        ov = await self.p.api_overview()
        self.assertEqual(ov["mine"], [])
        self.assertEqual([(r["state"], r["bg"], r["since"]) for r in ov["board"][0]["rows"]],
                         [("bg", ["Сборка"], self.p.live[SID].bg_seen["b1"])])    # the chip's time: since the task was seen
        # an API error ends the turn: a failure, in Telegram too
        await run_hook(ev("UserPromptSubmit", prompt="Дальше"))
        await run_hook(ev("StopFailure", error="rate_limit", last_assistant_message="Usage limit reached"))
        await until(lambda: any(t.startswith("⚠️ <b>proj</b> · упёрся в лимит подписки") for t in self.texts()))
        await until(lambda: any("⚠️ <b>proj</b> · оборвался через" in t for t in self.texts("editMessageText")))
        ov = await self.p.api_overview()
        self.assertEqual([(r["state"], r["line"]) for r in ov["mine"]], [("fail", "упёрся в лимит подписки")])
        self.assertEqual(self.p.fail_text("weird_new"), "оборвался: weird_new")
        await self.p.api_seen(SID)                                                   # "Got it"
        self.assertEqual((await self.p.api_overview())["mine"], [])
        # the model's line, when allowed: "only a report" is not the owner's move
        await self.p.api_prefs(brief=True)
        asked = []

        async def fake_brief(prompt, reply, bg, lang, cwd):
            asked.append((prompt, lang))
            return {"line": "Отчёт собран, всё зелёное", "you": False, "need": ""}
        with mock.patch.object(pultd.B, "brief", fake_brief):
            await run_hook(ev("UserPromptSubmit", prompt="Проверь"))
            await run_hook(ev("Stop", last_assistant_message="Проверил: все тесты зелёные, можно выкладывать?",
                              background_tasks=[]))                                  # the build is over
            await until(lambda: self.p.attn.rec[SID].get("model"))
        self.assertEqual(asked, [("Проверь", "ru")])
        ov = await self.p.api_overview()
        self.assertEqual(ov["mine"], [])
        self.assertEqual([(r["state"], r["line"], r["model"]) for r in ov["board"][0]["rows"]],
                         [("done", "Отчёт собран, всё зелёное", True)])

    async def test_away(self):
        # away from the computer: a locked screen at once; where the lock can be read, 5 min without input (watching
        # Claude work is still "here"), else 2 min; without input data — the owner's last action in a session
        self.p.env.pop("PULT_FORCE_AWAY", None)
        cases = [(True, 10, True), (False, 200, False), (False, 400, True), (None, 200, True), (None, 60, False)]
        for locked, idle, away in cases:
            self.p._locked, self.p._idle = (time.monotonic(), locked), (time.monotonic(), idle)
            self.assertEqual(await self.p.away(), away, (locked, idle))
        self.p._locked, self.p._idle = (time.monotonic(), False), (time.monotonic(), 400)
        self.assertEqual(await self.p.where(), "away")
        await self.p.api_presence(True)
        self.assertEqual(await self.p.where(), "app")                                 # the app is on the screen
        await self.p.api_presence(False)
        self.assertEqual(await self.p.where(), "away")
        await self.p.api_presence(True)                                               # then silence: off after APP_ON
        self.p.app_on -= pultd.APP_ON + 1
        await self.p.presence_check()
        self.assertFalse(self.p.app_vis)

    async def test_project_and_outcome(self):
        # the project's screen: what waits for the owner, what runs, today's outcomes; the session shows its outcome
        # as it was found (red), and a second look finds it seen; "Got it" from a card; ready replies kept
        self.p._procs = (time.monotonic() + 1e6, None)
        Path(TP).parent.mkdir(parents=True, exist_ok=True)
        Path(TP).write_text(tline("user", "Сделай кэш") + "\n" + tline("assistant", "Два варианта. Какой?") + "\n")
        await self.p.api_prefs(brief=True)

        async def fake_brief(prompt, reply, bg, lang, cwd):
            return {"line": "Два варианта кэша", "you": True, "need": "Выбери А или Б", "replies": ["А", "Б"]}
        with mock.patch.object(pultd.B, "brief", fake_brief):
            await run_hook(ev("UserPromptSubmit", prompt="Сделай кэш"))
            await run_hook(ev("Stop", last_assistant_message="Два варианта. Какой?", background_tasks=[]))
            await until(lambda: self.p.attn.rec.get(SID, {}).get("model"))
        d = await self.p.api_project(PKEY)
        self.assertEqual([(r["sid"], r["state"], r["replies"]) for r in d["mine"]], [(SID, "you", ["А", "Б"])])
        self.assertEqual((d["name"], d["live"], d["turns"]), ("proj", [], 1))
        with self.assertRaises(ValueError):
            await self.p.api_project("-nowhere-at-all")
        info = await self.p.api_session(SID)
        self.assertEqual((info["outcome"]["state"], info["outcome"]["need"], info["outcome"]["replies"]), ("you", "Выбери А или Б", ["А", "Б"]))
        # opened, yet the decision is still the owner's: it stays "your move" until they answer or press "Got it"
        self.assertEqual((await self.p.api_session(SID))["outcome"]["state"], "you")
        self.assertEqual([r["sid"] for r in (await self.p.api_project(PKEY))["mine"]], [SID])
        await self.p.api_seen(SID)
        self.assertEqual((await self.p.api_session(SID))["outcome"]["state"], "idle")
        d = await self.p.api_project(PKEY)
        self.assertEqual(([r["sid"] for r in d["today"]], d["mine"]), ([SID], []))
        with mock.patch.object(self.p, "list_projects", lambda known: [(time.time(), PKEY, "/Users/x/proj")]):
            rows = (await self.p.api_projects())["projects"]
        self.assertEqual([(r["pkey"], r["line"], r["mine"], r["turns"]) for r in rows], [(PKEY, "Два варианта кэша", 0, 1)])

    async def test_pager(self):
        # Telegram as a pager (stage V, Q22 «а», on where the app is set up): no turn or result messages for work
        # the owner drives from the app or the computer; a "your move" they can't see is paged once — line, need,
        # ready replies, the way into the app; a reply button sends into the session and folds the call; seen in
        # the app — folded too; at the computer or in the app — nothing; a dialog in a topic — one message per turn
        self.p.env.update(PULT_APP_LINK="https://t.me/b/pult", PULT_RELAY_URL="wss://h.example/pult/agent")
        self.p._procs = (time.monotonic() + 1e6, None)
        self.assertTrue(self.p.pager())
        Path(TP).parent.mkdir(parents=True, exist_ok=True)
        Path(TP).write_text(tline("user", "Сделай кэш") + "\n")
        await self.p.api_prefs(brief=True)

        async def fake_brief(prompt, reply, bg, lang, cwd):
            return {"line": "Два варианта кэша", "you": True, "need": "Выбери А или Б", "replies": ["А — память", "Б — SQLite"]}
        with mock.patch.object(pultd.B, "brief", fake_brief):
            await run_hook(ev("UserPromptSubmit", prompt="Сделай кэш"))
            await run_hook(ev("PostToolUse", tool_name="Read", tool_input={"file_path": "/Users/x/proj/a.py"}))
            await run_hook(ev("Stop", last_assistant_message="Два варианта. Какой?", background_tasks=[]))
            await until(lambda: self.p.attn.rec.get(SID, {}).get("model"))
        await asyncio.sleep(0.2)
        self.assertEqual([t for t in self.texts() if "Сделай кэш" in t or t.startswith("✅")], [])   # no turn, no result
        await self.p.page_due()
        page = self.fake.of("sendMessage")[-1]
        # the session's own title (its first prompt until it has a name) — the topic already says the project
        self.assertEqual(page["text"], "🔴 <b>Сделай кэш</b>\nДва варианта кэша\n<b>Выбери А или Б</b>")
        self.assertEqual(page["disable_notification"], "false")
        kb = json.loads(page["reply_markup"])["inline_keyboard"]
        self.assertEqual(kb[0], [{"text": "А — память", "callback_data": "r:%s:0" % SID}, {"text": "Б — SQLite", "callback_data": "r:%s:1" % SID}])
        self.assertIn("startapp=s_" + SID, json.dumps(kb))
        n = len(self.fake.of("sendMessage"))
        await self.p.page_due()
        self.assertEqual(len(self.fake.of("sendMessage")), n)                         # once
        sent = []

        async def fake_send(sid, text, fork=False, files=None):
            sent.append((sid, text))
            return {"ok": True, "how": "tab"}
        with mock.patch.object(self.p, "api_send", fake_send):
            await self.p.on_callback({"id": "c1", "from": {"id": OWNER}, "data": "r:%s:1" % SID})
        self.assertEqual(sent, [(SID, "Б — SQLite")])
        await until(lambda: any("→ «Б — SQLite»" in t for t in self.texts("editMessageText")))
        # the next outcome: seen in the app before the pager runs — no call; at the computer — no call either
        await run_hook(ev("UserPromptSubmit", prompt="Дальше"))
        await run_hook(ev("Stop", last_assistant_message="Готово, жду решения.", background_tasks=[]))
        await until(lambda: self.p.attn.rec[SID]["line"] == "Готово, жду решения.")
        self.p.attn.rec[SID]["model"] = True
        self.p.env["PULT_FORCE_AWAY"] = "0"
        await self.p.page_due()
        self.assertEqual(len(self.fake.of("sendMessage")), n)
        self.p.env["PULT_FORCE_AWAY"] = "1"
        await self.p.api_presence(True)
        await self.p.page_due()
        self.assertEqual(len(self.fake.of("sendMessage")), n)                         # in the app
        await self.p.api_presence(False)
        await self.p.page_due()
        self.assertEqual(len(self.fake.of("sendMessage")), n + 1)                     # away now — paged
        await self.p.api_seen(SID)
        await until(lambda: any(t.startswith("✓ <b>Сделай кэш</b> · Готово, жду решения.") for t in self.texts("editMessageText")))
        # a restart: outcomes from before it are not paged again in a burst
        self.p.attn.rec[SID].update(seen=False, paged=False)
        self.p.attn.rec[SID].pop("paged")
        self.p.attn.save()
        p2 = pultd.Pult(self.p.env, self.p.tg, self.store)
        self.assertTrue(p2.attn.rec[SID]["paged"])
        # a dialog in the topic: the owner's message → one message per turn (the turn's own message goes away)
        self.p.expect[SID] = 555
        await run_hook(ev("UserPromptSubmit", prompt="Как дела?"))
        # a call that was only seen is answered by the next prompt, from wherever it came — it says with what
        await until(lambda: "✓ <b>Сделай кэш</b> · Готово, жду решения.\n→ «Как дела?»" in self.texts("editMessageText"))
        replies_555 = lambda: [d for d in self.fake.of("sendMessage") if '"message_id": 555' in d.get("reply_parameters", "")]
        await until(lambda: replies_555())                                            # the turn's message, under theirs
        await run_hook(ev("Stop", last_assistant_message="Всё хорошо.", background_tasks=[]))
        await until(lambda: any(t.startswith("✅") and "Всё хорошо." in t for t in self.texts()))
        await until(lambda: self.fake.of("deleteMessage"))
        res = next(d for d in self.fake.of("sendMessage") if d["text"].startswith("✅"))
        self.assertEqual(json.loads(res["reply_parameters"])["message_id"], 555)
        self.assertEqual(self.fake.of("deleteMessage")[-1]["message_id"], str(intro_id(self.fake, replies_555()[0])))
        await self.p.page_due()
        self.assertFalse(any("Всё хорошо" in t and t.startswith("🔴") for t in self.texts()))   # the answer was the call

    async def test_pager_requests_and_limit(self):
        # as a pager, a permission request waits in the app while the owner is at the computer and is posted once
        # they leave; a turn broken off by the usage limit is paged with "continue at …", which schedules the
        # word "continue" for the reset and says it then
        self.p.env.update(PULT_APP_LINK="https://t.me/b/pult", PULT_RELAY_URL="wss://h.example/pult/agent",
                          PULT_FORCE_AWAY="0")
        self.p._procs = (time.monotonic() + 1e6, None)
        hook = await run_hook(ev("PermissionRequest", tool_name="Bash", tool_input={"command": "make deploy"}), wait=False)
        await until(lambda: self.p.req_by_rid)
        await asyncio.sleep(0.2)
        self.assertFalse(any("make deploy" in t for t in self.texts()))
        self.p.env["PULT_FORCE_AWAY"] = "1"
        await self.p.page_due()
        self.assertTrue(any("make deploy" in t for t in self.texts()))
        rid = next(iter(self.p.req_by_rid))
        await self.p.on_callback({"id": "c2", "from": {"id": OWNER}, "data": "p:%s:y" % rid})
        await hook.wait()
        reset = time.time() + 3600
        self.p._usage = {"limits": [{"kind": "session", "percent": 100, "resets_at": reset}], "ts": time.time()}
        await run_hook(ev("UserPromptSubmit", prompt="Дальше"))
        await run_hook(ev("StopFailure", error="rate_limit", last_assistant_message="Limit reached"))
        await until(lambda: (self.p.attn.rec.get(SID) or {}).get("fail") == "rate_limit")
        await self.p.page_due()
        page = self.fake.of("sendMessage")[-1]
        self.assertTrue(page["text"].startswith("⚠️ <b>Дальше</b>\nупёрся в лимит подписки"), page["text"])
        self.assertIn('"z:%s"' % SID, page["reply_markup"])
        await self.p.on_callback({"id": "c3", "from": {"id": OWNER}, "data": "z:" + SID})
        self.assertAlmostEqual(self.p.attn.resume[SID], reset + 60, delta=1)
        hm = time.strftime("%H:%M", time.localtime(self.p.attn.resume[SID]))
        await until(lambda: any(t.startswith("✓ <b>Дальше</b> · ") and t.endswith("\n→ Продолжу в " + hm)
                                for t in self.texts("editMessageText")))
        self.assertIsNone(self.p.attn.rec[SID]["page"])          # decided: "continue" later won't redo the call
        self.assertEqual((await self.p.api_overview())["usage_pct"], 100)
        sent = []

        async def fake_send(sid, text, fork=False, files=None):
            sent.append((sid, text))
            return {"ok": True, "how": "resume"}
        self.p.attn.resume[SID] = time.time() - 1
        with mock.patch.object(self.p, "api_send", fake_send):
            await self.p.resume_due()
        self.assertEqual(sent, [(SID, pultd.CONTINUE)])
        self.assertEqual(self.p.attn.resume, {})
        # the topic's pinned card shows who waits
        self.store.set_topic(PKEY, "/Users/x/proj", "proj", 77)
        self.p.attn.rec[SID]["seen"] = False
        await self.p.cards_status()
        await until(lambda: any(t.startswith("<b>🔴 ждут тебя: 1") for t in self.sent()))

    async def test_catchup(self):
        # "While you were away": the app comes back after an hour or more — the turns since, what is done, what waits
        self.p._procs = (time.monotonic() + 1e6, None)
        self.p.app_seen = time.time() - 2 * 3600
        self.p.attn.finished(SID, PKEY, 30, "", "Отчёт готов.", waits=False, now=time.time() - 3000)
        self.p.attn.finished("99999999-2222-3333-4444-555555555555", PKEY, 30, "", "Нужен выбор.", waits=True)
        self.assertIsNone((await self.p.api_overview())["catchup"])
        await self.p.api_presence(True)
        c = (await self.p.api_overview())["catchup"]
        self.assertEqual((c["turns"], c["projects"], c["done"], c["mine"]), (2, 1, 1, 1))
        self.assertEqual([(x["name"], x["line"], x["you"]) for x in c["lines"]], [("proj", "Нужен выбор.", True)])
        await self.p.api_presence(False)                                               # the visit is over
        self.assertIsNone((await self.p.api_overview())["catchup"])

    async def test_load_view(self):
        # the load view: the computer and each session with a claude process; a background task is found among the
        # processes by its command; `claude agents` first, then the hook's parent, then Pult's own children
        await run_hook(ev("UserPromptSubmit", prompt="Посчитай в фоне"))
        await run_hook(ev("Stop", last_assistant_message="Запустил", background_tasks=[
            {"id": "b1", "type": "shell", "status": "running", "description": "Тяжёлый расчёт", "command": HEAVY}]))
        other = "99999999-2222-3333-4444-555555555555"
        procs = fprocs()
        mac = {"cores": 8, "cpu": 40.0, "mem_total": 16 << 30, "mem_used": 8 << 30, "load": 3.04}
        self.p._procs = (time.monotonic() + 1e6, (procs, mac))
        self.p._agents = (time.monotonic() + 1e6, [{"sessionId": SID, "pid": 100, "cwd": "/Users/x/proj"},
                                                   {"sessionId": other, "pid": 200, "cwd": "/Users/x/other"}])
        ov = await self.p.api_overview()
        self.assertEqual(ov["load"]["claude"], {"n": 2, "cpu": round(124 / 8, 1) + round(0.1 / 8, 1),
                                                "mem": sum(d["mem"] for d in procs.values())})
        self.assertEqual((ov["load"]["cpu"], ov["load"]["load"]), (40.0, 3.0))
        d = await self.p.api_load()
        self.assertEqual([(r["sid"], r["state"], r["idle"]) for r in d["sessions"]], [(SID, "bg", False), (other, "idle", True)])
        self.assertEqual((d["sessions"][0]["title"], d["sessions"][1]["project"]), ("proj", "other"))
        d = await self.p.api_load(sid=SID)
        self.assertEqual(d["session"]["pid"], 100)
        self.assertEqual([(x["id"], x["found"], x["cpu"]) for x in d["tasks"]], [("b1", True, 12.5)])
        # `claude agents` missed them: the hook's parent (here — this test) and a claude Pult itself started
        self.p._agents = (time.monotonic() + 1e6, [])
        procs[os.getpid()] = fproc(1, CLAUDE, mem=1 << 20)
        three = "33333333-2222-3333-4444-555555555555"
        procs[300] = fproc(os.getpid(), CLAUDE + " --resume " + three)
        self.p.driven[three] = types.SimpleNamespace(path="/Users/x/three", busy=False, bg=set())
        try:
            d = await self.p.api_load()
        finally:
            self.p.driven.pop(three)
        self.assertEqual({r["sid"]: r["pid"] for r in d["sessions"]}, {SID: os.getpid(), three: 300})
        self.p._procs = (time.monotonic() + 1e6, None)                   # a system Pult can't read
        self.assertEqual(await self.p.api_load(), {"ok": False})
        self.assertIsNone((await self.p.api_overview())["load"])

    async def test_tab(self):
        # a VS Code tab with Pult's wrapper introduced itself and reported its session → replies from Telegram and
        # from the app go straight into it; the turn for that message replies to the owner's message
        self.store.touch_session(SID, PKEY, path="/Users/x/proj")
        self.store.set_topic(PKEY, "/Users/x/proj", "proj", 77)
        r, w = await pultd.open_link(os.environ["PULT_SOCK"])
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
            r, w = await pultd.open_link(os.environ["PULT_SOCK"])
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
        vs.write_text('{\n  // настройки\n  "claudeCode.claudeProcessWrapper": "/x/%s",\n}' % pultd.TAB_FILE)
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

    async def test_telegram_start_waits(self):
        # Telegram out of reach at start (after logging in to Windows the VPN comes up later, 2026-10-21): the bot's
        # menu, the panel, the version notice and reading updates wait until it first answers — not lost one by one
        fails = [httpx.ConnectError("no route"), httpx.ConnectTimeout("timeout")]

        def handler(req):
            if req.url.path.endswith("/getMe") and fails:
                raise fails.pop(0)
            return self.fake.handler(req)
        self.p.tg = pultd.Tg("T", transport=httpx.MockTransport(handler))
        started = []

        async def mark(name):
            started.append((name, len(self.fake.calls)))
        logged = []
        with mock.patch.object(pultd, "TG_REACH", (0.01, 0.02)), \
                mock.patch.object(pultd, "log", lambda *a: logged.append(" ".join(map(str, a)))), \
                mock.patch.object(self.p, "poll", lambda: mark("poll")), \
                mock.patch.object(self.p, "tab_version_watch", lambda: mark("version")), \
                mock.patch.object(self.p, "ensure_panel", lambda: mark("panel")), \
                mock.patch.object(self.p, "menu_watch", lambda: mark("menu")):
            await asyncio.wait_for(self.p.telegram_start(), 5)
        methods = [m for m, _ in self.fake.calls]
        self.assertEqual(methods[0], "getMe")                     # the first call that got through
        self.assertEqual(methods[1:3], ["setMyCommands", "setMyCommands"])
        self.assertEqual(sorted(n for n, _ in started), ["menu", "panel", "poll", "version"])
        self.assertTrue(all(at >= 3 for _, at in started))        # after the menu, not before Telegram answered
        self.assertEqual(len([x for x in logged if "out of reach" in x]), 1)   # said once, not on every try
        self.assertTrue(any("Telegram reachable after" in x for x in logged))
        # Telegram answers with an error (a revoked token): reachable — no endless waiting
        self.fake.calls.clear()
        self.p.tg = pultd.Tg("T", transport=httpx.MockTransport(
            lambda req: httpx.Response(401, json={"ok": False, "error_code": 401, "description": "Unauthorized"})))
        with mock.patch.object(self.p, "setup_commands", lambda: mark("commands")), \
                mock.patch.object(self.p, "poll", lambda: mark("poll2")), \
                mock.patch.object(self.p, "tab_version_watch", lambda: mark("version2")), \
                mock.patch.object(self.p, "ensure_panel", lambda: mark("panel2")), \
                mock.patch.object(self.p, "menu_watch", lambda: mark("menu2")):
            await asyncio.wait_for(self.p.telegram_start(), 5)
        self.assertIn("commands", [n for n, _ in started])

    def test_tab_wrapper_rules(self):
        import pult_tab
        v = "/x/anthropic.claude-code-2.1.301-darwin-arm64/resources/native-binary/claude"
        self.assertEqual(pult_tab.version_of(v), "2.1.301")
        # the session id: `--resume=<id>` is how the extension opens a session from its history (2.1.301),
        # `--resume <id>` is how the SDK passes it; without either, the wrapper waits for system/init
        self.assertEqual(pult_tab.arg([v, "--resume=" + SID, "--verbose"], "--resume"), SID)
        self.assertEqual(pult_tab.arg([v, "--resume", SID], "--resume"), SID)
        self.assertIsNone(pult_tab.arg([v, "--resume"], "--resume"))
        self.assertIsNone(pult_tab.arg([v, "--resumed=x"], "--resume"))
        conf = {"folders": [str(TMP / "sandbox")], "versions": ["2.1.301"]}
        (TMP / "sandbox" / "sub").mkdir(parents=True, exist_ok=True)
        chat = [v, "--output-format", "stream-json", "--input-format", "stream-json", "--verbose"]
        self.assertIsNone(pult_tab.why_direct(chat, conf, str(TMP / "sandbox" / "sub")))
        self.assertEqual(pult_tab.why_direct(chat, conf, str(TMP)), "folder not in the list")
        self.assertEqual(pult_tab.why_direct([v, "--claude-in-chrome-mcp"], conf, str(TMP / "sandbox")), "not a chat session")
        self.assertIn("version", pult_tab.why_direct([v.replace("301", "302")] + chat[1:], conf, str(TMP / "sandbox")))
        # no daemon — the wrapper still passes data byte for byte and exits with claude's exit code
        fake = fake_claude(TMP / "anthropic.claude-code-2.1.301-darwin-arm64", ECHO)
        (TMP / "tab.json").write_text(json.dumps(conf))
        data = "".join('{"type":"user","n":%d,"t":"%s"}\n' % (i, "ж" * i) for i in range(300)).encode()
        p = subprocess.run([sys.executable, str(HERE / "pult_tab.py"), str(fake), "--input-format",
                            "stream-json", "--output-format", "stream-json"], input=data, capture_output=True,
                           cwd=str(TMP / "sandbox"), timeout=20,
                           env=plain_env(PULT_TAB_CONF=str(TMP / "tab.json"), PULT_SOCK=str(TMP / "нет.sock")))
        self.assertEqual((p.stdout, p.returncode), (data, 3))
        old, pult_tab.OFF = pult_tab.OFF, str(TMP / "tab-off")
        try:
            Path(pult_tab.OFF).touch()
            self.assertEqual(pult_tab.why_direct(chat, conf, str(TMP / "sandbox")), "switched off")
        finally:
            pult_tab.OFF = old

    async def test_tab_wrapper_control(self):
        # a control request from Pult goes into Claude Code; its answer is held back from the extension, the rest of
        # the output passes unchanged; the wrapper says it can do it ("control" in hello)
        d = TMP / "ctl"
        seen = d / "seen.jsonl"
        fake = fake_claude(d / "anthropic.claude-code-2.1.301-darwin-arm64",
                           "import json, sys\nsys.stdout.reconfigure(newline='\\n', encoding='utf-8')\n"   # as claude: LF, UTF-8
                           "log = open(%r, 'a', encoding='utf-8')\n"
                           "for line in sys.stdin.buffer:\n    line = line.decode()\n"
                           "    log.write(line); log.flush()\n    o = json.loads(line)\n"
                           "    if o.get('type') == 'control_request':\n"
                           "        print(json.dumps({'type': 'control_response', 'response': {'subtype': 'success', "
                           "'request_id': o['request_id'], 'response': {}}}), flush=True)\n"
                           "    else:\n        print(line.strip(), flush=True)\n" % str(seen))
        (d / "tab.json").write_text(json.dumps({"folders": [str(d)], "versions": ["2.1.301"]}))
        sock = str(d / "d.sock")
        hello, conn = asyncio.get_running_loop().create_future(), []

        async def daemon(reader, writer):
            conn.append(writer)
            hello.set_result(json.loads(await reader.readline()))
            try:
                await reader.read()
            except ConnectionError:                    # Windows: a closed wrapper is a reset, not an end of data
                pass
        server = await pultd.start_link(daemon, sock)
        proc = await asyncio.create_subprocess_exec(
            sys.executable, str(HERE / "pult_tab.py"), str(fake), "--input-format", "stream-json", "--output-format",
            "stream-json", stdin=subprocess.PIPE, stdout=subprocess.PIPE, cwd=str(d),
            env=plain_env(PULT_TAB_CONF=str(d / "tab.json"), PULT_SOCK=sock, PULT_TAB_LOG=str(d / "tab.log")))
        try:
            self.assertIn("control", (await asyncio.wait_for(hello, 10))["caps"])
            req = {"subtype": "apply_flag_settings", "settings": {"effortLevel": "low"}}
            conn[0].write((json.dumps({"op": "control", "request": req}) + "\n").encode())
            conn[0].write(b'{"op": "control", "request": "not a request"}\n')
            await conn[0].drain()
            await until(lambda: seen.exists() and "control_request" in seen.read_text())
            user = b'{"type":"user","t":"\xd0\xb6"}\n'
            out, _ = await asyncio.wait_for(proc.communicate(user), 20)
        finally:
            for w in conn:
                w.close()
            server.close()
            await server.wait_closed()
        sent = [json.loads(x) for x in seen.read_text().splitlines()]
        self.assertEqual([x["type"] for x in sent], ["control_request", "user"])     # the malformed one went nowhere
        self.assertEqual(sent[0]["request"], req)
        self.assertEqual(out, user)                                                   # the answer stayed with the wrapper
        self.assertIn("apply_flag_settings done", (d / "tab.log").read_text())

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

    async def test_driven_midturn(self):
        # a message written while Pult's own session works goes straight to Claude Code, which reads it at the turn's
        # next step (probe_midturn.py, 2.1.300); Pult no longer holds it until the result: on 2026-10-21 "stop, wrong
        # project" waited out a 10-minute turn. Stop drops what is still waiting, so it starts no next turn
        from claude_agent_sdk import ResultMessage
        import claude_agent_sdk
        res = lambda: ResultMessage(subtype="success", duration_ms=1, duration_api_ms=1, is_error=False, num_turns=1,
                                    session_id=SID, result="ok")

        class FakeClient:
            def __init__(self, options):
                self.out, self.sent, self.stops = asyncio.Queue(), [], 0
                made.append(self)

            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                pass

            async def query(self, text):
                self.sent.append(text)                 # a long turn: no result until it is interrupted

            async def interrupt(self):
                self.stops += 1
                self.out.put_nowait(res())

            async def receive_messages(self):
                while True:
                    yield await self.out.get()

        made = []
        old = claude_agent_sdk.ClaudeSDKClient
        claude_agent_sdk.ClaudeSDKClient = FakeClient
        self.store.touch_session(SID, PKEY, path="/Users/x/proj", driven=True)
        try:
            d = self.p.driven[SID] = pultd.Driven(self.p, SID, "/Users/x/proj")
            await d.say("глянь", 1)
            await until(lambda: made and made[0].sent == ["глянь"] and d.asking)
            c = made[0]
            await d.say("стоп, не туда", 2)            # mid-turn: at once, and the result will answer this one
            self.assertEqual(c.sent, ["глянь", "стоп, не туда"])
            self.assertEqual(self.p.expect[SID], 2)
            r = await self.p.api_send(SID, "остановись")   # from the app: the same way
            self.assertEqual((r["how"], c.sent[-1]), ("session", "остановись"))
            d.q.put_nowait(("ещё одно", None))         # waiting in Pult (the loop is busy with the turn)
            r = await self.p.api_stop(SID)
            self.assertEqual((r["ok"], c.stops), (True, 1))
            await until(lambda: not d.asking)
            await asyncio.sleep(0.05)
            self.assertNotIn("ещё одно", c.sent)        # dropped: Stop does not start the next turn
            self.assertTrue(d.q.empty())
            await d.say("теперь дальше", None)         # between turns: through the loop, as before
            await until(lambda: c.sent[-1] == "теперь дальше")
        finally:
            claude_agent_sdk.ClaudeSDKClient = old
            d.task.cancel()

    async def test_interrupted_turn_closes(self):
        # an interrupted turn of Pult's own session gets no Stop hook, only its result (probe_midturn.py stop, 2.1.300):
        # shortly after the result it is closed as interrupted, so it doesn't stay "working" and keep the idle process
        # alive (2026-10-21, a session after Stop). A turn whose Stop comes is closed by the Stop, as before
        old = pultd.RESULT_GRACE
        pultd.RESULT_GRACE = 0.3
        try:
            await run_hook(ev("UserPromptSubmit", prompt="Долгая задача"))
            await until(lambda: self.p.live.get(SID) and self.p.live[SID].turn)
            t = self.p.live[SID].turn
            self.p.result_seen(SID)
            await until(lambda: self.p.live[SID].turn is None)
            self.assertEqual(t.done[0], "⏹")
            await run_hook(ev("UserPromptSubmit", prompt="Ещё раз"))
            await until(lambda: self.p.live[SID].turn)
            t2 = self.p.live[SID].turn
            self.p.result_seen(SID)
            await run_hook(ev("Stop", last_assistant_message="Готово"))
            await asyncio.sleep(0.5)
            self.assertEqual(t2.done[0], "✔️")
            self.p.result_seen(SID)                    # no turn open: nothing to close
        finally:
            pultd.RESULT_GRACE = old

    async def test_busy_report(self):
        # what a restart would cut off (pult busy, install.sh): Pult's own sessions with a turn, queued prompts or
        # background tasks — a subagent too, after the session's turn has ended (2026-10-20: a restart killed one);
        # an idle one is not listed. Asked over the socket, as pult_setup does
        import pult_setup
        NS, idle, queued = types.SimpleNamespace, "22222222-2222-3333-4444-555555555555", "33333333-2222-3333-4444-555555555555"
        lv = self.p.live_of(SID, PKEY)
        lv.bg = [{"id": "a1", "type": "subagent", "status": "running", "description": "Probe A: maker"}]
        q = asyncio.Queue()
        q.put_nowait(("дальше", None))
        self.p.driven.update({SID: NS(busy=False, bg={"a1"}, q=asyncio.Queue()),
                              idle: NS(busy=False, bg=set(), q=asyncio.Queue()),
                              queued: NS(busy=False, bg=set(), q=q)})
        with mock.patch.object(pult_setup, "SOCK", os.environ["PULT_SOCK"]), \
                mock.patch.object(pult_setup, "service", lambda lbl: ("running", "1")):
            busy = await asyncio.to_thread(pult_setup.busy_sessions, "x")
            self.assertEqual(sorted((b["sid"], b["turn"], b["bg"], b["n"]) for b in busy),
                             [(SID, False, ["Probe A: maker"], 1), (queued, True, [], 0)])
            self.assertEqual(busy[0]["project"], "proj")
            # the SDK reports a task the Stop hook hasn't yet: counted without its name
            lv.bg = []
            busy = await asyncio.to_thread(pult_setup.busy_sessions, "x")
            self.assertEqual([(b["bg"], b["n"]) for b in busy if b["sid"] == SID], [([], 1)])
            self.p.driven.clear()
            self.assertEqual(await asyncio.to_thread(pult_setup.busy_sessions, "x"), [])

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

    async def test_choice_marks(self):
        # a choice made with a button: the message keeps its text, says what was picked and loses its buttons; its
        # other buttons do nothing after that; a menu (projects to open) stays as it is; "Log out everywhere" says when
        runs = []

        async def drive(sid, path, text, origin, **kw):
            runs.append(text)
        self.p.drive = drive
        self.store.set_topic(PKEY, "/Users/x/proj", "proj", 77)
        self.store.touch_session(SID, PKEY, path="/Users/x/proj", title="Отчёт")
        await self.p.ask_target(self.store.topic(PKEY), "Новая задача", 10, 77)
        q = self.fake.of("sendMessage")[-1]
        cm = {"message_id": 4242, "text": q["text"], "reply_markup": json.loads(q["reply_markup"]),
              "message_thread_id": 77, "is_topic_message": True}
        sess, new = self.fake.buttons("t:")
        await self.p.on_callback({"id": "c1", "from": {"id": OWNER}, "data": new, "message": cm})
        self.assertEqual(runs, ["Новая задача"])
        await until(lambda: self.fake.of("editMessageText"))
        e = self.fake.of("editMessageText")[-1]
        self.assertEqual((e["message_id"], e["text"]), ("4242", R.esc(q["text"]) + "\n→ <b>▶️ Новая сессия</b>"))
        self.assertEqual(json.loads(e["reply_markup"]), {"inline_keyboard": []})
        await self.p.on_callback({"id": "c2", "from": {"id": OWNER}, "data": sess, "message": cm})
        self.assertEqual(runs, ["Новая задача"])
        self.assertEqual(self.fake.of("answerCallbackQuery")[-1]["text"], "уже решено")
        # a menu: a link to a project's topic, and the list stays for another tap
        tok = self.p.offer(("open", PKEY, "/Users/x/proj", None))
        menu = {"message_id": 4243, "text": "Проекты", "reply_markup": {"inline_keyboard": [[
            {"text": "proj", "callback_data": "o:" + tok}]]}}
        n = len(self.fake.of("editMessageText"))
        await self.p.on_callback({"id": "c3", "from": {"id": OWNER}, "data": "o:" + tok, "message": menu})
        self.assertIn("t.me/c/123/77", self.fake.of("sendMessage")[-1]["text"])
        await asyncio.sleep(0.05)
        self.assertEqual(len(self.fake.of("editMessageText")), n)
        # "Log out everywhere" under a login alert: the alert keeps its words and says when
        alert = {"message_id": 4244, "text": "🔐 Вход в приложение из новой сети: 10.0.0.0/24 · android 8.0 · "
                                             "приложение открыли.\nЕсли это не ты — выйди везде.",
                 "reply_markup": {"inline_keyboard": [[{"text": "Выйти везде", "callback_data": "k:out"}]]}}
        web = types.SimpleNamespace(logout_all=mock.AsyncMock())
        with mock.patch.object(self.p, "web", web):
            await self.p.on_callback({"id": "c4", "from": {"id": OWNER}, "data": "k:out", "message": alert})
        web.logout_all.assert_awaited_once()
        await until(lambda: self.fake.of("editMessageText")[-1]["message_id"] == "4244")
        self.assertRegex(self.fake.of("editMessageText")[-1]["text"],
                         r"^🔐 Вход .*\nЕсли это не ты — выйди везде\.\n→ <b>вышел везде в \d\d:\d\d</b>$")

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
