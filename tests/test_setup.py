#!/usr/bin/env python3
"""Checks for installing, setting up and removing Pult (pult_setup, pultctl) — without Telegram, launchd, systemd
or the real settings: every path points into a temporary folder, Telegram and the service are fakes.

  ~/.local/share/pult/venv/bin/python tests/test_setup.py
"""
import builtins
import getpass
import io
import hashlib
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
import pult_update as U  # noqa: E402

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


BUSY = S.busy_sessions                         # the real one: Base replaces it with a fake


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
        self.busy = []                         # what the daemon says a restart would cut off
        self.patches += [
            mock.patch.object(S, "service", lambda lbl: ("running", "1") if self.svc.loaded else (None, None)),
            mock.patch.object(S, "svc_stop", self.fake_stop),
            mock.patch.object(S, "svc_start", self.fake_start),
            mock.patch.object(S, "busy_sessions", lambda lbl: self.busy),
            mock.patch.dict(os.environ, {"PULT_LANG": "en", "PULT_SOCK": ""}),    # "": in a session Pult started
        ]                                                                         # it is the real daemon's socket
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
        # since 0.18.5 both take every module by a pattern, staged first: none can be left out, none half-copied
        self.assertIn('cp "$SRC"/src/*.py "$SRC"/src/pult-tab.sh "$SRC"/requirements.txt "$STAGE"/', inst)
        self.assertIn('for f in "$STAGE"/*; do mv -f "$f" "$DST"/; done', inst)
        self.assertIn("Copy-Item -Force (Join-Path $Src 'src\\*.py') $stage", ps1)
        for name in sorted(p.name for p in src.glob("*.py")):
            self.assertIn(name, S.HOME_FILES, name)                           # and the uninstaller knows each
        self.assertTrue({".install-new", ".new"} <= set(S.HOME_FILES))
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

    @unittest.skipIf(WIN, "a shell script stands in for Python here")
    def test_environment_check(self):
        # the daemon can't say its environment is broken — it doesn't start — so `pult status` does (0.18.5)
        self.assertEqual(S.venv_problem(), "no python")
        S.PY.parent.mkdir(parents=True, exist_ok=True)
        S.PY.write_text("#!/bin/sh\necho \"ModuleNotFoundError: No module named 'httpx'\" >&2\nexit 1\n")
        S.PY.chmod(0o755)
        self.assertEqual(S.venv_problem(), "ModuleNotFoundError: No module named 'httpx'")
        out = io.StringIO()
        with redirect_stdout(out), mock.patch.object(S, "service", lambda lbl: (None, None)), \
                mock.patch.object(S, "sock_ok", lambda: False):
            pultctl.cmd_status()
        self.assertIn("broken (ModuleNotFoundError: No module named 'httpx') — run ./install.sh", out.getvalue())
        self.assertIn("environment: ModuleNotFoundError", "\n".join(S.report_lines()))
        S.PY.write_text('#!/bin/sh\nexec %s "$@"\n' % shlex.quote(sys.executable))       # whole: the packages are there
        self.assertIsNone(S.venv_problem())

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

    def test_busy_guard(self):
        # a restart or stop cuts off what Pult's own sessions are doing (2026-10-20: an agent ran `bash install.sh`
        # and killed a background subagent in a session from the app): without a terminal — refused; in one — asked,
        # no by default; PULT_FORCE=1 — anyway; nothing running — no question
        self.svc.loaded = True
        self.busy = [{"sid": "s1", "title": "Поиск стратегий", "project": "trader", "turn": False,
                      "bg": ["Probe A: maker"], "n": 1}, {"unknown": 2}]
        tty = lambda v: mock.patch.object(sys.stdin, "isatty", lambda: v)
        ready = mock.patch.object(S, "configured", lambda env=None: True)
        ready.start()
        self.addCleanup(ready.stop)
        for op in ("restart", "stop"):
            with tty(False):
                res, out = self.run_cli(S.cmd_service, op)
            self.assertEqual((res, self.svc.stopped), (1, 0), out)
            self.assertIn("trader · Поиск стратегий — in the background: Probe A: maker", out)
            self.assertIn("2 Claude processes", out)
            self.assertIn("PULT_FORCE=1", out)
            with tty(True):
                res, out = self.run_cli(S.cmd_service, op, answers=[""])
            self.assertEqual((res, self.svc.stopped), (1, 0), out)
        with tty(True):
            res, out = self.run_cli(S.cmd_service, "restart", answers=["y"])
        self.assertEqual((res, self.svc.stopped, self.svc.started), (0, 1, 1), out)
        with tty(False), mock.patch.dict(os.environ, {"PULT_FORCE": "1"}):
            res, out = self.run_cli(S.cmd_service, "restart")
        self.assertEqual((res, self.svc.stopped), (0, 2), out)
        self.assertEqual(self.run_cli(S.cmd_busy)[0], 1)
        self.busy = []
        with tty(True):
            res, out = self.run_cli(S.cmd_service, "restart")
        self.assertEqual((res, self.svc.stopped), (0, 3), out)
        res, out = self.run_cli(S.cmd_busy)
        self.assertEqual(res, 0)
        self.assertIn("cuts nothing off", out)

    def test_busy_sessions(self):
        # the daemon is asked over its socket; one that answers nothing (an older Pult) yet holds Claude processes
        # counts as busy; no service — nothing
        import socket
        a, b = socket.socketpair()
        b.sendall(json.dumps({"busy": [{"sid": "s1", "turn": True, "bg": [], "n": 0}]}).encode() + b"\n")
        with mock.patch.object(S, "busy_sessions", BUSY), mock.patch.object(S, "service", lambda lbl: ("running", "7")), \
                mock.patch.object(S.pult_os, "link_connect", lambda path, timeout=1.0: a):
            self.assertEqual(S.busy_sessions("x"), [{"sid": "s1", "turn": True, "bg": [], "n": 0}])
        self.assertEqual(json.loads(b.recv(100)), {"op": "busy"})
        b.close()
        with mock.patch.object(S, "busy_sessions", BUSY), mock.patch.object(S, "service", lambda lbl: ("running", "7")), \
                mock.patch.object(S.pult_os, "link_connect", mock.Mock(side_effect=OSError)), \
                mock.patch.object(S.pult_os, "children", lambda pid, name=None: [11, 12]):
            self.assertEqual(S.busy_sessions("x"), [{"unknown": 2}])
        with mock.patch.object(S, "busy_sessions", BUSY), mock.patch.object(S, "service", lambda lbl: (None, None)):
            self.assertEqual(S.busy_sessions("x"), [])

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


