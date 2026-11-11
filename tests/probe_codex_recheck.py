"""Probe: can Codex check the fixes of its own findings (review 2026-11-11, block 6 — "Check the fixes")? Pult's second
opinion is one `review/start` in a read-only thread, and the app-server is closed after it. For the next round Codex has
to say of each earlier finding: fixed, left, or deliberate. Two ways to ask, both tried here:
  B — the same thread, resumed in a new app-server (`thread/resume`), a plain turn that names no finding: does it
      remember what it found?
  C — a new thread, the findings and the doer's answer in the turn's own text: nothing kept between the rounds.
A made-up shop in a temporary folder: a commit, then a change with three planted faults; after the review the probe
"fixes" the first, calls the second deliberate in the doer's answer, and leaves the third as it was.

Run (uses a little of the ChatGPT plan, ~2 min; no project's code goes anywhere — the folder is made up here):
  ~/.local/share/pult/venv/bin/python tests/probe_codex_recheck.py [product]
`product` — Pult's own path instead of B and C, as the daemon runs it: review() and parse() for the review, then
check_instructions(), review(plain=True) and parse_check() for the check of the fixes.
"""
import asyncio, os, subprocess, sys, tempfile, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
import pult_codex as CX  # noqa: E402

TMP = Path(os.path.realpath(tempfile.mkdtemp(prefix="pult-cxre-")))
T0 = time.time()
ENV = {k: v for k, v in os.environ.items() if not k.startswith("PULT_")}

BASE = '''"""The shop's cart."""


def total(items):
    """The cart's total in cents: items are (price_cents, quantity)."""
    return sum(p * q for p, q in items)
'''
CHANGED = '''"""The shop's cart."""


def total(items, discount=0):
    """The cart's total in cents: items are (price_cents, quantity); discount — percent off, 0–100."""
    s = sum(p * q for p, q in items)
    return s - s * discount / 100


def average_price(items):
    """The mean price of one thing in the cart, in cents."""
    return total(items) / sum(q for p, q in items)


def cheapest(items):
    """The cheapest thing's price in cents."""
    return sorted(items)[-1][0]
'''
FIXED = CHANGED.replace("    return total(items) / sum(q for p, q in items)",
                        "    n = sum(q for p, q in items)\n    return total(items) / n if n else 0")
ANSWER = ("Fixed: average_price returns 0 for an empty cart. Deliberate: total() returns a float with a discount — the "
          "owner asked for fractions of a cent to be kept until the invoice is rounded, so it stays. I did not touch "
          "cheapest().")
FORMAT = ("For each of those findings, in their order, answer one line and nothing before it:\n"
          "N. FIXED — one sentence\nN. LEFT — one sentence: what is still wrong\nN. DELIBERATE — one sentence\n"
          "FIXED: the change is in the files now and is right. DELIBERATE: the doer says it is on purpose and you "
          "accept the reason. LEFT: anything else. Read the files as they are now; change nothing.")


def say(*a):
    print("%5.1f" % (time.time() - T0), *a, flush=True)


def git(*a):
    subprocess.run(["git", "-C", str(TMP), *a], check=True, capture_output=True)


async def start(path):
    s = await CX.AppServer.start(path, str(TMP), ENV)
    await s.request("initialize", {"clientInfo": {"name": "pult", "title": "Pult", "version": "probe"}})
    await s.send({"method": "initialized"})
    return s


async def turn_text(s, tid, timeout=600):
    """The words of the turn that is running in the thread, the commands it ran."""
    said, review, steps, end = None, None, 0, time.time() + timeout
    while True:
        m = await asyncio.wait_for(s.events.get(), max(1.0, end - time.time()))
        if m is None:
            raise RuntimeError("Codex stopped: " + s.tail())
        prm = m.get("params") if isinstance(m.get("params"), dict) else {}
        if prm.get("threadId") not in (None, tid):
            continue
        if m.get("method") == "item/completed":
            it = prm.get("item") or {}
            if it.get("type") == "exitedReviewMode":
                review = it.get("review")
            elif it.get("type") == "agentMessage" and it.get("text"):
                said = it["text"]
            elif it.get("type") == "commandExecution":
                steps += 1
        elif m.get("method") == "turn/completed":
            turn = prm.get("turn") or {}
            if turn.get("status") != "completed":
                raise RuntimeError("turn: %r" % (turn.get("error") or turn.get("status")))
            return (review if review is not None else said) or "", steps


