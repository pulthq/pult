#!/usr/bin/env python3
"""Web app tests without Telegram or Claude: login (signed with the bot key), reading the conversation from
the transcript, and the end-to-end chain phone → relay (relay/relay.py) → daemon (pult_web) → hook.

  ~/.local/share/pult/venv/bin/python tests/test_web.py
"""
import asyncio
import base64
import hashlib
import hmac
import json
import os
import shutil
import subprocess
import sys
import time
import unittest
import urllib.parse
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import test_pult as T  # noqa: E402  — fake Telegram, the hook, temp folders

os.environ.update(PULT_RELAY_SECRET="s3cret", PULT_OWNER_ID=str(T.OWNER), PULT_BOT_ID="777",
                  PULT_WEB_DIR=str(HERE.parent / "relay" / "web"))
sys.path.insert(0, str(HERE.parent / "relay"))
import aiohttp  # noqa: E402
from aiohttp.test_utils import TestServer  # noqa: E402
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey  # noqa: E402
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat  # noqa: E402

import pult_web as PW  # noqa: E402
import pultd  # noqa: E402
import pult_spend as S  # noqa: E402
import relay  # noqa: E402

TOKEN = "777:TEST-TOKEN"
KEY = Ed25519PrivateKey.generate()
relay.TG_PUBLIC = KEY.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)


def init_data(uid=T.OWNER, age=0, hmac_with_signature=True, tamper=False):
    """initData as Telegram signs it: signature (Ed25519) and hash (HMAC with the bot key)."""
    f = {"auth_date": str(int(time.time() - age)), "chat_type": "supergroup", "start_param": "s_x",
         "user": json.dumps({"id": uid, "first_name": "D"})}
    dcs = "777:WebAppData\n" + "\n".join("%s=%s" % (k, f[k]) for k in sorted(f))
    f["signature"] = base64.urlsafe_b64encode(KEY.sign(dcs.encode())).decode().rstrip("=")
    secret = hmac.new(b"WebAppData", TOKEN.encode(), hashlib.sha256).digest()
    fs = f if hmac_with_signature else {k: v for k, v in f.items() if k != "signature"}
    f["hash"] = hmac.new(secret, "\n".join("%s=%s" % (k, fs[k]) for k in sorted(fs)).encode(),
                         hashlib.sha256).hexdigest()
    if tamper:
        f["chat_type"] = "private"
    return urllib.parse.urlencode(f)


def line(kind, content, side=False, meta=False):
    return json.dumps({"type": kind, "isSidechain": side, "isMeta": meta, "timestamp": "2026-10-16T12:00:00.000Z",
                       "message": {"role": kind, "content": content}})


class InitTest(unittest.TestCase):
    def test_check_init(self):
        owners = {T.OWNER}
        self.assertEqual(PW.check_init(init_data(), TOKEN, owners), (True, T.OWNER, "with signature"))
        self.assertEqual(PW.check_init(init_data(hmac_with_signature=False), TOKEN, owners)[0::2],
                         (True, "without signature"))
        self.assertEqual(PW.check_init(init_data(tamper=True), TOKEN, owners)[2], "signature mismatch")
        self.assertEqual(PW.check_init(init_data(), "777:OTHER", owners)[2], "signature mismatch")
        self.assertEqual(PW.check_init(init_data(uid=5), TOKEN, owners)[2], "not the owner")
        self.assertEqual(PW.check_init(init_data(age=2 * 86400), TOKEN, owners)[2], "login expired")
        self.assertFalse(PW.check_init("", TOKEN, owners)[0])
        # a new login takes minutes-fresh initData; an older one still proves the owner — for a resume key
        self.assertTrue(PW.check_init(init_data(age=5 * 60), TOKEN, owners)[0])
        self.assertEqual(PW.check_init(init_data(age=11 * 60), TOKEN, owners)[2], "login expired")
        self.assertTrue(PW.check_init(init_data(age=2 * 86400), TOKEN, owners, max_age=PW.SIGNED_MAX)[0])
        self.assertAlmostEqual(PW.init_age(init_data(age=300)), 300, delta=2)

    def test_resume_keys(self):
        k = PW.Keys(pultd.Store(T.TMP / "keys.db"))
        a = k.issue(42, now=1000)
        self.assertIsNone(k.use(a, 43, now=1001))                       # someone else's
        b = k.use(a, 42, now=1001)
        self.assertTrue(b and b != a)
        self.assertTrue(k.use(a, 42, now=1001 + PW.KEY_GRACE - 1))      # a racing reconnect still gets in…
        self.assertIsNone(k.use(a, 42, now=1001 + PW.KEY_GRACE + 1))    # …then the old key is dead
        self.assertIsNone(k.use(b, 42, now=1001 + PW.KEY_IDLE + 1))     # unused for too long
        self.assertIsNone(k.use("", 42) or k.use(None, 42) or k.use("nope", 42))
        c = k.issue(42)
        self.assertNotIn(c, json.dumps(k.store.get("app_keys")))       # only hashes are kept
        k.drop_all()
        self.assertIsNone(k.use(c, 42))
        for _ in range(PW.KEYS_MAX + 5):
            k.issue(42)
        self.assertEqual(len(k.store.get("app_keys")), PW.KEYS_MAX)

    def test_networks(self):
        self.assertEqual(PW.net_of("203.0.113.77"), "203.0.113.x")
        self.assertEqual(PW.net_of("::ffff:203.0.113.77"), "203.0.113.x")
        self.assertEqual(PW.net_of("2001:db8:1:2::5"), "2001:db8:1::/48")
        self.assertEqual(PW.net_of("garbage"), "garbage")
        self.assertEqual(PW.net_of("127.0.0.1"), "")                     # the web server's own hop: unknown
        self.assertEqual(PW.net_of("::1"), "")
        lg = PW.Logins(pultd.Store(T.TMP / "logins.db"))
        self.assertFalse(lg.note(True, "open", "203.0.113.1", {"platform": "android", "version": "9.6"}))  # learns
        self.assertFalse(lg.note(True, "key", "203.0.113.9", {}))         # the same network
        self.assertFalse(lg.note(False, "expired", "198.51.100.1", {}))   # refused: not a new place to tell about
        self.assertTrue(lg.note(True, "open", "198.51.100.1", {}))
        self.assertFalse(lg.note(True, "open", "198.51.100.2", {}))
        rec = lg.recent()
        self.assertEqual([(r["ok"], r["how"]) for r in rec[:3]], [(True, "open"), (True, "open"), (False, "expired")])
        self.assertEqual(rec[-1]["dev"], "android 9.6")
        self.assertFalse(lg.note(True, "open", "127.0.0.1", {}))           # unknown: never "new", never learned
        self.assertNotIn("", lg.store.get("app_nets"))
        old = PW.Logins(pultd.Store(T.TMP / "logins-0923.db"))
        old.store.put("app_nets", {"127.0.0.x": 1})                       # what 0.9.23 learned behind the stream
        self.assertFalse(old.note(True, "open", "203.0.113.1", {}))        # the first real network: learned quietly
        self.assertEqual(list(old.store.get("app_nets")), ["203.0.113.x"])

    def test_links_show_where_they_lead(self):
        import pult_render as R
        self.assertEqual(R.link("docs", "https://example.com/a"), '<a href="https://example.com/a">docs</a> (example.com)')
        self.assertEqual(R.link("example.com", "https://www.example.com/a"), '<a href="https://www.example.com/a">example.com</a>')
        self.assertEqual(R.link("https://example.com/x", "https://example.com/y"),
                         '<a href="https://example.com/y">https://example.com/x</a>')
        self.assertIn("(evil.example)", R.link("google.com", "https://evil.example/login"))
        self.assertIn("(evil.example)", R.link("https://google.com/?evil.example", "https://evil.example/"))
        self.assertIn("(xn--", R.link("Telegram", "https://teleqrаm.org/"))           # a Cyrillic "а" stays visible
        self.assertIn("(evil.example)", R.md_to_html("[Войти](https://evil.example/x)"))

    @unittest.skipUnless(shutil.which("node"), "node is not installed")
    def test_links_in_the_app(self):
        md = (HERE.parent / "relay" / "web" / "static" / "md.js").as_uri()
        js = ("import {md} from %s; for (const s of [\"[docs](https://example.com/a)\", \"[example.com](https://www.example.com/)\", "
              "\"[Telegram](https://teleqrаm.org/)\", \"[x](https://e.example/\\\"onmouseover=1)\"]) console.log(md(s));" % json.dumps(md))
        out = subprocess.run(["node", "--input-type=module", "-e", js], capture_output=True, text=True, timeout=30)
        lines = out.stdout.splitlines()
        self.assertEqual(len(lines), 4, out.stderr)
        self.assertIn('docs</a> <span class="host">(example.com)</span>', lines[0])
        self.assertNotIn("host", lines[1])
        self.assertIn("(xn--", lines[2])
        self.assertNotIn('"onmouseover', lines[3])                         # the address stays inside its quotes


