#!/usr/bin/env python3
"""Pult's gateway beside ComfyUI (stage M, step 6.7; the owner, 2026-11-21: "as with Ollama, I'd like to manage the
local models from Pult without you, in ComfyUI too"; 2026-11-25: "music there as well"). Pictures and music on the
computer with the graphics card: which of the verified sets of models are on its disk, a download from that list, a
removal, the main one of each kind — and ComfyUI itself only while there is work. It grew from the gateway of lesson 4 of
the owner's course on local models (2026-11-05): what that one did it still does, at the same address, with
the same answers, so its client (img.py) keeps working.

It listens on 127.0.0.1 only (GATE_PORT, 8190): Pult reaches it through the same ssh tunnel as Ollama. Standard library
only — it runs on the server, not in Pult's environment; deploy/comfy-gate/install.sh installs it.

  GET  /health       ComfyUI's state, the job running, the card's memory (the first gateway's answer, and "v")
  GET  /models       the verified sets (sets.json), what of each is on the disk, the main one of each kind, the download
                     running, the room — the disk and the models' cap. Never starts ComfyUI.
  POST /image        {"prompt", "model"?, "width"?, "height"?, "steps"?, "seed"?} → PNG
  POST /audio        {"caption", "lyrics"?, "duration"?, "bpm"?, "language"?, "seed"?, "model"?} → MP3
  POST /pull         {"id", "ollama"?: bytes} — a set from Hugging Face, in the background, one at a time
  POST /pull/stop    stop it: what came stays, the next /pull goes on from there
  POST /remove       {"id"} — a set's files off the disk; a file another set still has stays
  POST /main         {"id"} — the set /image or /audio takes when the request names none
  POST /free         ComfyUI lets go of the card's memory now
  POST /start        ComfyUI for the browser (127.0.0.1:8188 through the tunnel); POST /stop — off now

The neighbours (the rules of a server shared with a family — lesson 4):
- before a job, Ollama's models leave the card: beside a drawing model they don't fit in 16 GB;
- ComfyUI not running and the card has less free than the set needs — no job: someone sits at that computer;
- a job that pushed Ollama's model out gives the card back at once: a task of Pult waits for its model;
- GATE_FREE_AFTER seconds of quiet — ComfyUI unloads its models, GATE_STOP_AFTER — it stops; the browser's work counts
  too (ComfyUI's queue and history);
- a picture or a song goes out in the answer and off the disk at once; a request's words never reach the log.
Downloads: only the files of sets.json, only from Hugging Face (GATE_HF), each checked by its sha256 before any job can
use it; the disk keeps GATE_KEEP_GB free, and all models together — Ollama's, GATE_ALSO's folders and ComfyUI's — stay
within GATE_CAP_GB. Nothing anyone sends is run: no command, no ComfyUI extension, no file from elsewhere, no path outside
the models' folders.
"""
import hashlib
import json
import os
import random
import re
import secrets
import shutil
import signal
import socketserver
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

VERSION = 2                       # lesson 4's gateway was the first; Pult reads it in /health and /models
HERE = Path(__file__).resolve().parent
HOME = Path.home()
E = os.environ.get

HOST = E("GATE_HOST", E("GEN_HOST", "127.0.0.1"))
PORT = int(E("GATE_PORT", E("GEN_PORT", "8190")))
COMFY_DIR = Path(E("COMFY_DIR", str(HOME / "llm/comfyui/current"))).expanduser()      # ComfyUI's program (main.py)
COMFY_PY = os.path.expanduser(E("COMFY_PY", str(HOME / "llm/comfyui/venv/bin/python")))
COMFY_BASE = Path(os.path.expanduser(E("COMFY_BASE", str(HOME / "llm/comfyui/data")))) if E("COMFY_BASE", "x") else None
COMFY_PORT = int(E("COMFY_PORT", "8188"))
# --offline — no paid cloud nodes and no internet from the browser; --disable-pinned-memory — pinned memory doesn't fit
# the service's memory ceiling; --vram-headroom 1 — a gigabyte of the card stays free for Windows
COMFY_ARGS = E("COMFY_ARGS", "--offline --disable-auto-launch --disable-pinned-memory --vram-headroom 1").split()
COMFY_CMD = E("COMFY_CMD", "")                   # a whole command instead of ComfyUI — for the tests
OLLAMA = E("OLLAMA_URL", "http://127.0.0.1:11434")
NVIDIA_SMI = E("NVIDIA_SMI", "/usr/lib/wsl/lib/nvidia-smi")
SETS = Path(E("GATE_SETS", str(HERE / "sets.json")))
STATE = Path(os.path.expanduser(E("GATE_STATE", "~/.local/state/pult-comfy-gate")))
DISK = E("GATE_DISK", "")                        # the disk whose room counts; "" — Windows's C: in WSL, else the models'
KEEP = int(float(E("GATE_KEEP_GB", "60")) * 1e9)  # the disk keeps this much free after a download (the owner's rule)
CAP = int(float(E("GATE_CAP_GB", "0")) * 1e9)    # all models together, at most; 0 — no such rule
ALSO = [Path(os.path.expanduser(p)) for p in E("GATE_ALSO", "").split(":") if p.strip()]   # more models' folders
HF = E("GATE_HF", "https://huggingface.co").rstrip("/")
MIN_FREE_MIB = int(E("GEN_MIN_FREE_MIB", "0"))  # one threshold for every set instead of each set's own (the tests)
FREE_AFTER = int(E("GATE_FREE_AFTER", E("GEN_FREE_AFTER", "120")))
STOP_AFTER = int(E("GATE_STOP_AFTER", E("GEN_STOP_AFTER", "600")))   # as Ollama's keep_alive: ten minutes at most
START_TIMEOUT = int(E("GEN_START_TIMEOUT", "300"))
JOB_TIMEOUT = int(E("GEN_JOB_TIMEOUT", "900"))
VRAM_WAIT = float(E("GEN_VRAM_WAIT", "15"))       # the card's memory comes back from Ollama a while after its unload
FREE_WAIT = float(E("GEN_FREE_WAIT", "8"))        # how long to wait for ComfyUI to give the card back
WATCH_EVERY = float(E("GEN_WATCH_EVERY", "5"))
PULL_TRIES = int(E("GATE_PULL_TRIES", "30"))     # a file's download picked up again after a broken connection
PULL_WAIT = float(E("GATE_PULL_WAIT", "5"))       # s before the next try (doubles, up to a minute)
LOG = STATE / "comfyui.log"
COMFY = "http://127.0.0.1:%d" % COMFY_PORT
BODY_MAX = 64 * 1024
CHUNK = 1024 * 1024
OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))   # localhost — never through a proxy
AGENT = "pult-comfy-gate/%d" % VERSION

