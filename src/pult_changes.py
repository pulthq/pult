"""What a task changed in its project's folder, read from git — the app's "Changes" (review 2026-11-11, block 5: the
view alone, nothing here writes): the files that differ from the commit the folder stood at when the task began
(pult_codex.git_base — the same point a second opinion counts from), committed since or not, the ones not in git yet
among them, each with its added and removed lines; and one file's change line by line. The parts:
  • changed — the list: the task's own files first (the ones its tools wrote and its turns touched), then whatever else
    changed in the folder since — commands, other sessions; a folder that is a repository and the repositories inside
    it (pult_codex.nested_repos) alike;
  • diff — one file of that list as rows: a line kept, added or removed with its numbers on both sides, and how many
    unchanged lines lie between two pieces; with `full` — the whole file with its changes in place.
The probe (2026-11-11, git 2.54): `git diff --raw --numstat -z -M <base>` gives both the kind and the counts in one
call, a rename as three fields, a binary file as "-"; files not in git yet come only from `git ls-files --others`;
30–50 ms on a project of 40 changed files. Git runs with GIT_OPTIONAL_LOCKS=0 — reading must never hold the index
under a session that is committing — and takes every path as it is written (GIT_LITERAL_PATHSPECS: "a[1].txt" is a
name, not a pattern). Standard library only. Design: docs/project.html, stage Ch2, block 5.
"""
import os
import re
import signal
import subprocess
import threading

import pult_codex as CX
import pult_files as F

GIT_TIME = 10                      # s one git call may take
FILES_MAX = 400                    # files listed at most, the task's own first
NEW_FILE_MAX = 256 * 1024          # a file not in git yet: its lines are counted up to this size,
NEW_READ_MAX = 4 * 1024 * 1024     # and this much is read for one list in all — past it a new file has no count
DIFF_MAX = 1024 * 1024             # bytes of one file's change taken from git; the rest is left out (cut)
ROW_MAX = 600                      # characters of one line on the screen
FULL = 1000000                     # lines of context that make "the whole file"
KEEP = 20                          # s the line under a task's outcome stays as counted (longer after a slow count)
WAIT = 0.7                         # s a task's screen waits for that count; a slower one comes by itself later
KEPT, ADDED, REMOVED, GAP = 0, 1, 2, 3     # a row's kind: [kind, its number before, its number now, the line]
_DIFF = ["diff", "--no-ext-diff", "--no-textconv", "--no-color", "-M", "--relative"]
_HUNK = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")


def _stop(p):
    """git and whatever it started, at once: a child that outlives it keeps its output open, and the read waits on."""
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/PID", str(p.pid), "/T", "/F"], capture_output=True, timeout=10)
        else:
            os.killpg(p.pid, signal.SIGKILL)
    except (OSError, subprocess.SubprocessError):
        p.kill()


def _git(cwd, args, limit=None):
    """→ (git's output as bytes, whether it was longer than limit). None for the output: git isn't there, failed or
    took longer than GIT_TIME."""
    try:
        p = subprocess.Popen(["git", "-C", cwd, "-c", "core.quotepath=off", *args], stdout=subprocess.PIPE,
                             stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL, start_new_session=os.name != "nt",
                             env=dict(os.environ, GIT_OPTIONAL_LOCKS="0", GIT_LITERAL_PATHSPECS="1"))
    except OSError:
        return None, False
    timer = threading.Timer(GIT_TIME, _stop, [p])
    timer.start()
    try:
        out = p.stdout.read(limit + 1) if limit else p.stdout.read()
        more = bool(limit) and len(out) > limit
        if more:
            _stop(p)
        p.stdout.close()
        code = p.wait()
    finally:
        timer.cancel()
    if code != 0 and not more:
        return None, False
    return (out[:limit] if more else out), more


