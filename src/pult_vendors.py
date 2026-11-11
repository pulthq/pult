"""Other vendors' models inside Claude Code (stage M, step 2): DeepSeek, GLM, Kimi answer Claude Code's own protocol at
an address of theirs, so a session Pult runs gets their profile in its environment — the address, the owner's key, the
models by role — and everything else (hooks, the chat, cards, whose move) works as it is. Anthropic doesn't support it
and Claude Code's prompts are Claude's: for the cheaper tasks, not the hard ones.

What tests/probe_vendor.py found on Claude Code 2.1.300 (2026-10-30), and what follows here:
  • with a key in ANTHROPIC_AUTH_TOKEN (Bearer) or ANTHROPIC_API_KEY (x-api-key) only that key reaches the address;
    both set — the API key wins; so a session gets the vendor's key in both, and an Anthropic key the daemon might
    inherit can take neither place;
  • with the address alone the Claude subscription's own token went there (Bearer sk-ant-…, the oauth beta) — so no
    environment is ever made without a key (session_env refuses);
  • "sonnet", "opus", "fable", "haiku" become the models the roles name (ANTHROPIC_DEFAULT_*_MODEL); the session's
    title is asked of the haiku role, the subagents of CLAUDE_CODE_SUBAGENT_MODEL; a model's own id works too;
  • CLAUDE_CODE_AUTO_COMPACT_WINDOW sets when the conversation is compacted — a vendor's window may be smaller than
    the one Claude Code assumes; the SDK's own entrypoint (sdk-py) keeps the session off VS Code's list (the owner,
    2026-10-30: continued in a tab it would go to Claude with another vendor's turns in it).
Your own model (stage M, step 6) is one more profile, "local": a server at this computer's own address that answers the
same protocol — Ollama's /v1/messages. What tests/probe_local.py found on Ollama 0.40.14 with gemma4:12b (2026-11-04):
  • no key is checked — Pult puts LOCAL_KEY in both places, so the subscription's token never goes there;
  • with Claude Code's five core tools a task was right both times in 8–10 s; with all 25 — 41 s, sloppy, and once a
    request hung in Ollama for 10 minutes: a local session gets the five (LOCAL_TOOLS);
  • a prompt longer than the model's context is cut silently, to half of it, its first five tokens kept — so a model is
    taken only with its context known (num_ctx in its Modelfile) and big enough, and the compaction window is that;
  • /api/show says what a model can do ("tools") and its num_ctx; an empty /v1/messages answers 400 without loading
    anything — the address speaks the protocol. One model does every role: Ollama keeps one loaded at a time.
Models as a list (2026-11-08, the owner: "a list with ticks, not names through commas"): a tick puts a model into a task's
menu, a star makes it the main one; a cloud vendor's helpers' model ("fast") is named, not the second of the list. The
server's own facts of each model come with its check — its size, its parameters, and its weights (the FROM of /api/show's
Modelfile), so a model made from another with a context set ("gemma4-32k" from gemma4:12b) and its base are known as one,
and a model without a context gets a copy with one on the owner's tap (/api/create: "from" and "parameters" — no second
copy of the weights). tests/probe_local.py --copy on Ollama 0.40.14 (2026-11-08): a copy and its base name one blob in
their FROM; the copy came in 0.15 s with its base's weights, and the models' folder kept its size.
What an "uncensored" model that refused inside Pult showed (a gemma4 12B from Ollama's library, Ollama 0.40.14, Claude
Code 2.1.300; its task's own request replayed, 3 tries a variant, 2026-11-08):
  • a request with a system prompt of its own goes without the model's SYSTEM from its Modelfile, and Claude Code always
    brings one; that model is uncensored by its SYSTEM and a thought its template puts before each answer — its weights
    alone refused 6 times of 6 — so its task's request, replayed, refused 6 of 6: "my rules forbid it". Its SYSTEM after
    the line on who it is: no refusal of 3 — so a session of one's own model gets it there (model_system, identity);
  • the line's "its tools and rules are yours" was what tipped it: without "and rules", or without the line, no refusal of
    3; the line now gives Claude Code's tools, not Claude's rules;
  • Claude Code reads CLAUDE.md in every folder above the project, and from ~ it took the owner's ~/.claude/CLAUDE.md for a
    project's in a session with a home of its own (tests/probe_home.py, the project's folder inside ~ as the owner's are;
    before, in the system's temporary folder, it never showed) — claudeMdExcludes in the session's settings keeps it out
    (md_excludes); the owner's skills stayed out either way.
Standard library and httpx (the key's check). Design: docs/project.html, stage M.
"""
import json
import os
import re
from pathlib import Path

import httpx

