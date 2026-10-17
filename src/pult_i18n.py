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
    "mode.auto.about": {
        "en": "Sound only when you've been away from the computer for 2+ minutes or the session was started from Telegram.",
        "ru": "Со звуком — только если ты отошёл от компьютера больше чем на 2 минуты или сессия запущена из Telegram.",
    },
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

    # ----- help -----
    "help": {
        "en": "<b>Pult</b> — Claude Code on your computer, from Telegram.\n\n"
              "• Every project gets its own topic. Sessions from VS Code and the terminal show up by themselves: "
              "what Claude is doing right now, and the result.\n"
              "• Claude's questions and permission requests — answer with buttons, here or on the computer, whoever is first.\n"
              "• Write in a project topic to give Claude a task; reply to a session's message to continue it.\n\n"
              "/mode — notifications · /status — what's open on the computer · /projects — projects · /app — the app · "
              "/feedback — a bug or an idea\n\nPick a topic:",
        "ru": "<b>Пульт</b> — Claude Code на твоём компьютере, из Telegram.\n\n"
              "• У каждого проекта — своя тема. Сессии из VS Code и терминала появляются сами: что Claude делает "
              "сейчас и итог.\n"
              "• На вопросы и разрешения Claude — кнопками, здесь или на компьютере, кто первый.\n"
              "• Напиши в тему проекта — Claude получит задачу; ответ на сообщение сессии — продолжение.\n\n"
              "/mode — уведомления · /status — что открыто на компьютере · /projects — проекты · /app — приложение · "
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
              "4. A new task — write in the project's topic, or /projects → pick a project.\n"
              "5. Leaving the computer — /phone; back — /desk. Or keep 🔄 Auto.",
        "ru": "<b>🚀 С чего начать</b>\n\n"
              "1. Работай на компьютере как обычно — в VS Code или терминале. Сессии появятся в темах сами.\n"
              "2. Ход — одно сообщение, оно обновляется: сколько идёт и что Claude делает сейчас. Итог — отдельным "
              "сообщением.\n"
              "3. ✋ Разрешение или ❓ вопрос Claude — кнопками. Окно на компьютере открыто одновременно: кто ответил "
              "первым, тот и решил.\n"
              "4. Новая задача — напиши в тему проекта или /projects → проект.\n"
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
              "• Text in a project topic — I'll ask where: one of the recent sessions or a new one. "
              "<code>/new text</code> — a new session right away.\n"
              "• 💻 The session is open in a VS Code tab with Pult's wrapper — your message appears right in the tab. "
              "🖥 Without the wrapper — I continue as a copy: same history, a separate session from there on.\n"
              "• A photo or file with a caption — Claude gets the path to the file.\n"
              "• /stop as a reply to a session started from here — interrupts the turn.",
        "ru": "<b>✍️ Писать Claude</b>\n\n"
              "• Ответ на любое сообщение сессии — продолжение этой сессии.\n"
              "• Текст в теме проекта — спрошу, куда: в одну из последних сессий или в новую. "
              "<code>/new текст</code> — сразу новая.\n"
              "• 💻 Сессия открыта во вкладке VS Code с обёрткой Пульта — сообщение появится прямо во вкладке. "
              "🖥 Без обёртки — продолжу копией: история та же, дальше отдельная сессия.\n"
              "• Фото или файл с подписью — Claude получит путь к файлу.\n"
              "• /stop ответом на сообщение сессии, запущенной отсюда, — прервать ход.",
    },
    "help.app": {
        "en": "<b>📱 The app</b>\n\nInside Telegram: every session on the computer, full transcripts with times, answers "
              "to Claude's questions, new tasks, subscription usage, settings.\n"
              "Open it with /app or the button in the pinned message.",
        "ru": "<b>📱 Приложение</b>\n\nВнутри Telegram: все сессии на компьютере, переписка целиком со временем, ответы на "
              "вопросы Claude, новая задача, расход подписки, настройки.\n"
              "Открыть — /app или кнопка в закреплённом сообщении.",
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
              "• Log: <code>~/Library/Logs/pult.log</code>\n\nA bug or an idea — /feedback.",
        "ru": "<b>🛠 Если что-то не так</b>\n\n"
              "• Бот молчит — <code>pult status</code> на компьютере: служба, связь с Telegram; "
              "<code>pult restart</code> перезапустит.\n"
              "• Нет сессий из VS Code — хуки выключены: <code>pult hooks on</code> и Reload Window.\n"
              "• Лента есть, а кнопок разрешений нет — Claude в режиме auto решает сам, это норма.\n"
              "• Сообщение не дошло во вкладку — вкладка запущена без обёртки (поможет Reload Window) или вышло "
              "обновление Claude Code: до проверки — копией.\n"
              "• Журнал: <code>~/Library/Logs/pult.log</code>\n\nОшибка или идея — /feedback.",
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
    "dur.s": {"en": "{n} s", "ru": "{n} с"},
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
    "ask.hint.one": {"en": "pick an option; your own answer — reply to this message",
                     "ru": "выбери вариант; свой ответ — ответом на это сообщение"},
    "ask.hint.many": {"en": "check the options and tap “Done”; your own answer — reply to this message",
                      "ru": "отметь варианты и нажми «Готово»; свой ответ — ответом на это сообщение"},

    # ----- daemon messages (pultd) -----
    "when.yesterday": {"en": "yesterday {hm}", "ru": "вчера {hm}"},
    "session.default": {"en": "session", "ru": "сессия"},
    "err.turn": {"en": "⚠️ The turn ended with an error: {err}", "ru": "⚠️ Ход закончился ошибкой: {err}"},
    "err.session": {"en": "⚠️ The session failed to start or crashed: <code>{err}</code>",
                    "ru": "⚠️ Сессия не запустилась или упала: <code>{err}</code>"},
    "topic.intro": {"en": "📂 <b>{name}</b> · <code>{path}</code>\nWrite here to start a new session in this project. "
                          "Reply to a session's message to continue that session.",
                    "ru": "📂 <b>{name}</b> · <code>{path}</code>\nПиши сюда — начну новую сессию в этом проекте. "
                          "Ответ на сообщение сессии — продолжение этой сессии."},
    "long.more": {"en": "\n<i>… {n} more characters</i>", "ru": "\n<i>… ещё {n} знаков</i>"},
    "btn.read_all": {"en": "Read in full", "ru": "Читать полностью"},
    "btn.details": {"en": "Details", "ru": "Подробнее"},
    "doc.caption": {"en": "in full — {n} characters", "ru": "целиком — {n} знаков"},
    "turn.running": {"en": "working {dur}", "ru": "работает {dur}"},
    "turn.done": {"en": "✔️ done in {dur}", "ru": "✔️ готово за {dur}"},
    "turn.stopped": {"en": "⏹ interrupted after {dur}", "ru": "⏹ прервано через {dur}"},
    "turn.you": {"en": "<i>You: {text}</i>", "ru": "<i>Ты: {text}</i>"},
    "vehi": {"en": "⏳ {head} has been working for {dur}", "ru": "⏳ {head} работает уже {dur}"},
    "vehi.muted": {"en": "\n<i>🔕 no more reminders — only the result will come</i>",
                   "ru": "\n<i>🔕 вех больше не будет — придёт только итог</i>"},
    "btn.mute": {"en": "🔕 Quiet until done", "ru": "🔕 Не беспокоить до конца"},
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
    "perm.reply_hint": {"en": "\n<i>or reply with text — Claude gets a refusal with your explanation</i>",
                        "ru": "\n<i>или ответь текстом — Claude получит отказ с твоим пояснением</i>"},
    "btn.approve": {"en": "✅ Approve", "ru": "✅ Утвердить"},
    "btn.reject_plan": {"en": "❌ Don't approve", "ru": "❌ Не утверждать"},
    "btn.allow": {"en": "✅ Allow", "ru": "✅ Разрешить"},
    "btn.deny": {"en": "❌ Deny", "ru": "❌ Отклонить"},
    "btn.always": {"en": "♾ Allow and don't ask again", "ru": "♾ Разрешить и больше не спрашивать"},
    "btn.done": {"en": "✅ Done", "ru": "✅ Готово"},
    "btn.new_session": {"en": "▶️ New session", "ru": "▶️ Новая сессия"},
    "btn.fork": {"en": "🔀 Continue as a copy", "ru": "🔀 Продолжить копией"},
    "btn.usage": {"en": "Usage", "ru": "Расход"},
    "where.tg": {"en": "Telegram", "ru": "Telegram"},
    "where.app": {"en": "the app", "ru": "приложения"},
    "dec.approved": {"en": "✅ approved from {where}", "ru": "✅ утверждён из {where}"},
    "dec.allowed": {"en": "✅ allowed from {where}", "ru": "✅ разрешено из {where}"},
    "dec.always": {"en": "♾ allowed and remembered", "ru": "♾ разрешено и запомнено"},
    "dec.denied_note": {"en": "❌ declined with a note: {text}", "ru": "❌ отказано с пояснением: {text}"},
    "dec.rejected_plan": {"en": "❌ not approved", "ru": "❌ не утверждён"},
    "dec.denied": {"en": "❌ declined from {where}", "ru": "❌ отклонено из {where}"},
    "note.decided": {"en": "already decided", "ru": "уже решено"},
    "note.unclear": {"en": "didn't understand the answer", "ru": "не понял ответ"},
    "note.denied": {"en": "no access", "ru": "нет доступа"},
    "note.pick_one": {"en": "check at least one option", "ru": "отметь хотя бы один вариант"},
    "note.stale": {"en": "this button is outdated", "ru": "кнопка устарела"},
    "note.stale_retry": {"en": "this button is outdated — repeat the command", "ru": "кнопка устарела — повтори команду"},
    "note.muted": {"en": "only the result until the turn ends", "ru": "до конца хода — только итог"},
    "note.bound": {"en": "topic bound to {name}", "ru": "тема привязана к {name}"},
    "note.starting_in": {"en": "starting in {name}", "ru": "запускаю в {name}"},
    "note.sending_to": {"en": "sending to {name}", "ru": "отправляю в {name}"},
    "note.new_session": {"en": "new session", "ru": "новая сессия"},
    "note.starting_copy": {"en": "starting a copy", "ru": "запускаю копию"},
    "result.empty": {"en": "_Claude finished without text._", "ru": "_Claude закончил без текста._"},
    "result.done_in": {"en": " · done in {dur}", "ru": " · готово за {dur}"},
    "result.done": {"en": " · done", "ru": " · готово"},
    "job.running": {"en": "⚙️ {cmd} · running {dur}", "ru": "⚙️ {cmd} · идёт {dur}"},
    "job.done.final": {"en": "✅ {cmd} · done in {dur}", "ru": "✅ {cmd} · готово за {dur}"},
    "job.done": {"en": "⚙️ {cmd} · ✔️ done in {dur}", "ru": "⚙️ {cmd} · ✔️ готово за {dur}"},
    "job.killed": {"en": "interrupted", "ru": "прервана"},
    "job.code": {"en": "error, code {code}", "ru": "ошибка, код {code}"},
    "job.fail.final": {"en": "❌ {cmd} · {why} after {dur}", "ru": "❌ {cmd} · {why}, через {dur}"},
    "job.fail": {"en": "⚙️ {cmd} · ✖ {why} after {dur}", "ru": "⚙️ {cmd} · ✖ {why}, через {dur}"},
    "job.vehi": {"en": "⏳ <b>{cmd}</b> has been running for {dur}", "ru": "⏳ <b>{cmd}</b> идёт уже {dur}"},
    "topic.bound": {"en": "📂 This topic is now bound to project <b>{name}</b> · <code>{path}</code>",
                    "ru": "📂 Тема привязана к проекту <b>{name}</b> · <code>{path}</code>"},
    "started.in": {"en": "▶️ Started a session in {title} — the turn and the result will be there.",
                   "ru": "▶️ Запустил сессию в теме {title} — ход и итог будут там."},
    "topic.link": {"en": "📂 Project topic {title} — write there to start a new session.",
                   "ru": "📂 Тема проекта {title} — пиши туда, начну новую сессию."},
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
    "private.elsewhere": {"en": "I don't read this private chat: I work in Pult's group, a topic per project — "
                                "write there.",
                          "ru": "Этот личный чат я не читаю: работаю в группе Пульта, тема на проект, — пиши туда."},
    "q.already": {"en": "This question is already decided.", "ru": "Этот вопрос уже решён."},
    "cmd.unknown": {"en": "I don't know this command. /help", "ru": "Не знаю такой команды. /help"},
    "where.ask": {"en": "Where should I send it? (💻 — open in a VS Code tab, I'll write right into it; 🖥 — open on "
                        "the computer, it'll go as a copy; reply to a session's message or <code>/new text</code> — no "
                        "question)",
                  "ru": "Куда отправить? (💻 — открыта во вкладке, напишу прямо в неё; 🖥 — открыта на компьютере, "
                        "пойдёт копией; ответ на сообщение сессии или <code>/new текст</code> — без этого вопроса)"},
    "err.no_folder": {"en": "I don't know which folder this session is in.", "ru": "Не знаю, в какой папке эта сессия."},
    "fork.offer": {"en": "This session is open on the computer (a VS Code tab or the terminal). Writing to it from here "
                         "would mix up the conversation. I can continue as a <b>copy</b>: the same history, a separate "
                         "session from there on.",
                   "ru": "Эта сессия открыта на компьютере (вкладка VS Code или терминал). Писать в неё отсюда нельзя — "
                         "переписка перемешается. Могу продолжить <b>копией</b>: вся история та же, дальше — "
                         "отдельная сессия."},
    "busy.driven": {"en": "{n} {sessions} from Telegram are already running — wait until one finishes.",
                    "ru": "Уже идут {n} {sessions} из Telegram — подожди, пока какая-нибудь закончит."},
    "tab.update": {"en": "🔄 Claude Code <b>{v}</b> is out. Writing from Telegram straight into VS Code tabs is off "
                         "on it until it's checked; until then, messages to open tabs go as a copy, as before.\n"
                         "After checking: <code>pult tab allow {v}</code> (see the README).",
                   "ru": "🔄 Вышло обновление Claude Code <b>{v}</b>. Писать из Telegram прямо во вкладки на нём пока "
                         "нельзя — сначала проверка. До неё сообщения в открытые вкладки уходят копией, как раньше.\n"
                         "После проверки: <code>pult tab allow {v}</code> (см. README)."},
    "status.head": {"en": "<b>On the computer now</b> · {state}", "ru": "<b>Сейчас на компьютере</b> · {state}"},
    "status.at_mac": {"en": "you're at the computer", "ru": "ты за компьютером"},
    "status.idle": {"en": "the computer has been idle for {dur}", "ru": "компьютер простаивает {dur}"},
    "status.none": {"en": "no open sessions", "ru": "открытых сессий нет"},
    "status.ask": {"en": "❓ waiting for an answer", "ru": "❓ ждёт ответа"},
    "status.work": {"en": "⏳ working", "ru": "⏳ работает"},
    "status.idle_sess": {"en": "💤 waiting for you", "ru": "💤 ждёт тебя"},
    "projects.open": {"en": "Projects with Claude sessions, most recent first. Tap one for a link to its topic.",
                      "ru": "Проекты с сессиями Claude, свежие сверху. Нажми — дам ссылку на тему."},
    "projects.new": {"en": "Which project should it run in?", "ru": "В каком проекте запустить?"},
    "projects.bind": {"en": "This topic isn't bound to a project yet. Pick a project — I'll bind the topic and start "
                            "a session.",
                      "ru": "Эта тема ещё не привязана к проекту. Выбери проект — привяжу тему и запущу сессию."},
    "projects.none": {"en": "No projects with Claude sessions found.", "ru": "Проектов с сессиями Claude не нашёл."},
    "sessions.where": {"en": "/sessions — inside a project topic.", "ru": "/sessions — в теме проекта."},
    "sessions.list": {"en": "Recent sessions (🖥 — open on the computer). Tap one — I'll show its last answer; reply to it "
                            "to continue.",
                      "ru": "Последние сессии (🖥 — открыта на компьютере). Нажми — покажу последний ответ, ответом на "
                            "него продолжишь."},
    "sessions.none": {"en": "No sessions.", "ru": "Сессий нет."},
    "card": {"en": "🧵 <b>{title}</b>\n{body}\n\n<i>reply to this message to continue the session</i>",
             "ru": "🧵 <b>{title}</b>\n{body}\n\n<i>ответь на это сообщение — продолжу сессию</i>"},
    "card.empty": {"en": "<i>no answers yet</i>", "ru": "<i>ответов нет</i>"},
    "stop.how": {"en": "/stop — as a reply to a message of a session started from Telegram. A turn in VS Code can "
                       "only be interrupted on the computer.",
                 "ru": "/stop — ответом на сообщение сессии, запущенной из Telegram. Ход в VS Code прерывается "
                       "только на компьютере."},
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
    "err.empty": {"en": "empty message", "ru": "пустое сообщение"},
    "err.no_folder_short": {"en": "I don't know the session's folder", "ru": "не знаю папку сессии"},
    "err.need_project_text": {"en": "a project and a text are needed", "ru": "нужны проект и текст"},
    "err.no_request": {"en": "no such request: {op}", "ru": "нет такого запроса: {op}"},

    # ----- the pult command in Terminal (plain text; the report itself is English only) -----
    "cli.usage": {
        "en": "Pult — Claude Code on your computer, from Telegram.\n\n"
              "  pult setup                    set up or change: the bot, you, the group, hooks\n"
              "  pult status                   what is on: the service, hooks, Telegram, tabs\n"
              "  pult start | stop | restart   the background service\n"
              "  pult hooks on | off           whether Pult sees sessions in VS Code and the terminal\n"
              "  pult tab                      writing from Telegram into open VS Code tabs\n"
              "  pult tab setup | on | off | allow VERSION\n"
              "  pult app [off]                the web app on your own server\n"
              "  pult run -- COMMAND           run a command; its start, progress and end go to Telegram\n"
              "  pult report                   versions and state for a bug report (no tokens, IDs or messages)\n"
              "  pult uninstall                remove Pult from this computer\n\n"
              "Hooks and the tab wrapper are picked up when a session starts: after changing them, run Reload Window "
              "in VS Code.",
        "ru": "Пульт — Claude Code на твоём компьютере из Telegram.\n\n"
              "  pult setup                    настроить или поменять: бот, ты, группа, хуки\n"
              "  pult status                   что включено: служба, хуки, Telegram, вкладки\n"
              "  pult start | stop | restart   фоновая служба\n"
              "  pult hooks on | off           видит ли Пульт сессии в VS Code и терминале\n"
              "  pult tab                      запись из Telegram в открытые вкладки VS Code\n"
              "  pult tab setup | on | off | allow ВЕРСИЯ\n"
              "  pult app [off]                веб-приложение на своём сервере\n"
              "  pult run -- КОМАНДА           выполнить команду; старт, ход и конец — в Telegram\n"
              "  pult report                   версии и состояние для сообщения об ошибке (без токенов, ID и переписки)\n"
              "  pult uninstall                удалить Пульт с этого компьютера\n\n"
              "Хуки и обёртка вкладок подхватываются при запуске сессии: после их смены — Reload Window в VS Code.",
    },
    "cli.yn.y": {"en": "[Y/n]", "ru": "[Д/н]"},
    "cli.yn.n": {"en": "[y/N]", "ru": "[д/Н]"},
    "cli.backup": {"en": "backup: {path}", "ru": "копия: {path}"},
    "cli.not_installed": {"en": "Pult isn't installed: ./install.sh in the Pult folder.",
                          "ru": "Пульт не установлен: ./install.sh в папке Пульта."},
    "cli.lang.en": {"en": "English", "ru": "английский"},
    "cli.lang.ru": {"en": "Russian", "ru": "русский"},
    "cli.install.done": {"en": "Pult {version} is installed in {home}.", "ru": "Пульт {version} установлен в {home}."},
    "cli.install.path": {
        "en": "The command is {path}, but ~/.local/bin isn't in PATH. Add it, then open a new Terminal window:\n"
              "  echo 'export PATH=\"$HOME/.local/bin:$PATH\"' >> ~/.zshrc",
        "ru": "Команда — {path}, но ~/.local/bin нет в PATH. Добавь и открой новое окно Терминала:\n"
              "  echo 'export PATH=\"$HOME/.local/bin:$PATH\"' >> ~/.zshrc",
    },
    "cli.install.taken": {"en": "{path} already belongs to another program — left as is. Pult's command: {ctl}",
                          "ru": "{path} уже занят другой программой — не трогаю. Команда Пульта: {ctl}"},
    "cli.install.next": {"en": "Next, set it up in Terminal: pult setup", "ru": "Дальше — настройка, в Терминале: pult setup"},
    "cli.svc.busy": {
        "en": "Pult holds a session started from Telegram. A restart interrupts a running turn (an idle session "
              "continues later by itself). Restart now?",
        "ru": "У Пульта открыта сессия, запущенная из Telegram. Перезапуск оборвёт идущий ход (простаивающая сессия "
              "потом продолжится сама). Перезапустить сейчас?",
    },
    "cli.svc.kept": {"en": "Not restarted.", "ru": "Не перезапускаю."},
    "cli.svc.started": {"en": "✓ Pult is running (service {label}).", "ru": "✓ Пульт работает (служба {label})."},
    "cli.svc.not_started": {"en": "✗ Pult didn't start — see the log: {log}",
                            "ru": "✗ Пульт не запустился — смотри журнал: {log}"},
    "cli.svc.stopped": {"en": "Pult is stopped. Start it: pult start", "ru": "Пульт остановлен. Запустить: pult start"},
    "cli.svc.not_ready": {"en": "Pult isn't set up yet: pult setup", "ru": "Пульт ещё не настроен: pult setup"},
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
              "• the web app (needs your own server) — deploy/relay/README.md, then pult app\n• all commands — pult help",
        "ru": "\nПо желанию:\n• писать из Telegram прямо в открытые вкладки VS Code — pult tab setup\n"
              "• веб-приложение (нужен свой сервер) — deploy/relay/README.md, затем pult app\n• все команды — pult help",
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
    "cli.hooks.reload": {"en": "New sessions pick this up; in VS Code: Cmd+Shift+P → Developer: Reload Window.",
                         "ru": "Подхватят новые сессии; в VS Code: Cmd+Shift+P → Developer: Reload Window."},
    "cli.hooks.no_hook": {"en": "No {path} — run ./install.sh first.", "ru": "Нет {path} — сначала ./install.sh."},
    "cli.hooks.unreadable": {
        "en": "{path} mentions Pult's hook but isn't plain JSON (comments or a broken edit) — I won't touch it. Remove "
              "the entries with pult_hook.py by hand, then run the command again.",
        "ru": "В {path} есть хук Пульта, но файл — не чистый JSON (комментарии или сломанная правка) — не трогаю. "
              "Убери записи с pult_hook.py вручную и повтори команду.",
    },
    "cli.st.daemon": {"en": "daemon:", "ru": "демон:"},
    "cli.st.running": {"en": "{state}, pid {pid}", "ru": "{state}, pid {pid}"},
    "cli.st.not_loaded": {"en": "not loaded ({label})", "ru": "не загружен ({label})"},
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
        "en": "Add this line to the VS Code settings (Cmd+Shift+P → Preferences: Open User Settings (JSON)):\n"
              "  {line}\nthen Cmd+Shift+P → Developer: Reload Window. Turn it off any time: pult tab off.",
        "ru": "Добавь строку в настройки VS Code (Cmd+Shift+P → Preferences: Open User Settings (JSON)):\n"
              "  {line}\nпотом Cmd+Shift+P → Developer: Reload Window. Выключить в любой момент: pult tab off.",
    },
    "cli.tab.unverified": {
        "en": "Your Claude Code extension is {v}: the wrapper hasn't been checked on it and stays out of the way "
              "until `pult tab allow {v}` (after tests/probe_tab.py, or at your own risk).",
        "ru": "У тебя расширение Claude Code {v}: обёртка на нём не проверялась и ни во что не вмешивается до "
              "`pult tab allow {v}` (после tests/probe_tab.py или на свой риск).",
    },
    "cli.tab.copy": {"en": "Copy the line to the clipboard?", "ru": "Скопировать строку в буфер обмена?"},
    "cli.tab.copied": {"en": "Copied.", "ru": "Скопировано."},
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
    "cli.un.done": {
        "en": "Pult is removed. The bot and the group stay in Telegram: @BotFather → /deletebot if you don't need the bot.",
        "ru": "Пульт удалён. Бот и группа остаются в Telegram: @BotFather → /deletebot, если бот не нужен.",
    },

    # ----- bot command menu -----
    "cmd.help": {"en": "how to use, turn on and off", "ru": "как пользоваться, включить и выключить"},
    "cmd.mode": {"en": "notifications: at the computer / on the phone", "ru": "уведомления: за компьютером / с телефоном"},
    "cmd.desk": {"en": "I'm at the computer — everything silent", "ru": "я за компьютером — всё беззвучно"},
    "cmd.phone": {"en": "I'm on the phone — with sound", "ru": "я с телефоном — со звуком"},
    "cmd.auto": {"en": "sound when I'm away from the computer", "ru": "звук, когда отошёл от компьютера"},
    "cmd.status": {"en": "what's open on the computer", "ru": "что открыто на компьютере"},
    "cmd.sessions": {"en": "recent sessions of the project", "ru": "последние сессии проекта"},
    "cmd.projects": {"en": "projects — open a topic", "ru": "проекты — открыть тему"},
    "cmd.stop": {"en": "interrupt a turn (as a reply)", "ru": "прервать ход (ответом)"},
    "cmd.app": {"en": "open the app", "ru": "открыть приложение"},
    "cmd.feedback": {"en": "report a bug or suggest an idea", "ru": "сообщить об ошибке или идее"},
}

COMMANDS = ("help", "mode", "desk", "phone", "auto", "status", "sessions", "projects", "stop", "app", "feedback")

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
