#!/usr/bin/env python3
"""Pult's reader beside Ollama (stage M, step 6.4): how much room the disk of the computer Ollama runs on has, and what
its graphics card holds — what Ollama itself doesn't say (0.40.14: /api/status answers about the cloud only). Pult reads
it through the same tunnel as Ollama, and draws it in Resources → Local model.

systemd starts it for each connection to 127.0.0.1:11436 (ollama-info.socket, Accept=yes): it reads the request's head
and drops it, answers one JSON and exits — nothing stays in memory, no request has parameters, nothing anyone sends is
run. By hand: `python3 ollama-info.py --print` prints the same JSON.

  {"v": 1, "name": "homelab", "disk": {"label": "C:", "total": bytes, "free": bytes, "path": "/mnt/c"},
   "gpu": [{"name": "NVIDIA GeForce RTX 4070 Ti SUPER", "total": bytes, "used": bytes}]}

The disk: in WSL, Windows's C: (/mnt/c) — the Linux disk is a file on it that grows, and its own free space says nothing;
elsewhere the folder Ollama keeps its models in (OLLAMA_MODELS, or its usual places), else /. PULT_INFO_DISK and
PULT_INFO_LABEL say otherwise. The name: PULT_INFO_NAME (the installer's --name), else the host's own. Standard library
only: it runs on the server, not in Pult's environment."""
import json
import os
import select
import shutil
import socket
import subprocess
import sys

MODELS = ("/usr/share/ollama/.ollama/models", "/var/lib/ollama/.ollama/models", "/var/lib/ollama",
          os.path.expanduser("~/.ollama/models"))
SMI = ("/usr/lib/wsl/lib/nvidia-smi", "nvidia-smi")        # WSL keeps its own copy outside PATH
HEAD_MAX, HEAD_WAIT = 8192, 5                               # bytes and seconds of a request's head: then it is answered


def in_wsl():
    try:
        with open("/proc/sys/kernel/osrelease") as f:
            return "microsoft" in f.read().lower()
    except OSError:
        return False


def disk():
    where = os.environ.get("PULT_INFO_DISK")
    if not where:
        if in_wsl() and os.path.isdir("/mnt/c"):
            where = "/mnt/c"
        else:
            where = os.environ.get("OLLAMA_MODELS") or next((p for p in MODELS if os.path.isdir(p)), "/")
    while True:                                  # a folder this user can't enter: the nearest one it can, same disk
        try:
            u = shutil.disk_usage(where)
            break
        except OSError:
            if where in ("/", ""):
                return None
            where = os.path.dirname(where.rstrip("/")) or "/"
    label = os.environ.get("PULT_INFO_LABEL") or ("C:" if where == "/mnt/c" else where)
    return {"label": label[:12], "total": u.total, "free": u.free, "path": where}


def gpus():
    """NVIDIA cards as nvidia-smi sees them (memory in MiB → bytes); none — an empty list."""
    for smi in SMI:
        exe = smi if os.path.isabs(smi) else shutil.which(smi)
        if not exe or not os.path.exists(exe):
            continue
        try:
            out = subprocess.run([exe, "--query-gpu=name,memory.total,memory.used", "--format=csv,noheader,nounits"],
                                 capture_output=True, text=True, timeout=8).stdout
        except (OSError, subprocess.SubprocessError):
            return []
        cards = []
        for line in out.splitlines():
            parts = [x.strip() for x in line.rsplit(",", 2)]            # a card's name may hold a comma
            if len(parts) == 3 and parts[1].isdigit() and parts[2].isdigit():
                cards.append({"name": parts[0][:60], "total": int(parts[1]) * 1048576, "used": int(parts[2]) * 1048576})
        return cards
    return []


def facts():
    return {"v": 1, "name": (os.environ.get("PULT_INFO_NAME") or socket.gethostname()).strip()[:40],
            "disk": disk(), "gpu": gpus()}


def answer(inp, out):
    """One connection: the request's head is read — at most HEAD_MAX bytes, HEAD_WAIT seconds — and dropped; a GET (or a
    HEAD) gets the facts, anything else 405."""
    head, fd = b"", inp.fileno()
    while b"\r\n\r\n" not in head and b"\n\n" not in head and len(head) < HEAD_MAX:
        if not select.select([fd], [], [], HEAD_WAIT)[0]:
            break
        chunk = os.read(fd, 1024)
        if not chunk:
            break
        head += chunk
    method = head.split(b" ", 1)[0]
    if method not in (b"GET", b"HEAD"):
        body, status = b'{"error": "only GET"}', b"405 Method Not Allowed"
    else:
        body, status = json.dumps(facts()).encode(), b"200 OK"
    out.write(b"HTTP/1.1 %s\r\nContent-Type: application/json\r\nContent-Length: %d\r\nCache-Control: no-store\r\n"
              b"Connection: close\r\n\r\n" % (status, len(body)) + (b"" if method == b"HEAD" else body))
    out.flush()


if __name__ == "__main__":
    if "--print" in sys.argv:
        print(json.dumps(facts(), indent=1))
    else:
        answer(sys.stdin.buffer, sys.stdout.buffer)
