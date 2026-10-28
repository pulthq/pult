"""Probe: do the owner's examples steer the small model (stage T, T2, the last step)? On the owner's subscription,
haiku: a made-up printer project whose list has "Sensors" in two sections; the owner's three examples put sensor tasks
under Electronics. Each new task is tagged without the examples and with them — prints both, the time and the tokens.
Spends a little of the subscription; touches nothing of Pult.
  ~/.local/share/pult/venv/bin/python tests/probe_examples.py [en]"""
import asyncio, sys, tempfile, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
import pult_tags as G  # noqa: E402

LANG = sys.argv[1] if len(sys.argv) > 1 else "ru"
VOCAB = [{"n": "Прошивка", "c": 0, "topics": [{"n": "Калибровка"}, {"n": "Обновление по сети"}]},
         {"n": "Электроника", "c": 1, "topics": [{"n": "Питание"}, {"n": "Драйверы"}, {"n": "Датчики"}]},
         {"n": "Экструдер", "c": 2, "topics": [{"n": "Сопла"}, {"n": "Подача"}, {"n": "Датчики"}]},
         {"n": "Корпус", "c": 3, "topics": [{"n": "Прочность"}, {"n": "Крепления"}]}]
EXAMPLES = [{"title": "Датчик конца филамента срабатывает зря", "ask": "", "sec": "Электроника", "topic": "Датчики"},
            {"title": "Датчик двери ставит паузу", "ask": "", "sec": "Электроника", "topic": "Датчики"},
            {"title": "Датчик температуры стола врёт на 5 градусов", "ask": "", "sec": "Электроника", "topic": "Датчики"}]
TASKS = ["Добавь датчик засора сопла: пауза, если пластик не идёт",
         "Датчик подачи филамента: считать, сколько ушло на печать",
         "Профиль PETG для слайсера: обдув и температура"]


async def ask(text, cwd):
    from claude_agent_sdk import ResultMessage, query
    t0, res = time.monotonic(), None
    async for m in query(prompt=text, options=G.options(LANG, cwd)):
        if isinstance(m, ResultMessage):
            res = m
    u = getattr(res, "usage", None) or {}
    return time.monotonic() - t0, u, G.parse(getattr(res, "structured_output", None))


async def main():
    cwd = Path(tempfile.mkdtemp(prefix="pult-probe-examples-"))
    tag = lambda g: (g["sec"] + (" / " + g["topic"] if g.get("topic") else "")) if g else "—"
    print("%-58s %-26s %s" % ("task", "without examples", "with the owner's three"))
    for task in TASKS:
        row = []
        for ex in ((), EXAMPLES):
            secs, u, got = await ask(G.request("Принтер", VOCAB, prompt=task, title=task, examples=ex), cwd)
            row.append("%s (%.1f s, out %s)" % (tag(got), secs, u.get("output_tokens")))
        print("%-58s %-26s %s" % (G.clip(task, 57), row[0], row[1]))


asyncio.run(main())
