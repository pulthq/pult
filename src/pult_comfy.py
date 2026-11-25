"""Pult's side of the gateway beside ComfyUI (stage M, step 6.7; the owner, 2026-11-21: "as with Ollama, I'd like to
manage the local models from Pult without you, in ComfyUI too"; 2026-11-25: "music there as well").

The gateway (deploy/comfy-gate/comfy_gate.py) runs on the computer with the graphics card, beside ComfyUI, at GATE_PORT
of the same address as Ollama — through the same tunnel. It keeps the verified list of sets of models (its sets.json),
downloads them from Hugging Face itself, checks each file's sha256, removes them, and starts ComfyUI only for a job.
Here: the client — what it says, a download, a removal, the main set, a trial picture or song — and the room's
arithmetic: the disk keeps its reserve, and all models together (Ollama's, ComfyUI's, the gateway's other folders) stay
within the server's cap. Nothing here runs anything on the server: the gateway takes only its own list's ids.

The daemon loads this module beside itself and never imports pultd (it runs as __main__)."""
import re

import httpx

GATE_PORT = 8190
GATE_V = 2                 # the gateway this Pult speaks; the first one (lesson 4's, no "v") has no models to manage
TIMEOUT = 8                # s for the list and the small requests: the gateway answers them without ComfyUI
JOB_TIMEOUT = 960          # s for a trial: ComfyUI's start (a minute, cold) and the job; the gateway's own limit is 900
JOB_MAX = 6 * 1024 * 1024  # bytes of a trial's file the app is given: in base64 it must fit the relay's 8 MB frame
LOOPBACK = re.compile(r"http://(127\.0\.0\.1|localhost|\[::1\])(:\d{1,5})?")
SET_ID = re.compile(r"[a-z0-9][a-z0-9.-]{0,39}")
KINDS = ("image", "audio")
# the trial's words: what the model is asked to make — in English, the language these models know best. A picture at
# its real size shows its real speed; a song — 20 s of an instrumental, a quick "does it sing at all"
TRIAL = {"image": {"prompt": "a red fox curled up asleep in fresh snow at dawn, soft light, detailed fur, photo",
                   "width": 1024, "height": 1024},
         "audio": {"caption": "calm lo-fi hip hop, mellow piano chords, soft drums, warm vinyl crackle",
                   "lyrics": "[Instrumental]", "duration": 20, "bpm": 80, "language": "en"}}
MIME = {"image": "image/png", "audio": "audio/mpeg"}


class GateError(Exception):
    """kind: "net" — nothing answers; "old" — the first gateway, without models; "proto" — an answer not like the
    gateway's; else the gateway's own word ("busy", "room", "cap", "notready"…); text — its words."""

    def __init__(self, kind, text=""):
        super().__init__("%s: %s" % (kind, text))
        self.kind, self.text = kind, text


def gate_url(local_url):
    """The gateway's address beside a local server's: its own host, GATE_PORT; None — not this computer's loopback
    (the gateway listens on 127.0.0.1 there, and only a tunnel brings it here)."""
    m = LOOPBACK.fullmatch(str(local_url or "").rstrip("/"))
    return "http://%s:%d" % (m.group(1), GATE_PORT) if m else None


def _int(x):
    return x if isinstance(x, int) and not isinstance(x, bool) and x >= 0 else None


def _str(x, most=80):
    return x[:most] if isinstance(x, str) else None


def clean(d):
    """The gateway's /models, taken only as far as it is what it should be. → {"v", "comfy": {"version", "state",
    "loaded", "idle", "stop_after"}, "sets": [...], "main": {kind: id}, "pull", "job", "bytes": {"comfy", "also",
    "other"}, "disk": {"label", "free", "total"} | None, "keep", "cap"}; ValueError — not the gateway's answer."""
    if not isinstance(d, dict) or not isinstance(d.get("sets"), list) or not isinstance(d.get("v"), int):
        raise ValueError("not the gateway's list")
    c = d.get("comfy") if isinstance(d.get("comfy"), dict) else {}
    sets = []
    for s in d["sets"]:
        if not isinstance(s, dict) or not isinstance(s.get("id"), str) or not SET_ID.fullmatch(s["id"]) or s.get("kind") not in KINDS:
            continue
        files = [{"folder": _str(f.get("folder"), 40), "name": _str(f.get("name"), 160), "size": _int(f.get("size")) or 0,
                  "have": f.get("have") is True, "part": _int(f.get("part")) or 0,
                  "shared": [x for x in f.get("shared") or [] if isinstance(x, str) and SET_ID.fullmatch(x)]}
                 for f in s.get("files") or [] if isinstance(f, dict)]
        sets.append({"id": s["id"], "kind": s["kind"], "name": _str(s.get("name"), 60) or s["id"],
                     "maker": _str(s.get("maker")), "released": _str(s.get("released"), 10), "license": _str(s.get("license"), 40),
                     "params": _str(s.get("params"), 12), "steps": _int(s.get("steps")),
                     "vram_gb": s.get("vram_gb") if isinstance(s.get("vram_gb"), (int, float)) and not isinstance(s.get("vram_gb"), bool) else None,
                     "does": [x for x in s.get("does") or [] if isinstance(x, str) and re.fullmatch(r"[a-z]{1,16}", x)],
                     "langs": _int(s.get("langs")), "tried": s.get("tried") is not False,
                     "files": files, "size": _int(s.get("size")) or sum(f["size"] for f in files),
                     "ready": s.get("ready") is True, "need": _int(s.get("need")) or 0, "frees": _int(s.get("frees")) or 0})
    p = d.get("pull") if isinstance(d.get("pull"), dict) else None
    pull = None
    if p and isinstance(p.get("id"), str):
        pull = {"id": p["id"], "name": _str(p.get("name"), 60) or p["id"], "total": _int(p.get("total")) or 0,
                "done": _int(p.get("done")) or 0, "rate": _int(p.get("rate")) or 0, "since": _int(p.get("since")),
                "file": _str(p.get("file"), 160), "phase": _str(p.get("phase"), 12), "end": _int(p.get("end")),
                "err": _str(p.get("err"), 300), "why": _str(p.get("why"), 20), "stopped": p.get("stopped") is True,
                "run": p.get("run") is True}
    j = d.get("job") if isinstance(d.get("job"), dict) else None
    disk = d.get("disk") if isinstance(d.get("disk"), dict) else {}
    b = d.get("bytes") if isinstance(d.get("bytes"), dict) else {}
    main = d.get("main") if isinstance(d.get("main"), dict) else {}
    return {"v": d["v"], "comfy": {"version": _str(c.get("version"), 20), "state": "running" if c.get("state") == "running" else "stopped",
                                   "loaded": c.get("loaded") is True, "idle": _int(c.get("idle_s")),
                                   "stop_after": _int(c.get("stop_after_s"))},
            "sets": sets, "main": {k: main.get(k) if isinstance(main.get(k), str) else None for k in KINDS}, "pull": pull,
            "job": {"kind": j.get("kind"), "model": _str(j.get("model"), 40), "since": _int(j.get("since"))}
            if j and j.get("kind") in KINDS else None,
            "bytes": {k: _int(b.get(k)) or 0 for k in ("comfy", "also", "other")},
            "disk": {"label": _str(disk.get("label"), 24) or "", "free": disk["free"], "total": disk["total"]}
            if _int(disk.get("free")) is not None and _int(disk.get("total")) else None,
            "keep": _int(d.get("keep")) or 0, "cap": _int(d.get("cap")) or None}


