"""Pult: rendering for Telegram — markdown to HTML, turn steps, permission requests, questions.

No dependencies and no network: everything here is covered by tests/test_pult.py. User-facing words come from
pult_i18n in the owner's current language.
"""
import html
import json
import os
import re
import time

import pult_i18n as I
from pult_i18n import T

TG_LIMIT = 4096
CHUNK = 3500          # a chunk of source markdown; it grows after HTML escaping


def esc(s):
    return html.escape(str(s or ""), quote=False)


def short(s, n):
    s = " ".join(str(s or "").split())
    return s if len(s) <= n else s[: n - 1] + "…"


def fmt_dur(sec):
    sec = int(max(0, sec))
    if sec < 3600:
        return "%d:%02d" % (sec // 60, sec % 60)
    return "%d:%02d:%02d" % (sec // 3600, sec % 3600 // 60, sec % 60)


def human_dur(sec):
    """“40 s”, “6 min”, “1 h 5 min” — for messages to a person."""
    sec = int(max(0, sec))
    if sec < 60:
        return T("dur.s", n=sec)
    if sec < 3600:
        return T("dur.m", n=sec // 60)
    m = sec % 3600 // 60
    return T("dur.h", n=sec // 3600) + (" " + T("dur.m", n=m) if m else "")


def reset_text(ts, now=None):
    """When a limit resets: “at 20:00 (in 2 h 10 min)”; more than a day away — “Thu 19:00”."""
    if not ts:
        return "—"
    now = now or time.time()
    left = ts - now
    lt = time.localtime(ts)
    if left > 86400:
        return "%s %s" % (T("weekdays").split()[lt.tm_wday], time.strftime("%H:%M", lt))
    return T("reset.at", hm=time.strftime("%H:%M", lt), left=T("reset.in", left=human_dur(max(0, left))))


def plain(md, n):
    """Claude's message as one line without markup — for the “now” line of a turn message."""
    s = re.sub(r"```.*?```", " … ", str(md or ""), flags=re.S)
    s = re.sub(r"\[([^\]\n]+)\]\([^)\s]+\)", r"\1", s)
    s = re.sub(r"(?m)^\s{0,3}(#{1,6}|[-*]|\d+\.)\s+", "", s)
    s = re.sub(r"\*\*|__|`|(?<!\w)\*(?!\s)|(?<!\s)\*(?!\w)", "", s)
    return short(s, n)


def steps_word(n):
    return "%d %s" % (n, I.plural(n, "step"))


def lines_word(n):
    return "%d %s" % (n, I.plural(n, "line"))


# ---------- Claude's background tasks ----------

_TASK_NOTE = re.compile(r"<task-notification>(.*?)</task-notification>", re.S)
_TASK_END = ("completed", "failed", "stopped", "killed")


def _tag(block, name):
    m = re.search(r"<%s>(.*?)</%s>" % (name, name), block, re.S)
    return m.group(1).strip() if m else ""


def _names(items, n):
    out = ", ".join(I.q(x) for x in items[:n])
    return out + (T("and_more", n=len(items) - n) if len(items) > n else "")


def task_notes(prompt):
    """A turn Claude Code started by itself because a background task ended: the “prompt” is then a set of
    <task-notification> blocks with task-id, status, summary (probe 2026-10-16, Claude Code 2.1.301).
    → [{id, status, what}]; for a prompt typed by a person — []."""
    if not str(prompt or "").lstrip().startswith("<task-notification>"):
        return []
    out = []
    for block in _TASK_NOTE.findall(prompt):
        summary = _tag(block, "summary")
        m = re.search(r'"(.+)"', summary)          # Background command "Description" completed (exit code 0)
        out.append({"id": _tag(block, "task-id"), "status": _tag(block, "status"),
                    "what": m.group(1) if m else summary})
    return out


def task_notes_text(notes):
    """Shown instead of “You: …” for a turn Claude started by itself: “⚙️ Background task finished: “Build””."""
    if len(notes) == 1:
        status = notes[0]["status"]
        key = "task.failed" if status == "failed" else "task.stopped" if status in ("stopped", "killed") \
            else "task.completed"
        return T(key, what=I.q(short(notes[0]["what"], 80)))
    return T("task.many", list=_names([short(n["what"], 50) for n in notes], 3))


def bg_text(tasks):
    """Background tasks still running after a turn (`background_tasks` of the Stop hook) → a line for the result
    message; none — ""."""
    names = [short(t.get("description") or t.get("command") or T("task.default"), 60) for t in tasks or []
             if isinstance(t, dict) and t.get("status") not in _TASK_END]
    if not names:
        return ""
    if len(names) == 1:
        return T("bg.one", what=I.q(names[0]))
    return T("bg.many", n=len(names), list=_names(names, 3))


# ---------- Claude's markdown → Telegram HTML ----------

def _inline(s):
    lines = []
    for line in s.split("\n"):
        m = re.match(r"^\s{0,3}#{1,6}\s+(.*?)\s*#*\s*$", line)
        if m:
            line = "**%s**" % m.group(1)
        line = re.sub(r"^(\s*)[-*]\s+", r"\1• ", line)
        lines.append(line)
    s = "\n".join(lines)
    keep = []

    def hold(h):
        keep.append(h)
        return "\x00%d\x00" % (len(keep) - 1)
    s = re.sub(r"`([^`\n]+)`", lambda m: hold("<code>%s</code>" % html.escape(m.group(1))), s)
    s = re.sub(r"\[([^\]\n]+)\]\((https?://[^\s)]+)\)",
               lambda m: hold('<a href="%s">%s</a>' % (html.escape(m.group(2)), html.escape(m.group(1)))), s)
    # a link to a project file [name](path) won't open in Telegram — keep the name and the path as code
    s = re.sub(r"\[([^\]\n]+)\]\(([^\s)]+)\)",
               lambda m: hold("%s (<code>%s</code>)" % (html.escape(m.group(1)), html.escape(m.group(2)))), s)
    s = html.escape(s, quote=False)
    s = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", s)
    s = re.sub(r"(?<![\w*])\*(?!\s)([^*\n]+?)(?<!\s)\*(?![\w*])", r"<i>\1</i>", s)
    return re.sub(r"\x00(\d+)\x00", lambda m: keep[int(m.group(1))], s)


def _is_table(block):
    rows = [r for r in block.strip("\n").split("\n") if r.strip()]
    return len(rows) >= 2 and all(r.lstrip().startswith("|") for r in rows)


def md_to_html(md):
    out = []
    for part in re.split(r"(```.*?```)", md or "", flags=re.S):
        if part.startswith("```") and part.endswith("```") and len(part) >= 6:
            body = re.sub(r"^[\w+-]*\n", "", part[3:-3], count=1)
            out.append("<pre>%s</pre>" % html.escape(body.strip("\n")))
            continue
        # Telegram doesn't draw markdown tables — as a monospace block they're at least readable
        pieces = re.split(r"((?:^[ \t]*\|.*\n?){2,})", part, flags=re.M)
        for p in pieces:
            if p and _is_table(p):
                out.append("<pre>%s</pre>\n" % html.escape(p.strip("\n")))
            else:
                out.append(_inline(p))
    return "".join(out)


def html_to_plain(h):
    return html.unescape(re.sub(r"<[^>]+>", "", h or ""))


def split_md(s, limit=CHUNK):
    """Split markdown into chunks by paragraph without breaking ```code``` blocks."""
    blocks = re.split(r"(```.*?```)", s or "", flags=re.S)
    paras = []
    for b in blocks:
        if b.startswith("```") and b.endswith("```") and len(b) >= 6:
            if len(b) <= limit:
                paras.append(b)
                continue
            head = b[: b.find("\n") + 1] if "\n" in b else "```\n"
            body = b[len(head):-3]
            step = limit - len(head) - 8
            for i in range(0, len(body), step):
                paras.append(head + body[i:i + step].strip("\n") + "\n```")
        else:
            paras.extend(p for p in b.split("\n\n") if p.strip())
    chunks, cur = [], ""
    for para in paras:
        while len(para) > limit:
            cut = para.rfind("\n", 0, limit)
            cut = cut if cut > limit // 2 else limit
            if cur:
                chunks.append(cur)
                cur = ""
            chunks.append(para[:cut])
            para = para[cut:].lstrip("\n")
        if cur and len(cur) + len(para) + 2 > limit:
            chunks.append(cur)
            cur = para
        else:
            cur = cur + "\n\n" + para if cur else para
    if cur:
        chunks.append(cur)
    return chunks or [""]


# ---------- turn steps ----------

def _rel(path, cwd):
    path = str(path or "")
    if cwd and path.startswith(cwd.rstrip("/") + "/"):
        return path[len(cwd.rstrip("/")) + 1:]
    home = os.path.expanduser("~")
    return "~" + path[len(home):] if path.startswith(home + "/") else path


def tool_step(name, inp, cwd=None, failed=False, sub=False):
    """One line per step: “📖 README.md”, “⌘ git status”. None — don't show the step.
    Steps no longer go to the chat (the turn shows Claude's own words); the app shows them."""
    inp = inp if isinstance(inp, dict) else {}
    n = name or "?"
    if n in ("TodoWrite", "TaskCreate", "TaskUpdate", "TaskList", "TaskGet"):
        return None
    if n == "Read":
        s = "📖 " + _rel(inp.get("file_path"), cwd)
    elif n in ("Edit", "MultiEdit", "Write", "NotebookEdit"):
        s = "✏️ " + _rel(inp.get("file_path") or inp.get("notebook_path"), cwd)
    elif n == "Bash":
        s = "⌘ " + (inp.get("description") or inp.get("command") or "")
    elif n in ("Grep", "Glob"):
        s = "🔎 " + str(inp.get("pattern") or "")
    elif n == "WebSearch":
        s = "🌐 " + str(inp.get("query") or "")
    elif n == "WebFetch":
        s = "🌐 " + str(inp.get("url") or "")
    elif n in ("Agent", "Task"):
        s = "🤖 " + str(inp.get("description") or inp.get("subagent_type") or T("step.subagent"))
    elif n == "AskUserQuestion":
        qs = inp.get("questions") or []
        ans = inp.get("answers") or {}
        s = "❓ " + "; ".join("%s → %s" % (q.get("header") or q.get("question"), ans.get(q.get("question"), "…"))
                              for q in qs)
    elif n == "ExitPlanMode":
        s = "📋 " + T("step.plan")
    elif n == "Skill":
        s = "🧩 " + str(inp.get("skill") or inp.get("command") or T("step.skill"))
    elif n.startswith("mcp__"):
        s = "🔌 " + n[5:].replace("__", ": ")
    else:
        s = "• " + n
    s = short(s, 90)
    if failed:
        s = "⚠️ " + s
    return ("↳ " + s) if sub else s


# ---------- permission requests and questions ----------

def _code(text, n=900):
    return "<pre>%s</pre>" % esc(short_block(text, n))


def short_block(text, n):
    text = str(text or "")
    return text if len(text) <= n else text[: n - 1] + "…"


def _nlines(s):
    s = str(s or "")
    return len(s.splitlines()) if s else 0


def _diff(edits, n=12):
    """An edit in short: “−” and “+” lines, at most n."""
    out = []
    for e in edits:
        out += ["− " + short(x, 110) for x in str(e.get("old_string") or "").splitlines()]
        out += ["+ " + short(x, 110) for x in str(e.get("new_string") or "").splitlines()]
    if len(out) > n:
        more = len(out) - n
        out = out[:n] + [T("diff.more", n=more, lines=I.plural(more, "line"))]
    return "<pre>%s</pre>" % esc("\n".join(out)) if out else ""


def permission_text(tool, inp, cwd=None):
    """What Claude wants to do, in plain words (HTML). The command is shown in full up to 1200 characters:
    nobody should decide blind."""
    inp = inp if isinstance(inp, dict) else {}
    if tool == "Bash":
        d = inp.get("description")
        return "%s\n%s" % (T("perm.bash", desc=": <b>%s</b>" % esc(I.q(d)) if d else ""), _code(inp.get("command"), 1200))
    if tool in ("Edit", "MultiEdit"):
        edits = inp.get("edits") if tool == "MultiEdit" else [inp]
        edits = [e for e in edits or [] if isinstance(e, dict)]
        plus = sum(_nlines(e.get("new_string")) for e in edits)
        minus = sum(_nlines(e.get("old_string")) for e in edits)
        return "%s\n%s" % (T("perm.edit", path=esc(_rel(inp.get("file_path"), cwd)), plus=plus, minus=minus),
                           _diff(edits))
    if tool == "Write":
        path = inp.get("file_path") or ""
        text = str(inp.get("content") or "")
        head = "\n".join(text.splitlines()[:8])
        key = "perm.overwrite" if os.path.exists(path) else "perm.create"
        return "%s\n%s" % (T(key, path=esc(_rel(path, cwd)), lines=lines_word(_nlines(text))),
                           _code(head, 600) if head else "")
    if tool == "NotebookEdit":
        return "%s\n%s" % (T("perm.notebook", path=esc(_rel(inp.get("notebook_path"), cwd))),
                           _code(inp.get("new_source"), 600))
    if tool == "WebFetch":
        return T("perm.fetch", url=esc(inp.get("url")))
    if tool == "WebSearch":
        return T("perm.search", query=esc(I.q(inp.get("query"))))
    if (tool or "").startswith("mcp__"):
        what = T("perm.mcp", name=esc(tool[5:].replace("__", ": ")))
    else:
        what = T("perm.tool", name=esc(tool))
    return "%s\n%s" % (what, _code(json.dumps(inp, ensure_ascii=False, indent=1), 900))


def question_text(q, picked=None, done=False):
    """An AskUserQuestion question: the title, options with their descriptions, what's checked."""
    picked = picked or []
    lines = ["<b>%s</b>" % esc(q.get("question"))]
    for o in q.get("options") or []:
        mark = "☑️" if o.get("label") in picked else "▫️"
        d = (" — " + esc(short(o.get("description"), 160))) if o.get("description") else ""
        lines.append("%s %s%s" % (mark, esc(o.get("label")), d))
    if not done:
        lines.append("<i>%s</i>" % T("ask.hint.many" if q.get("multiSelect") else "ask.hint.one"))
    return "\n".join(lines)


def answers_for(questions, chosen):
    """chosen: {question index: [answers]} → `answers` for AskUserQuestion."""
    return {q.get("question"): ", ".join(chosen[i]) for i, q in enumerate(questions) if i in chosen}
