"""Probe: Claude Code with another vendor's model — a profile in the session's environment (stage M, step 2), on the
Agent SDK's own Claude Code, as Pult's sessions run it.

A stand-in Anthropic API on 127.0.0.1 (/v1/messages streamed or not, count_tokens, models) keeps every request: the
path, which credential came — ours, a Claude one (sk-ant-…), another, none; never printed — the model, the betas; it
answers with a short text. A stand-in proxy keeps every host Claude Code tries to reach past it and lets none through,
so nothing leaves the computer and no subscription is spent. Each run is one prompt in a fresh folder, no user settings:
  token   — ANTHROPIC_BASE_URL + ANTHROPIC_AUTH_TOKEN, the models by role (ANTHROPIC_DEFAULT_*_MODEL), model "sonnet";
  key     — the same with ANTHROPIC_API_KEY instead of the token;
  bare    — ANTHROPIC_BASE_URL alone: which credential goes then (a Claude one must never reach another vendor);
  direct  — the token, the model by its own id, no roles;
  quiet   — "token" with CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1: what still tries to reach elsewhere;
  both    — the token and the key at once, both ours (Pult's way: an inherited Anthropic key can't take either place);
  window  — "both" with a compaction window of 128 000 and the SDK's own entrypoint (hidden from VS Code's list);
  deepseek — DeepSeek's own settings for Claude Code: a model with the [1m] suffix and effort "max" — what reaches it.
  ~/.local/share/pult/venv/bin/python tests/probe_vendor.py [run …]
"""
import asyncio, json, os, re, shutil, sys, tempfile, time
from pathlib import Path

from aiohttp import web
from claude_agent_sdk import ClaudeAgentOptions, ClaudeSDKClient, PermissionResultAllow, ResultMessage, SystemMessage

OURS = "probe-vendor-secret-0001"
ROLES = {"ANTHROPIC_DEFAULT_OPUS_MODEL": "probe-opus", "ANTHROPIC_DEFAULT_SONNET_MODEL": "probe-sonnet",
         "ANTHROPIC_DEFAULT_HAIKU_MODEL": "probe-haiku", "ANTHROPIC_DEFAULT_FABLE_MODEL": "probe-fable",
         "CLAUDE_CODE_SUBAGENT_MODEL": "probe-sub"}
T0 = time.time()


def say(*a):
    print("%5.1f" % (time.time() - T0), *a, flush=True)


def credential(headers):
    """Which credential a request carried — never the credential itself."""
    for kind, raw in (("x-api-key", headers.get("x-api-key")), ("bearer", headers.get("authorization"))):
        if not raw:
            continue
        v = raw[7:] if kind == "bearer" and raw.lower().startswith("bearer ") else raw
        who = "ours" if v == OURS else "CLAUDE'S (sk-ant-…)" if v.startswith("sk-ant-") else "another (%d chars)" % len(v)
        return "%s: %s" % (kind, who)
    return "none"


