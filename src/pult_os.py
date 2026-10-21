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
import time
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
    if KIND == "windows":
        try:
            import ctypes
            import locale
            name = locale.windows_locale.get(ctypes.windll.kernel32.GetUserDefaultUILanguage(), "")
        except (OSError, AttributeError):
            name = ""
        if name:
            return name[:2].lower()
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
        name = "Windows %s (build %s)" % (platform.release(), platform.version().split(".")[-1] or "?")
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
    if KIND == "windows":
        return win_idle()
    return None


def screen_locked():
    """Whether the screen is locked: True / False, or None where the system can't tell. macOS — the console session's
    CGSSessionScreenIsLocked in the IORegistry (the key is there only while locked); Linux — logind's LockedHint."""
    if KIND == "mac":
        out = subprocess.run(["ioreg", "-n", "Root", "-d1", "-a"], capture_output=True, timeout=5).stdout \
            if shutil.which("ioreg") else b""
        try:
            users = plistlib.loads(out).get("IOConsoleUsers") or []
        except Exception:
            return None
        console = [u for u in users if u.get("kCGSSessionOnConsoleKey")]
        return any(bool(u.get("CGSSessionScreenIsLocked")) for u in console) if console else None
    if KIND == "linux" and os.environ.get("XDG_SESSION_ID") and shutil.which("loginctl"):
        out = run("loginctl", "show-session", os.environ["XDG_SESSION_ID"], "-p", "LockedHint", "--value") or ""
        return {"yes": True, "no": False}.get(out.strip())
    if KIND == "windows":
        return win_locked()
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
    if KIND == "windows":
        return "GetLastInputInfo" if win_idle() is not None else "none"
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


# ---------- the link between the daemon and the hook, the tab wrapper, the `pult` command ----------
#
# macOS and Linux: a unix socket, mode 600. Windows (Python has no unix sockets there): 127.0.0.1 and a free port;
# the link file, where the socket would be, holds {"port", "key", "pid"} — it is in the user's own folder, and the
# key is the first line of every connection. PULT_LINK=tcp turns the Windows way on elsewhere too (the checks).
# pult_hook.py and pult_tab.py repeat link_connect: they import nothing of Pult's.

def link_tcp():
    return KIND == "windows" or os.environ.get("PULT_LINK") == "tcp"


def link_connect(path, timeout=1.0):
    """A connected socket to the daemon; OSError (or ValueError: a broken link file) when there is none."""
    import socket
    if not link_tcp():
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.settimeout(timeout)
        try:
            s.connect(path)
        except OSError:
            s.close()
            raise
        return s
    import json
    with open(path, encoding="utf-8") as f:
        link = json.load(f)
    try:
        port, key = int(link["port"]), str(link["key"])
    except (KeyError, TypeError) as e:
        raise ValueError("bad link file") from e
    s = socket.create_connection(("127.0.0.1", port), timeout=timeout)
    s.sendall(key.encode() + b"\n")
    return s


# ---------- Windows: processes, keyboard idle, the lock screen ----------
#
# ctypes with the argument types spelled out: without them a 64-bit handle is cut to 32 bits.

_w = {}


