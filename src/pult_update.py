"""Updating Pult from its own folder (stage U): what the folder has that isn't installed yet, and the installer the
app's "Install" button starts. Standard library only.

The source is the git checkout install.sh ran from; every install writes it down in installed.json. Only what is
committed goes in, so a session halfway through its work can't ship a half-made change. And only a commit that
changed a file the installer copies counts: one with the journal or the docs doesn't light the button. What goes in
is everything in src/ plus requirements.txt, taken from the commit itself, so a module added in a later version
isn't left behind by an older copy of this file.

The installer is a process of its own (macOS: a new session; Linux: a transient systemd unit), because it stops the
very service that started it: a plain child dies with it and leaves Pult stopped (tests/probe_update.py). It keeps
the installed files in prev/, puts the commit's files in, restarts the service through `pultctl install`, and counts
the update in only once the new daemon has stayed up and reached the app's server (health.json). Otherwise it puts
prev/ back. Every install — from the app or from install.sh — goes into installs.json.

  python pult_update.py run <commit> <how>        # the daemon starts it; how: app | app_wait
"""
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
from pathlib import Path

import pult_os

HOME = Path(os.environ.get("PULT_HOME") or "~/.local/share/pult").expanduser()
LOG = (Path(os.environ["PULT_LOG"]).expanduser().parent if os.environ.get("PULT_LOG") else pult_os.LOG_DIR) / "pult-update.log"
MANIFEST, HISTORY, STATUS, HEALTH, PREV = "installed.json", "installs.json", "update.json", "health.json", "prev"
TREE = ("src", "requirements.txt")    # what the installer copies, as paths in the repository
EXEC = ("pult_tab.py", "pult-tab.sh")
KEEP = 20                             # installs kept in the history
STABLE = 15                           # s the new daemon has to stay up, with the app's server reached
HEALTH_WAIT = 90                      # s for that before the old version goes back
RUN_STALE = 15 * 60                   # s; "installing" older than this, with its process gone, was cut short
NEWS = 8


class Fail(Exception):
    pass


# ---------- small files in Pult's folder ----------

def read(name, default=None):
    try:
        return json.loads((HOME / name).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def write(name, data):
    p = HOME / name
    tmp = p.with_name(p.name + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, p)


def history():
    """Installs, the latest first: [{"ts", "from", "to", "how", "ok", "commit", "why"}]."""
    h = read(HISTORY, [])
    return h if isinstance(h, list) else []


def record(**entry):
    write(HISTORY, ([dict(entry, ts=entry.get("ts") or time.time())] + history())[:KEEP])


def version_of(text):
    m = re.search(r'^VERSION = "([^"]+)"', text or "", re.M)
    return m.group(1) if m else None


def installed_version():
    try:
        return version_of((HOME / "pultd.py").read_text(encoding="utf-8"))
    except OSError:
        return None


# ---------- the repository ----------

def git(repo, *args, timeout=15, raw=False):
    """Output of a read-only git command in repo, or None. No locks taken: sessions may be committing next door."""
    env = dict(os.environ, GIT_OPTIONAL_LOCKS="0", GIT_TERMINAL_PROMPT="0", LC_ALL="C")
    try:
        p = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, timeout=timeout, env=env,
                           stdin=subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError):
        return None
    if p.returncode:
        return None
    return p.stdout if raw else p.stdout.decode("utf-8", "replace").strip()


def blob(path):
    """The git blob id of a file — what `git ls-tree` gives for the same bytes; None if it isn't there."""
    try:
        data = Path(path).read_bytes()
    except OSError:
        return None
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


def tree(repo, commit):
    """{file name in Pult's folder: blob id} of what the installer would copy from this commit."""
    out = git(repo, "ls-tree", "-r", commit, "--", *TREE)
    if out is None:
        return None
    files = {}
    for ln in out.splitlines():
        meta, _, path = ln.partition("\t")
        parts = meta.split()
        if len(parts) == 3 and parts[1] == "blob" and (path == "requirements.txt" or path.count("/") == 1):
            files[Path(path).name] = parts[2]
    return files


def source(src):
    """What install.sh installs from src: {"src", "commit", "dirty"}; commit None outside git."""
    head = git(src, "rev-parse", "HEAD")
    if not head:
        return {"src": str(src), "commit": None, "dirty": False}
    return {"src": str(src), "commit": head, "dirty": bool(git(src, "status", "--porcelain", "--", *TREE))}