# The verified sets (sets.json) are checked against these when the gateway starts: a set names only ComfyUI's own nodes
# below, loads only its own files, takes only its kind's values, and its files come only from Hugging Face, by commit.
FOLDERS = ("checkpoints", "diffusion_models", "text_encoders", "vae", "loras")
NODES = {"UNETLoader", "CLIPLoader", "DualCLIPLoader", "VAELoader", "CLIPTextEncode", "ConditioningZeroOut",
         "EmptySD3LatentImage", "EmptyFlux2LatentImage", "KSampler", "KSamplerSelect", "RandomNoise", "CFGGuider",
         "SamplerCustomAdvanced", "Flux2Scheduler", "ModelSamplingAuraFlow", "VAEDecode", "SaveImage",
         "TextEncodeAceStepAudio1.5", "EmptyAceStep1.5LatentAudio", "VAEDecodeAudio", "SaveAudioAdvanced"}
LOADS = {"unet_name": "diffusion_models", "clip_name": "text_encoders", "clip_name1": "text_encoders",
         "clip_name2": "text_encoders", "vae_name": "vae", "ckpt_name": "checkpoints", "lora_name": "loras"}
SAMPLERS = ("KSampler", "SamplerCustomAdvanced")
# a kind: where ComfyUI's history keeps its output, the nodes that save it, the values a request fills in, its type
KINDS = {"image": {"out": "images", "save": ("SaveImage",), "ctype": "image/png",
                   "fill": ("prompt", "width", "height", "steps", "seed", "prefix")},
         "audio": {"out": "audio", "save": ("SaveAudioAdvanced",), "ctype": "audio/mpeg",
                   "fill": ("caption", "lyrics", "duration", "bpm", "language", "seed", "prefix")}}
# ACE-Step 1.5's languages, as ComfyUI 0.44.0 lists them (comfy_extras/nodes_ace.py)
LANGS = ("ar", "az", "bg", "bn", "ca", "cs", "da", "de", "el", "en", "es", "fa", "fi", "fr", "he", "hi", "hr", "ht", "hu",
         "id", "is", "it", "ja", "ko", "la", "lt", "ms", "ne", "nl", "no", "pa", "pl", "pt", "ro", "ru", "sa", "sk", "sr",
         "sv", "sw", "ta", "te", "th", "tl", "tr", "uk", "ur", "vi", "yue", "zh", "unknown")
ID_RE = re.compile(r"[a-z0-9][a-z0-9.-]{0,39}")
FILE_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,150}\.safetensors")
REPO_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,95}/[A-Za-z0-9][A-Za-z0-9._-]{0,95}")
PATH_RE = re.compile(r"(?:[A-Za-z0-9._-]+/){0,4}[A-Za-z0-9._-]+")


class GateError(Exception):
    """An answer that isn't the work: HTTP code, a short word Pult knows ("busy", "room"…), and the words for a human."""

    def __init__(self, code, why, text):
        super().__init__(text)
        self.code, self.why, self.text = code, why, text


def say(text):
    print(text, flush=True)                              # the service's journal puts the time


def gib(mib):
    return "%.1f" % (mib / 1024)


def gb(b):
    return "%.1f GB" % (b / 1e9)


def http(url, body=None, timeout=10, raw=False):
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(url, data=data, method="GET" if body is None else "POST",
                                 headers={} if body is None else {"Content-Type": "application/json"})
    with OPENER.open(req, timeout=timeout) as r:
        blob = r.read()
    if raw:
        return blob
    return json.loads(blob) if blob.strip() else {}


# ---------- the verified sets ----------

def load_sets(path=SETS):
    """sets.json → {id: set} in its order, or ValueError saying what is wrong. A set: {"id", "kind": image | audio,
    "name", "files": [{"folder", "name", "size", "sha256", "repo", "rev", "path"}], "graph": ComfyUI's workflow in its
    API format with "$name" where a request's value goes, "vram_mib": the card's free memory it needs to start,
    "defaults": {…}, and facts for Pult to show ("maker", "released", "license", "params", "steps", "vram_gb", …)}."""
    d = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(d, dict) or not isinstance(d.get("sets"), list):
        raise ValueError("no list of sets")
    out, seen = {}, {}
    for s in d["sets"]:
        sid = s.get("id") if isinstance(s, dict) else None
        if not isinstance(sid, str) or not ID_RE.fullmatch(sid) or sid in out:
            raise ValueError("a set's id: %r" % (sid,))
        kind = KINDS.get(s.get("kind"))
        if not kind or not isinstance(s.get("name"), str) or not 0 < len(s["name"]) <= 60:
            raise ValueError("%s: kind or name" % sid)
        files = s.get("files")
        if not isinstance(files, list) or not 0 < len(files) <= 8:
            raise ValueError("%s: files" % sid)
        own = set()
        for f in files:
            ok = (isinstance(f, dict) and f.get("folder") in FOLDERS and isinstance(f.get("name"), str)
                  and FILE_RE.fullmatch(f["name"]) and isinstance(f.get("size"), int) and f["size"] > 0
                  and isinstance(f.get("sha256"), str) and re.fullmatch(r"[0-9a-f]{64}", f["sha256"])
                  and isinstance(f.get("repo"), str) and REPO_RE.fullmatch(f["repo"]) and ".." not in f["repo"]
                  and isinstance(f.get("rev"), str) and re.fullmatch(r"[0-9a-f]{40}", f["rev"])
                  and isinstance(f.get("path"), str) and PATH_RE.fullmatch(f["path"]) and ".." not in f["path"]
                  and f["path"].rsplit("/", 1)[-1] == f["name"])
            if not ok:
                raise ValueError("%s: a file: %r" % (sid, f))
            key = (f["folder"], f["name"])
            if key in seen and (seen[key]["size"], seen[key]["sha256"]) != (f["size"], f["sha256"]):
                raise ValueError("%s: %s/%s differs from another set's file of that name" % (sid, *key))
            seen[key] = f
            own.add(key)
        graph = s.get("graph")
        if not isinstance(graph, dict) or not graph:
            raise ValueError("%s: graph" % sid)
        saves = 0
        for nid, node in graph.items():
            if not isinstance(node, dict) or node.get("class_type") not in NODES or not isinstance(node.get("inputs"), dict):
                raise ValueError("%s: node %s — not one of the nodes a set may have" % (sid, nid))
            saves += node["class_type"] in kind["save"]
            for k, v in node["inputs"].items():
                if isinstance(v, str) and v[:1] == "$" and v[1:] not in kind["fill"]:
                    raise ValueError("%s: node %s fills %s — not a value of its kind" % (sid, nid, v))
                if k in LOADS and (not isinstance(v, str) or (LOADS[k], v) not in own):
                    raise ValueError("%s: node %s loads %r — not a file of the set" % (sid, nid, v))
                if k == "filename_prefix" and v != "$prefix":
                    raise ValueError("%s: node %s saves under a name of its own" % (sid, nid))
        if saves != 1:
            raise ValueError("%s: one saving node, not %d" % (sid, saves))
        if not isinstance(s.get("vram_mib"), int) or not 1024 <= s["vram_mib"] <= 98304:
            raise ValueError("%s: vram_mib" % sid)
        if not isinstance(s.get("defaults", {}), dict):
            raise ValueError("%s: defaults" % sid)
        out[sid] = s
    return out


