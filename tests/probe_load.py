"""Probe: how a background task of Claude Code looks among the Mac's processes — for the load view (0.9.16).

Run (uses a little of the subscription, ~30 s; with no argument, the binary of the newest VS Code extension):
  ~/.local/share/pult/venv/bin/python tests/probe_load.py [path to the claude binary]
Claude starts `sleep 20; echo "it's done"` in the background and ends the turn. Then, while the task runs:
  1. Stop's background_tasks: the task's id, type and command, exactly as Claude Code reports them;
  2. the process tree under this session's claude: is the task a child shell, and does its command line hold the
     command as `eval '<command>'` (a single quote written as '"'"'), so a task can be found by its text;
  3. `claude agents --json`: is a session started through the SDK (entrypoint claude-vscode, as Pult starts them)
     listed, and with which pid;
  4. the pid the hook sees as its parent (pult_hook.py sends os.getppid()): is it claude itself.
User settings are not loaded (setting_sources=[]); PULT_OFF=1, so the real Pult does not see the events.
"""
import asyncio, json, os, subprocess, sys, tempfile
from pathlib import Path
from claude_agent_sdk import ClaudeAgentOptions, ClaudeSDKClient, PermissionResultAllow, ResultMessage

CLI = sys.argv[1] if len(sys.argv) > 1 else str(max(
    Path.home().glob(".vscode/extensions/anthropic.claude-code-*/resources/native-binary/claude"),
    key=lambda p: [int(x) for x in p.parts[-4].split("-")[2].split(".")]))
print("Claude Code:", CLI.split("/extensions/")[-1].split("/")[0] if "/extensions/" in CLI else CLI, flush=True)
TMP = Path(tempfile.mkdtemp(prefix="pult-load-"))
LOG = TMP / "hooks.jsonl"
HOOK = TMP / "hook.py"
HOOK.write_text("""import json, sys, time, os
d = json.load(sys.stdin)
d["_t"] = time.time()
d["_ppid"] = os.getppid()
open(os.environ["HOOK_LOG"], "a").write(json.dumps(d, ensure_ascii=False) + "\\n")
""")
CMD = 'sleep 20; echo "it\'s done"'


def procs():
    out = subprocess.run(["ps", "-axww", "-o", "pid=,ppid=,args="], capture_output=True, text=True).stdout
    rows = {}
    for line in out.splitlines():
        p = line.split(None, 2)
        if len(p) >= 2:
            rows[int(p[0])] = (int(p[1]), p[2] if len(p) > 2 else "")
    return rows


def under(rows, root):
    out, todo = [], [root]
    while todo:
        p = todo.pop()
        kids = [c for c, (pp, _) in rows.items() if pp == p]
        out += kids
        todo += kids
    return out


def quoted(cmd):
    return "eval '" + cmd.replace("'", "'\"'\"'") + "'"


async def allow(tool, inp, ctx):
    return PermissionResultAllow()


async def main():
    cmd = "%s %s" % (sys.executable, HOOK)
    hooks = {ev: [{"matcher": "*", "hooks": [{"type": "command", "command": cmd, "timeout": 10}]}]
             for ev in ("Stop", "PostToolUse")}
    opts = ClaudeAgentOptions(cli_path=CLI, cwd=str(TMP), model="claude-haiku-5-5", permission_mode="default",
                              can_use_tool=allow, setting_sources=[], settings=json.dumps({"hooks": hooks}),
                              env={"HOOK_LOG": str(LOG), "PULT_OFF": "1", "PULT_SOCK": "/nonexistent",
                                   "CLAUDE_CODE_ENTRYPOINT": "claude-vscode"},
                              stderr=lambda s: None)
    async with ClaudeSDKClient(options=opts) as c:
        await c.query("This is a test of background commands. Your first action must be a call to the Bash tool with "
                      "exactly this command: %s — and the parameter run_in_background: true. After the tool call "
                      "returns, do not wait or check on it: reply with one word, STARTED." % CMD)
        async for m in c.receive_messages():
            if isinstance(m, ResultMessage):
                break
        await asyncio.sleep(2)
        stops = [json.loads(x) for x in LOG.read_text().splitlines()] if LOG.exists() else []
        stop = next((d for d in reversed(stops) if d.get("hook_event_name") == "Stop"), {})
        sid = stop.get("session_id")
        print("1. Stop background_tasks:", json.dumps(stop.get("background_tasks"), ensure_ascii=False), flush=True)
        rows = procs()
        me = os.getpid()
        claude = [p for p in under(rows, me) if CLI in rows[p][1] or rows[p][1].split(" ")[0].endswith("/claude")]
        print("   claude under this probe:", claude, flush=True)
        if claude:
            cp = claude[0]
            for p in under(rows, cp):
                a = rows[p][1]
                short = a if len(a) < 160 else a[:60] + " … " + a[-90:]
                print("2. pid %d ppid %d: %s" % (p, rows[p][0], short), flush=True)
            for t in stop.get("background_tasks") or []:
                c_ = t.get("command") or ""
                hit = [p for p in under(rows, cp) if c_ and quoted(c_) in rows[p][1]]
                print("   task %s: command == ours: %s; found by eval '…': %s" % (t.get("id"), c_ == CMD, hit), flush=True)
            agents = []
            for b in (str(Path.home() / ".local/bin/claude"), CLI):
                try:
                    out = subprocess.run([b, "agents", "--json"], capture_output=True, text=True, timeout=20).stdout
                    agents = json.loads(out or "[]")
                except (OSError, ValueError, subprocess.SubprocessError) as e:
                    print("   agents via %s failed: %s" % (b, e), flush=True)
                    continue
                mine = [a for a in agents if a.get("sessionId") == sid]
                print("3. agents via %s: %d listed; ours: %s" % (b.split("/")[-1] if "/.local/" in b else "extension",
                                                               len(agents), mine), flush=True)
            pp = {d.get("_ppid") for d in stops}
            print("4. the hook's parent pid: %s; claude pid %d" % (sorted(pp), cp), flush=True)
        await c.interrupt()


asyncio.run(main())
