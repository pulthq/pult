"""Probe: Codex as the one who does a task (stage M, step M4) — what Pult would drive through `codex app-server`, on the
owner's ChatGPT subscription: a thread in a project's folder that may write there (workspace-write) and asks before
anything else (approvalPolicy "untrusted"); the requests it sends for approval and questions, and Pult's answers; the
turn's items as the app would show them; a continuation after the app-server is started anew (Pult restarts); a
message in the middle of a turn (turn/steer); a stop (turn/interrupt); the thread's history read back (thread/read) and
its file on disk; time, memory, the plan's windows. Changes nothing outside a temporary folder.

Run (uses a little of the ChatGPT plan, ~2–4 min):
  ~/.local/share/pult/venv/bin/python tests/probe_codex_doer.py
"""
import asyncio, json, os, subprocess, sys, tempfile, time
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
import pult_codex as CX  # noqa: E402

TMP = Path(os.path.realpath(tempfile.mkdtemp(prefix="pult-cxdo-")))
T0 = time.time()


def say(*a):
    print("%5.1f" % (time.time() - T0), *a, flush=True)


class Server(CX.AppServer):
    """The review's client, but the server's own requests — approvals, questions — come to the probe to answer."""

    def __init__(self, proc):
        super().__init__(proc)
        self.reqs = asyncio.Queue()

    async def _read(self):
        try:
            while True:
                try:
                    line = await self.p.stdout.readline()
                except ValueError:
                    continue
                if not line:
                    break
                try:
                    m = json.loads(line)
                except ValueError:
                    continue
                if not isinstance(m, dict):
                    continue
                if "method" in m and "id" in m:
                    self.reqs.put_nowait(m)
                    self.events.put_nowait({"method": "(request) " + str(m["method"]), "params": m.get("params")})
                elif "id" in m:
                    fut = self.wait.pop(m["id"], None)
                    if fut is not None and not fut.done():
                        fut.set_result(m)
                elif "method" in m:
                    self.events.put_nowait(m)
        except (ConnectionError, asyncio.CancelledError):
            pass
        finally:
            self.events.put_nowait(None)


def rss(pid):
    """Memory of a process and its children, MB (ps)."""
    try:
        out = subprocess.run(["ps", "-A", "-o", "pid=,ppid=,rss="], capture_output=True, text=True).stdout
    except OSError:
        return 0
    kids, mem = {}, {}
    for ln in out.splitlines():
        p, pp, r = (int(x) for x in ln.split())
        kids.setdefault(pp, []).append(p)
        mem[p] = r
    tot, todo = 0, [pid]
    while todo:
        p = todo.pop()
        tot += mem.get(p, 0)
        todo += kids.get(p, [])
    return tot // 1024


async def start():
    s = await Server.start(CX.find(os.environ), str(TMP), {k: v for k, v in os.environ.items() if not k.startswith("PULT_")})
    await s.request("initialize", {"clientInfo": {"name": "pult-probe", "title": "Pult probe", "version": "0"}})
    await s.send({"method": "initialized"})
    acc = await s.request("account/read", {})
    say("app-server pid %d · account: %s" % (s.p.pid, (acc.get("account") or {}).get("type")))
    return s


