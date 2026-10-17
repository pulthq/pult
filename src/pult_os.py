"""Pult: what depends on the operating system, in one place. Standard library only.

Pult runs on macOS and Linux; Windows is being ported (stage K). Each function answers for the system it runs on and
says "don't know" (None) rather than fail, so the rest of Pult keeps working where an answer is missing.
"""
import os
import platform
import plistlib
import re
import shutil
import subprocess
import sys
from pathlib import Path

KIND = "mac" if sys.platform == "darwin" else "windows" if sys.platform == "win32" else "linux"
NAME = {"mac": "macOS", "linux": "Linux", "windows": "Windows"}[KIND]
HOME = Path.home()

# Logs: where each system keeps them. Fixed paths, like ~/.config/pult: the service, the CLI and the tab wrapper
# run with different environments and must all agree (the tab wrapper repeats this line: it imports nothing of Pult's)
LOG_DIR = HOME / "Library" / "Logs" if KIND == "mac" else HOME / ".local" / "state" / "pult"
PALETTE = "Cmd+Shift+P" if KIND == "mac" else "Ctrl+Shift+P"     # VS Code's command palette

# VS Code and its forks: the folder name of their settings, and of their server when a window is remote (Remote-SSH)
EDITOR_APPS = ("Code", "Code - Insiders", "Cursor", "VSCodium", "Windsurf")
EDITOR_SERVERS = (".vscode-server", ".vscode-server-insiders", ".cursor-server", ".vscodium-server", ".windsurf-server")
FLATPAKS = (("com.visualstudio.code", "Code"), ("com.vscodium.codium", "VSCodium"))


def editor_dirs(home=HOME):
    """Folders that hold settings.json of VS Code and its forks here: the user settings (with profiles inside) and,
    on a machine VS Code reaches through Remote-SSH, the remote machine settings. claudeProcessWrapper is a
    machine-level setting: in a remote window only the remote one counts."""
    if KIND == "mac":
        dirs = [home / "Library" / "Application Support" / app / "User" for app in EDITOR_APPS]
    elif KIND == "windows":
        roaming = Path(os.environ.get("APPDATA") or home / "AppData" / "Roaming")
        dirs = [roaming / app / "User" for app in EDITOR_APPS]
    else:
        dirs = [home / ".config" / app / "User" for app in EDITOR_APPS]
        dirs += [home / ".var" / "app" / fid / "config" / app / "User" for fid, app in FLATPAKS]
    return dirs + [home / srv / "data" / "Machine" for srv in EDITOR_SERVERS]


def extension_dirs(home=HOME):
    """Where VS Code keeps extensions: the desktop app, Insiders, Flatpak, and the server side of Remote-SSH."""
    return [home / ".vscode" / "extensions", home / ".vscode-insiders" / "extensions",
            home / ".var" / "app" / "com.visualstudio.code" / "data" / "vscode" / "extensions",
            home / ".vscode-server" / "extensions", home / ".vscode-server-insiders" / "extensions"]


def settings_files(dirs):
    for d in dirs:
        yield d / "settings.json"
        yield from sorted(d.glob("profiles/*/settings.json"))


def files_with(dirs, mark):
    """settings.json files among dirs that mention mark (JSON with comments: a search for the string)."""
    found = []
    for f in settings_files(dirs):
        try:
            if mark in f.read_text(encoding="utf-8"):
                found.append(f)
        except (OSError, UnicodeDecodeError):
            pass
    return found


def remote_server(home=HOME):
    """VS Code reaches this machine through Remote-SSH (its server is installed here)."""
    return any((home / srv).is_dir() for srv in EDITOR_SERVERS)


def newest_extension(dirs):
    """The newest installed version of the Claude Code extension, e.g. "2.1.301", or None."""
    best, key = None, None
    for d in dirs:
        for p in d.glob("anthropic.claude-code-*"):
            v = p.name[len("anthropic.claude-code-"):].split("-")[0]
            try:
                k = tuple(int(x) for x in v.split("."))
            except ValueError:
                continue
            if key is None or k > key:
                best, key = v, k
    return best


def run(*cmd, timeout=5):
    """stdout of a command, or None when it can't run or fails."""
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError):
        return None
    return p.stdout if p.returncode == 0 else None


