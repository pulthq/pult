"""Claude as the one who gives a second opinion (stage M, M4.2; review 2026-11-11, block 6): Codex did a task — Claude
reads what it changed, on the owner's Claude subscription, and changes nothing. Who reviews whose work is said in one
place here (reviewer_of): a task Codex did is read by Claude, any other — by Codex (pult_codex.review).

Claude only reads by what it is given, not by a promise (tests/probe_claude_review.py, Claude Code 2.1.322,
claude-sonnet-5-5, 2026-11-11):
  • the Agent SDK's `tools` names the only tools the session has — Read, Grep, Glob: no Bash, no Write, no Edit; ordered
    to write a file and to run a command it could do neither, and said which three tools it has;
  • no MCP server either (`--strict-mcp-config` with none named): without it the account's own claude.ai connectors
    came along — eight more tools in the first run, writing ones among them;
  • no settings are loaded (no hooks, nobody's CLAUDE.md as instructions), PULT_OFF=1 keeps Pult's own hook silent, and
    nothing is kept as a session (`--no-session-persistence`: no file appeared under ~/.claude/projects);
  • a tool that would need a permission (a file outside the folder) has nobody to ask and is refused;
  • with no command to run, the changes come in the prompt: Pult reads git itself (git_diff). A review took 10 s and
    a check of the fixes 5 s on a small change; both came in the shape pult_codex.parse and parse_check read.
The answer's shape is Codex's own review format, asked for in words (SHAPE), so one reader serves both reviewers.
Standard library and the Agent SDK only; the SDK is imported when a review runs."""
import asyncio
import json
import os
import re
import subprocess

import pult_codex as CX
import pult_files as F
import pult_web as PW

MODEL = "claude-sonnet-5-5"     # the owner's choice (Q182): enough to read a change, lighter on the plan than Opus
TOOLS = ("Read", "Grep", "Glob")
TIMEOUT = 15 * 60               # s: as Codex's review
DIFF_MAX = 120_000              # characters of the changes put into the prompt; longer — cut, the files are there to read
NEW_MAX = 60                    # new files named, at most
GIT_TIME = 20                   # s for one git command
SYSTEM = ("You give a second opinion on code changes another coding agent made. You can only read files in this folder: "
          "you have no way to change anything or to run a command.")
SHAPE = ("Answer in this shape exactly. First your overall words, a sentence or two. Then, if there are findings, the line "
         "\"Review comments:\" and each finding as \"- [P1] title — path/to/file:12-14\" (P0 the gravest, P3 the "
         "slightest; the path from this folder), with what breaks and how to fix it on the next lines, two spaces in. "
         "No findings — your overall words only.")
REVIEWERS = {
    # who gives the second opinion: its name on the screens, whose service the project's code goes to with it, and the
    # store's key of the projects the owner allowed it to read (Codex's is the older one, Q105)
    "codex": {"name": "Codex", "to": "OpenAI", "ok": "vendors.ok"},
    "claude": {"name": "Claude", "to": "Anthropic", "ok": "review.claude"},
}


def reviewer_of(vendor):
    """Who gives a second opinion on a task: Claude on one Codex did, Codex on any other — Claude's own or another
    vendor's model inside Claude Code. vendor — the task's (pult_tg.Store.vendor_of): None is Claude."""
    return "claude" if vendor == "codex" else "codex"


def codex_facts(path, cwd=None):
    """What a task Codex did was, from its history file — as pult_codex.task_facts gives a Claude task's: t0, asks (the
    owner's messages in order), report (Codex's last words), files (what its patches wrote, from the folder when inside
    it)."""
    t0, asks, report, files = None, [], "", {}
    try:
        f = open(path, "rb")
    except OSError:
        return {"t0": None, "asks": [], "report": "", "files": []}
    real = os.path.realpath(cwd) if cwd else None
    with f:
        for line in f:
            try:
                e = json.loads(line)
            except ValueError:
                continue
            if not isinstance(e, dict):
                continue
            if t0 is None and e.get("timestamp"):
                t0 = CX._epoch(e["timestamp"])
            p = e.get("payload") if isinstance(e.get("payload"), dict) else {}
            kind, what = e.get("type"), p.get("type")
            who, text = PW._cx_said(kind, what, p)
            text = (text or "").strip()
            if who == "user" and text and (not asks or asks[-1] != text):       # Codex keeps the same words in several records
                asks.append(text)
            elif who == "codex" and text:
                report = text
            elif kind == "response_item" and what == "custom_tool_call":
                for name in PW.codex_step(p.get("input"))[1].get("files") or []:
                    files.setdefault(CX._inside(os.path.join(real, name) if real and not os.path.isabs(name) else name, real), None)
    return {"t0": t0, "asks": asks, "report": report, "files": list(files)}


def _git(cwd, *args):
    try:
        r = subprocess.run(["git", "-C", cwd, "-c", "core.quotepath=off", *args], capture_output=True, timeout=GIT_TIME,
                           stdin=subprocess.DEVNULL, env=dict(os.environ, GIT_OPTIONAL_LOCKS="0"))
    except (OSError, subprocess.SubprocessError):
        return None
    return r.stdout.decode("utf-8", "replace") if r.returncode == 0 else None