def _client(transport, timeout):
    kw = dict(transport=transport) if transport is not None else {}
    return httpx.AsyncClient(timeout=httpx.Timeout(timeout, connect=5), trust_env=False, **kw)


def _why(r):
    try:
        d = r.json()
        return str(d.get("why") or "other")[:20], str(d.get("error") or "")[:300]
    except ValueError:
        return "proto", "HTTP %d" % r.status_code


async def models(url, transport=None):
    """The gateway's list and what of it is on the disk. GateError "net" — nothing answers; "old" — the first gateway
    (it answers /health, not /models); "proto" — something else answers there."""
    try:
        async with _client(transport, TIMEOUT) as c:
            r = await c.get(url + "/models")
            if r.status_code == 404:
                h = await c.get(url + "/health")
                if h.status_code == 200 and isinstance(h.json(), dict) and "comfy" in h.json():
                    raise GateError("old", "")
            if r.status_code != 200:
                raise GateError("proto", "HTTP %d" % r.status_code)
            return clean(r.json())
    except httpx.TransportError as e:
        raise GateError("net", type(e).__name__) from None
    except ValueError as e:
        raise GateError("proto", str(e)[:80]) from None


async def post(url, path, body=None, transport=None):
    """A small request to the gateway (/pull, /pull/stop, /remove, /main, /free, /stop). → its JSON; GateError with
    the gateway's word when it says no."""
    try:
        async with _client(transport, TIMEOUT + 30) as c:
            r = await c.post(url + path, json=body or {})
    except httpx.TransportError as e:
        raise GateError("net", type(e).__name__) from None
    if r.status_code not in (200, 202):
        raise GateError(*_why(r))
    try:
        return r.json()
    except ValueError:
        raise GateError("proto", "not JSON") from None


async def job(url, kind, model, transport=None):
    """A trial: the model makes the trial's picture or song. → (bytes, {"seed", "secs", "start", "cached"}); GateError
    with the gateway's word."""
    body = dict(TRIAL[kind], model=model)
    try:
        async with _client(transport, JOB_TIMEOUT) as c:
            r = await c.post(url + "/" + kind, json=body)
    except httpx.TransportError as e:
        raise GateError("net", type(e).__name__) from None
    if r.status_code != 200:
        raise GateError(*_why(r))
    blob = r.content
    if not blob or len(blob) > JOB_MAX:
        raise GateError("proto", "%d bytes" % len(blob))

    def num(h):
        try:
            return float(r.headers.get(h) or 0)
        except ValueError:
            return 0.0
    return blob, {"seed": r.headers.get("X-Seed", "")[:24], "secs": num("X-Seconds"), "start": num("X-Start-Seconds"),
                  "cached": r.headers.get("X-Cached") == "1"}


def room(m, ollama, need):
    """What a download of need bytes leaves: the disk's free bytes after it against the reserve the server keeps, and
    all models together after it against the server's cap (None — no cap there). ollama — Ollama's models on the disk,
    as Pult counts them (by their weights: a copy with another context holds none of its own). → {"after", "keep",
    "disk_ok", "cap", "total", "cap_ok", "ok"}; after is None when the disk isn't known."""
    disk = m.get("disk")
    after = disk["free"] - need if disk else None
    keep = m.get("keep") or 0
    total = (m["bytes"]["comfy"] + m["bytes"]["also"] + (ollama or 0)) + need
    cap = m.get("cap")
    disk_ok = after is None or after >= keep
    cap_ok = cap is None or total <= cap
    return {"after": after, "keep": keep, "disk_ok": disk_ok, "cap": cap, "total": total, "cap_ok": cap_ok,
            "ok": disk_ok and cap_ok}
