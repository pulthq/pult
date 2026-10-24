"""Probe: does a process started by the daemon outlive the stop of the daemon's own service — for the "Install
update" button (the daemon starts the installer; the installer restarts the daemon's own service).
macOS: a launchd user agent and `launchctl bootout`; Linux: a systemd user service and `systemctl --user stop`.

Run (standard library only, no Claude, no network; the cases run side by side):
  macOS  ~/.local/share/pult/venv/bin/python tests/probe_update.py [variant ...] [--keep]     ~45 s
  Linux  python3 tests/probe_update.py [variant ...] [--keep]                                 ~2 min (see 2)

macOS. Each case is a throwaway job io.github.pulthq.probe-update-<variant>-<mode>, bootstrapped into gui/$UID from a
plist in a temporary folder (not ~/Library/LaunchAgents), set up like Pult's own plist (RunAtLoad, KeepAlive, Nice 5,
ExitTimeOut left at the default). Its main process (the "daemon") starts a "child" (the "installer"):
  1   plain subprocess.Popen — same process group and session;
  1n  as 1, but the child keeps the default signal handling, as a real installer would (the control case);
  2   Popen(start_new_session=True) — setsid: a session and process group of its own;
  3   as 2, then the child forks and exits at once; the grandchild goes on (double fork);
  4   plain Popen, but the job's plist has AbandonProcessGroup = true;
  5a  `launchctl submit -l <label> -- <cmd>` — the child is a job of its own;
  5b  `launchctl bootstrap` of a separate one-shot plist — the child is a job of its own.
Modes: ext — the probe boots the job out from outside; self — the child itself runs `launchctl bootout
gui/$UID/<job>`, as the installer would. Once the job is gone, the child runs `launchctl bootstrap gui/$UID <the job's
plist>` — the restart.

Linux. Each case is a throwaway unit pult-probe-update-<variant>-<mode>.service, written to ~/.config/systemd/user
like Pult's own (Restart=always, RestartSec=10, Nice=5, StartLimitIntervalSec=0, PATH and the like in Environment=;
KillMode and TimeoutStopSec left at the defaults — control-group and the manager's DefaultTimeoutStopSec), started
but not enabled. Its main process (the "daemon") starts a "child" (the "installer"):
  1n  plain subprocess.Popen, default signal handling (the control case);
  2   Popen(start_new_session=True) — setsid; the child is still in the unit's cgroup;
  6   `systemd-run --user --collect --quiet --unit=<label>-run-<pid> --setenv=PULT_PROBE_SET=set -E PULT_PROBE_PASS
      <python> <probe> child <dir>` — a transient service of its own (its parent is the user manager);
  6s  the same with --scope — a transient scope: still the daemon's child, but in a cgroup of its own.
Modes: ext — the probe runs `systemctl --user stop <unit>`; self — the child runs it, as the installer would. Once the
unit is inactive, the child runs `systemctl --user start <unit>` — the restart — and asks `is-active`.
The unit's Environment= sets PATH, PULT_PROBE_HOME and PULT_PROBE_PASS (as Pult's sets PATH and PULT_HOME); the
daemon and the child log what they see of these, of XDG_RUNTIME_DIR and DBUS_SESSION_BUS_ADDRESS, and their cgroup.
The daemon of 6 also runs `systemctl --user is-system-running` and `systemd-run --user /bin/true` with its
environment as is, without DBUS_SESSION_BUS_ADDRESS, and without XDG_RUNTIME_DIR too. A child that traps SIGTERM
inside the unit's cgroup holds the stop until TimeoutStopSec (90 s by default) and then gets SIGKILL — so 2 makes
the run last about two minutes. A user manager must be running (a login session, or `loginctl enable-linger`).

Both. Except in 1n, the child traps SIGTERM, SIGHUP and SIGINT (logs each and stays alive: a child that does not trap
SIGTERM would have died there), checks in 3 s after the stop (the marker), restarts the service and keeps a heartbeat
to +30 s, past launchd's wait between SIGTERM and SIGKILL. The restarted daemon sees it already spawned and only
stays up. The probe watches the child's pid, so a SIGKILL shows as the time of death.
Only the probe's own jobs and units are touched (io.github.pulthq.probe-update-*, pult-probe-update-*): every
launchctl, systemctl and systemd-run call goes through a guard; `systemctl --user daemon-reload` is the one
manager-wide call. Everything is stopped, killed and removed at the end, also on failure — on Linux also
reset-failed and the unit files deleted — and leftovers of an earlier run at the start. Pult's own service is never
touched. --keep leaves the temporary folder with every log for a look.
"""
import json, os, plistlib, shutil, signal, subprocess, sys, tempfile, threading, time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

