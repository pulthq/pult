"""Every check of the app in Chrome, each on a stand of its own, in one go (review 2026-10-27, Т9).

  ~/.local/share/pult/venv/bin/python tools/check.py            all of them, ~6 min
  ~/.local/share/pult/venv/bin/python tools/check.py copy tags  only these

Each stand gets a free port and is stopped by its own pid — never `pkill`, other sessions may run stands of their own;
Chrome gets a free DevTools port (tools/_cdp.py). Screenshots go to a temporary folder, printed at the end. Not here:
voice_check (a recording and a Groq key), update_live (a second Pult as a real service), the pictures (media.py).
Exit 1 when any check failed."""
import os
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import _cdp

ROOT = Path(__file__).resolve().parent.parent
PY = sys.executable
# check: the stand's switches, what the check takes — "out" (the stand's output) or the name of a URL it prints — and
# its own arguments after that. None: the check raises the stands it needs itself
CHECKS = {
    "memory": ({"STAND_LANG": "ru", "STAND_MEMORY": "96"}, "out", []),
    "power": ({"STAND_LANG": "ru"}, "out", []),   # 2026-11-12: Home's limit and machine, the battery, the machine's name
    "fileview": ({"STAND_FILES": "1"}, "SESS", []),
    "compose": ({"STAND_LANG": "ru"}, "out", []),
    "newproject": ({"STAND_LANG": "ru"}, "NEWPROJ", []),
    "editor": ({}, "SESS", []),
    "viewer": ({}, "SESS", []),
    "files": ({"STAND_LANG": "ru"}, "SESS4", []),
    "tags": ({"STAND_TAGS": "1", "STAND_LANG": "ru"}, "out", []),
    "tags-job": ({"STAND_TAGS": "1", "STAND_TAGJOB": "1", "STAND_LANG": "ru"}, "out", []),     # T2: a made-up model sorts
    "choice": ({"STAND_LANG": "ru", "STAND_CCM": "none"}, "out", []),   # the default's logic, on the names without versions
    "models": ({"STAND_LANG": "ru", "STAND_TAB": "1"}, "out", []),     # Claude Code's names with versions, a tab's own (Q173)
    "models-none": ({"STAND_LANG": "ru", "STAND_CCM": "none"}, "out", ["none"]),   # … no list known yet: as before
    "ticks": ({"STAND_TICKS": "4", "STAND_LANG": "ru"}, "out", []),
    "copy": ({"STAND_COPY": "1", "STAND_ASK2": "1", "STAND_LANG": "ru"}, "out", []),
    "ask": ({"STAND_ASK2": "1", "STAND_LANG": "ru"}, "out", []),
    "advice": ({"STAND_ADVICE": "1", "STAND_LANG": "ru"}, "out", []),
    "queue": ({"STAND_QUEUE": "1"}, "out", []),
    "layers-home": ({"STAND_TAGS": "1", "STAND_LANG": "ru"}, "out", ["home"]),
    "layers-session": ({"STAND_LANG": "ru"}, "out", ["session"]),
    "clip": ({"STAND_LANG": "ru"}, "out", []),
    "spend": ({"STAND_LANG": "ru"}, "USAGE", []),
    "pins": ({"STAND_TAGS": "1", "STAND_HOMES": "1", "STAND_PINS": "blog,shop", "STAND_HIDES": "desk", "STAND_LANG": "ru"}, "out", []),   # stage Zh
    "msgcopy": ({"STAND_LANG": "ru"}, "out", []),                  # stage Zh, step 3: a slide copies Claude's message
    "second": ({"STAND_SECOND": "1", "STAND_LANG": "ru"}, "out", []),   # stage M, step 1: Codex's second opinion
    # stage M, M4.2: Claude's second opinion on a task Codex did
    "claude_second": ({"STAND_VENDORS": "1", "STAND_CLREVIEW": "1", "STAND_LANG": "ru"}, "out", []),
    "changes": ({"STAND_SECOND": "allowed", "STAND_CHANGES": "1", "STAND_LANG": "ru"}, "out", []),   # block 5: what a task changed
    "codexerrors": ({"STAND_SECOND": "allowed", "STAND_SECOND_FAIL": "serverOverloaded", "STAND_LANG": "ru"}, "out", []),
    "vendors": ({"STAND_VENDORS": "1", "STAND_HOMES": "1", "STAND_LANG": "ru"}, "out", []),   # stage M, step 2
    "local": ({"STAND_LOCAL": "1", "STAND_HOMES": "1", "STAND_LANG": "ru"}, "out", []),   # stage M, step 6: one's own model
    "local-down": ({"STAND_LOCAL": "down", "STAND_HOMES": "1", "STAND_LANG": "ru"}, "out", ["down"]),   # … its server silent
    "panel": ({"STAND_LOCAL": "on", "STAND_LOCAL_MANY": "1", "STAND_LOCAL_SRV": "1", "STAND_PULL_S": "0.1", "STAND_HOMES": "1",
               "STAND_LANG": "ru"}, "out", []),                               # stage M, step 6.4: the local model's panel
    "panel-busy": ({"STAND_LOCAL": "on", "STAND_LOCAL_MANY": "1", "STAND_LOCAL_SRV": "busy", "STAND_HOMES": "1", "STAND_LANG": "ru"},
                   "out", ["busy"]),                                          # … a model in the card's memory
    "tune": ({"STAND_LOCAL": "on", "STAND_LOCAL_MANY": "1", "STAND_LOCAL_SRV": "1", "STAND_HOMES": "1", "STAND_LANG": "ru"},
             "out", []),                                                      # stage M, step 6.5: a model's settings
    "gotit": ({"STAND_REPORT": "1", "STAND_LANG": "ru"}, "out", []),   # every finished task waits for "Got it" (2026-10-30)
    "states": ({"STAND_TAGS": "1", "STAND_ASK2": "1", "STAND_LANG": "ru"}, "out", []),   # a task's state in colour (Q110–Q112)
    "worktime": ({"STAND_VENDORS": "1", "STAND_HOMES": "1", "STAND_REPORT": "1", "STAND_LANG": "ru"}, "out", []),   # one clock per task (Q117)
    "ctx": ({"STAND_VENDORS": "1", "STAND_HOMES": "1", "STAND_REPORT": "1", "STAND_CTX": "1", "STAND_LANG": "ru"}, "out", []),   # the context's line (Q151)
    "paste": ({"STAND_HOMES": "1", "STAND_LANG": "ru"}, "out", []),      # a screenshot by ⌘V or a drag (Q127)
    "helpers": ({"STAND_HELPERS": "1", "STAND_LANG": "ru"}, "out", []),  # helpers in the background, seen mid-turn (Q128)
    "settings": ({"STAND_VENDORS": "1", "STAND_HOMES": "1", "STAND_UPD": "ready", "STAND_PARTS": "lag", "STAND_LANG": "ru"}, "out", []),   # block 4: Settings as a menu
    "projset": ({"STAND_VENDORS": "1", "STAND_HOMES": "1", "STAND_REPORT": "1", "STAND_DESK": "deepseek", "STAND_LANG": "ru"}, "out", []),   # 7.2
    "parts": None,
    "update": None,
    "vcheck": None,
}


