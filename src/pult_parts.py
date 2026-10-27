"""Pult's parts and its updates — what the Settings screen "Pult and its parts" shows and does, and what keeps Pult
current: an update installed from the app (stage U), the relay's server following this computer and the releases on
GitHub (U3), every part against what is installed (U2), and the check of a Claude Code version VS Code has downloaded,
before a window reloads onto it (stage A); out of pultd.py unchanged (review 2026-10-27, 6.2).

Parts is a mixin, like pult_api's Api: the daemon is `class Pult(Api, Parts)`, these stay its methods, and each side
calls the other through self. This module never imports pultd — the daemon runs as __main__, and `import pultd` would
load a second copy of it; the daemon's own names, the ones it reads as well, come late through the daemon itself
(self.D, the module that defines Pult). What only the parts read lives here, and a test changes it here (EXT_DIRS, the
clock of release_look).
"""
import asyncio
import functools
import json
import os
import re
import sys
import time
from pathlib import Path

import pult_hook
import pult_os
import pult_render as R
import pult_update as U

EXT_DIRS = pult_os.extension_dirs()
TAB_CHECK_EVERY = 600    # s; whether VS Code has downloaded a Claude Code version tab.json doesn't list (stage A)
TAB_RETRY = 3600         # s; a check that couldn't run (no login, a limit, the network) is tried again after this
TAB_CHECK_LIMIT = 360    # s for the check's process (it gives itself pult_tabcheck.TOTAL and cleans up)
ANNOUNCE_EVERY = 600     # s; the relay's server is reminded of the release this computer runs while it runs another (U3)
# the server's updater failed for a reason of the moment: it tries again on the next reminder, nobody is told
SRV_TRANSIENT = ("network", "pip", "no_mac_before", "git", "no_git", "no_mac_retry")
SRV_KEYS = ("state", "tag", "commit", "have", "from", "step", "why", "detail", "back", "back_ok", "ts")   # relay.STATUS_KEYS


def log(*a):
    print(time.strftime("%Y-%m-%d %H:%M:%S"), *a, flush=True)      # as pultd.log: the daemon's journal, the same form


def srv_status(upd):
    """The server updater's report as the relay passes it, in the shapes it has (relay.updater_status): its known fields,
    strings cut short, flags and the time; anything else — None. The relay is a server Pult doesn't control."""
    if not isinstance(upd, dict):
        return None
    out = {}
    own = upd.get("self")                 # the updater's own files (0.18.6) — without them, an older updater
    if isinstance(own, dict):
        out["self"] = {k: v for k, v in list(own.items())[:12] if isinstance(k, str) and len(k) <= 80
                       and (v is None or isinstance(v, str) and re.fullmatch(r"[0-9a-f]{40}", v))}
    for k in SRV_KEYS:
        v = upd.get(k)
        if isinstance(v, bool) and k in ("back", "back_ok"):
            out[k] = v
        elif k == "ts" and isinstance(v, (int, float)) and not isinstance(v, bool):
            out[k] = v
        elif isinstance(v, str) and k not in ("back", "back_ok", "ts"):
            out[k] = v[:300]
    return out


def vnum(v):
    """"2.1.310" → (2, 1, 310), for sorting versions; anything else sorts first."""
    try:
        return tuple(int(x) for x in str(v).split("."))
    except ValueError:
        return ()


