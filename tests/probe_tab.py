"""Stage 2 probe without VS Code: the tab wrapper (src/pult_tab.py) between the "extension" and Claude Code.

Run (uses a little of the subscription, ~30 s; with no argument, the binary of the newest VS Code extension):
  ~/.local/share/pult/venv/bin/python tests/probe_tab.py [path to the claude binary]
The Agent SDK stands in for the extension: it launches `wrapper <claude> <args>`, as with
claudeCode.claudeProcessWrapper, and passes --replay-user-messages, as the extension does. A stand-in daemon
listens on its own socket.
1. A utility command (`--version`) — the wrapper hands it straight to the real claude.
2. The "extension's" own prompt — the wrapper introduces itself to the daemon and reports the session id.
3. The daemon writes into the tab — Claude Code echoes the message to its output (that is how the tab shows it),
   starts a turn (system/init — the tab shows "working") and replies (result).
User settings are not loaded (setting_sources=[]); PULT_OFF=1, so the real Pult does not see the events.
"""
import asyncio, json, os, subprocess, sys, tempfile, time
from pathlib import Path
from claude_agent_sdk import (AssistantMessage, ClaudeAgentOptions, ClaudeSDKClient, PermissionResultAllow,
                              ResultMessage, SystemMessage, TextBlock, UserMessage)

SRC = Path(__file__).resolve().parent.parent / "src"
WIN = os.name == "nt"
CLI = sys.argv[1] if len(sys.argv) > 1 else str(max(
    [p for pat in (".vscode/extensions", ".vscode-server/extensions")
     for p in Path.home().glob(pat + "/anthropic.claude-code-*/resources/native-binary/claude" + (".exe" if WIN else ""))],
    key=lambda p: [int(x) for x in p.parts[-4].split("-")[2].split(".")]))
sys.path.insert(0, str(SRC))
import pult_tab  # noqa: E402
import pultd  # noqa: E402

VER = pult_tab.version_of(CLI)
print("Claude Code:", VER, flush=True)
TMP = Path(tempfile.mkdtemp(prefix="pult-tab-"))
PROJ = TMP / "proj"
PROJ.mkdir()
SOCK = str(TMP / "d.sock")
(TMP / "tab.json").write_text(json.dumps({"folders": [str(PROJ)], "versions": [VER]}))
if WIN:                                 # pult-tab.exe as install makes it, with the extension's first argument inside
    import pult_setup  # noqa: E402
    SHIM = pult_setup.make_exe(TMP / "ext-spawn.exe", pult_setup.base_pythonw(), {
        "pult_tab.py": (SRC / "pult_tab.py").read_bytes(),
        "__main__.py": "import sys\nsys.argv[1:1] = [%r]\nimport pult_tab\npult_tab.entry()\n" % CLI})
else:
    SHIM = TMP / "ext-spawn.sh"        # like the extension with a wrapper: <wrapper> <its own claude> <args>
    SHIM.write_text('#!/bin/sh\nexec %s %s %s "$@"\n' % (sys.executable, SRC / "pult_tab.py", CLI))
    SHIM.chmod(0o755)
ENV = {"PULT_TAB_CONF": str(TMP / "tab.json"), "PULT_SOCK": SOCK, "PULT_OFF": "1"}
T0 = time.time()


def say(*a):
    print("%5.1f" % (time.time() - T0), *a, flush=True)


async def allow(tool, inp, ctx):
    return PermissionResultAllow()


async def main():
    out = subprocess.run([str(SHIM), "--version"], capture_output=True, text=True, env=dict(os.environ, **ENV), timeout=30)
    say("1. служебная команда через обёртку:", out.stdout.strip() or out.stderr.strip()[:100])

    tabs = []

    async def daemon(reader, writer):
        hello = json.loads(await reader.readline())
        t = {"hello": hello, "sid": hello.get("sid"), "w": writer}
        tabs.append(t)
        try:
            while line := await reader.readline():
                m = json.loads(line)
                if m.get("op") == "sid":
                    t["sid"] = m["sid"]
        except ConnectionError:
            pass                       # Windows: the wrapper's exit drops the connection instead of closing it
    server = await pultd.start_link(daemon, SOCK)

    opts = ClaudeAgentOptions(cli_path=str(SHIM), cwd=str(PROJ), model="claude-haiku-5-5", permission_mode="default",
                              can_use_tool=allow, setting_sources=[], env=ENV, stderr=lambda s: None,
                              extra_args={"replay-user-messages": None})
    seen = []
    async with ClaudeSDKClient(options=opts) as c:
        async def read():
            async for m in c.receive_messages():
                if isinstance(m, SystemMessage) and m.subtype == "init":
                    seen.append(("init",))
                elif isinstance(m, UserMessage):
                    txt = m.content if isinstance(m.content, str) else " ".join(
                        getattr(b, "text", "") for b in m.content if isinstance(b, TextBlock))
                    seen.append(("user", txt, getattr(m, "uuid", None)))
                elif isinstance(m, AssistantMessage):
                    seen.append(("assistant", " ".join(b.text for b in m.content if isinstance(b, TextBlock))))
                elif isinstance(m, ResultMessage):
                    seen.append(("result", m.result))
        reader = asyncio.create_task(read())
        await c.query("Reply with exactly one word: ONE")
        for _ in range(300):
            if any(x[0] == "result" for x in seen) and tabs and tabs[0]["sid"]:
                break
            await asyncio.sleep(0.1)
        say("2. свой запрос:", [x for x in seen if x[0] in ("user", "result")],
            "· обёртка у демона:", bool(tabs), "· сессия:", tabs[0]["sid"] if tabs else None)
        n = len(seen)
        uid = "11111111-2222-4333-8444-555555555555"
        tabs[0]["w"].write((json.dumps({"op": "send", "text": "Reply with exactly one word: TWO", "uuid": uid}) + "\n").encode())
        await tabs[0]["w"].drain()
        for _ in range(300):
            if any(x[0] == "result" for x in seen[n:]):
                break
            await asyncio.sleep(0.1)
        new = seen[n:]
        say("3. из «Telegram» во вкладку:", new)
        replay = [x for x in new if x[0] == "user" and "TWO" in x[1]]
        say("   повтор сообщения в выходе:", bool(replay), "· uuid наш:", bool(replay and replay[0][2] == uid),
            "· ход начат (init):", ("init",) in new, "· итог:", [x[1] for x in new if x[0] == "result"])
        reader.cancel()
    server.close()
    log = Path(pult_tab.LOG)
    if log.exists():
        say("журнал обёртки:", [l for l in log.read_text(encoding="utf-8").splitlines() if str(PROJ) in l or "во вкладку" in l][-3:])


asyncio.run(main())
