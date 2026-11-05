"""A stand-in for Codex's program — the tests' and the stand's (stage M, step 1): `--version`, `app-server
generate-json-schema --out <folder>` (only what pult_codex.schema_ok looks for) and `app-server`, speaking as much of its
protocol as a review needs: initialize, account/read, thread/start, review/start with its items and turn/completed,
account/rateLimits/read. Standard library only.

FAKE_CODEX_CONF names a JSON file that shapes it, read anew on every start: version; schema — "old" leaves out the custom
review target; login — false: not signed in; fail — a codexErrorInfo ("usageLimitExceeded", "unauthorized") or "other";
wait — seconds the review takes; hang — seconds it stays silent before going on (past a test's timeout); ask — it
asks an approval of its own; steps — commands it runs; review — its answer; big — bytes its answer to account/read
grows by (longer than a test's LINE_MAX); log — a file where
every request lands as a JSON line (the tests read the sandbox and the instructions there; initialize — with the PULT_
names of its environment). launcher(folder, conf) makes
the command that runs it on any system — a shell script, or a .cmd on Windows.

As the one who does a task (stage M, M4.1): thread/start and thread/resume (a history file like Codex's own, in conf's
"sessions" folder; resume_bytes — the history thread/resume returns unless asked for excludeTurns), turn/start — its
turn runs beside the reading of requests, so it can wait for the answer to an approval it asks and hear turn/steer and
turn/interrupt — and model/list. conf "doer" shapes the turn: approve —
"command" or "file", what it asks before it acts; file — the file it writes (hello.txt); wait — seconds the turn
works; fail — a codexErrorInfo the turn ends with; say — its last words."""
import json
import os
import queue
import sys
import threading
import time

REVIEW = """Made-up review: two real problems in the change.

Full review comments:

- [P1] Rebuild only the new item's trigrams — {cwd}/search/index.py:41-58
  The whole index is rebuilt on every new product: with 40,000 products that is a couple of seconds without writes.
  Add the new item's trigrams instead.

- [P2] Skip fuzzy search for one or two letters — {cwd}/search/query.py:12-12
  A query of one or two letters returns half the catalogue; search with typos only from three characters, and test it."""


def conf():
    try:
        with open(os.environ["FAKE_CODEX_CONF"], encoding="utf-8") as f:
            return json.load(f)
    except (KeyError, OSError, ValueError):
        return {}


def launcher(folder, conf_path):
    """A command that runs this stand-in with its settings file, on any system: → its path."""
    me, py = os.path.abspath(__file__), sys.executable
    if os.name == "nt":
        path = os.path.join(folder, "codex.cmd")
        with open(path, "w") as f:
            f.write('@echo off\r\nset "FAKE_CODEX_CONF=%s"\r\n"%s" "%s" %%*\r\n' % (conf_path, py, me))
    else:
        path = os.path.join(folder, "codex")
        with open(path, "w") as f:
            f.write('#!/bin/sh\nFAKE_CODEX_CONF="%s" exec "%s" "%s" "$@"\n' % (conf_path, py, me))
        os.chmod(path, 0o755)
    return path


def schema(out, c):
    """Just the parts pult_codex.schema_ok reads, shaped as Codex writes them."""
    def variants(kinds):
        return {"oneOf": [{"properties": {"method": {"enum": [k]}}} for k in kinds]}
    custom = [] if c.get("schema") == "old" else [
        {"properties": {"type": {"enum": ["custom"]}, "instructions": {"type": "string"}}}]
    files = {
        "ClientRequest.json": variants(["initialize", "account/read", "thread/start", "review/start", "model/list"]),
        "ServerNotification.json": variants(["item/started", "item/completed", "turn/completed", "error"]),
        "v2/ReviewStartParams.json": {"definitions": {"ReviewTarget": {"oneOf": [
            {"properties": {"type": {"enum": ["uncommittedChanges"]}}}] + custom}}},
        "v2/ItemCompletedNotification.json": {"definitions": {"ThreadItem": {"oneOf": [
            {"properties": {"type": {"enum": ["exitedReviewMode"]}, "review": {"type": "string"}}}]}}},
        "v2/ThreadStartParams.json": {"properties": {"cwd": {}, "sandbox": {}, "approvalPolicy": {}},
                                      "definitions": {"SandboxMode": {"enum": ["read-only", "workspace-write"]},
                                                      "AskForApproval": {"oneOf": [{"enum": ["untrusted", "never"]}]}}},
    }
    for name, doc in files.items():
        path = os.path.join(out, name)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            json.dump(doc, f)


