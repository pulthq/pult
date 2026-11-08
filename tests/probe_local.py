"""Probe: Claude Code on a local model behind an Anthropic-compatible address — Ollama's /v1/messages (stage M, step 6).
Nothing in Pult changes; the session is made as a vendor's would be (the address, a key in both places, every role on one
model, the compaction window from the model's context), on the Agent SDK's own Claude Code, as Pult's sessions run it.

What it looks at, in order:
  server  — /api/version, /api/tags (no "-cloud" names), /api/show: the context the model is made with (num_ctx);
  key     — /v1/messages with no key and with a wrong one: whether the server checks keys at all;
  load    — the first one-token request: how long the model takes to load; /api/ps — memory on the card, its context;
  task    — a Claude Code task in a fresh folder: create hello.txt, read it back; with the five core tools ("five") and with
            all of them ("all"): the time to the first answer and to the end, the tools it called, whether the file is
            right, the tokens the server reported; /api/ps again;
  overflow — (with --overflow) a prompt longer than the context: does the server refuse it, or cut its start silently?
  copy    — (with --copy BASE, alone: nothing is loaded on the card; the list of models, 2026-11-08) what Pult's own
            check_local reads of each model — size, parameters, the context it was trained for, its weights (the FROM of
            /api/show's Modelfile) — and which are one (kin); then a copy of BASE with num_ctx 32768 by Pult's own
            make_copy: the time, the same weights as BASE, its context, its place in /api/tags; then it is deleted.
A stand-in proxy refuses everything Claude Code tries past the local address, so nothing leaves the computer and no
subscription is spent. The model's tools are kept to the task's folder: Write, Edit, Read inside it, Bash only for a
few reading commands.
  ~/.local/share/pult/venv/bin/python tests/probe_local.py --model NAME [--url http://127.0.0.1:11434] [--runs five,all]
      [--overflow] [--claude-md FILE] [--env NAME=VALUE ...]
  ~/.local/share/pult/venv/bin/python tests/probe_local.py --copy BASE [--url ...]
"""
import argparse, asyncio, json, os, re, shutil, tempfile, time
from pathlib import Path

import httpx
from claude_agent_sdk import (AssistantMessage, ClaudeAgentOptions, ClaudeSDKClient, PermissionResultAllow,
                              PermissionResultDeny, ResultMessage, ToolUseBlock)

KEY = "pult-local-no-key-needed"   # what Pult would put in both places: never the subscription's token (probe_vendor)
FIVE = ["Bash", "Read", "Edit", "Write", "AskUserQuestion"]
TASK = ("Create a file named hello.txt in the current folder containing exactly one line: local model works. "
        "Then read the file back and reply with its exact contents.")
SAFE_BASH = re.compile(r"\s*(cat|ls|pwd|head|tail|wc|echo)\b[^;&|`$<>]*")
T0 = time.time()


def say(*a):
    print("%6.1f" % (time.time() - T0), *a, flush=True)


async def server(c, url, model):
    out = {}
    r = await c.get(url + "/api/version")
    out["version"] = r.json().get("version")
    tags = (await c.get(url + "/api/tags")).json().get("models") or []
    out["models"] = [m.get("name") for m in tags]
    out["cloud"] = [n for n in out["models"] if n and "cloud" in n]
    show = (await c.post(url + "/api/show", json={"model": model})).json()
    params = show.get("parameters") or ""
    m = re.search(r"num_ctx\s+(\d+)", params)
    out["num_ctx"] = int(m.group(1)) if m else None
    info = show.get("model_info") or {}
    out["trained_ctx"] = next((v for k, v in info.items() if k.endswith(".context_length")), None)
    out["family"] = (show.get("details") or {}).get("family")
    out["size"] = (show.get("details") or {}).get("parameter_size")
    return out


async def one_token(c, url, model, key):
    headers = {"anthropic-version": "2023-06-01", "content-type": "application/json"}
    if key:
        headers.update({"x-api-key": key, "Authorization": "Bearer " + key})
    t = time.time()
    r = await c.post(url + "/v1/messages", headers=headers,
                     json={"model": model, "max_tokens": 1, "messages": [{"role": "user", "content": "ping"}]})
    return r.status_code, round(time.time() - t, 1), r.text[:80]


async def ps(c, url):
    rows = (await c.get(url + "/api/ps")).json().get("models") or []
    return [{"name": m.get("name"), "size_gb": round((m.get("size") or 0) / 2**30, 1),
             "vram_gb": round((m.get("size_vram") or 0) / 2**30, 1), "ctx": m.get("context_length")} for m in rows]


