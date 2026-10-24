#!/usr/bin/env python3
"""Pult: installing, setting up and removing Pult on this computer — what is behind `pult install`, `pult setup`,
`pult start|stop|restart`, `pult report`, `pult uninstall`, `pult tab setup` and `pult app`.

Standard library only, like pultctl: it has to work before Pult's environment exists and when it is broken.
Paths follow the daemon (PULT_HOME, PULT_ENV, PULT_SOCK, PULT_LOG). The service (launchd on macOS, systemd --user
on Linux, a Task Scheduler task on Windows — pult_os) is named PULT_LABEL from the settings, else the name of a
service that already runs this copy of Pult (an existing install keeps its name), else the default one.
"""
import getpass
import http.client
import json
import os
import re
import secrets
import shlex
import shutil
import sqlite3
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

try:
    import pwd
except ImportError:                            # Windows
    pwd = None

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import pult_hook  # noqa: E402
import pult_i18n as I  # noqa: E402
import pult_update as U  # noqa: E402
import pult_os  # noqa: E402
from pult_i18n import T  # noqa: E402

HOME = Path(os.environ.get("PULT_HOME") or "~/.local/share/pult").expanduser()
ENV_FILE = Path(os.environ.get("PULT_ENV") or "~/.config/pult/env").expanduser()
SOCK = os.environ.get("PULT_SOCK") or str(HOME / "pult.sock")
LOG = Path(os.environ.get("PULT_LOG") or pult_os.LOG_DIR / "pult.log").expanduser()
WIN = pult_os.KIND == "windows"
PY = HOME / "venv" / ("Scripts/python.exe" if WIN else "bin/python")    # Pult's environment; the hook and the tab
PYW = HOME / "venv" / "Scripts" / "pythonw.exe"                         # wrapper run on it too (Windows: see below)
TAB_FILE = "pult-tab.exe" if WIN else "pult-tab.sh"     # what claudeCode.claudeProcessWrapper points at
SVC = pult_os.service_manager()                 # launchd / systemd --user
BIN = Path("~/.local/bin").expanduser()
TAB_LOG = pult_os.LOG_DIR / "pult-tab.log"
SETTINGS = Path("~/.claude/settings.json").expanduser()
TAB_CONF = Path("~/.config/pult/tab.json").expanduser()
TAB_OFF = Path("~/.config/pult/tab-off").expanduser()
EDITOR_DIRS = pult_os.editor_dirs()             # VS Code and its forks (and their remote side): where the wrapper may be set
EXT_DIRS = pult_os.extension_dirs()
DEFAULT_LABEL = SVC.DEFAULT
MARK = "pult_hook.py"                          # Pult's hooks are recognised by this in the command
LAUNCHER_MARK = "# Pult command line"
TAB_VERIFIED = ("2.1.301",)    # Claude Code versions the tab wrapper was checked on (tests/probe_tab.py, probe_race.py)
SERVICE_PATH = pult_os.service_path(BIN)
WAIT_LIMIT = 15 * 60           # s; how long the setup waits for /start and /bind
TOKEN_RE = re.compile(r"^\d{5,}:[A-Za-z0-9_-]{30,}$")
STT_MODELS = "https://api.groq.com/openai/v1/models"    # the cheapest call that tells whether a Groq key works


def say(*a):
    print(*a, flush=True)


def tilde(p):
    p, home = str(p), str(Path.home())
    return "~" + p[len(home):] if p == home or p.startswith(home + os.sep) else p


def version():
    for src in (HOME / "pultd.py", HERE / "pultd.py"):
        try:
            m = re.search(r'^VERSION = "([^"]+)"', src.read_text(encoding="utf-8"), re.M)
        except OSError:
            continue
        if m:
            return m.group(1)
    return "?"


# ---------- answers in the terminal ----------

def ask(prompt, default=""):
    try:
        v = input(prompt).strip()
    except EOFError:
        raise KeyboardInterrupt from None      # no one to answer (closed input): stop, don't guess
    return v or default


def yes(prompt, default=True):
    v = ask("%s %s " % (prompt, T("cli.yn.y" if default else "cli.yn.n"))).lower()
    return default if not v else v[0] in "yд"


def secret(prompt):
    try:
        return getpass.getpass(prompt).strip()
    except EOFError:
        raise KeyboardInterrupt from None


# ---------- settings and state ----------

def read_env():
    env = {}
    try:
        for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip().strip("'\"")
    except FileNotFoundError:
        pass
    return env


def write_env(**kv):
    """Updates the settings file in place (mode 600): given keys are set, None removes one; other lines stay."""
    path = ENV_FILE.resolve()                  # a symlinked file stays a symlink
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    out, seen = [], set()
    for line in lines:
        k = line.split("=", 1)[0].strip() if "=" in line and not line.lstrip().startswith("#") else None
        if k in kv:
            seen.add(k)
            if kv[k] is not None:
                out.append("%s=%s" % (k, kv[k]))
        else:
            out.append(line)
    out += ["%s=%s" % (k, v) for k, v in kv.items() if k not in seen and v is not None]
    if not path.parent.exists():
        path.parent.mkdir(parents=True, mode=0o700)   # only a folder it creates gets 700, never someone else's
    tmp = path.with_name(path.name + ".tmp")
    tmp.unlink(missing_ok=True)
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write("\n".join(out) + "\n")
    os.replace(tmp, path)


def sget(k, default=None):
    """A value from the daemon's state (state.db, table kv)."""
    db = HOME / "state.db"
    if not db.exists():
        return default
    try:
        c = sqlite3.connect(str(db))
        try:
            r = c.execute("SELECT v FROM kv WHERE k=?", (k,)).fetchone()
        finally:
            c.close()
    except sqlite3.Error:
        return default
    return json.loads(r[0]) if r else default


def sput(**kv):
    HOME.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(str(HOME / "state.db"), isolation_level=None)
    try:
        c.execute("CREATE TABLE IF NOT EXISTS kv(k TEXT PRIMARY KEY, v TEXT)")
        for k, v in kv.items():
            c.execute("INSERT OR REPLACE INTO kv VALUES(?,?)", (k, json.dumps(v)))
    finally:
        c.close()


def system_lang():
    return I.lang_of(pult_os.system_lang())