class Doer:
    """A turn of a task, beside the reading of requests: it may ask and wait, and hears steer and interrupt."""

    def __init__(self, c, say, cwd):
        self.c, self.say, self.cwd = c, say, cwd
        self.waits, self.answers = {}, {}
        self.steered, self.stop = [], threading.Event()
        self.thread = self.path = None
        self.n = 0
        self.asks = 900

    def history(self, kind, what, **payload):
        if self.path:
            with open(self.path, "a", encoding="utf-8") as f:
                f.write(json.dumps({"timestamp": time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime()), "type": kind,
                                    "payload": dict(payload, type=what)}, ensure_ascii=False) + "\n")

    def open(self, prm, tid=None):
        folder = self.c.get("sessions") or os.path.join(self.cwd, ".fake-codex")
        os.makedirs(folder, exist_ok=True)
        self.thread = tid or "th-%d" % int(time.time() * 1000)
        self.path = os.path.join(folder, "rollout-fake-%s.jsonl" % self.thread)
        if not os.path.exists(self.path):
            self.history("session_meta", None, id=self.thread, cwd=prm.get("cwd"))
        return {"thread": {"id": self.thread, "path": self.path, "turns": []}, "model": prm.get("model") or "gpt-5.6-sol",
                "reasoningEffort": "high", "cwd": prm.get("cwd"), "sandbox": {"type": prm.get("sandbox")},
                "approvalPolicy": prm.get("approvalPolicy")}

    def ask(self, method, params):
        """A request of its own; → Pult's answer (its result), waiting as long as the owner does."""
        self.asks += 1
        i, ev = self.asks, threading.Event()
        self.waits[i] = ev
        self.say({"id": i, "method": method, "params": params})
        ev.wait()
        return self.answers.pop(i, {})

    def run(self, text):
        d = (conf() or self.c).get("doer") or {}         # read anew each turn: a test changes the next one
        self.n += 1
        th, tu = self.thread, "tu-%d" % self.n
        self.stop.clear()
        self.say({"method": "turn/started", "params": {"threadId": th, "turn": {"id": tu, "status": "inProgress", "items": []}}})
        self.history("event_msg", "task_started", turn_id=tu)
        self.history("event_msg", "user_message", message=text)
        self.say({"method": "item/completed", "params": {"threadId": th, "turnId": tu, "item": {
            "type": "agentMessage", "id": "m0", "text": "Делаю."}}})
        self.history("event_msg", "agent_message", message="Делаю.")
        name = d.get("file", "hello.txt")
        path = os.path.join(self.cwd, name)
        allowed = True
        if d.get("approve") == "file":
            self.say({"method": "item/started", "params": {"threadId": th, "turnId": tu, "item": {
                "type": "fileChange", "id": "f1", "changes": [{"path": path, "kind": {"type": "add"}}], "status": "inProgress"}}})
            got = self.ask("item/fileChange/requestApproval", {"threadId": th, "turnId": tu, "itemId": "f1", "startedAtMs": 0})
            allowed = got.get("decision") in ("accept", "acceptForSession")
        elif d.get("approve") == "command":
            got = self.ask("item/commandExecution/requestApproval", {"threadId": th, "turnId": tu, "itemId": "c1", "startedAtMs": 0,
                                                                    "command": "/bin/zsh -lc 'curl -sI https://example.com'",
                                                                    "reason": "needs the network", "cwd": self.cwd})
            allowed = got.get("decision") in ("accept", "acceptForSession")
        if allowed:
            with open(path, "a", encoding="utf-8") as f:
                f.write("hi %d\n" % self.n)
            self.say({"method": "item/completed", "params": {"threadId": th, "turnId": tu, "item": {
                "type": "fileChange", "id": "f1", "changes": [{"path": path}], "status": "completed"}}})
            self.history("response_item", "custom_tool_call", call_id="call-%d" % self.n, name="exec",
                         input='const patch = "*** Begin Patch\\n*** Add File: %s\\n+hi\\n*** End Patch";\ntext(await tools.apply_patch(patch));' % path)
            self.say({"method": "item/completed", "params": {"threadId": th, "turnId": tu, "item": {
                "type": "commandExecution", "id": "c2", "command": "/bin/zsh -lc 'cat %s'" % name, "status": "completed"}}})
        end = time.time() + float(d.get("wait", 0.3))
        while time.time() < end and not self.stop.is_set():
            time.sleep(0.05)
        if self.stop.is_set():
            self.history("event_msg", "turn_aborted", turn_id=tu, reason="interrupted")
            self.say({"method": "turn/completed", "params": {"threadId": th, "turn": {"id": tu, "status": "interrupted", "items": []}}})
            return
        if d.get("fail"):
            err = d["fail"] if isinstance(d["fail"], dict) else {"message": "made-up failure: " + d["fail"],
                                                              "codexErrorInfo": d["fail"]}
            self.say({"method": "turn/completed", "params": {"threadId": th, "turn": {"id": tu, "status": "failed", "items": [], "error": err}}})
            return
        words = d.get("say", "Готово: записал %s." % name) + ("" if allowed else " Без файла: ты не разрешил.")
        if self.steered:
            words += " Учёл: " + "; ".join(self.steered)
            self.steered = []
        self.say({"method": "thread/tokenUsage/updated", "params": {"threadId": th, "turnId": tu, "tokenUsage": {
            "modelContextWindow": 258400, "total": {"totalTokens": 1200}, "last": {"totalTokens": 300}}}})
        self.say({"method": "item/completed", "params": {"threadId": th, "turnId": tu, "item": {
            "type": "agentMessage", "id": "m1", "text": words}}})
        self.history("event_msg", "agent_message", message=words)
        self.history("event_msg", "task_complete", turn_id=tu, last_agent_message=words)
        self.say({"method": "turn/completed", "params": {"threadId": th, "turn": {"id": tu, "status": "completed", "items": []}}})


