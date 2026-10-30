"""Pult's line to Telegram and its memory, out of pultd.py unchanged (review 2026-10-27, 6.2): the Bot API client
(through the proxy first, directly when that fails), the queue every message to the group goes through (Telegram's
limits), and the state database — topics, sessions, the group's messages, the usage log, turns with files, task tags.

pultd imports the classes by name: pultd.Tg, pultd.Store and the rest stay what the tests and the stand use.
"""
import asyncio
import contextlib
import json
import sqlite3
import time

import httpx

import pult_tags as G

TURNS_KEPT = 50                 # turns with files kept per session (stage F4)


def log(*a):
    print(time.strftime("%Y-%m-%d %H:%M:%S"), *a, flush=True)      # as pultd.log: the daemon's journal, the same form


# ---------- Telegram ----------

class TgError(Exception):
    def __init__(self, method, desc, code=None, retry_after=None):
        super().__init__("%s: %s" % (method, desc))
        self.desc = str(desc or "")
        self.code = code
        self.retry_after = retry_after


class Tg:
    """Bot API. Through the proxy first if one is set (PULT_PROXY); if that fails, directly (and back again)."""

    def __init__(self, token, proxy=None, transport=None):
        self.base = "https://api.telegram.org/bot%s/" % token
        self.file_base = "https://api.telegram.org/file/bot%s/" % token
        t = httpx.Timeout(70, connect=10)
        if transport is not None:
            self.clients = [httpx.AsyncClient(transport=transport, timeout=t)]
        else:
            self.clients = ([httpx.AsyncClient(proxy=proxy, timeout=t)] if proxy else []) + \
                           [httpx.AsyncClient(timeout=t)]
        self.cur = 0

    async def _post(self, url, **kw):
        last = None
        for k in range(len(self.clients)):
            i = (self.cur + k) % len(self.clients)
            try:
                r = await self.clients[i].post(url, **kw)
            except (httpx.ConnectError, httpx.ProxyError, httpx.ConnectTimeout, httpx.ReadError) as e:
                last = e
                continue
            except httpx.HTTPError as e:
                # any other failure on the way (a timeout, a broken answer): the request may have reached Telegram, so
                # it isn't tried on the other route — a message would go twice. A TgError like every other Telegram
                # failure: callers catch only that (a ReadTimeout once closed a session from Telegram, 2026-10-24)
                raise TgError(url.rsplit("/", 1)[-1], "no answer (%s)" % type(e).__name__) from None
            if i != self.cur:
                log("Telegram: route switched to", "proxy" if i == 0 and len(self.clients) > 1 else "direct")
                self.cur = i
            return r
        raise TgError(url.rsplit("/", 1)[-1], "no connection: %r" % last)

    async def call(self, method, files=None, http_timeout=None, **params):
        """A Bot API method → its result; anything else is a TgError. http_timeout is the HTTP request's own (a big
        upload); `timeout` among the params is Telegram's — getUpdates holds the request that long (long polling;
        before 0.18.5 it was taken for the HTTP one, and the daemon asked Telegram every few seconds)."""
        data = {}
        for k, v in params.items():
            if v is None:
                continue
            if isinstance(v, bool):
                v = "true" if v else "false"
            data[k] = json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else v
        r = await self._post(self.base + method, data=data, files=files,
                             timeout=http_timeout if http_timeout else httpx.USE_CLIENT_DEFAULT)
        try:
            j = r.json()
        except ValueError:
            j = None
        if not isinstance(j, dict):        # not Telegram's answer (a proxy's error page): no code — not Telegram's word
            raise TgError(method, "not a Bot API answer (HTTP %s)" % r.status_code)
        if not j.get("ok"):
            raise TgError(method, j.get("description"), j.get("error_code"),
                          (j.get("parameters") or {}).get("retry_after"))
        return j["result"]

    async def download(self, file_id):
        info = await self.call("getFile", file_id=file_id)
        for k in range(len(self.clients)):
            i = (self.cur + k) % len(self.clients)
            try:
                r = await self.clients[i].get(self.file_base + info["file_path"], timeout=180)
                r.raise_for_status()
                return info["file_path"], r.content
            except httpx.HTTPError:
                continue
        raise TgError("getFile", "download failed")