# the owner's key for each lives in the settings file (~/.config/pult/env), written by the daemon from the app
KEY_PREFIX = "PULT_VENDOR_KEY_"
KEY_CHARS = r"[A-Za-z0-9_.\-]{16,300}"
MODEL_RE = re.compile(r"[A-Za-z0-9][\w.:/\-\[\]]{0,79}")
MODELS_MAX = 8
CHECK_TIMEOUT = 30                 # s for the key's check
# What the vendors' own pages say (2026-10-30; names change every month or two, so the owner edits the list in
# Settings): the first model is the main one, the second the fast one (titles, subagents), the rest can be picked for a
# task. ctx — the compaction window; env — what the vendor's own guide adds; price — US $ per million tokens, input
# (not cached) and output, its cheapest hours (stage M, step 3 counts with it). "[1m]": Claude Code drops the suffix
# from the name it sends and asks for the 1M-token window (context-1m beta) — probe_vendor.py, run "deepseek"
PRESETS = {
    # api-docs.deepseek.com, Claude Code guide and pricing: flash is V4.1-Flash, v4-pro is V4-Pro; 1M window, 384K
    # output; peak hours (01–04, 06–10 UTC, Mon–Fri) cost twice; a name that doesn't start with "claude" and isn't
    # theirs is refused (400); flash sees pictures, v4-pro doesn't
    "deepseek": {"name": "DeepSeek", "url": "https://api.deepseek.com/anthropic",
                 "models": ["deepseek-flash[1m]", "deepseek-flash", "deepseek-v4-pro[1m]"], "ctx": 786432,
                 "env": {"CLAUDE_CODE_EFFORT_LEVEL": "max"},
                 "price": {"deepseek-flash": [0.15, 0.6], "deepseek-v4-pro": [0.66, 1.98]}},
    # docs.z.ai, the GLM Coding Plan in Claude Code (a subscription): GLM-4.7 for the main roles, long answers allowed
    "glm": {"name": "GLM", "url": "https://api.z.ai/api/anthropic", "models": ["glm-4.7"], "ctx": None,
            "env": {"API_TIMEOUT_MS": "3000000"}, "price": {}},
    # Moonshot: third parties' guides only, not checked — a starting point for the owner's own list
    "kimi": {"name": "Kimi", "url": "https://api.moonshot.ai/anthropic", "models": ["kimi-k3.1-pro"], "ctx": None,
             "env": {}, "price": {"kimi-k3.1-pro": [2.0, 10.0]}},
    # a model of the owner's own through Ollama, at this computer's address (a tunnel to another computer is the
    # owner's); its models and their context come from the server itself (check_local), its name from the daemon's
    # words; a request may wait long on a slow card, not the 10 minutes Claude Code would
    "local": {"name": "Local model", "short": "Local", "url": "http://127.0.0.1:11434", "models": [], "ctx": None,
              "env": {"API_TIMEOUT_MS": "300000"}, "price": {}, "local": True},
}
ORDER = ("deepseek", "glm", "kimi", "local")
LOCAL = "local"
LOCAL_KEY = "pult-local-no-key-needed"
LOCAL_TOOLS = ("Bash", "Read", "Edit", "Write", "AskUserQuestion")
LOCAL_CTX_MIN = 16384      # tokens: the five tools' first request is ~5K (the probe), a big CLAUDE.md and the work need more
LOCAL_CTX_COPY = 32768     # the context of a copy Pult makes: the one gemma4:12b ran with on a 16 GB card (the probe, 2026-11-04)
LOCAL_OUT_MAX = 8192       # tokens an answer may take: it has to fit in the context with the prompt
LOCAL_REACH = 3            # s to answer "is it there" before a task starts
OWN_SYSTEM_MAX = 4000      # chars of one's own model's own instructions passed on: a Modelfile's SYSTEM is a few lines
LOOPBACK = re.compile(r"http://(127\.0\.0\.1|localhost|\[::1\])(:\d{1,5})?")
CLOUD = re.compile(r"(^|[-:])cloud\b", re.I)       # Ollama's cloud models run on ollama.com: not one's own

# Isolation (stage M, step 7.1; Q139): another vendor's session gets a Claude Code home of its own — CLAUDE_CONFIG_DIR, a
# folder of Pult's — so the owner's global CLAUDE.md, settings and memory stay out of its requests, and its transcripts,
# memory and settings stay out of ~/.claude, where Claude and the owner's tabs live; Claude Code's own nonessential
# requests (to api.anthropic.com, and its session title) go off; the system prompt gets a line on who the model is —
# Claude Code's own text says "Claude". All three by tests/probe_home.py on Claude Code 2.1.300 (project.html #stage-m7)
QUIET = {"CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1"}
MAKERS = {"deepseek": "a DeepSeek model", "glm": "a GLM model by Z.ai", "kimi": "a Kimi model by Moonshot AI",
          "local": "a model running through Ollama on the owner's own computer"}
LANGS = {"en": "English", "ru": "Russian"}


def identity(vid, model, own=""):
    """The line appended to Claude Code's system prompt in a session on another vendor's model: who it is — Claude Code's
    tools are its, nothing said of Claude's rules ("its tools and rules are yours" made a model of one's own refuse,
    citing its rules: 2026-11-08). own — one's own model's instructions from its Modelfile, after the line: Ollama
    leaves them out of a request that brings a system prompt (model_system)."""
    model = re.sub(r"\[1m\]$", "", str(model or ""))
    line = ("Who you are: you are not Claude. You are %s, %s, working inside Claude Code through Pult. The text above "
            "was written for Claude: its tools are yours, but when asked who or what you are, say you are %s."
            % (model, MAKERS.get(vid, "another vendor's model"), model))
    own = str(own or "").strip()[:OWN_SYSTEM_MAX]
    return line + ("\n\nYour own instructions, from your Modelfile:\n" + own if own else "")


def md_excludes(home):
    """claudeMdExcludes of a vendor's session: the owner's own CLAUDE.md and rules — in home (their Claude Code home,
    ~/.claude) and in CLAUDE_CONFIG_DIR's when the daemon runs with one. Claude Code reads CLAUDE.md in every folder above
    the project, and from ~ it takes ~/.claude/CLAUDE.md for a project's when the session's home is another
    (tests/probe_home.py, 2.1.300); the patterns are absolute paths, matched with forward slashes."""
    homes = [Path(home).expanduser()]
    if os.environ.get("CLAUDE_CONFIG_DIR"):
        homes.append(Path(os.environ["CLAUDE_CONFIG_DIR"]).expanduser())
    out = []
    for h in homes:
        for x in ((h / "CLAUDE.md").as_posix(), (h / "rules").as_posix() + "/**"):
            if x not in out:
                out.append(x)
    return out


def home_rules(lang):
    """CLAUDE.md of a vendor's own Claude Code home — instead of the owner's global one, which stays out (Q139)."""
    return ("# Rules from Pult\n\n"
            "- Answer the owner in %s unless they write in another language.\n"
            "- The owner often reads you on a phone: keep answers short and plain.\n" % LANGS.get(lang, "English"))


class VendorError(Exception):
    """A key that doesn't pass its check: kind "key" (refused), "balance" (no money left on it), "model" (the key is
    good, the model's name isn't), "net" (no way there), "other" (anything else, with the vendor's words)."""
    def __init__(self, kind, text=""):
        super().__init__(text or kind)
        self.kind, self.text = kind, str(text or "")