class UpdateTest(Base):
    """Stage U: what the source folder has that isn't installed, the record install.sh leaves, the installer the app's
    button starts — with the way back when the new version doesn't come up."""

    def setUp(self):
        super().setUp()
        self.patches2 = [mock.patch.object(U, "HOME", S.HOME), mock.patch.object(U, "LOG", self.tmp / "update.log"),
                         mock.patch.object(U, "say", lambda *a: None)]
        for p in self.patches2:
            p.start()
        self.repo = self.tmp / "repo"
        (self.repo / "src").mkdir(parents=True)
        (self.repo / "docs").mkdir()
        self.git("init", "-q")
        self.files({"src/pultd.py": 'VERSION = "1.0"\n', "src/pult_update.py": "# updater 1\n",
                    "src/pult_x.py": "x = 1\n", "src/pult-tab.sh": "#!/bin/sh\n", "requirements.txt": "aiohttp\n",
                    "docs/journal.md": "j\n"})
        self.c1 = self.commit("Pult 1.0")
        for name in ("pultd.py", "pult_update.py", "pult_x.py", "pult-tab.sh"):        # install.sh did this
            shutil.copyfile(self.repo / "src" / name, S.HOME / name)
        shutil.copyfile(self.repo / "requirements.txt", S.HOME / "requirements.txt")
        U.installed_by("terminal", self.repo, True)

    def tearDown(self):
        for p in reversed(self.patches2):
            p.stop()
        super().tearDown()

    def git(self, *a):
        return subprocess.run(["git", "-C", str(self.repo), "-c", "user.email=t@example.com", "-c", "user.name=T", *a],
                              check=True, capture_output=True, text=True).stdout.strip()

    def files(self, d):
        for k, v in d.items():
            (self.repo / k).write_text(v)

    def commit(self, msg):
        self.git("add", "-A")
        self.git("commit", "-qm", msg)
        return self.git("rev-parse", "HEAD")

    def test_check(self):
        m = U.read(U.MANIFEST)
        self.assertEqual((m["src"], m["commit"], m["dirty"], m["version"]), (str(self.repo), self.c1, False, "1.0"))
        self.assertEqual([(h["how"], h["to"], h["ok"]) for h in U.history()], [("terminal", "1.0", True)])
        self.assertFalse(U.check()["ready"])
        self.files({"docs/journal.md": "j2\n"})                  # the journal and the docs don't count
        self.commit("Pult: journal")
        self.assertFalse(U.check()["ready"])
        self.files({"src/pult_x.py": "x = 2\n"})                  # not committed yet: a session halfway through
        self.assertFalse(U.check()["ready"])
        self.files({"src/pultd.py": 'VERSION = "1.1"\n'})
        c3 = self.commit("Pult 1.1: x is two")
        c = U.check()
        self.assertTrue(c["ready"])
        self.assertEqual((c["head"], c["version"], c["news"], c["failed"]), (c3, "1.1", ["Pult 1.1: x is two"], False))
        U.write(U.STATUS, {"state": "fail", "commit": c3})       # this commit didn't come up
        self.assertTrue(U.check()["failed"])
        self.assertEqual(U.check({})["repo"], None)              # no record of the source: no way to tell

    def test_parts_git(self):
        # stage U2: how far a part is behind HEAD — the computer's install by its commit, the relay server's copy by
        # its files (whichever commit has exactly them) — and what CHANGELOG.md says waits for a release
        (self.repo / "relay" / "web").mkdir(parents=True)
        self.files({"relay/relay.py": "r1\n", "relay/web/app.js": "a1\n", "CHANGELOG.md": "# Changelog\n\n## Unreleased\n\n"
                    "- **One.** x\n  more of one\n- **Two.** y\n\n## 1.0.0 — 2026-10-20\n\n- old\n"})
        c2 = self.commit("Pult: relay and app")
        # what a server holds: git's own (LF) text — Git for Windows checks these files out with CRLF
        served = {"relay/web/app.js": U.blob(self.repo / "relay/web/app.js", lf=True)}
        self.files({"relay/web/app.js": "a2\n"})
        c3 = self.commit("Pult: app two")
        self.files({"docs/journal.md": "j3\n"})
        self.commit("Pult: journal")
        self.files({"relay/web/app.js": "a3\n", "src/pult_x.py": "x = 3\n"})
        head = self.commit("Pult: app three, x three")
        b = U.built_from(self.repo, head, served, U.PARTS["web"])
        self.assertEqual((b["commit"], b["n"], b["news"]), (c2, 2, ["Pult: app three, x three", "Pult: app two"]))
        self.assertEqual(b["since"], int(self.git("log", "-1", "--format=%ct", c3)))
        now = {"relay/web/app.js": U.blob(self.repo / "relay/web/app.js", lf=True)}
        self.assertEqual(U.built_from(self.repo, head, now, U.PARTS["web"])["n"], 0)
        self.assertIsNone(U.built_from(self.repo, head, {"relay/web/app.js": "0" * 40}, U.PARTS["web"]))   # uncommitted
        self.assertIsNone(U.built_from(self.repo, head, dict(now, **{"relay/web/extra.js": "0" * 40}), U.PARTS["web"]))
        relay = {"relay/relay.py": U.blob(self.repo / "relay/relay.py", lf=True)}
        self.assertEqual(U.built_from(self.repo, head, relay, U.PARTS["relay"])["commit"], c2)
        # the same pair again costs no git at all — a copy of uncommitted files included (review 2026-10-27, У12)
        with mock.patch.object(U, "ls_tree", mock.Mock(side_effect=AssertionError("git again"))), \
                mock.patch.object(U, "git", mock.Mock(side_effect=AssertionError("git again"))):
            self.assertEqual(U.built_from(self.repo, head, relay, U.PARTS["relay"])["commit"], c2)
            self.assertIsNone(U.built_from(self.repo, head, {"relay/web/app.js": "0" * 40}, U.PARTS["web"]))
        lag = U.behind(self.repo, self.c1, head, U.TREE)                 # the journal and the relay don't count
        self.assertEqual((lag["n"], lag["news"]), (1, ["Pult: app three, x three"]))
        self.assertEqual(U.behind(self.repo, head, head, U.TREE)["n"], 0)
        self.assertIsNone(U.behind(self.repo, "f" * 40, head, U.TREE))  # not in this history
        self.assertIsNone(U.behind(self.repo, None, head, U.TREE))
        self.assertEqual(U.changelog(self.repo, head), {"last": "1.0.0", "date": "2026-10-20", "waiting": 2})
        self.assertIsNone(U.changelog(self.repo, self.c1))
        # only the folder releases are made from has the release row: a clone of the public repository has no build script
        self.assertFalse(U.makes_releases(self.repo, head))
        (self.repo / "publish").mkdir()
        self.files({"publish/build.py": "# build\n"})
        self.assertTrue(U.makes_releases(self.repo, self.commit("Pult: the build script")))

    def test_releases_from_github(self):
        # stage U3: a clone of Pult's GitHub repository looks there for releases, fetches a newer one without touching
        # the folder's files, offers it with its CHANGELOG titles, and names the release it runs for the server
        gh = self.tmp / "gh"                                   # stands for github.com/pulthq/pult
        shutil.copytree(self.repo, gh)
        g = lambda *a: subprocess.run(["git", "-C", str(gh), "-c", "user.email=t@example.com", "-c", "user.name=T", *a],
                                      check=True, capture_output=True, text=True).stdout.strip()
        (gh / "relay" / "web" / "static").mkdir(parents=True)
        for k, v in {"relay/relay.py": "r1\n", "relay/web/index.html": "<title>Pult</title>\n{{importmap}}\n",
                     "relay/web/static/app.js": "// app 1\n", "CHANGELOG.md": "# Changelog\n\n## 1.0.0 — 2026-10-20\n\n- old\n"}.items():
            (gh / k).write_text(v)
        g("add", "-A")
        g("commit", "-qm", "Pult 1.0.0")
        g("branch", "-M", "main")           # GitHub's branch; `git init` names it by config (Actions: master)
        g("tag", "-a", "v1.0.0", "-m", "v1.0.0")
        clone = self.tmp / "clone"
        subprocess.run(["git", "clone", "-q", str(gh), str(clone)], check=True, capture_output=True)
        cg = lambda *a: subprocess.run(["git", "-C", str(clone), "-c", "user.email=t@example.com", "-c", "user.name=T", *a],
                                       check=True, capture_output=True, text=True).stdout.strip()
        cg("remote", "set-url", "origin", "https://github.com/pulthq/pult.git")      # what `git remote -v` says…
        cg("config", "url.%s.insteadOf" % gh, "https://github.com/pulthq/pult.git")  # …and where git really goes
        a = cg("rev-parse", "HEAD")
        U.installed_by("terminal", clone, True)
        self.assertEqual((U.official_remote(clone), U.release_mode(clone, a)), ("origin", "origin"))
        self.assertIsNone(U.release_mode(self.repo, self.c1))              # not a clone of Pult's GitHub repository
        self.assertEqual(U.release_of(clone, a), "v1.0.0")
        self.assertEqual(U.discover(clone, "origin", "1.0"), (True, None))  # nothing newer
        self.assertFalse(U.check()["ready"])
        # a new release on GitHub: a change in src/ and two CHANGELOG entries
        (gh / "src" / "pultd.py").write_text('VERSION = "1.1"\n')
        (gh / "relay" / "web" / "static" / "app.js").write_text("// app 2\n")
        (gh / "CHANGELOG.md").write_text("# Changelog\n\n## 1.1.0 — 2026-10-26\n\n- **Faster replies.** Text\n  more\n"
                                         "- **Fewer messages.** Text\n\n## 1.0.0 — 2026-10-20\n\n- old\n")
        g("add", "-A")
        g("commit", "-qm", "Pult 1.1.0")
        g("tag", "-a", "v1.1.0", "-m", "v1.1.0")
        b = g("rev-parse", "HEAD")
        self.assertEqual(U.remote_releases(clone, "origin")[0], ((1, 1, 0), "v1.1.0", b))
        self.assertEqual(U.discover(clone, "origin", "1.0"), (True, "v1.1.0"))
        self.assertEqual(cg("rev-parse", "HEAD"), a)                       # the folder's files stay as they were
        self.assertEqual((clone / "src" / "pultd.py").read_text(), 'VERSION = "1.0"\n')
        c = U.check()
        self.assertEqual((c["ready"], c["head"], c["tag"], c["version"], c["news"]),
                         (True, b, "v1.1.0", "1.1", ["Faster replies.", "Fewer messages."]))
        self.assertEqual(U.release_of(clone, b), "v1.1.0")
        # what a server on that release must hand the phone: from git, as make_manifest has it from the files
        man = U.manifest_at(clone, b)
        self.assertEqual(man["index"], "<title>Pult</title>\n{{importmap}}\n")
        self.assertEqual(man["files"], {"app.js": hashlib.sha256(b"// app 2\n").hexdigest()})
        # commits of one's own on top of the old release: the folder's own HEAD, as before stage U3
        (clone / "src" / "pult_x.py").write_text("x = 5\n")
        cg("add", "-A")
        cg("commit", "-qm", "mine")
        mine = cg("rev-parse", "HEAD")
        self.assertEqual(U.target(clone, mine), (mine, None))
        self.assertIsNone(U.release_of(clone, mine))
        # GitHub doesn't answer
        cg("config", "url.%s-gone.insteadOf" % gh, "https://github.com/pulthq/pult.git")
        cg("config", "--unset", "url.%s.insteadOf" % gh)
        self.assertEqual(U.discover(clone, "origin", "1.0"), (False, None))

    def test_release_for_server(self):
        # what the computer tells the server's updater to take (stage U3): a clone — the release its commit is; the folder
        # releases are made in (the developer's own, Q83) — the newest on GitHub not newer than the version it runs, with
        # GitHub's commit for it: without it a developer's server on the shared path would never hear of a release
        repo = self.tmp / "dev"
        (repo / "publish").mkdir(parents=True)
        (repo / "publish" / "build.py").write_text("# the build script: releases are made here\n")
        g = lambda *a: subprocess.run(["git", "-C", str(repo), "-c", "user.email=t@example.com", "-c", "user.name=T", *a],
                                      check=True, capture_output=True, text=True).stdout.strip()
        g("init", "-q", "-b", "main")
        g("add", "-A")
        g("commit", "-qm", "dev")
        head = g("rev-parse", "HEAD")
        asked = []

        def gh(r, remote, proxy=None):
            asked.append((remote, proxy))
            return [((1, 1, 0), "v1.1.0", "c" * 40), ((1, 0, 1), "v1.0.1", "b" * 40), ((1, 0, 0), "v1.0.0", "a" * 40)]
        with mock.patch.object(U, "remote_releases", gh):
            self.assertEqual(U.release_for_server(repo, head, "1.0.1", proxy="http://p:1"), ("v1.0.1", "b" * 40))
            self.assertEqual(U.release_for_server(repo, head, "1.0.9"), ("v1.0.1", "b" * 40))     # between releases
            self.assertEqual(U.release_for_server(repo, head, "1.2.0"), ("v1.1.0", "c" * 40))
            self.assertIsNone(U.release_for_server(repo, head, "0.9.0"))                         # older than all
            self.assertIsNone(U.release_for_server(repo, None, "1.0.1"))
        self.assertEqual(asked[0], ("https://github.com/pulthq/pult", "http://p:1"))
        with mock.patch.object(U, "remote_releases", lambda r, remote, proxy=None: None):       # GitHub didn't answer
            self.assertIsNone(U.release_for_server(repo, head, "1.0.1"))
        with mock.patch.object(U, "release_of", lambda r, c: "v1.0.0"):                         # a clone: as before
            self.assertEqual(U.release_for_server(self.repo, self.c1, "9.9.9"), ("v1.0.0", self.c1))

    def test_check_crlf(self):
        # a checkout with core.autocrlf (Git for Windows): the files are CRLF in the folder and installed so, LF in the
        # commit — a commit that didn't touch them is nothing to install (Actions on Windows, 2026-10-24)
        for name in ("pultd.py", "pult_update.py", "pult_x.py"):
            p = S.HOME / name
            p.write_bytes(p.read_bytes().replace(b"\r\n", b"\n").replace(b"\n", b"\r\n"))   # CRLF here and on Windows
        self.files({"docs/journal.md": "j2\n"})
        self.commit("Pult: journal")
        self.assertFalse(U.check()["ready"])
        self.files({"src/pult_x.py": "x = 2\n"})
        self.commit("Pult: x is two")
        self.assertTrue(U.check()["ready"])                      # a real change still counts

    def test_installed_from_uncommitted_files(self):
        # install.sh from a folder with uncommitted changes: they are newer than HEAD, not older
        self.files({"src/pult_x.py": "x = 9\n"})
        shutil.copyfile(self.repo / "src" / "pult_x.py", S.HOME / "pult_x.py")
        U.installed_by("terminal", self.repo, True, "1.0")
        self.assertTrue(U.read(U.MANIFEST)["dirty"])
        self.assertFalse(U.check()["ready"])
        self.commit("Pult: x is nine")                            # committed as installed: nothing to install
        self.assertFalse(U.check()["ready"])

    def test_install_sh_records(self):
        S.write_env(PULT_BOT_TOKEN=GOOD, PULT_ALLOWED_USER_IDS=str(OWNER))
        S.sput(chat=CHAT)
        self.files({"src/pultd.py": 'VERSION = "1.1"\n'})
        c2 = self.commit("Pult 1.1")
        shutil.copyfile(self.repo / "src" / "pultd.py", S.HOME / "pultd.py")
        with mock.patch.object(sys.stdin, "isatty", lambda: False), mock.patch.dict(os.environ, {"PULT_SRC": str(self.repo)}):
            res, _ = self.run_cli(S.cmd_install)
        self.assertEqual(res, 0)
        self.assertEqual(U.read(U.MANIFEST)["commit"], c2)
        h = U.history()[0]
        self.assertEqual((h["from"], h["to"], h["how"], h["ok"]), ("1.0", "1.1", "terminal", True))
        # run by the installer: it keeps its own record
        with mock.patch.object(sys.stdin, "isatty", lambda: False), \
                mock.patch.dict(os.environ, {"PULT_SRC": str(self.repo), "PULT_UPDATER": "app"}):
            self.run_cli(S.cmd_install)
        self.assertEqual(len(U.history()), 2)

    def installer(self, health, busy=()):
        """An installer for HEAD whose service is a fake: health() → (ok, why) per check, in turn."""
        inst = U.Installer(self.git("rev-parse", "HEAD"), "app")
        calls = []
        inst.busy = lambda: list(busy)
        inst.stop = lambda: calls.append("stop")
        inst.install = lambda: calls.append("install") or True
        inst.pip = lambda: calls.append("pip")
        answers = list(health)
        inst.checks = []                                          # how each check was asked: need_relay or not

        def healthy(t0, wait=U.HEALTH_WAIT, need_relay=True):
            inst.checks.append(need_relay)
            return answers.pop(0)
        inst.healthy = healthy
        inst.error_line = lambda t0: "ImportError: cannot import name 'y'"
        inst.alarm = lambda: calls.append("alarm")
        return inst, calls

    def test_installer_puts_the_commit_in(self):
        self.files({"src/pultd.py": 'VERSION = "1.1"\n', "src/pult_new.py": "new = 1\n", "src/pult_update.py": "# updater 2\n"})
        c2 = self.commit("Pult 1.1")
        self.files({"src/pult_x.py": "x = 'half-made'\n"})       # uncommitted: must not go in
        inst, calls = self.installer([(True, None)])
        moved, real = [], U.os.replace

        def replace(a, b):
            moved.append((Path(a).parent.name, Path(b).name))
            return real(a, b)
        with mock.patch.object(U.os, "replace", replace):
            self.assertEqual(inst.run(), 0)
        self.assertEqual(calls, ["stop", "install"])             # requirements.txt unchanged: no pip
        # each file is written beside its place and renamed over it: a hook or a tab starting meanwhile reads the old
        # one or the new one, never half of one (0.18.5)
        placed = {b for a, b in moved if a == U.NEW}
        self.assertTrue({"pultd.py", "pult_new.py", "pult_update.py", "pult-tab.sh"} <= placed, placed)
        self.assertFalse((S.HOME / U.NEW).exists())
        self.assertEqual((S.HOME / "pultd.py").read_text(), 'VERSION = "1.1"\n')
        self.assertEqual((S.HOME / "pult_new.py").read_text(), "new = 1\n")   # a module the old updater never heard of
        self.assertEqual((S.HOME / "pult_x.py").read_text(), "x = 1\n")
        self.assertEqual((S.HOME / "prev" / "pultd.py").read_text(), 'VERSION = "1.0"\n')
        self.assertTrue(os.access(S.HOME / "pult-tab.sh", os.X_OK) or WIN)
        self.assertEqual(U.read(U.MANIFEST)["commit"], c2)
        self.assertEqual(U.read(U.STATUS)["state"], "done")
        h = U.history()[0]
        self.assertEqual((h["from"], h["to"], h["how"], h["ok"]), ("1.0", "1.1", "app", True))
        self.assertFalse(U.check()["ready"])

    def test_installer_goes_back(self):
        self.files({"src/pultd.py": 'VERSION = "1.1"\nimport broken\n', "src/pult_new.py": "new = 1\n",
                    "requirements.txt": "aiohttp\nmore\n"})
        c2 = self.commit("Pult 1.1: broken")
        inst, calls = self.installer([(False, "restarts"), (True, None)])
        self.assertEqual(inst.run(), 1)
        self.assertEqual(calls, ["stop", "pip", "install", "stop", "pip", "install"])
        self.assertEqual(inst.checks, [True, False])              # the version going back: up is enough
        self.assertEqual((S.HOME / "pultd.py").read_text(), 'VERSION = "1.0"\n')
        self.assertEqual((S.HOME / "requirements.txt").read_text(), "aiohttp\n")
        self.assertFalse((S.HOME / "pult_new.py").exists())      # what the new version added goes too
        self.assertFalse((S.HOME / U.NEW).exists())
        st = U.read(U.STATUS)
        self.assertEqual((st["state"], st["why"], st["back"], st["back_ok"], st["reported"], st["commit"], st["to"]),
                         ("fail", "restarts", True, True, False, c2, "1.1"))
        self.assertIn("ImportError", st["detail"])
        self.assertEqual(U.read(U.MANIFEST)["commit"], self.c1)
        h = U.history()[0]
        self.assertEqual((h["ok"], h["why"], h["to"]), (False, "restarts", "1.1"))
        self.assertTrue(U.check()["failed"])                      # not offered again until a new commit
        self.files({"src/pultd.py": 'VERSION = "1.1"\n'})
        self.commit("Pult 1.1: fixed")
        self.assertFalse(U.check()["failed"])

    def test_installer_server_down(self):
        # the app's server answers nobody while the new version starts: the update counts — before 0.18.5 it went back
        # and said neither version came up (the old one couldn't reach the server either)
        self.files({"src/pultd.py": 'VERSION = "1.1"\n'})
        c2 = self.commit("Pult 1.1")
        inst, calls = self.installer([(True, "relay_down")])
        self.assertEqual(inst.run(), 0)
        self.assertEqual(calls, ["stop", "install"])
        self.assertEqual((S.HOME / "pultd.py").read_text(), 'VERSION = "1.1"\n')
        st = U.read(U.STATUS)
        self.assertEqual((st["state"], st["note"], st["commit"]), ("done", "relay_down", c2))
        self.assertEqual((U.history()[0]["ok"], U.history()[0]["why"]), (True, "relay_down"))

    def test_installer_neither_comes_up(self):
        self.files({"src/pultd.py": 'VERSION = "1.1"\nimport broken\n'})
        self.commit("Pult 1.1: broken")
        inst, calls = self.installer([(False, "no_start"), (False, "no_start")])
        self.assertEqual(inst.run(), 1)
        self.assertEqual(calls[-1], "alarm")                     # no daemon left to tell the owner
        self.assertFalse(U.read(U.STATUS)["back_ok"])

    def test_installer_something_started(self):
        self.files({"src/pultd.py": 'VERSION = "1.1"\n'})
        self.commit("Pult 1.1")
        inst, calls = self.installer([], busy=[{"title": "t", "turn": True}])
        self.assertEqual(inst.run(), 3)
        self.assertEqual(calls, [])
        self.assertEqual((S.HOME / "pultd.py").read_text(), 'VERSION = "1.0"\n')
        self.assertEqual(U.read(U.STATUS)["state"], "idle")

    def test_installer_unknown_commit(self):
        inst, calls = self.installer([])
        inst.commit = "0" * 40
        self.assertEqual(inst.run(), 1)
        self.assertEqual(calls, [])                               # nothing was touched
        st = U.read(U.STATUS)
        self.assertEqual((st["state"], st["why"], st["back"]), ("fail", "no_commit", False))

    def test_healthy(self):
        inst = U.Installer("c" * 40, "app")
        pids = []
        inst.S = SimpleNamespace(service=lambda lbl: ("running", pids.pop(0) if len(pids) > 1 else pids[0]))
        t0 = U.time.time()
        with mock.patch.object(U, "STABLE", 0), mock.patch.object(U.time, "sleep", lambda s: None):
            pids[:] = ["7"]
            U.write(U.HEALTH, {"pid": 7, "started": t0, "relay": True})
            self.assertEqual(inst.healthy(t0, wait=1), (True, None))
            U.write(U.HEALTH, {"pid": 7, "started": t0, "relay": None})        # no app server: the daemon alone
            self.assertEqual(inst.healthy(t0, wait=1), (True, None))
            U.write(U.HEALTH, {"pid": 7, "started": t0, "relay": False})
            # up without the app's server: the server is asked itself (0.18.5) — it answers, the new version is at fault
            inst.relay_answers = lambda: True
            self.assertEqual(inst.healthy(t0, wait=0.05), (False, "no_relay"))
            inst.relay_answers = lambda: False                                     # it answers nobody: not the update
            self.assertEqual(inst.healthy(t0, wait=0.05), (True, "relay_down"))
            self.assertEqual(inst.healthy(t0, wait=1, need_relay=False), (True, None))   # going back: up is enough
            U.write(U.HEALTH, {"pid": 7, "started": t0 - 100, "relay": True})  # the old daemon's note
            self.assertEqual(inst.healthy(t0, wait=0.05), (False, "no_start"))
            pids[:] = ["8", "9", "10", "11"]                                       # launchd restarting a crashing one
            self.assertEqual(inst.healthy(t0, wait=1), (False, "restarts"))

    def test_relay_answers(self):
        # the relay's own /healthz decides whether a daemon without it is the new version's fault (0.18.5)
        import http.server
        import threading
        got = []

        class H(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                got.append(self.path)
                body = b'{"ok": true, "mac": false}'
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *a):
                pass
        srv = http.server.HTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        self.addCleanup(srv.shutdown)
        port = srv.server_address[1]
        inst = U.Installer("c" * 40, "app")
        env = {"PULT_RELAY_URL": "ws://127.0.0.1:%d/pult/agent" % port}
        inst.S = SimpleNamespace(read_env=lambda: env)
        self.assertTrue(inst.relay_answers())
        self.assertEqual(got, ["/pult/healthz"])
        srv.shutdown()
        srv.server_close()
        self.assertFalse(inst.relay_answers())                    # nobody there
        env.clear()
        self.assertFalse(inst.relay_answers())                    # no app server at all
        self.assertEqual(U.health_url("wss://h.example/pult/agent"), "https://h.example/pult/healthz")
        self.assertIsNone(U.health_url("https://h.example/pult/"))

    def test_alarm_and_install(self):
        # the installer's last word when neither version came up and no daemon is left to say it (review 2026-10-27,
        # Т7): straight to the owner in Telegram, through the proxy, in the owner's language; Telegram down too — its
        # log says so and nothing breaks; no token — nothing to do
        inst = U.Installer("c" * 40, "app")
        inst.st.update({"to": "9.9", "from": "9.8"})
        sent = []
        env = {"PULT_BOT_TOKEN": "T", "PULT_ALLOWED_USER_IDS": "42,7", "PULT_PROXY": "http://proxy.example:3128"}
        inst.S = SimpleNamespace(read_env=lambda: env, cli_lang=lambda: "ru", I=S.I,
                                 bot_call=lambda token, method, **kw: sent.append((token, method, kw)))
        inst.alarm()
        self.assertEqual([(t, m, kw["chat_id"], kw["proxy"]) for t, m, kw in sent], [("T", "sendMessage", 42, "http://proxy.example:3128")])
        self.assertEqual(sent[0][2]["text"], S.I.T("upd.dead", lang="ru", to="9.9", back="9.8"))
        said = []
        inst.S.bot_call = mock.Mock(side_effect=OSError("down"))
        with mock.patch.object(U, "say", lambda *a: said.append(" ".join(map(str, a)))):
            inst.alarm()
        self.assertTrue(said and said[0].startswith("couldn't tell the owner"), said)
        env.clear()
        inst.S.bot_call = mock.Mock()
        inst.alarm()
        inst.S.bot_call.assert_not_called()
        # its install step: the installed pultctl with PULT_FORCE=1 and who asked; what it says goes to the log
        (S.HOME / "pultctl.py").write_text("import os, sys\nprint('force', os.environ.get('PULT_FORCE'), 'by', "
                                           "os.environ.get('PULT_UPDATER'), sys.argv[1:])\nsys.exit(int(os.environ.get('FAKE_EXIT', '0')))\n")
        inst.S = SimpleNamespace(PY=sys.executable)
        said = []
        with mock.patch.object(U, "say", lambda *a: said.append(" ".join(map(str, a)))):
            self.assertTrue(inst.install())
            with mock.patch.dict(os.environ, {"FAKE_EXIT": "3"}):
                self.assertFalse(inst.install())
        self.assertIn("  pultctl: force 1 by app ['install']", said)

    def test_spawn(self):
        seen = {}

        def popen(argv, **kw):
            seen.update(argv=argv, **kw)
            return SimpleNamespace(wait=lambda timeout=None: 0)
        with mock.patch.object(U.subprocess, "Popen", popen), mock.patch.object(U.pult_os, "KIND", "mac"):
            self.assertTrue(U.spawn("c" * 40, "app", python="/py"))
        self.assertEqual(seen["argv"], ["/py", "-u", str(S.HOME / "pult_update.py"), "run", "c" * 40, "app"])
        self.assertTrue(seen["start_new_session"])                # its own session: launchd's SIGTERM misses it
        with mock.patch.object(U.subprocess, "Popen", popen), mock.patch.object(U.pult_os, "KIND", "linux"), \
                mock.patch.dict(os.environ, {"PULT_HOME": str(S.HOME)}):
            self.assertTrue(U.spawn("c" * 40, "app_wait", python="/py"))
        self.assertEqual(seen["argv"][:4], ["systemd-run", "--user", "--collect", "--quiet"])
        self.assertIn("--setenv=PULT_HOME=%s" % S.HOME, seen["argv"])
        self.assertEqual(seen["argv"][-6:], ["/py", "-u", str(S.HOME / "pult_update.py"), "run", "c" * 40, "app_wait"])
        with mock.patch.object(U.pult_os, "KIND", "windows"):
            self.assertFalse(U.spawn("c" * 40, "app"))            # not yet (Q53)

    def test_running(self):
        self.assertIsNone(U.running())
        U.write(U.STATUS, {"state": "run", "ts": U.time.time(), "pid": os.getpid()})
        self.assertEqual(U.running()["state"], "run")
        U.write(U.STATUS, {"state": "run", "ts": 1, "pid": 99999999})           # long gone: cut short
        self.assertIsNone(U.running())


