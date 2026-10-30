"""Sessions Pult runs itself — from Telegram and the app — through the Agent SDK, and what Pult keeps of every live
session; out of pultd.py unchanged (review 2026-10-27, 6.2): a turn, an open permission request or question, a live
session, a `pult run` task, and Driven — a session Pult drives (new, continued or a copy), its place among the turns
that run at once, and the hooks Pult puts into it.

pultd imports the classes and MAX_RUNNING by name: pultd.Driven, pultd.Turn and the rest stay what the tests and the
stand use. What only these sessions read — DRIVEN_IDLE, ASK_TIMEOUT, SDK_LINE_MAX, PERMISSION_MODE, the hook's Python
and path — lives here, and a test changes it here.
"""
import asyncio
import json
import os
import secrets
import shlex
import sys
import time
from pathlib import Path

import pult_hook
import pult_render as R
import pult_vendors as V

HOME = Path(os.environ.get("PULT_HOME") or "~/.local/share/pult").expanduser()   # as pultd, pult_setup, pult_update
SOCK = os.environ.get("PULT_SOCK") or str(HOME / "pult.sock")                    # the daemon's: the hook's way back
HOOK_PY = os.environ.get("PULT_HOOK_PY") or (
    # Windows: the base pythonw, not the venv's — the venv's python is a redirector that would be the hook's parent
    # instead of claude, and a console program would open a console window for every hook call
    str(Path(getattr(sys, "_base_executable", sys.executable)).with_name("pythonw.exe")) if os.name == "nt"
    else sys.executable)                                      # Pult's own Python: the hook needs nothing else
HOOK = str(HOME / "pult_hook.py")
MAX_RUNNING = 3          # turns from Telegram at once: Claude Code takes 250–450 MB each
DRIVEN_IDLE = 20 * 60    # an idle session from Telegram is closed; it continues via resume
ASK_TIMEOUT = 6 * 3600   # how long to wait for a permission answer in a session from Telegram
# the longest line of the Claude process's stream: a picture Claude reads comes in it twice (the result and
# tool_use_result), and the SDK's own 1 MB cut off a session at one ~470 KB screenshot (2026-10-21)
SDK_LINE_MAX = 64 * 1024 * 1024
PERMISSION_MODE = os.environ.get("PULT_PERMISSION_MODE", "auto")


def log(*a):
    print(time.strftime("%Y-%m-%d %H:%M:%S"), *a, flush=True)      # as pultd.log: the daemon's journal, the same form


def injected_hooks(windows=os.name == "nt"):
    """The hooks Pult puts into the sessions it runs. They run beside the global hook, which stays silent there: this
    one says it is the injected one with PULT_INJECTED=1 in front of the shell command — on Windows, where hooks run
    in exec form without a shell, with --injected among the arguments."""
    if windows:
        return pult_hook.hooks_config(HOOK_PY, [HOOK, "--injected"])
    return pult_hook.hooks_config("PULT_INJECTED=1 %s %s" % (shlex.quote(HOOK_PY), shlex.quote(HOOK)))


def ctx_from_usage(model_usage, model=None):
    """The context window of a turn's main model from the result's modelUsage → (window, max output tokens), or None.
    The main model is the one named by system/init; without it — the entry that read the most."""
    mu = model_usage if isinstance(model_usage, dict) else {}
    entry = mu.get(model) if model else None
    if not isinstance(entry, dict):
        entry = max((v for v in mu.values() if isinstance(v, dict)), default=None,
                    key=lambda v: (v.get("inputTokens") or 0) + (v.get("cacheReadInputTokens") or 0))
    if not entry or not entry.get("contextWindow"):
        return None
    return int(entry["contextWindow"]), int(entry.get("maxOutputTokens") or 0)


# ---------- live session state ----------

class Turn:
    def __init__(self, prompt=None, reply_to=None):
        self.started = self.last = time.time()
        self.prompt = prompt
        self.reply_to = reply_to
        self.n = 0
        self.msg = None
        self.created = asyncio.get_running_loop().create_future()
        self.changed = asyncio.Event()
        self.done = None          # (icon, time) when the turn ended
        self.now = None           # Claude's latest reply in this turn
        self.muted = False        # 🔕 — no milestones until the turn ends
        self.vehi = None
        self.vehi_ids = []        # the milestones' messages: removed when the result comes (one message per turn)
        self.note = None          # the turn was started by Claude itself: "⚙️ Background task finished …"
        self.here = False         # the owner typed the prompt at this computer (not from Telegram or the app)
        self.prompt_id = None     # Claude Code's id of the turn: a message absorbed into it comes with the same one
        self.ask = None           # the owner's request as written, wherever it came from (prompt — only when typed here)


