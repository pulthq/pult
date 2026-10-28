#!/usr/bin/env python3
"""Pult relay: the server's updater (stage U3). Puts on this server the release the computer runs — taken from
GitHub, never from the computer. Standard library only; runs under an account of its own (pult-update) that owns the
relay's code and nothing else, and can't read the relay's secret.

  relay ──want.json──► this (pult-relay-update.path starts it when the file changes) ──git──► github.com/pulthq/pult

The relay writes into want.json the release the computer says it runs: a tag and a commit, nothing else. Here:
  - only an official release goes in: the tag on github.com/pulthq/pult points at that very commit, and the commit is
    in main; and never an older one than what runs here — a computer someone took over could otherwise send the
    server back to a release with holes in it;
  - only that release's relay/ is fetched (a partial clone: commits and trees, then the relay's own files, ~0.5 MB),
    next to the release that runs; the relay's dependencies are installed when its requirements.txt changed;
  - `current` is switched to it and systemd restarts the relay (this writes `restart`: pult-relay-restart.path);
  - it counts once the relay has restarted, answers, and the computer is connected again; else `current` goes back.
The report — status.json — reaches the computer through the relay. Install it with deploy/relay/install.sh --auto.

  python3 -I update.py run          # pult-relay-update.service
"""
import fcntl
import hashlib
import http.client
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import time
import urllib.parse
from pathlib import Path

HOME = Path(os.environ.get("PULT_UPDATE_HOME", "/var/lib/pult-relay-update"))   # the updater's own folder
APP = Path(os.environ.get("PULT_UPDATE_APP", "/opt/pult-relay/app"))            # releases/ and `current`
VENV = Path(os.environ.get("PULT_UPDATE_VENV", "/opt/pult-relay/venv"))
WANT = Path(os.environ.get("PULT_UPDATE_WANT", "/var/lib/pult-relay/want.json"))
HEALTH = os.environ.get("PULT_UPDATE_HEALTH", "http://127.0.0.1:8097/pult/healthz")   # or unix:<socket path>
SERVICE = os.environ.get("PULT_UPDATE_SERVICE", "pult-relay.service")
# where releases come from; only root changes it, in the unit (the tests point it at a repository of their own)
REPO = os.environ.get("PULT_UPDATE_REPO", "https://github.com/pulthq/pult.git")
TAG_RE = re.compile(r"v\d{1,4}\.\d{1,4}\.\d{1,4}")
SHA_RE = re.compile(r"[0-9a-f]{40}")
NEED = ("relay/relay.py", "relay/requirements.txt", "relay/web/index.html")
# what install.sh puts in place and only install.sh replaces — the updater itself and the services — by where each lies
# in the repository: every report says which these are here, so the computer can tell a release that changed them
# needs `sudo bash deploy/relay/install.sh` once (review 2026-10-27, У5)
UNITS = Path(os.environ.get("PULT_UPDATE_UNITS", "/etc/systemd/system"))
OWN = {"deploy/relay/update.py": Path(__file__).resolve(),
       "deploy/relay/pult-relay.service": UNITS / "pult-relay.service",
       "deploy/relay/pult-relay-update.service": UNITS / "pult-relay-update.service",
       "deploy/relay/pult-relay-update.path": UNITS / "pult-relay-update.path",
       "deploy/relay/pult-relay-restart.service": UNITS / "pult-relay-restart.service",
       "deploy/relay/pult-relay-restart.path": UNITS / "pult-relay-restart.path",
       "deploy/relay/pult-relay-update.conf": UNITS / "pult-relay.service.d" / "update.conf"}