def key_name(vid):
    return KEY_PREFIX + vid.upper()


def url_ok(vid, url):
    """An address a profile may take: https; a local model's — this computer's own, plain http."""
    url = str(url or "").rstrip("/")
    return url.startswith("https://") or vid == LOCAL and bool(LOOPBACK.fullmatch(url))


def profiles(own=None, names=None):
    """The presets with the owner's own changes over them (state.db, "vendors.conf": {vid: {"models", "fast", "url"}};
    the local model's also "on", "ctx" — {model: its context}, as the server said — and "found", the server's last
    answer); names — {vid: (name, short)} in the owner's language. "models" are the ticked ones, the main one first;
    "fast" — the helpers' model, one of them; the local model's "fit" — every model of its server that can take a task."""
    out = {}
    for vid in ORDER:
        p = dict(PRESETS[vid], id=vid)
        mine = (own or {}).get(vid) or {}
        models = [m for m in mine.get("models") or [] if isinstance(m, str) and MODEL_RE.fullmatch(m)][:MODELS_MAX]
        if models:
            p["models"] = models
        if isinstance(mine.get("url"), str) and url_ok(vid, mine["url"]):
            p["url"] = mine["url"].rstrip("/")
        if p.get("local"):
            ctx = mine.get("ctx") if isinstance(mine.get("ctx"), dict) else {}
            p["ctxs"] = {m: int(n) for m, n in ctx.items() if isinstance(n, int) and n > 0}
            p["models"] = [m for m in p["models"] if p["ctxs"].get(m, 0) >= LOCAL_CTX_MIN]
            found = ((mine.get("found") or {}).get("models") or []) if isinstance(mine.get("found"), dict) else []
            p["fit"] = [m["name"] for m in found if isinstance(m, dict) and fits(m)] or list(p["models"])
            p["on"] = bool(mine.get("on")) and bool(p["models"])
            p["tools"] = list(LOCAL_TOOLS)
            p["fast"] = p["models"][0] if p["models"] else None        # one model for every role
        else:
            fast = mine.get("fast")
            p["fast"] = fast if fast in p["models"] else p["models"][1] if len(p["models"]) > 1 else p["models"][0]
        if vid in (names or {}):
            p["name"], p["short"] = names[vid]
        out[vid] = p
    return out


def fits(m):
    """A model of one's own server can take a task: it uses tools, and its context is set and big enough."""
    return bool(m.get("tools")) and (m.get("ctx") or 0) >= LOCAL_CTX_MIN


def clean_models(names):
    """The owner's list of models from Settings — a list (the ticks), or a line with commas, spaces or lines between
    them (an app before the ticks) — → a list, or ValueError."""
    if isinstance(names, (list, tuple)):
        names = [str(x).strip() for x in names if str(x).strip()]
    else:
        names = [x for x in re.split(r"[\s,;]+", str(names or "")) if x]
    if not names or len(names) > MODELS_MAX or not all(MODEL_RE.fullmatch(x) for x in names):
        raise ValueError(names)
    return list(dict.fromkeys(names))


def kin(models):
    """Which of one's own models are one: a model made from another with a context set ("gemma4-32k" FROM gemma4:12b)
    has its weights — the same "w" — and only one of them fits. → {name: {"from": its base} or {"copy": its copy}}."""
    out = {}
    for m in models:
        if not fits(m) or not m.get("w"):
            continue
        base = next((x for x in models if x is not m and x.get("w") == m["w"] and not fits(x)), None)
        if base:
            out[m["name"]] = {"from": base["name"]}
            out.setdefault(base["name"], {"copy": m["name"]})
    return out


