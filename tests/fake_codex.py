"""A stand-in for Codex's program — the tests' and the stand's (stage M, step 1): `--version`, `app-server
generate-json-schema --out <folder>` (only what pult_codex.schema_ok looks for) and `app-server`, speaking as much of its
protocol as a review needs: initialize, account/read, thread/start, review/start with its items and turn/completed,
account/rateLimits/read. Standard library only.

FAKE_CODEX_CONF names a JSON file that shapes it, read anew on every start: version; schema — "old" leaves out the custom
review target; login — false: not signed in; fail — a codexErrorInfo ("usageLimitExceeded", "unauthorized") or "other";
wait — seconds the review takes; hang — seconds it stays silent before going on (past a test's timeout); ask — it
asks an approval of its own; steps — commands it runs; review — its answer; log — a file where
every request lands as a JSON line (the tests read the sandbox and the instructions there). launcher(folder, conf) makes
the command that runs it on any system — a shell script, or a .cmd on Windows."""
import json
import os
import sys
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


def serve(c):
    def say(m):
        sys.stdout.write(json.dumps(m, ensure_ascii=False) + "\n")
        sys.stdout.flush()

    def note(m):
        if c.get("log"):
            with open(c["log"], "a", encoding="utf-8") as f:
                f.write(json.dumps(m, ensure_ascii=False) + "\n")
    cwd = os.getcwd()
    for line in sys.stdin:
        try:
            m = json.loads(line)
        except ValueError:
            continue
        note(m)
        meth, i, prm = m.get("method"), m.get("id"), m.get("params") or {}
        if i is None or not meth:                       # a notification, or the answer to a request of its own
            continue
        if meth == "initialize":
            say({"id": i, "result": {"userAgent": "fake_codex/0"}})
        elif meth == "account/read":
            say({"id": i, "result": {"account": None if c.get("login") is False else {"type": "chatgpt", "planType": "plus"},
                                     "requiresOpenaiAuth": True}})
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
                info = c["fail"] if c["fail"] != "other" else "internalServerError"
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
