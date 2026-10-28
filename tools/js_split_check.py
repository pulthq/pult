#!/usr/bin/env python3
"""Pult: the app's split into modules only moved its lines (review 2026-10-27, 6.4) — as tools/split_check.py does for
the daemon. Against app.js at <commit>: every line of the modules made since and of app.js now — leaving out what a move
adds (the header comment at a module's top, its imports, `export { … }`) and blank lines — is a line of that app.js,
each used once and in the same order within each file; and the modules import no app.js and form no cycle.

  python3 tools/js_split_check.py <commit>      # e.g. the commit before the move
"""
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATIC = "relay/web/static"
IMPORT = re.compile(r'^import \{[^}]*\} from "([^"]+)";$')
EXPORT = re.compile(r"^export \{[^}]*\};$")


def git(*args):
    return subprocess.run(["git", "-C", str(ROOT), *args], capture_output=True, text=True, check=True).stdout


def kept(text, new):
    """The lines a move carried, as (line, number): imports, exports and blank lines left out; in a new module also
    the comment lines on top, before its first import."""
    out, top = [], new
    for no, line in enumerate(text.split("\n"), 1):
        if top and line.startswith("//"):
            continue
        top = False
        if not line.strip() or IMPORT.match(line) or EXPORT.match(line):
            continue
        out.append((line, no))
    return out


def main(argv):
    if len(argv) != 2:
        print(__doc__.strip().splitlines()[-1].strip(), file=sys.stderr)
        return 2
    base = argv[1]
    then = set(git("ls-tree", "-r", "--name-only", base, "--", STATIC).split())
    old = kept(git("show", "%s:%s/app.js" % (base, STATIC)), False)
    files = sorted(p.relative_to(ROOT).as_posix() for p in (ROOT / STATIC).rglob("*.js"))
    files = [f for f in files if f == STATIC + "/app.js" or f not in then]
    used = [None] * len(old)
    where = {}                                     # old line text → its positions, in order
    for i, (line, _) in enumerate(old):
        where.setdefault(line, []).append(i)
    bad = []
    graph = {}
    for f in files:
        text = (ROOT / f).read_text(encoding="utf-8")
        here = Path(f).parent
        graph[f] = [(here / m.group(1)).as_posix() for m in map(IMPORT.match, text.split("\n")) if m]
        last = -1
        for line, no in kept(text, f != STATIC + "/app.js"):
            spot = next((i for i in where.get(line, []) if i > last and used[i] is None), None)
            if spot is None:
                bad.append("%s:%d — not a line of app.js at %s (or out of its order): %s" % (f, no, base, line.strip()[:100]))
                break
            used[spot], last = f, spot
    left = [old[i] for i, u in enumerate(used) if u is None]
    if left and not bad:
        bad.append("%d line(s) of app.js at %s are in no file now, the first — %d: %s"
                   % (len(left), base, left[0][1], left[0][0].strip()[:100]))
    norm = lambda p: str(Path(p).resolve().relative_to(ROOT)) if (ROOT / p).exists() else p
    for f, deps in graph.items():
        for d in deps:
            if f != STATIC + "/app.js" and norm(d) == STATIC + "/app.js":
                bad.append("%s imports app.js — the entry imports the modules, never the other way" % f)
    seen, stack = set(), []

    def visit(f):
        if f in stack:
            bad.append("an import cycle: " + " → ".join(stack[stack.index(f):] + [f]))
            return
        if f in seen:
            return
        seen.add(f)
        stack.append(f)
        for d in graph.get(f, []):
            if norm(d) in graph:
                visit(norm(d))
        stack.pop()
    for f in graph:
        visit(f)
    if bad:
        print("\n".join(bad))
        return 1
    counts = {f: sum(1 for u in used if u == f) for f in files}
    print("only moved: %d lines of app.js at %s — %s" % (len(old), base, ", ".join(
        "%s %d" % (f[len(STATIC) + 1:], n) for f, n in counts.items())))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