def models_root():
    return (COMFY_BASE if COMFY_BASE else COMFY_DIR) / "models"


def output_dir():
    return (COMFY_BASE if COMFY_BASE else COMFY_DIR) / "output"


def tree_bytes(root):
    """Bytes of every file under a folder (the apparent size); a folder that isn't there — 0."""
    n = 0
    for dirpath, _, names in os.walk(root):
        for name in names:
            try:
                st = os.lstat(os.path.join(dirpath, name))
            except OSError:
                continue
            if not os.path.islink(os.path.join(dirpath, name)):
                n += st.st_size
    return n


def in_wsl():
    try:
        with open("/proc/sys/kernel/osrelease") as f:
            return "microsoft" in f.read().lower()
    except OSError:
        return False


def disk_room():
    """The disk the models take room on: GATE_DISK; in WSL Windows's C: — the Linux disk is a file on it that grows,
    and its own free space says nothing; else the models' folder. → {"label", "free", "total"} or None."""
    where = DISK or ("/mnt/c" if in_wsl() and os.path.isdir("/mnt/c") else str(models_root()))
    while True:
        try:
            u = shutil.disk_usage(where)
            break
        except OSError:
            if where in ("/", ""):
                return None
            where = os.path.dirname(where.rstrip("/")) or "/"
    return {"label": "C:" if where == "/mnt/c" else where[:24], "free": u.free, "total": u.total}


class Disk:
    """What lies in the models' folders — a look at most every few seconds: the tab asks every 15 s."""

    def __init__(self):
        self.lock = threading.Lock()
        self.at, self.seen = 0.0, None

    def drop(self):
        with self.lock:
            self.at = 0.0

    def look(self):
        with self.lock:
            if self.seen is not None and time.monotonic() - self.at < 5:
                return self.seen
        root, files, parts = models_root(), {}, {}
        for folder in FOLDERS:
            d = root / folder
            try:
                names = os.listdir(d)
            except OSError:
                continue
            for name in names:
                p = d / name
                try:
                    if not p.is_file() or p.is_symlink():
                        continue
                    size = p.stat().st_size
                except OSError:
                    continue
                if name.endswith(".part"):
                    parts[(folder, name[:-5])] = size
                else:
                    files[(folder, name)] = size
        seen = {"files": files, "parts": parts, "comfy": tree_bytes(root), "also": sum(tree_bytes(p) for p in ALSO)}
        with self.lock:
            self.at, self.seen = time.monotonic(), seen
        return seen


disk = Disk()


def has(f, seen):
    return seen["files"].get((f["folder"], f["name"])) == f["size"]


def ready(s, seen):
    return all(has(f, seen) for f in s["files"])


def keeps(sid, key, seen):
    """The other sets that need this file of a set and are on the disk by a file of their own — one this set hasn't —
    whole or in part. A file the two only share says nothing: Z-Image's encoder is FLUX.2 klein's too, and with Z-Image
    alone on the disk it goes when Z-Image goes."""
    mine = {(f["folder"], f["name"]) for f in sets[sid]["files"]}
    return [x["id"] for x in sets.values() if x["id"] != sid
            and any((f["folder"], f["name"]) == key for f in x["files"])
            and any((f["folder"], f["name"]) not in mine and (has(f, seen) or (f["folder"], f["name"]) in seen["parts"])
                    for f in x["files"])]


def frees(s, seen):
    """Bytes a set's removal gives back: its files on the disk that no other set there has; and their pieces."""
    n = 0
    for f in s["files"]:
        key = (f["folder"], f["name"])
        if keeps(s["id"], key, seen):
            continue
        n += f["size"] if has(f, seen) else seen["parts"].get(key, 0)
    return n


def need(s, seen):
    """Bytes still to download for a set: its missing files, less the pieces already there."""
    return sum(f["size"] - min(seen["parts"].get((f["folder"], f["name"]), 0), f["size"])
               for f in s["files"] if not has(f, seen))


def mains():
    try:
        d = json.loads((STATE / "main.json").read_text())
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def main_of(kind, seen):
    """The set a request of this kind gets when it names none: the one made main, while it is whole on the disk; else
    the first whole one of the list."""
    sid = mains().get(kind)
    if sid in sets and sets[sid]["kind"] == kind and ready(sets[sid], seen):
        return sid
    return next((x["id"] for x in sets.values() if x["kind"] == kind and ready(x, seen)), None)


# ---------- the card, Ollama, ComfyUI ----------

def vram():
    """→ (taken, total) MiB of the whole card — with Windows's programs; (None, None) — not known."""
    try:
        out = subprocess.run([NVIDIA_SMI, "--query-gpu=memory.used,memory.total", "--format=csv,noheader,nounits"],
                             capture_output=True, text=True, timeout=15).stdout
        used, total = (int(x) for x in out.strip().splitlines()[0].split(","))
        return used, total
    except (OSError, ValueError, IndexError, subprocess.SubprocessError):
        return None, None


def unload_ollama():
    """Ollama's models out of the card: beside a drawing one they don't fit. → their names."""
    try:
        names = [m.get("name") or m.get("model") for m in http(OLLAMA + "/api/ps", timeout=5).get("models") or []]
    except (OSError, ValueError):
        return []                                        # no Ollama, or it doesn't answer — nothing to unload
    for name in names:
        try:
            http(OLLAMA + "/api/generate", {"model": name, "keep_alive": 0}, timeout=30)
        except (OSError, ValueError):
            pass
    deadline = time.monotonic() + 20
    while names and time.monotonic() < deadline:
        try:
            if not http(OLLAMA + "/api/ps", timeout=5).get("models"):
                break
        except (OSError, ValueError):
            break
        time.sleep(0.5)
    if names:
        say("unloaded from Ollama: " + ", ".join(names))
    return names


