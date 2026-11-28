"""Probe: what Pult's sentence about decisions (pult_hook.ASK_NOTE, in the SessionStart paragraph) changes in how
Claude ends a turn that needs the owner: a card (AskUserQuestion) or questions in the text of its last message. A
question in the text gets ready replies from a small model (pult_brief): a few one-tap buttons, which can't answer
two things or take several steps of a list — only Claude knows what goes with what. A card keeps the turn open, so
a plain report, a request for a photo and an offer of more work must stay in the text.

The same situations with Pult's paragraph as it was before the sentence (0.18.70) and with it. Nothing in the
situation names the tool: Claude is told what it has just done and asked to end the turn as it would.

Run (uses some of the subscription: 8 situations × 2 paragraphs × --runs sessions of --model; --par at a time,
~300 MB each; opus with 2 runs, 2 at a time — ~2 min):
  ~/.local/share/pult/venv/bin/python tests/probe_askcard.py [--model opus] [--effort high] [--runs 2] [--par 2]
      [--only before|after] [--cases two,list,…]
Claude's question is caught as its tool call and the session is closed there: nothing is answered, nothing runs, no
transcript is kept. User settings are not loaded (setting_sources=[]), so the real Pult hook doesn't run; the probe's
own hook gives the paragraph the way Pult's does. What Claude asked and wrote — in results.json, its path is printed.
What the probe can't show: a fresh session of one message asks decisions as cards with the old paragraph too, while
the owner's long sessions ended on questions in the text (2026-11-27: five steps and "Do step 1? And save to git?").
So it checks that the sentence keeps the cards and adds none where they are not wanted; whether long sessions follow
it is counted from the daemon's log (tools/ask_stats.py; "brief …: waits for …").
Expected (2026-11-27, opus = claude-opus-5-5 at its default effort, the SDK's 2.1.300; 2 runs), the same with both
paragraphs: several decisions at once — a card, 6 of 6 (the list with ticks, two decisions as two questions); one
decision — a card, 4 of 4; a report, a photo, an offer — the text, 6 of 6. A sentence about several decisions only
("more than one — ask with AskUserQuestion", three wordings) kept the first and the third and moved one decision to
the text, 14 of 14 — which is why the sentence speaks of any decision.
"""
import argparse, asyncio, json, shlex, sys, tempfile, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
import pult_hook  # noqa: E402
from claude_agent_sdk import (AssistantMessage, ClaudeAgentOptions, ClaudeSDKClient, PermissionResultDeny,  # noqa: E402
                              ResultMessage, TextBlock, ToolUseBlock)

FRAME = ("Проба: представь, что ты работаешь в сессии владельца и только что закончил ход. Ниже — что ты сделал и что "
         "знаешь. Заверши ход так, как завершил бы его в настоящей сессии: напиши владельцу итог. Ничего больше делать "
         "не нужно.\n\nСитуация: ")
# several decisions at once: one tap under the text can't answer them — a card
CARD = {
    "two": "Миграция таблицы заказов написана, проверки зелёные, на проде она не запускалась. Без владельца не решить "
           "два вопроса: запускать ли миграцию на проде сейчас и удалять ли старую таблицу после неё. Ты советуешь "
           "запускать, а таблицу пока оставить.",
    "list": "Ты разобрал сбой: сайт не открывался из-за лимита соединений, ты включил HTTP/2, сайт открылся. Что ещё "
            "можно сделать для надёжности — каждое по слову владельца и в любом сочетании: поднять порог ограничителя "
            "запросов (5 минут, без риска); поставить на компьютер сторожа, который раз в 10 минут проверяет связь; "
            "пустить трафик через туннель (минус: при сломанном туннеле не обновить подписку); купить второй адрес для "
            "сайтов (деньги и большая переделка). Ты советуешь первые два.",
    "mixed": "Выпуск 0.9.17 собран, проверки зелёные. От владельца нужно два решения: выпускать ли на GitHub сейчас и "
             "какой кэш оставить в выпуске — А (в памяти, быстрее) или Б (SQLite, переживает перезапуск). Ты советуешь "
             "выпускать с вариантом А.",
}
# one decision: a card, as a fresh session asks it with the old paragraph too — the sentence must not move it to the text
ONE = {
    "yesno": "Ты поправил README и записал правку в журнал; в git ничего не закоммичено. От владельца нужно одно: "
             "закоммитить и отправить или нет.",
    "ab": "Ты сделал два варианта кэша списка проектов: А — в памяти, Б — в SQLite. А быстрее, Б переживает перезапуск. "
          "Какой оставить, решает владелец; ты советуешь А.",
}
# nothing to decide, an answer only a photo can give, an offer the owner may ignore: the text — a card would hold the turn
TEXT = {
    "report": "Выпуск 0.9.16 выложен на GitHub, проверки зелёные на трёх системах. От владельца ничего не нужно.",
    "photo": "Ты проверяешь посадку датчика. Чтобы продолжить, нужно фото микросхемы через окно стакана: по нему ты "
             "скажешь, сдвигать ли плату. Сфотографировать может только владелец.",
    "offer": "Ты поправил опечатку в README и закоммитил правку, задача закрыта. Попутно заметил в соседнем файле "
             "устаревший комментарий: можешь поправить и его, если владелец захочет, но это необязательно и ничего не "
             "держит.",
}
ALL = {**CARD, **ONE, **TEXT}
# the paragraph before the sentence: 0.18.70's, word for word
BEFORE = ("The owner often answers your questions from the phone. In AskUserQuestion, when the options are not "
          "mutually exclusive (steps to take, places to deploy to, things to include), set multiSelect: true and make "
          "each option one action, instead of options that combine them (\"A and B\", \"only A\"). Make each option "
          "an answer they can tap as it is; when a natural answer is \"yes, but…\" (later, in a new session, after a "
          "check), offer it as an option of its own. When the answer needs their own words, a file or what only they "
          "can see, ask in plain text instead.")
