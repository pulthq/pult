"""Whose move: per session, how its last turn ended and whether the owner has seen it (stage V, "Attention").

A session's move is Claude's while a turn runs or a background task will wake it, and the owner's when it waits
for an answer, failed, or ended a turn that needs them and they haven't seen it yet. Once seen, it rests: a line in
its project, no counter, no call. This module keeps what has to outlive a restart (the outcome of each session's
last turn, the "seen" mark, today's turns per project) and decides a session's state from it plus what the daemon
knows live. Standard library only. Design: docs/project.html, stage V.
"""
import time

KEEP = 3 * 86400        # s: outcomes older than this are forgotten
LOG_MAX = 300           # outcomes kept for "While you were away"
RECENT = 3 * 3600       # s: a resting session with an outcome this fresh is still shown in its project
CTX_WARN = 85           # % of the context window: time to compact or start a new session

# a session's state, in the order the owner should look at them
ORDER = {"ask": 0, "fail": 1, "you": 2, "work": 3, "bg": 4, "done": 5, "idle": 6}
MINE = ("ask", "fail", "you")          # the owner's move


def today(now=None):
    return time.strftime("%Y-%m-%d", time.localtime(now or time.time()))


class Attn:
    def __init__(self, store):
        self.store = store
        self.rec = store.get("attn") or {}       # sid → the outcome of its last turn (finished)
        self.day = store.get("attn_day") or {}   # {"d": date, "p": {pkey: [turns, seconds of work]}}
        self.log = store.get("attn_log") or []   # every outcome, oldest first: [ts, pkey, sid, line, you, fail]
        self.resume = store.get("attn_resume") or {}   # sid → when to say "continue" (after a usage limit resets)

    def save(self):
        self.store.put("attn", self.rec)
        self.store.put("attn_day", self.day)
        self.store.put("attn_log", self.log)
        self.store.put("attn_resume", self.resume)

    def finished(self, sid, pkey, dur, text, line, waits, fail=None, seen=False, now=None):
        """A turn ended. waits — nothing else runs in the session, so the next step is the owner's (the rule; the
        model may refine it with briefed); fail — the error when the turn broke off; seen — the owner watched it."""
        now = now or time.time()
        self.rec[sid] = {"pkey": pkey, "ts": now, "dur": dur, "line": line, "need": "", "you": bool(waits),
                         "fail": fail, "seen": bool(seen), "text": text, "model": False, "replies": []}
        self.log.append([now, pkey, sid, line, bool(waits), fail])
        self.resume.pop(sid, None)            # a new outcome: an old "continue after the reset" is moot
        d = today(now)
        if self.day.get("d") != d:
            self.day = {"d": d, "p": {}}
        n, secs = self.day["p"].get(pkey) or [0, 0]
        self.day["p"][pkey] = [n + 1, round(secs + max(0.0, dur or 0))]
        self.prune(now)
        self.save()
        return self.rec[sid]

    def briefed(self, sid, ts, brief, waits):
        """The model's reading of the result that ended at ts: its line, and whether Claude waits for the owner
        (only while nothing else runs — a background task means Claude goes on by itself)."""
        r = self.rec.get(sid)
        if not r or r["ts"] != ts or not brief:
            return None
        you = bool(waits and brief["you"])
        r.update(line=brief["line"], need=brief["need"] if you else "", you=you, model=True,
                 replies=(brief.get("replies") or []) if you else [])
        for e in reversed(self.log):
            if e[2] == sid and e[0] == ts:
                e[3], e[4] = r["line"], you
                break
        self.save()
        return r

    def seen(self, sid):
        """The owner saw the outcome: opened the session, answered it, dismissed it, closed the tab."""
        r = self.rec.get(sid)
        if r and not r["seen"]:
            r["seen"] = True
            self.save()
            return True
        return False

    def prune(self, now=None):
        old = (now or time.time()) - KEEP
        for sid in [s for s, r in self.rec.items() if r["ts"] < old]:
            del self.rec[sid]
        self.log = [e for e in self.log if e[0] >= old][-LOG_MAX:]

    def since(self, ts):
        """Outcomes after ts, for "While you were away": [ts, pkey, sid, line, you, fail], oldest first."""
        return [e for e in self.log if e[0] > ts]

    def day_of(self, pkey):
        """[turns, seconds of work] in the project today."""
        return (self.day.get("p") or {}).get(pkey, [0, 0]) if self.day.get("d") == today() else [0, 0]


def state(pending, working, bg, rec):
    """The session's state: ask (waits for an answer), work, bg (Claude goes on by itself after a background task),
    fail / you (ended and the owner hasn't seen it: broke off / needs them), done (ended, unseen, only a report),
    idle (rests)."""
    if pending:
        return "ask"
    if working:
        return "work"
    fresh = rec and not rec.get("seen")
    if fresh and rec.get("fail"):
        return "fail"                    # even with a background task: its turn would hit the same error
    if bg:
        return "bg"
    if fresh:
        return "you" if rec.get("you") else "done"
    return "idle"


def resting(row, now=None):
    """Folded under "+ N more resting": nothing happens and its last outcome is old (or there is none)."""
    return row["state"] == "idle" and (now or time.time()) - (row.get("ts") or 0) > RECENT


def sort_rows(rows):
    """What needs the owner first — the longest waiting on top; then work; then by recency."""
    return sorted(rows, key=lambda r: (ORDER[r["state"]], (r.get("since") or 0) if r["state"] in MINE
                                       else -(r.get("ts") or r.get("since") or 0)))


def sort_projects(projects):
    """Projects where the owner is needed first (the longest waiting), then those at work, then by recency."""
    def key(p):
        mine = [r["since"] or 0 for r in p["rows_all"] if r["state"] in MINE]
        work = any(r["state"] in ("work", "bg") for r in p["rows_all"])
        last = max([r.get("ts") or r.get("since") or 0 for r in p["rows_all"]] or [0])
        return (0 if mine else 1 if work else 2, min(mine) if mine else -last)
    return sorted(projects, key=key)