def ollama_rough():
    """Ollama's models on the disk when Pult hasn't said: their sizes by digest. A copy made with another context has
    a digest of its own and the same weights — this counts them twice; Pult's own count knows better."""
    try:
        ms = http(OLLAMA + "/api/tags", timeout=5).get("models") or []
    except (OSError, ValueError):
        return 0
    return sum({m.get("digest"): m.get("size") or 0 for m in ms if isinstance(m, dict)}.values())


def need_vram(mib):
    """Enough of the card free to start ComfyUI for this set? Waits up to VRAM_WAIT s: memory comes back slowly."""
    mib = MIN_FREE_MIB or mib
    used, total = vram()
    if used is None:
        say("nvidia-smi didn't answer — the card isn't checked")
        return
    deadline = time.monotonic() + VRAM_WAIT
    while total - used < mib and time.monotonic() < deadline:
        time.sleep(1)
        used, total = vram()
        if used is None:
            return
    if total - used < mib:
        raise GateError(409, "card", "The graphics card is busy: %s GiB free of %s, %s needed — someone is using that "
                                     "computer. Try later." % (gib(total - used), gib(total), gib(mib)))


def comfy_version():
    try:
        m = re.search(r"__version__\s*=\s*[\"']([\w.+-]{1,20})[\"']", (COMFY_DIR / "comfyui_version.py").read_text())
        return m.group(1) if m else None
    except OSError:
        return None


class Comfy:
    """ComfyUI — the gateway's child: started when there is work, unloaded and stopped by quiet."""

    def __init__(self):
        self.proc = None
        self.lock = threading.Lock()     # starting and stopping
        self.job = threading.Lock()      # one job at a time
        self.doing = None                # the job running: {"kind", "model", "since"}
        self.last = time.time()          # when ComfyUI was last needed
        self.freed = True                # its models are already out of the card after the last job
        self.seen = None                 # the last record of its history — so the browser's work is seen

    def running(self):
        p = self.proc                    # the watcher may drop self.proc at any moment — one look
        return p is not None and p.poll() is None

    def touch(self, freed=False):
        with self.lock:
            self.last, self.freed = time.time(), freed

    def command(self):
        if COMFY_CMD:
            return COMFY_CMD.split(), None
        base = ["--base-directory", str(COMFY_BASE)] if COMFY_BASE else []
        return [COMFY_PY, "main.py", "--listen", "127.0.0.1", "--port", str(COMFY_PORT)] + base + COMFY_ARGS, str(COMFY_DIR)

    def start(self):
        """ComfyUI up, if it isn't. → seconds it took (0 — it was running). GateError — it didn't come up."""
        with self.lock:
            if self.running():
                return 0.0
            t0 = time.monotonic()
            cmd, cwd = self.command()
            # with --base-directory ComfyUI 0.44.0 doesn't make custom_nodes itself and falls on os.listdir (2026-11-05)
            if COMFY_BASE:
                for d in ("custom_nodes", "output"):
                    (COMFY_BASE / d).mkdir(parents=True, exist_ok=True)
            STATE.mkdir(parents=True, exist_ok=True)
            if LOG.exists():
                LOG.replace(LOG.with_name(LOG.name + ".1"))
            with open(LOG, "wb") as log:
                proc = subprocess.Popen(cmd, cwd=cwd, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT)
            self.proc = proc
            say("starting ComfyUI, its log — %s" % LOG)
            while time.monotonic() - t0 < START_TIMEOUT:
                if proc.poll() is not None:
                    code, self.proc = proc.returncode, None
                    raise GateError(503, "comfy", "ComfyUI didn't start (code %s). The end of its log %s:\n%s"
                                    % (code, LOG, tail(LOG)))
                try:
                    http(COMFY + "/system_stats", timeout=3)
                    break
                except (OSError, ValueError):
                    time.sleep(1)
            else:
                self._kill()
                raise GateError(504, "comfy", "ComfyUI didn't answer in %d s. Its log: %s" % (START_TIMEOUT, LOG))
            secs = time.monotonic() - t0
            self.last, self.freed, self.seen = time.time(), True, None
            say("ComfyUI ready in %.1f s" % secs)
            return secs

    def _kill(self):
        p, self.proc = self.proc, None
        if p is None or p.poll() is not None:
            return
        p.send_signal(signal.SIGTERM)
        try:
            p.wait(20)
        except subprocess.TimeoutExpired:
            p.kill()
            p.wait(10)

    def stop(self, why):
        with self.lock:
            if not self.running():
                self.proc = None
                return False
            self._kill()
        say("ComfyUI stopped: %s" % why)
        return True

    def free_models(self, wait=0.0):
        """ComfyUI lets its models out of the card; wait — until the memory is really back."""
        before, _ = vram()
        try:
            http(COMFY + "/free", {"unload_models": True, "free_memory": True}, timeout=10)
        except (OSError, ValueError):
            return False
        self.freed = True
        deadline = time.monotonic() + wait
        while before is not None and time.monotonic() < deadline:
            used, _ = vram()
            if used is None or used <= before - 2048:
                break
            time.sleep(0.5)
        return True

    def browser_busy(self):
        """The browser's work: not the gateway's, but in ComfyUI's queue and history."""
        try:
            q = http(COMFY + "/queue", timeout=5)
            h = http(COMFY + "/history?max_items=1", timeout=5)
        except (OSError, ValueError):
            return False
        top = next(iter(h), None)
        new, self.seen = top is not None and top != self.seen, top
        return bool(q.get("queue_running") or q.get("queue_pending")) or new

    def tick(self):
        """Every WATCH_EVERY s: unload the models or stop ComfyUI when it is quiet."""
        p = self.proc
        if p is not None and p.poll() is not None and self.lock.acquire(blocking=False):
            try:                             # the lock taken — a start or a stop runs, it sees to it
                if self.proc is p:
                    say("ComfyUI ended by itself, code %s — its log %s" % (p.returncode, LOG))
                    self.proc = None
            finally:
                self.lock.release()
        if not self.running() or self.job.locked():
            return
        if self.browser_busy():
            self.touch()
            return
        with self.lock:                      # decided and stopped under one lock: no job slips in between
            if self.job.locked() or not self.running():
                return
            idle, freed = time.time() - self.last, self.freed
            if idle >= STOP_AFTER:
                self._kill()
        if idle >= STOP_AFTER:
            say("ComfyUI stopped: %d s of quiet" % idle)
        elif idle >= FREE_AFTER and not freed and self.free_models():
            say("ComfyUI unloaded its models: %d s of quiet" % idle)

    def watch(self):
        while True:
            time.sleep(WATCH_EVERY)
            try:
                self.tick()
            except Exception as e:                      # the watcher must not die
                say("watcher: %r" % e)