def system_lang():
    """The two-letter language of the system ("ru", "en"), or "" when unknown."""
    if KIND == "mac":
        m = re.search(r'\(\s*"?([A-Za-z]{2})', run("defaults", "read", "-g", "AppleLanguages", timeout=3) or "")
        if m:
            return m.group(1).lower()
    for k in ("LANGUAGE", "LC_ALL", "LC_MESSAGES", "LANG"):      # the order gettext reads them in
        v = os.environ.get(k, "").split(":")[0]
        if v and v != "POSIX" and not v.startswith("C"):
            return v[:2].lower()
    return ""


def describe():
    """"macOS 26.0 (arm64)", "Ubuntu 24.04.1 LTS (aarch64)" — for the bug report."""
    if KIND == "mac":
        name = "macOS " + (platform.mac_ver()[0] or "?")
    elif KIND == "windows":
        name = "Windows " + platform.release()
    else:
        try:
            name = platform.freedesktop_os_release().get("PRETTY_NAME") or ""
        except (OSError, AttributeError):
            name = ""
        name = name or "Linux " + platform.release()
    return "%s (%s)" % (name, platform.machine())


def desktop():
    """The Linux desktop for the report: "GNOME, wayland", or "none" (a server, an SSH session)."""
    de, kind = os.environ.get("XDG_CURRENT_DESKTOP", ""), os.environ.get("XDG_SESSION_TYPE", "")
    if not (de or os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")):
        return "none"
    return ", ".join(x for x in (de, kind) if x) or "unknown"


def clipboard():
    """The command that puts its stdin on the clipboard here, or None (a server, nothing installed)."""
    if KIND == "mac":
        return ["pbcopy"] if shutil.which("pbcopy") else None
    if os.environ.get("WAYLAND_DISPLAY") and shutil.which("wl-copy"):
        return ["wl-copy"]
    if os.environ.get("DISPLAY"):
        for cmd in (["xclip", "-selection", "clipboard"], ["xsel", "--clipboard", "--input"]):
            if shutil.which(cmd[0]):
                return cmd
    return None


def shell_rc():
    """The startup file of the user's shell, where a PATH line goes."""
    sh = os.path.basename(os.environ.get("SHELL", "") or ("zsh" if KIND == "mac" else "bash"))
    return {"zsh": "~/.zshrc", "fish": "~/.config/fish/config.fish"}.get(sh, "~/.bashrc")


# ---------- keyboard and mouse ----------

def input_idle():
    """Seconds since the last keyboard or mouse input on this computer, or None when the system can't tell
    (a server without a screen, a remote session, a desktop Pult doesn't know)."""
    if KIND == "mac":
        m = re.search(r'"HIDIdleTime"\s*=\s*(\d+)',
                      run("ioreg", "-c", "IOHIDSystem", "-d", "4", "-r", "-k", "HIDIdleTime") or "")
        return int(m.group(1)) / 1e9 if m else None
    if KIND == "linux":
        return linux_idle()
    return None


def _dbus(dest, path, method):
    """A call on the session bus with no arguments: gdbus (GLib), else dbus-send. Its output, or None."""
    if shutil.which("gdbus"):
        return run("gdbus", "call", "--session", "--dest", dest, "--object-path", path, "--method", method, timeout=2)
    if shutil.which("dbus-send"):
        return run("dbus-send", "--session", "--print-reply", "--dest=" + dest, path, method, timeout=2)
    return None


def _gnome():
    # GNOME (Wayland and X11): milliseconds
    out = _dbus("org.gnome.Mutter.IdleMonitor", "/org/gnome/Mutter/IdleMonitor/Core",
                "org.gnome.Mutter.IdleMonitor.GetIdletime")
    m = re.search(r"uint64 (\d+)", out or "")
    return int(m.group(1)) / 1000 if m else None


def _screensaver():
    # KDE Plasma and other desktops with the freedesktop screensaver interface: seconds
    out = _dbus("org.freedesktop.ScreenSaver", "/org/freedesktop/ScreenSaver",
                "org.freedesktop.ScreenSaver.GetSessionIdleTime")
    m = re.search(r"uint32 (\d+)", out or "")
    return float(m.group(1)) if m else None


def _x11():
    # an X11 session (not Wayland: there X shows only its own windows' input). Xlib may end the process on a
    # protocol error, so the query runs in a separate Python, never in the daemon
    if not os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY") \
            or os.environ.get("XDG_SESSION_TYPE", "x11") != "x11":
        return None
    out = run(sys.executable, "-I", os.path.abspath(__file__), "x11-idle", timeout=3)
    return int(out) / 1000 if out and out.strip().isdigit() else None


LINUX_WAYS = {"gnome": _gnome, "screensaver": _screensaver, "x11": _x11}
_last = [None]                         # the way that answered last time: asked first


def linux_idle():
    order = sorted(LINUX_WAYS, key=lambda k: k != _last[0])
    for name in order:
        v = LINUX_WAYS[name]()
        if v is not None:
            _last[0] = name
            return v
    _last[0] = None
    return None


def idle_source():
    """Which way told the idle time last ("ioreg", "gnome", "screensaver", "x11"), or "none" — for the report."""
    if KIND == "mac":
        return "ioreg"
    if KIND == "linux":
        linux_idle()
        return _last[0] or "none"
    return "none"


def _x11_idle_ms():
    import ctypes
    import ctypes.util

    class Info(ctypes.Structure):
        _fields_ = [("window", ctypes.c_ulong), ("state", ctypes.c_int), ("kind", ctypes.c_int),
                    ("til_or_since", ctypes.c_ulong), ("idle", ctypes.c_ulong), ("event_mask", ctypes.c_ulong)]

    x11 = ctypes.CDLL(ctypes.util.find_library("X11") or "libX11.so.6")
    xss = ctypes.CDLL(ctypes.util.find_library("Xss") or "libXss.so.1")
    x11.XOpenDisplay.restype = ctypes.c_void_p
    x11.XDefaultRootWindow.argtypes = [ctypes.c_void_p]
    x11.XDefaultRootWindow.restype = ctypes.c_ulong
    xss.XScreenSaverQueryExtension.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_int),
                                               ctypes.POINTER(ctypes.c_int)]
    xss.XScreenSaverAllocInfo.restype = ctypes.POINTER(Info)
    xss.XScreenSaverQueryInfo.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.POINTER(Info)]
    dpy = x11.XOpenDisplay(None)
    if not dpy:
        return None
    a, b = ctypes.c_int(), ctypes.c_int()
    if not xss.XScreenSaverQueryExtension(dpy, ctypes.byref(a), ctypes.byref(b)):
        return None
    info = xss.XScreenSaverAllocInfo()
    if not xss.XScreenSaverQueryInfo(dpy, x11.XDefaultRootWindow(dpy), info):
        return None
    return info.contents.idle


