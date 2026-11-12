# Using Pult

[README](../README.md) · [Install](install.md) · **Using it** · [Troubleshooting](troubleshooting.md) · [Русский](usage.ru.md)

Pult is an app inside Telegram for the AI agents on your computer: the app is the main screen, and the chat calls you
when you're needed. Every Claude Code session shows there — VS Code tabs, terminals, the tasks you start from the
phone — on Claude's models or another vendor's, and another model can check what one did.

## In the app

- **Home** is built around whose move it is: what runs right now (each task with what you asked and what Claude says
  so far), then what waits for you — permission requests to answer right there, and every session that ended, with
  ready replies taken from Claude's own message — then every project with its colour. A finished task stays there,
  a plain report too, until you tap **Reviewed** (on the card, or under the outcome in the session) or answer it:
  opening it doesn't put it away, so nothing finished slips by unchecked. What a tap decides can be taken back: an
  option of a question, **Allow** and **Deny** go three seconds later, with **Undo** beside them; **Reviewed** leaves a
  note at the bottom — **Bring back** — for five seconds; **Stop** asks before it stops a turn. Under **Always allow**
  the card says what it would allow and where — "the commands `npm test …` — in this project, for good", "edits of
  files without asking — until the task ends". Each state has its colour: what runs is
  green, what waits for you warm — the whole card, a failed one red — and history plain, each row with a grey tick
  of a task you reviewed; a project's screen shows them the same way.
- **Pinned projects**: slide a project's row to the left on the Projects screen and tap Pin, or tap the pin in a
  project's header. Pinned projects stay on top of Projects, of Home and of the new task's list, the newest pin
  first; the rest are ordered by who needs you. The pin is kept on the computer, so every phone sees the same.
  The same slide offers **Hide** — the project goes into a folded "Hidden" section at the bottom of Projects and
  leaves Home's board and the new task's list (what runs in it and what waits for you still show; a slide in the
  fold brings it back) — and **New task**, which opens the form with that project. A task's row slides to **Tags**,
  a card of "Your move" slides to **Reviewed**; questions and permissions don't slide.
- **Copy a message**: in a session, slide it to the left until its copy sign lights up and let go. A message of
  Claude's goes to the clipboard whole, formatted as Telegram copies a message — a paste into Telegram, notes or mail
  keeps the bold, the links, the code and the quotes — and as Claude's markdown for plain-text places; one of yours
  goes as you wrote it. A tap on a grey block of code still copies just that block.
- **A session** shows the whole conversation, live, with the model, the effort and the context gauge by the message
  field. Pick the model and how hard Claude thinks for that session; a running one switches at once. The models carry
  the versions the session's own Claude Code gives them — "Fable 5.2", "Opus 5.5" — so a VS Code tab on an older Claude
  Code may say "Fable 5.1"; **Other versions** under the menu keeps a session on an older one, as Claude Code's own menu
  does. Settings → Models and keys → Model and effort sets what sessions from the app and Telegram start with; VS Code tabs
  keep their own settings.
- **Tags**: every task gets two — the section of the project it belongs to and the subsection in it — from the same small
  model that writes the result line, as soon as its request is in and again when its turn ends; turn it on in
  Settings → Models and keys → One-line result and tags (it is off at first). The folders and files are only the model's hint: there
  is nothing else to set up. Tap a section on top of a project's screen to see only its tasks (and its subsections); tap the
  tags under a task's title to correct them — your choice stays. `#tag` in a request sets it at once, even with the
  switch off. In Telegram each result ends with them as hashtags — `#firmware #filament_sensor`: a tap shows every
  message with one (Settings → Notifications → Hashtags in Telegram). The tag button beside a project's sections opens all its tags,
  the busiest first, each with how many tasks have it: rename a section or a subsection, give a section its colour, merge
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
- **Home's top**: the limit that runs out first, in a tile of its own, and the machine Pult runs on — its processor,
  memory and, on a laptop, power: a plug, or the battery with its charge, yellow from 20 % and red from 10 %. On its
  battery Pult writes to General at 20 % and, with sound whatever the mode, at 10 % — the machine would sleep at the
  last per cent and every turn on it would break; the charger back after a warning — a quiet line.