def copy_name(name, ctx, taken):
    """The name of a copy with a context: "qwen3.5:4b" → "qwen3.5-4b-32k"; another one's name is never taken."""
    base = re.sub(r"[:/]", "-", name.removesuffix(":latest"))[:70] + "-%dk" % (int(ctx) // 1024)
    out, i = base, 2
    while out in taken or out + ":latest" in taken:
        out, i = "%s-%d" % (base, i), i + 1
    return out


def session_env(p, key, model=None):
    """The environment of a session that runs on vendor profile p with this key: never without a key — with the
    address alone Claude Code sends the Claude subscription's token there (probe_vendor.py)."""
    if not (isinstance(key, str) and key.strip()):
        raise ValueError("no key for " + p["name"])
    main = model or p["models"][0]
    fast = p.get("fast") or (p["models"][1] if len(p["models"]) > 1 else p["models"][0])
    ctx = p.get("ctx")
    if p.get("local"):                 # one model for every role, its own context — never one Pult doesn't know
        fast, ctx = main, (p.get("ctxs") or {}).get(main)
        if not ctx or ctx < LOCAL_CTX_MIN:
            raise ValueError("%s: the context of %s isn't known, or is too small" % (p["name"], main))
    env = {k: str(v) for k, v in (p.get("env") or {}).items()}       # the vendor's own advice first: never over these
    env.update({"ANTHROPIC_BASE_URL": p["url"], "ANTHROPIC_AUTH_TOKEN": key, "ANTHROPIC_API_KEY": key,
                "ANTHROPIC_DEFAULT_OPUS_MODEL": main, "ANTHROPIC_DEFAULT_SONNET_MODEL": main,
                "ANTHROPIC_DEFAULT_FABLE_MODEL": main, "ANTHROPIC_DEFAULT_HAIKU_MODEL": fast,
                "CLAUDE_CODE_SUBAGENT_MODEL": fast, "CLAUDE_CODE_ENTRYPOINT": "sdk-py"})
    if ctx:
        env["CLAUDE_CODE_AUTO_COMPACT_WINDOW"] = str(int(ctx))
    if p.get("local"):
        env["CLAUDE_CODE_MAX_OUTPUT_TOKENS"] = str(local_out(ctx))
        # this computer's own address never through a proxy (Pult's own goes to another country)
        near = [os.environ.get("NO_PROXY") or os.environ.get("no_proxy") or "", "127.0.0.1,localhost,::1"]
        env["NO_PROXY"] = env["no_proxy"] = ",".join(x for x in near if x)
    return env


def local_out(ctx):
    """Tokens an answer of one's own model may take: it has to fit in its context with the prompt."""
    return min(LOCAL_OUT_MAX, int(ctx) // 4)


async def check_local(url, transport=None):
    """What a local server has (Settings → Local model → Check): Ollama's version, and each of its models — whether it
    can use tools, its context (num_ctx in its Modelfile; None — the server's default, which no answer says), and for
    the owner's list: its size on disk, its parameters ("9.7B"), the context it was trained for, and its weights (w —
    the first 12 of the FROM blob's sha256: a copy made from it has the same). Never through a proxy, never loads a
    model: /api/show and an empty /v1/messages (400 — it speaks Claude Code's protocol).
    → {"version", "models": [{"name", "ctx", "tools", "size", "params", "max", "w"}]}; VendorError: "url", "net",
    "proto", "model"."""
    url = str(url or "").rstrip("/")
    if not url_ok(LOCAL, url):
        raise VendorError("url", url)
    kw = dict(transport=transport) if transport is not None else {}
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(15, connect=LOCAL_REACH), trust_env=False, **kw) as c:
            version = (await c.get(url + "/api/version")).json().get("version") or "?"
            tags = (await c.get(url + "/api/tags")).json().get("models") or []
            probe = await c.post(url + "/v1/messages", json={})
            if probe.status_code == 404:
                raise VendorError("proto", version)
            models = []
            for m in tags:
                name = m.get("name") or m.get("model")
                if not isinstance(name, str) or CLOUD.search(name) or not MODEL_RE.fullmatch(name) or name.startswith(WAS_NS):
                    continue
                show = (await c.post(url + "/api/show", json={"model": name})).json()
                n = re.search(r"(?m)^num_ctx\s+(\d+)", show.get("parameters") or "")
                w = re.search(r"(?m)^FROM\s+\S*sha256[-:]([0-9a-f]{12})", show.get("modelfile") or "")
                info = show.get("model_info") if isinstance(show.get("model_info"), dict) else {}
                top = next((v for k, v in info.items() if k.endswith(".context_length") and isinstance(v, int)), None)
                det = m.get("details") if isinstance(m.get("details"), dict) else {}
                params = det.get("parameter_size")
                models.append({"name": name.removesuffix(":latest"), "ctx": int(n.group(1)) if n else None,
                               "tools": "tools" in (show.get("capabilities") or []),
                               "size": m["size"] if isinstance(m.get("size"), int) else None,
                               "params": params if isinstance(params, str) and len(params) < 12 else None,
                               "max": top, "w": w.group(1) if w else None})
    except httpx.TransportError as e:
        raise VendorError("net", type(e).__name__) from None
    except ValueError as e:                  # not JSON: something else answers there
        raise VendorError("proto", str(e)[:80]) from None
    if not any(m["tools"] for m in models):
        raise VendorError("model", ", ".join(m["name"] for m in models))
    return {"version": version, "models": models[:MODELS_MAX * 2]}


async def make_copy(url, name, ctx, taken, transport=None):
    """A copy of a model of one's own server with its context set (Settings → Local model → "Make a copy with 32K", the
    owner's tap): /api/create from the model with the one parameter — the server keeps one copy of the weights, the
    new model is a few lines on top. Never one more than the model was trained for, never over another's name.
    → the copy's name; VendorError: "url", "net", "other"."""
    url = str(url or "").rstrip("/")
    if not url_ok(LOCAL, url):
        raise VendorError("url", url)
    new = copy_name(name, ctx, taken)
    kw = dict(transport=transport) if transport is not None else {}
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(120, connect=LOCAL_REACH), trust_env=False, **kw) as c:
            r = await c.post(url + "/api/create", json={"model": new, "from": name, "parameters": {"num_ctx": int(ctx)},
                                                        "stream": False})
    except httpx.TransportError as e:
        raise VendorError("net", type(e).__name__) from None
    try:
        got = r.json()
    except ValueError:
        got = {}
    if r.status_code != 200 or got.get("status") != "success":
        raise VendorError("other", str(got.get("error") or got.get("status") or "HTTP %d" % r.status_code)[:200])
    return new


async def model_system(url, model, transport=None):
    """One's own model's own instructions — the SYSTEM of its Modelfile (/api/show) — or "": none, or no answer. A request
    with a system prompt of its own goes without them, and Claude Code always brings one, so Pult passes them on after the
    line on who the model is (identity). Never through a proxy, never loads the model."""
    kw = dict(transport=transport) if transport is not None else {}
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(5, connect=LOCAL_REACH), trust_env=False, **kw) as c:
            r = await c.post(str(url).rstrip("/") + "/api/show", json={"model": model})
            text = r.json().get("system") if r.status_code == 200 else None
    except (httpx.HTTPError, ValueError, AttributeError):
        return ""
    return text.strip() if isinstance(text, str) else ""


async def reach(url, transport=None):
    """Whether a local server answers now — before a task starts on it: the computer with the model may be off."""
    kw = dict(transport=transport) if transport is not None else {}
    try:
        async with httpx.AsyncClient(timeout=LOCAL_REACH, trust_env=False, **kw) as c:
            return (await c.get(str(url).rstrip("/") + "/api/version")).status_code == 200
    except httpx.HTTPError:
        return False


