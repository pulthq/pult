"""Pult: user-facing strings in English and Russian.

One key — both languages side by side, so a translation is never forgotten. `T(key, lang, **kw)` formats with
str.format. English is the fallback for a missing key or language. Telegram HTML is allowed in values; values
must stay valid HTML after formatting (callers escape what they substitute).
"""

LANGS = ("en", "ru")

S = {
    # ----- notification modes -----
    "mode.auto": {"en": "🔄 Auto", "ru": "🔄 Авто"},
    "mode.mac": {"en": "💻 At my computer", "ru": "💻 За компьютером"},
    "mode.phone": {"en": "📱 On my phone", "ru": "📱 С телефоном"},
    "mode.auto.btn": {"en": "🔄 Auto", "ru": "🔄 Авто"},          # short: three fit in one row of chat buttons
    "mode.mac.btn": {"en": "💻 Computer", "ru": "💻 Компьютер"},
    "mode.phone.btn": {"en": "📱 Phone", "ru": "📱 Телефон"},
    "mode.auto.about": {
        "en": "Sound only when you've been away from the computer for 2+ minutes or the session was started from Telegram.",
        "ru": "Со звуком — только если ты отошёл от компьютера больше чем на 2 минуты или сессия запущена из Telegram.",
    },
    # the same modes when Telegram is a pager (stage V): only "your move" comes, and only where you are
    "mode.auto.pager": {
        "en": "Pult calls you where you are: in the app — in the app; at the computer — not at all; away (the screen locked "
              "or 5 minutes without the keyboard) — in Telegram, with sound.",
        "ru": "Пульт зовёт туда, где ты: в приложении — в приложении; за компьютером — никак; отошёл (экран заблокирован "
              "или 5 минут без клавиатуры) — в Telegram, со звуком.",
    },
    "mode.mac.pager": {"en": "Telegram stays quiet: what waits for you is in the app and on the computer.",
                       "ru": "Telegram молчит: всё, что ждёт тебя, — в приложении и на компьютере."},
    "mode.phone.pager": {"en": "Everything that waits for you comes to Telegram with sound, wherever you are.",
                         "ru": "Всё, что ждёт тебя, приходит в Telegram со звуком, где бы ты ни был."},
    "mode.mac.about": {
        "en": "Everything arrives silently — you're at the computer. Nothing is lost: every message is still posted.",
        "ru": "Всё приходит беззвучно — ты за компьютером. Ничего не теряется: сообщения приходят как обычно.",
    },
    "mode.phone.about": {
        "en": "Results, questions, permission requests and long-turn reminders arrive with sound.",
        "ru": "Итоги, вопросы, разрешения и напоминания о долгих ходах — со звуком.",
    },
    "mode.set": {"en": "Notifications: {mode}", "ru": "Уведомления: {mode}"},
    "panel": {
        "en": "🎛 <b>Pult</b> · notifications: <b>{mode}</b>\n{about}",
        "ru": "🎛 <b>Пульт</b> · уведомления: <b>{mode}</b>\n{about}",
    },
    "panel.app": {
        "en": "\n\nThe app: every session on the computer, full transcripts, Claude's questions, new tasks, usage.",
        "ru": "\n\nПриложение: все сессии на компьютере, переписка целиком, вопросы Claude, новые задачи, расход.",
    },
    "panel.open": {"en": "Open Pult", "ru": "Открыть Пульт"},
    "card.app": {"en": "📱 Pult", "ru": "📱 Пульт"},       # the button of a project topic's pinned card
    "card.focus": {"en": "🎯 Now: {name}", "ru": "🎯 Сейчас: {name}"},   # the topic's current session, under the status
    "focus.first": {"en": "→ {name}. Text in this topic goes there from now on; to switch — reply to another "
                          "session's message, or <code>/new text</code>.",
                    "ru": "→ {name}. Текст в этой теме дальше идёт туда же; сменить — ответ на сообщение другой "
                          "сессии или <code>/new текст</code>."},
    "menu.app": {"en": "Pult", "ru": "Пульт"},            # the app button next to the message field, private chat

    # ----- help -----
    "help": {
        "en": "<b>Pult</b> — Claude Code on your computer, from Telegram.\n\n"
              "• Every project gets its own topic. Sessions from VS Code and the terminal show up by themselves: "
              "what Claude is doing right now, and the result.\n"
              "• Claude's questions and permission requests — answer with buttons, here or on the computer, whoever is first.\n"
              "• Text in a project topic goes to the topic's current session; a reply to a session's message — to that "
              "session; <code>/new text</code> — a new session.\n\n"
              "/new · /stop · /status — what's open on the computer · /projects · /mode — notifications · /app · "
              "/feedback — a bug or an idea\n\nPick a topic:",
        "ru": "<b>Пульт</b> — Claude Code на твоём компьютере, из Telegram.\n\n"
              "• У каждого проекта — своя тема. Сессии из VS Code и терминала появляются сами: что Claude делает "
              "сейчас и итог.\n"
              "• На вопросы и разрешения Claude — кнопками, здесь или на компьютере, кто первый.\n"
              "• Текст в теме проекта идёт в её текущую сессию; ответ на сообщение сессии — в ту сессию; "
              "<code>/new текст</code> — новая сессия.\n\n"
              "/new · /stop · /status — что открыто на компьютере · /projects · /mode — уведомления · /app · "
              "/feedback — ошибка или идея\n\nВыбери раздел:",
    },
    "help.btn.start": {"en": "🚀 Getting started", "ru": "🚀 С чего начать"},
    "help.btn.notify": {"en": "🔔 Notifications", "ru": "🔔 Уведомления"},
    "help.btn.write": {"en": "✍️ Writing to Claude", "ru": "✍️ Писать Claude"},
    "help.btn.app": {"en": "📱 The app", "ru": "📱 Приложение"},
    "help.btn.onoff": {"en": "⏻ Turn on and off", "ru": "⏻ Включить и выключить"},
    "help.btn.trouble": {"en": "🛠 Troubleshooting", "ru": "🛠 Если что-то не так"},
    "help.btn.back": {"en": "◀️ Help", "ru": "◀️ Помощь"},
    "help.start": {
        "en": "<b>🚀 Getting started</b>\n\n"
              "1. Work on the computer as usual — in VS Code or the terminal. Sessions appear in the topics by themselves.\n"
              "2. A turn is one message that keeps updating: how long it has been running and what Claude is doing. "
              "The result comes as a separate message.\n"
              "3. ✋ A permission request or ❓ a question from Claude — answer with buttons. The dialog on the computer is "
              "open at the same time; whoever answers first decides.\n"
              "4. A new task — <code>/new text</code> in the project's topic, or write in General and pick the project.\n"
              "5. Leaving the computer — /phone; back — /desk. Or keep 🔄 Auto.",
        "ru": "<b>🚀 С чего начать</b>\n\n"
              "1. Работай на компьютере как обычно — в VS Code или терминале. Сессии появятся в темах сами.\n"
              "2. Ход — одно сообщение, оно обновляется: сколько идёт и что Claude делает сейчас. Итог — отдельным "
              "сообщением.\n"
              "3. ✋ Разрешение или ❓ вопрос Claude — кнопками. Окно на компьютере открыто одновременно: кто ответил "
              "первым, тот и решил.\n"
              "4. Новая задача — <code>/new текст</code> в теме проекта или текст в «Общей» → выбор проекта.\n"
              "5. Уходишь от компьютера — /phone, вернулся — /desk. Или оставь 🔄 Авто.",
    },
    "help.notify": {
        "en": "<b>🔔 Notifications</b>\n\nMessages always arrive — only the sound changes.\n"
              "• 🔄 Auto — with sound if you've been away from the computer for 2+ minutes or the session was started "
              "from here.\n"
              "• 💻 At my computer — everything silent.\n"
              "• 📱 On my phone — results, questions, permission requests and reminders with sound.\n\n"
              "Switch: the buttons in the pinned message in General, /auto /desk /phone, or in the app.\n"
              "Long turns: reminders at 10, 30 and 60 minutes while sound is on; 🔕 — only the result after that. "
              "Reminders can be turned off in the app's settings.",
        "ru": "<b>🔔 Уведомления</b>\n\nСообщения приходят всегда — меняется только звук.\n"
              "• 🔄 Авто — со звуком, если ты отошёл от компьютера больше чем на 2 минуты или сессия запущена отсюда.\n"
              "• 💻 За компьютером — всё беззвучно.\n"
              "• 📱 С телефоном — итоги, вопросы, разрешения и напоминания со звуком.\n\n"
              "Переключить: кнопки в закреплённом сообщении «Общей», /auto /desk /phone или в приложении.\n"
              "Долгий ход: напоминания на 10, 30 и 60 минуте, пока звук включён; 🔕 — дальше только итог. "
              "Выключить напоминания — в настройках приложения.",
    },
    "help.write": {
        "en": "<b>✍️ Writing to Claude</b>\n\n"
              "• Reply to any message of a session — continues that session.\n"
              "• Text in a project topic goes to the topic's current session (🎯 in the pinned card): the one you chose "
              "last — by a reply, a button or <code>/new</code>. None yet — to the only open session, or I'll ask once. "
              "The choice lasts until the session closes or 2 hours of quiet in the topic. "
              "<code>/new text</code> — a new session right away.\n"
              "• 💻 The session is open in a VS Code tab with Pult's wrapper — your message appears right in the tab. "
              "If Claude is busy there, it reads your message mid-turn (the tab doesn't show it) and the turn's result "
              "replies to you. 🖥 Without the wrapper — I continue as a copy: same history, a separate session from "
              "there on.\n"
              "• Asked “which session?” — 💻 a VS Code tab (I write straight into it), 🖥 open on the computer (goes as "
              "a copy), 📱 from Telegram, ▫️ closed (I continue it).\n"
              "• A photo or file with a caption — Claude gets the path to the file.\n"
              "• /stop in a topic interrupts its current session started from here; as a reply — that session.",
        "ru": "<b>✍️ Писать Claude</b>\n\n"
              "• Ответ на любое сообщение сессии — продолжение этой сессии.\n"
              "• Текст в теме проекта идёт в текущую сессию темы (🎯 в закрепе): ту, что ты выбрал последней — ответом, "
              "кнопкой или <code>/new</code>. Её ещё нет — в единственную открытую сессию, иначе спрошу один раз. Выбор "
              "держится, пока сессия не закроется или 2 часа тишины в теме. <code>/new текст</code> — сразу новая.\n"
              "• 💻 Сессия открыта во вкладке VS Code с обёрткой Пульта — сообщение появится прямо во вкладке. "
              "Если Claude там занят, он прочтёт сообщение посреди хода (во вкладке оно не покажется), а итог хода "
              "ответит тебе. 🖥 Без обёртки — продолжу копией: история та же, дальше отдельная сессия.\n"
              "• В вопросе «в какую сессию?»: 💻 — вкладка VS Code (пишу прямо в неё), 🖥 — открыта на компьютере "
              "(пойдёт копией), 📱 — из Telegram, ▫️ — закрыта (продолжу).\n"
              "• Фото или файл с подписью — Claude получит путь к файлу.\n"
              "• /stop в теме — прервать её текущую сессию, запущенную отсюда; ответом — ту сессию.",
    },
    "help.app": {
        "en": "<b>📱 The app</b>\n\nInside Telegram: every session on the computer, full transcripts with times, answers "
              "to Claude's questions, a screenshot for Claude, the context gauge, new tasks, subscription usage, "
              "settings.\n"
              "Open it with the 📱 Pult button pinned at the top of each project topic (it opens that project), the "
              "button in the pinned message in General, /app, or the Pult button next to the message field in your "
              "private chat with the bot.",
        "ru": "<b>📱 Приложение</b>\n\nВнутри Telegram: все сессии на компьютере, переписка целиком со временем, ответы на "
              "вопросы Claude, снимок экрана для Claude, шкала контекста, новая задача, расход подписки, настройки.\n"
              "Открыть — кнопкой «📱 Пульт» в закрепе вверху каждой темы проекта (откроет этот проект), кнопкой в "
              "закреплённом сообщении «Общей», командой /app или кнопкой «Пульт» у строки ввода в личном чате с ботом.",
    },
    "help.app.off": {
        "en": "\n\nNot set up yet: the app needs your own server with a domain — see the README.",
        "ru": "\n\nСейчас не настроено: приложению нужен свой сервер с доменом — инструкция в README.",
    },
    "help.onoff": {
        "en": "<b>⏻ Turn on and off</b> — in a terminal on the computer\n\n"
              "<code>pult status</code> — what is on\n"
              "<code>pult hooks off</code> / <code>on</code> — Pult stops / starts seeing sessions "
              "(then Reload Window in VS Code)\n"
              "<code>pult tab off</code> / <code>on</code> — writing from Telegram into VS Code tabs\n"
              "<code>pult stop</code> / <code>start</code> — stop Pult entirely / start it again\n"
              "<code>pult setup</code> — change the bot, the owner or the group\n"
              "<code>pult uninstall</code> — remove Pult from the computer\n\n"
              "If <code>pult</code> isn't found: <code>~/.local/bin/pult</code>. "
              "Claude sessions keep working as usual without Pult.",
        "ru": "<b>⏻ Включить и выключить</b> — в терминале на компьютере\n\n"
              "<code>pult status</code> — что включено\n"
              "<code>pult hooks off</code> / <code>on</code> — Пульт перестаёт / начинает видеть сессии "
              "(потом Reload Window в VS Code)\n"
              "<code>pult tab off</code> / <code>on</code> — запись из Telegram во вкладки VS Code\n"
              "<code>pult stop</code> / <code>start</code> — остановить Пульт целиком / запустить снова\n"
              "<code>pult setup</code> — сменить бота, владельца или группу\n"
              "<code>pult uninstall</code> — удалить Пульт с компьютера\n\n"
              "Если <code>pult</code> не находится: <code>~/.local/bin/pult</code>. "
              "Сессии Claude без Пульта работают как обычно.",
    },
    "help.trouble": {
        "en": "<b>🛠 Troubleshooting</b>\n\n"
              "• The bot is silent — <code>pult status</code> on the computer: the service, the link to Telegram; "
              "<code>pult restart</code> restarts it.\n"
              "• No sessions from VS Code — hooks are off: <code>pult hooks on</code> and Reload Window.\n"
              "• The feed works but no permission buttons — Claude in auto mode decides by itself; that's normal.\n"
              "• A message didn't reach the tab — the tab was started without the wrapper (Reload Window fixes it) "
              "or Claude Code was just updated: until it's checked, messages go as a copy.\n"
              "• Log: <code>{log}</code>\n\nA bug or an idea — /feedback.",
        "ru": "<b>🛠 Если что-то не так</b>\n\n"
              "• Бот молчит — <code>pult status</code> на компьютере: служба, связь с Telegram; "
              "<code>pult restart</code> перезапустит.\n"
              "• Нет сессий из VS Code — хуки выключены: <code>pult hooks on</code> и Reload Window.\n"
              "• Лента есть, а кнопок разрешений нет — Claude в режиме auto решает сам, это норма.\n"
              "• Сообщение не дошло во вкладку — вкладка запущена без обёртки (поможет Reload Window) или вышло "
              "обновление Claude Code: до проверки — копией.\n"
              "• Журнал: <code>{log}</code>\n\nОшибка или идея — /feedback.",
    },
    "feedback": {
        "en": "Found a bug or have an idea? Open an issue: {url}\nFor a bug, add the output of "
              "<code>pult report</code> (it has no tokens or messages) and roughly when it happened.",
        "ru": "Нашёл ошибку или есть идея? Напиши на GitHub: {url}\nДля ошибки приложи вывод "
              "<code>pult report</code> (в нём нет токенов и переписки) и примерное время, когда это было.",
    },
    "feedback.none": {
        "en": "The GitHub link will appear here once Pult is published.",
        "ru": "Ссылка на GitHub появится здесь, когда Пульт будет опубликован.",
    },

    # ----- rendering (pult_render) -----
    "dur.s": {"en": "{n} s", "ru": "{n} сек"},
    "dur.m": {"en": "{n} min", "ru": "{n} мин"},
    "dur.h": {"en": "{n} h", "ru": "{n} ч"},
    "reset.at": {"en": "at {hm} ({left})", "ru": "в {hm} ({left})"},
    "reset.in": {"en": "in {left}", "ru": "через {left}"},
    "weekdays": {"en": "Mon Tue Wed Thu Fri Sat Sun", "ru": "пн вт ср чт пт сб вс"},
    "and_more": {"en": " and {n} more", "ru": " и ещё {n}"},
    "task.completed": {"en": "⚙️ Background task finished: {what}", "ru": "⚙️ Закончилась фоновая задача {what}"},
    "task.failed": {"en": "⚙️ Background task failed: {what}", "ru": "⚙️ Не удалась фоновая задача {what}"},
    "task.stopped": {"en": "⚙️ Background task stopped: {what}", "ru": "⚙️ Остановлена фоновая задача {what}"},
    "task.many": {"en": "⚙️ Background tasks finished: {list}", "ru": "⚙️ Закончились фоновые задачи: {list}"},
    "task.default": {"en": "task", "ru": "задача"},
    "bg.one": {"en": "⚙️ Still running in the background: {what}", "ru": "⚙️ В фоне ещё идёт: {what}"},
    "bg.many": {"en": "⚙️ Still running in the background ({n}): {list}", "ru": "⚙️ В фоне ещё {n}: {list}"},
    "step.subagent": {"en": "subagent", "ru": "субагент"},
    "step.plan": {"en": "plan", "ru": "план"},
    "step.skill": {"en": "skill", "ru": "навык"},
    "diff.more": {"en": "… {n} more {lines}", "ru": "… ещё {n} {lines}"},
    "perm.bash": {"en": "Run a command{desc}", "ru": "Выполнить команду{desc}"},
    "perm.edit": {"en": "Edit file <code>{path}</code> (+{plus} −{minus})", "ru": "Изменить файл <code>{path}</code> (+{plus} −{minus})"},
    "perm.create": {"en": "Create file <code>{path}</code> ({lines})", "ru": "Создать файл <code>{path}</code> ({lines})"},
    "perm.overwrite": {"en": "Overwrite file <code>{path}</code> ({lines})", "ru": "Перезаписать файл <code>{path}</code> ({lines})"},
    "perm.notebook": {"en": "Edit notebook <code>{path}</code>", "ru": "Изменить блокнот <code>{path}</code>"},
    "perm.fetch": {"en": "Open the page {url}", "ru": "Открыть страницу {url}"},
    "perm.search": {"en": "Search the web: <b>{query}</b>", "ru": "Искать в интернете: <b>{query}</b>"},
    "perm.mcp": {"en": "Call <b>{name}</b>", "ru": "Вызвать <b>{name}</b>"},
    "perm.tool": {"en": "Use the tool <b>{name}</b>", "ru": "Использовать инструмент <b>{name}</b>"},
    "ask.hint.one": {"en": "pick an option, or reply to this message with your own answer",
                     "ru": "выбери вариант кнопкой или напиши свой — ответом на это сообщение"},
    "ask.hint.many": {"en": "check the options and tap “Done”, or reply to this message with your own answer",
                      "ru": "отметь варианты и нажми «Готово» или напиши свой ответ — ответом на это сообщение"},

    # ----- daemon messages (pultd) -----
    "when.yesterday": {"en": "yesterday {hm}", "ru": "вчера {hm}"},
    "session.default": {"en": "session", "ru": "сессия"},
    "err.turn": {"en": "⚠️ The turn ended with an error: {err}", "ru": "⚠️ Ход закончился ошибкой: {err}"},
    "err.session": {"en": "⚠️ The session failed to start or crashed: <code>{err}</code>",
                    "ru": "⚠️ Сессия не запустилась или упала: <code>{err}</code>"},
    "topic.intro": {"en": "📂 <b>{name}</b>\nText here goes to the current session (🎯), a reply — to that message's "
                          "session, <code>/new text</code> — to a new one.",
                    "ru": "📂 <b>{name}</b>\nТекст сюда — в текущую сессию (🎯), ответ на сообщение — в его сессию, "
                          "<code>/new текст</code> — в новую."},
    "long.more": {"en": "\n<i>… {n} more characters</i>", "ru": "\n<i>… ещё {n} знаков</i>"},
    "btn.read_all": {"en": "Read in full", "ru": "Читать полностью"},
    "btn.details": {"en": "Details", "ru": "Подробнее"},
    "doc.caption": {"en": "in full — {n} characters", "ru": "целиком — {n} знаков"},
    "turn.fresh": {"en": "working…", "ru": "работает…"},
    "turn.running": {"en": "working {dur}", "ru": "работает {dur}"},
    "turn.done": {"en": "done in {dur}", "ru": "готово за {dur}"},
    "turn.stopped": {"en": "interrupted after {dur}", "ru": "прервано через {dur}"},
    "turn.failed": {"en": "broke off after {dur}", "ru": "оборвался через {dur}"},
    "queue.state": {"en": "in the queue", "ru": "в очереди"},
    "queue.why": {"en": "Up to {n} tasks from the phone run at once, and all places are taken: this one starts as soon as one ends.",
                  "ru": "С телефона идут не больше {n} задач разом, все места заняты: начну, как только одна закончится."},
    "btn.jump": {"en": "▶️ Start now", "ru": "▶️ Начать сейчас"},
    "turn.you": {"en": "<i>You: {text}</i>", "ru": "<i>Ты: {text}</i>"},
    "att.image": {"en": "📎 picture", "ru": "📎 снимок"},
    "att.file": {"en": "📎 file", "ru": "📎 файл"},
    # ----- voice input (pult_stt: Groq Whisper) -----
    "stt.nokey": {
        "en": "🎤 Voice input is off: add a Groq key in the app (Settings → Voice input) or run pult stt on the computer.",
        "ru": "🎤 Голосовой ввод выключен: задай ключ Groq в приложении («Настройки → Голосовой ввод») или командой "
              "pult stt на компьютере.",
    },
    "stt.empty": {"en": "🎤 I couldn't make out any words.", "ru": "🎤 Не разобрал ни слова."},
    "stt.failed": {"en": "🎤 Couldn't recognize the speech: {err}", "ru": "🎤 Не удалось распознать речь: {err}"},
    "stt.e.big": {"en": "the recording is too big to recognize (up to 20 MB)",
                  "ru": "запись слишком большая для распознавания (до 20 МБ)"},
    "stt.e.key": {"en": "Groq doesn't accept this key", "ru": "Groq не принимает этот ключ"},
    "stt.e.limit": {"en": "Groq's limit is used up for now — try again in a minute",
                    "ru": "лимит Groq на сейчас исчерпан — попробуй через минуту"},
    "stt.e.net": {"en": "no connection to Groq ({why})", "ru": "нет связи с Groq ({why})"},
    "stt.e.format": {"en": "unknown recording format: {kind}", "ru": "неизвестный формат записи: {kind}"},
    "stt.e.groq": {"en": "Groq: {msg}", "ru": "Groq: {msg}"},
    # what Whisper is told before a recording (not shown to people): a sentence in the language spoken, punctuated,
    # with the terms people say to Claude — it copies the spelling and the punctuation style; the owner's own words
    # (Settings → Voice input) go after it. Mind Groq's 896 bytes: a Russian letter takes two (pult_stt.fit)
    "stt.prompt": {
        "en": "This is a voice message to Claude Code about code and a project: commit, deploy, hook, session, tab, "
              "VS Code, Telegram, GitHub, Pult.",
        "ru": "Это голосовое сообщение для Claude Code о коде и проекте. Говорю по-русски, вставляю английские слова: "
              "Claude, VS Code, Telegram, GitHub. Коммит, деплой, хук, сессия, вкладка, Пульт.",
    },
    "stt.prompt.words": {"en": "Also: {words}.", "ru": "Ещё слова: {words}."},
    "vehi": {"en": "⏳ {head} · has been working for {dur}", "ru": "⏳ {head} · работает уже {dur}"},
    "vehi.muted": {"en": "\n<i>🔕 no more reminders — only the result will come</i>",
                   "ru": "\n<i>🔕 вех больше не будет — придёт только итог</i>"},
    "btn.mute": {"en": "🔕 Only the result", "ru": "🔕 Только итог"},
    "bg.closed": {"en": "⚙️ The session was opened on the computer — its background tasks stopped together with Pult's "
                        "process{names}",
                  "ru": "⚙️ Сессию открыли на компьютере — её фоновые задачи остановлены вместе с процессом Пульта{names}"},
    "req.decided_mac": {"en": "decided on the computer", "ru": "решено на компьютере"},
    "req.answered_mac": {"en": "answered on the computer", "ru": "отвечено на компьютере"},
    "req.allowed_mac": {"en": "allowed on the computer", "ru": "разрешено на компьютере"},
    "req.session_closed": {"en": "the session was closed", "ru": "сессия закрыта"},
    "req.asks": {"en": "Claude asks", "ru": "Claude спрашивает"},
    "req.plan": {"en": "Claude proposes a plan", "ru": "Claude предлагает план"},
    "req.perm": {"en": "Claude asks for permission", "ru": "Claude спрашивает разрешение"},
    "plan.full": {"en": "the full plan", "ru": "план целиком"},
    "plan.decided": {"en": "plan · <b>{note}</b>", "ru": "план · <b>{note}</b>"},
    "perm.reply_hint": {"en": "\n<i>a text reply — a refusal with your note for Claude</i>",
                        "ru": "\n<i>ответ текстом — отказ с пояснением для Claude</i>"},
    "btn.approve": {"en": "Approve", "ru": "Утвердить"},
    "btn.reject_plan": {"en": "Don't approve", "ru": "Не утверждать"},
    "btn.allow": {"en": "Allow", "ru": "Разрешить"},
    "btn.deny": {"en": "Deny", "ru": "Отклонить"},
    "btn.always": {"en": "\u267e\ufe0f Always allow", "ru": "\u267e\ufe0f Разрешать всегда"},     # ♾ drawn as an emoji
    "btn.done": {"en": "Done", "ru": "Готово"},
    "btn.new_session": {"en": "▶️ New session", "ru": "▶️ Новая сессия"},
    "btn.fork": {"en": "🔀 Continue as a copy", "ru": "🔀 Продолжить копией"},
    "btn.usage": {"en": "Usage", "ru": "Расход"},
    "where.app": {"en": " from the app", "ru": " из приложения"},     # a decision in Telegram itself says no "where"
    "dec.approved": {"en": "✔️ approved{where}", "ru": "✔️ утверждён{where}"},
    "dec.allowed": {"en": "✔️ allowed{where}", "ru": "✔️ разрешено{where}"},
    "dec.always": {"en": "✔️ allowed, won't ask again", "ru": "✔️ разрешено и больше не спросит"},
    "dec.denied_note": {"en": "declined with a note: {text}", "ru": "отказано с пояснением: {text}"},
    "dec.rejected_plan": {"en": "not approved", "ru": "не утверждён"},
    "dec.denied": {"en": "declined{where}", "ru": "отклонено{where}"},
    "note.decided": {"en": "already decided", "ru": "уже решено"},
    "note.unclear": {"en": "didn't understand the answer", "ru": "не понял ответ"},
    "note.denied": {"en": "no access", "ru": "нет доступа"},
    "note.pick_one": {"en": "check at least one option", "ru": "отметь хотя бы один вариант"},
    "note.stale": {"en": "this button is outdated", "ru": "кнопка устарела"},
    "note.stale_retry": {"en": "this button is outdated — repeat the command", "ru": "кнопка устарела — повтори команду"},
    "note.muted": {"en": "only the result until the turn ends", "ru": "до конца хода — только итог"},
    "note.jump": {"en": "starting over the limit", "ru": "начинаю сверх лимита"},
    "note.not_queued": {"en": "it isn't waiting any more", "ru": "уже не ждёт"},
    "note.bound": {"en": "topic bound to {name}", "ru": "тема привязана к {name}"},
    "note.starting_in": {"en": "starting in {name}", "ru": "запускаю в {name}"},
    "note.sending_to": {"en": "sending to {name}", "ru": "отправляю в {name}"},
    "note.new_session": {"en": "new session", "ru": "новая сессия"},
    "note.starting_copy": {"en": "starting a copy", "ru": "запускаю копию"},
    "result.empty": {"en": "*Claude finished without text.*", "ru": "*Claude закончил без текста.*"},
    "result.done_in": {"en": " · done in {dur}", "ru": " · готово за {dur}"},
    "result.done": {"en": " · done", "ru": " · готово"},
    # ----- a turn broken off by an API error (StopFailure's error) -----
    "fail.rate_limit": {"en": "hit the usage limit", "ru": "упёрся в лимит подписки"},
    "fail.overloaded": {"en": "Anthropic is overloaded — try again", "ru": "Anthropic перегружен — повтори позже"},
    "fail.server_error": {"en": "Anthropic's server error — try again", "ru": "ошибка на сервере Anthropic — повтори"},
    "fail.authentication_failed": {"en": "signed out of Claude — sign in again", "ru": "вход в Claude слетел — войди заново"},
    "fail.billing_error": {"en": "a billing problem with the subscription", "ru": "проблема с оплатой подписки"},
    "fail.invalid_request": {"en": "the request was rejected", "ru": "запрос отклонён"},
    "fail.max_output_tokens": {"en": "the answer hit the length limit", "ru": "ответ упёрся в предел длины"},
    "fail.model_not_found": {"en": "the model is unavailable", "ru": "модель недоступна"},
    "fail.other": {"en": "broke off: {code}", "ru": "оборвался: {code}"},
    # ----- Telegram as a pager (stage V) -----
    "btn.resume": {"en": "▶ Continue at {hm}", "ru": "▶ Продолжить в {hm}"},
    "btn.resume_after": {"en": "▶ Continue after the reset", "ru": "▶ Продолжить после сброса"},
    "note.reply_sent": {"en": "Sent to the session", "ru": "Отправлено в сессию"},
    "note.reply_open": {"en": "The session is open on the computer without Pult — answer there or in the app",
                        "ru": "Сессия открыта на компьютере без Пульта — ответь там или в приложении"},
    "note.resume": {"en": "Will continue at {hm}", "ru": "Продолжу в {hm}"},
    "err.no_reset": {"en": "Don't know when the limit resets — open Resources in the app",
                     "ru": "Не знаю, когда сброс лимита — открой «Ресурсы» в приложении"},
    "card.st.work": {"en": "⏳ at work: {n}", "ru": "⏳ в работе: {n}"},
    "card.st.mine": {"en": "🟠 waiting for you: {n}, since {hm}", "ru": "🟠 ждут тебя: {n}, с {hm}"},
    "card.st.quiet": {"en": "✔️ nothing waits for you", "ru": "✔️ ничего не ждёт"},
    "job.fresh": {"en": "⚙️ {cmd} · running…", "ru": "⚙️ {cmd} · идёт…"},
    "job.running": {"en": "⚙️ {cmd} · running {dur}", "ru": "⚙️ {cmd} · идёт {dur}"},
    "job.done.final": {"en": "✅ {cmd} · done in {dur}", "ru": "✅ {cmd} · готово за {dur}"},
    "job.done": {"en": "✔️ {cmd} · done in {dur}", "ru": "✔️ {cmd} · готово за {dur}"},
    "job.killed": {"en": "interrupted", "ru": "прервана"},
    "job.code": {"en": "error, code {code}", "ru": "ошибка, код {code}"},
    "job.fail.final": {"en": "⚠️ {cmd} · {why} after {dur}", "ru": "⚠️ {cmd} · {why}, через {dur}"},
    "job.fail": {"en": "⚠️ {cmd} · {why} after {dur}", "ru": "⚠️ {cmd} · {why}, через {dur}"},
    "job.vehi": {"en": "⚙️ <b>{cmd}</b> · has been running for {dur}", "ru": "⚙️ <b>{cmd}</b> · идёт уже {dur}"},
    "topic.bound": {"en": "📂 This topic is now bound to project <b>{name}</b> · <code>{path}</code>",
                    "ru": "📂 Тема привязана к проекту <b>{name}</b> · <code>{path}</code>"},
    "started.in": {"en": "▶️ Started a session in {title} — the turn and the result will be there.",
                   "ru": "▶️ Запустил сессию в теме {title} — ход и итог будут там."},
    "topic.link": {"en": "📂 {title} — the project's topic: the turns, results and questions of its sessions. "
                         "A new session there: <code>/new text</code>.",
                   "ru": "📂 {title} — тема проекта: ходы, итоги и вопросы её сессий. Новая сессия там: "
                         "<code>/new текст</code>."},
    "bind.need_forum": {"en": "Topics are off in this group: the group's settings → Topics → on, then /bind again.",
                        "ru": "В этой группе выключены темы: настройки группы → Темы → включить, потом снова /bind."},
    "bind.private": {
        "en": "This is our private chat, and /bind goes in a group with topics. Here's how:\n"
              "1. Telegram → New Group → add me → create.\n"
              "2. The group's settings → Topics → on.\n"
              "3. Administrators → Add Admin → pick me, with “Manage Topics” and “Pin Messages”.\n"
              "4. Send /bind in the group itself.",
        "ru": "Это наш личный чат, а /bind пишут в группе с темами. Как её сделать:\n"
              "1. Telegram → Создать группу → добавь меня → создать.\n"
              "2. Настройки группы → Темы → включить.\n"
              "3. Администраторы → Добавить администратора → выбери меня, с правами «Управление темами» и "
              "«Закрепление сообщений».\n"
              "4. Напиши /bind в самой группе.",
    },
    "private.elsewhere": {"en": "I don't read this private chat: I work in Pult's group, a topic per project.",
                          "ru": "Этот личный чат я не читаю: работаю в группе Пульта, тема на проект."},
    "btn.group": {"en": "Open the group", "ru": "Открыть группу"},
    "q.already": {"en": "This question is already decided.", "ru": "Этот вопрос уже решён."},
    "cmd.unknown": {"en": "I don't know this command. /help", "ru": "Не знаю такой команды. /help"},
    "where.ask": {"en": "Which session? I'll remember the choice for this topic.\n"
                        "💻 a VS Code tab — straight into it · 🖥 open on the computer — as a copy · 📱 from Telegram · "
                        "▫️ closed — I'll continue it",
                  "ru": "В какую сессию? Запомню выбор для этой темы.\n"
                        "💻 вкладка VS Code — прямо в неё · 🖥 открыта на компьютере — копией · 📱 из Telegram · "
                        "▫️ закрыта — продолжу"},
    "err.no_folder": {"en": "I don't know which folder this session is in.", "ru": "Не знаю, в какой папке эта сессия."},
    "fork.offer": {"en": "This session is open on the computer (a VS Code tab or the terminal). Writing to it from here "
                         "would mix up the conversation. I can continue as a <b>copy</b>: the same history, a separate "
                         "session from there on.",
                   "ru": "Эта сессия открыта на компьютере (вкладка VS Code или терминал). Писать в неё отсюда нельзя — "
                         "переписка перемешается. Могу продолжить <b>копией</b>: вся история та же, дальше — "
                         "отдельная сессия."},
    "busy.driven": {"en": "{n} {sessions} from Telegram are already running — wait until one finishes.",
                    "ru": "Уже идут {n} {sessions} из Telegram — подожди, пока какая-нибудь закончит."},
    "tab.update": {"en": "🔄 Claude Code <b>{v}</b> is out. Pult hasn't been checked on it yet, so messages to its "
                         "VS Code tabs go as a copy. A Pult release checked on it turns writing into tabs back on once "
                         "it's installed. To allow it now, at your own risk: <code>pult tab allow {v}</code>, then "
                         "Reload Window in VS Code.",
                   "ru": "🔄 Вышел Claude Code <b>{v}</b>. Пульт на нём ещё не проверен, поэтому сообщения в его "
                         "вкладки VS Code уходят копией. Выпуск Пульта, проверенный на нём, вернёт запись во вкладки, "
                         "когда его поставят. Разрешить сейчас, на свой риск: <code>pult tab allow {v}</code>, потом "
                         "Reload Window в VS Code."},
    # security (0.9.23): a login from a new network, the app files on the server, someone else holding the bot token
    "login.new": {"en": "🔐 App login from a new network: {net} · {dev} · {how}.\nNot you? Log everyone out.",
                  "ru": "🔐 Вход в приложение из новой сети: {net} · {dev} · {how}.\nЕсли это не ты — выйди везде."},
    "login.via.open": {"en": "the app was opened", "ru": "приложение открыли"},
    "login.via.key": {"en": "a window reconnected", "ru": "окно переподключилось"},
    "btn.logout_all": {"en": "Log out everywhere", "ru": "Выйти везде"},
    "note.logged_out": {"en": "logged out everywhere: app windows closed", "ru": "вышел везде: окна приложения закрыты"},
    "mark.logged_out": {"en": "logged out everywhere at {hm}", "ru": "вышел везде в {hm}"},
    "files.differ": {"en": "⚠️ <b>The app is closed.</b> The server hands out other files than you deployed: {files}. "
                           "That's what it looks like when someone changes the app on the server. Until the files "
                           "match, the computer doesn't answer the app.\nJust updated the server yourself? Deploy "
                           "again. Otherwise check the server.",
                     "ru": "⚠️ <b>Приложение закрыто.</b> Сервер отдаёт не те файлы, что ты выкладывал: {files}. Так "
                           "бывает, если приложение на сервере подменили. Пока файлы не совпадут, компьютер не "
                           "отвечает приложению.\nСам только что обновлял сервер — выложи ещё раз. Иначе проверь сервер."},
    "files.match": {"en": "✅ The app files on the server match your deploy again — the app is open.",
                    "ru": "✅ Файлы приложения на сервере снова совпадают с выложенными — приложение открыто."},
    # stage U: installing an update from the app
    "upd.cant": {"en": "Nothing to install right now — open Settings again.",
                 "ru": "Сейчас ставить нечего — открой «Настройки» заново."},
    "upd.cant.busy": {"en": "Not now: a restart would cut off Pult's sessions that are working. "
                            "Install once they're free.",
                      "ru": "Сейчас нельзя: перезапуск оборвёт работающие сессии Пульта. "
                            "Поставь, когда освободятся."},
    "upd.cant.spawn": {"en": "Couldn't start the installer. Install from the terminal: bash install.sh",
                       "ru": "Не запустился установщик. Поставь из терминала: bash install.sh"},
    "upd.failed": {"en": "⚠️ <b>Pult {to} didn't come up</b> — {back} is back and works as before.\nWhy: {why}.\n"
                         "Details — in the app: Settings → Pult.",
                   "ru": "⚠️ <b>Пульт {to} не поднялся</b> — вернул {back}, всё работает как прежде.\nПричина: {why}.\n"
                         "Подробности — в приложении: Настройки → Пульт."},
    "upd.failed.kept": {"en": "⚠️ <b>Pult {to} wasn't installed</b> — {back} stays.\nWhy: {why}.",
                        "ru": "⚠️ <b>Пульт {to} не поставлен</b> — остался {back}.\nПричина: {why}."},
    "upd.dead": {"en": "⚠️ Pult didn't start after the update to {to}, nor after going back to {back}. "
                       "On the computer, in Pult's folder: bash install.sh — and see pult status.",
                 "ru": "⚠️ Пульт не запустился ни после обновления до {to}, ни после возврата к {back}. "
                       "На компьютере, в папке Пульта: bash install.sh — и посмотри pult status."},
    "upd.why.restarts": {"en": "it kept restarting — it crashes at start", "ru": "перезапускался снова и снова — падает при запуске"},
    "upd.why.no_start": {"en": "it didn't start", "ru": "не запустился"},
    "upd.why.no_relay": {"en": "it didn't reach the app's server in 90 s", "ru": "не связался с сервером приложения за 90 с"},
    "upd.why.no_commit": {"en": "the folder no longer has that commit", "ru": "в папке больше нет этого коммита"},
    "upd.why.no_source": {"en": "Pult doesn't know which folder it was installed from", "ru": "Пульт не знает, из какой папки его ставили"},
    "upd.why.pip": {"en": "the dependencies didn't install", "ru": "не поставились зависимости"},
    "upd.why.error": {"en": "the installer failed", "ru": "сбой установщика"},
    "upd.why.spawn": {"en": "the installer didn't start", "ru": "не запустился установщик"},
    # stage U3: the app's server takes the release the computer runs, from GitHub (deploy/relay/update.py)
    "srv.failed": {"en": "⚠️ <b>The app's server didn't take {to}</b> — {back} is back there and works as before.\nWhy: {why}.\n"
                         "Details — in the app: Settings → Pult and its parts.",
                   "ru": "⚠️ <b>Сервер приложения не взял {to}</b> — там снова {back}, всё работает как прежде.\nПричина: {why}.\n"
                         "Подробности — в приложении: Настройки → Пульт и его части."},
    "srv.failed.dead": {"en": "⚠️ <b>The app's server is down</b> after taking {to}, and going back to {back} didn't help. "
                              "On the server: journalctl -u pult-relay -u pult-relay-update",
                        "ru": "⚠️ <b>Сервер приложения не отвечает</b> после {to}, и возврат к {back} не помог. "
                              "На сервере: journalctl -u pult-relay -u pult-relay-update"},
    "srv.why.no_start": {"en": "the relay didn't start", "ru": "посредник не запустился"},
    "srv.why.no_mac": {"en": "the computer couldn't connect to it", "ru": "компьютер не смог к нему подключиться"},
    "srv.why.no_restart": {"en": "systemd didn't restart the relay", "ru": "systemd не перезапустил посредника"},
    "srv.why.broken": {"en": "the release lacks the relay's files", "ru": "в выпуске нет файлов посредника"},
    "srv.why.error": {"en": "the updater failed", "ru": "сбой обновлятеля"},
    "files.differ.warn": {"en": "⚠️ The server hands out the app not as release {tag} has it: {files}. A CDN or a proxy in "
                                "front of the server may change files — otherwise check the server. The app stays open.",
                          "ru": "⚠️ Сервер отдаёт приложение не таким, как в выпуске {tag}: {files}. Так бывает, если перед "
                                "сервером стоит CDN или прокси, который меняет файлы, — иначе проверь сервер. Приложение открыто."},
    "tg.conflict": {"en": "⚠️ Someone else receives this bot's messages (Telegram answers 409). If no second Pult runs "
                          "with this bot, the bot token has leaked: @BotFather → /revoke, then <code>pult setup</code> "
                          "asks for the new one.",
                    "ru": "⚠️ Сообщения этого бота получает кто-то ещё (Telegram отвечает 409). Если второй Пульт с "
                          "этим ботом не запущен — токен бота утёк: @BotFather → /revoke, затем <code>pult setup</code> "
                          "попросит новый."},
    "tg.conflict.hook": {"en": "⚠️ Someone set a webhook on this bot — only whoever holds the bot token can. Removed. "
                               "Change the token: @BotFather → /revoke, then <code>pult setup</code>.",
                         "ru": "⚠️ Кто-то поставил этому боту вебхук — так может только тот, у кого есть токен. Убрал. "
                               "Смени токен: @BotFather → /revoke, затем <code>pult setup</code>."},
    "menu.changed": {"en": "⚠️ Someone changed the app button of this bot — only whoever holds the bot token can. Put it "
                           "back. Change the token: @BotFather → /revoke, then <code>pult setup</code>.",
                     "ru": "⚠️ Кто-то поменял кнопку приложения у бота — так может только тот, у кого есть токен бота. "
                           "Вернул как было. Смени токен: @BotFather → /revoke, затем <code>pult setup</code>."},
    "status.head": {"en": "<b>On the computer now</b> · {state}", "ru": "<b>Сейчас на компьютере</b> · {state}"},
    "status.at_mac": {"en": "you're at the computer", "ru": "ты за компьютером"},
    "status.idle": {"en": "the computer has been idle for {dur}", "ru": "компьютер простаивает {dur}"},
    "status.none": {"en": "no open sessions", "ru": "открытых сессий нет"},
    "status.ask": {"en": "❓ waiting for an answer", "ru": "❓ ждёт ответа"},
    "status.work": {"en": "⏳ working", "ru": "⏳ работает"},
    "status.idle_sess": {"en": "💤 idle", "ru": "💤 свободна"},
    "projects.open": {"en": "Projects with Claude sessions, most recent first. Tap one for a link to its topic.",
                      "ru": "Проекты с сессиями Claude, свежие сверху. Нажми — дам ссылку на тему."},
    "projects.new": {"en": "Which project should it run in?", "ru": "В каком проекте запустить?"},
    "projects.bind": {"en": "This topic isn't bound to a project yet. Pick a project — I'll bind the topic and start "
                            "a session.",
                      "ru": "Эта тема ещё не привязана к проекту. Выбери проект — привяжу тему и запущу сессию."},
    "projects.none": {"en": "No projects with Claude sessions found.", "ru": "Проектов с сессиями Claude не нашёл."},
    "projects.create": {"en": "＋ New project", "ru": "＋ Новый проект"},
    # ----- files to and from the phone (stage F) -----
    "files.big": {"en": "📎 {name} — {mb} MB: Telegram hands bots files up to 20 MB. Put it into the project on the computer, "
                        "or send a smaller one (a zip, parts).",
                  "ru": "📎 {name} — {mb} МБ: Telegram отдаёт ботам файлы до 20 МБ. Положи его в проект на компьютере "
                        "или пришли поменьше (архивом, частями)."},
    "btn.files": {"en": "📎 Files ({n})", "ru": "📎 Файлы ({n})"},
    "send.err.session": {"en": "Pult doesn't know this session or its project folder",
                         "ru": "Пульт не знает этой сессии или папки её проекта"},
    "send.err.many": {"en": "At most {n} files at once", "ru": "Не больше {n} файлов за раз"},
    "send.err.outside": {"en": "not inside this project's folder", "ru": "не в папке этого проекта"},
    "send.err.none": {"en": "no such file", "ru": "такого файла нет"},
    "send.err.secret": {"en": "looks like keys or settings — not sent", "ru": "похоже на ключи или настройки — не отправляю"},
    "show.err.secret": {"en": "looks like keys or settings — not shown", "ru": "похоже на ключи или настройки — не показываю"},
    "send.err.empty": {"en": "the file is empty", "ru": "файл пустой"},
    "send.err.big": {"en": "over {mb} MB — Telegram takes no bigger files from bots; zip or split it",
                     "ru": "больше {mb} МБ — Telegram не берёт у ботов файлы крупнее; сожми или разбей"},
    "send.err.tg": {"en": "Telegram refused: {why}", "ru": "Telegram отказал: {why}"},
    "send.err.nothing": {"en": "Nothing to send", "ru": "Нечего отправлять"},
    "send.err.zip_raw": {"en": "{mb} MB of files is too much for one archive (up to {max} MB) — pick fewer",
                         "ru": "{mb} МБ файлов — слишком много для одного архива (до {max} МБ), отметь меньше"},
    "send.err.zip_big": {"en": "the archive grows over {mb} MB — Telegram takes no bigger files from bots; pick fewer",
                         "ru": "архив выходит больше {mb} МБ — Telegram не берёт у ботов файлы крупнее; отметь меньше"},
    "send.zip.caption": {"en": "Files: {n}", "ru": "Файлов: {n}"},
    "cli.send.usage": {"en": "pult send FILE… [-m TEXT] — files to the owner's phone, into the project's Telegram topic; "
                             "run it from a Claude Code session",
                       "ru": "pult send ФАЙЛ… [-m ТЕКСТ] — файлы владельцу на телефон, в тему проекта в Telegram; "
                             "запускать из сессии Claude Code"},
    "cli.send.nosession": {"en": "pult send works inside a Claude Code session: the project is found by the session "
                                 "(CLAUDE_CODE_SESSION_ID)",
                           "ru": "pult send работает внутри сессии Claude Code: проект находится по сессии "
                                 "(CLAUDE_CODE_SESSION_ID)"},
    "cli.send.nodaemon": {"en": "Pult isn't running — nothing was sent", "ru": "Пульт не запущен — ничего не отправлено"},
    "cli.send.old": {"en": "This Pult can't send files yet — update it (bash install.sh)",
                     "ru": "Этот Пульт ещё не умеет отправлять файлы — обнови его (bash install.sh)"},
    "cli.send.sent": {"en": "sent: {name}", "ru": "отправлено: {name}"},
    "cli.send.refused": {"en": "not sent: {name} — {why}", "ru": "не отправлено: {name} — {why}"},
    # ----- a new project from the phone (stage S) -----
    "new.err.title": {"en": "A name is needed", "ru": "Нужно название"},
    "new.err.name": {"en": "A folder name takes Latin letters, digits, \"_\", \"-\" and \".\": up to 64, starting with a letter "
                             "or a digit, not ending with a dot",
                     "ru": "Имя папки — латиница, цифры, «_», «-» и «.»: до 64 знаков, начало — буква или цифра, в конце не точка"},
    "new.err.where": {"en": "No such folder in your home folder", "ru": "Такой папки в домашней нет"},
    "new.err.exists": {"en": "There is a \"{name}\" there already — pick another name",
                       "ru": "Там уже есть «{name}» — выбери другое имя"},
    "new.err.key": {"en": "Claude Code would mix this project up with {other}: to it, names that differ only in marks are "
                            "the same. Pick another name",
                    "ru": "Claude Code спутает этот проект с {other}: для него имена, которые различаются только знаками, — "
                          "одно и то же. Выбери другое имя"},
    "new.err.link": {"en": "That doesn't look like a link to a repository (https://github.com/owner/name)",
                     "ru": "Не похоже на ссылку на репозиторий (https://github.com/кто/что)"},
    "new.err.git": {"en": "There is no git on the computer — nothing to clone with",
                    "ru": "На компьютере нет git — клонировать нечем"},
    "new.err.about": {"en": "Say what the project is about", "ru": "Напиши, о чём проект"},
    "new.err.job": {"en": "This project is no longer tracked — look in Projects", "ru": "Это создание уже не отслеживается — загляни в «Проекты»"},
    "new.err.slow": {"en": "The clone took over {min} min and was stopped; its folder is removed",
                     "ru": "Клон шёл дольше {min} мин и остановлен, папка убрана"},
    "new.err.clone": {"en": "Couldn't clone: {why}", "ru": "Не получилось склонировать: {why}"},
    "new.describe.session": {"en": "CLAUDE.md from the description", "ru": "CLAUDE.md по описанию"},
    "sessions.where": {"en": "/sessions — inside a project topic.", "ru": "/sessions — в теме проекта."},
    "sessions.list": {"en": "Recent sessions of this project. Tap one — I'll show its last answer; reply to that to "
                            "continue. 🖥 — open on the computer, 📱 — from Telegram.",
                      "ru": "Последние сессии проекта. Нажми — покажу последний ответ, ответом на него продолжишь. "
                            "🖥 — открыта на компьютере, 📱 — из Telegram."},
    "sessions.none": {"en": "No sessions.", "ru": "Сессий нет."},
    "card": {"en": "🧵 <b>{title}</b>\n{body}\n\n<i>reply to this message to continue the session</i>",
             "ru": "🧵 <b>{title}</b>\n{body}\n\n<i>ответь на это сообщение — продолжу сессию</i>"},
    "card.empty": {"en": "<i>no answers yet</i>", "ru": "<i>ответов нет</i>"},
    "stop.how": {"en": "/stop in a project topic interrupts the topic's current session, if it was started from "
                       "Telegram; as a reply to a session's message — that session. A turn in VS Code is interrupted "
                       "on the computer.",
                 "ru": "/stop в теме проекта прерывает её текущую сессию, если она запущена из Telegram; ответом на "
                       "сообщение сессии — ту сессию. Ход в VS Code прерывается на компьютере."},
    "stop.none": {"en": "Nothing to interrupt: no session from Telegram is working here right now.",
                  "ru": "Прерывать нечего: сессии из Telegram здесь сейчас не работают."},
    "stop.tab": {"en": "The current session is open in VS Code — its turn is interrupted on the computer.",
                 "ru": "Текущая сессия открыта в VS Code — её ход прерывается на компьютере."},
    "new.next": {"en": "Write the task — I'll start it as a new session in this project.",
                 "ru": "Напиши задачу — запущу её новой сессией в этом проекте."},
    "new.general": {"en": "Write the task here — I'll ask which project it's for. In a project topic, "
                          "<code>/new text</code> starts it right away.",
                    "ru": "Напиши задачу сюда — спрошу, в каком проекте. В теме проекта <code>/new текст</code> "
                          "запускает сразу."},
    "stop.only_driven": {"en": "only a session started from Telegram can be stopped — a turn in a tab is interrupted "
                               "on the computer",
                         "ru": "остановить можно только сессию из Telegram — ход во вкладке прерывается на компьютере"},
    "usage.warn": {"en": "⚠️ <b>{name} — {pct} %</b>\nResets {reset}.", "ru": "⚠️ <b>{name} — {pct} %</b>\nСброс {reset}."},
    "lim.session": {"en": "5-hour window", "ru": "Окно 5 ч"},
    "lim.week": {"en": "Week", "ru": "Неделя"},
    "lim.other": {"en": "limit", "ru": "лимит"},
    "err.bad_sid": {"en": "invalid session id", "ru": "неверный номер сессии"},
    "err.no_transcript": {"en": "session transcript not found", "ru": "транскрипт сессии не найден"},
    "err.no_project": {"en": "project not found", "ru": "проект не найден"},
    "tags.e.name": {"en": "the tag needs a name", "ru": "у тега нужно название"},
    "err.empty": {"en": "empty message", "ru": "пустое сообщение"},
    "err.no_folder_short": {"en": "I don't know the session's folder", "ru": "не знаю папку сессии"},
    "err.need_project_text": {"en": "a project and a text are needed", "ru": "нужны проект и текст"},
    "err.no_request": {"en": "no such request: {op}", "ru": "нет такого запроса: {op}"},
    "err.old_wrapper": {"en": "this tab started with an older Pult wrapper: Reload Window in VS Code first",
                        "ru": "вкладка запущена со старой обёрткой Пульта: сначала Reload Window в VS Code"},

    # ----- the pult command in Terminal (plain text; the report itself is English only) -----
    "cli.usage": {
        "en": "Pult — Claude Code on your computer, from Telegram.\n\n"
              "  pult setup                    set up or change: the bot, you, the group, hooks\n"
              "  pult status                   what is on: the service, hooks, Telegram, tabs\n"
              "  pult start | stop | restart   the background service\n"
              "  pult busy                     what a restart would cut off (sessions from Telegram at work)\n"
              "  pult hooks on | off           whether Pult sees sessions in VS Code and the terminal\n"
              "  pult tab                      writing from Telegram into open VS Code tabs\n"
              "  pult tab setup | on | off | allow VERSION\n"
              "  pult app [off]                the web app on your own server\n"
              "  pult stt [off]                voice input: a Groq key for speech recognition\n"
              "  pult run -- COMMAND           run a command; its start, progress and end go to Telegram\n"
              "  pult send FILE… [-m TEXT]     files to your phone, into the project's topic (Claude runs it)\n"
              "  pult report                   versions and state for a bug report (no tokens, IDs or messages)\n"
              "  pult uninstall                remove Pult from this computer\n\n"
              "Hooks and the tab wrapper are picked up when a session starts: after changing them, run Reload Window "
              "in VS Code.",
        "ru": "Пульт — Claude Code на твоём компьютере из Telegram.\n\n"
              "  pult setup                    настроить или поменять: бот, ты, группа, хуки\n"
              "  pult status                   что включено: служба, хуки, Telegram, вкладки\n"
              "  pult start | stop | restart   фоновая служба\n"
              "  pult busy                     что оборвёт перезапуск (работающие сессии из Telegram)\n"
              "  pult hooks on | off           видит ли Пульт сессии в VS Code и терминале\n"
              "  pult tab                      запись из Telegram в открытые вкладки VS Code\n"
              "  pult tab setup | on | off | allow ВЕРСИЯ\n"
              "  pult app [off]                веб-приложение на своём сервере\n"
              "  pult stt [off]                голосовой ввод: ключ Groq для распознавания речи\n"
              "  pult run -- КОМАНДА           выполнить команду; старт, ход и конец — в Telegram\n"
              "  pult send ФАЙЛ… [-m ТЕКСТ]    файлы тебе на телефон, в тему проекта (запускает Claude)\n"
              "  pult report                   версии и состояние для сообщения об ошибке (без токенов, ID и переписки)\n"
              "  pult uninstall                удалить Пульт с этого компьютера\n\n"
              "Хуки и обёртка вкладок подхватываются при запуске сессии: после их смены — Reload Window в VS Code.",
    },
    "cli.yn.y": {"en": "[Y/n]", "ru": "[Д/н]"},
    "cli.yn.n": {"en": "[y/N]", "ru": "[д/Н]"},
    "cli.backup": {"en": "backup: {path}", "ru": "копия: {path}"},
    "cli.not_installed": {"en": "Pult isn't installed: ./install.sh in the Pult folder (Windows: install.ps1).",
                          "ru": "Пульт не установлен: ./install.sh в папке Пульта (Windows: install.ps1)."},
    "cli.lang.en": {"en": "English", "ru": "английский"},
    "cli.lang.ru": {"en": "Russian", "ru": "русский"},
    "cli.install.done": {"en": "Pult {version} is installed in {home}.", "ru": "Пульт {version} установлен в {home}."},
    "cli.install.path": {
        "en": "The command is {path}, but ~/.local/bin isn't in PATH. Add it, then open a new terminal window:\n"
              "  echo 'export PATH=\"$HOME/.local/bin:$PATH\"' >> {rc}",
        "ru": "Команда — {path}, но ~/.local/bin нет в PATH. Добавь и открой новое окно терминала:\n"
              "  echo 'export PATH=\"$HOME/.local/bin:$PATH\"' >> {rc}",
    },
    "cli.install.taken": {"en": "{path} already belongs to another program — left as is. Pult's command: {ctl}",
                          "ru": "{path} уже занят другой программой — не трогаю. Команда Пульта: {ctl}"},
    "cli.install.next": {"en": "Next, set it up in a terminal: pult setup", "ru": "Дальше — настройка, в терминале: pult setup"},
    "cli.svc.busy": {"en": "Stop Pult anyway?", "ru": "Всё равно остановить Пульт?"},
    "cli.svc.wait": {
        "en": "Not stopped. Wait until they finish (`pult busy` shows what is left), or anyway: PULT_FORCE=1 before "
              "the command.",
        "ru": "Не останавливаю. Подожди, пока закончат (`pult busy` покажет, что осталось), или всё равно: "
              "PULT_FORCE=1 перед командой.",
    },
    "cli.busy.list": {
        "en": "Stopping Pult would cut off its own sessions — those started from Telegram or the app:\n{list}",
        "ru": "Остановка Пульта оборвёт его собственные сессии — запущенные из Telegram или приложения:\n{list}",
    },
    "cli.busy.turn": {"en": "a turn is running", "ru": "идёт ход"},
    "cli.busy.bg": {"en": "in the background: {tasks}", "ru": "в фоне: {tasks}"},
    "cli.busy.unknown": {
        "en": "{n} Claude processes; this Pult can't tell whether they are busy",
        "ru": "процессов Claude: {n}; этот Пульт не может сказать, заняты ли они",
    },
    "cli.busy.none": {"en": "Nothing of Pult's own is running: a restart cuts nothing off.",
                      "ru": "У Пульта ничего не идёт: перезапуск ничего не оборвёт."},
    "cli.svc.kept": {"en": "Left as it is.", "ru": "Оставляю как есть."},
    "cli.svc.started": {"en": "✓ Pult is running (service {label}).", "ru": "✓ Пульт работает (служба {label})."},
    "cli.svc.not_started": {"en": "✗ Pult didn't start — see the log: {log}",
                            "ru": "✗ Пульт не запустился — смотри журнал: {log}"},
    "cli.svc.stopped": {"en": "Pult is stopped. Start it: pult start", "ru": "Пульт остановлен. Запустить: pult start"},
    "cli.svc.not_ready": {"en": "Pult isn't set up yet: pult setup", "ru": "Пульт ещё не настроен: pult setup"},
    "cli.svc.no_manager": {
        "en": "✗ Pult runs as a systemd user service, and those aren't available here ({why}). Log in as this user "
              "directly (SSH, not su or sudo); on WSL turn systemd on ([boot] systemd=true in /etc/wsl.conf). "
              "Or keep the daemon running yourself: {cmd}",
        "ru": "✗ Пульт работает как служба systemd пользователя, а их здесь нет ({why}). Войди этим пользователем "
              "напрямую (SSH, не su и не sudo); в WSL включи systemd ([boot] systemd=true в /etc/wsl.conf). "
              "Или держи демон запущенным сам: {cmd}",
    },
    "cli.svc.linger": {
        "en": "On a server or over SSH, Pult stops when you log out. To keep it running (and start it at boot): "
              "sudo loginctl enable-linger {user}",
        "ru": "На сервере или по SSH Пульт останавливается, когда ты выходишь. Чтобы работал всегда (и сам "
              "запускался при загрузке): sudo loginctl enable-linger {user}",
    },
    "cli.setup.title": {
        "en": "Pult setup: 4 steps, about 5 minutes. Ctrl+C stops it; `pult setup` again continues where you left off.",
        "ru": "Настройка Пульта: 4 шага, минут пять. Ctrl+C — прервать; `pult setup` ещё раз продолжит с того же места.",
    },
    "cli.setup.pause": {"en": "Pult is paused while you set it up.", "ru": "Пульт на время настройки остановлен."},
    "cli.setup.failed": {"en": "✗ Something went wrong ({why}). `pult report` shows the state for a bug report.",
                         "ru": "✗ Что-то пошло не так ({why}). `pult report` покажет состояние для сообщения об ошибке."},
    "cli.setup.stopped": {"en": "Setup stopped. Continue: pult setup", "ru": "Настройка прервана. Продолжить: pult setup"},
    "cli.setup.done": {
        "en": "\nDone: the panel and help are in the group's General topic. Write a task there — Pult asks which "
              "project and starts Claude on the computer; every project gets a topic of its own.",
        "ru": "\nГотово: панель и помощь — в «Общей» теме группы. Напиши туда задачу — Пульт спросит, в каком "
              "проекте, и запустит Claude на компьютере; у каждого проекта будет своя тема.",
    },
    "cli.setup.extras": {
        "en": "\nOptional:\n• write from Telegram straight into open VS Code tabs — pult tab setup\n"
              "• the web app (needs your own server) — deploy/relay/README.md, then pult app\n"
              "• voice input (a free Groq key) — pult stt\n• all commands — pult help",
        "ru": "\nПо желанию:\n• писать из Telegram прямо в открытые вкладки VS Code — pult tab setup\n"
              "• веб-приложение (нужен свой сервер) — deploy/relay/README.md, затем pult app\n"
              "• голосовой ввод (бесплатный ключ Groq) — pult stt\n• все команды — pult help",
    },
    "cli.step.bot": {"en": "Bot", "ru": "Бот"},
    "cli.step.you": {"en": "You", "ru": "Ты"},
    "cli.step.group": {"en": "Group", "ru": "Группа"},
    "cli.step.hooks": {"en": "Claude Code sessions", "ru": "Сессии Claude Code"},
    "cli.bot.how": {
        "en": "In Telegram, open @BotFather → /newbot → a name, then a username ending in “bot”.\n"
              "BotFather replies with the bot's token, like 123456789:AAF…",
        "ru": "В Telegram открой @BotFather → /newbot → имя, затем адрес, оканчивающийся на «bot».\n"
              "BotFather пришлёт токен бота, вида 123456789:AAF…",
    },
    "cli.bot.ask": {"en": "Bot token (not shown as you paste): ", "ru": "Токен бота (при вставке не виден): "},
    "cli.bot.keep": {"en": "Bot @{bot} — keep it?", "ru": "Бот @{bot} — оставить?"},
    "cli.bot.shape": {"en": "✗ That doesn't look like a bot token (digits, a colon, then ~35 letters and digits). Copy it "
                            "from @BotFather once more.",
                      "ru": "✗ Это не похоже на токен бота (цифры, двоеточие и ~35 букв и цифр). Скопируй его из "
                            "@BotFather ещё раз."},
    "cli.bot.ok": {"en": "✓ bot @{bot}", "ru": "✓ бот @{bot}"},
    "cli.bot.bad": {"en": "✗ Telegram doesn't accept this token ({why}). Copy it from @BotFather once more.",
                    "ru": "✗ Telegram не принимает этот токен ({why}). Скопируй его из @BotFather ещё раз."},
    "cli.bot.net": {"en": "✗ No connection to Telegram ({why}). Check the internet (or PULT_PROXY in {env}) and try again.",
                    "ru": "✗ Нет связи с Telegram ({why}). Проверь интернет (или PULT_PROXY в {env}) и попробуй ещё раз."},
    "cli.bot.webhook": {
        "en": "This bot already hands its messages to {host}. Pult needs a bot of its own: if this one works "
              "elsewhere, make a new one. Switch that off and give the bot to Pult?",
        "ru": "Этот бот уже отдаёт сообщения на {host}. Пульту нужен свой бот: если этот работает где-то ещё — заведи "
              "новый. Отключить это и отдать бота Пульту?",
    },
    "cli.you.keep": {"en": "Owner: Telegram ID {id} — keep?", "ru": "Владелец: Telegram ID {id} — оставить?"},
    "cli.you.how": {
        "en": "Open this link on your phone and tap Start — the bot will know it's you:\n  {link}\n"
              "(or send the bot: /start {code})\nWaiting…",
        "ru": "Открой ссылку на телефоне и нажми «Старт» — бот узнает, что это ты:\n  {link}\n"
              "(или отправь боту: /start {code})\nЖду…",
    },
    "cli.you.nocode": {"en": "  /start from {name} without the code — open the link above.",
                       "ru": "  /start от {name} без кода — открой ссылку выше."},
    "cli.you.timeout": {"en": "No /start for 15 minutes.", "ru": "За 15 минут /start не пришёл."},
    "cli.you.ok": {"en": "✓ {name} · Telegram ID {id} · language: {language}", "ru": "✓ {name} · Telegram ID {id} · язык: {language}"},
    "cli.group.how": {
        "en": "Pult works in a separate Telegram group with topics, a topic per project.\n"
              "1. Telegram → New Group → add @{bot} → create.\n"
              "2. The group's settings → Topics → on.\n"
              "3. Administrators → Add Admin → @{bot}, with “Manage Topics” and “Pin Messages”.\n"
              "4. In the group itself (not in the chat with the bot), send: /bind@{bot}\nWaiting…",
        "ru": "Пульт работает в отдельной группе Telegram с темами, тема на проект.\n"
              "1. Telegram → Создать группу → добавь @{bot} → создать.\n"
              "2. Настройки группы → Темы → включить.\n"
              "3. Администраторы → Добавить администратора → @{bot}, с правами «Управление темами» и "
              "«Закрепление сообщений».\n"
              "4. В самой группе (не в чате с ботом) напиши: /bind@{bot}\nЖду…",
    },
    "cli.group.keep": {"en": "Group “{title}” — keep it?", "ru": "Группа «{title}» — оставить?"},
    "cli.group.problem": {"en": "Group “{title}”: {why}.", "ru": "Группа «{title}»: {why}."},
    "cli.group.not_forum": {"en": "  The group has no topics yet: settings → Topics → on, then /bind again.",
                            "ru": "  В группе ещё нет тем: настройки → Темы → включить, потом снова /bind."},
    "cli.group.not_admin": {"en": "  @{bot} isn't an admin with “Manage Topics” yet — fix that, then /bind again.",
                            "ru": "  @{bot} пока не админ с правом «Управление темами» — исправь и снова /bind."},
    "cli.group.no_pin": {"en": "  Without “Pin Messages” the panel won't be pinned — the right can be given later.",
                         "ru": "  Без права «Закрепление сообщений» панель не закрепится — право можно дать позже."},
    "cli.group.timeout": {"en": "No /bind for 15 minutes.", "ru": "За 15 минут /bind не пришёл."},
    "cli.group.ok": {"en": "✓ group “{title}”", "ru": "✓ группа «{title}»"},
    "cli.why.not_forum": {"en": "topics are off", "ru": "темы выключены"},
    "cli.why.not_admin": {"en": "the bot isn't an admin with “Manage Topics”",
                          "ru": "бот не админ с правом «Управление темами»"},
    "cli.why.gone": {"en": "the bot can't see the group ({why})", "ru": "бот не видит группу ({why})"},
    "cli.tg.hello": {"en": "✅ Pult knows you now. Back to the terminal on the computer: next you'll make a separate group "
                           "with topics.",
                     "ru": "✅ Пульт тебя узнал. Возвращайся в терминал на компьютере: дальше сделаем отдельную группу с "
                           "темами."},
    "cli.tg.need_admin": {"en": "Make me an admin with “Manage Topics” (and “Pin Messages”), then send /bind again.",
                          "ru": "Сделай меня админом с правом «Управление темами» (и «Закрепление сообщений»), потом "
                                "снова /bind."},
    "cli.tg.bound": {"en": "✅ This group is Pult's now. The panel and help will appear here in a minute.",
                     "ru": "✅ Теперь это группа Пульта. Панель и помощь появятся здесь через минуту."},
    "cli.tg.conflict": {"en": "Someone else is reading this bot's updates (another copy of Pult?) — waiting…",
                        "ru": "Обновления этого бота читает кто-то ещё (другая копия Пульта?) — жду…"},
    "cli.hooks.about": {
        "en": "Pult sees VS Code tabs and terminal sessions through Claude Code hooks: {n} entries marked "
              "pult_hook.py in {path}. Your other settings stay as they are; a backup copy is made first. Without "
              "hooks, only sessions started from Telegram are visible.",
        "ru": "Пульт видит вкладки VS Code и сессии в терминале через хуки Claude Code: {n} записей с меткой "
              "pult_hook.py в {path}. Остальные твои настройки не меняются, сначала делается копия. Без хуков видны "
              "только сессии, запущенные из Telegram.",
    },
    "cli.hooks.ask": {"en": "Turn the hooks on?", "ru": "Включить хуки?"},
    "cli.hooks.already": {"en": "✓ hooks are on", "ru": "✓ хуки включены"},
    "cli.hooks.later": {"en": "Later: pult hooks on", "ru": "Позже: pult hooks on"},
    "cli.hooks.state": {"en": "Pult hooks: {events}", "ru": "Хуки Пульта: {events}"},
    "cli.hooks.off": {"en": "off", "ru": "выключены"},
    "cli.hooks.missing": {"en": " — not yet {events}: run pult hooks on", "ru": " — пока нет {events}: pult hooks on"},
    "cli.hooks.reload": {"en": "New sessions pick this up; in VS Code: {palette} → Developer: Reload Window.",
                         "ru": "Подхватят новые сессии; в VS Code: {palette} → Developer: Reload Window."},
    "cli.hooks.no_hook": {"en": "No {path} — run ./install.sh first.", "ru": "Нет {path} — сначала ./install.sh."},
    "cli.hooks.unreadable": {
        "en": "{path} mentions Pult's hook but isn't plain JSON (comments or a broken edit) — I won't touch it. Remove "
              "the entries with pult_hook.py by hand, then run the command again.",
        "ru": "В {path} есть хук Пульта, но файл — не чистый JSON (комментарии или сломанная правка) — не трогаю. "
              "Убери записи с pult_hook.py вручную и повтори команду.",
    },
    "cli.st.daemon": {"en": "daemon:", "ru": "демон:"},
    "cli.st.running": {"en": "{state}, pid {pid}", "ru": "{state}, pid {pid}"},
    "cli.st.not_loaded": {"en": "not running ({label})", "ru": "не запущен ({label})"},
    "cli.st.sock": {"en": "socket:", "ru": "сокет:"},
    "cli.st.answers": {"en": "answers", "ru": "отвечает"},
    "cli.st.no": {"en": "no", "ru": "нет"},
    "cli.st.hooks": {"en": "hooks:", "ru": "хуки:"},
    "cli.st.settings": {"en": "settings:", "ru": "настройки:"},
    "cli.st.no_token": {"en": "no bot token — pult setup", "ru": "нет токена бота — pult setup"},
    "cli.st.tg": {"en": "Telegram:", "ru": "Telegram:"},
    "cli.st.via_proxy": {"en": "via proxy", "ru": "через прокси"},
    "cli.st.direct": {"en": "direct", "ru": "напрямую"},
    "cli.st.route_ok": {"en": "{route} — yes", "ru": "{route} — да"},
    "cli.st.route_bad": {"en": "{route} — no ({why})", "ru": "{route} — нет ({why})"},
    "cli.st.tabs": {"en": "tabs:", "ru": "вкладки:"},
    "cli.st.log": {"en": "log:", "ru": "журнал:"},
    "cli.tab.not_wrapped": {"en": "the wrapper isn't in the VS Code settings — writing into tabs is off (pult tab setup)",
                            "ru": "обёртки нет в настройках VS Code — запись во вкладки выключена (pult tab setup)"},
    "cli.tab.off": {"en": "off ({path}) — pult tab on", "ru": "выключено ({path}) — pult tab on"},
    "cli.tab.on": {"en": "on · folders: {folders} · Claude Code versions: {versions}",
                   "ru": "включено · папки: {folders} · версии Claude Code: {versions}"},
    "cli.tab.none": {"en": "none", "ru": "нет"},
    "cli.tab.next": {"en": "Applies to tabs that start from now on; open ones — after Reload Window.",
                     "ru": "Действует на вкладки, которые запустятся дальше; открытые — после Reload Window."},
    "cli.tab.about": {
        "en": "Pult can put your Telegram messages straight into an open Claude tab in VS Code — they show up there "
              "as if typed on the computer. It works through a small wrapper around Claude Code: if anything is off, Claude "
              "starts directly, as without Pult.",
        "ru": "Пульт может вписывать сообщения из Telegram прямо в открытую вкладку Claude в VS Code — они появятся "
              "там, будто набраны на компьютере. Для этого — небольшая обёртка вокруг Claude Code: если что-то не так, "
              "Claude запускается напрямую, как без Пульта.",
    },
    "cli.tab.folders": {"en": "Folders where it works, comma-separated (Enter — {default}): ",
                        "ru": "Папки, где это работает, через запятую (Enter — {default}): "},
    "cli.tab.saved": {"en": "saved: {path}", "ru": "записано: {path}"},
    "cli.tab.line": {
        "en": "Add this line to the VS Code settings ({palette} → Preferences: Open User Settings (JSON)):\n"
              "  {line}\nthen {palette} → Developer: Reload Window. Turn it off any time: pult tab off.",
        "ru": "Добавь строку в настройки VS Code ({palette} → Preferences: Open User Settings (JSON)):\n"
              "  {line}\nпотом {palette} → Developer: Reload Window. Выключить в любой момент: pult tab off.",
    },
    "cli.tab.remote": {
        "en": "VS Code reaches this machine through Remote-SSH: then the line goes into the remote settings instead — "
              "in a window connected here, {palette} → Preferences: Open Remote Settings (JSON).",
        "ru": "VS Code заходит на эту машину через Remote-SSH: тогда строка идёт в удалённые настройки — в окне, "
              "подключённом сюда, {palette} → Preferences: Open Remote Settings (JSON).",
    },
    "cli.tab.unverified": {
        "en": "Your Claude Code extension is {v}: the wrapper hasn't been checked on it and stays out of the way "
              "until `pult tab allow {v}` (after tests/probe_tab.py, or at your own risk).",
        "ru": "У тебя расширение Claude Code {v}: обёртка на нём не проверялась и ни во что не вмешивается до "
              "`pult tab allow {v}` (после tests/probe_tab.py или на свой риск).",
    },
    "cli.tab.added": {
        "en": "Tabs: this release is checked on Claude Code {v} — Pult writes into its tabs too; tabs already open — "
              "after Reload Window in VS Code.",
        "ru": "Вкладки: этот выпуск проверен на Claude Code {v} — Пульт пишет и в его вкладки; уже открытые — после "
              "Reload Window в VS Code.",
    },
    "cli.tab.broken": {
        "en": "⚠️ The wrapper line in {file} isn't valid JSON: VS Code reads \"{value}\" with the backslashes eaten, "
              "and Claude tabs don't start at all. Replace the line with:\n  {line}\nthen {palette} → Developer: Reload Window.",
        "ru": "⚠️ Строка обёртки в {file} — не JSON: VS Code прочтёт \"{value}\" без обратных косых, и вкладки Claude "
              "не запустятся совсем. Замени строку на:\n  {line}\nпотом {palette} → Developer: Reload Window.",
    },
    "cli.tab.missing": {
        "en": "⚠️ The wrapper line in {file} names {value}, and there's no such file: Claude tabs in VS Code don't start "
              "at all. Replace the line with:\n  {line}\nthen {palette} → Developer: Reload Window.",
        "ru": "⚠️ Строка обёртки в {file} указывает на {value}, а такого файла нет: вкладки Claude в VS Code не "
              "запустятся совсем. Замени строку на:\n  {line}\nпотом {palette} → Developer: Reload Window.",
    },
    "cli.tab.copy": {"en": "Copy the line to the clipboard?", "ru": "Скопировать строку в буфер обмена?"},
    "cli.tab.copied": {"en": "Copied.", "ru": "Скопировано."},
    "cli.stt.about": {
        "en": "Voice input: a voice message in Telegram or the microphone button in the app becomes text for Claude.\n"
              "Recognition is done by Groq (groq.com, Whisper): the recordings go there. A free key is made at "
              "console.groq.com; it is kept only in {env}.",
        "ru": "Голосовой ввод: голосовое в Telegram или кнопка микрофона в приложении становятся текстом для Claude.\n"
              "Распознаёт Groq (groq.com, Whisper): записи уходят туда. Бесплатный ключ — на console.groq.com; "
              "хранится только в {env}.",
    },
    "cli.stt.key": {"en": "Groq API key (typing is hidden): ", "ru": "Ключ API Groq (ввод скрыт): "},
    "cli.stt.key_again": {"en": "Groq API key (typing is hidden; Enter — keep the current one): ",
                          "ru": "Ключ API Groq (ввод скрыт; Enter — оставить нынешний): "},
    "cli.stt.none": {"en": "No key entered — voice input stays off.", "ru": "Ключ не введён — голосовой ввод выключен."},
    "cli.stt.kept": {"en": "The key stays as it was.", "ru": "Ключ оставлен прежним."},
    "cli.stt.checking": {"en": "Checking the key with Groq…", "ru": "Проверяю ключ у Groq…"},
    "cli.stt.bad": {"en": "✗ Groq doesn't accept the key: {why}", "ru": "✗ Groq не принимает ключ: {why}"},
    "cli.stt.done": {
        "en": "✅ Voice input is on: send a voice message in Telegram or tap the microphone in the app. Off: pult stt off",
        "ru": "✅ Голосовой ввод включён: отправь голосовое в Telegram или нажми микрофон в приложении. Выключить: pult stt off",
    },
    "cli.stt.off": {"en": "Voice input is off; the key is removed.", "ru": "Голосовой ввод выключен, ключ убран."},
    "cli.app.about": {
        "en": "The web app opens from Telegram on your phone: every session in full, Claude's questions, new tasks, "
              "usage. It needs your own server with a domain and HTTPS — deploy/relay/README.md.",
        "ru": "Веб-приложение открывается из Telegram на телефоне: все сессии целиком, вопросы Claude, новые задачи, "
              "расход. Ему нужен свой сервер с доменом и HTTPS — deploy/relay/README.md.",
    },
    "cli.app.url": {"en": "The app's address on your server, like https://example.com/pult/ (Enter — {default}): ",
                    "ru": "Адрес приложения на твоём сервере, вида https://example.com/pult/ (Enter — {default}): "},
    "cli.app.bad_url": {"en": "It needs an https:// address.", "ru": "Нужен адрес с https://."},
    "cli.app.link": {"en": "The Mini App link from @BotFather (Enter — {default}): ",
                     "ru": "Ссылка на Mini App из @BotFather (Enter — {default}): "},
    "cli.app.server_env": {
        "en": "Put these lines into the server's .env (the secret is the computer's key to the server — keep it private):",
        "ru": "Эти строки — в .env на сервере (секрет — ключ компьютера к серверу, никому не показывай):",
    },
    "cli.app.botfather": {"en": "In @BotFather: /newapp → your bot → Web App URL {url} → a short name (for the link).",
                          "ru": "В @BotFather: /newapp → твой бот → Web App URL {url} → короткое имя (для ссылки)."},
    "cli.app.off": {"en": "The web app is off.", "ru": "Веб-приложение выключено."},
    "cli.run.usage": {"en": "pult run -- command [arguments]", "ru": "pult run -- команда [аргументы]"},
    "cli.run.failed": {"en": "didn't start:", "ru": "не запустилось:"},
    "cli.report.head": {
        "en": "Pult report for a GitHub issue. Tokens, IDs, folder names and message text are removed — still, read it "
              "before posting.",
        "ru": "Отчёт Пульта для issue на GitHub. Токены, ID, имена папок и текст сообщений убраны — и всё же прочитай "
              "перед отправкой.",
    },
    "cli.un.about": {
        "en": "This removes Pult from this computer: the background service, the hooks in {settings}, the pult command and "
              "{home} (state and environment). Claude Code itself stays as it is.",
        "ru": "Это удалит Пульт с компьютера: фоновую службу, хуки в {settings}, команду pult и {home} (состояние и "
              "окружение). Сам Claude Code останется как есть.",
    },
    "cli.un.ask": {"en": "Remove Pult?", "ru": "Удалить Пульт?"},
    "cli.un.conf": {"en": "Also delete the settings with the bot token ({conf}) and the logs?",
                    "ru": "Удалить и настройки с токеном бота ({conf}), и журналы?"},
    "cli.un.cancel": {"en": "Nothing changed.", "ru": "Ничего не менял."},
    "cli.un.tab": {
        "en": "Claude tabs are still started through {path} ({settings}): it's left as a stub that just runs Claude. "
              "Remove the claudeCode.claudeProcessWrapper line from those settings, then delete {home}.",
        "ru": "Вкладки Claude всё ещё запускаются через {path} ({settings}): там оставлена заглушка, которая просто "
              "запускает Claude. Убери строку claudeCode.claudeProcessWrapper из этих настроек, потом удали {home}.",
    },
    "cli.un.left": {
        "en": "Not removed — Windows holds them while this window runs Pult's Python: {paths}. Close the window and "
              "delete them.",
        "ru": "Не удалились — Windows держит их, пока это окно работает на Python Пульта: {paths}. Закрой окно и удали.",
    },
    "cli.un.done": {
        "en": "Pult is removed. The bot and the group stay in Telegram: @BotFather → /deletebot if you don't need the bot.",
        "ru": "Пульт удалён. Бот и группа остаются в Telegram: @BotFather → /deletebot, если бот не нужен.",
    },

    # ----- bot command menu -----
    "cmd.new": {"en": "new session: /new task text", "ru": "новая сессия: /new текст задачи"},
    "cmd.help": {"en": "how to use, turn on and off", "ru": "как пользоваться, включить и выключить"},
    "cmd.mode": {"en": "notifications: at the computer / on the phone", "ru": "уведомления: за компьютером / с телефоном"},
    "cmd.desk": {"en": "I'm at the computer — everything silent", "ru": "я за компьютером — всё беззвучно"},
    "cmd.phone": {"en": "I'm on the phone — with sound", "ru": "я с телефоном — со звуком"},
    "cmd.auto": {"en": "sound when I'm away from the computer", "ru": "звук, когда отошёл от компьютера"},
    "cmd.status": {"en": "what's open on the computer", "ru": "что открыто на компьютере"},
    "cmd.sessions": {"en": "recent sessions of the project", "ru": "последние сессии проекта"},
    "cmd.projects": {"en": "projects — open a topic", "ru": "проекты — открыть тему"},
    "cmd.stop": {"en": "interrupt the turn (in a topic or as a reply)", "ru": "прервать ход (в теме или ответом)"},
    "cmd.app": {"en": "open the app", "ru": "открыть приложение"},
    "cmd.feedback": {"en": "report a bug or suggest an idea", "ru": "сообщить об ошибке или идее"},
}