def check(manifest=None):
    """What the source folder has for Pult's folder: {"repo"} alone — no way to tell (no record of the source, or it
    isn't a git checkout); else also "head", "short", "ready" (a commit with other files than installed), and when
    ready: "version", "news" (subjects of the commits that changed them), "failed" (this commit didn't come up)."""
    m = read(MANIFEST, {}) if manifest is None else manifest
    src = m.get("src")
    if not src or not Path(src).is_dir():
        return {"repo": None}
    head = git(src, "rev-parse", "HEAD")
    if not head:
        return {"repo": None, "src": src}
    out = {"repo": src, "head": head, "short": head[:7], "ready": False}
    if head == m.get("commit"):
        return out              # nothing committed since (an install from uncommitted files is newer, not older)
    want = tree(src, head)
    if not want or all(blob(HOME / name) == b for name, b in want.items()):
        return out
    base = m.get("commit")
    if base and git(src, "merge-base", "--is-ancestor", base, head) is not None:
        log_ = git(src, "log", "--format=%s", "-n", str(NEWS), base + ".." + head, "--", *TREE)
    else:
        log_ = git(src, "log", "--format=%s", "-n", "3", head, "--", *TREE)
    st = read(STATUS, {}) or {}
    out.update(ready=True, version=version_of(git(src, "show", head + ":src/pultd.py")) or head[:7],
               news=[s for s in (log_ or "").splitlines() if s][:NEWS],
               failed=st.get("state") == "fail" and st.get("commit") == head)
    return out


def installed_by(how, src, ok, prev_version=None):
    """install.sh (or the installer) put src's files in: the record of where they came from, and the history."""
    m = dict(source(src), version=installed_version(), ts=time.time())
    write(MANIFEST, m)
    record(**{"from": prev_version, "to": m["version"], "how": how, "ok": bool(ok), "commit": m["commit"]})
    st = read(STATUS, {}) or {}
    if st.get("state") == "fail" and ok:
        write(STATUS, {"state": "done", "ts": time.time()})          # put in by hand after a failed one


# ---------- starting the installer (the daemon) ----------

SETENV = ("PULT_HOME", "PULT_ENV", "PULT_SOCK", "PULT_LOG", "PULT_LABEL", "PULT_LANG", "PULT_PROXY", "HOME", "PATH",
          "LANG", "LC_ALL")


def spawn(commit, how, python=None):
    """Starts the installer outside the daemon's service → True; False where it can't (Windows: not yet)."""
    if pult_os.KIND == "windows":
        return False
    py = str(python or sys.executable)
    argv = [py, "-u", str(HOME / "pult_update.py"), "run", commit, how]
    if pult_os.KIND == "linux":
        # stopping a systemd unit ends its whole cgroup, a new session included: the installer gets a unit of its own,
        # and the environment the service had (a transient unit doesn't inherit it)
        sets = ["--setenv=%s=%s" % (k, os.environ[k]) for k in SETENV if os.environ.get(k)]
        argv = ["systemd-run", "--user", "--collect", "--quiet", "--unit", "pult-update-%d" % time.time(),
                *sets, *argv]
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with open(LOG, "ab") as out:          # what fails before the installer opens its log (systemd-run's own words)
        p = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=out, stderr=subprocess.STDOUT, cwd=str(HOME),
                             start_new_session=True, close_fds=True)
    if pult_os.KIND == "linux":
        try:
            return p.wait(timeout=20) == 0          # systemd-run returns once the unit has started
        except subprocess.TimeoutExpired:
            return True
    return True


def alive(pid):
    try:
        os.kill(int(pid), 0)
        return True
    except (OSError, ValueError, TypeError):
        return False


def running():
    """The installer's status while it works, or None: "installing" whose process is gone for long was cut short."""
    st = read(STATUS, {}) or {}
    if st.get("state") != "run":
        return None
    if time.time() - (st.get("ts") or 0) > RUN_STALE and not alive(st.get("pid")):
        return None
    return st


# ---------- the installer ----------

def say(*a):
    print(time.strftime("%Y-%m-%d %H:%M:%S"), *a, flush=True)