LINUX = sys.platform.startswith("linux")
PREFIX = "pult-probe-update-" if LINUX else "io.github.pulthq.probe-update-"
TMP_PREFIX = "pult-probe-update-"
UID = os.getuid()
VARIANTS = ("1n", "2", "6", "6s") if LINUX else ("1", "1n", "2", "3", "4", "5a", "5b")
MODES = ("ext", "self")
WATCH = 30            # the child's heartbeat lasts this long after the stop
WAIT = WATCH + (120 if LINUX else 15)       # the probe's wait for a case; on Linux past TimeoutStopSec's SIGKILL
UNITS = Path.home() / ".config" / "systemd" / "user"
SEEN = ("PATH", "PULT_PROBE_HOME", "PULT_PROBE_PASS", "PULT_PROBE_SET", "XDG_RUNTIME_DIR", "DBUS_SESSION_BUS_ADDRESS",
        "HOME", "USER", "LANG", "INVOCATION_ID")


def call(argv, env=None, timeout=60):
    """Run a command: (rc, its output, seconds); rc None when it could not run or ran out of time."""
    t = time.time()
    try:
        r = subprocess.run(argv, capture_output=True, text=True, timeout=timeout, env=env)
        return r.returncode, (r.stdout + r.stderr).strip(), round(time.time() - t, 2)
    except (OSError, subprocess.SubprocessError) as e:
        return None, repr(e), round(time.time() - t, 2)


def lctl(*args):
    """launchctl on this probe's own labels only; anything else is refused, so Pult's service is never touched."""
    verb = args[0]
    if verb in ("bootout", "print"):
        ok = len(args) == 2 and args[1].rsplit("/", 1)[-1].startswith(PREFIX)
    elif verb == "remove":
        ok = len(args) == 2 and args[1].startswith(PREFIX)
    elif verb == "submit":
        ok = args[1] == "-l" and args[2].startswith(PREFIX)
    elif verb == "bootstrap":
        with open(args[2], "rb") as f:
            ok = len(args) == 3 and plistlib.load(f).get("Label", "").startswith(PREFIX)
    elif verb == "list":
        ok = len(args) == 1
    else:
        ok = False
    if not ok:
        raise SystemExit("probe_update: refusing launchctl %r" % (args,))
    return call(["launchctl", *args])


def sctl(*args, env=None, timeout=150):
    """systemctl --user on this probe's own units only (plus reads of the manager and daemon-reload); anything else is
    refused, so Pult's own unit is never touched."""
    verb, names = args[0], [a for a in args[1:] if not a.startswith("-")]
    if verb in ("daemon-reload", "is-system-running"):
        ok = not names
    elif verb == "show":
        ok = all(n.startswith(PREFIX) for n in names)          # no unit: the manager's own properties
    elif verb in ("start", "stop", "is-active", "reset-failed"):
        ok = bool(names) and all(n.startswith(PREFIX) for n in names)
    elif verb == "list-units":
        ok = names == [PREFIX + "*"]
    else:
        ok = False
    if not ok:
        raise SystemExit("probe_update: refusing systemctl --user %r" % (args,))
    return call(["systemctl", "--user", *args], env, timeout)


def srun(*args):
    """The argv of `systemd-run --user` for one of this probe's own units only."""
    units = [a[len("--unit="):] for a in args if a.startswith("--unit=")]
    if len(units) != 1 or not units[0].startswith(PREFIX):
        raise SystemExit("probe_update: refusing systemd-run %r" % (args,))
    return ["systemd-run", "--user", *args]


def short(r):
    return [r[0], r[1][-200:], r[2]]


def put(path, text):
    """Write at once: the other side polls for the file and must never read it half-written."""
    tmp = path.with_suffix(".tmp")
    tmp.write_text(text)
    os.replace(tmp, path)


