"""How many tokens a project's work took, from Claude Code's transcripts in ~/.claude/projects (read-only): the
project's sessions with their background agents and, for Pult itself, its tests and probes — the folders with "pult"
in the name (e2e_live, tests/probe_*.py, a sandbox). One reply is written as several lines with the same message.id,
and a session copy repeats the original's lines: a reply counts once, in the oldest file. By kind, model, source and
day, with what the same tokens cost at the API's prices; how long sessions worked (pauses up to 10 min) and how many
messages the owner wrote. A session that began in another project's folder is added with --extra.

An agent's transcript keeps the output count from the start of the stream, not the final one (Claude Code 2.1.300
and 2.1.301, 2026-10-28): such a reply has no stop_reason, and its output is estimated by the length of what it
wrote, at the characters per token of the finished replies (thinking stays unseen).
  python3 tools/token_stats.py [--project DIR] [--extra SESSION.jsonl]... [--since 2026-10-20] [--json]
"""
import argparse, collections, datetime, json, os, re, time
from pathlib import Path

ROOT = Path.home() / ".claude" / "projects"
REPO = Path(__file__).resolve().parent.parent
GAP = 600                        # s: a pause up to this inside a session is work
KINDS = ("read", "write_1h", "write_5m", "output", "input")
# The API's prices per million tokens on 2026-10-06 (Claude's own reference): input, cache write for 5 min and for
# 1 h, cache read, output. A model not listed takes its family's; Haiku over 100 K tokens of prompt costs five times.
PRICE = {"claude-fable-5-1": (10, 12.5, 20, 0.25, 50), "claude-opus-5-5": (4, 5, 8, 0.20, 20),
         "claude-sonnet-5-5": (2, 2.5, 4, 0.20, 10), "claude-haiku-5-5": (0.10, 0.125, 0.20, 0.01, 0.50)}
HAIKU_LONG = 100_000


def folder(path):
    """The name of a project's transcript folder: its path with every character but letters and digits a dash."""
    return re.sub(r"[^A-Za-z0-9]", "-", os.path.realpath(path))


def mtime(p):
    try:
        return p.stat().st_mtime
    except OSError:
        return 0.0                   # gone meanwhile — a test's temporary folder


def transcripts(project, extra=(), tests=False, root=ROOT):
    """(source, path) of every transcript to count, oldest first. Sources: "sessions", "agents" (<session>/subagents/),
    "extra" (sessions given by hand, with their agents) and "tests"."""
    own = root / folder(project)
    out = [("agents" if "subagents" in p.parts else "sessions", p) for p in own.rglob("*.jsonl")] if own.is_dir() else []
    for f in (Path(x).expanduser() for x in extra):
        out += [("extra", f)] + [("extra", p) for p in f.with_suffix("").glob("subagents/*.jsonl")]
    if tests:
        out += [("tests", p) for d in root.iterdir() if d.is_dir() and d != own and "pult" in d.name.lower()
                for p in d.rglob("*.jsonl")]
    return sorted(out, key=lambda sp: mtime(sp[1]))


def price(model, prompt):
    """$ per token of each kind (as KINDS) for a reply with a prompt of this many tokens; None — no price known."""
    p = PRICE.get(model) or next((v for k, v in PRICE.items() if k.split("-")[1] in (model or "")), None)
    if p is None:
        return None
    x = 5 if "haiku" in model and prompt > HAIKU_LONG else 1
    inp, w5, w1, read, out = p
    return dict(zip(KINDS, (v * x / 1e6 for v in (read, w1, w5, out, inp))))


def stamp(s):
    try:
        return datetime.datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()
    except (AttributeError, ValueError):
        return None


def shown(content):
    """The characters of a reply a person sees: its text and its tools' input."""
    n = 0
    for b in content if isinstance(content, list) else ():
        if b.get("type") == "text":
            n += len(b.get("text") or "")
        elif b.get("type") == "tool_use":
            n += len(json.dumps(b.get("input"), ensure_ascii=False))
        elif b.get("type") == "thinking":
            n += len(b.get("thinking") or "")
    return n


def owner_wrote(e):
    """Whether a user line is a message the owner wrote, in a tab or from the phone — not a tool's result, a
    notification, another session's message or the summary of a compaction."""
    if e.get("isMeta") or e.get("isSidechain"):
        return False
    if "promptSource" in e:                  # where a turn came from, in Claude Code 2.1.300
        return e["promptSource"] == "sdk" and e.get("turnOrigin") in ("human", "sdk")
    c = (e.get("message") or {}).get("content")
    if isinstance(c, list):
        if any(isinstance(b, dict) and b.get("type") == "tool_result" for b in c):
            return False
        c = " ".join(b.get("text") or "" for b in c if isinstance(b, dict) and b.get("type") == "text")
    return isinstance(c, str) and bool(c.strip()) and not c.startswith(("<", "Caveat:", "This session is being continued"))