def _tracked(top, base):
    """The files under `top` that differ from commit `base`, committed since or not: [{p, was, st, add, del, bin}] —
    p from `top`, was — a renamed file's earlier path, st — git's letter (M, A, D, R, T), add and del — lines (None
    for a binary one). None: git didn't answer. A repository inside (a submodule's link) is not a file: left out."""
    out, _ = _git(top, _DIFF + ["--raw", "--numstat", "-z", base, "--", "."])
    if out is None:
        return None
    toks, kinds, rows, i = out.decode("utf-8", "replace").split("\0"), {}, [], 0
    try:
        while i < len(toks):
            tok = toks[i]
            if tok.startswith(":"):                    # ":100644 100644 <id> <id> R082", then the path or two
                f = tok.split(" ")
                n = 2 if f[-1][:1] in "RC" else 1
                kinds[toks[i + n]] = "S" if "160000" in (f[0][1:], f[1]) else f[-1][:1]
                i += 1 + n
            elif tok.count("\t") >= 2:                 # "12\t3\tpath", or "12\t3\t" and the two paths of a rename
                a, d, p = tok.split("\t", 2)
                was = None
                if not p:
                    was, p = toks[i + 1], toks[i + 2]
                    i += 2
                rows.append({"p": p, "was": was, "add": None if a == "-" else int(a), "del": None if d == "-" else int(d),
                             "bin": a == "-"})
                i += 1
            else:
                i += 1
    except (IndexError, ValueError):
        pass                                           # an answer cut short: what was read whole stays
    return [dict(r, st=kinds.get(r["p"], "M")) for r in rows if kinds.get(r["p"]) != "S"]


def _lines(blob):
    return blob.count(b"\n") + (1 if blob and not blob.endswith(b"\n") else 0)


def _untracked(top, first, room):
    """The files under `top` that git doesn't know yet (and doesn't ignore): [{p, st: "A", new: True, add, del: 0, bin}].
    Their lines are counted by reading them — the ones in `first` (the task's own) before the rest, a file up to
    NEW_FILE_MAX, `room[0]` bytes in all (shared by the whole list); past that add is None. A link is one line: where it
    points, never followed."""
    out, _ = _git(top, ["ls-files", "--others", "--exclude-standard", "-z", "--", "."])
    if out is None:
        return None
    names = [n for n in out.decode("utf-8", "replace").split("\0") if n and not n.endswith("/")]
    rows = {}
    for n in sorted(names, key=lambda n: n not in first):
        row = {"p": n, "was": None, "st": "A", "new": True, "add": None, "del": 0, "bin": False}
        path = os.path.join(top, n)
        try:
            if os.path.islink(path):
                row["add"] = 1
            else:
                size = os.path.getsize(path)
                with open(path, "rb") as f:
                    head = f.read(8000)
                    if b"\0" in head:                  # git's own test for a binary file
                        row.update({"bin": True, "del": None})
                    elif size <= NEW_FILE_MAX and size <= room[0]:
                        row["add"] = _lines(head + f.read())
                        room[0] -= size
        except OSError:
            pass
        rows[n] = row
    return [rows[n] for n in names]


def _parts(project, t0, own):
    """The repositories a task's changes are read from: [(prefix, folder, base)] — the project's own folder when it is
    in git, and each repository inside it where the task changed files."""
    root = os.path.realpath(project)
    base = CX.git_base(root, t0)
    parts = [("", root, base)] if base else []
    for r in CX.nested_repos(root, own, t0):
        if r.get("base"):
            parts.append((r["dir"] + "/", os.path.join(root, *r["dir"].split("/")), r["base"]))
    return parts


def _all(project, t0, own):
    """Every changed file with where it was read from (_top, _rel, _base) — or None: nothing of the folder is in git,
    or git didn't answer."""
    parts = _parts(project, t0, own)
    if not parts:
        return None
    own, room, files = set(own), [NEW_READ_MAX], []
    for prefix, top, base in parts:
        first = {p[len(prefix):] for p in own if p.startswith(prefix)}
        got, new = _tracked(top, base), _untracked(top, first, room)
        if got is None or new is None:
            return None
        for r in got + new:
            p, was = prefix + r["p"], prefix + r["was"] if r["was"] else None
            files.append(dict(r, p=p, was=was, own=p in own or was in own, _top=top, _rel=r["p"], _was=r["was"], _base=base,
                              lock=F.secret_like(p) or bool(was and F.secret_like(was))))
    files.sort(key=lambda f: (not f["own"], f["p"].casefold()))
    return files


def _public(f):
    return {k: v for k, v in f.items() if not k.startswith("_")}


