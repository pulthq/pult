"""Probe: what the small model makes of a task's tags (stage T, pult_tags) — on the owner's subscription, haiku, a few
made-up tasks: a maker of 3D printers (modules in folders) with an empty list and with one, a project tagged by
meaning, the owner's own hashtag, and the result line's call asking for the tags too (pult_brief). Prints each answer,
the time and the tokens. Spends a little of the subscription; touches nothing of Pult.
  ~/.local/share/pult/venv/bin/python tests/probe_tags.py [en]"""
import asyncio, sys, tempfile, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
import pult_brief as B  # noqa: E402
import pult_tags as G  # noqa: E402

LANG = sys.argv[1] if len(sys.argv) > 1 else "ru"
PRINTER = ["docs", "electronics", "extruder", "firmware", "frame", "marketing", "slicer"]
PULT = ["docs", "media", "publish", "relay", "src", "tests", "tools"]
P_VOCAB = [{"n": "Прошивка", "c": 0, "topics": [{"n": "Калибровка"}, {"n": "Wi-Fi"}]},
           {"n": "Корпус", "c": 1, "topics": [{"n": "Прочность"}]},
           {"n": "Электроника", "c": 2, "topics": [{"n": "Питание"}]},
           {"n": "Маркетинг", "c": 3, "topics": [{"n": "Выставка"}]}]
M_VOCAB = [{"n": "Голос", "c": 0, "topics": [{"n": "Распознавание"}]},
           {"n": "Выпуск", "c": 1, "topics": [{"n": "GitHub"}]},
           {"n": "Приложение", "c": 2, "topics": [{"n": "Скрепка"}, {"n": "Галочки"}]}]
CASES = [
    ("printer, empty list", dict(project="Принтер", vocab=[], dirs=PRINTER, paths=["firmware/runout.c", "firmware/pins.h"],
                                 prompt="Добавь датчик конца филамента: пауза печати и сообщение на экране")),
    ("printer, its list", dict(project="Принтер", vocab=P_VOCAB, paths=["firmware/stepper.c", "electronics/driver.kicad_sch"],
                               prompt="Почему слой съезжает на третьем часу печати? Посмотри драйверы моторов")),
    ("by meaning, empty list", dict(project="Пульт", vocab=[], dirs=PULT, paths=["src/pult_stt.py", "relay/web/static/app.js"],
                                    prompt="Микрофон в приложении съедает первый слог: подними порог тишины перед Whisper")),
    ("by meaning, its list", dict(project="Пульт", vocab=M_VOCAB, paths=["CHANGELOG.md", "publish/build.py"],
                                  prompt="Выложи новый выпуск на GitHub, Actions на трёх системах")),
    ("the owner's hashtag", dict(project="Принтер", vocab=P_VOCAB, own="датчики", paths=[],
                                 prompt="#датчики проверь, что датчик двери тоже ставит печать на паузу")),
    ("a long task, «done»", dict(project="Пульт", vocab=M_VOCAB, title="Механизм тегирования задач проекта", paths=[],
                                prompt="поставил", reply="Т1 готов: теги задач, фильтр и лист правки")),
    ("a wrong first guess", dict(project="Пульт", vocab=M_VOCAB + [{"n": "Развёртывание", "c": 3, "topics": [{"n": "Установка"}]}],
                                 title="Механизм тегирования задач проекта", cur={"sec": "Развёртывание", "topic": "Установка"},
                                 prompt="поставил", reply="0.17.1: модели видно название задачи", paths=["src/pult_tags.py"])),
    ("fitting tags stay", dict(project="Пульт", vocab=M_VOCAB, title="Выпуск v0.17 на GitHub", cur={"sec": "Выпуск", "topic": "GitHub"},
                               prompt="проверь Actions ещё раз", reply="Actions зелёные на трёх системах", paths=[".github/workflows/ci.yml"])),
]


async def ask(text, cwd):
    from claude_agent_sdk import ResultMessage, query
    t0, res = time.monotonic(), None
    async for m in query(prompt=text, options=G.options(LANG, cwd)):
        if isinstance(m, ResultMessage):
            res = m
    return time.monotonic() - t0, res


async def main():
    cwd = Path(tempfile.mkdtemp(prefix="pult-probe-tags-"))
    for name, c in CASES:
        secs, res = await ask(G.request(**c), cwd)
        u = getattr(res, "usage", None) or {}
        print("%-24s %4.1f s  in %s (cache %s) out %s  →  %s" % (
            name, secs, u.get("input_tokens"), u.get("cache_read_input_tokens"), u.get("output_tokens"),
            G.parse(getattr(res, "structured_output", None))))
    # the result line's call, asking for the tags too: the line and "needs you" must stay as good
    ctx = {"project": "Принтер", "vocab": P_VOCAB, "paths": ["electronics/driver.kicad_sch"], "cur": None, "dirs": []}
    t0 = time.monotonic()
    b = await B.brief("Почему слой съезжает? Посмотри драйверы", "Причина — перегрев драйвера оси X. Есть два способа: "
                      "снизить ток мотора или поставить радиатор. Какой выбираешь?", [], LANG, cwd, tags=ctx)
    print("%-24s %4.1f s  →  %s" % ("the result line + tags", time.monotonic() - t0, b))


asyncio.run(main())