class TranscriptTest(unittest.TestCase):
    def setUp(self):
        self.p = T.TMP / "page.jsonl"
        lines = [line("user", "<system-reminder>шум</system-reminder>Сделай отчёт"),
                 line("assistant", [{"type": "thinking", "thinking": "…"}, {"type": "text", "text": "Читаю файлы"}]),
                 line("assistant", [{"type": "tool_use", "id": "t1", "name": "Read", "input": {"file_path": "/p/a.md"}}]),
                 line("user", [{"type": "tool_result", "tool_use_id": "t1", "content": "строки файла"}]),
                 line("assistant", [{"type": "text", "text": "субагент"}], side=True),
                 line("user", "служебное", meta=True),
                 line("assistant", [{"type": "text", "text": "Готово"}]),
                 # a turn started by Claude Code itself: a background task ended — not something the owner said
                 line("user", "<task-notification>\n<task-id>b1</task-id>\n<status>completed</status>\n<summary>"
                              "Background command \"Сборка\" completed (exit code 0)</summary>\n</task-notification>")]
        self.p.write_text("\n".join(lines) + "\n" + '{"type":"assistant","mess')      # a partially written line

    def test_tail(self):
        page = PW.transcript_page(str(self.p), cwd="/p")
        kinds = [(i["k"], i.get("text") or i.get("step")) for i in page["items"]]
        self.assertEqual(kinds, [("user", "Сделай отчёт"), ("text", "Читаю файлы"), ("tool", "📖 a.md"),
                                 ("text", "Готово"), ("note", "⚙️ Закончилась фоновая задача «Сборка»")])
        # the owner's picture: the chat gets the text without the path and what to show instead
        p2 = T.TMP / "att.jsonl"
        p2.write_text(T.tline("user", "глянь\n\n[Attachment from the Pult app: /Users/x/.local/share/pult/inbox/2026-10/app-7.jpg]") + "\n" +
                      T.tline("user", "Have a look at the attachment.\n\n[Attachment from Telegram: /Users/x/Downloads/a.pdf]") + "\n")
        items = PW.transcript_page(str(p2))["items"]
        self.assertEqual([(i["text"], i.get("att")) for i in items], [
            ("глянь", [{"name": "2026-10/app-7.jpg", "image": True, "inbox": True}]),
            ("", [{"name": "a.pdf", "image": False, "inbox": False}])])
        # a message that reached Claude mid-turn (Claude Code 2.1.301: a queued_command attachment, not a user
        # message) shows up as the owner's message, marked; other attachments stay invisible
        p3 = T.TMP / "mid.jsonl"
        p3.write_text("\n".join([
            json.dumps({"type": "attachment", "timestamp": "2026-10-17T20:56:18.492Z", "attachment": {
                "type": "queued_command", "prompt": [{"type": "text", "text": "а меня ты обновил?"}], "commandMode": "prompt",
                "origin": {"kind": "human"}, "humanTurn": True}}),
            json.dumps({"type": "attachment", "timestamp": "2026-10-17T20:56:19.000Z", "attachment": {"type": "total_tokens_reminder"}}),
            json.dumps({"type": "queue-operation", "operation": "remove", "content": "а меня ты обновил?", "reason": "absorbed_mid_turn"}),
            # a session through the SDK (Pult's own): the same attachment has no origin at all (probe_midturn.py,
            # 2.1.300); a background task's report in that shape is Claude's own, not the owner's
            json.dumps({"type": "attachment", "timestamp": "2026-10-21T15:35:52.582Z", "attachment": {
                "type": "queued_command", "prompt": "стоп, не туда", "commandMode": "prompt"}}),
            json.dumps({"type": "attachment", "timestamp": "2026-10-21T15:35:53.000Z", "attachment": {
                "type": "queued_command", "commandMode": "prompt", "prompt":
                "<task-notification><task-id>b1</task-id><status>completed</status></task-notification>"}}),
        ]) + "\n")
        items = PW.transcript_page(str(p3))["items"]
        self.assertEqual([(i["k"], i["text"], i.get("mid")) for i in items],
                         [("user", "а меня ты обновил?", True), ("user", "стоп, не туда", True)])
        self.assertEqual(page["items"][2]["out"], "строки файла")
        self.assertIsNone(page["before"])
        self.assertEqual(page["end"], self.p.read_bytes().rfind(b"\n") + 1)      # the partial line is not consumed

    def test_spoken(self):
        # words that came by voice: the marker is for Claude; the chat gets the words and a flag
        p = T.TMP / "voice.jsonl"
        p.write_text(T.tline("user", "сделай деплой\n\n[Spoken message, transcribed automatically; some words may be misheard]") + "\n")
        items = PW.transcript_page(str(p))["items"]
        self.assertEqual([(i["text"], i.get("voice")) for i in items], [("сделай деплой", True)])

    def test_shown_pictures(self):
        # a picture Claude shows: a path into Pult's inbox in its reply → under the message, the path out of the text;
        # a picture anywhere else stays plain text
        p = T.TMP / "shown.jsonl"
        pic = "/Users/x/.local/share/pult/inbox/2026-10/claude-mock-home.png"
        p.write_text(T.tline("assistant", "Вот макет «Главной»:\n\n`%s`\n\nи ещё раз %s. Чужой: /tmp/a.png" % (pic, pic)) + "\n")
        item = PW.transcript_page(str(p))["items"][0]
        self.assertEqual(item["att"], [{"name": "2026-10/claude-mock-home.png", "image": True, "inbox": True}])
        self.assertNotIn("inbox", item["text"])
        self.assertIn("/tmp/a.png", item["text"])

    def test_updates(self):
        # Claude's own lines about its progress: the transcript marks the entry thinkingDisplay "updates" (the VS Code
        # tab shows it as "summary"); plain thinking stays private, empty lines are skipped, signatures never leave
        def think(text, display=None):
            e = {"type": "assistant", "timestamp": "2026-10-18T08:06:10.000Z",
                 "message": {"role": "assistant", "content": [{"type": "thinking", "thinking": text, "signature": "SIG"}]}}
            if display:
                e["thinkingDisplay"] = display
            return json.dumps(e, ensure_ascii=False)
        p = T.TMP / "upd.jsonl"
        p.write_text("\n".join([think("private reasoning"), think("Смотрю журнал демона\n", "updates"), think("", "updates"),
                                T.tline("assistant", tool=True)]) + "\n")
        page = PW.transcript_page(str(p))
        self.assertEqual([(i["k"], i.get("text") or i.get("name")) for i in page["items"]],
                         [("update", "Смотрю журнал демона"), ("tool", "Read")])
        self.assertNotIn("SIG", json.dumps(page))
        self.assertNotIn("private", json.dumps(page))

    def test_before_after(self):
        size = self.p.stat().st_size
        page = PW.transcript_page(str(self.p), page=400)
        self.assertIsNotNone(page["before"])
        older = PW.transcript_page(str(self.p), before=page["before"], page=10000)
        self.assertEqual(older["items"][0]["text"], "Сделай отчёт")
        with self.p.open("a") as f:
            f.write('age":{"content":[{"type":"text","text":"Новое"}]}}\n')    # the line got completed
        new = PW.transcript_page(str(self.p), after=page["end"])
        self.assertEqual([i["text"] for i in new["items"]], ["Новое"])
        self.assertEqual(PW.transcript_page(str(self.p), after=0, page=100)["reset"], True)
        self.assertGreater(new["end"], size)


