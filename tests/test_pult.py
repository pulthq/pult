#!/usr/bin/env python3
"""Pult tests without Telegram or Claude: a fake Bot API, a real socket and the real hook.

  ~/.local/share/pult/venv/bin/python tests/test_pult.py
"""
import asyncio
import atexit
import base64
import gc
import io
import json
import os
import re
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
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent / "src"
TMP = Path(tempfile.mkdtemp(prefix="pult-test-"))
atexit.register(shutil.rmtree, TMP, True)        # test_web, test_relay and the stand import this: theirs goes too
os.environ.update(PULT_HOME=str(TMP), PULT_SOCK=str(TMP / "s.sock"), PULT_ENV=str(TMP / "env"),
                  PULT_PROJECTS=str(TMP / "projects"))
sys.path.insert(0, str(HERE))

import httpx  # noqa: E402

import pult_api  # noqa: E402
import pult_attn as A  # noqa: E402
import pult_brief as B  # noqa: E402
import pult_driven  # noqa: E402
import pult_hook  # noqa: E402
import pult_i18n as I  # noqa: E402
import pult_load as L  # noqa: E402
import pult_new as N  # noqa: E402
import pult_files as F  # noqa: E402
import pult_os  # noqa: E402
import pult_parts  # noqa: E402
import pult_render as R  # noqa: E402
import pult_stt as STT  # noqa: E402
import pult_tags as G  # noqa: E402
import pult_tg  # noqa: E402
import pult_update as U  # noqa: E402
import pultd  # noqa: E402

# Pult's folder and the transcripts' are the tests' temporary ones: a module imported before the environment above
# would keep the owner's own, and tests delete files there (review 2026-10-27, Т8; the stand once wrote there)
for _p in (pultd.HOME, U.HOME, pultd.CLAUDE_PROJECTS):
    assert Path(_p).resolve().is_relative_to(TMP.resolve()), "not a temporary folder: %s" % _p

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
        if ctype.startswith("multipart/form-data"):           # sendDocument: fields, and the file as _name / _bytes
            raw = req.content
            for m in re.finditer(rb'name="(\w+)"(?:; filename="([^"]*)")?[^\r\n]*\r\n(?:[^\r\n]+\r\n)*\r\n(.*?)\r\n--', raw, re.S):
                if m.group(2) is not None:
                    data["_name"], data["_bytes"] = m.group(2).decode(), m.group(3)
                else:
                    data[m.group(1).decode()] = m.group(3).decode()
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
        # a block in one line longer than a chunk: no character of it lost (the first went — review 2026-10-27, М6)
        line = "Z" + "x" * (R.CHUNK + 500) + "Q"
        chunks = R.split_md("```" + line + "```")
        self.assertGreater(len(chunks), 1)
        self.assertEqual("".join(c[len("```\n"):-len("\n```")] for c in chunks), line)

    def test_steps(self):
        self.assertEqual(R.tool_step("Read", {"file_path": "/Users/x/proj/a/b.md"}, "/Users/x/proj"), "📖 a/b.md")
        self.assertEqual(R.tool_step("Bash", {"command": "ls", "description": "Список"}), "⌘ Список")
        self.assertIsNone(R.tool_step("TodoWrite", {}))
        self.assertTrue(R.tool_step("Bash", {"command": "x"}, failed=True).startswith("⚠️"))
        self.assertTrue(R.tool_step("Read", {"file_path": "a"}, sub=True).startswith("↳"))
        # a step of an odd shape — the model wrote a call that doesn't fit the tool, Claude Code keeps it as written:
        # its name, never an error (it broke the session's screen in the app for good before 0.18.6)
        self.assertEqual(R.tool_step("AskUserQuestion", {"questions": [None, {"question": "Q?", "header": "H"}],
                                                         "answers": ["x"]}), "❓ H → …")
        for name, inp in (("AskUserQuestion", {"questions": "q"}), ("Bash", {"description": ["a"]}),
                          ("Read", {"file_path": ["a"]}), ("Bash", ["not", "a", "dict"]), (None, None)):
            self.assertIsInstance(R.tool_step(name, inp), str, (name, inp))
        # a Mac too busy to answer about its screen lock in 5 s: unknown, not an error in the middle of a turn's end
        with mock.patch.object(pult_os, "KIND", "mac"), mock.patch.object(pult_os.shutil, "which", lambda x: "/usr/sbin/ioreg"), \
                mock.patch.object(pult_os.subprocess, "run", mock.Mock(side_effect=subprocess.TimeoutExpired("ioreg", 5))):
            self.assertIsNone(pult_os.screen_locked())
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

    def test_folded(self):
        # a short reply stays as it is; a long one shows its first paragraphs, the rest folds into a quote that opens with
        # a tap — code and links stay inside (Telegram keeps them there: tests/probe_quote.py)
        self.assertEqual(R.folded_html("Готово: **27 тестов**"), "Готово: <b>27 тестов</b>")
        md = "## Итог\n\nВсе **27 тестов** зелёные.\n\n" + "\n\n".join("Пункт %d: `код %d` и [стенд](https://example.com)." % (i, i) for i in range(30))
        h = R.folded_html(md)
        lead, rest = h.split("\n<blockquote expandable>")
        self.assertIn("Все <b>27 тестов</b> зелёные.", lead)                   # a lone heading took the next paragraph
        self.assertTrue(rest.endswith("</blockquote>"))
        self.assertIn("<code>код 29</code>", rest)
        self.assertIn('<a href="https://example.com">стенд</a>', rest)
        self.assertNotIn("Пункт 29", lead)
        # one long paragraph cut where a mark is: the mark goes whole into the fold (review 2026-10-27, М15)
        para = "слово " * 50 + "**жирное посреди разреза**" + " слово" * 120
        lead, rest = R.folded_html(para).split("\n<blockquote expandable>")
        self.assertNotIn("*", lead + rest)
        self.assertIn("<b>жирное посреди разреза</b>", rest)
        # a code block keeps whole on either side
        h = R.folded_html("Сделал так:\n\n```\n" + "\n".join("строка %d" % i for i in range(80)) + "\n```")
        self.assertEqual(h.count("<pre>"), 1)
        self.assertEqual(h.count("</pre>"), 1)

    def test_permission_line(self):
        # a decided request in one line: the headline; a command without a description — its beginning
        self.assertEqual(R.permission_line("Bash", {"command": "git push", "description": "Отправить"}), "Выполнить команду: <b>«Отправить»</b>")
        self.assertEqual(R.permission_line("Bash", {"command": "git push"}), "Выполнить команду <code>git push</code>")
        self.assertNotIn("\n", R.permission_line("Edit", {"file_path": "/x/a.py", "old_string": "a", "new_string": "b\nc"}, "/x"))
        # a description in two lines: one line, its <b> closed (it was cut inside — review 2026-10-27, М5)
        self.assertEqual(R.permission_line("Bash", {"command": "make", "description": "Собрать\n  и проверить"}),
                         "Выполнить команду: <b>«Собрать и проверить»</b>")

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

    def test_advice(self):
        # Claude's advice in an option's label, in the words sessions use: checked from the start in multi-select
        for label in ("MIT (Recommended)", "Сервер (Рекомендую)", "Ночью (Рекомендуется)", "Маска на колоду (Рекоменд.)",
                      "Обе (рекомендую)"):
            self.assertTrue(R.advised(label), label)
        self.assertTrue(R.advised("Б (Рекомендовано)"))
        # only the mark itself: words after it may turn it round, or describe the thing (review 2026-10-27, М7)
        for label in ("Не рекомендую", "Отчёт (из рекомендаций)", "", None, "Б (Рекомендую не делать)",
                      "Сразу (recommended against)", "Питание (рекомендуется 3,3 В)", "Схема (рекомендация устарела)"):
            self.assertFalse(R.advised(label), label)
        qs = [{"question": "Что выкладываем?", "multiSelect": True,
               "options": [{"label": "Сервер (Рекомендую)"}, {"label": "Выпуск"}, {"label": "Друг (Recommended)"}]},
              {"question": "Лицензия?", "multiSelect": False, "options": [{"label": "MIT (Recommended)"}, {"label": "Apache"}]},
              {"question": "Что ещё?", "multiSelect": True, "options": [{"label": "A"}, {"label": "B"}]}, "мусор"]
        self.assertEqual(R.advised_picks(qs), {0: ["Сервер (Рекомендую)", "Друг (Recommended)"]})  # a single choice: one tap
        self.assertEqual(R.advised_picks(None), {})
        self.assertIn("совет Claude уже отмечен", R.question_text(qs[0], ["Сервер (Рекомендую)"]))
        self.assertIn("отметь варианты", R.question_text(qs[2]))

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

    def test_i18n_used(self):
        # every key the code names outright is in the dictionary: a missing one would send the key itself, or fail
        # where a message was due (review 2026-10-27, М13); keys built from parts are checked where they are built
        import re as _re
        used = set()
        for f in HERE.glob("*.py"):
            text = f.read_text(encoding="utf-8")
            used |= set(_re.findall(r'(?<![\w.])(?:self\.t|I\.T|T|t)\(\s*"([a-z][\w-]*(?:\.[\w-]+)+)"', text))
            used |= set(_re.findall(r'\bplural\([^,()]+,\s*"([\w.]+)"', text))
        self.assertGreater(len(used), 300)
        self.assertFalse(used - set(I.S) - set(I.P), "keys the code uses but the dictionary lacks")


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
        with mock.patch.object(pult_driven, "HOOK_PY", "/x y/venv/bin/python"), \
                mock.patch.object(pult_driven, "HOOK", "/x y/pult_hook.py"):
            me = types.SimpleNamespace(path="/x", sid=SID, resume=None, fork=False, _wait_hook=None,
                                       d=types.SimpleNamespace(wanted=lambda m, e: (m, e)))
            opts = pultd.Driven.options(me)
        h = json.loads(opts.settings)["hooks"]["Stop"][0]["hooks"][0]
        if os.name == "nt":                          # exec form: no shell to read an environment prefix
            self.assertEqual((h["command"], h["args"]), ("/x y/venv/bin/python", ["/x y/pult_hook.py", "--injected"]))
        else:
            self.assertEqual(h["command"], "PULT_INJECTED=1 '/x y/venv/bin/python' '/x y/pult_hook.py'")
        with mock.patch.object(pult_driven, "HOOK_PY", r"C:\Py\pythonw.exe"), mock.patch.object(pult_driven, "HOOK", r"C:\P\pult_hook.py"):
            h = pult_driven.injected_hooks(windows=True)["PermissionRequest"][0]["hooks"][0]
        self.assertEqual(list(h), ["type", "command", "args", "timeout"])
        self.assertEqual(h["args"], [r"C:\P\pult_hook.py", "--injected"])

    def test_sessions_module_finds_the_daemon(self):
        # pult_driven works out Pult's folder and the daemon's socket itself, as pult_setup and pult_update do: the hook
        # in a session Pult runs has to reach this daemon (review 2026-10-27, 6.2)
        self.assertEqual((pult_driven.HOME, pult_driven.SOCK), (pultd.HOME, pultd.SOCK))

    def test_split_of_the_daemon(self):
        # pultd.py is split into modules by moving code (review 2026-10-27, 6.2), and what goes wrong there goes wrong
        # quietly. The daemon runs as `python pultd.py`, its module is __main__: a module it loads that imports pultd
        # would load a second copy of the daemon, and these tests, which import it as pultd, would never see that
        import ast

        def called(n):                       # f(…) or x.f(…) → "f"
            return isinstance(n, ast.Call) and (getattr(n.func, "attr", None) or getattr(n.func, "id", None))

        def imported(n):
            if isinstance(n, ast.Import):
                return [a.name for a in n.names]
            if isinstance(n, ast.ImportFrom):
                return [n.module or ""]
            if called(n) in ("__import__", "import_module") and n.args and isinstance(n.args[0], ast.Constant):
                return [str(n.args[0].value)]
            return []
        who, todo = {}, ["pultd"]
        while todo:
            name = todo.pop()
            for n in ast.walk(ast.parse((HERE / (name + ".py")).read_text(encoding="utf-8"))):
                for m in imported(n):
                    if (HERE / (m + ".py")).exists() and m not in who:
                        who[m] = name
                        todo.append(m)
        self.assertTrue({"pult_api", "pult_parts", "pult_driven", "pult_tg", "pult_web"} <= set(who), sorted(who))
        self.assertNotIn("pultd", who, "%s imports pultd" % who.get("pultd"))
        # run as the service runs it, the daemon's file gets as far as its settings: no token here — exit 2
        env = {k: v for k, v in os.environ.items() if k != "PULT_BOT_TOKEN"}
        env.update(PULT_ENV=str(TMP / "no-env"), PULT_LOG=str(TMP / "script.log"))
        r = subprocess.run([sys.executable, "-u", str(HERE / "pultd.py")], env=env, capture_output=True, text=True,
                           timeout=60)
        self.assertEqual((r.returncode, "Traceback" in r.stderr), (2, False), r.stdout + r.stderr)
        self.assertIn("no PULT_BOT_TOKEN in", r.stdout)
        # a setting a test or a tool changes on pultd is pultd's own: one that moved (NEW_ROOT is pult_api's) and is
        # changed on pultd changes nothing the moved code reads — the new-project tests would make folders in the real
        # home. pultd's own: what it assigns, defines or imports as a module (patching pultd.time changes its clock)
        own = set()
        for n in ast.parse((HERE / "pultd.py").read_text(encoding="utf-8")).body:
            if isinstance(n, (ast.Assign, ast.AnnAssign)):
                for t in n.targets if isinstance(n, ast.Assign) else [n.target]:
                    own |= {x.id for x in ast.walk(t) if isinstance(x, ast.Name)}
            elif isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                own.add(n.name)
            elif isinstance(n, ast.Import):
                own |= {(a.asname or a.name).split(".")[0] for a in n.names}
        changed = []
        for f in sorted([*(HERE.parent / "tests").glob("*.py"), *(HERE.parent / "tools").glob("*.py")]):
            for n in ast.walk(ast.parse(f.read_text(encoding="utf-8"))):
                if isinstance(n, (ast.Assign, ast.AugAssign)):
                    for t in n.targets if isinstance(n, ast.Assign) else [n.target]:
                        for x in t.elts if isinstance(t, (ast.Tuple, ast.List)) else [t]:
                            if isinstance(x, ast.Attribute) and getattr(x.value, "id", None) == "pultd":
                                changed.append((f.name, x.attr))
                elif called(n) and n.args and getattr(n.args[0], "id", None) == "pultd":
                    if called(n) in ("object", "setattr") and len(n.args) > 1 and isinstance(n.args[1], ast.Constant):
                        changed.append((f.name, n.args[1].value))         # mock.patch.object(pultd, "X"), setattr
                    elif called(n) == "multiple":
                        changed += [(f.name, k.arg) for k in n.keywords]  # mock.patch.multiple(pultd, X=…)
                elif called(n) == "patch" and n.args and isinstance(n.args[0], ast.Constant) \
                        and str(n.args[0].value).startswith("pultd."):
                    changed.append((f.name, n.args[0].value.split(".")[1]))   # mock.patch("pultd.X")
        self.assertGreater(len(changed), 30)
        self.assertEqual(sorted({c for c in changed if c[1] not in own}), [], "changed on pultd, but not pultd's own")
        # moved, not copied: a method in two of the classes would be the first one's in the MRO, the other dead code
        mixins = {pult_api: pult_api.Api, pult_parts: pult_parts.Parts}
        self.assertEqual(pultd.Pult.__bases__, tuple(mixins.values()))
        names = [{k for k in vars(c) if not k.startswith("__")} for c in (pultd.Pult, *mixins.values())]
        self.assertEqual([a & b for i, a in enumerate(names) for b in names[i + 1:]], [set()] * 3)
        # the daemon's names the mixins read late, self.D.X, are its own: a renamed one fails here, not on a tap
        self.assertIs(pultd.Pult.D, pultd)
        for m in mixins:
            late = {n.attr for n in ast.walk(ast.parse(Path(m.__file__).read_text(encoding="utf-8")))
                    if isinstance(n, ast.Attribute) and isinstance(n.value, ast.Attribute) and n.value.attr == "D"
                    and getattr(n.value.value, "id", None) == "self"}
            self.assertGreater(len(late), 5, m.__name__)
            self.assertEqual(sorted(late - own), [], m.__name__)

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


def intro_id_of(fake, data):
    """The message_id the fake gave a call's data dict (ids go up by one per call, starting at 1001)."""
    return 1001 + next(i for i, (m, d) in enumerate(fake.calls) if d is data)


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


class NewProjectTest(unittest.TestCase):
    """Stage S without the daemon: the folder's name from a title, the checks, clone links, clone progress."""

    def test_folder_name(self):
        for title, name in [("Дача у моря", "dacha_u_morya"), ("Щука и ёжик", "shchuka_i_ezhik"), ("Київ", "kiyiv"),
                            ("Объединение", "obedinenie"), ("my-shop-api", "my-shop-api"), ("My App!", "my_app"),
                            ("Café 2026", "cafe_2026"), ("  .hidden. ", "hidden"), ("中文", ""), ("🙂 план", "plan")]:
            self.assertEqual(N.folder_name(title), name, title)
        self.assertEqual(len(N.folder_name("я" * 80)), N.NAME_MAX)
        for name in ["dacha_u_morya", "x", "My.App-2", "a_"]:
            self.assertIsNone(N.bad_name(name), name)
        for name in ["", ".x", "-x", "x.", "con", "LPT1.txt", "a b", "дача", "a/b", "..", "x" * 65]:
            self.assertEqual(N.bad_name(name), "new.err.name", name)

    def test_repo(self):
        gh = ("https://github.com/pulthq/pult.git", "pult", "pulthq/pult")
        for link in ["https://github.com/pulthq/pult", "https://github.com/pulthq/pult.git", "github.com/pulthq/pult/",
                     "git@github.com:pulthq/pult.git", "ssh://git@github.com/pulthq/pult.git",
                     "https://github.com/pulthq/pult/tree/main?tab=readme#x", " https://www.github.com/pulthq/pult "]:
            self.assertEqual(N.repo(link), gh, link)
        self.assertEqual(N.repo("https://gitlab.com/g/sub/proj.git"), ("https://gitlab.com/g/sub/proj.git", "proj", None))
        for link in ["", "pulthq/pult", "https://github.com/pulthq", "ext::sh -c touch", "file:///etc/x", "/Users/x/repo",
                     "https://github.com/../x", "https://github.com/-o/x", "https://github.com/o/.x", "--upload-pack=x"]:
            self.assertIsNone(N.repo(link), link)

    def test_progress_and_places(self):
        self.assertEqual(N.progress("Receiving objects:  45% (9/20)\rReceiving objects: 100% (20/20), done.\n"
                                    "Resolving deltas:  12% (1/8)\r"), ("resolve", 12))
        self.assertIsNone(N.progress("Cloning into 'x'...\n"))
        root = TMP / "places"
        (root / "b").mkdir(parents=True, exist_ok=True)
        (root / "A").mkdir(exist_ok=True)
        (root / ".hidden").mkdir(exist_ok=True)
        (root / "file.txt").write_text("")
        self.assertEqual(N.dirs(root), ["A", "b"])
        self.assertTrue(N.inside(root / "b", root))
        self.assertTrue(N.inside(root, root))
        self.assertFalse(N.inside(TMP, root))
        self.assertFalse(N.inside(str(root) + "x", root))
        (root / "out").symlink_to(TMP) if not (root / "out").exists() else None
        self.assertFalse(N.inside(root / "out", root))          # a link out of the home folder is outside
        self.assertIn("Дача", N.describe_prompt(" Дача ", "грядки"))


class FilesTest(unittest.TestCase):
    """Stage F without the daemon: names for files from the phone, what may go back to Telegram, a turn's files."""

    def test_names(self):
        for given, name in [("../../etc/passwd", "passwd"), ("a/b\\c.pdf", "c.pdf"), (".env", "env"),
                            ("re:port?.docx", "re_port_.docx"), ("CON.txt", "_CON.txt"), ("", "file"), ("  ", "file"),
                            ("Отчёт [финал].docx", "Отчёт [финал].docx"), ("-rf", "rf")]:
            self.assertEqual(F.safe_name(given), name, given)
        long = F.safe_name("я" * 200 + ".pptx")
        self.assertTrue(long.endswith(".pptx") and len(long) == F.NAME_MAX)
        d = TMP / "names"
        d.mkdir(exist_ok=True)
        (d / "a.pdf").write_text("x")
        (d / "a (2).pdf").write_text("x")
        self.assertEqual(os.path.basename(F.unique(str(d), "a.pdf")), "a (3).pdf")
        self.assertEqual(os.path.basename(F.unique(str(d), "b.pdf")), "b.pdf")
        self.assertTrue(F.drop_dir("/p", time.mktime((2026, 10, 23, 12, 0, 0, 0, 0, -1))).endswith(os.path.join("inbox", "2026-10-23")))

    def test_git_exclude(self):
        proj = TMP / "gitproj"
        (proj / ".git" / "info").mkdir(parents=True, exist_ok=True)
        (proj / ".git" / "info" / "exclude").write_text("# git's own\n*.log")
        self.assertTrue(F.exclude_inbox(str(proj)))
        self.assertFalse(F.exclude_inbox(str(proj)))                      # once
        self.assertEqual((proj / ".git" / "info" / "exclude").read_text().count("/inbox/"), 1)
        self.assertIn("*.log\n# files", (proj / ".git" / "info" / "exclude").read_text())
        (TMP / "plain").mkdir(exist_ok=True)
        self.assertFalse(F.exclude_inbox(str(TMP / "plain")))

    def test_what_may_go(self):
        proj = TMP / "sendproj"
        (proj / "out").mkdir(parents=True, exist_ok=True)
        (proj / "sub" / ".ssh").mkdir(parents=True, exist_ok=True)
        ok = proj / "out" / "Отчёт.docx"
        ok.write_bytes(b"PK..")
        (proj / ".env").write_text("TOKEN=1")
        (proj / "sub" / ".ssh" / "config").write_text("x")
        (proj / "server.pem").write_text("x")
        (proj / "credentials.json").write_text("{}")
        (proj / "empty.txt").write_text("")
        big = proj / "big.zip"
        with open(big, "wb") as f:
            f.truncate(F.TG_SEND_MAX + 1)
        outside = TMP / "outside.txt"
        outside.write_text("x")
        link_out = proj / "report.pdf"
        if not link_out.exists():
            link_out.symlink_to(outside)
        link_secret = proj / "notes.txt"
        if not link_secret.exists():
            link_secret.symlink_to(proj / ".env")
        self.assertIsNone(F.why_not_send(str(ok), str(proj)))
        for path, why in [(outside, "send.err.outside"), (link_out, "send.err.outside"), (proj / ".env", "send.err.secret"),
                          (link_secret, "send.err.secret"), (proj / "sub" / ".ssh" / "config", "send.err.secret"),
                          (proj / "server.pem", "send.err.secret"), (proj / "credentials.json", "send.err.secret"),
                          (proj / "empty.txt", "send.err.empty"), (big, "send.err.big"), (proj / "nope.pdf", "send.err.none"),
                          (proj / "out", "send.err.none"), (str(proj) + "x/a.txt", "send.err.outside")]:
            self.assertEqual(F.why_not_send(str(path), str(proj)), why, path)
        # the other usual homes of secrets, by name; code named after them is code (review 2026-10-27, Б9)
        for name in ("client_secret.json", "secrets.yaml", "token", "token.json", "github_token", "api-token.txt",
                     "passwords.csv", "release.keystore", "deploy.gpg", "terraform.tfstate", "state.db", "app.sqlite3",
                     "google-credentials.json", "pub.asc"):
            self.assertTrue(F.secret_like(name), name)
        for name in ("tokenizer.py", "password_reset.py", "keyboard.js", "monkey.png", "report.pdf", "config.yaml"):
            self.assertFalse(F.secret_like(name), name)

    def test_turn_files(self):
        proj = TMP / "turnproj"
        for rel in ["old.pdf", "new.pptx", "build/deck.pdf", "a/b/c.png", ".git/index", "node_modules/x.js", "inbox/2026-10-23/in.pdf",
                    "~$new.pptx", ".hidden.txt", "__pycache__/m.pyc", ".claude/settings.json"]:
            (proj / rel).parent.mkdir(parents=True, exist_ok=True)
            (proj / rel).write_text(rel)
        start = time.time() - 60
        os.utime(proj / "old.pdf", (start - 600, start - 600))
        os.utime(proj / "a" / "b" / "c.png", (start + 10, start + 10))
        got, n = F.turn_files(str(proj), start)
        self.assertEqual(sorted(f["p"] for f in got), sorted(["new.pptx", os.path.join("build", "deck.pdf"), os.path.join("a", "b", "c.png")]))
        self.assertEqual((got[-1]["p"], n), (os.path.join("a", "b", "c.png"), 3))              # newest first
        with mock.patch.object(F, "TURN_FILES_MAX", 2):                                       # a long list: the newest, and how many in all
            got, n = F.turn_files(str(proj), start)
            self.assertEqual((len(got), n), (2, 3))
        self.assertEqual(F.turn_files(str(proj), time.time() + 100), ([], 0))
        self.assertEqual(F.turn_files(str(TMP / "no-such"), start), ([], 0))
        at = time.mktime((2026, 10, 23, 12, 40, 0, 0, 0, -1))
        self.assertEqual(F.zip_name(str(proj) + os.sep, at), "turnproj-2026-10-23-1240.zip")
        self.assertEqual([F.size_text(n) for n in (436, 12 * 1024, 2_400_000)], ["436 B", "12 KB", "2.3 MB"])


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
        # a path with a space (a home folder with one) — when it is a file; claude.exe (review 2026-10-27, М16)
        spaced = TMP / "with space" / "claude"
        spaced.parent.mkdir(exist_ok=True)
        spaced.write_text("")
        self.assertTrue(L.is_claude("%s --resume x" % spaced))
        self.assertTrue(L.is_claude("C:/Users/x/claude.exe --resume x"))
        self.assertFalse(L.is_claude("/usr/bin/python3 %s" % spaced.parent))
        self.assertFalse(L.is_claude("/usr/bin/python3 /x/claude --resume x"))
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
        # a look puts an outcome to rest unless the owner has to decide: broke off, or the model's "your move"
        self.assertFalse(A.needs_owner(dict(rec, model=False, need="")))   # the rule alone: nothing runs
        self.assertTrue(A.needs_owner(dict(rec, model=True, need="")))
        self.assertTrue(A.needs_owner(dict(rec, model=True, need="Выбери А или Б")))
        self.assertFalse(A.needs_owner(dict(rec, model=True, you=False)))  # only a report
        self.assertTrue(A.needs_owner(dict(rec, you=False, fail="rate_limit")))
        self.assertFalse(A.needs_owner(None))

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