COMMANDS = ("new", "stop", "status", "sessions", "projects", "app", "desk", "phone", "auto", "mode", "help", "feedback")

# Plural forms: English — one/other, Russian — one/few/many.
P = {
    "step": {"en": ("step", "steps"), "ru": ("шаг", "шага", "шагов")},
    "line": {"en": ("line", "lines"), "ru": ("строка", "строки", "строк")},
    "request": {"en": ("request", "requests"), "ru": ("запрос", "запроса", "запросов")},
    "session": {"en": ("session", "sessions"), "ru": ("сессия", "сессии", "сессий")},
}

LANG = "en"          # the owner's language; Pult has one owner, so one language at a time (set_lang)


def set_lang(lang):
    global LANG
    LANG = lang if lang in LANGS else "en"


def T(key, lang=None, **kw):
    v = S.get(key) or {}
    s = v.get(lang or LANG) or v.get("en") or key
    return s.format(**kw) if kw else s


def plural(n, key, lang=None):
    """The word for n in the current language: plural(3, "step") → "steps" / «шага»."""
    lang = lang or LANG
    forms = (P.get(key) or {}).get(lang) or (P.get(key) or {}).get("en") or (key, key)
    n = abs(int(n))
    if lang != "ru":
        return forms[0] if n == 1 else forms[1]
    if n % 10 == 1 and n % 100 != 11:
        return forms[0]
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return forms[1]
    return forms[2]


def q(s, lang=None):
    """Quote a name: “name” in English, «name» in Russian."""
    return ("«%s»" if (lang or LANG) == "ru" else "“%s”") % s


def lang_of(code):
    """Telegram language_code → one of LANGS."""
    return "ru" if str(code or "").lower().startswith("ru") else "en"