def stand(env, out):
    """A stand on a free port, its lines going to `out`; → its process, once it has printed its URLs."""
    e = dict(os.environ, STAND_PORT=str(_cdp.any_port()), HOLD="900", **env)
    with open(out, "w") as fh:
        p = subprocess.Popen([PY, str(ROOT / "tools" / "stand.py")], cwd=ROOT, env=e, stdout=fh,
                             stderr=subprocess.STDOUT, start_new_session=True)
    for _ in range(240):
        if "HOME http" in Path(out).read_text(errors="replace"):
            return p
        if p.poll() is not None:
            break
        time.sleep(0.25)
    stop(p)
    raise RuntimeError("the stand didn't come up — " + out)


def stop(p):
    try:
        os.killpg(p.pid, signal.SIGTERM)
        p.wait(15)
    except (ProcessLookupError, subprocess.TimeoutExpired):
        try:
            os.killpg(p.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass


def run(name, shots):
    script = str(ROOT / "tools" / (name.split("-")[0] + "_check.py"))
    spec = CHECKS[name]
    out_dir = shots / name
    out_dir.mkdir(parents=True, exist_ok=True)
    if spec is None:
        return subprocess.run([PY, script, str(out_dir)], cwd=ROOT, capture_output=True, text=True, timeout=1200)
    env, takes, extra = spec
    out = str(shots / (name + ".stand"))
    p = stand(env, out)
    try:
        arg = out if takes == "out" else _cdp.stand_urls(out)[takes]
        rest = extra or [str(out_dir)]
        return subprocess.run([PY, script, arg, *rest], cwd=ROOT, capture_output=True, text=True, timeout=900)
    finally:
        stop(p)


def main(names):
    bad = [n for n in names if n not in CHECKS]
    if bad:
        sys.exit("no such check: %s (there are: %s)" % (", ".join(bad), ", ".join(CHECKS)))
    shots = Path(tempfile.mkdtemp(prefix="pult-checks-"))
    failed = []
    for name in names or list(CHECKS):
        t0 = time.time()
        try:
            r = run(name, shots)
            lines = (r.stdout + r.stderr).strip().split("\n")
            code = r.returncode
        except (RuntimeError, subprocess.TimeoutExpired) as e:
            lines, code = [str(e)], 1
        oks = sum(ln.startswith("ok") for ln in lines)
        print("%-15s %s  %3d ok  %3d s" % (name, "ok  " if code == 0 else "FAIL", oks, time.time() - t0), flush=True)
        if code:
            failed.append(name)
            for ln in [x for x in lines if not x.startswith("ok") and x.strip()][-8:]:
                print("    " + ln[:200], flush=True)
    print("screenshots and stands' output:", shots)
    if failed:
        print("failed:", ", ".join(failed))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
