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
import pult_changes as CH
import pult_codex as CX
from pult_driven import MAX_RUNNING   # turns at once — pult_driven's
import pult_files as F
import pult_hook
import pult_i18n as I
import pult_load as L
import pult_new as N
import pult_os
import pult_render as R
import pult_spend as S
import pult_stt as STT
import pult_tags as G
import pult_update as U
import pult_vendors as V
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
LEFT_MAX = 40              # findings the owner left, remembered for a task's next reviews
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
        pending = [self.req_item(r) for r in self.req_by_rid.values() if not r.fut.done()]
        for x in pending:                            # which model asks: a question's card says it too (Q108), and how
            x["ctx"], x["llm"] = await self.row_stats(x["sid"])      # full its context is — along its bottom edge (Q151)
            x["work"] = self.work_total(x["sid"])     # and the task's clock, stopped while it waits
        return {"mac": {"idle": idle, "away": await self.away(), "mode": self.mode(), "until": self.prefs()["mode_until"]}, "now": time.time(),
                "lang": self.lang(), "load": self.load_sum(load[2], load[3]) if load else None,
                # a session may end while this waited for the process snapshot (SessionEnd drops it): it is just gone
                # from the list — before, Home failed with KeyError until the next event (review 2026-10-27, A1)
                "live": [self.live_item(self.live[s]) for s in shown if s in self.live],
                "pending": pending, "open": opened, "recent": list(self.recent),
                "jobs": [self.job_item(j) for j in self.jobs.values()] + [self.job_item(j) for j in self.jobs_done],
                "update": await self.update_row(), "pull": self.local_pull_view(), **await self.board(agents)}

    async def api_seen(self, sid):
        """"Got it" on a card of "Your move": the outcome is seen without opening the session."""
        self.mark_seen(sid)
        return {"ok": True}

    async def api_unseen(self, sid):
        """"Bring back" in the app's note right after "Got it": the outcome waits in "Your move" again. A call about
        it in Telegram, folded by "Got it", stays folded — the owner is looking at the card."""
        if not self.attn.unseen(sid):
            return {"ok": False, "note": self.t("note.unseen_late")}
        log("outcome %s: brought back to «your move»" % sid[:8])
        self.changed(sid)
        return {"ok": True}

    def live_item(self, lv):
        t = lv.turn
        q = self.queued(lv.sid)
        return {"sid": lv.sid, "title": self.title(lv), "project": self.project_label(lv.pkey), "pkey": lv.pkey,
                "driven": lv.driven, "state": "ask" if lv.pending else "work" if t else "queue" if q else "idle",
                "queued": q, "waiting": self.driven[lv.sid].waiting if q else None, "slots": MAX_RUNNING,
                # run: when the task's clock would have started, had it never stopped — "working N" is all its work
                "started": t.started if t else None, "run": time.time() - self.work_total(lv.sid) if t else None,
                "prompt": R.short(R.prompt_text(t.prompt), 300) if t and t.prompt else None,
                "note": t.note if t else None, "now": R.plain(t.now, self.D.NOW_LEN) if t and t.now else None,
                "bg": [R.short(b.get("description") or b.get("command") or self.t("task.default"), 80) for b in lv.bg],
                "bgk": [b.get("type") or "shell" for b in lv.bg],
                "bg_since": self.bg_since(lv), "tab": bool(self.tab_for(lv.sid)), "work": self.work_total(lv.sid),
                "silent": t.silent if t else None}       # since when it makes no step and says no word

    def req_item(self, req):
        lv = self.live.get(req.sid) or self.stub(req.sid)
        d = {"rid": req.rid, "sid": req.sid, "kind": req.kind, "tool": req.tool, "title": self.title(lv),
             "project": self.project_label(lv.pkey), "suggest": bool(req.suggestions), "since": req.ts,
             "work": self.work_total(req.sid), "who": "codex" if self.store.vendor_of(req.sid) == "codex" else None}
        if req.suggestions and not d["who"]:
            d["always"] = R.always_text(req.suggestions, lv.cwd)       # what "always" would allow, in words (UX7)
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

    async def row_stats(self, sid):
        """A shown row's figures from its transcript: how full the session's context is, % — the number VS Code shows
        (the line along its card's bottom edge, Q151); a Codex task's — by Codex's own count; None if unknown — and
        which model does its work (llm_view)."""
        try:
            path, _ = self.transcript_of(sid)
        except ValueError:
            return None, self.llm_view(sid, None)
        if PW.is_codex(path):            # Codex's own figures aren't Claude Code's (stage M, M4.1): its count, its history
            return await asyncio.to_thread(PW.codex_ctx, path), self.llm_view(sid, None)
        st = await asyncio.to_thread(self.stats.get, path)
        await self.work_ready(sid, path)             # the clock has the turns from before Pult counted them (work_into)
        ctx = self.ctx_of(sid, (st or {}).get("model"))
        pct = min(100, round(st["context"] * 100 / self.ctx_room(sid, ctx))) if st and st.get("context") and ctx else None
        return pct, self.llm_view(sid, st)

    def ctx_room(self, sid, ctx):
        """How much of a session's window its context may fill: VS Code's figure; one's own model's — its server's own
        limit, the context less its answer's room (Ollama cuts a longer request silently)."""
        if self.store.vendor_of(sid) == V.LOCAL:
            return max(1, ctx[0] - ctx[1])
        return ctx_usable(ctx[0], ctx[1])

    def work_into(self, r):
        """A row's clock, again after row_stats: the turns from before Pult counted them are in it now."""
        r["work"] = self.work_total(r["sid"])
        if r["state"] == "work":
            r["since"] = time.time() - r["work"]

    def llm_view(self, sid, stats):
        """Which model does a session's work, for its row (the owner, 2026-10-30: two tasks running, one of them on
        DeepSeek — which is which?): {"model"} — Claude's, as its last request said, else the model picked for it — an
        alias as the session's Claude Code resolves it, so the label has the version (Q173); {"vendor",
        "model"} — another vendor's (stage M, step 2): as picked, else as it answered, else its main one; None — not
        known yet (no answer so far, nothing picked)."""
        model, chosen = (stats or {}).get("model"), (self.choice.get(sid) or {}).get("model")
        vid = self.store.vendor_of(sid)
        if vid == "codex":
            keep = self.store.get("codex." + sid) or {}
            got = chosen or keep.get("model") or next(iter(self.codex_models()), None)
            return {"vendor": "Codex", "model": got} if got else {"vendor": "Codex", "model": "Codex"}
        p = self.vendor_profiles().get(vid) if vid else None
        if p:
            return {"vendor": p.get("short") or p["name"], "model": chosen or model or next(iter(p["models"]), None)}
        if not model and chosen:                     # no answer yet: what the picked alias stands for there (Q173)
            model = self.cc_model_of(chosen, self.cc_version_of(sid))
        return {"model": model} if model else None

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
                r["ctx"], r["llm"] = await self.row_stats(r["sid"])
                self.work_into(r)
            projects.append({"pkey": pkey, "name": self.name_of(pkey, rs), "rows": shown, "rows_all": rs,
                             "resting": sum(1 for r in rs if A.resting(r, now)),
                             "work": sum(1 for r in rs if r["state"] in ("work", "bg", "queue")),
                             "mine": sum(1 for r in rs if r["state"] in A.MINE), "turns": turns, "secs": secs})
        mine = A.sort_rows([dict(r, project=p["name"]) for p in projects for r in p["rows_all"] if r["state"] in ("you", "fail")])
        for r in mine:                               # which model did the work and how long: its card says it too (Q108);
            r["ctx"], r["llm"] = await self.row_stats(r["sid"])      # how full its context is (Q151)
            self.work_into(r)
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

    async def api_waiting(self, but=None):
        """What waits for the owner's move, for the count on Home's tab and the line in a task about another one (review
        2026-11-11, UX1): open questions, permissions and plans, and outcomes that need the owner or broke off — not
        plain reports, and not a session that has gone on since. but — the task open now: `others` and `top` leave it
        out. → {n, others, top: the newest of the others {sid, project, what, ts} or None}."""
        rows = {}
        for req in self.req_by_rid.values():
            if not req.fut.done() and (req.sid not in rows or req.ts > rows[req.sid][0]):
                rows[req.sid] = (req.ts, req.kind, (self.live.get(req.sid) or self.stub(req.sid)).pkey)   # ask, plan, perm
        for sid, r in self.attn.rec.items():
            lv = self.live.get(sid)
            if sid in rows or r.get("seen") or not (r.get("you") or r.get("fail")) or lv and lv.turn:
                continue
            rows[sid] = (r["ts"], "fail" if r.get("fail") else "you", r["pkey"])
        others = sorted(((ts, sid, what, pkey) for sid, (ts, what, pkey) in rows.items() if sid != but), reverse=True)
        top = None
        if others:
            ts, sid, what, pkey = others[0]
            top = {"sid": sid, "project": self.name_of(pkey), "what": what, "ts": ts}
        return {"n": len(rows), "others": len(others), "top": top}

    def catchup(self):
        """"While you were away": the turns since the app was last on the screen, what is behind (put away by the owner
        or followed by another turn), what waits for them now — every outcome they haven't put away — the latest line
        per project."""
        if not self.catch_from:
            return None
        es = self.attn.since(self.catch_from)
        if not es:
            return None
        last = {}
        for e in es:
            last[e[1]] = e
        def waits(e):                                # this very outcome still waits for the owner
            r = self.attn.rec.get(e[2])
            return bool(r and r["ts"] == e[0] and A.waiting(r))
        lines = []
        for pkey, e in sorted(last.items(), key=lambda x: -x[1][0])[:4]:
            lines.append({"pkey": pkey, "sid": e[2], "name": self.name_of(pkey), "line": e[3], "you": waits(e), "fail": e[5]})
        return {"from": self.catch_from, "turns": len(es), "projects": len(last),
                "done": sum(1 for e in es if not e[5] and not waits(e)), "lines": lines,
                "mine": sum(1 for r in self.attn.rec.values() if A.waiting(r))}

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

    async def api_paste(self, how="paste", n=0, types=(), words=False, plat=""):
        """A picture pasted (⌘V / Ctrl+V) or dropped onto a message field in the app (Q127): how many files the webview
        gave and of which types, or none beside the clipboard's other types — on the Mac it is WebKit inside Telegram,
        which the stand never runs; the first real paste tells. words — the clipboard had words too: they went in
        as words, the picture was left. Every field is checked: it goes to the log."""
        ok = lambda x: isinstance(x, str) and re.fullmatch(r"[\w.+/-]{1,60}", x)
        kinds = [x for x in (types if isinstance(types, list) else [])[:8] if ok(x)]
        try:
            n = min(9, max(0, int(n)))
        except (TypeError, ValueError):
            n = 0
        plat = plat if ok(plat) else "?"
        what = "dropped" if how == "drop" else "pasted"
        log("app: %s — %s (%s; %s)%s" % (what, "%d file(s)" % n if n else "no file", ", ".join(kinds) or "no types", plat,
                                         " — the words went in, the picture was left" if words else ""))
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
                "mem_used": mac["mem_used"], "mem_total": mac["mem_total"], "mem_scope": mac.get("mem_scope", "system"),
                "claude": {"n": len(rows), "cpu": round(sum(r["cpu"] for r in rows), 1),
                           "mem": sum(r["mem"] for r in rows)}}

    async def api_memory(self):
        reading = await asyncio.to_thread(pult_os.memory)
        return dict(reading, now=time.time()) if reading else None

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
        lv, used, tasks = self.live.get(sid), set(), []
        for b in lv.bg if lv else []:
            story = None
            if b.get("type") == "subagent" and lv.transcript and re.fullmatch(r"[\w-]{1,64}", str(b.get("id") or "")):
                # a helper: what it has done so far, from its own record (Q128 б)
                path = os.path.join(os.path.splitext(lv.transcript)[0], "subagents", "agent-%s.jsonl" % b["id"])
                story = await asyncio.to_thread(self.helpers().story, path, lambda n, i: R.tool_step(n, i, lv.cwd))
            tasks.append(L.task(procs, row and row["pid"], kids, mac["cores"], b, lv.bg_seen.get(b.get("id")), used, story))
        return dict(out, session=row, tasks=tasks)

    def helpers(self):
        """The helpers' own records, each read on from where it stopped (pult_load.HelperLogs): one for the daemon."""
        if getattr(self, "_helpers", None) is None:
            self._helpers = L.HelperLogs()
        return self._helpers

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
        await self.codex_state()                    # Codex for "Who does it" (stage M, M4.1): looked up, kept a while
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
                        "turns": self.attn.day_of(pkey)[0], "pinned": pins.get(pkey, 0), "hidden": hides.get(pkey, 0),
                        # model: who does its tasks (stage M, 7.2); who — the same, for an app from before it
                        "model": self.project_model(pkey), "who": self.project_model(pkey), "vok": self.vendors_ok(pkey)})
        # the pinned first, the newest pin on top (stage Zh, Q98); then what needs you, then what works, then what
        # is open, then by recency; the hidden last — the app folds them (Q101)
        out.sort(key=lambda r: (-r["pinned"], r["hidden"] > 0, -(r["mine"] > 0), -(r["work"] + r["ask"] > 0), -(r["open"] > 0), -r["last"]))
        # stt: the app shows the microphone only with a key; create: this daemon makes new projects (stage S);
        # choice: the default model and effort from Settings, what a new task starts with when nothing is picked;
        # cc_models: the model menu of the Claude Code a new task starts on — its names with versions (Q173)
        p = self.prefs()
        # vendors: who else can do a task (stage M, step 2) — each with its key's state and models
        return {"projects": out, "stt": self.stt_state()["on"], "create": True,
                "choice": {"model": p["model"], "effort": p["effort"]}, "cc_models": self.cc_models_view(self.app_cc_version()),
                "vendors": self.vendors_list(), "vendor_all": self.vendor_all(), "codex": self.codex_view()}

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

    FIND_MAX = 60            # tasks a search shows
    EARLIER = 40             # earlier tasks a project's screen shows at first, and each "Show more" adds
    EARLIER_MAX = 2000

    async def task_index(self):
        """Every task of every project, for the search: [{sid, pkey, title, first, last}], the newest first. From the
        transcripts' own records (the SDK's list_sessions: title, summary, first prompt) and the other vendors' homes;
        229 tasks of 18 projects are listed in 0.34 s on the owner's computer (2026-11-11) — kept for 30 s."""
        at, rows = getattr(self, "_task_index", (0.0, None))
        if rows is not None and time.monotonic() - at < 30:
            return rows
        from claude_agent_sdk import list_sessions
        known = {r["pkey"]: r["path"] for r in self.store.db.execute("SELECT pkey, path FROM topics") if r["path"]}
        rows, seen = [], set()
        for _, pkey, path in await asyncio.to_thread(self.list_projects, known):
            if not path or not os.path.isdir(path):
                continue
            try:
                items = await asyncio.to_thread(list_sessions, path, self.EARLIER_MAX)
            except Exception as e:
                log("search: sessions of %s not listed — %r" % (pkey, e))
                items = []
            for x in items + await asyncio.to_thread(self.home_sessions, path, self.EARLIER_MAX):
                if x.session_id in seen:
                    continue
                seen.add(x.session_id)
                rows.append({"sid": x.session_id, "pkey": pkey, "title": str(x.custom_title or x.summary or ""),
                             "first": str(getattr(x, "first_prompt", None) or ""), "last": (x.last_modified or 0) / 1000})
        rows.sort(key=lambda r: -r["last"])
        self._task_index = (time.monotonic(), rows)
        return rows

    async def api_find(self, q, pkey=None):
        """A search of tasks (review 2026-11-11, UX4; Q180): every word of q in the task's title, or among its tags, or
        in its first request — in that order of worth; in one project (pkey) or in all that aren't hidden. → {rows:
        [{sid, pkey, project, title, last, tags, by: "title"|"tag"|"ask", ask, state}], more}."""
        words = [w for w in str(q or "").lower().split() if len(w) > 1][:8]
        if not words:
            return {"rows": [], "more": False}
        hides = {} if pkey else self.store.hides()
        tagged, out, more = {}, [], False
        for r in await self.task_index():
            if pkey and r["pkey"] != pkey or hides.get(r["pkey"]):
                continue
            tags = [g["n"] for g in self.tags_of(r["sid"], tagged)]
            title, tagline, first = r["title"].lower(), " ".join(tags).lower(), r["first"].lower()
            by = "title" if all(w in title for w in words) else \
                "tag" if all(w in title or w in tagline for w in words) else \
                "ask" if all(w in title or w in tagline or w in first for w in words) else None
            if not by:
                continue
            if len(out) >= self.FIND_MAX:
                more = True
                break
            lv, rec = self.live.get(r["sid"]), self.attn.rec.get(r["sid"])
            state = "ask" if lv and any(not x.fut.done() for x in lv.pending.values()) else "work" if lv and lv.turn else \
                "you" if A.waiting(rec) else None
            out.append({"sid": r["sid"], "pkey": r["pkey"], "project": self.name_of(r["pkey"]),
                        "title": R.short(r["title"] or r["first"] or "—", 80), "last": r["last"], "tags": tags, "by": by,
                        "ask": R.short(R.prompt_text(r["first"]), 140) if by == "ask" else "", "state": state})
        out.sort(key=lambda r: ({"title": 0, "tag": 1, "ask": 2}[r["by"]], -r["last"]))
        log("app: search — %d word(s), %d found%s" % (len(words), len(out), " in one project" if pkey else ""))
        return {"rows": out, "more": more}

    async def api_project(self, pkey, earlier=None):
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
        today = sorted([r for r in rows if r["state"] == "idle" and (r["ts"] or 0) >= midnight],     # put away by the owner
                       key=lambda r: -(r["ts"] or 0))
        for r in live + today:
            r["ctx"], r["llm"] = await self.row_stats(r["sid"])
            self.work_into(r)
        for r in mine + pending:                     # the cards that wait for the owner name the model too (Q108) and
            r["ctx"], r["llm"] = await self.row_stats(r["sid"])      # show how full its context is (Q151)
            r["work"] = self.work_total(r["sid"])
        shown = {r["sid"] for r in mine + live + today} | {r["sid"] for r in pending}
        earlier, further = [], False
        if path and os.path.isdir(path):
            from claude_agent_sdk import list_sessions
            try:
                # "Earlier" stopped at the fortieth task with no way on (review 2026-11-11, UX4): the app asks for more,
                # forty at a time; one more than asked for is read — whether there is anything further
                lim = min(self.EARLIER_MAX, max(self.EARLIER, int(earlier or self.EARLIER)))
                items = await asyncio.to_thread(list_sessions, path, lim + len(shown) + 1)
            except Exception as e:
                log("project sessions not listed:", repr(e))
                items, lim = [], self.EARLIER
            items = sorted(items + await asyncio.to_thread(self.home_sessions, path, lim + len(shown) + 1),
                           key=lambda x: -(x.last_modified or 0))
            rest = [x for x in items if x.session_id not in shown]
            further, items = len(rest) > lim, rest[:lim]
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
                "live": live, "today": today, "earlier": earlier, "earlier_more": bool(earlier) and further,
                "turns": turns, "secs": secs,
                "reset": self.limit_reset(), "stt": self.stt_state()["on"],
                "tagset": self.tag_list(pkey, list(shown) + [x["sid"] for x in earlier]),
                "tags_n": len(self.store.tag_vocab(pkey)), "tag_job": self.tag_jobs.get(pkey),
                "pinned": bool(self.store.pins().get(pkey)), "hidden": bool(self.store.hides().get(pkey)),
                # the project's model (stage M, 7.2), and whether Claude works in it on the computer though it is another's
                "model": self.model_view(self.project_model(pkey)),
                "tabwarn": any(r["ro"] and not r["driven"] for r in live + mine),
                "vendors_ok": self.vendors_ok(pkey)}

    async def api_sessions(self, pkey):
        path = self.project_path(pkey)
        if not path:
            raise ValueError(self.t("err.no_project"))
        from claude_agent_sdk import list_sessions
        items = await asyncio.to_thread(list_sessions, path, 30)
        items = sorted(items + await asyncio.to_thread(self.home_sessions, path, 30), key=lambda x: -(x.last_modified or 0))[:30]
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
                # model: Claude haiku can sort them — on in Settings, and the project lets it (stage M, 7.2: haiku)
                "hidden": gone, "sug": sug, "tidy": pkey in self.tidying, "model": self.prefs()["brief"] and self.haiku_on(pkey),
                "haiku": self.haiku_on(pkey),
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
        if not self.prefs()["brief"] or not self.haiku_on(pkey) or pkey in self.tag_jobs or self.D.skip_pkey(pkey) \
                or not self.project_path(pkey):
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
        if not self.haiku_on(pkey):                     # the project keeps its tasks from Claude haiku (stage M, 7.2)
            raise ValueError(self.t("tags.e.haiku"))
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
                items = [x for x in items if self.helper_reads(x.session_id, pkey)]      # not another model's (7.1–7.2)
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
            # another model's earlier task (one from before 7.1 is still in ~/.claude) never goes to Claude haiku, nor any
            # of a project that keeps its tasks from it (stage M, 7.2)
            todo = [x for x in items if not ((self.store.session_tag(x.session_id) or {"sec": None})["sec"])
                    and self.helper_reads(x.session_id, pkey)]
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
        # the session's last outcome: the app shows it at the end of the chat — what came out, what is needed, ready
        # replies, "Got it" while it waits — until the next turn
        rec = self.attn.rec.get(sid)
        pending = [r for r in lv.pending.values() if not r.fut.done()]
        outcome = None
        if rec and lv.turn is None:
            outcome = {k: rec.get(k) for k in ("line", "need", "replies", "fail", "ts", "dur", "turn_files")}
            outcome.update(state=A.state(pending, False, lv.bg, rec), resume=self.attn.resume.get(sid),
                           reset=self.limit_reset() if rec.get("fail") == "rate_limit" else None)
        # opening it puts nothing away: the outcome stays "your move" until the owner presses "Got it" or answers —
        # a report too (the owner, 2026-10-30: "I want to send every session I start to the checked ones myself";
        # before, a look put a report away, and so did the model's "only a report" — and a task went by unnoticed)
        codex = PW.is_codex(path)
        page = await asyncio.to_thread(PW.codex_page if codex else PW.transcript_page, path, before, after, lv.cwd)
        stats = None if codex else await asyncio.to_thread(self.stats.get, path)
        await self.work_ready(sid, path)
        if outcome:
            outcome["work"] = self.work_total(sid)       # the task's clock, stopped: all its work so far
            # what the task changed, counted from git: the line "Changes: N files +a −b" under the outcome (block 5)
            outcome["changes"] = await self.changes_brief(sid, rec.get("ts"))
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
                "ctx": {"window": ctx[0], "max_out": ctx[1], "usable": self.ctx_room(sid, ctx)} if ctx else None,
                "pending": [self.req_item(r) for r in lv.pending.values() if not r.fut.done()],
                "out": self.out_view(sid), "second": await self.second_view(sid, rec, lv), "vendor": self.vendor_view(sid),
                "cost": self.cost_view(sid, stats),
                # the model menu of the Claude Code this session runs on — a tab's own, else the app's (Q173); another
                # vendor's session has its own models
                "cc_models": None if self.store.vendor_of(sid) else self.cc_models_view(self.cc_version_of(sid)),
                # ro: another model's task than its project's — read only (stage M, 7.2; Q148): its model and the project's
                "ro": self.ro_view(sid, lv.pkey)}

    def ro_view(self, sid, pkey):
        ro = self.read_only(sid, pkey)
        return {"name": self.model_name(ro[0]), "its": self.model_name(ro[1])} if ro else None

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
        why = self.vendor_stop(sid, pkey)
        if why:
            raise ValueError(why)
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
        oid, copy = None, None
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
            # a copy is a new task: the app goes to it at once — before, the message left for a task the owner couldn't
            # see, and the old one stayed on the screen with "it will show in the list" (review 2026-11-11, UX5)
            copy = str(uuid.uuid4()) if how == "fork" else None
            await self.drive(sid, cwd, body, None, resume=sid if how == "resume" else None, fork=how == "fork", pkey=pkey,
                             app=True, copy=copy)
            if how == "resume":
                oid = next((o["id"] for o in reversed(self.outbox.get(sid) or []) if o["body"] == body), None)
        self.mark_seen(sid, body)                  # answered: the outcome is behind, and a call about it says with what
        return {"ok": True, "how": how, "out": oid, "sid": copy}          # sid — the copy's, when one was made

    @staticmethod
    def check_choice(model, effort):
        model = (model or "").strip() or None
        effort = (effort or "").strip() or None
        if model and not MODEL_RE.fullmatch(model) or effort and effort not in EFFORTS:
            raise ValueError("bad model or effort")
        return model, effort

    async def api_new(self, pkey, text, files=None, model=None, effort=None, vendor=None):
        """A new task in a project, on the project's model (stage M, 7.2): vendor — what an app from before 7.2 picked;
        another than the project's model is refused. model, effort — the model's own choice for this task."""
        text = (text or "").strip()
        path = self.project_path(pkey)
        if not (text or files) or not path or not os.path.isdir(path):
            raise ValueError(self.t("err.need_project_text"))
        if self.project_model(pkey) == "codex":
            await self.codex_state()
        vid = self.vendor_for_new(pkey, vendor)
        if vid == "codex":                                   # its own model and level of effort, checked against its list
            model = self.vendor_model(vid, model)
            effort = self.codex_effort(model or next(iter(self.codex_models()), None), effort)
        elif vid:
            model, effort = self.vendor_model(vid, model), None    # a vendor's model; the effort is Claude's own
        else:
            model, effort = self.check_choice(model, effort)
        if self.driven_full():
            raise ValueError(self.busy_driven())       # before the pictures are saved: nothing is left behind
        sid = str(uuid.uuid4())
        await self.drive(sid, path, self.with_uploads(text, files, path), None, pkey=pkey, model=model, effort=effort,
                         app=True, vendor=vid or "claude")
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
        ro = self.read_only(sid)
        if ro:                                           # another model's task than its project's: read only (7.2)
            raise ValueError(self.t("model.err.ro", name=self.model_name(ro[0]), its=self.model_name(ro[1])))
        if self.store.vendor_of(sid) == "codex":         # Codex's own models and levels (stage M, M4.1)
            return await self.codex_choice(sid, model, effort)
        m, e = self.check_choice(None if model is KEEP else model, None if effort is KEEP else effort)
        if self.store.vendor_of(sid) and effort is not KEEP:
            raise ValueError(self.t("vendor.err.effort"))         # how hard it thinks is Claude's own setting
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

    # ----- other vendors' models inside Claude Code (stage M, step 2; Q105, Q106) -----
    # DeepSeek, GLM, Kimi answer Claude Code's own protocol (pult_vendors): a session Pult runs gets the vendor's profile
    # in its environment. Only in a project the owner allowed (vendors.ok — the same as the second opinion's), only with
    # the owner's key (the settings file; never without one: the subscription's token would go there), never in a VS
    # Code tab; a session keeps its vendor (session_vendor) for its continuations and copies

    def vendor_home(self, vid, path, resume=None):
        """The Claude Code home of a session on another vendor's model (stage M, step 7.1): its own folder under Pult's
        home, with Pult's rules for it — or None: Claude's, Codex's, or a session begun before 7.1, whose transcript is in
        ~/.claude (its continuation and copy stay there: Claude Code finds a session only in its own home)."""
        if not vid or vid == "codex":
            return None
        if resume and (self.D.CLAUDE_PROJECTS / self.D.sanitize(path) / (resume + ".jsonl")).exists():
            return None
        home = self.D.HOMES / vid
        home.mkdir(parents=True, exist_ok=True)
        rules = home / "CLAUDE.md"
        text = V.home_rules(self.lang())
        if not rules.exists() or rules.read_text(encoding="utf-8") != text:
            rules.write_text(text, encoding="utf-8")
        return home

    def home_sessions(self, path, limit):
        """The sessions other vendors' models did in this folder, from their own homes — for Earlier and the list of
        sessions (the SDK's list_sessions reads ~/.claude only). Its reader of a folder is the SDK's own (private): on a
        version without it — none, said in the log."""
        try:
            from claude_agent_sdk._internal.sessions import _read_sessions_from_dir
        except ImportError:
            log("other vendors' sessions not listed: this SDK has no reader of a folder")
            return []
        out = []
        for d in sorted(self.D.HOMES.glob("*/projects/" + self.D.sanitize(path))):
            try:
                out += _read_sessions_from_dir(d, path)
            except Exception as e:
                log("sessions of %s not listed: %r" % (d.parent.parent.name, e))
        return sorted(out, key=lambda x: -(x.last_modified or 0))[:limit]

    def vendor_profiles(self):
        return V.profiles(self.store.get("vendors.conf") or {},
                          names={V.LOCAL: (self.t("vendor.local"), self.t("vendor.local.short"))})

    def vendor_key(self, vid):
        if vid == V.LOCAL:           # no key of its own: on once a check found a model Claude Code can work with
            return V.LOCAL_KEY if self.vendor_profiles()[V.LOCAL]["on"] else None
        return (self.env.get(V.key_name(vid)) or "").strip() or None if vid else None

    # ----- a project belongs to one model (stage M, step 7.2; Q138, Q143, Q146–Q148) -----
    # Every task of a project runs on its model — from the app and from Telegram, never another one in its place; the
    # owner changes it on the project's settings page while nothing runs there. The model gets the project's code because
    # the owner picked it for the project (the change says where the code goes): "may go to other vendors" (vendors.ok)
    # is a review's alone now — Codex's second opinion. A task of another model than the project's — done before a
    # change, or in a VS Code tab — is read only: open, read, copy its words; to go on, the project gets its model back

    def is_model(self, vid):
        return vid in ("claude", "codex") or vid in V.PRESETS

    def project_models(self):
        """{pkey: model} of the projects that aren't Claude's. Made once from what was there before 7.2 (models_before)."""
        got = self.store.get("proj.model")
        if not isinstance(got, dict):
            got = self.models_before()
            self.store.put("proj.model", got)
            self.store.put("vendors.default", None)        # a project's own default became its model
            log("projects' models: %s" % (", ".join("%s — %s" % kv for kv in sorted(got.items())) or "Claude everywhere"))
        return got

    def project_model(self, pkey):
        """The model a project's tasks run on: "claude", "codex" or another vendor's id."""
        vid = self.project_models().get(pkey)
        return vid if self.is_model(vid) else "claude"

    def models_before(self):
        """Each project's model when 7.2 comes (Q146): the one its new tasks went to — its own default, or the common
        one for a project allowed to go to other vendors while its key was here — else the one other model every task
        of it was on (no task of Claude's there, in Pult's store or in ~/.claude), else Claude — then left out."""
        out, decided = {}, set()
        for pkey, vid in (self.store.get("vendors.default") or {}).items():
            if self.is_model(vid):              # "Disallow" took a vendor's default away: what is left was reachable
                decided.add(pkey)
                if vid != "claude":
                    out[pkey] = vid
        common = self.store.get("vendors.all")
        if common in V.PRESETS and self.vendor_ready(common):
            for pkey in self.store.get("vendors.ok") or {}:
                if pkey not in decided:
                    out[pkey] = common
                    decided.add(pkey)
        tasks = {}
        for r in self.store.db.execute("SELECT s.sid, s.pkey, v.vendor FROM sessions s LEFT JOIN session_vendor v ON v.sid = s.sid"):
            tasks.setdefault(r["pkey"], {})[r["sid"]] = r["vendor"] or "claude"
        for pkey, by in tasks.items():
            if pkey in decided or not pkey:
                continue
            for f in (self.D.CLAUDE_PROJECTS / pkey).glob("*.jsonl"):
                by.setdefault(f.stem, "claude")              # a tab's task Pult hasn't seen is Claude's
            if len(set(by.values())) == 1 and next(iter(by.values())) != "claude":
                out[pkey] = next(iter(by.values()))
        return out

    def model_name(self, vid, short=False):
        """A model's name for the owner: "Claude", "Codex", "DeepSeek", "Local model"…"""
        if vid in (None, "claude"):
            return "Claude"
        if vid == "codex":
            return "Codex"
        p = self.vendor_profiles().get(vid)
        return (p.get("short") if short else None) or p["name"] if p else vid

    def model_why(self, vid):
        """Why a model can't take a task now — its key gone, one's own model off, Codex missing — or None. A project's
        task waits for it: Claude never takes it in its place (Q143)."""
        if vid in (None, "claude"):
            return None
        if vid == "codex":
            return None if self.codex_ready() else self.t("vendor.err.codex")
        if self.vendor_key(vid):
            return None
        return self.t("vendor.err.local.off") if vid == V.LOCAL else self.t("vendor.err.key", name=self.model_name(vid))

    def vendor_all(self):
        """The model new projects get (Settings; Q147 — before 7.2 "who does new tasks by default everywhere"): a
        vendor's id or "codex" — one that can take a task — or None: Claude."""
        vid = self.store.get("vendors.all")
        return vid if vid in V.PRESETS or vid == "codex" else None

    def task_model(self, sid):
        """The model a task ran on: "claude", "codex" or another vendor's id."""
        return self.store.vendor_of(sid) or "claude"

    def read_only(self, sid, pkey=None):
        """A task of another model than its project's (Q148): (its model, the project's) — or None, it can go on."""
        if not pkey:
            row = self.store.session(sid)
            pkey = row["pkey"] if row else None
        if not pkey:
            return None
        mine, its = self.task_model(sid), self.project_model(pkey)
        return (mine, its) if mine != its else None

    def haiku_on(self, pkey):
        """The project's helper Claude haiku — its result lines and tags (Q142): the owner's switch on its settings
        page, else on in Claude's projects and off in the rest."""
        own = (self.store.get("proj.haiku") or {}).get(pkey)
        return own if isinstance(own, bool) else self.project_model(pkey) == "claude"

    def helper_reads(self, sid, pkey):
        """Whether Claude haiku may read this task — its request and its outcome — for a result line or its tags: the
        model is on in Settings, the project's switch is on, and the task is Claude's or its project's model's: another
        model's task in it (one before a change) stays out of it (stage M, 7.1–7.2)."""
        return bool(self.prefs()["brief"] and pkey and self.haiku_on(pkey)
                    and self.task_model(sid) in ("claude", self.project_model(pkey)))

    def topic_full(self, pkey):
        """What the project's topic in Telegram gets (Q145): the request and the outcome, as before 7.2 — or, False,
        only "done" and what needs the owner, without the task's words."""
        return (self.store.get("proj.topic") or {}).get(pkey) != "done"

    def model_view(self, vid):
        """A model for the project's settings page and "Who does it": its name, what it runs as (the vendor's main
        model, Codex's own), why it can't take a task now; cloud — the project's code goes to another company."""
        p = self.vendor_profiles().get(vid) if vid in V.PRESETS else None
        sub = (p["models"][0] if p["models"] else None) if p else next(iter(self.codex_models()), None) if vid == "codex" else None
        return {"id": vid, "name": self.model_name(vid), "short": self.model_name(vid, short=True), "sub": sub,
                "why": self.model_why(vid), "local": bool(p and p.get("local")),
                "cloud": vid == "codex" or bool(p and not p.get("local"))}

    async def project_busy(self, pkey):
        """What runs in a project now — [{"sid", "title"}]: a turn or a question waiting for the owner, a queue, a
        background task or helper — in Pult's own sessions, VS Code tabs and terminals alike — and a review of it. A
        project's model changes only when nothing does (Q138), the way `pult busy` counts what a restart would break;
        a tab gone without its SessionEnd keeps its background list for ever, so that counts only while it is open."""
        alive = {a.get("sessionId") for a in await self.agents()}
        out = {}

        def add(sid):
            lv = self.live.get(sid) or self.stub(sid, pkey)
            out.setdefault(sid, {"sid": sid, "title": R.short(lv.title or self.t("session.default"), 60)})
        for sid, d in self.driven.items():
            lv = self.live.get(sid)
            if getattr(d, "closing", False) or ((lv and lv.pkey) or self.session_pkey(sid) or self.D.sanitize(d.path)) != pkey:
                continue
            if d.busy or not d.q.empty() or d.bg:
                add(sid)
        for sid, lv in self.live.items():
            if lv.pkey != pkey:
                continue
            bg = [b for b in lv.bg if b.get("status") not in R._TASK_END] if sid in self.driven or sid in alive else []
            if lv.turn is not None or bg or any(not r.fut.done() for r in lv.pending.values()):
                add(sid)
        for sid, task in self.second_tasks.items():
            if not task.done() and (self.seconds.get(sid) or {}).get("pkey") == pkey:
                add(sid)
        return list(out.values())

    async def api_projset(self, pkey):
        """A project's settings page (stage M, 7.2; slide 4 of isolation-presentation.html): its model and the ones it
        could change to, what runs in it now (a change waits for nothing to run), the helper Claude haiku, what its
        topic gets, its review, pinned and hidden, its tags."""
        if not await self.known_project(pkey):
            raise ValueError(self.t("err.no_project"))
        await self.codex_state()
        vid, own = self.project_model(pkey), (self.store.get("proj.haiku") or {}).get(pkey)
        info = self._codex[1] or {}
        return {"pkey": pkey, "name": self.name_of(pkey), "model": self.model_view(vid),
                "models": [self.model_view(v) for v in ("claude", "codex") + tuple(V.ORDER)],
                "busy": await self.project_busy(pkey), "haiku": self.haiku_on(pkey), "haiku_own": isinstance(own, bool),
                "brief": bool(self.prefs()["brief"]), "topic": "full" if self.topic_full(pkey) else "done",
                "review": {"ok": self.vendors_ok(pkey), "codex": bool(info.get("path")), "mine": vid == "codex"},
                "pinned": bool(self.store.pins().get(pkey)), "hidden": bool(self.store.hides().get(pkey)),
                "tags_n": len(self.store.tag_vocab(pkey))}

    async def api_project_model(self, pkey, model):
        """The project's model, from its settings page (Q138): only while nothing runs in it — no turn, no queue, no
        background task or helper (as `pult busy` counts them) — and to a model that can take a task now. Its helper
        Claude haiku goes back to the new model's default: on with Claude, off with the rest. The tasks of the one
        before stay where they are, read only (Q148). → the page."""
        if not await self.known_project(pkey):
            raise ValueError(self.t("err.no_project"))
        if not self.is_model(model):
            raise ValueError("bad model")
        if model == "codex":
            await self.codex_state()
        cur = self.project_model(pkey)
        if model != cur:
            why = self.model_why(model)
            if why:
                raise ValueError(why)
            busy = await self.project_busy(pkey)
            if busy:
                raise ValueError(self.t("ps.err.busy", what=busy[0]["title"]) if len(busy) == 1
                                 else self.t("ps.err.busy.n", what=busy[0]["title"], m=len(busy) - 1))
            got = dict(self.project_models())
            if model == "claude":
                got.pop(pkey, None)
            else:
                got[pkey] = model
            self.store.put("proj.model", got)
            haiku = self.store.get("proj.haiku") or {}
            if haiku.pop(pkey, None) is not None:
                self.store.put("proj.haiku", haiku)
            for sid, dr in list(self.driven.items()):     # idle processes of the model before: their tasks are read only
                row = self.store.session(sid)
                if row and row["pkey"] == pkey and self.read_only(sid, pkey):
                    dr.task.cancel()
            focus = self.focus_of(pkey)
            if focus and self.read_only(focus, pkey):      # plain text in the topic no longer goes to it
                self.clear_focus(focus)
            log("app: project %s — its model %s → %s" % (pkey, cur, model))
            self.changed()
        return await self.api_projset(pkey)

    async def api_project_prefs(self, pkey, haiku=None, topic=None):
        """The project's own switches (7.2): the helper Claude haiku (Q142) and what its topic in Telegram gets (Q145):
        "full" — the request and the outcome, "done" — only "done" and what needs the owner. → the page."""
        if not await self.known_project(pkey):
            raise ValueError(self.t("err.no_project"))
        if haiku is not None:
            if not isinstance(haiku, bool):
                raise ValueError("bad haiku")
            got = self.store.get("proj.haiku") or {}
            got[pkey] = haiku
            self.store.put("proj.haiku", got)
            log("app: project %s — the helper Claude haiku %s" % (pkey, "on" if haiku else "off"))
        if topic is not None:
            if topic not in ("full", "done"):
                raise ValueError("bad topic")
            got = self.store.get("proj.topic") or {}
            if topic == "full":
                got.pop(pkey, None)
            else:
                got[pkey] = topic
            self.store.put("proj.topic", got)
            log("app: project %s — its topic gets %s" % (pkey, "the request and the outcome" if topic == "full" else "only “done”"))
        self.changed()
        return await self.api_projset(pkey)

    def vendor_ready(self, vid):
        """A vendor can take a task now: its key is here — or, Codex, it is here and Pult can use it."""
        return self.codex_ready() if vid == "codex" else bool(self.vendor_key(vid))

    def codex_ready(self, sure=False):
        """Codex here and usable, as last looked up (codex_state). Not looked up yet — yes, unless sure: a task's own
        start looks again (pult_driven.CodexDriven.start)."""
        got = self._codex[1]
        return bool(got.get("ok")) if got is not None else not sure

    def codex_catalog(self):
        """Codex's models with their levels of effort, its default first (its own list, kept per version):
        [{"model", "efforts", "effort"}]; [] — not known yet."""
        got = self._codex[1] or {}
        rows = (self.store.get("codex.catalog") or {}).get(got.get("v") or "")
        if rows is None:                              # kept before the levels (0.18.36): names only
            rows = [{"model": m, "efforts": [], "effort": None}
                    for m in (self.store.get("codex.models") or {}).get(got.get("v") or "", [])]
        return [r for r in rows if isinstance(r, dict) and r.get("model")]

    def codex_models(self):
        """Codex's models, its default first; [] — not known yet."""
        return [r["model"] for r in self.codex_catalog()]

    def codex_efforts(self, model=None):
        """A Codex model's own levels of effort and its default → (levels, default); the default model's when none is
        named or it isn't in the list; ([], None) — not known."""
        rows = self.codex_catalog()
        row = next((r for r in rows if r["model"] == model), None) or next(iter(rows), None)
        return (list(row.get("efforts") or []), row.get("effort")) if row else ([], None)

    def codex_levels(self):
        """For the app: each model's levels and its default → ({model: levels}, {model: default})."""
        rows = self.codex_catalog()
        return {r["model"]: list(r.get("efforts") or []) for r in rows}, {r["model"]: r.get("effort") for r in rows}

    def codex_view(self):
        """Codex for "Who does it" (stage M, M4.1): whether it can take a task, why not, its models and their levels
        of effort (the owner, 2026-10-31: "selectable effort, like Claude's")."""
        got = self._codex[1] or {}
        efforts, dflt = self.codex_levels()
        return {"ok": bool(got.get("ok")), "why": got.get("why"), "v": got.get("v"), "models": self.codex_models(),
                "efforts": efforts, "effort": dflt}

    def codex_effort(self, model, effort):
        """A level of effort the owner picked for a Codex task, checked against its model's own → it, or None (its
        default); a level the model doesn't have is refused."""
        effort = (effort or "").strip() or None
        if effort is None:
            return None
        levels, _ = self.codex_efforts(model)
        if not CX.EFFORT_RE.fullmatch(effort) or levels and effort not in levels:
            raise ValueError(self.t("vendor.err.cx_effort", e=effort, m=model or "Codex"))
        return effort

    async def codex_choice(self, sid, model, effort):
        """A Codex task's model and effort, from its screen: its own lists; Codex takes both with every turn, so they
        go with the next one. A level the new model doesn't have goes back to its default."""
        cur = self.choice.get(sid) or {}
        keep = self.store.get("codex." + sid) or {}
        m = cur.get("model") if model is KEEP else (model or "").strip() or None
        if m and not V.MODEL_RE.fullmatch(m):
            raise ValueError("bad model")
        e = cur.get("effort") if effort is KEEP else (effort or "").strip() or None
        target = m or keep.get("model") or next(iter(self.codex_models()), None)
        if e and effort is KEEP and e not in (self.codex_efforts(target)[0] or [e]):
            e = None                                  # the new model hasn't the level picked for the old one
        else:
            e = self.codex_effort(target, e)
        self.set_choice(sid, m or "", e or "")
        log("choice for %s: Codex %s, effort %s (next turn)" % (sid[:8], m or "default", e or "default"))
        self.changed(sid)
        return {"ok": True, "live": False, "choice": self.choice.get(sid) or {}}

    def vendors_list(self):
        """For the app: each vendor — its name, whether its key is here, its models (the ticked ones, the main one
        first), the helpers' one (fast), the models Pult knows for it (known) and their prices; the local model —
        "key": on, its address, what its last check found, the models that can take a task (fit), which are one
        (kin: a copy with a context and its base) and the context of each."""
        out = []
        for vid, p in self.vendor_profiles().items():
            row = {"id": vid, "name": p["name"], "key": bool(self.vendor_key(vid)), "models": p["models"],
                   "fast": p.get("fast")}
            if p.get("local"):
                found = ((self.store.get("vendors.conf") or {}).get(vid) or {}).get("found") or {}
                row.update(local=True, short=p["short"], url=p["url"], ctx=p["ctxs"], found=found, fit=p["fit"],
                           kin=V.kin(found.get("models") or []), min=V.LOCAL_CTX_MIN, copy=V.LOCAL_CTX_COPY,
                           panel=True)
            else:
                row.update(known=list(V.PRESETS[vid]["models"]), price=V.PRESETS[vid].get("price") or {})
            out.append(row)
        return out

    def vendor_view(self, sid):
        """The vendor a session runs on, for its screen: {"id", "name", "models"}, or None — Claude."""
        vid = self.store.vendor_of(sid)
        if vid == "codex":
            keep = self.store.get("codex." + sid) or {}
            models = list(dict.fromkeys([m for m in [keep.get("model")] if m] + self.codex_models()))   # its own first
            efforts, dflt = self.codex_levels()
            return {"id": "codex", "name": "Codex", "models": models, "key": self.codex_ready(), "own": True,
                    "efforts": efforts, "effort": dflt}
        p = self.vendor_profiles().get(vid) if vid else None
        return {"id": vid, "name": p["name"], "short": p.get("short") or p["name"], "models": p["models"],
                "key": bool(self.vendor_key(vid)), "local": bool(p.get("local"))} if p else None

    def cost_view(self, sid, stats):
        """What a vendor's task has cost so far, for its screen's header: V.cost over the session's tokens, or None —
        Claude's and Codex's tasks run on a subscription, and so may a vendor's (no price in its profile)."""
        vid = self.store.vendor_of(sid)
        p = self.vendor_profiles().get(vid) if vid and vid != "codex" else None
        return V.cost(p.get("price"), (stats or {}).get("by")) if p else None

    def vendor_stop(self, sid, pkey=None):
        """Why a task can't go on from here — a continuation, a copy, a message into it — or None: it is another model's
        than its project's (read only, Q148), or its model can't take it now (its key gone, one's own model off, Codex
        missing). "Disallow" stops only reviews now (7.2): before, a continuation after it sent the code again (Codex's
        second opinion on M2)."""
        ro = self.read_only(sid, pkey)
        if ro:
            return self.t("model.err.ro", name=self.model_name(ro[0]), its=self.model_name(ro[1]))
        vid = self.store.vendor_of(sid)
        if not vid or vid == "codex":
            return self.model_why(vid)
        if not self.vendor_key(vid):
            return self.t("vendor.err.local.off") if vid == V.LOCAL else self.t("vendor.err.gone", name=self.model_name(vid))
        return None

    def vendor_for_new(self, pkey, vendor=None):
        """Whose model a project's new task runs on — the project's own (Q143) → a vendor's id, or None for Claude. A
        vendor asked for that isn't the project's model is refused (an app from before 7.2 picks one per task), and so
        is a model that can't take a task now: Claude never takes it in its place."""
        vid = self.project_model(pkey)
        if vendor not in (None, "", vid):
            raise ValueError(self.t("model.err.not", name=self.model_name(vendor), its=self.model_name(vid)))
        why = self.model_why(vid)
        if why:
            raise ValueError(why)
        return None if vid == "claude" else vid

    def vendor_model(self, vid, model):
        """A model the owner picked for a vendor's session — one of its list, or a name that could be one; None — its
        main model."""
        model = (model or "").strip() or None
        if model and not V.MODEL_RE.fullmatch(model):
            raise ValueError("bad model")
        return model

    async def api_vendor_key(self, vendor, key=""):
        """A vendor's key from Settings: checked with the vendor (one token of its fast model), then written to the
        settings file on this computer — never into anything the app can read back; "" removes it."""
        p = self.vendor_profiles().get(vendor)
        if not p or p.get("local"):                  # the local model has no key: it is turned on by its check
            raise ValueError("bad vendor")
        key = str(key or "").strip()
        model, warn = None, None
        if key:
            try:
                model = await V.check_key(p, key, proxy=self.env.get("PULT_PROXY") or None)
            except V.VendorError as e:
                log("vendor %s: the key didn't pass — %s%s" % (vendor, e.kind, ": " + e.text[:120] if e.text else ""))
                if e.kind != "model":            # the key itself is good: kept, the owner fixes the models' names
                    raise ValueError(self.t("vendor.key." + e.kind, name=p["name"], why=e.text[:200])) from None
                warn = self.t("vendor.key.model", name=p["name"], why=e.text[:200])
        from pult_setup import write_env           # the same careful writer the command line uses
        write_env(**{V.key_name(vendor): key or None})
        self._env_mt = self.D.env_mtime()
        if key:
            self.env[V.key_name(vendor)] = key
        else:
            self.env.pop(V.key_name(vendor), None)
            if self.vendor_all() == vendor:          # no key, no common default to it
                self.store.put("vendors.all", None)
        log("vendor %s: key %s%s" % (vendor, "set" if key else "removed", " (%s answered)" % model if model else ""))
        self.changed()
        return {"key": bool(key), "model": model, "warn": warn}

    async def api_vendor_models(self, vendor, models="", fast=None):
        """The owner's models of a vendor (Settings → its list: the ticked ones, the starred — the main one — first,
        as a line with commas — a computer from before the list takes only that — or a list): they are a task's menu;
        fast — the helpers' model (subagents), one of them, kept while it stays ticked; "" — back to Pult's own list.
        The local model's are its server's own: only those that fit, at least one; the ones left unticked stay so
        after the next check."""
        if vendor not in V.PRESETS:
            raise ValueError("bad vendor")
        conf = self.store.get("vendors.conf") or {}
        mine = conf.setdefault(vendor, {})
        if models if isinstance(models, (list, tuple)) else str(models or "").strip():
            try:
                names = V.clean_models(models)
            except ValueError:
                raise ValueError(self.t("vendor.err.models")) from None
            if V.PRESETS[vendor].get("local"):
                fit = self.vendor_profiles()[vendor]["fit"]
                if any(m not in fit for m in names):
                    raise ValueError(self.t("vendor.err.local.models"))
                mine["off"] = [m for m in fit if m not in names]
            mine["models"] = names
            if fast in names and not V.PRESETS[vendor].get("local"):
                mine["fast"] = fast
            elif fast is not None or mine.get("fast") not in names:
                mine.pop("fast", None)
        elif V.PRESETS[vendor].get("local"):
            raise ValueError(self.t("vendor.err.local.models"))
        else:
            mine.pop("models", None)
            mine.pop("fast", None)
        self.store.put("vendors.conf", conf)
        p = self.vendor_profiles()[vendor]
        log("vendor %s: models %s, the helpers' %s" % (vendor, ", ".join(p["models"]), p.get("fast")))
        self.changed()
        return {"models": p["models"], "fast": p.get("fast"), "vendor": self.vendor_row(vendor)}

    async def api_vendor_local(self, url=None, on=True, quiet=False):
        """The local model (Settings → Other vendors → Local model). "Check and turn on": the server at url says what it
        has (V.check_local) — the models Claude Code can work with (tools) and each one's context — and it is on while
        one of them fits (its context known and at least LOCAL_CTX_MIN); the owner's ticks and star are kept, the
        starred one is the one a task gets; a model new on the server comes ticked. on=False — off: its tasks can't
        start, the common default to it goes back to Claude. quiet — the look the app takes on its own as Settings
        open, while the model is on (a model made on the server since shows at once — the owner's case, 2026-11-05):
        a server that doesn't answer changes nothing and is no error, only "down" with the words.
        → {"vendor": its row as vendors_list has it, "words"}."""
        conf = self.store.get("vendors.conf") or {}
        mine = conf.setdefault(V.LOCAL, {})
        if not on:
            mine["on"] = False
            self.store.put("vendors.conf", conf)
            if self.vendor_all() == V.LOCAL:
                self.store.put("vendors.all", None)
            log("vendor local: turned off")
            self.changed()
            return {"vendor": self.vendor_row(V.LOCAL), "words": self.t("vendor.local.offed")}
        url = str(url or self.vendor_profiles()[V.LOCAL]["url"]).strip().rstrip("/")
        if quiet and not self.vendor_profiles()[V.LOCAL]["on"]:
            return {"vendor": self.vendor_row(V.LOCAL), "words": ""}
        try:
            got = await V.check_local(url)
        except V.VendorError as e:
            log("vendor local: %s didn't pass%s — %s%s" % (url, " (a look)" if quiet else "", e.kind,
                                                            ": " + e.text[:120] if e.text else ""))
            words = self.t("vendor.local." + e.kind, url=url, why=e.text[:200])
            if quiet:
                return {"vendor": self.vendor_row(V.LOCAL), "words": "", "down": words}
            raise ValueError(words) from None
        fit = [m["name"] for m in got["models"] if V.fits(m)]
        if quiet and not fit:                 # a look never turns it off: the owner checks, and sees why
            return {"vendor": self.vendor_row(V.LOCAL), "words": "",
                    "down": self.t("vendor.local.none", min="%dK" % (V.LOCAL_CTX_MIN // 1024))}
        off = [m for m in mine.get("off") or [] if m in fit]
        keep = [m for m in mine.get("models") or [] if m in fit]                # the owner's ticks, the star first
        models = keep + [m for m in fit if m not in keep and m not in off] or fit[:1]   # a new one comes ticked
        same = got["models"] == (mine.get("found") or {}).get("models") and models == mine.get("models")
        mine.update(url=url, on=bool(fit), models=models, off=[m for m in fit if m not in models],
                    ctx={m["name"]: m["ctx"] for m in got["models"] if m["ctx"]},
                    found={"version": got["version"], "models": got["models"], "ts": time.time()})
        if quiet and same:                    # the look found what was there: only when it was seen
            self.store.put("vendors.conf", conf)
            return {"vendor": self.vendor_row(V.LOCAL), "words": ""}
        self.store.put("vendors.conf", conf)
        log("vendor local: %s — Ollama %s, models %s; %s" % (url, got["version"], ", ".join(
            "%s (%s%s)" % (m["name"], m["ctx"] or "ctx ?", "" if m["tools"] else ", no tools") for m in got["models"]),
            "on, " + mine["models"][0] if fit else "nothing fits — off"))
        if not fit and self.vendor_all() == V.LOCAL:
            self.store.put("vendors.all", None)
        self.changed()
        if fit:
            words = self.t("vendor.local.ok", v=got["version"], m=mine["models"][0],
                           ctx="%dK" % (mine["ctx"][mine["models"][0]] // 1024), n=len(fit))
        else:
            words = self.t("vendor.local.none", min="%dK" % (V.LOCAL_CTX_MIN // 1024))
        return {"vendor": self.vendor_row(V.LOCAL), "words": "" if quiet else words}

    async def api_vendor_copy(self, model):
        """A copy of one's own model with its context set (Settings → Local model → a model that doesn't fit, "Make a
        copy with 32K"): the server makes it from the model's own weights (V.make_copy), then a check finds it — it
        comes ticked. Never one more than the model was trained for, never below LOCAL_CTX_MIN. → as api_vendor_local."""
        p = self.vendor_profiles()[V.LOCAL]
        found = ((self.store.get("vendors.conf") or {}).get(V.LOCAL) or {}).get("found") or {}
        m = next((x for x in found.get("models") or [] if x.get("name") == model), None)
        if not m or not m.get("tools") or V.fits(m):
            raise ValueError(self.t("vendor.err.local.copy", name=model))
        ctx = min(V.LOCAL_CTX_COPY, m.get("max") or V.LOCAL_CTX_COPY)
        if ctx < V.LOCAL_CTX_MIN:
            raise ValueError(self.t("vendor.local.toosmall", name=model, ctx="%dK" % (ctx // 1024)))
        taken = {x.get("name") for x in found.get("models") or []}
        try:
            new = await V.make_copy(p["url"], model, ctx, taken)
        except V.VendorError as e:
            log("vendor local: a copy of %s with %d didn't come — %s%s" % (model, ctx, e.kind, ": " + e.text[:120] if e.text else ""))
            raise ValueError(self.t("vendor.local.copy.fail", name=model, why=e.text[:200] or e.kind)) from None
        log("vendor local: %s made from %s with the context %d" % (new, model, ctx))
        got = await self.api_vendor_local(p["url"])
        got["words"] = self.t("vendor.local.copied", name=new, base=model, ctx="%dK" % (ctx // 1024))
        got["made"] = new
        return got

    # ---------- the local model's panel (stage M, step 6.4; 2026-11-08) ----------
    # Resources → Local model, and Settings' card opens it: the server's disk and card, its models by their weights
    # with each family's bytes, what is in memory, a download. Ollama answers the models; the disk and the card — the
    # reader beside it (V.info_url), when there is one. Nothing here loads a model.

    def local_found(self):
        return ((self.store.get("vendors.conf") or {}).get(V.LOCAL) or {}).get("found") or {}

    def local_running(self):
        """One's own model's sessions with a turn running now: unloading or removing the model under them would cut it."""
        return [sid for sid, d in self.driven.items() if d.busy and self.store.vendor_of(sid) == V.LOCAL]

    def local_pull_view(self):
        pl = getattr(self, "local_pull", None)
        if not pl:
            return None
        task = getattr(self, "local_task", None)
        return dict(pl, run=bool(task and not task.done()))

    async def api_local_panel(self, peek=False):
        """The local model's panel: the server — Ollama's version, the reader's name for it and its facts (the disk,
        the card; "info": false — no reader there); its models by their weights — each family once on the disk, a base
        and its copies (fams), each model's facts (rows: its size, parameters, context, whether it can take a task,
        what its removal gives back), the ticked ones with the starred first (models), which is in memory and until
        when (mem); the download that runs (pull). A model come or gone since the last check — the check anew, quietly.
        peek — only whether there is a panel at all (Resources' tabs). → {…}; a server that doesn't answer is "down" with
        the list of the last check."""
        p = self.vendor_profiles()[V.LOCAL]
        found = self.local_found()
        if peek:
            return {"on": p["on"], "set": bool(found)}
        now, down = None, ""
        if found or p["on"]:
            try:
                now = await V.local_now(p["url"])
            except V.VendorError as e:
                down = self.t("vendor.local." + e.kind, url=p["url"], why=e.text[:200])
        if now and p["on"] and {x["name"] for x in now["tags"]} != {m["name"] for m in found.get("models") or []}:
            await self.api_vendor_local(p["url"], quiet=True)          # a model came or went: its facts anew
            p, found = self.vendor_profiles()[V.LOCAL], self.local_found()
        models = found.get("models") or []
        sizes = {x["name"]: x["size"] for x in (now or {}).get("tags") or [] if x["size"]}
        rows = {m["name"]: {"size": sizes.get(m["name"]) or m.get("size"), "params": m.get("params"), "ctx": m.get("ctx"),
                            "max": m.get("max"), "tools": m.get("tools"), "fit": V.fits(m), "frees": V.frees(models, m["name"])}
                for m in models}
        info = (now or {}).get("info") or {}
        gpu = info.get("gpu")
        mem = (now or {}).get("ps") or []
        if gpu and now and not mem:
            self.local_base = gpu["used"]                  # the card with no model of ours: what the others take
        if gpu:
            gpu = dict(gpu, base=getattr(self, "local_base", None))
        self.local_card, self.local_info_name = gpu, info.get("name")   # a model's settings count its contexts by it
        fams = V.families([dict(m, size=rows[m["name"]]["size"]) for m in models])
        return {"on": p["on"], "url": p["url"], "version": (now or found).get("version"), "at": found.get("ts"),
                "down": down, "info": bool(info), "name": info.get("name"), "disk": info.get("disk"), "gpu": gpu,
                "mem": mem, "fams": fams, "rows": rows, "models": p["models"], "kin": V.kin(models),
                "total": sum(f["size"] for f in fams), "reserve": V.reserve((info.get("disk") or {}).get("total")),
                "copy": V.LOCAL_CTX_COPY, "min": V.LOCAL_CTX_MIN,
                "pull": self.local_pull_view()}

    def local_model(self, model):
        model = str(model or "").strip()
        if model not in {m["name"] for m in self.local_found().get("models") or []}:
            raise ValueError(self.t("local.err.gone", name=model[:80]))
        return model

    async def api_local_unload(self, model):
        """A model out of the card now (the panel's "Unload"): never under a running task of its own."""
        model = self.local_model(model)
        if self.local_running():
            raise ValueError(self.t("local.err.running"))
        try:
            await V.unload(self.vendor_profiles()[V.LOCAL]["url"], model)
        except V.VendorError as e:
            raise ValueError(self.t("local.err.server", why=e.text[:200] or e.kind)) from None
        log("local model: %s unloaded from the card" % model)
        self.changed()
        return dict(await self.api_local_panel(), words=self.t("local.unloaded", name=model))

    async def api_local_delete(self, model):
        """A model off the server's disk (the panel's "Remove", asked first): never the one a running task is on, never
        while it downloads; its weights stay while another model has them. Then a check: the list without it — and the
        local model off when nothing that fits is left."""
        model = self.local_model(model)
        models = self.local_found().get("models") or []
        if self.local_running():
            raise ValueError(self.t("local.err.running"))
        pl = self.local_pull_view()
        if pl and pl["run"]:
            raise ValueError(self.t("local.err.pulling", name=pl["model"]))
        gives = V.frees(models, model)
        url = self.vendor_profiles()[V.LOCAL]["url"]
        try:
            await V.delete(url, model)
        except V.VendorError as e:
            raise ValueError(self.t("local.err.server", why=e.text[:200] or e.kind)) from None
        log("local model: %s removed from the server (%s bytes back)" % (model, gives))
        tunes = self.local_tunes()
        if (tunes.pop(model, None) or {}).get("was"):
            try:
                await V.delete(url, V.was_name(model))      # the model as it was before Pult changed it goes with it
            except V.VendorError:
                pass
        self.local_tunes(tunes)
        try:
            await self.api_vendor_local(url)
        except ValueError:
            pass                                          # nothing fits now: the check turned it off and says so below
        return dict(await self.api_local_panel(), words=self.t("local.deleted", name=model, gb=self.gb(gives)))

    # ---------- a model's settings (stage M, step 6.5; 2026-11-08) ----------
    # Resources → Local model → a model → Settings: what its Modelfile has — the system prompt, the context, the
    # sampling — written into the model itself, as the owner's course does it by hand (ollama create); and what Pult
    # does with it in a task — its tools, the card after a turn. What reaches a task and why — pult_vendors, "One's own
    # model's settings".

    def local_tunes(self, put=None):
        """Pult's own part of each model's settings (vendors.conf → local → tune): {model: {"tools": "five" | "all",
        "after": "keep" | "free", "was": the model as it was is kept on the server}}; put — store these."""
        conf = self.store.get("vendors.conf") or {}
        mine = conf.setdefault(V.LOCAL, {})
        if put is not None:
            mine["tune"] = {k: v for k, v in put.items() if v}
            self.store.put("vendors.conf", conf)
        return dict(mine.get("tune") or {})

    def local_running_on(self, model):
        """The running turns on this one of one's own models."""
        p = self.vendor_profiles()[V.LOCAL]
        return [sid for sid in self.local_running() if p["models"] and self.driven[sid].vendor_model(p) == model]

    async def api_local_model(self, model):
        """A model's settings: its system prompt, context and sampling as its server has them — a parameter it doesn't
        set says what it falls back to (the weights' own sampling, then Ollama's) — each context it can take with how
        much of the card it would want (V.vram_at; the card's other programs as the panel last saw them), and what Pult
        does with it in a task. Nothing is loaded. → {…}."""
        model = self.local_model(model)
        p = self.vendor_profiles()[V.LOCAL]
        try:
            s = await V.model_show(p["url"], model)
        except V.VendorError as e:
            raise ValueError(self.t("local.err.server", why=e.text[:200] or e.kind)) from None
        m = next(x for x in self.local_found().get("models") or [] if x.get("name") == model)
        mine = self.local_tunes().get(model) or {}
        params = {k: {"v": s["params"].get(k, s["sampling"].get(k, V.OLLAMA_DEFAULTS[k])), "set": k in s["params"],
                      "lo": lo, "hi": hi, "int": k in V.TUNE_INT} for k, (lo, hi) in V.TUNE.items()}
        card = getattr(self, "local_card", None)
        room = card["total"] - (card.get("base") or 0) if card else None
        ctxs = [{"n": n, "vram": V.vram_at(m.get("size"), s["cost"], n)} for n in V.CTXS
                if n >= V.LOCAL_CTX_MIN and (not s["max"] or n <= s["max"])]
        ctx = s["params"].get("num_ctx") if isinstance(s["params"].get("num_ctx"), int) else None
        return {"name": model, "system": s["system"], "sysmax": V.OWN_SYSTEM_MAX, "params": params, "ctx": ctx,
                "max": s["max"], "ctxs": ctxs, "room": room, "card": card["total"] if card else None,
                "think": "thinking" in s["caps"], "tools_ok": "tools" in s["caps"], "size": m.get("size"),
                "params_n": m.get("params"), "tools": mine.get("tools") or "five", "after": mine.get("after") or "keep",
                "all_ctx": V.LOCAL_ALL_CTX,
                "was": bool(mine.get("was")), "busy": bool(self.local_running_on(model)),
                "where": (getattr(self, "local_info_name", None) or ""), "min": V.LOCAL_CTX_MIN}

    async def api_local_tune(self, model, system=None, params=None, ctx=None, tools=None, after=None):
        """A model's settings saved (the owner's "Save"): the system prompt, the context and the sampling into the model
        itself — the first change keeps the model as it was on the server, to come back to — and Pult's own part. The
        context doesn't change under a running turn on the model (Ollama would load it anew mid-task, and the task's
        compaction window is its start's). Then a check: the list knows the new context. → as api_local_model, "words"."""
        model = self.local_model(model)
        p = self.vendor_profiles()[V.LOCAL]
        try:
            now = await V.model_show(p["url"], model)
        except V.VendorError as e:
            raise ValueError(self.t("local.err.server", why=e.text[:200] or e.kind)) from None
        write = {}
        try:
            for k, v in (params or {}).items():
                x = V.tune_value(k, v)
                if now["params"].get(k) != x:
                    write[k] = x
        except (ValueError, TypeError):
            raise ValueError(self.t("local.err.param")) from None
        if ctx is not None:
            if not isinstance(ctx, int) or ctx not in V.CTXS or ctx < V.LOCAL_CTX_MIN or (now["max"] and ctx > now["max"]):
                raise ValueError(self.t("local.err.param"))
            if ctx != now["params"].get("num_ctx"):
                if self.local_running_on(model):
                    raise ValueError(self.t("local.err.ctxrun", name=model))
                write["num_ctx"] = ctx
        sys_new = None
        if system is not None:
            if not isinstance(system, str) or len(system.strip()) > V.OWN_SYSTEM_MAX:
                raise ValueError(self.t("local.err.system", n=V.OWN_SYSTEM_MAX))
            if system.strip() != now["system"]:
                sys_new = system.strip()
        tunes = self.local_tunes()
        mine = dict(tunes.get(model) or {})
        was_tools = mine.get("tools") or "five"
        if tools in ("five", "all"):
            if tools == "all" and (write.get("num_ctx") or now["params"].get("num_ctx") or 0) < V.LOCAL_ALL_CTX:
                raise ValueError(self.t("local.err.allctx", ctx="%dK" % (V.LOCAL_ALL_CTX // 1024)))
            mine["tools"] = tools if tools == "all" else None
        if after in ("keep", "free"):
            mine["after"] = after if after == "free" else None
        if mine.get("tools") == "all" and (write.get("num_ctx") or now["params"].get("num_ctx") or 0) < V.LOCAL_ALL_CTX:
            mine["tools"] = None                     # a context made shorter takes the five back
        if write or sys_new is not None:
            try:
                await V.tune(p["url"], model, system=sys_new, params=write, keep=not mine.get("was"))
            except V.VendorError as e:
                log("local model: %s's settings didn't go in — %s%s" % (model, e.kind, ": " + e.text[:120] if e.text else ""))
                raise ValueError(self.t("local.err.server", why=e.text[:200] or e.kind)) from None
            mine["was"] = True
            log("local model: %s — settings saved in the model%s%s" % (model, (": " + ", ".join(
                "%s %s" % kv for kv in write.items())) if write else "", " and its system prompt (%d chars)" % len(sys_new)
                if sys_new is not None else ""))
        tunes[model] = {k: v for k, v in mine.items() if v}
        self.local_tunes(tunes)
        if "num_ctx" in write:
            try:
                await self.api_vendor_local(p["url"])        # the list and a task's window know the new context
            except ValueError:
                pass
        if "num_ctx" in write or (mine.get("tools") or "five") != was_tools:
            self.local_close_idle(model)
        self.changed()
        return dict(await self.api_local_model(model), words=self.t("local.tuned", name=model))

    def local_close_idle(self, model):
        """After a model's context or tools changed: the open processes of its tasks that do nothing now close — the next
        turn starts one anew, with the new compaction window, answer limit and tools (a running turn keeps its own: the
        context doesn't change under one). → how many."""
        p = self.vendor_profiles()[V.LOCAL]
        n = 0
        for sid, d in list(self.driven.items()):
            if (self.store.vendor_of(sid) == V.LOCAL and p["models"] and d.vendor_model(p) == model and not d.busy
                    and not getattr(d, "bg", None) and not getattr(d, "closing", False)):
                d.closing = True                         # a message from now on starts a new process (resume)
                d.q.put_nowait(None)
                n += 1
        if n:
            log("local model: %s's settings changed — %d open task process(es) closed, the next turn starts anew" % (model, n))
        return n

    async def local_after_turn(self, sid):
        """A turn of one's own model ended: when its settings say "free the card", it is unloaded at once (keep_alive 0) —
        unless another turn on one's own model runs or waits, which would have it loaded anew."""
        if self.store.vendor_of(sid) != V.LOCAL:
            return
        p = self.vendor_profiles()[V.LOCAL]
        d = self.driven.get(sid)
        if not d or not p["models"]:
            return
        model = d.vendor_model(p)
        if (self.local_tunes().get(model) or {}).get("after") != "free" or [x for x in self.local_running() if x != sid]:
            return
        try:
            await V.unload(p["url"], model)
            log("local model: %s unloaded after a turn — its settings say so" % model)
        except V.VendorError as e:
            log("local model: %s didn't unload after a turn — %s%s" % (model, e.kind, ": " + e.text[:120] if e.text else ""))

    async def api_local_untune(self, model):
        """A model back as it was before Pult first changed it (the owner's "Back as it was", asked first): made anew
        from the copy kept then, which goes. Not under a running turn on it. → as api_local_model, "words"."""
        model = self.local_model(model)
        tunes = self.local_tunes()
        mine = dict(tunes.get(model) or {})
        if not mine.get("was"):
            raise ValueError(self.t("local.err.nowas", name=model))
        if self.local_running_on(model):
            raise ValueError(self.t("local.err.ctxrun", name=model))
        url = self.vendor_profiles()[V.LOCAL]["url"]
        try:
            await V.untune(url, model)
        except V.VendorError as e:
            raise ValueError(self.t("local.err.server", why=e.text[:200] or e.kind)) from None
        mine.pop("was", None)
        try:
            back = (await V.model_show(url, model))["params"].get("num_ctx") or 0
        except V.VendorError:
            back = 0
        if mine.get("tools") == "all" and back < V.LOCAL_ALL_CTX:
            mine.pop("tools", None)                      # the context it came back with doesn't take them all
        tunes[model] = {k: v for k, v in mine.items() if v}
        self.local_tunes(tunes)
        log("local model: %s is back as it was before Pult changed it" % model)
        try:
            await self.api_vendor_local(url)
        except ValueError:
            pass
        self.local_close_idle(model)
        self.changed()
        return dict(await self.api_local_model(model), words=self.t("local.untuned", name=model))

    def gb(self, b):
        """Bytes as the panel writes them: decimal gigabytes, one digit after the point."""
        n = ("%.1f" % (b / 1e9)).rstrip("0").rstrip(".")
        return self.t("gb", n=n.replace(".", ",") if self.lang() == "ru" else n)

    async def api_local_pull(self, model, go=False):
        """A model from ollama.com onto the server (the panel's "Download"). First the look — its size from the
        registry, room on the disk after it (RESERVE stays free), how much of the card it would take with a 32K
        context; go — the download itself, the server's own, its progress in the panel; one at a time."""
        try:
            V.pull_name(model)
        except ValueError:
            raise ValueError(self.t("local.err.name")) from None
        model = str(model).strip()
        pl = self.local_pull_view()
        if pl and pl["run"]:
            raise ValueError(self.t("local.err.pulling", name=pl["model"]))
        if model in {m["name"] for m in self.local_found().get("models") or []}:
            raise ValueError(self.t("local.err.have", name=model))
        try:
            size = await V.pull_size(model, proxy=self.env.get("PULT_PROXY") or None)
        except V.VendorError as e:
            raise ValueError(self.t("local.err.registry", why=e.text[:200] or e.kind)) from None
        if not size:
            raise ValueError(self.t("local.err.nosuch", name=model))
        url = self.vendor_profiles()[V.LOCAL]["url"]
        try:
            now = await V.local_now(url)
        except V.VendorError as e:
            raise ValueError(self.t("vendor.local." + e.kind, url=url, why=e.text[:200])) from None
        info = now.get("info") or {}
        disk, gpu = info.get("disk"), info.get("gpu")
        after = disk["free"] - size if disk else None
        keep = V.reserve(disk["total"] if disk else None)
        look = {"model": model, "size": size, "after": after, "reserve": keep, "need": V.vram_need(size),
                "card": gpu["total"] if gpu else None, "ok": after is None or after >= keep}
        if not go:
            return {"look": look}
        if not look["ok"]:                       # the app hides the button; a word from an older app says why
            raise ValueError(self.t("local.err.room", gb=self.gb(max(0, after)), keep=self.gb(keep)))
        self.local_pull = {"model": model, "total": size, "done": 0, "rate": 0, "since": time.time(), "status": "", "err": None,
                           "stopped": False, "end": None}
        self.local_task = asyncio.ensure_future(self.local_pulling(url, model))
        log("local model: %s downloads to the server (%s bytes)" % (model, size))
        self.changed()
        return {"pull": self.local_pull_view()}

    async def local_pulling(self, url, model):
        pl, mark = self.local_pull, {"t": 0.0, "done": 0, "at": time.time()}

        def step(done, total, status):
            t = time.time()
            pl.update(done=done, total=max(total, pl["total"] or 0), status=status)
            if t - mark["t"] >= V.PULL_STEP:
                pl["rate"] = int((done - mark["done"]) / max(0.1, t - mark["at"])) if mark["t"] else 0
                mark.update(t=t, done=done, at=t)
                if self.web:
                    self.web.emit("local")
        try:
            await V.pull(url, model, step)
            pl.update(done=pl["total"], end=time.time())
            log("local model: %s is on the server" % model)
            await self.api_vendor_local(url, quiet=True)
        except asyncio.CancelledError:
            pl.update(stopped=True, end=time.time())
            log("local model: the download of %s stopped by the owner" % model)
        except V.VendorError as e:
            pl.update(err=e.text[:200] or e.kind, end=time.time())
            log("local model: the download of %s failed — %s" % (model, e.text[:120] or e.kind))
        except Exception as e:                       # never a task that dies without a word
            pl.update(err=type(e).__name__, end=time.time())
            log("local model: the download of %s broke — %r" % (model, e))
        self.changed()
        if self.web:
            self.web.emit("local")

    async def api_local_pull_stop(self):
        task = getattr(self, "local_task", None)
        if task and not task.done():
            task.cancel()
            await asyncio.sleep(0.2)
        return await self.api_local_panel()

    def vendor_row(self, vid):
        return next((r for r in self.vendors_list() if r["id"] == vid), None)

    async def api_vendor_all(self, vendor=None):
        """The model new projects get (Settings; Q147): a vendor that can take a task — its key here, one's own model
        on, Codex here — or None: Claude. A project already there keeps its own. → {"vendor"}."""
        if vendor in ("", "claude"):
            vendor = None
        if vendor is not None:
            if vendor != "codex" and vendor not in V.PRESETS:
                raise ValueError("bad vendor")
            if vendor == "codex":
                await self.codex_state()
            why = self.model_why(vendor)
            if why:
                raise ValueError(why)
        self.store.put("vendors.all", vendor)
        log("app: new projects get %s" % (vendor or "claude"))
        self.changed()
        return {"vendor": vendor}

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
            known = self.store.get("codex.catalog") or {}
            if got["ok"] and v not in known:
                known[v] = await CX.models(path, env={k: x for k, x in env.items() if not k.startswith("PULT_")},
                                           client=self.D.VERSION)
                self.store.put("codex.catalog", known)
                log("codex %s: models %s" % (v, ", ".join("%s (%s)" % (r["model"], "/".join(r["efforts"])) for r in known[v])
                                             or "unknown"))
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

    def second_left(self, sid):
        """The findings of this task's reviews the owner took the tick off — seen and left as they are: the next
        review is told not to repeat them (review 2026-11-11, block 6). [{"title", "where"}], the newest last."""
        return self.store.get("second.left." + sid) or []

    def second_leave(self, sid, items):
        left = self.second_left(sid)
        for it in items:
            x = {"title": R.short(it.get("title") or "", 200), "where": CX.where(it)}
            if x["title"] and x not in left:
                left.append(x)
        self.store.put("second.left." + sid, left[-LEFT_MAX:])

    @staticmethod
    def second_open(job):
        """The places of the findings that can still go to the doer: every one of a review; of a check of the fixes —
        what is left and what is new."""
        return [k for k, it in enumerate(job.get("items") or []) if it.get("st") not in ("fixed", "meant")]

    @staticmethod
    def second_off(job, off):
        """The findings the owner took the tick off, as the app names them — by their place in the list."""
        n = len(job.get("items") or [])
        return sorted({k for k in (off if isinstance(off, list) else []) if type(k) is int and 0 <= k < n})

    def vendors_ok(self, pkey):
        """Whether the owner let this project go to other vendors (Q105 b): its code reaches OpenAI with a second opinion."""
        return bool((self.store.get("vendors.ok") or {}).get(pkey))

    @staticmethod
    def second_fix(job):
        """Whether the fixes can be checked (review 2026-11-11, block 6): the last review's findings went to the doer,
        or a check of them failed — it can be asked again."""
        return bool(job and (job.get("sent") or (job.get("kind") == "check" and job.get("st") == "fail")))

    async def second_view(self, sid, rec, lv):
        """For the session's screen: can — the button under the outcome (Codex is here, the task changed files, its
        turn has ended); why — what a tap says instead ("version": a Codex Pult can't use), v — its version; job — the
        review while it runs and once done, until the owner puts it away, else None; fix — the button asks to check
        the fixes of the findings that went to the doer (act "check"), not for a review anew. A job's kind is "check"
        for such a check: each of its items has st — "fixed", "left", "meant" — and note, what Codex said of it; an
        item without st is new."""
        info = await self.codex_state()
        job = self.second_job(sid)
        mine = self.store.vendor_of(sid) == "codex"            # Codex did it: Claude's second opinion is step 4.2 (Q122)
        mine = mine or bool(self.read_only(sid, lv.pkey))      # another model's task: its findings would go nowhere (7.2)
        return {"can": bool(info["path"] and rec and lv.turn is None and self.store.turn(sid)) and not mine,
                "why": info["why"] if info["path"] else None, "v": info["v"],
                "fix": self.second_fix(job),
                "job": {k: job.get(k) for k in ("st", "ts", "t0", "dur", "steps", "model", "summary", "items", "why",
                                                "text", "limits", "kind")} if job and not job.get("away") else None}

    async def api_second(self, sid, act="start", fork=False, off=None):
        """act: start — ask Codex (→ {"need": "allow", "project"} when the project isn't allowed yet); allow — allow
        the project and start; cancel — stop it; away — "Got it"; send — the findings into the session (api_send: a
        session open on the computer without the wrapper answers {"need": "fork"} the same way). off — the findings
        the owner took the tick off, by their place in the list: they don't go with "send", and with "send" or "away"
        they are remembered as left — the task's next review doesn't repeat them (second_left)."""
        path, lv = self.transcript_of(sid)
        pkey, project = self.session_project(sid)
        if act == "away":
            job = self.second_job(sid)
            if job:
                if job.get("st") == "done":
                    self.second_leave(sid, [job["items"][k] for k in self.second_off(job, off)])
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
            out = self.second_off(job, off)
            go = [job["items"][k] for k in self.second_open(job) if k not in out]
            if not go:
                return {"ok": False, "note": self.t("second.err.none")}
            job["sending"] = True
            try:
                res = await self.api_send(sid, CX.message(go, job.get("model"), check=job.get("kind") == "check"), fork=fork)
            finally:
                job.pop("sending", None)
            if res.get("ok"):
                job["away"] = job["sent"] = True
                job["went"] = go                     # what a check of the fixes will be asked about
                self.second_leave(sid, [job["items"][k] for k in out])
                self.second_keep(sid, job)
                log("second opinion %s: sent to Claude (%d findings of %d)" % (sid[:8], len(go), len(job["items"])))
                self.changed(sid)
            return res
        if act not in ("start", "allow", "check"):
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
        if act == "check":
            # a check of the fixes: what went to the doer last time (a failed check — the same again). The review
            # it follows stays in the store until this one ends: stopped, the button still offers the check
            if not self.second_fix(job):
                return {"ok": False, "note": self.t("note.decided")}
            was = job["was"] if job.get("kind") == "check" and job.get("st") == "fail" else job.get("went") or job.get("items") or []
            job = {"st": "wait", "ts": time.time(), "pkey": pkey, "kind": "check",
                   "was": [{k: v for k, v in it.items() if k not in ("st", "note")} for it in was]}
            self.seconds[sid] = job
        else:
            job = {"st": "wait", "ts": time.time(), "pkey": pkey}
            self.second_keep(sid, job)
            self.store.put("second." + sid, None)        # the one before is replaced: a new review, the old one gone
        self.second_tasks[sid] = asyncio.create_task(self.second_run(sid, job, path, project, info))
        self.changed(sid)
        return {"ok": True}

    async def api_vendors_ok(self, pkey, on=False):
        """Whether another vendor may review a project (stage M, Q105 b; since 7.2 a review's alone — the project's
        model gets its code by the owner's choice of it): given by the second opinion's first tap, taken back by
        "Disallow" on the project's settings page — then its review stops, now and from the queue. → {"on"}."""
        if on and not await self.known_project(pkey):
            raise ValueError(self.t("err.no_project"))
        ok = self.store.get("vendors.ok") or {}
        if on:
            ok[pkey] = time.time()
        else:
            ok.pop(pkey, None)
        self.store.put("vendors.ok", ok)
        log("app: project %s %s" % (pkey, "may be reviewed by other vendors" if on else "is reviewed by no other vendor"))
        if not on:                           # taken back: no review of it goes on, nor starts later from the queue
            for sid, task in list(self.second_tasks.items()):
                if (self.seconds.get(sid) or {}).get("pkey") == pkey:
                    task.cancel()
        self.changed()
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
                # the parts of the folder that are repositories of their own: found by the files the task's edit tools
                # wrote and its turns made or changed (commands too) — 2026-10-31
                repos = await asyncio.to_thread(CX.nested_repos, project, facts["files"] + self.store.task_files(sid),
                                                facts["t0"])
                check = job.get("kind") == "check"
                text = CX.check_instructions(facts, job["was"], base, self.lang()) if check else \
                    CX.instructions(facts, base, self.lang(), rules=os.path.isfile(os.path.join(project, "CLAUDE.md")),
                                    repos=repos, left=self.second_left(sid))
                env = {k: v for k, v in os.environ.items() if not k.startswith("PULT_")}

                def step(n):
                    job["steps"] = n
                    self.changed(sid)
                got = await CX.review(info["path"], project, text, env=env, on_step=step, client=self.D.VERSION, plain=check)
                if check:                 # each earlier finding with what Codex says of it now; no line for one — left
                    said, new = CX.parse_check(got["text"], len(job["was"]), project)
                    read = {"summary": "", "items": [dict(it, st=said.get(k, ("left", ""))[0], note=said.get(k, ("left", ""))[1])
                                                     for k, it in enumerate(job["was"])] + new}
                else:
                    read = CX.parse(got["text"], project)
                job.update(st="done", dur=time.time() - job["t0"], model=got["model"], summary=read["summary"],
                           items=read["items"], limits=got["limits"])
                log("second opinion %s: Codex %s (%s), %s, %d commands, %.0f s%s%s" % (
                    sid[:8], info["v"], got["model"],
                    "the fixes checked — " + ", ".join("%d %s" % (sum(it.get("st") == s for it in read["items"]), s)
                                                       for s in ("fixed", "left", "meant", None)) if check
                    else "%d findings" % len(read["items"]), job["steps"], job["dur"],
                    "; nested repositories: " + ", ".join(r["dir"] for r in repos) if repos else "",
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
            if not self.topic_full(lv.pkey):       # only "done" in the topic (stage M, 7.2): no title, no findings
                head, items = "👁 %s · " % self.head(lv), [] if job["st"] == "fail" else [None] * len(items)
            if job["st"] == "fail":
                text = head + self.t("second.tg.fail", why=R.esc(self.t("second.why." + job.get("why", "failed"))))
            elif job.get("kind") == "check":       # a check of the fixes: how many of each, and what is left by name
                was = job.get("items") or []
                n = {s: sum(it.get("st") == s for it in was) for s in ("left", "fixed", "meant", None)}
                text = head + self.t("second.tg.check", sum=", ".join(
                    self.t("second.n." + (s or "new"), n=n[s]) for s in ("left", "fixed", "meant", None) if n[s]))
                open_ = [it for it in was if it.get("st") in ("left", None)]
                if open_ and None not in items:
                    text += "\n" + "\n".join("%d. %s" % (k, R.esc(R.short(it["title"], 140)))
                                              for k, it in enumerate(open_[:SECOND_LINES], 1)) + \
                        ("\n…" if len(open_) > SECOND_LINES else "")
            elif not items:
                text = head + self.t("second.tg.none")
            elif None in items:
                text = head + self.t("second.tg.done", n=len(items), findings=I.plural(len(items), "finding"))
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
        why = self.vendor_stop(sid)
        if why:                                  # read only (another model's task, 7.2), its key gone: not later either
            raise ValueError(why)
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
                         files=None, model=None, effort=None, big=False, vendor=None):
        """A new project: a folder with git (how=empty), the same with a first turn that writes CLAUDE.md from the
        owner's description (describe), or a clone (clone — a job, the app asks api_job). Its topic in the group
        comes at once, named by the title; a first task starts a session there, as "+" does. Nothing that exists
        is touched: a taken folder or project key is a refusal. vendor — the project's model (stage M, 7.2; Q147):
        "claude", "codex" or a vendor's id, one that can take a task now; none said — the model of new projects."""
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
        vid = vendor or self.vendor_all() or "claude"
        if not self.is_model(vid):
            raise ValueError("bad vendor")
        if vid == "codex":
            await self.codex_state()
        if self.model_why(vid):
            raise ValueError(self.model_why(vid))
        if vid == "codex":                          # its own model and level of effort, checked against its list
            model = self.vendor_model(vid, model)
            effort = self.codex_effort(model or next(iter(self.codex_models()), None), effort)
        elif vid != "claude":
            model, effort = self.vendor_model(vid, model), None
        else:
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
        done = lambda git: self.project_made(pkey, dest, title, parent, how, first, model, effort, git, vid)
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

    async def project_made(self, pkey, dest, title, parent, how, first, model, effort, git, vid="claude"):
        """The folder is there: remember the project under its title and its model, open its topic, start the first
        turn — on its model."""
        row = self.store.topic(pkey)
        self.store.set_topic(pkey, dest, title, row["thread"] if row and row["path"] == dest else None)
        self.store.put("new_parent", parent)
        got = dict(self.project_models())
        if vid == "claude":
            got.pop(pkey, None)
        else:
            got[pkey] = vid
        self.store.put("proj.model", got)
        log("new project: %s (%s%s) · %s" % (dest, how, "" if git else ", no git", vid))
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

    # ----- what a task changed, from git (review 2026-11-11, block 5: the view alone) -----

    async def changes_facts(self, sid):
        """What a task's changes are counted from: (its project's folder, when it began, the files known as its own —
        the ones its edit tools wrote and its turns made or changed, as paths from the folder). The folder is None when
        Pult doesn't know the session's project or the folder is gone; the start is None for a task without a
        transcript. The transcript is read again only once it has grown."""
        if not self.D.SID_RE.fullmatch(sid or ""):
            raise ValueError(self.t("send.err.session"))
        project = self.session_project(sid)[1]
        if not project:
            return None, None, []
        try:
            path = self.transcript_of(sid)[0]
            st = os.stat(path)
        except (ValueError, OSError):
            return project, None, []
        key, memo = (st.st_size, st.st_mtime_ns), self.facts_memo.get(path)
        if not memo or memo[0] != key:
            facts = await asyncio.to_thread(CX.task_facts, path, project)
            if len(self.facts_memo) >= 60:
                self.facts_memo.clear()
            memo = self.facts_memo[path] = (key, facts["t0"], [f for f in facts["files"] if not os.path.isabs(f)])
        own = dict.fromkeys(memo[2] + [f.replace(os.sep, "/") for f in self.store.task_files(sid)])
        return project, memo[1], list(own)

    async def changes_read(self, sid):
        """A task's changes, read from git now: CH.changed's answer, or None — no folder, no git, no task yet."""
        project, t0, own = await self.changes_facts(sid)
        if not project or t0 is None:
            return None
        return await asyncio.to_thread(CH.changed, project, t0, own)

    def changes_keep(self, sid, key, got, took=0.0):
        """What the line under a task's outcome says, kept: {n, add, del} of the task's own changed files — None when
        it has none. A slow count is kept longer, so a huge folder isn't walked every CH.KEEP s."""
        brief = got["mine"] if got and got["mine"]["n"] else None
        if len(self.changes_memo) >= 60:
            self.changes_memo.clear()
        self.changes_memo[sid] = {"key": key, "brief": brief, "until": time.time() + max(CH.KEEP, 30 * took)}
        return brief

    async def changes_brief(self, sid, key):
        """For a task's screen: the line of its changes, counted for this outcome (key — the outcome's time) not longer
        than CH.KEEP s ago. A count slower than CH.WAIT doesn't hold the screen: it goes on, and the screen hears when
        the line is there."""
        memo = self.changes_memo.get(sid)
        if memo and memo["key"] == key and time.time() < memo["until"]:
            return memo["brief"]
        task = self.changes_tasks.get(sid)
        if not task:
            task = self.changes_tasks[sid] = asyncio.create_task(self.changes_count(sid, key))
        await asyncio.wait({task}, timeout=CH.WAIT)
        memo = self.changes_memo.get(sid)
        return memo["brief"] if memo else None

    async def changes_count(self, sid, key):
        t0, got = time.monotonic(), None
        try:
            got = await self.changes_read(sid)
        except Exception as e:
            log("changes %s: not counted — %r" % (sid[:8], e))
        finally:
            self.changes_tasks.pop(sid, None)
        old, took = self.changes_memo.get(sid), time.monotonic() - t0
        brief = self.changes_keep(sid, key, got, took)
        if took > CH.WAIT:
            log("changes %s: counted in %.1f s" % (sid[:8], took))
            if not old or old["brief"] != brief:
                self.changed(sid)                      # the screen went on without the line: now it is there

    async def api_changes(self, sid):
        """The screen "Changes" of a task: git — whether its folder (or a part of it) is in git at all; since — when
        the task began; files — its own changed files, each {p, was, st, add, del, bin, new, lock}, with n, add and del
        of them all; more — what else changed in the folder since then (commands, other sessions); cut — the list is
        longer than what is here, total — how long."""
        t0 = time.monotonic()
        project, since, own = await self.changes_facts(sid)
        got = await asyncio.to_thread(CH.changed, project, since, own) if project and since is not None else None
        rec, row = self.attn.rec.get(sid), self.store.session(sid)
        self.changes_keep(sid, rec.get("ts") if rec else None, got, time.monotonic() - t0)
        pkey = self.session_project(sid)[0]
        head = {"project": self.project_label(pkey) if pkey else "", "title": (row["title"] if row else None) or "",
                "git": got is not None, "since": since}
        if not got:
            return dict(head, files=[], more=[], cut=False, total=0, n=0, add=0, **{"del": 0})
        mine = [f for f in got["files"] if f["own"]]
        log("app: changes of %s — %d of the task's files (+%d −%d), %d more in the folder, %.0f ms" % (
            sid[:8], got["mine"]["n"], got["mine"]["add"], got["mine"]["del"], got["total"] - got["mine"]["n"],
            (time.monotonic() - t0) * 1000))
        return dict(head, files=mine, more=[f for f in got["files"] if not f["own"]],
                    cut=got["total"] > len(got["files"]), total=got["total"], **got["mine"])

    async def api_diff(self, sid, p="", full=False):
        """One changed file of a task line by line (CH.diff): rows — [kind, its number before, its number now, the
        line] with kind 0 kept, 1 added, 2 removed, 3 a gap of that many unchanged lines; cut — only the start is
        here; full — the whole file was asked for. same — the file didn't change since the task began: the app opens
        it as it is. here — the file is there to be opened whole. Like keys or settings — never shown."""
        project, since, own = await self.changes_facts(sid)
        if not project:
            raise ValueError(self.t("send.err.session"))
        p = str(p or "").replace("\\", "/").strip("/")
        if not p or F.secret_like(p):
            raise ValueError(self.t("show.err.secret" if p else "send.err.none"))
        got = await asyncio.to_thread(CH.diff, project, since, p, own, bool(full)) if since is not None else {"same": True}
        if got is None:
            raise ValueError(self.t("chg.err.git"))
        if got.get("lock"):
            raise ValueError(self.t("show.err.secret"))
        if not got.get("same"):
            got["here"] = not F.why_not_show(os.path.join(project, *p.split("/")), project)
        return dict(got, project=self.project_label(self.session_project(sid)[0]))

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
        await self.codex_state()                    # the model of new projects may be Codex (stage M, 7.2)
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
                "mac": {"idle": idle, "away": await self.away(), "mode": self.mode(), "until": self.prefs()["mode_until"]},
                "telegram": "proxy" if len(self.tg.clients) > 1 and self.tg.cur == 0 else "direct",
                "stt": self.stt_state(), "cc": self.cc_choice(), "vendors": self.vendors_list(), "vendor_all": self.vendor_all(),
                "codex": self.codex_view(), "cc_models": self.cc_models_view(self.app_cc_version()),
                "log": [x for x in lines if "Bearer" not in x][-40:]}

    async def api_prefs(self, **kw):
        cur = self.prefs()
        for k, v in kw.items():
            if k in ("vehi", "brief", "pager", "gh", "vcheck", "hashtags", "ccfresh") and isinstance(v, bool) or k == "mode" and v in self.D.MODES or k == "lang" and v in I.LANGS \
                    or k == "pace" and v in S.PACES:
                cur[k] = v
            elif k == "digest" and (v is None or isinstance(v, int) and not isinstance(v, bool) and 0 <= v <= 23):
                cur[k] = v                                # the hour of the day's summary; None — none
            elif k == "quiet" and (v is None or isinstance(v, list) and len(v) == 2 and v[0] != v[1]
                                   and all(isinstance(x, int) and not isinstance(x, bool) and 0 <= x <= 23 for x in v)):
                cur[k] = v                                # [from, to) hours; None — none
            elif k == "page_delay" and isinstance(v, int) and not isinstance(v, bool) and 0 <= v <= 60:
                cur[k] = v                                # minutes
            elif k == "remind" and isinstance(v, bool):
                cur[k] = v
            elif k in ("model", "effort") and (v is None or isinstance(v, str)):
                m, e = self.check_choice(v if k == "model" else None, v if k == "effort" else None)
                cur[k] = m if k == "model" else e         # "" — back to Claude Code's settings
        self.store.put("prefs", cur)
        if "mode" in kw:
            await self.set_mode(cur["mode"])
            cur = self.prefs()                            # with the hour "Computer" holds until
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