MAC_WAIT = 60        # s for the computer to be connected before the switch: a check needs it
UP_WAIT = 90          # s for the restarted relay to answer with the computer connected again
ROUNDS = 3            # want.json changed while this ran: look again, at most this many times
LOCK_WAIT = 900       # s this run waits for the lock — another run, or install.sh (flock -w 900 there too)
# failures that belong to the release itself: it isn't tried again until the computer names another one, or the owner
# asks for it again (the relay stamps that word with this server's clock: "retry" in want.json)
FINAL = ("not_official", "broken", "no_restart", "no_start", "no_mac")
# the computer didn't come back after the switch: it may only have been asleep or off the network for that minute and a
# half, so the release is tried again on the computer's next word (~10 min later), this many times in all (0.18.5;
# before, once was final, and a server stayed behind its computer until the next release)
NO_MAC_TRIES = 3


class Fail(Exception):
    """why (a short code the computer has words for), detail (a line for the log and the app)."""


def say(*a):
    print(time.strftime("%Y-%m-%d %H:%M:%S"), *a, flush=True)


def vnum(tag):
    m = TAG_RE.fullmatch(tag or "")
    return tuple(int(x) for x in tag[1:].split(".")) if m else (0, 0, 0)


def read(path, default=None):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def write(path, data):
    path = Path(path)
    tmp = path.with_name("." + path.name + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    os.chmod(tmp, 0o644)
    os.replace(tmp, path)


class UnixHTTP(http.client.HTTPConnection):
    def __init__(self, path, timeout=5):
        super().__init__("relay", timeout=timeout)
        self.path = path

    def connect(self):
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(self.timeout)
        self.sock.connect(self.path)


def own_files():
    """{path in the repository: the git blob id of the file here, None — missing} for OWN."""
    out = {}
    for rel, path in OWN.items():
        try:
            data = path.read_bytes()
        except OSError:
            out[rel] = None
            continue
        out[rel] = hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()
    return out


class Updater:
    """One look at want.json. systemd, the relay's health and the clock are methods, so the tests stand in for them."""

    def __init__(self):
        self.cache = HOME / "cache.git"

    # ----- the relay and systemd -----

    def health(self):
        """The relay's /pult/healthz → {"ok", "mac"}, or None when it doesn't answer."""
        try:
            if HEALTH.startswith("unix:"):
                c = UnixHTTP(HEALTH[5:])
                c.request("GET", "/pult/healthz", headers={"Host": "relay"})
            else:
                u = urllib.parse.urlsplit(HEALTH)
                c = http.client.HTTPConnection(u.hostname, u.port or 80, timeout=5)
                c.request("GET", u.path or "/pult/healthz")
            r = c.getresponse()
            body = r.read()
            c.close()
            return json.loads(body) if r.status == 200 else None
        except (OSError, ValueError, http.client.HTTPException):
            return None

    def service(self):
        """The relay's service: {"pid", "state", "restarts" (by systemd since the last restart asked for)} — `systemctl
        show` needs no rights."""
        props = ("MainPID", "ActiveState", "NRestarts")
        try:
            out = subprocess.run(["systemctl", "show", *("-p" + k for k in props), SERVICE],
                                 capture_output=True, text=True, timeout=10).stdout
        except (OSError, subprocess.SubprocessError):
            return {}
        kv = dict(ln.split("=", 1) for ln in out.splitlines() if "=" in ln)
        num = lambda k: int(kv[k]) if (kv.get(k) or "").isdigit() else 0
        return {"pid": num("MainPID"), "state": kv.get("ActiveState", ""), "restarts": num("NRestarts")}

    def restart(self):
        """systemd restarts the relay when this file changes (pult-relay-restart.path): this account has no other way."""
        write(HOME / "restart", {"ts": time.time()})

    def sleep(self, s):
        time.sleep(s)

    def now(self):
        return time.time()

    # ----- git -----

    def git(self, *args, timeout=60, raw=False):
        # GIT_NO_LAZY_FETCH: a missing file is fetched only when asked for by name (git before 2.44 ignores it and
        # fetches it on the spot, one by one — slower, the same result)
        env = dict(os.environ, GIT_TERMINAL_PROMPT="0", GIT_NO_LAZY_FETCH="1", LC_ALL="C", HOME=str(HOME))
        try:
            p = subprocess.run(["git", "--git-dir", str(self.cache), *args], capture_output=True, timeout=timeout,
                               env=env, stdin=subprocess.DEVNULL)
        except subprocess.TimeoutExpired:
            raise Fail("network", "git %s: no answer in %d s" % (args[0], timeout))
        except OSError as e:
            raise Fail("no_git", repr(e)[:300])
        if p.returncode:
            raise Fail("git", (p.stderr.decode("utf-8", "replace").strip().splitlines() or ["?"])[-1][:300])
        return p.stdout if raw else p.stdout.decode("utf-8", "replace").strip()

    def net(self, *args, timeout=180):
        """A git command that goes to GitHub: any failure of it is the network's (tried again later)."""
        try:
            return self.git(*args, timeout=timeout)
        except Fail as e:
            raise Fail("network", e.args[1] if len(e.args) > 1 else None)

    def fetch(self, tag, commit):
        """The release's commit and main's history (no file contents yet) from GitHub; checks that it is official."""
        if not (self.cache / "HEAD").exists():
            self.git("init", "-q", "--bare")
            for k, v in (("remote.origin.url", REPO), ("remote.origin.promisor", "true"),
                         ("remote.origin.partialclonefilter", "blob:none")):
                self.git("config", k, v)
        self.git("config", "remote.origin.url", REPO)            # the unit's word, should root have changed it
        if not self.net("ls-remote", "origin", "refs/tags/" + tag, timeout=60):
            raise Fail("not_official", "%s is not a release of %s" % (tag, REPO))
        self.net("fetch", "-q", "--no-tags", "--filter=blob:none", "origin",
                 "+refs/heads/main:refs/remotes/origin/main", "+refs/tags/%s:refs/tags/%s" % (tag, tag))
        got = self.git("rev-parse", "refs/tags/%s^{commit}" % tag)
        if got != commit:
            raise Fail("not_official", "%s is %s on GitHub, not %s" % (tag, got[:7], commit[:7]))
        try:
            self.git("merge-base", "--is-ancestor", commit, "refs/remotes/origin/main")
        except Fail:
            raise Fail("not_official", "%s is not in main" % commit[:7])

    def place(self, tag, commit):
        """The release's relay/ → releases/<tag>-<commit>, file by file from git (blobs fetched by id: `git archive`
        would fetch the whole tree). → its folder."""
        rows = []
        for ln in self.git("ls-tree", "-r", "--full-tree", commit, "--", "relay").splitlines():
            meta, _, path = ln.partition("\t")
            mode, kind, oid = meta.split()
            if kind != "blob" or mode not in ("100644", "100755"):
                raise Fail("broken", "%s: %s %s" % (path, kind, mode))      # no links or submodules in a relay
            rel = path[len("relay/"):]
            parts = Path(rel).parts
            if not rel or rel.startswith("/") or ".." in parts or "__pycache__" in parts:
                raise Fail("broken", path)
            rows.append((oid, path, rel))
        if not all(any(p == need for _, p, _ in rows) for need in NEED):
            raise Fail("broken", "no " + ", ".join(n for n in NEED if not any(p == n for _, p, _ in rows)))
        missing = []
        for oid, _, _ in rows:
            try:
                self.git("cat-file", "-e", oid)
            except Fail:
                missing.append(oid)
        if missing:
            self.net("fetch", "-q", "--no-tags", "--filter=blob:none", "origin", *missing)
        name = "%s-%s" % (tag, commit[:7])
        dest, tmp = APP / "releases" / name, APP / "releases" / (name + ".new")
        shutil.rmtree(tmp, ignore_errors=True)
        tmp.mkdir(parents=True)
        for oid, _, rel in rows:
            f = tmp / rel
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_bytes(self.git("cat-file", "blob", oid, raw=True))
            os.chmod(f, 0o644)
        shutil.rmtree(dest, ignore_errors=True)
        os.rename(tmp, dest)
        return dest

    # ----- releases -----

    def current(self):
        """The release folder `current` points at, or None."""
        cur = APP / "current"
        return cur.resolve() if cur.is_symlink() else None

    def switch(self, dest):
        tmp = APP / ".current.new"
        if tmp.is_symlink() or tmp.exists():
            tmp.unlink()
        os.symlink(os.path.relpath(Path(dest).resolve(), APP.resolve()), tmp)     # relative: the folder may move
        os.replace(tmp, APP / "current")

    def pip(self, new, old):
        """The relay's dependencies, when this release asks for others than the one running (rare: 0.8.0 was the last)."""
        req = new / "requirements.txt"
        if old is not None and (old / "requirements.txt").is_file() and (old / "requirements.txt").read_bytes() == req.read_bytes():
            return
        p = subprocess.run([str(VENV / "bin" / "pip"), "install", "-q", "--disable-pip-version-check", "--no-cache-dir",
                            "--require-hashes", "-r", str(req)], capture_output=True, text=True, timeout=600,
                           env=dict(os.environ, HOME=str(HOME), PIP_NO_INPUT="1"))
        if p.returncode:
            raise Fail("pip", (p.stderr.strip().splitlines() or ["?"])[-1][:300])

    def came_up(self, pid0):
        """(True, None, None) once the relay runs under a new process, answers and has the computer back; else
        (False, why, detail). A relay that keeps exiting at start — at once: systemd restarts it again and again. Its
        count of restarts starts anew with the restart asked for; until that is seen, an old count (of the release
        that failed, while going back) means nothing."""
        end, why, fresh = self.now() + UP_WAIT, "no_restart", False
        while self.now() < end:
            s = self.service()
            pid, state, n = s.get("pid", 0), s.get("state", ""), s.get("restarts", 0)
            fresh = fresh or n < 2
            if fresh and n >= 2:
                return False, "no_start", "the relay exits at start: systemd restarted it %d times" % n
            if pid and pid != pid0 and state == "active":
                h = self.health()
                if h and h.get("ok"):
                    if h.get("mac"):
                        return True, None, None
                    why = "no_mac"
                else:
                    why = "no_start"
            elif pid != pid0 or state not in ("active", ""):
                why = "no_start"
            self.sleep(1)
        return False, why, None

    def mac_here(self):
        """The computer is connected now (waits up to MAC_WAIT): only then can the switch be checked."""
        end = self.now() + MAC_WAIT
        while True:
            h = self.health()
            if h and h.get("mac"):
                return True
            if self.now() >= end:
                return False
            self.sleep(2)

    def prune(self, keep):
        """Only the release that runs and the one before it stay (the way back)."""
        keep = {Path(k).resolve() for k in keep if k}
        for d in (APP / "releases").iterdir():
            if d.is_dir() and not d.is_symlink() and d.resolve() not in keep:
                shutil.rmtree(d, ignore_errors=True)

    # ----- one look -----

    def status(self, **st):
        st["ts"] = int(self.now())
        st["self"] = own_files()
        write(HOME / "status.json", st)
        say("status:", json.dumps(st, ensure_ascii=False))

    def once(self):
        """→ the want it acted on (to see whether want.json changed meanwhile)."""
        w = read(WANT, {}) or {}
        tag, commit = w.get("tag"), w.get("commit")
        have = read(HOME / "installed.json", {}) or {}
        last = read(HOME / "status.json", {}) or {}
        if not (isinstance(tag, str) and isinstance(commit, str) and TAG_RE.fullmatch(tag) and SHA_RE.fullmatch(commit)):
            return w
        if commit == have.get("commit"):
            if last.get("tag") != tag or last.get("state") not in ("done", "idle"):
                self.status(state="idle", have=have.get("tag"))
            return w
        if vnum(tag) < vnum(have.get("tag")) or vnum(tag) == vnum(have.get("tag")) and have.get("official"):
            # an older release, or the same one again from elsewhere: what runs here stays
            if last.get("tag") != tag or last.get("state") != "refused":
                self.status(state="refused", tag=tag, commit=commit, have=have.get("tag"), why="older")
            return w
        failed, key = read(HOME / "failed.json", {}) or {}, "%s %s" % (tag, commit)
        rec = failed.get(key)
        if isinstance(rec, str):                       # before 0.18.5: the reason alone, always final
            rec = {"why": rec, "n": NO_MAC_TRIES, "ts": 0, "final": True}
        retry = w.get("retry")
        if rec and isinstance(retry, (int, float)) and not isinstance(retry, bool) and retry > (rec.get("ts") or 0):
            say("asked to try %s again" % tag)         # the owner's word, newer than the failure: the count starts anew
            failed.pop(key, None)
            write(HOME / "failed.json", failed)
            rec = None
        if rec and rec.get("final"):
            return w                                   # this release didn't come up here: the report says so already
        old = have.get("tag")
        base = dict(tag=tag, commit=commit, have=old)
        say("the computer runs %s (%s); here %s" % (tag, commit[:7], old))
        prev, switched, why, detail = self.current(), False, None, None
        try:
            self.status(state="run", step="fetch", **base)
            self.fetch(tag, commit)
            dest = self.place(tag, commit)
            self.status(state="run", step="pip", **base)
            self.pip(dest, prev)
            if not self.mac_here():
                raise Fail("no_mac_before", "the computer isn't connected — later")
            self.status(state="run", step="switch", **base)
            pid0 = self.service().get("pid", 0)
            self.switch(dest)
            switched = True
            self.restart()
            self.status(state="run", step="check", **base)
            ok, why, detail = self.came_up(pid0)
        except Fail as e:
            ok, why, detail = False, e.args[0], e.args[1] if len(e.args) > 1 else None
        except Exception as e:                      # a bug of this updater: what runs stays, the report says what
            ok, why, detail = False, "error", repr(e)[:300]
        if ok:
            write(HOME / "installed.json", {"tag": tag, "commit": commit, "official": True, "ts": int(self.now())})
            self.prune([dest, prev])
            self.status(state="done", tag=tag, commit=commit, have=tag, **{"from": old})
            return w
        say("%s not installed: %s %s" % (tag, why, detail or ""))
        if why in FINAL:
            n = ((rec or {}).get("n") or 0) + 1
            final = why != "no_mac" or n >= NO_MAC_TRIES
            failed[key] = {"why": why, "n": n, "ts": int(self.now()), "final": final}
            write(HOME / "failed.json", failed)
            if not final:
                why = "no_mac_retry"                   # tried again on the computer's next word
        if not switched:
            self.status(state="refused" if why == "not_official" else "fail", why=why, detail=detail, back=False, **base)
            return w
        back_ok = False
        if prev is not None:
            say("back to", prev.name)
            self.status(state="run", step="back", **base)
            try:
                pid1 = self.service().get("pid", 0)
                self.switch(prev)
                self.restart()
                back_ok = self.came_up(pid1)[0]
            except Exception as e:
                say("couldn't go back:", repr(e))
        self.status(state="fail", why=why, detail=detail, back=prev is not None, back_ok=back_ok, **base)
        return w

    def run(self):
        HOME.mkdir(parents=True, exist_ok=True)
        with open(HOME / "lock", "w") as lock:
            # one at a time, and this one waits its turn: install.sh holds the lock to its end, and a want.json the relay
            # it had just restarted wrote meanwhile went unread when this run left at once (a live server, 2026-10-28)
            end = self.now() + LOCK_WAIT
            while True:
                try:
                    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except OSError:
                    if self.now() >= end:
                        say("the lock stayed taken for %d min — want.json is looked at when it changes" % (LOCK_WAIT // 60))
                        return 0
                    self.sleep(1)
            seen = None
            for _ in range(ROUNDS):
                now = read(WANT, {}) or {}
                if now == seen:
                    break
                seen = self.once()
        return 0


def main(argv):
    if argv[1:] == ["run"]:
        return Updater().run()
    print(__doc__.strip().splitlines()[-1].strip(), file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