def _win():
    """kernel32 and user32 with the functions Pult calls; set up on first use."""
    if not _w:
        import ctypes
        from ctypes import wintypes as t
        k = ctypes.WinDLL("kernel32", use_last_error=True)
        u = ctypes.WinDLL("user32", use_last_error=True)
        for f, res, args in (
                (k.OpenProcess, t.HANDLE, [t.DWORD, t.BOOL, t.DWORD]),
                (k.GetExitCodeProcess, t.BOOL, [t.HANDLE, ctypes.POINTER(t.DWORD)]),
                (k.TerminateProcess, t.BOOL, [t.HANDLE, t.UINT]),
                (k.CloseHandle, t.BOOL, [t.HANDLE]),
                (k.CreateToolhelp32Snapshot, t.HANDLE, [t.DWORD, t.DWORD]),
                (k.Process32FirstW, t.BOOL, [t.HANDLE, ctypes.c_void_p]),
                (k.Process32NextW, t.BOOL, [t.HANDLE, ctypes.c_void_p]),
                (k.ProcessIdToSessionId, t.BOOL, [t.DWORD, ctypes.POINTER(t.DWORD)]),
                (k.GetTickCount, t.DWORD, []),
                (u.GetLastInputInfo, t.BOOL, [ctypes.c_void_p]),
                (u.OpenInputDesktop, t.HANDLE, [t.DWORD, t.BOOL, t.DWORD]),
                (u.SwitchDesktop, t.BOOL, [t.HANDLE]),
                (u.CloseDesktop, t.BOOL, [t.HANDLE])):
            f.restype, f.argtypes = res, args
        _w.update(k=k, u=u, ctypes=ctypes, t=t)
    return _w


def win_session():
    """The Windows session this process runs in: 0 is the services' one — no screen, no keyboard."""
    w = _win()
    sid = w["t"].DWORD()
    return sid.value if w["k"].ProcessIdToSessionId(os.getpid(), w["ctypes"].byref(sid)) else None


def win_idle():
    """Seconds since the last keyboard or mouse input in this user's session, or None (the services' session)."""
    if win_session() in (0, None):
        return None
    w = _win()

    class Info(w["ctypes"].Structure):
        _fields_ = [("cbSize", w["t"].UINT), ("dwTime", w["t"].DWORD)]
    li = Info()
    li.cbSize = w["ctypes"].sizeof(li)
    if not w["u"].GetLastInputInfo(w["ctypes"].byref(li)):
        return None
    return ((w["k"].GetTickCount() - li.dwTime) & 0xFFFFFFFF) / 1000     # both wrap around after 49.7 days


def win_locked():
    """True while the input goes to another desktop than the user's — the lock screen (or a screen saver, or a UAC
    prompt for a moment); None in the services' session, where there is no input desktop at all."""
    if win_session() in (0, None):
        return None
    w = _win()
    h = w["u"].OpenInputDesktop(0, False, 0x0100)          # DESKTOP_SWITCHDESKTOP
    if not h:
        return True
    try:
        return not w["u"].SwitchDesktop(h)                 # switching to the desktop we are on: fails only when locked
    finally:
        w["u"].CloseDesktop(h)


def pid_alive(pid):
    """Whether the process exists. Not os.kill(pid, 0) on Windows: there it terminates the process."""
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return True
    if KIND != "windows":
        try:
            os.kill(pid, 0)
            return True
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
    w = _win()
    h = w["k"].OpenProcess(0x1000, False, pid)               # PROCESS_QUERY_LIMITED_INFORMATION
    if not h:
        return w["ctypes"].get_last_error() == 5            # access denied: it exists, it isn't ours
    try:
        code = w["t"].DWORD()
        return not w["k"].GetExitCodeProcess(h, w["ctypes"].byref(code)) or code.value == 259     # STILL_ACTIVE
    finally:
        w["k"].CloseHandle(h)


def win_procs():
    """Windows: {pid: (parent pid, program file name)} of every process — one Toolhelp snapshot."""
    w = _win()
    c, t = w["ctypes"], w["t"]

    class Entry(c.Structure):
        _fields_ = [("dwSize", t.DWORD), ("cntUsage", t.DWORD), ("th32ProcessID", t.DWORD),
                    ("th32DefaultHeapID", c.c_size_t), ("th32ModuleID", t.DWORD), ("cntThreads", t.DWORD),
                    ("th32ParentProcessID", t.DWORD), ("pcPriClassBase", c.c_long), ("dwFlags", t.DWORD),
                    ("szExeFile", c.c_wchar * 260)]
    snap = w["k"].CreateToolhelp32Snapshot(2, 0)             # TH32CS_SNAPPROCESS
    if not snap or snap == c.c_void_p(-1).value:
        return {}
    out, e = {}, Entry()
    e.dwSize = c.sizeof(e)
    try:
        ok = w["k"].Process32FirstW(snap, c.byref(e))
        while ok:
            out[e.th32ProcessID] = (e.th32ParentProcessID, e.szExeFile)
            ok = w["k"].Process32NextW(snap, c.byref(e))
    finally:
        w["k"].CloseHandle(snap)
    return out


