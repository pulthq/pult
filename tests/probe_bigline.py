"""Probe: a picture Claude reads, in the SDK stream — how long its line is, and whether a session Pult runs survives it.

Run (uses a little of the subscription, ~30 s; with no argument, the claude the SDK carries — the one Pult's own
sessions run on):
  ~/.local/share/pult/venv/bin/python tests/probe_bigline.py [path to the claude binary]
A ~470 KB picture of noise (it can't be compressed; the real case was a 471 KB screenshot — Claude Code passes it
as is, while a ~600 KB one it re-encodes smaller) is read with the Read tool twice: with the SDK's default line
limit and with Pult's SDK_LINE_MAX. Expected (2026-10-21): the default one fails with CLIJSONDecodeError (the picture
comes in the line twice, in the tool result and in tool_use_result), Pult's one ends the turn with its result.
User settings are not loaded (setting_sources=[]); PULT_OFF=1, so the real Pult does not see the events.
"""
import asyncio, gc, os, random, struct, subprocess, sys, tempfile, time, warnings, zlib
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent / "src"
TMP = Path(tempfile.mkdtemp(prefix="pult-bigline-"))
os.environ.update(PULT_HOME=str(TMP / "home"), PULT_SOCK=str(TMP / "s.sock"), PULT_ENV=str(TMP / "env"))
sys.path.insert(0, str(SRC))
import pultd  # noqa: E402
import claude_agent_sdk  # noqa: E402
from claude_agent_sdk import (ClaudeAgentOptions, ClaudeSDKClient, PermissionResultAllow,  # noqa: E402
                              ResultMessage, UserMessage)

CLI = sys.argv[1] if len(sys.argv) > 1 else None
RUNS = CLI or str(Path(claude_agent_sdk.__file__).parent / "_bundled" / ("claude.exe" if os.name == "nt" else "claude"))
T0 = time.time()


def say(*a):
    print("%5.1f" % (time.time() - T0), *a, flush=True)


def noise_png(path, side=400):
    """An RGB picture of random pixels: deflate can't shrink it, so its size is about side² × 3 bytes."""
    rnd = random.Random(7)
    raw = b"".join(b"\0" + bytes(rnd.getrandbits(8) for _ in range(side * 3)) for _ in range(side))

    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xffffffff)
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", side, side, 8, 2, 0, 0, 0))
                     + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))


async def allow(tool, inp, ctx):
    return PermissionResultAllow()


async def once(limit):
    kw = dict(cwd=str(TMP), model="claude-haiku-5-5", permission_mode="default", can_use_tool=allow,
              setting_sources=[], env={"PULT_OFF": "1", "PULT_SOCK": "/nonexistent"}, stderr=lambda s: None)
    if CLI:
        kw["cli_path"] = CLI
    if limit:
        kw["max_buffer_size"] = limit
    biggest = 0
    try:
        async with ClaudeSDKClient(options=ClaudeAgentOptions(**kw)) as c:
            await c.query("Read the file pic.png in the current folder with the Read tool (once), then reply with "
                          "one word: SEEN.")
            async for m in c.receive_messages():
                if isinstance(m, UserMessage) and m.tool_use_result:
                    biggest = max(biggest, len(str(m.tool_use_result)))
                if isinstance(m, ResultMessage):
                    return "result: %s (tool_use_result ~%d KB)" % ((m.result or m.subtype).strip(), biggest // 1024)
    except Exception as e:
        # after a reader error the SDK leaves the process's stdout pipe to the garbage collector: collect it now,
        # while the loop runs, so the run doesn't end with "Event loop is closed"
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", ResourceWarning)
            gc.collect()
            await asyncio.sleep(0.1)
            gc.collect()
        return "failed: %r" % e
    return "the stream ended without a result"


async def main():
    say("Claude Code %s, SDK %s" % (subprocess.run([RUNS, "-v"], capture_output=True, text=True).stdout.split()[0],
                                    claude_agent_sdk.__version__))
    noise_png(TMP / "pic.png")
    say("picture: %d KB, base64 ~%d KB" % ((TMP / "pic.png").stat().st_size // 1024,
                                            (TMP / "pic.png").stat().st_size * 4 // 3 // 1024))
    say("SDK default (1 MB):", await once(None))
    say("Pult's SDK_LINE_MAX (%d MB):" % (pultd.SDK_LINE_MAX // 2 ** 20), await once(pultd.SDK_LINE_MAX))


asyncio.run(main())
