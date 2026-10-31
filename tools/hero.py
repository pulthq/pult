"""The README's opening picture: one model does a task, another checks it — in the app inside Telegram (the universal
remote, Q113). The phone is the app itself on the test stand (tools/stand.py, made-up data): Home with a task on Opus
beside one on DeepSeek, New task's "Who does it", DeepSeek's outcome with "Second opinion · Codex", Codex reading
(tests/fake_codex.py stands in for it), its two findings and "Send to DeepSeek" — the button names the doer (Q116).
Above the phone: the three steps — does it, checks it, fixes it — and a line saying what happens.

  STAND_LANG=ru ~/.local/share/pult/venv/bin/python tools/hero.py media/hero.ru.gif [dark]

The first frame — two models at work on Home — stands on its own: GitHub shows only it when animations are paused; it
is left next to the animation as a PNG (tools/media.py takes it for the link preview). The screens are taken in headless
Chrome over DevTools (tools/_cdp.py), the frames drawn by tools/shot.py and joined with ffmpeg. Run it from a clean
worktree of a commit: the stand takes src/ and the app from the folder it is in."""
import asyncio, html, os, shutil, subprocess, sys, tempfile, time
from pathlib import Path

import _cdp

REPO = Path(__file__).resolve().parent.parent
LANG = os.environ.get("STAND_LANG", "en")
OUT = Path(sys.argv[1] if len(sys.argv) > 1 else "hero.%s.gif" % LANG).resolve()
DARK = len(sys.argv) > 2 and sys.argv[2] == "dark"
PW, PH = 412, 760            # the phone's screen, CSS px — as the README's other screens
W, H = 440, 874              # the frame: the steps and a line above the phone, which runs to its bottom; drawn at 2×
GIF_W = 660                  # shown at about 420 in the README: sharp on a phone's screen, a few hundred KB

D = {
    "en": dict(steps=("does it", "checks it", "fixes it"), who="Who does it", send="Send to DeepSeek", lines=(
        "Tasks run on different models — Opus and DeepSeek", "You pick who does a task: Claude, DeepSeek, GLM or Kimi",
        "DeepSeek is done — under its outcome, a second opinion", "Codex reads what the task changed — and only reads",
        "Two findings, each at its place in the code", "Back to the doer in one tap")),
    "ru": dict(steps=("делает", "проверяет", "исправляет"), who="Кто делает", send="Отправить DeepSeek", lines=(
        "Задачи идут на разных моделях — Opus и DeepSeek", "Кто делает задачу — выбираешь сам: Claude, DeepSeek, GLM, Kimi",
        "DeepSeek закончил — под итогом второе мнение", "Codex читает, что изменила задача, — и только читает",
        "Два замечания — у каждого место в коде", "Замечания — исполнителю одним касанием")),
}[LANG if LANG in ("en", "ru") else "en"]

# a step keeps its colour: green — the doer at work (the app's "running"), violet — the second opinion, blue — your tap
TONES = ("#58c088", "#b48cf0", "#6ea2f0") if DARK else ("#2c9a63", "#8b5cf6", "#2f6fcf")
THEME = (dict(bg="linear-gradient(135deg,#17233a,#221a12)", ink="#e9ebef", mute="#9aa3b0", chip="rgba(255,255,255,.07)",
              line="rgba(255,255,255,.16)")
         if DARK else
         dict(bg="linear-gradient(135deg,#e6eefb,#f7efe4)", ink="#171a21", mute="#5d6675", chip="rgba(255,255,255,.75)",
              line="rgba(15,23,42,.14)"))
