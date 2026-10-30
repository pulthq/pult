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
Standard library and httpx (the key's check). Design: docs/project.html, stage M.
"""
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
}
ORDER = ("deepseek", "glm", "kimi")


class VendorError(Exception):
    """A key that doesn't pass its check: kind "key" (refused), "balance" (no money left on it), "model" (the key is
    good, the model's name isn't), "net" (no way there), "other" (anything else, with the vendor's words)."""
    def __init__(self, kind, text=""):
        super().__init__(text or kind)
        self.kind, self.text = kind, str(text or "")


def key_name(vid):
    return KEY_PREFIX + vid.upper()


def profiles(own=None):
    """The presets with the owner's own changes over them (state.db, "vendors.conf": {vid: {"models", "url"}})."""
    out = {}
    for vid in ORDER:
        p = dict(PRESETS[vid], id=vid)
        mine = (own or {}).get(vid) or {}
        models = [m for m in mine.get("models") or [] if isinstance(m, str) and MODEL_RE.fullmatch(m)][:MODELS_MAX]
        if models:
            p["models"] = models
        if isinstance(mine.get("url"), str) and mine["url"].startswith("https://"):
            p["url"] = mine["url"].rstrip("/")
        out[vid] = p
    return out


def clean_models(text):
    """The owner's list of models from Settings — commas, spaces or lines between them — → a list, or ValueError."""
    names = [x for x in re.split(r"[\s,;]+", str(text or "")) if x]
    if not names or len(names) > MODELS_MAX or not all(MODEL_RE.fullmatch(x) for x in names):
        raise ValueError(text)
    return list(dict.fromkeys(names))


def session_env(p, key, model=None):
    """The environment of a session that runs on vendor profile p with this key: never without a key — with the
    address alone Claude Code sends the Claude subscription's token there (probe_vendor.py)."""
    if not (isinstance(key, str) and key.strip()):
        raise ValueError("no key for " + p["name"])
    main = model or p["models"][0]
    fast = p["models"][1] if len(p["models"]) > 1 else p["models"][0]
    env = {k: str(v) for k, v in (p.get("env") or {}).items()}       # the vendor's own advice first: never over these
    env.update({"ANTHROPIC_BASE_URL": p["url"], "ANTHROPIC_AUTH_TOKEN": key, "ANTHROPIC_API_KEY": key,
                "ANTHROPIC_DEFAULT_OPUS_MODEL": main, "ANTHROPIC_DEFAULT_SONNET_MODEL": main,
                "ANTHROPIC_DEFAULT_FABLE_MODEL": main, "ANTHROPIC_DEFAULT_HAIKU_MODEL": fast,
                "CLAUDE_CODE_SUBAGENT_MODEL": fast, "CLAUDE_CODE_ENTRYPOINT": "sdk-py"})
    if p.get("ctx"):
        env["CLAUDE_CODE_AUTO_COMPACT_WINDOW"] = str(int(p["ctx"]))
    return env


async def check_key(p, key, proxy=None, transport=None):
    """Whether the key works: the smallest request there is — one token from the fast model (a fraction of a cent).
    Through the proxy first when one is set, then directly, like Telegram. → the model that answered; VendorError."""
    if not re.fullmatch(KEY_CHARS, key or ""):
        raise VendorError("key")
    model = re.sub(r"\[1m\]$", "", p["models"][1] if len(p["models"]) > 1 else p["models"][0])   # as Claude Code sends it
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
