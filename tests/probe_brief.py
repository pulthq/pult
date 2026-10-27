"""Probe: what it costs to have a small model read a turn's result (stage V, "whose move"). Claude Code + Agent SDK.

At the end of a turn Pult wants one plain line about the outcome and an answer to "does Claude wait for the owner?".
This probe runs the same request Pult would: haiku through the owner's subscription, no tools, no settings, Pult's
own short system prompt in place of Claude Code's, JSON by schema, no transcript left behind. For each sample it
prints the answer, the wall time, the claude process's peak memory and the tokens; then checks that no session file
appeared. Run (a few tiny haiku requests): ~/.local/share/pult/venv/bin/python tests/probe_brief.py [ru|en]
"""
import asyncio, os, subprocess, sys, tempfile, time
from pathlib import Path
from claude_agent_sdk import ResultMessage, query

SRC = Path(__file__).resolve().parent.parent / "src"
sys.path.insert(0, str(SRC))
import pult_brief as B  # noqa: E402

LANG = sys.argv[1] if len(sys.argv) > 1 else "ru"
CWD = Path(tempfile.mkdtemp(prefix="pult-brief-"))
PROJECTS = Path.home() / ".claude" / "projects"

SAMPLES = [
    ("задачи 1–5 по передаче MT6835, потом ревью",
     "Черновик D-0047 написан, запасы порогов проверены: остаток ×1,5 / ×1,27, Δc ×2,4 / ×2,8, Δoff ×2,0 / ×2,3. "
     "Жду повтор A и ревью T-0048.", ["Review T-0048 far-wall rescue"], None),     # Claude continues: "you" unused
    ("сделай кэш для списка проектов",
     "Сделал два варианта: А — кэш в памяти, Б — в SQLite. А быстрее, Б переживает перезапуск демона. Какой берём?",
     [], True),
    ("выложи 0.9.16",
     "Готово: v0.9.16 на GitHub, проверки в чистом окружении 75+31+14+5 зелёные, Actions зелёные на macOS и Ubuntu.",
     [], False),
    ("put the Groq key in place",
     "I couldn't write the key to ~/.config/pult/env — the auto-mode classifier blocks writes to secret stores. "
     "Run this in Terminal (the key is not printed): `pult stt`. The daemon picks it up by itself.", [], True),
    ("выложи 0.9.17",                                       # a yes/no question: ready replies expected
     "Собрал выпуск 0.9.17, проверки в чистом окружении зелёные. Выкладывать на GitHub? Нужно твоё «да».", [], True),
]


def peak_rss(stop, out):
    """The largest memory of any claude process under this one while the request runs (ps, every 0.1 s)."""
    me = os.getpid()
    while not stop.is_set():
        try:
            kids = subprocess.run(["pgrep", "-P", str(me)], capture_output=True, text=True).stdout.split()
            for k in kids:
                rss = subprocess.run(["ps", "-o", "rss=", "-p", k], capture_output=True, text=True).stdout.strip()
                if rss:
                    out[0] = max(out[0], int(rss) * 1024)
        except OSError:
            pass
        time.sleep(0.1)


async def one(prompt, reply, bg):
    import threading
    stop, peak = threading.Event(), [0]
    th = threading.Thread(target=peak_rss, args=(stop, peak), daemon=True)
    th.start()
    t0 = time.time()
    res = None
    async for m in query(prompt=B.request(prompt, reply, bg), options=B.options(LANG, CWD)):
        if isinstance(m, ResultMessage):
            res = m
    stop.set()
    th.join()
    return res, time.time() - t0, peak[0]


async def main():
    before = set(PROJECTS.glob("*/*.jsonl"))
    tot_in = tot_out = 0
    for prompt, reply, bg, want in SAMPLES:
        res, secs, peak = await one(prompt, reply, bg)
        brief = B.parse(res)
        u = res.usage or {}
        tin = (u.get("input_tokens") or 0) + (u.get("cache_read_input_tokens") or 0) + (u.get("cache_creation_input_tokens") or 0)
        tout = u.get("output_tokens") or 0
        tot_in, tot_out = tot_in + tin, tot_out + tout
        ok = brief is not None and (want is None or brief["you"] == want)
        print("%s %.1f s · peak %d MB · in %d (cache read %d) · out %d · $%.4f" % (
            "OK  " if ok else "MISS", secs, peak // 2**20, tin, u.get("cache_read_input_tokens") or 0, tout,
            res.total_cost_usd or 0), flush=True)
        print("     ", brief, flush=True)
    after = set(PROJECTS.glob("*/*.jsonl"))
    new = [p for p in after - before if "pult-brief-" in str(p)]
    print("session files left behind:", len(new), [str(p) for p in new][:3])
    print("total tokens: in %d, out %d" % (tot_in, tot_out))


asyncio.run(main())