def usage_reply(session=12, week=4, fable=0, share=None):
    lim = lambda kind, pct, model=None: {"kind": kind, "percent": pct, "resets_at": "2026-10-16T17:00:00+00:00",
                                         "severity": "normal", "is_active": kind == "session",
                                         "scope": {"model": {"display_name": model}} if model else None}
    return {"subscription_type": "max", "rate_limits": {
        "limits": [lim("session", session), lim("weekly_all", week), lim("weekly_scoped", fable, "Fable")],
        "weekly_scoped_shares": [{"limit_index": 2, "used_percent_of_weekly": share, "allowance_percent_of_weekly": 50}] if share is not None else [],
        "extra_usage": {"is_enabled": False}, "seven_day_breakdown": {"rows": [
            {"display_name": "Claude Code", "percent": 100}, {"display_name": "Chats", "percent": 0}]}}}


def tline(kind, ts, **message):
    """A transcript line at `ts`: the owner's message, a tool's result or a model reply."""
    return json.dumps({"type": kind, "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(ts)) + ".000Z",
                       "message": dict({"role": kind}, **message)}) + "\n"


def reply(ts, mid, model="claude-opus-5-5", stop="end_turn", **usage):
    return tline("assistant", ts, id=mid, model=model, stop_reason=stop, content=[], usage=usage)


