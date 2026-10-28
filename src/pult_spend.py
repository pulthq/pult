"""Pult: how the plan's limits are spent (stage R) — for each limit the curve from its start to its reset, the even
pace, the forecast at the current pace, how many sessions worked at once and what spent it. Standard library only:
the daemon reads and counts, the app draws.

The percent is the truth: Claude Code's get_usage (whole numbers), read every 15 min while there is work and when the
app asks; every reading goes into the usage log. The transcripts on this computer give the rest — every model reply
carries its tokens (2026-10-21: the Mac's transcripts held 8416 of the week's 8560 requests). A reply weighs its
tokens at its model's API price ratios times its model's factor. Between two readings the growth is spread over the
5-minute slots in proportion to weight, so the curve passes through every reading whatever the plan's own weights
are; growth with no tokens here is "elsewhere" — another computer, the chats. Whether the plan weighs tokens the same
way is probe P1 of stage R (docs/project.html).

A session works from the owner's message to the end of its turn (the reply with stop_reason end_turn); a pause inside
a turn up to GAP is a long command, not a rest. Agents are the files in <session>/subagents/.
"""
import json
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

SLOT = 300                       # s: the finest grain of the curve and of "at once"
HORIZON = 8 * 86400              # kept: the week and the day before it (the pace of the last day)
GAP = 30 * 60                    # s: inside a turn, a pause up to this is work; a longer one is not
WRITE_5M, WRITE_1H, OUT = 1.25, 2.0, 5.0       # the API's price ratios against an input token, alike for every model,
READ = {"opus": 0.05, "fable": 0.025, "sonnet": 0.1, "haiku": 0.1, "other": 0.1}   # but a cache read's is its model's
# own: Opus 5.5 and Fable 5.1 read cheaper (the API's prices on 2026-10-28, Q95)
FAMILIES = ("opus", "fable", "sonnet", "haiku", "other")
FACTOR = {"opus": 1.0, "fable": 9.0, "sonnet": 0.6, "haiku": 0.2, "other": 1.0}   # per weight, against Opus: Fable
# fitted to its weekly share on 2026-10-28 with these read prices (8.7 with 0.1 for every model; 4.25 on 2026-10-21) and
# refitted at every reading (fit_factor); Sonnet and Haiku rough, their share is small
WINDOWS = {"session": ("h5", 5 * 3600, 300), "five_hour": ("h5", 5 * 3600, 300),
           "weekly_all": ("week", 7 * 86400, 3600), "seven_day": ("week", 7 * 86400, 3600)}   # kind → key, span, bar step
RECENT = {"h5": 3600, "week": 86400}   # the pace the forecast assumes: the last hour / the last day
PACE_LOW = 90                    # % at the reset: from here on pace, below it under (decision Q33)
PACES = (85, 90, 95)
MIN_STEP = 3                     # percentage points between two readings used for the curve: whole percents are rough
MIN_K = 3                        # % of a limit below which its own per-token rate is too rough — the stored one is used
END = ("end_turn", "stop_sequence")


def ts_of(s):
    """A transcript timestamp (UTC, 2026-10-21T20:19:29.001Z) → seconds, or None."""
    try:
        if len(s) == 24 and s.endswith("Z"):
            return datetime.fromisoformat(s[:23]).replace(tzinfo=timezone.utc).timestamp()
        return datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()
    except (TypeError, ValueError):
        return None


def family(model):
    m = (model or "").lower()
    return next((f for f in FAMILIES[:-1] if f in m), "other")


def weight_of(u, fam):
    """A reply's tokens at its model's API price ratios, in input tokens."""
    write = u.get("cache_creation_input_tokens") or 0
    w1h = min(write, (u.get("cache_creation") or {}).get("ephemeral_1h_input_tokens") or 0)
    return ((u.get("input_tokens") or 0) + READ[fam] * (u.get("cache_read_input_tokens") or 0) + OUT * (u.get("output_tokens") or 0)
            + WRITE_5M * (write - w1h) + WRITE_1H * w1h)