comfy = Comfy()


def tail(path, lines=15):
    try:
        return "\n".join(Path(path).read_text(errors="replace").splitlines()[-lines:])
    except OSError:
        return "(no log)"


# ---------- a job: a picture or a song ----------

def check_params(kind, s, p):
    """A request's values for a set, checked: → the values its graph takes."""
    if not isinstance(p, dict):
        raise GateError(400, "bad", "A JSON object is needed.")
    dflt = s.get("defaults") or {}

    def text(name, need, most):
        v = p.get(name, "" if not need else None)
        if not isinstance(v, str) or (need and not v.strip()):
            raise GateError(400, "bad", "No %s." % name)
        if len(v) > most:
            raise GateError(400, "bad", "%s is longer than %d characters." % (name, most))
        return v.strip()

    def num(name, lo, hi, step=1, real=False):
        v = p.get(name, dflt.get(name))
        ok = isinstance(v, (int, float) if real else int) and not isinstance(v, bool) and lo <= v <= hi
        if not ok or (not real and v % step):
            raise GateError(400, "bad", "%s — %s from %s to %s%s." % (name, "a number" if real else "a whole number",
                                                                    lo, hi, ", a multiple of %d" % step if step > 1 else ""))
        return v

    seed = p.get("seed")
    seed = random.randrange(2 ** 48) if seed is None else num("seed", 0, 2 ** 53)
    if kind == "image":
        return {"prompt": text("prompt", True, 2000), "width": num("width", 256, 2048, 16),
                "height": num("height", 256, 2048, 16), "steps": num("steps", 1, 50), "seed": seed}
    lang = p.get("language", dflt.get("language", "en"))
    if lang not in LANGS:
        raise GateError(400, "bad", "language — one of: %s." % ", ".join(LANGS))
    return {"caption": text("caption", True, 2000), "lyrics": text("lyrics", False, 6000) or "[Instrumental]",
            "duration": float(num("duration", 10, 600, real=True)), "bpm": num("bpm", 30, 300),
            "language": lang, "seed": seed}


def fill(node, params):
    """The request's values into the graph: the string "$prompt" → the prompt, "$seed" → the number, and so on."""
    if isinstance(node, dict):
        return {k: fill(v, params) for k, v in node.items()}
    if isinstance(node, list):
        return [fill(v, params) for v in node]
    if isinstance(node, str) and node[:1] == "$" and node[1:] in params:
        return params[node[1:]]
    return node


def describe(blob):
    """ComfyUI's answer with an error → a short text: what is wrong and in which node."""
    try:
        d = json.loads(blob)
    except ValueError:
        return blob[:300].decode(errors="replace")
    parts = []
    err = d.get("error")
    if isinstance(err, dict):
        parts.append(err.get("message") or "")
    for nid, ne in (d.get("node_errors") or {}).items():
        for e in ne.get("errors") or []:
            parts.append("%s: %s %s" % (ne.get("class_type", nid), e.get("message", ""), e.get("details", "")))
    return "; ".join(x.strip() for x in parts if x.strip()) or str(d)[:300]


def forget(pid):
    """The gateway's own record out of ComfyUI's history: only the browser's work stays there."""
    try:
        http(COMFY + "/history", {"delete": [pid]}, timeout=10)
    except (OSError, ValueError):
        pass


def run_graph(graph):
    """The graph to ComfyUI, and the wait for its end. → (its id, the history's record)."""
    try:
        pid = http(COMFY + "/prompt", {"prompt": graph, "client_id": "pult-comfy-gate"}, timeout=30)["prompt_id"]
    except urllib.error.HTTPError as e:
        raise GateError(500, "graph", "ComfyUI didn't take the graph: " + describe(e.read()))
    deadline = time.monotonic() + JOB_TIMEOUT
    while time.monotonic() < deadline:
        if not comfy.running():
            raise GateError(500, "comfy", "ComfyUI fell during the job. The end of its log %s:\n%s" % (LOG, tail(LOG)))
        rec = http(COMFY + "/history/" + pid, timeout=10).get(pid)
        if rec:
            st = rec.get("status") or {}
            if st.get("status_str") == "success":
                return pid, rec
            forget(pid)
            msgs = [m[1].get("exception_message", "") for m in st.get("messages") or []
                    if isinstance(m, list) and len(m) == 2 and m[0] == "execution_error" and isinstance(m[1], dict)]
            raise GateError(500, "job", "ComfyUI: the job failed — " + ("; ".join(msgs).strip() or "no word why"))
        time.sleep(0.5)
    try:
        http(COMFY + "/interrupt", {}, timeout=10)
    except (OSError, ValueError):
        pass
    raise GateError(504, "comfy", "ComfyUI didn't finish in %d s — stopped it. Its log: %s" % (JOB_TIMEOUT, LOG))


def from_cache(rec, graph):
    """Did ComfyUI give a result it had: the same request with the same seed it remembers rather than counts again."""
    cached = set()
    for m in (rec.get("status") or {}).get("messages") or []:
        if isinstance(m, list) and len(m) == 2 and m[0] == "execution_cached" and isinstance(m[1], dict):
            cached.update(str(n) for n in m[1].get("nodes") or [])
    return any(n.get("class_type") in SAMPLERS and nid in cached for nid, n in graph.items())


def take_outputs(pid, rec, key):
    """The job's files from ComfyUI, then off the disk, its history record too. → the first one's bytes."""
    first = None
    out_dir = output_dir().resolve()
    for out in (rec.get("outputs") or {}).values():
        for it in out.get(key) or []:
            q = urllib.parse.urlencode({"filename": it["filename"], "subfolder": it.get("subfolder", ""),
                                        "type": it.get("type", "output")})
            try:
                blob = http(COMFY + "/view?" + q, timeout=60, raw=True)
            except urllib.error.HTTPError as e:
                forget(pid)
                raise GateError(500, "job", "ComfyUI named a file that isn't there (%s, %d)." % (it["filename"], e.code))
            first = first if first is not None else blob
            if it.get("type", "output") == "output":
                f = (out_dir / it.get("subfolder", "") / it["filename"]).resolve()
                if out_dir in f.parents:
                    f.unlink(missing_ok=True)
    forget(pid)
    if first is None:
        raise GateError(500, "job", "ComfyUI finished, but there is nothing in its answer.")
    return first


def pick(kind, model):
    """The set a job runs on: the one named, else the main one of its kind; whole on the disk."""
    seen = disk.look()
    if model is None:
        sid = main_of(kind, seen)
        if not sid:
            raise GateError(409, "none", "No %s model is on the disk yet — download one first." % kind)
        return sets[sid]
    s = sets.get(model) if isinstance(model, str) else None
    if not s or s["kind"] != kind:
        raise GateError(404, "nosuch", "No such %s model: %r." % (kind, model))
    if not ready(s, seen):
        raise GateError(409, "notready", "%s isn't on the disk whole — download it first." % s["name"])
    return s


