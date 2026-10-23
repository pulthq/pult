"""Probe: a session Pult runs in a folder made a moment ago — does it start, and can its first turn write CLAUDE.md there.

Run (uses a little of the subscription, ~30 s; with no argument, the claude the SDK carries — the one Pult's own
sessions run on):
  ~/.local/share/pult/venv/bin/python tests/probe_newdir.py [path to the claude binary]
A new folder (git init, nothing else, never opened by Claude Code) gets a session with Pult's own options — the user's
settings, permission mode auto, the standard system prompt — and the prompt stage S sends for "with a description".
Expected (2026-10-23): no question about trusting the folder (that dialog belongs to the terminal UI), the turn ends
with its result, CLAUDE.md is in the folder. PULT_OFF=1 and a dead socket, so the real Pult does not see the session;
the folder is under the temp directory, which Pult never lists as a project.
"""
import asyncio, os, shutil, subprocess, sys, tempfile, time
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent / "src"
TMP = Path(tempfile.mkdtemp(prefix="pult-newdir-"))
os.environ.update(PULT_HOME=str(TMP / "home"), PULT_SOCK=str(TMP / "s.sock"), PULT_ENV=str(TMP / "env"))
sys.path.insert(0, str(SRC))
import pultd  # noqa: E402
import pult_new  # noqa: E402
import claude_agent_sdk  # noqa: E402
from claude_agent_sdk import (AssistantMessage, ClaudeAgentOptions, ClaudeSDKClient, PermissionResultAllow,  # noqa: E402
                              ResultMessage, SystemMessage, ToolUseBlock)

CLI = sys.argv[1] if len(sys.argv) > 1 else None
RUNS = CLI or str(Path(claude_agent_sdk.__file__).parent / "_bundled" / ("claude.exe" if os.name == "nt" else "claude"))
T0 = time.time()
asked = []


def say(*a):
    print("%5.1f" % (time.time() - T0), *a, flush=True)


async def allow(tool, inp, ctx):
    asked.append(tool)
    return PermissionResultAllow()


async def main():
    say("Claude Code %s, SDK %s" % (subprocess.run([RUNS, "-v"], capture_output=True, text=True).stdout.split()[0],
                                    claude_agent_sdk.__version__))
    d = TMP / "dacha_u_morya"
    d.mkdir()
    subprocess.run(["git", "init", "-q", str(d)], check=True)
    kw = dict(cwd=str(d), system_prompt={"type": "preset", "preset": "claude_code"}, model="claude-haiku-5-5",
              permission_mode=pultd.PERMISSION_MODE, can_use_tool=allow, setting_sources=["user", "project", "local"],
              env={"PULT_OFF": "1", "PULT_SOCK": "/nonexistent", "CLAUDE_CODE_ENTRYPOINT": "claude-vscode"},
              max_buffer_size=pultd.SDK_LINE_MAX, stderr=lambda s: None)
    if CLI:
        kw["cli_path"] = CLI
    tools, result = [], None
    async with ClaudeSDKClient(options=ClaudeAgentOptions(**kw)) as c:
        await c.query(pult_new.describe_prompt("Дача у моря", "Учёт дел по даче: посадки, полив, покупки. Пока только записи."))
        async for m in c.receive_messages():
            if isinstance(m, SystemMessage) and m.subtype == "init":
                say("init: cwd %s, permission mode %s" % (m.data.get("cwd"), m.data.get("permissionMode")))
            if isinstance(m, AssistantMessage):
                tools += [b.name for b in m.content if isinstance(b, ToolUseBlock)]
            if isinstance(m, ResultMessage):
                result = m
                break
    say("result: %s, %d turns, tools %s, asked to allow: %s" % (result and result.subtype, result and result.num_turns,
                                                                 tools, asked or "nothing"))
    md = d / "CLAUDE.md"
    if md.exists():
        say("CLAUDE.md, %d bytes:\n%s" % (md.stat().st_size, md.read_text()[:600]))
    else:
        say("NO CLAUDE.md; files:", sorted(p.name for p in d.iterdir()))
    shutil.rmtree(TMP, ignore_errors=True)


asyncio.run(main())