class Api:
    def __init__(self):
        self.seen = []

    async def any(self, req):
        body = {}
        if req.method == "POST":
            try:
                body = await req.json()
            except ValueError:
                body = {}
        row = {"path": req.path, "cred": credential(req.headers), "model": body.get("model"),
               "stream": bool(body.get("stream")), "beta": req.headers.get("anthropic-beta", ""),
               "tools": len(body.get("tools") or []), "max": body.get("max_tokens"),
               "think": json.dumps({k: body[k] for k in ("thinking", "output_config") if k in body})}
        self.seen.append(row)
        if req.path.endswith("/messages/count_tokens"):
            return web.json_response({"input_tokens": 42})
        if req.path.endswith("/models"):
            return web.json_response({"data": [{"id": v, "type": "model", "display_name": v} for v in ROLES.values()],
                                      "has_more": False})
        if not req.path.endswith("/messages"):
            return web.json_response({"type": "error", "error": {"type": "not_found_error", "message": "probe"}}, status=404)
        model = body.get("model") or "probe"
        if not body.get("stream"):
            return web.json_response({"id": "msg_probe", "type": "message", "role": "assistant", "model": model,
                                      "content": [{"type": "text", "text": "OK"}], "stop_reason": "end_turn",
                                      "stop_sequence": None, "usage": {"input_tokens": 10, "output_tokens": 1}})
        resp = web.StreamResponse(headers={"Content-Type": "text/event-stream", "Cache-Control": "no-cache"})
        await resp.prepare(req)
        for ev, data in (
                ("message_start", {"type": "message_start", "message": {
                    "id": "msg_probe", "type": "message", "role": "assistant", "model": model, "content": [],
                    "stop_reason": None, "stop_sequence": None, "usage": {"input_tokens": 10, "output_tokens": 1}}}),
                ("content_block_start", {"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}}),
                ("content_block_delta", {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "OK"}}),
                ("content_block_stop", {"type": "content_block_stop", "index": 0}),
                ("message_delta", {"type": "message_delta", "delta": {"stop_reason": "end_turn", "stop_sequence": None},
                                   "usage": {"output_tokens": 1}}),
                ("message_stop", {"type": "message_stop"})):
            await resp.write(("event: %s\ndata: %s\n\n" % (ev, json.dumps(data))).encode())
        await resp.write_eof()
        return resp


class Proxy:
    """Keeps the host of every CONNECT or plain request and refuses it."""
    def __init__(self):
        self.hosts = []

    async def conn(self, reader, writer):
        try:
            line = (await asyncio.wait_for(reader.readline(), 5)).decode(errors="replace")
            parts = line.split()
            if len(parts) >= 2:
                target = parts[1]
                host = target.split("//", 1)[-1].split("/", 1)[0] if "://" in target else target
                self.hosts.append(host)
            writer.write(b"HTTP/1.1 403 Forbidden\r\nContent-Length: 0\r\nConnection: close\r\n\r\n")
            await writer.drain()
        except (asyncio.TimeoutError, ConnectionError):
            pass
        finally:
            writer.close()


async def allow(tool, inp, ctx):
    return PermissionResultAllow()


def forget(proj):
    """The run's own transcripts out of Claude Code's history — its temporary folder's, nobody else's (as
    pult_tabcheck.forget does for the tab check)."""
    key = re.sub(r"[^a-zA-Z0-9]", "-", os.path.realpath(proj))
    shutil.rmtree(Path.home() / ".claude" / "projects" / key, ignore_errors=True)
    shutil.rmtree(proj, ignore_errors=True)


async def one(name, env, model, api, proxy, api_url, proxy_url):
    proj = Path(tempfile.mkdtemp(prefix="pult-vendor-%s-" % name))
    api.seen.clear()
    proxy.hosts.clear()
    errs = []
    env = dict(env, HTTPS_PROXY=proxy_url, HTTP_PROXY=proxy_url, https_proxy=proxy_url, http_proxy=proxy_url,
               NO_PROXY="127.0.0.1,localhost", no_proxy="127.0.0.1,localhost", PULT_OFF="1")
    opts = ClaudeAgentOptions(cwd=str(proj), setting_sources=[], permission_mode="default", can_use_tool=allow,
                              env=env, model=model, stderr=errs.append)
    init, result = {}, None
    try:
        async with ClaudeSDKClient(options=opts) as c:
            await c.query("Reply with the single word OK.")

            async def read():
                nonlocal init, result
                async for m in c.receive_messages():
                    if isinstance(m, SystemMessage) and m.subtype == "init":
                        init = m.data
                    elif isinstance(m, ResultMessage):
                        result = m
                        return
            await asyncio.wait_for(read(), 90)
            await asyncio.sleep(3)                       # background requests that follow a turn (a title, a summary)
    except Exception as e:
        say(name, "— the session failed:", repr(e)[:300])
    finally:
        forget(proj)
    say("== %s: model asked %r, init model %r, apiKeySource %r" % (name, model, init.get("model"), init.get("apiKeySource")))
    if result is not None:
        say("   result:", "error" if result.is_error else "ok", repr((result.result or "")[:80]),
            "· models used:", sorted((result.model_usage or {}).keys()))
    for r in api.seen:
        say("   %-26s %-28s model=%-14s stream=%-5s tools=%-3s max=%s %s beta=%s" % (
            r["path"], r["cred"], r["model"], r["stream"], r["tools"], r["max"], r["think"], r["beta"][:60]))
    if not api.seen:
        say("   nothing reached the stand-in API")
    say("   past the proxy (refused):", sorted(set(proxy.hosts)) or "nothing")
    leak = [r for r in api.seen if "CLAUDE'S" in r["cred"]]
    if leak:
        say("   !!! a Claude credential reached the other vendor's address in %d requests" % len(leak))
    if errs:
        say("   stderr:", " | ".join(e.strip() for e in errs if e.strip())[-400:])
    return {"init": init, "seen": list(api.seen), "hosts": sorted(set(proxy.hosts)), "leak": bool(leak)}


async def main():
    api, proxy = Api(), Proxy()
    app = web.Application()
    app.router.add_route("*", "/{tail:.*}", api.any)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    api_port = site._server.sockets[0].getsockname()[1]
    psrv = await asyncio.start_server(proxy.conn, "127.0.0.1", 0)
    proxy_port = psrv.sockets[0].getsockname()[1]
    api_url, proxy_url = "http://127.0.0.1:%d" % api_port, "http://127.0.0.1:%d" % proxy_port
    say("stand-in API", api_url, "· stand-in proxy", proxy_url)
    runs = {
        "token": (dict(ROLES, ANTHROPIC_BASE_URL=api_url, ANTHROPIC_AUTH_TOKEN=OURS), "sonnet"),
        "key": (dict(ROLES, ANTHROPIC_BASE_URL=api_url, ANTHROPIC_API_KEY=OURS), "sonnet"),
        "bare": ({"ANTHROPIC_BASE_URL": api_url}, "sonnet"),
        "direct": ({"ANTHROPIC_BASE_URL": api_url, "ANTHROPIC_AUTH_TOKEN": OURS}, "probe-direct-id"),
        "both": (dict(ROLES, ANTHROPIC_BASE_URL=api_url, ANTHROPIC_AUTH_TOKEN=OURS, ANTHROPIC_API_KEY=OURS), "sonnet"),
        # DeepSeek's own settings for Claude Code (api-docs.deepseek.com, 2026-10-30): the [1m] suffix, effort max
        "deepseek": ({"ANTHROPIC_BASE_URL": api_url, "ANTHROPIC_AUTH_TOKEN": OURS, "ANTHROPIC_API_KEY": OURS,
                      "ANTHROPIC_DEFAULT_OPUS_MODEL": "deepseek-flash[1m]", "ANTHROPIC_DEFAULT_SONNET_MODEL": "deepseek-flash[1m]",
                      "ANTHROPIC_DEFAULT_HAIKU_MODEL": "deepseek-flash", "CLAUDE_CODE_SUBAGENT_MODEL": "deepseek-flash",
                      "CLAUDE_CODE_EFFORT_LEVEL": "max", "CLAUDE_CODE_AUTO_COMPACT_WINDOW": "786432"}, "deepseek-flash[1m]"),
        "window": (dict(ROLES, ANTHROPIC_BASE_URL=api_url, ANTHROPIC_AUTH_TOKEN=OURS, ANTHROPIC_API_KEY=OURS,
                        CLAUDE_CODE_AUTO_COMPACT_WINDOW="128000", CLAUDE_CODE_ENTRYPOINT="sdk-py"), "probe-opus"),
        "quiet": (dict(ROLES, ANTHROPIC_BASE_URL=api_url, ANTHROPIC_AUTH_TOKEN=OURS,
                       CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC="1"), "sonnet"),
    }
    want = sys.argv[1:] or list(runs)
    out = {}
    for name in want:
        env, model = runs[name]
        out[name] = await one(name, env, model, api, proxy, api_url, proxy_url)
    psrv.close()
    await runner.cleanup()
    say("summary:", json.dumps({k: {"leak": v["leak"], "source": v["init"].get("apiKeySource"),
                                    "models": sorted({r["model"] for r in v["seen"] if r["model"]}),
                                    "elsewhere": v["hosts"]} for k, v in out.items()}))


asyncio.run(main())