class ServerOwnTest(unittest.TestCase):
    @unittest.skipIf(WIN, "the updater runs on a Linux server (it imports fcntl)")
    def test_server_own_files_agree(self):
        # the files the server's updater reports and the ones the computer compares (review 2026-10-27, У5): one list
        import importlib.util
        spec = importlib.util.spec_from_file_location("pult_relay_update_own", SRC.parent / "deploy" / "relay" / "update.py")
        M = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(M)
        self.assertEqual(sorted(M.OWN), sorted(U.SRV_OWN))
        for rel in U.SRV_OWN:                              # each one is in the repository, where install.sh takes it
            self.assertTrue((SRC.parent / rel).exists(), rel)

class PrivateDirTest(unittest.TestCase):
    @unittest.skipIf(WIN, "Windows keeps a user's folders by its own rights")
    def test_private_dir(self):
        # Pult's own folders for logs and settings are its user's only — made so, and made so again when an older
        # install left them readable; a folder that isn't Pult's own is never changed (review 2026-10-27, Б7)
        t = Path(tempfile.mkdtemp(prefix="pult-private-"))
        self.addCleanup(shutil.rmtree, t, True)
        fresh = pult_os.private_dir(t / "state" / "pult")
        self.assertEqual(fresh.stat().st_mode & 0o777, 0o700)
        old = t / "config" / "pult"
        old.mkdir(parents=True)
        old.chmod(0o755)
        pult_os.private_dir(old)
        self.assertEqual(old.stat().st_mode & 0o777, 0o700)
        logs = t / "Library" / "Logs"
        logs.mkdir(parents=True)
        logs.chmod(0o755)
        pult_os.private_dir(logs)
        self.assertEqual(logs.stat().st_mode & 0o777, 0o755)