def wait_for(cond, limit, step=0.05):
    end = time.time() + limit
    while time.time() < end:
        if cond():
            return True
        time.sleep(step)
    return False


def cgroup():
    try:
        return Path("/proc/self/cgroup").read_text().splitlines()[-1].split(":", 2)[2]
    except (OSError, IndexError):
        return None


def seen():
    return {k: os.environ.get(k) for k in SEEN}


def log(d, name, ev, **kw):
    kw.update(ev=ev, t=time.time(), pid=os.getpid(), ppid=os.getppid(), pgid=os.getpgrp(), sid=os.getsid(0))
    if LINUX:
        kw["cg"] = cgroup()
    with open(d / name, "a") as f:
        f.write(json.dumps(kw) + "\n")


# ---- the service, either platform ----

def stop(c):
    """Stop the case's service — what the installer does first."""
    return sctl("stop", c["unit"]) if LINUX else lctl("bootout", "gui/%d/%s" % (UID, c["label"]))


def gone(c):
    """Whether the service is down: the restart waits for it."""
    if LINUX:
        return sctl("is-active", c["unit"], timeout=30)[1] in ("inactive", "failed")
    return lctl("print", "gui/%d/%s" % (UID, c["label"]))[0] != 0


def restart(c):
    return sctl("start", c["unit"]) if LINUX else lctl("bootstrap", "gui/%d" % UID, c["plist"])


def state(c):
    """The service's state at the end, as its manager tells it."""
    if LINUX:
        out = sctl("show", c["unit"], "--property=ActiveState,SubState", timeout=30)[1]
        p = dict(ln.split("=", 1) for ln in out.splitlines() if "=" in ln)
        return "%s/%s" % (p.get("ActiveState"), p.get("SubState"))
    st = lctl("print", "gui/%d/%s" % (UID, c["label"]))
    return next((ln.split("=", 1)[1].strip() for ln in st[1].splitlines() if ln.strip().startswith("state =")),
                None) if st[0] == 0 else "not loaded"


# ---- inside the throwaway services: the probe copies itself into the temporary folder and runs from there ----

def envcheck(label):
    """From inside the service: systemctl and systemd-run with its environment as is, without
    DBUS_SESSION_BUS_ADDRESS, and without XDG_RUNTIME_DIR too."""
    out = {}
    for i, drop in enumerate(((), ("DBUS_SESSION_BUS_ADDRESS",), ("DBUS_SESSION_BUS_ADDRESS", "XDG_RUNTIME_DIR"))):
        e = {k: v for k, v in os.environ.items() if k not in drop}
        out["without " + " ".join(drop) if drop else "as is"] = {
            "systemctl": short(sctl("is-system-running", env=e, timeout=30)),
            "systemd-run": short(call(srun("--collect", "--quiet", "--unit=%s-envcheck-%d" % (label, i), "/bin/true"),
                                      e, 30))}
    return out


def role_parent(d, c):
    """The service's main process — the daemon. Starts the child its variant's way, then stays up."""
    log(d, "parent.log", "start", env=seen())
    if (d / "spawned").exists():
        log(d, "parent.log", "restarted")
    else:
        (d / "spawned").touch()
        v, cmd = c["variant"], [sys.executable, __file__, "child", str(d)]
        if v in ("1", "1n", "4"):
            log(d, "parent.log", "spawned", child=subprocess.Popen(cmd).pid)
        elif v == "2":
            log(d, "parent.log", "spawned", child=subprocess.Popen(cmd, start_new_session=True).pid)
        elif v == "3":
            p = subprocess.Popen(cmd + ["detach"], start_new_session=True)
            p.wait()
            log(d, "parent.log", "spawned", child=p.pid, rc=p.returncode)
        elif v == "5a":
            log(d, "parent.log", "spawned", r=short(lctl("submit", "-l", c["child_label"], "--", *cmd)))
        elif v == "5b":
            log(d, "parent.log", "spawned", r=short(lctl("bootstrap", "gui/%d" % UID, c["child_plist"])))
        elif v in ("6", "6s"):
            if v == "6":
                log(d, "parent.log", "envcheck", checks=envcheck(c["label"]))
            argv = srun(*(["--scope"] if v == "6s" else []), "--collect", "--quiet",
                        "--unit=%s-run-%d" % (c["label"], os.getpid()),
                        "--setenv=PULT_PROBE_SET=set", "-E", "PULT_PROBE_PASS", *cmd)
            if v == "6":
                log(d, "parent.log", "spawned", r=short(call(argv)))
            else:                           # a scope's process is systemd-run itself, exec'ing the child: no wait
                log(d, "parent.log", "spawned", child=subprocess.Popen(argv).pid)
    time.sleep(300)                         # the probe died midway: the service takes itself away
    if LINUX:
        sctl("stop", c["unit"])
    else:
        lctl("bootout", "gui/%d/%s" % (UID, c["label"]))


