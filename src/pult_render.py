"""Pult: rendering for Telegram — markdown to HTML, turn steps, permission requests, questions.

No dependencies and no network: everything here is covered by tests/test_pult.py. User-facing words come from
pult_i18n in the owner's current language.
"""
import html
import json
import os
import re
import time
import urllib.parse

import pult_i18n as I
from pult_i18n import T

TG_LIMIT = 4096
CHUNK = 3500          # a chunk of source markdown; it grows after HTML escaping


def esc(s):
    return html.escape(str(s or ""), quote=False)


def host_of(url):
    """Where a link really leads, as the reader should see it: a non-Latin name in its xn-- form (a look-alike
    letter doesn't pass), without "www."."""
    try:
        h = urllib.parse.urlsplit(url).hostname or ""
    except ValueError:
        return ""
    try:
        h = h.encode("idna").decode()
    except UnicodeError:
        pass
    return h[4:] if h.startswith("www.") else h


def link(text, url):
    """[text](url) → a link whose words can't hide where it leads: unless they show that very address, the address
    follows in brackets. Claude may write a link a web page talked it into, and it comes from the owner's own bot."""
    host = host_of(url)
    a = '<a href="%s">%s</a>' % (html.escape(url), html.escape(text))
    t = text.strip()
    if not host or host_of(t if "://" in t else "http://" + t) == host:
        return a
    return "%s (%s)" % (a, html.escape(host))


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


# ---------- the owner's attachments ----------

# what Claude reads under a message with a picture or a file: the path on the computer (pultd.take_files,
# with_uploads). People see the text without it, and "📎 picture" instead
_ATT = re.compile(r"[ \n]*\[Attachment from (?:Telegram|the Pult app): ([^\n]+?)\](?=\n|$)")   # a name may hold "] "
ATT_DEFAULT = "Have a look at the attachment."
IMAGE_EXT = (".jpg", ".jpeg", ".png", ".gif", ".webp")
# words that came by voice (pultd.hear_message): Claude is told so — misheard words are to be expected; people
# see 🎤 before the text instead
VOICE_MARK = "\n\n[Spoken message, transcribed automatically; some words may be misheard]"
_VOICE = re.compile(r"[ \n]*\[Spoken message, transcribed automatically; some words may be misheard\]")


def spoken_body(text):
    """The owner's words from a recording, as Claude gets them."""
    return str(text or "").rstrip() + VOICE_MARK


def is_spoken(text):
    return bool(_VOICE.search(str(text or "")))


def attachments(text):
    """The owner's text → (the text without attachment and voice markers, [paths])."""
    text = _VOICE.sub("", str(text or ""))
    paths = _ATT.findall(text)
    clean = _ATT.sub("", text).strip()
    return ("" if clean == ATT_DEFAULT and paths else clean), paths


def is_image(path):
    return str(path).lower().endswith(IMAGE_EXT)


def prompt_text(text):
    """The owner's prompt for a person: "deploy it 📎 picture" — the path is for Claude; "🎤 deploy it" — said aloud."""
    clean, paths = attachments(text)
    marks = " ".join(T("att.image" if is_image(p) else "att.file") for p in paths)
    out = (clean + " " + marks).strip() if marks else clean
    return ("🎤 " + out).strip() if is_spoken(text) else out


def steps_word(n):
    return "%d %s" % (n, I.plural(n, "step"))


def lines_word(n):
    return "%d %s" % (n, I.plural(n, "line"))


# ---------- Claude's background tasks ----------

_TASK_NOTE = re.compile(r"<task-notification>(.*?)</task-notification>", re.S)
# a subagent that hands its report back itself (SubagentHandback) starts the turn with it, before its
# task-notification: <agent-message from="id">; the transcript keeps it as "Another Claude session sent a message: …"
# with origin peer (a real session 2026-10-20, Claude Code 2.1.300); the hook's text is not seen yet — both forms
_AGENT_MSG = re.compile(r'(?:Another Claude session sent a message:\s*)?<agent-message from="([^"]*)"')
_TASK_END = ("completed", "failed", "stopped", "killed")


