"""Every picture of the README, made from the test stand and the daemon's own output — never from real projects.

  ~/.local/share/pult/venv/bin/python tools/media.py          # both languages, both themes, a few minutes
  ~/.local/share/pult/venv/bin/python tools/media.py glance steps   # only these kinds (glance, steps, screens, hero, social)

  media/hero.{en,ru}[.dark].gif     the opening picture: one model does a task, another checks it — the app's own
                                    screens on the stand, the three steps above the phone (tools/hero.py)
  media/glance.{en,ru}[.dark].png   the whole of Pult in one look: its three sides — an app inside Telegram, any agent
                                    and model, models that work together — four tiles each
  media/steps.{en,ru}[.dark].png    how it works in three steps
  media/f-<name>.{en,ru}[.dark].png one phone screen per feature: home, who, second, session, tags, pace, files,
                                    newproject, parts (each from its stand — STANDS; MEDIA_PORT=<port> moves them all,
                                    beside a stand someone else runs)
  media/social.png                  1280×640, the link preview: GitHub takes it only in the repository's settings
                                    (Settings → General → Social preview); there is no API for it
  media/logo.svg, logo-512.png      the mark — tools/brand.py draws them

One picture says one thing and holds one phone, readable on GitHub's phone app; ".dark" goes to the README's
<picture> for GitHub's dark theme. The stand (tools/stand.py) runs with a VS Code tab on its session; the screens are
drawn by tools/shot.py.
"""
import os, re, shutil, subprocess, sys, tempfile, time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
MEDIA = REPO / "media"
PY = sys.executable
TMP = Path(tempfile.mkdtemp(prefix="pult-media-"))
FONT = "-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif"

# a feature's screen: the stand's link, the window's height (CSS px at 412 wide), what to do before the picture, which
# stand it comes from, and how long to wait after that (a second opinion takes the stand's Codex about five seconds)
TO_BOTTOM = "window.scrollTo(0, document.documentElement.scrollHeight)"
WHO = ("[...document.querySelectorAll('.form .field')].find((b) => b.previousElementSibling"
       " && /^(Who does it|Кто делает)$/.test(b.previousElementSibling.textContent.trim())).click()")
# the first picture asks Codex; the second (the dark one) finds its card already there, kept till Reviewed
SECOND = ("(() => { const b = document.querySelector('.card.outcome .sec-ask'); if (b) b.click();"
          " setTimeout(() => window.scrollTo(0, document.documentElement.scrollHeight), b ? 11000 : 300); })()")
FEATURES = [
    ("home", "HOME", 760, "", "vendors", 1),
    ("who", "NEW", 760, WHO, "vendors", 1),
    ("second", "SESS4", 760, SECOND, "second", 14),
    ("session", "SESS4", 760, TO_BOTTOM, "main", 1),
    ("tags", "PROJT", 760, "", "tags", 1),
    ("pace", "USAGE", 700, "document.querySelector('.spend-seg button').click()", "main", 1),
    ("files", "SESS4", 700, "document.querySelector('.tfline').click()", "main", 1),
    ("newproject", "NEWPROJ", 640, "", "main", 1),
    ("parts", "SETTINGS", 700, "", "tags", 1),
]
# the plain stand; a third project full of tagged tasks and every part of Pult in Settings' table; a task on DeepSeek
# running beside one on Opus, and other vendors in New task; Codex's second opinion on the shop's search
PORT = int(os.environ.get("MEDIA_PORT") or 18097)
STANDS = {"main": (str(PORT), {}), "tags": (str(PORT + 2), {"STAND_TAGS": "1", "STAND_PARTS": "now"}),
          "vendors": (str(PORT + 4), {"STAND_VENDORS": "1", "STAND_HOMES": "1"}),
          "second": (str(PORT + 6), {"STAND_SECOND": "allowed"})}