class Outbox:
    """Everything posted to the group goes through this queue: Telegram lets ~20 messages a minute into a group,
    and edits count too. Questions and results go first; turn edits go last
    and are coalesced: only the latest state of a message is sent."""

    def __init__(self, rate=18, burst=5):
        self.q = asyncio.PriorityQueue()
        self.seq = 0
        self.per = 60.0 / rate
        self.burst = burst
        self.tokens = float(burst)
        self.t = time.monotonic()
        self.pause_until = 0.0
        self.edits = {}          # message_id → edit function with the latest text

    def _put(self, prio, fn, fut):
        self.seq += 1
        self.q.put_nowait((prio, self.seq, fn, fut))

    async def submit(self, prio, fn):
        fut = asyncio.get_running_loop().create_future()
        self._put(prio, fn, fut)
        return await fut

    def edit(self, key, fn, prio=8):
        fresh = key not in self.edits
        self.edits[key] = fn
        if fresh or prio < 8:
            self._put(prio, ("edit", key), None)

    async def _token(self):
        while True:
            now = time.monotonic()
            if now < self.pause_until:
                await asyncio.sleep(self.pause_until - now)
                continue
            self.tokens = min(self.burst, self.tokens + (now - self.t) / self.per)
            self.t = now
            if self.tokens >= 1:
                self.tokens -= 1
                return
            await asyncio.sleep((1 - self.tokens) * self.per)

    async def run(self):
        while True:
            prio, seq, fn, fut = await self.q.get()
            key = None
            if isinstance(fn, tuple):
                key = fn[1]
                fn = self.edits.pop(key, None)
                if fn is None:
                    continue           # this message has already been superseded by a newer edit
            await self._token()
            try:
                res = await fn()
                if fut and not fut.done():
                    fut.set_result(res)
            except TgError as e:
                if e.retry_after:
                    log("Telegram asks to wait %s s" % e.retry_after)
                    self.pause_until = time.monotonic() + float(e.retry_after) + 0.5
                    if key is not None:
                        # by its key again: an edit of this message that comes during the pause takes its place —
                        # requeued as it was, the stale text landed over the newer one (review 2026-10-27, Я8)
                        self.edits.setdefault(key, fn)
                        self._put(prio, ("edit", key), None)
                    else:
                        self._put(prio, fn, fut)
                    continue
                if fut and not fut.done():
                    fut.set_exception(e)
                else:
                    log("Telegram:", e)
            except Exception as e:
                if fut and not fut.done():
                    fut.set_exception(e)
                else:
                    log("send failed:", repr(e))


# ---------- state ----------