def children(pid, name=None):
    """Direct children of a process (pids), only those whose program is name ("claude") when given."""
    pid = int(pid)
    if KIND == "windows":
        want = name and name.lower()
        return [p for p, (pp, exe) in win_procs().items() if pp == pid and
                (not want or exe.lower() in (want, want + ".exe"))]
    # macOS pgrep leaves out the asker's own ancestors unless -a: asked from a session Pult started, its claude
    # would be missing (Linux pgrep has no such rule, and its -a means something else)
    out = run("pgrep", *(["-a"] if KIND == "mac" else []), "-P", str(pid), *(["-f", name] if name else [])) or ""
    return [int(x) for x in out.split()]


def kill(pid):
    """Ends a process at once (Windows: TerminateProcess; elsewhere SIGKILL). Whether it was there to end."""
    if KIND != "windows":
        try:
            os.kill(int(pid), 9)
            return True
        except OSError:
            return False
    w = _win()
    h = w["k"].OpenProcess(0x0001, False, int(pid))          # PROCESS_TERMINATE
    if not h:
        return False
    try:
        return bool(w["k"].TerminateProcess(h, 1))
    finally:
        w["k"].CloseHandle(h)


# ---------- the load on the computer: processes, processor, memory ----------
#
# One snapshot of every process for the app's load view: what Claude's sessions and the commands they run cost the
# computer. Proc: ppid, cmd (the command line), cpu (% of one core, now), mem (bytes held now), peak (the process's
# highest mem since it started, or None), cpu_time (seconds of processor since it started, its finished children
# included, or None), started (epoch seconds), mine (our user's). Machine: cores, cpu (% of the whole computer),
# mem_total and mem_used (bytes), load (the 1-minute load average).

def processes():
    """(procs {pid: Proc}, machine), or None when this system can't tell — the app then shows no load."""
    try:
        if KIND == "mac":
            return _mac_processes()
        if KIND == "linux":
            return _linux_processes()
    except (OSError, ValueError):
        pass
    return None


def clock(s):
    """ps's elapsed and processor time — "[dd-][hh:]mm:ss[.cc]" — as seconds."""
    days, _, s = s.rpartition("-")
    parts = s.split(":")
    sec = float(parts[-1].replace(",", "."))
    for i, n in enumerate(reversed(parts[:-1])):
        sec += int(n) * (60, 3600)[min(i, 1)]
    return sec + (int(days) * 86400 if days else 0)


CTRL = re.compile(r"\\(0[0-3][0-7])")       # ps writes a newline or a tab in the arguments as \012, \011


def ps_rows(out, now, uid):
    """`ps -o pid=,ppid=,uid=,pcpu=,rss=,etime=,time=,args=` → {pid: Proc}; rss is in KiB."""
    procs = {}
    for line in out.splitlines():
        p = line.split(None, 7)
        if len(p) < 7:
            continue
        try:
            procs[int(p[0])] = {"ppid": int(p[1]), "mine": int(p[2]) == uid,
                                "cmd": CTRL.sub(lambda m: chr(int(m.group(1), 8)), p[7]) if len(p) > 7 else "",
                                "cpu": float(p[3].replace(",", ".")), "mem": int(p[4]) * 1024, "peak": None,
                                "cpu_time": clock(p[6]), "started": now - clock(p[5])}
        except ValueError:
            continue
    return procs


_rusage = [None]          # macOS: proc_pid_rusage, set up on first use (False — not available)