def serve(c):
    lock = threading.Lock()

    def say(m):
        with lock:
            sys.stdout.write(json.dumps(m, ensure_ascii=False) + "\n")
            sys.stdout.flush()

    def note(m):
        if c.get("log"):
            with lock, open(c["log"], "a", encoding="utf-8") as f:
                f.write(json.dumps(m, ensure_ascii=False) + "\n")
    cwd = os.getcwd()
    doer = Doer(c, say, cwd)
    lines = queue.Queue()

    def pump():
        for ln in sys.stdin:
            lines.put(ln)
        lines.put(None)
    threading.Thread(target=pump, daemon=True).start()
    while True:
        line = lines.get()
        if line is None:
            break
        try:
            m = json.loads(line)
        except ValueError:
            continue
        meth, i, prm = m.get("method"), m.get("id"), m.get("params") or {}
        # initialize with Pult's names from its environment: what a command of the task's would get (pult send)
        note(dict(m, env={k: v for k, v in os.environ.items() if k.startswith("PULT_")}) if meth == "initialize" else m)
        if not meth and i in doer.waits:                # Pult's answer to a request of the doer's own
            doer.answers[i] = m.get("result") or {}
            doer.waits.pop(i).set()
            continue
        if i is None or not meth:                       # a notification, or the answer to a request of its own
            continue
        if meth == "thread/start" and prm.get("sandbox") == "workspace-write":
            say({"id": i, "result": doer.open(prm)})
        elif meth == "thread/resume":
            result = doer.open(prm, prm.get("threadId"))
            if c.get("resume_bytes") and not prm.get("excludeTurns"):
                result["thread"]["turns"] = [{"id": "old", "items": [
                    {"type": "agentMessage", "id": "old-message", "text": "x" * c["resume_bytes"]}]}]
            say({"id": i, "result": result})
        elif meth == "turn/start":
            text = " ".join(str(x.get("text") or "") for x in prm.get("input") or [] if isinstance(x, dict))
            say({"id": i, "result": {"turn": {"id": "tu-%d" % (doer.n + 1), "status": "inProgress", "items": []}}})
            threading.Thread(target=doer.run, args=(text,), daemon=True).start()
        elif meth == "turn/steer":
            doer.steered += [str(x.get("text") or "") for x in prm.get("input") or [] if isinstance(x, dict)]
            say({"id": i, "result": {"turnId": prm.get("expectedTurnId")}})
        elif meth == "turn/interrupt":
            doer.stop.set()
            say({"id": i, "result": {}})
        elif meth == "model/list":
            def levels(*names):
                return [{"reasoningEffort": n, "description": n} for n in names]
            say({"id": i, "result": {"data": [
                {"model": "gpt-5.6-mini", "isDefault": False, "hidden": False, "defaultReasoningEffort": "medium",
                 "supportedReasoningEfforts": levels("low", "medium", "high")},
                {"model": "gpt-5.6-sol", "isDefault": True, "hidden": False, "defaultReasoningEffort": "low",
                 "supportedReasoningEfforts": levels("low", "medium", "high", "xhigh", "max", "ultra")},
                {"model": "codex-internal", "isDefault": False, "hidden": True}]}})
        elif meth == "initialize":
            say({"id": i, "result": {"userAgent": "fake_codex/0"}})
        elif meth == "account/read":
            say({"id": i, "result": {"account": None if c.get("login") is False else {"type": "chatgpt", "planType": "plus"},
                                     "requiresOpenaiAuth": True, "pad": "x" * int(c.get("big") or 0)}})
        elif meth == "thread/start":
            say({"id": i, "result": {"thread": {"id": "th-1"}, "model": "gpt-5.6-sol", "reasoningEffort": "high",
                                     "cwd": prm.get("cwd"), "sandbox": {"type": prm.get("sandbox")},
                                     "approvalPolicy": prm.get("approvalPolicy")}})
        elif meth == "review/start":
            say({"id": i, "result": {"turn": {"id": "tu-1", "status": "inProgress", "items": []}, "reviewThreadId": "th-1"}})
            say({"method": "turn/started", "params": {"threadId": "th-1", "turn": {"id": "tu-1", "status": "inProgress", "items": []}}})
            say({"method": "item/started", "params": {"threadId": "th-1", "item": {"type": "enteredReviewMode", "id": "r0", "review": "x"}}})
            n = int(c.get("steps", 2))
            for k in range(n):
                time.sleep(float(c.get("wait", 0.2)) / max(1, n + 1))
                say({"method": "item/completed", "params": {"threadId": "th-1", "item": {
                    "type": "commandExecution", "id": "c%d" % k, "command": "git diff", "status": "completed"}}})
            if c.get("ask"):                                # a request of its own: Pult declines it
                say({"id": 99, "method": "item/commandExecution/requestApproval",
                     "params": {"threadId": "th-1", "turnId": "tu-1", "itemId": "c0", "command": "rm -rf x"}})
            if c.get("hang"):
                time.sleep(float(c["hang"]))
            time.sleep(float(c.get("wait", 0.2)) / max(1, n + 1))
            if c.get("fail"):
                info = c["fail"]
                err = {"message": "made-up failure: " + info, "codexErrorInfo": info}
                say({"method": "error", "params": {"threadId": "th-1", "turnId": "tu-1", "willRetry": False, "error": err}})
                say({"method": "turn/completed", "params": {"threadId": "th-1", "turn": {"id": "tu-1", "status": "failed",
                                                                                         "items": [], "error": err}}})
                continue
            text = c.get("review", REVIEW).replace("{cwd}", cwd)
            say({"method": "item/completed", "params": {"threadId": "th-1", "item": {"type": "exitedReviewMode", "id": "r1",
                                                                                     "review": text}}})
            say({"method": "turn/completed", "params": {"threadId": "th-1", "turn": {"id": "tu-1", "status": "completed",
                                                                                     "items": []}}})
        elif meth == "account/rateLimits/read":
            now = int(time.time())
            say({"id": i, "result": {"rateLimits": {"planType": "plus",
                                                    "primary": {"usedPercent": 12, "windowDurationMins": 300, "resetsAt": now + 3 * 3600},
                                                    "secondary": {"usedPercent": 30, "windowDurationMins": 10080, "resetsAt": now + 4 * 86400}}}})
        else:
            say({"id": i, "error": {"code": -32601, "message": "fake_codex: no " + str(meth)}})


def main():
    c = conf()
    a = sys.argv[1:]
    if a[:1] == ["--version"]:
        print("codex-cli " + c.get("version", "0.148.0-alpha.9"))
    elif a[:2] == ["app-server", "generate-json-schema"]:
        schema(a[a.index("--out") + 1], c)
    elif a[:1] == ["app-server"]:
        serve(c)
    else:
        sys.exit("fake_codex: %s?" % " ".join(a))


if __name__ == "__main__":
    main()
