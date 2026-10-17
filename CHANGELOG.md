# Changelog

Versions 0.x come before the first public release. Newest first.

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
