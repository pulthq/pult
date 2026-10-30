"""A slide copies Claude's message (stage Zh, step 3; the owner, 2026-10-29), in headless Chrome over DevTools, on the
stand, with real touches. A slide to the left past the mark copies the whole message as it reads — HTML the way Telegram
itself copies a message, and the markdown Claude wrote — and the message springs back, outlined, with "Copied"; a short
slide or a tap copies nothing; a slide from a block of code or a table doesn't move the message (the block keeps its own
tap, which still copies it); a finger held still first is selecting words, and a mouse drag selects them too; when the
lift doesn't reach the clipboard, the message stays open on its round button and a tap on it copies; without
ClipboardItem the copy command's event carries both kinds. Your own message slides the same way and goes as you wrote it
(2026-10-30). The stand's output shows what the computer's journal says.
  STAND_LANG=ru STAND_PORT=18151 HOLD=300 ~/.local/share/pult/venv/bin/python tools/stand.py > /tmp/stand.out &
  ~/.local/share/pult/venv/bin/python tools/msgcopy_check.py /tmp/stand.out [out_dir]
Screenshots go to out_dir (a temporary folder by default): the slide past the mark (light and dark), the copy done, the
button left out, your message slid. Exit 1 on a failed check."""
import asyncio
import json
import os
import sys
import tempfile

import _cdp

STAND = sys.argv[1]
URLS = _cdp.stand_urls(STAND, ("SESS",))
OUT = sys.argv[2] if len(sys.argv) > 2 else tempfile.mkdtemp(prefix="pult-msgcopy-")
os.makedirs(OUT, exist_ok=True)
verdict = _cdp.Verdicts()
# what would reach the clipboard is kept by the page itself (headless Chrome's own clipboard is the Mac's): both kinds
# of a write, the plain text, the copy command with what its event was given; whether the gesture still counted then.
# __deny — the clipboard refuses everything, as a webview that doesn't take the lift of a finger for a tap. Every toast
# and every outline is kept as it comes: a toast lives 1.8 s, the outline 1.2 s, and with stands side by side the
# check came to look later than that (tools/check.py, 2026-10-29)
SPY = """(() => { window.__w = []; window.__t = []; window.__x = []; window.__act = []; window.__deny = false;
  window.__toasts = []; window.__lit = 0;
  new MutationObserver((ms) => { for (const m of ms) {
    if (m.type === 'attributes') { if (m.target.classList.contains('lit') && !(m.oldValue || '').includes('lit')) window.__lit++; continue; }
    for (const n of m.addedNodes) if (n.nodeType === 1 && n.classList.contains('toast')) window.__toasts.push(n.textContent);
  } }).observe(document.body, {childList: true, subtree: true, attributes: true, attributeFilter: ['class'], attributeOldValue: true});
  navigator.clipboard.write = async (items) => {
    window.__act.push(navigator.userActivation ? navigator.userActivation.isActive : null);
    if (window.__deny) throw new DOMException('denied', 'NotAllowedError');
    const it = items[0];
    window.__w.push({types: [...it.types], html: await (await it.getType('text/html')).text(), text: await (await it.getType('text/plain')).text()});
  };
  navigator.clipboard.writeText = async (s) => { if (window.__deny) throw new DOMException('denied', 'NotAllowedError'); window.__t.push(s); };
  document.execCommand = (c) => {
    if (window.__deny) return false;
    const dt = new DataTransfer(), at = document.activeElement || document.body;
    at.dispatchEvent(new ClipboardEvent('copy', {clipboardData: dt, bubbles: true, cancelable: true}));
    window.__x.push({c, html: dt.getData('text/html'), text: dt.getData('text/plain'), sel: at.value || ''});
    return true;
  };
  return true; })()"""
MSG = "[...document.querySelectorAll('.swr.quick')].find((r) => r.textContent.includes('27 тестов'))"
WORDS = MSG + ".querySelector('.md p')"
ASK = "Сделай сообщения об ошибках при оплате понятнее, по примерам из макета"
MINE = "[...document.querySelectorAll('.swr.quick')].find((r) => r.querySelector('.msg.me') && r.textContent.includes(%s))" % json.dumps(ASK)
X = "(() => { const tf = getComputedStyle((%s).querySelector('.swr-in')).transform; return tf === 'none' ? 0 : Math.round(new DOMMatrixReadOnly(tf).m41); })()" % MSG
SIGN = "+getComputedStyle((%s).querySelector('.swr-act')).opacity" % MSG
TOAST = "window.__toasts.at(-1)"
COUNT = "window.__w.length + window.__x.length + window.__t.length"


def journal():
    with open(STAND, encoding="utf-8", errors="replace") as f:
        return f.read()