STEPS = {
    "en": [("Give the task to any model", "from the phone, or as usual in VS Code or a terminal: Pult picks up every session"),
           ("Your phone rings only when needed", "a permission, a question, a result to check — your answer reaches even the open tab"),
           ("Another model checks it", "Codex reads what the task changed; its findings go back to the doer in one tap")],
    "ru": [("Дай задачу любой модели", "с телефона или как обычно — в VS Code, в терминале: Пульт подхватит каждую сессию"),
           ("Телефон зовёт, только когда нужен ты", "разрешение, вопрос, итог на проверку — ответ дойдёт и до открытой вкладки"),
           ("Другая модель проверит", "Codex читает, что изменила задача; замечания — исполнителю одним касанием")],
}
# Pult's three sides, each a title, a line, and four tiles: an icon, a title of a few words and a line under it — the
# app's own line icons (IC in ui/kit.js)
GLANCE = {
    "en": [("A Telegram app", "the main screen, on any phone", [
               ("home", "Whose move", "what runs, what waits for you"),
               ("msg", "The whole session", "live, with ready replies"),
               ("shield", "Allow or answer", "a permission, a question"),
               ("mic", "Voice and files", "speak — it arrives as text; files both ways")]),
           ("Any agent, any model", "on macOS, Linux or Windows", [
               ("tabs", "Every session", "VS Code tabs, a terminal, the phone"),
               ("spark", "Who does it", "Claude, DeepSeek, GLM or Kimi"),
               ("gauge", "Model and effort", "per task, and a default"),
               ("tag", "Who did what", "the model on every card")]),
           ("Models work together", "one does the task, another checks it", [
               ("eye", "A second opinion", "Codex reads what changed"),
               ("send", "Back to the doer", "its findings in one tap"),
               ("pin", "A doer per project", "who does its new tasks"),
               ("lock", "Only where you allow", "asked once per project")])],
    "ru": [("Приложение в Telegram", "главный экран — на любом телефоне", [
               ("home", "Чей ход", "что идёт, что ждёт тебя"),
               ("msg", "Вся сессия", "вживую, с готовыми ответами"),
               ("shield", "Разрешить, ответить", "запрос и вопрос — с телефона"),
               ("mic", "Голос и файлы", "скажи — придёт текстом; файлы в обе стороны")]),
           ("Любой агент и модель", "на macOS, Linux или Windows", [
               ("tabs", "Каждая сессия", "вкладки VS Code, терминал, телефон"),
               ("spark", "Кто делает", "Claude, DeepSeek, GLM или Kimi"),
               ("gauge", "Модель и раздумья", "на задачу и по умолчанию"),
               ("tag", "Кто что сделал", "модель на каждой карточке")]),
           ("Модели работают вместе", "одна делает задачу, другая проверяет", [
               ("eye", "Второе мнение", "Codex читает, что изменилось"),
               ("send", "Обратно исполнителю", "замечания одним касанием"),
               ("pin", "Исполнитель проекта", "кто делает его новые задачи"),
               ("lock", "Только где разрешишь", "спрашивает раз на проект")])],
}
IC = {  # the app's own line icons (ui/kit.js), the ones the pictures use
    "home": '<path d="M3.5 10.5 12 3.5l8.5 7"/><path d="M5.5 9v11a1 1 0 0 0 1 1h3.5v-6h4v6h3.5a1 1 0 0 0 1-1V9"/>',
    "msg": '<path d="M20.5 14.5a2 2 0 0 1-2 2H8l-4.5 4v-15a2 2 0 0 1 2-2h13a2 2 0 0 1 2 2z"/>',
    "shield": '<path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/><path d="m9 12 2 2 4-4"/>',
    "mic": '<rect x="9" y="2.5" width="6" height="12" rx="3"/><path d="M5.5 11a6.5 6.5 0 0 0 13 0M12 17.5v4"/>',
    "tabs": '<rect x="2.5" y="4" width="19" height="16" rx="2.5"/><path d="M2.5 9h19M9 4v5"/>',
    "spark": '<path d="M12 3v4M12 17v4M3 12h4M17 12h4M5.6 5.6l2.8 2.8M15.6 15.6l2.8 2.8M5.6 18.4l2.8-2.8M15.6 8.4l2.8-2.8"/>',
    "gauge": '<path d="M4.2 18.5a9 9 0 1 1 15.6 0"/><path d="m12 13.5 4-4.5"/><circle cx="12" cy="13.5" r="1.2"/>',
    "tag": '<path d="M20.6 13.4 13.4 20.6a2 2 0 0 1-2.8 0L3 13V3h10l7.6 7.6a2 2 0 0 1 0 2.8z"/><path d="M7.5 7.5h.01"/>',
    "eye": '<path d="M2.5 12c1.2-2.6 5-7 9.5-7s8.3 4.4 9.5 7c-1.2 2.6-5 7-9.5 7s-8.3-4.4-9.5-7z"/><circle cx="12" cy="12" r="3"/>',
    "send": '<path d="M21.5 2.5 10.5 13.5"/><path d="m21.5 2.5-7 19-4-8-8-4z"/>',
    "pin": '<path d="M8.5 2.5h7"/><path d="M9.5 2.5v6.3L6.5 12v2h11v-2l-3-3.2V2.5"/><path d="M12 14v7.5"/>',
    "lock": '<rect x="4.5" y="10.5" width="15" height="11" rx="2"/><path d="M8 10.5V7a4 4 0 0 1 8 0v3.5"/>',
    "plus": '<path d="M12 5v14M5 12h14"/>',
    "phone": '<rect x="6" y="2" width="12" height="20" rx="2.6"/><path d="M11 18h2"/>',
}
ICONS = [IC["plus"], IC["phone"], IC["eye"]]   # the steps: a new task, the phone that rings, the second look


