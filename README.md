<p align="center"><img src="media/logo.svg" width="84" height="84" alt=""></p>

<h1 align="center">Pult</h1>

<p align="center"><b>Every Claude Code session on your computer — in Telegram.</b><br>
Claude asks — your phone rings. You answer — the open VS Code tab goes on.</p>

<p align="center">
  <a href="https://github.com/pulthq/pult/actions/workflows/tests.yml"><img src="https://github.com/pulthq/pult/actions/workflows/tests.yml/badge.svg" alt="tests"></a>
  <a href="https://github.com/pulthq/pult/releases"><img src="https://img.shields.io/github/v/release/pulthq/pult?label=release&color=2f6fcf" alt="release"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-555" alt="MIT"></a>
</p>

<p align="center"><a href="#from-the-phone">From the phone</a> · <a href="#install">Install</a> · <a href="#how-it-works">How it works</a> · <a href="#what-you-get">What you get</a> · <a href="guide/usage.md">Guide</a> · <a href="README.ru.md">Русский</a></p>

<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="media/hero.en.dark.gif">
    <img src="media/hero.en.gif" width="880" alt="On the left, a Claude Code tab on the computer asks to run a command; on the right, the phone shows the same question in the project's Telegram topic. A tap on Allow on the phone, and the tab goes on by itself; the result comes to the topic, and the next message from the phone appears in the tab as if typed there">
  </picture>
</p>

You give Claude Code a task and walk away. When Claude stops to ask, **Pult** rings your phone in the project's
Telegram topic, and your answer reaches the session — even the tab open in VS Code. It runs on your computer and
opens no port to the network. *Pult* is Russian for a remote control.

## From the phone

<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="media/glance.en.dark.png">
    <img src="media/glance.en.png" width="560" alt="Allow or deny a permission from the phone; answer Claude's question; say what's next and it lands in the open VS Code tab; see whose move it is; the whole session live, with ready replies; voice that arrives as text; files both ways; a new project; your plan's pace; tags on every task; the model and the effort; Pult keeps itself current">
  </picture>
</p>

