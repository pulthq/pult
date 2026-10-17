# Changelog

Versions 0.x come before the first public release. Newest first.

## 0.9.9 — 2026-10-18

- The effort level of a session can be switched from the phone, next to the model: one menu with two columns,
  Model and Effort, that stays open while you pick. A session Pult runs switches at once; a VS Code tab with
  Pult's wrapper switches for that tab only, without touching Claude Code's settings (`apply_flag_settings`,
  checked with a probe on 2.1.301: the next request runs at the new level, "Default" goes back to the settings).
  Open tabs pick it up after Reload Window.
- The status under the message field is two steady lines: the model with its effort as five dots (a tap opens the
  menu), then where the message goes and the context gauge. Before, the pieces wrapped unevenly on a narrow phone
  and the model name stood out of the line.
- Scrolled up, your own message stays pinned at the top of the session screen — the nearest one above what is on
  screen, two lines of it; a tap shows it in full with its pictures and a way back to it.
- Earlier history loads by itself as you scroll up, and what you are reading stays in place; no "Show earlier"
  button to hunt for.
- The tab wrapper takes any control request from Pult (`op: control`), so new switches won't need another Reload
  Window; its log can be redirected with `PULT_TAB_LOG`.
- After an update the app no longer mixes new and old files: every module it imports gets the release's `?v=`
  through an import map, and app files are revalidated on each open. Before, Telegram kept an old dictionary under
  a new app and showed string keys instead of words.
- A column of the model menu that can't switch here (a tab with an older wrapper) still answers a tap: the reason
  under the columns lights up.

## 0.9.8 — 2026-10-18

- The status under the message field wraps instead of being cut off on a narrow phone, and a tap on it explains
  in plain words where the message goes, which model this is and what the context number means.
- “↓” and the auto-scroll land at the very bottom, with the last message fully above the composer.
- The model of a session from Telegram can be picked from the phone: in the new-task form (with the effort level)
  and, for a session Pult runs, by a tap on the model name under the message field — a running session switches
  at once, a resting one starts with the choice next time. A VS Code tab with Pult's wrapper switches too: the
  wrapper sends the process the same request the tab's own picker ends in (checked with a probe on 2.1.301). Open
  tabs pick the wrapper change up after Reload Window.
- The explanation of the status line opens as a sheet of the app's own, whatever its length: Telegram's alert
  box shows nothing beyond 256 characters.
- "Working 14 s" ticks every second on Home and in a session, and the working chip pulses green. In Russian,
  seconds read "сек" instead of "с".
- The model menu closes with a tap outside, its ×, the system back gesture or Telegram's Back — like a picture
  opened full screen.
- After Pult restarts in the middle of a turn, the turn's time counts from your prompt, not from the first step
  Pult happened to see; milestones already past don't fire in a burst.

## 0.9.7 — 2026-10-18

- The context gauge sits by the message field on the session screen, always in view, next to the model name — as
  in VS Code. A session that hasn't finished a turn since the update borrows the window size known for its model.
- A tap on a picture in the chat opens it full screen; a tap, the system back gesture or Telegram's Back closes it
  and keeps the conversation open. The message field shrinks back to one line
  after sending, and the page leaves room for the composer whatever its height — the end of the conversation no
  longer hides under it.
- A message that reached Claude in the middle of its turn (written while it was busy) now shows in the app's chat
  as your message, marked "during the turn". Claude Code keeps such messages apart from ordinary ones and its own
  tab doesn't show them.
- The composer is laid out like a chat's: the message field on top, one line of controls under it — the paperclip,
  where the text goes (the VS Code tab, or a copy), the model and the context gauge, Stop, Send. The field's hint is
  one word. Scrolled up more than a screen, a “↓” button takes you straight to the bottom; it says “↓ new” when
  messages arrived meanwhile.
- The project list shows what is going on in each project: how many sessions are open, working and waiting for an
  answer; projects with activity come first, and the list updates live.
- Several pictures in one message sit in a row as square thumbnails. The Home strip says "away 1 h 7 min" in
  short, so the time fits. The tab bar no longer stays in English when the language arrives before the app has
  subscribed to it.

## 0.9.6 — 2026-10-18

