#!/usr/bin/env python3
"""The gateway beside ComfyUI (comfy_gate.py) checked without a graphics card: ComfyUI, Ollama, nvidia-smi and Hugging
Face are stand-ins. Runs the gateway on free ports and goes through: the list and the disk, downloads (a broken
connection, a wrong file, a stop and the rest after it, the room and the cap), removal with a shared file, the main set,
a picture on each model, a song, the first gateway's requests, refusals, unloading and stopping by quiet, the browser's
work, a ComfyUI that doesn't start. About a minute.

  python3 deploy/comfy-gate/test_gate.py
"""
import hashlib
import importlib.util
import json
import os
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
GATE = HERE / "comfy_gate.py"
TMP = Path(tempfile.mkdtemp(prefix="pult-comfy-gate-test-"))
OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))

# The stand-in ComfyUI: a graph is "worked" in 0.4 s — a picture (a 1×1 PNG) or a song (bytes like an MP3) under the
# graph's own prefix; the request's words steer it: FAIL — a failed job, BADNODE — a graph it won't take, VIEW404 — a
# file it names but hasn't, SLOW — two seconds of work. The same graph again but the file's name — from its cache.
FAKE_COMFY = r'''
import json, os, signal, struct, sys, threading, time, uuid, zlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs
a = sys.argv[1:]
port, base = int(a[a.index("--port") + 1]), a[a.index("--base") + 1]
if "--crash" in a:
    print("oops: no CUDA"); sys.exit(3)
if "--slow" in a:
    time.sleep(float(a[a.index("--slow") + 1]))
out = os.path.join(base, "output"); os.makedirs(out, exist_ok=True)
history, running, n, last = {}, [], [0], {"sig": None, "full": None, "file": None}
def png():
    raw = b"\x00\xff\x00\x00"
    def chunk(t, d): return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d))
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)) + \
        chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b"")
def count(name):
    f = os.path.join(base, name); v = int(open(f).read()) if os.path.exists(f) else 0
    open(f, "w").write(str(v + 1))
def words(graph):
    return " ".join(v for nd in graph.values() for v in nd.get("inputs", {}).values() if isinstance(v, str))
def work(pid, graph):
    running.append(pid)
    text = words(graph)
    save = next(k for k, nd in graph.items() if nd["class_type"] in ("SaveImage", "SaveAudioAdvanced"))
    audio = graph[save]["class_type"] == "SaveAudioAdvanced"
    prefix = graph[save]["inputs"]["filename_prefix"]
    full = json.dumps(graph, sort_keys=True)
    sig = json.dumps({k: v for k, v in graph.items() if k != save}, sort_keys=True)
    msgs = [["execution_start", {}]]
    if full == last["full"]:
        name = last["file"]
    elif "VIEW404" in text:
        name = "not-there_00001_.png"
    else:
        if sig == last["sig"]:
            msgs.append(["execution_cached", {"nodes": [k for k in graph if k != save]}])
        else:
            time.sleep(2 if "SLOW" in text else 0.4)
        n[0] += 1; name = "%s_%05d_.%s" % (prefix, n[0], "mp3" if audio else "png")
        if "FAIL" not in text:
            open(os.path.join(out, name), "wb").write(b"ID3\x04\x00fake-mp3" if audio else png())
    last.update(sig=sig, full=full, file=name)
    if "FAIL" in text:
        history[pid] = {"outputs": {}, "status": {"status_str": "error", "completed": False,
                        "messages": msgs + [["execution_error", {"exception_message": "boom"}]]}}
    else:
        history[pid] = {"outputs": {save: {"audio" if audio else "images": [{"filename": name, "subfolder": "", "type": "output"}]}},
                        "status": {"status_str": "success", "completed": True, "messages": msgs}}
    running.remove(pid)
class H(BaseHTTPRequestHandler):
    def log_message(self, *x): pass
    def send(self, code, obj, ctype="application/json"):
        b = obj if isinstance(obj, bytes) else json.dumps(obj).encode()
        self.send_response(code); self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)
    def do_GET(self):
        u = urlparse(self.path); q = parse_qs(u.query)
        if u.path == "/system_stats": return self.send(200, {"devices": [{"name": "fake"}]})
        if u.path == "/queue": return self.send(200, {"queue_running": [[0, p] for p in running], "queue_pending": []})
        if u.path == "/history":
            k = list(history)[-int(q.get("max_items", ["1"])[0]):]
            return self.send(200, {x: history[x] for x in k})
        if u.path.startswith("/history/"):
            pid = u.path.split("/")[-1]; return self.send(200, {pid: history[pid]} if pid in history else {})
        if u.path == "/view":
            f = os.path.join(out, q["filename"][0])
            if not os.path.exists(f): return self.send(404, {})
            return self.send(200, open(f, "rb").read(), "application/octet-stream")
        self.send(404, {})
    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
        if self.path == "/prompt":
            g = body["prompt"]
            json.dump(g, open(os.path.join(base, "last_graph.json"), "w"))
            if "BADNODE" in words(g):
                return self.send(400, {"error": {"message": "Prompt outputs failed validation"},
                                       "node_errors": {"16": {"class_type": "UNETLoader", "errors": [
                                           {"message": "Value not in list", "details": "unet_name: 'x' not in []"}]}}})
            pid = str(uuid.uuid4()); threading.Thread(target=work, args=(pid, g), daemon=True).start()
            return self.send(200, {"prompt_id": pid, "number": 1, "node_errors": {}})
        if self.path == "/free": count("frees"); return self.send(200, b"", "text/plain")
        if self.path == "/history":
            for x in body.get("delete", []): history.pop(x, None)
            return self.send(200, b"", "text/plain")
        if self.path == "/interrupt": return self.send(200, b"", "text/plain")
        self.send(404, {})
signal.signal(signal.SIGTERM, lambda *x: os._exit(0))
print("fake ComfyUI on", port, flush=True)
ThreadingHTTPServer(("127.0.0.1", port), H).serve_forever()
'''