CSS = """
* { box-sizing: border-box; }
html, body { margin: 0; background: transparent; }
body { font: 15px/1.35 -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; }
.stage { position: relative; width: %(W)dpx; height: %(H)dpx; border-radius: 26px; overflow: hidden; background: %(bg)s;
  padding: 14px 14px 0; display: flex; flex-direction: column; }
.steps { display: flex; gap: 6px; }
.s { flex: 1; padding: 6px 4px; border-radius: 999px; text-align: center; font-weight: 650; font-size: 14px; color: %(mute)s;
  background: %(chip)s; white-space: nowrap; }
.s b { margin-right: 4px; }
.s.on { color: #fff; }
.line { height: 48px; margin: 9px 4px 10px; display: flex; align-items: center; font-weight: 700; font-size: 17.5px;
  line-height: 1.25; color: %(ink)s; letter-spacing: -.01em; }
.ph { position: relative; width: %(PW)dpx; height: %(PH)dpx; border-radius: 30px 30px 0 0; overflow: hidden;
  border: 1.5px solid %(line)s; border-bottom: 0; margin-top: auto; flex: none; }
.ph img { display: block; width: %(PW)dpx; height: %(PH)dpx; }
.ring { position: absolute; border-radius: 14px; border: 3px solid; box-shadow: 0 0 0 6px rgba(0,0,0,.06); }
""" % dict(W=W, H=H, PW=PW, PH=PH, **THEME)

ASK = "document.querySelector('.card.outcome .sec-ask')"
CARD = "document.querySelector('.card.second')"
SEND = CARD + ".querySelector('.foot .btn')"
WHO = ("[...document.querySelectorAll('.form .field')].find((b) => b.previousElementSibling"
       " && b.previousElementSibling.textContent.trim() === %r)")
VENDOR = "[...document.querySelectorAll('.card.pick.who .opt')].find((b) => b.textContent.trim().startsWith('DeepSeek'))"
BOTTOM = "window.scrollTo(0, document.documentElement.scrollHeight)"
RECT = "(() => { const b = (%s).getBoundingClientRect(); return [b.left, b.top, b.width, b.height]; })()"


def stand():
    """The stand: a task on DeepSeek's model beside one on Opus (STAND_VENDORS), the shop's task with a second opinion
    to ask, its project already allowed (STAND_SECOND=allowed) → its process and its screens' links."""
    out = Path(tempfile.mkdtemp(prefix="hero-")) / "stand.out"
    env = dict(os.environ, STAND_VENDORS="1", STAND_HOMES="1", STAND_SECOND="allowed", STAND_TAB="1", STAND_LANG=LANG,
               STAND_PORT=str(_cdp.any_port()), HOLD="600")
    with open(out, "w") as fh:
        proc = subprocess.Popen([sys.executable, str(REPO / "tools" / "stand.py")], cwd=REPO, env=env, stdout=fh,
                                stderr=subprocess.STDOUT, start_new_session=True)
    for _ in range(240):
        if "NEWPROJ http" in out.read_text(errors="replace"):
            return proc, _cdp.stand_urls(str(out))
        if proc.poll() is not None:
            break
        time.sleep(0.25)
    _cdp.stop(proc)
    sys.exit("hero: the stand didn't come up — " + out.read_text(errors="replace")[-600:])


async def screens(urls, tmp):
    """The phone's screens, in order, each with where a finger goes on it (or None): [(png, rect)]."""
    got = []
    async with _cdp.Page(width=PW, height=PH) as pg:
        if DARK:
            await pg.cmd("Emulation.setEmulatedMedia", features=[{"name": "prefers-color-scheme", "value": "dark"}])

        async def snap(name, ring=None):
            await asyncio.sleep(0.5)
            png = tmp / (name + ".png")
            await pg.shot(str(png))
            got.append((png, await pg.js(RECT % ring) if ring else None))

        async def go(url):          # a page of its own each time: the links differ only after "#", where the app starts
            await pg.open("about:blank")
            await asyncio.sleep(0.3)
            await pg.open(url)

        async def need(what, expr, tries=150):
            if not await pg.until(expr, tries):
                sys.exit("hero: no %s on the stand" % what)

        await go(urls["HOME"])
        await need("task on DeepSeek running on Home", "document.body.innerText.includes('DeepSeek')")
        await snap("home")
        await go(urls["NEW"])
        await need("New task", "!!" + WHO % D["who"])
        await pg.tap(WHO % D["who"], wait=0.6)
        await need("Who does it sheet", "!!" + VENDOR)
        await snap("who", VENDOR)
        await go(urls["SESS4"])
        await need("second opinion under DeepSeek's outcome", "!!" + ASK)
        await pg.js(BOTTOM)
        await snap("outcome", ASK)
        await pg.tap(ASK, wait=0.4)
        await need("Codex reading", CARD + " && " + CARD + ".classList.contains('run')", 60)
        await asyncio.sleep(1.6)    # its clock past "0 s", well before the stand's Codex is done (about five seconds)
        await pg.js(BOTTOM)
        await snap("reading")
        await need("two findings", "document.querySelectorAll('.card.second .sec-list li').length === 2")
        await pg.js(BOTTOM)
        said = (await pg.js(SEND + ".textContent") or "").strip()
        if said != D["send"]:
            sys.exit("hero: the button says %r, not %r — it names the doer (Q116)" % (said, D["send"]))
        await snap("findings")
        got.append((got[-1][0], await pg.js(RECT % SEND)))
        if pg.errors:
            sys.exit("hero: script errors on the page: %s" % pg.errors)
    return got