def _mac_usage():
    """pid → {mem, peak, cpu_time} from proc_pid_rusage (our own processes only): mem is the "Memory" Activity Monitor
    shows (the physical footprint), peak — the highest footprint since the start, cpu_time — the process's own time
    plus that of its children which have finished. None — not available."""
    if _rusage[0] is None:
        try:
            import ctypes
            import ctypes.util
            names = ("user_time system_time pkg_idle_wkups interrupt_wkups pageins wired_size resident_size "
                     "phys_footprint proc_start_abstime proc_exit_abstime child_user_time child_system_time "
                     "child_pkg_idle_wkups child_interrupt_wkups child_pageins child_elapsed_abstime diskio_bytesread "
                     "diskio_byteswritten qos_default qos_maintenance qos_background qos_utility qos_legacy "
                     "qos_user_initiated qos_user_interactive billed_system_time serviced_system_time logical_writes "
                     "lifetime_max_phys_footprint instructions cycles billed_energy serviced_energy "
                     "interval_max_phys_footprint runnable_time").split()

            class Info(ctypes.Structure):          # struct rusage_info_v4, <sys/resource.h>; room to spare at the end
                _fields_ = [("uuid", ctypes.c_uint8 * 16)] + [(n, ctypes.c_uint64) for n in names] + \
                    [("spare", ctypes.c_uint64 * 16)]

            class Timebase(ctypes.Structure):
                _fields_ = [("numer", ctypes.c_uint32), ("denom", ctypes.c_uint32)]
            lib = ctypes.CDLL(ctypes.util.find_library("proc") or "/usr/lib/libproc.dylib")
            tb = Timebase()
            ctypes.CDLL(None).mach_timebase_info(ctypes.byref(tb))
            tick = tb.numer / tb.denom / 1e9       # the times are in Mach ticks: 125/3 ns on Apple silicon

            def use(pid):
                r = Info()
                if lib.proc_pid_rusage(pid, 4, ctypes.byref(r)) != 0:
                    return None
                return {"mem": r.phys_footprint, "peak": max(r.lifetime_max_phys_footprint, r.phys_footprint),
                        "cpu_time": (r.user_time + r.system_time + r.child_user_time + r.child_system_time) * tick}
            _rusage[0] = use
        except (OSError, AttributeError):
            _rusage[0] = False
    return _rusage[0] or None


def _mac_processes():
    out = run("ps", "-axww", "-o", "pid=,ppid=,uid=,pcpu=,rss=,etime=,time=,args=", timeout=10)
    if out is None:
        return None
    procs = ps_rows(out, time.time(), os.getuid())
    use = _mac_usage()
    for pid, d in procs.items():
        r = use(pid) if use and d["mine"] else None
        if r:
            d.update(r)
    cores = os.cpu_count() or 1
    info = (run("sysctl", "-n", "hw.memsize", "kern.memorystatus_level") or "").split()
    total = int(info[0]) if info and info[0].isdigit() else None
    # memorystatus_level: the share of memory the system counts as available (what `memory_pressure` prints)
    free = int(info[1]) if len(info) > 1 and info[1].isdigit() else None
    return procs, {"cores": cores, "cpu": min(100.0, sum(d["cpu"] for d in procs.values()) / cores),
                   "mem_total": total, "mem_used": total * (100 - free) // 100 if total and free is not None else None,
                   "load": os.getloadavg()[0]}


_ticks = [None]           # Linux: the previous reading — "now" is the difference between two readings


def _linux_read():
    rows = {}
    for name in os.listdir("/proc"):
        if not name.isdigit():
            continue
        try:
            with open("/proc/%s/stat" % name, "rb") as f:
                s = f.read().decode(errors="replace")
        except OSError:
            continue
        f = s[s.rfind(")") + 2:].split()        # the fields after "(comm)": f[0] is field 3, the state
        rows[int(name)] = (int(f[1]), int(f[11]) + int(f[12]), int(f[13]) + int(f[14]), int(f[19]), int(f[21]))
    with open("/proc/stat") as f:
        cpu = [int(x) for x in f.readline().split()[1:]]
    return time.monotonic(), rows, cpu


