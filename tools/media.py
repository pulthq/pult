"""Every picture of the README, made from the test stand and the daemon's own output — never from real projects.

  ~/.local/share/pult/venv/bin/python tools/media.py          # both languages, about two minutes

  media/demo.{en,ru}.gif         the opening animation: a project's topic in Telegram, turn by turn (tools/chat_shot.py)
  media/app-session.{en,ru}.png  the session screen of the web app: your message pinned on top, the status by the field
  media/app.{en,ru}.png          three app screens in phone frames: Home ("Your move" with ready replies and the board),
                                 a project's screen, a session ending in its outcome card
  media/social.png               1280×640, the link preview: GitHub takes it only in the repository's settings
                                 (Settings → General → Social preview); there is no API for it

The stand (tools/stand.py) runs with a VS Code tab on its session; the screens are drawn by tools/shot.py.
"""
import os, shutil, subprocess, sys, tempfile, time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
MEDIA = REPO / "media"
PY = sys.executable
TMP = Path(tempfile.mkdtemp(prefix="pult-media-"))

FRAME = """
* { box-sizing: border-box; }
body { margin: 0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; }
.ph { border-radius: 30px; overflow: hidden; background: #fff; border: 1px solid rgba(15, 23, 42, .14);
  box-shadow: 0 18px 40px rgba(15, 23, 42, .18), 0 3px 8px rgba(15, 23, 42, .08); }
.ph img { display: block; width: 100%; }
"""


def shot(url, out, width=412, wait=6, **env):
    subprocess.run([PY, str(REPO / "tools" / "shot.py"), url, str(out), str(width), str(wait)], check=True,
                   stdout=subprocess.DEVNULL, env=dict(os.environ, **env))


def page(name, body, css):
    p = TMP / name
    p.write_text('<!doctype html><meta charset="utf-8"><style>%s%s</style>%s' % (FRAME, css, body), encoding="utf-8")
    return p.as_uri()


def screens(lang):
    """Home, a project, a session's outcome and the session with your pinned message, from a stand in this language."""
    log = TMP / ("stand.%s.out" % lang)            # a file, not a pipe: a full pipe would stall the stand mid-shot
    with open(log, "w") as f:
        stand = subprocess.Popen([PY, str(REPO / "tools" / "stand.py")], stdout=f, stderr=subprocess.DEVNULL,
                                 env=dict(os.environ, STAND_TAB="1", STAND_LANG=lang, HOLD="240"))
    urls = {}
    try:
        for _ in range(120):
            urls = dict(l.partition(" ")[::2] for l in log.read_text().splitlines() if " http" in l)
            if "PROJECTS" in urls:
                break
            time.sleep(0.5)
        out = {k: TMP / ("%s.%s.png" % (k, lang)) for k in ("home", "project", "outcome", "session")}
        # Home from the "Your move" card that waits for a choice: its ready replies, then the projects board
        shot(urls["HOME"], out["home"], SHOT_HEIGHT="860", SHOT_JS="const c = document.querySelector('.card.mine'); "
             "window.scrollTo(0, c.getBoundingClientRect().top + window.scrollY - 14)")
        shot(urls["PROJ"], out["project"], SHOT_HEIGHT="860")
        # opened once, so its outcome card is still red: it waited for you when you opened it
        shot(urls["SESS4"], out["outcome"], SHOT_HEIGHT="860")
        # your message pinned; 412×740 is the animation's own shape, so the two stand side by side at one size
        shot(urls["SESS"], out["session"], SHOT_HEIGHT="740", SHOT_JS="window.scrollTo(0, 560)")
        return out
    finally:
        stand.terminate()
        stand.wait()


def phones(imgs, out):
    """Screens side by side in phone frames, on a transparent background."""
    body = '<div class="row">%s</div>' % "".join('<div class="ph"><img src="%s"></div>' % p.as_uri() for p in imgs)
    css = ".row { display: flex; gap: 30px; padding: 26px 36px 50px; width: max-content; } .ph { width: 300px; }"
    shot(page(out.stem + ".html", body, css), out, width=36 * 2 + 300 * len(imgs) + 30 * (len(imgs) - 1), wait=2,
         SHOT_FIT=".row", SHOT_CLEAR="1")


def social(chat, session, out):
    """The link preview: the name and what it does on the left, the chat and the app on the right."""
    body = """<div class="card"><div class="text"><div class="name">Pult</div>
      <div class="tag">Watch and steer every Claude Code session on your computer — from Telegram.</div>
      <div class="chips"><span>macOS · Linux</span><span>Telegram + web app</span><span>MIT</span></div>
      <div class="url">github.com/pulthq/pult</div></div>
      <div class="ph one"><img src="%s"></div><div class="ph two"><img src="%s"></div></div>""" % (chat.as_uri(), session.as_uri())
    css = """.card { position: relative; width: 1280px; height: 640px; overflow: hidden;
        background: radial-gradient(circle at 78% 30%, #dbe7fb 0, #eef3fa 45%, #f6f8fb 100%); }
      .text { position: absolute; left: 76px; top: 120px; width: 600px; color: #14213d; }
      .name { font-size: 104px; font-weight: 800; letter-spacing: -2px; line-height: 1; }
      .tag { margin-top: 26px; font-size: 38px; line-height: 1.25; font-weight: 600; color: #26344f; }
      .chips { margin-top: 34px; display: flex; gap: 12px; }
      .chips span { padding: 8px 16px; border-radius: 999px; background: #fff; border: 1px solid #d5deea; font-size: 20px;
        color: #3a4a66; font-weight: 600; }
      .url { margin-top: 40px; font-size: 22px; color: #5d6b82; }
      .ph { position: absolute; width: 300px; }
      .one { left: 720px; top: 70px; transform: rotate(-4deg); }
      .two { left: 930px; top: 150px; transform: rotate(3deg); }"""
    big = TMP / "social-2x.png"
    shot(page("social.html", body, css), big, width=1280, wait=2, SHOT_HEIGHT="640")
    subprocess.run(["sips", "-z", "640", "1280", str(big), "--out", str(out)], check=True, stdout=subprocess.DEVNULL)


def main():
    MEDIA.mkdir(exist_ok=True)
    for lang in ("en", "ru"):
        s = screens(lang)
        shutil.copy(s["session"], MEDIA / ("app-session.%s.png" % lang))
        phones([s["home"], s["project"], s["outcome"]], MEDIA / ("app.%s.png" % lang))
        env = dict(os.environ, STAND_LANG=lang)
        subprocess.run([PY, str(REPO / "tools" / "chat_shot.py"), str(MEDIA / ("demo.%s.gif" % lang))], check=True, env=env,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if lang == "en":
            chat = TMP / "chat.en.png"
            subprocess.run([PY, str(REPO / "tools" / "chat_shot.py"), str(chat)], check=True, env=env,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            social(chat, s["session"], MEDIA / "social.png")
        print(lang, "done", flush=True)
    for p in sorted(MEDIA.iterdir()):
        print("%-24s %5.0f KB" % (p.name, p.stat().st_size / 1024))


if __name__ == "__main__":
    t0 = time.time()
    main()
    print("%.0f s" % (time.time() - t0))