SCHEMA = """
CREATE TABLE IF NOT EXISTS kv(k TEXT PRIMARY KEY, v TEXT);
CREATE TABLE IF NOT EXISTS topics(pkey TEXT PRIMARY KEY, path TEXT, name TEXT, thread INTEGER);
CREATE TABLE IF NOT EXISTS pins(pkey TEXT PRIMARY KEY, ts REAL);
CREATE TABLE IF NOT EXISTS hides(pkey TEXT PRIMARY KEY, ts REAL);
CREATE TABLE IF NOT EXISTS sessions(sid TEXT PRIMARY KEY, pkey TEXT, path TEXT, title TEXT,
    driven INTEGER DEFAULT 0, last_seen REAL);
CREATE TABLE IF NOT EXISTS msgs(msg INTEGER PRIMARY KEY, sid TEXT, kind TEXT, ts REAL);
CREATE TABLE IF NOT EXISTS usage_log(ts REAL, kind TEXT, pct REAL, resets REAL);
CREATE INDEX IF NOT EXISTS usage_log_ts ON usage_log(ts);
CREATE TABLE IF NOT EXISTS turns(id INTEGER PRIMARY KEY, sid TEXT, pkey TEXT, start REAL, ts REAL, dur REAL,
    n INTEGER, files TEXT);
CREATE INDEX IF NOT EXISTS turns_sid ON turns(sid, id);
CREATE TABLE IF NOT EXISTS tag_secs(pkey TEXT, name TEXT, color INTEGER, own INTEGER DEFAULT 0, ts REAL,
    PRIMARY KEY(pkey, name));
CREATE TABLE IF NOT EXISTS tag_topics(pkey TEXT, sec TEXT, name TEXT, own INTEGER DEFAULT 0, ts REAL,
    PRIMARY KEY(pkey, sec, name));
CREATE TABLE IF NOT EXISTS session_tags(sid TEXT PRIMARY KEY, pkey TEXT, sec TEXT, topic TEXT, own INTEGER DEFAULT 0,
    ts REAL);
CREATE TABLE IF NOT EXISTS tag_hide(pkey TEXT, sec TEXT, topic TEXT, ts REAL, PRIMARY KEY(pkey, sec, topic));
CREATE TABLE IF NOT EXISTS tag_keep(pkey TEXT, a_sec TEXT, a_topic TEXT, b_sec TEXT, b_topic TEXT, ts REAL,
    PRIMARY KEY(pkey, a_sec, a_topic, b_sec, b_topic));
CREATE TABLE IF NOT EXISTS tag_alias(pkey TEXT, old TEXT, old_topic TEXT, sec TEXT, topic TEXT, ts REAL,
    PRIMARY KEY(pkey, old, old_topic));
CREATE TABLE IF NOT EXISTS tag_examples(pkey TEXT, sid TEXT, title TEXT, ask TEXT, sec TEXT, topic TEXT, ts REAL,
    PRIMARY KEY(pkey, sid));
CREATE TABLE IF NOT EXISTS session_vendor(sid TEXT PRIMARY KEY, vendor TEXT, ts REAL);
"""
# stage T, T2: what the owner did to a project's list lives in tables of its own — the hidden tags (topic "" for a
# whole section), the pairs kept apart, the names a tag had before a rename or a merge (by pult_tags.key), the owner's
# own choices for tasks (the model's examples) — so the tables of 0.17 stay as they were and an older daemon still
# writes to them after a rollback


