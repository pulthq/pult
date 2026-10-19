"""Pult: the load Claude's sessions put on the computer — processor and memory — counted from one snapshot of the
processes (pult_os.processes). Standard library only; nothing here asks the system anything.

A session is its claude process and everything under it. The commands Claude runs are child shells of claude,
`zsh -c '… eval '<command>' < /dev/null && pwd -P >| /tmp/claude-…-cwd'`, a single quote in the command written as
'"'"' (Claude Code 2.1.301, tests/probe_load.py) — so a background task is found by its command's text. Subagents and
workflows have no process of their own: they think on Anthropic's servers, and the commands they run are children of
the same claude.
"""
import os
import re

LOCAL = ("shell", "monitor")     # background tasks that are processes on the computer
NOTABLE_CPU = 5.0                # % of one core: a process that is not Claude's command is listed from here
NOTABLE_MEM = 100 << 20          # bytes: … or from here
IDLE_CPU = 0.5                   # % of the computer: a session below this, with no command running, is resting
EVAL = re.compile(r"""\beval '((?:'"'"'|[^'])*)'""")
SESSION_ARG = re.compile(r"--(?:resume|session-id)[= ]([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})")
INTERPRETERS = ("node", "python", "bun", "deno", "npx", "uv", "ruby", "java", "bash", "sh", "zsh")


def children(procs):
    kids = {}
    for pid, d in procs.items():
        if d["ppid"] != pid:
            kids.setdefault(d["ppid"], []).append(pid)
    return kids


def tree(root, kids):
    """The root and everything under it."""
    out, seen, todo = [], set(), [root]
    while todo:
        p = todo.pop()
        if p in seen:
            continue
        seen.add(p)
        out.append(p)
        todo.extend(kids.get(p, ()))
    return out


def total(procs, pids):
    """The sum over processes: cpu — % of one core, mem — bytes now, peak — the sum of each process's own peak (an
    upper bound when there are several), cpu_time — seconds since each started, finished children included."""
    rows = [procs[p] for p in pids if p in procs]
    peaks = [d.get("peak") or d["mem"] for d in rows]
    times = [d["cpu_time"] for d in rows if d.get("cpu_time") is not None]
    return {"cpu": sum(d["cpu"] for d in rows), "mem": sum(d["mem"] for d in rows),
            "peak": sum(peaks) if any(d.get("peak") for d in rows) else None,
            "cpu_time": sum(times) if times else None, "n": len(rows)}


def view(t, cores):
    """For the app: the processor as a share of the whole computer (it adds up to the computer's own figure), the
    cores that share keeps busy, whole bytes and seconds."""
    cores = cores or 1
    return {"cpu": round(t["cpu"] / cores, 1), "cores": round(t["cpu"] / 100, 1), "mem": int(t["mem"]),
            "peak": int(t["peak"]) if t.get("peak") is not None else None,
            "cpu_time": int(t["cpu_time"]) if t.get("cpu_time") is not None else None, "n": t.get("n", 0)}


def short(s, n=160):
    s = " ".join((s or "").split())
    return s if len(s) <= n else s[:n - 1] + "…"


def quoted(cmd):
    return "eval '" + cmd.replace("'", "'\"'\"'") + "'"


def bash_command(args):
    """The command Claude runs in this shell — the text inside eval '…' — or None: not one of Claude's commands."""
    m = EVAL.search(args or "")
    if not m or "claude" not in args[m.end():]:
        return None
    return m.group(1).replace("'\"'\"'", "'")


def program(args):
    """A process that is not one of Claude's commands (an MCP server, a helper): only the program's name, with the
    script for an interpreter — its other arguments may hold keys."""
    parts = (args or "").split()
    if not parts:
        return "?"
    name = os.path.basename(parts[0])
    if name.lower().startswith(INTERPRETERS):
        script = next((os.path.basename(x) for x in parts[1:] if not x.startswith("-")), None)
        if script:
            return name + " " + script
    return name


def is_claude(args):
    return os.path.basename((args or "").split(" ", 1)[0]) == "claude"


def session_arg(args):
    """The session a claude process continues or starts (--resume / --session-id), or None."""
    m = SESSION_ARG.search(args or "")
    return m.group(1) if m else None


def squash(s):
    return re.sub(r"[\s'\"\\]+", "", s or "")       # spaces and quotes aside: the same command quoted another way


def find(procs, root, kids, command, used=()):
    """The shell that runs a background task's command, under the session's claude, or None."""
    if not command or root not in procs:
        return None
    want, loose, near = quoted(command), squash(command), None
    for pid in tree(root, kids)[1:]:
        if pid in used:
            continue
        args = procs[pid]["cmd"]
        if want in args:
            return pid
        if near is None and len(loose) >= 8:
            c = bash_command(args)
            if c is not None and squash(c) == loose:
                near = pid
    return near


def session(procs, root, kids, cores, bg=()):
    """One session: its claude with everything under it, and what runs under it — each command Claude runs (marked
    with its background task's id) and any other notable process."""
    used, mark = set(), {}
    for b in bg:
        if b.get("type", "shell") in LOCAL:
            p = find(procs, root, kids, b.get("command"), used)
            if p:
                used.add(p)
                mark[p] = b.get("id")
    cmds = []
    for pid in kids.get(root, ()):
        d = procs[pid]
        sub = tree(pid, kids)
        t = total(procs, sub)
        c = bash_command(d["cmd"])
        if c is None and t["cpu"] < NOTABLE_CPU and t["mem"] < NOTABLE_MEM:
            continue
        cmds.append(dict(view(t, cores), started=d["started"], claude=c is not None,
                         text=short(c) if c is not None else program(d["cmd"]),
                         bg=next((mark[p] for p in sub if p in mark), None)))
    cmds.sort(key=lambda x: (-x["cpu"], -x["mem"]))
    s = dict(view(total(procs, tree(root, kids)), cores), pid=root, started=procs[root]["started"], cmds=cmds)
    s["idle"] = s["cpu"] < IDLE_CPU and not any(x["claude"] for x in cmds)
    return s


def task(procs, root, kids, cores, b, seen=None, used=None):
    """One background task for the app's card: what it is, since when, and — for a process on the computer — its
    processor and memory now, its processor time and memory peak; found=False — no such process (it has ended)."""
    kind = b.get("type") or "shell"
    what, cmd = b.get("description") or "", b.get("command") or ""
    d = {"id": b.get("id"), "type": kind, "what": short(what or cmd, 200),
         "cmd": short(cmd, 400) if cmd and cmd != what else "", "since": seen}
    if kind not in LOCAL:
        d["remote"] = True
        return d
    used = set() if used is None else used
    pid = find(procs, root, kids, cmd, used) if root else None
    if pid is None:
        d["found"] = False
        return d
    used.add(pid)
    d.update(view(total(procs, tree(pid, kids)), cores), found=True, since=procs[pid]["started"])
    return d
