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
Standard library and httpx (the key's check). Design: docs/project.html, stage M.
"""
import os
import re

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


def identity(vid, model):
    """The line appended to Claude Code's system prompt in a session on another vendor's model: who it is."""
    model = re.sub(r"\[1m\]$", "", str(model or ""))
    return ("Who you are: you are not Claude. You are %s, %s, working inside Claude Code through Pult. The text above "
            "was written for Claude: its tools and rules are yours, but when asked who or what you are, say you are %s."
            % (model, MAKERS.get(vid, "another vendor's model"), model))


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
                if not isinstance(name, str) or CLOUD.search(name) or not MODEL_RE.fullmatch(name):
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


def vendor_of_model(model):
    """A reply's model → whose: None for Claude's own (and Claude Code's synthetic lines), else a word for the other."""
    m = (model or "").lower()
    if not m or "claude" in m or m.startswith("<"):
        return None
    return next((vid for vid in ORDER if vid in m or (vid == "kimi" and "moonshot" in m)), "other")