class Req:
    """An open permission request or question — waits for a button in Telegram or an answer on the Mac."""

    def __init__(self, sid, tool, inp, suggestions):
        self.rid = secrets.token_hex(4)
        self.sid = sid
        self.tool = tool
        self.inp = inp if isinstance(inp, dict) else {}
        self.suggestions = suggestions or []
        self.kind = "ask" if tool == "AskUserQuestion" else "plan" if tool == "ExitPlanMode" else "perm"
        self.fut = asyncio.get_running_loop().create_future()
        self.msgs = []            # [(message_id, question index or None)]
        self.closed = None        # (note, answers) once decided: a message still on its way gets the same line on arrival
        self.chosen = {}          # question → [answers]
        # multi-select question → checked options; Claude's advice ("(Recommended)") is checked from the start
        self.picks = R.advised_picks(self.inp.get("questions")) if self.kind == "ask" else {}
        self.ts = time.time()     # since when it waits for the owner
        self.paged = False        # posted to Telegram (as a pager, only when the owner is neither in the app nor here)


class Live:
    def __init__(self, sid, pkey):
        self.sid = sid
        self.pkey = pkey
        self.cwd = None
        self.title = None
        self.named = False        # title is a real name (set by the user or by Claude Code), not the prompt
        self.transcript = None
        self.driven = False
        self.turn = None
        self.pending = {}
        self.bg = []              # background tasks still running after the turn (background_tasks in Stop)
        self.bg_seen = {}         # task id → when Pult first saw it running
        self.run = None           # when the owner's prompt set the work going: turns Claude starts by itself (its
                                  # background task or subagent reported back) go on with it — "working 27 min"
        self.pid = None           # the session's claude process: the hook's parent (probe_load.py)


class Job:
    """A task without Claude — `pult run -- command`."""

    def __init__(self, rid, cmd, cwd, pid, pkey):
        self.rid, self.cmd, self.cwd, self.pid, self.pkey = rid, cmd, cwd, pid, pkey
        self.started = time.time()
        self.last = None              # last line of output
        self.code = None
        self.ended = None
        self.tail = []
        self.msg = None
        self.muted = False
        self.watch = None


# ---------- sessions from Telegram ----------