_FILE = re.compile(r"^diff --git a/(.*?) b/(.*)$", re.M)


def git_diff(cwd, base, repos=(), limit=DIFF_MAX):
    """What a task changed, as words for the prompt — the reviewer has no command to run: the folder's diff since
    `base` (pult_codex.git_base; None — the folder isn't in git) and each nested repository's since its own (repos —
    pult_codex.nested_repos), the new files by name; a file whose name looks like keys or settings is named, never
    shown (pult_files.secret_like — the rule of the app's "Changes"); longer than `limit` — cut, and said so. "" when
    git has nothing to show."""
    parts, new = [], []
    for d, b in ([("", base)] if base else []) + [(r["dir"], r.get("base")) for r in repos if r.get("base")]:
        top = os.path.join(cwd, d) if d else cwd
        pre = d.replace(os.sep, "/") + "/" if d else ""
        text = _git(top, "diff", "--no-color", "--src-prefix=a/" + pre, "--dst-prefix=b/" + pre, b, "--", ".")
        for sec in re.split(r"(?m)^(?=diff --git )", text or ""):
            m = _FILE.match(sec)
            if not m:
                continue
            if F.secret_like(m.group(2)) or F.secret_like(m.group(1)):
                sec = "diff --git a/%s b/%s\n(this file looks like keys or settings: it changed, and is not shown)\n" % m.groups()
            parts.append(sec)
        for name in (_git(top, "ls-files", "--others", "--exclude-standard", "--", ".") or "").splitlines():
            if name.strip():
                new.append(pre + name.strip())
    text = "".join(parts)
    if len(text) > limit:
        text = text[:limit].rsplit("\n", 1)[0] + "\n(the changes are longer than this — cut here: read the files themselves)\n"
    if new:
        text += ("\nNew files, not in git yet — read them as they are: %s%s\n"
                 % (", ".join(new[:NEW_MAX]), " and %d more" % (len(new) - NEW_MAX) if len(new) > NEW_MAX else ""))
    return text


def options(cli, cwd, model=MODEL):
    """Agent SDK options of a session that can only read (the module's header says what each one is for)."""
    from claude_agent_sdk import ClaudeAgentOptions
    kw = dict(model=model, cwd=str(cwd), tools=list(TOOLS), setting_sources=[], permission_mode="default",
              env={"PULT_OFF": "1"}, mcp_servers={}, system_prompt=SYSTEM,
              extra_args={"no-session-persistence": None, "strict-mcp-config": None}, stderr=lambda s: None)
    if cli:
        kw["cli_path"] = str(cli)
    return ClaudeAgentOptions(**kw)


def kind_of(text):
    """Why Claude gave no review, by its words — one of the causes the card and the topic have words for."""
    low = str(text or "").lower()
    if "limit" in low and ("usage" in low or "rate" in low or "reached" in low):
        return "limit"
    if "log in" in low or "login" in low or "authenticat" in low or "api key" in low or "unauthorized" in low:
        return "login"
    if "overloaded" in low:
        return "overloaded"
    return "failed"


async def claude(cli, cwd, text, on_step=None, timeout=TIMEOUT, model=MODEL):
    """One second opinion by Claude: a session in `cwd` that can only read, asked `text`; on_step(n) after each file it
    read or searched. → {"text", "model", "effort", "limits", "asked"} as pult_codex.review gives (no plan windows are
    read: Pult counts Claude's usage itself). Raises pult_codex.CodexError with a cause; cancelled — the session is
    closed by the SDK."""
    try:
        from claude_agent_sdk import AssistantMessage, ResultMessage, SystemMessage, TextBlock, ToolUseBlock, query
    except ImportError as e:
        raise CX.CodexError("start", repr(e))
    said, res, ran, steps = "", None, None, 0

    async def run():
        nonlocal said, res, ran, steps
        async for m in query(prompt=text, options=options(cli, cwd, model)):
            if isinstance(m, SystemMessage) and m.subtype == "init":
                ran = m.data.get("model")
            elif isinstance(m, AssistantMessage):
                for b in m.content:
                    if isinstance(b, TextBlock) and b.text.strip():
                        said = b.text
                    elif isinstance(b, ToolUseBlock):
                        steps += 1
                        if on_step:
                            on_step(steps)
            elif isinstance(m, ResultMessage):
                res = m
    try:
        await asyncio.wait_for(run(), timeout)
    except asyncio.TimeoutError:
        raise CX.CodexError("timeout", "no end in %d min" % (timeout // 60))
    except asyncio.CancelledError:
        raise
    except Exception as e:
        raise CX.CodexError(kind_of(repr(e)) if kind_of(repr(e)) != "failed" else "start", repr(e)[:300])
    if res is None or getattr(res, "is_error", False) or not said.strip():
        why = str(getattr(res, "result", "") or said or "no answer")
        raise CX.CodexError(kind_of(why), why[:300])
    return {"text": said, "model": ran or model, "effort": None, "limits": [], "asked": []}