def frame(png, ring, step, line):
    steps = "".join('<span class="s%s" style="%s"><b>%d</b>%s</span>' % (" on" if i == step else "",
                                                                       "background:%s" % TONES[i] if i == step else "", i + 1, html.escape(s))
                    for i, s in enumerate(D["steps"]))
    mark = ('<i class="ring" style="left:%.0fpx;top:%.0fpx;width:%.0fpx;height:%.0fpx;border-color:%s"></i>'
            % (ring[0] - 5, ring[1] - 5, ring[2] + 10, ring[3] + 10, TONES[step]) if ring else "")
    return ('<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width"><style>%s</style>'
            '<div class="stage"><div class="steps">%s</div><div class="line">%s</div><div class="ph"><img src="%s">%s</div></div>'
            % (CSS, steps, html.escape(line), png.as_uri(), mark))


def gif(frames, out):
    tmp = Path(tempfile.mkdtemp(prefix="hero-"))
    lines = []
    for i, (page, secs) in enumerate(frames):
        src, png = tmp / ("f%02d.html" % i), tmp / ("f%02d.png" % i)
        src.write_text(page, encoding="utf-8")
        subprocess.run([sys.executable, str(REPO / "tools" / "shot.py"), src.as_uri(), str(png), str(W), "1"], check=True,
                       env=dict(os.environ, SHOT_HEIGHT=str(H), SHOT_CLEAR="1"), stdout=subprocess.DEVNULL)
        lines += ["file '%s'" % png, "duration %s" % secs]
        if i == 0:
            first = png
    lines.append("file '%s'" % (tmp / ("f%02d.png" % (len(frames) - 1))))
    (tmp / "list.txt").write_text("\n".join(lines) + "\n")
    # 2× drawn, shown at GIF_W: one palette for the whole run keeps it small; the round corners stay transparent
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "concat", "-safe", "0", "-i", str(tmp / "list.txt"),
                    "-vf", "scale=%d:-1:flags=lanczos,split[a][b];[a]palettegen=max_colors=256:stats_mode=full:reserve_transparent=1[p];"
                           "[b][p]paletteuse=dither=none:alpha_threshold=128" % GIF_W, "-fps_mode", "vfr", "-loop", "0", str(out)], check=True)
    return first


def main():
    proc, urls = stand()
    try:
        shots = asyncio.run(screens(urls, Path(tempfile.mkdtemp(prefix="hero-"))))
    finally:
        _cdp.stop(proc)
    # (screen, step, seconds): Home, Who does it, the outcome, Codex reading, its findings, the tap that sends them
    plan = [(0, 0, 2.8), (1, 0, 2.0), (2, 1, 1.9), (3, 1, 1.5), (4, 1, 2.8), (5, 2, 2.2)]
    frames = [(frame(shots[k][0], shots[k][1], step, D["lines"][k]), secs) for k, step, secs in plan]
    still = gif(frames, OUT)
    png = OUT.with_suffix(".png")
    shutil.copyfile(still, png)
    print("hero", OUT, "%.0f KB" % (OUT.stat().st_size / 1024), "· first frame", png.name)


if __name__ == "__main__":
    main()