def make(kind, body):
    """A job: the set's graph with the request's values, ComfyUI started if it isn't. → (bytes, values, s, start s)."""
    s = pick(kind, (body or {}).get("model") if isinstance(body, dict) else None)
    params = check_params(kind, s, body)
    if not comfy.job.acquire(blocking=False):
        raise GateError(409, "busy", "The gateway is doing another job — wait and try again.")
    try:
        comfy.doing = {"kind": kind, "model": s["id"], "since": int(time.time())}
        comfy.touch()
        t0 = time.monotonic()
        displaced = unload_ollama()
        started = 0.0
        if not comfy.running():
            need_vram(s["vram_mib"])
            started = comfy.start()
        comfy.touch()
        # each job's file has a name of its own: a repeat ComfyUI takes from its cache, but saves anew — else it would
        # name the last file, which the gateway has already removed (2026-11-05, lesson 4, step 4.6)
        graph = fill(s["graph"], dict(params, prefix="pult-gate-" + secrets.token_hex(4)))
        pid, rec = run_graph(graph)
        params["cached"] = from_cache(rec, graph)
        blob = take_outputs(pid, rec, KINDS[kind]["out"])
        if displaced and comfy.free_models(wait=FREE_WAIT):
            say("gave the card back: " + ", ".join(displaced) + " waits for it")
        secs = time.monotonic() - t0
        used, _ = vram()
        what = ("a picture %d×%d, %d steps" % (params["width"], params["height"], params["steps"]) if kind == "image"
                else "a song of %d s, %d bpm, %s" % (params["duration"], params["bpm"], params["language"]))
        say("%s: %s, seed %d — %.1f s%s%s; the words — %d characters; the card has %s MiB taken"
            % (s["id"], what, params["seed"], secs, " (starting ComfyUI %.1f s of them)" % started if started else "",
               ", from ComfyUI's cache" if params["cached"] else "",
               len(params.get("prompt") or "") + len(params.get("caption") or "") + len(params.get("lyrics") or ""),
               used if used is not None else "?"))
        return blob, params, s, secs, started
    finally:
        comfy.doing = None
        comfy.touch(freed=comfy.freed)
        comfy.job.release()


# ---------- the downloads ----------

class Pull:
    """A set from Hugging Face, in a thread of its own: Pult only asks how far it is. A file comes as <name>.part —
    picked up where it broke off — and gets its name only when its sha256 is the list's. The progress is counted from
    the disk: the bytes of the set's missing files that are there, whole or in part."""

    def __init__(self):
        self.lock = threading.Lock()
        self.st = None
        self.thread = None
        self.halt = threading.Event()
        self.todo = []
        self.mark = (0.0, 0)
        self.seen_at = 0.0

    def running(self):
        t = self.thread
        return t is not None and t.is_alive()

    def view(self):
        with self.lock:
            return dict(self.st, run=self.running()) if self.st else None

    def set(self, **kw):
        with self.lock:
            self.st.update(kw)

    def progress(self):
        root, n = models_root(), 0
        for f in self.todo:
            try:
                if (root / f["folder"] / f["name"]).stat().st_size == f["size"]:
                    n += f["size"]
                    continue
            except OSError:
                pass
            try:
                n += min((root / f["folder"] / (f["name"] + ".part")).stat().st_size, f["size"])
            except OSError:
                pass
        return n

    def tick(self, force=False):
        """The progress anew, about once a second; the pace over the last few seconds."""
        now = time.monotonic()
        if not force and now - self.seen_at < 1:
            return
        self.seen_at, done = now, self.progress()
        with self.lock:
            self.st["done"] = done
            t0, d0 = self.mark
            if now - t0 >= 3:
                self.st["rate"] = max(0, int((done - d0) / (now - t0))) if t0 else 0
                self.mark = (now, done)

    def start(self, sid, ollama=None):
        s = sets.get(sid) if isinstance(sid, str) else None
        if not s:
            raise GateError(404, "nosuch", "No such set: %r." % (sid,))
        with self.lock:
            if self.running():
                raise GateError(409, "pulling", "Another download runs: %s." % self.st["name"])
            disk.drop()
            seen = disk.look()
            if ready(s, seen):
                raise GateError(409, "have", "%s is on the disk already." % s["name"])
            todo = need(s, seen)
            room = disk_room()
            if room and room["free"] - todo < KEEP:
                raise GateError(507, "room", "%s free on the disk; after %s, %s would stay — %s must stay free."
                                % (gb(room["free"]), gb(todo), gb(room["free"] - todo), gb(KEEP)))
            if CAP:
                theirs = ollama if isinstance(ollama, int) and not isinstance(ollama, bool) and ollama >= 0 else ollama_rough()
                after = seen["comfy"] + seen["also"] + theirs + todo
                if after > CAP:
                    raise GateError(507, "cap", "All models would take %s — more than %s. Remove something first."
                                    % (gb(after), gb(CAP)))
            self.todo = [f for f in s["files"] if not has(f, seen)]
            self.halt.clear()
            total = sum(f["size"] for f in self.todo)
            self.st = {"id": sid, "name": s["name"], "total": total, "done": total - todo, "rate": 0,
                       "since": int(time.time()), "file": None, "phase": "download", "end": None, "err": None,
                       "why": None, "stopped": False}
            self.mark, self.seen_at = (time.monotonic(), total - todo), 0.0
            self.thread = threading.Thread(target=self.run, args=(s,), daemon=True)
            self.thread.start()
        say("download: %s — %s to come" % (sid, gb(todo)))
        return self.view()

    def stop(self):
        t = self.thread
        if t is None or not t.is_alive():
            return False
        self.halt.set()
        t.join(30)
        return True

    def run(self, s):
        try:
            for f in self.todo:
                if self.halt.is_set():
                    break
                self.fetch(f)
                disk.drop()
            self.tick(force=True)
            if self.halt.is_set():
                self.set(stopped=True, end=int(time.time()), rate=0)
                say("download: %s stopped — what came stays" % s["id"])
            else:
                self.set(end=int(time.time()), rate=0, phase="done", file=None)
                say("download: %s is on the disk" % s["id"])
        except GateError as e:
            self.set(err=e.text, why=e.why, end=int(time.time()), rate=0)
            say("download: %s failed — %s" % (s["id"], e.text))
        except Exception as e:                       # never a thread that dies without a word
            self.set(err="%r" % e, why="other", end=int(time.time()), rate=0)
            say("download: %s broke — %r" % (s["id"], e))
        disk.drop()

    def fetch(self, f):
        d = models_root() / f["folder"]
        d.mkdir(parents=True, exist_ok=True)
        final, part = d / f["name"], d / (f["name"] + ".part")
        try:
            if final.stat().st_size == f["size"]:
                return                                       # another set's download brought it meanwhile
        except OSError:
            pass
        url = "%s/%s/resolve/%s/%s" % (HF, f["repo"], f["rev"], urllib.parse.quote(f["path"]))
        self.set(file=f["name"], phase="download")
        tries, wait = 0, PULL_WAIT
        while True:
            have = part.stat().st_size if part.exists() else 0
            if have > f["size"]:
                part.unlink()
                have = 0
            if have == f["size"]:
                break
            if self.halt.is_set():
                return
            room = disk_room()
            if room and room["free"] - (f["size"] - have) < KEEP // 2:
                raise GateError(507, "room", "The disk is filling up from elsewhere: %s free — stopped." % gb(room["free"]))
            req = urllib.request.Request(url, headers={"User-Agent": AGENT, "Range": "bytes=%d-" % have})
            try:
                with urllib.request.urlopen(req, timeout=60) as r:
                    if r.status == 200 and have:             # the server didn't take the range: from the start
                        have = 0
                    with open(part, "ab" if have else "wb") as out:
                        while not self.halt.is_set():
                            chunk = r.read1(CHUNK)           # what has come, not a whole megabyte: a stop is heard at once
                            if not chunk:
                                break
                            out.write(chunk)
                            self.tick()
                tries, wait = 0, PULL_WAIT
            except urllib.error.HTTPError as e:
                if e.code == 416:                            # nothing past that byte: the piece is whole or wrong
                    if part.exists() and part.stat().st_size != f["size"]:
                        part.unlink()
                    continue
                if e.code in (401, 403, 404):
                    raise GateError(502, "source", "Hugging Face answered %d for %s." % (e.code, f["name"]))
                tries += 1
                if tries > PULL_TRIES:
                    raise GateError(502, "net", "Hugging Face kept answering %d for %s." % (e.code, f["name"]))
                self.halt.wait(wait)
                wait = min(60, wait * 2)
            except (OSError, ValueError) as e:              # a broken connection, a timeout: again from where it is
                tries += 1
                if tries > PULL_TRIES:
                    raise GateError(502, "net", "%s didn't come: %s." % (f["name"], getattr(e, "reason", e)))
                self.halt.wait(wait)
                wait = min(60, wait * 2)
            self.tick(force=True)
        if self.halt.is_set():
            return
        self.set(phase="check", rate=0)
        h = hashlib.sha256()
        with open(part, "rb") as src:
            while True:
                b = src.read(8 * CHUNK)
                if not b:
                    break
                h.update(b)
        if h.hexdigest() != f["sha256"]:
            part.unlink(missing_ok=True)
            self.tick(force=True)
            raise GateError(502, "sha", "%s came, but its sha256 isn't the list's — removed; download it again."
                            % f["name"])
        os.replace(part, final)
        self.set(phase="download")
        say("download: %s — whole, its sha256 is the list's" % f["name"])