def role_child(d, c):
    """The installer: outlive the stop of the service, then restart it."""
    if "detach" in sys.argv:
        if os.fork():
            os._exit(0)                     # the middle process exits at once; the grandchild goes on
    for s in (signal.SIGTERM, signal.SIGHUP, signal.SIGINT) if c["variant"] != "1n" else ():
        signal.signal(s, lambda n, f: log(d, "child.log", "signal", sig=signal.Signals(n).name))
    if (d / "done").exists():               # a `launchctl submit` job is kept alive: a relaunch only waits
        log(d, "child.log", "respawn")
        time.sleep(300)
        lctl("remove", c["child_label"])
        return
    log(d, "child.log", "start", env=seen())
    t0f = d / "t0"
    if c["mode"] == "self":
        if not wait_for((d / "go").exists, 60):
            return
        put(t0f, repr(time.time()))
        log(d, "child.log", "stop", r=short(stop(c)))
    elif not wait_for(t0f.exists, 60):
        return
    t0 = float(t0f.read_text())
    time.sleep(max(0.0, t0 + 3 - time.time()))
    log(d, "child.log", "alive3")
    down = wait_for(lambda: gone(c), max(0.0, t0 + WATCH - 3 - time.time()), 0.5)
    log(d, "child.log", "service down" if down else "service still up")     # the restart's call follows
    log(d, "child.log", "restart", r=short(restart(c)))
    if LINUX:
        log(d, "child.log", "is-active", r=short(sctl("is-active", c["unit"], timeout=30)))
    while time.time() < t0 + WATCH:
        log(d, "child.log", "beat")
        time.sleep(1)
    log(d, "child.log", "end")
    (d / "done").touch()


# ---- the probe itself ----

def events(path):
    try:
        return [json.loads(x) for x in path.read_text().splitlines() if x.strip()]
    except (OSError, ValueError):
        return []


def write_plist(path, data):
    with open(path, "wb") as f:
        plistlib.dump(data, f)


def sd_quote(s, exec_line=False):
    """One word of a unit file line, quoted, with systemd's specifiers (and, on ExecStart, variables) escaped."""
    s = str(s).replace("\\", "\\\\").replace('"', '\\"').replace("%", "%%")
    return '"%s"' % (s.replace("$", "$$") if exec_line else s)