async def check_key(p, key, proxy=None, transport=None):
    """Whether the key works: the smallest request there is — one token from the fast model (a fraction of a cent).
    Through the proxy first when one is set, then directly, like Telegram. → the model that answered; VendorError."""
    if not re.fullmatch(KEY_CHARS, key or ""):
        raise VendorError("key")
    fast = p.get("fast") or (p["models"][1] if len(p["models"]) > 1 else p["models"][0])
    model = re.sub(r"\[1m\]$", "", fast)                                                  # as Claude Code sends it
    body = {"model": model, "max_tokens": 1, "messages": [{"role": "user", "content": "ping"}]}
    headers = {"x-api-key": key, "Authorization": "Bearer " + key, "anthropic-version": "2023-06-01",
               "content-type": "application/json"}
    routes = [dict(transport=transport)] if transport is not None else \
        ([dict(proxy=proxy)] if proxy else []) + [dict()]
    last = None
    for r in routes:
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(CHECK_TIMEOUT, connect=10), **r) as c:
                resp = await c.post(p["url"] + "/v1/messages", json=body, headers=headers)
        except httpx.TransportError as e:
            last = e
            continue
        if resp.status_code == 200:
            try:
                return resp.json().get("model") or model
            except ValueError:
                return model
        try:
            err = resp.json().get("error") or {}
            words = err.get("message") if isinstance(err, dict) else str(err)
        except ValueError:
            words = resp.text[:200]
        words = str(words or "HTTP %d" % resp.status_code)[:200]
        if resp.status_code in (401, 403):
            raise VendorError("key", words)
        if resp.status_code == 402 or re.search(r"balance|insufficient|quota|payment", words, re.I):
            raise VendorError("balance", words)
        if resp.status_code in (400, 404) and re.search(r"model", words, re.I):
            raise VendorError("model", words)
        raise VendorError("other", words)
    raise VendorError("net", type(last).__name__ if last else "")


def cost(prices, by):
    """What a vendor's task has cost so far, by its list price (review 2026-11-11, block 6): prices — the profile's
    {model: [$ per million tokens in, out]}, by — the session's tokens by model (pult_web.Stats). → {"usd", "in", "out",
    "models"} over the models that have a price, or None — none of them has (a subscription, one's own model, a model
    Pult has no price for). An estimate from above: a cache read is counted as plain input, and a vendor's rush-hour
    price isn't known here. A model's name goes without its "[1m]"."""
    usd, tin, tout, models = 0.0, 0, 0, []
    for model, n in (by or {}).items():
        name = re.sub(r"\[[^\]]*\]$", "", str(model))
        p = (prices or {}).get(name)
        if not p or not (n.get("in") or n.get("out")):
            continue
        usd += (n.get("in", 0) * p[0] + n.get("out", 0) * p[1]) / 1e6
        tin, tout = tin + n.get("in", 0), tout + n.get("out", 0)
        if name not in models:
            models.append(name)
    return {"usd": round(usd, 4), "in": tin, "out": tout, "models": models} if models else None


def vendor_of_model(model):
    """A reply's model → whose: None for Claude's own (and Claude Code's synthetic lines), else a word for the other."""
    m = (model or "").lower()
    if not m or "claude" in m or m.startswith("<"):
        return None
    return next((vid for vid in ORDER if vid in m or (vid == "kimi" and "moonshot" in m)), "other")


# The local model's panel (stage M, step 6.4; the owner, 2026-11-08: "how much room is left on the server, how much each
# model takes"). Ollama says which models it has, their sizes and which one is in memory (/api/tags, /api/ps) — not its
# disk, not its card: Ollama 0.40.14 has no such answer (server/routes.go: /api/status is the cloud's only). Those come
# from a reader beside it, at INFO_PORT of the same address (through the same tunnel), which only answers what it sees —
# never a command Pult sends there.
INFO_PORT = 11436
INFO_TIMEOUT = 4                  # s: a card that doesn't answer leaves the panel without its facts, not without models
RESERVE = 60 * 1000 ** 3          # bytes that stay free after a download (Q168: the owner's own rule — below 60 GB, none)
PULL_STEP = 5                     # s between two words of a download's progress to the app (Home re-reads with each)
REGISTRY = "https://registry.ollama.ai/v2/"
MANIFEST = "application/vnd.docker.distribution.manifest.v2+json"


def info_url(url):
    """The facts' address beside a local server's: its own host, INFO_PORT."""
    m = LOOPBACK.fullmatch(str(url or "").rstrip("/"))
    return "http://%s:%d" % (m.group(1), INFO_PORT) if m else None


def _int(x):
    return x if isinstance(x, int) and not isinstance(x, bool) and x >= 0 else None


def clean_info(d):
    """The reader's answer, taken only as far as it is what it should be: {"name", "disk": {"label", "total", "free"},
    "gpu": {"name", "total", "used"}} — bytes; anything else is dropped."""
    if not isinstance(d, dict):
        return None
    out = {"name": d["name"][:40] if isinstance(d.get("name"), str) and d["name"].strip() else None}
    disk = d.get("disk") if isinstance(d.get("disk"), dict) else {}
    if _int(disk.get("total")) and _int(disk.get("free")) is not None and disk["free"] <= disk["total"]:
        out["disk"] = {"label": str(disk.get("label") or "")[:12], "total": disk["total"], "free": disk["free"]}
    gpus = d.get("gpu") if isinstance(d.get("gpu"), list) else []
    g = next((x for x in gpus if isinstance(x, dict) and _int(x.get("total")) and _int(x.get("used")) is not None), None)
    if g:
        out["gpu"] = {"name": str(g.get("name") or "")[:60], "total": g["total"], "used": min(g["used"], g["total"])}
    return out


