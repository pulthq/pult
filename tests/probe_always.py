"""Probe: what does Claude Code offer as "always allow" with a permission request? Pult's card and its Telegram button
apply these suggestions as they are (`updatedPermissions`), and said nothing of what they are — one command, every `git`,
the whole of Bash, for the task or for good (review 2026-11-11, UX7). To say it in words Pult has to know their shapes.

Run (uses a little of the subscription, ~1 min; with no argument, the claude the SDK carries):
  ~/.local/share/pult/venv/bin/python tests/probe_always.py [path to the claude binary]
Claude is asked for six things one after another, each needing a permission: a plain command, a compound one, a new
file, an edit of a file outside the folder, a web page, a read outside the folder. Every request is refused; printed
for each: the tool, its input, and the suggestions — as the SDK's can_use_tool gets them (a task Pult runs) and as the
PermissionRequest hook gets them (a VS Code tab).
User settings are not loaded (setting_sources=[]); PULT_OFF=1, so the real Pult does not see the events.
"""
import asyncio, json, sys, tempfile, time
from pathlib import Path
from claude_agent_sdk import (AssistantMessage, ClaudeAgentOptions, ClaudeSDKClient, PermissionResultDeny, ResultMessage,
                              SystemMessage, TextBlock)

ARGS = sys.argv[1:]
TMP = Path(tempfile.mkdtemp(prefix="pult-always-"))
LOG = TMP / "hooks.jsonl"
HOOK = TMP / "hook.py"
HOOK.write_text("""import json, sys, os
d = json.load(sys.stdin)
open(os.environ["HOOK_LOG"], "a").write(json.dumps(d, ensure_ascii=False) + "\\n")
""")
T0 = time.time()
ASKS = [
    "Call the Bash tool with the command `npm test` exactly.",
    "Call the Bash tool with the command `make deploy-staging && git commit -qm probe` exactly.",
    "Call the Write tool to create the file notes.txt in the current folder with the text `probe`.",
    "Call the Write tool to create the file /tmp/pult-probe-always/outside.txt with the text `probe`.",
    "Call the WebFetch tool for https://example.com with the prompt `title`.",
    "Call the Read tool for the file /etc/hosts.",
]


def say(*a):
    print("%5.1f" % (time.time() - T0), *a, flush=True)


def plain(x):
    """A suggestion as plain data, whatever the SDK hands over (a dataclass with to_dict, or a dict)."""
    return x.to_dict() if hasattr(x, "to_dict") else x


async def refuse(tool, inp, ctx):
    got = [plain(s) for s in (getattr(ctx, "suggestions", None) or [])]
    say("ASK  %s %s" % (tool, json.dumps(inp, ensure_ascii=False)[:110]))
    for s in got:
        say("  can_use_tool:", json.dumps(s, ensure_ascii=False))
    if not got:
        say("  can_use_tool: no suggestions")
    return PermissionResultDeny(message="Refused by the probe. Don't retry; say REFUSED.")


async def main():
    cmd = "%s %s" % (sys.executable, HOOK)
    hooks = {"PermissionRequest": [{"matcher": "*", "hooks": [{"type": "command", "command": cmd, "timeout": 10}]}]}
    kw = dict(cwd=str(TMP), model="claude-haiku-5-5", permission_mode="default", can_use_tool=refuse,
              setting_sources=[], settings=json.dumps({"hooks": hooks}),
              env={"PULT_OFF": "1", "PULT_SOCK": "/nonexistent", "HOOK_LOG": str(LOG)}, stderr=lambda s: None)
    if ARGS:
        kw["cli_path"] = ARGS[0]
    async with ClaudeSDKClient(options=ClaudeAgentOptions(**kw)) as c:
        for ask in ASKS:
            await c.query("This is a test of permission requests. " + ask + " Call it at once, without a word; when "
                          "it is refused, answer REFUSED and nothing else.")
            async for m in c.receive_response():
                if isinstance(m, SystemMessage) and m.subtype == "init":
                    say("SDK init: Claude Code", m.data.get("claude_code_version"))
                elif isinstance(m, AssistantMessage):
                    for b in m.content:
                        if isinstance(b, TextBlock) and b.text.strip():
                            say("assistant:", b.text[:60])
                elif isinstance(m, ResultMessage):
                    break
    say("— the PermissionRequest hook's events —")
    for line in (LOG.read_text().splitlines() if LOG.exists() else []):
        d = json.loads(line)
        say("HOOK %s %s" % (d.get("tool_name"), json.dumps(d.get("tool_input"), ensure_ascii=False)[:90]))
        for s in d.get("permission_suggestions") or []:
            say("  hook:", json.dumps(s, ensure_ascii=False))
        if not d.get("permission_suggestions"):
            say("  hook: no suggestions; keys:", sorted(d))


asyncio.run(main())