async def main():
    path = CX.find(dict(os.environ))
    say("codex:", path, CX.version(path))
    (TMP / "cart.py").write_text(BASE)
    for a in (["init", "-q"], ["config", "user.email", "probe@example.invalid"], ["config", "user.name", "probe"],
              ["config", "commit.gpgsign", "false"], ["add", "-A"], ["commit", "-qm", "cart: total"]):
        git(*a)
    base = subprocess.run(["git", "-C", str(TMP), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
    (TMP / "cart.py").write_text(CHANGED)
    facts = {"asks": ["Add a discount to the cart's total, the mean price and the cheapest thing."],
             "report": "Added the discount, average_price and cheapest to cart.py.", "files": ["cart.py"], "t0": time.time()}
    text = CX.instructions(facts, base, "en")

    if "product" in sys.argv[1:]:
        t = time.time()
        got = await CX.review(path, str(TMP), text, env=ENV, client="probe")
        read = CX.parse(got["text"], str(TMP))
        say("REVIEW (review): %d findings, %.0f s; model %s" % (len(read["items"]), time.time() - t, got["model"]))
        for n, it in enumerate(read["items"], 1):
            say("  %d. [%s] %s — %s" % (n, it["prio"], it["title"], CX.where(it)))
        (TMP / "cart.py").write_text(FIXED)
        t, steps = time.time(), []
        ask = CX.check_instructions(dict(facts, report=ANSWER), read["items"], base, "ru")
        got = await CX.review(path, str(TMP), ask, env=ENV, on_step=steps.append, client="probe", plain=True)
        said, new = CX.parse_check(got["text"], len(read["items"]), str(TMP))
        say("CHECK (review plain): %d commands, %.0f s; asked: %s\n%s" % (len(steps), time.time() - t, got["asked"], got["text"]))
        say("  read as:", {k + 1: v for k, v in sorted(said.items())}, "new:", [it["title"] for it in new])
        say("  every finding has its line:", len(said) == len(read["items"]))
        say("the folder after (the probe's own fix only):",
            subprocess.run(["git", "-C", str(TMP), "status", "--short"], capture_output=True, text=True).stdout.strip())
        return

    # the review, as Pult runs it
    s = await start(path)
    th = await s.request("thread/start", {"cwd": str(TMP), "sandbox": "read-only", "approvalPolicy": "never"})
    tid = th["thread"]["id"]
    t = time.time()
    await s.request("review/start", {"threadId": tid, "delivery": "inline", "target": {"type": "custom", "instructions": text}})
    got, steps = await turn_text(s, tid)
    read = CX.parse(got, str(TMP))
    say("REVIEW: %d findings, %d commands, %.0f s; model %s" % (len(read["items"]), steps, time.time() - t, th.get("model")))
    for n, it in enumerate(read["items"], 1):
        say("  %d. [%s] %s — %s" % (n, it["prio"], it["title"], CX.where(it)))
    await s.close()
    if not read["items"]:
        say("no findings — nothing to check"); return

    # the doer's round: one fixed, one called deliberate, the rest untouched
    (TMP / "cart.py").write_text(FIXED)

    # B — the same thread in a new app-server, the findings not named again
    s = await start(path)
    t = time.time()
    try:
        r = await s.request("thread/resume", {"threadId": tid, "cwd": str(TMP), "sandbox": "read-only",
                                               "approvalPolicy": "never", "excludeTurns": True})
        say("B: thread/resume ok — %s" % sorted(r)[:8])
        ask = ("The doer has answered the findings of your review above:\n\"\"\"\n%s\n\"\"\"\n%s" % (ANSWER, FORMAT))
        await s.request("turn/start", {"threadId": tid, "input": [{"type": "text", "text": ask}]})
        got, steps = await turn_text(s, tid)
        say("B: %d commands, %.0f s:\n%s" % (steps, time.time() - t, got))
    except Exception as e:
        say("B: FAILED — %r" % e)
    await s.close()

    # C — a new thread, everything in the turn's text
    s = await start(path)
    t = time.time()
    th = await s.request("thread/start", {"cwd": str(TMP), "sandbox": "read-only", "approvalPolicy": "never"})
    tid2 = th["thread"]["id"]
    ask = ("You reviewed a task another coding agent did in this folder and reported these findings:\n\n%s\n\n"
           "The doer has answered them:\n\"\"\"\n%s\n\"\"\"\n%s"
           % (CX.message(read["items"]).split("\n", 2)[2], ANSWER, FORMAT))
    await s.request("turn/start", {"threadId": tid2, "input": [{"type": "text", "text": ask}]})
    got, steps = await turn_text(s, tid2)
    say("C: %d commands, %.0f s:\n%s" % (steps, time.time() - t, got))
    try:
        say("limits:", CX.window(await s.request("account/rateLimits/read", None, timeout=10)))
    except Exception as e:
        say("limits: %r" % e)
    await s.close()
    after = subprocess.run(["git", "-C", str(TMP), "status", "--short"], capture_output=True, text=True).stdout.strip()
    say("the folder after (the probe's own fix only):", after)


asyncio.run(main())