class Parts:
    """Parts and updates — a mixin of pultd.Pult: self is the daemon, self.D its module."""

    # ----- updating Pult from its folder (stage U) -----

    @property
    def upd_wait(self):
        """The owner asked to install once Pult's sessions are free: since when. Kept in the store — in memory a restart
        for another reason forgot the request, and the app dropped it without a word (review 2026-10-27, У11)."""
        return self.store.get("upd_wait")

    @upd_wait.setter
    def upd_wait(self, ts):
        self.store.put("upd_wait", ts)

    def note_health(self, **kw):
        """health.json: this daemon is up, and whether it has reached Telegram and the app's server. The installer
        counts an update in only once the new daemon has said so (pult_update.Installer.healthy)."""
        self.health.update(kw)
        try:
            U.write(U.HEALTH, dict(self.health, pid=os.getpid(), version=self.D.VERSION, started=self.t_start))
        except OSError as e:
            log("health.json:", e)

    async def update_check(self, age=60):
        """What the source folder has (pult_update.check), at most `age` s old: it takes a few short git commands, and
        the app asks again on every change it hears of."""
        t, v = self._upd
        if v is None or time.monotonic() - t >= age:
            v = await asyncio.to_thread(U.check)
            self._upd = (time.monotonic(), v)
        return v

    async def update_view(self, age=60):
        """The app's "Pult" block. state: ok — nothing newer; ready — a commit to install; busy — one, but a restart
        would cut Pult's own sessions off (busy_report); wait — the owner asked to install once they are free; run —
        installing; fail — this commit didn't come up (the old version is back); na — no way here (no git source,
        Windows). The history goes with every state."""
        hist = [{k: h.get(k) for k in ("ts", "from", "to", "how", "ok", "why")} for h in U.history()[:10]]
        v = {"have": self.D.VERSION, "hist": hist, "state": "ok"}
        run = U.running()
        if run:
            return dict(v, state="run", next=run.get("to"), step=run.get("step"))
        if pult_os.KIND == "windows":
            return dict(v, state="na", why="windows")          # not yet (Q53): install.ps1
        c = await self.update_check(age)
        if not c.get("repo"):
            return dict(v, state="na", why="norepo")
        home = str(Path.home())
        v.update(dir="~" + c["repo"][len(home):] if c["repo"].startswith(home + os.sep) else c["repo"], commit=c.get("short"))
        if not c.get("ready"):
            return v
        v.update(next=c["version"], news=c["news"])
        if c.get("tag") and self.srv and "want" in self.srv["can"]:
            v["srv"] = True                     # stage U3: the app's server takes the same release after this computer
        if c.get("failed"):
            st = U.read(U.STATUS, {}) or {}
            return dict(v, state="fail", why=st.get("why"), detail=st.get("detail"), back=bool(st.get("back")),
                        back_ok=st.get("back_ok", True))
        busy = [{"project": b["project"], "title": b["title"], "turn": b["turn"], "n": b["n"]} for b in self.busy_report()]
        return dict(v, busy=busy, state="wait" if self.upd_wait else "busy" if busy else "ready")

    async def update_row(self):
        """Home's line about an update — only while there is something to do or to know."""
        try:
            v = await self.update_view()
        except Exception as e:
            log("update:", repr(e))
            return None
        broken = await self.broken()
        srv = (self.srv or {}).get("upd") or {}
        if srv.get("state") == "run" and v["state"] in ("ok", "na"):
            return {"state": "srv_run", "have": v["have"], "next": srv.get("tag")}     # stage U3: the server follows
        if v["state"] in ("ok", "na") and not broken:
            return None
        row = {"state": v["state"], "have": v["have"], "next": v.get("next"), "back": v.get("back"),
               "left": len(v.get("busy") or [])}
        if broken:
            row["broken"] = broken              # stage U2: Home says what doesn't work, not only what to install
        return row

    def emit_update(self):
        if self.web:
            self.web.emit("update")

    async def api_update(self):
        return await self.update_view(10)

    async def api_update_go(self):
        """"Install": only what the view says is ready, from the folder install.sh wrote down — the phone sends the
        tap and nothing else (no arguments: an extra one fails the call)."""
        v = await self.update_view(0)
        if v["state"] != "ready":
            raise ValueError(self.t("upd.cant.busy" if v["state"] in ("busy", "wait") else "upd.cant"))
        await self.update_start("app")
        return await self.update_view()

    async def api_update_wait(self):
        """"Install once they're free": update_tick starts it when no session of Pult's own runs."""
        v = await self.update_view(0)
        if v["state"] not in ("busy", "ready", "wait"):
            raise ValueError(self.t("upd.cant"))
        if not self.upd_wait:
            self.upd_wait = time.time()
            log("update: %s goes in once Pult's sessions are free" % v.get("next"))
        self.emit_update()
        return await self.update_view()

    async def api_update_cancel(self):
        if self.upd_wait:
            log("update: no longer waiting")
        self.upd_wait = None
        self.emit_update()
        return await self.update_view()

    async def update_start(self, how):
        """The installer, outside this service (pult_update.spawn): it stops this daemon, so "installing" is written
        first — the next daemon and the app read it from update.json."""
        c = await self.update_check()
        self.upd_wait = None
        U.write(U.STATUS, {"state": "run", "step": "start", "commit": c["head"], "from": self.D.VERSION, "to": c["version"],
                           "how": how, "ts": time.time(), "pid": None})
        log("update: installing %s (%s) — %s" % (c["version"], c["short"], how))
        ok = await asyncio.to_thread(U.spawn, c["head"], how, sys.executable)
        if not ok:
            U.write(U.STATUS, {"state": "fail", "why": "spawn", "commit": c["head"], "from": self.D.VERSION, "to": c["version"],
                               "back": False, "reported": True, "ts": time.time()})
            self._upd = (0.0, None)
            raise ValueError(self.t("upd.cant.spawn"))
        if self.web:                    # on any screen of the app: "installing", not "the computer is offline" (П8)
            self.web.emit("update", state="run")

    async def update_watch(self):
        """Every 5 s (stage U): install once Pult's sessions are free, when the owner asked to; say once, in General,
        that an update didn't come up."""
        while True:
            await asyncio.sleep(5)
            try:
                await self.update_tick()
            except Exception as e:
                log("update:", repr(e))

    async def update_tick(self):
        st = U.read(U.STATUS, {}) or {}
        if st.get("state") == "fail" and st.get("reported") is False:
            st["reported"] = True
            U.write(U.STATUS, st)
            why = self.t("upd.why." + str(st.get("why")))
            if why.startswith("upd.why."):
                why = str(st.get("why"))
            await self.send(None, self.t("upd.failed" if st.get("back") else "upd.failed.kept", to=R.esc(str(st.get("to"))),
                                         back=R.esc(self.D.VERSION), why=R.esc(why)), notify=True, prio=1)
            self._upd = (0.0, None)
            self.emit_update()
        if self.upd_wait:
            v = await self.update_view()
            if v["state"] == "wait" and not v.get("busy"):
                await self.update_start("app_wait")
            elif v["state"] not in ("wait", "run"):
                self.upd_wait = None             # nothing to install any more (installed from the terminal, say)
                self.emit_update()

    # ----- the relay's server follows this computer; releases from GitHub (stage U3) -----

    async def release_watch(self):
        """Every pult_update.CHECK_EVERY: a clone of Pult's GitHub repository looks there for a new release (one
        `git ls-remote`; a newer release is fetched into the clone, not installed — that is the owner's button), and
        the relay's server is reminded of the release this computer runs while it runs another."""
        await asyncio.sleep(20)
        while True:
            try:
                await self.release_look()
                await self.announce()
            except Exception as e:
                log("releases:", repr(e))
            await asyncio.sleep(U.CHECK_EVERY)

    async def release_look(self, force=False):
        """One look at GitHub — at most once a minute (Settings asks for one when it opens)."""
        # never looked yet: look now — the monotonic clock counts from the computer's boot, and in its first minute a
        # 0.0 for "never" read as a look a moment ago (it failed a test on a fresh CI machine, 2026-10-27)
        if not self.prefs()["gh"] or not force and self.gh["t"] is not None and time.monotonic() - self.gh["t"] < 60:
            return
        self.gh["t"] = time.monotonic()
        src = (U.read(U.MANIFEST, {}) or {}).get("src")
        head = await asyncio.to_thread(U.git, src, "rev-parse", "HEAD") if src else None
        remote = await asyncio.to_thread(U.release_mode, src, head) if head else None
        if not remote:
            return
        ok, tag = await asyncio.to_thread(U.discover, src, remote, U.installed_version(), self.env.get("PULT_PROXY") or None)
        if ok != self.gh["ok"]:
            log("releases: GitHub %s" % ("answers" if ok else "doesn't answer"))
        self.gh.update(at=time.time(), ok=ok)
        if tag and tag != self.gh.get("tag"):
            self.gh["tag"] = tag
            log("releases: %s is out — fetched into %s, ready to install" % (tag, src))
            self._upd = (0.0, None)
            self.emit_update()

    async def relay_said(self, msg):
        """The relay's word (stage U3): on connecting — whether its server has the updater and the updater's last
        report; later — each new report. A server that can follow hears the release this computer runs — on a task of
        its own: the relay's messages wait for nothing here, and finding the release may ask GitHub (the developer's
        own folder) — awaited, it held the app's requests up to half a minute (tools/update_live.py, 2026-10-27)."""
        if "can" in msg:
            can = msg.get("can")
            self.srv = {"can": [c for c in can if isinstance(c, str)] if isinstance(can, list) else [], "upd": None}
            self.told = (None, 0.0)
        if self.srv is None:
            return
        if "upd" in msg:
            upd = srv_status(msg.get("upd"))
            self.srv["upd"] = upd
            await self.srv_report(upd)
        if self.announcing is None or self.announcing.done():
            self.announcing = asyncio.ensure_future(self.announce(force="can" in msg))
        self._parts = (0.0, None, None)
        self.emit_update()

    async def announce(self, force=False):
        """The relay's server, when it has the updater, hears which release this computer runs — and takes the same
        one from GitHub. On connecting; then every ANNOUNCE_EVERY while it runs another and may still take it."""
        srv = self.srv
        if not self.web or not srv or "want" not in srv["can"]:
            return
        tag, commit = await self.release_for_server() or (None, None)
        upd = srv.get("upd") or {}
        if not tag or upd.get("have") == tag or upd.get("tag") == tag and (
                upd.get("state") == "refused" or upd.get("state") == "fail" and upd.get("why") not in SRV_TRANSIENT):
            return
        last, at = self.told
        if not force and last == (tag, commit) and time.monotonic() - at < ANNOUNCE_EVERY:
            return
        self.told = ((tag, commit), time.monotonic())
        await self.web.send({"t": "want", "tag": tag, "commit": commit})
        log("app server: told it this computer runs %s" % tag)

    async def release_for_server(self):
        """What the server's updater is told to take (pult_update.release_for_server) → (tag, commit), or None; kept
        ANNOUNCE_EVERY for this folder, commit and version — the developer's own folder asks GitHub for it."""
        m = U.read(U.MANIFEST, {}) or {}
        src, commit = m.get("src"), m.get("commit")
        if not src or not commit:
            return None
        key = (src, commit, self.D.VERSION)
        t, k, v = self.srv_rel
        if k != key or time.monotonic() - t >= ANNOUNCE_EVERY:
            v = await asyncio.to_thread(U.release_for_server, src, commit, self.D.VERSION, self.env.get("PULT_PROXY") or None)
            self.srv_rel = (time.monotonic(), key, v)
        return v

    async def api_srv_retry(self):
        """"Try again on the server" (Settings → Pult and its parts): a release the server's updater didn't take and
        won't try by itself (stage U3). The relay passes the word on with its own clock, and the updater tries it anew."""
        srv = self.srv
        tag, commit = await self.release_for_server() or (None, None)
        if not self.web or not srv or "want" not in srv["can"] or not tag:
            raise ValueError(self.t("srv.retry.no"))
        self.told = ((tag, commit), time.monotonic())
        await self.web.send({"t": "want", "tag": tag, "commit": commit, "retry": True})
        log("app server: asked it to try %s again" % tag)
        return {"ok": True, "v": tag}

    async def srv_report(self, upd):
        """Each report of the server's updater, once (the relay repeats the last one on every connection): a release
        it didn't take is told in Telegram; once it runs a release, the file check expects that release's files."""
        if not upd:
            return
        if U.vtag(upd.get("have") or ""):
            await asyncio.to_thread(self.expect_release, upd["have"])
        ts = upd.get("ts") if isinstance(upd.get("ts"), (int, float)) else 0
        if upd.get("state") not in ("fail", "done") or ts <= (self.store.get("srv_report_ts") or 0):
            return
        self.store.put("srv_report_ts", ts)              # the server's own clock: its reports only go forward
        if upd["state"] == "done":
            log("app server: took %s" % upd.get("tag"))
            return
        why = upd.get("why")
        log("app server: didn't take %s — %s %s" % (upd.get("tag"), why, upd.get("detail") or ""))
        if why in SRV_TRANSIENT:
            return
        words = self.t("srv.why.%s" % why)
        if words.startswith("srv.why."):
            words = str(why)
        await self.send(None, self.t("srv.failed" if upd.get("back_ok") else "srv.failed.dead", to=R.esc(str(upd.get("tag"))),
                                     back=R.esc(str(upd.get("have"))), why=R.esc(words)), notify=True, prio=1)

    def expect_release(self, tag):
        """The file check expects what release `tag` hands the phone, from this computer's own copy of it
        (pult_update.manifest_at); a difference closes the app, as after a deploy — or, with PULT_GUARD=warn in the
        settings (a CDN in front of the server changes files), only warns (Q85). A deploy script's record (a
        developer's own server) gives way only to a release that holds what was deployed: the server moved to releases
        (Q83, Q90); something deployed after the release keeps its record."""
        wanted = "warn" if (self.env.get("PULT_GUARD") or "").strip().lower() == "warn" else "release"
        try:
            cur = json.loads(self.D.WEB_MANIFEST.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            cur = None
        if cur and cur.get("mode") == wanted and cur.get("tag") == tag:
            return
        src = (U.read(U.MANIFEST, {}) or {}).get("src")
        commit = U.git(src, "rev-parse", "-q", "--verify", "refs/tags/%s^{commit}" % tag) if src else None
        if cur and cur.get("mode") not in ("warn", "release"):
            done = cur.get("commit")
            if not (commit and done and U.git(src, "merge-base", "--is-ancestor", done, commit) is not None):
                return
        man = U.manifest_at(src, commit) if commit else None
        if not man:
            return
        man.update(mode=wanted, tag=tag)
        tmp = self.D.WEB_MANIFEST.with_name(self.D.WEB_MANIFEST.name + ".tmp")
        tmp.write_text(json.dumps(man), encoding="utf-8")
        os.replace(tmp, self.D.WEB_MANIFEST)
        log("app files check: expects release %s (%s)" % (tag, "warns only: PULT_GUARD=warn" if wanted == "warn"
                                                          else "a difference closes the app"))

    # ----- every part of Pult against main (stage U2) -----

    def hooks_on(self):
        """The events Pult's hook is set for in Claude Code's settings."""
        hooks = []
        try:
            for ev, groups in (json.loads(self.D.SETTINGS.read_text(encoding="utf-8")).get("hooks") or {}).items():
                if any("pult_hook.py" in str(h.get("command", "")) for g in groups for h in g.get("hooks", [])):
                    hooks.append(ev)
        except (OSError, ValueError, AttributeError, TypeError):
            pass
        return sorted(hooks)

    @staticmethod
    @functools.cache
    def sdk_versions():
        """The Agent SDK the sessions from the app run on, and the Claude Code it carries — the same till a restart
        (reading the package's metadata takes ~0.4 s the first time: called in a thread)."""
        try:
            import importlib.metadata
            sdk = importlib.metadata.version("claude-agent-sdk")
        except Exception:
            sdk = None
        try:
            from claude_agent_sdk._cli_version import __cli_version__ as cli
        except Exception:
            cli = None
        return sdk, cli

    async def cc_facts(self, age=30):
        """Claude Code on this computer: the extension versions VS Code runs now (by their processes, and the tabs with
        the wrapper), the newest one it has downloaded, the ones the wrapper is verified on (tab.json), whether the
        wrapper is set up at all. A tab on an unverified version runs without the wrapper — writing into it is off."""
        t, v = self._cc
        if v is not None and time.monotonic() - t < age:
            return v
        snap = await self.snapshot()
        running = {t.version for t in self.tabs.values() if t.version}
        for pr in ((snap or [{}])[0] or {}).values():
            m = re.search(r"anthropic\.claude-code-(\d+(?:\.\d+)+)", pr.get("cmd") or "")
            if m and pr.get("mine", True):
                running.add(m.group(1))
        try:
            conf = json.loads(self.D.TAB_CONF.read_text(encoding="utf-8"))
            verified, checked = conf.get("versions") or [], conf.get("checked") or {}
        except (OSError, ValueError, AttributeError):
            verified, checked = [], {}
        wrapped = bool(await asyncio.to_thread(pult_os.files_with, self.D.EDITOR_DIRS, self.D.TAB_FILE))
        sdk, cli = await asyncio.to_thread(self.sdk_versions)
        v = {"running": sorted(running, key=vnum), "verified": sorted(verified, key=vnum), "wrapped": wrapped,
             "newest": await asyncio.to_thread(pult_os.newest_extension, EXT_DIRS), "sdk": sdk, "cli": cli,
             "checked": checked if isinstance(checked, dict) else {}, "checking": self.tab_checking,
             "auto": self.prefs()["vcheck"]}
        self._cc = (time.monotonic(), v)
        return v

    async def broken(self):
        """What doesn't work for want of an update, for Home's line: some hook events missing (all off is the owner's
        choice — `pult hooks off`), tabs on a Claude Code the wrapper isn't verified on."""
        out = []
        on = self.hooks_on()
        missing = [e for e in pult_hook.EVENTS if e not in on]
        if on and missing:
            out.append({"k": "hooks", "missing": missing})
        cc = await self.cc_facts()
        fail = lambda v: (cc.get("checked", {}).get(v) or {}).get("ok") is False and not cc["checked"][v].get("error")  # noqa: E731
        # tabs on a version the wrapper is out of (not while it's being checked); else one VS Code has downloaded that
        # failed Pult's check — tabs still write, until a window reloads onto it ("next")
        off = [v for v in cc["running"] if v not in cc["verified"] and v != cc.get("checking")] if cc["wrapped"] else []
        nxt = [v for v in [cc["newest"]] if cc["wrapped"] and v and v not in cc["verified"] and v not in cc["running"]
               and fail(v)]
        if off:
            out.append({"k": "cc", "v": off[-1], "fail": fail(off[-1])})
        elif nxt:
            out.append({"k": "cc", "v": nxt[0], "fail": True, "next": True})
        return out

    def tab_facts(self):
        """The tabs with Pult's wrapper: the project, and whether its wrapper is the installed one — True, False (an
        older one, or one before 0.16 that doesn't say), None (it couldn't tell)."""
        now = {U.blob(self.D.HOME / "pult_tab.py"), U.blob(self.D.HOME / "pult_tab.py", lf=True)} - {None}
        out = []
        for t in list(self.tabs.values()):
            lv = self.live.get(t.sid) if t.sid else None
            name = self.name_of(lv.pkey) if lv and lv.pkey else os.path.basename((t.cwd or "").rstrip(self.D.SEPS)) or "?"
            own = getattr(t, "own", False)
            out.append({"project": name, "same": None if own is None else bool(own) and own in now})
        return out

    async def git_facts(self, age=60):
        """The source folder against what is installed and served: the computer's lag, the commit the relay server's
        copy was made from, the CHANGELOG — a few short git commands, kept `age` s per HEAD and relay build."""
        c = await self.update_check(age)
        repo, head = c.get("repo"), c.get("head")
        if not repo or not head:
            return {"repo": None}
        build = self.web.build if self.web else None
        key = (head, json.dumps(build, sort_keys=True) if build else None)
        t, k, v = self._parts
        if v is not None and k == key and time.monotonic() - t < age:
            return v
        v = await asyncio.to_thread(self.git_parts, repo, head, build)
        self._parts = (time.monotonic(), key, v)
        return v

    @staticmethod
    def git_parts(repo, head, build):
        m = U.read(U.MANIFEST, {}) or {}
        out = {"repo": repo, "head": head, "branch": U.git(repo, "rev-parse", "--abbrev-ref", "HEAD"),
               "mac": U.behind(repo, m.get("commit"), head, U.TREE),
               "gh": U.changelog(repo, head) if U.makes_releases(repo, head) else None,   # only where releases are made
               "release": U.release_mode(repo, head) is not None}      # a clone of GitHub's: the server may follow (U3)
        if out["release"] and m.get("commit"):        # what the server's updater should be, at the release this runs
            out["srv_files"] = U.ls_tree(repo, m["commit"], [p for p in U.SRV_OWN])
        for part, paths in U.PARTS.items():
            files = {p: b for p, b in (build or {}).items() if any(p == x or p.startswith(x + "/") for x in paths)}
            out[part] = U.built_from(repo, head, files, paths) if files else None
            out[part + "_told"] = bool(files)
        return out

    async def parts_facts(self):
        """Everything the table is made of, in one go (the stand puts made-up facts here). What the source folder has
        is at most 10 s old, as in the Pult block before the table: Settings is what one opens after a commit, and with
        the 60 s it had Install came up to a minute late (tools/update_live.py, 2026-10-27)."""
        return {"upd": await self.update_view(10), "git": await self.git_facts(10), "relay": bool(self.web),
                "tabs": self.tab_facts(), "hooks": self.hooks_on(), "cc": await self.cc_facts(), "srv": self.srv}

    @staticmethod
    def parts_rows(f):
        """The table "Pult and its parts" (Settings): one row per part — k, st (ok · warn — can be brought up to date ·
        bad — something doesn't work · attn — worth a look · info — to know, or not known), have (what is there) and
        what the app says about it. The phone's own copy is the app's row: only it knows which one it runs."""
        g, upd = f["git"], f["upd"]
        rows = []
        lag_mac = g.get("mac") or {}
        n = lag_mac.get("n") if upd["state"] not in ("ok", "na") else 0
        rows.append({"k": "mac", "st": {"ok": "ok", "na": "info", "fail": "bad"}.get(upd["state"], "warn"),
                     "have": upd["have"], "n": n, "since": lag_mac.get("since"), "upd": upd})
        if f["relay"]:
            srv = f.get("srv")
            auto = bool(srv and "want" in srv["can"])
            upd_srv = (srv or {}).get("upd") or {}
            for part in ("web", "relay"):
                b = g.get(part)
                if b:
                    row = {"k": part, "st": "warn" if b["n"] else "ok", "have": b["ts"], "commit": b["commit"][:7],
                           "n": b["n"], "since": b["since"], "news": b["news"]}
                else:
                    why = "norepo" if not g.get("repo") else "other" if g.get(part + "_told") else "old"
                    row = {"k": part, "st": "info", "why": why}
                if g.get("release"):          # stage U3: whether the server takes this computer's releases itself
                    row["auto"] = auto
                    if auto and upd_srv:
                        row["srv"] = {k: upd_srv.get(k) for k in ("state", "tag", "have", "step", "why", "detail", "back",
                                                                  "back_ok", "ts")}
                        # a release it didn't take and won't try again: behind — to update; else worth a look
                        row["srv"]["final"] = upd_srv.get("state") == "fail" and upd_srv.get("why") not in SRV_TRANSIENT
                        if upd_srv.get("state") == "run" or row["srv"]["final"] and b and b["n"]:
                            row["st"] = "warn"
                        elif row["srv"]["final"]:
                            row["st"] = "attn"
                        if part == "relay":
                            # the updater and the services only install.sh replaces: older than this release — once,
                            # there, sudo bash deploy/relay/install.sh ("old": an updater before 0.18.6 doesn't say)
                            own, want = upd_srv.get("self"), g.get("srv_files") or {}
                            stale = "old" if own is None else sorted(k.rsplit("/", 1)[-1] for k in U.SRV_OWN
                                                                     if k in want and own.get(k) != want[k])
                            if stale:
                                row["srv"]["self"] = stale
                                if row["st"] == "ok":
                                    row["st"] = "warn"
                rows.append(row)
        tabs, cc = f["tabs"], f["cc"]
        if tabs or cc["wrapped"]:
            old = sorted({t["project"] for t in tabs if t["same"] is False})
            rows.append({"k": "tabs", "st": "warn" if old else "ok", "have": len(tabs), "old": old,
                         "n_old": sum(t["same"] is False for t in tabs),
                         "unknown": sum(t["same"] is None for t in tabs)})
        on = f["hooks"]
        missing = [e for e in pult_hook.EVENTS if e not in on]
        # an event missing is a step to take at the computer, not "broken": all off is (review 2026-10-27, У10)
        rows.append({"k": "hooks", "st": "bad" if not on else "warn" if missing else "ok", "have": len(on),
                     "all": len(pult_hook.EVENTS), "missing": missing})
        off = [v for v in cc["running"] if v not in cc["verified"]] if cc["wrapped"] else []
        fresh = cc["newest"] if cc["wrapped"] and cc["newest"] and cc["newest"] not in cc["verified"] \
            and cc["newest"] not in cc["running"] else None
        checked, checking = cc.get("checked") or {}, cc.get("checking")
        have = (cc["running"] or [cc["newest"]])[-1]
        failed = [v for v in off + [fresh] if v and (checked.get(v) or {}).get("ok") is False]
        # stage A: a version being checked is a matter of a minute; one that failed is broken, even before VS Code reloads
        st = ("attn" if checking in off else "bad") if off else ("bad" if fresh in failed else "attn") if fresh \
            else "ok" if cc["wrapped"] else "info"
        rows.append({"k": "cc", "st": st, "have": have, "off": off, "fresh": fresh, "newest": cc["newest"],
                     "verified": cc["verified"][-1] if cc["verified"] else None, "wrapped": cc["wrapped"],
                     "sdk": cc["sdk"], "cli": cc["cli"], "checking": checking, "auto": cc.get("auto"),
                     "checked": {v: checked[v] for v in {have, fresh, cc["newest"], *off} if v in checked}})
        gh = g.get("gh")
        if gh and gh.get("last"):
            rows.append({"k": "gh", "st": "info" if gh["waiting"] else "ok", "have": gh["last"], "date": gh["date"],
                         "waiting": gh["waiting"]})
        return rows

    async def api_parts(self):
        """Settings → "Pult and its parts": the table, the source folder's HEAD it was checked against, and when."""
        f = await self.parts_facts()
        head = (f["git"].get("head") or "")[:7] or None
        return {"head": head, "branch": f["git"].get("branch"), "at": time.time(), "rows": self.parts_rows(f)}

    # ----- a Claude Code version VS Code has downloaded, checked here before a window reloads onto it (stage A) -----

    async def tab_version_watch(self):
        while True:
            try:
                await self.tab_version_check()
            except Exception as e:
                log("version check for tabs:", repr(e))
            await asyncio.sleep(TAB_CHECK_EVERY)

    async def tab_version_check(self):
        """VS Code has downloaded a Claude Code version tab.json doesn't list: the wrapper stays out of tabs on it until
        it's checked. Pult checks it here (stage A, pult_tabcheck) — while open windows still run the old one, so
        writing into tabs never goes off. One that failed waits for "Check again"; one it couldn't check is tried again
        in an hour. With the check off (Settings), the owner is told once, as before 0.18.1."""
        try:
            conf = json.loads(self.D.TAB_CONF.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        if not isinstance(conf, dict):
            return
        wrapped = bool(pult_os.files_with(self.D.EDITOR_DIRS, self.D.TAB_FILE))
        v = pult_os.newest_extension(EXT_DIRS)
        if not wrapped or not v or v in (conf.get("versions") or []):
            return
        if self.prefs()["vcheck"]:
            rec = (conf.get("checked") or {}).get(v) or {}
            if rec.get("ok") is False and not rec.get("error"):
                return                                  # failed: "Check again" in the app, or pult tab check
            if rec.get("error") and time.time() - (rec.get("ts") or 0) < TAB_RETRY:
                return
            self.tab_check(v)
            return
        if self.store.get("tab_warned") == v:
            return
        self.store.put("tab_warned", v)
        log("Claude Code extension %s is not verified — writing into tabs is off on it" % v)
        await self.send(None, self.t("tab.update", v=R.esc(v)), notify=True)

    def tab_check(self, v):
        """Start the check of Claude Code v for the tabs, unless one runs already; True when started."""
        if self.tab_checking:
            return False
        self.tab_checking = v
        self._cc = (0.0, None)
        if self.web:
            self.web.emit("update")
        asyncio.ensure_future(self.tab_check_run(v))
        return True

    async def tab_check_run(self, v):
        """The check in a process of its own, at a low priority — `pult tab check --json v`: it writes its findings to
        tab.json itself, and a version that passed is allowed there. Here: the log, and the owner is told only of a
        failure (Q79) — once per version; a check that couldn't run says nothing and is tried again later."""
        log("checking Claude Code %s for the tabs" % v)
        rep = None
        try:
            cmd = [sys.executable, str(self.D.HOME / "pultctl.py"), "tab", "check", "--json", v]
            if os.name == "nt":
                kw = {"creationflags": 0x00004000 | 0x08000000}     # below normal priority, no console window
            else:
                cmd, kw = ["nice", "-n", "10"] + cmd, {}
            proc = await asyncio.create_subprocess_exec(*cmd, stdout=asyncio.subprocess.PIPE,
                                                        stderr=asyncio.subprocess.PIPE, **kw)
            try:
                out, err = await asyncio.wait_for(proc.communicate(), TAB_CHECK_LIMIT)
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()
                out, err = b"", b"the check took too long"
            lines = (out or b"").decode(errors="replace").strip().splitlines()
            rep = json.loads(lines[-1]) if lines else None
            if not rep:
                log("tab check %s: no report — %s" % (v, (err or b"").decode(errors="replace").strip()[-300:]))
        except (OSError, ValueError) as e:
            log("tab check %s: %r" % (v, e))
        finally:
            self.tab_checking = None
            self._cc = (0.0, None)
            if self.web:
                self.web.emit("update")
        if not rep:
            return
        steps = rep.get("steps") or []
        log("tab check %s: %s — %s" % (v, {True: "passed", False: "FAILED", None: "couldn't check"}[rep.get("ok")],
                                        rep.get("error") or ", ".join("%s %s" % (x.get("k"), x.get("ok")) for x in steps)))
        if rep.get("ok") is False and self.store.get("tab_check_told") != v:
            self.store.put("tab_check_told", v)
            step = next((x.get("k") for x in steps if x.get("ok") is False and x.get("k") != "race"), "own")
            await self.send(None, self.t("tab.check.fail", v=R.esc(v), step=self.t("tab.step." + step)), notify=True)
        if rep.get("race") is False and self.store.get("tab_race_told") != v:
            self.store.put("tab_race_told", v)
            await self.send(None, self.t("tab.check.race", v=R.esc(v)), notify=True)

    async def api_tab_check(self):
        """"Check again" in Settings → Pult and its parts: the version the tabs run that the wrapper is out of, else
        the newest one VS Code has downloaded."""
        cc = await self.cc_facts(age=0)
        off = [v for v in cc["running"] if v not in cc["verified"]]
        v = off[-1] if off else cc["newest"] if cc["newest"] not in cc["verified"] else None
        if not v:
            return {"ok": False, "note": self.t("tab.check.nothing")}
        return {"ok": self.tab_check(v), "v": v, "note": None if self.tab_checking == v else self.t("tab.check.busy")}
