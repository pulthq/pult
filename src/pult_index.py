"""Pult: search over everything (stage И, step И1 — by words; the owner's request of 2026-11-05, Q187). An index of
what the owner and the models said in the projects' tasks, and of the projects' documents: SQLite FTS5 with trigrams —
a substring, case aside, in any language — in its own database, search.db, next to state.db.

Two sides in one module. The indexer is a child process of the daemon at a low priority (`python pult_index.py serve`):
every CYCLE it reads what is new — a transcript from where it stopped, a document again when its size or time changed —
and cleans secrets out before anything is written. What to read the daemon tells it in search-what.json; the child
ends with the daemon (its stdin closes). The daemon asks the index itself (`find`): a read-only connection in a thread.

What counts: the owner's prompts and the models' replies (Claude Code, other vendors in their own homes, Codex tasks
Pult runs); `.md`, `.txt`, `.html` files in the projects' folders. Not: what commands printed, Claude Code's own
records (meta, compacted summaries, subagents' chats), PDFs, pictures, code. Measured on the owner's Mac 2026-11-13:
249 tasks, 3.7 GB of transcripts with 24 MB of words in them; about 45 MB of text in documents."""
import html as H
import json
import os
import re
import sqlite3
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

DB_NAME = "search.db"
WHAT_NAME = "search-what.json"
CYCLE = 20                     # s between looks for what is new
DOCS_EVERY = 600               # s between walks through the projects' folders
DOC_EXT = (".md", ".markdown", ".txt", ".html", ".htm")
DOC_MAX = 2 * 1024 * 1024      # a bigger document is a dump or a page of pictures, not something one wrote
DOC_DIRS_MAX = 20000           # folders walked in one project at most: a project with a data dump inside stays cheap
CHUNK = 1200                   # characters of a document in one place
TEXT_MAX = 64 * 1024           # a message longer than this is kept by its beginning
READ_MAX = 32 * 1024 * 1024    # bytes of one transcript read in one go; the rest comes on the next round
COMMIT_EVERY = 2.0             # s of work between commits: readers see progress, a write never holds long
RECYCLE_AT = 2000              # places added or dropped in a round, after which the child starts itself anew (exec)
LOG_AT = 200                   # places added or dropped in a round worth a line in the daemon's journal
FIND_ROWS = 600                # places of what was said one search reads at most
FIND_DOCS = 200                # … and of the documents
GROUP_PLACES = 20              # places shown in one task
SKIP_DIRS = {"node_modules", "venv", "__pycache__", "site-packages", "dist", "build", "target", "vendor", "Pods",
             "DerivedData", "bower_components", "coverage", ".git"}

SCHEMA = """
CREATE TABLE IF NOT EXISTS files(id INTEGER PRIMARY KEY, path TEXT UNIQUE NOT NULL, kind TEXT NOT NULL, sid TEXT,
  pkey TEXT, size INTEGER NOT NULL DEFAULT 0, mtime REAL NOT NULL DEFAULT 0, done INTEGER NOT NULL DEFAULT 0,
  ctitle TEXT, atitle TEXT, first TEXT);
CREATE TABLE IF NOT EXISTS places(id INTEGER PRIMARY KEY, fid INTEGER NOT NULL, at INTEGER NOT NULL, who TEXT NOT NULL,
  ts REAL, text TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS places_fid ON places(fid);
CREATE TABLE IF NOT EXISTS meta(k TEXT PRIMARY KEY, v TEXT);
"""
# contentless: the words themselves are kept once, in places.text — the index holds only the trigrams
WORDS = "CREATE VIRTUAL TABLE IF NOT EXISTS words USING fts5(text, tokenize='trigram', content='')"
SCHEMA_V = 1                   # PRAGMA user_version: another one — the index is built anew (it holds nothing of its own)