- The app's composer takes pictures: a paperclip on the session screen and in the new-task form. A screenshot is
  shrunk on the phone (JPEG, up to 1600 px) and saved on the computer next to the attachments from Telegram, and
  Claude gets its path. Up to three per message; anything that isn't a picture is dropped. In the app's chat the
  owner's message shows the picture itself (tap to enlarge), not the path Claude got; in Telegram the turn says
  "You: “deploy it” 📎 picture". A link to a file whose name is its path is shown once, as code.
- The session screen shows the context the way VS Code does: `context 183k · 92 % of 200k`. The window size comes
  from each turn's result (`modelUsage`) — the tab wrapper reads it for VS Code tabs, the SDK stream for sessions
  from Telegram — and the percentage divides by the same usable part VS Code divides by. Open tabs pick the wrapper
  change up after Reload Window.
- A message written from Telegram into a VS Code tab where Claude is busy: Claude Code reads it in the middle of
  its turn and the tab doesn't show it as a separate message (extension 2.1.301). The turn's result now replies to
  that message in Telegram, so the answer finds the question; the help and the README say how this works.

## 0.9.5 — 2026-10-17

The front page, rewritten for a stranger.

- README (English and Russian): what Pult is in one sentence, then "An hour with Pult" — six steps from leaving
  the computer to coming back; the feature list is shorter and the web app has a section of its own.
- A picture of a project topic — the result, a running turn with Claude's words, a permission request with its
  buttons — drawn from the daemon's real output on the made-up project of the test stand (`tools/chat_shot.py`).
  Not a Telegram screenshot: the README never shows real projects.
- A release badge. `tools/shot.py` can cut a picture at an element's bottom edge (`SHOT_FIT`).

## 0.9.4 — 2026-10-17

A usability pass over the chat and the app: the same words and icons everywhere, less noise, and two commands that
work straight from the command menu.

- A turn message starts with its state: `⏳ title · working 6 min`, then `✔️ title · done in 6 min` or
  `⏹ title · interrupted after 6 min`; `pult run` tasks follow the same pattern. Under a minute the seconds aren't
  counted aloud.
- The "which session?" question is short, with a one-line legend (💻 a VS Code tab · 🖥 open on the computer ·
  📱 from Telegram · ▫️ closed); the session buttons read `💻 title · 14:05`, in that question and in `/sessions`.
- Pult no longer posts "→ session" after every text in a topic — only the first time a topic picks a session by
  itself. The reaction on your message and the turn replying to it say where the text went.
- A reply to your own message continues the same session; an idle session from Telegram reacts 👀 at once.
- `/new` on its own (a tap in the command menu): the next text in the topic starts a new session. `/stop` on its
  own in a project topic interrupts the topic's current session started from Telegram.
- The command menu is ordered by use and includes `/new`; the mode buttons in the pinned panel are short enough to
  fit one row on a phone (🔄 Auto · 💻 Computer · 📱 Phone).
- Texts that still said "write here to start a new session" (the topic card, `/projects`, help) describe the
  current rules; the private chat with the bot gets a button into the group.
- The app: Home opens with a one-line strip — where you are, and the settings gear — instead of a three-button
  switch; the session screen links to its project and says "as a copy" in the message field when the session is
  open on the computer; sentence-case section headers, touch feedback, a neutral palette outside Telegram. The tab
  bar no longer stays in English when a screen learns the language first.

## 0.9.3 — 2026-10-17

Text in a project topic no longer asks "where to?" every time.

- Each topic has a current session: the one you chose last — with a button, a reply to its message or `/new`.
  Plain text in the topic goes there until the session closes or after 2 hours of quiet in the topic.
- With no current session, text goes to the project's only session that can be written into right now (a VS Code
  tab with Pult's wrapper, or a session started from Telegram). With several, Pult asks once and remembers.
- Pult answers "→ «session»" so you see where the text went, and the topic's pinned card starts with
  "🎯 Now: «session»".

## 0.9.2 — 2026-10-17

- Every project topic gets its pinned 📱 Pult card when Pult starts, not only once Pult writes there. A topic
  Telegram refuses (deleted) is remembered and not tried again on every start.

## 0.9.1 — 2026-10-17