- **Resources**: Limits — the curve of each limit against the even pace, the forecast (on pace, under: how many hours
  of a session's work would go unused, over: when it runs out), who spent it; the machine's tab, by its name ("MacBook
  Air", "homelab" — a laptop or a server; Settings → Pult and its parts renames it) — the processor, the memory, the power
  on a laptop (charge, the system's estimate, cycles and the capacity left) and each Claude session's commands.
  From 85 % of the computer's memory a line at the top of every screen says so, red from 95 %; a tap opens Resources.
- **Files of the turn**: what Claude made or changed in the project — tick the ones you need and send them to the
  topic, one by one or as one archive; earlier turns' files stay a swipe away.
- **Changes**: under a task's outcome — **Changes: 4 files +120 −30** — what the task changed in its project, counted
  from git since the commit the folder stood at when the task began: committed since or not, new files too. A tap
  lists the task's own files — the ones its tools wrote and its turns touched; what else changed in the folder
  meanwhile, by commands or by other tasks, is folded under them. A file opens its change line by line: removed lines
  with **−**, added ones with **+**, the unchanged stretch between two pieces as a count; **Whole file** shows all of
  it with the changes in place. Files that look like keys or settings are counted and never shown. It is a view:
  nothing is committed or changed from here. A project that isn't in git has no such line.
- **A new project**: a folder anywhere in your home folder — empty with git, with a `CLAUDE.md` that Claude writes
  from your description, or a clone of a repository. Its topic appears in the group at once.

- **Settings** is a menu of five screens — Notifications, Models and keys, Voice and language, Pult and its parts,
  Security — and each row says what is set there now.
- **Pult itself**: Settings → Pult and its parts — the computer, the app and the relay on your server, this phone's
  copy, the VS Code tabs, the hooks, Claude Code and the release, each with what it runs and how far it is behind the
  branch Pult was installed from. A new release installs from there with one tap (macOS, Linux; a clone finds releases
  on GitHub by itself), and your app server takes the same one from GitHub
  ([once: `install.sh --auto`](../deploy/relay/README.md#updates)). A Claude Code version VS Code has downloaded is
  checked on your computer before the tabs move to it; "Check new Claude Code versions" turns that off. When a session
  from the app works on it too, new and continued tasks from the app start on it — instead of the Claude Code built
  into Pult, which only a Pult release moves; "A fresh Claude Code for the app" turns that off. Tasks on other vendors'
  models and on your own stay on the built-in one. The same row says which Claude Code is out.

## Who does the task, who checks it

Pult drives each vendor's own program: Claude Code for Claude's models and, inside it, for DeepSeek, GLM and Kimi and
for a model of your own through Ollama; Codex for its own tasks and for a second opinion. So one model can do a task
and another check it — from the phone.

- **A project belongs to one model**: Claude, Codex, DeepSeek, GLM or Kimi, or a model of your own — it does every task
  of the project, from the app and from Telegram. The project's screen names it under the name; the gear opens **Project settings**,
  where it is changed — only while nothing runs in the project (a turn, a queue, a background task or helper), after
  saying where the code goes. The tasks of the model before stay, read only: open, read, copy; to go on with one, give
  the project its model back. New task's **Who does it** shows the project's model and leads to its settings; the model
  field lists that model's own models (and Codex's levels of effort). DeepSeek, GLM and Kimi run inside Claude Code —
  they answer its own protocol at an address of theirs — with your key: the turns, the cards, the outcome and the topic
  work as with Claude. Put a key in Settings → Models and keys — it is checked with one tiny request and stays on the
  computer — and its models are a list there: a tick puts a model in a task's menu, the star makes it the main one,
  **Helpers** names the one subagents run on; a model Pult doesn't list yet is added by its name. Settings → Models and keys → **The model of new projects** is what a project made in the app gets (its form
  can pick another). A model without its key, or your own one turned off, can't take the project's task — Claude
  never takes it in its place. A vendor's session doesn't show in VS Code's list. Anthropic doesn't support this, and
  Claude Code's prompts are written for Claude: for the cheaper tasks, not the hard ones.
- **Project settings**: besides the model — **Helper Claude (haiku)**, the result line and tags: on in Claude's projects,
  off in other models' (on, the tasks' requests and outcomes go to Anthropic — asked first); **Topic in Telegram** —
  "Request and outcome", or "Only “done”": none of the task's words go to Telegram, only "done" and "waits for you", and
  `pult send` files don't go there either; the **review** — a second opinion only by your tap, and Codex's permission to
  read the code, with **Disallow**; the project's tags, pin and hide. A VS Code tab or a terminal with Claude in a
  project of another model is noticed: its topic hears it once, and the project's screen says so.
- **Kept apart**: a task on another vendor's model runs in a Claude Code home of its own (in Pult's folder): your global
  CLAUDE.md, settings and memory stay out of its requests, and its conversation and memory stay out of `~/.claude`;
  Claude Code's own requests elsewhere are off, and the model is told who it is. Claude haiku reads these tasks only if
  you switch it on in the project — otherwise their result line is the first sentence of the answer, and their tags are
  yours to set. A task begun before goes on as it was.
- **A model of your own**: a project's model can be **Local model** too — Ollama on this computer, or on another one
  through a tunnel you keep open (Pult reaches only this computer's own address). Settings → Models and keys → Local model →
  **Check and turn on** asks the server what it has: a model fits when it can use tools and its context is set to 16K
  or more (`PARAMETER num_ctx` in its Modelfile) — Ollama cuts a longer request silently, so a model without it isn't
  taken. Once on, it has a tab of its own — **Resources → Local model** (Settings' card opens it): Ollama's models
  by their weights — a base with its size and, under it, the copies made from it with a context, which hold the same
  weights (+0 GB); a tick puts a model in a task's menu, the star makes it the main one; one without a context set gets
  **Make a copy with 32k** — Ollama makes it from the same weights. A tap on a model: **Unload** it from the card's
  memory, **Remove** it — with how much that gives back (nothing while another model holds its weights). **Download a
  model** by its name on ollama.com: Pult first says its size, the room left after it and whether it fits the card with
  a 32k context, and refuses one that would leave the disk under its reserve (60 GB, or a tenth of a smaller disk); the
  Ollama downloads it itself, its progress shows in the tab and on Home, and **Stop** keeps what came for the next
  time. The tab asks Ollama as it opens, so a model made there since shows at once. Ollama doesn't say how much
  room its disk has or what its card holds: for that, put the small reader in `deploy/ollama-info/` beside it
  (`sudo bash deploy/ollama-info/install.sh`, a systemd socket on 127.0.0.1:11436 — one JSON per request, nothing
  kept in memory) and forward its port the way Ollama's goes. In WSL the disk shown is Windows's C:, which the Linux
  disk grows on; space a removal frees comes back to C: only when that disk is sparse. No key: the
  code stays home. Claude Code gets five tools there — commands,
  reading, editing and writing files, a question to you — and one model does every role; a task doesn't start while
  the server doesn't answer. A model's own instructions — the SYSTEM in its Modelfile: a persona, a language, fewer
  refusals — go with every task: Ollama drops them when a request brings a system prompt, and Claude Code always does,
  so Pult passes them on. **Settings of the model** (a tap on a model in the tab): its system prompt; its context length —
  16K to 256K, each with how much of the graphics card it would take, counted from the model's own make (gemma4's
  window layers keep a long context cheap); its temperature, and under **Fine tuning** top_k, top_p, min_p,
  repeat_penalty and presence_penalty — the ones its Modelfile doesn't set are grey. They are written into the model
  itself, as `ollama create` would do it, so it behaves the same outside Pult; Claude Code's requests carry none of
  them, so a task gets the Modelfile's. Pult keeps the model as it was before its first change (a `pult-was/…` copy:
  a few lines, the weights stay one), and **Back as it was before Pult** restores it. Two settings are Pult's own:
  **Tools** — the five core ones, or all of Claude Code's (from a 64K context: their descriptions alone are ~22K
  tokens); **After a turn** — keep the model on the card, or free the card at once (the next answer then waits for
  the model to load). A new task gets the system prompt; one begun keeps the one it began with. The context doesn't
  change while a task runs on the model. Thinking can't be turned off from here: Claude Code never asks for no
  thinking, and Ollama has a model that can think do so. Free, but weaker and slower than Claude.