async def local_now(url, transport=None):
    """What the local server holds right now: its models (/api/tags — names, sizes on disk, digests), the ones in memory
    and until when (/api/ps), and the reader's facts beside it (info_url: the disk, the card) — None when nothing
    answers there. Never loads a model, never through a proxy. → {"version", "tags": [{"name", "size", "digest"}],
    "ps": [{"name", "until", "vram"}], "info"}; VendorError "url", "net", "proto"."""
    url = str(url or "").rstrip("/")
    if not url_ok(LOCAL, url):
        raise VendorError("url", url)
    kw = dict(transport=transport) if transport is not None else {}
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(10, connect=LOCAL_REACH), trust_env=False, **kw) as c:
            version = (await c.get(url + "/api/version")).json().get("version") or "?"
            tags, ps = [], []
            for m in (await c.get(url + "/api/tags")).json().get("models") or []:
                name = m.get("name") or m.get("model")
                if isinstance(name, str) and MODEL_RE.fullmatch(name) and not CLOUD.search(name) and not name.startswith(WAS_NS):
                    tags.append({"name": name.removesuffix(":latest"), "size": _int(m.get("size")),
                                 "digest": str(m.get("digest") or "")[:12]})
            for m in (await c.get(url + "/api/ps")).json().get("models") or []:
                name = m.get("name") or m.get("model")
                if isinstance(name, str):
                    ps.append({"name": name.removesuffix(":latest"), "until": str(m.get("expires_at") or "")[:40],
                               "vram": _int(m.get("size_vram"))})
            info = None
            try:
                r = await c.get(info_url(url) + "/", timeout=INFO_TIMEOUT)
                info = clean_info(r.json()) if r.status_code == 200 else None
            except (httpx.HTTPError, ValueError):
                info = None
    except httpx.TransportError as e:
        raise VendorError("net", type(e).__name__) from None
    except ValueError as e:
        raise VendorError("proto", str(e)[:80]) from None
    return {"version": version, "tags": tags, "ps": ps, "info": info}


def families(models):
    """One's own models by their weights: a copy with a context and its base share them (the same "w"), so the disk
    holds them once. → [{"size": the weights' bytes, once; "head": the base (or the only one); "rest": its copies}],
    the biggest first; a model whose weights aren't known is a family of its own."""
    groups = {}
    for m in models:
        groups.setdefault(m.get("w") or "name:" + m["name"], []).append(m)
    out = []
    for ms in groups.values():
        head = next((m for m in ms if not fits(m)), ms[0])
        out.append({"size": max((m.get("size") or 0) for m in ms), "head": head["name"],
                    "rest": [m["name"] for m in ms if m is not head]})
    return sorted(out, key=lambda f: -f["size"])


def frees(models, name):
    """Bytes a model's removal gives back: its weights — unless another model of the server has the same ones."""
    m = next((x for x in models if x["name"] == name), None)
    if not m:
        return 0
    shared = m.get("w") and any(x is not m and x.get("w") == m["w"] for x in models)
    return 0 if shared else (m.get("size") or 0)


def reserve(total):
    """Bytes a download leaves free on the server's disk: RESERVE (Q168), a tenth of a smaller disk."""
    return min(RESERVE, int(total) // 10) if total else RESERVE


def vram_need(size, ctx=LOCAL_CTX_COPY):
    """How much of a card a model takes with a 32K context — its weights and the context's cache, a rough count:
    gemma4:12b, 8.0 GB on disk, took 9.7 GB of the card with 32K (nvidia-smi, the probe of 2026-11-04) — a fifth more."""
    return int(size * 1.2) if size else None


def pull_name(name):
    """A model's name on ollama.com as the owner types it ("qwen3.5:14b", "user/model") → (namespace, model, tag), or
    ValueError: cloud models, other registries (hf.co/…) and odd names aren't pulled from here."""
    name = str(name or "").strip()
    other_site = "/" in name and "." in name.split("/")[0]            # hf.co/…, registry.example.com/…
    if not MODEL_RE.fullmatch(name) or CLOUD.search(name) or name.count("/") > 1 or other_site:
        raise ValueError(name)
    ns, _, rest = name.rpartition("/")
    model, _, tag = rest.partition(":")
    return ns or "library", model, tag or "latest"


async def pull_size(name, proxy=None, transport=None):
    """How big a model on ollama.com is before the server takes it: the sum of its manifest's layers. → bytes; None —
    no such model; VendorError "net" — no answer."""
    ns, model, tag = pull_name(name)
    kw = dict(transport=transport) if transport is not None else dict(proxy=proxy) if proxy else {}
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(15, connect=8), **kw) as c:
            r = await c.get(REGISTRY + "%s/%s/manifests/%s" % (ns, model, tag), headers={"Accept": MANIFEST})
    except httpx.TransportError as e:
        raise VendorError("net", type(e).__name__) from None
    if r.status_code == 404:
        return None
    try:
        layers = r.json().get("layers") or []
        return sum(int(x.get("size") or 0) for x in layers) or None
    except (ValueError, TypeError, AttributeError):
        raise VendorError("other", "HTTP %d" % r.status_code) from None


async def pull(url, name, step, transport=None):
    """The server downloads a model from ollama.com itself (/api/pull, streamed): step(done, total, status) — bytes so
    far over all its layers — as it goes. Closing this request stops the download; the server keeps what came and goes
    on from there the next time. → None when the model is there; VendorError "net", "other"."""
    url = str(url or "").rstrip("/")
    if not url_ok(LOCAL, url):
        raise VendorError("url", url)
    kw = dict(transport=transport) if transport is not None else {}
    got = {}
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(None, connect=LOCAL_REACH), trust_env=False, **kw) as c:
            async with c.stream("POST", url + "/api/pull", json={"model": name, "stream": True}) as r:
                async for line in r.aiter_lines():
                    try:
                        d = json.loads(line)
                    except ValueError:
                        continue
                    if d.get("error"):
                        raise VendorError("other", str(d["error"])[:200])
                    if d.get("digest") and _int(d.get("total")):
                        got[d["digest"]] = (_int(d.get("completed")) or 0, d["total"])
                    step(sum(a for a, _ in got.values()), sum(b for _, b in got.values()), str(d.get("status") or "")[:60])
                    if d.get("status") == "success":
                        return None
    except httpx.TransportError as e:
        raise VendorError("net", type(e).__name__) from None
    raise VendorError("other", "the download ended without success")


async def unload(url, name, transport=None):
    """A model out of the card now (keep_alive 0): the memory goes back to whoever sits at that computer."""
    await _local_call(url, "POST", "/api/generate", {"model": name, "keep_alive": 0}, transport)


