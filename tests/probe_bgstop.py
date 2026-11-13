"""Probe: stopping a session's background task from outside, the way the app's "Stop" would — the SDK's
ClaudeSDKClient.stop_task(task_id) (a control request, streaming mode only). Pult counts a session's background tasks
as busy, and "Install once they're free" waits for them with no limit: two hung waiters held it on 2026-11-11 (journal
21:40). Before a button stops one, the facts on this Claude Code: does stop_task end the process, how fast, what the
stream says (background_tasks_changed, task_updated, task_notification), does Claude start a turn by itself after it
(a turn would make the session busy again), and what the Stop hook's background_tasks then say.

Run (uses a little of the subscription, ~1 min; with no argument, the claude the SDK carries):
  ~/.local/share/pult/venv/bin/python tests/probe_bgstop.py [path to the claude binary]
Turn 1: Bash in the background `sleep 611; echo BG` (a marker no other process has), then DONE. After the turn's
result and the task in background_tasks_changed: stop_task(id); then 30 s of watching the stream, the hooks and ps.
User settings are not loaded (setting_sources=[]); PULT_OFF=1, so the real Pult does not see the events.
"""
import asyncio, json, subprocess, sys, tempfile, time
from pathlib import Path
from claude_agent_sdk import (AssistantMessage, ClaudeAgentOptions, ClaudeSDKClient, PermissionResultAllow,
                              ResultMessage, SystemMessage, TextBlock, ToolUseBlock)

ARGS = sys.argv[1:]
TMP = Path(tempfile.mkdtemp(prefix="pult-bgstop-"))
LOG = TMP / "hooks.jsonl"
HOOK = TMP / "hook.py"
HOOK.write_text("""import json, sys, time, os
d = json.load(sys.stdin)
d["_t"] = time.time()
open(os.environ["HOOK_LOG"], "a").write(json.dumps(d, ensure_ascii=False) + "\\n")
""")
EVENTS = ["UserPromptSubmit", "PostToolUse", "Stop", "StopFailure", "Notification", "SessionEnd"]
MARK = "sleep 611"
T0 = time.time()


def say(*a):
    print("%5.1f" % (time.time() - T0), *a, flush=True)


def alive():
    """The background command's processes, by its marker."""
    r = subprocess.run(["pgrep", "-f", MARK], capture_output=True, text=True)
    return [p for p in r.stdout.split() if p.strip()]


async def allow(tool, inp, ctx):
    return PermissionResultAllow()


async def main():
    cmd = "%s %s" % (sys.executable, HOOK)
    hooks = {ev: [{"matcher": "*", "hooks": [{"type": "command", "command": cmd, "timeout": 10}]}] for ev in EVENTS}
    kw = dict(cwd=str(TMP), model="claude-haiku-5-5", permission_mode="default", can_use_tool=allow,
              setting_sources=[], settings=json.dumps({"hooks": hooks}),
              env={"PULT_OFF": "1", "PULT_SOCK": "/nonexistent", "HOOK_LOG": str(LOG)}, stderr=lambda s: None)
    if ARGS:
        kw["cli_path"] = ARGS[0]
    async with ClaudeSDKClient(options=ClaudeAgentOptions(**kw)) as c:
        results, tasks, done = 0, {}, asyncio.Event()
        seen = asyncio.Event()

        async def read():
            nonlocal results, tasks
            async for m in c.receive_messages():
                if isinstance(m, SystemMessage) and m.subtype == "init":
                    say("SDK init: Claude Code", m.data.get("claude_code_version"))
                elif isinstance(m, SystemMessage):
                    if m.subtype == "background_tasks_changed":
                        tasks = {t.get("task_id"): t for t in m.data.get("tasks") or [] if isinstance(t, dict)}
                        if tasks:
                            seen.set()
                    say("SDK system", m.subtype, json.dumps(m.data, ensure_ascii=False)[:260])
                elif isinstance(m, AssistantMessage):
                    for b in m.content:
                        if isinstance(b, ToolUseBlock):
                            say("SDK tool:", json.dumps(b.input, ensure_ascii=False)[:120])
                        elif isinstance(b, TextBlock) and b.text.strip():
                            say("SDK assistant:", b.text[:100])
                elif isinstance(m, ResultMessage):
                    results += 1
                    say("SDK result #%d" % results, m.subtype, repr((m.result or "")[:60]))
                    done.set()

        reader = asyncio.create_task(read())
        await c.query("This is a test of background tasks. Call the Bash tool with run_in_background set to true and "
                      "command `%s; echo BG`. Then reply with one word: DONE. Nothing else, and don't wait for it." % MARK)
        await asyncio.wait_for(done.wait(), 120)
        await asyncio.wait_for(seen.wait(), 30)
        say("--- the turn is over; in the background:", list(tasks), "· processes:", alive())
        tid = next(iter(tasks))
        t_stop = time.time()
        await c.stop_task(tid)
        say("--- stop_task(%s) returned in %.2f s · processes: %s" % (tid, time.time() - t_stop, alive()))
        gone_at = None
        for _ in range(60):
            await asyncio.sleep(0.5)
            if gone_at is None and not alive():
                gone_at = time.time()
                say("--- the process is gone, %.1f s after stop_task" % (gone_at - t_stop))
        say("--- after 30 s: results %d (1 = no turn of its own after the stop), in the background: %s, processes: %s"
            % (results, list(tasks), alive()))
        reader.cancel()
    for p in alive():                               # never leave the marker's sleep behind
        subprocess.run(["kill", p])
    say("--- hooks:")
    for line in LOG.read_text().splitlines() if LOG.exists() else []:
        d = json.loads(line)
        extra = ""
        if d.get("hook_event_name") == "Stop":
            extra = " background_tasks=" + json.dumps(d.get("background_tasks"), ensure_ascii=False)[:200]
        print("%5.1f %s %s %s%s" % (d["_t"] - T0, d.get("hook_event_name"), (d.get("prompt_id") or "-")[:8],
                                    repr((d.get("prompt") or d.get("message") or d.get("last_assistant_message") or "")[:90]),
                                    extra), flush=True)


asyncio.run(main())