- **Which model did what**: every card names its model — in Running now at the right of its top line ("Opus 5.5",
  "DeepSeek · v4-pro"), on a finished task's card at its foot across from Reviewed, on a question or a permission
  before how long it waits, on a finished task's row at the right end of its second line; in a session, by the field.
- **How long Claude worked**: "working 47 min" in Running now is the whole task's work — all its turns, without the
  time it waited for you; on a card of Your move and at the top of a session the same clock stands, grey with a pause
  sign, until you answer. A background task Claude left running isn't in it; the turn its end starts is.
- **In the background**: by "working…" in a session, and on its card in Running now, — how many helpers (the subagents
  Claude starts) and commands run in the background, from the moment Claude starts them, not only after its turn. A
  tap lists each: a helper's type, its model, how long it runs, its steps and tokens so far and what it does now (from
  its own record); a command with its processor and memory.
- **A screenshot by ⌘V**: in What to do, in a session's message field and in a new project's first task, ⌘V (Ctrl+V
  on Windows and Linux) with a picture on the clipboard attaches it the way Picture does — take one straight to the
  clipboard with ⌃⇧⌘4 on a Mac. A file dragged onto the field comes in too; words on the clipboard stay words, even
  beside a picture (as Word, Excel and Numbers copy).
- **What a vendor's task has cost** stands beside its clock in the task's header — "≈ $0.04" — for DeepSeek and Kimi:
  the task's tokens at the model's list price; a tap says how many went in and out. It is an estimate from above: a
  cache read is counted as plain input, and a rush-hour price isn't known. GLM runs on a subscription and a model of
  your own costs nothing — no figure there.
