"""Isolation probe (stage M, step 7.1): a vendor's session in a Claude Code home of its own (CLAUDE_CONFIG_DIR), with
an identity line appended to the system prompt and, optionally, CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1.
A stand-in Anthropic API on 127.0.0.1 keeps every request; a stand-in proxy refuses and keeps every host tried.
Looks at: the owner's global CLAUDE.md and auto memory in the request or not; the appended line there or not; where the
transcript went (the own home or ~/.claude); which hosts Claude Code tried past the local address; a title request.
The owner's global CLAUDE.md is looked for by a line of its own, read at run time.
  ~/.local/share/pult/venv/bin/python tests/probe_home.py [quiet]"""
import asyncio, json, os, re, shutil, sys, tempfile
from pathlib import Path

from aiohttp import web
from claude_agent_sdk import ClaudeAgentOptions, ClaudeSDKClient, PermissionResultAllow, ResultMessage

QUIET = len(sys.argv) > 1 and sys.argv[1] == "quiet"
SEEN, HOSTS = [], []
IDENT = "You are not Claude. You are the model probe-local-32k, running through Ollama on the owner's own computer."


def text_of(x):
    if isinstance(x, str):
        return x
    return "\n".join(b.get("text", "") for b in x or [] if isinstance(b, dict))


async def api(req):
    body = await req.json() if req.method == "POST" else {}
    if not req.path.endswith("/messages"):
        return web.json_response({"input_tokens": 9} if req.path.endswith("count_tokens") else {})
    SEEN.append({"sys": text_of(body.get("system")), "msgs": json.dumps(body.get("messages"), ensure_ascii=False),
                 "tools": len(body.get("tools") or [])})
    msg = {"id": "msg_p", "type": "message", "role": "assistant", "model": body.get("model") or "m", "content": [],
           "stop_reason": None, "stop_sequence": None, "usage": {"input_tokens": 10, "output_tokens": 1}}
    resp = web.StreamResponse(headers={"Content-Type": "text/event-stream"})
    await resp.prepare(req)
    for ev, data in (("message_start", {"type": "message_start", "message": msg}),
                     ("content_block_start", {"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}}),
                     ("content_block_delta", {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "OK"}}),
                     ("content_block_stop", {"type": "content_block_stop", "index": 0}),
                     ("message_delta", {"type": "message_delta", "delta": {"stop_reason": "end_turn", "stop_sequence": None},
                                        "usage": {"output_tokens": 1}}),
                     ("message_stop", {"type": "message_stop"})):
        await resp.write(("event: %s\ndata: %s\n\n" % (ev, json.dumps(data))).encode())
    await resp.write_eof()
    return resp


async def refuse(reader, writer):
    try:
        line = (await asyncio.wait_for(reader.readline(), 5)).decode(errors="replace").split()
        if len(line) >= 2:
            HOSTS.append(line[1].split("//", 1)[-1].split("/", 1)[0])
        writer.write(b"HTTP/1.1 403 Forbidden\r\nContent-Length: 0\r\nConnection: close\r\n\r\n")
        await writer.drain()
    except (asyncio.TimeoutError, ConnectionError):
        pass
    finally:
        writer.close()


async def allow(tool, inp, ctx):
    return PermissionResultAllow()


async def main():
    app = web.Application()
    app.router.add_route("*", "/{tail:.*}", api)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    url = "http://127.0.0.1:%d" % site._server.sockets[0].getsockname()[1]
    psrv = await asyncio.start_server(refuse, "127.0.0.1", 0)
    proxy = "http://127.0.0.1:%d" % psrv.sockets[0].getsockname()[1]
    home = Path(tempfile.mkdtemp(prefix="pult-home-"))
    (home / "CLAUDE.md").write_text("Answer in Russian. PROBE-OWN-RULES-LINE.\n")      # the rules Pult would write there
    proj = Path(tempfile.mkdtemp(prefix="pult-home-proj-"))
    key = re.sub(r"[^a-zA-Z0-9]", "-", os.path.realpath(proj))
    m = "probe-local-32k"
    env = {"ANTHROPIC_BASE_URL": url, "ANTHROPIC_AUTH_TOKEN": "probe-local-no-key", "ANTHROPIC_API_KEY": "probe-local-no-key",
           "ANTHROPIC_DEFAULT_OPUS_MODEL": m, "ANTHROPIC_DEFAULT_SONNET_MODEL": m, "ANTHROPIC_DEFAULT_FABLE_MODEL": m,
           "ANTHROPIC_DEFAULT_HAIKU_MODEL": m, "CLAUDE_CODE_SUBAGENT_MODEL": m, "CLAUDE_CODE_ENTRYPOINT": "sdk-py",
           "CLAUDE_CONFIG_DIR": str(home),
           "HTTPS_PROXY": proxy, "HTTP_PROXY": proxy, "https_proxy": proxy, "http_proxy": proxy,
           "NO_PROXY": "127.0.0.1,localhost", "no_proxy": "127.0.0.1,localhost", "PULT_OFF": "1"}
    if QUIET:
        env["CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC"] = "1"
    opts = ClaudeAgentOptions(cwd=str(proj), system_prompt={"type": "preset", "preset": "claude_code", "append": IDENT},
                              setting_sources=["user", "project", "local"], permission_mode="default", can_use_tool=allow,
                              env=env, model=m, stderr=lambda s: None, tools=["Bash", "Read", "Edit", "Write", "AskUserQuestion"])
    try:
        async with ClaudeSDKClient(options=opts) as c:
            await c.query("Who are you? Reply in one sentence.")
            async for msg in c.receive_messages():
                if isinstance(msg, ResultMessage):
                    break
            await asyncio.sleep(3)
    finally:
        psrv.close()
        await runner.cleanup()
    own = sorted(str(p.relative_to(home)) for p in home.rglob("*.jsonl"))
    shared = Path.home() / ".claude" / "projects" / key
    main = [s for s in SEEN if s["tools"]]
    allt = "\n".join(s["sys"] + s["msgs"] for s in SEEN)
    print("quiet:", QUIET, "· requests:", len(SEEN), "(with tools: %d)" % len(main))
    md = Path("~/.claude/CLAUDE.md").expanduser()
    mine = next((x.strip() for x in (md.read_text(errors="replace").splitlines() if md.exists() else []) if len(x.strip()) > 40), "")
    print("owner's global CLAUDE.md in a request:", bool(mine) and mine in allt, "" if mine else "(none here to look for)")
    print("auto memory instructions in a request:", "MEMORY.md" in allt)
    print("the home's own CLAUDE.md in a request:", "PROBE-OWN-RULES-LINE" in allt)
    print("identity line in the system prompt:", any(IDENT in s["sys"] for s in main))
    print("'You are a Claude agent' still there:", any("You are a Claude agent" in s["sys"] for s in main))
    print("title-like requests (no tools):", len(SEEN) - len(main))
    print("transcripts in the own home:", own[:3])
    print("anything under ~/.claude/projects for this folder:", shared.exists())
    print("hosts tried past the local address:", sorted(set(HOSTS)) or "none")
    shutil.rmtree(home, ignore_errors=True)
    shutil.rmtree(proj, ignore_errors=True)
    shutil.rmtree(shared, ignore_errors=True)


asyncio.run(main())
