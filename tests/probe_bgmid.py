"""Probe: a background task that ends while a turn still runs — what do the hooks and the SDK say then? Pult keeps a
session's background tasks from the Stop hook (background_tasks) and lets one go when a turn opens with its
<task-notification>; one that ended mid-turn stayed listed until the turn's end (`pult busy`, "in the background" on
the card — 2026-10-28). Does Claude Code tell its end mid-turn — a UserPromptSubmit with the running turn's
prompt_id and the notification as its prompt, like a message absorbed mid-turn (tests/probe_midturn.py)?

Run (uses a little of the subscription, ~30 s; with no argument, the claude the SDK carries):
  ~/.local/share/pult/venv/bin/python tests/probe_bgmid.py [path to the claude binary]
Turn 1: Bash in the background `sleep 3; echo BG`, then Bash `sleep 9; echo FG` (the background one ends during it),
then DONE. Printed: the SDK's system messages (background_tasks_changed), every hook event with its prompt_id and
the start of its prompt, and the Stop's background_tasks.
User settings are not loaded (setting_sources=[]); PULT_OFF=1, so the real Pult does not see the events.
"""
import asyncio, json, sys, tempfile, time
from pathlib import Path
from claude_agent_sdk import (AssistantMessage, ClaudeAgentOptions, ClaudeSDKClient, PermissionResultAllow,
                              ResultMessage, SystemMessage, TextBlock, ToolUseBlock)

ARGS = sys.argv[1:]
TMP = Path(tempfile.mkdtemp(prefix="pult-bgmid-"))
LOG = TMP / "hooks.jsonl"
HOOK = TMP / "hook.py"
HOOK.write_text("""import json, sys, time, os
d = json.load(sys.stdin)
d["_t"] = time.time()
open(os.environ["HOOK_LOG"], "a").write(json.dumps(d, ensure_ascii=False) + "\\n")
""")
EVENTS = ["UserPromptSubmit", "PostToolUse", "Stop", "StopFailure", "Notification", "SessionEnd"]
T0 = time.time()


def say(*a):
    print("%5.1f" % (time.time() - T0), *a, flush=True)


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
        results = 0

        async def read():
            nonlocal results
            async for m in c.receive_messages():
                if isinstance(m, SystemMessage) and m.subtype == "init":
                    say("SDK init: Claude Code", m.data.get("claude_code_version"))
                elif isinstance(m, SystemMessage):
                    say("SDK system", m.subtype, json.dumps(m.data, ensure_ascii=False)[:220])
                elif isinstance(m, AssistantMessage):
                    for b in m.content:
                        if isinstance(b, ToolUseBlock):
                            say("SDK tool:", json.dumps(b.input, ensure_ascii=False)[:90])
                        elif isinstance(b, TextBlock) and b.text.strip():
                            say("SDK assistant:", b.text[:80])
                elif isinstance(m, ResultMessage):
                    results += 1
                    say("SDK result #%d" % results, m.subtype, repr((m.result or "")[:40]))

        reader = asyncio.create_task(read())
        await c.query("This is a test of background tasks. First call the Bash tool with run_in_background set to true "
                      "and command `sleep 3; echo BG`. Right after it, call the Bash tool (not in the background) with "
                      "command `sleep 9; echo FG`. Then reply with one word: DONE. Nothing else.")
        await asyncio.sleep(35)
        reader.cancel()
        say("--- results: %d" % results)
    say("--- hooks:")
    for line in LOG.read_text().splitlines() if LOG.exists() else []:
        d = json.loads(line)
        extra = ""
        if d.get("hook_event_name") == "Stop":
            extra = " background_tasks=" + json.dumps(d.get("background_tasks"), ensure_ascii=False)[:160]
        print("%5.1f %s %s %s%s" % (d["_t"] - T0, d.get("hook_event_name"), (d.get("prompt_id") or "-")[:8],
                                    repr((d.get("prompt") or d.get("message") or d.get("last_assistant_message") or "")[:70]),
                                    extra), flush=True)


asyncio.run(main())
