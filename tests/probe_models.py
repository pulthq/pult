"""Probe: the models Claude Code names at start-up — each row of its model menu with the model it resolves to.

Run (free: no request to a model, ~3 s a binary; with no argument — every Claude Code on this computer: the one the
Agent SDK carries, Pult's own copies, the VS Code extensions):
  ~/.local/share/pult/venv/bin/python tests/probe_models.py [path to a claude binary ...]
The answer to `initialize` (ClaudeSDKClient.get_server_info()) carries "models": the rows the extension's model menu
shows — "value" (an alias or a model id), "resolvedModel" (the model id the value resolves to), "displayName",
"description". An alias moves with Claude Code's own catalog and with what the server sends: 2026-11-10 "fable" was
claude-fable-5-1 up to 2.1.319 and claude-fable-5-2 in 2.1.322, while every version listed claude-fable-5-2 on a
row of its own (project.html #model-versions). Nothing is asked, so no transcript is written; user settings and
hooks are not loaded (setting_sources=[]); PULT_OFF=1, so the real Pult does not see the sessions.
"""
import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path

from claude_agent_sdk import ClaudeAgentOptions, ClaudeSDKClient

EXE = "claude.exe" if os.name == "nt" else "claude"
ALIASES = ("default", "fable", "opus", "sonnet", "haiku")


def binaries():
    """Every Claude Code here: the SDK's own, Pult's copies (stage A2), the VS Code extensions."""
    import claude_agent_sdk
    found = [Path(claude_agent_sdk.__file__).parent / "_bundled" / EXE]
    found += sorted((Path.home() / ".local" / "share" / "pult" / "claude").glob("*/" + EXE))
    for pat in (".vscode/extensions", ".vscode-server/extensions"):
        found += sorted(Path.home().glob(pat + "/anthropic.claude-code-*/resources/native-binary/" + EXE))
    return [p for p in found if p.is_file()]


async def models_of(cli, cwd):
    """(version, rows) of one claude binary, without a single request to a model."""
    opts = ClaudeAgentOptions(cli_path=str(cli), cwd=str(cwd), setting_sources=[], tools=[],
                              env={"PULT_OFF": "1", "PULT_SOCK": str(Path(cwd) / "none")}, stderr=lambda s: None)
    async with ClaudeSDKClient(options=opts) as c:
        info = await c.get_server_info() or {}
    return info.get("claude_code_version"), info.get("models")


async def main():
    paths = [Path(p) for p in sys.argv[1:]] or binaries()
    bad = 0
    with tempfile.TemporaryDirectory(prefix="pult-probe-models-") as tmp:
        for cli in paths:
            try:
                ver, rows = await models_of(cli, tmp)
            except Exception as e:                      # couldn't start or lost it: say so and go on
                print("FAIL %s: %s: %s" % (cli, type(e).__name__, str(e)[:160]))
                bad += 1
                continue
            if not isinstance(rows, list) or not rows:
                print("FAIL %s (%s): no models in the answer to initialize" % (cli, ver))
                bad += 1
                continue
            print("== %s — Claude Code %s, %d rows" % (cli, ver, len(rows)))
            for r in rows:
                print("   %-26s → %-26s %s" % (r.get("value"), r.get("resolvedModel"), r.get("displayName")))
            got = {r.get("value"): r.get("resolvedModel") for r in rows}
            missing = [a for a in ALIASES if not got.get(a)]
            if missing:
                print("FAIL %s: no resolved model for %s" % (ver, ", ".join(missing)))
                bad += 1
            print(json.dumps({"version": ver, "aliases": {a: got.get(a) for a in ALIASES}}))
    sys.exit(1 if bad else 0)


asyncio.run(main())