# secrets are cleaned out before anything is written (the patterns the search's prototype used)
SECRET = "[secret]"
SECRETS = [
    (re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", re.S), SECRET),
    (re.compile(r"\bsk-(?:ant-|proj-)?[A-Za-z0-9_\-]{20,}"), SECRET),
    (re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}"), SECRET),
    (re.compile(r"\bgithub_pat_[A-Za-z0-9_]{30,}"), SECRET),
    (re.compile(r"\b\d{8,12}:[A-Za-z0-9_\-]{35}\b"), SECRET),               # a Telegram bot's token
    (re.compile(r"\bxox[abprs]-[A-Za-z0-9\-]{10,}"), SECRET),
    (re.compile(r"\bAKIA[0-9A-Z]{16}\b"), SECRET),
    (re.compile(r"\bAIza[0-9A-Za-z_\-]{35}\b"), SECRET),
    (re.compile(r"\bgsk_[A-Za-z0-9]{20,}"), SECRET),                         # a Groq key (voice)
    (re.compile(r"(://[^/\s:@]+:)[^/\s@]+(@)"), r"\1" + SECRET + r"\2"),     # a password in an address user:pass@host
    (re.compile(r"(?i)\b(password|passwd|pwd|secret|token|api[_-]?key|пароль)(\s*[=:]\s*)[\"']?([^\s\"']{6,})"),
     r"\1\2" + SECRET),
]


def unsecret(text):
    for rx, rep in SECRETS:
        text = rx.sub(rep, text)
    return text


def fold(text):
    """What the index and a query are compared by: ё as е (the trigrams are case-free already)."""
    return text.replace("ё", "е").replace("Ё", "Е")


def log(*a):
    print("search:", *a, file=sys.stderr, flush=True)


def stamp(ts):
    """A transcript's ISO time → seconds; None when there is none."""
    if not isinstance(ts, str) or not ts:
        return None
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def has_fts():
    """Whether this Python's SQLite has FTS5 with trigrams (3.34 and newer, built with FTS5) — without them the
    search reads titles alone, as before."""
    try:
        db = sqlite3.connect(":memory:")
        db.execute("CREATE VIRTUAL TABLE t USING fts5(x, tokenize='trigram', content='')")
        db.close()
        return True
    except sqlite3.Error:
        return False


# ---------- what a transcript says ----------

def _web():
    import pult_web
    return pult_web


def cc_said(line):
    """One line of a Claude Code transcript → (who, text, ts) — "me" for the owner's prompt, "ai" for the model's words —
    or None for the rest: steps and what they printed, Claude Code's own records, a subagent's chat, a background
    task's notice. A prompt sent in the middle of a turn is kept as an attachment: it counts as the owner's."""
    try:
        e = json.loads(line)
    except ValueError:
        return None
    if not isinstance(e, dict):
        return None
    W = _web()
    kind = e.get("type")
    if kind in ("custom-title", "ai-title"):          # the task's name: the owner's own, or the one Claude Code gave
        text = str(e.get("customTitle") or e.get("aiTitle") or "").strip()
        return (kind, text, None) if text else None
    if kind == "attachment":
        att = e.get("attachment") if isinstance(e.get("attachment"), dict) else {}
        origin = att.get("origin")
        if att.get("type") == "queued_command" and att.get("commandMode", "prompt") == "prompt" \
                and (origin is None or isinstance(origin, dict) and origin.get("kind") == "human"):
            text = W.user_text(att.get("prompt"))
            if text and not W.R.task_notes(text):
                return "me", text, stamp(e.get("timestamp"))
        return None
    if kind not in ("user", "assistant") or e.get("isSidechain") or e.get("isMeta") or e.get("isCompactSummary"):
        return None
    content = (e.get("message") or {}).get("content")
    if kind == "user":
        text = W.user_text(content)
        if not text or text.startswith("<local-command-") or text.startswith("<command-") or W.R.task_notes(text):
            return None
        return "me", text, stamp(e.get("timestamp"))
    if isinstance(content, str):
        text = content.strip()
    else:
        text = "\n".join(b.get("text") or "" for b in content or [] if isinstance(b, dict) and b.get("type") == "text").strip()
    return ("ai", text, stamp(e.get("timestamp"))) if text else None


def cx_said(line):
    """One line of a Codex task's history → (who, text, ts) or None — the owner's and Codex's words (pult_web._cx_said)."""
    try:
        e = json.loads(line)
    except ValueError:
        return None
    if not isinstance(e, dict):
        return None
    p = e.get("payload") if isinstance(e.get("payload"), dict) else {}
    who, text = _web()._cx_said(e.get("type"), p.get("type"), p)
    if who not in ("user", "codex") or not (text or "").strip():
        return None
    return ("me" if who == "user" else "ai"), text.strip(), stamp(e.get("timestamp"))


_STR_CONTENT = re.compile(rb'"content":\s?"')       # a prompt as a plain string


def chat_places(path, start, said, names=None):
    """What a transcript says from byte `start` on, whole lines only, about READ_MAX bytes at most: [(at, who, ts,
    text)] and where to go on from. A line not finished yet is left for the next round. Read line by line: a read of
    32 MB cut into lines left the child at 865 MB on the owner's Mac — the allocator kept the thousands of freed
    pieces (2026-11-13); one line at a time reuses the same memory. `names` (a dict) gets the task's names met on
    the way: custom-title, ai-title (the latest of each) and its first prompt."""
    out, at, prev = [], start, None
    names = {} if names is None else names
    with open(path, "rb") as f:
        f.seek(start)
        for line in f:
            if not line.endswith(b"\n"):
                break                                  # not finished yet: the next round
            here, at = at, at + len(line)
            # cheap first: a Claude Code line with no words in it isn't parsed — most of a transcript is what steps
            # printed, and a line with a step's result carries no words (none of 33 778 on the owner's Mac,
            # 2026-11-13); Codex's histories are small and keep words under several names
            if said is cc_said and (b'"tool_use_id"' in line or b'"text"' not in line and b"queued_command" not in line
                                    and b'Title"' not in line and not _STR_CONTENT.search(line)):
                pass
            else:
                got = said(line)
                if got and got[0] in ("custom-title", "ai-title"):
                    names[got[0]] = unsecret(got[1][:200])
                elif got and prev != got[:2]:            # Codex writes the same words in two records
                    who, text, ts = got
                    prev = (who, text)
                    if who == "me" and "first" not in names:
                        names["first"] = unsecret(text[:200])
                    out.append((here, who, ts, unsecret(text[:TEXT_MAX])))
            if at - start >= READ_MAX:
                break
    return out, at


# ---------- what a document says ----------

_SCRIPT = re.compile(r"<\s*(script|style|svg|noscript)\b", re.I)


def html_lines(text):
    """A page's text line by line, its own line numbers kept (the app opens the page at the line): no tags, no
    scripts, styles or drawings, the entities undone."""
    out, skip, in_tag = [], None, False
    for line in text.split("\n"):
        i, res, low = 0, [], None
        while i < len(line):
            if skip:
                low = low or line.lower()
                j = low.find("</" + skip, i)
                if j < 0:
                    break
                k = line.find(">", j)
                i, skip = (k + 1 if k >= 0 else len(line)), None
                continue
            if in_tag:
                k = line.find(">", i)
                if k < 0:
                    break
                i, in_tag = k + 1, False
                continue
            j = line.find("<", i)
            if j < 0:
                res.append(line[i:])
                break
            res.append(line[i:j])
            m = _SCRIPT.match(line, j)
            if m:
                skip = m.group(1).lower()
            k = line.find(">", j)
            if k < 0:
                in_tag = not skip
                break
            i = k + 1
        out.append(H.unescape(" ".join(res)).strip())
    return out


def doc_places(path):
    """A document's places: [(line, "doc", mtime, text)] — lines gathered up to CHUNK characters each, a place's
    number is its first line's. Not text (a zero byte) — none."""
    with open(path, "rb") as f:
        data = f.read(DOC_MAX + 1)
    if len(data) > DOC_MAX or b"\x00" in data[:8192]:
        return []
    text = data.decode("utf-8", "replace")
    lines = html_lines(text) if path.lower().endswith((".html", ".htm")) else text.split("\n")
    mtime = os.path.getmtime(path)
    out, buf, first, size = [], [], 0, 0
    for n, line in enumerate(lines, 1):
        s = line.strip()
        if not s:
            continue
        if not buf:
            first = n
        buf.append(s)
        size += len(s) + 1
        if size >= CHUNK:
            out.append((first, "doc", mtime, unsecret("\n".join(buf))))
            buf, size = [], 0
    if buf:
        out.append((first, "doc", mtime, unsecret("\n".join(buf))))
    return out


def secret_like(rel):
    import pult_files
    return pult_files.secret_like(rel)


def project_docs(root):
    """The documents of a project's folder: (path, size, mtime) — without hidden folders, dependencies and builds,
    without what looks like keys or settings (Telegram's rule: pult_files.secret_like)."""
    out, dirs = [], 0
    for top, ds, fs in os.walk(root):
        dirs += 1
        if dirs > DOC_DIRS_MAX:
            break
        ds[:] = [d for d in ds if not d.startswith(".") and d not in SKIP_DIRS and not d.endswith(".egg-info")]
        for name in fs:
            if not name.lower().endswith(DOC_EXT) or name.startswith("."):
                continue
            p = os.path.join(top, name)
            try:
                st = os.stat(p)
            except OSError:
                continue
            if 0 < st.st_size <= DOC_MAX and not secret_like(os.path.relpath(p, root)):
                out.append((p, st.st_size, st.st_mtime))
    return out


# ---------- the index ----------

def open_db(path, ro=False):
    if ro:
        db = sqlite3.connect("file:%s?mode=ro" % path, uri=True, timeout=5)
    else:
        db = sqlite3.connect(str(path), timeout=30)
        db.execute("PRAGMA journal_mode=WAL")
        if db.execute("PRAGMA user_version").fetchone()[0] != SCHEMA_V:
            for t in ("words", "places", "files", "meta"):
                db.execute("DROP TABLE IF EXISTS " + t)
            db.execute("PRAGMA user_version=%d" % SCHEMA_V)
        db.executescript(SCHEMA)
        db.execute(WORDS)
        db.commit()
    db.row_factory = sqlite3.Row
    return db


def meta_get(db, k, default=None):
    r = db.execute("SELECT v FROM meta WHERE k=?", (k,)).fetchone()
    return json.loads(r["v"]) if r else default


def meta_put(db, k, v):
    db.execute("INSERT OR REPLACE INTO meta VALUES(?,?)", (k, json.dumps(v)))


def drop_places(db, fid):
    """A file's places out of the index: a contentless index is told each row's own words (the 'delete' command)."""
    rows = db.execute("SELECT id, text FROM places WHERE fid=?", (fid,)).fetchall()
    db.executemany("INSERT INTO words(words, rowid, text) VALUES('delete', ?, ?)", [(r["id"], fold(r["text"])) for r in rows])
    db.execute("DELETE FROM places WHERE fid=?", (fid,))
    return len(rows)


def add_places(db, fid, places):
    for at, who, ts, text in places:
        cur = db.execute("INSERT INTO places(fid, at, who, ts, text) VALUES(?,?,?,?,?)", (fid, at, who, ts, text))
        db.execute("INSERT INTO words(rowid, text) VALUES(?, ?)", (cur.lastrowid, fold(text)))
    return len(places)


class Indexer:
    """The child process's work: rounds over what the daemon names, each reading only what is new."""

    def __init__(self, home):
        self.home = Path(home)
        self.db = open_db(self.home / DB_NAME)
        self.docs_at = 0.0
        self.what_mt = None
        self.what = None

    def load_what(self):
        p = self.home / WHAT_NAME
        try:
            mt = p.stat().st_mtime
            if mt != self.what_mt:
                self.what = json.loads(p.read_text(encoding="utf-8"))
                self.what_mt = mt
        except (OSError, ValueError):
            pass
        return self.what

    def files(self, what, docs):
        """Everything to look at in this round: (kind, path, sid, pkey)."""
        out = []
        for pr in what.get("projects") or []:
            pkey = pr.get("pkey")
            if not pkey:
                continue
            for root in what.get("roots") or []:
                d = Path(root) / pkey
                if d.is_dir():
                    out += [("cc", str(f), f.stem, pkey) for f in sorted(d.glob("*.jsonl"))]
            if docs and pr.get("path") and os.path.isdir(pr["path"]):
                out += [("doc", p, None, pkey) for p, _, _ in project_docs(pr["path"])]
        for cx in what.get("codex") or []:
            if cx.get("path") and cx.get("sid"):
                out.append(("cx", cx["path"], cx["sid"], cx.get("pkey")))
        return out

    def round(self, docs):
        """One round: new words of every transcript, changed documents (when `docs`), files gone forgotten. → the
        numbers of places added and dropped."""
        what = self.load_what()
        if not what:
            return 0, 0
        added = dropped = 0
        seen = set()
        last = time.monotonic()
        for kind, path, sid, pkey in self.files(what, docs):
            seen.add(path)
            try:
                st = os.stat(path)
            except OSError:
                continue
            row = self.db.execute("SELECT * FROM files WHERE path=?", (path,)).fetchone()
            if row is None:
                cur = self.db.execute("INSERT INTO files(path, kind, sid, pkey) VALUES(?,?,?,?)", (path, kind, sid, pkey))
                row = {"id": cur.lastrowid, "size": 0, "mtime": 0, "done": 0, "pkey": pkey, "sid": sid}
            elif row["pkey"] != pkey or row["sid"] != sid:
                self.db.execute("UPDATE files SET pkey=?, sid=? WHERE id=?", (pkey, sid, row["id"]))
            fid = row["id"]
            try:
                if kind == "doc":
                    if row["size"] == st.st_size and row["mtime"] == st.st_mtime:
                        continue
                    dropped += drop_places(self.db, fid)
                    added += add_places(self.db, fid, doc_places(path))
                    self.db.execute("UPDATE files SET size=?, mtime=?, done=? WHERE id=?", (st.st_size, st.st_mtime, st.st_size, fid))
                else:
                    done = row["done"]
                    if st.st_size < done:                     # written anew (shorter than read): from the start
                        dropped += drop_places(self.db, fid)
                        self.db.execute("UPDATE files SET ctitle=NULL, atitle=NULL, first=NULL WHERE id=?", (fid,))
                        done = 0
                    names = {}
                    while done < st.st_size:
                        places, nxt = chat_places(path, done, cc_said if kind == "cc" else cx_said, names)
                        added += add_places(self.db, fid, places)
                        if nxt == done:
                            break
                        done = nxt
                        if time.monotonic() - last > COMMIT_EVERY:
                            self.db.execute("UPDATE files SET done=? WHERE id=?", (done, fid))
                            self.db.commit()
                            last = time.monotonic()
                    self.db.execute("UPDATE files SET size=?, mtime=?, done=? WHERE id=?", (st.st_size, st.st_mtime, done, fid))
                    if names:      # a name changed later wins; the first prompt stays the first one ever read
                        self.db.execute("UPDATE files SET ctitle=coalesce(?, ctitle), atitle=coalesce(?, atitle), "
                                        "first=coalesce(first, ?) WHERE id=?",
                                        (names.get("custom-title"), names.get("ai-title"), names.get("first"), fid))
            except OSError as e:
                log("%s not read: %s" % (os.path.basename(path), e.strerror or e))
            if time.monotonic() - last > COMMIT_EVERY:
                self.db.commit()
                last = time.monotonic()
        # gone: a transcript or a document no longer named (its project left, the file deleted); documents only
        # when they were walked this round
        kinds = ("cc", "cx", "doc") if docs else ("cc", "cx")
        for r in self.db.execute("SELECT id, path, kind FROM files WHERE kind IN (%s)" % ",".join("?" * len(kinds)), kinds).fetchall():
            if r["path"] not in seen:
                dropped += drop_places(self.db, r["id"])
                self.db.execute("DELETE FROM files WHERE id=?", (r["id"],))
        self.db.commit()
        return added, dropped

    def serve(self):
        """Rounds until the daemon is gone; the numbers the app shows go to meta."""
        first = meta_get(self.db, "first_done") is None
        t0 = time.monotonic()
        while True:
            docs = time.time() - self.docs_at >= DOCS_EVERY
            try:
                added, dropped = self.round(docs)
            except sqlite3.Error as e:
                log("the round broke: %r" % e)
                time.sleep(CYCLE)
                continue
            if docs and self.what:
                self.docs_at = time.time()
            now = time.time()
            meta_put(self.db, "last", now)
            if first and self.what and docs:
                first = False
                meta_put(self.db, "first_done", now)
                n = self.db.execute("SELECT COUNT(*) FROM places").fetchone()[0]
                log("the first round: %d places in %d files, %.0f s" % (
                    n, self.db.execute("SELECT COUNT(*) FROM files").fetchone()[0], time.monotonic() - t0))
            elif added + dropped >= LOG_AT:            # a round of a turn or two stays out of the journal: one every 20 s
                log("+%d −%d places" % (added, dropped))
            self.db.commit()
            if added + dropped >= RECYCLE_AT and os.name == "posix":
                # a big round leaves the memory it freed with the allocator — 92 MB after the first one on the owner's
                # Mac, 0.1 MB of it Python's (2026-11-13); started anew it is ~30 MB. The same process: its pid, its
                # stdin from the daemon and its priority stay
                self.db.close()
                log("big round: starting anew to give its memory back")
                os.execv(sys.executable, [sys.executable] + sys.orig_argv[1:])
            time.sleep(CYCLE)


def child_main(home):
    """`pult_index.py serve`: the daemon's child. Ends when the daemon does — its stdin closes."""
    os.umask(0o077)
    if hasattr(os, "nice") and sys.platform != "darwin":   # macOS: started under taskpolicy -b (pult_os)
        try:
            os.nice(10)
        except OSError:
            pass

    def parent_gone():
        try:
            while sys.stdin.buffer.read(1024):
                pass
        except (OSError, ValueError):
            pass
        os._exit(0)
    threading.Thread(target=parent_gone, daemon=True).start()
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    log("started, pid %d" % os.getpid())
    Indexer(home).serve()


# ---------- the daemon's side: asking ----------

def words_of(q):
    """The words of a query the index can look for: three characters and more (a trigram), at most eight."""
    return [w for w in str(q or "").split() if len(w) >= 3][:8]


def _rx(words):
    parts = []
    for w in sorted(words, key=len, reverse=True):
        p = re.escape(fold(w).lower())
        parts.append(p.replace("е", "[её]"))
    return re.compile("|".join(parts), re.I)


def snippet(text, words, width=230):
    """The piece of a place around the first of the words: about `width` characters, at word edges, on one line."""
    m = _rx(words).search(text)
    i = m.start() if m else 0
    a = max(0, i - width * 2 // 5)
    b = min(len(text), a + width)
    a = max(0, min(a, b - width))
    nl = text.rfind("\n", a, i)
    if nl >= 0:                            # the line with the word from its start: a heading above it isn't glued on
        a = nl + 1
    elif a > 0:
        sp = text.find(" ", a, i) if i > a else -1
        a = sp + 1 if sp >= 0 else a
    if b < len(text):
        sp = text.rfind(" ", (m.end() if m else a) + 1, b)
        b = sp if sp > 0 else b
    out = re.sub(r"[`*#>]+", "", text[a:b])
    out = " ".join(out.split())
    return ("…" if a > 0 else "") + out + ("…" if b < len(text) else "")


def doc_line(path, line, words):
    """The line of a document where the words are, from a place's first line on — a place holds several lines, and
    the app opens the document on the one with the word. Not found (the file changed since) — the place's own line."""
    try:
        with open(path, "rb") as f:
            data = f.read(DOC_MAX + 1)
    except OSError:
        return line
    text = data.decode("utf-8", "replace")
    lines = html_lines(text) if path.lower().endswith((".html", ".htm")) else text.split("\n")
    rx = _rx(words)
    for n in range(max(1, line), len(lines) + 1):
        if rx.search(lines[n - 1]):
            return n
    return line


def find(path, words, pkey=None, mine=False, limit=FIND_ROWS, docs_limit=FIND_DOCS):
    """The index asked: places with every word, the newest first, grouped — by task (kind cc and cx: sid), by
    document (path); what was said and the documents each within a limit of its own (a hundred documents touched
    today would leave no room for the tasks). → {"tasks": [{sid, pkey, kind, title, n, places: [{at, who, ts, snip}]}],
    "docs": [{path, pkey, n, places: [{at (its line), ts, snip}]}], "more": a limit was reached}. No index or no
    words — None."""
    words = words_of(" ".join(words) if isinstance(words, (list, tuple)) else words)
    if not words or not os.path.exists(path):
        return None
    match = " AND ".join('"%s"' % fold(w).replace('"', '""') for w in words)
    sql = ("SELECT p.at, p.who, p.ts, p.text, f.kind, f.sid, f.pkey, f.path, coalesce(f.ctitle, f.atitle, f.first) AS title "
           "FROM words w JOIN places p ON p.id = w.rowid JOIN files f ON f.id = p.fid WHERE words MATCH ? AND f.kind %s 'doc'")
    args = [match]
    if pkey:
        sql += " AND f.pkey = ?"
        args.append(pkey)
    if mine:
        sql += " AND p.who = 'me'"
    sql += " ORDER BY p.ts DESC LIMIT ?"
    db = open_db(path, ro=True)
    try:
        said = db.execute(sql % "!=", args + [limit + 1]).fetchall()
        docs_rows = [] if mine else db.execute(sql % "=", args + [docs_limit + 1]).fetchall()
    except sqlite3.Error:
        return None
    finally:
        db.close()
    more = len(said) > limit or len(docs_rows) > docs_limit
    tasks, docs = {}, {}
    for r in said[:limit] + docs_rows[:docs_limit]:
        if r["kind"] == "doc":
            g = docs.setdefault(r["path"], {"path": r["path"], "pkey": r["pkey"], "n": 0, "places": []})
        else:
            g = tasks.setdefault(r["sid"], {"sid": r["sid"], "pkey": r["pkey"], "kind": r["kind"], "title": r["title"], "n": 0, "places": []})
        g["n"] += 1
        if len(g["places"]) < GROUP_PLACES:
            g["places"].append({"at": r["at"], "who": r["who"], "ts": r["ts"], "snip": snippet(r["text"], words)})
    for g in docs.values():                  # the card opens on the line with the word
        g["places"][0]["at"] = doc_line(g["path"], g["places"][0]["at"], words)
    return {"tasks": list(tasks.values()), "docs": list(docs.values()), "more": more}


def state(path):
    """What Settings → Search shows: places, files by kind, the size on disk, the last round, the first one done."""
    out = {"places": 0, "tasks": 0, "docs": 0, "size": 0, "last": None, "ready": False}
    if not os.path.exists(path):
        return out
    out["size"] = sum(os.path.getsize(str(path) + x) for x in ("", "-wal") if os.path.exists(str(path) + x))
    try:
        db = open_db(path, ro=True)
        try:
            out["places"] = db.execute("SELECT COUNT(*) FROM places").fetchone()[0]
            for kind, n in db.execute("SELECT kind, COUNT(*) FROM files GROUP BY kind"):
                out["docs" if kind == "doc" else "tasks"] += n
            out["last"] = meta_get(db, "last")
            out["ready"] = meta_get(db, "first_done") is not None
        finally:
            db.close()
    except sqlite3.Error:
        pass
    return out


def ready(path):
    """Whether the first round is done, and when the last one was: (ready, last) — for a search's answer."""
    if not os.path.exists(path):
        return False, None
    try:
        db = open_db(path, ro=True)
        try:
            return meta_get(db, "first_done") is not None, meta_get(db, "last")
        finally:
            db.close()
    except sqlite3.Error:
        return False, None


class Runner:
    """The daemon's side of the indexer: what to read written for it, the child started, looked after and stopped.
    Its lines (stderr) go to the daemon's log; a child that died is started again a little later each time."""

    def __init__(self, home, log):
        self.home = Path(home)
        self.log = log
        self.proc = None
        self.stopping = False
        self.pause = 5
        self.next_try = 0.0
        self.what = None

    def alive(self):
        return self.proc is not None and self.proc.returncode is None

    def write_what(self, what):
        """search-what.json, only when it changed (the child reads it again by its time)."""
        if what == self.what:
            return
        p = self.home / WHAT_NAME
        tmp = p.with_name(p.name + ".tmp")
        fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(what, f, ensure_ascii=False)
        os.replace(str(tmp), str(p))
        self.what = what

    async def start(self):
        import asyncio
        import pult_os
        if self.alive() or time.time() < self.next_try:
            return
        cmd, kw = pult_os.background([sys.executable, "-I", str(Path(__file__).resolve()), "serve"])
        env = dict(os.environ, PULT_HOME=str(self.home))
        self.stopping = False
        try:
            self.proc = await asyncio.create_subprocess_exec(*cmd, stdin=asyncio.subprocess.PIPE,
                                                             stdout=asyncio.subprocess.DEVNULL,
                                                             stderr=asyncio.subprocess.PIPE, env=env, **kw)
        except OSError as e:
            self.log("search: the indexer didn't start — %s" % (e.strerror or e))
            self.next_try = time.time() + self.pause
            self.pause = min(self.pause * 2, 600)
            return
        asyncio.ensure_future(self._lines(self.proc, time.time()))

    async def _lines(self, proc, t0):
        try:
            while True:
                line = await proc.stderr.readline()
                if not line:
                    break
                self.log(line.decode("utf-8", "replace").rstrip())
        except Exception:
            pass
        code = await proc.wait()
        if self.stopping:
            return
        # a child that lived long enough starts again soon; one that keeps dying waits longer each time
        self.pause = 5 if time.time() - t0 > 600 else min(self.pause * 2, 600)
        self.next_try = time.time() + self.pause
        self.log("search: the indexer ended (%s) — again in %d s" % (code, self.pause))

    async def stop(self):
        import asyncio
        proc = self.proc
        if not proc or proc.returncode is not None:
            return
        self.stopping = True
        try:
            proc.stdin.close()
        except Exception:
            pass
        try:
            await asyncio.wait_for(proc.wait(), 5)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()


def remove(home):
    """The index gone, its files too (Search off, "Build again")."""
    for x in ("", "-wal", "-shm", "-journal"):
        try:
            os.remove(str(Path(home) / DB_NAME) + x)
        except OSError:
            pass


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "serve":
        child_main(os.environ.get("PULT_HOME") or os.path.expanduser("~/.local/share/pult"))
