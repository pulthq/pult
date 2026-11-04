"""A Codex capacity error through the fake protocol, daemon and actual app on a narrow phone.
Run with tools/check.py codexerrors; no real Codex, account or model requests are used."""
import asyncio
import os
import sys
import tempfile

import _cdp

URLS = _cdp.stand_urls(sys.argv[1], ("SESS4",))
OUT = sys.argv[2] if len(sys.argv) > 2 else tempfile.mkdtemp(prefix="pult-codexerrors-")
os.makedirs(OUT, exist_ok=True)
verdict = _cdp.Verdicts()
CARD = "document.querySelector('.card.second.fail')"


async def main():
    async with _cdp.Page(width=320) as pg:
        await pg.open(URLS["SESS4"])
        ready = await pg.until("!!document.querySelector('.card.outcome .sec-ask')", 150)
        verdict("second opinion is available", ready)
        if not ready:
            return 1
        await pg.tap("document.querySelector('.card.outcome .sec-ask')", wait=0.2)
        ready = await pg.until("!!" + CARD, 150)
        verdict("a failed review reaches the phone", ready)
        if not ready:
            return 1
        text = await pg.js(CARD + ".innerText")
        verdict("the model's capacity is named", "Модель Codex перегружена" in text, text)
        verdict("the next step is explained", "подожди или выбери другую" in text, text)
        verdict("capacity is not reported as a subscription limit", "лимит подписки" not in text, text)
        verdict("manual retry remains available", "Ещё раз" in text, text)
        verdict("the explanation fits 320 px", await pg.js("document.documentElement.scrollWidth <= innerWidth"))
        await pg.shot(os.path.join(OUT, "codex-overloaded.png"))
        await asyncio.sleep(1)
        verdict("the failure remains until the owner acts", await pg.js("!!" + CARD))
        verdict("no script errors", not pg.errors, pg.errors)
    print("screenshots:", OUT)
    return verdict.code()


sys.exit(asyncio.run(main()))
