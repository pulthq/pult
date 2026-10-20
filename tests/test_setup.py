#!/usr/bin/env python3
"""Checks for installing, setting up and removing Pult (pult_setup, pultctl) — without Telegram, launchd, systemd
or the real settings: every path points into a temporary folder, Telegram and the service are fakes.

  ~/.local/share/pult/venv/bin/python tests/test_setup.py
"""
import builtins
import getpass
import io
import json
import os
import plistlib
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest import mock
import zipfile

try:
    import pwd
except ImportError:                    # Windows
    pwd = None

SRC = Path(__file__).resolve().parent.parent / "src"
sys.path.insert(0, str(SRC))

import pult_i18n as I  # noqa: E402
import pult_os  # noqa: E402
import pult_setup as S  # noqa: E402
import pultctl  # noqa: E402

GOOD = "123456789:" + "A" * 35
OWNER, CHAT, BOT_ID = 42, -1001234567890, 777
WIN = os.name == "nt"
LAUNCHER = "pult.cmd" if WIN else "pult"


class FakeBot:
    """Bot API for pult_setup.bot_call. `updates` — batches for getUpdates; a batch may be a function that changes
    the fake's state (the owner fixed something in Telegram) and returns the batch."""

    def __init__(self):
        self.calls, self.updates, self.members, self.chats = [], [], {}, {}
        self.next_update = 100

    def __call__(self, token, method, proxy=None, http_timeout=20, **params):
        self.calls.append((method, params))
        if token != GOOD:
            raise S.TgError("Unauthorized", 401)
        if method == "getMe":
            return {"id": BOT_ID, "username": "test_pult_bot", "is_bot": True}
        if method == "getWebhookInfo":
            return {"url": ""}
        if method == "getUpdates":
            if params.get("offset") == -1 or params.get("timeout") == 0:
                return []
            batch = self.updates.pop(0) if self.updates else []
            return batch() if callable(batch) else batch
        if method == "getChat":
            return self.chats[params["chat_id"]]
        if method == "getChatMember":
            return self.members.get(params["chat_id"], {"status": "member"})
        return {"message_id": 1} if method == "sendMessage" else True

    def msg(self, chat, text, uid=OWNER, lang="ru", **chat_kw):
        self.next_update += 1
        return {"update_id": self.next_update, "message": {
            "message_id": self.next_update, "text": text, "chat": dict({"id": chat}, **chat_kw),
            "from": {"id": uid, "first_name": "Owner", "language_code": lang}}}

    def sent(self):
        return [p["text"] for m, p in self.calls if m == "sendMessage"]


def fake_manager(folder):
    """This system's service manager writing its files into folder, but never calling launchctl or systemctl."""
    class Fake(type(pult_os.service_manager())):
        def ctl(self, *a, **kw):
            return None

        def state(self, lbl):
            return None, None

        def problem(self):
            return None

        def stop(self, lbl):
            return True

        def start(self, lbl):
            return True

        def linger(self):
            return None
    return Fake(folder)


def service_env(path):
    """The environment a service file gives the daemon: a plist or a systemd unit (a Windows task has none)."""
    if path.suffix == ".plist":
        with open(path, "rb") as f:
            return plistlib.load(f)["EnvironmentVariables"]
    line = next(ln for ln in path.read_text().splitlines() if ln.startswith("Environment="))
    return dict(kv.split("=", 1) for kv in shlex.split(line[len("Environment="):]))