# ---------- the service that keeps the daemon running ----------

def sd_quote(s, exec_line=False):
    """A value for a systemd unit file: in double quotes, % doubled; in ExecStart= also $ (variables)."""
    s = s.replace("\\", "\\\\").replace('"', '\\"').replace("%", "%%")
    return '"%s"' % (s.replace("$", "$$") if exec_line else s)


class Launchd:
    """macOS: a per-user launchd agent in ~/Library/LaunchAgents."""
    DEFAULT = "io.github.pulthq.pult"

    def __init__(self, folder=None):
        self.folder = Path(folder or HOME / "Library" / "LaunchAgents")

    def path(self, lbl):
        return self.folder / (lbl + ".plist")

    def find(self, script):
        """The label of an agent that runs this copy of Pult (an existing install keeps its name), or None."""
        for p in sorted(self.folder.glob("*.plist")):
            try:
                with open(p, "rb") as f:
                    d = plistlib.load(f)
            except Exception:
                continue
            if isinstance(d, dict) and str(script) in (d.get("ProgramArguments") or []) and d.get("Label"):
                return d["Label"]
        return None

    def write(self, lbl, argv, env, log, cwd):
        d = {"Label": lbl, "ProgramArguments": [str(a) for a in argv], "WorkingDirectory": str(cwd),
             "EnvironmentVariables": env, "RunAtLoad": True, "KeepAlive": True, "ThrottleInterval": 10, "Nice": 5,
             "StandardOutPath": str(log), "StandardErrorPath": str(log)}
        self.folder.mkdir(parents=True, exist_ok=True)
        with open(self.path(lbl), "wb") as f:
            plistlib.dump(d, f)
        return self.path(lbl)

    def state(self, lbl):
        """(state, pid); (None, None) — not loaded."""
        out = run("launchctl", "print", "gui/%d/%s" % (os.getuid(), lbl), timeout=10) or ""
        val = lambda key: next((ln.split("=", 1)[1].strip() for ln in out.splitlines()
                                if ln.strip().startswith(key + " =")), None)
        return val("state"), val("pid")

    def problem(self):
        return None

    def stop(self, lbl):
        run("launchctl", "bootout", "gui/%d/%s" % (os.getuid(), lbl), timeout=30)
        return True

    def start(self, lbl):
        return run("launchctl", "bootstrap", "gui/%d" % os.getuid(), str(self.path(lbl)), timeout=30) is not None

    def remove(self, lbl):
        self.path(lbl).unlink(missing_ok=True)

    def linger(self):
        return None


