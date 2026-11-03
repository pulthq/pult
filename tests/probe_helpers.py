"""Probe: what Claude Code tells about a helper (Agent) and a command it starts in the background, at the moment it
starts them. Pult used to learn of background tasks only from the Stop hook's background_tasks — after the turn; the
app shows "N helpers, M commands in the background" next to "working…" from their start (Q128, 2026-11-03). Is the
PostToolUse of a background Agent and a background Bash enough: its tool_response with the task's id, the helper's
type and model? Is that id the one the end's <task-notification> (or the helper's own <agent-message>) and Stop's
background_tasks carry? Where is the helper's own transcript, and what does it hold?

Run (uses a little of the subscription, ~1 min; with no argument, the claude the SDK carries):
  ~/.local/share/pult/venv/bin/python tests/probe_helpers.py [path to the claude binary]
Turn 1: Agent in the background (general-purpose: `sleep 6; echo ONE TWO THREE`), Bash in the background
`sleep 4; echo BG`, then DONE. Printed: every hook event — PostToolUse with its tool_response, Stop with its
background_tasks, UserPromptSubmit with the start of its prompt — and the helper's transcript folder.
User settings are not loaded (setting_sources=[]); PULT_OFF=1, so the real Pult does not see the events.
"""
import asyncio, json, sys, tempfile, time
from pathlib import Path
from claude_agent_sdk import (AssistantMessage, ClaudeAgentOptions, ClaudeSDKClient, PermissionResultAllow,
                              ResultMessage, SystemMessage, ToolUseBlock)

ARGS = sys.argv[1:]
TMP = Path(tempfile.mkdtemp(prefix="pult-helpers-"))
LOG = TMP / "hooks.jsonl"
HOOK = TMP / "hook.py"
HOOK.write_text("""import json, sys, time, os
d = json.load(sys.stdin)
d["_t"] = time.time()
open(os.environ["HOOK_LOG"], "a").write(json.dumps(d, ensure_ascii=False) + "\\n")
""")
EVENTS = ["UserPromptSubmit", "PostToolUse", "Stop", "SessionEnd"]
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
                    say("SDK system", m.subtype, json.dumps(m.data, ensure_ascii=False)[:240])
                elif isinstance(m, AssistantMessage):
                    for b in m.content:
                        if isinstance(b, ToolUseBlock):
                            say("SDK tool:", b.name, json.dumps(b.input, ensure_ascii=False)[:110])
                elif isinstance(m, ResultMessage):
                    results += 1
                    say("SDK result #%d" % results, m.subtype, repr((m.result or "")[:40]))

        reader = asyncio.create_task(read())
        await c.query("This is a test of background helpers. First call the Agent tool with subagent_type "
                      "\"general-purpose\", run_in_background set to true, description \"Count to three\" and prompt "
                      "\"Run the Bash command `sleep 6; echo ONE TWO THREE` and reply with its output only.\". Right "
                      "after it, call the Bash tool with run_in_background set to true and command `sleep 4; echo BG`. "
                      "Then reply with one word: DONE. When a background task finishes later, reply with one word: OK.")
        await asyncio.sleep(70)
        reader.cancel()
        say("--- results: %d" % results)
    say("--- hooks:")
    transcript = None
    for line in LOG.read_text().splitlines() if LOG.exists() else []:
        d = json.loads(line)
        transcript = d.get("transcript_path") or transcript
        ev = d.get("hook_event_name")
        if ev == "PostToolUse":
            extra = "%s tool_response=%s" % (d.get("tool_name"), json.dumps(d.get("tool_response"), ensure_ascii=False)[:420])
        elif ev == "Stop":
            extra = "background_tasks=" + json.dumps(d.get("background_tasks"), ensure_ascii=False)[:600]
        else:
            extra = repr((d.get("prompt") or d.get("last_assistant_message") or "")[:300])
        print("%5.1f %s %s %s" % (d["_t"] - T0, ev, (d.get("prompt_id") or "-")[:8], extra), flush=True)
    if transcript:
        sub = Path(transcript).with_suffix("") / "subagents"
        print("--- helper transcripts in", sub, flush=True)
        for f in sorted(sub.glob("*")) if sub.is_dir() else []:
            if f.suffix == ".json":
                print(f.name, f.read_text()[:400], flush=True)
            else:
                rows = [json.loads(x) for x in f.read_text().splitlines() if x.strip()]
                uses = [b.get("name") for r in rows if r.get("type") == "assistant"
                        for b in (r.get("message") or {}).get("content") or [] if isinstance(b, dict) and b.get("type") == "tool_use"]
                models = {(r.get("message") or {}).get("model") for r in rows if r.get("type") == "assistant"}
                print(f.name, "%d lines, tools %s, models %s, first %s" % (len(rows), uses, models,
                                                                         rows[0].get("timestamp") if rows else None), flush=True)


asyncio.run(main())
