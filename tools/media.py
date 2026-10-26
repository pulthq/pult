"""Every picture of the README, made from the test stand and the daemon's own output — never from real projects.

  ~/.local/share/pult/venv/bin/python tools/media.py          # both languages, both themes, a few minutes
  ~/.local/share/pult/venv/bin/python tools/media.py glance steps   # only these kinds (glance, steps, screens, hero, social)

  media/hero.{en,ru}[.dark].gif     the opening picture: the computer's Claude Code tab and the phone's topic side by
                                    side — a question on both, Allow on the phone, the tab goes on (tools/hero.py)
  media/glance.{en,ru}[.dark].png   what the phone can do, in twelve tiles — the whole of Pult in one look
  media/steps.{en,ru}[.dark].png    how it works in three steps
  media/f-<name>.{en,ru}[.dark].png one phone screen per feature: home, session, tags, pace, files, newproject, parts
                                    (tags and parts come from a second stand: STAND_TAGS=1 STAND_PARTS=now)
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

# a feature's screen: the stand's link, the window's height (CSS px at 412 wide), what to do before the picture, and
# which stand it comes from — the plain one, or the one with a third project full of tagged tasks and every part of
# Pult in Settings' table ("tags": STAND_TAGS=1 STAND_PARTS=now, on a port of its own)
TO_BOTTOM = "window.scrollTo(0, document.documentElement.scrollHeight)"
FEATURES = [
    ("home", "HOME", 760, "", "main"),
    ("session", "SESS4", 760, TO_BOTTOM, "main"),
    ("tags", "PROJT", 760, "", "tags"),
    ("pace", "USAGE", 700, "document.querySelector('.spend-seg button').click()", "main"),
    ("files", "SESS4", 700, "document.querySelector('.tfline').click()", "main"),
    ("newproject", "NEWPROJ", 640, "", "main"),
    ("parts", "SETTINGS", 700, "", "tags"),
]
STANDS = {"main": ("18097", {}), "tags": ("18099", {"STAND_TAGS": "1", "STAND_PARTS": "now"})}

STEPS = {
    "en": [("Work as usual", "VS Code or a terminal: Pult picks up every session"),
           ("Your phone rings only when needed", "a permission, a question, a turn that waits for you"),
           ("Answer — the tab goes on", "allow, pick, reply: it lands in the open tab")],
    "ru": [("Работаешь как обычно", "VS Code или терминал: Пульт подхватит каждую сессию"),
           ("Телефон зовёт, только когда нужен ты", "разрешение, вопрос, ход, который ждёт тебя"),
           ("Ответил — во вкладке пошло дальше", "разрешить, выбрать, ответить — прямо в открытую вкладку")],
}
# what the phone can do: a title of a few words and a line under it — the app's own line icons (IC in app.js)
GLANCE = {
    "en": [("Allow or deny", "a permission, from the phone"),
           ("Answer a question", "an option, or your own words"),
           ("Say what's next", "lands in the open VS Code tab"),
           ("Whose move", "what runs, what waits for you"),
           ("The whole session", "live, with ready replies"),
           ("Voice", "speak — it arrives as text"),
           ("Files both ways", "to the project and back"),
           ("A new project", "a folder, a CLAUDE.md, a clone"),
           ("Your plan's pace", "each limit, with a forecast"),
           ("Tags on every task", "section and topic, by Claude"),
           ("Model and effort", "per session, and a default"),
           ("Keeps itself current", "a release in one tap; new Claude Code checked")],
    "ru": [("Разрешить или нет", "запрос разрешения — с телефона"),
           ("Ответить на вопрос", "вариант или свои слова"),
           ("Сказать, что дальше", "в открытую вкладку VS Code"),
           ("Чей ход", "что идёт, что ждёт тебя"),
           ("Вся сессия", "вживую, с готовыми ответами"),
           ("Голосом", "скажи — придёт текстом"),
           ("Файлы в обе стороны", "в проект и обратно"),
           ("Новый проект", "папка, CLAUDE.md или клон"),
           ("Темп твоего плана", "каждый лимит, с прогнозом"),
           ("Теги у каждой задачи", "раздел и тема, от Claude"),
           ("Модель и раздумья", "на сессию и по умолчанию"),
           ("Обновляется сам", "выпуск одной кнопкой; новый Claude Code проверен")],
}
GLANCE_ICONS = [
    '<path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/><path d="m9 12 2 2 4-4"/>',                                    # shield
    '<circle cx="12" cy="12" r="9.5"/><path d="M9.2 9.2a3 3 0 0 1 5.7 1.1c0 2-2.9 2.7-2.9 2.7"/><path d="M12 17h.01"/>',    # help
    '<path d="M20.5 14.5a2 2 0 0 1-2 2H8l-4.5 4v-15a2 2 0 0 1 2-2h13a2 2 0 0 1 2 2z"/>',                                     # msg
    '<path d="M3.5 10.5 12 3.5l8.5 7"/><path d="M5.5 9v11a1 1 0 0 0 1 1h3.5v-6h4v6h3.5a1 1 0 0 0 1-1V9"/>',               # home
    '<rect x="8" y="2.5" width="8" height="4" rx="1"/><path d="M16 4.5h2a2 2 0 0 1 2 2V20a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V6.5a2 2 0 0 1 2-2h2"/><path d="M9 12h6M9 16h4"/>',  # plan
    '<rect x="9" y="2.5" width="6" height="12" rx="3"/><path d="M5.5 11a6.5 6.5 0 0 0 13 0M12 17.5v4"/>',                 # mic
    '<path d="m20.5 11.5-8.6 8.6a5.3 5.3 0 0 1-7.5-7.5l8.6-8.6a3.5 3.5 0 0 1 5 5l-8.6 8.6a1.8 1.8 0 0 1-2.5-2.5l7.9-7.9"/>',  # clip
    '<path d="M3 7.5V18a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2V9.5a2 2 0 0 0-2-2h-7l-2-3H5a2 2 0 0 0-2 2z"/>',                   # folder
    '<path d="M4.2 18.5a9 9 0 1 1 15.6 0"/><path d="m12 13.5 4-4.5"/><circle cx="12" cy="13.5" r="1.2"/>',               # gauge
    '<path d="M20.6 13.4 13.4 20.6a2 2 0 0 1-2.8 0L3 13V3h10l7.6 7.6a2 2 0 0 1 0 2.8z"/><path d="M7.5 7.5h.01"/>',        # tag
    '<path d="M12 3v4M12 17v4M3 12h4M17 12h4M5.6 5.6l2.8 2.8M15.6 15.6l2.8 2.8M5.6 18.4l2.8-2.8M15.6 8.4l2.8-2.8"/>',     # spark
    '<path d="M20.5 12a8.5 8.5 0 0 1-14.6 5.9L3.5 15.5"/><path d="M3.5 12a8.5 8.5 0 0 1 14.6-5.9l2.4 2.4"/><path d="M20.5 3.5v5h-5M3.5 20.5v-5h5"/>',  # auto
]
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
    """The features' screens from the stands in this language, light and dark: {(name, dark): png}."""
    procs, urls = [], {}
    try:
        for which, (port, extra) in STANDS.items():
            log = TMP / ("stand.%s.%s.out" % (which, lang))   # a file, not a pipe: a full pipe would stall the stand mid-shot
            with open(log, "w") as f:
                procs.append(subprocess.Popen([PY, str(REPO / "tools" / "stand.py")], stdout=f, stderr=subprocess.DEVNULL,
                                              env=dict(os.environ, STAND_TAB="1", STAND_LANG=lang, HOLD="400", STAND_PORT=port, **extra)))
            for _ in range(120):
                urls[which] = dict(l.partition(" ")[::2] for l in log.read_text().splitlines() if " http" in l)
                if "NEWPROJ" in urls[which]:
                    break
                time.sleep(0.5)
        out = {}
        for name, key, height, js, which in FEATURES:
            for dark in (False, True):
                png = TMP / ("%s.%s%s.png" % (name, lang, ".dark" if dark else ""))
                shot(urls[which][key], png, dark=dark, SHOT_HEIGHT=str(height), **({"SHOT_JS": js} if js else {}))
                out[(name, dark)] = png
        return out
    finally:
        for p in procs:
            p.terminate()
            p.wait()


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


