"""Probe: what Telegram keeps inside an expandable blockquote (stage D4, a folded result). The Bot API's rules say a
blockquote can hold bold, italic, underline, strikethrough and spoiler only — "all other entities can't contain each
other"; this checks it on the real Bot API. Sends three silent messages to the owner's private chat with the bot and
deletes each at once. Prints only what Telegram answered: no token, no IDs.

  ~/.local/share/pult/venv/bin/python tests/probe_quote.py
"""
import asyncio, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
import pultd  # noqa: E402

CASES = [
    ("bold, italic", "<b>Итог</b>\n<blockquote expandable>Длинный текст с <b>жирным</b> и <i>курсивом</i>.</blockquote>"),
    ("inline code", "<b>Итог</b>\n<blockquote expandable>Коммит — <code>Checkout: clearer errors</code>.</blockquote>"),
    ("a link", "<b>Итог</b>\n<blockquote expandable>Посмотреть: <a href=\"https://example.com\">стенд</a>.</blockquote>"),
    ("a code block", "<b>Итог</b>\n<blockquote expandable>До блока\n<pre>make deploy-staging</pre>\nпосле блока</blockquote>"),
]


async def main():
    env = pultd.load_env()
    tg = pultd.Tg(env["PULT_BOT_TOKEN"], proxy=env.get("PULT_PROXY") or None)
    chat = sorted(int(x) for x in env.get("PULT_ALLOWED_USER_IDS", "").replace(",", " ").split())[0]
    for name, text in CASES:
        try:
            m = await tg.call("sendMessage", chat_id=chat, text=text, parse_mode="HTML", disable_notification=True)
        except pultd.TgError as e:
            print("%-14s refused: %s" % (name, e))
            continue
        kept = [(x["type"], x["offset"], x["length"]) for x in m.get("entities", [])]
        print("%-14s accepted · entities: %s" % (name, kept))
        try:
            await tg.call("deleteMessage", chat_id=chat, message_id=m["message_id"])
        except pultd.TgError as e:
            print("   not deleted:", e)


asyncio.run(main())