def _tag(block, name):
    m = re.search(r"<%s>(.*?)</%s>" % (name, name), block, re.S)
    return m.group(1).strip() if m else ""


def _names(items, n):
    out = ", ".join(I.q(x) for x in items[:n])
    return out + (T("and_more", n=len(items) - n) if len(items) > n else "")


def task_notes(prompt):
    """A turn Claude Code started by itself because a background task ended: the “prompt” is then a set of
    <task-notification> blocks with task-id, status, summary (probe 2026-10-16, Claude Code 2.1.301), or a subagent's
    own report, <agent-message> ("what" is then empty: the task's description is the caller's to find).
    → [{id, status, what}]; for a prompt typed by a person — []."""
    m = _AGENT_MSG.match(str(prompt or "").lstrip())
    if m:
        return [{"id": m.group(1), "status": "completed", "what": ""}]
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
    s = re.sub(r"\[([^\]\n]+)\]\((https?://[^\s)]+)\)", lambda m: hold(link(m.group(1), m.group(2))), s)
    # a link to a project file [name](path) won't open in Telegram — keep the name and the path as code
    s = re.sub(r"\[([^\]\n]+)\]\(([^\s)]+)\)",
               lambda m: hold("<code>%s</code>" % html.escape(m.group(2)) if m.group(1) == m.group(2)
                              or m.group(2).endswith("/" + m.group(1))
                              else "%s (<code>%s</code>)" % (html.escape(m.group(1)), html.escape(m.group(2)))), s)
    s = html.escape(s, quote=False)
    s = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", s)
    s = re.sub(r"(?<![\w*])\*(?!\s)([^*\n]+?)(?<!\s)\*(?![\w*])", r"<i>\1</i>", s)
    return re.sub(r"\x00(\d+)\x00", lambda m: keep[int(m.group(1))], s)


def _is_table(block):
    rows = [r for r in block.strip("\n").split("\n") if r.strip()]
    return len(rows) >= 2 and all(r.lstrip().startswith("|") for r in rows)


# Telegram's six topic icon colours (createForumTopic); the app shows a project's tile in the same one (app.js hue)
TOPIC_COLORS = (0x6FB9F0, 0xFFD67E, 0xCB86DB, 0x8EEE98, 0xFF93B2, 0xFB6F5F)


def topic_color(name):
    """A project's colour by its name: the same sum over the UTF-8 bytes as the app's hue(), so a new topic's icon and
    the project's tile in the app match."""
    h = 0
    for b in str(name).encode("utf-8"):
        h = (h * 31 + b) & 0xFFFFFFFF
    return TOPIC_COLORS[h % len(TOPIC_COLORS)]


FOLD_FROM = 700     # a result longer than this (markdown characters) folds: its beginning shows, the rest opens with a tap
FOLD_LEAD = 320     # the beginning: whole paragraphs up to about this much


def folded_html(md):
    """A reply for Telegram: short — as it is; longer — its first paragraphs, the rest in a folded quote that opens
    with a tap. Code, links and code blocks stay inside it: Telegram keeps them there (tests/probe_quote.py,
    2026-10-23 — the Bot API's own rules say it wouldn't). A code block is never cut: it folds whole."""
    md = (md or "").strip()
    if len(md) <= FOLD_FROM:
        return md_to_html(md)
    blocks = []
    for b in re.split(r"(```.*?```)", md, flags=re.S):
        if b.startswith("```") and b.endswith("```") and len(b) >= 6:
            blocks.append(b)
        else:
            blocks.extend(x.strip("\n") for x in b.split("\n\n") if x.strip())
    lead, n = [], 0
    for b in blocks:
        if b.startswith("```") or (lead and (n + len(b) > FOLD_LEAD and n >= 120)):
            break                                   # a code block folds whole; a lone heading takes the next paragraph
        if len(b) > FOLD_FROM:                      # one long paragraph: its beginning, to a line or a sentence
            cut = max(b.rfind("\n", 0, FOLD_LEAD), b.rfind(". ", 0, FOLD_LEAD) + 1)
            cut = cut if cut > FOLD_LEAD // 3 else FOLD_LEAD
            lead.append(b[:cut].rstrip())
            blocks = blocks[:len(lead) - 1] + [b[:cut].rstrip(), b[cut:].lstrip()] + blocks[len(lead):]
            break
        lead.append(b)
        n += len(b)
    rest = "\n\n".join(blocks[len(lead):]).strip()
    if not rest:
        return md_to_html(md)
    head = md_to_html("\n\n".join(lead)).rstrip("\n")
    return (head + "\n" if head else "") + "<blockquote expandable>" + md_to_html(rest).strip("\n") + "</blockquote>"