async def finger(pg, expr):
    """Where the finger goes: the element's middle — once it stays put there, two looks 0.15 s apart, and nothing else
    is on top of it; scrolled to the middle of the screen when it isn't. The session scrolls itself to its end as new
    events load (it keeps to the end when you are near it), and a finger came down on what was above the message: one
    run in three had no first slide at all (2026-10-30)."""
    last = None
    for _ in range(40):
        r = await pg.js("(() => { const el = (%s); const b = el.getBoundingClientRect();"
                        " const x = Math.round(b.left + b.width / 2), y = Math.round(b.top + b.height / 2), at = document.elementFromPoint(x, y);"
                        " if (!at || !el.contains(at) || b.top < 0 || b.bottom > innerHeight) { el.scrollIntoView({block: 'center'}); return null; }"
                        " return [x, y]; })()" % expr)
        if r and r == last:
            return r
        last = r
        await asyncio.sleep(0.15)
    raise RuntimeError("no still place for a finger on " + expr)


async def slide(pg, expr, dx, rest=0.0, lift=True):
    """A finger on the element's middle, after `rest` seconds dx to the side in steps; lifted unless told not to."""
    x, y = await finger(pg, expr)
    await pg.cmd("Input.dispatchTouchEvent", type="touchStart", touchPoints=[{"x": x, "y": y}])
    await asyncio.sleep(rest)
    for k in range(1, 9):
        await pg.cmd("Input.dispatchTouchEvent", type="touchMove", touchPoints=[{"x": x + dx * k / 8, "y": y}])
        await asyncio.sleep(0.02)
    if lift:
        await up(pg)


async def up(pg):
    await pg.cmd("Input.dispatchTouchEvent", type="touchEnd", touchPoints=[])
    await asyncio.sleep(0.6)