class TagsTest(unittest.TestCase):
    """Task tags (stage T, pult_tags): names, the owner's hashtags, the project's list and its limits, the hints."""

    VOCAB = [{"n": "Прошивка", "c": 0, "topics": [{"n": "Калибровка"}, {"n": "Wi-Fi"}]},
             {"n": "Корпус", "c": 1, "topics": [{"n": "Прочность"}]}]

    def test_hashtag(self):
        # T3 (Q94): a tag under a result as Telegram writes a hashtag — lower case, words through "_", only letters,
        # digits and "_"; the owner's own #tag parser reads it back; nothing without a letter
        self.assertEqual(G.hashtag("Датчик филамента"), "#датчик_филамента")
        self.assertEqual(G.hashtag("Обновление  по сети!"), "#обновление_по_сети")
        self.assertEqual((G.hashtag("Wi-Fi"), G.hashtag("3D-печать")), ("#wi_fi", "#3d_печать"))
        self.assertEqual((G.hashtag("2026"), G.hashtag(""), G.hashtag(None)), (None, None, None))
        self.assertEqual(G.hashtags("снова " + G.hashtag("Датчик филамента")), ["датчик филамента"])

    def test_names(self):
        self.assertEqual(G.norm("  калибровка   стола "), "Калибровка стола")
        self.assertEqual(G.norm("#тёмная_тема"), "Тёмная тема")
        self.assertEqual(G.norm("«Выпуск»."), "Выпуск")
        self.assertEqual(G.norm("Метка «в фоне»"), "Метка «в фоне»")         # a quote that closes one inside stays
        self.assertEqual(G.norm("Node.js"), "Node.js")                     # a name with a dot is a name
        self.assertEqual((G.norm("ASP.NET"), G.norm("GPT-4.1")), ("ASP.NET", "GPT-4.1"))
        for bad in ("", "  ", "src/app.js", "runout.c", "C:\\work", "#", "—", "README.md", "pult_tags.py", "`CHANGELOG.md`"):
            self.assertIsNone(G.norm(bad), bad)                            # files and paths are never tags
        long = G.norm("очень длинное название раздела проекта", G.SEC_LEN)
        self.assertLessEqual(len(long), G.SEC_LEN)
        self.assertTrue("очень длинное название раздела проекта".lower().startswith(long.lower()))
        self.assertEqual(G.key("Тёмная  Тема"), G.key("темная_тема"))

    def test_hashtags(self):
        self.assertEqual(G.hashtags("Почини #калибровка и #тёмная_тема, issue #123, # Заголовок, a#b, &#39; #калибровка"),
                         ["калибровка", "тёмная тема"])
        self.assertEqual(G.hashtags("#один #два #три"), ["один", "два"])       # two at most: a section and a topic
        self.assertEqual(G.hashtags("без тегов"), [])

    def test_place(self):
        v = self.VOCAB
        self.assertEqual(G.find(v, "калибровка")[0], "topic")
        self.assertEqual(G.find(v, "КОРПУС")[1]["n"], "Корпус")
        self.assertIsNone(G.find(v, "Маркетинг"))
        # the list's own spelling; a new section or topic is marked as new
        self.assertEqual(G.place(v, {"sec": "прошивка", "topic": "wi-fi"}), ("Прошивка", "Wi-Fi", False, False))
        self.assertEqual(G.place(v, {"sec": "Корпус", "topic": "Крепления"}), ("Корпус", "Крепления", False, True))
        self.assertEqual(G.place(v, {"sec": "Маркетинг", "topic": "Выставка"}), ("Маркетинг", "Выставка", True, True))
        # the limits: past SEC_MAX the task keeps its tags (or gets none); past TOPIC_MAX — its topic in that section
        full = [{"n": "Р%d" % i, "c": i, "topics": []} for i in range(G.SEC_MAX)]
        self.assertIsNone(G.place(full, {"sec": "Новый", "topic": "x"}))
        self.assertEqual(G.place(full, {"sec": "Новый", "topic": "x"}, {"sec": "Р1", "topic": None}), ("Р1", None, False, False))
        crowded = [{"n": "Прошивка", "c": 0, "topics": [{"n": "Т%d" % i} for i in range(G.TOPIC_MAX)]}]
        self.assertEqual(G.place(crowded, {"sec": "Прошивка", "topic": "Ещё"}, {"sec": "Прошивка", "topic": "Т3"}),
                         ("Прошивка", "Т3", False, False))
        self.assertEqual(G.place(crowded, {"sec": "Прошивка", "topic": "Ещё"}), ("Прошивка", None, False, False))

    def test_resolve(self):
        # T2: an old name — renamed or merged by the owner — lands on the tag that took its place, along a chain; a
        # name in the list is itself; the model's and a hashtag's words go through it
        v = self.VOCAB
        alias = {("сеть", ""): ("Связь", None), ("связь", ""): ("Прошивка", None),          # Сеть → Связь → Прошивка
                 ("прошивка", "обновление по сети"): ("Прошивка", "Wi-Fi"),
                 ("корпус", "рама"): ("Корпус", "Прочность")}
        self.assertEqual(G.resolve(v, alias, "Сеть", "калибровка"), ("Прошивка", "калибровка"))
        self.assertEqual(G.resolve(v, alias, "Прошивка", "Обновление по сети"), ("Прошивка", "Wi-Fi"))
        self.assertEqual(G.resolve(v, alias, "сеть", "Обновление по сети"), ("Прошивка", "Wi-Fi"))
        self.assertEqual(G.resolve(v, alias, "Корпус", "Крепления"), ("Корпус", "Крепления"))      # no alias: as it is
        self.assertEqual(G.resolve(v, None, "Сеть", None), ("Сеть", None))
        self.assertEqual(G.place(v, {"sec": "Сеть", "topic": "Обновление по сети"}, alias=alias), ("Прошивка", "Wi-Fi", False, False))
        self.assertEqual(G.place(v, {"sec": "Корпус", "topic": "рама"}, alias=alias), ("Корпус", "Прочность", False, False))
        self.assertEqual(G.find(v, "обновление_по_сети", alias)[2]["n"], "Wi-Fi")
        self.assertEqual(G.find(v, "Сеть", alias)[1]["n"], "Прошивка")
        self.assertIsNone(G.find(v, "Маркетинг", alias))
        # a live name never follows an alias, even a stale one
        self.assertEqual(G.resolve(v, {("прошивка", ""): ("Корпус", None)}, "Прошивка", None), ("Прошивка", None))

    def test_tidy(self):
        # T2: the model's offers to merge two tags — as the list has them, both of one kind, never kept apart or hidden
        v = [{"n": "Прошивка", "c": 0, "topics": [{"n": "Wi-Fi"}, {"n": "Обновление по сети"}, {"n": "Калибровка"}]},
             {"n": "Корпус", "c": 1, "topics": [{"n": "Прочность"}]}, {"n": "Рама", "c": 2, "topics": []}]
        uses = {("Прошивка", None): 3, ("Прошивка", "Wi-Fi"): 1, ("Прошивка", "Обновление по сети"): 2, ("Корпус", None): 1}
        req = G.tidy_request("Принтер", v, uses, {frozenset({("Корпус", None), ("Рама", None)})})
        for part in ("- Прошивка (3): Wi-Fi (1), Обновление по сети (2), Калибровка (0)", "- Рама (0): —", "- Корпус — Рама"):
            self.assertIn(part, req)
        p = lambda a, b: {"a": {"sec": a[0], "topic": a[1]}, "keep": {"sec": b[0], "topic": b[1]}}
        d = {"pairs": [p(("прошивка", "wi-fi"), ("Прошивка", "обновление по сети")),     # the list's spelling
                       p(("Корпус", ""), ("Рама", "")),                                  # kept apart
                       p(("Прошивка", "Калибровка"), ("Прошивка", "Калибровка")),        # one tag twice
                       p(("Прошивка", ""), ("Корпус", "Прочность")),                     # a section and a topic
                       p(("Прошивка", "Нет такой"), ("Прошивка", "Калибровка")),         # not in the list
                       p(("Прошивка", "Калибровка"), ("Прошивка", "Wi-Fi"))]}            # Wi-Fi is in a pair already
        kept = {frozenset({("Корпус", None), ("Рама", None)})}
        self.assertEqual(G.tidy_pairs(d, v, kept), [[("Прошивка", "Wi-Fi"), ("Прошивка", "Обновление по сети")]])
        self.assertEqual(G.tidy_pairs(d, v, kept, {("Прошивка", None)}), [])            # its section hidden
        self.assertEqual(G.tidy_pairs(d, v), [[("Прошивка", "Wi-Fi"), ("Прошивка", "Обновление по сети")], [("Корпус", None), ("Рама", None)]])
        for bad in (None, "x", {}, {"pairs": "x"}, {"pairs": [1, None]}):
            self.assertEqual(G.tidy_pairs(bad, v), [], bad)
        self.assertNotEqual(G.sig(v), G.sig(v[:2]))
        self.assertEqual(G.sig(v), G.sig(list(reversed(v))))
        o = G.options("ru", TMP, G.TIDY_SYSTEM, G.TIDY_SCHEMA)
        self.assertIn("never a section and a topic", o.system_prompt)
        self.assertEqual(o.output_format["schema"]["required"], ["pairs"])

    def test_batch_and_list(self):
        # T2: the project's earlier tasks in batches — the title, the first request (unless it is the title), the last
        # thing Claude said; the answer only for the batch's own ids; a new list for "Sort them again"
        tasks = [{"id": "1", "title": "Продолжение работы", "ask": "продолжаем", "said": "Готово: " + "датчик " * 80},
                 {"id": "2", "title": "Калибровка стола", "ask": "Калибровка стола", "said": ""}]
        req = G.batch_request("Принтер", self.VOCAB, tasks, ["firmware"])
        for part in ('<task id="1">', "<title>Продолжение работы</title>", "<request>продолжаем</request>", "<claude>Готово: датчик",
                     "<top_folders>firmware</top_folders>", "- Прошивка: Калибровка, Wi-Fi"):
            self.assertIn(part, req)
        self.assertEqual(req.count("<request>"), 1)                                   # the second asks what its title says
        self.assertLessEqual(len(req.split("<claude>")[1].split("</claude>")[0]), G.SAID_LEN)
        d = {"tasks": [{"id": "1", "sec": "прошивка", "topic": "датчики"}, {"id": "1", "sec": "Корпус", "topic": ""},
                       {"id": "9", "sec": "Чужое", "topic": ""}, {"id": "2", "sec": "src/x.py", "topic": "x"}, "x"]}
        self.assertEqual(G.batch_tags(d, {"1", "2"}), {"1": {"sec": "Прошивка", "topic": "Датчики"}})
        for bad in (None, "x", {}, {"tasks": "x"}):
            self.assertEqual(G.batch_tags(bad, {"1"}), {}, bad)
        own = [{"n": "Голос", "topics": [{"n": "Порог"}]}]
        req = G.list_request("Принтер", "# Принтер\n" + "я" * 5000, "", ["Задача %d" % i for i in range(60)], own, ["firmware"])
        self.assertIn("- Задача 39", req)
        self.assertNotIn("- Задача 40", req)                                          # the latest 40 titles
        self.assertNotIn("<claude_md>", req)
        self.assertIn("- Голос: Порог", req)
        self.assertLess(len(req), G.DOC_LEN + 2000)
        got = G.new_list({"secs": [{"n": "прошивка", "topics": ["калибровка", "Прошивка", "калибровка", "Wi-Fi"]},
                                   {"n": "Прошивка", "topics": ["Другое"]}, {"n": "src/app.js", "topics": []},
                                   {"n": "Корпус", "topics": "x"}] + [{"n": "Р%d" % i, "topics": []} for i in range(20)]})
        self.assertEqual(got[:2], [("Прошивка", ["Калибровка", "Wi-Fi"]), ("Корпус", [])])
        self.assertEqual(len(got), G.SEC_MAX)
        self.assertEqual(G.new_list(None), [])
        o = G.options("ru", TMP, G.BATCH_SYSTEM.format(lang="Russian", sec_max=G.SEC_MAX), G.BATCH_SCHEMA)
        self.assertIn("every task of the batch, once", o.system_prompt)
        self.assertNotIn("{", o.system_prompt.split("Answer with JSON only:")[0])        # every placeholder filled

    def test_fresh_and_parse(self):
        now = time.time()
        self.assertTrue(G.is_fresh({"own": False, "ts": now - 60}, 1, now))
        self.assertFalse(G.is_fresh({"own": True, "ts": now - 60}, 1, now))           # the owner's: never new
        self.assertFalse(G.is_fresh({"own": False, "ts": now - 60}, 2, now))          # a second task has it
        self.assertFalse(G.is_fresh({"own": False, "ts": now - G.FRESH - 1}, 1, now))   # a day old
        self.assertEqual(G.parse({"sec": "прошивка", "topic": "Прошивка"}), {"sec": "Прошивка", "topic": None})
        self.assertEqual(G.parse({"sec": "Голос", "topic": ""}), {"sec": "Голос", "topic": None})
        for bad in (None, "x", {}, {"sec": "src/stt.py", "topic": "x"}, {"sec": "", "topic": "Тема"}):
            self.assertIsNone(G.parse(bad), bad)

    def test_hints_and_paths(self):
        root = TMP / "tagproj"
        for d in ("firmware", "marketing", ".git", "node_modules", "inbox"):
            (root / d).mkdir(parents=True, exist_ok=True)
        (root / "README.md").write_text("# x")
        self.assertEqual(G.hints(root), ["firmware", "marketing"])           # no hidden folders, dependencies, inbox
        self.assertEqual(G.hints(TMP / "nowhere"), [])
        tr = TMP / "tagproj.jsonl"
        stamp = lambda ago: time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime(time.time() - ago))
        use = lambda ago, *inputs: json.dumps({"type": "assistant", "timestamp": stamp(ago), "message": {"content": [
            {"type": "tool_use", "name": "x", "input": i} for i in inputs]}})
        tr.write_text("\n".join([
            use(500, {"file_path": str(root / "docs" / "old.md")}),                       # before the turn
            use(50, {"file_path": str(root / "firmware" / "runout.c")}, {"command": "make"}),
            use(40, {"path": "marketing/show"}, {"file_path": "/etc/hosts"}),             # outside the project: no
            use(30, {"notebook_path": str(root / "firmware" / "plot.ipynb")}),
            use(20, {"file_path": str(root / "firmware" / "runout.c")}),                  # again: the latest place
            "not json"]) + "\n")
        self.assertEqual(G.turn_paths(tr, time.time() - 100, root),
                         ["marketing/show", "firmware/plot.ipynb", "firmware/runout.c"])
        self.assertEqual(G.turn_paths(TMP / "no.jsonl", 0, root), [])
        req = G.request("Принтер", self.VOCAB, prompt="Добавь датчик", reply="Готово", paths=["firmware/runout.c"],
                        cur={"sec": "Корпус", "topic": "Прочность"}, own="датчики", dirs=["firmware"], title="Датчики двери")
        for part in ("- Прошивка: Калибровка, Wi-Fi", "<current_tags>Корпус / Прочность</current_tags>", "<task_title>Датчики двери</task_title>",
                     "<owner_tag>датчики</owner_tag>", "firmware/runout.c", "<top_folders>firmware</top_folders>", "Добавь датчик"):
            self.assertIn(part, req)
        self.assertIn("(empty", G.request("x", [], prompt="y"))
        o = G.options("ru", TMP)
        self.assertEqual((o.model, o.tools, o.setting_sources), ("haiku", [], []))
        self.assertIn("Russian", o.system_prompt)
        self.assertIn("never after a folder", o.system_prompt)

    def test_brief_asks_for_tags(self):
        # one request per turn: the result line's call asks for the tags too, when they are wanted
        ctx = {"project": "Принтер", "vocab": self.VOCAB, "paths": ["firmware/a.c"], "cur": None, "dirs": []}
        req = B.request("сделай", "готово", [], ctx)
        self.assertIn("<project_tags>", req)
        self.assertNotIn("<project_tags>", B.request("сделай", "готово", []))
        o = B.options("ru", TMP, tags=True)
        self.assertIn("sec", o.output_format["schema"]["required"])
        self.assertNotIn("sec", B.options("ru", TMP).output_format["schema"]["properties"])
        res = types.SimpleNamespace(is_error=False, structured_output={"line": "Готово", "you": False, "need": "",
                                                                      "sec": "прошивка", "topic": "датчики"})
        self.assertEqual(B.parse(res, True)["tags"], {"sec": "Прошивка", "topic": "Датчики"})
        self.assertNotIn("tags", B.parse(res))


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
        for fail in (httpx.WriteTimeout("t"), httpx.RemoteProtocolError("gone"), httpx.PoolTimeout("t")):   # 0.18.6
            e = await err(raise_=fail)
            self.assertEqual((e.key, e.kw), ("stt.e.net", {"why": type(fail).__name__}))
        with self.assertRaises(STT.SttError) as cm:
            await STT.Stt("k" * 24, transport=self.handler()[1]).transcribe(b"x", "text/plain")
        self.assertEqual(cm.exception.key, "stt.e.format")
        with self.assertRaises(STT.SttError) as cm:
            await STT.Stt("k" * 24, transport=self.handler()[1]).transcribe(b"x" * (STT.MAX_BYTES + 1), "audio/ogg")
        self.assertEqual(cm.exception.key, "stt.e.big")
        for k in ("stt.e.key", "stt.e.limit", "stt.e.big", "stt.e.groq", "stt.e.net", "stt.e.format"):
            self.assertIn(k, I.S)                                   # every reason has words in both languages

    async def test_model_and_prompt(self):
        # large-v3 unless told otherwise; the prompt is cut to Groq's 896 bytes of UTF-8 at a word (a longer one is
        # refused outright — 2026-10-23)
        seen, tr = self.handler()
        self.assertEqual(STT.Stt("k" * 24, transport=tr).model, "whisper-large-v3")
        await STT.Stt("k" * 24, transport=tr, model="whisper-large-v3-turbo").transcribe(b"x" * 10, "audio/webm",
                                                                                          prompt="Пульт, " * 200)
        self.assertIn(b'name="model"\r\n\r\nwhisper-large-v3-turbo', seen[0].content)
        cut = STT.fit("Пульт, " * 200)
        self.assertLessEqual(len(cut.encode()), STT.PROMPT_MAX)
        self.assertGreater(len(cut.encode()), STT.PROMPT_MAX - 20)
        self.assertTrue(cut.endswith("Пульт"), cut[-10:])
        self.assertIn(cut.encode(), seen[0].content)
        self.assertEqual(STT.fit("коротко."), "коротко.")

    def test_scrub(self):
        # Whisper's subtitle credits over silence are cut off the end; the same words inside a sentence stay
        cases = {
            "Продолжение следует...": ("", ["Продолжение следует..."]),
            "Сделай деплой. Продолжение следует...": ("Сделай деплой.", ["Продолжение следует..."]),
            "Посмотри логи. Редактор субтитров А.Семкин Корректор А.Егорова":
                ("Посмотри логи.", ["Редактор субтитров А.Семкин Корректор А.Егорова"]),
            "Привет. Субтитры сделал DimaTorzok": ("Привет.", ["Субтитры сделал DimaTorzok"]),
            "Готово. Спасибо за просмотр! Продолжение следует...":
                ("Готово.", ["Спасибо за просмотр!", "Продолжение следует..."]),
            "Thanks for watching!": ("", ["Thanks for watching!"]),
            "Это продолжение следует логике.": ("Это продолжение следует логике.", []),
            "Посмотри, что следует дальше.": ("Посмотри, что следует дальше.", []),
        }
        for text, want in cases.items():
            self.assertEqual(STT.scrub(text), want, text)

    async def test_proxy_fallback(self):
        # the proxy route fails → the direct one answers and stays the first choice afterwards
        _, dead = self.handler(raise_=httpx.ProxyError("no proxy"))
        seen, alive = self.handler(status=200, body={"data": []})
        stt = STT.Stt("k" * 24, transport=[dead, alive])
        await stt.check()
        self.assertEqual((stt.cur, len(seen)), (1, 1))
        await stt.check()
        self.assertEqual(len(seen), 2)