class Slot:
    __slots__ = ("per", "work", "agents", "reads")

    def __init__(self):
        self.per = {}            # pkey → [weight per family…, requests, tokens written, tokens read]
        self.work = set()        # sessions working in this slot
        self.agents = set()      # agents working in this slot
        self.reads = [0] * len(FAMILIES)   # cache-read tokens per family: what the same work would weigh on Opus

    def weight(self, factor, pkey=None):
        rows = self.per.values() if pkey is None else [self.per[pkey]]
        return sum(r[i] * factor[f] for r in rows for i, f in enumerate(FAMILIES))


class Spend:
    """The transcripts of the last HORIZON in 5-minute slots, reading only new data: the first pass reads the week
    (measured 2026-10-21: 310 files, 1.15 GB — 2.3 s, 31 MB), after that only what was appended. One reply is written
    as several lines with the same message.id and tokens, and a session copy repeats the original's lines: a reply
    counts once, in the oldest file."""

    def __init__(self, root, skip=lambda pkey: False):
        self.root = Path(root)
        self.skip = skip
        self.lock = threading.Lock()
        self.files = {}          # path → {"off", "last", "open"}
        self.seen = {}           # message.id → time
        self.slots = {}          # slot number → Slot

    def update(self, now=None):
        with self.lock:
            self._update(now or time.time())

    def _update(self, now):
        since = now - HORIZON
        found = []
        for p in list(self.root.glob("*/*.jsonl")) + list(self.root.glob("*/*/subagents/*.jsonl")):
            rel = p.relative_to(self.root).parts
            try:
                st = p.stat()
            except OSError:
                continue
            if st.st_mtime >= since and not self.skip(rel[0]):
                found.append((st.st_mtime, p, rel, st.st_size))
        for _, p, rel, size in sorted(found):     # oldest first: a reply repeated in a session copy counts once
            key = str(p)
            f = self.files.get(key)
            if f is None or size < f["off"]:
                f = self.files[key] = {"off": 0, "last": None, "open": False}
            if size > f["off"]:
                agent = len(rel) == 4
                self._read(key, f, rel[0], rel[1] if agent else rel[1][:-6], p.stem if agent else None, since)
        keep = {str(p) for _, p, _, _ in found}
        self.files = {k: v for k, v in self.files.items() if k in keep}   # older than the week: forgotten
        cut = int(since // SLOT)
        for i in [i for i in self.slots if i < cut]:
            del self.slots[i]
        self.seen = {k: v for k, v in self.seen.items() if v >= since}

    def _read(self, key, f, pkey, sid, agent, since):
        try:
            with open(key, "rb") as fh:
                fh.seek(f["off"])
                for line in fh:
                    if not line.endswith(b"\n"):
                        break                      # an unfinished line — the rest next time
                    f["off"] += len(line)
                    if b'"usage"' in line and b'"assistant"' in line:
                        self._reply(f, line, pkey, sid, agent, since)
                    elif b'"type":"user"' in line or b'"type": "user"' in line:
                        # the first unescaped "timestamp" is the line's own: inside a string every quote is escaped,
                        # and the message comes before it (checked on 5416 lines, 2026-10-21) — a regex took 2.9 s a week
                        at = line.find(b'"timestamp":')
                        a0 = line.find(b'"', at + 12) + 1 if at >= 0 else 0
                        ts = ts_of(line[a0:line.find(b'"', a0)].decode()) if a0 else None
                        if ts and ts >= since:
                            self._mark(f, ts, sid, agent)
                            f["open"] = True       # the owner's message or a tool's result: the turn goes on
        except OSError:
            pass

    def _reply(self, f, line, pkey, sid, agent, since):
        try:
            e = json.loads(line)
        except ValueError:
            return
        m = e.get("message") or {}
        ts = ts_of(e.get("timestamp") or "")
        if e.get("type") != "assistant" or not ts or ts < since:
            return
        self._mark(f, ts, sid, agent)
        f["open"] = m.get("stop_reason") not in END
        u, mid = m.get("usage"), m.get("id")
        if not u or not mid or mid in self.seen:
            return
        self.seen[mid] = ts
        slot = self._slot(ts)
        row = slot.per.setdefault(pkey, [0.0] * len(FAMILIES) + [0, 0, 0])
        fam = family(m.get("model"))
        row[FAMILIES.index(fam)] += weight_of(u, fam)
        slot.reads[FAMILIES.index(fam)] += u.get("cache_read_input_tokens") or 0
        row[-3] += 1
        row[-2] += u.get("output_tokens") or 0
        row[-1] += (u.get("input_tokens") or 0) + (u.get("cache_read_input_tokens") or 0) + (u.get("cache_creation_input_tokens") or 0)

    def _slot(self, ts):
        i = int(ts // SLOT)
        s = self.slots.get(i)
        if s is None:
            s = self.slots[i] = Slot()
        return s

    def _mark(self, f, ts, sid, agent):
        """The session (or agent) works at ts — and since its previous line, if that was inside a turn."""
        last, f["last"] = f["last"], ts
        start = last if f["open"] and last and 0 <= ts - last <= GAP else ts
        for i in range(int(start // SLOT), int(ts // SLOT) + 1):
            s = self.slots.get(i) or self._slot(i * SLOT)
            (s.agents if agent else s.work).add(agent or sid)

    # ---------- what the app shows ----------

    def today(self, now=None):
        """Today's requests and tokens per project (the old "Today by project")."""
        now = now or time.time()
        with self.lock:
            self._update(now)
            lt = time.localtime(now)
            midnight = time.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday, 0, 0, 0, 0, 0, -1))
            per = {}
            for i, s in self.slots.items():
                if i * SLOT >= midnight:
                    for pkey, r in s.per.items():
                        d = per.setdefault(pkey, {"req": 0, "out": 0, "read": 0})
                        d["req"] += r[-3]
                        d["out"] += r[-2]
                        d["read"] += r[-1]
        rows = [dict(v, pkey=k) for k, v in per.items()]
        return {"day": midnight, "projects": sorted(rows, key=lambda r: -r["out"])}

    def view(self, usage, log=(), now=None, pace=PACE_LOW, known=None):
        """The Resources screen from a get_usage reading (pult_web.simplify_usage) and the usage log
        ([(time, kind, percent, resets)…]). `known` — the per-token rates and factors kept between calls
        ({"k": {key: rate}, "fable": factor}); the answer carries them back under "known"."""
        now = now or time.time()
        with self.lock:
            self._update(now)
            return view(self.slots, usage, log, now, pace, known or {})


# ---------- the curve, the pace and the forecast: plain functions over the slots ----------

def fit_factor(slots, usage, t0, t1, now):
    """Each model's factor, Fable's fitted to its weekly share: Fable spent `used` of the week's `total` points
    with weight wf, the rest with wr — so its factor is used/(total−used) · wr/wf."""
    factor = dict(FACTOR)
    week = next((x for x in usage.get("limits") or [] if WINDOWS.get(x["kind"], ("",))[0] == "week"), None)
    for sh in usage.get("shares") or []:
        fam = family(sh.get("name"))
        if fam in ("opus", "other") or not week or not sh.get("used"):
            continue
        total, used = week["percent"], sh["used"]
        wf = sum(s.per[p][FAMILIES.index(fam)] for i, s in slots.items() if t0 <= i * SLOT < now for p in s.per)
        wr = sum(s.weight(dict(factor, **{fam: 0.0})) for i, s in slots.items() if t0 <= i * SLOT < now)
        if wf > 0 and wr > 0 and 0.02 < used / max(total, 1) < 0.98:
            # up to twice the old bound: Fable's reads weigh half Opus's now, so its factor per weight comes out higher
            factor[fam] = min(24.0, max(1.0, used / (total - used) * wr / wf))
    return factor


def same_work(slots, factor, t0, now, fam="fable"):
    """How many times the same work costs on a family as on Opus, between t0 and now: its factor, times what its
    tokens weigh against what they would weigh at Opus's read price — Fable reads cheaper per token, so its work costs
    less than its factor (Q95). With no such work — the factor itself."""
    i = FAMILIES.index(fam)
    w = r = 0.0
    for k, s in slots.items():
        if t0 <= k * SLOT < now:
            w += sum(row[i] for row in s.per.values())
            r += s.reads[i]
    return factor[fam] * w / (w + (READ["opus"] - READ[fam]) * r) if w > 0 else factor[fam]


def anchors(t0, t1, now, used, log, kind):
    """The readings the curve passes through: the start at 0, the readings of this window that rose at least
    MIN_STEP points, now at `used`."""
    out = [(t0, 0.0)]
    for ts, k, pc, resets in sorted(log, key=lambda e: e[0]):     # by time alone: a None among resets broke it (М9)
        if k == kind and t0 < ts < now and resets and abs(resets - t1) < 600 and out[-1][1] + MIN_STEP <= pc <= used:
            out.append((ts, float(pc)))
    out.append((now, float(used)))
    return out


def curve(slots, t0, now, used, log, kind, t1, factor):
    """Every slot of the window up to now → (time, its weight, its percent, of it — from elsewhere): the growth
    between two readings spread in proportion to weight; with no weight here, evenly — as "elsewhere"."""
    first, last = int(t0 // SLOT), int(now // SLOT)
    rows = [[i * SLOT, slots[i].weight(factor) if i in slots else 0.0, 0.0, 0.0] for i in range(first, last + 1)]
    pts = anchors(t0, t1, now, used, log, kind)
    carry, j = 0.0, 0
    for k in range(1, len(pts)):
        end = pts[k][0] if k < len(pts) - 1 else float("inf")
        seg = []
        while j < len(rows) and rows[j][0] < end:
            seg.append(rows[j])
            j += 1
        delta = max(0.0, pts[k][1] - pts[k - 1][1]) + carry
        if not seg:
            carry = delta
            continue
        carry = 0.0
        w = sum(r[1] for r in seg)
        for r in seg:
            if w > 0:
                r[2] = delta * r[1] / w
            else:
                r[2] = r[3] = delta / len(seg)
    return rows


def at_once(slots, i0, i1):
    """The most sessions and agents working in the same slot between i0 and i1 (inclusive)."""
    s = a = 0
    for i in range(i0, i1 + 1):
        x = slots.get(i)
        if x:
            s, a = max(s, len(x.work)), max(a, len(x.agents))
    return s, a


def session_hours(slots, since, until):
    """Hours of one session's work over a period: each working session counts its slots."""
    return sum(len(s.work) for i, s in slots.items() if since <= i * SLOT < until) * SLOT / 3600


def view(slots, usage, log, now, pace, known):
    pace = pace if pace in PACES else PACE_LOW
    ks = dict(known.get("k") or {})
    lims = {}
    for lim in usage.get("limits") or []:
        w = WINDOWS.get(lim["kind"])
        # a reading from before its reset says nothing about the new window: wait for the next reading
        if w and lim.get("resets_at") and lim["resets_at"] > now and w[0] not in lims:
            lims[w[0]] = (lim, w)
    week = lims.get("week")
    t0w = week[0]["resets_at"] - week[1][1] if week else now - 7 * 86400
    factor = fit_factor(slots, usage, t0w, week[0]["resets_at"], now) if week else dict(FACTOR)
    # a session-hour's weight over the last 7 days: the unit of "how much is left"
    wk7 = sum(s.weight(factor) for i, s in slots.items() if now - 7 * 86400 <= i * SLOT < now)
    sh7 = session_hours(slots, now - 7 * 86400, now)
    per_sh_w = wk7 / sh7 if sh7 > 0 else None
    out, raw = {}, {}
    for key, (lim, (_, span, step)) in lims.items():
        t1 = lim["resets_at"]
        t0, used = t1 - span, float(lim["percent"] or 0)
        rows = curve(slots, t0, min(now, t1), used, log, lim["kind"], t1, factor)
        w_all = sum(r[1] for r in rows)
        ext = sum(r[3] for r in rows)
        k = (used - ext) / w_all if w_all > 0 and used >= MIN_K else None
        if k is not None:
            ks[key] = k
        k = k if k is not None else ks.get(key)
        recent = RECENT[key]
        # spend from elsewhere is averaged over no less than the span the local pace uses: right after a reset 2 % in
        # half an hour read as 4 %/h over the week — "runs out" on Home until a turn here (review 2026-10-27, М4)
        elapsed = max(float(recent), min(now, t1) - t0)
        w_recent = sum(s.weight(factor) for i, s in slots.items() if now - recent <= i * SLOT < now)
        rate = (w_recent * k / (recent / 3600) + ext / (elapsed / 3600)) if k is not None else None   # % per hour
        left = max(0.0, t1 - now) / 3600
        res = {"key": key, "kind": lim["kind"], "name": lim["name"], "used": used, "t0": t0, "t1": t1, "now": now,
               "step": step, "pace": pace, "state": "none", "proj": None, "hit": None, "spare": None, "rate": rate,
               "per_sh": per_sh_w * k if per_sh_w and k else None, "sh_left": None, "par": None, "ext": round(ext, 2)}
        if used >= 100:
            res.update(state="over", proj=100.0, hit=now, spare=0.0)
        elif rate is not None:
            proj = used + rate * left
            hit = now + (100 - used) / rate * 3600 if rate > 0 and proj >= 100 else None
            res.update(proj=min(proj, 100.0) if hit else proj, hit=hit, spare=0.0 if hit else max(0.0, 100 - proj),
                       state="over" if hit else "pace" if proj >= pace else "under")
        if res["spare"] is not None and res["per_sh"]:
            res["sh_left"] = res["spare"] / res["per_sh"]
            res["par"] = res["sh_left"] / left if key == "h5" and left > 0.25 else None
        # the bars: each step's spend, of it from elsewhere, the most sessions and agents at once, its biggest projects
        n_bars = int((min(now, t1) - t0) // step) + 1
        cost, other, by = [0.0] * n_bars, [0.0] * n_bars, [{} for _ in range(n_bars)]
        spent = {}
        for r in rows:
            b = min(n_bars - 1, int((max(r[0], t0) - t0) // step))
            cost[b] += r[2]
            other[b] += r[3]
            s = slots.get(int(r[0] // SLOT))
            if s and r[1] > 0 and r[2] > 0:
                for pkey in s.per:
                    c = r[2] * s.weight(factor, pkey) / r[1]
                    by[b][pkey] = by[b].get(pkey, 0.0) + c
                    spent[pkey] = spent.get(pkey, 0.0) + c
        projects = sorted(spent.items(), key=lambda x: -x[1])
        idx = {p: i for i, (p, _) in enumerate(projects)}
        bars = []
        for b in range(n_bars):
            a0 = t0 + b * step
            n, ag = at_once(slots, int(a0 // SLOT), int(min(a0 + step - 1, now) // SLOT))
            top3 = [[idx[p], round(c, 3)] for p, c in sorted(by[b].items(), key=lambda x: -x[1])[:3]]
            bars.append([round(cost[b], 3), n, ag, top3] + ([round(other[b], 3)] if other[b] > 0 else []))
        res["bars"] = bars
        res["projects"] = [[p, round(c, 3), round(c / res["per_sh"], 2) if res["per_sh"] else None] for p, c in projects]
        raw[key] = (k, res)
        out[key] = res
    # the 5-hour window can't use more than the week has left: compare what is left in weight
    if "h5" in raw and "week" in raw and raw["h5"][0] and raw["week"][0]:
        h5, wk = raw["h5"][1], raw["week"][1]
        if h5["spare"] is not None and wk["spare"] is not None:
            left_h5, left_wk = h5["spare"] / raw["h5"][0], wk["spare"] / raw["week"][0]
            if left_wk < left_h5:
                h5["tighter"] = {"sh": left_wk / per_sh_w if per_sh_w else None}
    # which limit the Home strip shows: the one that runs out first, else the fuller one
    hits = [r for r in out.values() if r["hit"]]
    top = min(hits, key=lambda r: r["hit"]) if hits else max(out.values(), key=lambda r: r["used"], default=None)
    return {"limits": [out[k] for k in ("week", "h5") if k in out], "top": top["key"] if top else None,
            "known": {"k": ks, "fable": factor.get("fable")}, "factor": factor, "per_sh_w": per_sh_w,
            "fable_x": same_work(slots, factor, t0w, now)}