class ConsistencyTest(unittest.TestCase):
    """tools/consistency.py, as CI runs it (review 2026-10-27, Т10): the version against the changelog and a release
    tag; the requirements locked with hashes (Q91), each lock holding what its .in asks for, both at one version."""

    @staticmethod
    def lock(*entries):
        """A lock as tools/lock.py makes it: "name==version [; marker] \\", its hashes after it — or none with "!"."""
        out = "# This file was autogenerated by uv via the following command:\n#    python3 tools/lock.py\n"
        for e in entries:
            bare = e.endswith("!")
            out += e.rstrip("!") + ("\n" if bare else " \\\n    --hash=sha256:%s\n    # via x\n" % ("a" * 64))
        return out

    def tree(self, version, log, pins=None, relay=None, asked="aiohttp==3.14.5\n"):
        d = Path(tempfile.mkdtemp(prefix="pult-consistency-"))
        self.addCleanup(shutil.rmtree, d, True)
        (d / "src").mkdir()
        (d / "relay").mkdir()
        (d / "src" / "pultd.py").write_text('VERSION = "%s"\n' % version)
        (d / "CHANGELOG.md").write_text(log)
        (d / "requirements.txt").write_text(pins or self.lock("aiohttp==3.14.5", "yarl==1.25.1"))
        (d / "relay" / "requirements.txt").write_text(relay or self.lock("aiohttp==3.14.5", "cryptography==50.0.2"))
        (d / "requirements.in").write_text(asked)
        return d

    def test_consistency(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location("pult_consistency", SRC.parent / "tools" / "consistency.py")
        C = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(C)
        between = "# Changelog\n\n## Unreleased\n\n- a thing\n\n## 1.2.3 — 2026-10-01\n\n- old\n"
        self.assertEqual(C.problems(self.tree("1.2.4", between)), [])                    # the next one is being made
        self.assertEqual(len(C.problems(self.tree("1.2.2", between))), 1)                # older than its own changelog
        released = "# Changelog\n\n## Unreleased\n\n## 1.2.4 — 2026-10-27\n\n- a thing\n\n## 1.2.3\n"
        self.assertEqual(C.problems(self.tree("1.2.4", released), "refs/tags/v1.2.4"), [])
        self.assertEqual(len(C.problems(self.tree("1.2.4", between), "refs/tags/v1.2.4")), 2)   # section, Unreleased
        self.assertEqual(len(C.problems(self.tree("1.2.5", released), "refs/tags/v1.2.4")), 1)  # the tag isn't VERSION
        self.assertEqual(C.problems(self.tree("1.2.4", between), "refs/heads/main"), [])
        # the locks: both at one version, every entry with its hashes, what the .in asks for in the lock
        self.assertEqual(len(C.problems(self.tree("1.2.4", between, relay=self.lock("aiohttp==3.14.4")))), 1)
        self.assertEqual(len(C.problems(self.tree("1.2.4", between, pins=self.lock("aiohttp==3.14.5", "yarl==1.25.1!")))), 1)
        self.assertEqual(len(C.problems(self.tree("1.2.4", between, asked="aiohttp==3.15.0\n"))), 1)   # the lock is old
        two = self.lock("aiohttp==3.14.5", "multidict==7.1.0 ; python_full_version < '3.11'",
                        "multidict==7.2.1 ; python_full_version >= '3.11'")                    # one for each Python
        self.assertEqual(C.problems(self.tree("1.2.4", between, pins=two, relay=two)), [])
        one = self.lock("aiohttp==3.14.5", "multidict==7.2.1")
        self.assertEqual(len(C.problems(self.tree("1.2.4", between, pins=two, relay=one))), 1)
        self.assertEqual(C.problems(SRC.parent), [])                                     # this very repository

class TokenStatsTest(unittest.TestCase):
    """tools/token_stats.py on transcripts made up here: a reply over two lines and in a session copy counts once, in
    the oldest file; the sources, the API's price (Haiku's long prompt too), the owner's messages, hours of work and
    the output an agent's transcript under-records (2026-10-28)."""

    def test_token_stats(self):
        import importlib.util
        import time
        spec = importlib.util.spec_from_file_location("pult_token_stats", SRC.parent / "tools" / "token_stats.py")
        T = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(T)
        root = Path(tempfile.mkdtemp(prefix="pult-tokens-"))
        self.addCleanup(shutil.rmtree, root, True)
        t0 = 1_800_000_000

        def at(s):
            return time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime(t0 + s))

        def reply(mid, s, out, model="claude-opus-5-5", stop="end_turn", **u):
            w1, w5 = u.get("w1", 0), u.get("w5", 0)
            usage = {"input_tokens": u.get("inp", 0), "cache_read_input_tokens": u.get("read", 0), "output_tokens": out,
                     "cache_creation_input_tokens": w1 + w5,
                     "cache_creation": {"ephemeral_1h_input_tokens": w1, "ephemeral_5m_input_tokens": w5}}
            text = "ж" * u.get("chars", 2 * out)                 # two characters a token, unless said otherwise
            return {"type": "assistant", "timestamp": at(s), "message": {
                "id": mid, "model": model, "stop_reason": stop, "usage": usage, "content": [{"type": "text", "text": text}]}}

        def user(s, content, **kw):
            return {"type": "user", "timestamp": at(s), "message": {"role": "user", "content": content}, **kw}

        def write(path, age, *lines):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("".join(json.dumps(x, ensure_ascii=False) + "\n" for x in lines), encoding="utf-8")
            os.utime(path, (t0 + age, t0 + age))

        project = root / "my_proj.x"
        self.assertTrue(T.folder(project).endswith("-my-proj-x"))
        own = root / T.folder(project)
        m1 = [reply("m1", 450, 500, stop=None, chars=500, inp=10, w1=1000, read=100_000),   # one reply, two lines
              reply("m1", 450, 500, stop="tool_use", chars=500, inp=10, w1=1000, read=100_000)]
        write(own / "a.jsonl", 100,
              user(0, "do it", promptSource="sdk", turnOrigin="human"), *m1,
              user(900, [{"type": "tool_result", "content": "ok"}]), reply("m2", 1350, 1000, read=200_000),
              user(1800, "<task-notification>done</task-notification>", promptSource="system",
                   turnOrigin="task_notification"),
              user(9000, [{"type": "text", "text": "and this"}]),                    # before promptSource: by its text
              user(9000, "This session is being continued from a previous conversation"))
        write(own / "b.jsonl", 200, *m1, reply("m3", 9300, 100, model="claude-fable-5-1", w5=2000))   # a copy of a
        write(own / "a" / "subagents" / "agent-x.jsonl", 150,
              reply("m4", 600, 3, stop=None, chars=1000, w5=500, read=1000))         # output from the stream's start
        write(root / "-tmp-pult-e2e-abc-proj" / "t.jsonl", 50,
              reply("m5", 300, 100, model="claude-haiku-5-5", read=200_000))        # a test; Haiku over 100 K: five times
        write(root / "-Users-x-other" / "o.jsonl", 60, reply("m6", 300, 100))       # another project
        began = root / "-Users-x-garden" / "h.jsonl"                                 # where the project began
        write(began, 10, user(100, "a remote for Claude?", promptSource="sdk", turnOrigin="sdk"), reply("m7", 200, 50))
        write(began.with_suffix("") / "subagents" / "agent-y.jsonl", 20, reply("m8", 300, 20))

        files = T.transcripts(project, [began], tests=True, root=root)
        s = T.summary(*T.read(files))
        self.assertEqual(s["replies"], 7)                                            # m1 once, m6 not at all
        self.assertEqual(s["files"], {"sessions": 2, "agents": 1, "extra": 2, "tests": 1})
        self.assertEqual(s["tokens"]["read"], 100_000 + 200_000 + 1000 + 200_000)
        self.assertAlmostEqual(s["sources"]["sessions"]["cost"],
                               10 * 4e-6 + 1000 * 8e-6 + 100_000 * 0.2e-6 + 500 * 20e-6       # m1: Opus, 1 h
                               + 200_000 * 0.2e-6 + 1000 * 20e-6                              # m2
                               + 2000 * 12.5e-6 + 100 * 50e-6)                                # m3: Fable, 5 min
        self.assertAlmostEqual(s["sources"]["tests"]["cost"], 5 * (200_000 * 0.01e-6 + 100 * 0.5e-6))
        self.assertEqual(s["messages"], 3)                     # not a tool's result, a notification or a compaction
        self.assertEqual(s["hours"], 0.5)                      # pauses up to 10 min; the one of 2 h is not work
        self.assertEqual(T.hours([(0, 1800), (100, 200), (3600, 5400)]), 1.0)
        self.assertEqual(s["chars_per_token"], 2.0)
        e = s["estimate"]                                      # m4: 1000 characters at 2 a token, 3 written
        self.assertEqual((e["replies"], e["agents"], e["written"], e["estimate"]), (1, 1, 3, 500))
        self.assertAlmostEqual(e["cost"], 497 * 20e-6)
        self.assertEqual(T.summary(*T.read(files, since=t0 + 9000))["replies"], 1)   # m3 alone
        self.assertEqual(T.summary(*T.read(T.transcripts(root / "nothing", root=root)))["replies"], 0)