class OutboxTest(unittest.IsolatedAsyncioTestCase):
    """The queue in front of Telegram (review 2026-10-27, Т6): every daemon test turns its limits off with a huge rate,
    so here it runs on a clock of its own — a sleep moves the clock, nothing really waits."""

    async def asyncSetUp(self):
        self.now = 1000.0
        real = asyncio.sleep

        async def sleep(s):
            self.now += max(0.0, s)
            await real(0)
        aio = types.SimpleNamespace(**{k: getattr(asyncio, k) for k in dir(asyncio) if not k.startswith("_")})
        aio.sleep = sleep
        clock = types.SimpleNamespace(**{k: getattr(time, k) for k in dir(time) if not k.startswith("_")})
        clock.monotonic = lambda: self.now
        for name, value in (("asyncio", aio), ("time", clock)):     # the queue's module's own names only: the loop keeps its clock
            patch = mock.patch.object(pult_tg, name, value)
            patch.start()
            self.addCleanup(patch.stop)

    def run_box(self, out):
        task = asyncio.get_running_loop().create_task(out.run())
        self.addCleanup(task.cancel)
        return out

    def note(self, done, what, at=None):
        async def fn():
            done.append(what if at is None else (what, round(self.now - at, 2)))
            return what
        return fn

    async def test_burst_then_rate(self):
        # three at once, then one a second; a quiet minute gives three at once again — never more
        out, done = self.run_box(pultd.Outbox(rate=60, burst=3)), []
        await asyncio.wait_for(asyncio.gather(*[out.submit(5, self.note(done, k, 1000.0)) for k in range(5)]), 5)
        self.assertEqual([t for _, t in done], [0, 0, 0, 1, 2])
        self.now += 60
        start, done = self.now, []
        await asyncio.wait_for(asyncio.gather(*[out.submit(5, self.note(done, k, start)) for k in range(4)]), 5)
        self.assertEqual([t for _, t in done], [0, 0, 0, 1])

    async def test_retry_after(self):
        # Telegram asks to wait: the message goes again after the pause and half a second, and what came meanwhile
        # waits too; any other refusal fails that message only
        out, tries, done = self.run_box(pultd.Outbox(rate=6000, burst=100)), [], []

        async def flaky():
            tries.append(self.now)
            if len(tries) == 1:
                raise pultd.TgError("sendMessage", "Too Many Requests", 429, 7)
            done.append(("flaky", self.now))
            return "ok"

        async def refused():
            raise pultd.TgError("sendMessage", "Bad Request: chat not found", 400)
        first = asyncio.ensure_future(out.submit(5, flaky))
        await until(lambda: tries)
        later = asyncio.ensure_future(out.submit(5, self.note(done, "later")))
        self.assertEqual(await asyncio.wait_for(first, 5), "ok")
        self.assertEqual(await asyncio.wait_for(later, 5), "later")
        self.assertEqual(len(tries), 2)
        self.assertGreaterEqual(done[0][1] - tries[0], 7.5)
        # caught by hand: assertRaises clears the frames of what it caught, and the queue's own loop is one of them —
        # it ended the loop here, which nothing does in the daemon
        try:
            await asyncio.wait_for(out.submit(5, refused), 5)
            self.fail("a refused message went through")
        except pultd.TgError as e:
            self.assertEqual(e.code, 400)
        self.assertEqual(await asyncio.wait_for(out.submit(5, self.note(done, "after")), 5), "after")

    async def test_order_and_edits(self):
        # what waits goes by priority — a question before a message, a message before a turn's edits; edits of one
        # message go once, its latest text; an urgent edit jumps ahead and leaves its stale place empty
        out, done = pultd.Outbox(rate=60, burst=1), []
        for k in (1, 2, 3):
            out.edit(7, self.note(done, "edit %d" % k))
        out.edit(9, self.note(done, "draft"))
        out.edit(9, self.note(done, "final"), prio=2)
        sent = [asyncio.ensure_future(out.submit(p, self.note(done, x))) for p, x in ((5, "message"), (1, "question"))]
        await asyncio.sleep(0)
        self.run_box(out)
        await asyncio.wait_for(asyncio.gather(*sent), 5)
        await until(lambda: len(done) >= 4)
        await asyncio.sleep(0.05)
        self.assertEqual(done, ["question", "final", "message", "edit 3"])
        self.assertEqual(out.edits, {})


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
        fast = mock.patch.object(pultd, "EDIT_EVERY", 0.05)       # undone after each test: a test after this class
        fast.start()                                               # sees the real one (review 2026-10-27, Т8)
        self.addCleanup(fast.stop)
        self.server = await pultd.start_link(self.p.handle_conn, os.environ["PULT_SOCK"])
        self.tasks = [asyncio.create_task(self.p.out.run())]
        self.tagged = []                         # what the tags' model was asked (stage T): it never really runs here

        async def no_model(text, lang, cwd):
            self.tagged.append(text)
            return None
        self.no_tag = mock.patch.object(pultd.G, "tag", no_model)
        self.no_tag.start()

    async def asyncTearDown(self):
        self.no_tag.stop()
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
        # one message per turn: the result says what was asked, the turn message goes (it said the same title and time)
        self.assertIn("\n<i>Ты: «Сделай отчёт по продажам»</i>\n", result["text"])
        self.assertNotIn("reply_parameters", result)
        self.assertEqual(self.store.msg(intro_id(self.fake, result))["sid"], SID)
        turn_id = intro_id(self.fake, next(d for d in self.fake.of("sendMessage") if "Сделай отчёт" in d["text"] and "⏳" in d["text"]))
        await until(lambda: any(str(d["message_id"]) == str(turn_id) for d in self.fake.of("deleteMessage")))
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

    async def test_superseded_turn(self):
        # two events at once each started a turn: the first one is nobody's — it closes itself, the session's own
        # goes on (2026-10-24: such a turn said "the session is gone" every minute for hours, closing the wrong one)
        lv = self.p.live_of(SID, PKEY)
        t1 = self.p.start_turn(lv, "задача")
        t2 = self.p.start_turn(lv, "задача")
        t1.changed.set()
        await until(lambda: t1.done)
        self.assertEqual((t1.done[0], lv.turn, t2.done), ("⏹", t2, None))
        self.p.finish_turn(lv, "✔️")
        self.assertEqual((t2.done[0], lv.turn), ("✔️", None))

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
        await until(lambda: any(t.startswith("⚠️") for t in self.texts()))
        start = next(d for d in self.fake.of("sendMessage") if d["text"].startswith("⚙️"))
        end = next(d for d in self.fake.of("sendMessage") if d["text"].startswith("⚠️"))
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
        self.assertEqual(self.p.prefs(), {"vehi": True, "mode": "auto", "lang": None, "brief": False, "pager": None, "pace": 90,
                                          "model": None, "effort": None, "gh": True, "vcheck": True, "hashtags": True})
        self.p.env["PULT_FORCE_AWAY"] = "0"                                           # you are at the Mac
        self.assertFalse(await self.p.loud())
        self.assertTrue(await self.p.loud(driven=True))                     # auto: a session from Telegram — with sound
        res = await self.p.api_prefs(mode="phone", vehi="да", lang="xx", brief="да", evil=True, pace="90", gh="off",
                                     hashtags="yes")                                # garbage is rejected
        self.assertEqual(res, {"vehi": True, "mode": "phone", "lang": None, "brief": False, "pager": None, "pace": 90,
                               "model": None, "effort": None, "gh": True, "vcheck": True, "hashtags": True})
        self.assertFalse((await self.p.api_prefs(hashtags=False))["hashtags"])      # stage T, T3: no hashtags under results
        await self.p.api_prefs(hashtags=True)
        self.assertFalse((await self.p.api_prefs(gh=False))["gh"])                  # stage U3: no looks at GitHub
        await self.p.api_prefs(gh=True)
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
        self.assertEqual(s["gh"]["release"], False)                 # not a clone of Pult's GitHub repository

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
        await until(lambda: any("✔️ 📱 Телефон" in d.get("reply_markup", "") for d in self.fake.of("editMessageText")))
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
        self.assertEqual(pult_driven.ctx_from_usage(mu, "claude-haiku-4-5"), (200000, 32000))
        self.assertEqual(pult_driven.ctx_from_usage(mu, None), (1000000, 64000))             # the one that read the most
        self.assertIsNone(pult_driven.ctx_from_usage({"m": {"inputTokens": 1}}, "m"))
        self.assertEqual(pult_tab.ctx_from_result({"type": "result", "modelUsage": mu}, "claude-haiku-4-5"), (200000, 32000))
        self.assertIsNone(pult_tab.ctx_from_result({"type": "assistant", "modelUsage": mu}))
        self.assertEqual(pult_api.ctx_usable(200000, 32000), 167000)                       # 200k − 20k − 13k, like VS Code
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

    async def test_new_project(self):
        # stage S: a folder in a place picked inside the home folder, git, the topic named by the title at once, the
        # project in the lists before Claude ever ran there; with a description — the first turn writes CLAUDE.md
        root = TMP / ("home-" + self._testMethodName)
        (root / "Documents" / "old").mkdir(parents=True)
        (root / "Code").mkdir()
        tabs = TMP / "tab-new.json"
        tabs.write_text(json.dumps({"folders": [str(root / "Documents")]}))
        # the test's home is in the temp folder, which Pult otherwise never lists as a project
        with mock.patch.object(pult_api, "NEW_ROOT", root), mock.patch.object(pultd, "TAB_CONF", tabs), \
                mock.patch.object(pultd, "SKIP_PREFIXES", ("-nothing-",)), mock.patch.object(self.p, "drive", mock.AsyncMock()) as drive:
            d = await self.p.api_dirs()
            self.assertEqual((d["show"], d["dirs"], d["tabs"]), (os.path.join("~", "Documents"), ["old"], True))   # ~\Documents on Windows
            self.assertEqual(d["up"], os.path.realpath(root))
            up = await self.p.api_dirs(d["up"])
            self.assertEqual((up["show"], up["up"], up["dirs"]), ("~", None, ["Code", "Documents"]))
            self.assertFalse((await self.p.api_dirs(up["path"], into="Code"))["tabs"])
            for bad in [dict(path="/"), dict(path=str(TMP)), dict(path=up["path"], into=".."), dict(path=up["path"], into="nope")]:
                with self.assertRaises(ValueError):
                    await self.p.api_dirs(**bad)
            self.assertEqual(await self.p.api_folder("Дача у моря"), {"name": "dacha_u_morya"})
            self.assertEqual(await self.p.api_folder("", "git@github.com:o/My.Repo.git"), {"name": "My.Repo"})
            # empty: a folder with git, a topic named by the title, listed with no transcripts, the place remembered
            r = await self.p.api_create("Дача у моря", parent=d["path"])
            dest = os.path.join(d["path"], "dacha_u_morya")
            self.assertEqual(r, {"pkey": pultd.sanitize(dest), "git": bool(shutil.which("git"))})
            self.assertTrue(os.path.isdir(dest))
            self.assertEqual(os.path.isdir(os.path.join(dest, ".git")), bool(shutil.which("git")))
            self.assertEqual(self.fake.of("createForumTopic")[-1]["name"], "Дача у моря")
            # its icon in the project's own colour: the app's tile is the same (app.js hue() gives index 5 for this name)
            self.assertEqual(str(self.fake.of("createForumTopic")[-1]["icon_color"]), str(R.TOPIC_COLORS[5]))
            self.assertEqual(self.store.topic(r["pkey"])["name"], "Дача у моря")
            drive.assert_not_called()
            rows = (await self.p.api_projects())["projects"]
            self.assertIn(("Дача у моря", dest), [(x["name"], x["path"]) for x in rows])
            self.assertEqual(self.store.get("new_parent"), d["path"])
            # refusals: nothing that exists is touched
            for kw, key in [(dict(title="Дача у моря"), "new.err.exists"), (dict(title="x", name="dacha-u-morya"), "new.err.key"),
                            (dict(title="x", name=".x"), "new.err.name"), (dict(title="中文"), "new.err.name"),
                            (dict(title="x", parent="/tmp"), "new.err.where"), (dict(title=""), "new.err.title"),
                            (dict(title="x", how="describe"), "new.err.about"), (dict(title="x", how="clone", link="nope"), "new.err.link"),
                            (dict(title="x", how="rm"), "err.no_request")]:
                with self.assertRaises(ValueError, msg=kw) as cm:
                    await self.p.api_create(**kw)
                self.assertEqual(str(cm.exception), self.p.t(key, name="dacha_u_morya", other=os.path.join("~", "Documents", "dacha_u_morya"), op="create"), kw)
            self.assertFalse(os.path.exists(os.path.join(d["path"], "dacha-u-morya")))
            # with a description: the first turn asks for CLAUDE.md in the new folder, in the project's place
            r = await self.p.api_create("Огород", how="describe", about="Грядки и полив", parent=up["path"] + "/Code", model="haiku")
            dest = os.path.join(up["path"], "Code", "ogorod")
            self.assertEqual(drive.call_args.args[1:3], (dest, N.describe_prompt("Огород", "Грядки и полив")))
            self.assertEqual((drive.call_args.kwargs["pkey"], drive.call_args.kwargs["model"]), (pultd.sanitize(dest), "haiku"))
            self.assertEqual(self.p.live[r["sid"]].title, "CLAUDE.md по описанию")
            # empty with a first task: started as "+" does
            r = await self.p.api_create("Третий", text="Сделай README", parent=d["path"])
            self.assertEqual(drive.call_args.args[1:3], (os.path.join(d["path"], "tretiy"), "Сделай README"))
            self.assertIn("sid", r)

    async def test_new_project_clone(self):
        # a clone is a job: the app polls it; done — the project is made as an empty one is; a failed clone leaves
        # nothing; a big repository is asked about first
        if not shutil.which("git"):
            self.skipTest("no git")
        root = TMP / ("home-" + self._testMethodName)
        (root / "Documents").mkdir(parents=True)
        origin = TMP / "origin-repo"
        subprocess.run(["git", "init", "-q", str(origin)], check=True)
        (origin / "README.md").write_text("hi\n")
        subprocess.run(["git", "-C", str(origin), "-c", "user.name=t", "-c", "user.email=t@t", "add", "."], check=True)
        subprocess.run(["git", "-C", str(origin), "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "init"], check=True)
        local = lambda link: (str(origin), "origin-repo", None) if link == "ok" else None if link == "nope" else (str(TMP / "none"), "none", None)
        with mock.patch.object(pult_api, "NEW_ROOT", root), mock.patch.object(pultd.N, "repo", local), \
                mock.patch.object(self.p, "drive", mock.AsyncMock()):
            r = await self.p.api_create(how="clone", link="ok")
            self.assertIn("job", r)
            # Home opens while a clone runs, and after it (one name for clones and `pult run` tasks broke it for an
            # hour, before 0.18.5)
            self.assertEqual((await self.p.api_overview())["jobs"], [])
            await until(lambda: self.p.clones[r["job"]]["state"] != "run", timeout=20)
            j = await self.p.api_job(r["job"])
            dest = os.path.join(os.path.realpath(root / "Documents"), "origin-repo")
            self.assertEqual((j["state"], j["pkey"], j["git"]), ("done", pultd.sanitize(dest), True))
            self.assertEqual(Path(dest, "README.md").read_text(), "hi\n")
            self.assertEqual(self.store.topic(j["pkey"])["name"], "origin-repo")
            self.assertEqual((await self.p.api_overview())["jobs"], [])
            r = await self.p.api_create(title="Пропал", how="clone", link="gone")
            await until(lambda: self.p.clones[r["job"]]["state"] != "run", timeout=20)
            j = await self.p.api_job(r["job"])
            self.assertEqual(j["state"], "fail")
            self.assertTrue(j["error"].startswith("Не получилось склонировать: "), j["error"])
            self.assertFalse(os.path.exists(os.path.join(os.path.dirname(dest), "propal")))
            with self.assertRaises(ValueError):
                await self.p.api_job("nope")
            with mock.patch.object(self.p, "repo_mb", mock.AsyncMock(return_value=2048)):
                self.assertEqual(await self.p.api_create(title="Большой", how="clone", link="ok"), {"big": 2048})
                r = await self.p.api_create(title="Большой", how="clone", link="ok", big=True)
                await until(lambda: self.p.clones[r["job"]]["state"] != "run", timeout=20)
                self.assertEqual(self.p.clones[r["job"]]["state"], "done")

    async def test_new_project_button(self):
        # Telegram: "which project" for a text from General ends with "＋ New project" into the app — only with the app
        await self.p.cmd_projects(None, "new", ("текст", 5))
        self.assertNotIn("newproject", self.fake.of("sendMessage")[-1].get("reply_markup", ""))
        self.p.env.update(PULT_APP_LINK="https://t.me/b/pult")
        await self.p.cmd_projects(None, "new", ("текст", 5))
        rows = json.loads(self.fake.of("sendMessage")[-1]["reply_markup"])["inline_keyboard"]
        self.assertEqual(rows[-1], [{"text": "＋ Новый проект", "url": "https://t.me/b/pult?startapp=newproject"}])

    async def test_files_from_telegram(self):
        # stage F: a file in a project topic lands in <project>/inbox/<date>/ under its own name and goes on with its
        # caption; without words it waits for the next message (👌); an album goes once; over 20 MB — a line back
        proj = TMP / ("proj-" + self._testMethodName)
        (proj / ".git").mkdir(parents=True)
        self.store.set_topic(PKEY, str(proj), "proj", 77)
        base = {"from": {"id": OWNER}, "chat": {"id": CHAT}, "message_thread_id": 77, "is_topic_message": True}
        doc = lambda name, size=10, **kw: {"document": dict({"file_id": "BQAC" + name, "file_name": name, "file_size": size}, **kw)}
        self.fake.file_bytes = b"%PDF-1.7 test"
        day = F.drop_dir(str(proj))
        with mock.patch.object(self.p, "route", mock.AsyncMock()) as route, mock.patch.object(pultd, "ALBUM_WAIT", 0.05):
            await self.p.on_message(dict(base, message_id=31, caption="Сравни с прошлым", **doc("Отчёт [v2].pdf")))
            body = route.call_args.args[3]
            self.assertTrue(body.startswith("Сравни с прошлым\n\n[Attachment from Telegram: "))
            self.assertEqual(R.attachments(body), ("Сравни с прошлым", [os.path.join(day, "Отчёт [v2].pdf")]))
            self.assertEqual(Path(day, "Отчёт [v2].pdf").read_bytes(), b"%PDF-1.7 test")
            self.assertIn("/inbox/", (proj / ".git" / "info" / "exclude").read_text())
            # no words: the files wait; the next text takes them along; a photo gets its own name
            route.reset_mock()
            await self.p.on_message(dict(base, message_id=32, **doc("Отчёт [v2].pdf")))
            await self.p.on_message(dict(base, message_id=33, photo=[{"file_id": "AgAD", "file_size": 10}]))
            route.assert_not_called()
            await until(lambda: len(self.fake.of("setMessageReaction")) == 2)
            await self.p.on_message(dict(base, message_id=34, text="Что тут нового?"))
            text, paths = R.attachments(route.call_args.args[3])
            self.assertEqual(text, "Что тут нового?")
            self.assertEqual([os.path.basename(x) for x in paths][0], "Отчёт [v2] (2).pdf")
            self.assertTrue(os.path.basename(paths[1]).startswith("photo-") and paths[1].endswith(".jpg"))
            route.reset_mock()
            await self.p.on_message(dict(base, message_id=35, text="И ещё"))          # taken once
            self.assertEqual(R.attachments(route.call_args.args[3])[1], [])
            # an album: three messages, the caption on the second; it goes once, after the last file
            route.reset_mock()
            for i, (name, cap) in enumerate([("a.pptx", None), ("b.docx", "Собери в одну"), ("c.xlsx", None)]):
                kw = dict(base, message_id=40 + i, media_group_id="g1", **doc(name))
                if cap:
                    kw["caption"] = cap
                await self.p.on_message(kw)
            route.assert_not_called()
            await until(lambda: route.called)
            text, paths = R.attachments(route.call_args.args[3])
            self.assertEqual((text, [os.path.basename(x) for x in paths]), ("Собери в одну", ["a.pptx", "b.docx", "c.xlsx"]))
            self.assertEqual(route.call_args.args[4], 41)                             # the message with the caption
            # too big for a bot: nothing downloaded, the owner is told, Claude is told what didn't come
            route.reset_mock()
            n = len(self.fake.of("getFile"))
            await self.p.on_message(dict(base, message_id=50, caption="Глянь", **doc("huge.zip", 25 * 1024 * 1024)))
            self.assertEqual(len(self.fake.of("getFile")), n)
            self.assertIn("huge.zip — 25 МБ", self.texts()[-1])
            self.assertIn("did not come: huge.zip, 25 MB", route.call_args.args[3])
        # in General, outside any project: Pult's own inbox, as before
        with mock.patch.object(self.p, "route", mock.AsyncMock()) as route:
            await self.p.on_message({"from": {"id": OWNER}, "chat": {"id": CHAT}, "message_id": 60, "caption": "x", **doc("g.pdf")})
            self.assertIn(str(pultd.HOME / "inbox"), route.call_args.args[3])

    async def test_send_files(self):
        # pult send: the session named in the command's environment → its project topic; only the project's files,
        # nothing like a secret; the app's "To Telegram" goes the same way
        proj = TMP / ("proj-" + self._testMethodName)
        (proj / "out").mkdir(parents=True)
        (proj / "out" / "Итог.docx").write_bytes(b"PK-docx")
        (proj / "deck.pptx").write_bytes(b"PK-pptx")
        (proj / ".env").write_text("TOKEN=1")
        self.store.set_topic(PKEY, str(proj), "proj", 77)
        self.store.touch_session(SID, PKEY, path=str(proj))
        res = await self.p.on_send({"sid": SID, "paths": [str(proj / "out" / "Итог.docx"), str(proj / ".env"), "/etc/hosts"],
                                    "caption": "Готово"})
        self.assertEqual(res["sent"], ["Итог.docx"])
        self.assertEqual(res["refused"], [[".env", "похоже на ключи или настройки — не отправляю"], ["hosts", "не в папке этого проекта"]])
        d = self.fake.of("sendDocument")[-1]
        self.assertEqual((d["_name"], d["_bytes"], d["caption"], d["message_thread_id"], d["chat_id"]),
                         ("Итог.docx", b"PK-docx", "Готово", "77", str(CHAT)))
        self.assertEqual(self.store.msg(intro_id_of(self.fake, d))["sid"], SID)     # a reply to the file goes to the session
        self.assertEqual(await self.p.on_send({"sid": "nope", "paths": ["a"]}), {"error": "Пульт не знает этой сессии или папки её проекта"})
        self.assertIn("error", await self.p.on_send({"sid": SID, "paths": ["x"] * 11}))
        r = await self.p.api_send_files(SID, ["deck.pptx"])
        self.assertEqual(r["sent"], ["deck.pptx"])
        with self.assertRaises(ValueError):
            await self.p.api_send_files(SID, [".env"])
        # the screen of a turn's files (stage F4): as one archive — the folders kept, a secret left out, packed files
        # stored as they are; nothing stays in the temporary folder
        tmps = lambda: sorted(Path(tempfile.gettempdir()).glob("pult-zip-*"))
        before = tmps()
        r = await self.p.api_send_files(SID, ["out/Итог.docx", "deck.pptx", ".env"], zip=True)
        self.assertEqual((r["sent"], r["refused"]), ([os.path.join("out", "Итог.docx"), "deck.pptx"],
                                                     [[".env", "похоже на ключи или настройки — не отправляю"]]))
        self.assertRegex(r["zip"], r"^%s-\d{4}-\d\d-\d\d-\d{4}\.zip$" % re.escape(proj.name))
        d = self.fake.of("sendDocument")[-1]
        self.assertEqual((d["_name"], d["caption"], d["message_thread_id"]), (r["zip"], "Файлов: 2", "77"))
        with zipfile.ZipFile(io.BytesIO(d["_bytes"])) as z:
            self.assertEqual(sorted(z.namelist()), ["deck.pptx", "out/Итог.docx"])
            self.assertEqual(z.read("out/Итог.docx"), b"PK-docx")
            self.assertEqual(z.getinfo("deck.pptx").compress_type, zipfile.ZIP_STORED)
        self.assertEqual(tmps(), before)
        # more than ten: one archive anyway (decision Q44)
        for i in range(11):
            (proj / ("n%02d.txt" % i)).write_text("x" * 100)
        n = len(self.fake.of("sendDocument"))
        r = await self.p.api_send_files(SID, ["n%02d.txt" % i for i in range(11)])
        self.assertEqual((len(r["sent"]), len(self.fake.of("sendDocument")) - n), (11, 1))
        self.assertTrue(r["zip"])
        # too much to pack — refused before packing; an archive that outgrows what Telegram takes — refused, nothing sent
        with mock.patch.object(F, "ZIP_RAW_MAX", 150), self.assertRaises(ValueError) as e:
            await self.p.api_send_files(SID, ["n00.txt", "n01.txt"], zip=True)
        self.assertIn("слишком много для одного архива", str(e.exception))
        with mock.patch.object(F, "TG_SEND_MAX", 150), self.assertRaises(ValueError) as e:
            await self.p.api_send_files(SID, ["n00.txt", "n01.txt"], zip=True)
        self.assertIn("архив выходит больше", str(e.exception))
        self.assertEqual((len(self.fake.of("sendDocument")) - n, tmps()), (1, before))
        # the command itself, as Claude runs it: the session comes from Claude Code's environment
        # a pipe in the system's code page, as on Windows: the Russian answer must not stop the command (Actions 2026-10-23)
        env = plain_env(PULT_SOCK=os.environ["PULT_SOCK"], CLAUDE_CODE_SESSION_ID=SID, PULT_LANG="ru", PYTHONIOENCODING="cp1252")
        p = await asyncio.create_subprocess_exec(sys.executable, str(HERE / "pultctl.py"), "send", "deck.pptx", "-m", "Вот",
                                                 cwd=str(proj), env=env, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        out, err = await p.communicate()
        self.assertEqual((p.returncode, out.decode().strip()), (0, "отправлено: deck.pptx"), err)
        self.assertEqual(self.fake.of("sendDocument")[-1]["caption"], "Вот")
        env.pop("CLAUDE_CODE_SESSION_ID")
        p = await asyncio.create_subprocess_exec(sys.executable, str(HERE / "pultctl.py"), "send", "deck.pptx", cwd=str(proj),
                                                 env=env, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        await p.communicate()
        self.assertEqual(p.returncode, 2)

    async def test_file_view(self):
        # a link in Claude's words tapped in the app (stage F5): the project's file or folder, by Telegram's rule —
        # inside the project, nothing like a secret; a link in a file's own page counts from that file's folder
        proj = TMP / ("proj-" + self._testMethodName)
        (proj / "docs" / "img").mkdir(parents=True)
        (proj / ".git").mkdir()
        (proj / "docs" / "handoff.md").write_text("# Передача\n\n[CLAUDE.md](../CLAUDE.md)\n")
        (proj / "CLAUDE.md").write_text("правила\n")
        png = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==")
        (proj / "docs" / "img" / "a b.png").write_bytes(png)
        (proj / "page.html").write_text("<p>привет</p>")
        (proj / "bin.dat").write_bytes(b"\x00\x01\x02")
        (proj / "cp1251.txt").write_bytes("привет".encode("cp1251"))
        (proj / "empty.txt").write_text("")
        (proj / "crlf.txt").write_bytes(b"a\r\nb\r\n")                       # Windows line ends: no \r at each line's end
        (proj / "long.txt").write_text("".join("строка %d\n" % i for i in range(100)))
        (proj / ".env").write_text("TOKEN=1")
        (proj / ".git" / "config").write_text("[core]")
        (proj / ".DS_Store").write_bytes(b"x")
        self.store.set_topic(PKEY, str(proj), "proj", 77)
        self.store.touch_session(SID, PKEY, path=str(proj))
        f = self.p.api_file
        r = await f(SID, "docs/handoff.md")
        self.assertEqual((r["p"], r["kind"], r["text"][:10], r["cut"], r["project"]), ("docs/handoff.md", "md", "# Передача", False, "proj"))
        r = await f(SID, "../CLAUDE.md", base="docs")
        self.assertEqual((r["p"], r["kind"], r["text"]), ("CLAUDE.md", "md", "правила\n"))
        r = await f(SID, "docs/img/a%20b.png")
        self.assertEqual((r["p"], r["kind"], r["pic"], base64.b64decode(r["data"])), ("docs/img/a b.png", "pic", "png", png))
        self.assertEqual((await f(SID, str(proj / "page.html")))["kind"], "html")          # an absolute path inside the project
        self.assertEqual((await f(SID, "file://" + str(proj / "CLAUDE.md")))["p"], "CLAUDE.md")
        self.assertEqual([(await f(SID, n))["kind"] for n in ("bin.dat", "cp1251.txt", "empty.txt")], ["other", "other", "text"])
        self.assertEqual((await f(SID, "crlf.txt"))["text"], "a\nb\n")
        with mock.patch.object(F, "SHOW_TEXT_MAX", 40):                                   # a long text: its start, cut at a line
            r = await f(SID, "long.txt")
        self.assertEqual((r["cut"], r["text"]), (True, "строка 0\nстрока 1\n"))
        with mock.patch.object(F, "SHOW_PIC_MAX", 10):                                    # a picture too big for the frame
            self.assertEqual((await f(SID, "docs/img/a b.png"))["kind"], "other")
        # folders: folders first, then by name; no temporary files; secrets listed but locked
        r = await f(SID, "")
        self.assertEqual((r["p"], r["kind"], r["n"]), ("", "dir", 10))
        self.assertEqual([(e["n"], e["dir"], e["lock"]) for e in r["entries"][:3]], [(".git", True, True), ("docs", True, False), (".env", False, True)])
        self.assertNotIn(".DS_Store", [e["n"] for e in r["entries"]])
        r = await f(SID, "docs/")
        self.assertEqual((r["p"], [e["n"] for e in r["entries"]]), ("docs", ["img", "handoff.md"]))
        # refused: outside the project, like a secret, gone, an unknown session
        for p_, why in (("/etc/hosts", "не в папке этого проекта"), ("../x", "не в папке этого проекта"),
                        ("../../CLAUDE.md", "не в папке этого проекта"), (".env", "не показываю"), (".git", "не показываю"),
                        (".git/config", "не показываю"), ("nope.md", "такого файла нет")):
            with self.assertRaises(ValueError, msg=p_) as e:
                await f(SID, p_, base="docs" if p_.startswith("../../") else "")
            self.assertIn(why, str(e.exception), p_)
        if os.name != "nt":                                   # a link out of the project (Windows: links need rights)
            (proj / "link.md").symlink_to("/etc/hosts")
            with self.assertRaises(ValueError) as e:
                await f(SID, "link.md")
            self.assertIn("не в папке этого проекта", str(e.exception))
        with self.assertRaises(ValueError) as e:
            await f("00000000-0000-4000-8000-000000000000", "CLAUDE.md")
        self.assertIn("Пульт не знает этой сессии", str(e.exception))

    async def test_turn_files_and_context(self):
        # a turn's files ride with its outcome (the app offers them to Telegram); a session learns about pult send at
        # its start — from the hook, only while the daemon runs
        proj = TMP / ("proj-" + self._testMethodName)
        proj.mkdir()
        self.store.set_topic(PKEY, str(proj), "proj", 77)
        t0 = time.time() - 5
        (proj / "made.pdf").write_bytes(b"x" * 2048)
        lv = self.p.live_of(SID, PKEY)
        files, n = await self.p.files_of_turn(lv, types.SimpleNamespace(started=t0))
        self.assertEqual(([f["p"] for f in files], files[0]["size"], n), (["made.pdf"], 2048, 1))
        self.assertEqual(await self.p.files_of_turn(lv, None), ([], 0))
        os.utime(proj / "made.pdf", (t0 - 60, t0 - 60))
        # a turn that made files (stage F4): kept, its outcome carries the line to them, the result's button opens that
        # very turn; the screen goes ‹ › between kept turns and shows each file as it is now
        self.p.env.update(PULT_APP_LINK="https://t.me/b/pult")
        await run_hook(ev("UserPromptSubmit", prompt="Сделай отчёт"))
        (proj / "out").mkdir()
        (proj / "out" / "report.md").write_text("# Отчёт")
        await run_hook(ev("Stop", last_assistant_message="Готово.", background_tasks=[]))
        await until(lambda: (self.p.attn.rec.get(SID) or {}).get("turn_files"))
        tf = self.p.attn.rec[SID]["turn_files"]
        self.assertEqual((tf["n"], tf["size"]), (1, len("# Отчёт".encode())))
        await until(lambda: any("f_%s_%d" % (SID, tf["id"]) in (m.get("reply_markup") or "") for m in self.fake.of("sendMessage")))
        res = [m for m in self.fake.of("sendMessage") if "f_%s_" % SID in (m.get("reply_markup") or "")][-1]
        # the turn's files and Details in one row: both open the app
        self.assertIn([{"text": "📎 Файлы (1)", "url": "https://t.me/b/pult?startapp=f_%s_%d" % (SID, tf["id"])},
                       {"text": "Подробнее", "url": "https://t.me/b/pult?startapp=s_" + SID}],
                      json.loads(res["reply_markup"])["inline_keyboard"])
        self.assertLessEqual(len("f_%s_%d" % (SID, tf["id"])), 64)                      # Telegram's startapp limit
        got = await self.p.api_turn_files(SID)
        self.assertEqual((got["id"], [f["p"] for f in got["files"]], got["prev"], got["next"], got["project"]),
                         (tf["id"], [os.path.join("out", "report.md")], None, None, "proj"))
        tid2 = self.store.add_turn(SID, PKEY, time.time() - 1, 1.0, [{"p": "deck.pptx", "size": 5, "mt": time.time()},
                                                                     {"p": os.path.join("out", "report.md"), "size": 1, "mt": time.time()}], 2)
        got = await self.p.api_turn_files(SID)
        self.assertEqual((got["id"], got["prev"], got["next"], got["n"]), (tid2, tf["id"], None, 2))
        self.assertEqual([(f["p"], f["gone"], f["size"]) for f in got["files"]],
                         [("deck.pptx", True, 5), (os.path.join("out", "report.md"), False, len("# Отчёт".encode()))])
        self.assertEqual((await self.p.api_turn_files(SID, str(tf["id"])))["next"], tid2)
        self.assertEqual(await self.p.api_turn_files("00000000-0000-4000-8000-000000000000"), {"id": None, "files": []})
        with self.assertRaises(ValueError):
            await self.p.api_turn_files("../x")
        for i in range(pult_tg.TURNS_KEPT + 3):                         # kept: the latest 50 per session
            self.store.add_turn("00000000-0000-4000-8000-000000000001", PKEY, 0, 0, [], 0)
        self.assertEqual(self.store.db.execute("SELECT count(*) FROM turns WHERE sid LIKE '%0001'").fetchone()[0], pult_tg.TURNS_KEPT)
        out = await run_hook(ev("SessionStart", source="startup"), extra_env={"PULT_SOCK": os.environ["PULT_SOCK"]})
        ctx = json.loads(out)["hookSpecificOutput"]
        self.assertEqual(ctx["hookEventName"], "SessionStart")
        self.assertIn("pult send", ctx["additionalContext"])
        self.assertIn("multiSelect: true", ctx["additionalContext"])      # ticks on the phone where options combine
        self.assertEqual(await run_hook(ev("SessionStart", source="startup"), extra_env={"PULT_SOCK": str(TMP / "нет.sock")}), "")
        self.assertEqual(await run_hook(ev("Stop"), extra_env={"PULT_SOCK": os.environ["PULT_SOCK"]}), "")

    async def test_project_inbox_pictures(self):
        # the app shows a picture from a project's inbox in the chat; nothing outside it, nothing but pictures
        proj = TMP / ("proj-" + self._testMethodName)
        day = Path(F.drop_dir(str(proj)))
        day.mkdir(parents=True)
        png = b"\x89PNG\r\n\x1a\n" + b"\0" * 32
        (day / "план 1.png").write_bytes(png)
        (day / "notes.pdf").write_bytes(b"%PDF")
        self.store.set_topic(PKEY, str(proj), "proj", 77)
        att = pultd.PW.inbox_name(str(day / "план 1.png"))
        self.assertEqual(att, {"name": day.name + "/план 1.png", "image": True, "inbox": True, "pkey": pultd.sanitize(str(proj))})
        self.store.set_topic(att["pkey"], str(proj), "proj", 78)
        self.assertEqual(base64.b64decode((await self.p.api_inbox(att["name"], att["pkey"]))["data"]), png)
        for name in [day.name + "/notes.pdf", day.name + "/../../x.png", "../план 1.png", "2026-10/план 1.png"]:
            with self.assertRaises(ValueError, msg=name):
                await self.p.api_inbox(name, att["pkey"])
        self.assertEqual(pultd.PW.inbox_name("/a/inbox/2026-10/app-1.jpg"), {"name": "2026-10/app-1.jpg", "image": True, "inbox": True})
        self.assertEqual(pultd.PW.inbox_name("/x/Downloads/a.pdf"), {"name": "a.pdf", "image": False, "inbox": False})
        # a document from the app goes to the project's inbox too
        body = self.p.with_uploads("Посмотри", [{"name": "смета.xlsx", "data": base64.b64encode(b"PK-xlsx").decode()}], str(proj))
        self.assertEqual(Path(R.attachments(body)[1][0]).read_bytes(), b"PK-xlsx")
        self.assertEqual(Path(R.attachments(body)[1][0]).parent, day)

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
        self.p.driven[SID] = SimpleNamespace(busy=False, queued=None, bg=set(), q=asyncio.Queue(), client=client, want_model=None,
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

    async def test_default_choice(self):
        # Settings → Model and effort: Pult's own default for the sessions it starts; a session's own choice wins, each
        # half on its own; "" — back to Claude Code's settings, which Pult only reads; VS Code tabs keep theirs
        from types import SimpleNamespace
        self.assertEqual(self.p.wanted(None, None), (None, None))              # nothing anywhere — Claude Code decides
        res = await self.p.api_prefs(model="opus", effort="high")
        self.assertEqual((res["model"], res["effort"]), ("opus", "high"))
        self.assertEqual(self.p.prefs()["model"], "opus")                       # kept
        with self.assertRaises(ValueError):
            await self.p.api_prefs(model="opus; rm -rf")
        with self.assertRaises(ValueError):
            await self.p.api_prefs(effort="turbo")
        self.assertEqual((self.p.prefs()["model"], self.p.prefs()["effort"]), ("opus", "high"))   # a refusal changes nothing
        self.assertEqual(self.p.wanted("sonnet", None), ("sonnet", "high"))
        # the SDK options alone, on a stand-in: a real Driven would start a claude process
        d = SimpleNamespace(d=self.p, sid=SID, path="/Users/x/proj", resume=None, fork=False, want_model=None, want_effort=None,
                            _wait_hook=None)
        o = pultd.Driven.options(d)
        self.assertEqual((o.model, o.effort), ("opus", "high"))                 # a new session with nothing picked
        d.want_effort = "low"
        o = pultd.Driven.options(d)
        self.assertEqual((o.model, o.effort), ("opus", "low"))                  # the session's own effort, the default model
        # the forms and the session's menu say what "Default" is; a session open on the computer has Claude Code's
        self.assertEqual((await self.p.api_projects())["choice"], {"model": "opus", "effort": "high"})
        self.store.touch_session(SID, PKEY, path="/Users/x/proj", driven=True)
        self.p.live_of(SID, PKEY).transcript = TP
        Path(TP).parent.mkdir(parents=True, exist_ok=True)
        Path(TP).write_text("")
        self.assertEqual((await self.p.api_session(SID))["default"], {"model": "opus", "effort": "high"})
        # "Default" on a running session goes to Pult's default, not to Claude Code's settings
        control = mock.AsyncMock(return_value={})
        client = SimpleNamespace(set_model=mock.AsyncMock(), _query=SimpleNamespace(_send_control_request=control))
        self.p.driven[SID] = SimpleNamespace(busy=False, queued=None, bg=set(), q=asyncio.Queue(), client=client, want_model="haiku",
                                             want_effort="max", task=SimpleNamespace(cancel=lambda: None))
        await self.p.api_model(SID, "", "")
        client.set_model.assert_awaited_once_with("opus")
        control.assert_awaited_once_with({"subtype": "apply_flag_settings", "settings": {"effortLevel": "high"}})
        self.assertEqual((self.p.driven[SID].want_model, self.p.driven[SID].want_effort), (None, None))   # follows the default
        del self.p.driven[SID]
        # back to Claude Code's settings: they are read for Settings, never written
        res = await self.p.api_prefs(model="", effort=None)
        self.assertEqual((res["model"], res["effort"]), (None, None))
        cc = TMP / "cc-settings.json"
        cc.write_text(json.dumps({"effortLevel": "xhigh", "model": "x y", "hooks": {}}))
        with mock.patch.object(pultd, "SETTINGS", cc):
            self.assertEqual((await self.p.api_settings())["cc"], {"model": None, "effort": "xhigh"})   # a bad name isn't shown
            cc.write_text("{broken")
            self.assertEqual(pultd.Pult.cc_choice(), {"model": None, "effort": None})
        with mock.patch.object(pultd, "SETTINGS", TMP / "none.json"):
            self.assertEqual(pultd.Pult.cc_choice(), {"model": None, "effort": None})

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
        old, pult_driven.SDK_LINE_MAX = pult_driven.SDK_LINE_MAX, 1024 * 1024
        try:
            d = D(self.p, SID, str(TMP))
            d.q.put_nowait(("глянь", None))
            await asyncio.wait_for(d.task, 20)        # the old limit: the reader fails and the session ends
            # after a reader error the SDK ends the process but leaves its stdout pipe to the garbage collector:
            # collect while the loop still runs (in the daemon the collector does it in its own time); not `del`: the
            # lambda above holds the name, and a deleted one reads as undefined to the linter
            d = None
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", ResourceWarning)
                gc.collect()
                await asyncio.sleep(0.1)
                gc.collect()
        finally:
            pult_driven.SDK_LINE_MAX = old

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
            self.p.driven[SID2] = SimpleNamespace(busy=True, queued=None, bg=set(), q=asyncio.Queue(), client=None,
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
        self.p.driven[SID2] = SimpleNamespace(busy=True, queued=None, bg=set(), q=asyncio.Queue(), path="/Users/x/proj", client=None,
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
        self.assertIn("Claude Code", prompt)                    # a sentence in the language spoken, with the terms
        self.assertNotIn("proj", prompt)                        # folder names stay out
        self.store.put("stt_words", "Орион, Кубер")            # the owner's own words go last, all within Groq's limit
        self.assertTrue(self.p.stt_prompt().endswith("Ещё слова: Орион, Кубер."), self.p.stt_prompt())
        self.store.put("stt_words", "Орион " * 200)
        self.assertLessEqual(len(self.p.stt_prompt().encode()), STT.PROMPT_MAX)
        stt.text = "сделай деплой. Продолжение следует..."   # Whisper's phantom after a pause is cut off
        with mock.patch.object(self.p, "drive", mock.AsyncMock()) as drive:
            await self.p.on_message(dict(base, message_id=26, text="/new"))
            await self.p.on_message(dict(base, message_id=27, **voice))
            self.assertTrue(drive.call_args.args[2].startswith("сделай деплой.\n\n[Spoken message"), drive.call_args.args[2])
        stt.text = "Продолжение следует..."                    # nothing but a phantom — "nothing heard", no turn
        with mock.patch.object(self.p, "drive", mock.AsyncMock()) as drive:
            await self.p.on_message(dict(base, message_id=28, **voice))
            drive.assert_not_called()
        self.assertEqual(self.texts()[-1], I.T("stt.empty", "ru"))
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
        self.assertEqual(len(self.fake.of("getFile")), 4)       # no key, too big — nothing was downloaded
        # Groq's own words in the reason are text, not Telegram's HTML: "<" broke the message (review 2026-10-27, М12)
        stt.transcribe = mock.AsyncMock(side_effect=STT.SttError("stt.e.groq", msg="<html> & so on"))
        with mock.patch.object(self.p, "drive", mock.AsyncMock()) as drive:
            await self.p.on_message(dict(base, message_id=29, **voice))
            drive.assert_not_called()
        self.assertIn("Groq: &lt;html&gt; &amp; so on", self.texts()[-1])
        self.assertEqual(self.p.stt_why(STT.SttError("stt.e.groq", msg="<x>")), "Groq: <x>")   # the app shows text as text

    async def test_api_stt(self):
        # a recording from the app → words; nothing heard, junk, no key — an error in words
        import base64

        class FakeStt:
            async def transcribe(self, blob, kind, language=None, prompt=None):
                return "привет мир" if blob.startswith(b"\x1aE\xdf\xa3") else ""
        self.p.stt = FakeStt()
        webm = base64.b64encode(b"\x1aE\xdf\xa3" + b"\0" * 30).decode()
        self.assertEqual(await self.p.api_stt(webm, "audio/webm;codecs=opus"), {"text": "привет мир"})
        notes = {"secs": 7.4, "ready": 640, "voice": 0, "first": -31.6, "peak": -12.2}
        with mock.patch.object(pult_api, "log") as lg:
            self.assertEqual(await self.p.api_stt(webm, "audio/webm", notes=notes), {"text": "привет мир"})
        self.assertIn("0 KB, 7 s, sound 0.64 s after the tap, voice from +0.0 s, first second -32 dB, loudest -12 dB "
                      "→ 10 characters", lg.call_args.args[0])
        self.assertEqual(self.p.stt_notes({"secs": "x", "ready": -5, "voice": None, "peak": 99}), ", no voice heard")
        self.assertEqual((self.p.stt_notes(None), self.p.stt_notes("junk")), ("", ""))
        with self.assertRaises(ValueError) as cm:
            await self.p.api_stt(base64.b64encode(b"\0" * 30).decode(), "audio/webm")
        self.assertEqual(str(cm.exception), I.T("stt.empty", "ru"))
        with self.assertRaises(ValueError):
            await self.p.api_stt("%%%", "audio/webm")
        self.p.stt = None
        with self.assertRaises(ValueError) as cm:
            await self.p.api_stt(webm, "audio/webm")
        self.assertIn("pult stt", str(cm.exception))
        self.assertEqual(self.p.stt_state(), {"on": False, "lang": "ru", "words": ""})
        # the app shows the microphone only when there is a key: the flag rides with the projects (and the session)
        with mock.patch.object(self.p, "list_projects", lambda known: []):
            self.assertEqual(await self.p.api_projects(), {"projects": [], "stt": False, "create": True,
                                                       "choice": {"model": None, "effort": None}})
            self.p.stt = FakeStt()
            self.assertTrue((await self.p.api_projects())["stt"])

    async def test_api_stt_words(self):
        # the owner's own words: squeezed, trimmed, capped; "" clears; Settings show them
        self.assertEqual(await self.p.api_stt_words("  Орион,\n  Кубер ,, Claude  Code;"), {"words": "Орион, Кубер, Claude Code"})
        self.assertEqual(self.p.stt_state()["words"], "Орион, Кубер, Claude Code")
        long = (await self.p.api_stt_words("слово " * 100))["words"]
        self.assertTrue(len(long) <= pult_api.STT_WORDS_MAX and long.endswith(" слово"), long[-12:])
        self.assertEqual(await self.p.api_stt_words(""), {"words": ""})
        self.assertEqual((await self.p.api_settings())["stt"]["words"], "")

    async def test_api_stt_key(self):
        # the key from the app's settings: checked with Groq, written to the settings file (600), in force at once;
        # "" removes it; a key written by `pult stt` while the daemon runs is noticed by the file's time
        env = Path(os.environ["PULT_ENV"])
        env.write_text("PULT_BOT_TOKEN=T\n")
        good = "gsk_" + "a" * 40
        with mock.patch.object(STT.Stt, "check", mock.AsyncMock()) as check, \
                mock.patch.object(STT.Stt, "aclose", mock.AsyncMock()) as closed:
            self.assertEqual(await self.p.api_stt_key(good), {"on": True})
        check.assert_awaited_once()
        closed.assert_awaited_once()                                   # the client made only to check the key (М11)
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
        old = STT.Stt("gsk_" + "d" * 40)
        self.p.stt = old
        with mock.patch.object(old, "aclose", mock.AsyncMock()) as closed, mock.patch.object(pultd, "STT_DROP", 0):
            self.assertEqual(self.p.stt_state(), {"on": True, "lang": "auto", "words": ""})
            for _ in range(3):
                await asyncio.sleep(0)
        closed.assert_awaited_once()                                   # the one it replaced, a while later (М11)
        self.assertEqual((self.p.stt.key, self.p.stt.model), ("gsk_" + "c" * 40, STT.MODEL))
        env.write_text("PULT_BOT_TOKEN=T\nPULT_STT_KEY=gsk_%s\nPULT_STT_MODEL=whisper-large-v3-turbo\n" % ("c" * 40))
        os.utime(env, (time.time() + 10, time.time() + 10))
        self.p.stt_state()                                              # the model back to turbo — by the same file
        self.assertEqual(self.p.stt.model, "whisper-large-v3-turbo")
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
        dr = self.p.driven[SID] = SimpleNamespace(q=q, busy=False, queued=None, asking=False, bg=set(), client=None,
                                                  task=SimpleNamespace(cancel=lambda: None))
        dr.say = types.MethodType(pultd.Driven.say, dr)
        png = base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"\0" * 20).decode()
        bad = base64.b64encode(b"#!/bin/sh\nrm -rf /\n").decode()
        res = await self.p.api_send(SID, "Look", files=[{"name": "a.png", "data": png}, {"name": "x.sh", "data": bad}, {"data": "%%%"}])
        self.assertEqual((res["ok"], res["how"], self.p.outbox[SID][-1]["id"]), (True, "session", res["out"]))
        text, _ = q.get_nowait()
        self.assertTrue(text.startswith("Look\n\n[Attachment from the Pult app: "), text)
        path = re.search(r"\[Attachment from the Pult app: ([^\]]+)\]", text).group(1)
        self.assertTrue(path.startswith(str(TMP / "inbox")) and path.endswith(".png"), path)
        # what couldn't be taken is said in the message itself — Claude and the owner both see it (review 2026-10-27, A4)
        self.assertIn("[Pult: 2 attachment(s) from the app couldn't be taken", text)
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
            busy=True, asking=False, queued=None, sid=SID, d=self.p, bg=set(), q=asyncio.Queue(), task=SimpleNamespace(cancel=lambda: None),
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
        pultd.VEHI = (0.3, 0.5)          # the second milestone well inside the 0.8 s that says none came after 🔕
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
        self.p.driven[SID] = SimpleNamespace(running=False, bg=set(), task=SimpleNamespace(cancel=lambda: cancelled.append(1)))
        await run_hook(ev("SessionStart", source="resume"))
        await until(lambda: cancelled == [1])           # the hook leaves without waiting for the daemon (Т8)
        self.assertFalse(self.p.live[SID].driven)
        # a background task lived in Pult's process and was closed with it; the owner is told which one
        self.p.live[SID].bg = [{"id": "b1", "description": "Сборка"}]
        self.p.driven[SID] = SimpleNamespace(running=False, bg={"b1"}, task=SimpleNamespace(cancel=lambda: cancelled.append(2)))
        await run_hook(ev("UserPromptSubmit", prompt="на Маке"))
        await until(lambda: cancelled == [1, 2])
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

    async def test_background_task_ends_mid_turn(self):
        # a background task that ends while a turn runs: its note comes absorbed into that turn — its prompt_id — at the
        # turn's next step (tests/probe_bgmid.py, 2.1.300); it stayed in the session's list till the turn's end (2026-10-28)
        await run_hook(ev("UserPromptSubmit", prompt="Собери проект в фоне", prompt_id="p1"))
        await until(lambda: SID in self.p.live and self.p.live[SID].turn)
        await run_hook(ev("Stop", last_assistant_message="Запустил сборку", prompt_id="p1", background_tasks=[
            {"id": "b7", "type": "shell", "status": "running", "description": "Сборка проекта"}]))
        await until(lambda: self.p.live[SID].turn is None and self.p.live[SID].bg)
        await run_hook(ev("UserPromptSubmit", prompt="Пока собирается, поправь README", prompt_id="p2"))
        await until(lambda: self.p.live[SID].turn)
        t = self.p.live[SID].turn
        note = ("<task-notification>\n<task-id>b7</task-id>\n<status>completed</status>\n<summary>Background command "
                "\"Сборка проекта\" completed (exit code 0)</summary>\n</task-notification>")
        await run_hook(ev("UserPromptSubmit", prompt=note, prompt_id="p2"))
        await until(lambda: self.p.live[SID].bg == [])
        self.assertIs(self.p.live[SID].turn, t)                         # the owner's turn goes on
        ov = await self.p.api_overview()
        self.assertEqual([s["bg"] for s in ov["live"]], [[]])
        self.assertEqual(self.p.busy_report(), [])                      # a tab's session: nothing of Pult's own runs

    async def test_absorbed_prompt(self):
        # a message absorbed into the running turn (another session's SendMessage, the owner's mid-turn message) comes
        # with a UserPromptSubmit of its own, but with the turn's prompt_id (probe_midturn.py, 2.1.300 and 2.1.301):
        # the turn goes on and "working N" keeps counting — 2026-10-24 it showed "working 28 s" 19 min into a turn
        await run_hook(ev("UserPromptSubmit", prompt="Сделай большую работу", prompt_id="p1"))
        await until(lambda: SID in self.p.live and self.p.live[SID].turn)
        t0 = self.p.live[SID].turn
        run0 = self.p.live[SID].run
        await run_hook(ev("PostToolUse", tool_name="Bash", tool_input={"command": "make"}, prompt_id="p1"))
        await until(lambda: t0.n == 1)
        self.p.expect[SID] = 7                                      # a mid-turn message from Telegram (Driven.say)
        seen = []
        changed, self.p.changed = self.p.changed, lambda sid=None: (seen.append(sid), changed(sid))
        await run_hook(ev("UserPromptSubmit", prompt='<cross-session-message from="uds:/tmp/cc-socks/1.sock" '
                                                     'from-name="сосед">\nкоммить первым\n</cross-session-message>',
                          prompt_id="p1"))
        await until(lambda: t0.reply_to == 7)                       # its result answers the latest message
        self.assertIn(SID, seen)                                    # the app re-reads the session at once, not a step later
        self.p.changed = changed
        self.p.expect.pop(SID)
        await run_hook(ev("UserPromptSubmit", prompt="и ещё одно", prompt_id="p1"))
        await run_hook(ev("PostToolUse", tool_name="Bash", tool_input={"command": "make test"}, prompt_id="p1"))
        await until(lambda: t0.n == 2)
        self.assertIs(self.p.live[SID].turn, t0)
        self.assertIsNone(t0.done)
        self.assertEqual((self.p.live[SID].run, t0.prompt), (run0, "Сделай большую работу"))
        ov = await self.p.api_overview()
        self.assertEqual([(r["state"], r["since"]) for r in ov["board"][0]["rows"]], [("work", run0)])
        await run_hook(ev("Stop", last_assistant_message="Готово", prompt_id="p1", background_tasks=[]))
        await until(lambda: t0.done)
        self.assertEqual(t0.done[0], "✔️")                         # one turn, one result — none closed as "⏹"
        # the next prompt is a turn of its own: a new prompt_id, a new run
        await run_hook(ev("UserPromptSubmit", prompt="Теперь другое", prompt_id="p2"))
        await until(lambda: self.p.live[SID].turn and self.p.live[SID].turn.prompt == "Теперь другое")
        self.assertGreater(self.p.live[SID].run, run0)
        # Claude Code without prompt_id: as before, every prompt starts a turn
        t2 = self.p.live[SID].turn
        await run_hook(ev("UserPromptSubmit", prompt="без id"))
        await until(lambda: self.p.live[SID].turn is not t2)
        self.assertEqual(t2.done[0], "⏹")

    async def test_outbox(self):
        # ticks (Q56): a message on its way is "sent" until its own UserPromptSubmit — absorbed mid-turn (one per message,
        # in the order sent: probe_midturn.py two) or a turn of its own — makes it "read"; the app gets each as the
        # transcript will show it; a Telegram message marked ✍ (the session was busy) gets 👀 once Claude reads it
        Path(TP).parent.mkdir(parents=True, exist_ok=True)
        Path(TP).write_text(tline("user", "Большая работа") + "\n")
        await run_hook(ev("UserPromptSubmit", prompt="Большая работа", prompt_id="p1"))
        await until(lambda: SID in self.p.live and self.p.live[SID].turn)
        pic = "/x/proj/inbox/2026-10-24/plan.png"
        one = "и ещё вот это\n\n[Attachment from the Pult app: %s]" % pic
        a = self.p.out_add(SID, one, tg=55, react="✍")
        b = self.p.out_add(SID, "и второе")
        out = (await self.p.api_session(SID))["out"]
        self.assertEqual([(o["id"], o["st"], o["text"]) for o in out], [(a, "sent", "и ещё вот это"), (b, "sent", "и второе")])
        self.assertEqual(out[0]["att"], pultd.PW.user_item(one, None)["att"])      # as the transcript will show it
        self.assertIsInstance(out[0]["ts"], float)
        await run_hook(ev("UserPromptSubmit", prompt=one, prompt_id="p1"))
        await until(lambda: self.p.outbox[SID][0]["st"] == "read")
        await until(lambda: self.fake.of("setMessageReaction"))
        r = self.fake.of("setMessageReaction")[-1]
        self.assertEqual((str(r["message_id"]), '"👀"' in str(r["reaction"])), ("55", True))
        self.assertEqual(self.p.outbox[SID][1]["st"], "sent")
        await run_hook(ev("UserPromptSubmit", prompt="и второе", prompt_id="p1"))
        await until(lambda: self.p.outbox[SID][1]["st"] == "read")
        self.assertEqual(len(self.fake.of("setMessageReaction")), 1)          # no ✍ on it: nothing to change
        # a message that starts a turn of its own is read at once; words nobody sent from here touch nothing
        await run_hook(ev("Stop", last_assistant_message="Готово", prompt_id="p1", background_tasks=[]))
        c = self.p.out_add(SID, "Теперь другое")
        await run_hook(ev("UserPromptSubmit", prompt="Набрано на Маке", prompt_id="p2"))
        await until(lambda: self.p.live[SID].turn and self.p.live[SID].turn.prompt == "Набрано на Маке")
        self.assertEqual(self.p.outbox[SID][-1]["st"], "sent")
        await run_hook(ev("Stop", last_assistant_message="Ок", prompt_id="p2", background_tasks=[]))
        await run_hook(ev("UserPromptSubmit", prompt="Теперь другое", prompt_id="p3"))
        await until(lambda: self.p.outbox[SID][-1]["st"] == "read")
        # the session ends before a message is read: it is gone; a read one stays read
        d = self.p.out_add(SID, "не успел")
        await run_hook(ev("SessionEnd", reason="other"))
        await until(lambda: self.p.outbox[SID][-1]["st"] == "gone")
        self.assertEqual([o["st"] for o in self.p.outbox[SID]], ["read", "read", "read", "gone"])
        self.assertEqual([o["id"] for o in self.p.out_view(SID)], [a, b, c, d])
        # read ones leave the view after OUT_READ, gone ones after OUT_GONE
        for o in self.p.outbox[SID]:
            o["at"] -= pultd.OUT_READ + 1
        self.assertEqual([o["id"] for o in self.p.out_view(SID)], [d])

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

        async def fake_brief(prompt, reply, bg, lang, cwd, tags=None):
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

    async def test_result_hashtags(self):
        # T3 (Q65, Q94): a result in the project's topic ends with the task's tags as hashtags — after the text however
        # it folds; off in Settings — none; a task without tags — none
        self.store.tag_add(PKEY, "Прошивка", "Датчик филамента")
        self.store.set_session_tag(SID, PKEY, "Прошивка", "Датчик филамента", 0)
        await run_hook(ev("UserPromptSubmit", prompt="Почини датчик нити"))
        await until(lambda: SID in self.p.live and self.p.live[SID].turn)
        await run_hook(ev("Stop", last_assistant_message="Порог поднят, ложных срабатываний нет"))
        await until(lambda: [t for t in self.texts() if t.startswith("✅")])
        res = [t for t in self.texts() if t.startswith("✅")][-1]
        self.assertTrue(res.endswith("\n#прошивка #датчик_филамента"), res)
        self.assertIn("Порог поднят", res.split("#прошивка")[0])
        await self.p.api_prefs(hashtags=False)
        await run_hook(ev("UserPromptSubmit", prompt="Проверь ещё раз"))
        await until(lambda: self.p.live[SID].turn)
        await run_hook(ev("Stop", last_assistant_message="Всё на месте"))
        await until(lambda: len([t for t in self.texts() if t.startswith("✅")]) == 2)
        self.assertNotIn("#прошивка", [t for t in self.texts() if t.startswith("✅")][-1])
        self.assertEqual(self.p.hashtag_line("00000000-0000-0000-0000-000000000000"), "")

    async def test_tags(self):
        # stage T: a task gets its tags from the model as soon as its request is in, and again with the result line;
        # the owner's hashtag or correction is final; the rows, the project and the session carry them
        self.p._procs = (time.monotonic() + 1e6, None)
        Path(TP).parent.mkdir(parents=True, exist_ok=True)
        Path(TP).write_text(tline("user", "Почини калибровку") + "\n")
        self.store.tag_add(PKEY, "Прошивка", "Калибровка", ts=time.time() - 3 * 86400)
        self.store.tag_add(PKEY, "Корпус", None, own=True, ts=time.time() - 3 * 86400)     # the owner's: stays without tasks
        # without the model: no request for tags; an owner's hashtag still works — from the list, or a section of its own
        await run_hook(ev("UserPromptSubmit", prompt="Почини стол #калибровка"))
        await until(lambda: self.store.session_tag(SID) is not None)
        r = self.store.session_tag(SID)
        self.assertEqual((r["sec"], r["topic"], r["own"]), ("Прошивка", "Калибровка", 1))
        self.assertEqual(self.tagged, [])
        # the model on: a task without tags asks for them at once; the owner's tags are never overwritten
        await self.p.api_prefs(brief=True)
        sid2 = "22222222-3333-4444-5555-666666666666"
        asked = []

        async def model(text, lang, cwd):
            asked.append(text)
            return {"sec": "голос", "topic": "Распознавание"}
        with mock.patch.object(pultd.G, "tag", model):
            await run_hook(dict(ev("UserPromptSubmit", prompt="Микрофон ест первый слог"), session_id=sid2))
            await until(lambda: self.store.session_tag(sid2) is not None)
        r2 = self.store.session_tag(sid2)
        self.assertEqual((r2["sec"], r2["topic"], r2["own"]), ("Голос", "Распознавание", 0))
        self.assertIn("Микрофон ест первый слог", asked[0])
        self.assertIn("<task_title>Микрофон ест первый слог</task_title>", asked[0])   # the task's name, for a "go on" later
        self.assertIn("- Прошивка: Калибровка", asked[0])                  # the project's list goes to the model
        self.assertEqual([s["n"] for s in self.store.tag_vocab(PKEY)], ["Прошивка", "Корпус", "Голос"])   # in their order
        # the result line's call brings the tags too: taken for the model's task, ignored for the owner's
        seen = {}

        async def fake_brief(prompt, reply, bg, lang, cwd, tags=None):
            seen[tags is not None] = tags
            return {"line": "Готово", "you": False, "need": "", "tags": {"sec": "Корпус", "topic": "Крепления"}}
        with mock.patch.object(pultd.B, "brief", fake_brief):
            await run_hook(dict(ev("Stop", last_assistant_message="Готово", background_tasks=[]), session_id=sid2))
            await until(lambda: self.store.session_tag(sid2)["sec"] == "Корпус")
            await run_hook(ev("UserPromptSubmit", prompt="И ещё"))
            await run_hook(ev("Stop", last_assistant_message="Готово", background_tasks=[]))
            await until(lambda: self.p.attn.rec.get(SID, {}).get("model"))
        self.assertEqual(self.store.session_tag(sid2)["topic"], "Крепления")
        self.assertEqual(self.store.session_tag(SID)["sec"], "Прошивка")             # the owner's — kept
        self.assertEqual(set(seen), {True, False})                                   # asked for one, not for the other
        # the owner corrects in the app: their section and a new topic; then back to Claude
        res = await self.p.api_tag(sid2, sec="голос", topic="тишина")
        self.assertEqual([(g["n"], g["k"]) for g in res["tags"]], [("Голос", "sec"), ("Тишина", "topic")])
        self.assertEqual(self.store.session_tag(sid2)["own"], 1)
        self.assertFalse(res["auto"])
        with self.assertRaises(ValueError):
            await self.p.api_tag(sid2, sec="  ")
        with self.assertRaises(ValueError):
            await self.p.api_tag("nope", sec="Голос")
        with mock.patch.object(pultd.G, "tag", model):
            res = await self.p.api_tag(sid2, auto=True)
            await until(lambda: self.store.session_tag(sid2)["topic"] == "Распознавание")
        self.assertTrue(res["auto"])
        self.assertEqual(self.store.session_tag(sid2)["own"], 0)
        # the answers: rows, the project's tag bar (what its screen shows), the session with the whole list
        row = next(r for r in self.p.session_rows([]) if r["sid"] == SID)
        self.assertEqual([(g["n"], g["k"], g["c"]) for g in row["tags"]], [("Прошивка", "sec", 0), ("Калибровка", "topic", 0)])
        d = await self.p.api_project(PKEY)
        bar = {g["n"]: (g["cnt"], [t["n"] for t in g["topics"]]) for g in d["tagset"]}
        self.assertEqual(bar, {"Прошивка": (1, ["Калибровка"]), "Голос": (1, ["Распознавание"])})   # Корпус: no task now
        info = await self.p.api_session(sid2)
        self.assertEqual([g["n"] for g in info["tagset"]], ["Прошивка", "Корпус", "Голос"])
        self.assertTrue(info["tag_auto"])
        self.assertFalse((await self.p.api_session(SID))["tag_auto"])
        fresh = {g["n"]: g["fresh"] for g in info["tags"]}
        # the topic the model made a moment ago, one task has it: new; the section the owner once picked: never again
        self.assertEqual(fresh, {"Голос": False, "Распознавание": True})

    async def test_tags_screen(self):
        # T2: the project's tags screen — counts over the whole project, the busiest of the last 30 days first; the
        # owner keeps, renames, colours, hides, merges; Claude's old words land on the new names; what no task has
        # goes by itself; Claude's offers to merge, and the pairs kept apart
        st, now = self.store, time.time()
        S = ["%08x-0000-4000-8000-%012x" % (0x30000000 + i, i) for i in range(11)]
        tags = [("Прошивка", "Калибровка"), ("Прошивка", "Wi-Fi"), ("Прошивка", "Обновление по сети"),
                ("Корпус", "Прочность"), ("Корпус", "Прочность"), ("Корпус", None), ("Маркетинг", "Выставка"),
                ("Механика", "Прочность"), ("Механика", "Ремни"), ("Слайсер", "Профили")]
        for sid, (s, t) in zip(S, tags):
            st.tag_add(PKEY, s, t, ts=None if s == "Маркетинг" else now - 3 * 86400)
            st.set_session_tag(sid, PKEY, s, t, False)
        st.db.execute("UPDATE session_tags SET ts=? WHERE sid IN (?,?,?,?,?,?)", (now - 40 * 86400, *S[3:6], *S[7:10]))
        d = await self.p.api_tags(PKEY)
        self.assertEqual([(s["n"], s["cnt"]) for s in d["secs"]],
                         [("Прошивка", 3), ("Маркетинг", 1), ("Корпус", 3), ("Механика", 2), ("Слайсер", 1)])
        self.assertEqual([(t["n"], t["cnt"]) for t in d["secs"][2]["topics"]], [("Прочность", 2)])
        fresh = {t["n"]: t["fresh"] for s in d["secs"] for t in s["topics"]}
        self.assertEqual((fresh["Выставка"], fresh["Калибровка"]), (True, False))      # Claude made it a moment ago
        self.assertEqual((d["name"], d["hidden"], d["sug"], d["tidy"]), ("proj", [], [], False))
        edit = self.p.api_tags_edit
        d = await edit(PKEY, "keep", "маркетинг", "выставка")                         # any case: the list's names
        self.assertFalse(d["secs"][1]["topics"][0]["fresh"])
        # rename: the tasks follow; a name another tag has — offered to merge, nothing changed
        await edit(PKEY, "rename", "Корпус", name="  рама ")
        self.assertEqual([st.session_tag(s)["sec"] for s in S[3:6]], ["Рама"] * 3)
        d = await edit(PKEY, "rename", "Рама", name="механика")
        self.assertEqual(d["exists"], {"sec": "Механика", "topic": None})
        d = await edit(PKEY, "rename", "Прошивка", "Калибровка", name="калибровка стола")
        self.assertEqual(st.session_tag(S[0])["topic"], "Калибровка стола")
        self.assertEqual(await edit(PKEY, "rename", "Прошивка", "Wi-Fi", name="обновление по сети"),
                         dict(await self.p.api_tags(PKEY), exists={"sec": "Прошивка", "topic": "Обновление по сети"}))
        # colour: a section's, one of eight
        await edit(PKEY, "color", "Рама", c=5)
        self.assertEqual(next(s["c"] for s in st.tag_vocab(PKEY) if s["n"] == "Рама"), 5)
        for bad in (dict(c=8), dict(c="1"), dict(c=True), dict(topic="Прочность", c=1)):
            with self.assertRaises(ValueError):
                await edit(PKEY, "color", "Рама", **bad)
        # hide: the tag stays on the task, but not in its rows, the project's bar, the hashtags; back — the same way
        d = await edit(PKEY, "hide", "Маркетинг")
        self.assertEqual(d["hidden"], [{"sec": "Маркетинг", "topic": None, "c": 2, "cnt": 1}])
        self.assertEqual((self.p.tags_of(S[6]), self.p.hashtag_line(S[6]), st.session_tag(S[6])["sec"]), ([], "", "Маркетинг"))
        self.assertNotIn("Маркетинг", [g["n"] for g in self.p.tag_list(PKEY)])
        await edit(PKEY, "show", "Маркетинг")
        self.assertEqual(self.p.hashtag_line(S[6]), "#маркетинг #выставка")
        await edit(PKEY, "hide", "Прошивка", "Wi-Fi")
        self.assertEqual([g["n"] for g in self.p.tags_of(S[1])], ["Прошивка"])         # a hidden topic: the section alone
        self.assertNotIn("Wi-Fi", [t["n"] for g in self.p.tag_list(PKEY) for t in g["topics"]])
        # merge: a topic into a topic, a section into a section (a topic of the same name becomes one)
        await edit(PKEY, "merge", "Прошивка", "Wi-Fi", to_sec="Прошивка", to_topic="Обновление по сети")
        self.assertEqual((st.session_tag(S[1])["topic"], st.tag_hidden(PKEY)), ("Обновление по сети", set()))
        d = await edit(PKEY, "merge", "Рама", to_sec="Механика")
        self.assertEqual([(st.session_tag(s)["sec"], st.session_tag(s)["topic"]) for s in S[3:6]],
                         [("Механика", "Прочность"), ("Механика", "Прочность"), ("Механика", None)])
        self.assertEqual([(s["n"], s["cnt"], [t["n"] for t in s["topics"]]) for s in d["secs"] if s["n"] == "Механика"],
                         [("Механика", 5, ["Прочность", "Ремни"])])
        self.assertNotIn("Рама", [s["n"] for s in st.tag_vocab(PKEY)])
        for bad in (dict(op="merge", sec="Механика", to_sec="Прошивка", to_topic="Обновление по сети"),   # two kinds
                    dict(op="merge", sec="Механика", to_sec="Механика"), dict(op="merge", sec="Корпус", to_sec="Механика"),
                    dict(op="rename", sec="Механика", name=" / "), dict(op="what", sec="Механика")):
            with self.assertRaises(ValueError, msg=bad):
                await edit(PKEY, **bad)
        # Claude's old words — and a hashtag's — land on the new names, along the chain Корпус → Рама → Механика
        lv = self.p.stub(S[10], PKEY)
        self.assertTrue(self.p.tags_set(lv, {"sec": "Корпус", "topic": "Прочность"}))
        self.assertEqual((st.session_tag(S[10])["sec"], st.session_tag(S[10])["topic"]), ("Механика", "Прочность"))
        self.p.tags_set(lv, {"sec": "прошивка", "topic": "wi-fi"})
        self.assertEqual(st.session_tag(S[10])["topic"], "Обновление по сети")
        self.assertTrue(self.p.tag_by_owner(lv, ["калибровка"]))
        self.assertEqual((st.session_tag(S[10])["topic"], st.session_tag(S[10])["own"]), ("Калибровка стола", 1))
        # what no task has goes: Claude's own tags by themselves, the owner's stay
        st.set_session_tag(S[9], PKEY, "Механика", "Ремни", False)
        d = await self.p.api_tags(PKEY)
        self.assertNotIn("Слайсер", [s["n"] for s in d["secs"]])
        self.assertIn("Прошивка", [s["n"] for s in st.tag_vocab(PKEY)])
        # the owner picks a hidden tag for a task in its sheet: it is seen again
        await edit(PKEY, "hide", "Маркетинг")
        st.touch_session(S[6], PKEY)
        await self.p.api_tag(S[6], sec="маркетинг", topic="Выставка")
        self.assertEqual(st.tag_hidden(PKEY), set())
        # Claude's offers to merge: looked for with the model on, once per change of the names; a pair kept apart
        # never comes back
        await self.p.api_prefs(brief=True)
        asked = []

        async def model(text, lang, cwd):
            asked.append(text)
            return {"pairs": [{"a": {"sec": "Прошивка", "topic": "Калибровка стола"}, "keep": {"sec": "Прошивка", "topic": "Обновление по сети"}},
                              {"a": {"sec": "Нет", "topic": ""}, "keep": {"sec": "Механика", "topic": ""}}]}
        with mock.patch.object(pultd.G, "tidy", model):
            d = await self.p.api_tags(PKEY)
            self.assertTrue(d["tidy"])
            await until(lambda: not self.p.tidying)
            d = await self.p.api_tags(PKEY)
            self.assertEqual(d["sug"], [{"a": {"sec": "Прошивка", "topic": "Калибровка стола"},
                                         "b": {"sec": "Прошивка", "topic": "Обновление по сети"}, "c": 0}])
            self.assertIn("- Механика (6): Прочность (3), Ремни (2)", asked[0])
            self.assertEqual((len(asked), d["tidy"]), (1, False))                           # the same names: not asked again
            d = await edit(PKEY, "apart", "Прошивка", "Калибровка стола", to_sec="Прошивка", to_topic="Обновление по сети")
            self.assertEqual(d["sug"], [])
            self.assertEqual(st.tag_kept(PKEY), {frozenset({("Прошивка", "Калибровка стола"), ("Прошивка", "Обновление по сети")})})
            await edit(PKEY, "rename", "Прошивка", "Калибровка стола", name="Калибровка")    # the pair follows a rename
            self.assertEqual(st.tag_kept(PKEY), {frozenset({("Прошивка", "Калибровка"), ("Прошивка", "Обновление по сети")})})
            await until(lambda: len(asked) == 2 and not self.p.tidying)                      # the names changed: once more
        self.assertIn("- Прошивка / Калибровка — Прошивка / Обновление по сети", asked[1])
        # the project's screen knows the project has a list, for the way to it
        self.assertEqual((await self.p.api_project(PKEY))["tags_n"], len(st.tag_vocab(PKEY)))
        with self.assertRaises(ValueError):
            await self.p.api_tags("-nowhere-at-all")

    def fake_sessions(self, n, ago=40 * 86400, base=0x50000000):
        """A project's earlier sessions as the SDK lists them, the latest first — and a transcript for the first one.
        The model's offers to merge (tidy) answer nothing here: with the model on, the tags screen would ask it."""
        async def tidy(text, lang, cwd):
            return {"pairs": []}
        patch = mock.patch.object(pultd.G, "tidy", tidy)
        patch.start()
        self.addCleanup(patch.stop)
        S = ["%08x-0000-4000-8000-%012x" % (base + i, i) for i in range(n)]
        items = [types.SimpleNamespace(session_id=s, custom_title="Задача %d" % i, summary="Задача %d" % i,
                                       first_prompt="запрос %d" % i, last_modified=(time.time() - ago - i * 60) * 1000)
                 for i, s in enumerate(S)]
        folder = Path(pultd.CLAUDE_PROJECTS) / PKEY
        folder.mkdir(parents=True, exist_ok=True)
        (folder / (S[0] + ".jsonl")).write_text(tline("user", "запрос 0") + "\n" + tline("assistant", "Готово: датчик двери ставит паузу") + "\n")
        return S, items

    async def test_tags_old(self):
        # T2 (Q93): the project's earlier tasks without tags get them once, by themselves, when the owner opens the
        # project with the model on — in batches, one request at a time; the owner's tags and the tagged stay; "N of M"
        # meanwhile; a task's time is its own; a model that gives nothing stops it — later it goes on
        st = self.store
        S, items = self.fake_sessions(25)
        st.tag_add(PKEY, "Голос", "Порог", own=True)
        st.set_session_tag(S[1], PKEY, "Голос", "Порог", True)
        st.tag_add(PKEY, "Корпус", "Рама")
        st.set_session_tag(S[2], PKEY, "Корпус", "Рама", False)
        asked, hold = [], asyncio.Event()

        async def model(text, lang, cwd):
            asked.append(text)
            await hold.wait()
            ids = re.findall(r'<task id="(\d+)">', text)
            return {"tasks": [{"id": i, "sec": "прошивка" if int(i) % 2 else "Корпус", "topic": "Датчики" if int(i) % 2 else "Рама"} for i in ids]}
        import claude_agent_sdk
        with mock.patch.object(claude_agent_sdk, "list_sessions", lambda path, limit=None, *a, **k: items[:limit]), \
                mock.patch.object(pultd.G, "batch", model):
            await self.p.api_project(PKEY)
            self.assertEqual(self.p.tag_jobs, {})                              # the model is off: nothing
            await self.p.api_prefs(brief=True)
            d = await self.p.api_project(PKEY)
            self.assertEqual(d["tag_job"]["kind"], "old")
            await until(lambda: asked)
            self.assertEqual(self.p.tag_jobs[PKEY], {"kind": "old", "done": 0, "total": 23})
            self.assertIn("<claude>Готово: датчик двери ставит паузу</claude>", asked[0])   # how it ended, from the transcript
            self.assertIn("<request>запрос 0</request>", asked[0])
            self.assertEqual(asked[0].count("<task id="), G.BATCH)
            self.assertEqual((await self.p.api_tags(PKEY))["job"]["total"], 23)
            hold.set()
            await until(lambda: not self.p.tag_jobs)
            self.assertEqual(len(asked), 2)                                    # 23 tasks: two batches
            self.assertEqual((st.session_tag(S[0])["sec"], st.session_tag(S[0])["topic"], st.session_tag(S[0])["own"]), ("Прошивка", "Датчики", 0))
            self.assertEqual((st.session_tag(S[1])["sec"], st.session_tag(S[1])["own"]), ("Голос", 1))      # the owner's
            self.assertEqual(sum(1 for s in S if st.session_tag(s) and st.session_tag(s)["sec"]), 25)
            self.assertAlmostEqual(st.session_tag(S[3])["ts"], items[3].last_modified / 1000, delta=1)   # its own time
            self.assertEqual(st.tag_uses(PKEY, time.time() - 30 * 86400), {("Голос", None): 1, ("Голос", "Порог"): 1,
                                                                           ("Корпус", None): 1, ("Корпус", "Рама"): 1})   # 40 days old: not of the 30
            self.assertFalse(any(t["fresh"] for g in (await self.p.api_tags(PKEY))["secs"] for t in g["topics"]))
            self.assertTrue(st.get("tags.old." + PKEY))
            await self.p.api_project(PKEY)                                     # once: not again
            self.assertEqual((self.p.tag_jobs, len(asked)), ({}, 2))
        # a model that gives nothing: the job stops, what is left goes on later — not at once
        PK2 = "-Users-x-proj2"
        st.set_topic(PK2, "/Users/x/proj2", "proj2", None)
        S2, items2 = self.fake_sessions(3, base=0x60000000)
        calls = []

        async def silent(text, lang, cwd):
            calls.append(text)
            return None
        with mock.patch.object(claude_agent_sdk, "list_sessions", lambda path, limit=None, *a, **k: items2[:limit]), \
                mock.patch.object(pultd.G, "batch", silent):
            self.p.tags_sort_soon(PK2)
            await until(lambda: not self.p.tag_jobs)
            self.p.tags_sort_soon(PK2)
            self.assertEqual((len(calls), self.p.tag_jobs, st.get("tags.old." + PK2)), (1, {}, None))
            self.p.tag_failed[PK2] -= 3600
            with mock.patch.object(pultd.G, "batch", model):
                self.p.tags_sort_soon(PK2)
                await until(lambda: not self.p.tag_jobs)
        self.assertTrue(st.get("tags.old." + PK2))

    async def test_tags_resort(self):
        # T2: "Sort them again" — the model off: no; a new list from the README, the latest titles and the owner's tags;
        # Claude's old tags go, the owner's stay, a section named again keeps its colour, one of the owner's is never
        # doubled; every other task sorted anew; a list the model didn't give changes nothing; a restart mid-way goes on
        st = self.store
        S, items = self.fake_sessions(6, ago=86400)
        st.tag_add(PKEY, "Голос", "Порог", own=True)                             # colour 0, the owner's
        st.set_session_tag(S[0], PKEY, "Голос", "Порог", True)
        for sec in ("Прошивка", "Электроника", "Слайсер"):                        # colours 1, 2, 3 — Claude's
            st.tag_add(PKEY, sec, "Тема")
        for s, sec in zip(S[1:4], ("Прошивка", "Электроника", "Слайсер")):
            st.set_session_tag(s, PKEY, sec, "Тема", False)
        with self.assertRaises(ValueError):
            await self.p.api_tags_resort(PKEY)                                   # the model is off
        await self.p.api_prefs(brief=True)
        lists, batches, hold, mid = [], [], asyncio.Event(), asyncio.Event()

        async def make_list(text, lang, cwd):
            lists.append(text)
            await hold.wait()
            return {"secs": [{"n": "слайсер", "topics": ["Профили"]}, {"n": "голос", "topics": ["Шум"]}, {"n": "Механика", "topics": ["Рама"]}]}

        async def batch(text, lang, cwd):
            batches.append(text)
            await mid.wait()
            ids = re.findall(r'<task id="(\d+)">', text)
            return {"tasks": [{"id": i, "sec": "Механика" if int(i) % 2 else "Слайсер", "topic": "Рама" if int(i) % 2 else "Профили"} for i in ids]}
        import claude_agent_sdk
        st.put("tags.old." + PKEY, {"ts": time.time()})                          # its earlier tasks were sorted once
        with mock.patch.object(claude_agent_sdk, "list_sessions", lambda path, limit=None, *a, **k: items[:limit]), \
                mock.patch.object(pultd.G, "make_list", make_list), mock.patch.object(pultd.G, "batch", batch):
            d = await self.p.api_tags_resort(PKEY)
            self.assertEqual(d["job"], {"kind": "resort", "done": 0, "total": 0, "list": True})
            with self.assertRaises(ValueError):
                await self.p.api_tags_resort(PKEY)                               # one job a project
            await until(lambda: lists)
            self.assertIn("- Голос: Порог", lists[0])                            # the owner's tags, to keep
            self.assertIn("- Задача 0", lists[0])
            hold.set()
            await until(lambda: batches)
            # the screen looks in mid-way: the new list, empty yet, stays — its look took it all away once (the stand)
            names = [g["n"] for g in (await self.p.api_tags(PKEY))["secs"]]
            self.assertTrue({"Слайсер", "Механика", "Голос"} <= set(names), names)
            self.assertIn("- Механика: Рама", batches[0])
            mid.set()
            await until(lambda: not self.p.tag_jobs)
        vocab = {s["n"]: (s["c"], [t["n"] for t in s["topics"]]) for s in st.tag_vocab(PKEY)}
        self.assertEqual(vocab["Голос"], (0, ["Порог"]))                       # "Шум": no task got it — gone by itself
        self.assertEqual(vocab["Слайсер"][0], 3)                                  # named again: its own colour
        self.assertNotIn("Прошивка", vocab)
        self.assertNotIn("голос", vocab)
        self.assertEqual((st.session_tag(S[0])["sec"], st.session_tag(S[0])["own"]), ("Голос", 1))
        self.assertEqual({st.session_tag(s)["sec"] for s in S[1:]}, {"Механика", "Слайсер"})
        self.assertEqual((st.get("tags.resort." + PKEY), len(batches)), (None, 1))
        # no list from the model: nothing changes, the screen says so
        before = st.tag_vocab(PKEY)

        async def no_list(text, lang, cwd):
            return None
        with mock.patch.object(claude_agent_sdk, "list_sessions", lambda path, limit=None, *a, **k: items[:limit]), \
                mock.patch.object(pultd.G, "make_list", no_list):
            await self.p.api_tags_resort(PKEY)
            await until(lambda: not self.p.tag_jobs)
        self.assertEqual(st.tag_vocab(PKEY), before)
        self.assertIn("ничего не изменилось", (await self.p.api_tags(PKEY))["note"])
        # cut short after the new list (a batch without an answer, as after a restart): the next open goes on, no new list
        lists.clear()

        async def silent(text, lang, cwd):
            return None
        with mock.patch.object(claude_agent_sdk, "list_sessions", lambda path, limit=None, *a, **k: items[:limit]), \
                mock.patch.object(pultd.G, "make_list", make_list), mock.patch.object(pultd.G, "batch", silent):
            await self.p.api_tags_resort(PKEY)
            await until(lambda: not self.p.tag_jobs)
        self.assertTrue(st.get("tags.resort." + PKEY))
        self.assertIsNone(st.session_tag(S[1]))
        self.p.tag_failed.clear()
        with mock.patch.object(claude_agent_sdk, "list_sessions", lambda path, limit=None, *a, **k: items[:limit]), \
                mock.patch.object(pultd.G, "make_list", make_list), mock.patch.object(pultd.G, "batch", batch):
            d = await self.p.api_project(PKEY)
            self.assertEqual(d["tag_job"]["kind"], "resort")
            await until(lambda: not self.p.tag_jobs)
        self.assertEqual((len(lists), st.get("tags.resort." + PKEY)), (1, None))
        self.assertTrue(st.session_tag(S[1])["sec"])

    async def test_project_and_outcome(self):
        # the project's screen: what waits for the owner, what runs, today's outcomes; the session shows its outcome
        # as it was found (red), and a second look finds it seen; "Got it" from a card; ready replies kept
        self.p._procs = (time.monotonic() + 1e6, None)
        Path(TP).parent.mkdir(parents=True, exist_ok=True)
        Path(TP).write_text(tline("user", "Сделай кэш") + "\n" + tline("assistant", "Два варианта. Какой?") + "\n")
        await self.p.api_prefs(brief=True)

        async def fake_brief(prompt, reply, bg, lang, cwd, tags=None):
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

    async def test_running_row(self):
        # "Running now" (0.17.3): a turn in progress gives the app what was asked — from Telegram or the app too, which
        # the old line left out — and what Claude says so far, apart; line stays as it was for older apps
        self.p._procs = (time.monotonic() + 1e6, None)
        Path(TP).parent.mkdir(parents=True, exist_ok=True)
        Path(TP).write_text(tline("user", "Сделай отчёт") + "\n")
        await run_hook(ev("SessionStart", source="startup"))
        self.p.expect[SID] = 77                                        # the prompt came from Telegram
        await run_hook(ev("UserPromptSubmit", prompt="А в каком формате его делать?"))

        async def row():
            ov = await self.p.api_overview()
            return next(r for r in [r for p in ov["board"] for r in p["rows"]] + ov["mine"] if r["sid"] == SID)
        r = await row()
        self.assertEqual((r["state"], r["ask"], r["now"], r["line"]), ("work", "А в каком формате его делать?", "", ""))
        self.p.live[SID].turn.now = "Смотрю шаблоны отчётов."
        r = await row()
        self.assertEqual((r["ask"], r["now"], r["line"]), ("А в каком формате его делать?", "Смотрю шаблоны отчётов.", "Смотрю шаблоны отчётов."))
        await run_hook(ev("Stop", last_assistant_message="PDF.", background_tasks=[]))
        await until(lambda: SID in self.p.attn.rec)
        r = await row()
        self.assertEqual((r["state"], "ask" in r, "now" in r), ("you", False, False))     # ended: no turn to tell about

    async def test_seen_waits_for_the_model(self):
        # the session screen re-reads itself the moment a turn ends, before the model has said what is needed: that
        # look must not put a question away (2026-10-26, 11:49: "turn the cup ~120°" went grey unanswered); once the
        # model has spoken it decides — its "your move" stays, a report or no answer at all is seen
        self.p._procs = (time.monotonic() + 1e6, None)
        Path(TP).parent.mkdir(parents=True, exist_ok=True)
        Path(TP).write_text(tline("user", "Что дальше?") + "\n" + tline("assistant", "Повернуть стакан?") + "\n")
        await self.p.api_prefs(brief=True)
        go, answers = asyncio.Event(), []

        async def fake_brief(prompt, reply, bg, lang, cwd, tags=None):
            await go.wait()
            return answers.pop(0)
        cases = [({"line": "Нужно повернуть стакан", "you": True, "need": "Повернуть стакан на 120°", "replies": []}, False),
                 ({"line": "Жду тебя", "you": True, "need": "", "replies": []}, False),           # its word, though it named nothing
                 ({"line": "Отчёт готов", "you": False, "need": "", "replies": []}, True),
                 (None, True)]
        with mock.patch.object(pultd.B, "brief", fake_brief):
            for answer, seen in cases:
                go.clear()
                answers.append(answer)
                n = self.p.attn.day_of(PKEY)[0]
                await run_hook(ev("UserPromptSubmit", prompt="Что дальше?"))
                await run_hook(ev("Stop", last_assistant_message="Повернуть стакан на 120°?", background_tasks=[]))
                await until(lambda: self.p.attn.day_of(PKEY)[0] == n + 1)
                info = await self.p.api_session(SID)                       # the screen was open: it re-reads at once
                self.assertEqual((info["outcome"]["state"], self.p.attn.rec[SID]["seen"]), ("you", False), answer)
                go.set()
                await until(lambda: SID not in self.p.reading)
                self.assertEqual(self.p.attn.rec[SID]["seen"], seen, answer)
        self.assertEqual([r["sid"] for r in (await self.p.api_overview())["mine"]], [])
        # not opened while the model read: nothing is seen by itself
        self.p.attn.finished(SID, PKEY, 5, "Выбери А или Б", "Два варианта", waits=True)
        self.assertEqual([r["sid"] for r in (await self.p.api_overview())["mine"]], [SID])

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

        async def fake_brief(prompt, reply, bg, lang, cwd, tags=None):
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
        self.assertEqual(page["text"], "🟠 <b>Сделай кэш</b>\nДва варианта кэша\n<b>Выбери А или Б</b>")
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
        await until(lambda: any(t.startswith("✔️ <b>Сделай кэш</b> · Готово, жду решения.") for t in self.texts("editMessageText")))
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
        await until(lambda: "✔️ <b>Сделай кэш</b> · Готово, жду решения.\n→ «Как дела?»" in self.texts("editMessageText"))
        replies_555 = lambda: [d for d in self.fake.of("sendMessage") if '"message_id": 555' in d.get("reply_parameters", "")]
        await until(lambda: replies_555())                                            # the turn's message, under theirs
        await run_hook(ev("Stop", last_assistant_message="Всё хорошо.", background_tasks=[]))
        await until(lambda: any(t.startswith("✅") and "Всё хорошо." in t for t in self.texts()))
        await until(lambda: self.fake.of("deleteMessage"))
        res = next(d for d in self.fake.of("sendMessage") if d["text"].startswith("✅"))
        self.assertEqual(json.loads(res["reply_parameters"])["message_id"], 555)
        self.assertEqual(self.fake.of("deleteMessage")[-1]["message_id"], str(intro_id(self.fake, replies_555()[0])))
        await self.p.page_due()
        self.assertFalse(any("Всё хорошо" in t and t.startswith("🟠") for t in self.texts()))   # the answer was the call

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
        await until(lambda: any(t.startswith("✔️ <b>Дальше</b> · ") and t.endswith("\n→ Продолжу в " + hm)
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
        await until(lambda: any(t.startswith("<b>🟠 ждут тебя: 1") for t in self.sent()))
        # with a current session the status stays the first line: the pinned bar shows only that one
        self.p.set_focus(PKEY, SID)
        await until(lambda: any(t.startswith("<b>🟠 ждут тебя: 1") and "\n🎯 Сейчас: " in t for t in self.texts("editMessageText")))

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
        res = await self.p.api_send(SID, "Ещё")
        self.assertEqual((res["ok"], res["how"], self.p.outbox[SID][-1]["id"]), (True, "tab", res["out"]))
        self.assertEqual(json.loads(await asyncio.wait_for(r.readline(), 3))["text"], "Ещё")
        # a message into a busy tab: Claude Code absorbs it into the running turn and the tab doesn't show it (2.1.301);
        # should no UserPromptSubmit claim it, the turn's result still replies to that message in Telegram
        await self.p.continue_session(SID, "А меня обновил?", 57, 77)
        self.assertEqual(json.loads(await asyncio.wait_for(r.readline(), 3))["text"], "А меня обновил?")
        self.assertEqual((self.p.outbox[SID][-1]["tg"], self.p.outbox[SID][-1]["react"]), (57, "✍"))   # 👀 once read
        await run_hook(ev("Stop", last_assistant_message="Да, обновил"))
        await until(lambda: any("Да, обновил" in d.get("text", "") for d in self.fake.of("sendMessage")))
        res = next(d for d in self.fake.of("sendMessage") if "Да, обновил" in d["text"])
        self.assertEqual(json.loads(res["reply_parameters"])["message_id"], 57)
        self.assertNotIn(SID, self.p.tab_expect)
        w.close()
        await until(lambda: not self.p.tabs)                       # the tab was closed — it can no longer be written to
        self.assertEqual(await self.p.api_send(SID, "снова"), {"ok": False, "need": "fork"})

    async def test_copy_why(self):
        # open on the computer without Pult's wrapper: the app is told why a message goes as a copy, read off the
        # session's process by the wrapper's own rules (a friend's tab on 2.1.310 got only "open in a tab", 2026-10-26)
        self.store.touch_session(SID, PKEY, path="/Users/x/proj")
        Path(TP).parent.mkdir(parents=True, exist_ok=True)
        Path(TP).write_text(tline("user", "Подбери камеру", ago=400) + "\n" + tline("assistant", "Подойдёт почти любая", ago=300) + "\n")
        ext ="/Users/x/.vscode/extensions/anthropic.claude-code-%s-darwin-arm64/resources/native-binary/claude"
        procs = {900: {"ppid": 1, "cmd": "claude --resume " + SID}}
        self.p._agents = (time.monotonic() + 1e6, [{"sessionId": SID, "pid": 900, "cwd": "/Users/x/proj"}])
        self.p._procs = (time.monotonic() + 1e6, (procs, {}))
        d = Path(tempfile.mkdtemp(dir=TMP))
        conf, off, editors = d / "tab.json", d / "tab-off", [d / "Code" / "User"]
        editors[0].mkdir(parents=True)
        why = lambda: self.p.api_send(SID, "Ещё")                   # noqa: E731
        with mock.patch.multiple(pultd, TAB_CONF=conf, TAB_OFF=off, EDITOR_DIRS=editors):
            self.assertEqual(await why(), {"ok": False, "need": "fork", "why": "terminal"})
            procs[900]["cmd"] = ext % "2.1.310" + " --output-format stream-json --input-format stream-json"
            self.assertEqual((await why())["why"], "nowrap")              # no wrapper line in VS Code
            (editors[0] / "settings.json").write_text('{"claudeCode.claudeProcessWrapper": "/x/%s"}' % pultd.TAB_FILE)
            conf.write_text(json.dumps({"folders": ["/Users/x"], "versions": ["2.1.301"]}))
            self.assertEqual(await why(), {"ok": False, "need": "fork", "why": "version", "v": "2.1.310"})
            conf.write_text(json.dumps({"folders": ["/Users/x/other"], "versions": ["2.1.301", "2.1.310"]}))
            self.assertEqual((await why())["why"], "folder")
            conf.write_text(json.dumps({"folders": ["/Users/x"], "versions": ["2.1.301", "2.1.310"]}))
            self.assertEqual((await why())["why"], "reload")              # it started before the wrapper could join it
            off.touch()
            self.assertEqual((await why())["why"], "off")
            off.unlink()
            info = await self.p.api_session(SID)
            self.assertEqual((info["live"]["open"], info["live"]["why"]), (True, "reload"))   # said under the field too
            procs[800] = {"ppid": 1, "cmd": "/x/venv/bin/python /x/pult_tab.py " + ext % "2.1.310"}
            procs[900]["ppid"] = 800                      # the wrapper is there and hasn't named the session yet
            self.assertEqual(await why(), {"ok": False, "need": "fork"})
            self.p._agents = (time.monotonic() + 1e6, [{"sessionId": SID}])   # an older Claude Code: no pid
            self.assertEqual(await why(), {"ok": False, "need": "fork"})

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
        # a new extension is out and Pult's own check is off (Settings) — the owner is told once that writing into tabs
        # on it awaits verification
        await self.p.api_prefs(vcheck=False)
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
        old = (pultd.TAB_CONF, pultd.EDITOR_DIRS, pult_parts.EXT_DIRS)
        pultd.TAB_CONF, pultd.EDITOR_DIRS, pult_parts.EXT_DIRS = conf, [TMP / "nothing", vs.parent], [ext, server]
        try:
            await self.p.tab_version_check()
            await self.p.tab_version_check()
            await until(lambda: self.fake.of("sendMessage"))
            warn = [t for t in self.texts() if "Вышел Claude Code" in t]
            self.assertEqual(len(warn), 1)
            self.assertIn("<b>2.1.301</b>", warn[0])
            self.assertIn("pult tab allow 2.1.301", warn[0])                 # what to do, not "see the README"
            conf.write_text('{"folders": ["~/Documents"], "versions": ["2.1.301"]}')
            self.store.put("tab_warned", None)
            await self.p.tab_version_check()                            # a verified version — silence
            await asyncio.sleep(0.1)
            self.assertEqual(len([t for t in self.texts() if "Вышел Claude Code" in t]), 1)
        finally:
            pultd.TAB_CONF, pultd.EDITOR_DIRS, pult_parts.EXT_DIRS = old

    async def test_tab_check(self):
        # stage A: VS Code has downloaded a version tab.json doesn't list — Pult checks it here, one check at a time, in a
        # process of its own that writes tab.json; the owner hears only of a failure, once (Q79); a version that failed
        # waits for "Check again", one it couldn't check is tried again in an hour; the copy, Home and the table say so
        import pult_setup
        ext, conf, vs = TMP / "ext-a", TMP / "tab-a.json", TMP / "vscode-a" / "User" / "settings.json"
        conf.write_text(json.dumps({"folders": ["/Users/x"], "versions": ["2.1.310"]}))
        vs.parent.mkdir(parents=True, exist_ok=True)
        vs.write_text('{"claudeCode.claudeProcessWrapper": "/x/%s"}' % pultd.TAB_FILE)
        steps = [{"k": k, "ok": True, "s": 1, "note": ""} for k in ("service", "own", "send", "model", "effort", "race")]
        reports = {"2.1.311": {"ok": True, "race": True, "error": None, "steps": steps},
                   "2.1.312": {"ok": False, "race": False, "error": None,
                               "steps": steps[:3] + [{"k": "model", "ok": False, "s": 1, "note": "claude-haiku-5-5"}]},
                   "2.1.313": {"ok": None, "race": None, "error": "login", "steps": []}}
        runs, real = [], asyncio.create_subprocess_exec

        class Proc:
            def __init__(self, out):
                self.out = out

            async def communicate(self):
                await asyncio.sleep(0.05)
                return self.out, b""

        async def fake_exec(*cmd, **kw):
            if "tab" not in cmd or "check" not in cmd:
                return await real(*cmd, **kw)
            runs.append(cmd)
            v = cmd[-1]
            rep = dict(reports[v], version=v, ts=time.time())
            pult_setup.tab_checked(v, rep)              # as the real `pult tab check` does
            return Proc(json.dumps(rep).encode() + b"\n")

        def downloaded(v):
            (ext / ("anthropic.claude-code-%s-darwin-arm64" % v)).mkdir(parents=True, exist_ok=True)

        async def check():
            await self.p.tab_version_check()
            await until(lambda: not self.p.tab_checking)

        def rec(v):
            return (json.loads(conf.read_text()).get("checked") or {}).get(v)
        with mock.patch.multiple(pultd, TAB_CONF=conf, EDITOR_DIRS=[vs.parent]), mock.patch.object(pult_parts, "EXT_DIRS", [ext]), \
                mock.patch.object(pult_setup, "TAB_CONF", conf), mock.patch("asyncio.create_subprocess_exec", fake_exec):
            downloaded("2.1.311")
            await check()
            self.assertEqual(len(runs), 1)
            self.assertEqual(list(runs[0][-5:]), [str(pultd.HOME / "pultctl.py"), "tab", "check", "--json", "2.1.311"])
            if os.name != "nt":
                self.assertEqual(list(runs[0][:3]), ["nice", "-n", "10"])           # a low priority
            self.assertIn("2.1.311", json.loads(conf.read_text())["versions"])        # passed: allowed
            await check()
            self.assertEqual(len(runs), 1)                                            # allowed: nothing more to check
            self.assertFalse([t for t in self.texts() if "2.1.311" in t])             # passed: said nowhere
            downloaded("2.1.312")
            await check()
            await until(lambda: len([t for t in self.texts() if "2.1.312" in t]) >= 2)
            fail = [t for t in self.texts() if "не прошёл проверку" in t]
            self.assertEqual(len(fail), 1)
            self.assertIn("смена модели", fail[0])
            self.assertTrue(any("кто ответил первым" in t for t in self.texts()))   # the race, told apart
            self.assertEqual((rec("2.1.312")["ok"], rec("2.1.312")["step"]), (False, "model"))
            await check()
            self.assertEqual(len(runs), 2)                                            # failed: waits for "Check again"
            # the copy says why; Home and the table too
            self.p._agents = (time.monotonic() + 1e6, [{"sessionId": SID, "pid": 900, "cwd": "/Users/x/proj"}])
            ext312 = "/Users/x/.vscode/extensions/anthropic.claude-code-2.1.312-darwin-arm64/resources/native-binary/claude"
            self.p._procs = (time.monotonic() + 1e6, ({900: {"ppid": 1, "cmd": ext312}}, {}))
            self.assertEqual(await self.p.copy_why(SID), {"why": "failed", "v": "2.1.312", "step": "смена модели"})
            self.assertIn({"k": "cc", "v": "2.1.312", "fail": True}, await self.p.broken())
            res = await self.p.api_tab_check()                                        # "Check again"
            self.assertEqual((res["ok"], res["v"]), (True, "2.1.312"))
            self.assertEqual(await self.p.copy_why(SID), {"why": "checking", "v": "2.1.312"})
            await until(lambda: not self.p.tab_checking)
            self.assertEqual(len(runs), 3)
            self.assertEqual(len([t for t in self.texts() if "не прошёл проверку" in t]), 1)   # told once per version
            f = await self.p.parts_facts()
            row = next(r for r in pultd.Pult.parts_rows(f) if r["k"] == "cc")
            self.assertEqual((row["st"], row["have"], row["checked"]["2.1.312"]["step"]), ("bad", "2.1.312", "model"))
            # couldn't check (not logged in): said nowhere, tried again in an hour
            downloaded("2.1.313")
            await check()
            self.assertEqual((len(runs), rec("2.1.313")["error"]), (4, "login"))
            await check()
            self.assertEqual(len(runs), 4)
            c = json.loads(conf.read_text())
            c["checked"]["2.1.313"]["ts"] -= 2 * 3600
            conf.write_text(json.dumps(c))
            await check()
            self.assertEqual(len(runs), 5)
            self.assertFalse([t for t in self.texts() if "2.1.313" in t])

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

    async def test_overview_session_gone_meanwhile(self):
        # a session that ends while Home waits for the process snapshot is just not listed: before, Home failed with a
        # KeyError and showed an error line until the next event (review 2026-10-27, A1)
        lv = pultd.Live(SID, PKEY)
        lv.bg = [{"description": "tests"}]
        self.p.live[SID] = lv

        async def snapshot_meanwhile():
            self.p.live.pop(SID, None)                     # SessionEnd came in while it waited
            return None
        with mock.patch.object(self.p, "load_state", snapshot_meanwhile):
            ov = await self.p.api_overview()
        self.assertEqual(ov["live"], [])

    async def test_no_place_for_a_session(self):
        # MAX_DRIVEN sessions of Pult's own, all busy: the app hears the refusal where the owner tapped, before any
        # picture is saved; a new project is made, its first turn waits; from Telegram the refusal goes to the topic.
        # Before 0.18.6 "+" answered "ok" with a session that never started (review 2026-10-27, A2)
        class Busy:
            busy, bg = True, []

            def __init__(self):
                self.q = asyncio.Queue()
        for i in range(pultd.MAX_DRIVEN):
            self.p.driven["%08d-0000-4000-8000-000000000000" % i] = Busy()
        proj = TMP / ("full-" + self._testMethodName)
        proj.mkdir(exist_ok=True)
        pk = pultd.sanitize(str(proj))
        self.store.set_topic(pk, str(proj), "full", 77)
        with self.assertRaises(ValueError) as c:
            await self.p.api_new(pk, "дальше")
        self.assertIn("подожди", str(c.exception))
        self.assertFalse((proj / "inbox").exists())                  # nothing saved for a turn that can't start
        Path(TP).parent.mkdir(parents=True, exist_ok=True)
        Path(TP).write_text(tline("user", "привет") + "\n")
        self.store.touch_session(SID, PKEY, path=str(proj))
        with self.assertRaises(ValueError):
            await self.p.api_send(SID, "ещё")                         # a closed session: it would be resumed
        out = await self.p.project_made(pk, str(proj), "full", str(TMP), "empty", lambda: "first turn", None, None, True)
        self.assertNotIn("sid", out)
        self.assertIn("подожди", out["busy"])
        n = len(self.fake.of("sendMessage"))
        self.assertFalse(await self.p.drive("99999999-0000-4000-8000-000000000000", str(proj), "из темы", 500, pkey=pk))
        self.assertIn("подожди", self.fake.of("sendMessage")[n]["text"])
        self.assertEqual(len(self.p.driven), pultd.MAX_DRIVEN)

    async def test_hook_events_one_at_a_time(self):
        # two PostToolUse at once for a session Pult first sees mid-turn (after a restart): one turn, not two — the
        # handling awaits in between, and both used to find no turn (review 2026-10-27, Я4)
        started, orig = [], self.p.start_turn

        def count(lv, **kw):
            started.append(lv.sid)
            return orig(lv, **kw)

        def slow(path, owner=False, tail=512 * 1024):
            time.sleep(0.3)                          # reading the transcript: the window both events used to pass
            return None
        Path(TP).parent.mkdir(parents=True, exist_ok=True)
        Path(TP).write_text(tline("user", "привет") + "\n")
        with mock.patch.object(self.p, "start_turn", count), mock.patch.object(pultd, "prompt_started", slow):
            await asyncio.gather(run_hook(ev("PostToolUse", tool_name="Read", tool_input={"file_path": "a"})),
                                 run_hook(ev("PostToolUse", tool_name="Read", tool_input={"file_path": "b"})))
            await until(lambda: self.p.live.get(SID) and self.p.live[SID].turn and self.p.live[SID].turn.n >= 2)
        self.assertEqual(started, [SID])
        # a permission request waits outside the lock: the session's other events go on meanwhile
        proc = await run_hook(ev("PermissionRequest", tool_name="Bash", tool_input={"command": "ls"}), wait=False)
        await until(lambda: self.p.req_by_rid)
        await run_hook(ev("PostToolUse", tool_name="Read", tool_input={"file_path": "c"}))
        await until(lambda: self.p.live[SID].turn.n >= 3)
        self.p.act(next(iter(self.p.req_by_rid.values())), "y")
        await proc.stdout.read()

    async def test_small_things_of_the_core(self):
        # review 2026-10-27, Я8–Я11 and A5–A8, each in a line or two
        # Я8: Telegram asks to wait on an edit while a message stands in the queue; a newer edit of the same message
        # comes in the pause: the newest lands last — before 0.18.6 the stale one went after it, on top
        out, sent, tries = pultd.Outbox(rate=6000, burst=100), [], []

        async def msg():
            sent.append("message")

        async def edit(text):
            tries.append(text)
            if len(tries) == 1:
                asyncio.ensure_future(out.submit(5, msg))   # a message comes while the edit is on its way
                raise pultd.TgError("editMessageText", "Too Many Requests", 429, 0.05)
            sent.append(text)
        runner = asyncio.create_task(out.run())
        try:
            out.edit(100, lambda: edit("old"))
            await until(lambda: tries)                       # the first try met the pause (~0.55 s)
            out.edit(100, lambda: edit("final"), prio=4)
            await until(lambda: "final" in sent, timeout=3)
            await asyncio.sleep(0.15)
            edits = [x for x in sent if x != "message"]
            self.assertEqual(edits[-1], "final")              # before 0.18.6: ["final", "old"]
        finally:
            runner.cancel()
        # Я10: a request nothing of which reached Telegram is offered again later
        lv = self.p.live_of(SID, PKEY)
        req = pultd.Req(SID, "Bash", {"command": "ls"}, None)

        async def nothing(*a, **kw):
            return None
        with mock.patch.object(self.p, "send", nothing), mock.patch.object(self.p, "pager", lambda: False):
            await self.p.post_request(lv, req, False)
        self.assertFalse(req.paged)
        # Я11: Home has a turn's outcome while its own Telegram message still waits (a rate-limit pause)
        t = pultd.Turn("сделай")
        t.done = ("✔️", time.time())
        post = asyncio.create_task(self.p.post_result(lv, t, "Готово: всё сделано."))
        await until(lambda: SID in self.p.attn.rec)
        self.assertFalse(post.done())
        t.created.set_result(None)
        await asyncio.wait_for(post, 5)
        # A5: a hidden folder is no place for a new project — the picker never shows one
        root = TMP / ("home-" + self._testMethodName)
        (root / ".ssh").mkdir(parents=True, exist_ok=True)
        (root / "Documents").mkdir(exist_ok=True)
        with mock.patch.object(pult_api, "NEW_ROOT", root):
            with self.assertRaises(ValueError):
                self.p.place(str(root / ".ssh"))
            self.assertEqual(self.p.place(str(root / "Documents")), os.path.realpath(root / "Documents"))
        # A6: answers to a question come as lists: a string fell apart into letters, each an answer
        ask = pultd.Req(SID, "AskUserQuestion", {"questions": [{"question": "Как?", "options": [{"label": "Так"}]}]}, None)
        self.p.req_by_rid[ask.rid] = ask
        with self.assertRaises(ValueError):
            await self.p.api_answer(ask.rid, answers={"0": "Так"})
        self.p.req_by_rid.pop(ask.rid)
        # A8: a message on its way that Claude never read is crossed out after six hours, then goes
        now = time.time()
        self.p.outbox[SID] = [dict(id=k, body=k, ts=now - age, at=now - age, st="sent", tg=None, react=None)
                              for k, age in (("a", pultd.OUT_SENT + 60), ("b", pultd.OUT_SENT + pultd.OUT_GONE + 60), ("c", 5))]
        self.assertEqual([(v["id"], v["st"]) for v in self.p.out_view(SID)], [("a", "gone"), ("c", "sent")])
        self.p.outbox.pop(SID)

    async def test_telegram_long_poll_and_failures(self):
        # 0.18.5: Telegram's own `timeout` reaches getUpdates, so it holds the request (long polling) — the HTTP timeout
        # stays the client's 70 s. Before, the 50 s were taken for the HTTP timeout: the daemon asked every few seconds
        seen = []

        def handler(req):
            seen.append((req.url.path.rsplit("/", 1)[-1], urllib.parse.parse_qs(req.content.decode(errors="replace")),
                         req.extensions.get("timeout") or {}))
            return httpx.Response(200, json={"ok": True, "result": []})
        tg = pultd.Tg("T", transport=httpx.MockTransport(handler))
        await tg.call("getUpdates", offset=5, timeout=50, allowed_updates=["message"])
        method, body, timeout = seen[-1]
        self.assertEqual((method, body.get("timeout"), body.get("offset")), ("getUpdates", ["50"], ["5"]))
        self.assertEqual(timeout.get("read"), 70)
        await tg.call("sendDocument", files={"document": ("a.txt", b"x")}, http_timeout=300, chat_id=1)
        self.assertEqual(seen[-1][2].get("read"), 300)                 # a big upload: its own HTTP timeout
        self.assertNotIn(b"http_timeout", str(seen[-1][1]).encode())
        # every failure on the way is a TgError without a code (not Telegram's word): callers catch only TgError,
        # and a ReadTimeout once ended a session from Telegram (2026-10-24 in the log)

        def raising(fail):
            def h(req):
                raise fail
            return h
        for fail in (httpx.ReadTimeout("t"), httpx.WriteTimeout("t"), httpx.PoolTimeout("t"), httpx.WriteError("w"),
                     httpx.RemoteProtocolError("Server disconnected without sending a response.")):
            tg = pultd.Tg("T", transport=httpx.MockTransport(raising(fail)))
            with self.assertRaises(pultd.TgError) as c:
                await tg.call("sendMessage", chat_id=1, text="x")
            self.assertIsNone(c.exception.code, type(fail).__name__)
            self.assertNotIn("T/", str(c.exception))                   # never the token's URL
        tg = pultd.Tg("T", transport=httpx.MockTransport(lambda req: httpx.Response(502, text="<html>Bad Gateway</html>")))
        with self.assertRaises(pultd.TgError) as c:
            await tg.call("getMe")
        self.assertIsNone(c.exception.code)                            # telegram_start keeps waiting on such an answer
        # the route switch is as before: no connection through the proxy — directly
        calls = []

        def via(name, fail=None):
            def h(req):
                calls.append(name)
                if fail:
                    raise fail
                return httpx.Response(200, json={"ok": True, "result": True})
            return h
        tg = pultd.Tg("T", transport=httpx.MockTransport(via("proxy", httpx.ConnectError("no route"))))
        tg.clients.append(httpx.AsyncClient(transport=httpx.MockTransport(via("direct"))))
        self.assertTrue(await tg.call("getMe"))
        self.assertEqual(calls, ["proxy", "direct"])

    async def test_no_topic_nothing_breaks(self):
        # a topic that can't be made — no network on the way, or a refusal (no right to manage topics): send() says
        # "not sent" and returns; before, the exception ended whatever wanted the message (a turn, a result)
        for answer in (httpx.ReadTimeout("t"),
                       httpx.Response(400, json={"ok": False, "error_code": 400,
                                                 "description": "Bad Request: not enough rights to create a topic"})):
            def handler(req, a=answer):
                if req.url.path.endswith("/createForumTopic"):
                    if isinstance(a, Exception):
                        raise a
                    return a
                return self.fake.handler(req)
            self.p.tg = pultd.Tg("T", transport=httpx.MockTransport(handler))
            self.assertIsNone(await self.p.send(PKEY, "привет"))
        self.assertFalse(self.store.topic(PKEY)["thread"])
        # the refusal is the owner's to fix: said in General once (the network's moment says nothing)
        told = [d for d in self.fake.of("sendMessage") if "не дал Пульту открыть тему" in d.get("text", "")]
        self.assertEqual(len(told), 1)
        self.assertIn("not enough rights", told[0]["text"])
        self.assertNotIn("message_thread_id", told[0])
        await self.p.send(PKEY, "ещё раз")                                # within six hours: not again
        self.assertEqual(len([d for d in self.fake.of("sendMessage") if "не дал Пульту" in d.get("text", "")]), 1)

    async def test_permission_waits_without_telegram(self):
        # the request couldn't go to Telegram (out of reach, refused): it still waits — the app and the computer
        # answer it. Before, the failure dropped it, and a session from the app waited six hours for nothing
        async def broken(*a, **kw):
            raise pultd.TgError("sendMessage", "no answer (ReadTimeout)")
        with mock.patch.object(self.p, "post_request", broken):
            proc = await run_hook(ev("PermissionRequest", tool_name="Bash", tool_input={"command": "git push"}), wait=False)
            await until(lambda: self.p.req_by_rid)
            await asyncio.sleep(0.2)
            self.assertTrue(self.p.req_by_rid)                           # still there after the failure
            self.p.act(next(iter(self.p.req_by_rid.values())), "y")
            out = json.loads((await proc.stdout.read()).decode())
        self.assertEqual(out["hookSpecificOutput"]["decision"]["behavior"], "allow")

    async def test_message_before_reaction(self):
        # a message from the topic into a session of Pult's own goes to Claude first; the 👀 is only a sign of it
        # (a reaction that hung on the network held the message back)
        order = []

        class Dr:
            busy = False

            async def say(self, text, origin):
                order.append("say")

        async def react(msg, emoji):
            order.append("react")
        self.store.touch_session(SID, PKEY, path="/Users/x/proj")
        self.p.driven[SID] = Dr()
        with mock.patch.object(self.p, "react", react):
            await self.p.continue_session(SID, "дальше", 501, None)
        self.assertEqual(order, ["say", "react"])

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
            h = await asyncio.wait_for(hello, 10)
            self.assertIn("control", h["caps"])
            self.assertEqual(h["self"], U.blob(HERE / "pult_tab.py"))  # stage U2: its own file, as the tab started
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
        self.p.spend = pultd.S.Spend(root, pultd.skip_pkey)
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
        old = (claude_agent_sdk.ClaudeSDKClient, pult_driven.DRIVEN_IDLE)
        claude_agent_sdk.ClaudeSDKClient, pult_driven.DRIVEN_IDLE = FakeClient, 0.1    # 0.5 s below: five times it
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
            # the session's list (from its last Stop) loses the task the moment the SDK says it ended — the hooks hear
            # of it only at the turn's next step (tests/probe_bgmid.py); a task the SDK still runs stays
            lv = self.p.live_of(SID, "proj")
            lv.bg = [{"id": "b1", "description": "Сборка"}, {"id": "b2", "description": "Тесты"}]
            c.out.put_nowait(bg(["b2"]))
            await until(lambda: [b["id"] for b in lv.bg] == ["b2"])
            c.out.put_nowait(bg([]))
            await until(lambda: closed, timeout=3)     # no background tasks — the idle process is closed
            self.assertEqual(lv.bg, [])
        finally:
            claude_agent_sdk.ClaudeSDKClient, pult_driven.DRIVEN_IDLE = old

    async def test_driven_say_during_its_own_turn(self):
        # Claude Code started a turn by itself (a background task ended) while Pult's loop waits: a message from the
        # owner goes straight into that turn and its result answers it — queued, it went as the loop's query, and that
        # other turn's result passed for its answer (review 2026-10-27, Я5)
        import claude_agent_sdk

        class FakeClient:
            def __init__(self, options):
                self.out, self.sent = asyncio.Queue(), []
                made.append(self)

            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                pass

            async def query(self, text):
                self.sent.append(text)

            async def receive_messages(self):
                while True:
                    yield await self.out.get()

        made = []
        old = claude_agent_sdk.ClaudeSDKClient
        claude_agent_sdk.ClaudeSDKClient = FakeClient
        self.store.touch_session(SID, PKEY, path="/Users/x/proj", driven=True)
        try:
            d = self.p.driven[SID] = pultd.Driven(self.p, SID, "/Users/x/proj")
            await until(lambda: d.client is not None)
            lv = self.p.live_of(SID, PKEY)
            lv.turn = object()                          # a turn the hooks saw begin — not the loop's query
            self.assertFalse(d.asking)
            await d.say("а ещё вот что", 3)
            self.assertEqual((made[0].sent, self.p.expect[SID], d.q.empty()), (["а ещё вот что"], 3, True))
            lv.turn = None
        finally:
            claude_agent_sdk.ClaudeSDKClient = old
            d.task.cancel()

    async def test_driven_closing_window(self):
        # a session closing for idleness — its process takes a moment to exit: a message then goes by resume, not into
        # a queue nobody reads any more, and the old one leaves the new one's place alone (review 2026-10-27, Я6)
        import claude_agent_sdk
        gate = asyncio.Event()

        class FakeClient:
            def __init__(self, options):
                self.out = asyncio.Queue()

            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                await gate.wait()                        # the process takes its time to exit

            async def query(self, text):
                pass

            async def receive_messages(self):
                while True:
                    yield await self.out.get()

        drives = []

        async def drive(sid, path, text, origin, **kw):
            drives.append((sid, text, kw.get("resume")))
            self.p.driven[sid] = types.SimpleNamespace(closing=False, busy=False, bg=set(), q=asyncio.Queue())
            return True
        old = (claude_agent_sdk.ClaudeSDKClient, pult_driven.DRIVEN_IDLE)
        claude_agent_sdk.ClaudeSDKClient, pult_driven.DRIVEN_IDLE = FakeClient, 0.2
        self.store.touch_session(SID, PKEY, path="/Users/x/proj", driven=True)
        try:
            d = self.p.driven[SID] = pultd.Driven(self.p, SID, "/Users/x/proj")
            await until(lambda: d.closing, timeout=3)          # idle: the loop is done, the process still exiting
            self.assertIs(self.p.driven.get(SID), d)
            with mock.patch.object(self.p, "drive", drive):
                await self.p.continue_session(SID, "ещё", 7, None)
            self.assertEqual(drives, [(SID, "ещё", SID)])
            gate.set()
            await until(lambda: d.task.done())
            self.assertIsNot(self.p.driven.get(SID), d)
            self.assertIn(SID, self.p.driven)                  # the new one keeps its place
        finally:
            claude_agent_sdk.ClaudeSDKClient, pult_driven.DRIVEN_IDLE = old
            gate.set()
            self.p.driven.pop(SID, None)

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
            self.assertEqual([(o["id"], o["st"]) for o in self.p.outbox[SID]], [(r["out"], "sent")])   # ✓ in the app
            self.p.out_add(SID, "ещё одно")
            d.q.put_nowait(("ещё одно", None))         # waiting in Pult (the loop is busy with the turn)
            r = await self.p.api_stop(SID)
            self.assertEqual((r["ok"], c.stops), (True, 1))
            await until(lambda: not d.asking)
            await asyncio.sleep(0.05)
            self.assertNotIn("ещё одно", c.sent)        # dropped: Stop does not start the next turn
            self.assertTrue(d.q.empty())
            # the one Claude Code already had stays on its way (it runs as the next turn); the dropped one is gone
            self.assertEqual([o["st"] for o in self.p.outbox[SID]], ["sent", "gone"])
            await d.say("теперь дальше", None)         # between turns: through the loop, as before
            await until(lambda: c.sent[-1] == "теперь дальше")
        finally:
            claude_agent_sdk.ClaudeSDKClient = old
            d.task.cancel()
        # the process ends: what hadn't been read won't be
        await until(lambda: [o["st"] for o in self.p.outbox[SID]] == ["gone", "gone"])

    async def test_driven_queue(self):
        # a turn past MAX_RUNNING waits for a place, and it shows: in the app the state "queue" with its words, in the
        # topic "⏳ … in the queue" with "Start now" (2026-10-23: unseen, a question waited 4 minutes, was sent again and
        # ran twice). A place frees — it starts, its message goes, the place is given back; "Start now" — over the
        # limit, nothing to give back; Stop — the message goes, nothing is interrupted
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
                self.sent.append(text)
                self.out.put_nowait(res())

            async def interrupt(self):
                self.stops += 1

            async def receive_messages(self):
                while True:
                    yield await self.out.get()

        made = []
        queue_msgs = lambda: [d for d in self.fake.of("sendMessage") if "в очереди" in d["text"]]
        old = claude_agent_sdk.ClaudeSDKClient
        claude_agent_sdk.ClaudeSDKClient = FakeClient
        self.store.touch_session(SID, PKEY, path="/Users/x/proj", driven=True)
        self.p.live_of(SID, PKEY).driven = True
        sem = self.p.run_sem
        for _ in range(pultd.MAX_RUNNING):
            await sem.acquire()                        # three turns run elsewhere
        try:
            d = self.p.driven[SID] = pultd.Driven(self.p, SID, "/Users/x/proj")
            d.q.put_nowait(("какими винтами?", 7))     # from the topic
            await until(lambda: d.queued and queue_msgs())
            c = made[0]
            self.assertEqual(c.sent, [])
            item = self.p.live_item(self.p.live[SID])
            self.assertEqual((item["state"], item["waiting"], item["slots"]), ("queue", "какими винтами?", 3))
            self.assertEqual([r["state"] for r in self.p.session_rows([]) if r["sid"] == SID], ["queue"])
            self.assertTrue(d.busy)                    # not closed as idle; a restart asks first
            kb = json.loads(queue_msgs()[0]["reply_markup"])["inline_keyboard"]
            self.assertEqual(kb[0][0]["callback_data"], "j:" + SID)
            sem.release()                              # a place frees
            await until(lambda: c.sent == ["какими винтами?"] and not d.asking)
            self.assertIsNone(d.queued)
            await until(lambda: self.fake.of("deleteMessage"))
            await asyncio.sleep(0.05)
            self.assertFalse(sem.locked())             # given back
            await sem.acquire()                        # three run again
            d.q.put_nowait(("ещё", None))              # from the app: no message in the topic
            await until(lambda: d.queued)
            self.assertEqual(len(queue_msgs()), 1)
            self.assertTrue((await self.p.api_jump(SID))["ok"])
            await until(lambda: c.sent[-1:] == ["ещё"] and not d.asking)
            await asyncio.sleep(0.05)
            self.assertTrue(sem.locked())              # over the limit: nothing was taken, nothing given back
            d.q.put_nowait(("третье", None))
            await until(lambda: d.queued)
            self.assertTrue((await self.p.api_stop(SID))["ok"])
            await until(lambda: d.queued is None)
            await asyncio.sleep(0.05)
            self.assertNotIn("третье", c.sent)
            self.assertEqual(c.stops, 0)               # no turn ran: nothing to interrupt
            self.assertTrue(sem.locked())
            self.assertFalse((await self.p.api_jump(SID))["ok"])
            # a turn runs and a message waits for a place: Stop drops the message and interrupts the turn
            # (review 2026-10-27, Т7)
            d.q.put_nowait(("четвёртое", None))
            await until(lambda: d.queued)
            self.p.live[SID].turn = pultd.Turn("идёт")
            self.assertTrue((await self.p.api_stop(SID))["ok"])
            await until(lambda: d.queued is None and c.stops == 1)
            self.assertNotIn("четвёртое", c.sent)
            self.p.live[SID].turn = None
            # a permission nobody answers in Telegram: declined after ASK_TIMEOUT, with words for Claude
            with mock.patch.object(pult_driven, "ASK_TIMEOUT", 0):
                r = await d._wait_hook("Bash", {"command": "ls"}, None)
            self.assertEqual((type(r).__name__, r.message.startswith("No answer from Telegram")), ("PermissionResultDeny", True))
        finally:
            claude_agent_sdk.ClaudeSDKClient = old
            d.task.cancel()

    async def test_interrupted_turn_closes(self):
        # an interrupted turn of Pult's own session gets no Stop hook, only its result (probe_midturn.py stop, 2.1.300):
        # shortly after the result it is closed as interrupted, so it doesn't stay "working" and keep the idle process
        # alive (2026-10-21, a session after Stop). A turn whose Stop comes is closed by the Stop, as before
        with mock.patch.object(pultd, "RESULT_GRACE", 0.3):
            await run_hook(ev("UserPromptSubmit", prompt="Долгая задача"))
            await until(lambda: self.p.live.get(SID) and self.p.live[SID].turn)
            t = self.p.live[SID].turn
            self.p.result_seen(SID)
            await until(lambda: self.p.live[SID].turn is None)
            self.assertEqual(t.done[0], "⏹")
        # the Stop's hook comes after the result: a grace it surely beats — a slow machine took longer than 0.3 s
        with mock.patch.object(pultd, "RESULT_GRACE", 5):
            await run_hook(ev("UserPromptSubmit", prompt="Ещё раз"))
            await until(lambda: self.p.live[SID].turn)
            t2 = self.p.live[SID].turn
            self.p.result_seen(SID)
            await run_hook(ev("Stop", last_assistant_message="Готово"))
            await until(lambda: t2.done)
            self.assertEqual(t2.done[0], "✔️")
            self.p.result_seen(SID)                    # no turn open: nothing to close

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

    def upd_reset(self, check):
        """Stage U: a clean Pult folder for update.json and the history; pult_update.check answers `check`."""
        for name in (U.STATUS, U.HISTORY, U.HEALTH):
            (U.HOME / name).unlink(missing_ok=True)
        self.p._upd = (0.0, None)
        self.p.upd_wait = None
        self.spawned = []
        self.addCleanup(lambda: [(U.HOME / n).unlink(missing_ok=True) for n in (U.STATUS, U.HISTORY, U.HEALTH)])
        patches = [mock.patch.object(U, "check", lambda: dict(check)),
                   mock.patch.object(U, "spawn", lambda commit, how, python=None: self.spawned.append((commit, how)) or True),
                   mock.patch.object(pultd.pult_os, "KIND", "mac"),
                   mock.patch.object(self.p, "broken", mock.AsyncMock(return_value=[]))]   # not this computer's hooks
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    READY = {"repo": "/Users/x/pult", "head": "c" * 40, "short": "c" * 7, "ready": True, "version": "9.9",
             "news": ["Pult 9.9: one button"], "failed": False}

    def busy_session(self):
        self.p.live_of(SID, PKEY)
        self.p.driven[SID] = types.SimpleNamespace(busy=True, running=True, queued=None, bg=set(), q=asyncio.Queue())

    async def test_update_view(self):
        # the "Pult" block in Settings and the line on Home: nothing newer, a commit to install, one that would cut a
        # working session off, waiting for it, installing, a commit that didn't come up, no git source
        self.upd_reset(dict(self.READY, ready=False))
        v = await self.p.api_update()
        self.assertEqual((v["state"], v["have"], v["dir"], v["commit"]), ("ok", pultd.VERSION, "/Users/x/pult", "c" * 7))
        self.assertIsNone((await self.p.api_overview())["update"])          # nothing to do: no line on Home
        self.upd_reset(self.READY)
        v = await self.p.api_update()
        self.assertEqual((v["state"], v["next"], v["news"], v["busy"]), ("ready", "9.9", ["Pult 9.9: one button"], []))
        self.assertEqual((await self.p.api_overview())["update"],
                         {"state": "ready", "have": pultd.VERSION, "next": "9.9", "back": None, "left": 0})
        self.busy_session()
        v = await self.p.api_update()
        self.assertEqual((v["state"], [(b["project"], b["turn"]) for b in v["busy"]]), ("busy", [("proj", True)]))
        self.p.upd_wait = time.time()
        self.assertEqual((await self.p.api_update())["state"], "wait")
        self.assertEqual((await self.p.api_overview())["update"]["left"], 1)
        U.write(U.STATUS, {"state": "run", "step": "check", "to": "9.9", "ts": time.time(), "pid": os.getpid()})
        v = await self.p.api_update()
        self.assertEqual((v["state"], v["next"], v["step"]), ("run", "9.9", "check"))
        self.p.driven.clear()
        U.write(U.STATUS, {"state": "fail", "why": "restarts", "detail": "ImportError: x", "back": True, "commit": "c" * 40})
        self.upd_reset(dict(self.READY, failed=True))
        U.write(U.STATUS, {"state": "fail", "why": "restarts", "detail": "ImportError: x", "back": True, "commit": "c" * 40})
        v = await self.p.api_update()
        self.assertEqual((v["state"], v["why"], v["detail"], v["back"]), ("fail", "restarts", "ImportError: x", True))
        self.upd_reset({"repo": None})
        self.assertEqual(((await self.p.api_update())["state"], (await self.p.api_update())["why"]), ("na", "norepo"))
        U.record(**{"from": "9.8", "to": "9.9", "how": "terminal", "ok": True, "commit": "c" * 40})
        self.assertEqual([(h["to"], h["how"]) for h in (await self.p.api_update())["hist"]], [("9.9", "terminal")])

    async def test_update_go(self):
        # "Install": only what is ready, from the folder Pult knows — the phone sends the tap and nothing else
        self.upd_reset(self.READY)
        with self.assertRaises(TypeError):
            await self.p.api_update_go(path="/tmp/evil")                     # no arguments from the phone
        web, self.p.web = self.p.web, mock.Mock()
        try:
            v = await self.p.api_update_go()
        finally:
            heard, self.p.web = self.p.web.emit.call_args_list, web
        self.assertIn(mock.call("update", state="run"), heard)    # any screen of the app: "installing", not "offline" (П8)
        self.assertEqual(self.spawned, [("c" * 40, "app")])
        self.assertEqual((v["state"], v["next"]), ("run", "9.9"))
        st = U.read(U.STATUS)
        self.assertEqual((st["state"], st["from"], st["to"], st["how"]), ("run", pultd.VERSION, "9.9", "app"))
        with self.assertRaises(ValueError):
            await self.p.api_update_go()                                    # a second tap while it installs
        self.assertEqual(len(self.spawned), 1)
        # a working session of Pult's own: not now
        self.upd_reset(self.READY)
        self.busy_session()
        with self.assertRaises(ValueError) as e:
            await self.p.api_update_go()
        self.assertIn("оборвёт", str(e.exception))
        self.assertEqual(self.spawned, [])
        # the installer couldn't start: said, and the button is back
        self.p.driven.clear()
        self.upd_reset(self.READY)
        with mock.patch.object(U, "spawn", lambda *a, **kw: False), self.assertRaises(ValueError):
            await self.p.api_update_go()
        self.assertEqual((U.read(U.STATUS)["state"], U.read(U.STATUS)["why"]), ("fail", "spawn"))
        self.assertEqual((await self.p.api_update())["state"], "ready")

    async def test_update_when_free(self):
        # "Install once they're free": the installer starts on the first check with no session of Pult's own working
        self.upd_reset(self.READY)
        self.busy_session()
        v = await self.p.api_update_wait()
        self.assertEqual(v["state"], "wait")
        await self.p.update_tick()
        self.assertEqual(self.spawned, [])
        # a restart meanwhile, for another reason: the next daemon still waits (in memory it forgot — review 2026-10-27, У11)
        again = pultd.Pult({"PULT_ALLOWED_USER_IDS": str(OWNER)}, self.p.tg, self.store)
        self.assertEqual(again.upd_wait, self.p.upd_wait)
        self.assertIsNotNone(again.upd_wait)
        self.p.driven.clear()
        await self.p.update_tick()
        self.assertEqual(self.spawned, [("c" * 40, "app_wait")])
        self.assertIsNone(self.p.upd_wait)
        self.assertEqual(U.read(U.STATUS)["how"], "app_wait")
        # "Cancel"; and waiting stops by itself when there is nothing to install any more
        self.upd_reset(self.READY)
        self.busy_session()
        await self.p.api_update_wait()
        self.assertEqual((await self.p.api_update_cancel())["state"], "busy")
        await self.p.api_update_wait()
        self.upd_reset(dict(self.READY, ready=False))
        self.p.upd_wait = time.time()
        await self.p.update_tick()
        self.assertIsNone(self.p.upd_wait)
        self.assertEqual(self.spawned, [])
        self.p.driven.clear()

    async def test_update_failed_told_once(self):
        # the old version is back: it says so in General, once (Q51: success says nothing)
        self.upd_reset(self.READY)
        U.write(U.STATUS, {"state": "fail", "why": "restarts", "back": True, "reported": False, "to": "9.9", "commit": "c" * 40})
        await self.p.update_tick()
        await self.p.update_tick()
        await asyncio.sleep(0.2)
        told = [t for t in self.texts() if "9.9" in t]
        self.assertEqual(len(told), 1)
        self.assertIn("не поднялся", told[0])
        self.assertIn("падает при запуске", told[0])
        self.assertIn(pultd.VERSION, told[0])
        self.assertTrue(U.read(U.STATUS)["reported"])
        U.write(U.STATUS, {"state": "done", "to": "9.9"})
        await self.p.update_tick()
        await asyncio.sleep(0.1)
        self.assertEqual(len([t for t in self.texts() if "9.9" in t]), 1)

    PARTS_GIT = {"repo": "/Users/x/pult", "head": "a" * 40, "branch": "main", "mac": {"n": 2, "since": 1000, "news": ["x", "y"]},
                 "web": {"n": 3, "since": 900, "news": ["a", "b", "c"], "commit": "b" * 40, "ts": 800},
                 "relay": {"n": 0, "since": None, "news": [], "commit": "c" * 40, "ts": 700}, "relay_told": True,
                 "gh": {"last": "9.8.0", "date": "2026-10-20", "waiting": 4}}
    PARTS_CC = {"running": ["2.1.301"], "verified": ["2.1.301"], "newest": "2.1.301", "wrapped": True, "sdk": "0.2.167",
                "cli": "2.1.300"}

    async def test_parts(self):
        # stage U2: every part of Pult in one table — what is there, how far behind main, what doesn't work
        self.upd_reset(self.READY)
        f = {"upd": await self.p.update_view(), "git": dict(self.PARTS_GIT), "relay": True,
             "tabs": [{"project": "a", "same": True}, {"project": "b", "same": False}, {"project": "b", "same": False}],
             "hooks": [e for e in pult_hook.EVENTS if e != "StopFailure"], "cc": dict(self.PARTS_CC)}
        rows = {r["k"]: r for r in self.p.parts_rows(f)}
        self.assertEqual(list(rows), ["mac", "web", "relay", "tabs", "hooks", "cc", "gh"])   # the phone's row is the app's
        st = {k: r["st"] for k, r in rows.items()}
        self.assertEqual(st, {"mac": "warn", "web": "warn", "relay": "ok", "tabs": "warn", "hooks": "warn", "cc": "ok", "gh": "info"})
        self.assertEqual((rows["mac"]["n"], rows["mac"]["have"], rows["mac"]["upd"]["state"]), (2, pultd.VERSION, "ready"))
        self.assertEqual((rows["web"]["n"], rows["web"]["commit"], rows["web"]["news"]), (3, "b" * 7, ["a", "b", "c"]))
        self.assertEqual((rows["tabs"]["old"], rows["tabs"]["n_old"], rows["tabs"]["have"]), (["b"], 2, 3))
        self.assertEqual((rows["hooks"]["missing"], rows["gh"]["waiting"]), (["StopFailure"], 4))
        # a downloaded Claude Code not verified yet — worth a look; tabs already on one — writing into them is off
        f["cc"] = dict(self.PARTS_CC, newest="2.1.310")
        cc = {r["k"]: r for r in self.p.parts_rows(f)}["cc"]
        self.assertEqual((cc["st"], cc["fresh"], cc["off"]), ("attn", "2.1.310", []))
        f["cc"] = dict(self.PARTS_CC, running=["2.1.301", "2.1.310"], newest="2.1.310")
        cc = {r["k"]: r for r in self.p.parts_rows(f)}["cc"]
        self.assertEqual((cc["st"], cc["off"], cc["fresh"], cc["have"]), ("bad", ["2.1.310"], None, "2.1.310"))
        f["cc"] = dict(self.PARTS_CC, running=["2.1.310"], newest="2.1.310", wrapped=False)    # no wrapper: no matter
        self.assertEqual({r["k"]: r for r in self.p.parts_rows(f)}["cc"]["st"], "info")
        # nothing the relay said / a copy from no commit of main / no git source; nothing to compare a computer with
        f["git"] = dict(self.PARTS_GIT, web=None, relay=None, relay_told=False, web_told=True)
        rows = {r["k"]: r for r in self.p.parts_rows(f)}
        self.assertEqual([(rows[k]["st"], rows[k]["why"]) for k in ("web", "relay")], [("info", "other"), ("info", "old")])
        rows = {r["k"]: r for r in self.p.parts_rows(dict(f, git={"repo": None}, upd=dict(f["upd"], state="na"), relay=False))}
        self.assertEqual((rows["mac"]["st"], "web" in rows, "gh" in rows), ("info", False, False))
        self.p.parts_facts = mock.AsyncMock(return_value=dict(f, git=self.PARTS_GIT))
        v = await self.p.api_parts()
        self.assertEqual((v["head"], v["branch"], len(v["rows"])), ("a" * 7, "main", 7))

    async def test_parts_facts(self):
        # the facts behind the table: the wrappers in the tabs against the installed one, Claude Code by its processes,
        # what doesn't work for Home's line
        d = TMP / "parts"
        d.mkdir(exist_ok=True)
        (d / "pult_tab.py").write_text("# wrapper 2\n")
        (d / "tab.json").write_text(json.dumps({"folders": [], "versions": ["2.1.301"]}))
        now = U.blob(d / "pult_tab.py")
        self.p.tabs = {1: types.SimpleNamespace(sid=None, cwd="/Users/x/shop", version="2.1.301", own=now),
                       2: types.SimpleNamespace(sid=None, cwd="/Users/x/blog/", version="2.1.301", own="0" * 40),
                       3: types.SimpleNamespace(sid=None, cwd="/Users/x/old", version="2.1.301", own=False),
                       4: types.SimpleNamespace(sid=None, cwd="/Users/x/win", version="2.1.301", own=None)}
        claude = "/Users/x/.vscode/extensions/anthropic.claude-code-%s-darwin-arm64/resources/native-binary/claude"
        procs = {10: {"cmd": claude % "2.1.310" + " --output-format stream-json", "mine": True},
                 11: {"cmd": "/usr/bin/python3 x.py", "mine": True}}
        with mock.patch.object(pultd, "HOME", d), mock.patch.object(pultd, "TAB_CONF", d / "tab.json"), \
                mock.patch.object(self.p, "snapshot", mock.AsyncMock(return_value=(procs, {}))), \
                mock.patch.object(pultd.pult_os, "files_with", lambda dirs, mark: ["settings.json"]), \
                mock.patch.object(pultd.pult_os, "newest_extension", lambda dirs: "2.1.310"), \
                mock.patch.object(self.p, "hooks_on", lambda: ["Stop", "UserPromptSubmit"]):
            self.assertEqual([(t["project"], t["same"]) for t in self.p.tab_facts()],
                             [("shop", True), ("blog", False), ("old", False), ("win", None)])
            self.p._cc = (0.0, None)
            cc = await self.p.cc_facts()
            self.assertEqual((cc["running"], cc["verified"], cc["newest"], cc["wrapped"]),
                             (["2.1.301", "2.1.310"], ["2.1.301"], "2.1.310", True))
            self.assertRegex(cc["sdk"] or "", r"^\d+\.\d+")
            broken = await self.p.broken()
            self.assertEqual([b["k"] for b in broken], ["hooks", "cc"])
            self.assertEqual(broken[1]["v"], "2.1.310")
            self.assertIn("StopFailure", broken[0]["missing"])
        self.p.tabs = {}
        self.p._cc = (0.0, None)
        # Home's line: nothing to install, yet something doesn't work
        self.upd_reset(dict(self.READY, ready=False))
        self.p.broken = mock.AsyncMock(return_value=broken)
        u = (await self.p.api_overview())["update"]
        self.assertEqual((u["state"], [b["k"] for b in u["broken"]]), ("ok", ["hooks", "cc"]))

    async def test_parts_table_is_fresh(self):
        # Settings → Pult and its parts after a commit: the folder's news within 10 s, as in the Pult block before the
        # table — with 60 s the new commit's Install came a minute late (tools/update_live.py, 2026-10-27)
        ages = []

        async def view(age=60):
            ages.append(("upd", age))
            return {"state": "ok", "have": "1.0"}

        async def facts(age=60):
            ages.append(("git", age))
            return {"repo": None}
        with mock.patch.object(self.p, "update_view", view), mock.patch.object(self.p, "git_facts", facts), \
                mock.patch.object(self.p, "cc_facts", mock.AsyncMock(return_value={})), \
                mock.patch.object(self.p, "tab_facts", lambda: []), mock.patch.object(self.p, "hooks_on", lambda: []):
            await self.p.parts_facts()
        self.assertEqual(ages, [("upd", 10), ("git", 10)])

    async def test_server_follows(self):
        # stage U3: a relay whose server has the updater hears the release this computer runs — on connecting, and
        # again while it hasn't taken it; a release it didn't take is told once, a failure of the moment not at all;
        # once it runs a release, the file check expects that release's files
        self.upd_reset(dict(self.READY, ready=False))
        sent, seen = [], []

        class Web:
            build = None

            async def send(self, msg):
                sent.append(msg)

            def emit(self, kind, **data):
                pass
        self.p.web = Web()
        rec = {"src": "/x/pult", "commit": "b" * 40}

        async def said(msg):                    # the relay's word; the release goes out on a task of its own
            await self.p.relay_said(msg)
            if self.p.announcing:
                await self.p.announcing
        with mock.patch.object(U, "read", lambda name, default=None: dict(rec) if name == U.MANIFEST else default), \
                mock.patch.object(U, "release_of", lambda src, commit: "v9.1.0"), \
                mock.patch.object(self.p, "expect_release", seen.append):
            await said({"t": "relay", "can": [], "upd": None})          # no updater there: nothing said
            self.assertEqual(sent, [])
            await said({"t": "relay", "can": ["want"], "upd": {"state": "idle", "have": "v9.0.0", "ts": 1}})
            self.assertEqual(sent, [{"t": "want", "tag": "v9.1.0", "commit": "b" * 40}])
            self.assertEqual(seen, ["v9.0.0"])
            await self.p.announce()                                                  # not again so soon
            self.assertEqual(len(sent), 1)
            self.p.told = (self.p.told[0], time.monotonic() - pult_parts.ANNOUNCE_EVERY - 1)
            await self.p.announce()
            self.assertEqual(len(sent), 2)
            # the server takes it: Home says so; then it runs it — nothing in Telegram, nothing more to say to it
            await said({"t": "relay", "upd": {"state": "run", "step": "fetch", "tag": "v9.1.0", "have": "v9.0.0", "ts": 2}})
            self.assertEqual((await self.p.update_row())["state"], "srv_run")
            await said({"t": "relay", "upd": {"state": "done", "tag": "v9.1.0", "have": "v9.1.0", "from": "v9.0.0", "ts": 3}})
            self.assertEqual(seen[-1], "v9.1.0")
            self.assertIsNone(await self.p.update_row())
            await self.p.announce(force=True)
            self.assertEqual(len(sent), 2)
            # a release it didn't take: told once — the relay repeats its last report on every connection
            fail = {"state": "fail", "why": "no_start", "back": True, "back_ok": True, "tag": "v9.2.0", "have": "v9.1.0", "ts": 4}
            await said({"t": "relay", "upd": fail})
            await said({"t": "relay", "can": ["want"], "upd": fail})
            await asyncio.sleep(0.2)
            told = [x for x in self.texts() if "v9.2.0" in x]
            self.assertEqual(len(told), 1)
            self.assertIn("не взял", told[0])
            self.assertIn("посредник не запустился", told[0])
            self.assertIn("v9.1.0", told[0])
            await said({"t": "relay", "upd": dict(fail, why="network", tag="v9.3.0", ts=5)})    # of the moment
            await asyncio.sleep(0.1)
            self.assertFalse([x for x in self.texts() if "v9.3.0" in x])
            # a computer on a release the server didn't take for good: it isn't asked again
            rec["commit"] = "d" * 40
            with mock.patch.object(U, "release_of", lambda src, commit: "v9.2.0"):
                await said({"t": "relay", "upd": dict(fail, have="v9.1.0")})
                await self.p.announce(force=True)
            self.assertEqual(len(sent), 2)
            await asyncio.sleep(0.1)
            self.assertEqual(len([x for x in self.texts() if "v9.2.0" in x]), 1)      # an older report: not again
            # the owner's "try again on the server" (0.18.5): the word goes even for a release it won't take by itself
            with mock.patch.object(U, "release_of", lambda src, commit: "v9.2.0"):
                self.assertEqual(await self.p.api_srv_retry(), {"ok": True, "v": "v9.2.0"})
            self.assertEqual(sent[-1], {"t": "want", "tag": "v9.2.0", "commit": "d" * 40, "retry": True})
            # the computer away after the switch: of the moment — nothing in Telegram, and it is reminded again
            await said({"t": "relay", "upd": dict(fail, why="no_mac_retry", tag="v9.2.0", ts=6)})
            await asyncio.sleep(0.1)
            self.assertEqual(len([x for x in self.texts() if "v9.2.0" in x]), 1)
            n = len(sent)
            with mock.patch.object(U, "release_of", lambda src, commit: "v9.2.0"):
                await self.p.announce(force=True)
            self.assertEqual(len(sent), n + 1)
            self.p.srv = {"can": [], "upd": None}                                   # no updater there: nothing to ask
            with self.assertRaises(ValueError):
                await self.p.api_srv_retry()
        self.p.web = None

    async def test_server_follows_the_developers_folder(self):
        # the folder releases are made in (the developer's own, Q83): it tells the server the newest release on GitHub not
        # newer than the version it runs, with GitHub's commit — asked at most every ANNOUNCE_EVERY
        sent, asked = [], []

        class Web:
            async def send(self, msg):
                sent.append(msg)

            def emit(self, kind, **data):
                pass

        def gh(repo, remote, proxy=None):
            asked.append(remote)
            return [((0, 18, 7), "v0.18.7", "c" * 40), ((0, 18, 6), "v0.18.6", "b" * 40), ((0, 18, 2), "v0.18.2", "a" * 40)]
        self.p.web, self.p.srv = Web(), {"can": ["want"], "upd": {"state": "idle", "have": "v0.18.2", "ts": 1}}
        rec = {"src": "/x/dev", "commit": "e" * 40}
        slow = lambda repo, remote, proxy=None: time.sleep(0.6) or gh(repo, remote, proxy)    # GitHub takes its time
        with mock.patch.object(U, "read", lambda name, default=None: dict(rec) if name == U.MANIFEST else default), \
                mock.patch.object(U, "makes_releases", lambda repo, head: True), \
                mock.patch.object(U, "remote_releases", gh), mock.patch.object(pultd, "VERSION", "0.18.6"):
            # the relay's word on connecting waits for nothing: the app's requests behind it on the link go on at once
            with mock.patch.object(U, "remote_releases", slow):
                t0 = time.monotonic()
                await self.p.relay_said({"t": "relay", "can": ["want"], "upd": {"state": "idle", "have": "v0.18.2", "ts": 1}})
                self.assertLess(time.monotonic() - t0, 0.3)
                self.assertEqual(sent, [])
                await self.p.announcing
            self.assertEqual(sent, [{"t": "want", "tag": "v0.18.6", "commit": "b" * 40}])
            await self.p.announce(force=True)
            self.assertEqual(len(asked), 1)                                          # GitHub asked once
            self.assertEqual(await self.p.api_srv_retry(), {"ok": True, "v": "v0.18.6"})
            self.assertEqual(sent[-1], {"t": "want", "tag": "v0.18.6", "commit": "b" * 40, "retry": True})
        self.p.web = self.p.srv = None

    async def test_release_look(self):
        # the daemon's look at GitHub for a release (stage U3; review 2026-10-27, Т7): off in Settings — GitHub isn't
        # asked; once a minute at most; a new release drops the cached install view and tells the app, the same one
        # again tells nothing
        looks = []

        def discover(src, remote, have, proxy):
            looks.append((src, remote, have))
            return True, "v9.9.0"
        web, self.p.web = self.p.web, mock.Mock()
        try:
            with mock.patch.object(U, "read", lambda name, default=None: {"src": "/x/pult"} if name == U.MANIFEST else default), \
                    mock.patch.object(U, "git", lambda repo, *a, **k: "c" * 40), \
                    mock.patch.object(U, "release_mode", lambda src, head: "origin"), \
                    mock.patch.object(U, "discover", discover), mock.patch.object(U, "installed_version", lambda: "9.8.0"):
                self.store.put("prefs", {"gh": False})
                await self.p.release_look(force=True)
                self.assertEqual(looks, [])
                self.store.put("prefs", {"gh": True})
                self.p._upd = (time.monotonic(), {"state": "ok"})
                # pultd's own clock, 5 s after the computer's boot: the first look happens whatever it says — on a
                # machine up for less than a minute it was skipped (a fresh CI machine, 2026-10-27)
                clock = types.SimpleNamespace(**{k: getattr(time, k) for k in dir(time) if not k.startswith("_")})
                clock.monotonic = lambda: now[0]
                now = [5.0]
                with mock.patch.object(pult_parts, "time", clock):
                    await self.p.release_look()
                    self.assertEqual(looks, [("/x/pult", "origin", "9.8.0")])
                    self.assertEqual((self.p.gh["tag"], self.p.gh["ok"], self.p._upd[0]), ("v9.9.0", True, 0.0))
                    self.p.web.emit.assert_called_with("update")
                    now[0] = 30.0
                    await self.p.release_look()                           # within the minute
                    self.assertEqual(len(looks), 1)
                self.p.web.emit.reset_mock()
                await self.p.release_look(force=True)                     # Settings opened: a look — nothing new
                self.assertEqual(len(looks), 2)
                self.p.web.emit.assert_not_called()
        finally:
            self.p.web = web
            self.store.put("prefs", {})

    async def test_expect_release(self):
        # the file check expects the release the server took — a difference closes the app (Q85), with PULT_GUARD=warn
        # (a CDN in front of the server) it only warns — and never replaces a deploy's record
        d = TMP / "expect"
        d.mkdir(exist_ok=True)
        man = d / "web-manifest.json"
        with mock.patch.object(pultd, "WEB_MANIFEST", man), \
                mock.patch.object(U, "read", lambda name, default=None: {"src": "/x/pult"} if name == U.MANIFEST else default), \
                mock.patch.object(U, "git", lambda repo, *a, **k: ancestor[0] if a[0] == "merge-base" else "c" * 40), \
                mock.patch.object(U, "manifest_at", lambda repo, commit: {"index": "<p>", "files": {"app.js": "0" * 64}}):
            ancestor = [None]
            self.p.expect_release("v9.1.0")
            m = json.loads(man.read_text())
            self.assertEqual((m["mode"], m["tag"], m["files"]), ("release", "v9.1.0", {"app.js": "0" * 64}))
            with mock.patch.dict(self.p.env, {"PULT_GUARD": "warn"}):
                self.p.expect_release("v9.1.0")                                  # the same release, the CDN switch on
                self.assertEqual(json.loads(man.read_text())["mode"], "warn")
            self.p.expect_release("v9.1.0")                                      # and off again
            self.assertEqual(json.loads(man.read_text())["mode"], "release")
            man.write_text(json.dumps({"index": "<p>", "files": {}}))              # a deploy script's record
            self.p.expect_release("v9.2.0")
            self.assertNotIn("mode", json.loads(man.read_text()))
            # a deploy's record of a commit: the developer's server moved to releases (Q83, Q90) — a release that holds
            # what was deployed takes its place; something deployed after the release keeps its record
            man.write_text(json.dumps({"index": "<p>", "files": {}, "commit": "d" * 40}))
            self.p.expect_release("v9.2.0")                                      # d isn't in it
            self.assertNotIn("mode", json.loads(man.read_text()))
            ancestor[0] = ""
            self.p.expect_release("v9.2.0")
            self.assertEqual(json.loads(man.read_text())["mode"], "release")

    async def test_guard_warns_only(self):
        # the file check on a release from GitHub (stage U3): with PULT_GUARD=warn a difference is told once and the app
        # stays open; without it — the default since Q85 — and with a deploy's record a difference closes the app
        PW = pultd.PW
        man = TMP / "guard-manifest.json"
        man.write_text(json.dumps({"index": "", "files": {}, "mode": "warn", "tag": "v9.1.0"}))
        w = PW.Web(self.p, "wss://h.example/pult/agent", "s", "T", {OWNER}, manifest=man)
        w.check_files = mock.AsyncMock(return_value=["app.js"])
        w.kick_all = mock.AsyncMock()
        alerts = []

        async def alert(bad, tag=None, warn=False):
            alerts.append((bad, tag, warn))
        with mock.patch.object(PW, "GUARD_RECHECK", 0), mock.patch.object(self.p, "files_alert", alert):
            await w.guard_once(None)
            await w.guard_once(None)
            self.assertEqual(alerts, [(["app.js"], "v9.1.0", True)])
            self.assertIsNone(w.locked)
            w.kick_all.assert_not_called()
            man.write_text(json.dumps({"index": "", "files": {}, "mode": "release", "tag": "v9.1.0"}))
            await w.guard_once(None)
            self.assertEqual((w.locked, alerts[-1]), ("app.js", (["app.js"], "v9.1.0", False)))
            w.kick_all.assert_called_once_with("locked")
            w.check_files = mock.AsyncMock(return_value=[])                    # the files match again: open
            await w.guard_once(None)
            self.assertIsNone(w.locked)
            w.check_files = mock.AsyncMock(return_value=["app.js"])
            man.write_text(json.dumps({"index": "", "files": {}}))
            await w.guard_once(None)
            self.assertEqual((w.locked, alerts[-1][1]), ("app.js", None))
            self.assertEqual(w.kick_all.call_count, 2)
        # the words in Telegram: closed by a release, told only with the CDN switch
        sent = []

        async def send(pkey, text, **kw):
            sent.append(text)
        with mock.patch.object(self.p, "send", send):
            await self.p.files_alert(["app.js"], tag="v9.1.0")
            await self.p.files_alert(["app.js"], tag="v9.1.0", warn=True)
        self.assertIn("Приложение закрыто", sent[0])
        self.assertIn("PULT_GUARD=warn", sent[0])
        self.assertIn("Приложение открыто", sent[1])

    async def test_parts_server(self):
        # stage U3, a clone of Pult's GitHub repository: the server's rows say whether it takes this computer's releases
        # itself and how its last one went; the developer's own folder hears nothing of it
        self.upd_reset(self.READY)
        f = {"upd": await self.p.update_view(), "git": dict(self.PARTS_GIT, release=True), "relay": True, "tabs": [],
             "hooks": list(pult_hook.EVENTS), "cc": dict(self.PARTS_CC), "srv": {"can": [], "upd": None}}
        rows = {r["k"]: r for r in self.p.parts_rows(f)}
        self.assertEqual((rows["web"]["auto"], "srv" in rows["web"]), (False, False))       # no updater: how to have it
        f["srv"] = {"can": ["want"], "upd": {"state": "run", "step": "fetch", "tag": "v9.1.0", "have": "v9.0.0", "ts": 1}}
        rows = {r["k"]: r for r in self.p.parts_rows(f)}
        self.assertEqual((rows["relay"]["auto"], rows["relay"]["st"], rows["relay"]["srv"]["step"]), (True, "warn", "fetch"))
        fail = {"state": "fail", "why": "no_start", "tag": "v9.1.0", "have": "v9.0.0", "back": True, "back_ok": True, "ts": 2}
        f["srv"]["upd"] = fail
        rows = {r["k"]: r for r in self.p.parts_rows(f)}
        # behind main: to update; as in main: worth a look
        self.assertEqual([(rows[k]["st"], rows[k]["srv"]["final"]) for k in ("web", "relay")], [("warn", True), ("attn", True)])
        # the server's updater and services as in the release this computer runs: nothing to do there (0.18.6)
        files = {"deploy/relay/update.py": "a" * 40, "deploy/relay/pult-relay.service": "b" * 40}
        f["git"] = dict(f["git"], srv_files=files)
        f["srv"]["upd"] = dict(fail, why="network", self=dict(files))
        rows = {r["k"]: r for r in self.p.parts_rows(f)}
        self.assertEqual([(rows[k]["st"], rows[k]["srv"]["final"]) for k in ("web", "relay")], [("warn", False), ("ok", False)])
        self.assertNotIn("self", rows["relay"]["srv"])
        # older than the release — which files; an updater before 0.18.6 doesn't say: "old" — either way install.sh once
        # (review 2026-10-27, У5)
        f["srv"]["upd"] = dict(fail, why="network", self=dict(files, **{"deploy/relay/update.py": "c" * 40}))
        rows = {r["k"]: r for r in self.p.parts_rows(f)}
        self.assertEqual((rows["relay"]["st"], rows["relay"]["srv"]["self"], "self" in rows["web"]["srv"]), ("warn", ["update.py"], False))
        f["srv"]["upd"] = dict(fail, why="network")
        self.assertEqual({r["k"]: r for r in self.p.parts_rows(f)}["relay"]["srv"]["self"], "old")
        self.assertEqual(pult_parts.srv_status({"state": "done", "self": {"deploy/relay/update.py": "a" * 40, "x": "nope", 5: "a" * 40}})["self"],
                         {"deploy/relay/update.py": "a" * 40})
        f["git"] = dict(self.PARTS_GIT)
        self.assertNotIn("auto", {r["k"]: r for r in self.p.parts_rows(f)}["web"])
        # the install block: the server takes the same release after this computer
        self.p.srv = {"can": ["want"], "upd": None}
        self.upd_reset(dict(self.READY, tag="v9.9.0"))
        self.assertTrue((await self.p.update_view())["srv"])
        self.upd_reset(self.READY)
        self.assertNotIn("srv", await self.p.update_view())
        self.p.srv = None

    async def test_note_health(self):
        # health.json — what the installer waits for: this daemon, when it started, the app's server reached
        self.upd_reset(self.READY)
        self.p.note_health(telegram=False, relay=False)
        self.p.note_health(relay=True)
        h = U.read(U.HEALTH)
        self.assertEqual((h["pid"], h["version"], h["relay"], h["telegram"]), (os.getpid(), pultd.VERSION, True, False))
        self.assertAlmostEqual(h["started"], self.p.t_start)

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
        # the edit goes through the outgoing queue: a slow Actions runner took over 5 s (macOS, v0.13.1 on main)
        await until(lambda: any("разрешено и больше не спросит" in t for t in self.texts("editMessageText")), timeout=15)
        # a decision tapped right in Telegram says no "from Telegram": the exact line
        proc = await run_hook(ev("PermissionRequest", tool_name="Bash", tool_input={"command": "git status"}), wait=False)
        await until(lambda: len(self.fake.buttons("p:")) > 0 and self.fake.buttons("p:")[-1].split(":")[1] != rid)
        rid2 = self.fake.buttons("p:")[-1].split(":")[1]
        await self.p.on_callback({"id": "3", "from": {"id": OWNER}, "data": "p:%s:y" % rid2})
        await proc.stdout.read()
        await until(lambda: any(t.endswith(" → <b>✔️ разрешено</b>") for t in self.texts("editMessageText")), timeout=15)

    async def test_permission_decided_in_flight(self):
        # decided while its message was still on its way (the computer's dialog, the app or a tap in that very moment):
        # the message closes as soon as its id is known — before, it kept Allow / Deny on a decided request for ever
        orig = self.p.send

        async def send(*a, **kw):
            m = await orig(*a, **kw)
            if kw.get("kind") == "perm":
                self.p.act(next(iter(self.p.req_by_rid.values())), "y")
            return m
        with mock.patch.object(self.p, "send", send):
            proc = await run_hook(ev("PermissionRequest", tool_name="Bash", tool_input={"command": "git status"}), wait=False)
            out = json.loads((await proc.stdout.read()).decode())
        self.assertEqual(out["hookSpecificOutput"]["decision"]["behavior"], "allow")
        await until(lambda: any(t.endswith(" → <b>✔️ разрешено</b>") for t in self.texts("editMessageText")))

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

    async def test_question_advice(self):
        # Claude's advice in a multi-select question is checked from the start — in Telegram and for the app — so
        # "Done" alone takes it; a single choice stays one tap with nothing checked (0.18.4)
        qs = [{"question": "Что выкладываем?", "header": "Выкладка", "multiSelect": True,
               "options": [{"label": "Сервер (Рекомендую)"}, {"label": "Выпуск на GitHub"}, {"label": "Другу (Recommended)"}]},
              {"question": "Лицензия?", "header": "Лицензия", "multiSelect": False,
               "options": [{"label": "MIT (Recommended)"}, {"label": "Apache-2.0"}]}]
        proc = await run_hook(ev("PermissionRequest", tool_name="AskUserQuestion", tool_input={"questions": qs}),
                              wait=False)
        await until(lambda: len([t for t in self.texts() if "Лицензия?" in t]) == 1)
        first = next(t for t in self.texts() if "Что выкладываем?" in t)
        self.assertIn("☑️ Сервер (Рекомендую)", first)
        self.assertIn("▫️ Выпуск на GitHub", first)
        self.assertIn("совет Claude уже отмечен", first)
        self.assertNotIn("☑️", next(t for t in self.texts() if "Лицензия?" in t))
        rid = self.fake.buttons("q:")[0].split(":")[1]
        self.assertEqual(self.p.req_item(self.p.req_by_rid[rid])["picks"],
                         {"0": ["Сервер (Рекомендую)", "Другу (Recommended)"]})
        for data in ("q:%s:0:2", "q:%s:0:ok", "q:%s:1:1"):          # one piece of advice unchecked, Done; the license
            await self.p.on_callback({"id": "x", "from": {"id": OWNER}, "data": data % rid})
        d = json.loads((await proc.stdout.read()).decode())["hookSpecificOutput"]["decision"]
        self.assertEqual(d["updatedInput"]["answers"], {"Что выкладываем?": "Сервер (Рекомендую)", "Лицензия?": "Apache-2.0"})

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
        d = SimpleNamespace(path="/x", resume=None, fork=False, sid="s", _wait_hook=None, d=self.p)
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


class TabCheckTest(unittest.IsolatedAsyncioTestCase):
    """pult_tabcheck (stage A) without Claude: what it reads off the output and the folders, and how a run goes —
    a second try for a failed step, trouble that isn't a failure, nothing left behind."""

    def test_trouble(self):
        import pult_tabcheck as C
        self.assertEqual(C.trouble("Invalid API key · Please run /login"), "login")
        self.assertEqual(C.trouble("Claude AI usage limit reached|1793030000"), "limit")
        self.assertEqual(C.trouble("Error: getaddrinfo ENOTFOUND api.anthropic.com"), "network")
        self.assertIsNone(C.trouble("TWO"))

    def test_binaries(self):
        import pult_tabcheck as C
        d = Path(tempfile.mkdtemp(dir=TMP))
        exe = "claude.exe" if os.name == "nt" else "claude"
        for v, has in (("2.1.310", True), ("2.1.311", True), ("2.1.312", False)):
            b = d / ("anthropic.claude-code-%s-darwin-arm64" % v) / "resources" / "native-binary"
            b.mkdir(parents=True)
            if has:
                (b / exe).write_text("")
        found = C.binaries([d, d / "nothing"])
        self.assertEqual(sorted(found), ["2.1.310", "2.1.311"])                    # no program — no version to check
        self.assertEqual(C.version_of(found["2.1.311"]), "2.1.311")
        self.assertEqual(max(found, key=C.vkey), "2.1.311")

    def test_forget(self):
        # only the check's own sessions leave Claude Code's history, and their folder once it's empty
        import pult_tabcheck as C
        root = Path(tempfile.mkdtemp(dir=TMP))
        a, b = root / "-tmp-pult-check-x-proj", root / "-Users-x-proj"
        a.mkdir()
        b.mkdir()
        (a / "s1.jsonl").write_text("{}")
        (a / "s1").mkdir()
        (b / "s2.jsonl").write_text("{}")
        (b / "mine.jsonl").write_text("{}")
        with mock.patch.object(C, "PROJECTS", root):
            C.forget({"s1", "s2"})
        self.assertFalse(a.exists())
        self.assertEqual([x.name for x in b.iterdir()], ["mine.jsonl"])

    async def test_tab_reads_what_goes_wrong(self):
        # how a tab session's failures read, without Claude (review 2026-10-27, Т7): an error result asking to log in
        # is trouble — the check didn't happen, try later; no answer at all fails the first step not done, unless
        # claude's own words say it is the network; claude gone — the same, with what it said
        import claude_agent_sdk as SDK
        import pult_tabcheck as C
        from claude_agent_sdk import ResultMessage

        class FakeSDK:
            script, errs = [], []          # what it says (an exception: it can't start) and claude's stderr

            def __init__(self, options):
                self.o = options

            async def __aenter__(self):
                for e in FakeSDK.errs:
                    self.o.stderr(e)
                if isinstance(FakeSDK.script, Exception):
                    raise FakeSDK.script
                return self

            async def __aexit__(self, *a):
                return False

            async def query(self, text):
                pass

            async def receive_messages(self):
                for m in FakeSDK.script:
                    yield m
                await asyncio.sleep(3600)

        class Server:
            def close(self):
                pass

        async def link(handler, path):
            return Server()
        login = ResultMessage(subtype="success", duration_ms=1, duration_api_ms=1, is_error=True, num_turns=1,
                              session_id="s1", result="Invalid API key · Please run /login")

        async def check(script, errs=()):
            FakeSDK.script, FakeSDK.errs = script, list(errs)
            ch = C.Check("/x/anthropic.claude-code-2.1.311-darwin-arm64/claude", "/w/pult_tab.py", "py", lambda *a: None)
            self.addCleanup(shutil.rmtree, ch.tmp, True)
            try:
                return await ch.tab(), ch.steps
            except C.Trouble as e:                  # by hand: assertRaises would clear the frames it caught
                return "trouble " + e.kind, ch.steps
        # the launcher is never run here: on Windows making one would read the wrapper's file, which isn't there
        with mock.patch.object(SDK, "ClaudeSDKClient", FakeSDK), mock.patch.object(pultd, "start_link", link), \
                mock.patch.object(C, "spawner", lambda *a: Path("spawn")), \
                mock.patch.object(C.Check, "service", mock.AsyncMock(return_value=True)), mock.patch.object(C, "WAIT", 0.3):
            self.assertEqual((await check([login]))[0], "trouble login")
            ok, steps = await check([])
            self.assertEqual((ok, [(s["k"], s["ok"]) for s in steps]), (False, [("own", False)]))
            self.assertIn("no answer", steps[0]["note"])
            self.assertEqual((await check([], ["Error: getaddrinfo ENOTFOUND api.anthropic.com"]))[0], "trouble network")
            ok, steps = await check(RuntimeError("claude exited with 1"))
            self.assertEqual((ok, steps[0]["k"], steps[0]["note"]), (False, "own", "RuntimeError: claude exited with 1"))
            self.assertEqual((await check(RuntimeError("exited"), ["Claude AI usage limit reached|1793030000"]))[0], "trouble limit")

    async def test_run(self):
        import pult_tabcheck as C
        outcomes = []

        async def tab(self):
            ok = outcomes.pop(0)
            if isinstance(ok, Exception):
                raise ok
            self.sids.add("s%d" % len(outcomes))
            self.steps.append({"k": "own", "ok": ok, "s": 1, "note": ""})
            return ok

        async def race(self):
            return True
        forgot, made, init = [], [], C.Check.__init__

        def made_by(self, *a):
            init(self, *a)
            made.append(self.tmp)
        with mock.patch.object(C.Check, "tab", tab), mock.patch.object(C.Check, "race", race), \
                mock.patch.object(C, "forget", forgot.append), mock.patch.object(C.Check, "__init__", made_by):
            outcomes[:] = [True]
            rep = await C.run("/x/anthropic.claude-code-2.1.311-darwin-arm64/claude", "/w/pult_tab.py", "py")
            self.assertEqual((rep["version"], rep["ok"], rep["race"], rep["error"]), ("2.1.311", True, True, None))
            outcomes[:] = [False, True]                 # one odd answer: passes on the second try
            rep = await C.run("/x/anthropic.claude-code-2.1.311-darwin-arm64/claude", "/w/pult_tab.py", "py")
            self.assertEqual((rep["ok"], len(rep["steps"]), "first" in rep), (True, 1, False))
            outcomes[:] = [False, False]
            rep = await C.run("/x/anthropic.claude-code-2.1.311-darwin-arm64/claude", "/w/pult_tab.py", "py")
            self.assertEqual((rep["ok"], rep["first"][0]["ok"]), (False, False))
            outcomes[:] = [C.Trouble("login", "Please run /login")]
            rep = await C.run("/x/anthropic.claude-code-2.1.311-darwin-arm64/claude", "/w/pult_tab.py", "py")
            self.assertEqual((rep["ok"], rep["error"], rep["race"]), (None, "login", None))
        self.assertEqual(len(forgot), 4)                # every run cleans up after itself
        self.assertTrue(len(made) == 4 and not any(d.exists() for d in made))


if __name__ == "__main__":
    try:
        unittest.main(verbosity=1)
    finally:
        shutil.rmtree(TMP, ignore_errors=True)
