"""How Claude asks in this computer's sessions: AskUserQuestion questions from the transcripts in ~/.claude/projects —
how many let the owner tick several answers (multiSelect), and how many give one choice with combinations glued
into options instead ("only A" / "A + B" / "both" — a rough rule: "A and B" slips past it, a plain "only" limit
gets in; --list shows them). Pult's SessionStart paragraph asks for ticks where options combine (0.18.3,
pult_hook.ASK_NOTE); this counts whether it took. And whether the buttons fit: answers in the owner's own words instead
of a button (2026-10-15…28: 4 of 123, each a "yes, but…" — the paragraph asks for those since 2026-10-28), and the
ready replies under a "your move" — tapped or not, from the daemon's journal (written since the same day).
Read-only; probes and Pult's tests (temporary folders) are left out.
  ~/.local/share/pult/venv/bin/python tools/ask_stats.py [--since 2026-10-27] [--until 2026-11-03] [--list]
"""
import argparse, collections, glob, json, os, re, time

ROOT = os.path.expanduser("~/.claude/projects")
SKIP = re.compile(r"private-var-folders|private-tmp|pult-e2e|pult-multi|pult-ctx|scratchpad")
GLUE = re.compile(r"\+|\b(только|оба|обе|ещё и|то же|only|both|as well)\b", re.I)
ADVICE = re.compile(r"\s*\((recommended|рекомендую)\)", re.I)
JOURNAL = os.path.expanduser("~/Library/Logs/pult.log")
READY = re.compile(r"^(\d{4}-\d\d-\d\d) [\d:]+ ready replies \w+: (tapped|own words)")


def questions(since, until):
    """(time, project, question) of every AskUserQuestion asked between since and until (ISO dates, UTC)."""
    t0 = time.mktime(time.strptime(since, "%Y-%m-%d")) - 86400 if since else 0
    for f in glob.glob(os.path.join(ROOT, "*", "*.jsonl")):
        proj = os.path.basename(os.path.dirname(f))
        if SKIP.search(proj) or os.path.getmtime(f) < t0:
            continue
        with open(f, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                if '"AskUserQuestion"' not in line:
                    continue
                try:
                    d = json.loads(line)
                except ValueError:
                    continue
                ts = d.get("timestamp") or ""
                if d.get("type") != "assistant" or (since and ts < since) or (until and ts >= until):
                    continue
                for c in (d.get("message") or {}).get("content") or []:
                    if isinstance(c, dict) and c.get("type") == "tool_use" and c.get("name") == "AskUserQuestion":
                        for q in (c.get("input") or {}).get("questions") or []:
                            yield ts, re.sub(r"^-Users-[^-]+-(Documents-)?", "", proj), q


def plain(s):
    return " ".join(ADVICE.sub("", str(s or "")).split()).casefold()


def taps(a, labels):
    """a — an answer: one label, or labels joined by ", " (ticks; a label may hold a comma itself: "Yes, go ahead")."""
    return a in labels or any(x and a.startswith(x + ", ") and taps(a[len(x) + 2:], labels) for x in labels)


def answered(since, until):
    """(time, project, own) for every answered question: own — the answer is not the question's buttons."""
    t0 = time.mktime(time.strptime(since, "%Y-%m-%d")) - 86400 if since else 0
    for f in glob.glob(os.path.join(ROOT, "*", "*.jsonl")):
        proj = os.path.basename(os.path.dirname(f))
        if SKIP.search(proj) or os.path.getmtime(f) < t0:
            continue
        asked, got = {}, {}
        with open(f, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                if '"AskUserQuestion"' not in line and not ('"tool_result"' in line and '"answers"' in line):
                    continue
                try:
                    d = json.loads(line)
                except ValueError:
                    continue
                for c in (d.get("message") or {}).get("content") or []:
                    if not isinstance(c, dict):
                        continue
                    if d.get("type") == "assistant" and c.get("type") == "tool_use" and c.get("name") == "AskUserQuestion":
                        asked[c.get("id")] = (d.get("timestamp") or "", (c.get("input") or {}).get("questions") or [])
                    elif d.get("type") == "user" and c.get("type") == "tool_result" and isinstance(d.get("toolUseResult"), dict):
                        got[c.get("tool_use_id")] = d["toolUseResult"].get("answers") or {}
        for tid, (ts, qs) in asked.items():
            if (since and ts < since) or (until and ts >= until):
                continue
            for q in qs:
                a = (got.get(tid) or {}).get(q.get("question"))
                if a is not None:
                    labels = {plain(o.get("label")) for o in q.get("options") or []}
                    yield ts, re.sub(r"^-Users-[^-]+-(Documents-)?", "", proj), not taps(plain(a), labels)


def ready(since, until):
    """The ready replies under a "your move": the journal's lines, tapped or the owner's own words instead."""
    n = collections.Counter()
    try:
        with open(JOURNAL, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                m = READY.match(line)
                if m and not (since and m.group(1) < since) and not (until and m.group(1) >= until):
                    n[m.group(2)] += 1
    except OSError:
        pass
    return n


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--since", help="YYYY-MM-DD (UTC), from this day on")
    p.add_argument("--until", help="YYYY-MM-DD (UTC), before this day")
    p.add_argument("--list", action="store_true", help="print the questions that look glued")
    a = p.parse_args()
    rows = sorted(questions(a.since, a.until), key=lambda r: r[0])
    if not rows:
        print("no questions")
        return
    multi = [r for r in rows if r[2].get("multiSelect")]
    glued = [r for r in rows if not r[2].get("multiSelect")
             and any(GLUE.search(o.get("label") or "") for o in r[2].get("options") or [])]
    n = len(rows)
    print("%s … %s: %d questions (%s)" % (rows[0][0][:10], rows[-1][0][:10], n,
                                          ", ".join("%s %d" % kv for kv in collections.Counter(r[1] for r in rows).most_common())))
    print("  ticks (multiSelect):          %3d  %3.0f%%" % (len(multi), 100.0 * len(multi) / n))
    print("  one choice, looks glued:      %3d  %3.0f%%" % (len(glued), 100.0 * len(glued) / n))
    print("  one choice, the rest:         %3d" % (n - len(multi) - len(glued)))
    got = list(answered(a.since, a.until))
    own = sum(1 for r in got if r[2])
    if got:
        print("  answered in own words:        %3d  %3.0f%%  (of %d answered)" % (own, 100.0 * own / len(got), len(got)))
    r = ready(a.since, a.until)
    if r:
        print("ready replies (journal): tapped %d, own words instead %d" % (r["tapped"], r["own words"]))
    if a.list:
        for ts, proj, q in glued:
            print("\n%s %s  %s" % (ts[:16].replace("T", " "), proj, q.get("question", "")[:160]))
            for o in q.get("options") or []:
                print("   - " + (o.get("label") or ""))


if __name__ == "__main__":
    main()
