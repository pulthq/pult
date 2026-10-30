"""What the app's screens ask the daemon — Home, projects, a session, a new project, files, voice, spend, settings:
the handlers of their requests (`api_*`) and the helpers only they use, which put a screen's data together; out of
pultd.py unchanged (review 2026-10-27, 6.2). The handlers of the parts and updates screen live with the parts' own
code, in pult_parts.

Api is a mixin: the daemon is `class Pult(Api, Parts)`, so the handlers stay its methods — pult_web finds them by name
(getattr(daemon, "api_" + op)), the tests and the stand call p.api_x() as before, and each side calls the other
through self. The daemon runs as `python pultd.py`: its module is __main__, and `import pultd` here would load a second
copy of it with globals of its own (at the top of this file — a circular import too), while the tests, which import
pultd by that name, would never notice. So this module never imports pultd; the daemon's own names, the ones it reads
as well, come late through the daemon itself: self.D is the module that defines Pult (sys.modules[__name__] in its
body), and a test that changes pultd.CLAUDE_PROJECTS changes what the handlers read too. What only the screens read
lives here, and a test changes it here (NEW_ROOT).
"""
import asyncio
import base64
import binascii
import json
import os
import re
import secrets
import shutil
import time
import uuid
from pathlib import Path

import pult_attn as A
import pult_codex as CX
from pult_driven import MAX_RUNNING   # turns at once — pult_driven's
import pult_files as F
import pult_hook
import pult_i18n as I
import pult_load as L
import pult_new as N
import pult_render as R
import pult_spend as S
import pult_stt as STT
import pult_tags as G
import pult_update as U
import pult_web as PW

CATCH_GAP = 3600         # s: the app was closed this long — "While you were away" on the next open
SPEND_COLORS = 5         # projects with a colour of their own on the spend screen; the rest are "other"
STT_WORDS_MAX = 280             # characters of the owner's own words for Whisper: with the sentence, within Groq's 896 bytes
STT_MAX = 4 * 1024 * 1024       # bytes of one recording from the app (5 min at 32 kbit/s ≈ 1.2 MB; base64 must fit the 8 MB frame)
NEW_ROOT = Path.home()   # a new project and the folder picker stay inside this (stage S)
MODEL_RE = re.compile(r"[A-Za-z0-9][\w.\-\[\]]{0,63}")        # a model alias or id for a session from Telegram
EFFORTS = ("low", "medium", "high", "xhigh", "max")
KEEP = object()        # an api_model argument the app did not send: that half of the choice stays as it is
CTX_RESERVE = 13000        # VS Code's context gauge: used ÷ (window − min(maxOutputTokens, 20000) − 13000) (webview 2.1.301)
CTX_OUT_CAP = 20000
TAGS_RECENT = 30 * 86400   # s: the tags screen puts first the tags of the tasks of these last days (stage T, T2)
TIDY_RETRY = 600           # s: the model gave nothing on a project's list — not asked about the same names before this
TAG_NOTE = 120             # s: the tags screen tells this long that a "Sort them again" changed nothing
MERGE_EXAMPLES = 2         # the latest tasks of a tag the owner merged into another: examples of where such tasks go
CODEX_TTL = 600            # s: Codex on this computer is looked up again after this (ChatGPT.app updates it by itself)
SECOND_LINES = 5           # findings named in the topic when a second opinion is ready; the rest — in the app


def log(*a):
    print(time.strftime("%Y-%m-%d %H:%M:%S"), *a, flush=True)      # as pultd.log: the daemon's journal, the same form


async def sdk_effort(client, effort):
    """Effort of a running SDK session: the apply_flag_settings control request (effortLevel in the flag layer, this
    process only; None — back to the settings). The Python SDK has no method for it yet, so its generic request is
    used; probe tests/probe_effort.py, Claude Code 2.1.301."""
    send = getattr(getattr(client, "_query", None), "_send_control_request", None)
    if send is None:
        raise RuntimeError("the SDK has no control requests")
    await send({"subtype": "apply_flag_settings", "settings": {"effortLevel": effort}})


def ctx_usable(window, max_out):
    """How much of the window counts as usable — the same number VS Code divides by."""
    return max(1, window - min(max_out, CTX_OUT_CAP) - CTX_RESERVE)


