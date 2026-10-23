"""Every picture of the README, made from the test stand and the daemon's own output — never from real projects.

  ~/.local/share/pult/venv/bin/python tools/media.py          # both languages, both themes, a few minutes

  media/hero.{en,ru}[.dark].gif     the opening picture: the computer's Claude Code tab and the phone's topic side by
                                    side — a question on both, Allow on the phone, the tab goes on (tools/hero.py)
  media/steps.{en,ru}[.dark].png    how it works in three steps
  media/f-<name>.{en,ru}[.dark].png one phone screen per feature: home, session, pace, files, newproject
  media/social.png                  1280×640, the link preview: GitHub takes it only in the repository's settings
                                    (Settings → General → Social preview); there is no API for it
  media/logo.svg, logo-512.png      the mark — tools/brand.py draws them

One picture says one thing and holds one phone, readable on GitHub's phone app; ".dark" goes to the README's
<picture> for GitHub's dark theme. The stand (tools/stand.py) runs with a VS Code tab on its session; the screens are
drawn by tools/shot.py.
"""
import os, shutil, subprocess, sys, tempfile, time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
MEDIA = REPO / "media"
PY = sys.executable
TMP = Path(tempfile.mkdtemp(prefix="pult-media-"))
FONT = "-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif"

# a feature's screen: the stand's link, the window's height (CSS px at 412 wide), what to do before the picture
TO_BOTTOM = "window.scrollTo(0, document.documentElement.scrollHeight)"
FEATURES = [
    ("home", "HOME", 760, ""),
    ("session", "SESS4", 760, TO_BOTTOM),
    ("pace", "USAGE", 700, "document.querySelector('.spend-seg button').click()"),
    ("files", "SESS4", 700, "document.querySelector('.tfline').click()"),
    ("newproject", "NEWPROJ", 640, ""),
]

STEPS = {
    "en": [("Work as usual", "VS Code or a terminal: Pult picks up every session"),
           ("Your phone rings only when needed", "a permission, a question, a turn that waits for you"),
           ("Answer — the tab goes on", "allow, pick, reply: it lands in the open tab")],
    "ru": [("Работаешь как обычно", "VS Code или терминал: Пульт подхватит каждую сессию"),
           ("Телефон зовёт, только когда нужен ты", "разрешение, вопрос, ход, который ждёт тебя"),
           ("Ответил — во вкладке пошло дальше", "разрешить, выбрать, ответить — прямо в открытую вкладку")],
}
ICONS = [  # computer, phone with the warm dot, check — the app's own line icons
    '<rect x="2.5" y="3.5" width="19" height="13" rx="2"/><path d="M8 21h8M12 16.5V21"/>',
    '<rect x="6" y="2" width="12" height="20" rx="2.6"/><path d="M11 18h2"/>',
    '<path d="M20 6 9 17l-5-5"/>',
]


def shot(url, out, width=412, wait=6, dark=False, **env):
    subprocess.run([PY, str(REPO / "tools" / "shot.py"), url, str(out), str(width), str(wait)] + (["dark"] if dark else []),
                   check=True, stdout=subprocess.DEVNULL, env=dict(os.environ, **env))


def page(name, body, css):
    p = TMP / name
    # the viewport: without it a mobile window narrower than 980 px lays the page out at 980 and shrinks it
    p.write_text('<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width"><style>'
                 '* { box-sizing: border-box; } html, body { margin: 0; background: transparent; } body { font-family: %s; }'
                 '%s</style>%s' % (FONT, css, body), encoding="utf-8")
    return p.as_uri()


def screens(lang):
    """The features' screens from a stand in this language, light and dark: {(name, dark): png}."""
    log = TMP / ("stand.%s.out" % lang)            # a file, not a pipe: a full pipe would stall the stand mid-shot
    with open(log, "w") as f:
        stand = subprocess.Popen([PY, str(REPO / "tools" / "stand.py")], stdout=f, stderr=subprocess.DEVNULL,
                                 env=dict(os.environ, STAND_TAB="1", STAND_LANG=lang, HOLD="400"))
    urls = {}
    try:
        for _ in range(120):
            urls = dict(l.partition(" ")[::2] for l in log.read_text().splitlines() if " http" in l)
            if "NEWPROJ" in urls:
                break
            time.sleep(0.5)
        out = {}
        for name, key, height, js in FEATURES:
            for dark in (False, True):
                png = TMP / ("%s.%s%s.png" % (name, lang, ".dark" if dark else ""))
                shot(urls[key], png, dark=dark, SHOT_HEIGHT=str(height), **({"SHOT_JS": js} if js else {}))
                out[(name, dark)] = png
        return out
    finally:
        stand.terminate()
        stand.wait()


def framed(img, out, dark):
    """One phone's screen with round corners and a hairline, on a transparent background — no shadow: it would vanish
    on GitHub's dark theme."""
    line = "rgba(255,255,255,.16)" if dark else "rgba(15,23,42,.14)"
    css = (".f { width: max-content; padding: 4px; } .ph { width: 412px; border-radius: 34px; overflow: hidden; border: 1.5px solid %s; }"
           " .ph img { display: block; width: 100%%; }" % line)
    shot(page(out.stem + ".html", '<div class="f"><div class="ph"><img src="%s"></div></div>' % img.as_uri(), css),
         out, width=422, wait=2, SHOT_FIT=".f", SHOT_CLEAR="1")


