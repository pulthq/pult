// Pult app: user-facing strings in English and Russian. One key — both languages side by side.
// The language comes from Telegram right away and then from Pult's own setting (the bot and the app share it).

const S = {
  // connection
  "conn.lost": { en: "connection lost", ru: "связь прервалась" },
  "conn.nomac": { en: "no connection to the computer", ru: "нет связи с компьютером" },
  "conn.timeout": { en: "the computer didn't answer", ru: "компьютер не ответил" },
  "banner.connecting": { en: "Connecting…", ru: "Подключаюсь…" },
  "banner.offline": { en: "No connection to the server — reconnecting…", ru: "Нет связи с сервером — переподключаюсь…" },
  "banner.auth": { en: "The computer is checking the login…", ru: "Компьютер проверяет вход…" },
  "banner.nomac": { en: "The computer is offline: Pult is off, the computer is asleep or has no network.",
    ru: "Компьютер не на связи: Пульт на нём выключен, компьютер спит или нет сети." },
  "banner.denied": { en: "No access: Pult opens only for its owner.", ru: "Нет доступа: Пульт открывается только у владельца." },
  loading: { en: "Loading…", ru: "Загружаю…" },
  failed: { en: "didn't work", ru: "не вышло" },

  // time and numbers
  "dur.s": { en: "{n} s", ru: "{n} сек" },
  "dur.m": { en: "{n} min", ru: "{n} мин" },
  "dur.h": { en: "{n} h", ru: "{n} ч" },
  today: { en: "Today, {d}", ru: "Сегодня, {d}" },
  yesterday: { en: "Yesterday, {d}", ru: "Вчера, {d}" },
  "ago.now": { en: "just now, {hm}", ru: "только что, {hm}" },
  "ago.min": { en: "{n} min ago, {hm}", ru: "{n} мин назад, {hm}" },
  "ago.yesterday": { en: "yesterday {hm}", ru: "вчера {hm}" },
  weekdays: { en: "Sun Mon Tue Wed Thu Fri Sat", ru: "вс пн вт ср чт пт сб" },
  "reset.at": { en: "at {hm} (in {left})", ru: "в {hm} (через {left})" },
  "kilo.m": { en: "{n}M", ru: "{n} млн" },
  "kilo.k": { en: "{n}k", ru: "{n} тыс." },

  // questions, permissions, plans
  done: { en: "Done", ru: "Готово" },
  "ask.own": { en: "Your own answer…", ru: "Свой ответ…" },
  "ask.answer": { en: "Answer", ru: "Ответить" },
  "req.plan": { en: "📋 Claude proposes a plan", ru: "📋 Claude предлагает план" },
  "req.perm": { en: "✋ Claude asks for permission", ru: "✋ Claude спрашивает разрешение" },
  plan: { en: "Plan", ru: "План" },
  approve: { en: "Approve", ru: "Утвердить" },
  allow: { en: "Allow", ru: "Разрешить" },
  "reject.plan": { en: "Don't approve", ru: "Не утверждать" },
  deny: { en: "Deny", ru: "Отклонить" },
  always: { en: "Allow and don't ask again", ru: "Разрешить и больше не спрашивать" },
  "plan.notes": { en: "Notes on the plan…", ru: "Замечания к плану…" },
  "deny.note": { en: "Decline with a note…", ru: "Отклонить с пояснением…" },
  "tell.claude": { en: "What to tell Claude", ru: "Что сказать Claude" },
  send: { en: "Send", ru: "Отправить" },

  // sessions
  bg: { en: "⚙️ In the background: {list}", ru: "⚙️ В фоне: {list}" },
  "st.ask": { en: "waiting for you", ru: "ждёт ответа" },
  "st.work": { en: "working {dur}", ru: "работает {dur}" },
  "st.bg": { en: "in the background", ru: "в фоне" },
  "st.open": { en: "open", ru: "открыта" },
  "mode.auto": { en: "🔄 Auto", ru: "🔄 Авто" },
  "mode.mac": { en: "💻 At my computer", ru: "💻 За компьютером" },
  "mode.phone": { en: "📱 On my phone", ru: "📱 С телефоном" },
  "mode.auto.btn": { en: "🔄 Auto", ru: "🔄 Авто" },
  "mode.mac.btn": { en: "💻 Computer", ru: "💻 Компьютер" },
  "mode.phone.btn": { en: "📱 Phone", ru: "📱 Телефон" },
  "mode.mac.short": { en: "everything silent", ru: "всё беззвучно" },
  "mode.phone.short": { en: "with sound", ru: "со звуком" },
  "mode.auto.about": { en: "Sound if you've been away from the computer for 2+ minutes or the session was started from the phone",
    ru: "Звук, если ты отошёл от компьютера больше чем на 2 мин или сессия запущена с телефона" },
  "mode.mac.about": { en: "Everything arrives silently — nothing is lost", ru: "Всё приходит беззвучно — ничего не теряется" },
  "mode.phone.about": { en: "Results, questions and permission requests — with sound", ru: "Итоги, вопросы и разрешения — со звуком" },
  "mac.away": { en: "You've been away from the computer for {dur}", ru: "Ты отошёл от компьютера {dur}" },
  "mac.here": { en: "You're at the computer", ru: "Ты за компьютером" },
  "mac.away.short": { en: "away {dur}", ru: "отошёл {dur}" },
  "mac.here.short": { en: "at the computer", ru: "за компьютером" },
  "home.pending": { en: "Waiting for an answer · {n}", ru: "Ждут ответа · {n}" },
  "home.live": { en: "Working · {n}", ru: "Работают · {n}" },
  "home.quiet": { en: "All quiet: no session is working or waiting.", ru: "Сейчас тихо: ни одна сессия не работает и ничего не ждёт." },
  "home.open": { en: "Open on the computer · {n}", ru: "Открыты на компьютере · {n}" },
  "home.jobs": { en: "Tasks without Claude", ru: "Задачи без Claude" },
  "home.recent": { en: "Recent results", ru: "Недавние итоги" },
  "home.took": { en: "in {dur}", ru: "за {dur}" },
  "job.running": { en: "running {dur}", ru: "идёт {dur}" },
  "job.killed": { en: "interrupted", ru: "прервана" },
  "job.code": { en: "code {code}", ru: "код {code}" },
  "job.noout": { en: "no output yet", ru: "вывода пока нет" },

  // settings
  settings: { en: "Settings", ru: "Настройки" },
  notifications: { en: "Notifications", ru: "Уведомления" },
  "vehi": { en: "Long-turn reminders", ru: "Вехи долгих ходов" },
  "vehi.about": { en: "At 10, 30, 60 min and every hour — while sound is on", ru: "10, 30, 60 мин и каждый час — пока звук включён" },
  "where": { en: "Where you are", ru: "Где ты" },
  language: { en: "Language", ru: "Язык" },
  status: { en: "Status", ru: "Состояние" },
  "status.pult": { en: "Pult {v} · {mac}", ru: "Пульт {v} · {mac}" },
  "status.tg": { en: "Telegram — {how}; app server — connected", ru: "Telegram — {how}; сервер приложения — на связи" },
  "tg.proxy": { en: "via proxy", ru: "через прокси" },
  "tg.direct": { en: "direct", ru: "напрямую" },
  "status.hooks": { en: "Hooks in sessions: {n} events", ru: "Хуки в сессиях: {n} событий" },
  "status.nohooks": { en: "Hooks in sessions: off — turn on: pultctl hooks on", ru: "Хуки в сессиях: выключены — включить: pultctl hooks on" },
  "log": { en: "Pult's log — last {n} lines", ru: "Журнал Пульта — последние {n} строк" },

  // projects and sessions
  projects: { en: "Projects", ru: "Проекты" },
  "project.new": { en: "New task in this project", ru: "Новая задача в этом проекте" },
  sessions: { en: "Sessions", ru: "Сессии" },
  "pj.open": { en: "{n} open", ru: "открыто {n}" },
  "pj.work": { en: "{n} working", ru: "работает {n}" },
  "pj.ask": { en: "{n} waiting", ru: "ждёт {n}" },
  "sessions.none": { en: "No sessions in this project yet. Start one with the button above.", ru: "Сессий в этом проекте пока нет. Начни первую кнопкой выше." },
  "projects.none": { en: "No projects with Claude Code sessions yet. Open one in VS Code or a terminal and it will appear here.",
    ru: "Проектов с сессиями Claude Code пока нет. Открой любой в VS Code или терминале, и он появится здесь." },
  "open.mac": { en: "open on the computer", ru: "открыта на компьютере" },
  "fork.ask": { en: "This session is open in a tab on the computer — writing to it from here would mix up the conversation.\n\nContinue as a copy? Same history, a separate session from there on.",
    ru: "Эта сессия открыта на компьютере во вкладке — писать в неё отсюда нельзя, переписка перемешается.\n\nПродолжить копией? История та же, дальше — отдельная сессия." },
  "fork.started": { en: "Started a copy — it'll appear in the project's session list.", ru: "Запустил копию — она появится в списке сессий проекта." },
  "sess.starting": { en: "The session is starting — the conversation will appear in a few seconds.",
    ru: "Сессия запускается — переписка появится через несколько секунд." },
  context: { en: "context {n}", ru: "контекст {n}" },
  "context.pct": { en: " · {pct} % of {win}", ru: " · {pct} % из {win}" },
  "turn.stats": { en: "turn: {n} {requests} · wrote {out} tokens", ru: "ход: {n} {requests} · написано {out} токенов" },
  "turn.think": { en: " (thinking {n})", ru: " (раздумья {n})" },
  earlier: { en: "Show earlier", ru: "Показать раньше" },
  "earlier.loading": { en: "Loading earlier…", ru: "Загружаю раньше…" },
  working: { en: "⏳ working…", ru: "⏳ работает…" },
  write: { en: "Message…", ru: "Сообщение…" },
  "dest.tab": { en: "💻 VS Code tab", ru: "💻 вкладка VS Code" },
  "dest.copy": { en: "🖥 goes as a copy", ru: "🖥 уйдёт копией" },
  "ctx.pct": { en: "{pct} % of {win}", ru: "{pct} % из {win}" },
  model: { en: "Model", ru: "Модель" },
  close: { en: "Close", ru: "Закрыть" },
  effort: { en: "Effort", ru: "Раздумья" },
  "model.default": { en: "Default (settings)", ru: "По умолчанию (из настроек)" },
  "effort.default": { en: "Default", ru: "По умолчанию" },
  "effort.low": { en: "Low", ru: "Мало" },
  "effort.medium": { en: "Medium", ru: "Средне" },
  "effort.high": { en: "High", ru: "Много" },
  "effort.xhigh": { en: "Extra high", ru: "Очень много" },
  "effort.max": { en: "Max", ru: "Максимум" },
  "effort.is": { en: "{e} effort", ru: "раздумья: {e}" },
  "effort.reload": { en: "Effort can be switched from here after Reload Window in VS Code: this tab runs an older Pult wrapper.",
    ru: "Раздумья можно будет менять отсюда после Reload Window в VS Code: во вкладке старая обёртка Пульта." },
  "pick.default": { en: "Default", ru: "По умолчанию" },
  "effort.tab": { en: "VS Code keeps showing the effort from its settings; the dots here show the real one.",
    ru: "VS Code продолжает показывать раздумья из своих настроек; настоящие — точки здесь." },
  "pick.default.note": { en: "Default is what Claude Code's settings say.", ru: "«По умолчанию» — как в настройках Claude Code." },
  "model.pick": { en: "Model and effort", ru: "Модель и раздумья" },
  "model.next": { en: "The next turn will use it.", ru: "Со следующего хода." },
  "model.later": { en: "Applies when the session is continued from here.", ru: "Вступит в силу при продолжении отсюда." },
  "model.tab": { en: "VS Code shows the new model after its next reply.", ru: "VS Code покажет новую модель после следующего ответа." },
  "model.reload": { en: "This tab started with an older Pult wrapper: Reload Window in VS Code, then the model can be switched from here.",
    ru: "Вкладка запущена со старой обёрткой Пульта: Reload Window в VS Code, и модель можно будет менять отсюда." },
  "model.fixed": { en: "This session is open on the computer without Pult's wrapper: its model is chosen there.",
    ru: "Сессия открыта на компьютере без обёртки Пульта: модель выбирается там." },
  "ex.tab": { en: "Your message will appear in the open VS Code tab on the computer and start a turn there.",
    ru: "Сообщение появится в открытой вкладке VS Code на компьютере и начнёт ход там." },
  "ex.copy": { en: "This session is open on the computer, so writing into it from here would mix up the conversation. Pult continues it as a copy: the same history, a separate session from there on.",
    ru: "Эта сессия открыта на компьютере, и писать в неё отсюда нельзя — переписка перемешается. Пульт продолжит её копией: история та же, дальше отдельная сессия." },
  "ex.session": { en: "Your message goes to this session; Pult runs it on the computer.", ru: "Сообщение уйдёт в эту сессию, её ведёт Пульт на компьютере." },
  "ex.model": { en: "Model: {m}.", ru: "Модель: {m}." },
  "ex.effort": { en: "Effort: {e} — how long the model thinks before it answers.", ru: "Раздумья: {e} — сколько модель думает перед ответом." },
  "ex.ctx": { en: "Context: {n} tokens{win} — everything the model re-reads on each request. Near the limit, Claude Code compacts the conversation.",
    ru: "Контекст: {n} токенов{win} — всё, что модель перечитывает на каждом запросе. Ближе к пределу Claude Code сжимает переписку." },
  "ex.ctx.win": { en: " of {w} ({pct} %)", ru: " из {w} ({pct} %)" },
  "new.msgs": { en: "↓ new", ru: "↓ новое" },
  "pin.you": { en: "You", ru: "Ты" },
  "pin.goto": { en: "Go to the message", ru: "К сообщению" },
  "to.bottom": { en: "To the bottom", ru: "В самый низ" },
  stop: { en: "Stop", ru: "Стоп" },
  attach: { en: "Attach a screenshot", ru: "Приложить снимок" },
  "attach.remove": { en: "Remove", ru: "Убрать" },
  "attach.failed": { en: "Couldn't read the picture", ru: "Не удалось прочитать картинку" },
  "att.file": { en: "📎 file", ru: "📎 файл" },
  "mid.turn": { en: "during the turn · ", ru: "во время хода · " },

  // new task
  "new.title": { en: "New task", ru: "Новая задача" },
  "new.project": { en: "Project", ru: "Проект" },
  "new.pick": { en: "— pick —", ru: "— выбери —" },
  "new.what": { en: "What to do", ru: "Что сделать" },
  "new.placeholder": { en: "A task for Claude…", ru: "Задача для Claude…" },
  "new.start": { en: "Start", ru: "Запустить" },
  "new.about": { en: "A new Claude Code session in the project's folder, as in a VS Code tab. The turn and the result — here and in the project's topic.",
    ru: "Новая сессия Claude Code в папке проекта, как во вкладке VS Code. Ход и итог — здесь и в теме проекта." },

  // usage
  usage: { en: "Usage", ru: "Расход" },
  "usage.failed": { en: "Usage not received: {err}", ru: "Расход не получен: {err}" },
  "usage.plan": { en: "Plan: {plan}", ru: "Подписка {plan}" },
  "usage.reset": { en: "resets {when}", ru: "сброс {when}" },
  "usage.week": { en: "This week: {list}", ru: "За неделю: {list}" },
  "usage.extra": { en: "Extra usage: {used} of {limit} {cur}", ru: "Доп. расход: {used} из {limit} {cur}" },
  refreshing: { en: "Refreshing…", ru: "Обновляю…" },
  refresh: { en: "Refresh", ru: "Обновить" },
  "usage.updated": { en: "Updated {ago}. Sound warnings go to General at 80 % and 95 %.",
    ru: "Обновлено {ago}. Предупреждения со звуком — в «Общей» на 80 % и 95 %." },
  "today.title": { en: "Today by project", ru: "Сегодня по проектам" },
  "today.row": { en: "{n} {requests} · wrote {out} · read {read}", ru: "{n} {requests} · написано {out} · прочитано {read}" },
  "today.about": { en: "Share — by tokens written. “Read” is context: the model re-reads it on every request.",
    ru: "Доля — по написанным токенам. «Прочитано» — контекст: модель перечитывает его на каждом запросе." },

  // tabs
  "tab.home": { en: "Home", ru: "Главная" },
  "tab.projects": { en: "Projects", ru: "Проекты" },
  "tab.usage": { en: "Usage", ru: "Расход" },
};

// plural forms: English — one/other, Russian — one/few/many
const P = {
  step: { en: ["step", "steps"], ru: ["шаг", "шага", "шагов"] },
  request: { en: ["request", "requests"], ru: ["запрос", "запроса", "запросов"] },
};

export let LANG = "en";
export const setLang = (l) => { LANG = l === "ru" ? "ru" : "en"; document.documentElement.lang = LANG; };
export const locale = () => (LANG === "ru" ? "ru-RU" : "en-GB");

export function t(key, vars) {
  const v = S[key] || {};
  let s = v[LANG] || v.en || key;
  if (vars) for (const k in vars) s = s.split("{" + k + "}").join(vars[k]);
  return s;
}

export function plural(n, key) {
  const f = (P[key] || {})[LANG] || (P[key] || {}).en || [key, key];
  n = Math.abs(n);
  if (LANG !== "ru") return n === 1 ? f[0] : f[1];
  return n % 10 === 1 && n % 100 !== 11 ? f[0] : n % 10 >= 2 && n % 10 <= 4 && (n % 100 < 12 || n % 100 > 14) ? f[1] : f[2];
}

// “name” in English, «name» in Russian
export const q = (s) => (LANG === "ru" ? "«" + s + "»" : "“" + s + "”");