def cli_lang():
    """Pult's language (chosen in the settings, else the owner's Telegram), else the system's."""
    if os.environ.get("PULT_LANG") in I.LANGS:
        return os.environ["PULT_LANG"]
    return (sget("prefs") or {}).get("lang") or sget("lang_tg") or system_lang()


def configured(env=None):
    env = read_env() if env is None else env
    return bool(env.get("PULT_BOT_TOKEN") and env.get("PULT_ALLOWED_USER_IDS") and sget("chat"))


# ---------- hooks in ~/.claude/settings.json ----------

def base_pythonw():
    """Windows: the pythonw of the Python Pult's environment is made from. The hook and the tab wrapper run on it,
    not on the environment's: they need only the standard library, survive the environment being rebuilt, and the
    environment's pythonw is a redirector that would stand between claude and them."""
    base = Path(getattr(sys, "_base_executable", "") or sys.executable)
    for p in (base.with_name("pythonw.exe"), Path(sys.executable).with_name("pythonw.exe"), PYW):
        if p.exists():
            return p
    return PYW


def hook_entry():
    """(command, args) for settings.json. macOS and Linux: a shell command, args None. Windows: exec form — base
    pythonw with the hook file as its argument (no shell there to guard with; uninstall takes the hooks out first)."""
    if not WIN:
        return hook_command(), None
    default = os.path.expanduser("~/.local/share/pult/pult.sock")
    return str(base_pythonw()), [str(HOME / "pult_hook.py")] + ([] if SOCK == default else ["--sock=" + SOCK])


def hook_command():
    """The command in settings.json. Claude Code runs it through the shell; without Pult's Python or the hook
    file (the environment is being rebuilt, Pult was removed while sessions were open) it exits 0 quietly."""
    py, hook = shlex.quote(str(PY)), shlex.quote(str(HOME / "pult_hook.py"))
    default = os.path.expanduser("~/.local/share/pult/pult.sock")      # what the hook uses without PULT_SOCK
    env = "" if SOCK == default else "PULT_SOCK=%s " % shlex.quote(SOCK)
    return "[ -x %s ] && [ -r %s ] && %sexec %s %s; exit 0" % (py, hook, env, py, hook)


def load_settings():
    return json.loads(SETTINGS.read_text(encoding="utf-8")) if SETTINGS.exists() else {}


