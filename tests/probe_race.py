"""Probe: do the PermissionRequest hook and the permission window (can_use_tool, stdio as in VS Code) race?

Run (uses a little of the subscription, ~20 s; with no argument, the binary of the newest VS Code extension):
  ~/.local/share/pult/venv/bin/python tests/probe_race.py [path to the claude binary]
A: the window denies after 0.5 s, the hook allows after 6 s  → the command must NOT run, denied in ~0.5 s
B: the hook allows after 0.5 s, the window denies after 8 s  → the command must run in ~0.5 s, the late denial ignored
User settings are not loaded (setting_sources=[]); PULT_OFF=1, so the real Pult does not see the events.
"""
import asyncio, json, sys, tempfile, time
from pathlib import Path
from claude_agent_sdk import (ClaudeAgentOptions, ClaudeSDKClient, PermissionResultDeny, ResultMessage,
                              UserMessage, ToolResultBlock)

CLI = sys.argv[1] if len(sys.argv) > 1 else str(max(
    Path.home().glob(".vscode/extensions/anthropic.claude-code-*/resources/native-binary/claude"),
    key=lambda p: [int(x) for x in p.parts[-4].split("-")[2].split(".")]))
print("Claude Code:", CLI.split("/extensions/")[-1].split("/")[0] if "/extensions/" in CLI else CLI, flush=True)
TMP = Path(tempfile.mkdtemp(prefix="pult-race-"))
HOOK = TMP / "hook.py"
HOOK.write_text("""import json, sys, time, os
d = json.load(sys.stdin)
open(os.environ["MARK"], "a").write("hook %.2f %s\\n" % (time.time(), d.get("tool_name")))
time.sleep(float(os.environ["HOOK_DELAY"]))
print(json.dumps({"hookSpecificOutput": {"hookEventName": "PermissionRequest",
                  "decision": {"behavior": os.environ["HOOK_DECISION"]}}}))
""")


async def case(name, hook_delay, hook_decision, window_delay):
    cwd = TMP / name
    cwd.mkdir()
    mark = TMP / (name + ".mark")
    t = {}

    async def window(tool, inp, ctx):
        t.setdefault("window_called", time.time())
        await asyncio.sleep(window_delay)
        t["window_answered"] = time.time()
        return PermissionResultDeny(message="probe: window says no")

    hooks = {"PermissionRequest": [{"matcher": "*", "hooks": [
        {"type": "command", "command": "%s %s" % (sys.executable, HOOK), "timeout": 60}]}]}
    opts = ClaudeAgentOptions(cli_path=CLI, cwd=str(cwd), model="claude-haiku-5-5", permission_mode="default",
                              can_use_tool=window, setting_sources=[], settings=json.dumps({"hooks": hooks}),
                              env={"MARK": str(mark), "HOOK_DELAY": str(hook_delay), "HOOK_DECISION": hook_decision,
                                   "PULT_OFF": "1", "PULT_SOCK": "/nonexistent"},
                              stderr=lambda s: None)
    t0 = time.time()
    async with ClaudeSDKClient(options=opts) as c:
        await c.query("Run exactly this with the Bash tool: `echo hi > x.txt`. Do not retry if it is denied. "
                      "Then reply with one word: DONE or DENIED.")
        async for m in c.receive_response():
            if isinstance(m, UserMessage) and isinstance(m.content, list):
                for b in m.content:
                    if isinstance(b, ToolResultBlock) and "tool_result" not in t:
                        t["tool_result"] = time.time()
                        t["tool_result_text"] = str(b.content)[:80]
            if isinstance(m, ResultMessage):
                t["final"] = (m.result or "")[:40]
    await asyncio.sleep(max(0, window_delay + 1 - (time.time() - t0)))  # let the late answer try to break something
    hook_lines = mark.read_text().splitlines() if mark.exists() else []
    hook_called = float(hook_lines[0].split()[1]) if hook_lines else None
    base = min(x for x in (t.get("window_called"), hook_called) if x)
    rel = lambda k: "%.1f" % (t[k] - base) if k in t else "—"
    print("%s: x.txt=%s  хук вызван=%s  окно вызвано=%s  результат инструмента через %s с: %r  итог=%r" % (
        name, (cwd / "x.txt").exists(), "%.1f" % (hook_called - base) if hook_called else "НЕТ",
        rel("window_called"), rel("tool_result"), t.get("tool_result_text"), t.get("final")), flush=True)


async def main():
    await case("A", hook_delay=6, hook_decision="allow", window_delay=0.5)
    await case("B", hook_delay=0.5, hook_decision="allow", window_delay=8)

asyncio.run(main())