async def refuse(reader, writer):
    try:
        await asyncio.wait_for(reader.readline(), 5)
        writer.write(b"HTTP/1.1 403 Forbidden\r\nContent-Length: 0\r\nConnection: close\r\n\r\n")
        await writer.drain()
    except (asyncio.TimeoutError, ConnectionError):
        pass
    finally:
        writer.close()


def guard(proj):
    root = os.path.realpath(proj)

    async def can_use(tool, inp, ctx):
        if tool in ("Write", "Edit", "Read", "NotebookEdit"):
            p = os.path.realpath(os.path.join(root, str(inp.get("file_path") or inp.get("notebook_path") or "")))
            if p == root or p.startswith(root + os.sep):
                return PermissionResultAllow()
            return PermissionResultDeny(message="Only files inside the current folder.")
        if tool == "Bash":
            if SAFE_BASH.fullmatch(str(inp.get("command") or "")):
                return PermissionResultAllow()
            return PermissionResultDeny(message="Use the Write and Read tools for files.")
        if tool == "AskUserQuestion":
            return PermissionResultDeny(message="Nobody is here to answer: decide yourself.")
        return PermissionResultDeny(message="Not in this probe.")
    return can_use


async def task(name, url, model, ctx, tools, claude_md, proxy_url, extra):
    proj = Path(tempfile.mkdtemp(prefix="pult-local-%s-" % name))
    if claude_md:
        shutil.copy(claude_md, proj / "CLAUDE.md")
    env = {"ANTHROPIC_BASE_URL": url, "ANTHROPIC_AUTH_TOKEN": KEY, "ANTHROPIC_API_KEY": KEY,
           "ANTHROPIC_DEFAULT_OPUS_MODEL": model, "ANTHROPIC_DEFAULT_SONNET_MODEL": model,
           "ANTHROPIC_DEFAULT_FABLE_MODEL": model, "ANTHROPIC_DEFAULT_HAIKU_MODEL": model,
           "CLAUDE_CODE_SUBAGENT_MODEL": model, "CLAUDE_CODE_ENTRYPOINT": "sdk-py",
           "HTTPS_PROXY": proxy_url, "HTTP_PROXY": proxy_url, "https_proxy": proxy_url, "http_proxy": proxy_url,
           "NO_PROXY": "127.0.0.1,localhost", "no_proxy": "127.0.0.1,localhost", "PULT_OFF": "1"}
    if ctx:
        env["CLAUDE_CODE_AUTO_COMPACT_WINDOW"] = str(ctx)
    env.update(extra)                  # what a run tries on top, e.g. MAX_THINKING_TOKENS=0
    errs, calls, first, result = [], [], None, None
    kw = dict(cwd=str(proj), system_prompt={"type": "preset", "preset": "claude_code"},
              setting_sources=["project"] if claude_md else [], permission_mode="default", can_use_tool=guard(proj),
              env=env, model=model, stderr=errs.append, max_turns=12)
    if tools:
        kw["tools"] = tools
    t = time.time()
    try:
        async with ClaudeSDKClient(options=ClaudeAgentOptions(**kw)) as c:
            await c.query(TASK)

            async def read():
                nonlocal first, result
                async for m in c.receive_messages():
                    if isinstance(m, AssistantMessage):
                        first = first or round(time.time() - t, 1)
                        calls.extend(b.name for b in m.content if isinstance(b, ToolUseBlock))
                    elif isinstance(m, ResultMessage):
                        result = m
                        return
            await asyncio.wait_for(read(), 600)
    except Exception as e:
        say(name, "— the session failed:", repr(e)[:300])
    f = proj / "hello.txt"
    content = f.read_text(errors="replace").strip() if f.exists() else None
    key = re.sub(r"[^a-zA-Z0-9]", "-", os.path.realpath(proj))
    shutil.rmtree(Path.home() / ".claude" / "projects" / key, ignore_errors=True)
    shutil.rmtree(proj, ignore_errors=True)
    out = {"tools": len(tools) if tools else "all", "first_s": first, "total_s": round(time.time() - t, 1),
           "calls": calls, "file": content, "file_ok": content == "local model works",
           "result": None if result is None else ("error " if result.is_error else "") + (result.result or "")[:200],
           "usage": None if result is None else {k: (result.usage or {}).get(k) for k in
                                                 ("input_tokens", "output_tokens", "cache_read_input_tokens")},
           "models": None if result is None else
           sorted((result.model_usage or {}).keys())}
    if errs:
        out["stderr"] = " | ".join(e.strip() for e in errs if e.strip())[-400:]
    return out


