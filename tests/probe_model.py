"""Probe: can the tab wrapper switch a VS Code tab's model? Claude Code 2.1.301.

The extension's own model picker ends in a `set_model` control request to the Claude Code process, and the tab's
webview learns the model from the process's replies (extension code). So the wrapper sends the same request. Here,
as in probe_tab.py, the Agent SDK stands in for the extension and a stand-in daemon for Pult:
1. a prompt on haiku — the reply's model;
2. the "daemon" tells the wrapper {"op": "model", "model": "sonnet"} — a control request goes into the process,
   its response is held back from the "extension";
3. another prompt — the reply's model must be a sonnet, and the "extension" must not have seen a stray response.
Run (a few small requests of the subscription): ~/.local/share/pult/venv/bin/python tests/probe_model.py [claude]
"""
import asyncio, json, os, subprocess, sys, tempfile, time
from pathlib import Path
from claude_agent_sdk import (AssistantMessage, ClaudeAgentOptions, ClaudeSDKClient, PermissionResultAllow,
                              ResultMessage, SystemMessage, TextBlock)

SRC = Path(__file__).resolve().parent.parent / "src"
CLI = sys.argv[1] if len(sys.argv) > 1 else str(max(
    [p for pat in (".vscode/extensions", ".vscode-server/extensions")
     for p in Path.home().glob(pat + "/anthropic.claude-code-*/resources/native-binary/claude")],
    key=lambda p: [int(x) for x in p.parts[-4].split("-")[2].split(".")]))
sys.path.insert(0, str(SRC))
import pult_tab  # noqa: E402
import pultd  # noqa: E402

VER = pult_tab.version_of(CLI)
print("Claude Code:", VER, flush=True)
TMP = Path(tempfile.mkdtemp(prefix="pult-model-"))
PROJ = TMP / "proj"
PROJ.mkdir()
SOCK = str(TMP / "d.sock")
(TMP / "tab.json").write_text(json.dumps({"folders": [str(PROJ)], "versions": [VER]}))
SHIM = TMP / "ext-spawn.sh"
SHIM.write_text('#!/bin/sh\nexec %s %s %s "$@"\n' % (sys.executable, SRC / "pult_tab.py", CLI))
SHIM.chmod(0o755)
LOG = TMP / "tab.log"
ENV = {"PULT_TAB_CONF": str(TMP / "tab.json"), "PULT_SOCK": SOCK, "PULT_OFF": "1"}
pult_tab.LOG = str(LOG)
T0 = time.time()


def say(*a):
    print("%5.1f" % (time.time() - T0), *a, flush=True)


async def allow(tool, inp, ctx):
    return PermissionResultAllow()


async def main():
    tabs = []

    async def daemon(reader, writer):
        hello = json.loads(await reader.readline())
        tabs.append({"hello": hello, "w": writer})
        while line := await reader.readline():
            pass
    server = await pultd.start_link(daemon, SOCK)
    env = dict(ENV, PULT_TAB_LOG=str(LOG))
    opts = ClaudeAgentOptions(cli_path=str(SHIM), cwd=str(PROJ), model="claude-haiku-5-5", permission_mode="default",
                              can_use_tool=allow, setting_sources=[], env=env, stderr=lambda s: None,
                              extra_args={"replay-user-messages": None})
    models, results, stray = [], [], []
    async with ClaudeSDKClient(options=opts) as c:
        async def read():
            async for m in c.receive_messages():
                if isinstance(m, AssistantMessage):
                    models.append(m.model)
                elif isinstance(m, ResultMessage):
                    results.append(sorted((m.model_usage or {}).keys()))
                elif isinstance(m, SystemMessage) and m.subtype not in ("init", "background_tasks_changed"):
                    stray.append(m.subtype)
        reader = asyncio.create_task(read())
        await c.query("Reply with one word: PING")
        while len(results) < 1:
            await asyncio.sleep(0.2)
        say("1. haiku replied:", models[-1], "| modelUsage:", results[-1])
        while not tabs:
            await asyncio.sleep(0.2)
        tabs[0]["w"].write(b'{"op": "model", "model": "sonnet"}\n')
        await tabs[0]["w"].drain()
        await asyncio.sleep(2)
        say("2. wrapper told to switch; wrapper log:", [l.split(" ", 3)[-1] for l in LOG.read_text().splitlines()[-3:]] if LOG.exists() else "no log")
        await c.query("Reply with one word: PONG")
        while len(results) < 2:
            await asyncio.sleep(0.2)
        say("3. after the switch:", models[-1], "| modelUsage:", results[-1])
        tabs[0]["w"].write(b'{"op": "model", "model": null}\n')
        await tabs[0]["w"].drain()
        await asyncio.sleep(2)
        await c.query("Reply with one word: PANG")
        while len(results) < 3:
            await asyncio.sleep(0.2)
        say("4. back to default (the launch model):", models[-1])
        reader.cancel()
    server.close()
    ok = "sonnet" in (models[-2] if len(models) >= 2 else "") and "haiku" in models[0]
    say("VERDICT:", "the wrapper switches the tab's model" if ok else "NO: " + str(models), "| stray system messages:", stray)
    print("log:", LOG)


asyncio.run(main())