pulls = Pull()


# ---------- the answers ----------

def health():
    used, total = vram()
    run = comfy.running()
    return {"ok": True, "v": VERSION, "comfy": "running" if run else "stopped", "busy": comfy.job.locked(),
            "job": comfy.doing, "idle_s": int(time.time() - comfy.last) if run else None,
            "models_loaded": run and not comfy.freed, "free_after_s": FREE_AFTER, "stop_after_s": STOP_AFTER,
            "vram_used_mib": used, "vram_total_mib": total, "min_free_mib": MIN_FREE_MIB or min(
                (s["vram_mib"] for s in sets.values()), default=0)}


def models():
    """The tab's answer: never starts ComfyUI, never asks the card."""
    seen = disk.look()
    run = comfy.running()
    out = []
    for s in sets.values():
        files = []
        for f in s["files"]:
            key = (f["folder"], f["name"])
            files.append({"folder": f["folder"], "name": f["name"], "size": f["size"], "have": has(f, seen),
                          "part": seen["parts"].get(key, 0), "shared": [x["id"] for x in sets.values()
                          if x["id"] != s["id"] and any((g["folder"], g["name"]) == key for g in x["files"])]})
        info = {k: v for k, v in s.items() if k not in ("files", "graph", "defaults")}
        out.append(dict(info, files=files, size=sum(f["size"] for f in s["files"]), ready=ready(s, seen),
                        need=need(s, seen), frees=frees(s, seen)))
    known = {(f["folder"], f["name"]) for s in sets.values() for f in s["files"]}
    other = sum(size for key, size in seen["files"].items() if key not in known)
    return {"v": VERSION, "comfy": {"version": comfy_version(), "state": "running" if run else "stopped",
                                    "loaded": run and not comfy.freed, "idle_s": int(time.time() - comfy.last) if run else None,
                                    "free_after_s": FREE_AFTER, "stop_after_s": STOP_AFTER},
            "job": comfy.doing, "sets": out, "main": {k: main_of(k, seen) for k in KINDS}, "pull": pulls.view(),
            "bytes": {"comfy": seen["comfy"], "also": seen["also"], "other": other},
            "disk": disk_room(), "keep": KEEP, "cap": CAP or None}


def set_main(sid):
    s = sets.get(sid) if isinstance(sid, str) else None
    if not s:
        raise GateError(404, "nosuch", "No such set: %r." % (sid,))
    if not ready(s, disk.look()):
        raise GateError(409, "notready", "%s isn't on the disk whole." % s["name"])
    STATE.mkdir(parents=True, exist_ok=True)
    m = dict(mains(), **{s["kind"]: sid})
    tmp = STATE / "main.json.tmp"
    tmp.write_text(json.dumps(m))
    os.replace(tmp, STATE / "main.json")
    say("main %s model: %s" % (s["kind"], sid))
    return {"ok": True, "main": {k: main_of(k, disk.look()) for k in KINDS}}


