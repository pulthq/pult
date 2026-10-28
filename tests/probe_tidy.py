"""Probe: what the small model offers to merge in a project's tags (stage T, T2, pult_tags.tidy) — on the owner's
subscription, haiku: a list with plain duplicates (two names of one thing, a section twice), a tidy one, one of close
but different topics, the same duplicates kept apart by the owner, an English one. Prints each answer as the model gave
it and as the app would show it (tidy_pairs), the time and the tokens. Spends a little of the subscription; touches
nothing of Pult.
  ~/.local/share/pult/venv/bin/python tests/probe_tidy.py [en]"""
import asyncio, sys, tempfile, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
import pult_tags as G  # noqa: E402

LANG = sys.argv[1] if len(sys.argv) > 1 else "ru"


def vocab(d):
    """{section: {topic: tasks}} → the list and its uses, as the daemon has them."""
    v = [{"n": s, "c": i, "topics": [{"n": t} for t in ts]} for i, (s, ts) in enumerate(d.items())]
    uses = {}
    for s, ts in d.items():
        uses[(s, None)] = sum(ts.values()) or 1
        uses.update({(s, t): n for t, n in ts.items()})
    return v, uses


DUPES = {"Прошивка": {"Калибровка": 3, "Обновление по воздуху": 2, "OTA": 1}, "Корпус": {"Прочность": 2, "Закупки": 1},
         "Электроника": {"Питание": 2, "Охлаждение": 1, "Драйверы моторов": 2}, "Экструдер": {"Датчики": 3, "Сенсоры": 1, "Сопла": 1},
         "Документы": {"Сборка": 2}, "Документация": {"Инструкция": 1}}
TIDY = {"Голос": {"Распознавание": 4, "Порог тишины": 1}, "Выпуск": {"GitHub": 3, "Заметки": 1},
        "Приложение": {"Скрепка": 2, "Галочки": 2, "Теги": 3}, "Сервер": {"Обновлятель": 2, "Секрет": 1}}
CLOSE = {"Маркетинг": {"Выставка": 2, "Реклама": 2, "Покупатели": 3, "Отзывы": 1, "Цены": 1},
         "Корпус": {"Рама": 2, "Крепления": 2, "Корпус дисплея": 1}}
EN = {"Firmware": {"Levelling": 3, "Over-the-air updates": 2, "OTA": 1}, "Docs": {"Assembly": 2}, "Documentation": {"Manual": 1},
      "Electronics": {"Power": 2, "Cooling": 1}}
CASES = [("plain duplicates", "Принтер", DUPES, ()),
         ("a tidy list", "Пульт", TIDY, ()),
         ("close, not the same", "Магазин", CLOSE, ()),
         ("duplicates kept apart", "Принтер", DUPES, ({("Экструдер", "Датчики"), ("Экструдер", "Сенсоры")},
                                                      {("Документы", None), ("Документация", None)})),
         ("in English", "Printer", EN, ())]


async def main():
    from claude_agent_sdk import ResultMessage, query
    cwd = Path(tempfile.mkdtemp(prefix="pult-probe-tidy-"))
    for name, project, d, kept in CASES:
        v, uses = vocab(d)
        kept = {frozenset(p) for p in kept}
        t0, res = time.monotonic(), None
        async for m in query(prompt=G.tidy_request(project, v, uses, kept), options=G.options(LANG, cwd, G.TIDY_SYSTEM, G.TIDY_SCHEMA)):
            if isinstance(m, ResultMessage):
                res = m
        u = getattr(res, "usage", None) or {}
        raw = getattr(res, "structured_output", None)
        print("%-22s %4.1f s  in %s (cache %s) out %s" % (name, time.monotonic() - t0, u.get("input_tokens"),
                                                         u.get("cache_read_input_tokens"), u.get("output_tokens")))
        print("    the model:", raw)
        print("    the app shows:", G.tidy_pairs(raw, v, kept))


asyncio.run(main())