async def turn(s, tid, text, answer=None, steer=None, stop_after=None, label=""):
    """One turn: what came (methods), the server's requests and our answers, its status and time."""
    t = time.time()
    got = await s.request("turn/start", {"threadId": tid, "input": [{"type": "text", "text": text}]})
    turn_id = (got.get("turn") or {}).get("id")
    seen, items, status, peak, steered = Counter(), Counter(), None, 0, False
    while True:
        try:
            m = await asyncio.wait_for(s.events.get(), 1.0)
        except asyncio.TimeoutError:
            m = False
        peak = max(peak, rss(s.p.pid))
        if steer and not steered and time.time() - t > steer[0]:
            steered = True
            r = await s.request("turn/steer", {"threadId": tid, "expectedTurnId": turn_id,
                                               "input": [{"type": "text", "text": steer[1]}]})
            say("  steer sent →", json.dumps(r)[:120])
        if stop_after and time.time() - t > stop_after and status is None:
            stop_after = None
            r = await s.request("turn/interrupt", {"threadId": tid, "turnId": turn_id})
            say("  interrupt sent →", json.dumps(r)[:120])
        while not s.reqs.empty():
            q = s.reqs.get_nowait()
            meth, prm = q["method"], q.get("params") or {}
            res = answer(meth, prm) if answer else {"decision": "decline"}
            say("  ASKED %s: %s → %s" % (meth, json.dumps({k: prm.get(k) for k in ("command", "cwd", "reason", "grantRoot",
                                                                                   "questions")}, ensure_ascii=False)[:400],
                                       json.dumps(res, ensure_ascii=False)))
            await s.send({"id": q["id"], "result": res})
        if m is False:
            continue
        if m is None:
            say("  app-server ended:", s.tail())
            break
        meth = m.get("method")
        seen[meth] += 1
        prm = m.get("params") or {}
        if meth == "item/completed":
            it = prm.get("item") or {}
            items[it.get("type")] += 1
            if it.get("type") == "agentMessage":
                say("  says:", (it.get("text") or "")[:160].replace("\n", " "))
            elif it.get("type") == "commandExecution":
                say("  ran:", (it.get("command") or "")[:100], "· exit", it.get("exitCode"), "·", it.get("status"))
            elif it.get("type") == "fileChange":
                say("  files:", [c.get("path") for c in it.get("changes") or []], "·", it.get("status"))
        elif meth == "turn/completed":
            tr = prm.get("turn") or {}
            status = tr.get("status")
            say("  turn %s: %s in %.0f s (durationMs %s) · error %s" % (label, status, time.time() - t, tr.get("durationMs"),
                                                                        json.dumps(tr.get("error"))[:200]))
            break
    say("  items:", dict(items), "· events:", dict(seen.most_common(12)), "· peak memory %d MB" % peak)
    return status


def accept(meth, prm):
    if meth == "item/tool/requestUserInput":
        qs = prm.get("questions") or []
        return {"answers": {q["id"]: {"answers": [((q.get("options") or [{}])[0] or {}).get("label") or "hi"]} for q in qs}}
    return {"decision": "accept"}


async def main():
    say("Codex %s · folder %s" % (CX.version(CX.find(os.environ)), TMP))
    subprocess.run(["git", "init", "-q", str(TMP)], check=True)
    s = await start()
    th = await s.request("thread/start", {"cwd": str(TMP), "sandbox": "workspace-write", "approvalPolicy": "untrusted"})
    tid = th["thread"]["id"]
    say("thread %s · model %s · effort %s · file %s" % (tid, th.get("model"), th.get("reasoningEffort"), th["thread"].get("path")))
    await turn(s, tid, "Ask me with your question tool whether the greeting should be 'hi' or 'hello', then run the shell "
                       "command `python3 -c 'print(6*7)'` and create hello.txt containing the greeting. Reply briefly.",
               answer=accept, label="A (a question, a command, a file)")
    await s.close()
    say("— the app-server closed and started anew, the thread resumed")
    s = await start()
    r = await s.request("thread/resume", {"threadId": tid, "cwd": str(TMP), "sandbox": "workspace-write", "approvalPolicy": "untrusted"})
    say("resumed · turns so far: %d" % len((r.get("thread") or {}).get("turns") or []))
    await turn(s, tid, "Append a line 'bye' to hello.txt. Reply briefly.", answer=accept, label="B (after a restart)")
    await turn(s, tid, "Run `sleep 6` in the shell, then create steer.txt with the word one. Reply briefly.", answer=accept,
               steer=(2.5, "Change of plan: write the word two into steer.txt instead."), label="C (a message mid-turn)")
    await turn(s, tid, "Run `sleep 40` in the shell, then reply done.", answer=accept, stop_after=6, label="D (stopped)")
    rd = await s.request("thread/read", {"threadId": tid, "includeTurns": True})
    turns = (rd.get("thread") or {}).get("turns") or []
    say("history: %d turns · %s" % (len(turns), [(t.get("status"), Counter(i.get("type") for i in t.get("items") or []).most_common())
                                                  for t in turns]))
    try:
        lim = await s.request("account/rateLimits/read", None, timeout=10)
        say("plan's windows:", CX.window(lim))
    except CX.CodexError as e:
        say("windows:", e)
    await s.close()
    for f in ("hello.txt", "steer.txt"):
        p = TMP / f
        say("%s: %r" % (f, p.read_text() if p.exists() else None))
    path = th["thread"].get("path")
    if path and os.path.exists(path):
        say("thread file: %s · %d KB · %d lines" % (path, os.path.getsize(path) // 1024, sum(1 for _ in open(path, "rb"))))


asyncio.run(main())
