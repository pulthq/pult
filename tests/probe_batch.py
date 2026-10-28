"""Probe: how the small model sorts a real project's earlier tasks in a batch (stage T, T2: Q93, "Sort them again") —
on the owner's subscription, haiku: the latest BATCH sessions of a project folder (the SDK's list: the title, the first
request; the last thing Claude said, from the transcript's end), first into the project's list as Pult keeps it (read
from Pult's state, read-only), then into a new list made the way "Sort them again" makes it. Prints each task's title
and its tags, the time and the tokens — to judge by eye how many would need correcting. Touches nothing of Pult.
  ~/.local/share/pult/venv/bin/python tests/probe_batch.py [project_folder] [en]"""
import asyncio, json, os, sqlite3, sys, tempfile, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
import pult_tags as G  # noqa: E402

FOLDER = os.path.realpath(sys.argv[1] if len(sys.argv) > 1 and not sys.argv[1] in ("ru", "en") else str(Path(__file__).resolve().parent.parent))
LANG = "en" if "en" in sys.argv[1:] else "ru"
STATE = Path.home() / ".local/share/pult/state.db"
PROJECTS = Path.home() / ".claude/projects"


def pkey_of(path):
    return "".join(c if c.isalnum() else "-" for c in path)


def said(sid, pkey):
    """The last thing Claude said in the session — from its transcript's end, as the daemon reads it."""
    f = PROJECTS / pkey / (sid + ".jsonl")
    try:
        with open(f, "rb") as h:
            h.seek(0, 2)
            h.seek(max(0, h.tell() - G.SAID_TAIL))
            data = h.read()
    except OSError:
        return ""
    for line in reversed(data.split(b"\n")):
        if b'"assistant"' not in line:
            continue
        try:
            e = json.loads(line)
        except ValueError:
            continue
        content = (e.get("message") or {}).get("content")
        text = content if isinstance(content, str) else "\n".join(
            b.get("text", "") for b in content or [] if isinstance(b, dict) and b.get("type") == "text")
        if e.get("type") == "assistant" and not e.get("isSidechain") and text.strip():
            return text
    return ""


def vocab(pkey):
    """The project's list as Pult keeps it — Store.tag_vocab, read-only."""
    try:
        db = sqlite3.connect("file:%s?mode=ro" % STATE, uri=True)
    except sqlite3.Error:
        return []
    secs = [{"n": n, "c": c, "own": bool(o), "topics": []} for n, c, o in
            db.execute("SELECT name, color, own FROM tag_secs WHERE pkey=? ORDER BY color, ts", (pkey,))]
    by = {s["n"]: s for s in secs}
    for sec, n, o in db.execute("SELECT sec, name, own FROM tag_topics WHERE pkey=? ORDER BY ts, name", (pkey,)):
        if sec in by:
            by[sec]["topics"].append({"n": n, "own": bool(o)})
    return secs


async def call(text, system, schema):
    from claude_agent_sdk import ResultMessage, query
    t0, res = time.monotonic(), None
    async for m in query(prompt=text, options=G.options(LANG, Path(tempfile.mkdtemp(prefix="pult-probe-batch-")), system, schema)):
        if isinstance(m, ResultMessage):
            res = m
    u = getattr(res, "usage", None) or {}
    print("  %.1f s  in %s (cache %s) out %s" % (time.monotonic() - t0, u.get("input_tokens"), u.get("cache_read_input_tokens"),
                                                 u.get("output_tokens")))
    return getattr(res, "structured_output", None)


async def main():
    from claude_agent_sdk import list_sessions
    pkey, name = pkey_of(FOLDER), os.path.basename(FOLDER)
    items = list_sessions(FOLDER, G.LIST_TASKS)
    batch = items[:G.BATCH]
    tasks = [{"id": str(i + 1), "title": x.custom_title or x.summary or x.first_prompt or "", "ask": x.first_prompt or "",
              "said": said(x.session_id, pkey)} for i, x in enumerate(batch)]
    v = vocab(pkey)
    print("%s: %d sessions, a batch of %d; Pult's list: %s" % (name, len(items), len(tasks), G.vocab_text(v).replace("\n", " | ")))
    sysb = G.BATCH_SYSTEM.format(lang=G.LANGS[LANG], sec_max=G.SEC_MAX)
    print("\n1. Into the list as it is:")
    got1 = G.batch_tags(await call(G.batch_request(name, v, tasks, G.hints(FOLDER) if len(v) < G.HINT_UNDER else []),
                                   sysb, G.BATCH_SCHEMA), {t["id"] for t in tasks})
    print("\n2. A new list (Sort them again):")
    docs = []
    for f in ("README.md", "CLAUDE.md"):
        try:
            docs.append(open(os.path.join(FOLDER, f), encoding="utf-8", errors="replace").read(G.DOC_LEN))
        except OSError:
            docs.append("")
    own = [{"n": s["n"], "topics": [t for t in s["topics"] if t["own"]]} for s in v if s["own"] or any(t["own"] for t in s["topics"])]
    titles = [x.custom_title or x.summary or x.first_prompt for x in items if x.custom_title or x.summary or x.first_prompt]
    new = G.new_list(await call(G.list_request(name, docs[0], docs[1], titles, own, G.hints(FOLDER)),
                                G.LIST_SYSTEM.format(lang=G.LANGS[LANG], sec_max=G.SEC_MAX, topic_max=G.TOPIC_MAX), G.LIST_SCHEMA))
    for sec, tops in new:
        print("   %s: %s" % (sec, ", ".join(tops)))
    v2 = [{"n": sec, "c": i, "topics": [{"n": t} for t in tops]} for i, (sec, tops) in enumerate(new)]
    got2 = G.batch_tags(await call(G.batch_request(name, v2, tasks), sysb, G.BATCH_SCHEMA), {t["id"] for t in tasks})
    print("\n%-56s %-34s %s" % ("task", "1. the list as it is", "2. a new list"))
    tag = lambda g: (g["sec"] + (" / " + g["topic"] if g.get("topic") else "")) if g else "—"
    for t in tasks:
        print("%-56s %-34s %s" % (G.clip(t["title"], 55), tag(got1.get(t["id"])), tag(got2.get(t["id"]))))


asyncio.run(main())