The app is one tap away. Telegram puts an app button next to the message field only in a private chat with the
bot, so Pult adds one there and pins one at the top of each project topic.

- Each project topic gets a pinned card: the topic's intro with a 📱 Pult button that opens the app on that
  project's screen. Telegram shows the button right in the topic's pinned bar. A new topic gets it at once; a topic
  from before gets it the first time Pult writes there, so the group isn't flooded with pins. When the language or
  the app's address changes, the cards are edited, not posted again. Without the app, topics stay as they were.
- Your private chat with the bot gets a Pult button next to the message field. Without the app, Telegram's own
  command list stays there.
- The app opens a project's screen (`startapp=p_<project>`) or the list of projects (`startapp=projects`).
- `/help` lists every way to open the app.

## 0.9.0 — 2026-10-17

Pult runs on Linux (stage K1). Tested on Ubuntu 24.04 (arm64): the installer, the setup wizard with a real bot,
a Claude Code session in a terminal with a permission answered from Telegram, a session started from Telegram,
`pult run`, the tab wrapper with the Linux build of the Claude Code extension 2.1.301, removal. Windows is next.

- `./install.sh` works on Linux. It looks for Python 3.10+ in PATH and, when the venv module is missing (Debian,
  Ubuntu), says which package to install.
- The service on Linux is a systemd user service (`~/.config/systemd/user/pult.service`, `Restart=always`), started
  at login. Over SSH or on a server, the installer reminds you about `sudo loginctl enable-linger $USER`, so Pult
  keeps running after you log out. Without systemd user services (a container, WSL without systemd), it says so
  and how to run the daemon yourself.
- Logs on Linux: `~/.local/state/pult/pult.log` and `pult-tab.log`; the bot's help shows this system's log.
- VS Code settings are looked for on Linux too (`~/.config/Code/User`, forks, Flatpak) and on a server VS Code
  reaches through Remote-SSH (`~/.vscode-server/data/Machine`). `pult tab setup` tells where the line goes in a
  remote window. The Claude Code extension's version is read from `~/.vscode-server/extensions` as well.
- Whether you're away from the computer on Linux comes from GNOME, KDE (the freedesktop screensaver) or X11;
  elsewhere, from your own actions in sessions (as in 0.8.3). The X11 query runs in a separate process.
- Ctrl+Shift+P instead of Cmd+Shift+P on Linux; "terminal" instead of "Terminal"; the PATH hint names your
  shell's startup file. `pult tab setup` copies the line with wl-copy, xclip or xsel where they exist.
- `pult report` names the system (for example, Ubuntu 24.04.5 LTS), the desktop, where idle time comes from and
  whether linger is on. `pult status` says "not running" instead of "not loaded".
- The language of `pult` before setup comes from LANGUAGE, LC_ALL, LC_MESSAGES or LANG on Linux.
- `src/pult_os.py` now holds everything that differs between systems: paths, the service (launchd and systemd),
  idle time, the system language.
- GitHub Actions run the tests on macOS and Ubuntu.

## 0.8.3 — 2026-10-17

The first step towards Linux and Windows (stage K): nothing changes on the Mac except the words.

- The bot and the app say "computer" instead of "Mac": 💻 At my computer, what's open on the computer. The command
  is `/desk`; `/mac` still works.
- Whether you're away is asked through `src/pult_os.py`. Where the system can't tell (no keyboard and mouse idle,
  as on a server), Pult goes by your own actions in sessions here: a prompt typed or a permission answered in the
  last 2 minutes means you're at the computer. Before, a failed idle check could drop permission requests and
  results.
- The hook reads and writes UTF-8 whatever the console's encoding is; Pult's files are read and written as UTF-8.
- The hook Pult adds to its own sessions keeps paths with spaces whole.
- `pult report` also hides Windows and Linux folder paths.
- The bot's language comes from your Telegram only the first time; after that it changes only in the app's
  settings. Before, a message from Telegram on another device in another language switched the bot.
- GitHub Actions: `actions/checkout@v5`, `actions/setup-python@v6`.

## 0.8.2 — 2026-10-17

- `pult setup` and the bot say plainly that `/bind` goes in the group itself, not in the private chat with the
  bot. `/bind` sent in the private chat answers with the four steps to make the group; any other message there
  says where Pult works.