- **A second opinion from Codex**: under a session's outcome, **Second opinion · Codex** asks Codex — OpenAI's coding
  agent, with the ChatGPT sign-in on your computer — to read what the task changed since it began (in git: everything
  since the commit the folder was on, new files too; without git: the files Claude's edits wrote), together with your
  request and Claude's report, so what was done on purpose isn't taken for a bug. It reads in a read-only sandbox and
  asks nothing; one at a time, usually a minute or two, and **Stop** ends it. The findings come as a card at the end
  of the session, each with its place in the project — a tap opens the file's change at that line (the file as it is,
  when the task didn't change it). Each finding has a tick: take it off, and that one stays here — the button says how
  many go, and the task's next review is told not to repeat it. **Send to Claude** puts the ticked ones
  into the session as your message — the button names whoever did the task: **Send to DeepSeek** on DeepSeek's
  model — and **Reviewed** puts the card away. Once they went and the task has answered, the button under the outcome
  becomes **Check the fixes · Codex**: Codex goes through the findings it gave and says of each one — **Fixed**,
  **Left** with what is still wrong, or **Deliberate** when the doer explained and Codex agrees — and names what the
  fixes broke, if anything; what is left goes back with one tap. Every round starts with your tap: Pult never sets
  one model on another by itself. **A task Codex did is read by Claude** the same way — **Second opinion · Claude**
  under its outcome: Claude (Sonnet) on your Claude subscription, in a session that has nothing but reading tools, so
  it can change nothing; its findings go to Codex, and it checks the fixes. That project is asked for once too — its
  code goes to Anthropic then. The first time in a project you're asked
  whether its code may go to OpenAI; the project's screen then says so, and **Disallow** takes it back. The button
  shows only where Codex is installed (ChatGPT for Mac carries it, or the `codex` command); a Codex version Pult
  wasn't checked on is checked against its own protocol first.

**Finding a task.** The field on top of Projects searches every project, the same field on a project's screen — that
project: by the tasks' titles, their first requests and their tags. A project's Earlier list goes on with *Show 40 more*.
Back returns to the place you left a screen at.

## In Telegram

Every project gets a topic in your group; its sessions' turns, results, questions and permission requests go there.

**When Telegram calls you** (with the app set up, Telegram is a pager — it rings only for what waits for you):
a call about something that ended while the app was on your screen waits five minutes after you leave the app, and
comes only if it still waits; a question or a permission you haven't answered is called about again after 30 minutes
and after 2 hours; from 23:00 to 8:00 everything comes without sound, except security alerts; and once a day, at 9:00,
one message in General sums up what waits for you, by project. All four are in the app: Settings → Notifications.
The **Computer** mode, which keeps Telegram silent, ends by itself in the morning — at the hour the quiet hours end,
8:00 without them — and is Auto again; Settings → Notifications says until when.

| | |
|---|---|
| reply to a session's message | continue that session |
| text in a topic | the topic's current session (🎯 in the pinned card); none — the only open one, else Pult asks once |
| `/new text`, or `/new` then the text | a new session in this project |
| files, photos, an album | land in the project's `inbox/<date>/` under their own names; files without words wait for your next message |
| a voice message | becomes text (with a free Groq key, `pult stt`); a quiet line under it says what was heard |
| `/desk` `/phone` `/auto` `/mode` | where you are: silent at the computer, always sound, or sound after 2 minutes away |
| `/status`, `/projects`, `/sessions` | what's open now; projects; recent sessions of this project |
| `/stop` | interrupt the topic's current session started from Telegram |
| `/app`, 📱 Pult in a topic's pinned bar | open the web app |

Signs in the feed: ⏳ works · ✅ a result · ✔️ decided or done · 🟠 waits for you · ✋ a permission · ❓ a question ·
⚠️ a failure · ⚙️ a job. A long result shows its beginning; the rest opens with a tap.

**Asking Claude for a file.** Every session learns, at its start, that it can send files of its project to the
project's topic with `pult send FILE… [-m TEXT]`; a task Codex does is told the same, and the command works inside its
sandbox. Only files inside the project, up to 50 MB each, ten at once, and nothing that looks like keys or settings
(`.env`, `*.pem`, `.ssh/`, `credentials*`).

**Called only when it matters.** With the web app, Telegram becomes a pager: it rings when Claude waits for you and
you're neither in the app nor at the computer. Reminders on long turns; warnings at 80 % and 95 % of a limit.

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
- **The relay** keeps nothing on disk and stops strangers by Telegram's signature and your ID; the computer checks every
  login again with the bot token, which never leaves it. The page runs scripts only from your server and Telegram.
  Whoever controls that server, though, could act in Pult as you: keep the relay on a server you trust as much as your
  computer.
- **Alerts** with sound on an app login from a new network and on signs that someone else holds the bot token;
  Settings → Security in the app logs every window out. A link whose words hide its address shows its domain.
- **Other vendors:** a project's code reaches OpenAI only in a project whose model you made Codex — its tasks run in a
  sandbox of the project's folder, and leaving it is asked — or with a second opinion you ask for, once you allowed that
  project; a review reads in a read-only sandbox. Both with your own ChatGPT sign-in; Pult gives Codex none of its keys,
  and it keeps the task or the review in its own history, as with any task of yours. DeepSeek, GLM and Kimi see a
  project only as its model, with your key; your own model through Ollama sends nothing anywhere.
- **Vendors' keys** live in `~/.config/pult/env` like the bot token; the app can set or remove one but never reads it
  back. Without a key Claude Code would send your Claude sign-in to the vendor's address, so Pult never starts a vendor
  session without one.
- **No telemetry.** Logs stay on the computer. `pult report` prints the state with tokens, IDs, folder names and
  message text removed, for a bug report. Vulnerabilities: [SECURITY.md](../SECURITY.md).

## Your plans and the vendors

Pult has no login and no model of its own. It drives the agents already installed and signed in on your computer, with
your accounts and your plans' limits, the same as you would by hand.

- **Claude Code** — your Claude account and plan, the same as in a terminal. Anthropic's
  [Agent SDK documentation](https://code.claude.com/docs/en/agent-sdk/overview) says: *"Unless previously approved,
  Anthropic does not allow third party developers to offer claude.ai login or rate limits for their products,
  including agents built on the Claude Agent SDK."* Pult doesn't offer a login: it runs your own Claude Code for
  you. Still, read the terms of your plan and decide for yourself. Claude Code can also be signed in with an
  Anthropic API key; Pult hasn't been tested that way yet.
- **Codex** — your ChatGPT sign-in, in Codex's own program; a task or a review takes a share of your plan's Codex windows
  (a review's card says how much of the 5-hour one is taken).
- **DeepSeek, GLM, Kimi** — your key with each, paid to them at their prices. Claude Code's prompts are written for
  Claude, and Anthropic doesn't support other models inside it.
- **A model of your own** — Ollama on your computer, or on another one of yours: free, and nothing leaves them; weaker and
  slower than Claude, for the simpler tasks.

Pult is an independent open-source project, not affiliated with or endorsed by Anthropic, OpenAI or any other vendor
it works with. Claude and Claude Code are trademarks of Anthropic, Codex and ChatGPT of OpenAI; other names belong to
their owners.