def glance(lang, dark, out):
    """What the phone can do, twelve tiles in two columns — the width of the README, and still readable in GitHub's
    phone app: an icon, a title of a few words, a line under it."""
    ink, mute, card, line = ("#e9ebef", "#9aa3b0", "#1a1e25", "rgba(255,255,255,.10)") if dark else ("#171a21", "#626a77", "#ffffff", "rgba(15,23,42,.10)")
    tones = ["#6ea2f0", "#f3a64a", "#58c088", "#b48cf0"] if dark else ["#4f8be8", "#e8892b", "#2c9a63", "#8b5cf6"]
    cells = []
    for i, ((title, sub), path) in enumerate(zip(GLANCE[lang], GLANCE_ICONS)):
        tone = tones[(i // 2 + i) % 4]
        cells.append('<div class="c"><div class="i" style="color:%s;background:%s"><svg viewBox="0 0 24 24" width="24" height="24" fill="none" '
                     'stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round">%s</svg></div>'
                     '<div class="w"><b>%s</b><span>%s</span></div></div>' % (tone, tone + "1f", path, title, sub))
    body = '<div class="g">%s</div>' % "".join(cells)
    # the type is sized for GitHub's phone app, where the picture is about two thirds of this: as in steps()
    css = (".g { width: 560px; padding: 6px; display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }"
           ".c { display: flex; align-items: flex-start; gap: 12px; background: %s; border: 1.5px solid %s; border-radius: 18px; padding: 14px 13px 14px 14px; }"
           ".i { flex: none; width: 42px; height: 42px; border-radius: 13px; display: flex; align-items: center; justify-content: center; }"
           ".w { min-width: 0; padding-top: 1px; }"
           "b { display: block; font-size: 18.5px; line-height: 1.2; color: %s; letter-spacing: -.012em; }"
           ".w > span { display: block; margin-top: 4px; font-size: 15px; line-height: 1.3; color: %s; }" % (card, line, ink, mute))
    shot(page(out.stem + ".html", body, css), out, width=572, wait=1, SHOT_FIT=".g", SHOT_CLEAR="1")


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


KINDS = ("screens", "steps", "glance", "hero", "social")


def main():
    only = set(sys.argv[1:]) or set(KINDS)
    bad = only - set(KINDS)
    if bad:
        sys.exit("media: no such kind %s — one of %s" % (", ".join(sorted(bad)), ", ".join(KINDS)))
    MEDIA.mkdir(exist_ok=True)
    subprocess.run([PY, str(REPO / "tools" / "brand.py")], check=True, stdout=subprocess.DEVNULL)
    still = None
    for lang in ("en", "ru"):
        if "screens" in only:
            for (name, dark), png in screens(lang).items():
                framed(png, MEDIA / ("f-%s.%s%s.png" % (name, lang, ".dark" if dark else "")), dark)
        for dark in (False, True):
            sfx = ".dark" if dark else ""
            if "steps" in only:
                steps(lang, dark, MEDIA / ("steps.%s%s.png" % (lang, sfx)))
            if "glance" in only:
                glance(lang, dark, MEDIA / ("glance.%s%s.png" % (lang, sfx)))
            if "hero" in only or ("social" in only and lang == "en" and not dark):
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
    if "social" in only:
        social(still, MEDIA / "social.png")
    for p in sorted(MEDIA.iterdir()):
        print("%-28s %5.0f KB" % (p.name, p.stat().st_size / 1024))


if __name__ == "__main__":
    t0 = time.time()
    main()
    print("%.0f s" % (time.time() - t0))