def alive(pid):
    if LINUX:                               # a zombie counts as dead
        try:
            return Path("/proc/%d/stat" % pid).read_text().rsplit(")", 1)[1].split()[0] != "Z"
        except OSError:
            return False
        except IndexError:
            return True
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def prepare(tmp, agent, variant, mode):
    """The case's folder and its service's definition: a plist in the folder, or a unit in ~/.config/systemd/user."""
    name = "%s-%s" % (variant, mode)
    d = tmp / name
    d.mkdir()
    label = PREFIX + name
    c = {"variant": variant, "mode": mode, "label": label, "unit": label + ".service", "plist": str(d / "job.plist"),
         "child_label": label + "-child", "child_plist": str(d / "child.plist")}
    (d / "case.json").write_text(json.dumps(c))
    if LINUX:
        env = {"PATH": "%s/bin:/usr/local/bin:/usr/bin:/bin" % d, "PULT_PROBE_HOME": str(d),
               "PULT_PROBE_PASS": "passed"}
        out = str(d / "job.out").replace("%", "%%")
        UNITS.mkdir(parents=True, exist_ok=True)
        (UNITS / c["unit"]).write_text("\n".join([
            "# A throwaway unit of tests/probe_update.py; the probe removes it.",
            "[Unit]", "Description=Pult probe_update " + name, "StartLimitIntervalSec=0", "",
            "[Service]", "ExecStart=" + " ".join(sd_quote(a, True) for a in (sys.executable, agent, "parent", d)),
            "WorkingDirectory=" + str(d).replace("%", "%%"),
            "Environment=" + " ".join(sd_quote("%s=%s" % kv) for kv in env.items()),
            "Restart=always", "RestartSec=10", "Nice=5",
            "StandardOutput=append:" + out, "StandardError=append:" + out, "",
            "[Install]", "WantedBy=default.target", ""]), encoding="utf-8")
        return d, c
    job = {"Label": label, "ProgramArguments": [sys.executable, str(agent), "parent", str(d)],
           "WorkingDirectory": str(d), "RunAtLoad": True, "KeepAlive": True, "ThrottleInterval": 10, "Nice": 5,
           "StandardOutPath": str(d / "job.out"), "StandardErrorPath": str(d / "job.out")}
    if variant == "4":
        job["AbandonProcessGroup"] = True
    write_plist(d / "job.plist", job)
    if variant == "5b":
        write_plist(d / "child.plist", {
            "Label": c["child_label"], "ProgramArguments": [sys.executable, str(agent), "child", str(d)],
            "WorkingDirectory": str(d), "RunAtLoad": True,
            "StandardOutPath": str(d / "child.out"), "StandardErrorPath": str(d / "child.out")})
    return d, c


def run_case(d, c):
    name = "%s-%s" % (c["variant"], c["mode"])
    r = sctl("start", c["unit"], timeout=60) if LINUX else lctl("bootstrap", "gui/%d" % UID, c["plist"])
    if r[0] != 0:
        return {"name": name, "error": "the start of the service failed: %s" % r[1]}
    props = sctl("show", c["unit"], "--property=KillMode,TimeoutStopUSec,ControlGroup", timeout=30)[1] if LINUX else ""
    if not wait_for(lambda: any(e["ev"] == "start" for e in events(d / "child.log")), 20):
        return {"name": name, "error": "the child did not start; parent %s; job.out %r" % (
            events(d / "parent.log"), (d / "job.out").read_text()[-300:] if (d / "job.out").exists() else "")}
    pid = next(e["pid"] for e in events(d / "child.log") if e["ev"] == "start")
    time.sleep(0.5)
    res, th = {}, None
    if c["mode"] == "ext":
        put(d / "t0", repr(time.time()))
        th = threading.Thread(target=lambda: res.update(r=short(stop(c))), daemon=True)
        th.start()
    else:
        (d / "go").touch()
    died, end = None, time.time() + WAIT
    while time.time() < end and not (d / "done").exists():
        if not alive(pid):
            died = time.time()
            break
        time.sleep(0.2)
    if th:
        th.join(WAIT)
    time.sleep(3 if LINUX else 1.5)
    return summarize(d, c, res.get("r"), died, props)