class Driven:
    """A session Pult drives through the Agent SDK: new, continued or a copy (fork)."""

    def __init__(self, d, sid, path, resume=None, fork=False, model=None, effort=None):
        self.d = d
        self.sid = sid
        self.path = path
        self.resume = resume
        self.fork = fork
        self.want_model = model       # the owner's choice for this session (None — Pult's default, else Claude Code's settings)
        self.want_effort = effort
        self.q = asyncio.Queue()
        self.client = None
        self.asking = False       # the query is sent, no result in the SDK stream yet
        # the loop is over (idle, the process gone) and the process is on its way out: a message now goes by resume —
        # put into the queue, nobody would read it (✕ "didn't reach Claude"; review 2026-10-27, Я6)
        self.closing = False
        self.result = asyncio.Event()
        self.bg = set()           # the process's background tasks: while they run, the process is not closed
        self.model = None         # the main model, from system/init: picks the entry in the result's modelUsage
        self.queued = None        # since when a message waits for a place among the MAX_RUNNING turns
        self.waiting = None       # that message's words, for the app and the topic
        self.jump = asyncio.Event()       # "Start now": this turn goes over the limit, once
        self.dropped = asyncio.Event()    # Stop while it waits: the message goes
        self.queue_msg = None     # the topic's "⏳ in the queue" message, removed once the turn starts
        self.task = asyncio.create_task(self.run())

    @property
    def busy(self):
        """A turn is running — our own query, or one Claude Code started itself when a background task finished —
        or a message waits in the queue for one."""
        return self.running or self.queued is not None

    @property
    def running(self):
        lv = self.d.live.get(self.sid)
        return self.asking or bool(lv and lv.turn)

    async def slot(self, text, origin):
        """A place among the MAX_RUNNING turns from Telegram and the app → True (taken: give it back), False (over the
        limit: "Start now"), None (Stop while it waited: the message is dropped). While it waits the session is "in
        the queue" — in the app, and in the topic when the message came from Telegram. A queue nobody could see made
        a 4th question look dead: it waited 4 minutes, the owner sent it again, it ran twice (2026-10-23)."""
        sem = self.d.run_sem
        if not sem.locked():
            await sem.acquire()
            return True
        self.queued, self.waiting = time.time(), R.short(R.prompt_text(text), 300)
        self.jump.clear()
        self.dropped.clear()
        log("Telegram session %s: in the queue, %d turns run" % (self.sid[:8], MAX_RUNNING))
        await self.d.queue_shown(self, origin)
        take = asyncio.ensure_future(sem.acquire())
        jump, drop = asyncio.ensure_future(self.jump.wait()), asyncio.ensure_future(self.dropped.wait())
        cancelled = False
        try:
            await asyncio.wait({take, jump, drop}, return_when=asyncio.FIRST_COMPLETED)
        except asyncio.CancelledError:
            cancelled = True                   # the session went (opened on the computer) as the place came
            raise
        finally:
            jump.cancel()
            drop.cancel()
            if not take.done():
                take.cancel()
            await asyncio.gather(take, jump, drop, return_exceptions=True)
            got = take.done() and not take.cancelled() and take.exception() is None
            waited = time.time() - self.queued
            self.queued = self.waiting = None
            if got and (self.dropped.is_set() or cancelled):
                sem.release()                  # a place taken in that very moment goes back: else it's lost till a restart
            await self.d.queue_gone(self)
        how = "dropped" if self.dropped.is_set() else "a place came" if got else "started over the limit"
        log("Telegram session %s: out of the queue after %d s — %s" % (self.sid[:8], waited, how))
        return None if self.dropped.is_set() else got

    async def say(self, text, origin):
        """A message for this session. During our query's turn it goes straight to Claude Code, which reads it at the
        turn's next step, as in a VS Code tab (a queued_command, absorbed_mid_turn — tests/probe_midturn.py, 2.1.300);
        held here until the result, "stop, wrong project" reached Claude only after a 10-minute turn (2026-10-21).
        A turn that ends before its next step runs the message as a turn of its own — Claude Code does that itself.
        The same during a turn Claude Code started by itself (a background task ended): queued, the message went as a
        query of the loop, and that other turn's result passed for its answer (review 2026-10-27, Я5)."""
        if self.client and (self.asking or getattr(self.d.live.get(self.sid), "turn", None) is not None):   # self.running
            try:
                await self.client.query(text)
                if origin:
                    self.d.expect[self.sid] = origin  # the turn's result answers the latest message
                return
            except Exception as e:                    # the process is going away: the loop will see it
                log("Telegram session %s: a message mid-turn: %r" % (self.sid[:8], e))
        self.q.put_nowait((text, origin))

    async def stop(self):
        """Stop means stop: messages still waiting here are dropped, so the interrupt doesn't start the next turn
        (2026-10-21: each tap on Stop let one more waiting "stop, wrong project" start a turn). → how many dropped."""
        items = []
        while not self.q.empty():
            items.append(self.q.get_nowait())
        if None in items:
            self.q.put_nowait(None)              # the process has ended: the loop still has to see that
        dropped = len([x for x in items if x is not None])
        for x in items:
            if x is not None:
                self.d.out_set(self.sid, "gone", x[0])
        lv = self.d.live.get(self.sid)
        if self.queued is not None:              # the message waiting for a place goes too
            self.dropped.set()
            dropped += 1
            if not (lv and lv.turn):
                return dropped                   # no turn runs: nothing to interrupt
        if self.client:
            await self.client.interrupt()
        return dropped

    async def _wait_hook(self, tool, inp, ctx):
        # The decision arrives via the PermissionRequest hook (buttons in Telegram) and cancels this call.
        from claude_agent_sdk import PermissionResultDeny
        await asyncio.sleep(ASK_TIMEOUT)
        return PermissionResultDeny(message="No answer from Telegram within %d h" % (ASK_TIMEOUT // 3600))

    def options(self):
        from claude_agent_sdk import ClaudeAgentOptions
        hooks = injected_hooks()
        # system_prompt — Claude Code's standard one: without it the SDK starts the session with an empty system
        # prompt, and Claude behaves differently than in the VS Code tab (seen 2026-10-15)
        kw = dict(cwd=self.path, system_prompt={"type": "preset", "preset": "claude_code"},
                  permission_mode=PERMISSION_MODE, can_use_tool=self._wait_hook,
                  setting_sources=["user", "project", "local"], settings=json.dumps({"hooks": hooks}),
                  # entrypoint: the SDK sets sdk-py, and VS Code hides sdk-* sessions from its list (a filter
                  # in extension 2.1.300). Without a terminal, Claude Code itself turns cli into sdk-cli;
                  # claude-vscode is kept: the session shows up in the Claude tab and can be continued on the Mac
                  env={"PULT_DRIVEN": "1", "PULT_SOCK": SOCK, "CLAUDE_CODE_ENTRYPOINT": "claude-vscode"},
                  max_buffer_size=SDK_LINE_MAX, stderr=lambda s: None)
        model, effort = self.d.wanted(getattr(self, "want_model", None), getattr(self, "want_effort", None))
        vid = self.d.store.vendor_of(self.sid)
        if vid:
            # another vendor's model (stage M, step 2): its profile in the environment, the owner's key in both of
            # Claude Code's places; never without the key — the subscription's own token would go there (pult_vendors)
            p, key = self.d.vendor_profiles().get(vid), self.d.vendor_key(vid)
            if not p or not key or self.d.vendor_stop(self.sid):
                raise RuntimeError("%s: no key, or the project no longer goes to other vendors" % vid)
            own = getattr(self, "want_model", None)
            model = own if own and own not in ("fable", "opus", "sonnet", "haiku") else p["models"][0]
            kw["env"] = dict(kw["env"], **V.session_env(p, key, model))
            effort = None                        # the vendor's own advice sets it (CLAUDE_CODE_EFFORT_LEVEL)
        if model:
            kw["model"] = model
        if effort:
            kw["effort"] = effort
        if self.resume:
            kw["resume"] = self.resume
        if self.fork:
            kw["fork_session"] = True
        if not self.resume or self.fork:
            kw["session_id"] = self.sid
        return ClaudeAgentOptions(**kw)

    async def read(self, c):
        """The whole SDK stream, not just up to our query's result: when a background task finishes, Claude Code
        starts a turn by itself, and its result would otherwise go to the next query (probe 2026-10-16, 2.1.301)."""
        from claude_agent_sdk import ResultMessage, SystemMessage
        try:
            async for m in c.receive_messages():
                if isinstance(m, ResultMessage):
                    if m.is_error:
                        await self.d.notice(self.sid, self.d.t("err.turn", err=R.esc(R.short(m.result or m.subtype, 600))),
                                            self.d.expect.get(self.sid))
                    ctx = ctx_from_usage(m.model_usage, self.model)
                    if ctx:
                        self.d.set_ctx(self.sid, *ctx, model=self.model)
                    self.d.result_seen(self.sid)
                    self.result.set()
                elif isinstance(m, SystemMessage) and m.subtype == "init":
                    self.model = m.data.get("model") or self.model
                elif isinstance(m, SystemMessage) and m.subtype == "background_tasks_changed":
                    self.bg = {t.get("task_id") for t in m.data.get("tasks") or [] if isinstance(t, dict)}
                    # the session's list of what runs in the background (from its last Stop) loses an ended task at
                    # once: the hooks hear of its end only at the turn's next step (tests/probe_bgmid.py, 2.1.300)
                    lv = self.d.live.get(self.sid)
                    if lv and any(b.get("id") not in self.bg for b in lv.bg):
                        lv.bg = [b for b in lv.bg if b.get("id") in self.bg]
                        self.d.changed(self.sid)
        finally:
            self.result.set()                    # the process has ended, so the query doesn't wait forever
            self.q.put_nowait(None)

    async def run(self):
        from claude_agent_sdk import ClaudeSDKClient
        try:
            async with ClaudeSDKClient(options=self.options()) as c:
                self.client = c
                reader = asyncio.create_task(self.read(c))
                try:
                    while True:
                        try:
                            item = await asyncio.wait_for(self.q.get(), timeout=DRIVEN_IDLE)
                        except asyncio.TimeoutError:
                            if self.busy or self.bg:
                                continue         # a background task lives as long as the process
                            break
                        if item is None:
                            break
                        text, origin = item
                        took = await self.slot(text, origin)
                        if took is None:
                            self.d.out_set(self.sid, "gone", text)       # Stop while it waited for a place
                            continue
                        try:
                            self.result.clear()
                            self.d.expect[self.sid] = origin
                            try:
                                await c.query(text)
                                self.asking = True       # only now: a message sent sooner must not overtake this one
                                await self.result.wait()
                            finally:
                                self.asking = False
                                self.d.expect.pop(self.sid, None)
                        finally:
                            if took:
                                self.d.run_sem.release()
                finally:
                    self.closing = True
                    reader.cancel()
                if reader.done() and not reader.cancelled():
                    if reader.exception():
                        raise reader.exception()
                    log("Telegram session %s: the Claude process exited by itself" % self.sid[:8])
        except Exception as e:
            log("Telegram session %s crashed: %r" % (self.sid[:8], e))
            await self.d.notice(self.sid, self.d.t("err.session", err=R.esc(R.short(repr(e), 600))))
        finally:
            self.closing = True
            self.client = None
            if self.d.driven.get(self.sid) is self:      # a message may have started a new one for the session meanwhile
                self.d.driven.pop(self.sid, None)
                self.d.out_gone_all(self.sid)