def changed(project, t0, own=()):
    """What changed in the project's folder since the task began (t0, epoch): {"files": [{p, was, st, add, del, bin,
    new, own, lock}] — FILES_MAX at most, "total": how many there are, "mine": totals of the task's own}. own — the
    paths known as the task's, from the folder: those files come first and are marked; the rest is everything else
    that changed there — commands, other sessions. lock — the name looks like keys or settings: counted, never shown.
    None — nothing of the folder is in git, or git didn't answer."""
    files = _all(project, t0, own)
    if files is None:
        return None
    return {"files": [_public(f) for f in files[:FILES_MAX]], "total": len(files),
            "mine": totals([f for f in files if f["own"]])}


def totals(files):
    """{n, add, del} of a list of changed files."""
    return {"n": len(files), "add": sum(f["add"] or 0 for f in files), "del": sum(f["del"] or 0 for f in files)}


def _cut(s):
    s = s[:-1] if s.endswith("\r") else s
    return s if len(s) <= ROW_MAX else s[:ROW_MAX - 1] + "…"


def rows_of(text):
    """A unified diff as rows: [KEPT, n before, n now, line], [ADDED, None, n now, line], [REMOVED, n before, None,
    line], and between two pieces [GAP, None, None, how many unchanged lines lie there]. Git's own lines — the header,
    "\\ No newline at end of file" — are not rows."""
    rows, a, b, inside = [], 1, 1, False
    for line in text.split("\n"):
        m = _HUNK.match(line)
        if m:
            start = int(m.group(1)) + (1 if m.group(2) == "0" else 0)      # "-5,0": nothing of the old side, after line 5
            if start > a:
                rows.append([GAP, None, None, start - a])
            a, b, inside = start, int(m.group(3)) + (1 if m.group(4) == "0" else 0), True
        elif not inside or not line:
            continue
        elif line[0] == " ":
            rows.append([KEPT, a, b, _cut(line[1:])])
            a, b = a + 1, b + 1
        elif line[0] == "+":
            rows.append([ADDED, None, b, _cut(line[1:])])
            b += 1
        elif line[0] == "-":
            rows.append([REMOVED, a, None, _cut(line[1:])])
            a += 1
        elif line[0] != "\\":                          # the next file's header (a file that became a link is two)
            a, b, inside = 1, 1, False
    return rows


def diff(project, t0, p, own=(), full=False):
    """One changed file line by line: its row of the list and {"rows": rows_of's, "cut": only the start is here,
    "full": the whole file was asked for}. A binary file and one that looks like keys or settings have no rows.
    {"same": True} — the file didn't change since the task began (or isn't in git); None — git didn't answer."""
    files = _all(project, t0, set(own) | {p})
    if files is None:
        return None
    f = next((x for x in files if x["p"] == p), None)
    if not f:
        return {"same": True}
    out = dict(_public(f), rows=[], cut=False, full=bool(full))
    if f["lock"] or f["bin"]:
        return out
    if f.get("new"):
        path = os.path.join(f["_top"], f["_rel"])
        try:
            if os.path.islink(path):
                text, more = "→ " + os.readlink(path), False
            else:
                with open(path, "rb") as fh:
                    blob = fh.read(DIFF_MAX + 1)
                more = len(blob) > DIFF_MAX
                if more:
                    blob = blob[:blob.rfind(b"\n", 0, DIFF_MAX) + 1 or DIFF_MAX]
                text = blob.decode("utf-8", "replace")
        except OSError:
            return {"same": True}                      # gone since it was listed
        lines = text.split("\n")
        if len(lines) > 1 and not lines[-1]:
            lines.pop()
        out.update(rows=[[ADDED, None, n, _cut(s)] for n, s in enumerate(lines, 1)], cut=more)
        return out
    names = ([f["_was"]] if f["_was"] else []) + [f["_rel"]]
    blob, more = _git(f["_top"], _DIFF + ["--unified=%d" % (FULL if full else 3), f["_base"], "--", *names], DIFF_MAX)
    if blob is None:
        return None
    if more:
        blob = blob[:blob.rfind(b"\n") + 1]
    out.update(rows=rows_of(blob.decode("utf-8", "replace")), cut=more)
    return out
