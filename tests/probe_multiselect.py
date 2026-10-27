"""Probe: does Pult's sentence about several answers (pult_hook.ASK_NOTE, in the SessionStart paragraph) make Claude
ask with multiSelect where the options can be combined, instead of gluing combinations into options ("only A" /
"A and B"), and keep one choice where only one answer makes sense? The same situations with Pult's paragraph
without the sentence (as before 0.18.3) and with it.

Run (uses some of the subscription: 9 situations × 2 paragraphs × --runs sessions of --model; 3 at a time, ~300 MB
each; opus with 2 runs — ~8 min):
  ~/.local/share/pult/venv/bin/python tests/probe_multiselect.py [--model opus] [--effort high] [--runs 2]
      [--only before|after] [--cases release,rules,…]
Claude's question is caught as its tool call and the session is closed there: nothing is answered, nothing runs, no
transcript is kept. User settings are not loaded (setting_sources=[]), so the real Pult hook doesn't run; the probe's
own hook gives the paragraph the way Pult's does. The questions as asked — in results.json, its path is printed;
`--rescore results.json` counts a saved run again by the rules below.
Expected (2026-10-26, opus = claude-opus-5-5 at its default effort, the SDK's 2.1.300; 2 runs): where several answers
make sense, without the sentence — glued 5 (one of them arguable: "No, only the measures"), one choice 2, a question
per action 2, ticks 3 of 12 ("Only the server (Recommended) | The server and the release | Nothing yet"); with it —
ticks 12 of 12 ("The server (Recommended) | Release on GitHub"). Where only one makes sense — one choice, 6 of 6 both
ways. An earlier wording of the situations gave the same: glued 4 → 0, ticks 4 → 10 (+2 a question per action).
"""
import argparse, asyncio, json, re, shlex, sys, tempfile, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
import pult_hook  # noqa: E402
from claude_agent_sdk import (AssistantMessage, ClaudeAgentOptions, ClaudeSDKClient, PermissionResultDeny,  # noqa: E402
                              ResultMessage, ToolUseBlock)

# where several answers make sense (one action per option, multiSelect) — and where only one does. Claude glues
# combinations mostly when it has advice of its own (the owner's real questions, 2026-10: "only the server
# (Recommended) / the server and the release / nothing yet"): the first four carry advice, taken from those questions;
# with no advice (the next two) Claude mostly ticks even without the sentence
SEVERAL = {
    "release": "Этап готов: Пульт 0.18.3 закоммичен, проверки зелёные. Выкладка у владельца — два отдельных шага, "
               "каждый по его слову: приложение на сервер (deploy.sh, минута) и выпуск на GitHub (сборка на "
               "проверочной ветке, Actions на трёх системах, минут 20). Ты советуешь пока только сервер, а выпуск — "
               "после того, как владелец посмотрит с телефона. Спроси владельца через AskUserQuestion.",
    "rules": "Чтобы текст в теме Telegram не требовал вопроса «в какую сессию», ты предлагаешь два правила: одна "
             "открытая сессия — текст идёт в неё без вопроса; выбрал сессию раз — тема помнит выбор. Советуешь оба. "
             "Спроси владельца через AskUserQuestion.",
    "queue": "Очередь из трёх ходов сейчас не видна. Можно: показывать очередь в сессии и на «Главной»; добавить кнопку "
             "«Начать сейчас», чтобы запустить ход сверх лимита; поднять лимит одновременных ходов с 3 до 4 (нагрузка "
             "на Мак выше). Ты советуешь показывать очередь и кнопку, лимит не трогать. Спроси владельца через "
             "AskUserQuestion.",
    "camera": "На камере у дорожки ложные тревоги: колода у стены распознаётся как человек. Можно: маска на колоду в "
              "Frigate (без перезапуска); убрать с дорожки колоду, стойку и тряпку руками; обрезать тревожную зону выше "
              "колоды (слепое пятно шире). Ты советуешь маску сейчас. Спроси владельца через AskUserQuestion.",
    "swap": "На сервере тревога: swap занят на 1,9 ГБ из 2. Что выяснил: ночной бэкап раздувает кэш страниц, "
            "swappiness = 60, swap лежит на SD-карте, хотя есть свободный NVMe, порог тревоги — 1 ГБ. Без владельца "
            "ничего на сервере не меняй. Спроси владельца через AskUserQuestion, что делаем.",
    "bot": "Обновление бота до 0.22.2 скачано и готово к установке. Попутно заметил три вещи: у службы бота нет "
           "ограничения памяти MemoryMax; голосовые ответы выключены, хотя владелец о них спрашивал; один из скиллов "
           "куратор убрал в архив. Спроси владельца через AskUserQuestion, как быть.",
}
ONE = {
    "license": "Репозиторий скоро станет публичным, ему нужна лицензия. Ты рассматриваешь MIT, Apache-2.0 или решить "
               "позже. Спроси владельца через AskUserQuestion.",
    "when": "Обновление сервера даст 10 минут простоя. Сейчас на сервере идёт расчёт, он закончится примерно через "
            "2 часа; ночью сервер свободен. Спроси владельца через AskUserQuestion, когда обновлять.",
    "version": "Бота можно обновить до 0.22.2 (новейшая, но в ней фоновые правки могут переписывать любые скиллы) или "
               "до 0.21.7 (последняя проверенная). Спроси владельца через AskUserQuestion, на какую версию обновлять.",
}
PARAGRAPH = {"before": pult_hook.FILES_NOTE, "after": pult_hook.CONTEXT}
# an option that glues actions together: "A + B", "только A", "оба", "то же + B" (tools/ask_stats.py — the same rule)
GLUE = re.compile(r"\+|\b(только|оба|обе|ещё и|то же|only|both|as well)\b", re.I)
TIMEOUT = 300
T0 = time.time()