async def overflow(c, url, model, ctx):
    """A prompt about a third longer than the context: the rule sits at the start, the question at the end."""
    filler = "The quick brown fox jumps over the lazy dog. " * int((ctx or 4096) * 1.35 / 10)
    body = {"model": model, "max_tokens": 20, "system": "The password is PELICAN-42. When asked, answer with the password only.",
            "messages": [{"role": "user", "content": filler + "\n\nWhat is the password?"}]}
    t = time.time()
    r = await c.post(url + "/v1/messages", json=body, headers={"x-api-key": KEY, "anthropic-version": "2023-06-01"})
    out = {"status": r.status_code, "s": round(time.time() - t, 1)}
    try:
        j = r.json()
        out["text"] = "".join(b.get("text", "") for b in j.get("content") or [])[:80]
        out["input_tokens"] = (j.get("usage") or {}).get("input_tokens")
        out["kept_the_start"] = "PELICAN" in out["text"].upper()
    except ValueError:
        out["text"] = r.text[:160]
    return out


async def copy_probe(url, base):
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
    import pult_vendors as V
    out = {}
    async with httpx.AsyncClient(timeout=httpx.Timeout(60, connect=5), trust_env=False) as c:
        for m in (await c.get(url + "/api/tags")).json().get("models") or []:     # the Modelfile's FROM as the server writes it
            show = (await c.post(url + "/api/show", json={"model": m["name"]})).json()
            line = re.search(r"(?m)^FROM\s+(.+)$", show.get("modelfile") or "")
            out.setdefault("from", {})[m["name"]] = line.group(1)[-80:] if line else None
    got = await V.check_local(url)
    out.update(version=got["version"], models=got["models"], kin=V.kin(got["models"]))
    say("models:", json.dumps(out, ensure_ascii=False))
    t = time.time()
    new = await V.make_copy(url, base, V.LOCAL_CTX_COPY, {m["name"] for m in got["models"]})
    out["create_s"] = round(time.time() - t, 2)
    again = await V.check_local(url)
    mine = next((m for m in again["models"] if m["name"] == new), None)
    was = next((m for m in again["models"] if m["name"] == base), None)
    out.update(copy=mine, same_weights=bool(mine and was and mine["w"] and mine["w"] == was["w"]), kin_after=V.kin(again["models"]))
    say("copy:", json.dumps({k: out[k] for k in ("create_s", "copy", "same_weights", "kin_after")}, ensure_ascii=False))
    async with httpx.AsyncClient(timeout=httpx.Timeout(60, connect=5), trust_env=False) as c:
        r = await c.request("DELETE", url + "/api/delete", json={"model": new})
        out["delete"] = r.status_code
        out["after_delete"] = [m.get("name") for m in (await c.get(url + "/api/tags")).json().get("models") or []]
    say("deleted:", out["delete"], out["after_delete"])
    return out


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://127.0.0.1:11434")
    ap.add_argument("--model")
    ap.add_argument("--copy", metavar="BASE", help="the list of models: a copy of BASE with a context, then deleted")
    ap.add_argument("--runs", default="five,all")
    ap.add_argument("--overflow", action="store_true")
    ap.add_argument("--claude-md")
    ap.add_argument("--env", action="append", default=[], help="NAME=VALUE for the Claude Code session")
    a = ap.parse_args()
    url = a.url.rstrip("/")
    if a.copy:
        say("summary:", json.dumps(await copy_probe(url, a.copy), ensure_ascii=False, default=str))
        return
    if not a.model:
        ap.error("--model is needed")
    extra = dict(x.split("=", 1) for x in a.env)
    report = {}
    async with httpx.AsyncClient(timeout=httpx.Timeout(900, connect=5), trust_env=False) as c:
        report["server"] = srv = await server(c, url, a.model)
        say("server:", json.dumps(srv))
        report["key"] = {"none": await one_token(c, url, a.model, None), "wrong": await one_token(c, url, a.model, "wrong-key-0000000000")}
        say("key:", json.dumps(report["key"]))
        report["ps_loaded"] = await ps(c, url)
        say("loaded:", json.dumps(report["ps_loaded"]))
        psrv = await asyncio.start_server(refuse, "127.0.0.1", 0)
        proxy_url = "http://127.0.0.1:%d" % psrv.sockets[0].getsockname()[1]
        for run in [r for r in a.runs.split(",") if r]:
            report[run] = await task(run, url, a.model, srv["num_ctx"], FIVE if run == "five" else None, a.claude_md, proxy_url,
                                     extra)
            say(run + ":", json.dumps(report[run], ensure_ascii=False))
            report["ps_" + run] = await ps(c, url)
            say("loaded:", json.dumps(report["ps_" + run]))
        psrv.close()
        if a.overflow:
            report["overflow"] = await overflow(c, url, a.model, srv["num_ctx"])
            say("overflow:", json.dumps(report["overflow"], ensure_ascii=False))
    say("summary:", json.dumps(report, ensure_ascii=False, default=str))


asyncio.run(main())