def permission_line(tool, inp, cwd=None):
    """A decided request in one line: what Claude wanted, without the command's full text (it was shown while it
    waited); a command without a description gets its beginning."""
    first = permission_text(tool, inp, cwd).split("\n", 1)[0]
    inp = inp if isinstance(inp, dict) else {}
    if tool == "Bash" and not inp.get("description") and inp.get("command"):
        first += " <code>%s</code>" % esc(short(str(inp.get("command")), 80))
    return first


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


_ENTITY_TAGS = {"bold": "b", "italic": "i", "underline": "u", "strikethrough": "s", "spoiler": "tg-spoiler",
                "code": "code", "pre": "pre", "blockquote": "blockquote", "expandable_blockquote": "blockquote"}


def entities_html(text, entities):
    """A message as Telegram hands it back (text and entities, offsets in UTF-16 units) → the HTML it was sent as,
    to edit the message without losing its formatting. Links Telegram finds by itself (url, mention) stay text."""
    u = str(text or "").encode("utf-16-le")
    opens, closes = {}, {}
    for k, e in enumerate(entities or []):
        kind = e.get("type")
        if kind == "text_link":
            tag, attr = "a", ' href="%s"' % html.escape(e.get("url") or "", quote=True)
        elif kind in _ENTITY_TAGS:
            tag = _ENTITY_TAGS[kind]
            attr = " expandable" if kind == "expandable_blockquote" else ""
        else:
            continue
        start, n = e.get("offset", 0), e.get("length", 0)
        if n <= 0:
            continue
        lang = e.get("language") if kind == "pre" else None
        o, c = "<%s%s>" % (tag, attr), "</%s>" % tag
        if lang:
            o, c = o + '<code class="language-%s">' % html.escape(lang, quote=True), "</code>" + c
        opens.setdefault(start, []).append((-n, k, o))            # the outer one opens first…
        closes.setdefault(start + n, []).append((n, -k, c))       # …and closes last
    out, last = [], 0
    for p in sorted(set(opens) | set(closes)):
        out.append(esc(u[2 * last:2 * p].decode("utf-16-le")))
        out += [c for *_, c in sorted(closes.get(p, []))] + [o for *_, o in sorted(opens.get(p, []))]
        last = p
    out.append(esc(u[2 * last:].decode("utf-16-le")))
    return "".join(out)


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

def under(path, root):
    """The rest of path inside the folder root, or None. Windows: either slash, any case."""
    if not root:
        return None
    if os.name == "nt":
        p, r = path.replace("/", "\\"), root.replace("/", "\\").rstrip("\\")
        return path[len(r) + 1:] if p.lower().startswith(r.lower() + "\\") else None
    r = root.rstrip("/")
    return path[len(r) + 1:] if path.startswith(r + "/") else None


def _rel(path, cwd):
    path = str(path or "")
    rest = under(path, cwd)
    if rest is not None:
        return rest
    rest = under(path, os.path.expanduser("~"))
    return "~" + os.sep + rest if rest is not None else path


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
