"""A tap on a block of code copies it whole (the owner, 2026-10-27), in headless Chrome over DevTools, on the stand,
with real taps: Claude's block in a session and the command a permission asks about. The block has its sign in the
corner; a tap gives the clipboard its text as it reads, a tick and "Copied" say so; without the clipboard API (some
webviews) the old way copies the same text; text selected by hand inside the block is left alone.
  STAND_LANG=ru STAND_PORT=18143 HOLD=300 ~/.local/share/pult/venv/bin/python tools/stand.py > /tmp/stand.out &
  ~/.local/share/pult/venv/bin/python tools/clip_check.py /tmp/stand.out [out_dir]
Screenshots go to out_dir (a temporary folder by default). Exit 1 on a failed check."""
import asyncio
import os
import sys
import tempfile

import _cdp

URLS = _cdp.stand_urls(sys.argv[1], ("SESS",))
OUT = sys.argv[2] if len(sys.argv) > 2 else tempfile.mkdtemp(prefix="pult-clip-")
os.makedirs(OUT, exist_ok=True)
verdict = _cdp.Verdicts()
# what would reach the clipboard is kept by the page itself: headless Chrome's own clipboard isn't read here
SPY = """(() => { window.__copied = []; window.__exec = [];
  navigator.clipboard.writeText = (s) => { window.__copied.push(s); return Promise.resolve(); };
  document.execCommand = (c) => { window.__exec.push([c, document.activeElement && document.activeElement.value]); return true; };
  return true; })()"""
BLOCK = "[...document.querySelectorAll('.md pre')].find((p) => p.textContent.includes('make deploy-staging'))"
PERM = "document.querySelector('.perm-b pre')"
TOAST = "(document.querySelector('.toast') || {}).textContent"


async def main():
    async with _cdp.Page() as pg:
        await pg.open(URLS["SESS"])
        verdict("the session shows Claude's block of code", await pg.until("!!" + BLOCK, 150))
        await pg.js(SPY)
        sign = await pg.js("(() => { const s = getComputedStyle(%s, '::after'); return s.webkitMaskImage || s.maskImage; })()" % BLOCK)
        verdict("the block has the copy sign in its corner", "svg" in (sign or ""), (sign or "")[:80])
        await pg.shot(os.path.join(OUT, "block.png"))
        await pg.tap(BLOCK, wait=0.2)
        verdict("a tap copies the block as it reads", await pg.until("window.__copied.length === 1")
                and await pg.js("window.__copied[0]") == "make deploy-staging", await pg.js("window.__copied"))
        verdict("... a tick and «Скопировано» say so", await pg.until(TOAST + " === 'Скопировано'")
                and await pg.js(BLOCK + ".classList.contains('copied')"), await pg.js(TOAST))
        await pg.shot(os.path.join(OUT, "copied.png"))
        verdict("... and the tick goes back to the sign", await pg.until("!" + BLOCK + ".classList.contains('copied')", 40))
        # no clipboard API (some webviews): the old way, a hidden field and the copy command
        await pg.js("navigator.clipboard.writeText = () => Promise.reject(new Error('no clipboard'))")
        await pg.tap(BLOCK, wait=0.2)
        verdict("without the clipboard API — the old way, the same text", await pg.until("window.__exec.length === 1")
                and await pg.js("JSON.stringify(window.__exec[0])") == '["copy","make deploy-staging"]', await pg.js("window.__exec"))
        # text selected by hand inside the block is what the owner wants there, not the whole block
        await pg.js("navigator.clipboard.writeText = (s) => { window.__copied.push(s); return Promise.resolve(); }")
        await pg.js("""(() => { const r = document.createRange(), n = %s.querySelector('code').firstChild;
            r.setStart(n, 0); r.setEnd(n, 4); const s = getSelection(); s.removeAllRanges(); s.addRange(r);
            %s.dispatchEvent(new MouseEvent('click', {bubbles: true})); })()""" % (BLOCK, BLOCK))
        await asyncio.sleep(0.3)
        verdict("text selected by hand in it is left alone", await pg.js("window.__copied.length") == 1, await pg.js("window.__copied"))
        await pg.js("getSelection().removeAllRanges()")
        # the command a permission asks about
        if await pg.until("!!" + PERM, 30):
            want = await pg.js(PERM + ".textContent.replace(/\\n+$/, '')")
            await pg.tap(PERM, wait=0.2)
            verdict("a tap on the permission's command copies it", await pg.until("window.__copied.length === 2")
                    and await pg.js("window.__copied[1]") == want, await pg.js("window.__copied"), want)
        else:
            verdict("the session shows a permission with its command", False)
        verdict("no script errors", not pg.errors, pg.errors[:3])
    print("screenshots:", OUT)
    sys.exit(verdict.code())


asyncio.run(main())