def save_settings(d):
    if SETTINGS.exists():
        bak = SETTINGS.with_name("settings.json.bak-pult-%s" % time.strftime("%Y%m%d-%H%M%S"))
        shutil.copy2(SETTINGS, bak)
        say(T("cli.backup", path=tilde(bak)))
    path = SETTINGS.resolve()                  # settings.json kept as a symlink (dotfiles) stays one
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(d, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def ours(h):
    """A hook Pult installed: the hook file is in its command (shell form) or among its arguments (exec form)."""
    return MARK in str(h.get("command", "")) or any(MARK in str(a) for a in h.get("args") or [])


def strip_ours(hooks):
    """Removes everything Pult installed from the hooks block; leaves other hooks alone."""
    out = {}
    for ev, groups in (hooks or {}).items():
        kept = []
        for g in groups:
            hs = [h for h in g.get("hooks", []) if not ours(h)]
            if hs:
                kept.append(dict(g, hooks=hs))
        if kept:
            out[ev] = kept
    return out


def hooks_unreadable():
    """settings.json mentions Pult's hook but isn't JSON Pult can read (comments, a broken edit)."""
    try:
        load_settings()
        return False
    except (OSError, ValueError):
        try:
            return MARK in SETTINGS.read_text(encoding="utf-8")
        except OSError:
            return False


def hooks_installed(d=None):
    try:
        d = load_settings() if d is None else d
    except (OSError, ValueError):
        return []
    return sorted(ev for ev, groups in (d.get("hooks") or {}).items()
                  for g in groups for h in g.get("hooks", []) if ours(h))


def hooks_set(on):
    try:
        d = load_settings()
    except ValueError:
        sys.exit(T("cli.hooks.unreadable", path=tilde(SETTINGS)))
    hooks = strip_ours(d.get("hooks"))
    if on:
        if not (HOME / "pult_hook.py").exists():
            sys.exit(T("cli.hooks.no_hook", path=tilde(HOME / "pult_hook.py")))
        for ev, groups in pult_hook.hooks_config(*hook_entry()).items():
            hooks.setdefault(ev, []).extend(groups)
    if hooks:
        d["hooks"] = hooks
    else:
        d.pop("hooks", None)
    save_settings(d)
    say(T("cli.hooks.state", events=", ".join(hooks_installed(d)) or T("cli.hooks.off")))
    say(T("cli.hooks.reload", palette=pult_os.PALETTE))


# ---------- the service (launchd / systemd --user, pult_os) ----------

def label():
    return read_env().get("PULT_LABEL") or SVC.find(HOME / "pultd.py") or DEFAULT_LABEL


def service_file(lbl):
    return SVC.path(lbl)


def write_service(lbl):
    env = {"PATH": SERVICE_PATH, "PULT_LABEL": lbl}
    for k in ("PULT_HOME", "PULT_ENV", "PULT_SOCK", "PULT_LOG"):
        if os.environ.get(k):
            env[k] = os.environ[k]                 # a separate (test) install keeps its own paths
    if pwd and str(Path.home()) != pwd.getpwuid(os.getuid()).pw_dir:
        env["HOME"] = str(Path.home())             # a trial install in a stand-in HOME: the service would get the real one
    LOG.parent.mkdir(parents=True, exist_ok=True)
    # Windows: pythonw (no console window); the daemon then writes its own log, and UTF-8 is said explicitly
    argv = [PYW, "-X", "utf8", HOME / "pultd.py"] if WIN else [PY, "-u", HOME / "pultd.py"]
    return SVC.write(lbl, argv, env, LOG, HOME)


def service(lbl):
    """(state, pid) of the service; (None, None) — not running (not loaded, stopped)."""
    return SVC.state(lbl)


def sock_ok(path=None):
    """Whether the daemon answers on its link (unix socket, or 127.0.0.1 and the key on Windows)."""
    try:
        pult_os.link_connect(path or SOCK).close()
        return True
    except (OSError, ValueError):
        return False


def svc_stop(lbl):
    SVC.stop(lbl)
    for _ in range(30):                        # launchd's bootout is asynchronous: wait until the old one is gone
        if service(lbl)[0] is None:
            return True
        time.sleep(0.5)
    return False


def svc_start(lbl):
    if not service_file(lbl).exists():
        write_service(lbl)
    for _ in range(3):
        if SVC.start(lbl):
            break
        time.sleep(2)
    end = time.time() + 20
    while time.time() < end:
        if sock_ok():
            return True
        time.sleep(0.5)
    return False


def busy_sessions(lbl):
    """What stopping the service would cut off, as the daemon tells it: Pult's own sessions (started from Telegram or
    the app) with a turn running or background tasks — [{"title", "project", "turn", "bg", "n"}]. A daemon that
    can't tell (an older Pult) yet holds Claude processes: [{"unknown": their count}]. Nothing — []."""
    pid = service(lbl)[1]
    if not pid:
        return []
    try:
        s = pult_os.link_connect(SOCK, timeout=5)
        try:
            s.sendall(b'{"op": "busy"}\n')         # no "wait": a daemon without this op answers nothing
            buf = b""
            while not buf.endswith(b"\n"):
                chunk = s.recv(65536)
                if not chunk:
                    break
                buf += chunk
        finally:
            s.close()
        return list(json.loads(buf)["busy"])
    except (OSError, ValueError, KeyError, TypeError):
        pass
    n = len(pult_os.children(pid, "claude"))
    return [{"unknown": n}] if n else []


def busy_text(busy):
    """The busy sessions for a human, one per line."""
    lines = []
    for b in busy:
        if "unknown" in b:
            lines.append("  • " + T("cli.busy.unknown", n=b["unknown"]))
            continue
        what = ([T("cli.busy.turn")] if b.get("turn") else []) + \
            ([T("cli.busy.bg", tasks=", ".join(b.get("bg") or []) or b.get("n"))] if b.get("n") else [])
        name = b.get("project") or ""
        if b.get("title") and b["title"] != name:
            name = "%s · %s" % (name, b["title"]) if name else b["title"]
        lines.append("  • %s — %s" % (name, "; ".join(what)))
    return "\n".join(lines)


def forced():
    return os.environ.get("PULT_FORCE") == "1"


def may_stop(lbl, interactive=False):
    """Whether the service may stop now: nothing of Pult's own runs, or the owner agreed in the terminal, or
    PULT_FORCE=1. Without a terminal (a script, an agent) the service isn't stopped while something runs."""
    busy = [] if forced() else busy_sessions(lbl)
    if not busy:
        return True
    say(T("cli.busy.list", list=busy_text(busy)))
    if interactive:
        if yes(T("cli.svc.busy"), False):
            return True
        say(T("cli.svc.kept"))
        return False
    say(T("cli.svc.wait"))
    return False


def cmd_busy():
    """`pult busy`: what a restart would cut off; exit code 1 while something runs."""
    busy = busy_sessions(label())
    say(T("cli.busy.list", list=busy_text(busy)) if busy else T("cli.busy.none"))
    return 1 if busy else 0


def restart(lbl, interactive=False):
    if not may_stop(lbl, interactive):
        return False
    svc_stop(lbl)
    why = SVC.problem()
    if why:
        say(T("cli.svc.no_manager", why=why, cmd="%s -u %s" % (tilde(PY), tilde(HOME / "pultd.py"))))
        return False
    ok = svc_start(lbl)
    say(T("cli.svc.started", label=lbl) if ok else T("cli.svc.not_started", log=tilde(LOG)))
    return ok


def linger_hint():
    """Linux over SSH or on a server: user services stop at logout unless linger is on — say how to turn it on."""
    if SVC.linger() is False and pult_os.desktop() == "none":
        say(T("cli.svc.linger", user=getpass.getuser()))


def cmd_service(op):
    lbl = label()
    if op == "stop":
        if not may_stop(lbl, interactive=sys.stdin.isatty()):
            return 1
        svc_stop(lbl)
        say(T("cli.svc.stopped"))
        return 0
    if not configured():
        say(T("cli.svc.not_ready"))
        return 1
    if op == "start" and service(lbl)[0]:
        say(T("cli.svc.started", label=lbl))
        return 0
    return 0 if restart(lbl, interactive=sys.stdin.isatty()) else 1


# ---------- install ----------

def write_launcher():
    """~/.local/bin/pult → pultctl on Pult's Python (Windows: pult.cmd). Someone else's `pult` there is left alone."""
    if os.environ.get("PULT_HOME"):
        return None                            # a separate (test) install doesn't take over the command
    p = BIN / ("pult.cmd" if WIN else "pult")
    if p.exists() or p.is_symlink():
        try:
            cur = p.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            cur = ""
        if LAUNCHER_MARK not in cur:
            say(T("cli.install.taken", path=tilde(p), ctl="%s %s" % (tilde(PY), tilde(HOME / "pultctl.py"))))
            return None
    BIN.mkdir(parents=True, exist_ok=True)
    if WIN:
        # cmd reads a .cmd file in the console's code page: ASCII only, and the paths come from %USERPROFILE%
        rel = lambda q: "%USERPROFILE%" + str(q)[len(str(Path.home())):] if tilde(q) != str(q) else str(q)
        # bytes, not text: in text mode Windows would turn each \r\n into \r\r\n. cmd reads a batch file as it goes,
        # and `pult uninstall` deletes this one while it runs ("The batch file cannot be found"): "(goto) 2>nul" ends
        # the batch first, and the rest of the line, already read, runs as if typed — with the program's exit code
        p.write_bytes(('@echo off\r\nrem %s — installed by install.ps1, removed by `pult uninstall`\r\n'
                       '(goto) 2>nul & "%s" -X utf8 "%s" %%*\r\n' % (LAUNCHER_MARK, rel(PY), rel(HOME / "pultctl.py")))
                      .encode("ascii", errors="replace"))
        return p
    p.write_text('#!/bin/sh\n%s — installed by install.sh, removed by `pult uninstall`\nexec %s %s "$@"\n'
                 % (LAUNCHER_MARK, shlex.quote(str(PY)), shlex.quote(str(HOME / "pultctl.py"))), encoding="utf-8")
    p.chmod(0o755)
    return p


# ---------- Windows programs: the tab wrapper ----------

def launcher_bytes(gui=True):
    """distlib's simple launcher for Windows — the one pip makes console scripts with (pip/_vendor/distlib): x64 or
    ARM64, GUI (w) or console (t)."""
    import importlib.util
    import platform
    spec = importlib.util.find_spec("pip")
    if not spec or not spec.submodule_search_locations:
        raise OSError("pip is not in Pult's environment")
    arm = platform.machine().lower() in ("arm64", "aarch64")
    name = "%s64%s.exe" % ("w" if gui else "t", "-arm" if arm else "")
    return (Path(list(spec.submodule_search_locations)[0]) / "_vendor" / "distlib" / name).read_bytes()


def make_exe(path, python, files, gui=True):
    """A Windows program made the way pip makes console scripts: the launcher, a #! line with the Python to run, and
    a zip with __main__.py — Python runs the .exe itself as a zip application (the launcher passes it its own path).
    A running program can't be overwritten on Windows but can be renamed: the old one steps aside and goes next time."""
    import io
    import zipfile
    py = str(python)
    shebang = ("#!" + ('"%s"' % py if " " in py else py) + "\n").encode("utf-8")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in files.items():
            z.writestr(name, data)
    data = launcher_bytes(gui) + shebang + buf.getvalue()
    path = Path(path)
    for old in path.parent.glob(path.stem + ".old-*" + path.suffix):
        try:
            old.unlink()
        except OSError:
            pass                               # still running in an open tab
    new = path.with_name(path.name + ".new")
    new.write_bytes(data)
    try:
        os.replace(new, path)
    except PermissionError:                    # a tab runs it right now
        path.rename(path.with_name("%s.old-%d%s" % (path.stem, time.time() * 1000, path.suffix)))
        os.replace(new, path)
    return path


TAB_MAIN = "import pult_tab\npult_tab.entry()\n"
TAB_STUB_MAIN = ("# Pult was removed: claude runs directly, so VS Code tabs keep working. Remove the\n"
                 "# claudeCode.claudeProcessWrapper line from the VS Code settings, then delete this folder.\n"
                 "import sys\nimport pult_tab\npult_tab.direct(sys.argv[1:])\n")


def make_tab_exe(stub=False):
    """Windows: pult-tab.exe — the GUI launcher with base pythonw and pult_tab.py inside (the extension starts the
    wrapper with pipes and windowsHide: a console program would get a console window for every tab)."""
    return make_exe(HOME / "pult-tab.exe", base_pythonw(),
                    {"pult_tab.py": (HOME / "pult_tab.py").read_bytes(), "__main__.py": TAB_STUB_MAIN if stub else TAB_MAIN})


def cmd_install():
    """The second half of install.sh, after the files and the environment are in place. install.sh says where the
    files came from (PULT_SRC): written down for the app's "Install" button, with the install in the history. The
    installer the button starts (PULT_UPDATER) keeps its own record."""
    lbl = label()
    src = None if os.environ.get("PULT_UPDATER") else os.environ.get("PULT_SRC")
    before = (U.read(U.MANIFEST, {}) or {}).get("version")
    write_service(lbl)
    launcher = write_launcher()
    if WIN and (HOME / "pult_tab.py").exists():
        make_tab_exe()
    say(T("cli.install.done", version=version(), home=tilde(HOME)))
    if launcher and not WIN and str(BIN) not in os.environ.get("PATH", "").split(":"):
        say(T("cli.install.path", path=tilde(launcher), rc=pult_os.shell_rc()))     # install.ps1 adds it on Windows
    if not configured():
        if src:
            U.installed_by("terminal", src, None, before)
        if sys.stdin.isatty():
            return cmd_setup()
        say(T("cli.install.next"))
        return 0
    ok = restart(lbl, interactive=sys.stdin.isatty())
    if src:
        U.installed_by("terminal", src, ok, before)
    if ok:
        linger_hint()
    if ok and sys.stdin.isatty() and not hooks_installed():
        step_hooks()
    return 0 if ok else 1


# ---------- Telegram (for the setup and the status) ----------

class TgError(Exception):
    def __init__(self, desc, code=None):
        super().__init__(desc)
        self.code = code


def bot_call(token, method, proxy=None, http_timeout=20, **params):
    """Bot API. proxy: None — the system's (environment variables), "" — direct, otherwise this proxy.
    Errors never carry the URL: it contains the token."""
    req = urllib.request.Request("https://api.telegram.org/bot%s/%s" % (token, method),
                                 data=json.dumps({k: v for k, v in params.items() if v is not None}).encode(),
                                 headers={"Content-Type": "application/json"})
    handlers = [] if proxy is None else [urllib.request.ProxyHandler({"https": proxy} if proxy else {})]
    try:
        with urllib.request.build_opener(*handlers).open(req, timeout=http_timeout) as r:
            j = json.load(r)
    except urllib.error.HTTPError as e:
        try:
            j = json.load(e)
        except ValueError:
            raise TgError("HTTP %s" % e.code, e.code) from None
    except urllib.error.URLError as e:
        raise OSError(str(e.reason)) from None
    except (http.client.HTTPException, ValueError) as e:
        # InvalidURL quotes the path — with the token in it; a non-JSON answer (a captive portal) is a ValueError
        raise TgError("bad request or answer (%s)" % type(e).__name__) from None
    if not j.get("ok"):
        raise TgError(j.get("description") or "error", j.get("error_code"))
    return j["result"]


class Bot:
    def __init__(self, token, proxy=None):
        self.token, self.proxy = token, proxy

    def __call__(self, method, http_timeout=20, **params):
        return bot_call(self.token, method, self.proxy, http_timeout, **params)


class Updates:
    """getUpdates for the setup: waits for one kind of message and remembers how far it has read."""

    def __init__(self, bot):
        self.bot, self.offset = bot, None

    def skip_old(self):
        ups = self.bot("getUpdates", offset=-1, timeout=0)
        if ups:
            self.offset = ups[-1]["update_id"] + 1

    def wait(self, match, limit=WAIT_LIMIT):
        end = time.time() + limit
        while time.time() < end:
            try:
                ups = self.bot("getUpdates", http_timeout=40, offset=self.offset, timeout=25,
                               allowed_updates=["message"])
            except TgError as e:
                if e.code == 409:
                    say(T("cli.tg.conflict"))
                elif not (e.code == 429 or (e.code or 0) >= 500):
                    raise
                time.sleep(5)
                continue
            except OSError:
                time.sleep(3)
                continue
            for u in ups:
                self.offset = u["update_id"] + 1
                r = match(u["message"]) if u.get("message") else None
                if r:
                    return r
        return None

    def confirm(self):
        """Marks what the setup read as handled — the daemon starts after it."""
        if self.offset:
            try:
                self.bot("getUpdates", offset=self.offset, timeout=0)
            except (TgError, OSError):
                pass
            sput(offset=self.offset)


def name_of(user):
    n = " ".join(x for x in (user.get("first_name"), user.get("last_name")) if x) or str(user.get("id"))
    return n + (" (@%s)" % user["username"] if user.get("username") else "")


# ---------- setup ----------

def step(n, key):
    say("\n%d/4 · %s" % (n, T(key)))


def step_bot(env):
    proxy = env.get("PULT_PROXY") or None
    old = env.get("PULT_BOT_TOKEN")
    if old:
        try:
            me = bot_call(old, "getMe", proxy)
            if yes(T("cli.bot.keep", bot=me["username"])):
                return Bot(old, proxy), me
        except TgError:
            pass
    say(T("cli.bot.how"))
    while True:
        token = secret(T("cli.bot.ask"))
        if not TOKEN_RE.match(token):
            say(T("cli.bot.shape"))
            continue
        try:
            me = bot_call(token, "getMe", proxy)
        except TgError as e:
            say(T("cli.bot.bad", why=e))
            continue
        except OSError as e:
            say(T("cli.bot.net", why=e, env=tilde(ENV_FILE)))
            continue
        hook = bot_call(token, "getWebhookInfo", proxy)
        if hook.get("url"):
            if not yes(T("cli.bot.webhook", host=urllib.parse.urlsplit(hook["url"]).netloc), False):
                continue
            bot_call(token, "deleteWebhook", proxy)
        break
    say(T("cli.bot.ok", bot=me["username"]))
    if token != old:
        write_env(PULT_BOT_TOKEN=token)
        sput(offset=0, panel=None)             # update numbers and messages belong to the old bot
    return Bot(token, proxy), me


def step_you(bot, me, env, ups):
    ids = env.get("PULT_ALLOWED_USER_IDS")
    if ids and yes(T("cli.you.keep", id=ids)):
        return int(re.split(r"[,\s]+", ids.strip())[0])
    code = secrets.token_hex(3)
    say(T("cli.you.how", link="https://t.me/%s?start=%s" % (me["username"], code), code=code))
    ups.skip_old()

    def match(m):
        if (m.get("chat") or {}).get("type") != "private":
            return None
        text = (m.get("text") or "").strip()
        if text in ("/start " + code, code):
            return m["from"]
        if text.startswith("/start"):
            say(T("cli.you.nocode", name=name_of(m["from"])))
        return None

    user = ups.wait(match)
    if not user:
        say(T("cli.you.timeout"))
        raise KeyboardInterrupt
    lang = I.lang_of(user.get("language_code"))
    sput(lang_tg=lang)
    if not os.environ.get("PULT_LANG") and not (sget("prefs") or {}).get("lang"):
        I.set_lang(lang)                       # from here on — in the owner's Telegram language
    write_env(PULT_ALLOWED_USER_IDS=str(user["id"]))
    bot("sendMessage", chat_id=user["id"], text=T("cli.tg.hello", lang=lang))
    say(T("cli.you.ok", name=name_of(user), id=user["id"], language=T("cli.lang." + lang)))
    return user["id"]


def group_check(bot, me, chat):
    """(title, problem) — problem is None when Pult can work in the group."""
    try:
        c = bot("getChat", chat_id=chat)
        if not c.get("is_forum"):
            return c.get("title"), T("cli.why.not_forum")
        m = bot("getChatMember", chat_id=chat, user_id=me["id"])
        if m.get("status") != "administrator" or not m.get("can_manage_topics"):
            return c.get("title"), T("cli.why.not_admin")
        return c.get("title"), None
    except TgError as e:
        return None, T("cli.why.gone", why=e)


def step_group(bot, me, owner, ups):
    chat = sget("chat")
    if chat:
        title, problem = group_check(bot, me, chat)
        if not problem and yes(T("cli.group.keep", title=title)):
            return chat
        if problem:
            say(T("cli.group.problem", title=title or chat, why=problem))
    say(T("cli.group.how", bot=me["username"]))
    if ups.offset is None:
        ups.skip_old()
    rx = re.compile(r"^/bind(?:@(\w+))?(?:\s|$)", re.I)

    def reply(text, where):
        try:
            bot("sendMessage", text=text, **where)
        except TgError:
            pass                               # can't post there (no rights yet) — the terminal says it anyway

    def match(m):
        mm = rx.match((m.get("text") or "").strip())
        if not mm or (m.get("from") or {}).get("id") != owner:
            return None
        if mm.group(1) and mm.group(1).lower() != me["username"].lower():
            return None
        c = m.get("chat") or {}
        where = {"chat_id": c.get("id"), "message_thread_id": m.get("message_thread_id")
                 if m.get("is_topic_message") else None}
        if c.get("type") == "private":
            reply(T("bind.private"), where)
            return None
        if not c.get("is_forum"):
            reply(T("bind.need_forum"), where)
            say(T("cli.group.not_forum"))
            return None
        _, problem = group_check(bot, me, c["id"])
        if problem:
            reply(T("cli.tg.need_admin"), where)
            say(T("cli.group.not_admin", bot=me["username"]))
            return None
        reply(T("cli.tg.bound"), where)
        return c

    c = ups.wait(match)
    if not c:
        say(T("cli.group.timeout"))
        raise KeyboardInterrupt
    try:
        m = bot("getChatMember", chat_id=c["id"], user_id=me["id"])
    except TgError:
        m = {}
    if not m.get("can_pin_messages"):
        say(T("cli.group.no_pin"))
    sput(chat=c["id"], panel=None, welcome=True)
    say(T("cli.group.ok", title=c.get("title") or c["id"]))
    return c["id"]


def step_hooks():
    if hooks_installed():
        say(T("cli.hooks.already"))
        return
    say(T("cli.hooks.about", n=len(pult_hook.EVENTS), path=tilde(SETTINGS)))
    if yes(T("cli.hooks.ask")):
        hooks_set(True)
    else:
        say(T("cli.hooks.later"))


def cmd_setup():
    if not (HOME / "pultd.py").exists():
        say(T("cli.not_installed"))
        return 1
    lbl = label()
    say(T("cli.setup.title"))
    if service(lbl)[0]:
        say(T("cli.setup.pause"))
        svc_stop(lbl)
    ups, done = None, False
    try:
        step(1, "cli.step.bot")
        bot, me = step_bot(read_env())
        ups = Updates(bot)
        step(2, "cli.step.you")
        owner = step_you(bot, me, read_env(), ups)
        step(3, "cli.step.group")
        step_group(bot, me, owner, ups)
        step(4, "cli.step.hooks")
        step_hooks()
        done = True
    except KeyboardInterrupt:
        say("")
    except (OSError, TgError) as e:
        say(T("cli.bot.net", why=e, env=tilde(ENV_FILE)))
    except SystemExit as e:                    # hooks_set: settings.json can't be read
        say(str(e.code or ""))
    except Exception as e:                     # whatever it is, the daemon must not stay stopped
        say(T("cli.setup.failed", why=type(e).__name__))
    finally:
        if ups:
            ups.confirm()
        if not done:
            say(T("cli.setup.stopped"))
            if configured():
                restart(lbl)
    if not done:
        return 1
    write_service(lbl)
    if not restart(lbl):
        return 1
    linger_hint()
    say(T("cli.setup.done"))
    say(T("cli.setup.extras"))
    return 0


# ---------- tabs and the app ----------

def tab_conf():
    try:
        return json.loads(TAB_CONF.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def wrapper_users():
    """Settings files of VS Code, its forks, their profiles and their remote side that run Claude tabs through
    the wrapper (claudeProcessWrapper is a machine-level setting: it isn't in a workspace's settings)."""
    return pult_os.files_with(EDITOR_DIRS, TAB_FILE)


def tab_wrapped():
    return bool(wrapper_users())


WRAPPER_VALUE = re.compile(r'"claudeCode\.claudeProcessWrapper"\s*:\s*"((?:[^"\\\r\n]|\\.)*)"')


def wrapper_line():
    """The line for the VS Code settings, as JSON wants it: on Windows each backslash of the path doubled."""
    return '"claudeCode.claudeProcessWrapper": %s,' % json.dumps(str(HOME / TAB_FILE), ensure_ascii=False)


def wrapper_problems():
    """[(settings file, "broken" | "missing", what the line holds)] for each wrapper line VS Code can't use. The
    extension hands the value to the SDK as the program to run, as is (no ~), and the SDK first checks the file is
    there: "broken" — not a JSON string (a Windows path with single backslashes: VS Code drops each one with the
    letter after it, 2026-10-21), "missing" — no such file. Either way Claude tabs in VS Code don't start at all."""
    out = []
    for f in wrapper_users():
        try:
            text = f.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for m in WRAPPER_VALUE.finditer(text):
            if "//" in text[text.rfind("\n", 0, m.start()) + 1:m.start()]:
                continue                                    # commented out: VS Code doesn't read it
            try:
                path = json.loads('"%s"' % m.group(1))
            except ValueError:
                out.append((f, "broken", m.group(1)))
                continue
            if not os.path.isfile(path):
                out.append((f, "missing", path))
    return out


def wrapper_warnings():
    """What `pult status` and `pult tab setup` say about wrapper lines VS Code can't use, one text each."""
    return [T("cli.tab.broken" if why == "broken" else "cli.tab.missing", file=tilde(f), value=value,
              line=wrapper_line(), palette=pult_os.PALETTE) for f, why, value in wrapper_problems()]


def vkey(v):
    try:
        return tuple(int(x) for x in v.split("."))
    except ValueError:
        return (0,)


def newest_extension():
    return pult_os.newest_extension(EXT_DIRS)


def cmd_tab_setup():
    say(T("cli.tab.about"))
    conf = tab_conf()
    default = ", ".join(conf.get("folders") or ["~"])
    folders = [f.strip() for f in ask(T("cli.tab.folders", default=default), default).split(",") if f.strip()]
    conf["folders"] = folders
    conf["versions"] = sorted(set(conf.get("versions") or []) | set(TAB_VERIFIED), key=vkey)
    TAB_CONF.parent.mkdir(parents=True, exist_ok=True)
    TAB_CONF.write_text(json.dumps(conf, ensure_ascii=False) + "\n", encoding="utf-8")
    say(T("cli.tab.saved", path=tilde(TAB_CONF)))
    line = wrapper_line()
    say(T("cli.tab.line", line=line, palette=pult_os.PALETTE))
    if pult_os.remote_server():
        say(T("cli.tab.remote", palette=pult_os.PALETTE))
    for w in wrapper_warnings():
        say(w)
    ext = newest_extension()
    if ext and ext not in conf["versions"]:
        say(T("cli.tab.unverified", v=ext))
    clip = pult_os.clipboard()
    if clip and sys.stdin.isatty() and yes(T("cli.tab.copy")):
        subprocess.run(clip, input=line.encode())
        say(T("cli.tab.copied"))
    return 0


def cmd_app(argv):
    env = read_env()
    if argv[:1] == ["off"]:
        write_env(PULT_RELAY_URL=None, PULT_RELAY_SECRET=None, PULT_APP_LINK=None)
        say(T("cli.app.off"))
        if service(label())[0]:
            restart(label())
        return 0
    if not configured(env):
        say(T("cli.svc.not_ready"))
        return 1
    say(T("cli.app.about"))
    cur = env.get("PULT_RELAY_URL", "")
    cur = "https://" + cur[len("wss://"):-len("/agent")] + "/" if cur.startswith("wss://") and cur.endswith("/agent") \
        else ""
    while True:
        u = urllib.parse.urlsplit(ask(T("cli.app.url", default=cur or "—"), cur))
        if u.scheme == "https" and u.netloc:
            break
        say(T("cli.app.bad_url"))
    path = u.path.rstrip("/") or "/pult"
    try:
        botname = bot_call(env["PULT_BOT_TOKEN"], "getMe", env.get("PULT_PROXY") or None)["username"]
    except (TgError, OSError):
        botname = "your_bot"
    link_default = env.get("PULT_APP_LINK") or "https://t.me/%s/pult" % botname
    link = ask(T("cli.app.link", default=link_default), link_default)
    key = env.get("PULT_RELAY_SECRET") or secrets.token_urlsafe(32)
    write_env(PULT_RELAY_URL="wss://%s%s/agent" % (u.netloc, path), PULT_RELAY_SECRET=key, PULT_APP_LINK=link)
    say(T("cli.app.server_env"))
    say("  PULT_RELAY_SECRET=%s\n  PULT_OWNER_ID=%s\n  PULT_BOT_ID=%s" % (
        key, re.split(r"[,\s]+", env["PULT_ALLOWED_USER_IDS"].strip())[0], env["PULT_BOT_TOKEN"].split(":")[0]))
    say(T("cli.app.botfather", url="https://%s%s/" % (u.netloc, path)))
    restart(label())
    return 0


# ---------- voice input ----------

def stt_check(key, proxy=None):
    """Whether Groq takes the key: GET /models with it. Raises TgError with the reason (the wizard's error class)."""
    req = urllib.request.Request(STT_MODELS, headers={"Authorization": "Bearer " + key})
    handlers = [] if proxy is None else [urllib.request.ProxyHandler({"https": proxy} if proxy else {})]
    try:
        with urllib.request.build_opener(*handlers).open(req, timeout=20) as r:
            r.read(4096)
    except urllib.error.HTTPError as e:
        raise TgError(T("stt.e.key") if e.code in (401, 403) else "HTTP %s" % e.code, e.code) from None
    except urllib.error.URLError as e:
        raise OSError(str(e.reason)) from None


def cmd_stt(argv):
    """pult stt — the Groq key for speech recognition; pult stt off — remove it. The daemon notices the settings
    file change by itself (Pult.refresh_stt), so the service is not restarted."""
    env = read_env()
    if argv[:1] == ["off"]:
        write_env(PULT_STT_KEY=None)
        say(T("cli.stt.off"))
        return 0
    if not configured(env):
        say(T("cli.svc.not_ready"))
        return 1
    say(T("cli.stt.about", env=tilde(ENV_FILE)))
    had = bool(env.get("PULT_STT_KEY"))
    key = secret(T("cli.stt.key_again" if had else "cli.stt.key"))
    if not key:
        say(T("cli.stt.kept" if had else "cli.stt.none"))
        return 0
    say(T("cli.stt.checking"))
    try:
        stt_check(key, env.get("PULT_PROXY") or None)
    except (TgError, OSError) as e:
        say(T("cli.stt.bad", why=e))
        return 1
    write_env(PULT_STT_KEY=key)
    say(T("cli.stt.done"))
    return 0


# ---------- report and uninstall ----------

def redactor(env):
    """Hides what a public bug report must not carry: secrets, IDs, folder names, message text, commands."""
    vals = sorted({v for k, v in env.items() if k not in ("PULT_LABEL", "PULT_LANG") and len(v) >= 6},
                  key=len, reverse=True)
    home = str(Path.home())
    rules = [
        (r"(?<!\d)\d{5,}:[A-Za-z0-9_-]{30,}", "<token>"),
        (r"←.*", "← …"),                                     # incoming message: where and the text
        (r"\b(job \w+:|задача \w+:).*", r"\1 …"),            # a task's command and folder
        (r"(answered from Telegram —|bound to project|topic created:|тема создана:|is gone, creating it again:).*",
         r"\1 …"),
        (r"(#s\w+: [^—]*—).*", r"\1 …"),                     # a permission decision's note
        (r"(→).*", r"\1 …"),                                 # what a button did: project and session names
        (r"~/(?!\.local/share/pult|\.config/pult|\.local/state/pult|Library/Logs)[^\s,;:)'\"]+", "~/…"),
        (r"~\\(?!AppData\\Local\\pult)[^\s,;:)'\"]+", r"~\\…"),        # Windows: under the home folder
        (r"(?<![\w/])[A-Za-z]:[\\/][^\s,;)'\"]+", r"?:\\…"),               # …and anywhere on a drive
        (r"/(?:private|var|tmp|Volumes|home|root|mnt|media|srv)/[^\s,;:)'\"]+", "/…"),
        (r"(?<!\w)-?\d{6,}(?!\w)", "<id>"),                 # a standalone number: Telegram IDs, chats
    ]
    rules = [(re.compile(rx), rep) for rx, rep in rules]

    def f(line):
        for v in vals:
            line = line.replace(v, "<secret>")
        line = line.replace(home, "~")
        for rx, rep in rules:
            line = rx.sub(rep, line)
        return line
    return f


def tail(path, n):
    try:
        with open(path, "rb") as f:
            f.seek(0, 2)
            f.seek(max(0, f.tell() - 256 * 1024))
            return f.read().decode(errors="replace").splitlines()[-n:]
    except OSError:
        return []


def run_out(*cmd):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=15).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def claude_versions():
    out = []
    cli = shutil.which("claude", path=SERVICE_PATH + os.pathsep + os.environ.get("PATH", ""))
    if cli:
        out.append("CLI %s" % (run_out(cli, "--version").split(" ")[0] or "?"))
    ext = newest_extension()
    if ext:
        out.append("VS Code extension %s" % ext)
    sdk = run_out(str(PY), "-c", "import importlib.metadata as m; print(m.version('claude-agent-sdk'))")
    if sdk:
        out.append("Agent SDK %s" % sdk)
    return " · ".join(out) or "not found"


def report_lines():
    """The report itself is in English: it goes into a GitHub issue."""
    env = read_env()
    lbl = label()
    st, _ = service(lbl)
    have = lambda k: "set" if env.get(k) else "—"
    conf = tab_conf()
    linger = SVC.linger()
    lines = [
        "Pult %s · %s · Python %s" % (version(), pult_os.describe(),
                                     run_out(str(PY), "-c", "import platform; print(platform.python_version())")
                                     or "— (no environment)"),
        "Claude Code: %s" % claude_versions(),
        "service: %s (%s%s) · socket %s" % (
            st or "not running", "default label" if lbl == DEFAULT_LABEL else "own label",
            "" if linger is None else ", linger " + ("on" if linger else "off"), "answers" if sock_ok() else "no"),
        "settings: token %s · owner %s · group %s · language %s · proxy %s · app %s · voice %s" % (
            have("PULT_BOT_TOKEN"), have("PULT_ALLOWED_USER_IDS"), "set" if sget("chat") else "—", cli_lang(),
            have("PULT_PROXY"), have("PULT_RELAY_URL"), have("PULT_STT_KEY")),
        "hooks: %s" % (", ".join(hooks_installed()) or "off"),
        "this computer: desktop %s · keyboard idle from %s · VS Code server %s" % (
            pult_os.desktop() if pult_os.KIND == "linux" else pult_os.NAME, pult_os.idle_source(),
            "yes" if pult_os.remote_server() else "no"),
        "tabs: wrapper in VS Code settings %s%s · off switch %s · folders %d · verified versions %s" % (
            "yes" if tab_wrapped() else "no",
            "".join(" (%s line in %s)" % (why, tilde(f)) for f, why, _ in wrapper_problems()),
            "yes" if TAB_OFF.exists() else "no", len(conf.get("folders") or []),
            ", ".join(conf.get("versions") or []) or "—"),
    ]
    if env.get("PULT_BOT_TOKEN"):
        routes = ([("via proxy", env["PULT_PROXY"])] if env.get("PULT_PROXY") else []) + [("direct", "")]
        res = []
        for name, proxy in routes:
            try:
                bot_call(env["PULT_BOT_TOKEN"], "getMe", proxy, http_timeout=10)
                res.append("%s ok" % name)
            except (TgError, OSError) as e:
                res.append("%s: %s" % (name, type(e).__name__ if isinstance(e, OSError) else e))
        lines.append("Telegram: %s" % " · ".join(res))
    hide = redactor(env)
    lines += ["", "pult.log (last 40 lines):"] + [hide(x) for x in tail(LOG, 40)]
    lines += ["", "pult-tab.log (last 10 lines):"] + [hide(x) for x in tail(TAB_LOG, 10)]
    return lines


def cmd_report():
    say(T("cli.report.head"))
    say("```\n" + "\n".join(report_lines()) + "\n```")
    return 0


# Pult's own files: removal touches only these, never a whole folder it doesn't know
HOME_FILES = ("pultd.py", "pult_hook.py", "pult_render.py", "pult_web.py", "pult_i18n.py", "pult_stt.py", "pult_load.py", "pult_new.py", "pult_files.py", "pult_spend.py", "pult_attn.py", "pult_brief.py", "pult_os.py", "pult_setup.py", "pult_update.py",
              "installed.json", "installs.json", "update.json", "health.json", "installed.json.tmp", "installs.json.tmp",
              "update.json.tmp", "health.json.tmp", "prev",
              "pultctl.py", "pult_tab.py", "pult-tab.sh", "pult-tab.exe", "pult-tab.exe.new", "requirements.txt", "state.db",
              "state.db-journal", "state.db-wal", "state.db-shm", "pult.sock", "pult.sock.tmp", "venv", "__pycache__")
CONF_FILES = ("env", "env.tmp", "tab.json", "tab-off")
TAB_STUB = ('#!/bin/sh\n# Pult was removed. This stub runs Claude Code directly, so VS Code tabs keep working:\n'
            '# remove the claudeCode.claudeProcessWrapper line from the VS Code settings, then delete this folder.\n'
            'exec "$@"\n')


def remove_known(folder, names, keep=()):
    """Removes these names in folder, then the folder if it's empty. What can't go (Windows won't delete a program
    that runs — the uninstaller's own Python) is returned, not fatal."""
    left = []
    for n in names:
        p = folder / n
        if n in keep or not (p.exists() or p.is_symlink()):
            continue
        try:
            if p.is_dir() and not p.is_symlink():
                shutil.rmtree(p)
            else:
                p.unlink()
        except OSError:
            left.append(p)
    try:
        folder.rmdir()                          # only if nothing else is left
    except OSError:
        pass
    return left


def cmd_uninstall():
    lbl = label()
    say(T("cli.un.about", settings=tilde(SETTINGS), home=tilde(HOME)))
    if hooks_unreadable():                     # removing the files would leave hooks pointing at nothing
        say(T("cli.hooks.unreadable", path=tilde(SETTINGS)))
        return 1
    if not yes(T("cli.un.ask"), False):
        say(T("cli.un.cancel"))
        return 1
    drop_conf = yes(T("cli.un.conf", conf=tilde(ENV_FILE.parent)), False)
    if hooks_installed():
        hooks_set(False)
    svc_stop(lbl)
    SVC.remove(lbl)
    launcher = BIN / ("pult.cmd" if WIN else "pult")
    try:
        if not os.environ.get("PULT_HOME") and LAUNCHER_MARK in launcher.read_text(encoding="utf-8", errors="replace"):
            launcher.unlink()
    except OSError:
        pass
    users = wrapper_users()
    if users and WIN:
        # the stub keeps pult_tab.py inside and runs on the base pythonw: the environment can go
        make_tab_exe(stub=True)
        left = remove_known(HOME, HOME_FILES, keep=("pult-tab.exe",))
        say(T("cli.un.tab", path=tilde(HOME / TAB_FILE), home=tilde(HOME),
              settings=", ".join(tilde(f) for f in users)))
    elif users:
        # VS Code would fail to start Claude tabs without the wrapper file: leave a pass-through stub
        left = remove_known(HOME, HOME_FILES, keep=("pult-tab.sh",))
        (HOME / "pult-tab.sh").write_text(TAB_STUB, encoding="utf-8")
        (HOME / "pult-tab.sh").chmod(0o755)
        say(T("cli.un.tab", path=tilde(HOME / "pult-tab.sh"), home=tilde(HOME),
              settings=", ".join(tilde(f) for f in users)))
    else:
        left = remove_known(HOME, HOME_FILES)
    if left:
        say(T("cli.un.left", paths=", ".join(tilde(p) for p in left)))
    if drop_conf:
        remove_known(ENV_FILE.parent, CONF_FILES + (ENV_FILE.name,))
        for p in (LOG, TAB_LOG):
            p.unlink(missing_ok=True)
        for d in {LOG.parent, TAB_LOG.parent}:
            if d.name == "pult":                # Linux: Pult's own log folder (macOS keeps logs in a shared one)
                try:
                    d.rmdir()
                except OSError:
                    pass
    say(T("cli.un.done"))
    return 0