Each one with its screen: [what you get](#what-you-get). The rest, from ticks on your message to `pult run`:
**[the guide](guide/usage.md)**.

## Install

```
git clone https://github.com/pulthq/pult.git && cd pult && ./install.sh
```

About ten minutes with a Telegram bot of your own; on Windows the installer is `install.ps1`. macOS, Linux and
Windows: **[the details](guide/install.md)**.

## How it works

<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="media/steps.en.dark.png">
    <img src="media/steps.en.png" width="560" alt="1. Work as usual: VS Code or a terminal, Pult picks up every session. 2. Your phone rings only when needed: a permission, a question, a turn that waits for you. 3. Answer, and the tab goes on: allow, pick, reply — it lands in the open tab">
  </picture>
</p>

Claude Code's hooks bring every session to Pult, the ones you opened before leaving too — there is nothing to start.
A permission request races the dialog on the computer: whichever answer comes first decides. If Pult isn't running,
Claude Code behaves as if it weren't there. The paths, with diagrams: [ARCHITECTURE.md](ARCHITECTURE.md).

## What you get

Telegram for the calls, a Mini App inside it for the rest. The app needs a small server of yours
([deploy/relay](deploy/relay/README.md)); without it, everything works in the chat alone.

### Whose move, at a glance

What runs right now, then what waits for you — answer a permission or a question right there.

<p align="center"><picture><source media="(prefers-color-scheme: dark)" srcset="media/f-home.en.dark.png"><img src="media/f-home.en.png" width="330" alt="Home in the app: two sessions running with their time, “While you were away”, then a permission request with Allow and Deny"></picture></p>

### The whole session in your pocket

The conversation live, the outcome with ready replies taken from Claude's own message, the model and the context
by the field.

<p align="center"><picture><source media="(prefers-color-scheme: dark)" srcset="media/f-session.en.dark.png"><img src="media/f-session.en.png" width="330" alt="A session in the app: Claude's report, its question, the outcome card waiting for you with three ready replies and the turn's files"></picture></p>

### Tasks sorted by Claude

Every task gets a section of the project and a topic in it, from the same small model that writes the result line —
nothing to set up. Tap a section to see only its tasks; tap the tags to correct them. In Telegram they end each result
as hashtags — a tap shows the topic's other tasks. The tag button beside the sections opens the project's list: rename,
recolour, merge two into one, hide — and Claude offers to merge two tags that name the same thing. A project's earlier
tasks get their tags too, once, the first time you open it; **Sort them again** makes the list anew. Your corrections
teach Claude: it tags tasks like them the same way.

<p align="center"><picture><source media="(prefers-color-scheme: dark)" srcset="media/f-tags.en.dark.png"><img src="media/f-tags.en.png" width="330" alt="A project in the app: its sections on top with how many tasks in each, a task that waits for you with its tags and ready replies, the tasks running"></picture></p>

### Your plan's pace

Each limit against the even pace, with a forecast: on pace, under or over — and when it would run out.

<p align="center"><picture><source media="(prefers-color-scheme: dark)" srcset="media/f-pace.en.dark.png"><img src="media/f-pace.en.png" width="330" alt="Resources in the app: the week's curve against the even pace, the forecast and how many sessions worked at once"></picture></p>

### Files both ways

Forward documents to a project's topic — they land in the project. What Claude made comes back with a tap. A file
Claude links to in a reply opens right in the app: a page, code at the very line, a picture or a folder.

<p align="center"><picture><source media="(prefers-color-scheme: dark)" srcset="media/f-files.en.dark.png"><img src="media/f-files.en.png" width="330" alt="Files of a turn: the files Claude made or changed, to tick and send to Telegram one by one or as one archive"></picture></p>

### A new project from the phone

An empty folder with git, a `CLAUDE.md` Claude writes from your words, or a clone — its topic appears at once.

<p align="center"><picture><source media="(prefers-color-scheme: dark)" srcset="media/f-newproject.en.dark.png"><img src="media/f-newproject.en.png" width="330" alt="New project in the app: a name, its folder, where to put it and how to start: empty, with a description or from GitHub"></picture></p>

### Pult looks after itself

Every part in one table: the computer, the app and its server, this phone's copy, the VS Code tabs, the hooks,
Claude Code. A new release goes in with one tap (macOS, Linux) and your app server follows
([once: `install.sh --auto`](deploy/relay/README.md#updates)); a Claude Code version VS Code has downloaded is
checked here before your tabs move to it.

<p align="center"><picture><source media="(prefers-color-scheme: dark)" srcset="media/f-parts.en.dark.png"><img src="media/f-parts.en.png" width="330" alt="Settings in the app: the table of Pult's parts — the computer, the app and the relay on the server, this phone, the VS Code tabs, the hooks, Claude Code, the release — each with what it runs and whether it is as in main; the switch that checks new Claude Code versions"></picture></p>

And:

- **Voice** — a voice message in the topic, or the microphone in the app, arrives as text (Groq Whisper, with a key of yours).
- **Model and effort** — per session, switched while it runs; a default for the sessions Pult starts.
- **Ticks** on your message — sent, read by Claude — and a pager that knows whether you're at the computer.
- **A second opinion** — under an outcome, Codex (OpenAI's agent, on your ChatGPT subscription) reads what the task
  changed in a read-only sandbox; its findings go back to Claude with one tap. Per project, only once you allow it.
- **`pult run`** for your own long commands, reported like a turn.

**[All of it](guide/usage.md)**.

## Next to the official options

Anthropic has its own ways to reach Claude Code away from the keyboard. If they fit you, use them.

| | Pult | [Remote Control](https://code.claude.com/docs/en/remote-control) | [Channels](https://code.claude.com/docs/en/channels) |
|---|---|---|---|
| Where you answer | Telegram, plus an optional web app inside it | claude.ai/code or the Claude app | Telegram, Discord or iMessage |
| Which sessions | every VS Code tab and terminal session, picked up by hooks | the ones you connect, or all with its auto-connect setting | a session started with `claude --channels …` |
| Your sign-in | whatever Claude Code is signed in with | a claude.ai plan; API keys aren't supported | claude.ai or a Console API key |
| Status | independent, open source | official | official, research preview |

## Safe by default

Only your Telegram account, only in your group. No port opened; the optional relay stores nothing. No telemetry.
Pult drives the Claude Code already signed in on your computer, with your plan — read its terms and decide for
yourself. **[Security, privacy and your plan](guide/usage.md#security-and-privacy)** · [SECURITY.md](SECURITY.md)

Pult is an independent open-source project, not affiliated with or endorsed by Anthropic. Claude and Claude Code
are trademarks of Anthropic.

---

[Install](guide/install.md) · [Using it](guide/usage.md) · [Troubleshooting](guide/troubleshooting.md) ·
[Architecture](ARCHITECTURE.md) · [Contributing](CONTRIBUTING.md) · [Changelog](CHANGELOG.md) · [MIT](LICENSE)
