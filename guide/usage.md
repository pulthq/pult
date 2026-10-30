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

- **Home** is built around whose move it is: what runs right now (each task with what you asked and what Claude says
  so far), then what waits for you — permission requests to answer right there, sessions that ended and need you,
  with ready replies taken from Claude's own message — then every project with its colour.
- **Pinned projects**: slide a project's row to the left on the Projects screen and tap Pin, or tap the pin in a
  project's header. Pinned projects stay on top of Projects, of Home and of the new task's list, the newest pin
  first; the rest are ordered by who needs you. The pin is kept on the computer, so every phone sees the same.
  The same slide offers **Hide** — the project goes into a folded "Hidden" section at the bottom of Projects and
  leaves Home's board and the new task's list (what runs in it and what waits for you still show; a slide in the
  fold brings it back) — and **New task**, which opens the form with that project. A task's row slides to **Tags**,
  a card of "Your move" slides to **Got it**; questions and permissions don't slide.
- **Copy a message**: in a session, slide it to the left until its copy sign lights up and let go. A message of
  Claude's goes to the clipboard whole, formatted as Telegram copies a message — a paste into Telegram, notes or mail
  keeps the bold, the links, the code and the quotes — and as Claude's markdown for plain-text places; one of yours
  goes as you wrote it. A tap on a grey block of code still copies just that block.
- **A second opinion from Codex**: under a session's outcome, **Second opinion · Codex** asks Codex — OpenAI's coding
  agent, with the ChatGPT sign-in on your computer — to read what the task changed since it began (in git: everything
  since the commit the folder was on, new files too; without git: the files Claude's edits wrote), together with your
  request and Claude's report, so what was done on purpose isn't taken for a bug. It reads in a read-only sandbox and
  asks nothing; one at a time, usually a minute or two, and **Stop** ends it. The findings come as a card at the end
  of the session, each with its place in the project — a tap opens the file at that line; **Send to Claude** puts
  them into the session as your message, **Got it** puts the card away. The first time in a project you're asked
  whether its code may go to OpenAI; the project's screen then says so, and **Disallow** takes it back. The button
  shows only where Codex is installed (ChatGPT for Mac carries it, or the `codex` command); a Codex version Pult
  wasn't checked on is checked against its own protocol first.
- **Other vendors' models**: New task has **Who does it** above the model — Claude, or DeepSeek, GLM or Kimi. Claude
  Code itself runs the task on their model (they answer its own protocol at an address of theirs), with your key:
  the turns, the cards, the outcome and the topic work as with Claude, and the model field lists that vendor's models.
  Put a key in Settings → Other vendors — it is checked with one tiny request and stays on the computer — and edit
  the list of models there: the first is the main one, the second the fast one (titles, subagents). The first pick in
  a project asks whether its code may go to other vendors (the same permission as the second opinion's); **Make it
  the default** sends the project's new tasks there, from Telegram too; Settings → Other vendors → **Who does new tasks
  by default** does it for every allowed project at once (a project's own choice comes first). A session keeps its vendor when it goes on or
  is copied, never starts without the key and doesn't show in VS Code's list. Anthropic doesn't support this, and
  Claude Code's prompts are written for Claude: for the cheaper tasks, not the hard ones.
- **A session** shows the whole conversation, live, with the model, the effort and the context gauge by the message
  field. Pick the model (Fable, Opus, Sonnet, Haiku) and how hard Claude thinks for that session; a running one
  switches at once. Settings → Model and effort sets what sessions from the app and Telegram start with; VS Code tabs
  keep their own settings.
- **Tags**: every task gets two — the section of the project it belongs to and the topic in it — from the same small
  model that writes the result line, as soon as its request is in and again when its turn ends; turn it on in
  Settings → A plain line for each result (it is off at first). The folders and files are only the model's hint: there
  is nothing else to set up. Tap a section on top of a project's screen to see only its tasks (and its topics); tap the
  tags under a task's title to correct them — your choice stays. `#topic` in a request sets it at once, even with the
  switch off. In Telegram each result ends with them as hashtags — `#firmware #filament_sensor`: a tap shows every
  message with one (Settings → Hashtags in Telegram). The tag button beside a project's sections opens all its tags,
  the busiest first, each with how many tasks have it: rename a section or a topic, give a section its colour, merge
  two into one, hide one (the tasks keep it; rows, the filter and Telegram don't show it — bring it back at the bottom
  of the screen). A tag Claude has just made is dashed until you keep it or merge it into another. Claude looks the
  list over too and offers to merge two tags that name the same thing; **Keep both**, and it won't offer them again.
  Claude goes on with your names: an old name it brings lands on the new tag. The first time you open a project with
  the switch on, Claude sorts its earlier tasks that have no tags (the latest 200, twenty at a time, in the background;
  "Claude is sorting the earlier tasks: 40 of 120" under its sections) — once a project. **Sort them again** at the
  bottom of its tags asks first, then makes the list anew from the README, CLAUDE.md, the latest tasks and your own
  tags, and sorts every task you didn't tag yourself into it — about a minute. Every tag you pick yourself — in a task's
  sheet, by a `#tag`, by a merge — is an example for Claude: it sees your latest six in the project and tags tasks like
  them the same way; **Claude picks them** in the sheet takes the example back.
- **Resources**: Limits — the curve of each limit against the even pace, the forecast (on pace, under: how many hours
  of a session's work would go unused, over: when it runs out), who spent it; Computer — the processor, the memory
  and each Claude session's commands.
- **Files of the turn**: what Claude made or changed in the project — tick the ones you need and send them to the
  topic, one by one or as one archive; earlier turns' files stay a swipe away.
- **A new project**: a folder anywhere in your home folder — empty with git, with a `CLAUDE.md` that Claude writes
  from your description, or a clone of a repository. Its topic appears in the group at once.

- **Pult itself**: Settings → Pult and its parts — the computer, the app and the relay on your server, this phone's
  copy, the VS Code tabs, the hooks, Claude Code and the release, each with what it runs and how far it is behind the
  branch Pult was installed from. A new release installs from there with one tap (macOS, Linux; a clone finds releases
  on GitHub by itself), and your app server takes the same one from GitHub
  ([once: `install.sh --auto`](../deploy/relay/README.md#updates)). A Claude Code version VS Code has downloaded is
  checked on your computer before the tabs move to it; "Check new Claude Code versions" turns that off.

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
- **Other vendors:** a project's code reaches OpenAI only with a second opinion you ask for, and only once you
  allowed that project. Codex reads in a read-only sandbox with your own ChatGPT sign-in; Pult gives it none of its
  keys. Codex keeps the review in its own history, as with any task of yours.
- **Vendors' keys** live in `~/.config/pult/env` like the bot token; the app can set or remove one but never reads it
  back. Without a key Claude Code would send your Claude sign-in to the vendor's address, so Pult never starts a vendor
  session without one.
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