def summarize(d, c, by_probe, died, props):
    ev, pev = events(d / "child.log"), events(d / "parent.log")
    t0 = float((d / "t0").read_text()) if (d / "t0").exists() else None
    start = next(e for e in ev if e["ev"] == "start")
    p0 = pev[0] if pev else {}
    mine = [e for e in ev if e["pid"] == start["pid"]]
    rel = lambda e: e["t"] - t0 if t0 else float("nan")
    same = lambda k: "same" if start.get(k) == p0.get(k) else "own"
    return {
        "name": "%s-%s" % (c["variant"], c["mode"]),
        "group": "%s pg, %s session" % (same("pgid"), same("sid")) + (", %s cgroup" % same("cg") if LINUX else ""),
        "ids": "daemon pid %s pgid %s sid %s | child pid %s ppid %s pgid %s sid %s" % (
            p0.get("pid"), p0.get("pgid"), p0.get("sid"), start["pid"], start["ppid"], start["pgid"], start["sid"]),
        "cgroups": "daemon %s | child %s" % (p0.get("cg"), start.get("cg")),
        "props": " ".join(props.split()),
        "alive3": any(e["ev"] == "alive3" for e in mine),
        "end": any(e["ev"] == "end" for e in mine),
        "last": max(rel(e) for e in mine),
        "died": died - t0 if died and t0 else None,
        "signals": ["%s %+.1fs" % (e["sig"], rel(e)) for e in mine if e["ev"] == "signal"],
        "stop": by_probe or next((e["r"] for e in mine if e["ev"] == "stop"), None),
        "stop_by": "probe" if by_probe else "child",
        "restart": next((e["r"] for e in mine if e["ev"] == "restart"), None),
        "daemon_gone": not alive(p0["pid"]) if p0 else None,
        "restarted": next((rel(e) for e in pev if e["ev"] == "restarted"), None),
        "state": state(c),
        "spawn": next((e.get("r") for e in pev if e["ev"] == "spawned" and "r" in e), None),
        "envcheck": next((e["checks"] for e in pev if e["ev"] == "envcheck"), None),
        "env": (p0.get("env") or {}, start.get("env") or {}),
        "timeline": ["%+.1f %s%s" % (rel(e), e["ev"], " " + e["sig"] if "sig" in e else
                                     " " + json.dumps(e["r"]) if "r" in e else "") for e in mine
                     if e["ev"] != "beat"] + (["(beats to %+.1f)" % max(rel(e) for e in mine if e["ev"] == "beat")]
                                              if any(e["ev"] == "beat" for e in mine) else []),
    }


def ours_loaded():
    """The probe's jobs, or its units (loaded or failed) and unit files, left in place."""
    if LINUX:
        out = sctl("list-units", "--all", "--plain", "--no-legend", PREFIX + "*", timeout=30)[1]
        rows = [[w for w in ln.split() if w != "●"] for ln in out.splitlines()]
        units = {w[0] for w in rows
                 if len(w) > 2 and w[0].startswith(PREFIX) and (w[1], w[2]) != ("not-found", "inactive")}
        return sorted(units | {p.name for p in UNITS.glob(PREFIX + "*")})
    out = lctl("list")[1]
    return sorted({ln.split()[-1] for ln in out.splitlines() if ln.split() and ln.split()[-1].startswith(PREFIX)})


def kill_ours(mark, role=None):
    """SIGKILL the probe's own processes: their command line holds the temporary folder."""
    ps = ["ps", "-e", "-ww", "-o", "pid=,args="] if LINUX else ["ps", "-axww", "-o", "pid=,args="]
    out = subprocess.run(ps, capture_output=True, text=True).stdout
    for line in out.splitlines():
        pid, _, args = line.strip().partition(" ")
        if mark in args and (role is None or " %s " % role in args) and int(pid) != os.getpid():
            try:
                os.kill(int(pid), signal.SIGKILL)
            except OSError:
                pass


def cleanup(mark):
    kill_ours(mark, "child")                # first the children, so none restarts a service behind our back
    if LINUX:
        for _ in range(2):                  # once more after the kill: a dead child's queued start may have run
            for u in ours_loaded():
                sctl("stop", u)
            kill_ours(mark)
        for u in ours_loaded():
            sctl("reset-failed", u, timeout=30)
        for p in UNITS.glob(PREFIX + "*"):
            p.unlink()
        sctl("daemon-reload")
        return ours_loaded()
    for lbl in ours_loaded():
        lctl("bootout", "gui/%d/%s" % (UID, lbl))
    for lbl in ours_loaded():               # a submitted job may need the old verb
        lctl("remove", lbl)
    kill_ours(mark)
    return ours_loaded()


def about_linux():
    """The system, the user manager and the probe's own environment; exits when there is no user manager."""
    os.system("grep PRETTY_NAME /etc/os-release; uname -sr; systemctl --version | head -1; "
              "loginctl show-user $(id -u) --property=Linger --property=State | tr '\\n' ' '; echo")
    r = sctl("is-system-running", timeout=30)
    print("user manager: %s (rc %s);" % (r[1], r[0]),
          " ".join(sctl("show", "--property=Version,DefaultTimeoutStopUSec", timeout=30)[1].split()))
    print("the probe's env: XDG_RUNTIME_DIR=%s DBUS_SESSION_BUS_ADDRESS=%s" % (
        os.environ.get("XDG_RUNTIME_DIR"), os.environ.get("DBUS_SESSION_BUS_ADDRESS")))
    if r[0] is None or "Failed to connect" in r[1] or not shutil.which("systemd-run"):
        sys.exit("probe_update: no systemd user manager here (log in, or `loginctl enable-linger`)")


