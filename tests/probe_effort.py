"""Probe: can the tab wrapper switch a VS Code tab's effort, for that process only? Claude Code 2.1.301.

The extension's own effort control writes effortLevel into the user's settings (update_settings, every session
follows). Pult switches one session instead: the apply_flag_settings control request puts effortLevel into the flag
layer of this process only; null takes it out again, back to what the settings say. Each request records its effort
in the transcript (the "effort" field of an assistant line), which is what this probe reads. As in probe_model.py,
the Agent SDK stands in for the extension and a stand-in daemon for Pult; the project's settings stand in for the
user's (effortLevel medium):
1. a prompt — effort medium (settings);
2. the "daemon" sends {"op": "control", ...} with effortLevel low → the next request is low; then max;
3. effortLevel null → back to medium; no stray control responses reach the "extension".
Then the same for a session Pult runs itself: no wrapper, pult_api.sdk_effort on the SDK client.
Run (a few small haiku requests): ~/.local/share/pult/venv/bin/python tests/probe_effort.py [claude]
"""
import asyncio, json, sys, tempfile, time
from pathlib import Path
from claude_agent_sdk import ClaudeAgentOptions, ClaudeSDKClient, PermissionResultAllow, ResultMessage, SystemMessage

SRC = Path(__file__).resolve().parent.parent / "src"
CLI = sys.argv[1] if len(sys.argv) > 1 else str(max(
    [p for pat in (".vscode/extensions", ".vscode-server/extensions")
     for p in Path.home().glob(pat + "/anthropic.claude-code-*/resources/native-binary/claude")],
    key=lambda p: [int(x) for x in p.parts[-4].split("-")[2].split(".")]))
sys.path.insert(0, str(SRC))
import pult_api  # noqa: E402
import pult_tab  # noqa: E402
import pultd  # noqa: E402

VER = pult_tab.version_of(CLI)
print("Claude Code:", VER, flush=True)
TMP = Path(tempfile.mkdtemp(prefix="pult-effort-"))
PROJ = TMP / "proj"
(PROJ / ".claude").mkdir(parents=True)
(PROJ / ".claude" / "settings.json").write_text(json.dumps({"effortLevel": "medium"}))
SOCK = str(TMP / "d.sock")
(TMP / "tab.json").write_text(json.dumps({"folders": [str(PROJ)], "versions": [VER]}))
SHIM = TMP / "ext-spawn.sh"
SHIM.write_text('#!/bin/sh\nexec %s %s %s "$@"\n' % (sys.executable, SRC / "pult_tab.py", CLI))
SHIM.chmod(0o755)
LOG = TMP / "tab.log"
T0 = time.time()


def say(*a):
    print("%5.1f" % (time.time() - T0), *a, flush=True)


async def allow(tool, inp, ctx):
    return PermissionResultAllow()


def efforts(sid):
    """The effort of each model request of the session, from its transcript."""
    out = []
    for f in (Path.home() / ".claude" / "projects").glob("*/%s.jsonl" % sid):
        for line in f.read_text().splitlines():
            e = json.loads(line)
            m = e.get("message") or {}
            if e.get("type") == "assistant" and m.get("usage") and m.get("id") not in [x[0] for x in out]:
                out.append((m.get("id"), e.get("effort")))
    return [x[1] for x in out]


async def main():
    tabs = []

    async def daemon(reader, writer):
        tabs.append({"hello": json.loads(await reader.readline()), "w": writer})
        while await reader.readline():
            pass
    server = await pultd.start_link(daemon, SOCK)
    env = {"PULT_TAB_CONF": str(TMP / "tab.json"), "PULT_SOCK": SOCK, "PULT_OFF": "1", "PULT_TAB_LOG": str(LOG)}
    opts = ClaudeAgentOptions(cli_path=str(SHIM), cwd=str(PROJ), model="claude-haiku-5-5", permission_mode="default",
                              can_use_tool=allow, setting_sources=["project"], env=env, stderr=lambda s: None,
                              extra_args={"replay-user-messages": None})
    results, stray, seen = [], [], []
    async with ClaudeSDKClient(options=opts) as c:
        async def read():
            async for m in c.receive_messages():
                if isinstance(m, ResultMessage):
                    results.append(m.session_id)
                elif isinstance(m, SystemMessage) and m.subtype not in ("init", "background_tasks_changed", "thinking_tokens"):
                    stray.append(m.subtype)
        reader = asyncio.create_task(read())

        async def turn(word, n):
            await c.query("Reply with one word: " + word)
            while len(results) < n:
                await asyncio.sleep(0.2)
            await asyncio.sleep(0.5)
            seen.append(efforts(results[-1])[-1])
            say(word, "→ effort", seen[-1])
        await turn("PING", 1)
        while not tabs:
            await asyncio.sleep(0.2)
        say("wrapper caps:", tabs[0]["hello"].get("caps"))
        for n, level in enumerate(("low", "max", None), start=2):
            req = {"subtype": "apply_flag_settings", "settings": {"effortLevel": level}}
            tabs[0]["w"].write((json.dumps({"op": "control", "request": req}) + "\n").encode())
            await tabs[0]["w"].drain()
            await asyncio.sleep(1.5)
            await turn("PONG%d" % n, n)
        reader.cancel()
    server.close()
    say("wrapper log:", [l.split(" ", 3)[-1] for l in LOG.read_text().splitlines()] if LOG.exists() else "no log")
    ok = seen == ["medium", "low", "max", "medium"]
    say("VERDICT:", "the wrapper switches the tab's effort, null goes back to the settings" if ok else "NO: %s" % seen,
        "| stray system messages:", stray)
    # a session Pult runs: the SDK client itself, the daemon's own function
    opts = ClaudeAgentOptions(cli_path=CLI, cwd=str(PROJ), model="claude-haiku-5-5", permission_mode="default",
                              can_use_tool=allow, setting_sources=["project"], env={"PULT_OFF": "1"}, stderr=lambda s: None)
    results.clear()
    sdk_seen = []
    async with ClaudeSDKClient(options=opts) as c:
        async def read2():
            async for m in c.receive_messages():
                if isinstance(m, ResultMessage):
                    results.append(m.session_id)
        reader = asyncio.create_task(read2())
        for n, level in enumerate((None, "high", None), start=1):
            if n > 1:
                await pult_api.sdk_effort(c, level)
            await c.query("Reply with one word: SDK%d" % n)
            while len(results) < n:
                await asyncio.sleep(0.2)
            await asyncio.sleep(0.5)
            sdk_seen.append(efforts(results[-1])[-1])
            say("SDK%d → effort" % n, sdk_seen[-1])
        reader.cancel()
    say("VERDICT (SDK):", "pult_api.sdk_effort switches a running session" if sdk_seen == ["medium", "high", "medium"]
        else "NO: %s" % sdk_seen)


asyncio.run(main())