class Installer:
    """One update: commit → Pult's folder, with the way back. The service and the checks are methods, so the tests
    can stand in for them."""

    def __init__(self, commit, how):
        import pult_setup                    # here, not on top: the daemon imports this module too
        self.S = pult_setup
        self.commit, self.how = commit, how
        self.lbl = pult_setup.label()
        self.st = {"state": "run", "step": "prepare", "commit": commit, "how": how, "from": installed_version(),
                   "to": None, "ts": time.time(), "pid": os.getpid()}

    def step(self, name):
        self.st["step"] = name
        write(STATUS, self.st)
        say("step:", name)

    # the service and its daemon
    def busy(self):
        return self.S.busy_sessions(self.lbl)

    def stop(self):
        return self.S.svc_stop(self.lbl)

    def install(self):
        """The installed pultctl writes the service file and the command and starts the service, as install.sh does."""
        env = dict(os.environ, PULT_FORCE="1", PULT_UPDATER=self.how)
        p = subprocess.run([str(self.S.PY), str(HOME / "pultctl.py"), "install"], env=env, stdin=subprocess.DEVNULL,
                           capture_output=True, text=True, timeout=180)
        for ln in (p.stdout + p.stderr).splitlines():
            say("  pultctl:", ln)
        return p.returncode == 0

    def pip(self):
        p = subprocess.run([str(self.S.PY), "-m", "pip", "install", "-q", "--disable-pip-version-check", "-r",
                            str(HOME / "requirements.txt")], capture_output=True, text=True, timeout=600)
        if p.returncode:
            raise Fail("pip", (p.stderr.strip().splitlines() or ["?"])[-1][:300])

    def healthy(self, t0, wait=HEALTH_WAIT):
        """(True, None) once a daemon started after t0 has stayed up STABLE s and reached the app's server (when it
        has one); (False, why) when it doesn't in `wait` s, or keeps restarting."""
        end, pid0, restarts, h = time.time() + wait, None, 0, {}
        while time.time() < end:
            pid = self.S.service(self.lbl)[1]
            if pid and pid0 and pid != pid0:
                restarts += 1
                if restarts >= 2:
                    return False, "restarts"
            pid0 = pid or pid0
            h = read(HEALTH, {}) or {}
            if pid and str(h.get("pid")) == str(pid) and (h.get("started") or 0) >= t0 - 1 \
                    and time.time() - h["started"] >= STABLE and h.get("relay") is not False:
                return True, None
            time.sleep(1)
        if not pid0:
            return False, "no_start"
        if str(h.get("pid")) == str(pid0) and h.get("relay") is False:
            return False, "no_relay"
        return False, "no_start"

    def error_line(self, t0):
        """The last exception the service's log has since t0 — the reason a new version didn't come up."""
        try:
            with open(self.S.LOG, "rb") as f:
                f.seek(0, 2)
                f.seek(max(0, f.tell() - 64000))
                lines = f.read().decode(errors="replace").splitlines()
        except OSError:
            return None
        found = None
        for ln in lines:
            if re.match(r"^[A-Za-z_][\w.]*(Error|Exception|Exit)\b", ln):
                found = ln.strip()
        return found[:300] if found else None

    # files
    def snapshot(self, into):
        """The commit's src/ and requirements.txt → {file name: path}, from git itself (not the working tree)."""
        src = (read(MANIFEST, {}) or {}).get("src")
        if not src:
            raise Fail("no_source")
        data = git(src, "archive", "--format=tar", self.commit, "--", *TREE, raw=True, timeout=60)
        if not data:
            raise Fail("no_commit")
        with tarfile.open(fileobj=io.BytesIO(data)) as tar:
            for m in tar.getmembers():
                if not (m.isfile() and (m.name == "requirements.txt" or (m.name.startswith("src/") and m.name.count("/") == 1))):
                    continue
                with tar.extractfile(m) as f, open(into / Path(m.name).name, "wb") as out:
                    shutil.copyfileobj(f, out)
        files = {p.name: p for p in into.iterdir()}
        if "pultd.py" not in files or "pult_update.py" not in files:
            raise Fail("no_commit")
        return files

    def keep(self, names):
        """The installed copies of these files (and of the ones they'd replace) → prev/."""
        prev = HOME / PREV
        shutil.rmtree(prev, ignore_errors=True)
        prev.mkdir()
        for name in names:
            if (HOME / name).is_file():
                shutil.copy2(HOME / name, prev / name)

    def put(self, files):
        for name, p in files.items():
            shutil.copyfile(p, HOME / name)
            if name in EXEC:
                os.chmod(HOME / name, 0o755)

    def restore(self, added):
        prev = HOME / PREV
        for p in prev.iterdir():
            shutil.copy2(p, HOME / p.name)
        for name in added:
            (HOME / name).unlink(missing_ok=True)

    def run(self):
        write(STATUS, self.st)
        say("update to", self.commit[:7], "(%s), from" % self.how, self.st["from"])
        tmp = Path(tempfile.mkdtemp(prefix="pult-update-"))
        changed = False
        try:
            files = self.snapshot(tmp)
            self.st["to"] = version_of((tmp / "pultd.py").read_text(encoding="utf-8")) or self.commit[:7]
            if self.busy():
                say("something started meanwhile — nothing changed")
                write(STATUS, {"state": "idle", "why": "busy", "ts": time.time()})
                return 3
            reqs = blob(tmp / "requirements.txt") != blob(HOME / "requirements.txt")
            had = {p.name for p in HOME.iterdir() if p.is_file()}
            added = [n for n in files if n not in had]
            self.keep([n for n in files if n in had])
            t0 = time.time()
            self.step("stop")
            self.stop()
            changed = True
            self.step("copy")
            self.put(files)
            if reqs:
                self.pip()
            self.step("start")
            self.install()
            self.step("check")
            ok, why = self.healthy(t0)
            if ok:
                m = (read(MANIFEST, {}) or {})
                write(MANIFEST, {"src": m.get("src"), "commit": self.commit, "dirty": False, "version": self.st["to"],
                                 "ts": time.time()})
                record(**{"from": self.st["from"], "to": self.st["to"], "how": self.how, "ok": True, "commit": self.commit})
                write(STATUS, {"state": "done", "commit": self.commit, "from": self.st["from"], "to": self.st["to"],
                               "ts": time.time()})
                say("done:", self.st["to"], "is up")
                return 0
            detail = self.error_line(t0)
            say("the new version didn't come up:", why, detail or "")
            self.back(added, reqs, why, detail)
            return 1
        except Exception as e:
            why = e.args[0] if isinstance(e, Fail) and e.args else "error"
            detail = (e.args[1] if len(e.args) > 1 else None) if isinstance(e, Fail) else repr(e)[:300]
            say("failed:", why, detail or "")
            if changed:
                self.back(added, reqs, why, detail)
            else:
                write(STATUS, dict(self.st, state="fail", why=why, detail=detail, back=False, reported=False,
                                   ts=time.time()))
                record(**{"from": self.st["from"], "to": self.st["to"], "how": self.how, "ok": False,
                          "commit": self.commit, "why": why})
            return 1
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def back(self, added, reqs, why, detail):
        """The old version back in place, started and checked; the history and the status say why."""
        self.step("back")
        t0 = time.time()
        try:
            self.stop()
            self.restore(added)
            if reqs:
                self.pip()
            self.install()
            ok, _ = self.healthy(t0)
        except Exception as e:
            say("rollback:", repr(e))
            ok = False
        record(**{"from": self.st["from"], "to": self.st["to"], "how": self.how, "ok": False, "commit": self.commit,
                  "why": why})
        write(STATUS, dict(self.st, state="fail", why=why, detail=detail, back=True, back_ok=ok, reported=False,
                           ts=time.time()))
        say("old version back:", "up" if ok else "NOT up")
        if not ok:
            self.alarm()

    def alarm(self):
        """Neither version is up — no daemon to tell the owner, so the installer writes to Telegram itself."""
        env = self.S.read_env()
        token, owner = env.get("PULT_BOT_TOKEN"), (env.get("PULT_ALLOWED_USER_IDS") or "").split(",")[0].strip()
        if not token or not owner:
            return
        text = self.S.I.T("upd.dead", lang=self.S.cli_lang(), to=self.st["to"], back=self.st["from"])
        try:
            self.S.bot_call(token, "sendMessage", proxy=env.get("PULT_PROXY") or None, chat_id=int(owner), text=text)
        except Exception as e:
            say("couldn't tell the owner:", repr(e))


def main(argv):
    if len(argv) == 4 and argv[1] == "run":
        # its own log on every system: under systemd-run the output would go to the journal
        LOG.parent.mkdir(parents=True, exist_ok=True)
        sys.stdout = sys.stderr = open(LOG, "a", encoding="utf-8", buffering=1)
        return Installer(argv[2], argv[3]).run()
    print(__doc__.strip().splitlines()[-1].strip(), file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