def read(files, since=None):
    """The replies by message.id, and for each transcript its source, the times of its lines and the owner's messages."""
    replies, seen = {}, {}
    for src, p in files:
        times, said = [], 0
        try:
            fh = open(p, "rb")
        except OSError:
            continue
        with fh:
            for line in fh:
                try:
                    e = json.loads(line)
                except ValueError:
                    continue                 # a line still being written
                t = e.get("type") if isinstance(e, dict) else None
                ts = stamp(e.get("timestamp")) if t in ("user", "assistant") else None
                if ts is None or (since and ts < since):
                    continue
                times.append(ts)
                if t == "user":
                    said += owner_wrote(e)
                    continue
                m = e.get("message") or {}
                mid, model, u = m.get("id"), m.get("model"), m.get("usage")
                if not mid or not u or model == "<synthetic>":
                    continue
                r = replies.get(mid)
                if r is None:
                    r = replies[mid] = dict(path=p, src=src, model=model, ts=ts, stop=None, shown=0, thinking=0,
                                            **dict.fromkeys(KINDS, 0))
                elif r["path"] != p:
                    continue                 # a session copy: counted in the oldest file
                write = u.get("cache_creation_input_tokens") or 0
                w1 = min(write, (u.get("cache_creation") or {}).get("ephemeral_1h_input_tokens") or 0)
                for k, v in (("read", u.get("cache_read_input_tokens")), ("write_1h", w1), ("write_5m", write - w1),
                             ("output", u.get("output_tokens")), ("input", u.get("input_tokens")),
                             ("thinking", (u.get("output_tokens_details") or {}).get("thinking_tokens"))):
                    r[k] = max(r[k], v or 0)
                r["stop"] = r["stop"] or m.get("stop_reason")
                r["shown"] += shown(m.get("content"))
        seen[p] = (src, sorted(times), said)
    return replies, seen


def hours(spans):
    """The length of the union of (start, end) spans, in hours."""
    total, end = 0.0, None
    for a, b in sorted(spans):
        if end is None or a > end:
            total, end = total + b - a, b
        elif b > end:
            total, end = total + b - end, b
    return total / 3600


def summary(replies, seen):
    """The report's numbers: tokens and their price by kind, model, source and day; the context a reply reads in
    sessions; hours of work, the owner's messages and the estimate of the output a transcript under-records."""
    def bucket():
        return dict(replies=0, tokens=0, cost=0.0)
    s = dict(replies=len(replies), tokens=dict.fromkeys(KINDS, 0), thinking=0, cost=dict.fromkeys(KINDS, 0.0),
             models=collections.defaultdict(bucket), sources=collections.defaultdict(bucket),
             days=collections.defaultdict(bucket), unpriced=set())
    context = collections.defaultdict(lambda: [0, 0])
    for r in replies.values():
        prompt = r["read"] + r["write_1h"] + r["write_5m"] + r["input"]
        p = price(r["model"], prompt)
        if p is None:
            s["unpriced"].add(r["model"])
        cost = sum(r[k] * p[k] for k in KINDS) if p else 0.0
        for k in KINDS:
            s["tokens"][k] += r[k]
            s["cost"][k] += r[k] * p[k] if p else 0.0
        s["thinking"] += r["thinking"]
        day = time.strftime("%Y-%m-%d", time.localtime(r["ts"]))
        for b in (s["models"][r["model"]], s["sources"][r["src"]], s["days"][day]):
            b["replies"] += 1
            b["tokens"] += prompt + r["output"]
            b["cost"] += cost
        if r["src"] in ("sessions", "extra"):
            context[r["model"]][0] += prompt
            context[r["model"]][1] += 1
    # a reply without stop_reason has its output counted from the start of the stream: estimated by what it wrote
    done = [r for r in replies.values() if r["stop"] and r["output"] > r["thinking"]]
    per = sum(r["shown"] for r in done) / max(1, sum(r["output"] - r["thinking"] for r in done))
    est = dict(replies=0, agents=0, written=0, estimate=0, cost=0.0)
    for r in replies.values():
        if r["stop"]:
            continue
        more = max(0, round(r["shown"] / per) - r["output"]) if per else 0
        p = price(r["model"], 0)
        est["replies"] += 1
        est["agents"] += r["src"] == "agents"
        est["written"] += r["output"]
        est["estimate"] += r["output"] + more
        est["cost"] += more * p["output"] if p else 0.0
    files = collections.Counter(seen[p][0] for p in {r["path"] for r in replies.values()})
    mine = [(t, said) for src, t, said in seen.values() if src in ("sessions", "extra")]
    spans = [[(a, b) for a, b in zip(t, t[1:]) if b - a <= GAP] for t, _ in mine]
    ts = [r["ts"] for r in replies.values()]
    s.update(first=min(ts, default=None), last=max(ts, default=None), files=dict(files), estimate=est,
             chars_per_token=round(per, 2), hours=round(hours(x for sp in spans for x in sp), 1),
             hours_summed=round(sum(hours(sp) for sp in spans), 1), messages=sum(said for _, said in mine),
             context={m: dict(tokens=round(n / k), replies=k) for m, (n, k) in context.items()},
             unpriced=sorted(s["unpriced"]))
    return s