async def delete(url, name, transport=None):
    """A model off the server's disk; its weights stay while another model has them."""
    await _local_call(url, "DELETE", "/api/delete", {"model": name}, transport)


async def _local_call(url, method, path, body, transport=None):
    url = str(url or "").rstrip("/")
    if not url_ok(LOCAL, url):
        raise VendorError("url", url)
    kw = dict(transport=transport) if transport is not None else {}
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(60, connect=LOCAL_REACH), trust_env=False, **kw) as c:
            r = await c.request(method, url + path, json=body)
    except httpx.TransportError as e:
        raise VendorError("net", type(e).__name__) from None
    if r.status_code != 200:
        try:
            why = r.json().get("error")
        except ValueError:
            why = None
        raise VendorError("other", str(why or "HTTP %d" % r.status_code)[:200])


# One's own model's settings (stage M, step 6.5; the owner, 2026-11-08: "the system settings of each model separately" —
# lesson 6 of his own course on local models: "the system prompt, the temperature, the context length — through the
# Modelfile"). What reaches the model, found 2026-11-08 — Claude Code 2.1.300 as Pult runs one's own model, on a stand-in
# server (tools: the five; thinking off, effort low, auto — each tried), and Ollama 0.40.14's own source:
#   • Claude Code's request names no temperature, top_p, top_k or stop — only max_tokens and its effort (and adaptive
#     thinking); Ollama lays a request's options over the Modelfile's PARAMETERs, and those over the weights' own
#     sampling (general.sampling.*: server/routes.go modelOptions) — so a task gets the Modelfile's sampling and context;
#   • its SYSTEM Ollama leaves out — Claude Code brings a system prompt of its own — and Pult passes it on (model_system);
#   • thinking isn't the Modelfile's to set, nor Pult's: Claude Code never says "disabled", and Ollama has a model that
#     can think do so when nothing says otherwise; keep_alive isn't a Modelfile's parameter either;
#   • /api/create from the model over its own name keeps every layer it isn't given (the weights, the template),
#     replaces the SYSTEM it is given — never with nothing — and lays the parameters over the ones there
#     (create.ApplyModelfileLayers): a parameter once set can't be unset, an instruction can't be emptied. So the first
#     change keeps the model as it was in a copy of its own (WAS_NS — a few lines, the weights stay one) to come back to.
TUNE = {"temperature": (0.0, 2.0), "top_k": (1, 200), "top_p": (0.05, 1.0), "min_p": (0.0, 1.0),
        "repeat_penalty": (0.5, 2.0), "presence_penalty": (-2.0, 2.0)}
TUNE_INT = ("top_k",)
OLLAMA_DEFAULTS = {"temperature": 0.8, "top_k": 40, "top_p": 0.9, "min_p": 0.0, "repeat_penalty": 1.0,
                   "presence_penalty": 0.0}              # api.DefaultOptions, v0.40.14: what is left when nothing sets one
SAMPLING = {"temperature": "general.sampling.temp", "top_k": "general.sampling.top_k", "top_p": "general.sampling.top_p"}
CTXS = (16384, 32768, 65536, 131072, 262144)
CARD_OVERHEAD = int(1.3 * 1000 ** 3)   # bytes a loaded model takes past its weights and cache: gemma4-32k took 10.2 GB of
                                       # the card with 32K (nvidia-smi, 2026-11-04) — 8.02 of weights, 0.87 of cache
WAS_NS = "pult-was/"                   # the copy of a model as it was before Pult first changed it
LOCAL_ALL_CTX = 65536                  # all of Claude Code's tools: their descriptions alone are ~22K tokens of the first
                                       # request (tests/probe_local.py, 2026-11-04) — a context of 64K at least


def parse_params(text):
    """/api/show's "parameters" — lines of "name value", a name more than once for a list (stop) → {name: value}."""
    out = {}
    for line in str(text or "").splitlines():
        k, _, v = line.strip().partition(" ")
        v = v.strip()
        if not k or not v:
            continue
        if len(v) >= 2 and v[0] == v[-1] == '"':
            v = v[1:-1]
        val = int(v) if re.fullmatch(r"-?\d+", v) else float(v) if re.fullmatch(r"-?(\d+\.\d*|\.\d+|\d+(\.\d*)?e-?\d+)", v) else v
        out[k] = (out[k] if isinstance(out[k], list) else [out[k]]) + [val] if k in out else val
    return out


def kv_cost(info):
    """What a model's cache takes on the card, by its make (/api/show's model_info): bytes per token of the context — the
    layers that see the whole of it — and a fixed part — the layers that see a window (gemma4: 40 of its 48, 1024 tokens)
    or keep a state of their own (qwen3.5: 24 of 32 take nothing that grows); f16 — two bytes a number, keys and
    values. → (per_token, fixed), or None when the make isn't told."""
    arch = info.get("general.architecture") if isinstance(info, dict) else None
    if not isinstance(arch, str):
        return None

    def g(k):
        return info.get("%s.%s" % (arch, k))
    n, kv = g("block_count"), g("attention.head_count_kv")
    kl, vl = g("attention.key_length"), g("attention.value_length")
    if not isinstance(n, int) or n <= 0 or kv is None:
        return None
    if not isinstance(kl, int) or not isinstance(vl, int):
        emb, heads = g("embedding_length"), g("attention.head_count")
        if not (isinstance(emb, int) and isinstance(heads, int) and heads > 0):
            return None
        kl = vl = emb // heads
    kls, vls = g("attention.key_length_swa") or kl, g("attention.value_length_swa") or vl
    swa, win = g("attention.sliding_window_pattern"), g("attention.sliding_window")
    rec, every = g("attention.recurrent_layers"), g("full_attention_interval")
    per = fixed = 0
    for i in range(n):
        h = kv[i] if isinstance(kv, list) and i < len(kv) else kv
        if not isinstance(h, int) or isinstance(h, bool):
            return None
        if isinstance(rec, list) and i < len(rec):
            state = bool(rec[i])
        else:
            state = isinstance(every, int) and every > 1 and (i + 1) % every != 0
        if state:
            continue
        if isinstance(swa, list) and i < len(swa) and swa[i] and isinstance(win, int) and win > 0:
            fixed += h * (kls + vls) * 2 * win
        else:
            per += h * (kl + vl) * 2
    return per, fixed