def remove(sid):
    s = sets.get(sid) if isinstance(sid, str) else None
    if not s:
        raise GateError(404, "nosuch", "No such set: %r." % (sid,))
    if comfy.job.locked():
        raise GateError(409, "busy", "A job runs now — removing a model under it would break it. Try when it ends.")
    if pulls.running():
        raise GateError(409, "pulling", "A download runs now — stop it first.")
    disk.drop()
    seen = disk.look()
    if comfy.running() and not comfy.freed:
        comfy.free_models(wait=FREE_WAIT)                # nothing of it stays in ComfyUI's memory
    root, gone, back = models_root(), [], 0
    for f in s["files"]:
        key = (f["folder"], f["name"])
        if keeps(sid, key, seen):
            continue
        for p in (root / f["folder"] / f["name"], root / f["folder"] / (f["name"] + ".part")):
            try:
                size = p.stat().st_size
                p.unlink()
            except OSError:
                continue
            gone.append(p.name)
            back += size
    disk.drop()
    say("removed %s: %s back (%s)" % (sid, gb(back), ", ".join(gone) or "nothing of its own"))
    return {"ok": True, "freed": back, "files": gone}


class Handler(BaseHTTPRequestHandler):
    server_version = "pult-comfy-gate/%d" % VERSION     # HTTP/1.0: the connection closes after each answer

    def log_message(self, fmt, *args):                  # the gateway writes its own lines, never a request's words
        pass

    def reply(self, code, blob, ctype, extra=None):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(blob)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(blob)

    def reply_json(self, code, obj):
        self.reply(code, json.dumps(obj, ensure_ascii=False).encode(), "application/json; charset=utf-8")

    def read_json(self):
        # JSON only: a page in a browser won't send it to another address without asking (CORS) — no site works the
        # gateway behind the owner's back
        if not (self.headers.get("Content-Type") or "").startswith("application/json"):
            raise GateError(415, "bad", "Content-Type: application/json is needed.")
        n = int(self.headers.get("Content-Length") or 0)
        if n > BODY_MAX:
            raise GateError(413, "bad", "The request is too big.")
        raw = self.rfile.read(n) if n else b"{}"
        try:
            return json.loads(raw or b"{}")
        except ValueError:
            raise GateError(400, "bad", "That's not JSON.")

    WHERE = "GET /health, /models; POST /image, /audio, /pull, /pull/stop, /remove, /main, /free, /start, /stop."

    def do_GET(self):
        if self.path == "/health":
            self.reply_json(200, health())
        elif self.path == "/models":
            self.reply_json(200, models())
        else:
            self.reply_json(404, {"error": "No such address. There are: " + self.WHERE, "why": "path"})

    def do_POST(self):
        try:
            body = self.read_json()
            arg = body if isinstance(body, dict) else {}
            if self.path in ("/image", "/audio"):
                kind = self.path[1:]
                blob, params, s, secs, started = make(kind, body)
                self.reply(200, blob, KINDS[kind]["ctype"], {
                    "X-Model": s["id"], "X-Seed": str(params["seed"]), "X-Seconds": "%.1f" % secs,
                    "X-Start-Seconds": "%.1f" % started, "X-Cached": "1" if params["cached"] else "0"})
            elif self.path == "/pull":
                self.reply_json(202, {"ok": True, "pull": pulls.start(arg.get("id"), arg.get("ollama"))})
            elif self.path == "/pull/stop":
                self.reply_json(200, {"ok": True, "stopped": pulls.stop(), "pull": pulls.view()})
            elif self.path == "/remove":
                self.reply_json(200, remove(arg.get("id")))
            elif self.path == "/main":
                self.reply_json(200, set_main(arg.get("id")))
            elif self.path == "/free":
                if comfy.job.locked():
                    raise GateError(409, "busy", "A job runs now — the card is freed when it ends.")
                freed = comfy.running() and comfy.free_models(wait=FREE_WAIT)
                self.reply_json(200, {"ok": True, "freed": bool(freed)})
            elif self.path == "/start":
                if not comfy.job.acquire(blocking=False):
                    raise GateError(409, "busy", "The gateway is doing a job — wait.")
                try:
                    unload_ollama()
                    started = 0.0
                    if not comfy.running():
                        need_vram(min((s["vram_mib"] for s in sets.values()), default=0))
                        started = comfy.start()
                    comfy.touch(freed=True)
                finally:
                    comfy.job.release()
                self.reply_json(200, {"ok": True, "started_s": round(started, 1), "ui": "http://127.0.0.1:%d" % COMFY_PORT,
                                      "stop_after_s": STOP_AFTER})
            elif self.path == "/stop":
                if comfy.job.locked():
                    raise GateError(409, "busy", "A job runs now — ComfyUI stops when it ends: try in a minute.")
                self.reply_json(200, {"ok": True, "stopped": comfy.stop("asked by /stop")})
            else:
                raise GateError(404, "path", "No such address. There are: " + self.WHERE)
        except GateError as e:
            if e.code >= 500:
                say("error %d: %s" % (e.code, e.text.splitlines()[0]))
            self.reply_json(e.code, {"error": e.text, "why": e.why})
        except Exception as e:
            say("the gateway broke: %r" % e)
            self.reply_json(500, {"error": "The gateway broke: %r" % e, "why": "other"})


class Server(ThreadingHTTPServer):
    """HTTPServer names itself by a reverse lookup of its address (socket.getfqdn) — on some machines that alone takes
    tens of seconds (GitHub's macOS runners, 2026-11-25); the name is never used here."""

    def server_bind(self):
        socketserver.TCPServer.server_bind(self)
        self.server_name, self.server_port = self.server_address[:2]


sets = {}


def main():
    global sets
    if "--check" in sys.argv:                             # the installer's look at the list before it starts anything
        print("%d sets: %s" % (len(load_sets()), ", ".join(load_sets())))
        return 0
    try:
        sets = load_sets()
    except (OSError, ValueError) as e:
        say("the list of sets %s is broken: %s" % (SETS, e))
        return 2
    STATE.mkdir(parents=True, exist_ok=True)
    for f in models_root().glob("*/*.part"):          # a download cut by a restart stays a piece: /pull goes on from it
        say("a piece left from a download: %s/%s (%s)" % (f.parent.name, f.name, gb(f.stat().st_size)))
    srv = Server((HOST, PORT), Handler)
    srv.daemon_threads = True
    threading.Thread(target=comfy.watch, daemon=True).start()

    def bye(signum, frame):
        raise SystemExit(0)

    signal.signal(signal.SIGTERM, bye)
    say("the gateway v%d listens on %s:%d; %d sets (%s); ComfyUI %s — when there is work: models out after %d s of "
        "quiet, off after %d s; the disk keeps %s free%s"
        % (VERSION, HOST, PORT, len(sets), ", ".join(sets), comfy_version() or "?", FREE_AFTER, STOP_AFTER, gb(KEEP),
           ", all models within %s" % gb(CAP) if CAP else ""))
    try:
        srv.serve_forever(poll_interval=0.5)
    finally:
        pulls.halt.set()
        comfy.stop("the service stops")


if __name__ == "__main__":
    sys.exit(main())
