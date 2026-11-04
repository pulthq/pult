"""Memory running low and the connection's banners on the stand, in headless Chrome. No real accounts or tasks.
Run through tools/check.py memory (STAND_MEMORY=96); screenshots use only made-up data. The strip shows only from 85 %:
the check moves the stand's reading down and back up (api_stand_memory).
"""
import asyncio
import os
import sys

import _cdp


async def main():
    urls = _cdp.stand_urls(sys.argv[1])
    out = sys.argv[2]
    os.makedirs(out, exist_ok=True)
    verdict = _cdp.Verdicts()
    async with _cdp.Page(width=320) as page:
        await page.open(urls["HOME"])
        verdict("memory running low is on Home", await page.until("!!document.querySelector('.memory-status.bad')"))
        text = await page.js("document.querySelector('.memory-status')?.textContent") or ""
        verdict("critical memory has its share, amount and what it means",
                "96 %" in text and "система может" in text and "8" in text, text)
        verdict("the line fits a narrow phone", await page.js("document.querySelector('.memory-status').scrollWidth <= innerWidth"))
        await page.shot(os.path.join(out, "memory-critical.png"))
        await page.js("(async () => { window.healthConn = await import('/pult/static/core/conn.js'); })()")
        await page.js("healthConn.api('stand_memory', {pct: 65})")
        verdict("memory in plenty takes no line", await page.until("!document.querySelector('.memory-status')", tries=150))
        await page.js("healthConn.api('stand_memory', {pct: 96})")
        verdict("the line is back when memory runs low again",
                await page.until("!!document.querySelector('.memory-status.bad')", tries=150))
        await page.js("healthConn.conn.ready=false; healthConn.conn.state='busy'; healthConn.emit('conn')")
        verdict("a full server is told apart from a broken link",
                await page.until("document.querySelector('.banner.busy')?.textContent.includes('занят другими окнами')"))
        verdict("offline, the last reading is marked old", await page.until("!!document.querySelector('.memory-status.stale')"))
        verdict("an old reading is no current alarm", await page.js(
            "!document.querySelector('.memory-status.bad') && document.querySelector('.memory-status').textContent.includes('сейчас — неизвестно')"))
        await page.js("location.hash='#/load'")
        verdict("an offline screen waits for the connection, not for data",
                await page.until("document.querySelector('main')?.textContent.includes('когда вернётся связь')"))
        await page.shot(os.path.join(out, "connection-busy.png"))
        await page.tap("document.querySelector('.banner button')")
        verdict("Reconnect brings the data back without reloading the page",
                await page.until("healthConn.conn.ready && !!document.querySelector('.memory-status.bad')"))
        verdict("the load screen returns", await page.until("!!document.querySelector('main .meter')"))
        verdict("no script errors", not page.errors, page.errors)
    return 1 if verdict.failures else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