def vram_at(size, cost, ctx):
    """How much of the card a model takes with this context: its weights, its cache by its make (kv_cost) and what a
    loaded model takes past them — a rough count; without the make — the cache growing as vram_need has it at 32K."""
    if not size:
        return None
    if not cost:
        return int(size * (1 + 0.2 * ctx / LOCAL_CTX_COPY))
    per, fixed = cost
    return int(size + fixed + per * ctx + CARD_OVERHEAD)


def local_tools(ctx, choice):
    """The tools a task of one's own model gets: the five core ones (LOCAL_TOOLS), or — when its settings say "all" and
    its context takes them (LOCAL_ALL_CTX) — None: no list, every tool Claude Code has."""
    return None if choice == "all" and (ctx or 0) >= LOCAL_ALL_CTX else list(LOCAL_TOOLS)


def tune_value(k, v):
    """One of the owner's values for parameter k → the number to write, or ValueError: a name not offered, a value out
    of its range."""
    if k not in TUNE or isinstance(v, bool):
        raise ValueError(k)
    lo, hi = TUNE[k]
    x = float(v)
    if not lo <= x <= hi:
        raise ValueError(k)
    return int(round(x)) if k in TUNE_INT else round(x, 3)


async def model_show(url, model, transport=None):
    """A model's settings as its server has them (/api/show): its SYSTEM, its PARAMETERs, what it was trained for, what
    it can do, its cache's cost (kv_cost) and its weights' own sampling — what a parameter not set falls back to. Never
    through a proxy, never loads it. → {"system", "params", "max", "caps", "cost", "sampling"}; VendorError "url",
    "net", "model" (no such model there)."""
    url = str(url or "").rstrip("/")
    if not url_ok(LOCAL, url):
        raise VendorError("url", url)
    kw = dict(transport=transport) if transport is not None else {}
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(10, connect=LOCAL_REACH), trust_env=False, **kw) as c:
            r = await c.post(url + "/api/show", json={"model": model})
    except httpx.TransportError as e:
        raise VendorError("net", type(e).__name__) from None
    try:
        d = r.json() if r.status_code == 200 else {}
    except ValueError:
        d = {}
    if not isinstance(d, dict) or not d:
        raise VendorError("model", model)
    info = d.get("model_info") if isinstance(d.get("model_info"), dict) else {}
    top = next((v for k, v in info.items() if k.endswith(".context_length") and isinstance(v, int)), None)
    sampling = {k: info[x] for k, x in SAMPLING.items() if isinstance(info.get(x), (int, float)) and not isinstance(info.get(x), bool)}
    system = d.get("system") if isinstance(d.get("system"), str) else ""
    return {"system": system.strip(), "params": parse_params(d.get("parameters")), "max": top,
            "caps": [x for x in d.get("capabilities") or [] if isinstance(x, str)], "cost": kv_cost(info), "sampling": sampling}


def was_name(model):
    """The name of a model's copy as it was before Pult first changed it: "qwen3.5:4b" → "pult-was/qwen3.5-4b"."""
    return WAS_NS + re.sub(r"[:/]", "-", model.removesuffix(":latest"))[:70]


async def tune(url, model, system=None, params=None, keep=False, transport=None):
    """A model's settings into the model itself (Settings of a model → "Save", the owner's tap): first, when keep — the
    model as it was, into its copy WAS_NS (a few lines; its weights stay one copy); then /api/create from the model over
    its own name with the SYSTEM (an empty one can't be written: a space takes its place, and Pult passes nothing on)
    and the parameters laid over its own. VendorError "url", "net", "other"."""
    url = str(url or "").rstrip("/")
    if not url_ok(LOCAL, url):
        raise VendorError("url", url)
    if keep and not await _exists(url, was_name(model), transport):    # one kept already is the true "as it was"
        await _create(url, {"model": was_name(model), "from": model}, transport)
    body = {"model": model, "from": model}
    if system is not None:
        body["system"] = str(system).strip()[:OWN_SYSTEM_MAX] or " "
    if params:
        body["parameters"] = dict(params)
    if len(body) > 2:
        await _create(url, body, transport)


async def untune(url, model, transport=None):
    """A model back as it was before Pult first changed it: made anew from its copy WAS_NS, which then goes."""
    url = str(url or "").rstrip("/")
    if not url_ok(LOCAL, url):
        raise VendorError("url", url)
    await _create(url, {"model": model, "from": was_name(model)}, transport)
    await _local_call(url, "DELETE", "/api/delete", {"model": was_name(model)}, transport)


async def _exists(url, model, transport=None):
    """Whether the server has this model (/api/show answers it): nothing is loaded."""
    kw = dict(transport=transport) if transport is not None else {}
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(10, connect=LOCAL_REACH), trust_env=False, **kw) as c:
            return (await c.post(url + "/api/show", json={"model": model})).status_code == 200
    except httpx.TransportError as e:
        raise VendorError("net", type(e).__name__) from None


async def _create(url, body, transport=None):
    kw = dict(transport=transport) if transport is not None else {}
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(120, connect=LOCAL_REACH), trust_env=False, **kw) as c:
            r = await c.post(url + "/api/create", json=dict(body, stream=False))
    except httpx.TransportError as e:
        raise VendorError("net", type(e).__name__) from None
    try:
        got = r.json()
    except ValueError:
        got = {}
    if r.status_code != 200 or got.get("status") != "success":
        raise VendorError("other", str(got.get("error") or got.get("status") or "HTTP %d" % r.status_code)[:200])