fails = 0


def check(name, cond):
    global fails
    print(("ok   " if cond else "FAIL ") + name)
    fails += 0 if cond else 1


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def call(port, path, body=None, ctype="application/json", timeout=30):
    """→ (code, headers, body)."""
    data = None if body is None else (body if isinstance(body, bytes) else json.dumps(body).encode())
    req = urllib.request.Request("http://127.0.0.1:%d%s" % (port, path), data=data,
                                 method="GET" if data is None else "POST", headers={"Content-Type": ctype} if ctype else {})
    try:
        with OPENER.open(req, timeout=timeout) as r:
            return r.status, r.headers, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.headers, e.read()
    except (urllib.error.URLError, ConnectionError, TimeoutError):
        return 0, {}, b""


def js(r):
    try:
        return json.loads(r[2])
    except ValueError:
        return {}


def err(r):
    return js(r).get("error", "")


def wait(cond, secs):
    end = time.time() + secs
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.2)
    return cond()


def port_open(port):
    with socket.socket() as s:
        s.settimeout(1)
        return s.connect_ex(("127.0.0.1", port)) == 0


# ---- the list: the real sets.json with each file made small — its own bytes, their sha256 and size
REAL = json.loads((HERE / "sets.json").read_text())
CONTENT = {}


def small(f):
    key = f["repo"] + "/" + f["path"]
    if key not in CONTENT:
        seed = hashlib.sha256(key.encode()).digest()
        CONTENT[key] = seed * (8000 + len(key) * 20)           # 260–330 KB: the slow download takes seconds
    return CONTENT[key]


SMALL = json.loads(json.dumps(REAL))
for s in SMALL["sets"]:
    for f in s["files"]:
        b = small(f)
        f["size"], f["sha256"] = len(b), hashlib.sha256(b).hexdigest()
(TMP / "sets.json").write_text(json.dumps(SMALL))
BY_SET = {s["id"]: s for s in SMALL["sets"]}

# ---- the stand-in Hugging Face: /<repo>/resolve/<rev>/<path>, ranges; its moods: "cut" — the first answer for a
# path breaks off halfway, "wrong" — a path's bytes aren't the list's, "slow" — 64 KB a second, "norange" — the whole
# file always
HF = {"cut": set(), "wrong": set(), "slow": set(), "norange": False, "asks": []}