def slots_of(weights, t0, fable=None):
    """Slots with an Opus weight each (and a Fable one), one session working in each."""
    out = {}
    for j, w in enumerate(weights):
        s = S.Slot()
        s.per["-Users-x-a"] = [float(w), float((fable or {}).get(j, 0)), 0.0, 0.0, 0.0, 1, 0, 0]
        s.work.add("s1")
        out[int(t0 // S.SLOT) + j] = s
    return out


class SpendTest(unittest.TestCase):
    """Stage R: the transcripts in slots, the curve through Claude Code's readings, the pace and the forecast."""

    def test_read(self):
        root = T.TMP / "spend"
        shutil.rmtree(root, ignore_errors=True)
        lt = time.localtime()
        now = time.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday, 12, 0, 0, 0, 0, -1))
        t = now - 3 * 3600 - (now % S.SLOT)
        (root / "-Users-x-a" / "s1" / "subagents").mkdir(parents=True)
        (root / "-private-tmp-x").mkdir(parents=True)
        tool = [{"type": "tool_result", "tool_use_id": "x", "content": 'a line "timestamp":"2020-01-01T00:00:00.000Z"'}]
        (root / "-Users-x-a" / "s1.jsonl").write_text(
            tline("user", t, content="do it")
            + reply(t + 60, "m1", stop="tool_use", input_tokens=10, output_tokens=100, cache_read_input_tokens=1000,
                    cache_creation_input_tokens=200, cache_creation={"ephemeral_1h_input_tokens": 100})
            + reply(t + 61, "m1", stop="tool_use", input_tokens=10, output_tokens=100)      # the same reply, another block
            + tline("user", t + 1200, content=tool)                                        # a 20-minute command
            + reply(t + 1260, "m2", model="claude-fable-5-1", output_tokens=50)            # the turn ends
            + tline("user", t + 7200, content="and this")                                  # two hours later
            + reply(t + 7260, "m3", model="claude-haiku-5-5", output_tokens=4))
        (root / "-Users-x-a" / "s1" / "subagents" / "agent-a1.jsonl").write_text(
            reply(t + 300, "a1", model="claude-sonnet-5-5", output_tokens=10))
        (root / "-private-tmp-x" / "t.jsonl").write_text(reply(t, "t1", output_tokens=99))   # a throwaway folder
        sp = S.Spend(root, pultd.skip_pkey)
        sp.update(now)
        i = int(t // S.SLOT)
        work = sorted(k - i for k, x in sp.slots.items() if x.work)
        self.assertEqual(work, [0, 1, 2, 3, 4, 24])          # the command counts as work, the 2 hours after the turn don't
        self.assertEqual([k - i for k, x in sp.slots.items() if x.agents], [1])
        self.assertEqual(sp.slots[i].per["-Users-x-a"][:2], [10 + 100 + 500 + 125 + 200, 0.0])    # one reply, once
        self.assertEqual(sp.slots[i + 4].weight(S.FACTOR), 250 * S.FACTOR["fable"])
        self.assertEqual(sp.today(now)["projects"], [{"pkey": "-Users-x-a", "req": 4, "out": 164, "read": 1210}])
        with (root / "-Users-x-a" / "s1.jsonl").open("a") as f:         # only what is appended is read again
            f.write(tline("user", t + 7500, content="more") + reply(t + 7560, "m4", output_tokens=1)[:30])
        sp.update(now)
        self.assertEqual(sp.today(now)["projects"][0]["req"], 4)      # the reply is not finished yet
        self.assertIn(i + 25, sp.slots)

    def test_curve(self):
        t0 = S.SLOT * 4000
        slots = slots_of([1, 1, 2, 0, 0, 0, 4], t0)
        log = [(t0 + 900, "session", 4, t0 + 18000), (t0 + 2400, "session", 6, t0 + 18000),   # +2 points: too rough
               (t0 + 1000, "session", 5, t0 + 99999)]                                       # another window's
        rows = S.curve(slots, t0, t0 + 3600, 10, log, "session", t0 + 18000, S.FACTOR)
        self.assertEqual([round(r[2], 3) for r in rows], [1, 1, 2, 0, 0, 0, 6, 0, 0, 0, 0, 0, 0])   # through each reading
        self.assertEqual(sum(r[3] for r in rows), 0)
        rows = S.curve(slots_of([0, 0, 0, 5], t0), t0, t0 + 1200, 5, [(t0 + 900, "session", 3, t0 + 18000)],
                       "session", t0 + 18000, S.FACTOR)
        self.assertEqual([(r[2], r[3]) for r in rows], [(1, 1), (1, 1), (1, 1), (2, 0), (0, 0)])  # no tokens here — elsewhere

    def lims(self, now, week, h5=None, h5_left=7200):
        out = [{"kind": "weekly_all", "name": "Неделя", "percent": week, "resets_at": now + 86400}]
        if h5 is not None:
            out.append({"kind": "session", "name": "Окно 5 ч", "percent": h5, "resets_at": now + h5_left})
        return {"limits": out, "shares": []}

    def test_forecast(self):
        t0 = S.SLOT * 4_000_000
        now = t0 + 6 * 86400                                   # a week at one weight unit a slot, one session always
        slots = slots_of([1] * (6 * 288), t0)
        state = lambda used: S.view(slots, self.lims(now, used), [], now, 90, {})["limits"][0]
        w = state(60)                                           # 10 % a day: the last day's pace
        self.assertEqual((w["state"], round(w["rate"], 4), round(w["proj"], 1), round(w["spare"], 1)), ("under", 0.4167, 70.0, 30.0))
        self.assertEqual((round(w["per_sh"], 4), round(w["sh_left"]), w["par"]), (0.4167, 72, None))
        self.assertEqual(len(w["bars"]), 145)                   # an hour a bar, up to now
        self.assertEqual((w["bars"][0][:3], w["projects"][0][0]), ([round(60 / 144, 3), 1, 0], "-Users-x-a"))
        self.assertEqual(state(80)["state"], "pace")            # ~93 % at the reset
        self.assertEqual(S.view(slots, self.lims(now, 80), [], now, 95, {})["limits"][0]["state"], "under")
        over = state(90)                                        # 105 %: runs out in 16 h, 8 h before the reset
        self.assertEqual((over["state"], round((over["hit"] - now) / 3600, 1), over["spare"]), ("over", 16.0, 0.0))
        self.assertEqual(state(100)["state"], "over")
        # the 5-hour window, 3 h in, 30 %: it would leave 50 % — unless the week has less left
        v = S.view(slots, self.lims(now, 60, h5=30), [], now, 90, {})
        h5 = v["limits"][1]
        self.assertEqual((h5["key"], h5["state"], round(h5["proj"]), round(h5["par"], 1)), ("h5", "under", 50, 2.5))   # 5 session-hours left in 2 h
        self.assertNotIn("tighter", h5)
        self.assertEqual(v["top"], "week")                     # nothing runs out: the fuller one
        v = S.view(slots, self.lims(now, 90, h5=30), [], now, 90, {})
        self.assertEqual((v["limits"][1]["tighter"], v["top"]), ({"sh": 0.0}, "week"))
        self.assertEqual(S.view(slots, self.lims(now, 60, h5=99, h5_left=7200), [], now, 90, {})["top"], "h5")
        stale = S.view(slots, self.lims(now, 60, h5=30, h5_left=-60), [], now, 90, {})   # the window reset after the reading
        self.assertEqual([x["key"] for x in stale["limits"]], ["week"])
        # 2 % is too rough for its own rate: the one kept from before
        v = S.view(slots, self.lims(now, 60, h5=2), [], now, 90, {"k": {"h5": 0.5}})
        self.assertEqual((round(v["limits"][1]["rate"], 2), v["known"]["k"]["h5"]), (6.0, 0.5))
        self.assertEqual(S.view(slots, self.lims(now, 60, h5=2), [], now, 90, {})["limits"][1]["state"], "none")

    def test_fable_factor(self):
        t0 = S.SLOT * 4_000_000
        slots = slots_of([300], t0, fable={0: 100})
        u = {"limits": [{"kind": "weekly_all", "percent": 60, "resets_at": t0 + 7 * 86400}], "shares": [{"name": "Fable", "used": 30}]}
        self.assertEqual(S.fit_factor(slots, u, t0, t0 + 7 * 86400, t0 + 600)["fable"], 3.0)   # half the week from a quarter of the tokens
        u["shares"][0]["used"] = 0
        self.assertEqual(S.fit_factor(slots, u, t0, t0 + 7 * 86400, t0 + 600)["fable"], S.FACTOR["fable"])

    def test_shares(self):
        self.assertEqual(PW.simplify_usage(usage_reply(fable=64, share=32))["shares"], [{"name": "Fable", "used": 32, "allow": 50}])
        self.assertEqual(PW.simplify_usage(usage_reply())["shares"], [])


class UsageStatsTest(unittest.TestCase):
    def test_simplify(self):
        u = PW.simplify_usage(usage_reply())
        self.assertEqual([(x["name"], x["percent"]) for x in u["limits"]],
                         [("Окно 5 ч", 12), ("Неделя", 4), ("Неделя · Fable", 0)])
        self.assertEqual(u["week_by"], [{"name": "Claude Code", "percent": 100}])
        old = PW.simplify_usage({"rate_limits": {"five_hour": {"utilization": 30, "resets_at": None}}})
        self.assertEqual(old["limits"][0]["name"], "Окно 5 ч")              # the old response format

    def test_reset_text(self):
        now = time.time()
        self.assertIn("через 2 ч 10 мин", T.R.reset_text(now + 2 * 3600 + 600, now))
        self.assertRegex(T.R.reset_text(now + 3 * 86400, now), r"^(пн|вт|ср|чт|пт|сб|вс) \d\d:\d\d$")

    def test_stats(self):
        p = T.TMP / "stats.jsonl"

        def a(mid, out, ctx, effort="xhigh", model="claude-opus-5-5"):
            return json.dumps({"type": "assistant", "effort": effort, "message": {"id": mid, "model": model, "usage": {
                "input_tokens": 2, "cache_read_input_tokens": ctx, "cache_creation_input_tokens": 10,
                "output_tokens": out, "output_tokens_details": {"thinking_tokens": out // 2}}, "content": []}})
        p.write_text("\n".join([line("user", "первый"), a("m1", 100, 1000), a("m1", 100, 1000), a("m2", 50, 2000)]) + "\n")
        s = PW.Stats()
        got = s.get(str(p))
        # context counts the reply's own tokens too — the same sum as VS Code's gauge (2012 read + 50 written)
        self.assertEqual((got["model"], got["effort"], got["context"]), ("claude-opus-5-5", "xhigh", 2062))
        self.assertEqual(got["turn"], {"req": 2, "out": 150, "think": 75})       # m1 is written twice — one request
        with p.open("a") as f:
            f.write(line("user", [{"type": "tool_result", "tool_use_id": "x", "content": "ok"}]) + "\n")
            f.write(a("m3", 10, 3000) + "\n" + line("user", "второй") + "\n" + a("m4", 7, 4000, "high") + "\n")
        got = s.get(str(p))                                                     # only the new part is read
        self.assertEqual(got["turn"], {"req": 1, "out": 7, "think": 3})        # a new prompt — a new turn
        self.assertEqual(got["sess"], {"req": 4, "out": 167})
        self.assertEqual(got["effort"], "high")

    def test_day_tokens(self):
        root = T.TMP / "day"
        now = time.time()
        iso = lambda ago: time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime(now - ago))
        lt = time.localtime(now)
        since = now - time.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday, 0, 0, 0, 0, 0, -1))   # since midnight

        def a(mid, out, ago=0.0, side=False):
            return json.dumps({"type": "assistant", "isSidechain": side, "timestamp": iso(ago), "message": {
                "id": mid, "usage": {"input_tokens": 1, "cache_read_input_tokens": 100, "cache_creation_input_tokens": 9,
                                     "output_tokens": out}, "content": []}}) + "\n"
        for d in ("-Users-x-a", "-Users-x-b", "-Users-x-a/s1/subagents", "-private-tmp-x"):
            (root / d).mkdir(parents=True, exist_ok=True)
        fa = root / "-Users-x-a" / "s1.jsonl"
        fa.write_text(a("y1", 999, ago=since + 60) + a("m1", 10) + a("m1", 10) + line("user", "запрос") + "\n" + a("m2", 5))
        (root / "-Users-x-a" / "s1" / "subagents" / "agent-1.jsonl").write_text(a("s1", 7, side=True))
        (root / "-Users-x-b" / "s2.jsonl").write_text(a("m1", 10) + a("m3", 100))  # session fork: m1 is already counted
        (root / "-private-tmp-x" / "t.jsonl").write_text(a("t1", 50))
        os.utime(fa, (now - 60, now - 60))                                       # copy b is newer than original a
        dt = S.Spend(root, pultd.skip_pkey)
        got = {r["pkey"]: (r["req"], r["out"], r["read"]) for r in dt.today(now)["projects"]}
        self.assertEqual(got, {"-Users-x-a": (3, 22, 330), "-Users-x-b": (1, 100, 110)})   # yesterday's, /tmp — skipped
        self.assertEqual([r["pkey"] for r in dt.today(now)["projects"]], ["-Users-x-b", "-Users-x-a"])  # sorted by output
        with fa.open("a") as f:
            f.write(a("m4", 1) + a("m5", 1000)[:40])                             # the second one is incomplete
        self.assertEqual(dt.today(now)["projects"][1]["out"], 23)
        with fa.open("a") as f:
            f.write(a("m5", 1000)[40:])
        self.assertEqual(dt.today(now)["projects"][0], {"pkey": "-Users-x-a", "req": 5, "out": 1023, "read": 550})
        self.assertEqual(dt.today(now + 86400)["projects"], [])                  # a new day: yesterday is not today


class ChainBase(unittest.IsolatedAsyncioTestCase):
    """A daemon with a fake Telegram, a real relay and app windows that log in through it."""

    async def asyncSetUp(self):
        self.fake = T.FakeTg()
        tg = pultd.Tg("T", transport=T.httpx.MockTransport(self.fake.handler))
        self.store = pultd.Store(T.TMP / ("web-%s.db" % self._testMethodName))
        self.store.put("chat", T.CHAT)
        self.store.put("lang_tg", "ru")
        self.store.set_topic(T.PKEY, "/Users/x/proj", "proj", 77)
        self.p = pultd.Pult({"PULT_ALLOWED_USER_IDS": str(T.OWNER), "PULT_FORCE_AWAY": "1"}, tg, self.store)
        self.p.out = pultd.Outbox(rate=60000, burst=1000)
        self.p._agents = (time.monotonic() + 1e6, [])
        pultd.EDIT_EVERY = 0.05
        self.sock = await pultd.start_link(self.p.handle_conn, os.environ["PULT_SOCK"])
        self.srv = TestServer(relay.app())
        await self.srv.start_server()
        url = str(self.srv.make_url("/pult/agent")).replace("http://", "ws://")
        self.p.web = PW.Web(self.p, url, "s3cret", TOKEN, {T.OWNER})
        self.tasks = [asyncio.create_task(self.p.out.run()), asyncio.create_task(self.p.web.run())]
        self.http = aiohttp.ClientSession()
        await T.until(lambda: self.p.web.ws is not None)

    async def asyncTearDown(self):
        await self.http.close()
        for t in self.tasks:
            t.cancel()
        await self.srv.close()
        self.sock.close()

    async def phone(self, init=None, resume=None, ip=None, keyed=False):
        """An app window logs in → the connection (keyed: and the resume key it got, or the refusal)."""
        ws = await self.http.ws_connect(str(self.srv.make_url("/pult/ws")), headers={"X-Real-IP": ip} if ip else None)
        await ws.send_str(json.dumps({"t": "hello", "init": init or init_data(), "resume": resume,
                                      "client": {"platform": "android", "version": "9.6"}}))
        self.assertEqual(json.loads((await ws.receive(timeout=5)).data)["t"], "hello")
        m = json.loads((await ws.receive(timeout=5)).data)
        if keyed:
            return ws, m
        self.assertEqual((m["t"], len(m.get("resume") or "")), ("ready", 43))   # the Mac verified it, gave a key
        return ws

    async def until_msg(self, ws, t):
        while True:
            m = json.loads((await ws.receive(timeout=5)).data)
            if m.get("t") == t:
                return m

    async def call(self, ws, op, **args):
        await ws.send_str(json.dumps({"t": "req", "id": op, "op": op, "args": args}))
        while True:
            m = json.loads((await ws.receive(timeout=5)).data)
            if m.get("t") == "res" and m.get("id") == op:
                return m


class ChainTest(ChainBase):
    async def test_chain(self):
        ws = await self.phone()
        res = await self.call(ws, "overview")
        self.assertEqual(res["data"]["live"], [])
        self.assertTrue(res["data"]["mac"]["away"])
        self.assertIn("нет такого запроса", (await self.call(ws, "rm_rf"))["error"])
        # Claude asks for permission in a tab — the app window learns about it at once and answers
        proc = await T.run_hook(T.ev("PermissionRequest", tool_name="Bash", tool_input={"command": "git push"}),
                                wait=False)
        while json.loads((await ws.receive(timeout=5)).data).get("kind") != "change":
            pass
        pending = (await self.call(ws, "overview"))["data"]["pending"]
        self.assertEqual(len(pending), 1)
        self.assertIn("git push", pending[0]["html"])
        self.assertLess(abs(pending[0]["since"] - time.time()), 30)          # "your move" orders it by time with the rest
        res = await self.call(ws, "answer", rid=pending[0]["rid"], act="y")
        self.assertTrue(res["data"]["ok"])
        out = json.loads((await proc.stdout.read()).decode())
        self.assertEqual(out["hookSpecificOutput"]["decision"]["behavior"], "allow")
        await T.until(lambda: any("разрешено из приложения" in t for t in [d.get("text", "") for d in self.fake.of("editMessageText")]))
        res = await self.call(ws, "answer", rid=pending[0]["rid"], act="y")
        self.assertEqual(res["data"]["note"], "уже решено")
        # the session transcript; a foreign path instead of an id — refused
        Path(T.TP).parent.mkdir(parents=True, exist_ok=True)
        Path(T.TP).write_text(line("user", "Привет") + "\n")
        self.store.touch_session(T.SID, T.PKEY)
        old, pultd.CLAUDE_PROJECTS = pultd.CLAUDE_PROJECTS, Path(T.TP).parent.parent
        try:
            res = await self.call(ws, "session", sid=T.SID)
            self.assertEqual(res["data"]["page"]["items"][0]["text"], "Привет")
            self.assertIn("неверный номер", (await self.call(ws, "session", sid="../../etc/passwd"))["error"])
        finally:
            pultd.CLAUDE_PROJECTS = old
        await ws.close()

    async def test_app_buttons(self):
        def urls(d):
            return [b.get("url") for row in json.loads(d.get("reply_markup", "{}")).get("inline_keyboard", []) for b in row if b.get("url")]
        self.p.env["PULT_APP_LINK"] = "https://t.me/bot/pult"
        await T.run_hook(T.ev("UserPromptSubmit", prompt="задача"))
        await T.until(lambda: self.fake.of("sendMessage"))
        turn = next(d for d in self.fake.of("sendMessage") if "задача" in d["text"])
        self.assertEqual(urls(turn), ["https://t.me/bot/pult?startapp=s_" + T.SID])
        long = "\n\n".join("Абзац %d. " % i + "слово " * 120 for i in range(12))       # ~9k characters
        await T.run_hook(T.ev("Stop", last_assistant_message=long))
        await T.until(lambda: any("готово" in d["text"] for d in self.fake.of("sendMessage")))
        await asyncio.sleep(0.2)
        res = [d for d in self.fake.of("sendMessage") if "Абзац" in d["text"]]
        self.assertEqual(len(res), 1)                                   # the app is connected — one message…
        self.assertIn("… ещё", res[0]["text"])
        self.assertIn("Абзац 0.", res[0]["text"])
        self.assertNotIn("Абзац 11.", res[0]["text"])                 # …with the beginning; the full text is in the app
        self.assertEqual(json.loads(res[0]["reply_markup"])["inline_keyboard"][0][0]["text"], "Читать полностью")
        del self.p.env["PULT_APP_LINK"]
        self.assertIsNone(self.p.with_app(None, T.SID))                 # not configured — no buttons

    async def test_usage_warnings(self):
        self.p.env["PULT_APP_LINK"] = "https://t.me/bot/pult"
        await self.p.warn_usage(PW.simplify_usage(usage_reply(session=82)))
        await self.p.warn_usage(PW.simplify_usage(usage_reply(session=85)))       # same threshold — not repeated
        warns = [d for d in self.fake.of("sendMessage") if "⚠️" in d["text"]]
        self.assertEqual(len(warns), 1)
        self.assertIn("Окно 5 ч — 82 %", warns[0]["text"])
        self.assertIn("Неделя — 4 %", warns[0]["text"])
        self.assertEqual(warns[0]["disable_notification"], "false")               # with sound
        self.assertNotIn("message_thread_id", warns[0])                            # to "General"
        self.assertIn("startapp=usage", warns[0]["reply_markup"])
        await self.p.warn_usage(PW.simplify_usage(usage_reply(session=96)))
        self.assertEqual(len([d for d in self.fake.of("sendMessage") if "⚠️" in d["text"]]), 2)

    async def test_spend_screen(self):
        # stage R through the daemon: every reading goes into the usage log, the screen names the projects and gives
        # the five biggest a colour each, the Home strip shows the limit that runs out first, "on pace" is a setting
        root = T.TMP / "spend-screen"
        shutil.rmtree(root, ignore_errors=True)
        now = time.time()
        for n, pkey in enumerate(("-Users-nobody-gone-alpha", "-Users-nobody-gone-beta")):
            (root / pkey).mkdir(parents=True)
            (root / pkey / "s.jsonl").write_text("".join(reply(now - 3600 + 300 * j, "%s%d" % (pkey, j), output_tokens=100 * (2 - n))
                                                         for j in range(10)))
        self.p.spend = S.Spend(root, pultd.skip_pkey)
        u = PW.simplify_usage(usage_reply(session=20, week=95, fable=64, share=32))
        for lim in u["limits"]:
            lim["resets_at"] = now + (3600 if lim["kind"] == "session" else 86400)
        calls = []

        async def fake_usage(force=False):
            calls.append(force)
            self.p._usage = u
            self.store.log_usage(u)
            return u
        self.p.usage = fake_usage
        v = await self.p.api_spend(force=True)
        self.assertEqual(calls, [True])
        self.assertEqual([x["key"] for x in v["limits"]], ["week", "h5"])
        week = v["limits"][0]
        self.assertEqual([(x["name"], x["color"]) for x in week["projects"]], [("alpha", 0), ("beta", 1)])
        self.assertEqual(week["state"], "over")               # 95 % and a day of work at this pace
        self.assertEqual(v["shares"], [{"name": "Fable", "used": 32, "allow": 50}])
        self.assertEqual([o["name"] for o in v["others"]], ["Неделя · Fable"])
        self.assertEqual(self.store.usage_log(now - 60)[0][1:3], ("session", 20))
        self.assertEqual((await self.p.api_overview())["usage_top"], {"key": "week", "pct": 95.0, "state": "over"})
        self.assertEqual((await self.p.api_prefs(pace=95))["pace"], 95)
        self.assertEqual((await self.p.api_prefs(pace=42))["pace"], 95)      # only 85, 90 or 95
        self.assertEqual(self.store.get("spend_colors")["-Users-nobody-gone-alpha"][0], 0)   # the colour stays

    async def test_send_open_session_needs_fork(self):
        ws = await self.phone()
        Path(T.TP).parent.mkdir(parents=True, exist_ok=True)
        Path(T.TP).write_text(line("user", "Привет") + "\n")
        self.store.touch_session(T.SID, T.PKEY, path="/Users/x/proj")
        self.p._agents = (time.monotonic() + 1e6, [{"sessionId": T.SID}])          # open in a tab
        runs = []

        async def drive(sid, path, text, origin, **kw):
            runs.append((sid, text, origin, kw.get("fork"), kw.get("resume")))
        self.p.drive = drive
        old, pultd.CLAUDE_PROJECTS = pultd.CLAUDE_PROJECTS, Path(T.TP).parent.parent
        try:
            res = await self.call(ws, "send", sid=T.SID, text="продолжи")
            self.assertEqual(res["data"], {"ok": False, "need": "fork"})              # no consent — nothing is written
            res = await self.call(ws, "send", sid=T.SID, text="продолжи", fork=True)
            self.assertEqual(res["data"]["how"], "fork")
            self.assertEqual(runs[-1], (T.SID, "продолжи", None, True, None))
            self.p._agents = (time.monotonic() + 1e6, [])                             # the tab was closed
            res = await self.call(ws, "send", sid=T.SID, text="ещё")
            self.assertEqual(res["data"]["how"], "resume")
            self.assertEqual(runs[-1][4], T.SID)
        finally:
            pultd.CLAUDE_PROJECTS = old
        await ws.close()



class SecurityTest(ChainBase):
    async def test_resume_and_logout(self):
        old, PW.KEY_GRACE = PW.KEY_GRACE, 0
        try:
            ws, m = await self.phone(keyed=True)
            key = m["resume"]
            await ws.close()
            # an hour later the window reconnects: its initData is old, the key lets it in and is replaced
            ws, m = await self.phone(init_data(age=3600), resume=key, keyed=True)
            self.assertEqual(m["t"], "ready")
            key2 = m["resume"]
            # an old initData alone, or with a used-up key, is worth nothing
            for k in (None, key, "made-up"):
                w, m = await self.phone(init_data(age=3600), resume=k, keyed=True)
                self.assertEqual(m, {"t": "denied", "by": "mac", "why": "expired"})
            # the daemon's link to the relay drops: the window is logged in again by its key, by itself
            await self.p.web.ws.close()
            m = await self.until_msg(ws, "ready")
            self.assertNotEqual(m["resume"], key2)
            self.assertIn("live", (await self.call(ws, "overview"))["data"])
            # log out everywhere from the app: the window is closed, its key is gone
            self.assertTrue((await self.call(ws, "logout_all"))["data"]["ok"])
            self.assertEqual(await self.until_msg(ws, "denied"), {"t": "denied", "by": "mac", "why": "out"})
            w, m = await self.phone(init_data(age=3600), resume=m.get("resume"), keyed=True)
            self.assertEqual(m["t"], "denied")
            hows = [x["how"] for x in (await self.p.api_logins())["logins"]]
            self.assertEqual(hows[-3:], ["expired", "key", "open"])
            self.assertIn("badkey", hows)
        finally:
            PW.KEY_GRACE = old

    async def test_new_network(self):
        alerts = lambda: [d for d in self.fake.of("sendMessage") if "новой сети" in d["text"]]  # noqa: E731
        ws1 = await self.phone(ip="203.0.113.5")            # the first login only learns
        ws2 = await self.phone(ip="203.0.113.77")           # the same network
        self.assertEqual(alerts(), [])
        ws3 = await self.phone(ip="198.51.100.9")
        await T.until(alerts)
        a = alerts()[0]
        self.assertIn("198.51.100.x", a["text"])
        self.assertIn("android 9.6", a["text"])
        self.assertEqual(a["disable_notification"], "false")                     # with sound, wherever the owner is
        self.assertEqual(json.loads(a["reply_markup"])["inline_keyboard"][0][0]["callback_data"], "k:out")
        # a stranger's tap does nothing; the owner's closes every window
        await self.p.on_callback({"id": "1", "from": {"id": 5}, "data": "k:out", "message": {"message_id": 1}})
        await self.p.on_callback({"id": "2", "from": {"id": T.OWNER}, "data": "k:out", "message": {"message_id": 1}})
        for w in (ws1, ws2, ws3):
            self.assertEqual((await self.until_msg(w, "denied"))["why"], "out")

    async def test_files_guard(self):
        self.assertEqual(PW.page_csp("{}", "h.example:1"), relay.csp("{}", "h.example:1"))
        man = PW.make_manifest(HERE.parent / "relay" / "web")
        path = T.TMP / "manifest.json"
        path.write_text(json.dumps(man))
        self.p.web.manifest = path
        old, PW.GUARD_RECHECK = PW.GUARD_RECHECK, 0
        try:
            async with aiohttp.ClientSession() as http:
                self.assertEqual(await self.p.web.check_files(http), [])
                ws = await self.phone()
                path.write_text(json.dumps(dict(man, files=dict(man["files"], **{"md.js": "0" * 64}))))
                await self.p.web.guard_once(http)
                self.assertEqual(self.p.web.locked, "md.js")
                self.assertEqual((await self.until_msg(ws, "denied"))["why"], "locked")    # the open window is closed
                await T.until(lambda: [d for d in self.fake.of("sendMessage") if "Приложение закрыто" in d["text"]])
                w, m = await self.phone(keyed=True)                                         # no new logins
                self.assertEqual(m, {"t": "denied", "by": "mac", "why": "locked"})
                path.write_text(json.dumps(dict(man, index=man["index"] + "<!-- -->")))
                self.assertEqual(await self.p.web.check_files(http), ["index.html"])
                path.write_text(json.dumps(man))
                await self.p.web.guard_once(http)
                self.assertIsNone(self.p.web.locked)
                await T.until(lambda: [d for d in self.fake.of("sendMessage") if "снова совпадают" in d["text"]])
                await self.phone()
            self.p.web.manifest = T.TMP / "none.json"
            async with aiohttp.ClientSession() as http:
                self.assertIsNone(await self.p.web.check_files(http))                      # no deploy record — no check
        finally:
            PW.GUARD_RECHECK = old

    async def test_token_conflict(self):
        said = lambda w: [d for d in self.fake.of("sendMessage") if w in d["text"]]  # noqa: E731
        for _ in range(2):
            await self.p.conflict("Conflict: terminated by other getUpdates request")
        self.assertEqual(said("409"), [])                       # a moment's overlap (a restart) is not a leak
        await self.p.conflict("Conflict: terminated by other getUpdates request")
        await T.until(lambda: said("409"))
        await self.p.conflict("Conflict: can't use getUpdates method while webhook is active")
        self.assertEqual(len(self.fake.of("deleteWebhook")), 1)
        self.assertEqual(said("вебхук"), [])                    # told at most every 6 h
        self.store.put("conflict_warned", 0)
        await self.p.conflict("Conflict: can't use getUpdates method while webhook is active")
        await T.until(lambda: said("вебхук"))


class AppStringsTest(unittest.TestCase):
    def test_app_strings(self):
        # the app's dictionary: every key has both languages with the same {placeholders}, and every key the app
        # names outright is there (a missing one would show the key itself on the screen)
        import re
        web = HERE.parent / "relay" / "web" / "static"
        src = (web / "i18n.js").read_text()
        body = src[src.index("const S = {"):src.index("\n};")]
        q = r'"((?:[^"\\]|\\.)*)"'
        entries = {k: (en, ru) for k, en, ru in re.findall(
            r'^\s*"?([\w.]+)"?:\s*\{\s*en:\s*' + q + r',\s*ru:\s*' + q + r'\s*\}', body, re.M)}
        self.assertGreater(len(entries), 150)
        self.assertEqual(len(entries), len(re.findall(r'^\s*"?[\w.]+"?:\s*\{', body, re.M)))   # none unparsed
        for k, (en, ru) in entries.items():
            self.assertEqual(sorted(re.findall(r"\{(\w+)\}", en)), sorted(re.findall(r"\{(\w+)\}", ru)), k)
        used = {k for k in re.findall(r'\bt\("([\w.]+)"', (web / "app.js").read_text()) if not k.endswith(".")}
        self.assertFalse(used - set(entries), "keys the app uses but the dictionary lacks")
        for e in ("low", "medium", "high", "xhigh", "max"):                  # effortName() builds these
            self.assertIn("effort." + e, entries)
        for how in set(PW.REFUSED.values()) | {"open", "key", "locked"}:     # the logins list builds these
            self.assertIn("logins.how." + how, entries)
        for why in ("expired", "out", "locked"):                            # and the banner these
            self.assertIn("banner.denied." + why, entries)

if __name__ == "__main__":
    unittest.main(verbosity=1)
