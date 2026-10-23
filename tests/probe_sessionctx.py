"""Probe: what a SessionStart hook adds to the context reaches the model — on a new session and on a resumed one — and
a command Claude runs knows its session (CLAUDE_CODE_SESSION_ID, CLAUDE_PID): what `pult send` relies on (stage F).

Run (uses a little of the subscription, ~40 s; with no argument, the claude the SDK carries — the one Pult's own
sessions run on; pass the VS Code extension's binary to check the tabs' version):
  ~/.local/share/pult/venv/bin/python tests/probe_sessionctx.py [path to the claude binary]
The hook is the probe's own (prints hookSpecificOutput.additionalContext with a code word); user settings are not
loaded (setting_sources=[]), so the real Pult hook doesn't run. Expected (2026-10-23): the code word is known on
start, and the resume's own word after a resume; the command's CLAUDE_CODE_SESSION_ID is the session's id and CLAUDE_PID its claude process.
"""
import asyncio, json, os, re, subprocess, sys, tempfile, time, uuid
from pathlib import Path

import claude_agent_sdk
from claude_agent_sdk import (AssistantMessage, ClaudeAgentOptions, ClaudeSDKClient, PermissionResultAllow,  # noqa: E402
                              ResultMessage, TextBlock, ToolResultBlock, UserMessage)

CLI = sys.argv[1] if len(sys.argv) > 1 else None
RUNS = CLI or str(Path(claude_agent_sdk.__file__).parent / "_bundled" / ("claude.exe" if os.name == "nt" else "claude"))
TMP = Path(tempfile.mkdtemp(prefix="pult-ctx-"))
HOOK = TMP / "hook.py"
HOOK.write_text("""import json, sys
ev = json.load(sys.stdin)
open(%r, "a").write(json.dumps({"source": ev.get("source"), "sid": ev.get("session_id")}) + "\\n")
word = "MANGO-3" if ev.get("source") == "resume" else "PAPAYA-7"
print(json.dumps({"hookSpecificOutput": {"hookEventName": "SessionStart",
                  "additionalContext": "Probe note: the code word for this session is now " + word + "."}}))
""" % str(TMP / "hook.log"))
T0 = time.time()


def say(*a):
    print("%5.1f" % (time.time() - T0), *a, flush=True)


async def allow(tool, inp, ctx):
    return PermissionResultAllow()


async def turn(sid, prompt, resume=False):
    kw = dict(cwd=str(TMP), model="claude-haiku-5-5", permission_mode="default", can_use_tool=allow, setting_sources=[],
              settings=json.dumps({"hooks": {"SessionStart": [{"hooks": [{"type": "command", "command": "%s %s" % (sys.executable, HOOK)}]}]}}),
              env={"PULT_OFF": "1"}, stderr=lambda s: None)
    kw["resume" if resume else "session_id"] = sid
    if CLI:
        kw["cli_path"] = CLI
    text, tool_out = [], []
    async with ClaudeSDKClient(options=ClaudeAgentOptions(**kw)) as c:
        await c.query(prompt)
        async for m in c.receive_messages():
            if isinstance(m, AssistantMessage):
                text += [b.text for b in m.content if isinstance(b, TextBlock)]
            if isinstance(m, UserMessage) and isinstance(m.content, list):
                tool_out += [str(b.content) for b in m.content if isinstance(b, ToolResultBlock)]
            if isinstance(m, ResultMessage):
                break
    return " ".join(text), " ".join(tool_out)


async def main():
    say("Claude Code %s, SDK %s" % (subprocess.run([RUNS, "-v"], capture_output=True, text=True).stdout.split()[0],
                                    claude_agent_sdk.__version__))
    sid = str(uuid.uuid4())
    text, out = await turn(sid, "Two things. 1) Reply with the code word for this session if your context gives one, "
                                "else say NONE. 2) Run with the Bash tool exactly: echo SID=$CLAUDE_CODE_SESSION_ID PID=$CLAUDE_PID")
    m = re.search(r"SID=(\S*) PID=(\S*)", out)
    say("start: code word %s · command env %s" % ("known" if "PAPAYA-7" in text else "NOT known (%r)" % text[:120],
                                                    m.groups() if m else repr(out[:120])))
    say("  the command's session id is the session's:", bool(m and m.group(1) == sid), "· pid given:", bool(m and m.group(2).isdigit()))
    # a resume gets its own word: known only if the hook's context came again, not from the history
    text, _ = await turn(sid, "Reply with the newest code word your context gives for this session, else NONE. No tools.", resume=True)
    say("resume: the new code word", "known" if "MANGO-3" in text else "NOT known (%r)" % text[:120])
    say("hook runs:", (TMP / "hook.log").read_text().strip().replace("\n", " | "))


asyncio.run(main())