class Api:
    """The handlers of the app's requests — a mixin of pultd.Pult: self is the daemon, self.D its module."""

    # ----- Home: the board, its rows, presence and "While you were away", the load on the computer -----

    async def api_overview(self):
        agents = await self.agents()
        idle = await self.idle()
        shown = {sid for sid, lv in self.live.items() if lv.turn or lv.pending or lv.bg or self.queued(sid)}
        opened = []
        for a in agents:
            sid = a.get("sessionId")
            if sid and sid not in shown:
                lv = self.live.get(sid) or self.stub(sid, self.D.sanitize(a.get("cwd") or ""))
                opened.append(dict(self.live_item(lv), project=os.path.basename((a.get("cwd") or "").rstrip(self.D.SEPS))))
        load = await self.load_state()
        return {"mac": {"idle": idle, "away": await self.away(), "mode": self.mode()}, "now": time.time(),
                "lang": self.lang(), "load": self.load_sum(load[2], load[3]) if load else None,
                # a session may end while this waited for the process snapshot (SessionEnd drops it): it is just gone
                # from the list — before, Home failed with KeyError until the next event (review 2026-10-27, A1)
                "live": [self.live_item(self.live[s]) for s in shown if s in self.live],
                "pending": [self.req_item(r) for r in self.req_by_rid.values() if not r.fut.done()],
                "open": opened, "recent": list(self.recent),
                "jobs": [self.job_item(j) for j in self.jobs.values()] + [self.job_item(j) for j in self.jobs_done],
                "update": await self.update_row(), **await self.board(agents)}

    async def api_seen(self, sid):
        """"Got it" on a card of "Your move": the outcome is seen without opening the session."""
        self.mark_seen(sid)
        return {"ok": True}

    def live_item(self, lv):
        t = lv.turn
        q = self.queued(lv.sid)
        return {"sid": lv.sid, "title": self.title(lv), "project": self.project_label(lv.pkey), "pkey": lv.pkey,
                "driven": lv.driven, "state": "ask" if lv.pending else "work" if t else "queue" if q else "idle",
                "queued": q, "waiting": self.driven[lv.sid].waiting if q else None, "slots": MAX_RUNNING,
                "started": t.started if t else None, "run": (lv.run or t.started) if t else None, "prompt": R.short(R.prompt_text(t.prompt), 300) if t and t.prompt else None,
                "note": t.note if t else None, "now": R.plain(t.now, self.D.NOW_LEN) if t and t.now else None,
                "bg": [R.short(b.get("description") or b.get("command") or self.t("task.default"), 80) for b in lv.bg],
                "bg_since": self.bg_since(lv), "tab": bool(self.tab_for(lv.sid))}

    def req_item(self, req):
        lv = self.live.get(req.sid) or self.stub(req.sid)
        d = {"rid": req.rid, "sid": req.sid, "kind": req.kind, "tool": req.tool, "title": self.title(lv),
             "project": self.project_label(lv.pkey), "suggest": bool(req.suggestions), "since": req.ts}
        if req.kind == "ask":
            d["questions"] = req.inp.get("questions") or []
            d["chosen"] = {str(i): v for i, v in req.chosen.items()}
            d["picks"] = {str(i): v for i, v in req.picks.items()}       # checked so far: Claude's advice, Telegram's taps
        elif req.kind == "plan":
            d["plan"] = str(req.inp.get("plan") or "")[:20000]
        else:
            d["html"] = R.permission_text(req.tool, req.inp, lv.cwd)     # everything is escaped in R
        return d

    def job_item(self, j):
        return {"id": j.rid, "cmd": j.cmd, "cwd": j.cwd, "project": self.project_label(j.pkey) if j.pkey else None,
                "started": j.started, "ended": j.ended, "code": j.code, "last": j.last, "tail": j.tail[-30:]}

    async def ctx_pct(self, sid):
        """How full the session's context is, % — the number VS Code shows; None if unknown."""
        try:
            path, _ = self.transcript_of(sid)
        except ValueError:
            return None
        st = await asyncio.to_thread(self.stats.get, path)
        ctx = self.ctx_of(sid, (st or {}).get("model"))
        if not st or not st.get("context") or not ctx:
            return None
        return min(100, round(st["context"] * 100 / ctx_usable(ctx[0], ctx[1])))

    async def board(self, agents):
        """The Home board (stage V): every session worth a look grouped by project; and "mine": the outcomes that
        wait for the owner. Requests waiting for an answer are not repeated here: the app shows them as answerable
        cards (overview.pending)."""
        now = time.time()
        by = {}
        for r in self.session_rows(agents):
            by.setdefault(r["pkey"], []).append(r)
        projects = []
        for pkey, rs in by.items():
            turns, secs = self.attn.day_of(pkey)
            shown = [r for r in A.sort_rows(rs) if r["state"] not in A.MINE and not A.resting(r, now)]
            for r in shown:
                r["ctx"] = await self.ctx_pct(r["sid"])
            projects.append({"pkey": pkey, "name": self.name_of(pkey, rs), "rows": shown, "rows_all": rs,
                             "resting": sum(1 for r in rs if A.resting(r, now)),
                             "work": sum(1 for r in rs if r["state"] in ("work", "bg", "queue")),
                             "mine": sum(1 for r in rs if r["state"] in A.MINE), "turns": turns, "secs": secs})
        mine = A.sort_rows([dict(r, project=p["name"]) for p in projects for r in p["rows_all"] if r["state"] in ("you", "fail")])
        projects = A.sort_projects(projects)
        pins, hides = self.store.pins(), self.store.hides()
        projects.sort(key=lambda p: -pins.get(p["pkey"], 0))      # the pinned first, the newest pin on top; the rest keep their order (stage Zh)
        for p in projects:                                           # a hidden one stays: its running rows feed "Running now"; the app skips its block
            p["pinned"], p["hidden"] = bool(pins.get(p["pkey"])), bool(hides.get(p["pkey"]))
            del p["rows_all"]
        return {"board": projects, "mine": mine, "brief": self.prefs()["brief"], "reset": self.limit_reset(),
                "usage_pct": self.limit_pct(), "usage_top": await self.spend_top(), "catchup": self.catchup(),
                "stt": self.stt_state()["on"],
                "pager": self.pager()}

    def catchup(self):
        """"While you were away": the turns since the app was last on the screen, what is done, what waits for the
        owner now, the latest line per project."""
        if not self.catch_from:
            return None
        es = self.attn.since(self.catch_from)
        if not es:
            return None
        last = {}
        for e in es:
            last[e[1]] = e
        lines = []
        for pkey, e in sorted(last.items(), key=lambda x: -x[1][0])[:4]:
            r = self.attn.rec.get(e[2]) or {}
            lines.append({"pkey": pkey, "name": self.name_of(pkey), "line": e[3],
                          "you": bool(e[4] and not r.get("seen")), "fail": e[5]})
        return {"from": self.catch_from, "turns": len(es), "projects": len(last),
                "done": sum(1 for e in es if not e[4] and not e[5]), "lines": lines,
                "mine": sum(1 for r in self.attn.rec.values() if not r["seen"] and (r["you"] or r["fail"]))}

    def limit_pct(self):
        """The 5-hour window, % used, from the last usage reading (no new request), or None."""
        for lim in (self._usage or {}).get("limits") or []:
            if lim.get("kind") in ("session", "five_hour"):
                return lim.get("percent")
        return None

    async def api_presence(self, on=True, quiet=False):
        """The app is on the owner's screen (or not): where to call them (stage V). A visit after a long break opens
        "While you were away"; the end of the visit closes it."""
        now = time.time()
        if on:
            if not self.app_vis:
                log("app: on the screen")
                if self.app_seen and now - self.app_seen > CATCH_GAP:
                    self.catch_from = self.app_seen
                    self.store.put("catch_from", self.catch_from)
            self.app_vis, self.app_on = True, now
            if now - self.app_seen > 60:
                self.store.put("app_seen", now)
            self.app_seen = now
        elif self.app_vis:
            log("app: no word for %d s — off the screen" % self.D.APP_ON if quiet else "app: off the screen")
            self.app_vis = False
            self.store.put("app_seen", now)
            self.app_seen = now
            if self.catch_from:
                self.catch_from = None
                self.store.put("catch_from", None)
        return {"ok": True}

    async def api_picker(self, kind="pic", opened=True, ms=0, why="", age=None, tgv="", cv=""):
        """How a tap on Picture or File in the app on Android ended: the picker came back with a file or empty, or it
        never opened — the last tap's picker never came back, and Chromium opens the next only after it, or Telegram
        refused at once. A window Telegram kept for hours can lose the gallery's answer and open none after it
        (relay/web/static/ui/pics.js); the journal tells how often, and whether only old windows. Every field is
        checked: it goes to the log. An app before 0.18.19 sends opened and why "", "cancel" or "silent"."""
        def whole(x, top):
            try:
                return min(top, max(0, int(x)))
            except (TypeError, ValueError):
                return None

        def took(sec):
            return "%d s" % sec if sec < 60 else "%d min" % (sec // 60) if sec < 3600 else "%.1f h" % (sec / 3600)
        if why not in ("picked", "closed", "stuck", "refused"):
            why = "picked" if opened else "refused" if why == "cancel" else "stuck"
        what = "picture" if kind == "pic" else "file"
        secs = (whole(ms, 86400000) or 0) / 1000
        age = whole(age, 90 * 86400)
        old = "window %s old" % took(age) if age is not None else "window's age unknown"
        if why in ("picked", "closed"):
            log("app: file picker came back %s (%s, %.1f s; %s)" % ("with a file" if why == "picked" else "empty", what, secs, old))
        else:
            tgv = tgv if re.fullmatch(r"\d{1,2}(\.\d{1,2}){0,2}", str(tgv or "")) else "?"
            cv = cv if re.fullmatch(r"\d{2,3}", str(cv or "")) else "?"
            log("app: file picker did not open — %s (%s; %s; Telegram API %s, Chrome %s)" % (
                "Telegram refused it" if why == "refused" else "the last tap's picker never came back (%s ago)" % took(int(secs)),
                what, old, tgv, cv))
        return {"ok": True}

    async def api_catchup_off(self):
        self.catch_from = None
        self.store.put("catch_from", None)
        return {"ok": True}

    async def claude_roots(self, procs):
        """sid → (claude's pid, folder) for each session with a process here: `claude agents` lists VS Code tabs,
        terminals and Pult's own sessions (probe_load.py); the hook's parent and Pult's own children cover a miss."""
        roots = {}
        for a in await self.agents():
            sid, pid = a.get("sessionId"), a.get("pid")
            if sid and pid in procs and sid not in roots:
                roots[sid] = (pid, a.get("cwd"))
        for sid, lv in self.live.items():
            if sid not in roots and lv.pid in procs and L.is_claude(procs[lv.pid]["cmd"]):
                roots[sid] = (lv.pid, lv.cwd)
        me = os.getpid()
        for pid, d in procs.items():
            sid = L.session_arg(d["cmd"]) if d["ppid"] == me and L.is_claude(d["cmd"]) else None
            if sid and sid not in roots:
                roots[sid] = (pid, getattr(self.driven.get(sid), "path", None))
        return roots

    def load_row(self, sid, pid, cwd, procs, kids, cores):
        lv = self.live.get(sid)
        if lv is None:
            lv = self.stub(sid, self.session_pkey(sid) or self.D.sanitize(cwd or ""))
            lv.cwd = cwd
        known = self.store.topic(lv.pkey)
        return dict(L.session(procs, pid, kids, cores, lv.bg), sid=sid, title=self.title(lv),
                    project=self.project_label(lv.pkey) if known else os.path.basename((cwd or "").rstrip(self.D.SEPS))
                    or self.project_label(lv.pkey),
                    state="ask" if lv.pending else "work" if lv.turn else "bg" if lv.bg else "idle",
                    driven=sid in self.driven)

    async def load_state(self):
        """(procs, kids, machine, rows — one per session, the busiest first), or None where the system can't tell."""
        snap = await self.snapshot()
        if not snap:
            return None
        procs, mac = snap
        kids = L.children(procs)
        rows = [self.load_row(sid, pid, cwd, procs, kids, mac["cores"])
                for sid, (pid, cwd) in (await self.claude_roots(procs)).items()]
        rows.sort(key=lambda r: (-r["cpu"], -r["mem"]))
        return procs, kids, mac, rows

    @staticmethod
    def load_sum(mac, rows):
        return {"cpu": round(mac["cpu"], 1), "cores": mac["cores"], "load": round(mac["load"], 1),
                "mem_used": mac["mem_used"], "mem_total": mac["mem_total"],
                "claude": {"n": len(rows), "cpu": round(sum(r["cpu"] for r in rows), 1),
                           "mem": sum(r["mem"] for r in rows)}}

    async def api_load(self, sid=None):
        """The load view: the computer and every session on it; with sid — that session and its background tasks."""
        st = await self.load_state()
        if not st:
            return {"ok": False}
        procs, kids, mac, rows = st
        out = {"ok": True, "mac": self.load_sum(mac, rows), "now": time.time()}
        if not sid:
            return dict(out, sessions=rows)
        row = next((r for r in rows if r["sid"] == sid), None)
        lv, used = self.live.get(sid), set()
        tasks = [L.task(procs, row and row["pid"], kids, mac["cores"], b, lv.bg_seen.get(b.get("id")), used)
                 for b in (lv.bg if lv else [])]
        return dict(out, session=row, tasks=tasks)

    # ----- projects and their sessions; a task's tags (stage T) -----

    async def project_counts(self):
        """Per project: sessions open right now (on the computer or from Telegram), working, waiting for an answer."""
        by = {}

        def add(pkey, sid, work, ask):
            if not pkey or not sid:
                return
            d = by.setdefault(pkey, {"open": set(), "work": set(), "ask": set()})
            d["open"].add(sid)
            if work:
                d["work"].add(sid)
            if ask:
                d["ask"].add(sid)
        for a in await self.agents():
            sid = a.get("sessionId")
            lv = self.live.get(sid)
            add(self.session_pkey(sid) or self.D.sanitize(a.get("cwd") or ""), sid,
                a.get("status") == "busy" or bool(lv and lv.turn), bool(lv and lv.pending))
        for sid, dr in self.driven.items():
            lv = self.live.get(sid)
            add(self.session_pkey(sid) or self.D.sanitize(dr.path), sid, dr.busy, bool(lv and lv.pending))
        for sid, lv in self.live.items():
            if lv.turn or lv.pending:                 # a tab mid-turn counts even if `claude agents` missed it
                add(lv.pkey, sid, bool(lv.turn), bool(lv.pending))
        return {k: {n: len(v[n]) for n in ("open", "work", "ask")} for k, v in by.items()}

    async def api_projects(self):
        known = {r["pkey"]: r["path"] for r in self.store.db.execute("SELECT pkey, path FROM topics") if r["path"]}
        counts = await self.project_counts()
        pins, hides = self.store.pins(), self.store.hides()
        by = {}
        for r in self.session_rows(await self.agents()):
            by.setdefault(r["pkey"], []).append(r)
        out = []
        for mtime, pkey, path in (await asyncio.to_thread(self.list_projects, known))[:40]:
            c = counts.get(pkey) or {}
            rs = by.get(pkey) or []
            last = max((r for r in rs if r["ts"]), key=lambda r: r["ts"], default=None)
            out.append({"pkey": pkey, "name": self.project_label(pkey) if pkey in known else self.project_name(pkey, path),
                        "path": path, "last": mtime, "open": c.get("open", 0), "work": c.get("work", 0), "ask": c.get("ask", 0),
                        "mine": sum(1 for r in rs if r["state"] in A.MINE), "line": last["line"] if last else "",
                        "turns": self.attn.day_of(pkey)[0], "pinned": pins.get(pkey, 0), "hidden": hides.get(pkey, 0)})
        # the pinned first, the newest pin on top (stage Zh, Q98); then what needs you, then what works, then what
        # is open, then by recency; the hidden last — the app folds them (Q101)
        out.sort(key=lambda r: (-r["pinned"], r["hidden"] > 0, -(r["mine"] > 0), -(r["work"] + r["ask"] > 0), -(r["open"] > 0), -r["last"]))
        # stt: the app shows the microphone only with a key; create: this daemon makes new projects (stage S);
        # choice: the default model and effort from Settings, what a new task starts with when nothing is picked
        p = self.prefs()
        return {"projects": out, "stt": self.stt_state()["on"], "create": True,
                "choice": {"model": p["model"], "effort": p["effort"]}}

    async def known_project(self, pkey):
        """A project the computer knows — with a topic, or with transcripts: the only ones the app's lists show."""
        known = {r["pkey"]: r["path"] for r in self.store.db.execute("SELECT pkey, path FROM topics") if r["path"]}
        return isinstance(pkey, str) and (pkey in known or any(
            k == pkey for _, k, _ in await asyncio.to_thread(self.list_projects, known)))

    async def api_pin(self, pkey, on=True, via="button"):
        """Pin a project (stage Zh, Q98): on top of Projects, of Home's board and of the new task's list, the newest
        pin first — or unpin it; a pin brings a hidden project back. via — how the owner did it, a slide on the row or
        the button in the project's header: the journal counts both, so whether the gesture earns its place shows
        there (runbook: a rule about the phone goes out silent, to the journal)."""
        if not await self.known_project(pkey):
            raise ValueError(self.t("err.no_project"))
        self.store.set_pin(pkey, bool(on))
        if on:
            self.store.set_hide(pkey, False)
        log("app: project %s via the %s" % ("pinned" if on else "unpinned", "swipe" if via == "swipe" else "button"))
        return {"pinned": bool(on)}

    async def api_hide(self, pkey, on=True, via="swipe"):
        """Hide a project (stage Zh, step 2 — Q101): into the fold at the bottom of Projects, off Home's board and the
        new task's list — what runs in it and what waits for the owner still show; hiding unpins. Or show it again."""
        if not await self.known_project(pkey):
            raise ValueError(self.t("err.no_project"))
        self.store.set_hide(pkey, bool(on))
        if on:
            self.store.set_pin(pkey, False)
        log("app: project %s via the %s" % ("hidden" if on else "shown again", "swipe" if via == "swipe" else "button"))
        return {"hidden": bool(on)}

    async def api_swipe(self, end="back", ms=0, dx=0, what="project"):
        """How a slide on a row ended (stage Zh): open on its actions, sprung back, or cancelled — the browser or
        Telegram's window took the finger (pointercancel); what — a project's row, a task's row or a card of "Your move"
        (step 2), or a message in a session — Claude's or the owner's own — which a slide copies (step 3): with its
        formatting, as plain text only, or not at all — the lift of the finger didn't count for the clipboard, and the
        copy waits on its button. The app says
        nothing of it; the journal tells whether the gesture works inside Telegram on the phone at all. Every field is
        checked: it goes to the log."""
        ends = {"open": "opened on its action", "back": "sprang back", "cancel": "cancelled — the window took the finger",
                "copied": "copied it with its formatting", "plain": "copied it as plain text only",
                "nocopy": "didn't copy it — the copy waits on its button"}
        rows = {"project": "a project's row", "task": "a task's row", "card": "a card", "msg": "Claude's message",
                "mine": "your message"}
        try:
            ms, dx = min(60000, max(0, int(ms))), min(1000, max(0, int(dx)))
        except (TypeError, ValueError):
            ms, dx = 0, 0
        log("app: swipe on %s %s (%d ms, %d px)" % (rows.get(what, rows["project"]), ends.get(end, ends["back"]), ms, dx))
        return {"ok": True}

    async def api_taginfo(self, sid):
        """A task's tags for the sheet opened from its row (stage Zh, step 2 — Q102): the same three fields the
        session's screen has — its tags, the project's list, whether Claude still picks them."""
        if not re.fullmatch(r"[0-9a-fA-F-]{36}", str(sid or "")):
            raise ValueError(self.t("err.bad_sid"))
        lv = self.live.get(sid) or self.stub(sid)
        own = self.store.session_tag(sid)
        return {"tags": self.tags_of(sid), "tagset": self.tag_list(lv.pkey), "tag_auto": not (own and own["own"])}

    async def api_project(self, pkey):
        """A project's screen — its board, large: what waits for the owner (requests to answer here, sessions that
        need them), what runs, today's outcomes, then the earlier sessions."""
        rows = [r for r in self.session_rows(await self.agents()) if r["pkey"] == pkey]
        path = self.project_path(pkey) or next((r["cwd"] for r in rows if r["cwd"]), None)
        if not path and not rows:
            raise ValueError(self.t("err.no_project"))
        midnight = time.mktime(time.localtime()[:3] + (0, 0, 0, 0, 0, -1))
        pending = [self.req_item(r) for r in self.req_by_rid.values()
                   if not r.fut.done() and (self.live.get(r.sid) or self.stub(r.sid)).pkey == pkey]
        mine = A.sort_rows([r for r in rows if r["state"] in ("you", "fail")])
        live = A.sort_rows([r for r in rows if r["state"] in ("work", "bg", "queue")])
        today = sorted([r for r in rows if r["state"] in ("done", "idle") and (r["ts"] or 0) >= midnight],
                       key=lambda r: -(r["ts"] or 0))
        for r in live + today:
            r["ctx"] = await self.ctx_pct(r["sid"])
        shown = {r["sid"] for r in mine + live + today} | {r["sid"] for r in pending}
        earlier = []
        if path and os.path.isdir(path):
            from claude_agent_sdk import list_sessions
            try:
                items = await asyncio.to_thread(list_sessions, path, 40)
            except Exception as e:
                log("project sessions not listed:", repr(e))
                items = []
            known, tagged = {r["sid"]: r for r in rows}, {}
            for x in items:
                if x.session_id in shown:
                    continue
                r = known.get(x.session_id) or {}
                earlier.append({"sid": x.session_id, "title": R.short(x.custom_title or x.summary or "—", 80),
                                "last": x.last_modified / 1000, "line": r.get("line") or "", "open": bool(r.get("open")),
                                "driven": x.session_id in self.driven, "tags": self.tags_of(x.session_id, tagged)})
        turns, secs = self.attn.day_of(pkey)
        # tags_n: the project has a list at all — the way to its tags screen, even when nothing on this one has tags;
        # tag_job: Claude sorts its earlier tasks now — the first open of the project with the model on starts it (Q93)
        self.tags_sort_soon(pkey)
        return {"pkey": pkey, "name": self.name_of(pkey, rows), "path": path, "pending": pending, "mine": mine,
                "live": live, "today": today, "earlier": earlier, "turns": turns, "secs": secs,
                "reset": self.limit_reset(), "stt": self.stt_state()["on"],
                "tagset": self.tag_list(pkey, list(shown) + [x["sid"] for x in earlier]),
                "tags_n": len(self.store.tag_vocab(pkey)), "tag_job": self.tag_jobs.get(pkey),
                "pinned": bool(self.store.pins().get(pkey)), "hidden": bool(self.store.hides().get(pkey)),
                "vendors_ok": self.vendors_ok(pkey)}

    async def api_sessions(self, pkey):
        path = self.project_path(pkey)
        if not path:
            raise ValueError(self.t("err.no_project"))
        from claude_agent_sdk import list_sessions
        items = await asyncio.to_thread(list_sessions, path, 30)
        live = {a.get("sessionId") for a in await self.agents()}
        return {"pkey": pkey, "name": self.project_label(pkey), "sessions": [
            {"sid": s.session_id, "title": R.short(s.custom_title or s.summary or "—", 80), "named": bool(s.custom_title),
             "last": s.last_modified / 1000, "open": s.session_id in live, "driven": s.session_id in self.driven}
            for s in items]}

    def tag_list(self, pkey, sids=None):
        """The project's sections for the app — [{n, c, cnt, fresh, topics: [{n, cnt, fresh}]}]. With sids — what a
        screen shows: cnt counts those sessions, only the sections and topics they have, the most used first (the tag
        bar); without — the whole list in its order, cnt over every task (the sheet that corrects a task's tags). What
        the owner hid is in neither (stage T, T2)."""
        vocab, uses, now = self.store.tag_vocab(pkey), self.store.tag_uses(pkey), time.time()
        hidden = self.store.tag_hidden(pkey)
        have = None
        if sids is not None:
            have = {}
            for sid in set(sids):
                r = self.store.session_tag(sid)
                if r and r["sec"] and r["pkey"] == pkey:
                    have[(r["sec"], None)] = have.get((r["sec"], None), 0) + 1
                    if r["topic"]:
                        have[(r["sec"], r["topic"])] = have.get((r["sec"], r["topic"]), 0) + 1
        out = []
        for s in vocab:
            if (s["n"], None) in hidden:
                continue
            cnt = (have if have is not None else uses).get((s["n"], None), 0)
            tops = [{"n": t["n"], "cnt": (have if have is not None else uses).get((s["n"], t["n"]), 0),
                     "fresh": G.is_fresh(t, uses.get((s["n"], t["n"]), 0), now)} for t in s["topics"]
                    if (s["n"], t["n"]) not in hidden]
            if have is not None:
                if not cnt:
                    continue
                tops = [t for t in tops if t["cnt"]]
            out.append({"n": s["n"], "c": s["c"], "cnt": cnt, "fresh": G.is_fresh(s, uses.get((s["n"], None), 0), now),
                        "topics": tops})
        if have is not None:
            out.sort(key=lambda g: (-g["cnt"], g["c"]))
        return out

    async def api_tag(self, sid, sec=None, topic=None, auto=False):
        """The owner's tags for a task (stage T): a section, and a topic in it if any — from the project's list or new
        (the limits are the model's, not the owner's); final: the model never changes them. auto — back to Claude:
        the model reads the task again, from its title and its last outcome."""
        if not re.fullmatch(r"[0-9a-fA-F-]{36}", str(sid or "")):
            raise ValueError(self.t("err.bad_sid"))
        lv = self.live.get(sid) or self.stub(sid)
        if not lv.pkey or self.D.skip_pkey(lv.pkey):
            raise ValueError(self.t("err.no_project"))
        cur = self.store.session_tag(sid)
        if auto:
            if cur and cur["own"]:
                self.store.set_session_tag(sid, lv.pkey, cur["sec"], cur["topic"], False)
                log("tags %s: back to Claude" % sid[:8])
            self.store.tag_unexample(lv.pkey, sid)              # no longer the owner's choice: not their example
            if self.prefs()["brief"]:
                rec = self.attn.rec.get(sid) or {}
                asyncio.create_task(self.tag_task(lv, lv.title or "", reply=rec.get("line")))
        else:
            name = G.norm(sec, G.SEC_LEN)
            if not name:
                raise ValueError(self.t("tags.e.name"))
            s = next((x for x in self.store.tag_vocab(lv.pkey) if G.key(x["n"]) == G.key(name)), None)
            name = s["n"] if s else name
            tp = G.norm(topic, G.TOPIC_LEN) if topic else None
            t = next((x for x in s["topics"] if G.key(x["n"]) == G.key(tp)), None) if s and tp else None
            tp = t["n"] if t else tp
            if not s:                            # a name the owner gives is theirs, even an old one of another tag
                self.store.tag_unalias(lv.pkey, name)
            if tp and not t:
                self.store.tag_unalias(lv.pkey, name, tp)
            self.store.tag_hide(lv.pkey, name, None, False)        # and what they pick is seen again, if it was hidden
            if tp:
                self.store.tag_hide(lv.pkey, name, tp, False)
            self.store.tag_add(lv.pkey, name, tp, own=True)
            self.store.set_session_tag(sid, lv.pkey, name, tp, True)
            self.tags_prune(lv.pkey)
            self.tag_example_soon(lv.pkey, sid)                 # the model sees it when it tags the project's next tasks
            log("tags %s: %s%s (the owner's)" % (sid[:8], name, " / " + tp if tp else ""))
        self.changed(sid)
        return {"tags": self.tags_of(sid), "tagset": self.tag_list(lv.pkey), "auto": bool(auto)}

    # ----- the project's tags screen (stage T, T2): the owner tidies what Claude keeps -----

    def tags_prune(self, pkey):
        """Claude's tags that no task has go (Store.tag_prune) — but not while a job sorts the project's tasks: a new
        list waits empty for its batches, and the screen's next look would take it all away (the stand, 2026-10-28)."""
        if pkey not in self.tag_jobs:
            self.store.tag_prune(pkey)

    def tags_pkey(self, pkey):
        if not isinstance(pkey, str) or not pkey or self.D.skip_pkey(pkey) or not (
                self.store.topic(pkey) or self.store.tag_vocab(pkey)):
            raise ValueError(self.t("err.no_project"))
        return pkey

    async def api_tags(self, pkey):
        """The project's tags screen: its sections, each with its topics and how many tasks of the whole project have
        them, the most used in the last 30 days first; what the owner hid, apart; Claude's offers to merge two tags
        that name the same thing (looked for in the background, when the names have changed: tidy_soon)."""
        self.tags_pkey(pkey)
        self.tags_prune(pkey)
        vocab, now = self.store.tag_vocab(pkey), time.time()
        uses, recent = self.store.tag_uses(pkey), self.store.tag_uses(pkey, now - TAGS_RECENT)
        hidden, kept = self.store.tag_hidden(pkey), self.store.tag_kept(pkey)
        rank = lambda k, c: (-recent.get(k, 0), -uses.get(k, 0), c)
        secs, gone = [], []
        for s in vocab:
            tops = []
            for i, t in enumerate(s["topics"]):
                k = (s["n"], t["n"])
                if k in hidden:
                    gone.append({"sec": s["n"], "topic": t["n"], "c": s["c"], "cnt": uses.get(k, 0)})
                    continue
                tops.append((rank(k, i), {"n": t["n"], "cnt": uses.get(k, 0), "own": t["own"],
                                          "fresh": G.is_fresh(t, uses.get(k, 0), now)}))
            k = (s["n"], None)
            if k in hidden:
                gone.append({"sec": s["n"], "topic": None, "c": s["c"], "cnt": uses.get(k, 0)})
                continue
            secs.append((rank(k, s["c"]), {"n": s["n"], "c": s["c"], "cnt": uses.get(k, 0), "own": s["own"],
                                           "fresh": G.is_fresh(s, uses.get(k, 0), now),
                                           "topics": [x for _, x in sorted(tops, key=lambda p: p[0])]}))
        color = {s["n"]: s["c"] for s in vocab}
        sug = [{"a": {"sec": a[0], "topic": a[1]}, "b": {"sec": b[0], "topic": b[1]}, "c": color[a[0]]}
               for a, b in G.tidy_pairs((self.store.get("tags.tidy." + pkey) or {}).get("raw"), vocab, kept, hidden)]
        self.tidy_soon(pkey, vocab)
        self.tags_sort_soon(pkey)
        note = self.tag_note.get(pkey)
        return {"pkey": pkey, "name": self.project_label(pkey), "secs": [x for _, x in sorted(secs, key=lambda p: p[0])],
                "hidden": gone, "sug": sug, "tidy": pkey in self.tidying, "model": self.prefs()["brief"],
                "job": self.tag_jobs.get(pkey), "note": note[1] if note and time.time() - note[0] < TAG_NOTE else None}

    async def api_tags_edit(self, pkey, op, sec, topic=None, name=None, c=None, to_sec=None, to_topic=None):
        """The owner tidies the project's tags: rename a section or a topic, colour a section, merge one into another
        (a topic — into a topic of any section), hide or show again, keep a tag Claude has just made, keep apart two
        that Claude offered to merge. Names as the list has them (any case); the changes are final — the model sees
        the new list, and an old name it or a hashtag brings lands on the new tag (pult_tags.resolve). → the screen
        anew; with {"exists": {sec, topic}} instead when the new name is another tag's — the app offers to merge."""
        self.tags_pkey(pkey)
        vocab = self.store.tag_vocab(pkey)

        def at(s_, t_):
            s = next((x for x in vocab if G.key(x["n"]) == G.key(s_)), None) if isinstance(s_, str) else None
            t = next((x for x in s["topics"] if G.key(x["n"]) == G.key(t_)), None) if s and isinstance(t_, str) and t_.strip() else None
            if not s or (isinstance(t_, str) and t_.strip() and not t):
                raise ValueError(self.t("tags.e.gone", n=I.q(str(t_ or s_ or "")[:40])))
            return s, t, (s["n"], t["n"] if t else None)
        s, t, me = at(sec, topic)
        label, said = self.project_label(pkey), me[0] + (" / " + me[1] if me[1] else "")
        if op == "rename":
            new = G.norm(name, G.TOPIC_LEN if t else G.SEC_LEN)
            if not new:
                raise ValueError(self.t("tags.e.name"))
            other = next((x for x in (s["topics"] if t else vocab) if G.key(x["n"]) == G.key(new) and x is not (t or s)), None)
            if other:
                return dict(await self.api_tags(pkey), exists={"sec": s["n"] if t else other["n"], "topic": other["n"] if t else None})
            if new != (t or s)["n"]:
                self.store.tag_rename(pkey, me[0], me[1], new)
                log("tags %s: %s renamed to %s" % (label, said, new))
        elif op == "color":
            if t or not isinstance(c, int) or isinstance(c, bool) or not 0 <= c < G.COLORS:
                raise ValueError("bad colour")
            self.store.tag_color(pkey, me[0], c)
        elif op in ("merge", "apart"):
            s2, t2, them = at(to_sec, to_topic)
            if them == me or (t is None) != (t2 is None):
                raise ValueError(self.t("tags.e.merge"))
            if op == "apart":
                self.store.tag_keep(pkey, me, them)
            else:
                moved = [r["sid"] for r in self.store.db.execute(       # its latest tasks: examples of where such go now
                    "SELECT sid FROM session_tags WHERE pkey=? AND sec=? AND (? IS NULL OR topic=?) ORDER BY ts DESC LIMIT ?",
                    (pkey, me[0], me[1], me[1], MERGE_EXAMPLES))]
                self.store.tag_merge(pkey, me[0], me[1], them[0], them[1])
                for sid in moved:
                    self.tag_example_soon(pkey, sid)
                log("tags %s: %s merged into %s" % (label, said, them[0] + (" / " + them[1] if them[1] else "")))
        elif op in ("hide", "show"):
            self.store.tag_hide(pkey, me[0], me[1], op == "hide")
        elif op == "keep":
            self.store.tag_own(pkey, me[0], me[1])
        else:
            raise ValueError(self.t("err.no_request", op=op))
        self.tags_prune(pkey)
        self.changed()
        return await self.api_tags(pkey)

    def tidy_soon(self, pkey, vocab):
        """Claude looks the project's list over for two tags that name the same thing — in the background, with the
        model switched on, when the owner opens the tags screen and the names have changed since its last look."""
        if not self.prefs()["brief"] or pkey in self.tidying or sum(1 + len(s["topics"]) for s in vocab) < 3:
            return
        sig, failed = G.sig(vocab), self.tidy_failed.get(pkey)
        if (self.store.get("tags.tidy." + pkey) or {}).get("sig") == sig or \
                failed and failed[0] == sig and time.time() - failed[1] < TIDY_RETRY:
            return
        self.tidying.add(pkey)
        asyncio.create_task(self.tidy_task(pkey, sig))

    async def tidy_task(self, pkey, sig):
        try:
            async with self.brief_sem:
                vocab = self.store.tag_vocab(pkey)
                text = G.tidy_request(self.project_label(pkey), vocab, self.store.tag_uses(pkey), self.store.tag_kept(pkey))
                self.D.BRIEF_DIR.mkdir(parents=True, exist_ok=True)
                d = await G.tidy(text, self.lang(), self.D.BRIEF_DIR)
            if d is None:
                self.tidy_failed[pkey] = (sig, time.time())
                log("tags %s: no answer from the model on the list" % self.project_label(pkey))
                return
            self.store.put("tags.tidy." + pkey, {"sig": G.sig(vocab), "raw": d, "ts": time.time()})
            n = len(G.tidy_pairs(d, vocab, self.store.tag_kept(pkey), self.store.tag_hidden(pkey)))
            log("tags %s: the list looked over — %d to merge" % (self.project_label(pkey), n))
        finally:
            self.tidying.discard(pkey)
            self.changed()

    # ----- the project's earlier tasks get their tags (stage T, T2; Q93), and "Sort them again" -----

    def tags_sort_soon(self, pkey):
        """The project's earlier tasks without tags get them once, by themselves, when the owner opens the project or
        its tags with the model on (Q93: the filter sees the whole history); a "Sort them again" a restart cut short
        goes on the same way. One job a project, in the background; a model that gave nothing — not again at once."""
        if not self.prefs()["brief"] or pkey in self.tag_jobs or self.D.skip_pkey(pkey) or not self.project_path(pkey):
            return
        resort = self.store.get("tags.resort." + pkey)
        if self.store.get("tags.old." + pkey) and not resort:
            return
        if time.time() - self.tag_failed.get(pkey, 0) < TIDY_RETRY:
            return
        self.tag_jobs[pkey] = {"kind": "resort" if resort else "old", "done": 0, "total": 0}
        asyncio.create_task(self.tags_sort(pkey))

    async def api_tags_resort(self, pkey):
        """"Sort them again": Claude makes the project's list anew — from the start of its README and CLAUDE.md, its
        latest tasks' titles and the owner's own tags, which stay as they are — then sorts into it every task the owner
        didn't tag, in batches, "N of M" on the screen. The model off or a job running — an error. → the screen."""
        self.tags_pkey(pkey)
        if not self.prefs()["brief"]:
            raise ValueError(self.t("tags.e.model"))
        if pkey in self.tag_jobs:
            raise ValueError(self.t("tags.e.busy"))
        if not self.project_path(pkey):
            raise ValueError(self.t("err.no_project"))
        self.tag_note.pop(pkey, None)
        self.tag_jobs[pkey] = {"kind": "resort", "done": 0, "total": 0, "list": True}
        asyncio.create_task(self.tags_sort(pkey, new_list=True))
        return await self.api_tags(pkey)

    def tag_put(self, pkey, sid, got, ts=None):
        """A batch's tags for a task that has none yet — one the owner tagged meanwhile, or a turn did, stays; a tag
        the batch makes is not "new" (the owner asked for the history, not for each of its topics). → whether it took."""
        cur = self.store.session_tag(sid)
        if cur and cur["sec"]:
            return False
        at = G.place(self.store.tag_vocab(pkey), got, None, self.store.tag_aliases(pkey))
        if at is None:
            return False
        self.store.tag_add(pkey, at[0], at[1], ts=time.time() - G.FRESH - 1)
        self.store.set_session_tag(sid, pkey, at[0], at[1], False, ts=ts)
        return True

    def old_tasks(self, pkey, items, lines):
        """A batch's tasks from the SDK's list of sessions: the title, the first request, and how it ended — the
        result line Pult still keeps (lines), else the last thing Claude said, from the transcript's end. In a thread."""
        out = []
        for i, x in enumerate(items):
            said = lines.get(x.session_id)
            if not said:
                for folder in (pkey, self.D.sanitize(getattr(x, "cwd", None) or "")):
                    f = self.D.CLAUDE_PROJECTS / folder / (x.session_id + ".jsonl")
                    if folder and f.is_file():
                        said = self.D.last_reply(str(f), tail=G.SAID_TAIL)
                        break
            ask = getattr(x, "first_prompt", None) or ""
            out.append({"id": str(i + 1), "sid": x.session_id, "title": x.custom_title or x.summary or ask, "ask": ask,
                        "said": said or "", "ts": (x.last_modified or 0) / 1000 or None})
        return out

    def project_docs(self, path):
        """The start of the project's README.md and CLAUDE.md, for a new list; "" for one it hasn't. In a thread."""
        out = []
        for name in ("README.md", "CLAUDE.md"):
            try:
                with open(os.path.join(path, name), encoding="utf-8", errors="replace") as f:
                    out.append(f.read(G.DOC_LEN))
            except OSError:
                out.append("")
        return out

    async def tags_sort(self, pkey, new_list=False):
        """The job of tags_sort_soon and api_tags_resort. new_list — first a new list: Claude's old tags go (the owner's
        stay), the sections it names again keep their colours; a list the model didn't give changes nothing. Then the
        project's latest tasks without tags, BATCH at a time, each batch one request after the result lines' (brief_sem).
        Done — the project's earlier tasks are sorted (tags.old); a batch without an answer stops the job: what is left
        goes on at a later open."""
        from claude_agent_sdk import list_sessions
        job, label, path = self.tag_jobs[pkey], self.project_label(pkey), self.project_path(pkey)
        n, cut = 0, False
        try:
            self.D.BRIEF_DIR.mkdir(parents=True, exist_ok=True)
            if new_list:
                items = await asyncio.to_thread(list_sessions, path, G.LIST_TASKS)
                readme, claude_md = await asyncio.to_thread(self.project_docs, path)
                vocab = self.store.tag_vocab(pkey)
                own = [{"n": s["n"], "topics": [t for t in s["topics"] if t["own"]]} for s in vocab
                       if s["own"] or any(t["own"] for t in s["topics"])]
                dirs = await asyncio.to_thread(G.hints, path)
                titles = [t for t in (x.custom_title or x.summary or getattr(x, "first_prompt", None) for x in items) if t]
                async with self.brief_sem:
                    d = await G.make_list(G.list_request(label, readme, claude_md, titles, own, dirs, self.tag_examples_for(pkey)),
                                          self.lang(), self.D.BRIEF_DIR)
                fresh = G.new_list(d)
                if not fresh:
                    self.tag_note[pkey] = (time.time(), self.t("tags.e.list"))
                    log("tags %s: no new list from the model — nothing changed" % label)
                    return
                colors = self.store.tag_reset(pkey)
                self.store.put("tags.resort." + pkey, time.time())
                vocab, old = self.store.tag_vocab(pkey), time.time() - G.FRESH - 1
                for sec, tops in fresh:
                    s = next((x for x in vocab if G.key(x["n"]) == G.key(sec)), None)
                    name = s["n"] if s else sec
                    self.store.tag_add(pkey, name, None, ts=old, color=colors.get(G.key(name)))
                    for t in tops:
                        same = next((x["n"] for x in (s["topics"] if s else []) if G.key(x["n"]) == G.key(t)), t)
                        self.store.tag_add(pkey, name, same, ts=old)
                log("tags %s: a new list — %s" % (label, ", ".join(sec for sec, _ in fresh)))
                job.pop("list", None)
                self.changed()
            items = await asyncio.to_thread(list_sessions, path, G.OLD_MAX)
            todo = [x for x in items if not ((self.store.session_tag(x.session_id) or {"sec": None})["sec"])]
            job["total"] = len(todo)
            self.changed()
            for i in range(0, len(todo), G.BATCH):
                chunk = todo[i:i + G.BATCH]
                lines = {x.session_id: (self.attn.rec.get(x.session_id) or {}).get("line") for x in chunk}
                tasks = await asyncio.to_thread(self.old_tasks, pkey, chunk, lines)
                async with self.brief_sem:
                    vocab = self.store.tag_vocab(pkey)
                    dirs = await asyncio.to_thread(G.hints, path) if len(vocab) < G.HINT_UNDER else []
                    d = await G.batch(G.batch_request(label, vocab, tasks, dirs, self.tag_examples_for(pkey)), self.lang(),
                                      self.D.BRIEF_DIR)
                if d is None:
                    self.tag_failed[pkey], cut = time.time(), True
                    log("tags %s: no answer from the model on a batch — %d of %d tasks sorted, the rest later"
                        % (label, job["done"], job["total"]))
                    return
                got = G.batch_tags(d, {t["id"] for t in tasks})
                n += sum(1 for t in tasks if t["id"] in got and self.tag_put(pkey, t["sid"], got[t["id"]], t["ts"]))
                job["done"] += len(chunk)
                self.changed()
            self.store.put("tags.old." + pkey, {"ts": time.time(), "n": n})
            self.store.put("tags.resort." + pkey, None)
            log("tags %s: %d of %d earlier tasks sorted%s" % (label, n, len(todo), " anew" if job["kind"] == "resort" else ""))
        except Exception as e:
            self.tag_failed[pkey], cut = time.time(), True
            log("tags %s: sorting the tasks stopped — %r" % (label, e))
        finally:
            self.store.tag_prune(pkey)
            self.tag_jobs.pop(pkey, None)
            if cut and n:
                log("tags %s: %d sorted before it stopped" % (label, n))
            self.changed()

    # ----- a session: reading, writing, answering, the model, stopping -----

    async def api_session(self, sid, before=None, after=None):
        path, lv = self.transcript_of(sid)
        row = self.store.session(sid)
        lv = lv or self.stub(sid, row["pkey"] if row else Path(path).parent.name)
        # the session's last outcome, as the owner found it (before opening it marks it seen): the app shows it at
        # the end of the chat — what came out, what is needed, ready replies — until the next turn
        rec = self.attn.rec.get(sid)
        pending = [r for r in lv.pending.values() if not r.fut.done()]
        outcome = None
        if rec and lv.turn is None:
            outcome = {k: rec.get(k) for k in ("line", "need", "replies", "fail", "ts", "dur", "turn_files")}
            outcome.update(state=A.state(pending, False, lv.bg, rec), resume=self.attn.resume.get(sid),
                           reset=self.limit_reset() if rec.get("fail") == "rate_limit" else None)
        # the owner opened it: its outcome no longer calls them — unless it waits for their decision (the model's
        # "your move") or broke off: reading isn't deciding, so that stays "your move" until they answer, write to
        # the session or press "Got it" (the owner, 2026-10-20; pult_attn.needs_owner). The model reads a fresh result
        # for a few seconds, and the screen re-reads itself the moment a turn ends: that look waits for its word
        # (brief_result) — taken for "seen" at once, it put a question away unanswered (2026-10-26)
        reading = self.reading.get(sid)
        if rec and rec.get("you") and not rec.get("model") and reading and reading["ts"] == rec["ts"]:
            reading["viewed"] = True
        elif not A.needs_owner(rec):
            self.mark_seen(sid)
        page = await asyncio.to_thread(PW.transcript_page, path, before, after, lv.cwd)
        stats = await asyncio.to_thread(self.stats.get, path)
        live = self.live_item(lv)
        # open on the computer without Pult's wrapper: a message from here goes as a copy — the app says so up front
        seen = sid in self.live and not lv.driven and lv.turn is not None
        live["open"] = (seen or any(a.get("sessionId") == sid for a in await self.agents())) \
            and not live["tab"] and sid not in self.driven
        if live["open"]:
            live.update(await self.copy_why(sid))      # why it goes as a copy: the app says it when asked
        ctx = self.ctx_of(sid, (stats or {}).get("model"))
        # the model can be picked from here: a session Pult runs, a tab with Pult's wrapper, or a closed session that
        # Pult would resume; only a session open on the computer without the wrapper keeps its own
        tab = self.tab_for(sid)
        ours = sid in self.driven or not (live["open"] or live["tab"])
        switch = ours or (tab is not None and "model" in tab.caps)
        switch_effort = ours or (tab is not None and "control" in tab.caps)       # a wrapper from 0.9.9 on
        # what "Default" means here: Pult's own from Settings for a session Pult runs or would resume, Claude Code's for a tab
        pref = self.prefs()
        dflt = {"model": pref["model"], "effort": pref["effort"]} if ours else None
        # the session's own title, as on the board (its first prompt until it has a name), the project beside it
        own = self.store.session_tag(sid)
        return {"sid": sid, "title": lv.title or self.title(lv), "project": self.project_label(lv.pkey), "pkey": lv.pkey,
                "outcome": outcome, "tags": self.tags_of(sid), "tagset": self.tag_list(lv.pkey),
                "tag_auto": not (own and own["own"]),
                "live": live, "page": page, "stats": stats, "choice": self.choice.get(sid) or {}, "switch": switch,
                "switch_effort": switch_effort, "default": dflt, "stt": self.stt_state()["on"],
                "ctx": {"window": ctx[0], "max_out": ctx[1], "usable": ctx_usable(ctx[0], ctx[1])} if ctx else None,
                "pending": [self.req_item(r) for r in lv.pending.values() if not r.fut.done()],
                "out": self.out_view(sid), "second": await self.second_view(sid, rec, lv)}

    async def api_answer(self, rid, act=None, answers=None, text=None):
        req = self.req_by_rid.get(rid)
        if not req or req.fut.done():
            return {"ok": False, "note": self.t("note.decided")}
        if req.kind == "ask":
            qs = req.inp.get("questions") or []
            if not isinstance(answers or {}, dict):
                raise ValueError("bad answers")
            for i, vals in (answers or {}).items():
                i = int(i)
                if not isinstance(vals, list):
                    raise ValueError("bad answers")   # a string fell apart into letters, each an answer (A6)
                if 0 <= i < len(qs) and vals:
                    self.answer_question(req, i, [str(v)[:2000] for v in vals][:20])
            return {"ok": True}
        note = self.act(req, act, "app", text=(text or "").strip() or None)
        return {"ok": note is None, "note": note}

    async def api_send(self, sid, text, fork=False, files=None):
        """files — pictures from the app's composer; they are saved only once the way is known (a "fork?" answer
        makes the app ask and send again)."""
        text = (text or "").strip()
        if not text and not files:
            raise ValueError(self.t("err.empty"))
        path, lv = self.transcript_of(sid)
        row = self.store.session(sid)
        pkey = row["pkey"] if row else Path(path).parent.name
        cwd = (row["path"] if row else None) or self.project_path(pkey)
        if not cwd:
            raise ValueError(self.t("err.no_folder_short"))
        tab = self.tab_for(sid)
        if sid in self.driven and not getattr(self.driven[sid], "closing", False):
            how = "session"
        elif tab:
            how = "tab"
        else:
            seen = sid in self.live and not self.live[sid].driven and self.live[sid].turn is not None
            how = "fork" if seen or any(a.get("sessionId") == sid for a in await self.agents()) else "resume"
            if how == "fork" and not fork:
                return {"ok": False, "need": "fork", **await self.copy_why(sid)}
        if how in ("resume", "fork") and self.driven_full():
            raise ValueError(self.busy_driven())       # before the pictures are saved: nothing is left behind
        body = self.with_uploads(text, files, self.session_project(sid)[1])
        oid = None
        if how == "session":
            oid = self.out_add(sid, body)          # before the hand-off: its hook may come before we are back
            try:
                await self.driven[sid].say(body, None)
            except Exception:
                self.out_drop(sid, oid)
                raise
        elif how == "tab":
            oid = self.out_add(sid, body)
            try:
                await self.to_tab(tab, body, None)
            except Exception:
                self.out_drop(sid, oid)
                raise
        else:
            # a resumed session (or a copy — a new session) gets its message into the outbox in drive()
            await self.drive(sid, cwd, body, None, resume=sid if how == "resume" else None, fork=how == "fork", pkey=pkey,
                             app=True)
            if how == "resume":
                oid = next((o["id"] for o in reversed(self.outbox.get(sid) or []) if o["body"] == body), None)
        self.mark_seen(sid, body)                  # answered: the outcome is behind, and a call about it says with what
        return {"ok": True, "how": how, "out": oid}

    @staticmethod
    def check_choice(model, effort):
        model = (model or "").strip() or None
        effort = (effort or "").strip() or None
        if model and not MODEL_RE.fullmatch(model) or effort and effort not in EFFORTS:
            raise ValueError("bad model or effort")
        return model, effort

    async def api_new(self, pkey, text, files=None, model=None, effort=None):
        text = (text or "").strip()
        path = self.project_path(pkey)
        if not (text or files) or not path or not os.path.isdir(path):
            raise ValueError(self.t("err.need_project_text"))
        model, effort = self.check_choice(model, effort)
        if self.driven_full():
            raise ValueError(self.busy_driven())       # before the pictures are saved: nothing is left behind
        sid = str(uuid.uuid4())
        await self.drive(sid, path, self.with_uploads(text, files, path), None, pkey=pkey, model=model, effort=effort,
                         app=True)
        return {"ok": True, "sid": sid}

    async def api_model(self, sid, model=KEEP, effort=KEEP):
        """The model and/or the effort of a session — whichever the app sent ("" — back to the default: Pult's from
        Settings for a session Pult runs, Claude Code's settings for a tab). A session Pult runs switches at once (SDK
        set_model, apply_flag_settings), a resting or closed one starts with the choice next time; a VS Code tab with
        Pult's wrapper switches through the wrapper."""
        if not self.D.SID_RE.fullmatch(sid or ""):
            raise ValueError(self.t("err.bad_sid"))
        if model is KEEP and effort is KEEP:
            raise ValueError("no model or effort")
        m, e = self.check_choice(None if model is KEEP else model, None if effort is KEEP else effort)
        dr = self.driven.get(sid)
        tab = None if dr else self.tab_for(sid)
        # a VS Code tab: the wrapper sends the requests the tab's own controls end in (set_model — probe_model.py)
        # or ones that touch this process only (effortLevel in the flag layer — probe_effort.py); a wrapper older
        # than the request can't, and the choice isn't kept then — it would show a level the tab doesn't have
        if tab and (model is not KEEP and "model" not in tab.caps or effort is not KEEP and "control" not in tab.caps):
            raise ValueError(self.t("err.old_wrapper"))
        self.set_choice(sid, None if model is KEEP else m or "", None if effort is KEEP else e or "")
        live = False
        if dr and dr.client:
            live = True
            dm, de = self.wanted(m, e)              # "" — Pult's default, if Settings has one
            if model is not KEEP:
                await dr.client.set_model(dm)
                dr.want_model = m
            if effort is not KEEP:
                dr.want_effort = e                  # a restart takes it anyway (--effort)
                try:
                    await sdk_effort(dr.client, de)
                except Exception as x:
                    log("effort for %s: not switched live: %s" % (sid[:8], type(x).__name__))
                    live = False
        elif tab:
            if model is not KEEP:
                tab.writer.write((json.dumps({"op": "model", "model": m}) + "\n").encode())
            if effort is not KEEP:
                req = {"subtype": "apply_flag_settings", "settings": {"effortLevel": e}}
                tab.writer.write((json.dumps({"op": "control", "request": req}) + "\n").encode())
            await tab.writer.drain()
            live = True
        said = ([] if model is KEEP else ["model " + (m or "default")]) + ([] if effort is KEEP else ["effort " + (e or "default")])
        log("choice for %s: %s (%s)" % (sid[:8], ", ".join(said), "live" if live else "next start"))
        self.changed(sid)
        return {"ok": True, "live": live, "choice": self.choice.get(sid) or {}}

    # ----- a second opinion (stage M, step 1; Q104, Q105): Codex reads what the task changed -----
    # A button under a session's outcome asks Codex — OpenAI's agent, on the owner's ChatGPT subscription — to read the
    # task's changes in a read-only sandbox and write its findings (pult_codex). One review at a time; a project goes to
    # another vendor only once the owner allowed it, one tap, once (Q105 b). The review shows at the end of the session
    # until the owner puts it away: "Got it", or "Send to Claude" — the findings as a message into the same session

    async def codex_state(self):
        """Codex on this computer: {"path", "v", "ok", "why"} — why: "missing" (none here) or "version" (one Pult
        can't use) — looked up again after CODEX_TTL. Pult uses a version pult_codex.VERIFIED lists, or one whose own
        schema still has what a review needs: checked once per version, the answer kept in the store."""
        at, got = self._codex
        if got is not None and time.monotonic() - at < CODEX_TTL:
            return got
        env = dict(os.environ, **({"PULT_CODEX": self.env["PULT_CODEX"]} if self.env.get("PULT_CODEX") else {}))
        path = await asyncio.to_thread(CX.find, env)
        got = {"path": path, "v": None, "ok": False, "why": None if path else "missing"}
        if path:
            v = got["v"] = await asyncio.to_thread(CX.version, path)
            if v in CX.VERIFIED:
                got["ok"] = True
            elif v:
                seen = self.store.get("codex.checked") or {}
                if v not in seen:
                    ok, why = await asyncio.to_thread(CX.schema_ok, path)
                    seen[v] = {"ok": ok, "why": why, "ts": time.time()}
                    self.store.put("codex.checked", seen)
                    log("codex %s: %s" % (v, "its protocol has what a second opinion needs" if ok else "can't be used — " + why))
                got["ok"] = bool(seen[v]["ok"])
            if not got["ok"]:
                got["why"] = "version"
        self._codex = (time.monotonic(), got)
        return got

    def second_job(self, sid):
        """The session's second opinion as kept: running or waiting — in memory; done, failed — in the store too."""
        job = self.seconds.get(sid)
        if job is None:
            job = self.store.get("second." + sid)
            if job:
                self.seconds[sid] = job
        return job

    def second_keep(self, sid, job):
        self.seconds[sid] = job
        if job["st"] in ("done", "fail"):
            self.store.put("second." + sid, job)

    def vendors_ok(self, pkey):
        """Whether the owner let this project go to other vendors (Q105 b): its code reaches OpenAI with a second opinion."""
        return bool((self.store.get("vendors.ok") or {}).get(pkey))

    async def second_view(self, sid, rec, lv):
        """For the session's screen: can — the button under the outcome (Codex is here, the task changed files, its
        turn has ended); why — what a tap says instead ("version": a Codex Pult can't use), v — its version; job — the
        review while it runs and once done, until the owner puts it away, else None."""
        info = await self.codex_state()
        job = self.second_job(sid)
        return {"can": bool(info["path"] and rec and lv.turn is None and self.store.turn(sid)),
                "why": info["why"] if info["path"] else None, "v": info["v"],
                "job": {k: job.get(k) for k in ("st", "ts", "t0", "dur", "steps", "model", "summary", "items", "why",
                                                "text", "limits")} if job and not job.get("away") else None}

    async def api_second(self, sid, act="start", fork=False):
        """act: start — ask Codex (→ {"need": "allow", "project"} when the project isn't allowed yet); allow — allow
        the project and start; cancel — stop it; away — "Got it"; send — the findings into the session (api_send: a
        session open on the computer without the wrapper answers {"need": "fork"} the same way)."""
        path, lv = self.transcript_of(sid)
        pkey, project = self.session_project(sid)
        if act == "away":
            job = self.second_job(sid)
            if job:
                job["away"] = True
                self.second_keep(sid, job)
                self.changed(sid)
            return {"ok": True}
        if act == "cancel":
            task = self.second_tasks.get(sid)
            if task:
                task.cancel()
            return {"ok": True}
        if act == "send":
            job = self.second_job(sid)
            if not job or job.get("st") != "done" or not job.get("items") or job.get("away") or job.get("sending"):
                return {"ok": False, "note": self.t("note.decided")}          # a second tap, or another screen did it
            # taken before the hand-off, which waits: requests run side by side, and a tap in a second window during
            # it sent the same findings twice (Codex's own second opinion on this, 2026-10-30); let go when it fails
            job["sending"] = True
            try:
                res = await self.api_send(sid, CX.message(job["items"], job.get("model")), fork=fork)
            finally:
                job.pop("sending", None)
            if res.get("ok"):
                job["away"] = job["sent"] = True
                self.second_keep(sid, job)
                log("second opinion %s: sent to Claude (%d findings)" % (sid[:8], len(job["items"])))
                self.changed(sid)
            return res
        if act not in ("start", "allow"):
            raise ValueError("bad act")
        if not project:
            raise ValueError(self.t("err.no_folder_short"))
        info = await self.codex_state()
        if not info["ok"]:
            raise ValueError(self.t("second.err." + (info["why"] or "missing"), v=info["v"] or "?"))
        if lv and lv.turn is not None:
            raise ValueError(self.t("second.err.turn"))
        if act == "allow":
            ok = self.store.get("vendors.ok") or {}
            ok[pkey] = time.time()
            self.store.put("vendors.ok", ok)
            log("app: project %s may go to other vendors (a second opinion asked there)" % pkey)
        elif not self.vendors_ok(pkey):
            return {"ok": False, "need": "allow", "project": self.name_of(pkey)}
        job = self.second_job(sid)
        if job and job.get("st") in ("wait", "run"):
            return {"ok": True}
        job = {"st": "wait", "ts": time.time(), "pkey": pkey}
        self.second_keep(sid, job)
        self.store.put("second." + sid, None)            # the one before is replaced: a new review, the old one gone
        self.second_tasks[sid] = asyncio.create_task(self.second_run(sid, job, path, project, info))
        self.changed(sid)
        return {"ok": True}

    async def api_vendors_ok(self, pkey, on=False):
        """The project's line "Codex can read this project · Disallow" (stage M, Q105 b): the owner takes it back —
        or gives it again. → {"on"}."""
        if on and not await self.known_project(pkey):
            raise ValueError(self.t("err.no_project"))
        ok = self.store.get("vendors.ok") or {}
        if on:
            ok[pkey] = time.time()
        else:
            ok.pop(pkey, None)
        self.store.put("vendors.ok", ok)
        log("app: project %s %s" % (pkey, "may go to other vendors" if on else "stays with Claude only"))
        if not on:                           # taken back: no review of it goes on, nor starts later from the queue
            for sid, task in list(self.second_tasks.items()):
                if (self.seconds.get(sid) or {}).get("pkey") == pkey:
                    task.cancel()
        return {"on": bool(on)}

    async def second_run(self, sid, job, path, project, info):
        """One review, after any other one ends (a single Codex at a time): the task's facts, the commit it began on,
        Codex's answer read into findings; the topic hears when it's ready if the owner isn't looking (page_now)."""
        cut = False
        try:
            async with self.codex_lock:
                if not self.vendors_ok(job["pkey"]):     # taken back while it waited (Codex's second opinion, 2026-10-30)
                    cut = True
                    self.seconds.pop(sid, None)
                    log("second opinion %s: not run — the project stays with Claude only" % sid[:8])
                    return
                job.update(st="run", t0=time.time(), steps=0)
                self.changed(sid)
                facts = await asyncio.to_thread(CX.task_facts, path, project)
                base = await asyncio.to_thread(CX.git_base, project, facts["t0"])
                text = CX.instructions(facts, base, self.lang(), rules=os.path.isfile(os.path.join(project, "CLAUDE.md")))
                env = {k: v for k, v in os.environ.items() if not k.startswith("PULT_")}

                def step(n):
                    job["steps"] = n
                    self.changed(sid)
                got = await CX.review(info["path"], project, text, env=env, on_step=step, client=self.D.VERSION)
                read = CX.parse(got["text"], project)
                job.update(st="done", dur=time.time() - job["t0"], model=got["model"], summary=read["summary"],
                           items=read["items"], limits=got["limits"])
                log("second opinion %s: Codex %s (%s), %d findings, %d commands, %.0f s%s" % (
                    sid[:8], info["v"], got["model"], len(read["items"]), job["steps"], job["dur"],
                    "; declined: " + ", ".join(got["asked"]) if got["asked"] else ""))
        except asyncio.CancelledError:
            cut = True
            self.seconds.pop(sid, None)
            log("second opinion %s: %s" % (sid[:8], "stopped by the owner" if self.vendors_ok(job["pkey"])
                                            else "stopped — the project stays with Claude only"))
        except CX.CodexError as e:
            job.update(st="fail", why=e.kind, text=R.short(e.text, 300), dur=time.time() - job.get("t0", job["ts"]))
            log("second opinion %s: Codex didn't — %s: %s" % (sid[:8], e.kind, e.text[:300]))
        except Exception as e:
            job.update(st="fail", why="failed", text=R.short(repr(e), 300), dur=time.time() - job.get("t0", job["ts"]))
            log("second opinion %s: failed — %r" % (sid[:8], e))
        finally:
            self.second_tasks.pop(sid, None)
            if not cut:
                self.second_keep(sid, job)
            self.changed(sid)
        if not cut:
            await self.second_told(sid, job)

    async def second_told(self, sid, job):
        """The topic hears that a second opinion is ready — its findings by name, the rest in the app — only when the
        owner isn't looking (page_now: the same rule as a "your move")."""
        try:
            if not self.chat or not await self.page_now():
                return
            lv = self.live.get(sid) or self.stub(sid, job.get("pkey"))
            head = "👁 <b>%s</b> · " % R.esc(lv.title or self.title(lv))         # as the session's screen names it
            items = job.get("items") or []
            if job["st"] == "fail":
                text = head + self.t("second.tg.fail", why=R.esc(self.t("second.why." + job.get("why", "failed"))))
            elif not items:
                text = head + self.t("second.tg.none")
            else:
                text = head + self.t("second.tg.done", n=len(items), findings=I.plural(len(items), "finding")) + "\n" + \
                    "\n".join("%d. %s" % (n, R.esc(R.short(it["title"], 140))) for n, it in enumerate(items[:SECOND_LINES], 1)) + \
                    ("\n…" if len(items) > SECOND_LINES else "")
            row = self.app_row(sid, self.t("btn.details"))
            await self.send(job.get("pkey") or lv.pkey, text, buttons=[row] if row else None, notify=True, sid=sid,
                            kind="second")
        except Exception as e:
            log("second opinion %s: the topic not told — %r" % (sid[:8], e))

    async def api_resume_at(self, sid, at=None):
        """"Continue when the usage limit resets": at that time (a minute after it) Pult says CONTINUE in the session,
        the way the owner's own message would go; at=None cancels. at=0 — the 5-hour window's reset, as last read."""
        if not self.D.SID_RE.fullmatch(sid or ""):
            raise ValueError(self.t("err.bad_sid"))
        if at is None:
            self.attn.resume.pop(sid, None)
            self.attn.save()
            self.changed(sid)
            return {"ok": True, "at": None}
        at = float(at or 0) or self.limit_reset()
        if not at:
            try:
                await self.usage(force=True)
            except Exception as e:
                log("usage for the reset time:", repr(e))
            at = self.limit_reset()
        if not at:
            raise ValueError(self.t("err.no_reset"))
        at = max(at, time.time()) + 60
        self.attn.resume[sid] = at
        self.attn.save()
        r = self.attn.rec.get(sid)
        if r and r.get("page"):                    # from the call's button or from the app — decided either way
            self.fold_page(sid, r, R.esc(self.t("note.resume", hm=time.strftime("%H:%M", time.localtime(at)))))
        self.changed(sid)
        log("continue %s at %s" % (sid[:8], time.strftime("%H:%M", time.localtime(at))))
        return {"ok": True, "at": at}

    async def api_stop(self, sid):
        dr = self.driven.get(sid)
        if not dr or not dr.client:
            return {"ok": False, "note": self.t("stop.only_driven")}
        if await dr.stop():
            log("stop: session %s, waiting messages dropped" % sid[:8])
        return {"ok": True}

    async def api_jump(self, sid):
        """"Start now": a turn waiting in the queue goes over the MAX_RUNNING limit, once."""
        dr = self.driven.get(sid)
        if not dr or dr.queued is None:
            return {"ok": False, "note": self.t("note.not_queued")}
        dr.jump.set()
        return {"ok": True}

    # ----- a new project from the phone (stage S) -----

    @staticmethod
    def tilde(path):
        root = os.path.realpath(NEW_ROOT)
        return "~" + path[len(root):] if path == root or path.startswith(root.rstrip(os.sep) + os.sep) else path

    def new_parent(self):
        """Where the picker opens: the place the last project went into, else ~/Documents, else home."""
        for p in (self.store.get("new_parent"), str(NEW_ROOT / "Documents"), str(NEW_ROOT)):
            if p and os.path.isdir(p) and N.inside(p, NEW_ROOT):
                return os.path.realpath(p)
        return str(NEW_ROOT)

    def place(self, path):
        """A folder the owner picked: an existing one inside NEW_ROOT, links followed; else a refusal."""
        p = os.path.realpath(os.path.expanduser(path)) if path else self.new_parent()
        root = os.path.realpath(NEW_ROOT)
        hidden = any(x.startswith(".") for x in os.path.relpath(p, root).split(os.sep)) if N.inside(p, NEW_ROOT) and p != root else False
        if not (os.path.isdir(p) and N.inside(p, NEW_ROOT)) or hidden:
            raise ValueError(self.t("new.err.where"))     # ~/.ssh, ~/.claude: the picker never shows them (A5)
        return p

    async def api_dirs(self, path=None, into=None):
        """The folder picker of a new project: the folders in one place (into — one of them, a step down), a step up,
        whether tabs are covered there."""
        p = self.place(path)
        if into is not None:
            if into not in await asyncio.to_thread(N.dirs, p):
                raise ValueError(self.t("new.err.where"))
            p = self.place(os.path.join(p, into))
        root = os.path.realpath(NEW_ROOT)
        return {"path": p, "show": self.tilde(p), "up": None if p == root else os.path.dirname(p),
                "dirs": await asyncio.to_thread(N.dirs, p), "tabs": self.tab_folder(p)}

    async def api_folder(self, title=None, link=None):
        """The folder's name the app shows under the title as it is typed: from the title, else from a clone link."""
        if (title or "").strip():
            return {"name": N.folder_name(title)}
        src = N.repo(link)
        return {"name": src[1] if src and not N.bad_name(src[1]) else ""}

    def key_taken(self, pkey, dest):
        """Another folder already answers to this project key (Claude Code turns every character but Latin letters
        and digits into "-"): its path, else None. A key of a folder that is gone is free — it was this path or none."""
        row = self.store.topic(pkey)
        if row and row["path"] and row["path"] != dest and os.path.isdir(row["path"]):
            return row["path"]
        if (self.D.CLAUDE_PROJECTS / pkey).is_dir():
            other = self.D.decode_pkey(pkey)
            if other and other != dest and os.path.isdir(other):
                return other
        return None

    async def api_create(self, title=None, name=None, parent=None, how="empty", about=None, link=None, text=None,
                         files=None, model=None, effort=None, big=False):
        """A new project: a folder with git (how=empty), the same with a first turn that writes CLAUDE.md from the
        owner's description (describe), or a clone (clone — a job, the app asks api_job). Its topic in the group
        comes at once, named by the title; a first task starts a session there, as "+" does. Nothing that exists
        is touched: a taken folder or project key is a refusal."""
        title, about, text = (title or "").strip(), (about or "").strip(), (text or "").strip()
        given = title                   # a clone without a title: the folder keeps the repository's name as it is
        if how not in ("empty", "describe", "clone"):
            raise ValueError(self.t("err.no_request", op="create"))
        src = None
        if how == "clone":
            src = N.repo(link)
            if not src:
                raise ValueError(self.t("new.err.link"))
            title = title or src[1]
            if not shutil.which("git"):
                raise ValueError(self.t("new.err.git"))
        if how == "describe" and not about:
            raise ValueError(self.t("new.err.about"))
        if not title:
            raise ValueError(self.t("new.err.title"))
        name = (name or "").strip() or (await self.api_folder(given, link if how == "clone" else None))["name"]
        if N.bad_name(name):
            raise ValueError(self.t("new.err.name"))
        model, effort = self.check_choice(model, effort)
        parent = self.place(parent)
        dest = os.path.join(parent, name)
        if os.path.lexists(dest):
            raise ValueError(self.t("new.err.exists", name=name))
        pkey = self.D.sanitize(dest)
        other = self.key_taken(pkey, dest)
        if other:
            raise ValueError(self.t("new.err.key", other=self.tilde(other)))
        # the first turn's words, once the folder is there: a file from the app goes into the new project's inbox
        first = ((lambda: N.describe_prompt(title, about)) if how == "describe" else
                 (lambda: self.with_uploads(text, files, dest)) if text or files else None)
        done = lambda git: self.project_made(pkey, dest, title, parent, how, first, model, effort, git)
        if how == "clone":
            if not big:
                mb = await self.repo_mb(src[2])
                if mb and mb > N.BIG_MB:
                    return {"big": mb}
            jid = secrets.token_hex(6)
            self.clones = {k: j for k, j in self.clones.items() if time.time() - j["t0"] < 3600}
            self.clones[jid] = {"state": "run", "t0": time.time(), "step": None, "name": name}
            log("new project: cloning %s into %s" % (src[0], dest))
            asyncio.create_task(self.clone(jid, src[0], dest, done))
            return {"job": jid}
        try:
            os.mkdir(dest)
        except FileExistsError:                       # a second tap, or a second window, a moment later (A7)
            raise ValueError(self.t("new.err.exists", name=name)) from None
        return await done(await self.git_init(dest))

    async def api_job(self, job):
        j = self.clones.get(str(job))
        if not j:
            raise ValueError(self.t("new.err.job"))
        return dict({k: v for k, v in j.items() if k != "t0"}, sec=int(time.time() - j["t0"]))

    async def git_init(self, dest):
        """An empty git repository in a new project; False — no git here (the folder stays, the app says so)."""
        if not shutil.which("git"):
            return False
        try:
            p = await asyncio.create_subprocess_exec("git", "init", "-q", dest, stdin=asyncio.subprocess.DEVNULL,
                                                     stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE)
            _, err = await asyncio.wait_for(p.communicate(), 30)
        except (OSError, asyncio.TimeoutError) as e:
            log("new project: git init: %r" % e)
            return False
        if p.returncode:
            log("new project: git init: %s" % err.decode(errors="replace").strip()[-200:])
        return p.returncode == 0

    async def repo_mb(self, slug):
        """A GitHub repository's size in MB before a clone (gh with the owner's login, else the public API); None —
        unknown (another host, no network): cloned without asking."""
        if not slug:
            return None
        kb = None
        if shutil.which("gh"):
            out = (await self._run("gh", "api", "repos/" + slug, "--jq", ".size", timeout=10)).strip()
            kb = int(out) if out.isdigit() else None
        if kb is None:
            def public():
                import urllib.request
                with urllib.request.urlopen("https://api.github.com/repos/" + slug, timeout=8) as r:
                    return json.loads(r.read()).get("size")
            try:
                kb = await asyncio.to_thread(public)
            except Exception:
                return None
        return round(kb / 1024) if isinstance(kb, int) else None

    async def clone(self, jid, url, dest, done):
        """git clone of a new project, at a lower priority, for N.CLONE_LIMIT at most; its progress goes to the job.
        A failed clone removes what it made itself; one stopped by the limit is removed here — the folder did not
        exist before (api_create checked), so it is Pult's own."""
        job = self.clones[jid]
        cmd = ["git", "clone", "--progress", "--", url, dest]
        if os.name != "nt" and shutil.which("nice"):
            cmd = ["nice", "-n", "10"] + cmd
        env = dict(os.environ, GIT_TERMINAL_PROMPT="0", GCM_INTERACTIVE="never")
        tail = ""
        try:
            p = await asyncio.create_subprocess_exec(*cmd, stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.DEVNULL,
                                                     stderr=asyncio.subprocess.PIPE, env=env)

            async def pump():
                nonlocal tail
                while True:
                    b = await p.stderr.read(4096)
                    if not b:
                        return
                    tail = (tail + b.decode(errors="replace"))[-4000:]
                    job["step"] = N.progress(tail) or job["step"]
            try:
                await asyncio.wait_for(asyncio.gather(pump(), p.wait()), N.CLONE_LIMIT)
            except asyncio.TimeoutError:
                p.kill()
                await p.wait()
                await asyncio.to_thread(shutil.rmtree, dest, True)
                log("new project: clone stopped after %d s: %s" % (N.CLONE_LIMIT, url))
                job.update(state="fail", error=self.t("new.err.slow", min=N.CLONE_LIMIT // 60))
                return
            if p.returncode:
                why = [ln.strip() for ln in re.split(r"[\r\n]+", tail) if ln.strip().startswith(("fatal:", "error:"))]
                log("new project: clone failed: %s" % (why[-1] if why else p.returncode))
                job.update(state="fail", error=self.t("new.err.clone", why=(why[-1] if why else "git %s" % p.returncode)[:200]))
                return
            job.update(state="done", **await done(True))
        except Exception as e:
            log("new project: clone: %r" % e)
            job.update(state="fail", error=self.t("new.err.clone", why=type(e).__name__))

    async def project_made(self, pkey, dest, title, parent, how, first, model, effort, git):
        """The folder is there: remember the project under its title, open its topic, start the first turn."""
        row = self.store.topic(pkey)
        self.store.set_topic(pkey, dest, title, row["thread"] if row and row["path"] == dest else None)
        self.store.put("new_parent", parent)
        log("new project: %s (%s%s)" % (dest, how, "" if git else ", no git"))
        try:
            await self.thread_for(pkey, dest)
        except Exception as e:
            log("new project: topic: %r" % e)
        self.changed(None)
        out = {"pkey": pkey, "git": git}
        try:
            first = first() if first else None
        except ValueError:
            first = None                                   # nothing of the first turn survived (only a broken file)
        if first and self.driven_full():
            out["busy"] = self.busy_driven()           # the project is there; its first turn has no place now
        elif first:
            sid = str(uuid.uuid4())
            if how == "describe":
                self.live_of(sid, pkey).title = self.t("new.describe.session")
            await self.drive(sid, dest, first, None, pkey=pkey, model=model, effort=effort, app=True)
            out["sid"] = sid
        return out

    # ----- files from and to the phone (stage F) -----

    async def api_inbox(self, name, pkey=None):
        """A picture from the owner's inbox for the app's chat: <month>/<file> inside Pult's own inbox folder (the app's
        screenshots, Telegram photos outside a project), or with pkey <date>/<file> inside that project's inbox/ (files
        from Telegram, stage F); only real images."""
        if pkey:
            root = self.project_path(pkey)
            if not root or not re.fullmatch(r"\d{4}-\d{2}-\d{2}/[^/\\]{1,%d}" % F.NAME_MAX, str(name or "")):
                raise ValueError(self.t("err.no_request", op="inbox"))
            base = Path(root) / F.INBOX
        else:
            if not re.fullmatch(r"\d{4}-\d{2}/[\w.-]{1,80}", str(name or "")):
                raise ValueError(self.t("err.no_request", op="inbox"))
            base = self.D.HOME / "inbox"
        p = (base / name).resolve()
        if not str(p).startswith(str(base.resolve()) + os.sep) or not p.is_file() or p.stat().st_size > self.D.UPLOAD_MAX:
            raise ValueError(self.t("err.no_transcript"))
        blob = await asyncio.to_thread(p.read_bytes)
        kind = self.D.image_kind(blob)
        if not kind:
            raise ValueError(self.t("err.no_transcript"))
        return {"kind": kind, "data": base64.b64encode(blob).decode()}

    async def api_send_files(self, sid, paths, zip=False):
        """The app's "To Telegram" on the screen of a turn's files (paths inside the project): the same checks as pult
        send. zip — as one archive; more than SEND_MANY files always go as one (decision Q44)."""
        pkey, project = self.session_project(sid) if self.D.SID_RE.fullmatch(sid or "") else (None, None)
        if not project:
            raise ValueError(self.t("send.err.session"))
        paths = [os.path.join(project, str(p)) for p in (paths or []) if p]
        if zip or len(paths) > F.SEND_MANY:
            res = await self.send_zip(sid, pkey, project, paths[:F.TURN_FILES_MAX])
        else:
            res = await self.send_files(sid, pkey, project, paths)
        if not res["sent"]:
            raise ValueError("; ".join("%s — %s" % (n, why) for n, why in res["refused"]) or self.t("send.err.nothing"))
        root = os.path.realpath(project)
        res["sent"] = [os.path.relpath(p, root) for p in res.pop("paths")]       # the app marks them by their paths
        return res

    async def api_turn_files(self, sid, turn=None):
        """The screen of a turn's files (stage F4): a session's turn that made or changed files — the latest one, or
        the one asked — each file as it is now (gone, or its size today), and the turns before and after it."""
        if not self.D.SID_RE.fullmatch(sid or ""):
            raise ValueError(self.t("send.err.session"))
        r = self.store.turn(sid, int(turn) if turn not in (None, "") else None)
        if not r:
            return {"id": None, "files": []}
        project = self.project_path(r["pkey"])
        files = []
        for f in r["files"]:
            p = os.path.join(project, f["p"]) if project else None
            files.append(dict(f, size=os.path.getsize(p), gone=False) if p and os.path.isfile(p) else dict(f, gone=True))
        row = self.store.session(sid)
        return {"id": r["id"], "start": r["start"], "ts": r["ts"], "dur": r["dur"], "n": r["n"], "files": files,
                "prev": r["prev"], "next": r["next"], "project": self.project_label(r["pkey"]),
                "title": (row["title"] if row else None) or ""}

    async def api_file(self, sid, p="", base=""):
        """A project's file or folder for the app's screen — a link in Claude's words tapped there (stage F5). p — the
        path as the link gives it, from the project's folder or, with base, from the folder of the project file whose
        page the link sits in. The rule is Telegram's: inside the project, nothing like keys or settings. → {p: the path
        inside the project ("" — its folder), kind: dir | pic | md | html | text | other, and entries | data | text}."""
        pkey, project = self.session_project(sid) if self.D.SID_RE.fullmatch(sid or "") else (None, None)
        if not project:
            raise ValueError(self.t("send.err.session"))
        path = F.link_target(project, p, base)
        why = F.why_not_show(path, project)
        if why:
            raise ValueError(self.t(why))
        root, real = os.path.realpath(project), os.path.realpath(path)
        rel = "" if real == root else os.path.relpath(real, root).replace(os.sep, "/")
        head = {"p": rel, "project": self.project_label(pkey)}
        if os.path.isdir(real):
            entries, n = await asyncio.to_thread(F.show_dir, real)
            return dict(head, kind="dir", entries=entries, n=n)
        got = await asyncio.to_thread(F.show_file, real)
        if "data" in got:
            got["data"] = base64.b64encode(got["data"]).decode()
        return dict(head, **got)

    # ----- voice: words from a recording (pult_stt) -----

    async def api_stt(self, data, mime=None, notes=None):
        """A recording from the app → its words (the app puts them into the message field). Nothing is kept. notes —
        how the recording went, from the app's level meter, for the log: whether the start of the words got lost."""
        try:
            blob = base64.b64decode(str(data or ""), validate=True)
        except (ValueError, binascii.Error):
            raise ValueError(self.t("stt.e.format", kind="?")) from None
        if not blob or len(blob) > STT_MAX:
            raise ValueError(self.t("stt.e.big"))
        try:
            text = await self.hear(blob, mime or "audio/webm")
        except STT.SttError as e:
            raise ValueError(self.stt_why(e)) from None
        log("voice from the app: %d KB%s → %d characters (%s)" % (len(blob) // 1024, self.stt_notes(notes), len(text),
                                                                  getattr(self.stt, "model", "?")))
        return {"text": text}

    @staticmethod
    def stt_notes(n):
        """The app's figures of one recording as a piece of the log line; anything odd is left out. secs — its
        length; asked — ms the phone took to give the microphone when the app asked for it anew (Telegram on Android
        asks the owner every time: then the tap's time is the owner's); ready — ms from the microphone given (the tap,
        when it was kept) until sound came; voice — ms from then until the first loud window (0: the
        owner was already speaking, the start may be lost); first — the loudest dB in that first second; peak — the
        loudest overall."""
        if not isinstance(n, dict):
            return ""
        num = lambda k, lo, hi: n.get(k) if isinstance(n.get(k), (int, float)) and lo <= n[k] <= hi else None
        out = []
        if num("secs", 0, 3600) is not None:
            out.append("%.0f s" % n["secs"])
        asked = num("asked", 0, 600000) is not None
        if asked:
            out.append("microphone asked anew: %.1f s" % (n["asked"] / 1000))
        if num("ready", 0, 60000) is not None:
            out.append("sound %.2f s after %s" % (n["ready"] / 1000, "it" if asked else "the tap"))
        if num("voice", 0, 3600000) is not None:
            out.append("voice from +%.1f s" % (n["voice"] / 1000))
        elif n.get("voice") is None and "voice" in n:
            out.append("no voice heard")
        if num("first", -200, 10) is not None:
            out.append("first second %.0f dB" % n["first"])
        if num("peak", -200, 10) is not None:
            out.append("loudest %.0f dB" % n["peak"])
        return ", " + ", ".join(out) if out else ""

    async def api_stt_words(self, words=""):
        """The owner's own words for Whisper (Settings → Voice input): names and terms, comma-separated; "" clears."""
        w = ", ".join(x for x in (" ".join(p.split()) for p in re.split(r"[,;\n]", str(words or ""))) if x)
        if len(w) > STT_WORDS_MAX:                                    # whole words only
            w = w[:STT_WORDS_MAX]
            w = w[:max(w.rfind(","), w.rfind(" "))].rstrip(" ,")
        self.store.put("stt_words", w)
        log("voice input: own words %s" % ("set (%d characters)" % len(w) if w else "cleared"))
        return {"words": w}

    async def api_stt_key(self, key=""):
        """The Groq key from the app's settings: checked with Groq, then written to the settings file on this
        computer (never into state the app can read back); "" removes it. Takes effect at once."""
        key = str(key or "").strip()
        if key:
            if not re.fullmatch(STT.KEY_CHARS, key):
                raise ValueError(self.t("stt.e.key"))
            probe = STT.Stt(key, proxy=self.env.get("PULT_PROXY") or None)
            try:
                await probe.check()
            except STT.SttError as e:
                raise ValueError(self.stt_why(e)) from None
            finally:
                await probe.aclose()
        from pult_setup import write_env           # the same careful writer the command line uses
        write_env(PULT_STT_KEY=key or None)
        self._env_mt = self.D.env_mtime()
        if key:
            self.env["PULT_STT_KEY"] = key
        else:
            self.env.pop("PULT_STT_KEY", None)
        old, self.stt = self.stt, self.make_stt()
        self.drop_stt(old)
        log("voice input from the app: key %s" % ("set" if key else "removed"))
        return {"on": bool(self.stt)}

    # ----- usage and spend (stage R) -----

    async def api_usage(self, force=False):
        return await self.usage(bool(force))

    async def api_today(self):
        """Today's tokens per project, for the Usage screen; kept apart from get_usage, since that one may break."""
        d = await asyncio.to_thread(self.spend.today)
        for r in d["projects"]:
            r["name"] = await self.spend_name(r["pkey"])
        return d

    async def spend_name(self, pkey):
        if pkey not in self._pnames:
            path = None if self.store.topic(pkey) else await asyncio.to_thread(self.D.decode_pkey, pkey)
            self._pnames[pkey] = self.project_name(pkey, path) if path else self.project_label(pkey)
        return self._pnames[pkey]

    async def spend_view(self, u):
        """The Resources screen (stage R) from a usage reading: the curve, pace and forecast of the 5-hour window
        and the week, who spent them. Named projects and their colours: a project keeps its colour (one of COLORS
        slots), the five biggest of a view get one — a slot goes to a project not seen for longest."""
        known = self.store.get("spend_known") or {}
        log_ = self.store.usage_log(time.time() - 8 * 86400)
        v = await asyncio.to_thread(self.spend.view, u, log_, None, self.prefs()["pace"], known)
        self.store.put("spend_known", v.pop("known"))
        colors = self.store.get("spend_colors") or {}        # pkey → [slot, last time it was among the five]
        now = time.time()
        for lim in v["limits"]:
            top = [p for p, _, _ in lim["projects"][:SPEND_COLORS]]
            for pkey in top:
                if pkey in colors:
                    colors[pkey][1] = now
            for pkey in top:
                if pkey not in colors:
                    taken = {c[0]: k for k, c in colors.items()}
                    free = [i for i in range(SPEND_COLORS) if i not in taken]
                    if not free:          # the slot of the project longest out of the five, not one shown now
                        old = min((k for k in colors if k not in top), key=lambda k: colors[k][1], default=None)
                        if old is None:
                            continue
                        free = [colors.pop(old)[0]]
                    colors[pkey] = [free[0], now]
            lim["projects"] = [{"name": await self.spend_name(p), "pct": round(c, 2), "sh": sh,
                                "color": colors[p][0] if p in colors and p in top else None} for p, c, sh in lim["projects"]]
        self.store.put("spend_colors", colors)
        v["others"] = [{"name": x["name"], "percent": x["percent"], "resets_at": x["resets_at"]}
                       for x in u["limits"] if x["kind"] not in S.WINDOWS]
        v["shares"] = u.get("shares") or []
        v.pop("factor")
        v.pop("per_sh_w")
        v.update(plan=u.get("plan"), ts=u.get("ts"), extra=u.get("extra"), fable_x=round(v.pop("fable_x") or 0, 1))
        self._spend = (time.time(), v)
        return v

    async def api_spend(self, force=False):
        """Resources (stage R): get_usage (kept a minute, `force` — anew) and the transcripts."""
        return await self.spend_view(await self.usage(bool(force)))

    async def spend_top(self):
        """The limit the Home strip shows — the one that runs out first, else the fuller one: from the last usage
        reading, no new request; the view is kept a minute."""
        at, v = self._spend
        if self._usage and (v is None or time.time() - at > 60):
            try:
                v = await self.spend_view(self._usage)
            except Exception as e:
                log("spend:", repr(e))
        lim = next((x for x in (v or {}).get("limits") or [] if x["key"] == v.get("top")), None)
        return {"key": lim["key"], "pct": lim["used"], "state": lim["state"]} if lim else None

    # ----- settings -----

    async def api_lang(self):
        """The language of the bot and the app — the app asks right after connecting, on any screen."""
        return self.lang()

    async def api_settings(self):
        hooks = self.hooks_on()
        try:
            with self.D.LOG_FILE.open("rb") as f:
                f.seek(0, 2)
                f.seek(max(0, f.tell() - 16000))
                lines = f.read().decode(errors="replace").splitlines()[1:]
        except OSError:
            lines = []
        idle = await self.idle()
        c = await self.update_check()
        release = bool(c.get("repo") and await asyncio.to_thread(U.release_mode, c["repo"], c.get("head")))
        if release:
            asyncio.ensure_future(self.release_look())      # opening Settings is a reason to look (once a minute)
        return {"version": self.D.VERSION, "prefs": dict(self.prefs(), lang=self.lang(), pager=self.pager()), "hooks": sorted(hooks),
                "gh": {"release": release, "at": self.gh["at"], "ok": self.gh["ok"]},
                "hooks_missing": [e for e in pult_hook.EVENTS if e not in hooks] if hooks else [],
                "mac": {"idle": idle, "away": await self.away(), "mode": self.mode()},
                "telegram": "proxy" if len(self.tg.clients) > 1 and self.tg.cur == 0 else "direct",
                "stt": self.stt_state(), "cc": self.cc_choice(),
                "log": [x for x in lines if "Bearer" not in x][-40:]}

    async def api_prefs(self, **kw):
        cur = self.prefs()
        for k, v in kw.items():
            if k in ("vehi", "brief", "pager", "gh", "vcheck", "hashtags") and isinstance(v, bool) or k == "mode" and v in self.D.MODES or k == "lang" and v in I.LANGS \
                    or k == "pace" and v in S.PACES:
                cur[k] = v
            elif k in ("model", "effort") and (v is None or isinstance(v, str)):
                m, e = self.check_choice(v if k == "model" else None, v if k == "effort" else None)
                cur[k] = m if k == "model" else e         # "" — back to Claude Code's settings
        self.store.put("prefs", cur)
        if "mode" in kw:
            await self.set_mode(cur["mode"])
        log("settings from the app:", cur)
        return cur

    async def api_logins(self):
        """The app's recent logins (Settings → Logins) and whether the app is closed by the file check."""
        if not self.web:
            return {"logins": [], "locked": None}
        return {"logins": self.web.logins.recent(), "locked": self.web.locked}

    async def api_logout_all(self):
        if self.web:
            asyncio.ensure_future(self.web.logout_all())
        return {"ok": True}