- `/feedback` links the GitHub issues.
- The relay no longer serves a leftover test page.
- On Linux or Windows, the installer and the README now say support is in progress instead of "not supported".

## 0.8.1 — 2026-10-17

- Public README in English and Russian, with screenshots from the test stand (made-up sessions only),
  CONTRIBUTING, SECURITY, issue and PR templates, the MIT license, tests on GitHub Actions (macOS).
- Web app: opening a session from a link in Telegram no longer leaves "Connecting…" on screen after the data has
  loaded. Table columns in replies stay as wide as their longest word instead of breaking words apart.
- Test stand: neutral made-up data in English and Russian (`STAND_LANG`); it never reads the Mac's own sessions.

## 0.8.0 — 2026-10-17

Installs on any Mac.

- `./install.sh` finds Python 3.10+ by itself and builds Pult's own environment; the hook and the VS Code tab
  wrapper run on it. Nothing is tied to one machine: a proxy only if `PULT_PROXY` is set, `claude` from `PATH`
  (or the one bundled with the Agent SDK), the launchd label `io.github.pulthq.pult` (an existing install keeps
  its own).
- The `pult` command in English and Russian: `setup`, `status`, `start|stop|restart`, `hooks`, `tab`, `app`,
  `run`, `report`, `uninstall`, `help`.
- `pult setup`, a wizard: the bot token → you, through a `t.me/<bot>?start=<code>` link → the group, with `/bind`
  (topics and admin rights checked) → hooks. Safe to re-run; the service is paused during it and always started
  again.
- `pult report`: versions, state and the end of the logs, without tokens, IDs, folder names or message text.
- `pult uninstall`: removes only Pult's own files; if an editor still starts Claude tabs through the wrapper, a
  pass-through stub stays in its place.
- The hook command checks for Pult's environment and exits quietly without it.
- `deploy/relay/`: the web app relay for any Linux server (installer, systemd unit, nginx and Caddy examples);
  `pult app` sets up the Mac side.

## 0.7.0 — 2026-10-16

- The bot and the web app speak English and Russian; the language follows your Telegram or the app's settings.
- Logs, messages for Claude and code comments are in English.

## 0.6.0 — 2026-10-16

- Notification modes: 🔄 Auto, 💻 At my Mac (silent), 📱 On my phone (with sound). Messages always arrive; only
  the sound changes. A pinned panel in General, `/auto` `/mac` `/phone` `/mode`.
- `/help` in sections, `/feedback`, the Telegram command menu in both languages.

## 0.5.0 — 2026-10-16

- From Telegram straight into an open VS Code tab: an optional wrapper (`claudeCode.claudeProcessWrapper`)
  between VS Code and Claude Code passes everything through and adds your message to the tab's input. It acts only
  in chosen folders and on checked Claude Code versions; otherwise it runs Claude Code directly.
- After a Claude Code extension update, writing into tabs waits for a check, and Pult says so once.

## 0.4.0 – 0.4.3 — 2026-10-16

- Usage in the web app: the 5-hour window, the week, per model, resets; warnings at 80 % and 95 %.
- The session card: model, effort, context, requests and tokens of the turn.
- `pult run -- command`: tasks without Claude report start, progress and the exit code.
- Claude's background tasks in results ("still running in the background") and turns Claude starts by itself
  when one finishes.
- Today's tokens by project. Time and date on every event in the app.

## 0.3.0 — 2026-10-16

- The web app, a Telegram Mini App: home, projects, a session's whole conversation with live updates, answers to
  questions and permissions, writing into a session, new tasks. A relay on your server connects it with the Mac;
  it stores nothing and checks Telegram's signature; the Mac checks every login again with the bot token.

## 0.2.0 — 2026-10-16

- Readable messages: one live message per turn with Claude's latest line, results with time, permission requests
  in plain words, reminders on long turns.

## 0.1.0 – 0.1.4 — 2026-10-15/16

- First version: hooks in every Claude Code session on the Mac → a daemon → a Telegram group with a topic per
  project. Turn feed, results, permissions and questions as buttons racing the dialog on the Mac. New and continued
  sessions through the Agent SDK, a copy for a session that is open on the Mac; asks "where to?" before starting.