def steps(lang, dark, out):
    """How it works in three steps, one under another — so its words stay readable in GitHub's phone app too: an
    icon, a few words, a line under them; a thin line joins them."""
    ink, mute, card, line = ("#e9ebef", "#9aa3b0", "#1a1e25", "rgba(255,255,255,.10)") if dark else ("#171a21", "#626a77", "#ffffff", "rgba(15,23,42,.10)")
    tones = ["#6ea2f0", "#f3a64a", "#58c088"] if dark else ["#4f8be8", "#e8892b", "#2c9a63"]
    cells = []
    for i, ((title, sub), path) in enumerate(zip(STEPS[lang], ICONS)):
        cells.append('<div class="c"><div class="i" style="color:%s;background:%s"><svg viewBox="0 0 24 24" width="30" height="30" fill="none" '
                     'stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round">%s</svg></div>'
                     '<div class="w"><b><span class="n">%d</span>%s</b><span>%s</span></div></div>' % (tones[i], tones[i] + "1f", path, i + 1, title, sub))
    body = '<div class="s">%s</div>' % '<div class="j"></div>'.join(cells)
    css = (".s { width: 560px; padding: 6px; }"
           ".c { display: flex; align-items: center; gap: 18px; background: %s; border: 1.5px solid %s; border-radius: 22px; padding: 18px 22px; }"
           ".i { flex: none; width: 58px; height: 58px; border-radius: 17px; display: flex; align-items: center; justify-content: center; }"
           ".w { min-width: 0; } .n { color: %s; margin-right: 9px; font-weight: 700; }"
           "b { display: block; font-size: 21px; line-height: 1.25; color: %s; letter-spacing: -.01em; }"
           ".w > span { display: block; margin-top: 4px; font-size: 16px; line-height: 1.35; color: %s; }"
           ".j { width: 2px; height: 16px; margin: 0 0 0 52px; background: %s; }" % (card, line, mute, ink, mute, line))
    shot(page(out.stem + ".html", body, css), out, width=572, wait=1, SHOT_FIT=".s", SHOT_CLEAR="1")


def social(still, out):
    """The link preview: the mark, the name and what it does on the left; the opening picture's first frame on the right."""
    logo = (MEDIA / "logo.svg").read_text(encoding="utf-8").replace("<svg ", '<svg width="96" height="96" ', 1)
    body = """<div class="card"><div class="text"><div class="mk">%s<div class="name">Pult</div></div>
      <div class="tag">Every Claude Code session on your computer — in Telegram.</div>
      <div class="chips"><span>macOS · Linux · Windows</span><span>Telegram + web app</span><span>MIT</span></div>
      <div class="url">github.com/pulthq/pult</div></div><img class="hero" src="%s"></div>""" % (logo, still.as_uri())
    css = """.card { position: relative; width: 1280px; height: 640px; overflow: hidden;
        background: radial-gradient(circle at 80% 30%, #dbe7fb 0, #eef3fa 45%, #f6f8fb 100%); }
      .text { position: absolute; left: 70px; top: 112px; width: 470px; color: #14213d; }
      .mk { display: flex; align-items: center; gap: 22px; }
      .name { font-size: 92px; font-weight: 800; letter-spacing: -2px; line-height: 1; }
      .tag { margin-top: 30px; font-size: 36px; line-height: 1.25; font-weight: 600; color: #26344f; }
      .chips { margin-top: 32px; display: flex; flex-wrap: wrap; gap: 10px; }
      .chips span { padding: 6px 12px; border-radius: 999px; background: #fff; border: 1px solid #d5deea; font-size: 16px; color: #3a4a66; font-weight: 600; }
      .url { margin-top: 34px; font-size: 21px; color: #5d6b82; }
      .hero { position: absolute; left: 570px; top: 120px; width: 690px; border-radius: 18px; }"""
    big = TMP / "social-2x.png"
    shot(page("social.html", body, css), big, width=1280, wait=2, SHOT_HEIGHT="640")
    subprocess.run(["sips", "-z", "640", "1280", str(big), "--out", str(out)], check=True, stdout=subprocess.DEVNULL)


def main():
    MEDIA.mkdir(exist_ok=True)
    subprocess.run([PY, str(REPO / "tools" / "brand.py")], check=True, stdout=subprocess.DEVNULL)
    still = None
    for lang in ("en", "ru"):
        s = screens(lang)
        for (name, dark), png in s.items():
            framed(png, MEDIA / ("f-%s.%s%s.png" % (name, lang, ".dark" if dark else "")), dark)
        for dark in (False, True):
            sfx = ".dark" if dark else ""
            steps(lang, dark, MEDIA / ("steps.%s%s.png" % (lang, sfx)))
            gif = MEDIA / ("hero.%s%s.gif" % (lang, sfx))
            subprocess.run([PY, str(REPO / "tools" / "hero.py"), str(gif)] + (["dark"] if dark else []), check=True,
                           env=dict(os.environ, STAND_LANG=lang), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            first = gif.with_suffix(".png")          # hero.py leaves its first frame next to the animation
            if lang == "en" and not dark:
                still = TMP / "hero-first.png"
                shutil.move(first, still)
            else:
                first.unlink()
        print(lang, "done", flush=True)
    social(still, MEDIA / "social.png")
    for p in sorted(MEDIA.iterdir()):
        print("%-28s %5.0f KB" % (p.name, p.stat().st_size / 1024))


if __name__ == "__main__":
    t0 = time.time()
    main()
    print("%.0f s" % (time.time() - t0))