@unittest.skipIf(WIN, "install.sh is for macOS and Linux")
class InstallShTest(unittest.TestCase):
    """install.sh itself, for real, in a sandbox: a stand-in HOME (the service file and the command land there), Pult's
    folder under it, its Python environment already in place and a pip that only takes notes — no network, no service."""

    def setUp(self):
        self.t = Path(tempfile.mkdtemp(prefix="pult-installsh-"))
        self.addCleanup(shutil.rmtree, self.t, True)
        self.home = self.t / "home"
        self.dst = self.home / ".local" / "share" / "pult"
        (self.dst / "venv" / "bin").mkdir(parents=True)
        py, pip = self.dst / "venv" / "bin" / "python", self.dst / "venv" / "bin" / "pip"
        py.write_text('#!/bin/sh\nexec %s "$@"\n' % shlex.quote(sys.executable))
        pip.write_text('#!/bin/sh\necho "$*" >> %s\n' % shlex.quote(str(self.t / "pip.log")))
        py.chmod(0o755)
        pip.chmod(0o755)

    def install(self, src):
        env = {k: v for k, v in os.environ.items() if not k.startswith("PULT_")}
        env.update(HOME=str(self.home), PULT_LANG="en", PULT_FORCE="1")     # FORCE: never ask a real daemon
        return subprocess.run(["bash", str(src / "install.sh")], env=env, stdin=subprocess.DEVNULL,
                              capture_output=True, text=True, timeout=120)

    def test_install_sh(self):
        root = SRC.parent
        r = self.install(root)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        names = sorted(p.name for p in SRC.glob("*.py")) + ["pult-tab.sh", "requirements.txt"]
        for name in names:                                    # every module, as it is in the folder
            src = root / ("requirements.txt" if name == "requirements.txt" else "src/" + name)
            self.assertEqual((self.dst / name).read_bytes(), src.read_bytes(), name)
        self.assertTrue(os.access(self.dst / "pult_tab.py", os.X_OK) and os.access(self.dst / "pult-tab.sh", os.X_OK))
        self.assertFalse((self.dst / ".install-new").exists())
        self.assertIn("-r %s" % (self.dst / "requirements.txt"), (self.t / "pip.log").read_text())
        self.assertTrue(list(self.home.rglob("*pult*.plist")) + list(self.home.rglob("*.service")))   # in the sandbox
        # a source missing: the install stops before anything installed changed (0.18.5; it copied file by file)
        tree = self.t / "tree"
        (tree / "src").mkdir(parents=True)
        shutil.copy2(root / "install.sh", tree / "install.sh")
        shutil.copy2(root / "requirements.txt", tree / "requirements.txt")
        for p in SRC.glob("*.py"):
            (tree / "src" / p.name).write_text("# a newer one\n")
        (self.dst / "pultd.py").write_text('VERSION = "1.0"  # installed\n')
        r = self.install(tree)                                # no src/pult-tab.sh there
        self.assertNotEqual(r.returncode, 0)
        self.assertEqual((self.dst / "pultd.py").read_text(), 'VERSION = "1.0"  # installed\n')
        self.assertEqual((self.dst / "pult_hook.py").read_bytes(), (SRC / "pult_hook.py").read_bytes())
        self.assertFalse((self.dst / ".install-new").exists())


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

    def test_wrapper_line_check(self):
        # a wrapper line VS Code can't use stops every Claude tab from starting (2026-10-21: a Windows path written
        # with single backslashes): pult status and pult tab setup say which file and give the right line
        (S.HOME / S.TAB_FILE).parent.mkdir(parents=True, exist_ok=True)
        (S.HOME / S.TAB_FILE).write_text("wrapper")
        user = S.EDITOR_DIRS[0] / "settings.json"
        user.parent.mkdir(parents=True)
        good = '{\n  // ours\n  %s\n  "x": 1\n}' % S.wrapper_line()
        self.assertEqual(json.loads(S.wrapper_line()[:-1].join("{}"))["claudeCode.claudeProcessWrapper"],
                         str(S.HOME / S.TAB_FILE))                       # the line we print is valid JSON
        user.write_text(good)
        self.assertEqual(S.wrapper_problems(), [])
        user.write_text(r'{"claudeCode.claudeProcessWrapper": "C:\Users\x\.local\share\pult\%s"}' % S.TAB_FILE)
        self.assertEqual([why for _, why, _ in S.wrapper_problems()], ["broken"])
        prof = S.EDITOR_DIRS[0] / "profiles" / "p1" / "settings.json"
        prof.parent.mkdir(parents=True)
        prof.write_text('{\n  // "claudeCode.claudeProcessWrapper": "/old/%s",\n'
                        '  "claudeCode.claudeProcessWrapper": "/nowhere/%s"\n}' % (S.TAB_FILE, S.TAB_FILE))
        self.assertEqual([(f, why) for f, why, _ in S.wrapper_problems()], [(user, "broken"), (prof, "missing")])
        out = io.StringIO()
        with redirect_stdout(out), mock.patch.object(S, "service", lambda lbl: (None, None)), \
                mock.patch.object(S, "sock_ok", lambda: False):
            pultctl.cmd_status()
        text = out.getvalue()
        self.assertIn("isn't valid JSON", text)
        self.assertIn("/nowhere/%s, and there's no such file" % S.TAB_FILE, text)
        self.assertEqual(text.count(S.wrapper_line()), 2)                  # the right line, for each file
        with mock.patch.object(sys.stdin, "isatty", lambda: False):
            _, out = self.run_cli(S.cmd_tab_setup, answers=["~"])
        self.assertIn("isn't valid JSON", out)
        res, out = self.run_cli(S.cmd_report)
        self.assertIn("(broken line in", out)
        self.assertIn("(missing line in", out)

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

    def test_tab_checked(self):
        # stage A: a check's findings go into tab.json — a version that passed joins "versions"; one that failed, or
        # couldn't be checked, only leaves its record; a blocked one never joins, and an install takes it out; the
        # last ten versions' records are kept
        self.assertFalse(S.tab_checked("2.1.311", {"ok": True}))                  # no tab.json: nothing
        S.TAB_CONF.parent.mkdir(parents=True, exist_ok=True)
        S.TAB_CONF.write_text(json.dumps({"folders": ["~/w"], "versions": ["2.1.310"]}))
        ok = {"ok": True, "race": True, "error": None, "ts": 100, "steps": [{"k": "service", "ok": True}]}
        self.assertTrue(S.tab_checked("2.1.311", ok))
        conf = json.loads(S.TAB_CONF.read_text())
        self.assertEqual((conf["folders"], conf["versions"]), (["~/w"], ["2.1.310", "2.1.311"]))
        self.assertEqual(conf["checked"]["2.1.311"], {"ts": 100, "ok": True, "race": True, "error": None, "step": None})
        bad = {"ok": False, "race": False, "error": None, "ts": 200,
               "steps": [{"k": "own", "ok": True}, {"k": "model", "ok": False}, {"k": "race", "ok": False}]}
        self.assertFalse(S.tab_checked("2.1.312", bad))
        self.assertFalse(S.tab_checked("2.1.313", {"ok": None, "error": "login", "ts": 300, "steps": []}))
        conf = json.loads(S.TAB_CONF.read_text())
        self.assertEqual(conf["versions"], ["2.1.310", "2.1.311"])
        self.assertEqual((conf["checked"]["2.1.312"]["step"], conf["checked"]["2.1.313"]["error"]), ("model", "login"))
        with mock.patch.object(S, "TAB_BLOCKED", ("2.1.311",)):
            self.assertFalse(S.tab_checked("2.1.311", ok))                       # a release blocked it: never allowed
            with mock.patch.object(sys.stdin, "isatty", lambda: False):
                self.run_cli(S.cmd_install)
            self.assertEqual(json.loads(S.TAB_CONF.read_text())["versions"], list(S.TAB_VERIFIED))   # the install took it out
        _, out = self.run_cli(S.cmd_report)                    # `pult report` carries them, for an issue
        self.assertIn("tab checks: 2.1.311 passed · 2.1.312 failed at model, race failed · 2.1.313 couldn't (login)", out)
        for i in range(12):
            S.tab_checked("2.2.%d" % i, {"ok": None, "error": "network", "ts": i, "steps": []})
        checked = json.loads(S.TAB_CONF.read_text())["checked"]
        self.assertEqual((len(checked), min(checked, key=S.vkey)), (10, "2.2.2"))

    def test_tab_check_command(self):
        # `pult tab check`: the newest version VS Code has downloaded, its report into tab.json; --json — one line for
        # the daemon; --dry leaves tab.json alone; a version VS Code doesn't have — said so
        import pult_tabcheck as C
        exe = "claude.exe" if os.name == "nt" else "claude"
        for v in ("2.1.310", "2.1.311"):
            b = S.EXT_DIRS[0] / ("anthropic.claude-code-%s-darwin-arm64" % v) / "resources" / "native-binary"
            b.mkdir(parents=True, exist_ok=True)
            (b / exe).write_text("")
        S.TAB_CONF.parent.mkdir(parents=True, exist_ok=True)
        S.TAB_CONF.write_text(json.dumps({"folders": ["~"], "versions": ["2.1.310"]}))
        asked = []

        def fake(ok, step=None):
            async def run(cli, wrapper, py, say=None):
                asked.append((C.version_of(cli), str(wrapper)))
                say and say("own", True)
                steps = [{"k": "own", "ok": True, "s": 1, "note": ""}] + ([{"k": step, "ok": False, "s": 1, "note": "x"}] if step else [])
                return {"version": C.version_of(cli), "ok": ok, "race": True, "error": None, "steps": steps, "ts": 5}
            return run
        with mock.patch.object(C, "run", fake(True)):
            res, out = self.run_cli(pultctl.cmd_tab, ["check", "--json"])
        self.assertEqual((res, json.loads(out.strip().splitlines()[-1])["ok"]), (0, True))
        self.assertEqual(asked[-1], ("2.1.311", str(S.HOME / "pult_tab.py")))       # the newest, through the installed wrapper
        self.assertIn("2.1.311", json.loads(S.TAB_CONF.read_text())["versions"])
        S.TAB_CONF.write_text(json.dumps({"folders": ["~"], "versions": ["2.1.310"]}))
        with mock.patch.object(C, "run", fake(False, "model")):
            res, out = self.run_cli(pultctl.cmd_tab, ["check", "2.1.311", "--dry"])
        self.assertEqual(res, 1)
        self.assertIn(S.T("cli.check.fail", v="2.1.311", step=S.T("tab.step.model")), out)
        self.assertEqual(json.loads(S.TAB_CONF.read_text()), {"folders": ["~"], "versions": ["2.1.310"]})   # --dry
        res, out = self.run_cli(pultctl.cmd_tab, ["check", "2.1.999"])
        self.assertEqual(res, 2)
        self.assertIn(S.T("cli.check.none", v="2.1.999"), out)

    def test_install_brings_verified_versions(self):
        # an install (install.sh, the app's "Install") adds the versions its release is checked on to tab.json and
        # keeps the folders and the versions allowed by hand; before, only `pult tab setup` did (2026-10-26)
        def install():
            with mock.patch.object(sys.stdin, "isatty", lambda: False):
                return self.run_cli(S.cmd_install)[1]
        install()
        self.assertFalse(S.TAB_CONF.exists())                    # writing into tabs isn't set up: nothing is written
        S.TAB_CONF.parent.mkdir(parents=True, exist_ok=True)
        S.TAB_CONF.write_text(json.dumps({"folders": ["~/work"], "versions": ["2.1.200", S.TAB_VERIFIED[0]]}))
        out = install()
        conf = json.loads(S.TAB_CONF.read_text())
        self.assertEqual(conf["folders"], ["~/work"])
        self.assertEqual(conf["versions"], sorted({"2.1.200", *S.TAB_VERIFIED}, key=S.vkey))
        added = S.T("cli.tab.added", v=", ".join(S.TAB_VERIFIED[1:]))
        self.assertIn(added, out)
        self.assertNotIn(added, install())                       # nothing new — nothing said
        S.TAB_CONF.write_text("{broken")
        install()
        self.assertEqual(S.TAB_CONF.read_text(), "{broken")      # one Pult can't read stays as it is


if __name__ == "__main__":
    unittest.main(verbosity=1)