def nb(text):
    """A word of one or two letters ("с", "по", "a", "to") stays with the next one: no line of a tile ends on it."""
    return re.sub(r"(?<=\s)(\w{1,2}) ", "\\1\u00a0", text)


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
        for name, key, height, js, which, after in FEATURES:
            for dark in (False, True):
                png = TMP / ("%s.%s%s.png" % (name, lang, ".dark" if dark else ""))
                shot(urls[which][key], png, dark=dark, SHOT_HEIGHT=str(height), SHOT_AFTER=str(after),
                     **({"SHOT_JS": js} if js else {}))
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
    # blue — what you do, warm — what waits for you, violet — the second opinion: the app's own colours for them
    tones = ["#6ea2f0", "#f3a64a", "#b48cf0"] if dark else ["#4f8be8", "#e8892b", "#8b5cf6"]
    cells = []
    for i, ((title, sub), path) in enumerate(zip(STEPS[lang], ICONS)):
        cells.append('<div class="c"><div class="i" style="color:%s;background:%s"><svg viewBox="0 0 24 24" width="30" height="30" fill="none" '
                     'stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round">%s</svg></div>'
                     '<div class="w"><b><span class="n">%d</span>%s</b><span>%s</span></div></div>' % (tones[i], tones[i] + "1f", path, i + 1, nb(title), nb(sub)))
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
    """The whole of Pult in one look: its three sides one under another, each a title with a line and four tiles in
    two columns — the width of the README, and still readable in GitHub's phone app: an icon, a title of a few words,
    a line under it. A side keeps one colour: blue — the app, green — the agents and models, violet — models that
    check each other (the second opinion's own colour in the app)."""
    ink, mute, card, line = ("#e9ebef", "#9aa3b0", "#1a1e25", "rgba(255,255,255,.10)") if dark else ("#171a21", "#626a77", "#ffffff", "rgba(15,23,42,.10)")
    tones = ["#6ea2f0", "#58c088", "#b48cf0"] if dark else ["#4f8be8", "#2c9a63", "#8b5cf6"]
    sides = []
    for (head, sub, tiles), tone in zip(GLANCE[lang], tones):
        cells = "".join('<div class="c"><div class="i" style="color:%s;background:%s"><svg viewBox="0 0 24 24" width="24" height="24" '
                        'fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round">%s</svg></div>'
                        '<div class="w"><b>%s</b><span>%s</span></div></div>' % (tone, tone + "1f", IC[icon], nb(title), nb(line_))
                        for icon, title, line_ in tiles)
        sides.append('<div class="side"><div class="h"><i style="background:%s"></i><b>%s</b><span>%s</span></div>'
                     '<div class="t">%s</div></div>' % (tone, nb(head), nb(sub), cells))
    body = '<div class="g">%s</div>' % "".join(sides)
    # the type is sized for GitHub's phone app, where the picture is about two thirds of this: as in steps()
    css = (".g { width: 560px; padding: 6px; display: flex; flex-direction: column; gap: 22px; }"
           ".h { display: flex; align-items: baseline; flex-wrap: wrap; gap: 2px 10px; margin: 0 4px 11px; }"
           ".h i { flex: none; width: 11px; height: 11px; border-radius: 50%%; align-self: center; }"
           ".h b { font-size: 22px; line-height: 1.2; color: %s; letter-spacing: -.015em; }"
           ".h span { flex-basis: 100%%; font-size: 16px; line-height: 1.3; color: %s; }"
           ".t { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }"
           ".c { display: flex; align-items: flex-start; gap: 12px; background: %s; border: 1.5px solid %s; border-radius: 18px; padding: 14px 13px 14px 14px; }"
           ".i { flex: none; width: 42px; height: 42px; border-radius: 13px; display: flex; align-items: center; justify-content: center; }"
           ".w { min-width: 0; padding-top: 1px; }"
           ".w b { display: block; font-size: 18.5px; line-height: 1.2; color: %s; letter-spacing: -.012em; }"
           ".w > span { display: block; margin-top: 4px; font-size: 15px; line-height: 1.3; color: %s; }" % (ink, mute, card, line, ink, mute))
    shot(page(out.stem + ".html", body, css), out, width=572, wait=1, SHOT_FIT=".g", SHOT_CLEAR="1")