class Store:
    def __init__(self, path):
        self.db = sqlite3.connect(str(path), isolation_level=None)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)

    def get(self, k, default=None):
        r = self.db.execute("SELECT v FROM kv WHERE k=?", (k,)).fetchone()
        return json.loads(r["v"]) if r else default

    def put(self, k, v):
        self.db.execute("INSERT OR REPLACE INTO kv VALUES(?,?)", (k, json.dumps(v)))

    def topic(self, pkey):
        return self.db.execute("SELECT * FROM topics WHERE pkey=?", (pkey,)).fetchone()

    def topic_by_thread(self, thread):
        return self.db.execute("SELECT * FROM topics WHERE thread=?", (thread,)).fetchone()

    def set_topic(self, pkey, path, name, thread):
        self.db.execute("INSERT OR REPLACE INTO topics VALUES(?,?,?,?)", (pkey, path, name, thread))

    # ----- pinned projects (stage Zh): the owner's few on top of every list, the newest pin first (Q98) -----

    def pins(self):
        """pkey → when it was pinned."""
        return {r["pkey"]: r["ts"] for r in self.db.execute("SELECT pkey, ts FROM pins")}

    def set_pin(self, pkey, on):
        if on:
            self.db.execute("INSERT OR REPLACE INTO pins VALUES(?,?)", (pkey, time.time()))
        else:
            self.db.execute("DELETE FROM pins WHERE pkey=?", (pkey,))

    # hidden projects (stage Zh, step 2): in a fold at the bottom of Projects, off Home's board and the new task's list

    def hides(self):
        return {r["pkey"]: r["ts"] for r in self.db.execute("SELECT pkey, ts FROM hides")}

    def set_hide(self, pkey, on):
        if on:
            self.db.execute("INSERT OR REPLACE INTO hides VALUES(?,?)", (pkey, time.time()))
        else:
            self.db.execute("DELETE FROM hides WHERE pkey=?", (pkey,))

    # stage M, step 2: a session Pult runs on another vendor's model — its continuations and copies go there too

    def vendor_of(self, sid):
        r = self.db.execute("SELECT vendor FROM session_vendor WHERE sid=?", (sid,)).fetchone()
        return r["vendor"] if r else None

    def set_vendor(self, sid, vendor):
        if vendor:
            self.db.execute("INSERT OR REPLACE INTO session_vendor VALUES(?,?,?)", (sid, vendor, time.time()))
        else:
            self.db.execute("DELETE FROM session_vendor WHERE sid=?", (sid,))

    def session(self, sid):
        return self.db.execute("SELECT * FROM sessions WHERE sid=?", (sid,)).fetchone()

    def touch_session(self, sid, pkey, path=None, driven=None, title=None):
        cur = self.session(sid)
        if cur is None:
            self.db.execute("INSERT INTO sessions VALUES(?,?,?,?,?,?)",
                            (sid, pkey, path, title, int(bool(driven)), time.time()))
            return
        self.db.execute("UPDATE sessions SET pkey=?, path=coalesce(?,path), title=coalesce(?,title),"
                        " driven=max(driven,?), last_seen=? WHERE sid=?",
                        (pkey or cur["pkey"], path, title, int(bool(driven)), time.time(), sid))

    # ----- task tags (stage T, pult_tags): the project's sections and topics, and each session's two -----

    def tag_vocab(self, pkey):
        """The project's tags: [{n, c, own, ts, topics: [{n, own, ts}]}] — sections in the order they were made (c is
        that order: their colour in the app), each with its topics in theirs."""
        secs = [{"n": r["name"], "c": r["color"], "own": bool(r["own"]), "ts": r["ts"], "topics": []}
                for r in self.db.execute("SELECT * FROM tag_secs WHERE pkey=? ORDER BY color, ts", (pkey,))]
        by = {s["n"]: s for s in secs}
        for r in self.db.execute("SELECT * FROM tag_topics WHERE pkey=? ORDER BY ts, name", (pkey,)):
            if r["sec"] in by:
                by[r["sec"]]["topics"].append({"n": r["name"], "own": bool(r["own"]), "ts": r["ts"]})
        return secs

    def tag_add(self, pkey, sec, topic=None, own=False, ts=None, color=None):
        """A section, and a topic in it, into the project's list unless they are there; own — the owner picked or made
        them: they are never "new" again; color — the one a new section had before ("Sort them again"), if free."""
        ts = ts or time.time()
        if self.db.execute("SELECT 1 FROM tag_secs WHERE pkey=? AND name=?", (pkey, sec)).fetchone():
            if own:
                self.db.execute("UPDATE tag_secs SET own=1 WHERE pkey=? AND name=?", (pkey, sec))
        else:                                    # its colour: the first one no section wears (merged and gone ones free theirs)
            worn = [r[0] for r in self.db.execute("SELECT color FROM tag_secs WHERE pkey=?", (pkey,))]
            c = next((i for i in range(G.COLORS) if i not in {w % G.COLORS for w in worn}), max(worn, default=-1) + 1)
            if color is not None and color not in worn:
                c = color
            self.db.execute("INSERT INTO tag_secs VALUES(?,?,?,?,?)", (pkey, sec, c, int(own), ts))
        if not topic:
            return
        if self.db.execute("SELECT 1 FROM tag_topics WHERE pkey=? AND sec=? AND name=?", (pkey, sec, topic)).fetchone():
            if own:
                self.db.execute("UPDATE tag_topics SET own=1 WHERE pkey=? AND sec=? AND name=?", (pkey, sec, topic))
        else:
            self.db.execute("INSERT INTO tag_topics VALUES(?,?,?,?,?)", (pkey, sec, topic, int(own), ts))

    def session_tag(self, sid):
        return self.db.execute("SELECT * FROM session_tags WHERE sid=?", (sid,)).fetchone()

    def set_session_tag(self, sid, pkey, sec, topic, own, ts=None):
        """ts — when the task was last at work, for one Pult never saw (its earlier tasks get tags in batches): the
        tags screen puts first the tags of the tasks of the last 30 days."""
        self.db.execute("INSERT OR REPLACE INTO session_tags VALUES(?,?,?,?,?,?)",
                        (sid, pkey, sec, topic, int(bool(own)), ts or time.time()))

    def tag_uses(self, pkey, since=None):
        """How many sessions have each section and each topic: {(sec, None): n, (sec, topic): n}; since — only the
        sessions active since then (their last request or result; one Pult never saw — since it was tagged)."""
        out = {}
        for r in self.db.execute("SELECT t.sec, t.topic, count(*) n FROM session_tags t LEFT JOIN sessions s ON s.sid=t.sid "
                                 "WHERE t.pkey=? AND t.sec IS NOT NULL AND coalesce(s.last_seen, t.ts, 0) >= ? "
                                 "GROUP BY t.sec, t.topic", (pkey, since or 0)):
            out[(r["sec"], None)] = out.get((r["sec"], None), 0) + r["n"]
            if r["topic"]:
                out[(r["sec"], r["topic"])] = r["n"]
        return out

    # ----- the owner tidies a project's tags (stage T, T2): hides, keeps apart, renames, merges, colours -----

    @contextlib.contextmanager
    def tx(self):
        """Several statements as one: all or none."""
        self.db.execute("BEGIN")
        try:
            yield
        except BaseException:
            self.db.execute("ROLLBACK")
            raise
        self.db.execute("COMMIT")

    def tag_hidden(self, pkey):
        """What the owner hid in a project's list: {(sec, None)} for a section, {(sec, topic)} for a topic."""
        return {(r["sec"], r["topic"] or None) for r in self.db.execute("SELECT sec, topic FROM tag_hide WHERE pkey=?", (pkey,))}

    def tag_hide(self, pkey, sec, topic, on):
        if on:
            self.db.execute("INSERT OR REPLACE INTO tag_hide VALUES(?,?,?,?)", (pkey, sec, topic or "", time.time()))
        else:
            self.db.execute("DELETE FROM tag_hide WHERE pkey=? AND sec=? AND topic=?", (pkey, sec, topic or ""))

    def tag_kept(self, pkey):
        """The pairs the owner keeps apart ("Keep both"): {frozenset({(sec, topic), (sec, topic)})}, topic None for a section."""
        return {frozenset({(r["a_sec"], r["a_topic"] or None), (r["b_sec"], r["b_topic"] or None)})
                for r in self.db.execute("SELECT * FROM tag_keep WHERE pkey=?", (pkey,))}

    def tag_keep(self, pkey, a, b):
        self.db.execute("INSERT OR REPLACE INTO tag_keep VALUES(?,?,?,?,?,?)",
                        (pkey, a[0], a[1] or "", b[0], b[1] or "", time.time()))

    def tag_aliases(self, pkey):
        """The names a project's tags had before the owner renamed or merged them:
        {(key(sec), key(topic) or ""): (sec, topic or None)} — what took each one's place (pult_tags.resolve)."""
        return {(r["old"], r["old_topic"]): (r["sec"], r["topic"] or None)
                for r in self.db.execute("SELECT * FROM tag_alias WHERE pkey=?", (pkey,))}

    def tag_unalias(self, pkey, sec, topic=None):
        """A name is a tag of the project again (the owner made it): no longer an old name of another."""
        self.db.execute("DELETE FROM tag_alias WHERE pkey=? AND old=? AND old_topic=?",
                        (pkey, G.key(sec), G.key(topic) if topic else ""))

    def _alias(self, pkey, sec, topic, to_sec, to_topic):
        old = (G.key(sec), G.key(topic) if topic else "")
        if old != (G.key(to_sec), G.key(to_topic) if to_topic else ""):
            self.db.execute("INSERT OR REPLACE INTO tag_alias VALUES(?,?,?,?,?,?)",
                            (pkey, old[0], old[1], to_sec, to_topic or "", time.time()))
        self.tag_unalias(pkey, to_sec, to_topic)

    def tag_own(self, pkey, sec, topic=None):
        """The owner keeps a tag Claude has made: it is never "new" again, and stays without tasks until hidden."""
        if topic:
            self.db.execute("UPDATE tag_topics SET own=1 WHERE pkey=? AND sec=? AND name=?", (pkey, sec, topic))
        else:
            self.db.execute("UPDATE tag_secs SET own=1 WHERE pkey=? AND name=?", (pkey, sec))

    def tag_color(self, pkey, sec, c):
        self.db.execute("UPDATE tag_secs SET color=?, own=1 WHERE pkey=? AND name=?", (int(c), pkey, sec))

    def tag_rename(self, pkey, sec, topic, name):
        """The owner renames a section (topic None) or a topic: its tasks, what was hidden and kept apart go with it,
        and the old name stays as an alias — the model's or a hashtag's old word lands on the new one."""
        with self.tx():
            if topic is None:
                for q in ("UPDATE tag_secs SET name=?, own=1 WHERE pkey=? AND name=?",
                          "UPDATE tag_topics SET sec=? WHERE pkey=? AND sec=?",
                          "UPDATE session_tags SET sec=? WHERE pkey=? AND sec=?",
                          "UPDATE tag_hide SET sec=? WHERE pkey=? AND sec=?",
                          "UPDATE tag_keep SET a_sec=? WHERE pkey=? AND a_sec=?",
                          "UPDATE tag_keep SET b_sec=? WHERE pkey=? AND b_sec=?"):
                    self.db.execute(q, (name, pkey, sec))
                self._alias(pkey, sec, None, name, None)
                return
            for q in ("UPDATE tag_topics SET name=?, own=1 WHERE pkey=? AND sec=? AND name=?",
                      "UPDATE session_tags SET topic=? WHERE pkey=? AND sec=? AND topic=?",
                      "UPDATE tag_hide SET topic=? WHERE pkey=? AND sec=? AND topic=?",
                      "UPDATE tag_keep SET a_topic=? WHERE pkey=? AND a_sec=? AND a_topic=?",
                      "UPDATE tag_keep SET b_topic=? WHERE pkey=? AND b_sec=? AND b_topic=?"):
                self.db.execute(q, (name, pkey, sec, topic))
            self._alias(pkey, sec, topic, sec, name)

    def tag_merge(self, pkey, sec, topic, to_sec, to_topic=None):
        """The owner merges a section into another (topic and to_topic None) — its topics move along, one of the same
        name becomes one — or a topic into another topic, in its section or any other. The tasks move, the merged tag
        goes, its name stays as an alias; the one merged into is the owner's now."""
        with self.tx():
            if topic is None:
                into = {G.key(r["name"]): r["name"] for r in
                        self.db.execute("SELECT name FROM tag_topics WHERE pkey=? AND sec=?", (pkey, to_sec))}
                for r in self.db.execute("SELECT name FROM tag_topics WHERE pkey=? AND sec=?", (pkey, sec)).fetchall():
                    same = into.get(G.key(r["name"]))
                    if same:
                        self.db.execute("UPDATE session_tags SET sec=?, topic=? WHERE pkey=? AND sec=? AND topic=?",
                                        (to_sec, same, pkey, sec, r["name"]))
                        self.db.execute("DELETE FROM tag_topics WHERE pkey=? AND sec=? AND name=?", (pkey, sec, r["name"]))
                        self.db.execute("DELETE FROM tag_hide WHERE pkey=? AND sec=? AND topic=?", (pkey, sec, r["name"]))
                    else:
                        self.db.execute("UPDATE tag_topics SET sec=? WHERE pkey=? AND sec=? AND name=?", (to_sec, pkey, sec, r["name"]))
                        self.db.execute("UPDATE tag_hide SET sec=? WHERE pkey=? AND sec=? AND topic=?", (to_sec, pkey, sec, r["name"]))
                self.db.execute("UPDATE session_tags SET sec=? WHERE pkey=? AND sec=?", (to_sec, pkey, sec))
                self.db.execute("DELETE FROM tag_secs WHERE pkey=? AND name=?", (pkey, sec))
                self.db.execute("DELETE FROM tag_hide WHERE pkey=? AND sec=?", (pkey, sec))
                self.db.execute("DELETE FROM tag_keep WHERE pkey=? AND (a_sec=? OR b_sec=?)", (pkey, sec, sec))
                self.tag_own(pkey, to_sec)
                self._alias(pkey, sec, None, to_sec, None)
                return
            self.db.execute("UPDATE session_tags SET sec=?, topic=? WHERE pkey=? AND sec=? AND topic=?",
                            (to_sec, to_topic, pkey, sec, topic))
            self.db.execute("DELETE FROM tag_topics WHERE pkey=? AND sec=? AND name=?", (pkey, sec, topic))
            self.db.execute("DELETE FROM tag_hide WHERE pkey=? AND sec=? AND topic=?", (pkey, sec, topic))
            self.db.execute("DELETE FROM tag_keep WHERE pkey=? AND (a_sec=? AND a_topic=? OR b_sec=? AND b_topic=?)",
                            (pkey, sec, topic, sec, topic))
            self.tag_own(pkey, to_sec, to_topic)
            self._alias(pkey, sec, topic, to_sec, to_topic)

    def tag_reset(self, pkey):
        """"Sort them again" (stage T, T2): Claude's own tags in the project go — every task's the owner didn't pick, and
        each section and topic none of the owner's tags needs; the owner's stay as they are. → the colours the
        sections had, {key(name): colour}: a section the new list names again keeps its own."""
        colors = {G.key(r["name"]): r["color"] for r in self.db.execute("SELECT name, color FROM tag_secs WHERE pkey=?", (pkey,))}
        with self.tx():
            self.db.execute("DELETE FROM session_tags WHERE pkey=? AND own=0", (pkey,))
            self.tag_prune(pkey)                 # a tag of Claude's that a task of the owner's has stays
        return colors

    def tag_example(self, pkey, sid, title, ask, sec, topic=None):
        """The owner's own tags for a task — an example the model sees when it tags the project's next tasks (stage T,
        T2): a task has one, its latest; a project keeps the latest EXAMPLES_KEPT."""
        self.db.execute("INSERT OR REPLACE INTO tag_examples VALUES(?,?,?,?,?,?,?)",
                        (pkey, sid, title or "", ask or "", sec, topic or "", time.time()))
        self.db.execute("DELETE FROM tag_examples WHERE pkey=? AND sid NOT IN (SELECT sid FROM tag_examples WHERE pkey=? "
                        "ORDER BY ts DESC LIMIT ?)", (pkey, pkey, G.EXAMPLES_KEPT))

    def tag_unexample(self, pkey, sid):
        """The owner gave the task's tags back to Claude: no longer their example."""
        self.db.execute("DELETE FROM tag_examples WHERE pkey=? AND sid=?", (pkey, sid))

    def tag_examples(self, pkey, n):
        """The project's latest examples, the newest first: [{sid, title, ask, sec, topic}] — names as they were then."""
        return [{"sid": r["sid"], "title": r["title"], "ask": r["ask"], "sec": r["sec"], "topic": r["topic"] or None}
                for r in self.db.execute("SELECT * FROM tag_examples WHERE pkey=? ORDER BY ts DESC LIMIT ?", (pkey, n))]

    def tag_prune(self, pkey):
        """Tags Claude made that no task has any more go by themselves; the owner's stay until hidden."""
        self.db.execute("DELETE FROM tag_topics WHERE pkey=? AND own=0 AND NOT EXISTS (SELECT 1 FROM session_tags s "
                        "WHERE s.pkey=tag_topics.pkey AND s.sec=tag_topics.sec AND s.topic=tag_topics.name)", (pkey,))
        self.db.execute("DELETE FROM tag_secs WHERE pkey=? AND own=0 AND NOT EXISTS (SELECT 1 FROM session_tags s "
                        "WHERE s.pkey=tag_secs.pkey AND s.sec=tag_secs.name) AND NOT EXISTS (SELECT 1 FROM tag_topics t "
                        "WHERE t.pkey=tag_secs.pkey AND t.sec=tag_secs.name)", (pkey,))

    def map_msg(self, msg, sid, kind):
        self.db.execute("INSERT OR REPLACE INTO msgs VALUES(?,?,?,?)", (msg, sid, kind, time.time()))

    def msg(self, msg):
        return self.db.execute("SELECT * FROM msgs WHERE msg=?", (msg,)).fetchone()

    def log_usage(self, u):
        """Every get_usage reading, each limit: the points the spend curve passes through (stage R)."""
        rows = [(u["ts"], x["kind"], x["percent"], x["resets_at"]) for x in u.get("limits") or [] if x.get("kind")]
        self.db.executemany("INSERT INTO usage_log VALUES(?,?,?,?)", rows)

    def usage_log(self, since):
        return [tuple(r) for r in self.db.execute("SELECT ts, kind, pct, resets FROM usage_log WHERE ts >= ? ORDER BY ts", (since,))]

    def add_turn(self, sid, pkey, start, dur, files, n):
        """A turn that made or changed files (stage F4): its files stay viewable after the next turn. → its id."""
        cur = self.db.execute("INSERT INTO turns(sid, pkey, start, ts, dur, n, files) VALUES(?,?,?,?,?,?,?)",
                              (sid, pkey, start, time.time(), dur, n, json.dumps(files, ensure_ascii=False)))
        self.db.execute("DELETE FROM turns WHERE sid=? AND id NOT IN (SELECT id FROM turns WHERE sid=? ORDER BY id DESC "
                        "LIMIT ?)", (sid, sid, TURNS_KEPT))
        return cur.lastrowid

    def turn(self, sid, tid=None):
        """A session's turn with files (the latest one when tid is None), with the ids of the one before and after."""
        r = (self.db.execute("SELECT * FROM turns WHERE sid=? AND id=?", (sid, tid)) if tid is not None else
             self.db.execute("SELECT * FROM turns WHERE sid=? ORDER BY id DESC LIMIT 1", (sid,))).fetchone()
        if not r:
            return None
        near = lambda q: (self.db.execute(q, (sid, r["id"])).fetchone() or [None])[0]
        return dict(r, files=json.loads(r["files"] or "[]"),
                    prev=near("SELECT max(id) FROM turns WHERE sid=? AND id<?"),
                    next=near("SELECT min(id) FROM turns WHERE sid=? AND id>?"))

    def prune(self, days=60):
        self.db.execute("DELETE FROM msgs WHERE ts < ?", (time.time() - days * 86400,))
        self.db.execute("DELETE FROM usage_log WHERE ts < ?", (time.time() - days * 86400,))
        self.db.execute("DELETE FROM turns WHERE ts < ?", (time.time() - days * 86400,))
