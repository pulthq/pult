"""Probe: what Claude Code reports about background tasks (Bash with run_in_background), in hooks and the SDK stream.

Run (uses a little of the subscription, ~40 s; with no argument, the binary of the newest VS Code extension):
  ~/.local/share/pult/venv/bin/python tests/probe_background.py [path to the claude binary]
Turn 1: Claude starts `sleep 6; echo bg-done` in the background and ends the turn right away.
  Expected: Stop has a background_tasks field with one shell/running task.
Then the task finishes on its own. We watch whether Claude starts a new turn without a prompt, whether
  UserPromptSubmit arrives and with what text, what this turn's Stop holds, and what is in the transcript.
User settings are not loaded (setting_sources=[]); PULT_OFF=1, so the real Pult does not see the events.
"""
import asyncio, json, sys, tempfile, time
from pathlib import Path
from claude_agent_sdk import (AssistantMessage, ClaudeAgentOptions, ClaudeSDKClient, PermissionResultAllow,
                              ResultMessage, SystemMessage, TextBlock)

CLI = sys.argv[1] if len(sys.argv) > 1 else str(max(
    Path.home().glob(".vscode/extensions/anthropic.claude-code-*/resources/native-binary/claude"),
    key=lambda p: [int(x) for x in p.parts[-4].split("-")[2].split(".")]))
print("Claude Code:", CLI.split("/extensions/")[-1].split("/")[0] if "/extensions/" in CLI else CLI, flush=True)
TMP = Path(tempfile.mkdtemp(prefix="pult-bg-"))
LOG = TMP / "hooks.jsonl"
HOOK = TMP / "hook.py"
HOOK.write_text("""import json, sys, time, os
d = json.load(sys.stdin)
d["_t"] = time.time()
open(os.environ["HOOK_LOG"], "a").write(json.dumps(d, ensure_ascii=False) + "\\n")
""")
EVENTS = ["SessionStart", "UserPromptSubmit", "PostToolUse", "Stop", "Notification", "SessionEnd"]
T0 = time.time()


def say(*a):
    print("%5.1f" % (time.time() - T0), *a, flush=True)


async def allow(tool, inp, ctx):
    return PermissionResultAllow()


async def main():
    cmd = "%s %s" % (sys.executable, HOOK)
    hooks = {ev: [{"matcher": "*", "hooks": [{"type": "command", "command": cmd, "timeout": 10}]}] for ev in EVENTS}
    opts = ClaudeAgentOptions(cli_path=CLI, cwd=str(TMP), model="claude-haiku-5-5", permission_mode="default",
                              can_use_tool=allow, setting_sources=[], settings=json.dumps({"hooks": hooks}),
                              env={"HOOK_LOG": str(LOG), "PULT_OFF": "1", "PULT_SOCK": "/nonexistent"},
                              stderr=lambda s: None)
    async with ClaudeSDKClient(options=opts) as c:
        await c.query("This is a test of background commands. Your first action must be a call to the Bash tool "
                      "with command `sleep 6; echo bg-done` and the parameter run_in_background: true. "
                      "After the tool call returns, do not wait or check on it: reply with one word, STARTED. "
                      "Later, when you are notified that the background command finished, reply with one word: FINISHED.")
        results = 0

        async def read():
            nonlocal results
            async for m in c.receive_messages():
                if isinstance(m, SystemMessage) and m.subtype != "init":
                    say("SDK system", m.subtype, json.dumps(m.data, ensure_ascii=False)[:300])
                elif isinstance(m, AssistantMessage):
                    txt = " ".join(b.text for b in m.content if isinstance(b, TextBlock))
                    if txt:
                        say("SDK assistant:", txt[:80])
                elif isinstance(m, ResultMessage):
                    results += 1
                    say("SDK result #%d" % results, m.subtype, repr((m.result or "")[:40]))

        reader = asyncio.create_task(read())
        await asyncio.sleep(35)                   # 6 s for the task + headroom for a new turn
        reader.cancel()
    say("--- хуки:")
    transcript = None
    for line in LOG.read_text().splitlines() if LOG.exists() else []:
        d = json.loads(line)
        transcript = d.get("transcript_path") or transcript
        ev = d.get("hook_event_name")
        extra = ""
        if ev == "UserPromptSubmit":
            extra = "prompt=%r" % (d.get("prompt") or "")[:160]
        elif ev == "Stop":
            extra = "background_tasks=%s session_crons=%s last=%r" % (
                json.dumps(d.get("background_tasks", "НЕТ ПОЛЯ"), ensure_ascii=False),
                json.dumps(d.get("session_crons", "НЕТ ПОЛЯ")), (d.get("last_assistant_message") or "")[:30])
        elif ev == "PostToolUse":
            extra = "%s bg=%s resp=%s" % (d.get("tool_name"), (d.get("tool_input") or {}).get("run_in_background"),
                                          json.dumps(d.get("tool_response"), ensure_ascii=False)[:200])
        elif ev == "Notification":
            extra = json.dumps({k: v for k, v in d.items() if k not in ("session_id", "transcript_path", "cwd")},
                               ensure_ascii=False)[:200]
        print("%5.1f %s %s" % (d["_t"] - T0, ev, extra), flush=True)
    say("--- транскрипт: записи с task-notification")
    if transcript and Path(transcript).exists():
        for line in Path(transcript).read_text().splitlines():
            if "task-notification" not in line:
                continue
            e = json.loads(line)
            content = (e.get("message") or {}).get("content") or e.get("content") or (e.get("attachment") or {}).get("prompt")
            print("   ", e.get("type"), e.get("operation") or (e.get("attachment") or {}).get("type") or "",
                  "origin=%s" % json.dumps(e.get("origin")), repr(str(content)[:120]), flush=True)


asyncio.run(main())