class Hub(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *x):
        pass

    def do_GET(self):
        parts = self.path.split("/", 5)              # "", org, repo, "resolve", rev, path
        key = None
        if len(parts) == 6 and parts[3] == "resolve":
            key = "%s/%s/%s" % (parts[1], parts[2], urllib.request.unquote(parts[5]))
        blob = next((v for k, v in CONTENT.items() if k == key), None)
        rng = self.headers.get("Range") or ""
        HF["asks"].append((key, rng))
        if blob is None:
            self.send_response(404)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        if key in HF["wrong"]:
            blob = bytes(len(blob))
        start = int(rng[6:].split("-")[0]) if rng.startswith("bytes=") and not HF["norange"] else 0
        if start >= len(blob) and start:
            self.send_response(416)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        body = blob[start:]
        self.send_response(206 if start else 200)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Content-Type", "application/octet-stream")
        self.end_headers()
        if key in HF["cut"]:
            HF["cut"].discard(key)
            self.wfile.write(body[: len(body) // 2])
            self.wfile.flush()
            self.connection.shutdown(socket.SHUT_RDWR)
            return
        if key in HF["slow"]:
            try:
                for i in range(0, len(body), 16384):
                    self.wfile.write(body[i:i + 16384])
                    self.wfile.flush()
                    time.sleep(0.25)
            except (BrokenPipeError, ConnectionResetError):      # the gateway stopped reading: a stop
                pass
            return
        self.wfile.write(body)


HF_PORT = free_port()
threading.Thread(target=ThreadingHTTPServer(("127.0.0.1", HF_PORT), Hub).serve_forever, daemon=True).start()

# ---- the stand-in Ollama and nvidia-smi
ollama_models = ["qwen9b-32k:latest"]
ollama_calls = []


class Ollama(BaseHTTPRequestHandler):
    def log_message(self, *x):
        pass

    def answer(self, obj):
        b = json.dumps(obj).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def do_GET(self):
        if self.path == "/api/tags":
            return self.answer({"models": [{"name": "gemma4:12b", "digest": "a1", "size": 8_000_000},
                                           {"name": "gemma4-32k", "digest": "b2", "size": 8_000_000}]})
        self.answer({"models": [{"name": m, "model": m} for m in ollama_models]})

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)))
        ollama_calls.append(body)
        if body.get("keep_alive") == 0 and body.get("model") in ollama_models:
            ollama_models.remove(body["model"])
        self.answer({"done": True, "done_reason": "unload"})


OLLAMA_PORT = free_port()
threading.Thread(target=ThreadingHTTPServer(("127.0.0.1", OLLAMA_PORT), Ollama).serve_forever, daemon=True).start()
(TMP / "fake_comfy.py").write_text(FAKE_COMFY)
VRAM = TMP / "vram.txt"
VRAM.write_text("600, 16376\n")
SMI = TMP / "nvidia-smi"
SMI.write_text("#!/bin/sh\ncat %s\n" % VRAM)
SMI.chmod(0o755)
NOPROXY = {k: v for k, v in os.environ.items() if "proxy" not in k.lower()}


def start_gate(name, comfy_extra="", **over):
    gport, cport, base = free_port(), free_port(), TMP / name
    (base / "models").mkdir(parents=True)
    (base / "also").mkdir()
    env = dict(NOPROXY, GATE_PORT=str(gport), COMFY_PORT=str(cport), COMFY_BASE=str(base), COMFY_DIR=str(base / "app"),
               COMFY_CMD="%s %s --port %d --base %s %s" % (sys.executable, TMP / "fake_comfy.py", cport, base, comfy_extra),
               OLLAMA_URL="http://127.0.0.1:%d" % OLLAMA_PORT, NVIDIA_SMI=str(SMI), GATE_STATE=str(base / "state"),
               GATE_SETS=str(TMP / "sets.json"), GATE_HF="http://127.0.0.1:%d" % HF_PORT, GATE_DISK=str(base),
               GATE_KEEP_GB="0", GATE_ALSO=str(base / "also"), GATE_PULL_WAIT="0.2",
               GATE_FREE_AFTER="2", GATE_STOP_AFTER="4", GEN_WATCH_EVERY="0.3", GEN_START_TIMEOUT="20",
               GEN_JOB_TIMEOUT="20", GEN_VRAM_WAIT="1", GEN_FREE_WAIT="0.5")
    env.update({k: str(v) for k, v in over.items()})
    (base / "app").mkdir()
    (base / "app" / "comfyui_version.py").write_text('__version__ = "0.44.0"\n')
    log = open(base / "gate.out", "w")
    p = subprocess.Popen([sys.executable, "-I", str(GATE)], env=env, stdout=log, stderr=subprocess.STDOUT)
    ok = wait(lambda: call(gport, "/health", timeout=2)[0] == 200 if p.poll() is None else True, 10)
    if not ok or p.poll() is not None:
        print((base / "gate.out").read_text())
        raise SystemExit("comfy_gate.py didn't come up")
    return p, gport, base


def put(base, sid, skip=()):
    """A set's files on the disk as an installer would leave them (lesson 4's install-comfyui.sh)."""
    for f in BY_SET[sid]["files"]:
        if f["name"] in skip:
            continue
        d = base / "models" / f["folder"]
        d.mkdir(parents=True, exist_ok=True)
        (d / f["name"]).write_bytes(small(f))