async def main():
    async with _cdp.Page() as pg:
        await pg.open(URLS["SESS"])
        verdict("Claude's summary is a message that slides", await pg.until("!!" + MSG, 150))
        await pg.js(SPY)

        # a short slide springs back and copies nothing; a tap copies nothing either
        await slide(pg, WORDS, -30)
        verdict("a short slide springs back", await pg.js(X) == 0, await pg.js(X))
        verdict("... and copies nothing", await pg.js(COUNT) == 0, await pg.js(COUNT))
        verdict("... and the journal says so", "swipe on Claude's message sprang back" in journal())
        await pg.tap(WORDS)
        verdict("a tap on the words copies nothing", await pg.js(COUNT) == 0, await pg.js(COUNT))

        # past the mark: the sign is out and lit, the finger still down
        await slide(pg, WORDS, -110, lift=False)
        verdict("past the mark the sign is out and lit", await pg.js(MSG + ".classList.contains('armed')") and await pg.js(SIGN) == 1,
                await pg.js(MSG + ".className"), await pg.js(SIGN))
        await pg.shot(os.path.join(OUT, "slide.png"))
        await up(pg)
        w = await pg.js("window.__w[0]")
        verdict("the lift copies the message: HTML and plain text", bool(w) and w["types"] == ["text/html", "text/plain"], w)
        w = w or {"html": "", "text": ""}
        for frag in ("<b>Итог</b>", "<b>27 тестов</b>", "• отказ по карте", "<pre>| случай | было | стало |<br>",
                     "<pre>make deploy-staging</pre>", '<a href="https://example.com">стенд</a>'):
            verdict("... the HTML has " + frag, frag in w["html"], w["html"][:400])
        verdict("... the plain text is the markdown Claude wrote", w["text"].startswith("## Итог") and "**27 тестов**" in w["text"]
                and "```\nmake deploy-staging\n```" in w["text"], w["text"][:200])
        verdict("... «Скопировано», the message outlined and back in place",
                await pg.until(TOAST + " === 'Скопировано'") and await pg.until("window.__lit === 1")
                and await pg.js(X) == 0, await pg.js(TOAST), await pg.js("window.__lit"), await pg.js(X))
        await pg.shot(os.path.join(OUT, "copied.png"))
        verdict("... and the journal says so", "swipe on Claude's message copied it with its formatting" in journal())
        print("     the gesture still counted when the clipboard was asked:", await pg.js("JSON.stringify(window.__act)"))

        # a block of code and a table keep their own drag; the block's tap still copies the block alone
        n = await pg.js(COUNT)
        await slide(pg, MSG + ".querySelector('pre')", -110)
        verdict("a slide from the block of code doesn't move the message", await pg.js(X) == 0 and await pg.js(COUNT) == n,
                await pg.js(X), await pg.js(COUNT))
        await slide(pg, MSG + ".querySelector('.tbl')", -110)
        verdict("... nor from the table", await pg.js(X) == 0 and await pg.js(COUNT) == n, await pg.js(X), await pg.js(COUNT))
        await pg.tap(MSG + ".querySelector('pre')")
        verdict("the block's own tap still copies the block", await pg.until("window.__t.length === 1")
                and await pg.js("window.__t[0]") == "make deploy-staging", await pg.js("window.__t"))

        # a finger held still first is selecting words; a mouse drag selects them
        n = await pg.js(COUNT)
        await slide(pg, WORDS, -110, rest=0.7)
        verdict("a finger held still before it moves doesn't slide", await pg.js(X) == 0 and await pg.js(COUNT) == n,
                await pg.js(X), await pg.js(COUNT))
        x, y = await finger(pg, WORDS)
        await pg.cmd("Input.dispatchMouseEvent", type="mousePressed", x=x, y=y, button="left", clickCount=1)
        for k in range(1, 9):
            await pg.cmd("Input.dispatchMouseEvent", type="mouseMoved", x=x - 110 * k / 8, y=y, button="left")
        await pg.cmd("Input.dispatchMouseEvent", type="mouseReleased", x=x - 110, y=y, button="left", clickCount=1)
        await asyncio.sleep(0.5)
        verdict("a mouse drag doesn't slide", await pg.js(X) == 0 and await pg.js(COUNT) == n, await pg.js(X), await pg.js(COUNT))
        await pg.js("getSelection().removeAllRanges()")

        # no ClipboardItem: the copy command's event carries both kinds
        await pg.js("window.__ci = window.ClipboardItem; delete window.ClipboardItem; true")
        await slide(pg, WORDS, -110)
        x_ = await pg.js("window.__x.at(-1)") or {}
        verdict("without ClipboardItem the copy command carries both kinds", x_.get("c") == "copy" and "<b>27 тестов</b>" in x_.get("html", "")
                and x_.get("text", "").startswith("## Итог"), x_)
        await pg.js("window.ClipboardItem = window.__ci; true")

        # the lift doesn't reach the clipboard: the message stays open on its button; a tap on it copies
        await pg.js("window.__deny = true")
        n = await pg.js("window.__w.length")
        await slide(pg, WORDS, -110)
        verdict("when the lift can't copy, the message stays open on its button", await pg.js(X) == -72 and await pg.js(SIGN) == 1,
                await pg.js(X), await pg.js(SIGN))
        verdict("... «Нажми на значок, чтобы скопировать»", await pg.until(TOAST + " === 'Нажми на значок, чтобы скопировать'"),
                await pg.js(TOAST))
        verdict("... and the journal says so", "swipe on Claude's message didn't copy it — the copy waits on its button" in journal())
        await pg.shot(os.path.join(OUT, "button.png"))
        await pg.js("window.__deny = false")
        await pg.tap(MSG + ".querySelector('.swr-act')")
        verdict("a tap on the button copies and closes", await pg.until("window.__w.length === %d" % (n + 1))
                and await pg.until(TOAST + " === 'Скопировано'") and await pg.js(X) == 0, await pg.js("window.__w.length"),
                await pg.js(TOAST), await pg.js(X))

        # your own message slides the same way and goes as you wrote it
        n, toasts, lit = await pg.js("[window.__w.length, window.__toasts.length, window.__lit]")
        await slide(pg, MINE + ".querySelector('.msg.me')", -110, lift=False)
        verdict("your message slides too, its sign lit", await pg.js(MINE + ".classList.contains('armed')"), await pg.js(MINE + ".className"))
        await pg.shot(os.path.join(OUT, "mine.png"))
        await up(pg)
        w = await pg.js("window.__w.at(-1)") if await pg.until("window.__w.length === %d" % (n + 1)) else None
        verdict("... and the lift copies your words as you wrote them", bool(w) and w["text"] == ASK and w["html"] == ASK, w)
        verdict("... «Скопировано» and the outline", await pg.until("window.__toasts.length === %d && %s === 'Скопировано'" % (toasts + 1, TOAST))
                and await pg.until("window.__lit === %d" % (lit + 1)), await pg.js("window.__toasts"), await pg.js("window.__lit"))
        for _ in range(30):
            if "swipe on your message copied it with its formatting" in journal():
                break
            await asyncio.sleep(0.1)
        verdict("... and the journal says so", "swipe on your message copied it with its formatting" in journal())

        # the same slide in the dark
        await pg.cmd("Emulation.setEmulatedMedia", features=[{"name": "prefers-color-scheme", "value": "dark"}])
        await asyncio.sleep(0.3)
        await slide(pg, WORDS, -100, lift=False)
        await pg.shot(os.path.join(OUT, "slide-dark.png"))
        await up(pg)
        verdict("no script errors", not pg.errors, pg.errors[:3])
        print("     journal:", json.dumps([ln.split("app: ", 1)[1] for ln in journal().splitlines() if "swipe on Claude's message" in ln],
                                         ensure_ascii=False))
    print("screenshots:", OUT)
    sys.exit(verdict.code())


asyncio.run(main())
