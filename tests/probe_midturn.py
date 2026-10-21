"""Probe: a second prompt sent through the SDK while a turn is running — does Claude Code absorb it into that turn
(as in a VS Code tab: a queued_command attachment, absorbed_mid_turn), or run it as a turn of its own afterwards?

Run (uses a little of the subscription, ~40 s; with no argument, the claude the SDK carries — the one Pult's own
sessions run on):
  ~/.local/share/pult/venv/bin/python tests/probe_midturn.py [interrupt] [path to the claude binary]
Turn 1: Claude calls Bash `sleep 4; echo step N` for N = 1..5, one call at a time, then replies DONE.
~7 s in (step 2 running), a second prompt: stop, no more tools, reply HALTED.
  Absorbed: Claude reads it at the next tool boundary — one result, HALTED, steps 3..5 not run.
  Not absorbed: the first result is DONE after five steps, then a second turn HALTED.
With `interrupt` — right after the second prompt, an interrupt: is the waiting prompt dropped, or does it run as
the next turn (what the owner saw from Pult's own queue on 2026-10-21)? With `stop` — an interrupt alone, ~7 s in,
no second prompt. Both print the hook events: does an interrupted turn get a Stop (Pult closes a turn on it)?
User settings are not loaded (setting_sources=[]); PULT_OFF=1, so the real Pult does not see the events.
"""
import asyncio, json, sys, tempfile, time
from pathlib import Path
from claude_agent_sdk import (AssistantMessage, ClaudeAgentOptions, ClaudeSDKClient, PermissionResultAllow,
                              ResultMessage, SystemMessage, TextBlock, ToolUseBlock)

INTERRUPT = "interrupt" in sys.argv[1:]
STOP = "stop" in sys.argv[1:]
ARGS = [a for a in sys.argv[1:] if a not in ("interrupt", "stop")]
TMP = Path(tempfile.mkdtemp(prefix="pult-mid-"))
LOG = TMP / "hooks.jsonl"
HOOK = TMP / "hook.py"
HOOK.write_text("""import json, sys, time, os
d = json.load(sys.stdin)
d["_t"] = time.time()
open(os.environ["HOOK_LOG"], "a").write(json.dumps(d, ensure_ascii=False) + "\\n")
""")
EVENTS = ["UserPromptSubmit", "Stop", "StopFailure", "SessionEnd"]
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
        results, steps = 0, 0

        async def read():
            nonlocal results, steps
            async for m in c.receive_messages():
                if isinstance(m, SystemMessage) and m.subtype == "init":
                    say("SDK init: Claude Code", m.data.get("claude_code_version"), m.data.get("session_id"))
                elif isinstance(m, SystemMessage):
                    say("SDK system", m.subtype, json.dumps(m.data, ensure_ascii=False)[:200])
                elif isinstance(m, AssistantMessage):
                    for b in m.content:
                        if isinstance(b, ToolUseBlock):
                            steps += 1
                            say("SDK tool:", json.dumps(b.input, ensure_ascii=False)[:80])
                        elif isinstance(b, TextBlock) and b.text.strip():
                            say("SDK assistant:", b.text[:80])
                elif isinstance(m, ResultMessage):
                    results += 1
                    say("SDK result #%d" % results, m.subtype, repr((m.result or "")[:40]))

        reader = asyncio.create_task(read())
        await c.query("This is a test of a long turn. Call the Bash tool with command `sleep 4; echo step N` for N = 1, "
                      "2, 3, 4, 5 — one call at a time, waiting for each to finish before the next. Then reply with "
                      "one word: DONE. If at any point you get a new message from the user, follow it instead.")
        await asyncio.sleep(7)
        if STOP:
            say("--- interrupt, no second prompt")
            await c.interrupt()
        else:
            say("--- second prompt mid-turn")
            await c.query("Stop the test now: make no more tool calls and reply with one word: HALTED.")
        if INTERRUPT:
            await asyncio.sleep(0.5)
            say("--- interrupt")
            await c.interrupt()
        await asyncio.sleep(30)
        reader.cancel()
        say("--- итог: результатов %d, вызовов инструментов %d" % (results, steps))
    say("--- хуки:")
    for line in LOG.read_text().splitlines() if LOG.exists() else []:
        d = json.loads(line)
        print("%5.1f %s %s" % (d["_t"] - T0, d.get("hook_event_name"),
                               repr((d.get("prompt") or d.get("last_assistant_message") or "")[:50])), flush=True)
    say("--- транскрипт: user, attachment и queue-operation")
    for f in Path.home().glob(".claude/projects/*%s*/*.jsonl" % TMP.name.replace("_", "-")):
        for line in f.read_text().splitlines():
            e = json.loads(line)
            t = e.get("type")
            if t == "queue-operation":
                print("   ", t, e.get("operation"), repr((e.get("content") or "")[:60]), e.get("reason") or "", flush=True)
            elif t == "attachment" and (e.get("attachment") or {}).get("type") in ("queued_command", "edited_text_file"):
                a = e["attachment"]
                print("   ", t, a.get("type"), repr(str(a.get("prompt"))[:80]), a.get("commandMode") or "", flush=True)
            elif t == "user":
                cont = (e.get("message") or {}).get("content")
                if isinstance(cont, str) or any(b.get("type") == "text" for b in cont or []):
                    txt = cont if isinstance(cont, str) else " ".join(b.get("text", "") for b in cont if b.get("type") == "text")
                    print("   ", t, repr(txt[:80]), flush=True)


asyncio.run(main())