def _linux_processes():
    tck, page = os.sysconf("SC_CLK_TCK"), os.sysconf("SC_PAGE_SIZE")
    prev, cur = _ticks[0], _linux_read()
    if not prev or not 0.4 <= cur[0] - prev[0] <= 120:
        time.sleep(0.5)                         # no recent reading to compare with: take a second one
        prev, cur = cur, _linux_read()
    _ticks[0] = cur
    span = cur[0] - prev[0]
    with open("/proc/stat") as f:
        btime = next(int(x.split()[1]) for x in f if x.startswith("btime"))
    uid, procs = os.getuid(), {}
    for pid, (ppid, own, kids, start, rss) in cur[1].items():
        was = prev[1].get(pid)
        d = {"ppid": ppid, "cpu": max(0.0, (own - was[1]) / tck / span * 100) if was and was[3] == start else 0.0,
             "mem": rss * page, "peak": None, "cpu_time": (own + kids) / tck, "started": btime + start / tck,
             "cmd": "", "mine": False}
        try:
            with open("/proc/%d/cmdline" % pid, "rb") as f:
                d["cmd"] = f.read().rstrip(b"\0").replace(b"\0", b" ").decode(errors="replace")
            d["mine"] = os.stat("/proc/%d" % pid).st_uid == uid
            if d["mine"]:
                with open("/proc/%d/status" % pid) as f:
                    hwm = next((x.split()[1] for x in f if x.startswith("VmHWM:")), None)
                d["peak"] = max(int(hwm) * 1024, d["mem"]) if hwm else None
        except (OSError, ValueError):
            pass
        procs[pid] = d
    a, b = prev[2], cur[2]
    busy = sum(b) - sum(a)
    idle = (b[3] + b[4]) - (a[3] + a[4])            # idle and iowait
    mem = {}
    with open("/proc/meminfo") as f:
        for x in f:
            k, _, v = x.partition(":")
            if k in ("MemTotal", "MemAvailable"):
                mem[k] = int(v.split()[0]) * 1024
    total = mem.get("MemTotal")
    return procs, {"cores": os.cpu_count() or 1, "cpu": 100.0 * (busy - idle) / busy if busy > 0 else 0.0,
                   "mem_total": total, "mem_used": total - mem["MemAvailable"] if total and "MemAvailable" in mem
                   else None, "load": os.getloadavg()[0]}


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


def xml_esc(s):
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def win_args(args):
    """A Windows command line from a list (the quoting CreateProcess and Python's argv parsing agree on)."""
    return subprocess.list2cmdline([str(a) for a in args])


