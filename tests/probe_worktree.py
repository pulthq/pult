"""Probe: a session Claude Code moves into a git worktree — where its transcript goes, and what its hooks say then
(transcript_path, cwd). Pult takes a session's project from the transcript's folder (pultd.hook_event), so a transcript
that moves takes the session to another project. Two ways in, both from the folder the session started in:
  a) EnterWorktree with a name — a worktree Claude Code makes itself, under .claude/worktrees/;
  b) EnterWorktree with a path — a worktree of a repository nested in that folder, made by `git worktree add` (the layout
     of one big project whose parts are their own repositories), then ExitWorktree.

Run (uses a little of the subscription, ~2 min; with no argument, the claude the SDK carries — the one Pult's own
sessions run on; pass the VS Code extension's binary to check the tabs' version):
  ~/.local/share/pult/venv/bin/python tests/probe_worktree.py [path to the claude binary]
The hooks are the probe's own (each event's cwd and transcript_path into a log); user settings are not loaded
(setting_sources=[]), so the real Pult hook doesn't run; the folders are under the temp directory, which Pult never lists.
Seen (2026-10-31, the same on 2.1.300 — the SDK's — and 2.1.314 — VS Code's):
  a) the transcript moves: right after EnterWorktree it lives in the worktree's own folder of ~/.claude/projects
     (<project>--claude-worktrees-<name>), the start folder's is left empty, and every later hook gives that new
     transcript_path; ExitWorktree moves it back. Pult would see the session's project change in the middle of it;
  b) the transcript stays in the start folder's; only the hooks' cwd follows the worktree and comes back on exit.
"""
import asyncio, json, os, subprocess, sys, tempfile, time, uuid
from pathlib import Path

import claude_agent_sdk
from claude_agent_sdk import (AssistantMessage, ClaudeAgentOptions, ClaudeSDKClient, PermissionResultAllow,
                              ResultMessage, TextBlock, ToolUseBlock)

CLI = sys.argv[1] if len(sys.argv) > 1 else None
RUNS = CLI or str(Path(claude_agent_sdk.__file__).parent / "_bundled" / ("claude.exe" if os.name == "nt" else "claude"))
TMP = Path(os.path.realpath(tempfile.mkdtemp(prefix="pult-wt-")))
PROJ = TMP / "proj"                    # the folder sessions start in: a repository of its own
COMP = PROJ / "comp"                   # a part of it that is a repository of its own, ignored by the outer one
WT = PROJ / "wt" / "comp-x"            # a worktree of comp, inside the project's folder
LOG = TMP / "hook.log"
HOOK = TMP / "hook.py"
HOOK.write_text("""import json, sys
ev = json.load(sys.stdin)
open(%r, "a").write(json.dumps({k: ev.get(k) for k in ("hook_event_name", "session_id", "cwd", "transcript_path",
                                                        "tool_name")}) + "\\n")
""" % str(LOG))
EVENTS = ("SessionStart", "UserPromptSubmit", "PostToolUse", "Stop", "SessionEnd")
PROJECTS = Path.home() / ".claude" / "projects"
T0 = time.time()


def say(*a):
    print("%5.1f" % (time.time() - T0), *a, flush=True)


def git(cwd, *a):
    subprocess.run(["git", "-C", str(cwd), *a], check=True, capture_output=True)


def setup():
    for d in (PROJ, COMP):
        d.mkdir(parents=True, exist_ok=True)
        git(d, "init", "-q", "-b", "main")
        git(d, "config", "user.email", "probe@example.com")
        git(d, "config", "user.name", "probe")
    (PROJ / ".gitignore").write_text("comp/\nwt/\n")
    (PROJ / "README.md").write_text("outer\n")
    git(PROJ, "add", "-A")
    git(PROJ, "commit", "-q", "-m", "outer")
    (COMP / "part.txt").write_text("inner\n")
    git(COMP, "add", "-A")
    git(COMP, "commit", "-q", "-m", "inner")
    WT.parent.mkdir(parents=True, exist_ok=True)
    git(COMP, "worktree", "add", "-q", str(WT), "-b", "x")


def key(p):
    return "".join(c if c.isalnum() else "-" for c in str(p))


def transcripts():
    """The probe's transcript folders in ~/.claude/projects: {folder name: [(file, lines)]}."""
    pre = key(TMP)
    out = {}
    for d in sorted(PROJECTS.glob(pre + "*")):
        out[d.name[len(pre):] or "."] = [(f.name[:8], sum(1 for _ in f.open("rb"))) for f in sorted(d.glob("*.jsonl"))]
    return out


async def allow(tool, inp, ctx):
    return PermissionResultAllow()


async def session(label, prompts):
    sid = str(uuid.uuid4())
    hooks = {e: [{"hooks": [{"type": "command", "command": "%s %s" % (sys.executable, HOOK)}]}] for e in EVENTS}
    kw = dict(cwd=str(PROJ), model="claude-haiku-5-5", permission_mode="default", can_use_tool=allow,
              setting_sources=[], session_id=sid, env={"PULT_OFF": "1"}, stderr=lambda s: None,
              settings=json.dumps({"hooks": hooks, "worktree": {"baseRef": "head"}}))
    if CLI:
        kw["cli_path"] = CLI
    say("— %s: session %s" % (label, sid[:8]))
    async with ClaudeSDKClient(options=ClaudeAgentOptions(**kw)) as c:
        for p in prompts:
            await c.query(p)
            tools, text = [], []
            async for m in c.receive_messages():
                if isinstance(m, AssistantMessage):
                    tools += [b.name for b in m.content if isinstance(b, ToolUseBlock)]
                    text += [b.text for b in m.content if isinstance(b, TextBlock)]
                if isinstance(m, ResultMessage):
                    break
            say("  turn: tools %s · %s" % (", ".join(tools) or "none", " ".join(text)[:140].replace("\n", " ")))
            say("  transcripts now:", transcripts())
    await asyncio.sleep(1)
    return sid


def events(sid):
    pre = str(TMP)
    for line in LOG.read_text().splitlines():
        e = json.loads(line)
        if e["session_id"] != sid:
            continue
        tp = (e["transcript_path"] or "").replace(str(PROJECTS) + os.sep + key(TMP), "<projects>/<tmp>")
        say("  %-16s %-12s cwd=%s  transcript=%s" % (e["hook_event_name"], e["tool_name"] or "",
                                                     (e["cwd"] or "").replace(pre, "<tmp>"), tp))


async def main():
    say("Claude Code %s, SDK %s, folder %s" % (subprocess.run([RUNS, "-v"], capture_output=True, text=True).stdout.split()[0],
                                               claude_agent_sdk.__version__, TMP))
    setup()
    a = await session("a) a worktree Claude Code makes", [
        "Use the EnterWorktree tool with name probe-a. Then run with the Bash tool: pwd. Reply with its output only.",
        "Run with the Bash tool: pwd. Reply with its output only.",
        "Use the ExitWorktree tool with action keep. Then run with the Bash tool: pwd. Reply with its output only.",
        "Run with the Bash tool: pwd. Reply with its output only.",
    ])
    events(a)
    b = await session("b) a nested repository's worktree, by path", [
        "Use the EnterWorktree tool with path %s. Then run with the Bash tool: pwd. Reply with its output only." % WT,
        "Run with the Bash tool: pwd. Reply with its output only.",
        "Use the ExitWorktree tool with action keep. Then run with the Bash tool: pwd. Reply with its output only.",
        "Run with the Bash tool: pwd. Reply with its output only.",
    ])
    events(b)
    say("transcript folders at the end:", transcripts())


asyncio.run(main())