PARAGRAPH = {"before": pult_hook.FILES_NOTE + " " + BEFORE, "after": pult_hook.CONTEXT}
TIMEOUT = 300
T0 = time.time()


def say(*a):
    print("%5.0f" % (time.time() - T0), *a, flush=True)


async def deny(tool, inp, ctx):
    return PermissionResultDeny(message="Probe: stop here.", interrupt=True)


async def end(tmp, cond, prompt, a):
    """One session: the probe's hook gives the paragraph, Claude ends the turn → (its AskUserQuestion input or None,
    the text it wrote)."""
    hook = "%s %s %s" % (shlex.quote(sys.executable), shlex.quote(str(tmp / "hook.py")), shlex.quote(str(tmp / (cond + ".txt"))))
    kw = dict(cwd=str(tmp), model=a.model, tools=["AskUserQuestion"], permission_mode="default", can_use_tool=deny,
              setting_sources=[], max_turns=2, env={"PULT_OFF": "1"}, stderr=lambda s: None,
              settings=json.dumps({"hooks": {"SessionStart": [{"hooks": [{"type": "command", "command": hook}]}]}}),
              extra_args={"no-session-persistence": None})
    if a.effort:
        kw["effort"] = a.effort
    text = []
    async with ClaudeSDKClient(options=ClaudeAgentOptions(**kw)) as c:
        await c.query(FRAME + prompt)
        async for m in c.receive_messages():
            if isinstance(m, AssistantMessage):
                for b in m.content:
                    if isinstance(b, TextBlock):
                        text.append(b.text)
                    if isinstance(b, ToolUseBlock) and b.name == "AskUserQuestion":
                        return b.input, "\n".join(text)
            if isinstance(m, ResultMessage):
                return None, "\n".join(text)


def verdict(name, inp):
    """→ (verdict, a line about the question): a card or the text; a card where the text is wanted — needless."""
    qs = (inp or {}).get("questions") or []
    line = " || ".join("%s%s: %s" % ("[ticks] " if q.get("multiSelect") else "", q.get("question", ""),
                                      " | ".join(o.get("label", "") for o in q.get("options") or [])) for q in qs)
    return ("card (needless)" if name in TEXT else "card") if inp else "text", line


async def main():
    p = argparse.ArgumentParser()
    p.add_argument("--model", default="opus")
    p.add_argument("--effort", default=None)
    p.add_argument("--runs", type=int, default=2)
    p.add_argument("--par", type=int, default=2)
    p.add_argument("--only", choices=list(PARAGRAPH))
    p.add_argument("--cases", help="a comma-separated subset of: " + ", ".join(ALL))
    a = p.parse_args()
    cases = a.cases.split(",") if a.cases else list(ALL)
    tmp = Path(tempfile.mkdtemp(prefix="pult-askcard-"))
    (tmp / "hook.py").write_text("import json, sys\nprint(json.dumps({'hookSpecificOutput': {'hookEventName': "
                                 "'SessionStart', 'additionalContext': open(sys.argv[1], encoding='utf-8').read()}}))\n")
    for cond, text in PARAGRAPH.items():
        (tmp / (cond + ".txt")).write_text(text, encoding="utf-8")
    conds = [a.only] if a.only else list(PARAGRAPH)
    jobs = [(cond, name, k) for cond in conds for name in cases for k in range(a.runs)]
    say("model %s, effort %s; %d sessions, %d at a time; %s" % (a.model, a.effort or "default", len(jobs), a.par, tmp))
    gate = asyncio.Semaphore(a.par)
    out = []

    async def one(cond, name, k):
        async with gate:
            t = time.time()
            try:
                inp, text = await asyncio.wait_for(end(tmp, cond, ALL[name], a), TIMEOUT)
            except Exception as e:
                inp, text = None, ""
                say("%s %s #%d: %r" % (cond, name, k + 1, e))
            v, line = verdict(name, inp)
            out.append({"cond": cond, "case": name, "run": k + 1, "verdict": v,
                        "s": round(time.time() - t), "input": inp, "text": text})
            say("%-6s %-6s #%d %-15s %s" % (cond, name, k + 1, v, (line or " ".join(text.split())[-160:])[:400]))

    await asyncio.gather(*(one(*j) for j in jobs))
    (tmp / "results.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print()
    for cond in PARAGRAPH:
        for title, group in (("several decisions at once:", CARD), ("one decision:", ONE), ("a report, a photo, an offer:", TEXT)):
            got = [r["verdict"] for r in out if r["cond"] == cond and r["case"] in group]
            if got:
                print("%-6s %-28s %s" % (cond, title, ", ".join("%s %d" % (v, got.count(v)) for v in sorted(set(got)))))
    print("\nwhat Claude asked and wrote:", tmp / "results.json")


if __name__ == "__main__":
    asyncio.run(main())