def say(*a):
    print("%5.0f" % (time.time() - T0), *a, flush=True)


async def deny(tool, inp, ctx):
    return PermissionResultDeny(message="Probe: stop here.", interrupt=True)


async def ask(tmp, cond, prompt, a):
    """One session: the probe's hook gives the paragraph, Claude asks; its AskUserQuestion input, or None."""
    hook = "%s %s %s" % (shlex.quote(sys.executable), shlex.quote(str(tmp / "hook.py")), shlex.quote(str(tmp / (cond + ".txt"))))
    kw = dict(cwd=str(tmp), model=a.model, tools=["AskUserQuestion"], permission_mode="default", can_use_tool=deny,
              setting_sources=[], max_turns=2, env={"PULT_OFF": "1"}, stderr=lambda s: None,
              settings=json.dumps({"hooks": {"SessionStart": [{"hooks": [{"type": "command", "command": hook}]}]}}),
              extra_args={"no-session-persistence": None})
    if a.effort:
        kw["effort"] = a.effort
    async with ClaudeSDKClient(options=ClaudeAgentOptions(**kw)) as c:
        await c.query(prompt)
        async for m in c.receive_messages():
            if isinstance(m, AssistantMessage):
                for b in m.content:
                    if isinstance(b, ToolUseBlock) and b.name == "AskUserQuestion":
                        return b.input
            if isinstance(m, ResultMessage):
                return None


def verdict(several, inp):
    """several — the situation calls for several answers. → (verdict, a line about the question)."""
    if not inp:
        return "no question", ""
    qs = inp.get("questions") or []
    multi = [q for q in qs if q.get("multiSelect")]
    # glue counts with ticks too: "Both rules (Recommended) | Rule A | Rule B" under multiSelect is the same habit
    glued = [o.get("label", "") for q in qs for o in q.get("options") or [] if GLUE.search(o.get("label", ""))]
    line = " || ".join("%s%s: %s" % ("[ticks] " if q.get("multiSelect") else "", q.get("question", ""),
                                      " | ".join(o.get("label", "") for o in q.get("options") or [])) for q in qs)
    if several:
        v = "ticks" if multi and not glued else "glued" if glued else "one per question" if len(qs) > 1 else "one choice"
    else:
        v = "ticks (needless)" if multi else "one choice"
    return v, line


async def main():
    p = argparse.ArgumentParser()
    p.add_argument("--model", default="opus")
    p.add_argument("--effort", default=None)
    p.add_argument("--runs", type=int, default=2)
    p.add_argument("--only", choices=list(PARAGRAPH))
    p.add_argument("--cases", help="a comma-separated subset of: " + ", ".join(list(SEVERAL) + list(ONE)))
    a = p.parse_args()
    cases = a.cases.split(",") if a.cases else list(SEVERAL) + list(ONE)
    tmp = Path(tempfile.mkdtemp(prefix="pult-multi-"))
    (tmp / "hook.py").write_text("import json, sys\nprint(json.dumps({'hookSpecificOutput': {'hookEventName': "
                                 "'SessionStart', 'additionalContext': open(sys.argv[1], encoding='utf-8').read()}}))\n")
    for cond, text in PARAGRAPH.items():
        (tmp / (cond + ".txt")).write_text(text, encoding="utf-8")
    conds = [a.only] if a.only else list(PARAGRAPH)
    jobs = [(cond, name, k) for cond in conds for name in cases for k in range(a.runs)]
    say("model %s, effort %s; %d sessions, 3 at a time; %s" % (a.model, a.effort or "default", len(jobs), tmp))
    gate = asyncio.Semaphore(3)
    out = []

    async def one(cond, name, k):
        async with gate:
            t = time.time()
            try:
                inp = await asyncio.wait_for(ask(tmp, cond, (SEVERAL.get(name) or ONE[name]), a), TIMEOUT)
            except Exception as e:
                inp = None
                say("%s %s #%d: %r" % (cond, name, k + 1, e))
            v, line = verdict(name in SEVERAL, inp)
            out.append({"cond": cond, "case": name, "run": k + 1, "several": name in SEVERAL, "verdict": v,
                        "s": round(time.time() - t), "input": inp})
            say("%-6s %-8s #%d %-17s %s" % (cond, name, k + 1, v, line[:400]))

    await asyncio.gather(*(one(*j) for j in jobs))
    (tmp / "results.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    summary(out)
    print("\nquestions as asked:", tmp / "results.json")


def summary(out):
    print()
    for cond in PARAGRAPH:
        rows = [r for r in out if r["cond"] == cond]
        for several in (True, False):
            got = [r["verdict"] for r in rows if r["several"] == several]
            if got:
                print("%-6s %-22s %s" % (cond, "several make sense:" if several else "only one makes sense:",
                                         ", ".join("%s %d" % (v, got.count(v)) for v in sorted(set(got)))))


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--rescore":       # a saved run, by today's rules: --rescore results.json
        rows = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))
        for r in rows:
            r["verdict"] = verdict(r["several"], r["input"])[0]
        summary(rows)
    else:
        asyncio.run(main())