class Schtasks:
    """Windows: a Task Scheduler task of this user, started at logon in the user's own session (a Windows service
    would live in the services' session, without the keyboard idle time) and restarted after a failure. schtasks.exe
    needs no administrator rights for a task that runs as the user who creates it.

    A task carries no environment variables: the daemon gets the user's own. The task's definition is kept next to
    Pult (<label>.task.xml) — it is what `pult start` registers again. The state comes from the daemon's link file
    (its pid; pult.sock holds the port, the key and the pid on Windows)."""
    DEFAULT = "Pult"

    def __init__(self, folder=None):
        self.folder = Path(folder or os.environ.get("PULT_HOME") or HOME / ".local" / "share" / "pult")
        self.link = Path(os.environ.get("PULT_SOCK") or self.folder / "pult.sock")

    def path(self, lbl):
        return self.folder / (lbl + ".task.xml")

    def find(self, script):
        for p in sorted(self.folder.glob("*.task.xml")):
            try:
                text = p.read_text(encoding="utf-16")
            except (OSError, UnicodeError):
                continue
            if xml_esc(script) in text:
                return p.name[:-len(".task.xml")]
        return None

    @staticmethod
    def user():
        import getpass
        dom = os.environ.get("USERDOMAIN")
        return "%s\\%s" % (dom, getpass.getuser()) if dom else getpass.getuser()

    def xml(self, argv, cwd):
        user = xml_esc(self.user())
        return "\n".join([
            '<?xml version="1.0" encoding="UTF-16"?>',
            '<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">',
            "  <RegistrationInfo><Description>Pult: Claude Code sessions from Telegram. Written by `pult install`, "
            "removed by `pult uninstall`.</Description></RegistrationInfo>",
            "  <Triggers><LogonTrigger><Enabled>true</Enabled><UserId>%s</UserId></LogonTrigger></Triggers>" % user,
            '  <Principals><Principal id="Author"><UserId>%s</UserId><LogonType>InteractiveToken</LogonType>'
            "<RunLevel>LeastPrivilege</RunLevel></Principal></Principals>" % user,
            "  <Settings>",
            "    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>",
            "    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>",
            "    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>",
            "    <AllowHardTerminate>true</AllowHardTerminate>",
            "    <StartWhenAvailable>true</StartWhenAvailable>",
            "    <RunOnlyIfNetworkAvailable>false</RunOnlyIfNetworkAvailable>",
            "    <IdleSettings><StopOnIdleEnd>false</StopOnIdleEnd><RestartOnIdle>false</RestartOnIdle></IdleSettings>",
            "    <AllowStartOnDemand>true</AllowStartOnDemand>",
            "    <Enabled>true</Enabled>",
            "    <Hidden>false</Hidden>",
            "    <RunOnlyIfIdle>false</RunOnlyIfIdle>",
            "    <WakeToRun>false</WakeToRun>",
            "    <ExecutionTimeLimit>PT0S</ExecutionTimeLimit>",
            "    <Priority>7</Priority>",
            "    <RestartOnFailure><Interval>PT1M</Interval><Count>999</Count></RestartOnFailure>",
            "  </Settings>",
            '  <Actions Context="Author"><Exec><Command>%s</Command><Arguments>%s</Arguments>'
            "<WorkingDirectory>%s</WorkingDirectory></Exec></Actions>" % (
                xml_esc(argv[0]), xml_esc(win_args(argv[1:])), xml_esc(cwd)),
            "</Task>", ""])

    def write(self, lbl, argv, env, log, cwd):
        self.folder.mkdir(parents=True, exist_ok=True)
        self.path(lbl).write_text(self.xml(argv, cwd), encoding="utf-16")      # schtasks reads UTF-16 only
        return self.path(lbl)

    def pid(self):
        try:
            with open(self.link, encoding="utf-8") as f:
                return int(__import__("json").load(f)["pid"])
        except (OSError, ValueError, KeyError, TypeError):
            return None

    def state(self, lbl):
        pid = self.pid()
        return ("running", str(pid)) if pid and pid_alive(pid) else (None, None)

    def problem(self):
        return None if shutil.which("schtasks") else "no schtasks.exe"

    def stop(self, lbl):
        run("schtasks", "/End", "/TN", lbl, timeout=30)
        pid = self.pid()
        exe = win_procs().get(pid, (0, ""))[1].lower() if pid else ""
        if exe in ("pythonw.exe", "python.exe"):
            kill(pid)                          # started by hand, not by the task: /End doesn't reach it
        return True

    def start(self, lbl):
        if run("schtasks", "/Create", "/TN", lbl, "/XML", str(self.path(lbl)), "/F", timeout=30) is None:
            return False
        return run("schtasks", "/Run", "/TN", lbl, timeout=30) is not None

    def remove(self, lbl):
        run("schtasks", "/Delete", "/TN", lbl, "/F", timeout=30)
        self.path(lbl).unlink(missing_ok=True)

    def linger(self):
        return None


def service_manager(folder=None):
    return Launchd(folder) if KIND == "mac" else Schtasks(folder) if KIND == "windows" else Systemd(folder)


def service_path(bin_dir):
    """PATH for the daemon's service: Pult's command first, then where Claude Code and the tools usually are."""
    if KIND == "windows":                       # the task has no environment of its own: this is only for lookups
        return os.pathsep.join([str(bin_dir), os.environ.get("PATH", "")])
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