class Base(unittest.TestCase):
    """Every path of pult_setup in a temporary folder; the service is a fake."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="pult-setup-test-"))
        t = self.tmp
        self.paths = dict(HOME=t / "share", ENV_FILE=t / "conf" / "env", SOCK=str(t / "s.sock"), LOG=t / "pult.log",
                          PY=t / "share" / "venv" / "bin" / "python", PYW=t / "share" / "venv" / "Scripts" / "pythonw.exe",
                          SVC=fake_manager(t / "services"), BIN=t / "bin",
                          TAB_LOG=t / "pult-tab.log", SETTINGS=t / "claude" / "settings.json",
                          TAB_CONF=t / "conf" / "tab.json", TAB_OFF=t / "conf" / "tab-off",
                          EDITOR_DIRS=[t / "editors" / app / "User" for app in ("Code", "Cursor")]
                          + [t / ".vscode-server" / "data" / "Machine"],
                          EXT_DIRS=[t / "extensions", t / ".vscode-server" / "extensions"])
        self.patches = [mock.patch.object(S, k, v) for k, v in self.paths.items()]
        self.svc = SimpleNamespace(loaded=False, started=0, stopped=0)
        self.patches += [
            mock.patch.object(S, "service", lambda lbl: ("running", "1") if self.svc.loaded else (None, None)),
            mock.patch.object(S, "svc_stop", self.fake_stop),
            mock.patch.object(S, "svc_start", self.fake_start),
            mock.patch.object(S, "telegram_sessions", lambda lbl: 0),
            mock.patch.dict(os.environ, {"PULT_LANG": "en"}),
        ]
        for p in self.patches:
            p.start()
        I.set_lang("en")
        S.HOME.mkdir(parents=True)
        (S.HOME / "pultd.py").write_text('VERSION = "9.9.9"\n')
        (S.HOME / "pult_hook.py").write_text("")

    def tearDown(self):
        for p in reversed(self.patches):
            p.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def fake_stop(self, lbl):
        self.svc.loaded, self.svc.stopped = False, self.svc.stopped + 1
        return True

    def fake_start(self, lbl):
        self.svc.loaded, self.svc.started = True, self.svc.started + 1
        return True

    def run_cli(self, fn, *args, answers=(), secrets_=()):
        """Runs fn with scripted answers in the terminal; returns (result, output)."""
        answers, secrets_ = list(answers), list(secrets_)

        def fake_input(prompt=""):
            if not answers:
                raise AssertionError("unexpected question: %r" % prompt)
            sys.stdout.write(prompt + "\n")            # as the real input() does
            return answers.pop(0)

        out = io.StringIO()
        with mock.patch.object(builtins, "input", fake_input), \
                mock.patch.object(getpass, "getpass", lambda prompt="": secrets_.pop(0)), redirect_stdout(out):
            res = fn(*args)
        self.assertEqual((answers, secrets_), ([], []), "not every answer was used")
        return res, out.getvalue()


class SettingsTest(Base):
    def test_every_module_installed(self):
        # a new module in src/ must be copied by install.sh and known to the uninstaller: 0.9.13 forgot pult_stt.py in
        # install.sh and the daemon crashed at start until the file was put there by hand
        root = Path(__file__).resolve().parent.parent
        src = root / "src"
        inst = (root / "install.sh").read_text(encoding="utf-8")
        ps1 = (root / "install.ps1").read_text(encoding="utf-8-sig")
        for name in sorted(p.name for p in src.glob("pult*.py")):
            self.assertIn("src/" + name, inst, name)
            self.assertIn("'src/%s'" % name, ps1, name)                       # Windows copies the same files
            self.assertIn(name, S.HOME_FILES, name)
        self.assertTrue((root / "install.ps1").read_bytes().startswith(b"\xef\xbb\xbf"))   # 5.1 reads it as UTF-8

    def test_write_env(self):
        S.ENV_FILE.parent.mkdir(parents=True)
        S.ENV_FILE.write_text("# mine\nPULT_BOT_TOKEN=old\nOTHER=1\n")
        S.write_env(PULT_BOT_TOKEN="new", PULT_ALLOWED_USER_IDS="42", OTHER=None)
        self.assertEqual(S.ENV_FILE.read_text(encoding="utf-8"), "# mine\nPULT_BOT_TOKEN=new\nPULT_ALLOWED_USER_IDS=42\n")
        if not WIN:                                    # Windows: the user's own folder is what keeps it private
            self.assertEqual(S.ENV_FILE.stat().st_mode & 0o777, 0o600)
        self.assertEqual(S.read_env(), {"PULT_BOT_TOKEN": "new", "PULT_ALLOWED_USER_IDS": "42"})

    def test_label(self):
        # an existing install keeps its service name: found by the service file that runs this copy of Pult
        self.assertEqual(S.label(), S.DEFAULT_LABEL)
        script = S.HOME / "pultd.py"
        mac, linux = pult_os.Launchd(self.tmp / "agents"), pult_os.Systemd(self.tmp / "units")
        mac.folder.mkdir()
        (mac.folder / "other.plist").write_bytes(b"not a plist")
        mac.write("com.someone.pult", ["py", "-u", script], {}, "log", "/")
        self.assertEqual(mac.find(script), "com.someone.pult")
        linux.folder.mkdir()
        (linux.folder / "other.service").write_text("[Service]\nExecStart=/bin/true\n")
        linux.write("my-pult", ["py", "-u", script], {}, "log", "/")
        self.assertEqual(linux.find(script), "my-pult")
        self.assertIsNone(linux.find(S.HOME / "elsewhere.py"))
        S.SVC.write("their.pult", ["py", "-u", script], {}, "log", "/")
        self.assertEqual(S.label(), "their.pult")
        S.write_env(PULT_LABEL="io.example.pult")
        self.assertEqual(S.label(), "io.example.pult")

    def test_service_file(self):
        # what the service runs and with which settings — the same on macOS and Linux; Windows: test_task
        p = S.write_service("io.github.pulthq.pult")
        self.assertEqual(p, S.service_file("io.github.pulthq.pult"))
        if WIN:
            text = p.read_text(encoding="utf-16")
            self.assertIn(pult_os.xml_esc(S.HOME / "pultd.py"), text)
            self.assertIn("<Command>%s</Command>" % pult_os.xml_esc(S.PYW), text)       # pythonw: no console window
            self.assertIn("<Arguments>-X utf8 ", text)
            return
        self.assertIn(str(S.HOME / "pultd.py"), p.read_text())
        env = service_env(p)
        self.assertEqual(env["PULT_LABEL"], "io.github.pulthq.pult")
        self.assertEqual(env["PATH"], S.SERVICE_PATH)
        with mock.patch.dict(os.environ, {"HOME": pwd.getpwuid(os.getuid()).pw_dir}):    # the real home
            self.assertNotIn("HOME", service_env(S.write_service("x")))
        with mock.patch.dict(os.environ, {"HOME": str(self.tmp / "friend")}):       # a trial install
            self.assertEqual(service_env(S.write_service("x"))["HOME"], str(self.tmp / "friend"))

    def test_plist(self):
        m = pult_os.Launchd(self.tmp / "agents")
        with open(m.write("io.github.pulthq.pult", ["/p y/python", "-u", "/p y/pultd.py"],
                          {"PATH": pult_os.service_path("/b"), "PULT_LABEL": "io.github.pulthq.pult"},
                          "/l/pult.log", "/p y"), "rb") as f:
            d = plistlib.load(f)
        self.assertEqual(d["Label"], "io.github.pulthq.pult")
        self.assertEqual(d["ProgramArguments"], ["/p y/python", "-u", "/p y/pultd.py"])
        self.assertEqual(d["EnvironmentVariables"]["PULT_LABEL"], "io.github.pulthq.pult")
        self.assertTrue(d["KeepAlive"])
        self.assertEqual(d["StandardOutPath"], "/l/pult.log")

    def test_task(self):
        # Windows: a Task Scheduler task — at logon, as the user, in the user's session, restarted after a failure;
        # the definition is UTF-16 (schtasks reads nothing else) and the paths are XML-escaped and quoted
        import xml.etree.ElementTree as ET
        m = pult_os.Schtasks(self.tmp / "share2")
        with mock.patch.object(pult_os.Schtasks, "user", staticmethod(lambda: "PC\\Анна & Co")):
            p = m.write("Pult", [r"C:\Users\Анна\venv\Scripts\pythonw.exe", "-X", "utf8", r"C:\Users\Анна\a b\pultd.py"],
                        {"PATH": "x"}, "log", r"C:\Users\Анна\a b")
        self.assertEqual(p.name, "Pult.task.xml")
        self.assertTrue(p.read_bytes().startswith(b"\xff\xfe"))                  # UTF-16 LE with its BOM
        ns = {"t": "http://schemas.microsoft.com/windows/2004/02/mit/task"}
        root = ET.fromstring(p.read_text(encoding="utf-16").split("?>", 1)[1])
        f = lambda path: root.find(path, ns).text
        self.assertEqual(f("t:Triggers/t:LogonTrigger/t:UserId"), "PC\\Анна & Co")
        self.assertEqual(f("t:Principals/t:Principal/t:LogonType"), "InteractiveToken")
        self.assertEqual(f("t:Principals/t:Principal/t:RunLevel"), "LeastPrivilege")
        self.assertEqual(f("t:Settings/t:ExecutionTimeLimit"), "PT0S")
        self.assertEqual(f("t:Settings/t:RestartOnFailure/t:Count"), "999")
        self.assertEqual(f("t:Actions/t:Exec/t:Command"), r"C:\Users\Анна\venv\Scripts\pythonw.exe")
        self.assertEqual(f("t:Actions/t:Exec/t:Arguments"), r'-X utf8 "C:\Users\Анна\a b\pultd.py"')
        self.assertEqual(m.find(r"C:\Users\Анна\a b\pultd.py"), "Pult")
        self.assertIsNone(m.find(r"C:\elsewhere\pultd.py"))
        # the state is the daemon's own: the pid in its link file, alive or not
        m.link.parent.mkdir(parents=True, exist_ok=True)
        m.link.write_text(json.dumps({"port": 1, "key": "k", "pid": os.getpid()}), encoding="utf-8")
        self.assertEqual(m.state("Pult"), ("running", str(os.getpid())))
        m.link.write_text("{}", encoding="utf-8")
        self.assertEqual(m.state("Pult"), (None, None))

    def test_systemd_unit(self):
        # quotes keep a path with spaces whole; % and $ would be expanded by systemd — doubled
        m = pult_os.Systemd(self.tmp / "units")
        text = m.write("pult", ["/home/a b/venv/bin/python", "-u", "/home/a b/pult%d$X.py"],
                       {"PATH": "/x:/usr/bin", "PULT_LABEL": "pult"}, "/home/a b/.local/state/pult/pult.log",
                       "/home/a b/pult").read_text()
        self.assertEqual(m.path("pult").name, "pult.service")
        self.assertIn('ExecStart="/home/a b/venv/bin/python" "-u" "/home/a b/pult%%d$$X.py"\n', text)
        self.assertIn('Environment="PATH=/x:/usr/bin" "PULT_LABEL=pult"\n', text)
        self.assertIn("Restart=always\n", text)
        self.assertIn("StartLimitIntervalSec=0\n", text)
        self.assertIn("StandardOutput=append:/home/a b/.local/state/pult/pult.log\n", text)
        self.assertIn("WantedBy=default.target\n", text)
        self.assertEqual(m.find("/home/a b/pult%d$X.py"), "pult")

    def test_hooks_exec_form(self):
        # Windows: exec form — base pythonw and the hook file as an argument; recognised and removed like the shell one
        S.SETTINGS.parent.mkdir()
        mine = {"PreToolUse": [{"matcher": "Bash", "hooks": [{"type": "command", "command": "guard.sh",
                                                              "args": ["--strict"]}]}]}
        S.SETTINGS.write_text(json.dumps({"hooks": mine}))
        with mock.patch.object(S, "WIN", True), mock.patch.object(S, "base_pythonw", lambda: Path("C:/Py/pythonw.exe")):
            self.run_cli(S.hooks_set, True)
            d = json.loads(S.SETTINGS.read_text(encoding="utf-8"))
            h = d["hooks"]["Stop"][0]["hooks"][0]
            self.assertEqual(h["command"], str(Path("C:/Py/pythonw.exe")))
            self.assertEqual(h["args"], [str(S.HOME / "pult_hook.py"), "--sock=" + S.SOCK])   # not the default link
            self.assertEqual(S.hooks_installed(d), sorted(S.pult_hook.EVENTS))
            self.run_cli(S.hooks_set, False)
        self.assertEqual(json.loads(S.SETTINGS.read_text(encoding="utf-8")), {"hooks": mine})

    @unittest.skipIf(WIN, "a shell command: macOS and Linux")
    def test_hooks(self):
        # Pult's hooks on the environment's Python; other hooks stay; a backup copy before every change
        S.SETTINGS.parent.mkdir()
        mine = {"PreToolUse": [{"matcher": "Bash", "hooks": [{"type": "command", "command": "guard.sh"}]}]}
        S.SETTINGS.write_text(json.dumps({"model": "x", "hooks": mine}))
        self.run_cli(S.hooks_set, True)
        d = json.loads(S.SETTINGS.read_text())
        self.assertEqual(S.hooks_installed(d), sorted(S.pult_hook.EVENTS))
        cmd = d["hooks"]["Stop"][0]["hooks"][0]["command"]
        self.assertIn("PULT_SOCK=%s exec %s " % (S.SOCK, S.PY), cmd)               # a non-default socket is passed
        # no environment (being rebuilt, or Pult removed while sessions are open) — exit 0, nothing printed
        p = subprocess.run(["/bin/sh", "-c", cmd], input="{}", capture_output=True, text=True, timeout=10)
        self.assertEqual((p.returncode, p.stdout, p.stderr), (0, "", ""))
        S.PY.parent.mkdir(parents=True)
        os.symlink(sys.executable, S.PY)
        (S.HOME / "pult_hook.py").write_text("import os, sys; print(sys.stdin.read(), os.environ['PULT_SOCK'])")
        p = subprocess.run(["/bin/sh", "-c", cmd], input="{}", capture_output=True, text=True, timeout=10)
        self.assertEqual(p.stdout, "{} %s\n" % S.SOCK)
        self.assertEqual(d["hooks"]["PreToolUse"], mine["PreToolUse"])
        # hooks from an older Pult lack a newer event: the status says which, and how to add it
        old = dict(d, hooks={k: v for k, v in d["hooks"].items() if k != "StopFailure"})
        S.SETTINGS.write_text(json.dumps(old))
        out = io.StringIO()
        with redirect_stdout(out), mock.patch.object(S, "service", lambda lbl: (None, None)), \
                mock.patch.object(S, "sock_ok", lambda: False):
            pultctl.cmd_status()
        self.assertIn("— not yet StopFailure: run pult hooks on", out.getvalue())
        S.SETTINGS.write_text(json.dumps(d))
        self.run_cli(S.hooks_set, False)
        self.assertEqual(json.loads(S.SETTINGS.read_text()), {"model": "x", "hooks": mine})
        self.assertTrue(list(S.SETTINGS.parent.glob("settings.json.bak-pult-*")))

    def test_launcher(self):
        with mock.patch.dict(os.environ, {"PULT_HOME": ""}):
            self.assertIsNotNone(S.write_launcher())
            text = (S.BIN / LAUNCHER).read_text(encoding="utf-8")
            if WIN:                                    # pult.cmd: ASCII, the paths through %USERPROFILE%
                self.assertIn('(goto) 2>nul & ', text)
                self.assertIn(S.LAUNCHER_MARK, text)
            else:
                self.assertIn(str(S.HOME / "pultctl.py"), text)
            (S.BIN / LAUNCHER).write_text("#!/bin/sh\necho someone else's\n")
            res, out = self.run_cli(S.write_launcher)
            self.assertIsNone(res)
            self.assertIn("already belongs to another program", out)
            self.assertIn("someone else's", (S.BIN / LAUNCHER).read_text())

    def test_windows_launcher(self):
        # pult.cmd: cmd reads it in the console's code page — ASCII, a home with Cyrillic in it through %USERPROFILE%
        home = self.tmp / "Анна"
        with mock.patch.dict(os.environ, {"PULT_HOME": ""}), mock.patch.object(S, "WIN", True), \
                mock.patch.object(S.Path, "home", lambda: home), mock.patch.object(S, "PY", home / "venv" / "python.exe"), \
                mock.patch.object(S, "HOME", home / "pult"):
            p = S.write_launcher()
        self.assertEqual(p.name, "pult.cmd")
        data = p.read_bytes()
        data.decode("ascii")
        self.assertIn(b'"%USERPROFILE%' + os.sep.encode() + b'venv' + os.sep.encode() + b'python.exe" -X utf8 ', data)
        self.assertIn(b"\r\n(goto) 2>nul & ", data)                      # uninstall deletes the file while it runs
        self.assertTrue(data.endswith(b" %*\r\n"))
        self.assertNotIn(b"\r\r", data)

    def test_cli_lang(self):
        with mock.patch.dict(os.environ, {"PULT_LANG": ""}), mock.patch.object(S, "system_lang", lambda: "en"):
            self.assertEqual(S.cli_lang(), "en")
            S.sput(lang_tg="ru")
            self.assertEqual(S.cli_lang(), "ru")
            S.sput(prefs={"lang": "en"})
            self.assertEqual(S.cli_lang(), "en")

    def test_usage(self):
        out = io.StringIO()
        with redirect_stdout(out):
            self.assertEqual(pultctl.main(["help"]), 0)
            self.assertEqual(pultctl.main(["nonsense"]), 2)
        self.assertIn("pult setup", out.getvalue())

    def test_install_not_set_up(self):
        # install.sh without a terminal and without settings: the service file is written, the setup is suggested
        with mock.patch.object(sys.stdin, "isatty", lambda: False):
            res, out = self.run_cli(S.cmd_install)
        self.assertEqual(res, 0)
        self.assertIn("pult setup", out)
        self.assertTrue(S.service_file(S.DEFAULT_LABEL).exists())
        self.assertEqual(self.svc.started, 0)


class SetupTest(Base):
    def test_wizard(self):
        fake = FakeBot()
        fake.chats[CHAT] = {"id": CHAT, "title": "Pult", "is_forum": True}
        fake.updates = [
            [fake.msg(OWNER, "/start", uid=9, type="private")],                  # someone without the code: ignored
            [fake.msg(OWNER, "/start c0de42", type="private")],                   # the owner, by the link
            [fake.msg(OWNER, "/bind", type="private")],                           # in the private chat: how to
            [fake.msg(-55, "/bind", uid=9, type="supergroup")],                   # not the owner: ignored
            [fake.msg(-55, "/bind@test_pult_bot", type="group", title="Old")],    # no topics: told so
            [fake.msg(CHAT, "/bind", type="supergroup", is_forum=True, title="Pult")],   # not an admin yet
            lambda: (fake.members.update({CHAT: {"status": "administrator", "can_manage_topics": True}})
                     or [fake.msg(CHAT, "/bind", type="supergroup", is_forum=True, title="Pult")]),
        ]
        S.SETTINGS.parent.mkdir()
        with mock.patch.object(S, "bot_call", fake), mock.patch.object(S.secrets, "token_hex", lambda n: "c0de42"), \
                mock.patch.dict(os.environ, {"PULT_LANG": ""}):
            res, out = self.run_cli(S.cmd_setup, answers=["y"],
                                    secrets_=["oops", "123:AAA BBB", "987654321:" + "B" * 35, GOOD])
        self.assertEqual(res, 0, out)
        env = S.read_env()
        self.assertEqual((env["PULT_BOT_TOKEN"], env["PULT_ALLOWED_USER_IDS"]), (GOOD, str(OWNER)))
        self.assertEqual((S.sget("chat"), S.sget("welcome"), S.sget("lang_tg")), (CHAT, True, "ru"))
        self.assertEqual(S.sget("offset"), fake.next_update + 1)
        self.assertIn("https://t.me/test_pult_bot?start=c0de42", out)
        self.assertIn("✗ Telegram doesn't accept this token", out)
        self.assertEqual(out.count("doesn't look like a bot token"), 2)        # never went into a URL
        sent = fake.sent()
        self.assertTrue(sent[0].startswith("✅ Пульт тебя узнал"), sent)     # in the owner's Telegram language
        self.assertEqual(sent[1], I.T("bind.private", "ru"))
        self.assertEqual(sent[2], I.T("bind.need_forum", "ru"))
        self.assertTrue(sent[3].startswith("Сделай меня админом"))
        self.assertTrue(sent[4].startswith("✅ Теперь это группа Пульта"))
        self.assertIn("(не в чате с ботом)", out)                           # the group step says where /bind goes
        self.assertIn("Хуки Пульта", out)                                   # after /start the setup speaks Russian
        self.assertEqual(S.hooks_installed(), sorted(S.pult_hook.EVENTS))
        self.assertEqual(self.svc.started, 1)
        self.assertTrue(S.service_file(S.DEFAULT_LABEL).exists())

    def test_rerun_keeps_everything(self):
        # a second run: Enter keeps the bot, the owner and the group; the running service is paused and started
        fake = FakeBot()
        fake.chats[CHAT] = {"id": CHAT, "title": "Pult", "is_forum": True}
        fake.members[CHAT] = {"status": "administrator", "can_manage_topics": True}
        S.write_env(PULT_BOT_TOKEN=GOOD, PULT_ALLOWED_USER_IDS=str(OWNER))
        S.sput(chat=CHAT, offset=500)
        S.SETTINGS.parent.mkdir()
        S.SETTINGS.write_text(json.dumps({"hooks": S.pult_hook.hooks_config("x pult_hook.py")}))
        self.svc.loaded = True
        with mock.patch.object(S, "bot_call", fake):
            res, out = self.run_cli(S.cmd_setup, answers=["", "", ""])
        self.assertEqual(res, 0, out)
        self.assertEqual((self.svc.stopped, self.svc.started), (2, 1))   # paused for the setup, then restarted
        self.assertEqual((S.sget("chat"), S.sget("offset"), S.sget("welcome")), (CHAT, 500, None))
        self.assertNotIn("getUpdates", [m for m, _ in fake.calls])       # nothing read: the daemon's messages stay
        self.assertIn("hooks are on", out)

    def test_group_lost(self):
        # the bound group lost its topics: the setup says why and asks for /bind again
        fake = FakeBot()
        fake.chats[CHAT] = {"id": CHAT, "title": "Pult", "is_forum": False}
        S.sput(chat=CHAT)
        with mock.patch.object(S, "bot_call", fake):
            title, problem = S.group_check(S.Bot(GOOD), {"id": BOT_ID}, CHAT)
        self.assertEqual((title, problem), ("Pult", "topics are off"))


class SetupFailTest(Base):
    def prepared(self):
        fake = FakeBot()
        fake.chats[CHAT] = {"id": CHAT, "title": "Pult", "is_forum": True}
        fake.members[CHAT] = {"status": "administrator", "can_manage_topics": True}
        S.write_env(PULT_BOT_TOKEN=GOOD, PULT_ALLOWED_USER_IDS=str(OWNER))
        S.sput(chat=CHAT)
        self.svc.loaded = True
        return fake

    def test_closed_input(self):
        # no one at the terminal (closed input): stop at once, and the paused Pult runs again
        fake = self.prepared()

        def eof(prompt=""):
            raise EOFError
        out = io.StringIO()
        with mock.patch.object(S, "bot_call", fake), mock.patch.object(builtins, "input", eof), redirect_stdout(out):
            self.assertEqual(S.cmd_setup(), 1)
        self.assertIn("Setup stopped", out.getvalue())
        self.assertTrue(self.svc.loaded)

    def test_unreadable_settings(self):
        # settings.json with comments: hooks are left alone, the setup stops, Pult runs again
        fake = self.prepared()
        S.SETTINGS.parent.mkdir()
        S.SETTINGS.write_text('{ // mine\n "model": "x" }')
        with mock.patch.object(S, "bot_call", fake):
            res, out = self.run_cli(S.cmd_setup, answers=["", "", "", "y"])
        self.assertEqual(res, 1)
        self.assertIn("isn't plain JSON", out)
        self.assertEqual(S.SETTINGS.read_text(), '{ // mine\n "model": "x" }')
        self.assertTrue(self.svc.loaded)

    def test_crash(self):
        # an error nobody expected: a short message without a traceback, Pult runs again
        fake = self.prepared()
        with mock.patch.object(S, "bot_call", fake), mock.patch.object(S, "step_hooks", lambda: 1 / 0):
            res, out = self.run_cli(S.cmd_setup, answers=["", "", ""])
        self.assertEqual(res, 1)
        self.assertIn("Something went wrong (ZeroDivisionError)", out)
        self.assertTrue(self.svc.loaded)

    def test_bad_url_no_token(self):
        # a token with a space or a line break never shows up in an error (the URL contains it)
        for bad in ("123456:AAA BBB", "123456:AAA\nBBB"):
            with self.assertRaises(S.TgError) as e:
                S.bot_call(bad, "getMe", proxy="")
            self.assertNotIn("AAA", str(e.exception))

    def test_symlinked_settings(self):
        real = self.tmp / "dotfiles" / "settings.json"
        real.parent.mkdir()
        real.write_text("{}")
        S.SETTINGS.parent.mkdir()
        S.SETTINGS.symlink_to(real)
        self.run_cli(S.hooks_set, True)
        self.assertTrue(S.SETTINGS.is_symlink())
        self.assertIn("pult_hook.py", real.read_text())


class ReportTest(Base):
    def test_redactor(self):
        home = str(Path.home())
        hide = S.redactor({"PULT_RELAY_SECRET": "s3cr3t-value-xyz", "PULT_LABEL": "com.x.pult"})
        cases = {
            "10:00:00 ← topic garden: сделай отчёт": "10:00:00 ← …",
            "job 1a2b3c4d: sh -c 'rm x' · %s/Documents/garden" % home: "job 1a2b3c4d: …",
            "Pult started; group: -1001234567890 ; socket: %s/.local/share/pult/pult.sock" % home:
                "Pult started; group: <id> ; socket: ~/.local/share/pult/pult.sock",
            "tab with the wrapper: pid 25434, %s/Documents/secret-proj, Claude Code 2.1.301" % home:
                "tab with the wrapper: pid 25434, ~/…, Claude Code 2.1.301",
            "getUpdates: %s failed" % GOOD: "getUpdates: <token> failed",
            "httpx: https://api.telegram.org/bot%s/getMe" % GOOD.replace("A", "C"):
                "httpx: https://api.telegram.org/bot<token>/getMe",
            "web: key s3cr3t-value-xyz leaked": "web: key <secret> leaked",
            "button o:abc from 42 → garden": "button o:abc from 42 → …",
            "Bash #s1234abcd: allow — denied: do not touch prod": "Bash #s1234abcd: allow — …",
            "topic created: atlas": "topic created: …",
            "AskUserQuestion #sb1234567: answered on the Mac": "AskUserQuestion #sb1234567: answered on the Mac",
            "button o:abc from 123456789 → x": "button o:abc from <id> → …",
            "proxying a tab: /private/var/folders/x/T/sandbox 2.1.301": "proxying a tab: /… 2.1.301",
            "tab with the wrapper: pid 7, C:\\Users\\x\\Documents\\secret-proj, Claude Code 2.1.301":
                "tab with the wrapper: pid 7, ?:\\…, Claude Code 2.1.301",
            "socket: ~\\AppData\\Local\\pult\\pult.sock, project ~\\Documents\\secret-proj":
                "socket: ~\\AppData\\Local\\pult\\pult.sock, project ~\\…",
            "proxying a tab: /home/someone/secret-proj and /mnt/data/x": "proxying a tab: /… and /…",
            "log: %s/.local/state/pult/pult.log, settings %s/.config/Code/User/settings.json" % (home, home):
                "log: ~/.local/state/pult/pult.log, settings ~/…",
        }
        for line, want in cases.items():
            self.assertEqual(hide(line), want, line)

    def test_report(self):
        S.write_env(PULT_BOT_TOKEN=GOOD, PULT_ALLOWED_USER_IDS=str(OWNER), PULT_RELAY_SECRET="s3cr3t-value-xyz")
        S.LOG.write_text("2026-10-17 10:00:00 ← topic garden: private text\n"
                         "2026-10-17 10:00:01 Pult started; group: -1001234567890 ; socket: x\n")
        with mock.patch.object(S, "bot_call", FakeBot()):
            res, out = self.run_cli(S.cmd_report)
        for secret in (GOOD, "s3cr3t-value-xyz", "1001234567890", "private text", "garden", str(OWNER) + " "):
            self.assertNotIn(secret, out)
        self.assertIn("Pult 9.9.9", out)
        self.assertIn("Telegram: direct ok", out)
        self.assertIn("settings: token set · owner set · group —", out)


class UninstallTest(Base):
    def wrapper_line(self):
        return '{"claudeCode.claudeProcessWrapper": %s}' % json.dumps(str(S.HOME / S.TAB_FILE))

    def stub_left(self):
        """The wrapper left in place just runs claude: pult-tab.sh execs it; pult-tab.exe calls pult_tab.direct."""
        if WIN:
            with zipfile.ZipFile(S.HOME / "pult-tab.exe") as z:
                return "pult_tab.direct(" in z.read("__main__.py").decode()
        return 'exec "$@"' in (S.HOME / "pult-tab.sh").read_text()

    def prepare(self, wrapped):
        S.write_env(PULT_BOT_TOKEN=GOOD)
        S.TAB_CONF.write_text("{}")
        (S.ENV_FILE.parent / "notes.txt").write_text("someone's file")         # not Pult's: stays
        (S.HOME / "venv" / "bin").mkdir(parents=True)
        (S.HOME / "state.db").write_text("")
        (S.HOME / S.TAB_FILE).write_text("wrapper")
        (S.HOME / "pult_tab.py").write_text("# the wrapper\n")
        S.SETTINGS.parent.mkdir()
        S.SETTINGS.write_text(json.dumps({"hooks": S.pult_hook.hooks_config("py pult_hook.py")}))
        S.write_service(S.label())
        S.BIN.mkdir()
        (S.BIN / LAUNCHER).write_text("#!/bin/sh\n%s\n" % S.LAUNCHER_MARK)
        S.LOG.write_text("log")
        vs = S.EDITOR_DIRS[0] / "settings.json"
        vs.parent.mkdir(parents=True)
        vs.write_text(self.wrapper_line() if wrapped else "{}")

    def test_keeps_tab_stub(self):
        # VS Code still runs tabs through the wrapper: a pass-through stub stays, settings are kept
        self.prepare(wrapped=True)
        with mock.patch.dict(os.environ, {"PULT_HOME": ""}):
            res, out = self.run_cli(S.cmd_uninstall, answers=["y", "n"])
        self.assertEqual(res, 0)
        self.assertEqual(sorted(p.name for p in S.HOME.iterdir()), [S.TAB_FILE])
        self.assertTrue(self.stub_left())
        self.assertEqual(S.hooks_installed(), [])
        self.assertFalse((S.BIN / LAUNCHER).exists())
        self.assertFalse(S.service_file(S.DEFAULT_LABEL).exists())
        self.assertTrue(S.ENV_FILE.exists() and S.LOG.exists())
        self.assertIn("claudeCode.claudeProcessWrapper", out)

    def test_removes_all(self):
        self.prepare(wrapped=False)
        logs = self.tmp / "state" / "pult"                                  # Linux: a log folder of its own
        logs.mkdir(parents=True)
        with mock.patch.dict(os.environ, {"PULT_HOME": ""}), mock.patch.object(S, "LOG", logs / "pult.log"), \
                mock.patch.object(S, "TAB_LOG", logs / "pult-tab.log"):
            S.LOG.write_text("log")
            self.run_cli(S.cmd_uninstall, answers=["y", "y"])
        self.assertFalse(S.HOME.exists())
        self.assertFalse(S.ENV_FILE.exists() or S.TAB_CONF.exists() or logs.exists())
        self.assertTrue(logs.parent.exists())
        self.assertEqual([p.name for p in S.ENV_FILE.parent.iterdir()], ["notes.txt"])

    def test_fork_editor(self):
        # the wrapper set in a Cursor profile: the stub stays, and the message names that file
        self.prepare(wrapped=False)
        prof = S.EDITOR_DIRS[1] / "profiles" / "p1" / "settings.json"
        prof.parent.mkdir(parents=True)
        prof.write_text(self.wrapper_line())
        res, out = self.run_cli(S.cmd_uninstall, answers=["y", "n"])
        self.assertTrue(self.stub_left())
        self.assertIn(os.path.join("Cursor", "User", "profiles", "p1", "settings.json"), out)

    def test_remote_ssh(self):
        # a server VS Code reaches through Remote-SSH: the wrapper is in its remote machine settings
        self.prepare(wrapped=False)
        remote = S.EDITOR_DIRS[2] / "settings.json"
        remote.parent.mkdir(parents=True)
        remote.write_text(self.wrapper_line())
        self.assertTrue(S.tab_wrapped())
        res, out = self.run_cli(S.cmd_uninstall, answers=["y", "n"])
        self.assertTrue(self.stub_left())
        self.assertIn(os.path.join(".vscode-server", "data", "Machine", "settings.json"), out)

    def test_unreadable_settings(self):
        # hooks can't be removed from settings.json — nothing is deleted
        self.prepare(wrapped=False)
        S.SETTINGS.write_text('{ // "x pult_hook.py" }')
        res, out = self.run_cli(S.cmd_uninstall)
        self.assertEqual(res, 1)
        self.assertTrue((S.HOME / "state.db").exists())

    def test_cancel(self):
        self.prepare(wrapped=False)
        res, out = self.run_cli(S.cmd_uninstall, answers=[""])
        self.assertEqual(res, 1)
        self.assertTrue((S.HOME / "state.db").exists())
        self.assertEqual(len(S.hooks_installed()), len(S.pult_hook.EVENTS))


class AppTest(Base):
    def test_app(self):
        S.write_env(PULT_BOT_TOKEN=GOOD, PULT_ALLOWED_USER_IDS=str(OWNER))
        S.sput(chat=CHAT)
        self.svc.loaded = True
        with mock.patch.object(S, "bot_call", FakeBot()):
            res, out = self.run_cli(S.cmd_app, [], answers=["http://plain.example", "https://example.com/pult/", ""])
        env = S.read_env()
        self.assertEqual(env["PULT_RELAY_URL"], "wss://example.com/pult/agent")
        self.assertEqual(env["PULT_APP_LINK"], "https://t.me/test_pult_bot/pult")
        self.assertGreater(len(env["PULT_RELAY_SECRET"]), 30)
        self.assertIn("It needs an https:// address", out)
        self.assertIn("PULT_OWNER_ID=42\n  PULT_BOT_ID=123456789", out)
        self.assertEqual(self.svc.started, 1)
        # again: the current address is the default, the secret stays
        key = env["PULT_RELAY_SECRET"]
        with mock.patch.object(S, "bot_call", FakeBot()):
            _, out = self.run_cli(S.cmd_app, [], answers=["", ""])
        self.assertIn("Enter — https://example.com/pult/", out)
        self.assertEqual(S.read_env()["PULT_RELAY_SECRET"], key)
        self.run_cli(S.cmd_app, ["off"])
        self.assertNotIn("PULT_RELAY_URL", S.read_env())

    def test_stt(self):
        # pult stt: the key is checked with Groq and written; a bad key — refused, nothing written; Enter keeps the
        # current one; off — removed. No restart: the daemon re-reads the file by itself
        S.write_env(PULT_BOT_TOKEN=GOOD, PULT_ALLOWED_USER_IDS=str(OWNER))
        S.sput(chat=CHAT)
        checked = []
        with mock.patch.object(S, "stt_check", lambda key, proxy=None: checked.append((key, proxy))):
            res, out = self.run_cli(S.cmd_stt, [], secrets_=["gsk_live_key_0001"])
        self.assertEqual((res, checked), (0, [("gsk_live_key_0001", None)]))
        self.assertEqual(S.read_env()["PULT_STT_KEY"], "gsk_live_key_0001")
        self.assertIn("console.groq.com", out)
        self.assertIn("Voice input is on", out)

        def bad(key, proxy=None):
            raise S.TgError("Groq doesn't accept this key", 401)
        with mock.patch.object(S, "stt_check", bad):
            res, out = self.run_cli(S.cmd_stt, [], secrets_=["gsk_bad"])
        self.assertEqual(res, 1)
        self.assertIn("doesn't accept", out)
        self.assertEqual(S.read_env()["PULT_STT_KEY"], "gsk_live_key_0001")
        res, out = self.run_cli(S.cmd_stt, [], secrets_=[""])
        self.assertEqual((res, S.read_env()["PULT_STT_KEY"]), (0, "gsk_live_key_0001"))
        self.assertIn("stays", out)
        self.run_cli(S.cmd_stt, ["off"])
        self.assertNotIn("PULT_STT_KEY", S.read_env())
        self.assertEqual(self.svc.started, 0)


class TabTest(Base):
    @unittest.skipIf(WIN, "Windows has pult-tab.exe: test_pult.WindowsTest")
    def test_shell_wrapper(self):
        # pult-tab.sh stands in the way of every VS Code tab: no environment or the off switch — the real claude
        # right away; with the environment — through pult_tab.py, which passes a non-chat run straight on too
        d = self.tmp / "inst"
        d.mkdir()
        shutil.copy(SRC / "pult-tab.sh", d)
        shutil.copy(SRC / "pult_tab.py", d)
        env = dict(os.environ, HOME=str(self.tmp / "home"))
        run = lambda: subprocess.run(["/bin/sh", str(d / "pult-tab.sh"), "/bin/echo", "hi"], capture_output=True,
                                     text=True, env=env, timeout=20)
        self.assertEqual(run().stdout, "hi\n")                                   # no environment
        (d / "venv" / "bin").mkdir(parents=True)
        (d / "venv" / "bin" / "python").write_text('#!/bin/sh\necho via-python "$@"\n')
        (d / "venv" / "bin" / "python").chmod(0o755)
        self.assertEqual(run().stdout, "via-python %s /bin/echo hi\n" % (d / "pult_tab.py"))
        (self.tmp / "home" / ".config" / "pult").mkdir(parents=True)
        (self.tmp / "home" / ".config" / "pult" / "tab-off").touch()
        self.assertEqual(run().stdout, "hi\n")                                   # switched off
        (self.tmp / "home" / ".config" / "pult" / "tab-off").unlink()
        (d / "venv" / "bin" / "python").unlink()
        os.symlink(sys.executable, d / "venv" / "bin" / "python")
        self.assertEqual(run().stdout, "hi\n")                                   # pult_tab.py: not a chat → exec

    def test_tab_setup(self):
        (S.EXT_DIRS[1] / "anthropic.claude-code-2.1.999-linux-x64").mkdir(parents=True)
        with mock.patch.object(sys.stdin, "isatty", lambda: False), \
                mock.patch.object(pult_os, "remote_server", lambda: True):
            _, out = self.run_cli(S.cmd_tab_setup, answers=["~/Documents, ~/work"])
        self.assertIn(pult_os.PALETTE + " → Preferences: Open User Settings (JSON)", out)
        self.assertIn("Open Remote Settings (JSON)", out)                   # Remote-SSH: where the line goes there
        self.assertIn("pult tab allow 2.1.999", out)
        conf = json.loads(S.TAB_CONF.read_text())
        self.assertEqual(conf["folders"], ["~/Documents", "~/work"])
        self.assertEqual(conf["versions"], list(S.TAB_VERIFIED))
        out = io.StringIO()
        with redirect_stdout(out):
            pultctl.cmd_tab(["allow", "2.1.999"])
        self.assertEqual(json.loads(S.TAB_CONF.read_text())["versions"], list(S.TAB_VERIFIED) + ["2.1.999"])


if __name__ == "__main__":
    unittest.main(verbosity=1)