def models(port):
    return js(call(port, "/models"))


def row(port, sid):
    return next(s for s in models(port)["sets"] if s["id"] == sid)


def pulled(port, secs=20):
    """Wait for the download to end. → its last state."""
    wait(lambda: not (models(port)["pull"] or {}).get("run"), secs)
    return models(port)["pull"]


def own_bytes(sid, names):
    return sum(f["size"] for f in BY_SET[sid]["files"] if f["name"] in names)


ZI, FK, AC = "z-image-turbo", "flux2-klein-4b", "ace-step-1.5-turbo"
ENC = "qwen_3_4b_fp8_mixed.safetensors"
procs = []
try:
    # ---- the list is checked when the gateway starts
    spec = importlib.util.spec_from_file_location("comfy_gate", GATE)
    G = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(G)
    check("the real sets.json is a good list: three sets", list(G.load_sets(HERE / "sets.json")) == [ZI, FK, AC])

    def bad(change):
        d = json.loads(json.dumps(REAL))
        change(d["sets"])
        f = TMP / "bad.json"
        f.write_text(json.dumps(d))
        try:
            G.load_sets(f)
            return ""
        except ValueError as e:
            return str(e)
    check("a node that isn't ComfyUI's own (an extension) — refused", "not one of the nodes" in bad(
        lambda ss: ss[0]["graph"].update({"99": {"class_type": "ExecuteCode", "inputs": {}}})))
    check("a loader of a file that isn't the set's — refused", "not a file of the set" in bad(
        lambda ss: ss[0]["graph"]["16"]["inputs"].update(unet_name="other.safetensors")))
    check("a loader fed by a link, not a file's name — refused", "not a file of the set" in bad(
        lambda ss: ss[0]["graph"]["16"]["inputs"].update(unet_name=["99", 0])))
    check("a path with .. — refused", "a file" in bad(lambda ss: ss[0]["files"][0].update(path="../../etc/x.safetensors")))
    check("a file that isn't .safetensors — refused", "a file" in bad(
        lambda ss: ss[0]["files"][0].update(name="model.ckpt", path="model.ckpt")))
    check("a file by a branch, not a commit — refused", "a file" in bad(lambda ss: ss[0]["files"][0].update(rev="main")))
    check("a value the kind doesn't have — refused", "not a value of its kind" in bad(
        lambda ss: ss[0]["graph"]["6"]["inputs"].update(text="$cmd")))
    check("a shared file with two different sha256 — refused", "differs" in bad(
        lambda ss: ss[1]["files"][1].update(sha256="0" * 64)))
    check("a save under a name of its own — refused", "name of its own" in bad(
        lambda ss: ss[0]["graph"]["9"]["inputs"].update(filename_prefix="/etc/x")))

    p, port, base = start_gate("main", GATE_CAP_GB="0")
    procs.append(p)
    h = js(call(port, "/health"))
    check("health: v2, ComfyUI off, the card seen", h.get("v") == 2 and h["comfy"] == "stopped" and h["vram_total_mib"] == 16376)
    m = models(port)
    check("the list: three sets, none on the disk, no main one", [s["id"] for s in m["sets"]] == [ZI, FK, AC]
          and not any(s["ready"] for s in m["sets"]) and m["main"] == {"image": None, "audio": None})
    check("the list says ComfyUI's version and the facts of a set", m["comfy"]["version"] == "0.44.0"
          and row(port, AC)["kind"] == "audio" and row(port, AC)["license"] == "MIT" and "graph" not in row(port, AC))
    r = call(port, "/image", {"prompt": "a fox"})
    check("a picture with no drawing model on the disk — 409 none", r[0] == 409 and js(r)["why"] == "none")

    put(base, ZI)                                     # as lesson 4's installer left it
    time.sleep(5.2)                                   # the disk's look is a few seconds old
    m = models(port)
    check("Z-Image's files put by hand — it is whole and the main one", row(port, ZI)["ready"] and m["main"]["image"] == ZI)
    check("FLUX.2 klein needs its own files only: the encoder is there", row(port, FK)["need"] == own_bytes(FK, (
        "flux-2-klein-4b-fp8.safetensors", "flux2-vae.safetensors")))

    secret = "a red fox sleeping in the snow, TOP-SECRET-WORDS"
    r = call(port, "/image", {"prompt": secret})
    check("a picture: 200, PNG, made by Z-Image", r[0] == 200 and r[2][:8] == b"\x89PNG\r\n\x1a\n" and r[1].get("X-Model") == ZI)
    check("a picture: its seed and ComfyUI's start time", r[1].get("X-Seed", "").isdigit()
          and float(r[1].get("X-Start-Seconds", "0")) > 0)
    check("Ollama's model left the card first", ollama_models == [] and {"model": "qwen9b-32k:latest", "keep_alive": 0} in ollama_calls)
    g = json.loads((base / "last_graph.json").read_text())
    check("the graph: the prompt, the seed, the size and Z-Image's 9 steps", g["6"]["inputs"]["text"] == secret
          and g["3"]["inputs"]["seed"] == int(r[1]["X-Seed"]) and g["13"]["inputs"]["width"] == 1024
          and g["3"]["inputs"]["steps"] == 9 and g["16"]["inputs"]["weight_dtype"] == "fp8_e4m3fn")
    check("the picture is off the disk after it went", not any((base / "output").iterdir()))
    r = call(port, "/image", {"prompt": "a cat", "seed": 42, "width": 512, "height": 768, "steps": 4})
    g = json.loads((base / "last_graph.json").read_text())
    check("as the first gateway was asked: seed 42, 512×768, 4 steps; ComfyUI not started again", r[0] == 200
          and r[1].get("X-Seed") == "42" and r[1].get("X-Start-Seconds") == "0.0"
          and (g["13"]["inputs"]["width"], g["13"]["inputs"]["height"], g["3"]["inputs"]["steps"]) == (512, 768, 4))
    r1 = call(port, "/image", {"prompt": "a fox in the snow", "seed": 7})
    r2 = call(port, "/image", {"prompt": "a fox in the snow", "seed": 7})
    check("the same seed again: from ComfyUI's cache (X-Cached)", r1[1].get("X-Cached") == "0" and r2[1].get("X-Cached") == "1"
          and r2[2][:4] == b"\x89PNG")
    r = call(port, "/image", {"prompt": "VIEW404"})
    check("a file ComfyUI names but hasn't — a word of it, not a crash", r[0] == 500 and "isn't there" in err(r))
    res = []
    ts = [threading.Thread(target=lambda: res.append(call(port, "/image", {"prompt": "a dog"})[0])) for _ in range(2)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    check("two pictures at once: one is drawn, the other — 409", sorted(res) == [200, 409])
    check("no prompt — 400", call(port, "/image", {"width": 512})[0] == 400)
    check("a width not a multiple of 16 — 400", call(port, "/image", {"prompt": "x", "width": 1000})[0] == 400)
    check("steps as a string — 400", call(port, "/image", {"prompt": "x", "steps": "9"})[0] == 400)
    check("not JSON (a form from another site) — 415", call(port, "/image", b"prompt=x",
                                                          ctype="application/x-www-form-urlencoded")[0] == 415)
    r = call(port, "/image", {"prompt": "FAIL please"})
    check("a failed job — 500 with ComfyUI's words", r[0] == 500 and "boom" in err(r))
    r = call(port, "/image", {"prompt": "BADNODE"})
    check("a graph ComfyUI won't take — 500 and its reason", r[0] == 500 and "didn't take the graph" in err(r)
          and "not in" in err(r))
    r = call(port, "/image", {"prompt": "x", "model": FK})
    check("a model not on the disk — 409 notready", r[0] == 409 and js(r)["why"] == "notready")
    r = call(port, "/image", {"prompt": "x", "model": AC})
    check("a picture from the music model — 404", r[0] == 404)

    # ---- a download: FLUX.2 klein — its model breaks off once and goes on from there; the shared encoder isn't asked
    HF["cut"].add("black-forest-labs/FLUX.2-klein-4b-fp8/flux-2-klein-4b-fp8.safetensors")
    HF["asks"].clear()
    r = call(port, "/pull", {"id": FK})
    check("a download starts: 202, its total — the set's own files", r[0] == 202 and js(r)["pull"]["run"]
          and js(r)["pull"]["total"] == own_bytes(FK, ("flux-2-klein-4b-fp8.safetensors", "flux2-vae.safetensors")))
    st = pulled(port)
    check("the download ends whole, no error", st and not st["err"] and not st["stopped"] and st["done"] == st["total"])
    check("FLUX.2 klein is whole on the disk", row(port, FK)["ready"])
    asked = [k for k, _ in HF["asks"]]
    check("the shared encoder wasn't downloaded again", not any(ENC in (k or "") for k in asked))
    cut = [rng for k, rng in HF["asks"] if k and k.endswith("flux-2-klein-4b-fp8.safetensors")]
    check("the broken connection — picked up from where it broke", len(cut) == 2 and cut[0] == "bytes=0-"
          and cut[1] != "bytes=0-")
    f = base / "models/diffusion_models/flux-2-klein-4b-fp8.safetensors"
    check("the file is the list's, byte for byte, no piece left", f.read_bytes() == small(BY_SET[FK]["files"][0])
          and not list((base / "models").glob("*/*.part")))
    r = call(port, "/pull", {"id": FK})
    check("a set already there — 409", r[0] == 409 and js(r)["why"] == "have")

    r = call(port, "/image", {"prompt": "a hedgehog in a party hat", "model": FK})
    g = json.loads((base / "last_graph.json").read_text())
    check("a picture on FLUX.2 klein: its graph, 4 steps, the shared encoder as flux2", r[0] == 200
          and r[1].get("X-Model") == FK and g["62"]["inputs"]["steps"] == 4 and g["71"]["inputs"]["type"] == "flux2"
          and g["73"]["inputs"]["noise_seed"] == int(r[1]["X-Seed"]) and g["74"]["inputs"]["text"] == "a hedgehog in a party hat")
    r = call(port, "/main", {"id": FK})
    check("FLUX.2 klein made the main one", r[0] == 200 and js(r)["main"]["image"] == FK)
    r = call(port, "/image", {"prompt": "a lighthouse"})
    check("a picture without a model — on the main one", r[1].get("X-Model") == FK)
    check("the main one survives a restart of the request's look", models(port)["main"]["image"] == FK)

    # ---- removal: FLUX.2 klein goes, the encoder stays for Z-Image
    want = own_bytes(FK, ("flux-2-klein-4b-fp8.safetensors", "flux2-vae.safetensors"))
    check("FLUX.2 klein's removal gives back its own files only", row(port, FK)["frees"] == want)
    check("Z-Image's removal would keep the encoder FLUX has", row(port, ZI)["frees"] == own_bytes(ZI, (
        "z_image_turbo_bf16.safetensors", "ae.safetensors")))
    r = call(port, "/remove", {"id": FK})
    check("removed: its two files, the bytes back", r[0] == 200 and js(r)["freed"] == want and len(js(r)["files"]) == 2)
    check("the encoder is still there, Z-Image whole", (base / "models/text_encoders" / ENC).exists() and row(port, ZI)["ready"])
    check("FLUX gone: Z-Image's removal would give back all its files, the encoder too", row(port, ZI)["frees"]
          == own_bytes(ZI, [f["name"] for f in BY_SET[ZI]["files"]]))
    check("the main picture model is Z-Image again", models(port)["main"]["image"] == ZI)

    # ---- a wrong file: its sha256 isn't the list's — removed, a word of it
    HF["wrong"].add("Comfy-Org/flux2-klein/split_files/vae/flux2-vae.safetensors")
    call(port, "/pull", {"id": FK})
    st = pulled(port)
    check("a file whose sha256 isn't the list's — an error, why sha", st["err"] and st["why"] == "sha")
    check("its piece is gone, FLUX not whole", not (base / "models/vae/flux2-vae.safetensors.part").exists()
          and not (base / "models/vae/flux2-vae.safetensors").exists() and not row(port, FK)["ready"])
    HF["wrong"].clear()

    # ---- a stop halfway, then the rest from that point
    call(port, "/remove", {"id": FK})
    slowkey = "black-forest-labs/FLUX.2-klein-4b-fp8/flux-2-klein-4b-fp8.safetensors"
    HF["slow"].add(slowkey)
    HF["asks"].clear()
    call(port, "/pull", {"id": FK})
    time.sleep(1.6)
    r = call(port, "/remove", {"id": ZI})
    check("removal while a download runs — 409 pulling", r[0] == 409 and js(r)["why"] == "pulling")
    r = call(port, "/pull", {"id": AC})
    check("a second download at once — 409", r[0] == 409 and js(r)["why"] == "pulling")
    r = call(port, "/pull/stop", {})
    st = js(r)["pull"]
    part = base / "models/diffusion_models/flux-2-klein-4b-fp8.safetensors.part"
    check("stopped: the piece stays, the state says so", r[0] == 200 and js(r)["stopped"] and st["stopped"]
          and not st["run"] and part.exists() and 0 < part.stat().st_size)
    had = part.stat().st_size
    HF["slow"].clear()
    HF["asks"].clear()
    r = call(port, "/pull", {"id": FK})
    check("again: it starts from the piece", js(r)["pull"]["done"] >= had)
    st = pulled(port)
    ask = [rng for k, rng in HF["asks"] if k == slowkey]
    check("the rest came with a range from the piece, and it is whole", ask and ask[0] == "bytes=%d-" % had
          and not st["err"] and row(port, FK)["ready"])

    # ---- a server that ignores ranges: the file anew from its start, still right
    call(port, "/remove", {"id": FK})
    HF["cut"].add(slowkey)
    HF["norange"] = True
    call(port, "/pull", {"id": FK})
    st = pulled(port)
    check("a server without ranges: the file from its start, whole and right", not st["err"] and row(port, FK)["ready"]
          and (base / "models/diffusion_models/flux-2-klein-4b-fp8.safetensors").read_bytes() == small(BY_SET[FK]["files"][0]))
    HF["norange"] = False

    # ---- music: ACE-Step 1.5 Turbo
    r = call(port, "/audio", {"caption": "calm piano"})
    check("a song with no music model on the disk — 409 none", r[0] == 409 and js(r)["why"] == "none")
    call(port, "/pull", {"id": AC})
    st = pulled(port)
    check("ACE-Step downloaded: four files, whole", not st["err"] and row(port, AC)["ready"] and models(port)["main"]["audio"] == AC)
    r = call(port, "/audio", {"caption": "calm lo-fi piano, soft drums", "duration": 30, "bpm": 80})
    g = json.loads((base / "last_graph.json").read_text())
    check("a song: 200, audio/mpeg, made by ACE-Step", r[0] == 200 and r[1].get("Content-Type") == "audio/mpeg"
          and r[2][:3] == b"ID3" and r[1].get("X-Model") == AC)
    check("the graph: style, an instrumental, 30 s in both places, 80 bpm, English", g["94"]["inputs"]["tags"]
          == "calm lo-fi piano, soft drums" and g["94"]["inputs"]["lyrics"] == "[Instrumental]"
          and g["94"]["inputs"]["duration"] == 30.0 and g["98"]["inputs"]["seconds"] == 30.0 and g["94"]["inputs"]["bpm"] == 80
          and g["94"]["inputs"]["language"] == "en" and g["94"]["inputs"]["seed"] == g["3"]["inputs"]["seed"]
          and g["111"]["inputs"]["format"] == "mp3")
    check("the song is off the disk after it went", not any((base / "output").iterdir()))
    r = call(port, "/audio", {"caption": "песня про кота", "lyrics": "[verse]\nкот на окне", "language": "ru", "duration": 90})
    g = json.loads((base / "last_graph.json").read_text())
    check("a song with words in Russian", r[0] == 200 and g["94"]["inputs"]["language"] == "ru"
          and g["94"]["inputs"]["lyrics"].startswith("[verse]"))
    check("a language it hasn't — 400", call(port, "/audio", {"caption": "x", "language": "xx"})[0] == 400)
    check("5 s — too short, 400", call(port, "/audio", {"caption": "x", "duration": 5})[0] == 400)
    check("no style — 400", call(port, "/audio", {"lyrics": "la la"})[0] == 400)
    check("a picture prompt to /audio isn't a song — 400", call(port, "/audio", {"prompt": "x"})[0] == 400)

    # ---- a job running: no removal, no freeing
    res = []
    th = threading.Thread(target=lambda: res.append(call(port, "/image", {"prompt": "SLOW fox"})[0]))
    th.start()
    time.sleep(0.6)
    r = call(port, "/remove", {"id": AC})
    r2 = call(port, "/free", {})
    h = js(call(port, "/health"))
    th.join()
    check("removal under a running job — 409 busy", r[0] == 409 and js(r)["why"] == "busy")
    check("freeing the card under a running job — 409", r2[0] == 409)
    check("health says what runs", (h.get("job") or {}).get("kind") == "image" and h["busy"])
    check("the job itself ended well", res == [200])
    r = call(port, "/free", {})
    check("/free: ComfyUI lets go of the card", r[0] == 200 and js(r)["freed"])

    # ---- quiet: models out, then ComfyUI off
    check("ComfyUI off after 4 s of quiet", wait(lambda: js(call(port, "/health"))["comfy"] == "stopped", 7))
    VRAM.write_text("10000, 16376\n")
    r = call(port, "/audio", {"caption": "x"})
    check("the card taken (6.2 GiB free) — 409, ComfyUI not started", r[0] == 409 and js(r)["why"] == "card"
          and js(call(port, "/health"))["comfy"] == "stopped")
    VRAM.write_text("600, 16376\n")
    r = call(port, "/start", {})
    check("/start: ComfyUI up for the browser", r[0] == 200 and js(call(port, "/health"))["comfy"] == "running")
    time.sleep(3)
    cport = int(js(r)["ui"].rsplit(":", 1)[1])
    call(cport, "/prompt", {"prompt": {"6": {"class_type": "CLIPTextEncode", "inputs": {"text": "from the browser"}},
                                       "9": {"class_type": "SaveImage", "inputs": {"filename_prefix": "b"}}}})
    time.sleep(2.2)
    check("the browser's work keeps ComfyUI up", js(call(port, "/health"))["comfy"] == "running")
    check("and then it stops by quiet too", wait(lambda: js(call(port, "/health"))["comfy"] == "stopped", 8))
    call(port, "/start", {})
    r = call(port, "/stop", {})
    check("/stop stops at once", r[0] == 200 and js(r)["stopped"] is True and js(call(port, "/health"))["comfy"] == "stopped")

    m = models(port)
    check("the bytes: ComfyUI's models counted, the other folder too", m["bytes"]["comfy"] > 0 and m["bytes"]["also"] == 0
          and m["bytes"]["other"] == 0 and m["cap"] is None and m["keep"] == 0)
    (base / "models/loras").mkdir(exist_ok=True)
    (base / "models/loras/mine.safetensors").write_bytes(b"x" * 1000)
    (base / "also/model.gguf").write_bytes(b"y" * 5000)
    time.sleep(5.2)
    m = models(port)
    check("a file of no set and another folder's model — counted apart", m["bytes"]["other"] == 1000 and m["bytes"]["also"] == 5000)

    log = (base / "gate.out").read_text()
    check("no prompt's words in the log", "TOP-SECRET" not in log and "кот" not in log and "from the browser" not in log)
    check("the log has the jobs, the downloads and the stop", "z-image-turbo: a picture 1024×1024" in log
          and "ace-step-1.5-turbo: a song of 30 s" in log and "is on the disk" in log and "ComfyUI stopped" in log)

    # ---- the room: the disk's own rule and the cap of all models together
    p2, port2, base2 = start_gate("room", GATE_KEEP_GB="1e9")
    procs.append(p2)
    r = call(port2, "/pull", {"id": AC})
    check("the disk would keep less than it must — 507 room, nothing downloaded", r[0] == 507 and js(r)["why"] == "room"
          and not (base2 / "models/diffusion_models").exists())
    cap = (own_bytes(AC, [f["name"] for f in BY_SET[AC]["files"]]) + 5000) / 1e9
    p3, port3, base3 = start_gate("cap", GATE_CAP_GB=str(cap))
    procs.append(p3)
    m = models(port3)
    check("the cap is in the list's answer", m["cap"] == int(cap * 1e9))
    r = call(port3, "/pull", {"id": AC, "ollama": 10_000})
    check("past the cap with Ollama's bytes Pult counted — 507 cap", r[0] == 507 and js(r)["why"] == "cap")
    r = call(port3, "/pull", {"id": AC, "ollama": 1000})
    check("within the cap — it starts", r[0] == 202)
    pulled(port3)
    r = call(port3, "/pull", {"id": ZI})
    check("Pult said nothing: Ollama's own list counted (16 MB) — past the cap", r[0] == 507 and js(r)["why"] == "cap")

    # ---- ComfyUI that doesn't come up
    p4, port4, base4 = start_gate("crash", comfy_extra="--crash")
    procs.append(p4)
    put(base4, ZI)
    time.sleep(5.2)
    r = call(port4, "/image", {"prompt": "a fox"})
    check("ComfyUI fell at its start — 503 and the end of its log", r[0] == 503 and "oops: no CUDA" in err(r))
    p5, port5, base5 = start_gate("slow", comfy_extra="--slow 5", GEN_START_TIMEOUT="2")
    procs.append(p5)
    put(base5, ZI)
    time.sleep(5.2)
    r = call(port5, "/image", {"prompt": "a fox"})
    check("ComfyUI didn't answer in time — 504, the process gone", r[0] == 504 and js(call(port5, "/health"))["comfy"] == "stopped")

    r = call(port, "/start", {})
    cport = int(js(r)["ui"].rsplit(":", 1)[1])
    p.terminate()
    p.wait(15)
    check("the service stops — ComfyUI with it", p.returncode == 0 and not port_open(cport))
finally:
    for x in procs:
        if x.poll() is None:
            x.terminate()
            try:
                x.wait(10)
            except subprocess.TimeoutExpired:
                x.kill()

print("\n%s: %d failed" % ("ALL GOOD" if not fails else "SOME FAILED", fails))
sys.exit(1 if fails else 0)
