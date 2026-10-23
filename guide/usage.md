# Using Pult

[README](../README.md) · [Install](install.md) · **Using it** · [Troubleshooting](troubleshooting.md) · [Русский](usage.ru.md)

## In Telegram

Every project gets a topic in your group; its sessions' turns, results, questions and permission requests go there.

| | |
|---|---|
| reply to a session's message | continue that session |
| text in a topic | the topic's current session (🎯 in the pinned card); none — the only open one, else Pult asks once |
| `/new text`, or `/new` then the text | a new session in this project |
| files, photos, an album | land in the project's `inbox/<date>/` under their own names; files without words wait for your next message |
| a voice message | becomes text (with a free Groq key, `pult stt`) |
| `/desk` `/phone` `/auto` `/mode` | where you are: silent at the computer, always sound, or sound after 2 minutes away |
| `/status`, `/projects`, `/sessions` | what's open now; projects; recent sessions of this project |
| `/stop` | interrupt the topic's current session started from Telegram |
| `/app`, 📱 Pult in a topic's pinned bar | open the web app |

Signs in the feed: ⏳ works · ✅ a result · ✔️ decided or done · 🟠 waits for you · ✋ a permission · ❓ a question ·
⚠️ a failure · ⚙️ a job. A long result shows its beginning; the rest opens with a tap.

**Asking Claude for a file.** Every session learns, at its start, that it can send files of its project to the
project's topic with `pult send FILE… [-m TEXT]`. Only files inside the project, up to 50 MB each, ten at once, and
nothing that looks like keys or settings (`.env`, `*.pem`, `.ssh/`, `credentials*`).

**Called only when it matters.** With the web app, Telegram becomes a pager: it rings when Claude waits for you and
you're neither in the app nor at the computer. Reminders on long turns; warnings at 80 % and 95 % of a limit.

## In the web app

- **Home** is built around whose move it is: what runs right now, then what waits for you — permission requests to
  answer right there, sessions that ended and need you, with ready replies taken from Claude's own message — then
  every project with its colour.
- **A session** shows the whole conversation, live, with the model, the effort and the context gauge by the message
  field. Pick the model (Fable, Opus, Sonnet, Haiku) and how hard Claude thinks for that session; a running one
  switches at once.
- **Resources**: Limits — the curve of each limit against the even pace, the forecast (on pace, under: how many hours
  of a session's work would go unused, over: when it runs out), who spent it; Computer — the processor, the memory
  and each Claude session's commands.
- **Files of the turn**: what Claude made or changed in the project — tick the ones you need and send them to the
  topic, one by one or as one archive; earlier turns' files stay a swipe away.
- **A new project**: a folder anywhere in your home folder — empty with git, with a `CLAUDE.md` that Claude writes
  from your description, or a clone of a repository. Its topic appears in the group at once.

## In a terminal

`pult help` lists them all: `status`, `setup`, `start|stop|restart`, `busy`, `hooks on|off`, `tab …`, `app`, `stt`,
`send`, `run`, `report`, `uninstall`. `pult run -- npm run build` reports a long command's start, progress and exit
code to Telegram the same way as Claude's turns.

## Security and privacy

- **Who can control your computer:** only your Telegram account (`PULT_ALLOWED_USER_IDS`), only in the bound group.
  Anyone inside your Telegram account could run Claude Code with your user's rights: turn on two-step verification.
- **The bot token is a key.** It lives in `~/.config/pult/env` (mode 600). If it leaks, `/revoke` it in @BotFather
  and run `pult setup`.
- **What goes to Telegram:** your prompts, Claude's replies, step names, commands and file names in permission
  requests, questions, and the files you or Claude send. Telegram keeps it like any chat; bot chats aren't
  end-to-end encrypted.
- **The relay** stores nothing and stops strangers by Telegram's signature and your ID; the computer checks every
  login again with the bot token, which never leaves it. The page runs scripts only from your server and Telegram.
- **Alerts** with sound on an app login from a new network and on signs that someone else holds the bot token;
  Settings → Logins in the app logs every window out. A link whose words hide its address shows its domain.
- **No telemetry.** Logs stay on the computer. `pult report` prints the state with tokens, IDs, folder names and
  message text removed, for a bug report. Vulnerabilities: [SECURITY.md](../SECURITY.md).

## Claude Code, your plan and Anthropic

Pult has no login and no model of its own. It drives the Claude Code already installed and signed in on your
computer, with your account and your plan's limits, the same as you would in a terminal. Anthropic's
[Agent SDK documentation](https://code.claude.com/docs/en/agent-sdk/overview) says: *"Unless previously approved,
Anthropic does not allow third party developers to offer claude.ai login or rate limits for their products,
including agents built on the Claude Agent SDK."* Pult doesn't offer a login: it runs your own Claude Code for
you. Still, read the terms of your plan and decide for yourself. Claude Code can also be signed in with an
Anthropic API key; Pult hasn't been tested that way yet.

Pult is an independent open-source project, not affiliated with or endorsed by Anthropic. Claude and Claude Code
are trademarks of Anthropic.