def report(s):
    def mil(n):
        return "{:,.1f}".format(n / 1e6)

    def usd(x):
        return "${:,.0f}".format(x)

    def when(t):
        return time.strftime("%Y-%m-%d %H:%M", time.localtime(t))
    if not s["replies"]:
        print("no replies")
        return
    f = s["files"]
    print("%s … %s: %s replies in transcripts of %s" % (
        when(s["first"]), when(s["last"]), "{:,}".format(s["replies"]),
        ", ".join("%s %d" % (k, f[k]) for k in ("sessions", "agents", "extra", "tests") if k in f)))
    print("                tokens, M   API")
    names = {"read": "cache read", "write_1h": "cache write 1 h", "write_5m": "cache write 5 min", "output": "output",
             "input": "input"}
    for k in KINDS:
        tail = "   thinking %s M" % mil(s["thinking"]) if k == "output" else ""
        print("  %-17s %9s %7s%s" % (names[k], mil(s["tokens"][k]), usd(s["cost"][k]), tail))
    print("  %-17s %9s %7s" % ("total", mil(sum(s["tokens"].values())), usd(sum(s["cost"].values()))))
    for title, key in (("by model", "models"), ("by source", "sources")):
        rows = sorted(s[key].items(), key=lambda kv: -kv[1]["cost"])
        print("%s: %s" % (title, " · ".join("%s %s" % (k, usd(v["cost"])) for k, v in rows)))
    many = sum(c["replies"] for c in s["context"].values()) / 100          # a model's 1 % of the replies and more
    print("context per reply in sessions: " + " · ".join(
        "%s %d K" % (m, c["tokens"] / 1e3) for m, c in sorted(s["context"].items(), key=lambda kv: -kv[1]["replies"])
        if c["replies"] >= many))
    print("by day:")
    for d, v in sorted(s["days"].items()):
        print("  %s %7s %8s M" % (d, usd(v["cost"]), "{:,.0f}".format(v["tokens"] / 1e6)))
    print("work: %.0f h with a session working (pauses up to %d min), %.0f h summed over sessions; the owner's messages: %d"
          % (s["hours"], GAP // 60, s["hours_summed"], s["messages"]))
    e = s["estimate"]
    if e["replies"]:
        print("output under-recorded: %d replies have no stop_reason (%d of them agents'); their transcripts give %s K"
              " tokens of output, what they wrote ≈ %s K (thinking unseen): +%s" % (
                  e["replies"], e["agents"], "{:,.0f}".format(e["written"] / 1e3), "{:,.0f}".format(e["estimate"] / 1e3),
                  usd(e["cost"])))
    if s["unpriced"]:
        print("no price for: " + ", ".join(s["unpriced"]))


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--project", default=str(REPO), help="the project's folder (default: this repository)")
    p.add_argument("--extra", action="append", default=[], help="a session's transcript from another folder — where the"
                   " project began; its agents come with it")
    p.add_argument("--since", help="YYYY-MM-DD (local time), from this day on")
    p.add_argument("--json", action="store_true", help="the numbers as JSON")
    a = p.parse_args()
    for f in a.extra:
        if not Path(f).expanduser().is_file():
            p.error("no such transcript: " + f)
    since = time.mktime(time.strptime(a.since, "%Y-%m-%d")) if a.since else None
    own = os.path.realpath(a.project) == str(REPO)
    s = summary(*read(transcripts(a.project, a.extra, tests=own), since))   # Pult's tests count for Pult only
    if a.json:
        print(json.dumps(s, indent=1, ensure_ascii=False))
    else:
        report(s)


if __name__ == "__main__":
    main()