def main():
    keep = "--keep" in sys.argv
    want = [a for a in sys.argv[1:] if a in VARIANTS] or list(VARIANTS)
    if LINUX:
        about_linux()
    left = cleanup(TMP_PREFIX)              # leftovers of an earlier run that died midway
    if left:
        sys.exit("probe_update: cannot clear old probe services: %s" % left)
    if not LINUX:
        os.system("sw_vers | tr '\\n' ' '; echo")
    print("python:", sys.executable, flush=True)
    tmp = Path(tempfile.mkdtemp(prefix=TMP_PREFIX))
    agent = tmp / "probe_update.py"
    shutil.copy(__file__, agent)            # jobs run from the temp folder: launchd jobs may not read ~/Documents
    results = []
    try:
        cases = [prepare(tmp, agent, v, m) for v in want for m in MODES]
        if LINUX:
            sctl("daemon-reload")
        print("cases:", " ".join("%(variant)s-%(mode)s" % c for _, c in cases), "— up to %d s" % (WAIT + 25),
              flush=True)
        with ThreadPoolExecutor(len(cases)) as ex:
            futs = [ex.submit(run_case, d, c) for d, c in cases]
            for f in futs:
                try:
                    results.append(f.result())
                except Exception as e:
                    results.append({"name": "?", "error": repr(e)})
    finally:
        left = cleanup(str(tmp))
        if keep:
            print("kept:", tmp)
        else:
            shutil.rmtree(tmp, ignore_errors=True)
        print("cleanup:", "clean" if not left else "LEFT %s" % left, flush=True)

    yn = lambda b: "yes" if b else "no"
    word = ("stop", "start") if LINUX else ("bootout", "bootstrap")
    row = "%-8s %-36s %-5s %-16s %-26s %-18s %-11s %s"
    print("\n" + row % ("case", "child", "+3s", "to +30s", "signals to the child", word[0] + " rc,s (by)",
                        word[1] + " rc", "service back"))
    for r in results:
        if "error" in r:
            print("%-8s ERROR %s" % (r["name"], r["error"]))
            continue
        st = "%s,%s (%s)" % (r["stop"][0], r["stop"][2], r["stop_by"]) if r["stop"] else "- (%s)" % r["stop_by"]
        print(row % (
            r["name"], r["group"], yn(r["alive3"]),
            "yes" if r["end"] else "no, died %+.1fs" % r["died"] if r["died"] is not None else "no %+.0fs" % r["last"],
            ", ".join(r["signals"]) or "none", st, str(r["restart"][0]) if r["restart"] else "-",
            "%s (%s)" % ("yes %+.1fs" % r["restarted"] if r["restarted"] is not None else "no", r["state"])))
    print("\ndetails (seconds from the stop):")
    for r in results:
        if "error" in r:
            continue
        print("  %s  %s; old daemon gone: %s" % (r["name"], r["ids"], r["daemon_gone"]))
        if LINUX:
            print("      unit:", r["props"])
            print("      cgroups:", r["cgroups"])
            daemon, child = r["env"]
            print("      env of the daemon:", json.dumps(daemon))
            diff = {k: child.get(k) for k in SEEN if child.get(k) != daemon.get(k)}
            print("      env of the child, where it differs:", json.dumps(diff) if diff else "the same")
        if r["spawn"]:
            print("      spawn:", json.dumps(r["spawn"]))
        for name, ch in (r["envcheck"] or {}).items():
            print("      from the service, %s: %s" % (name, json.dumps(ch)))
        for line in r["timeline"]:
            print("      " + line)


if __name__ == "__main__":
    if len(sys.argv) > 2 and sys.argv[1] in ("parent", "child"):
        d = Path(sys.argv[2])
        (role_parent if sys.argv[1] == "parent" else role_child)(d, json.loads((d / "case.json").read_text()))
    else:
        main()