class Systemd:
    """Linux: a systemd user service in ~/.config/systemd/user (systemctl --user). It runs while the user is
    logged in; on a server, `loginctl enable-linger` keeps it after logout and starts it at boot."""
    DEFAULT = "pult"

    def __init__(self, folder=None):
        self.folder = Path(folder or HOME / ".config" / "systemd" / "user")

    def path(self, lbl):
        return self.folder / (lbl + ".service")

    def find(self, script):
        for p in sorted(self.folder.glob("*.service")):
            try:
                text = p.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            if any(ln.startswith("ExecStart=") and sd_quote(str(script), True) in ln for ln in text.splitlines()):
                return p.name[:-len(".service")]
        return None

    def write(self, lbl, argv, env, log, cwd):
        lines = ["# Pult: Claude Code sessions from Telegram. Written by `pult install`, removed by `pult uninstall`.",
                 "[Unit]", "Description=Pult: Claude Code sessions from Telegram",
                 "StartLimitIntervalSec=0", "",
                 "[Service]", "ExecStart=" + " ".join(sd_quote(str(a), True) for a in argv),
                 "WorkingDirectory=" + str(cwd).replace("%", "%%"),
                 "Environment=" + " ".join(sd_quote("%s=%s" % kv) for kv in env.items()),
                 "Restart=always", "RestartSec=10", "Nice=5",
                 "StandardOutput=append:" + str(log).replace("%", "%%"),
                 "StandardError=append:" + str(log).replace("%", "%%"), "",
                 "[Install]", "WantedBy=default.target", ""]
        self.folder.mkdir(parents=True, exist_ok=True)
        self.path(lbl).write_text("\n".join(lines), encoding="utf-8")
        return self.path(lbl)

    def ctl(self, *args, timeout=30):
        return run("systemctl", "--user", *args, timeout=timeout)

    def state(self, lbl):
        out = self.ctl("show", lbl + ".service", "--property=LoadState,ActiveState,SubState,MainPID", timeout=10)
        d = dict(ln.split("=", 1) for ln in (out or "").splitlines() if "=" in ln)
        if d.get("LoadState") != "loaded" or d.get("ActiveState") in (None, "inactive", "failed"):
            return None, None
        return d.get("SubState") or d.get("ActiveState"), (d.get("MainPID") if d.get("MainPID") not in ("", "0") else None)

    def problem(self):
        """Why user services can't run here, or None: no systemd (a container, WSL without it), no user manager
        (a shell from su or sudo, not a login)."""
        if not shutil.which("systemctl"):
            return "no systemctl"
        if self.ctl("show-environment", timeout=10) is None:
            return "no user session bus (systemctl --user)"
        return None

    def stop(self, lbl):
        self.ctl("stop", lbl + ".service")
        return True

    def start(self, lbl):
        self.ctl("daemon-reload")
        self.ctl("enable", lbl + ".service")                   # starts with the next login (or boot, with linger)
        return self.ctl("start", lbl + ".service") is not None

    def remove(self, lbl):
        self.ctl("disable", lbl + ".service")
        self.path(lbl).unlink(missing_ok=True)
        self.ctl("daemon-reload")

    def linger(self):
        """Whether this user's services outlive their login (loginctl enable-linger); None — unknown."""
        out = run("loginctl", "show-user", str(os.getuid()), "--property=Linger", "--value")
        return None if out is None else out.strip() == "yes"


def service_manager(folder=None):
    return Launchd(folder) if KIND == "mac" else Systemd(folder)


def service_path(bin_dir):
    """PATH for the daemon's service: Pult's command first, then where Claude Code and the tools usually are."""
    extra = "/opt/homebrew/bin:/usr/local/bin" if KIND == "mac" else "/usr/local/bin"
    tail = ":/snap/bin" if KIND == "linux" else ""
    return "%s:%s:/usr/bin:/bin:/usr/sbin:/sbin%s" % (bin_dir, extra, tail)


if __name__ == "__main__" and sys.argv[1:] == ["x11-idle"]:
    try:
        ms = _x11_idle_ms()
    except Exception:
        ms = None
    if ms is None:
        sys.exit(1)
    print(ms)