def social(still, out):
    """The link preview: the mark, the name and what it does on the left; the opening picture's first frame — a phone
    with the three steps above it — on the right."""
    logo = (MEDIA / "logo.svg").read_text(encoding="utf-8").replace("<svg ", '<svg width="96" height="96" ', 1)
    body = """<div class="card"><div class="text"><div class="mk">%s<div class="name">Pult</div></div>
      <div class="tag">The universal remote for AI agents — in Telegram.</div>
      <div class="chips"><span>Claude Code · Codex · DeepSeek</span><span>macOS · Linux · Windows</span><span>MIT</span></div>
      <div class="url">github.com/pulthq/pult</div></div><img class="hero" src="%s"></div>""" % (logo, still.as_uri())
    css = """.card { position: relative; width: 1280px; height: 640px; overflow: hidden;
        background: radial-gradient(circle at 80% 30%, #dbe7fb 0, #eef3fa 45%, #f6f8fb 100%); }
      .text { position: absolute; left: 70px; top: 104px; width: 640px; color: #14213d; }
      .mk { display: flex; align-items: center; gap: 22px; }
      .name { font-size: 92px; font-weight: 800; letter-spacing: -2px; line-height: 1; }
      .tag { margin-top: 30px; font-size: 36px; line-height: 1.25; font-weight: 600; color: #26344f; }
      .chips { margin-top: 32px; display: flex; flex-wrap: wrap; gap: 10px; }
      .chips span { padding: 6px 12px; border-radius: 999px; background: #fff; border: 1px solid #d5deea; font-size: 16px; color: #3a4a66; font-weight: 600; }
      .url { margin-top: 34px; font-size: 21px; color: #5d6b82; }
      .hero { position: absolute; right: 96px; top: 24px; height: 592px; border-radius: 22px; }"""
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
