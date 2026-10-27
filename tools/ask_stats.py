"""How Claude asks in this computer's sessions: AskUserQuestion questions from the transcripts in ~/.claude/projects —
how many let the owner tick several answers (multiSelect), and how many give one choice with combinations glued
into options instead ("only A" / "A + B" / "both" — a rough rule: "A and B" slips past it, a plain "only" limit
gets in; --list shows them). Pult's SessionStart paragraph asks for ticks where options combine (0.18.3,
pult_hook.ASK_NOTE); this counts whether it took. Read-only; probes and Pult's tests (temporary folders) are left out.
  ~/.local/share/pult/venv/bin/python tools/ask_stats.py [--since 2026-10-27] [--until 2026-11-03] [--list]
"""
import argparse, collections, glob, json, os, re, time

ROOT = os.path.expanduser("~/.claude/projects")
SKIP = re.compile(r"private-var-folders|private-tmp|pult-e2e|pult-multi|pult-ctx|scratchpad")
GLUE = re.compile(r"\+|\b(только|оба|обе|ещё и|то же|only|both|as well)\b", re.I)


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
    if a.list:
        for ts, proj, q in glued:
            print("\n%s %s  %s" % (ts[:16].replace("T", " "), proj, q.get("question", "")[:160]))
            for o in q.get("options") or []:
                print("   - " + (o.get("label") or ""))


if __name__ == "__main__":
    main()
