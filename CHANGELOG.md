# Changelog

Versions 0.x come before the first public release. Newest first.

## Unreleased

## 0.18.16 — 2026-10-28

- **A project's earlier tasks get their tags too.** The first time you open a project in the app with the result
  line's model on, Claude sorts its latest 200 tasks that have no tags yet — twenty at a time, from each one's
  title, first request and the last thing Claude said in it, one request after another in the background — once a
  project; "Claude is sorting the earlier tasks: 40 of 120" shows under its sections meanwhile, and the filter then
  finds the whole history. A task keeps its own time, so the tags screen still puts first what was busy in the last
  30 days. **Sort them again** at the bottom of the project's tags asks first, then Claude makes the list anew — from
  the start of the README and CLAUDE.md, the latest tasks' titles and your own tags, which stay as they are — and
  sorts every other task into it; a section it names again keeps its colour.
- **A tag's name keeps a quote that closes one inside it** ("Pulsing «in the background» mark"): the closing quote
  used to go with the end punctuation.
- **Resources weighs a cache read at its model's API price.** Between two readings the curve follows the tokens in
  the transcripts, a cache read at a tenth of an input token for every model until now; at the API's prices Opus 5.5
  reads at 0.05 and Fable 5.1 at 0.025, Sonnet and Haiku at 0.1 as before. The percentages don't change; on a week of
  real work the projects' shares moved by about a point and the week's forecast by one. "On Fable it costs about N×
  as much" now compares the same work — Fable's tokens against their weight at Opus's read price — instead of
  showing Fable's factor itself (7.6× instead of 8.7× on that week); the factor's default and its upper bound follow
  the new weights.
- **How many tokens a project took.** `tools/token_stats.py` counts them from this computer's Claude Code
  transcripts: by kind (cache read and write, output, input), model, source — the project's sessions, their
  background agents, Pult's tests and probes, a session that began in another folder (`--extra`) — and day, with
  what the same tokens cost at the API's prices, how long the sessions worked and how many messages the owner wrote.
  A reply counts once however many lines and session copies repeat it. A background agent's transcript keeps its
  output count from the start of the stream (Claude Code 2.1.300 and 2.1.301): the report estimates that output from
  what the agent wrote.

## 0.18.15 — 2026-10-28

- **A project's tags on a screen of their own.** The tag button beside a project's sections opens its list: each
  section with its topics and how many of the project's tasks have them, the busiest of the last 30 days first.
  Rename a section or a topic, give a section one of eight colours, merge two into one (a topic into a topic of any
  section), hide one — the tasks keep it, but rows, the filter and the hashtags in Telegram don't show it — and bring
  it back from the bottom of the screen. A tag Claude has just made is dashed there, with **Keep** and **Merge
  into…**. With the result line's model on, Claude looks the list over when the names have changed and offers to
  merge two tags that name the same thing; **Keep both** — it won't offer that pair again. Claude goes on with the new
  names: an old one it or a hashtag brings lands on the new tag, and a tag of Claude's that no task has any more goes
  by itself. The button stays in sight however many sections the row has.

## 0.18.14 — 2026-10-28

- **Hashtags under each result in Telegram.** A result in the project's topic ends with the task's section and topic
  as hashtags — `#firmware #filament_sensor`, lower case, words joined with `_` — after its text however it folds;
  Telegram makes them links, and a tap shows every message with one. Settings → **Hashtags in Telegram** turns them
  off; a hashtag copied back into a request sets that topic, as `#topic` always did.

## 0.18.13 — 2026-10-28

- **A chat opens at its very end.** The session screen scrolled to its end before the room under the last message
  was made for the message field — an observer set it a frame later — so now and then a chat opened a little above
  its end, the last lines behind the field. The room is made first now.
- **A background task that ends mid-turn leaves the session's list at once.** Its end reaches the running turn as a
  note of its own, which Pult took for a message and passed by: the app's "in the background" and `pult busy` kept
  the task until the turn was over. Now it goes when Claude Code tells of it — at once in a session Pult runs, at the
  turn's next step in a VS Code tab (`tests/probe_bgmid.py`).
- **The log says what the app's files were checked against** — the release, when the server takes releases
  itself; it said "the deploy" either way.

## 0.18.12 — 2026-10-28

- **For contributors: the app is modules all the way.** Its screens (`relay/web/static/screens/`: home, session,
  settings, projects, resources) and the parts they share (`ui/`: small parts and icons, pictures, the cards that wait
  for you, the computer's load, an update in words) moved out of `app.js` as they were, which now only routes to them —
  68 lines instead of 3145; modules import downwards only (screens → ui → core), checked with
  `tools/js_split_check.py`, and `tests/app_core.mjs` loads every module and links `app.js` — a name nobody exports
  is caught before it reaches a phone. Nothing looks or works differently.

## 0.18.11 — 2026-10-28

- **For contributors: the app's state machines are modules of their own, checked in node.** The connection
  (`core/conn.js`), where you are and Back (`core/nav.js`), this phone's copy following the server (`core/update.js`)
  and voice (`core/voice.js`) — Telegram's own bits in `core/tg.js` — moved out of `relay/web/static/app.js` as they
  were (`tools/js_split_check.py` checks a split moved lines only); `tests/app_core.mjs` runs them in a browser made
  up in node — 23 checks, the voice recorder among them — so their behaviour no longer waits for a phone to be
  checked. Nothing looks or works differently.

## 0.18.10 — 2026-10-28

- **Settings stop asking for `install.sh` once it has run.** The server's updater names its own files in each
  report, but wrote a report only when it took a release — so after `sudo bash deploy/relay/install.sh` put in a newer
  updater, the relay's row kept asking for it until the next release. Now the updater's next look names the files that
  run, the rest of the report as it was, and `install.sh` has it look when it ends.

## 0.18.9 — 2026-10-28

- **A server on a socket takes releases by itself.** Its updater couldn't enter the relay's socket folder — only the
  relay and the group `pult` may — so it never heard whether the relay was up and the computer connected, and refused
  each release with "the computer isn't connected". The updater's service joins the group `pult` now. Takes effect
  where `deploy/relay/install.sh` runs again.

## 0.18.8 — 2026-10-28

- **The server's updater waits its turn.** A run that found the lock taken left at once, trusting the other run to
  look again — but `install.sh` holds that lock to its end, and the release the computer named in those seconds went
  unread, so the computer kept naming it. Now it waits for the lock, up to 15 minutes. Takes effect where
  `deploy/relay/install.sh` runs again (the updater doesn't update itself).

## 0.18.7 — 2026-10-28

- **Install shows up in Settings right after a new version is in the folder.** The parts table read the folder at
  most once a minute, so Settings opened just after a commit said everything was current for up to a minute; now it
  reads it every 10 seconds, as the Pult block before it did.
- **Dependencies are installed only as locked, with their hashes.** `requirements.txt` and `relay/requirements.txt`
  pin every package, the ones they bring along too, with the hashes of their files for macOS, Linux and Windows on
  Python 3.10 and newer; every installer — the computer's, the server's and its updater — installs only those files.
  They are made from `requirements.in` and `relay/requirements.in` by `tools/lock.py`.
- **A new relay server listens on a socket, not a port.** `deploy/relay/install.sh` sets new servers up on
  `/run/pult-relay/relay.sock`, a folder only the relay and the web server can enter, and adds the web server's user to
  the group `pult`; a free port can be taken by any program on the server while the relay restarts. A server set up
  before keeps its port; the nginx and Caddy examples show both.
- **A server also follows the computer where Pult's releases are made.** Such a computer runs commits of its own, so
  it never named a release to its server's updater; now it names the newest release on GitHub that isn't newer than
  the version it runs. The app files check moves from a deploy script's record to that release once the release holds
  what was deployed.
- **Pult looks for a new release right after the computer starts.** "Never looked" read as a look a moment ago
  during the computer's first minute after a boot, so that first look was skipped until the next one.
- **A tap copies a block of code.** Commands and other code in Claude's words, and the command a permission asks
  about, carry a copy sign in the corner; a tap copies the block whole, and a tick and "Copied" say so. Text selected
  by hand inside a block is left alone.
- **Installing an update from the app no longer looks like a failure.** While the computer restarts Pult, the banner
  says it's installing in its calm colour, not the red of a computer gone; the parts table says "Installing…" at once
  and never offers Install again meanwhile — a reload sent as Pult stopped held the next one back for half a minute,
  so the old button stayed and got tapped twice; an answer lost to the restart reads as installing, not as an error.
  Calls to a computer that has gone fail at once instead of after 30 seconds.
- **For contributors: `pultd.py` is split up, one module at a time.** The daemon's Telegram client, its outbox and
  the state database are in `src/pult_tg.py`; the sessions Pult runs through the Agent SDK and what it keeps of every
  live session in `src/pult_driven.py`; the handlers of what the app's screens ask in `src/pult_api.py` and Pult's
  parts and updates in `src/pult_parts.py` — mixins of the daemon's class that read the daemon's own settings through
  the daemon (`self.D`): a module the daemon loads never imports `pultd`, which runs as `__main__`, and a test says
  so; `tools/split_check.py <commit>` checks that a step only moved code. Nothing changes in how Pult works.

## 0.18.6 — 2026-10-27

- **Settings tell what only you can update on the server.** The server's updater takes the relay's code from each
  release, but not itself or its services: when a release changes them, the relay's row now says which file is older
  and that `sudo bash deploy/relay/install.sh` is due there, once. "Install once they're free" survives a restart of
  Pult; a hook event missing reads as a step to take (`pult hooks on`), in amber, not as something broken; and the
  parts table no longer runs git a hundred times a minute when the server's copy matches no commit.
- **Smaller holes closed.** On Linux, Pult's folders for logs and settings are its user's only — anyone on the
  machine could read the messages and paths there; `pult send` refuses more kinds of secrets by their names (key
  stores, tokens and passwords kept as files, databases, Terraform's state); the check of a new Claude Code version
  gives the model no tools at all; the relay lets fewer connections wait without saying who they are (each could
  bring 8 MB first); behind Caddy a client can't pass its own address on any more — take the new `reverse_proxy` block
  from `deploy/relay/Caddyfile`; the relay's requirements are exact versions, and CI's actions are pinned by commit.
- **The relay on your own server runs locked down**: no network beyond the web server on that machine, no privileges,
  no devices, no way into the kernel's settings — systemd's own measure of exposure went from 8.3 ("exposed") to 1.5
  ("OK"). It works as before; re-run `sudo bash deploy/relay/install.sh` once to have it.
- **A server that takes releases itself now closes the app when its files differ from the release**, as a server
  you deploy to always did: before, it only said so in Telegram, and a changed app ran in your window meanwhile. A CDN
  or a proxy in front of the server that changes files: `PULT_GUARD=warn` in the computer's settings — then it only
  warns.
- **More of Pult is checked before it reaches you.** The queue in front of Telegram — three messages at once, then
  one a second; a wait Telegram asks for; one message's edits sent once, its latest text; questions ahead of turn
  updates — is now tested on a clock of its own: every other test turns its limits off. The tests refuse to run
  against Pult's real folder or the real transcripts (`PULT_PROJECTS` points both readers of transcripts at one place)
  and no longer leave a temporary folder behind on every run. What updates Pult is covered where it wasn't: the look
  for a release on GitHub, the installer's own message to Telegram when no version comes up, how a check of a new
  Claude Code version reads a login prompt, silence or a crash, Stop while a turn runs with a message waiting, and
  the server's updater reading systemd, its relay's health and a want that changes on the way. Tests that passed or
  failed by the machine's speed now wait for what they check.
- **One command runs every check of the app in Chrome** — `tools/check.py`, each on a stand of its own; the checks
  share `tools/_cdp.py`: Chrome is found (`CHROME` for another one), DevTools and stands take free ports — two checks at
  once no longer meet on one — and a check's Chrome profile and a stand's temporary folder go when they end.
- **CI checks more than the tests.** A lint job — names that don't exist, imports and values nobody uses (ruff), the
  shell scripts (shellcheck), and whether the version, the changelog, a release tag and the requirements agree
  (`tools/consistency.py`); `tools/ci_local.sh` does what CI does, in a fresh environment, on your own computer.
- **The app's small things.** A folder picked for a new project went back to the default whenever the connection
  blinked; with a sheet open on Home the phone's own Back closed the whole app instead of the sheet; two quick taps on
  ✕ went back twice and left the screen; one Back closed a file and the sheet under it, and the next Back did nothing;
  the late end of a connection already replaced failed the new one's requests. While events came faster than every
  0.4 s — a turn's quick steps, agents side by side — a screen didn't update until they paused; now it keeps up. An
  update started while you read a session looked like "the computer is offline"; a HEIC photo the phone couldn't draw
  was dropped instead of going as a file; told "too many windows", the app now waits for the server to let go of the
  dead ones instead of knocking every few seconds. Rows and folding headings can be reached from a keyboard, ✕ and a
  card's links are easier to hit, and 21 strings nothing used are gone.
- **Small things in the helpers, each visible somewhere.** A permission request whose description ran over two lines
  showed its decided line with no formatting in Telegram; a one-line code block longer than one Telegram message lost
  its first character; an option saying "(Recommended against)" — or a spec such as "(recommended 5 V)" — was ticked
  in advance as Claude's advice, and now only the mark itself counts; a file name in capitals such as README.md could
  become a task's tag; two spend readings in the same second could stop the Resources screen from building; Groq's own
  words in a voice error made Telegram refuse the message; a long paragraph folded in Telegram could be cut through a
  bold word or a link, showing its stars and brackets. The small model that writes the result line and the tags is told
  that the session's text is data, never instructions to it; a replaced voice key's connections are closed; the log
  says why the small model gave nothing; a `claude` whose path has a space counts on the load screen.
- **Small things in the daemon, each a way something could go quietly wrong.** After Telegram asked Pult to wait, an
  older text of a message could land over its newer one; a request nothing of which reached Telegram counted as shown
  there; a turn's outcome waited for its Telegram message before Home had it; a queued turn cancelled the moment it got
  its place kept that place; files from the app that couldn't be taken vanished without a word (now the message says
  so); a hidden folder (`~/.ssh`) was accepted for a new project; an answer that wasn't a list fell apart into letters;
  a second tap of Create showed the system's own error; a message never read stayed "on its way" for good (now crossed
  out after six hours).
- **A session's events are handled in order, and fewer messages go nowhere.** Each hook event arrives on its own and
  its handling waits in between, so two events at once — after a restart mid-turn, say — could both start a turn, or a
  turn's end could slip past a step and leave a turn "working" for good; a session's events now go one at a time (a
  permission request still waits apart). A message to a session of Pult's own while Claude works on a turn it started
  by itself now joins that turn, as it does any other, and one sent as the session closes for idleness resumes it
  instead of being lost. When Telegram refuses to open a project's topic — the bot lost the right to manage topics —
  General says so, instead of that project's turns vanishing without a word.
- **What you are in the middle of is no longer lost.** The app's copy reloads itself when the server has a newer
  one, and it could do so under Telegram's microphone question, during a ready reply's countdown, with answers you had
  ticked but not sent, or while you read a session far from its end — it now waits for those. A ready reply whose
  countdown was running when you left the screen is sent, as it said it would be, instead of quietly dropped; words you
  dictated just as you left come back in that field when you return.
- **A long session reads smoothly on the phone.** Each time the connection came back — Telegram in the background
  for a minute is enough — the session screen reloaded from its end and dropped the earlier history you had scrolled
  to, right under your finger; now it loads only what is new. Loading earlier history no longer rebuilds every message
  on the screen (pictures were asked for again, "Show all" folded back), and a message's text is formatted once
  instead of every second.
- **No false "runs out" right after a limit resets.** Spend from another computer or claude.ai was spread over the
  time since the reset, so 2 % in the first half hour read as 4 % an hour for the whole week, and Home said the week
  would run out until a turn ran here. It is now spread over no less than the span the local pace uses — an hour for the
  five-hour window, a day for the week; spending that is really fast still shows.
- **Three rare failures no longer cost you anything.** A tool call of an odd shape in a session — the model can write
  one, and Claude Code keeps it as written — broke that session's screen in the app for good; now the step shows by
  its name. A long voice message whose upload timed out on the way to Groq got neither words nor "didn't work"; every
  network failure now tries the other route and then says it. And on a busy Mac a slow answer about the screen lock
  could lose the end of a turn — it now counts as "don't know".
- **When Pult runs as many sessions as it may, the app says so.** With five sessions of Pult's own busy, a new task
  from **+** answered "done" for a session that never started — the session screen then couldn't find it — and a
  message to a closed session vanished; the refusal went to the project's topic in Telegram instead. Now the app shows
  it where you tapped, before any picture is saved; a new project is made and says its first turn has to wait. And
  Home no longer fails for a moment when a session ends while it loads.
- **Claude's words show right in the app, whatever they are.** A link to a file with its name in code — the way
  Claude often writes them — showed `�0�` instead of the name; a table made of separator lines alone froze the session
  screen until the message scrolled away. Both are fixed, and the app's markdown can no longer stop a screen: if it ever
  fails, the words show as they are.
- **When the computer has been silent for hours, you can tell.** A computer whose Pult doesn't start — say, its
  Python environment lost its Python to a Homebrew upgrade — looks just like one that is asleep: the hook and the tab
  wrapper stay quiet by design, and the app only said the computer was offline. The app now says since when ("Away
  since 03:10" — the relay counts it), and `pult status` and `pult report` check that Pult's environment can still run
  the daemon, and say what to run when it can't.
- **A server that updates itself doesn't give up on a release because the computer dozed off.** If the computer
  didn't reconnect in the minute and a half after the server switched to a new release — asleep, its network blinked —
  the server went back and never tried that release again, staying behind until the next one. Now it tries again on the
  computer's next word, about ten minutes later, three times in all. And Settings → Pult and its parts has **Try again
  on the server** for a release the server won't try by itself. The server's updater doesn't update itself: to take this
  one, run `sudo bash deploy/relay/install.sh` once on the server, after `git pull`.
- **`install.sh` and `install.ps1` change nothing until every file is at hand.** They copied Pult's files one by
  one over the installed ones, so a file missing halfway left a mix of two versions for the next start. Now they take
  every module in `src/` by a pattern — none can be left out of a list any more — into a folder beside the install
  first, and only then put them in place (on macOS and Linux each by a rename, as Install from the app does).
  `install.sh` has a test of its own that runs it for real in a sandbox.
- **Install puts each file in place in one step.** The hook runs on every event of every Claude Code session and the
  tab wrapper starts with every VS Code tab; an update emptied each file before writing it, so one starting in that
  instant could read half of it. Each file is now written beside its place and renamed over the old one.
- **An update isn't taken back because the app's server is down.** The installer counted a new version in only once
  it had reached the app's server, so with the server down for a minute, Install put the old version back — and,
  as the old one couldn't reach the server either, told you in Telegram that neither had come up. Now the installer
  asks the server itself: if it answers and the new version can't reach it, that version goes back as before; if it
  answers nobody, the update counts. The version going back only has to come up.
- **The relay passes on only what an app window may say: a request.** A window that was in could send the computer
  anything the relay itself sends — a login with an address it made up, a report of the server's updater — and the
  computer took it for the relay's word. Now the relay keeps everything but requests to itself, and the computer
  doesn't log in a window that is in already.
- **Home opens while a new project is cloned from the phone.** The clone's progress and the tasks run with `pult run`
  were kept under one name, so after a clone Home failed to load for up to an hour (and a running `pult run` task broke
  a new project's creation). They are kept apart now.
- **An odd message from the app's server can't stop Pult.** The daemon took the relay's messages in the shapes it
  expected, and one of another shape — a list where a word was due — raised an error that ended the whole daemon, with
  every session Pult runs, and again after each restart while the server kept sending it. Each message is now handled
  on its own: one that can't be is noted in the log and dropped; the server updater's report is read field by field,
  in the shapes it has.
- **Telegram is read the way it was meant to: one request waits up to 50 s for news.** The daemon handed
  Telegram's long-poll timeout to its own HTTP client instead, so Telegram answered at once and Pult asked again every
  few seconds — tens of thousands of requests a day instead of under two thousand, all through the proxy when there is
  one. A message from a topic now arrives the moment it's sent.
- **A network hiccup on the way to Telegram no longer breaks anything.** A timeout, a dropped connection or a proxy's
  error page escaped as a raw error: a session started from Telegram could close, a permission request vanished from
  the app and the computer, and a topic that couldn't be created ended the turn that needed it. Every such failure is
  now handled like any refusal from Telegram — the message isn't sent, the request still waits in the app and on the
  computer, the session goes on. A message to a session of Pult's own reaches Claude before its 👀, not after.
- **Claude's questions let you tick several answers where they combine.** When Claude asks with options and marks
  the question as taking several answers, Pult shows ticks and "Done" — in the app and in Telegram. Claude seldom
  did: it glued the combinations into options of a single choice instead ("Only the server (Recommended) / The server
  and the release / Nothing yet"), mostly when it had advice of its own, and a question holds four options at most.
  The note Pult gives each session at its start (the one about `pult send`) now asks for ticks where the options
  combine, one action per option. A probe on Opus (`tests/probe_multiselect.py`) — where several answers make
  sense: glued options in 5 of 12 questions without the note, none with it, all 12 with ticks; where only one does,
  a single choice both ways. VS Code tabs get it too (their question dialog has ticks), from a session's next start, resume or
  compaction. `tools/ask_stats.py` counts how this computer's sessions ask: how many questions have ticks and how many
  look glued.
- **Claude's advice comes checked.** In a question of several answers, the options Claude marks as its advice
  ("(Recommended)", or the session's own words for it) are checked from the start — in the app and in Telegram — so
  "Done" alone takes the advice, as one tap takes it in a question of one answer; uncheck or add before "Done" as you
  like. Telegram's hint says the advice is checked. A checked option is now filled in the app, not told by its box
  alone. `tools/advice_check.py` checks it with real taps on the stand (`STAND_ADVICE=1`).

## 0.18.2 — 2026-10-26

- **The README opens with what the phone can do.** Twelve tiles under the opening picture — allow or deny, answer a
  question, say what's next, whose move, the whole session, voice, files both ways, a new project, the plan's pace,
  tags, model and effort, Pult keeping itself current — so the whole of Pult is one look, in GitHub's phone app too;
  the navigation starts from them. Two more screens among the features: a project's tasks sorted by Claude's tags,
  and Settings' table of Pult's parts with the release and the Claude Code check. What was one long paragraph of
  everything since 0.15 is a short list. The pictures come from `tools/media.py` as before — the tiles and the two
  screens are new (`glance`, `f-tags`, `f-parts`), from a second stand with tagged tasks and the parts table;
  `tools/media.py glance` redraws one kind. The guide names Settings → Pult and its parts, the install from there
  and the Claude Code check. Every picture is redrawn: Home's cards show a task's title whole, as since 0.18.0.

## 0.18.1 — 2026-10-26

- **Pult checks a new Claude Code version itself, before your tabs move to it.** VS Code updates the Claude Code
  extension by itself, nearly every day, and Pult writes into a tab only on a version it's checked on — so after an
  update, messages to open tabs went as a copy until a Pult release caught up. Now, once VS Code has downloaded a new
  version, Pult checks it on your computer while the open windows still run the old one (they move to it only when
  they reload): a utility command through the tab wrapper, a tab's own request, a message from the phone into the tab,
  switching the model and the effort, and the permission race — on the new version's own `claude`, apart from your
  sessions and settings, with its sessions removed afterwards. About half a minute and ten short requests, almost all
  on haiku. Passed — the version is allowed and nothing is said; failed — one message, Home's line, and "Check again"
  in Settings → Pult and its parts; couldn't run (not logged in, a limit, no network) — tried again in an hour. `pult
  tab check [VERSION]` does it by hand. On by default; Settings → "Check new Claude Code versions" turns it off. A
  release can still block a version (`TAB_BLOCKED`): no check passes it and an install takes it out.

## 0.18.0 — 2026-10-26

- **"Running now" says what runs again.** Each running task shows its title whole — two lines at most, its time
  beside it — then what you asked in this turn (unless that is its title) and what Claude says so far, up to three
  lines; before Claude has said a word, what you asked. The project and the task's tags have a line of their own on
  top, and a tag that doesn't fit is left out whole rather than cut. A project's screen shows its running tasks the
  same way. Since 0.17.0 the tags stood in front of the one line under a running task's title and left nothing of
  it. On a "your move" card the tags moved up beside the project too, so the result line is whole again.
- **Watching a turn end no longer puts its question away.** The session screen re-reads itself the moment a turn
  ends, a few seconds before the small model has read the result; that look counted as "seen", and a turn that
  needed you went grey — off "Your move", no call in Telegram, folded on Home three hours later. Now a look while the
  model reads waits for its word: its "your move" stays until you answer or press "Got it"; only a report, or no
  answer from the model, is seen. The model's "your move" holds even when it can't name what is needed.
- **Writing into VS Code tabs keeps up with Claude Code, and a copy says why.** Pult writes into a tab only on a
  Claude Code version it is checked on, and VS Code updates the extension by itself: since 2.1.301, the only checked
  version, nine more came out, and on any of them a message to an open tab went as a copy. Pult is now checked on
  2.1.310 too (the tab probes, and the extension's code against 2.1.301; its Linux build has the same code). An
  install — `install.sh` or the app's "Install" — now adds the versions its release is checked on to `tab.json`;
  before, only `pult tab setup` did, so a newer check never reached a computer that had Pult already. When the app
  offers a copy, it says why the session takes no message from here: a Claude Code Pult isn't checked on yet, a tab
  started before the wrapper (Reload Window), writing into tabs off or not set up, a project outside the wrapper's
  folders, or a session in a terminal. A "your move" card says "goes as a copy" before you type, as the session's
  own field does, and the "Claude Code is out" message in Telegram says how to get writing back.
- **The app's server updates itself after the computer.** "Install" in Settings put a new Pult on the computer only;
  the relay and the app on your server stayed as they were until someone ran `deploy/relay/install.sh` there by hand,
  and could lag behind for days unnoticed. Now, once the computer has installed a release, it tells the relay which
  one — a tag and a commit, nothing else — and an updater on the server takes that same release from
  github.com/pulthq/pult: only an official one (the tag on GitHub is that very commit, in `main`) and never an older
  one than it runs, so a computer someone took over can't push code to the server or send it back to a release with
  holes in it. The updater runs under an account of its own that owns the relay's code and nothing else (not the
  secret, not the services); it fetches only the release's `relay/` (about half a megabyte), puts it next to the one
  that runs, switches over, and counts it in once the relay answers and the computer is connected again — otherwise
  it switches back by itself (at once when the new relay keeps exiting at start) and the computer says so once in
  Telegram. To turn it on, once, on the server: `git pull`, then `sudo bash deploy/relay/install.sh --auto` (`--no-auto`
  turns it off). Settings' "Pult and its parts" shows the server following, its step while it updates and why a
  release didn't go in; the install block says the server takes the same release; Home has a line while it updates.
  The relay's own code is now read-only to it and its secret is read by systemd only; releases sit in
  `/opt/pult-relay/app/releases/` with `app/current` pointing at the one that runs (`install.sh` moves an older
  install there by itself).
- **A clone of Pult's repository learns of new releases by itself.** Every 5 minutes Pult asks GitHub which releases
  there are (`git ls-remote`, through `PULT_PROXY` when it is set) and fetches a newer one into the folder you
  installed from — nothing there is checked out or changed, nothing installs until you tap "Install", which now takes
  that release and shows what its CHANGELOG says is new. A switch in Settings turns it off; the folder releases are
  made from, and a clone with commits of its own, install from their own HEAD as before.
- **The phone's copy of the app follows the server.** When the server hands out a newer app — after an update, or any
  deploy — the open copy reloads itself a few seconds later, on the same screen, as long as nothing would be lost: no
  words typed anywhere, no menu or picture open, no recording, no request on its way. Otherwise "Refresh the app" in
  Settings, as before.
- **The file check on a server that takes releases from GitHub.** Pult on the computer reads the files of the release
  the server took from its own copy of it and checks that the server hands the phone exactly those; a difference is
  told once in Telegram, and the app stays open (a CDN in front of the server may change files). A server that a
  deploy script fills keeps its own check: a difference closes the app, as before.

## 0.17.2 — 2026-10-26

- **Task tags: a section and a topic.** Every task gets two tags — the section of its project it belongs to and the
  topic in that section, in plain words ("Firmware · Bed levelling") — so tasks running side by side and piling up in
  the history can be told apart at a glance. The small model that writes the result line keeps them: it tags a task
  as soon as its request is in, and again with the result line, in the same request. It picks from the project's own
  list and adds a section or a topic only when nothing fits; the folders and files a task worked with are only its
  hint — there is nothing to set up, no folders or paths to map. The tags show on every task's row (Home, the
  project, its earlier sessions) and under the task's title; on top of a project's screen its sections with how many
  tasks each, a tap narrows every list to one and shows its topics. Correct a task's tags with a tap under its title
  (or `#topic` in a request): your choice stays, the model never changes it again; "Claude picks them" gives it back.
  The model reads the task's title too, so a long task's "go on" or "done" still gets the tags of what it is about,
  and replaces a first guess made from one short request once the task shows what it is.
  It runs on the same switch as the result line — Settings → **A plain line for each result**, off at first; the
  switch now says it tags tasks too, and with it off a task has only the tags you give it. New module
  `src/pult_tags.py`; `tests/probe_tags.py` checks the model on made-up tasks, `tools/tags_check.py` drives the
  screens with taps on the stand (`STAND_TAGS=1`).
- **The result line reads your request** for messages sent from Telegram and the app too, not only those typed at the
  computer.
- **Lines on Home are one line again**, and project names in "While you were away" no longer break mid-word: the file
  viewer's own style (0.15.3) had overridden them.

## 0.16.2 — 2026-10-26

- **A default model and effort.** Settings → **Model and effort**: what the sessions Pult starts begin with — new ones
  from the app and Telegram, and sessions continued from the phone — when a session has no choice of its own, each half
  on its own (a task with Sonnet picked keeps the default effort). "As in Claude Code" leaves it to Claude Code's
  settings, and the menu shows in grey what they say now; Pult only reads them. A new task's field shows the default
  before anything is picked, a session's menu says whose default "Default" is, and "Default" on a running session
  switches it to Pult's default at once. VS Code tabs keep their own settings. `tools/choice_check.py` drives it with
  taps on the stand.

## 0.16.1 — 2026-10-26

- **The parts table reads right for everyone.** The release row shows only in a folder releases are made from (it
  has `publish/build.py`): in a clone of the public repository it said "all released" in green, which read as "you
  have the latest" though Pult never asks GitHub. The hints say what anyone can do — deploy the app again the way the
  server was set up (`deploy/relay/install.sh` on your own server), allow a new Claude Code with `pult tab allow
  <version>` or wait for a Pult release that checks it — and Windows says PowerShell instead of "unknown".
  `tools/parts_check.py` has a stand of someone with a clone (`STAND_PARTS=public`).
- **Every part of Pult in one table.** Settings → **Pult and its parts**: the computer (daemon, hook, wrapper, `pult`),
  the app and the relay on your server, this phone's copy of the app, the wrapper in your VS Code tabs, the hooks,
  Claude Code, and the GitHub release — what each one runs now and how far it is behind the branch of the folder Pult
  was installed from, counted in the commits that changed that part. Green is as in `main`, orange can be brought up to
  date, red doesn't work, grey is to know. A tap opens a row: what's new and who does it — the computer's row holds
  the install block of 0.15.0. The relay names the git blob ids of its own files when the app opens, and the computer
  finds the commit they were made from; the tab wrapper names its own file; this phone's copy compares itself with
  the one the server hands out and offers **Refresh the app**. Home's line now also says what can be done from the
  phone — install on the computer, refresh this copy — and what doesn't work: hook events missing, or tabs on a Claude
  Code the wrapper isn't verified on (writing into them is off). No new network requests: the GitHub row reads
  `CHANGELOG.md` in the folder. `tools/parts_check.py` drives it with taps on the stand (`STAND_PARTS=now|lag|bad`).
- **"Working…" stays under the message you just sent.** In the app, a message sent to a session showed under the
  "⏳ working…" line until the session's chat had it, then jumped above it when the first output came. Now the
  session's state — working, or waiting in the queue — always comes after your messages on their way.
  `tools/ticks_check.py` checks the order in a session that works.

## 0.15.3 — 2026-10-24

- **A link to a project file in Claude's words opens it in the app.** Claude writes file links like
  `[ARCHITECTURE.md](ARCHITECTURE.md)`; the app showed them as a name and a path that couldn't be opened. Now a tap opens
  the file over the chat, and Back returns to the same place in it: Markdown as a page (Text shows the source, and its
  own links count from its folder), code and text with line numbers (a link to `#L124` puts that line in the middle,
  marked), a project's HTML page drawn with no script running, a picture on the whole screen, a folder as a list, and
  the folder in a file's header lists that folder. Anything else says the app can't show it, and **To Telegram** under
  any file sends it to the project's topic (Windows line ends show as plain ones). The rule is the one of To Telegram: only files inside the session's
  project, nothing that looks like keys or settings. `tools/fileview_check.py` drives it with taps on the stand
  (`STAND_FILES=1`).
- **Voice: "speak" waits for sound even after Telegram's microphone question.** Telegram on Android asks for the
  microphone at every new request and remembers nothing, so the first recording of a visit waits for that answer.
  The 1.5 s wait for sound counted from the tap, so after a slow answer "speak" came at once, before sound flowed —
  the very thing that lost the first syllable. It now counts from the moment the microphone is given, and the
  computer's log tells how long the question took ("microphone asked anew: N s").
- **A turn left behind no longer runs for good.** When two events of a session started a turn at the same moment, the
  first one belonged to nobody: nothing ever ended it, and once the session went quiet Pult logged "the session is
  gone from the Mac" every minute, closing the wrong turn. A turn now closes itself — within a minute once another
  one has taken its place, or once its session is gone.

## 0.15.2 — 2026-10-24

- **On Windows, Settings → Pult no longer sees an update that isn't there.** Git for Windows checks Pult's files out
  with CRLF line ends and stores them with LF, so the installed files never matched the commit, and any later commit —
  docs alone — looked like a new version. A file now matches its commit either way.
- **Ticks on your message, as in a messenger.** Claude reads a message sent while it works only at its turn's next
  step, sometimes a minute later, and until then the session showed nothing. Now the message is in the chat as soon
  as you tap Send: a clock while it goes, ✓ when the computer has it ("Claude will read it after the current step"),
  ✓✓ when Claude has read it; every message of yours in the chat has ✓✓. One stopped before Claude read it is crossed
  out, and a tap puts its words back in the field. In a Telegram topic the ✍ reaction on your message turns into 👀
  when Claude reads it. `tools/ticks_check.py` drives it with real taps on the stand (`STAND_TICKS`).
- **"Answer sent" stays three seconds.** The computer drops an answered request at once, so the line that replaced the
  card was gone before it could be read. It now stays 3 s, with a bar along its bottom running out, on Home, a
  project's screen and in a session; the note that popped up at the bottom of the screen with the same words is gone.
- **"Your move" is one line by time.** Questions, permissions and the sessions that wait for you went in two groups,
  each from the longest waiting down; now they are one list, the newest on top and the longest waiting at the bottom,
  on Home and a project's screen. A question or a permission says how long it waits, as a session's card does (the
  computer now sends when it began to wait; with an older one, requests stay on top). `tools/ask_check.py` checks
  both on the stand.
- **Install an update from the app.** Pult now remembers the git checkout `install.sh` ran from. When a commit there
  changes Pult's own files, Settings → Pult says so ("0.15.1 is ready", with the commits' subjects) and **Install** puts
  it in; Home shows one line about it only while there is something to do. If a restart would cut off a turn, a queued
  message or a background task of Pult's own sessions, the button waits: the block lists what runs, and
  **Install once they're free** does it the moment they finish (**Cancel** any time). Only committed files go in, so
  half-made work in the folder stays out, and nothing is downloaded. The installer runs outside the service it
  restarts (macOS: a session of its own; Linux: `systemd-run --user`), keeps the installed files, and counts the
  update in only once the new daemon has stayed up and reached the app's server — otherwise it puts the old version back
  by itself, says why in Telegram, and doesn't offer that commit again. Settings keeps the last installs: when, which
  versions, from the app or the terminal, and how it went. Windows: not yet (update with `install.ps1`).
  `tools/update_check.py` drives every state on the stand (`STAND_UPD`); `tools/update_live.py` installs, updates and
  rolls back a second Pult as a real launchd service; `tests/probe_update.py` holds the launchd and systemd facts.
- **"Working N" no longer restarts on a message mid-turn.** A message absorbed into a running turn — yours, sent while
  Claude works, or another session's — comes with a hook of its own, and Pult took it for a new turn: a session that
  had worked for 19 minutes showed "working 28 s". Claude Code gives such a message the running turn's `prompt_id`;
  Pult now keeps the turn and its start, and the turn's result still answers your latest message. The app's session
  shows the message the moment Claude reads it.
- **A turn waiting in the queue shows, and can start now.** Up to three turns from Telegram and the app run at once;
  a fourth used to wait without a sign — its session looked dead, and a question sent again ran twice. Now the session is
  "in the queue" with the time it waits: an amber chip on Home under Running now (counted apart) and in the session's
  header, a card that says why, with **Start now** — the turn goes over the limit, once. A message from the topic gets
  the same answer there, with the button; it is deleted as soon as the turn starts. Stop while it waits drops the
  message (before, it still ran once a place freed). `tools/queue_check.py` drives it on the stand (`STAND_QUEUE=1`).
- **Pictures on the whole screen, as in Telegram.** A tap on a picture in a session, or on a thumbnail before sending,
  opens it over everything: pinch or double-tap to zoom, drag the zoomed picture, swipe sideways through the message's
  pictures (1 / 3), swipe up or down — or Back — to close; a single tap hides the bars. Before sending, the viewer has
  Crop (the editor) and Remove; the thumbnail no longer opens the editor straight away. `tools/viewer_check.py` drives
  it with real touches on the stand; `STAND_PORT` runs a second stand beside one already up.
- **Home from a session.** A session has no tab bar — the message box takes its place — so the only way out was Telegram's
  Back, and after starting a session that led to the finished form first. The session's header now starts with the
  Home icon (Home › project · state), and so does the bar that stays at the top while you scroll. The new task and new
  project forms step out of the history once they start a session: Back leads to where the form was opened from.
  `tools/compose_check.py` drives it with real taps on the stand.
- **A question of several parts stays open until all are answered.** Claude's question can have several parts, and
  the computer takes the answers one by one; but in the app an answer to the first part replaced the whole card with
  "Answer sent", and the other parts showed up only after the app was opened again. Now an answered part shows its answer
  and the next one waits in the same card; "Answer sent" comes with the last part. `tools/ask_check.py` drives it with
  real taps on the stand (`STAND_ASK2=1`).
- **Picture and File are two choices.** In Telegram on Android the app's file picker is handed to the phone as it is:
  a picker for pictures opens the gallery, a picker for any file opens the phone's file manager — and on some phones that
  came straight back with nothing, so since 0.13.0 a screenshot couldn't be attached from the app there. The new task and new
  project forms now show **Picture** and **File** side by side; in a session the paperclip opens a menu of the two.
- **Where you are, in a session.** A session opens at its last message, so its header — the title, the project, the
  state — was off the top of the screen. Once the header scrolls away, a bar at the top keeps the project (its colour
  tile and name, a tap opens it), the session's title and its state; your last message stays pinned under it.
  `tools/compose_check.py` drives both with real taps on the stand.
- **Voice input hears the whole sentence.** Whisper drops the first syllable when a recording starts quietly, which is
  what a phone's own sound processing does: its gain control starts low and ramps up. The app's microphone now records
  without the phone's echo cancellation, noise suppression and gain control, shows "Microphone…" until sound really
  flows and only then buzzes and turns the dot red; the dot breathes with your voice, and 0.3 s more is recorded after
  Stop so the last word isn't cut.
- **No more made-up words over silence.** A recording without a voice isn't sent ("No voice was heard"), and the
  subtitle credits Whisper writes over silence ("Продолжение следует...", "Thanks for watching") are cut off the end
  of the words, from Telegram voice messages too.
- **Better words.** The default model is `whisper-large-v3` (free on Groq with the same limits and speed;
  `PULT_STT_MODEL=whisper-large-v3-turbo` brings the fast one back). Whisper is prompted with a sentence in your
  language instead of a list of folder names, plus **Your words** — names and terms you add in Settings → Voice input.
  The prompt is kept within Groq's real limit, 896 bytes (a longer one is refused).
- Each recording from the app leaves one line in the log: how long the microphone took, when the voice began, how loud,
  which model — the recording itself is still kept nowhere.
- A permission request decided while its message was still on its way to Telegram — on the computer, in the app or by
  a tap in that very moment — kept its Allow and Deny buttons for ever: the decision found no message to close yet.
  Now the message closes as soon as it arrives. (This was also why `test_permission_allow` failed now and then.)

## 0.14.0 — 2026-10-23

- **One look across the app.** What waits for you — a permission, a question, a turn that needs you — has one warm
  bar and dot; red is kept for failures, refusals and a limit that runs out; green for what works and what is done.
  One set of line icons replaces the emoji the app used as icons (they drew differently on Android and on a Mac):
  permission, question, background, command, computer, phone, files, close, carets. Claude's options and the ready
  replies are one outlined button; your own answer is one round field everywhere, its button shows up once there is
  text. A five-step type scale and one card radius.
- **Home.** "Running now" is a line per session: a beating dot, the title, the time; the context share shows only
  when it is nearly full. "Your move" cards share one head — the project, the title, what kind of question, how long it
  waits. "Always allow" and "Deny with a note" are a quiet line under Allow and Deny, no longer the biggest button;
  "Open the session ›" is gone, the title opens it.
- **A colour for each project.** A tile with its first letter, in one of Telegram's six topic colours, on Home, the
  list of projects, the project's screen and in Resources' "what spent the window". A topic Pult creates from now on
  gets the same colour for its icon (Telegram doesn't let a bot recolour existing ones).
- **The session's header** keeps the title, the project and the state; the model, the effort and the context live by
  the message field only, as in VS Code. The last turn's figures moved into the sheet a tap on that line opens.
- **Resources** has two sections, Limits and Computer, instead of five screens of scrolling; "how it's counted" sits
  behind ⓘ; Pult's own state lives in Settings only.
- **Settings**: one line under each switch, the rest behind "More"; logins in a row from the same device read as one
  line ("6 times"). New task and New project: fields in the card's colour, readable on the page; nothing picked for the
  model reads "As in Claude Code's settings", not "Default · Default". A disabled button is grey, not a pale blue.
- The tab bar has icons; New is the accent button.
- **Telegram: a long result folds.** Its first paragraphs show, the rest sits in a quote that opens with a tap — code,
  links and code blocks included (Telegram keeps them inside, though the Bot API's rules say it wouldn't; a probe,
  `tests/probe_quote.py`, checks it). A code block is never cut in two.
- **Telegram: one message per turn without the app too.** The result takes the place of the turn's "⏳ working"
  message (both said the title and the time, and the quote said it a third time); what you asked shows in the
  result's head when there is no message of yours to reply to. A long turn's reminders go with it.
- **Telegram: a decided request is one line** — "✋ title · Run a command: «Deploy» → ✔️ allowed" — without the
  command's full text again and without "from Telegram" when it was decided right there.
- **Telegram: one sign per meaning.** ⏳ works, ✅ a result, ✔️ decided or done, 🟠 waits for you (it was a red dot, the
  colour of an error), ✋ a permission, ❓ a question, ⚠️ a failure (jobs too, instead of ❌ and ✖), ⚙️ a job. Allow and
  Deny buttons are plain words; "♾ Always allow" and "🔕 Only the result" fit a phone's row. Files and Details sit side
  by side under a result. The topic's pinned card drops the folder's path; `/status` says "idle", not "waiting for you",
  for a session that isn't asking anything.

- **The README is pictures first.** The mark, one line on what Pult does, an opening animation with the computer's
  Claude Code tab next to the phone (a question on both, Allow on the phone, the tab goes on), install in one line,
  how it works in three steps, five features with one phone screen each — light and dark, through `<picture>`. It
  is 110 lines instead of 260: requirements, platforms, commands, security and troubleshooting moved to `guide/`.
  `tools/media.py` draws every picture from the stand in both languages and both themes; `tools/hero.py` draws the
  animation from Pult's own messages.
- **Pult has a mark**: a remote — its body, the button and the warm light of "Claude waits for you".
- A checkbox in the app follows the theme (the files of a turn in the dark).

## 0.13.2 — 2026-10-23

- **The web app follows Telegram's theme.** The colours Telegram doesn't send (fields, choice buttons, code blocks, the
  green and the yellow) followed the phone's own theme: a light Telegram on a dark phone drew them white on a white
  card. Outside Telegram (the stand, a browser) the phone's theme still decides.
- **An answer from the app says so.** Allow, Deny, an approved plan or an answered question shows "✓ Allowed" (and the
  like) at once: in the card while it stays, and as a short note at the bottom of the screen, since the list may drop
  the card right away.
- **The computer offline.** Opened while the computer is away, a screen says nothing can be shown — everything comes
  straight from it, nothing is kept in the phone — instead of "Loading…" for ever; with data already on screen, the
  banner says what time it is from.
- **The topic's pinned card** puts "who works, who waits" first: Telegram shows only the first line in the pinned bar,
  and the topic's current session (🎯) stood above it.
- "Claude finished without text" shows in italics in Telegram, not between literal underscores.

## 0.13.1 — 2026-10-23

- **The screen of a turn's files.** The outcome card has one line, "📎 Files of the turn: N · size", instead of the
  list; it opens a screen where you tick the files you need — nothing is ticked at first, since the list holds
  everything the turn touched — and send them with "To Telegram (k)", one by one or as one zip with the folders
  inside the project kept. More than ten ticked go only as an archive. A zip is packed in the system's temporary
  folder and removed after sending; over 50 MB it is refused, and more than 200 MB of files are not packed at all.
  ‹ › go through the session's earlier turns that had files: Pult keeps the last 50 such turns of each session
  (paths and sizes, in `state.db`). A file deleted since shows as gone. The "📎 Files (N)" button under a result in
  Telegram opens that very turn, not the latest one. Up to 100 files per turn are listed (was 30); past that the
  screen says how many there were.
- The log shows a small file's size in bytes ("436 B"), not "0 KB".

## 0.13.0 — 2026-10-23

- **Files to Claude.** A document, a deck, a spreadsheet or a picture sent or forwarded to a project's topic lands in
  that project's `inbox/<date>/` under its own name (in a git project the folder is excluded locally, never
  committed). The caption is the task; an album goes as one message with its caption; files sent without words wait
  up to ten minutes for your next message in the topic and go with it, and a 👌 says they arrived. Over Telegram's
  20 MB limit for bots, you're told so, and so is Claude. Outside a project topic files go to Pult's own inbox, as
  before. The web app's paperclip takes any file now — pictures as before, other files up to 5 MB in all.
- **Files from Claude.** `pult send FILE… [-m TEXT]` sends files to the project's topic. Claude runs it when you ask
  for a file: every session learns about it at its start, through the SessionStart hook's added context, while Pult
  runs. The command finds its session by Claude Code's own environment (`CLAUDE_CODE_SESSION_ID`). It sends only
  files inside that session's project folder (after links), nothing that looks like keys or settings (`.env`, `*.pem`,
  `id_*`, `.ssh/`, `credentials*` and the like), 1 byte to 50 MB, at most ten at once; each file sent is logged.
- **Files of the turn.** When a turn ends, Pult notes the project's files it made or changed (hidden folders,
  dependencies, caches, the inbox and lock files skipped); the result in Telegram gets a "📎 Files (N)" button into
  the app, and the outcome card there lists them, each with "To Telegram", plus "All to Telegram".
- Pictures from a project's inbox show in the app's chat, like Telegram photos did.
- The `pult` command writes UTF-8 into a pipe. On Windows a pipe got the system's code page, and Russian words or a
  file's name stopped the command midway.
- `tests/probe_sessionctx.py` checks the added context and the session's environment on Claude Code 2.1.300 and
  2.1.301; `tools/files_check.py` drives the files in the app on the stand.
- Docs: ARCHITECTURE and CONTRIBUTING name `src/pult_new.py` and `src/pult_files.py`; ARCHITECTURE lists what a new
  project and a file sent may touch, and SECURITY counts going past those limits as a vulnerability.

## 0.12.0 — 2026-10-23

- **A new project from the phone.** In the web app, "＋ New project" heads the project list of "+" and sits under
  Projects; in Telegram it closes the "which project" buttons. Give it any name — the folder's name is made from it
  (Cyrillic in Latin letters, marks as "_", editable before you create), pick the place folder by folder inside your
  home folder, and choose how it begins: empty (a folder with git), with a description (the first turn writes
  `CLAUDE.md` from your words), or a clone of a repository by its link. Its topic appears in the group at once,
  under the name you gave; a first task, if you add one, starts a session there as "+" does.
- Nothing that exists is touched: a taken folder is refused, and so is a name Claude Code would mix up with another
  folder (it turns every mark in a path into "-", so `my_app` and `my-app` side by side are one project to it).
- A clone goes over https even from a `git@` link (port 22 is often shut), runs at a lower priority with a 15-minute
  limit, shows its progress in the app, and asks first when the repository is over 1 GB. Private repositories clone
  when git on the computer knows your login (`gh auth setup-git`, for one).
- A project made from the phone is in the lists before Claude has ever run in it.
- `tests/probe_newdir.py` checks that a session starts in a folder made a moment ago (no "trust this folder" question)
  and writes `CLAUDE.md` there; `tools/newproject_check.py` drives the new screen on the stand in headless Chrome.

## 0.11.1 — 2026-10-22

- **Crop and rotate a picture before sending it.** In the web app, tap an attached picture's thumbnail (the pencil
  badge) to open an editor like Telegram's own: drag the frame's corners and sides or the frame itself, turn the
  picture a quarter left, mirror it, or fix the proportion — free, original, 1:1, 4:3 or 16:9 (3:4 and 9:16 while
  the frame stands upright). Back or Cancel leaves the picture as it was; tapping the thumbnail again reopens the
  same edit. Telegram's own editor isn't available to Mini Apps, so this one is the app's own code, with no library.
- The cut is made from the original file, and only the result is shrunk to 1600 px: a small part of a big screenshot
  keeps its detail instead of being cut from an already shrunk copy.
- While the editor is open, Telegram doesn't fold the window on a swipe down, so pulling the frame down can't close
  the app.
- `tools/editor_check.py` drives the editor on the stand in headless Chrome with touch emulation and checks the
  result by the colour of each quarter of a test picture.

## 0.11.0 — 2026-10-22

- **Usage pace on Resources.** Each limit — the week and the 5-hour window — now has a curve from its start to its
  reset: what you have used, against the even pace (nothing at the start, the whole limit at the reset), and a
  forecast at your current pace. One line says how it ends: on pace, under (how much will go unused, in hours of one
  session's work, and for the window how many sessions you could add before it resets), or over (when the limit runs
  out and how much slower you'd have to go). Under the curve, on the same time axis: how many sessions and agents
  worked at once. Touch the chart for that hour's spend, sessions and projects; "as a table" gives the same in rows.
  "What spent the week" splits the limit by project; a project keeps its colour.
- The percentages come from Claude Code as before; the curve between two readings comes from the tokens in this
  computer's transcripts (a reply weighs its tokens at the API's price ratios, Fable's factor is fitted to its own
  weekly share), so it passes through every reading. Every reading is now kept in the state database for 60 days.
- The Home strip shows the limit that runs out first (or the fuller one), with ● ▼ ▲ for its forecast, and is red
  only when the limit will run out before its reset. Before, it always showed the 5-hour window.
- Settings: what counts as on pace — 85, 90 (default) or 95 % at the reset.
- "Today by project" is counted from the same pass over the transcripts; reading a week of transcripts takes about
  two seconds at start, after that only what was appended.
- **Docs.** The README is shorter, with a diagram of how it works; the new [ARCHITECTURE.md](ARCHITECTURE.md) (and
  ARCHITECTURE.ru.md) has a diagram for each path — the big picture, a permission answered from the phone, a message
  into an open tab, the web app's login, the usage curve — plus the rules that keep Claude Code safe, a code map and
  where things live. New pictures: Resources with the week and the 5-hour window.

## 0.10.0 — 2026-10-21

- **Windows.** Pult now runs on Windows too; tested on Windows 11 (x64) with VS Code, Telegram and the Claude Code
  extension 2.1.306. Install with `install.ps1`; a Task Scheduler task starts Pult when you log in, with no admin
  rights; the hooks run as programs, not through a shell; the tab wrapper is `pult-tab.exe`; the hooks and
  the wrapper open no console windows. Checked live: the task at logon, a VS Code tab through the wrapper, a message from Telegram into the tab, a
  permission answered from Telegram (Claude Code runs commands through PowerShell when there is no Git Bash),
  logging out and in. Not on Windows yet: the computer's load on the web app's Resources screen. The README has a
  Windows section.
- At start, Pult waits until Telegram answers before it sets the bot's menu, posts the panel and the version notice,
  and reads updates. Right after logging in to Windows the network may come up later (a VPN), and those calls used to
  fail one by one and were never tried again. The app, the tabs and the hooks don't wait for Telegram.
- `pult status`, `pult tab setup` and `pult report` check the wrapper line in the VS Code settings. A line that isn't
  valid JSON (a Windows path with single backslashes: VS Code drops each one with the letter after it) or that names a
  missing file stops every Claude tab in VS Code from starting; Pult now says which settings file and prints the
  right line.
- Windows: the notice that a new Claude Code extension waits for verification was never sent — Pult looked for
  `pult-tab.sh` in the VS Code settings, and on Windows the wrapper is `pult-tab.exe`.
- Tests: `tests/probe_tab.py` and `tests/e2e_live.py` run on Windows. The tab probe builds the wrapper the way the
  installer does (`pult-tab.exe`), and the live test expects the load view to stay empty there. Both passed on a
  Windows 11 machine with the VS Code extension 2.1.306.

## 0.9.30 — 2026-10-21

- A turn stopped from the app or with `/stop` now ends as interrupted. Claude Code sends no Stop hook for an
  interrupted turn, only the turn's result, so the session stayed "working" in the app and in `pult busy`, and its
  idle Claude process was never closed. Pult now closes a turn that has a result but no Stop a few seconds later.
  `tests/probe_midturn.py stop` shows it on a real Claude Code (2.1.300).

## 0.9.29 — 2026-10-21

- A message written while a session started from Telegram or the app is working now reaches Claude in that turn, at
  its next step, as in a VS Code tab. Before, Pult held it until the turn's result, so "stop, wrong project" waited
  out a ten-minute turn. The app shows such a message in the chat, marked as written during the turn.
  `tests/probe_midturn.py` shows it on a real Claude Code (2.1.300).
- Stop stops: messages still waiting in Pult are dropped instead of starting the next turn one by one, which had
  made Stop look as if it did nothing. A message Claude Code already holds runs after the interrupt, as Claude Code
  itself does.
- New task: the project, the model and the effort are picked from the app's own lists instead of native drop-downs,
  which failed to pick a project in Telegram on Android; a list stays as it was while it is open. The form starts on the
  project last started from it, not on the project that needs you first, which sent a task to the wrong project.

## 0.9.28 — 2026-10-21

- A session started from Telegram or the app no longer crashes when Claude reads a picture. A picture comes in the
  Claude process's stream twice, in the tool result and again beside it, so one ordinary ~470 KB screenshot made a
  line over the Agent SDK's default 1 MB limit, and the SDK ended the session in the middle of its turn. Pult now
  takes lines up to 64 MB. `tests/probe_bigline.py` shows both on a real Claude Code (2.1.300): the default limit
  fails on such a picture, Pult's goes through.
- A new session opened in the app right after it was started shows an empty chat until Claude Code writes the
  session's file, instead of "session transcript not found" for a moment.

## 0.9.27 — 2026-10-21

- After a restart in the middle of a turn, the turn and the start of the owner's run now appear together: for a
  moment the app could count "working N" from the turn instead.
- Tests: two checks of the run's start wait for the daemon to read the hook's event — on Windows the hook can finish
  first. That is why 0.9.26's tests failed on Windows; macOS and Linux were green.

## 0.9.26 — 2026-10-21

- Restarting or stopping Pult no longer cuts off its own sessions without a word. `pult busy` asks the daemon what a
  restart would cut off: sessions started from Telegram or the app with a turn running, prompts queued, or background
  tasks, subagents included, even once the session's turn has ended. Without a terminal (a script, an agent),
  `pult restart`, `pult stop`, `install.sh` and `install.ps1` refuse while something runs; in a terminal they ask, "no"
  by default; `PULT_FORCE=1` goes ahead anyway. Before, an update run by a script killed a background subagent in a
  session started from the app, and the session never learned of it.
- On macOS, the daemon's Claude processes are found when asked from inside one of its own sessions: `pgrep` there
  leaves out the asker's ancestors unless told otherwise.
- Home opens with "Running now": every session with a turn in progress, every session with background tasks, every
  task without Claude still running — the earliest started on top in each kind, so new ones come in below. A row is
  two lines: the title with its time chip, then the project and what it does now. They leave the project blocks
  below, and the finished tasks without Claude stay at the bottom: nothing shows twice.
- The app's chips with a running time — "working 14 s", "running 25 min" for a task without Claude, and now
  "background 3 min" — keep one width as the time ticks, all of them the same: the digits are tabular and each chip
  is as wide as its longest form ("working 59 min"); past an hour they show whole hours. "Background" counts from when
  Pult first saw the oldest task still running and pulses too, in grey, on the board and on the session screen; a tap
  opens the task card as before.
- "Working N" in the app counts from the owner's own prompt: a turn Claude starts by itself — a background task or a
  subagent reported back — goes on with the same work instead of starting the clock again. Telegram's turn messages
  keep each turn's own time. After a restart the start comes from the transcript.
- A subagent that hands its report back itself (an `<agent-message>` before its task notification) starts Claude's own
  turn, like a finished background task: shown as "Background task finished", not as the owner's prompt.
- Reading isn't deciding: an outcome that waits for the owner's decision (the model named what is needed) or a turn that
  broke off stays in "Your move" after the session is opened, until the owner answers, writes to the session or presses
  "Got it" — now also on the outcome card at the end of the session. A plain report, or "your move" guessed without the
  model, is put to rest by opening the session, as before.
- The Home strip no longer cuts its text on a phone: the "where you are" and "limit · CPU" chips are now small tiles,
  a label over a value ("🔄 Auto" over "away 12 min", "limit" and "CPU" over their numbers). A style meant only for
  the first chip clipped every piece of the second one — "lim… · CPU 1…".
- Groundwork for Windows. Windows itself is not released yet: it waits for a check on a real machine. The daemon's
  link can run over 127.0.0.1 with a key from the link file; the VS Code tab wrapper becomes `pult-tab.exe`, which runs
  claude without a console window and ends it together with the tab; hooks use Claude Code's exec form (no shell); a
  Task Scheduler task starts Pult at logon; there is an `install.ps1`. GitHub Actions now run on Windows too, with a
  real install and removal.
- `pult run` keeps the last line of output when lines end with CRLF. The tail used to come out empty.
- Checking whether a process is still there no longer uses `os.kill(pid, 0)`: on Windows that call ends the process.

## 0.9.25 — 2026-10-20

- A Telegram message with choice buttons says what was chosen once it's done: "Which session?", "Which project
  should it run in?", "Continue as a copy" and "Log out everywhere" keep their text, gain "→ the choice" and lose
  their buttons, so the other buttons of a decided question can't start a second session. Menus (projects to open,
  sessions to look at) stay as they are.
- A "your move" call shows the answer from wherever it came — the app, a VS Code tab, a reply in the topic — not only
  from its own buttons; "Continue at …" folds it with the time. A reply that can't go in (the session is open on the
  computer without Pult's wrapper) no longer folds the call.

## 0.9.24 — 2026-10-20

- Behind a TCP proxy that passes no client address (nginx `stream` without PROXY protocol) every phone reaches the
  relay as 127.0.0.1. The relay no longer applies its per-address limit to such an address (one stranger's three idle
  connections would have locked everyone out), and the computer treats it as unknown: never a "new network", never
  learned as one.

## 0.9.23 — 2026-10-20

Security, after a review of how someone could get in without the owner's Telegram account.

- A new app login takes an initData Telegram made minutes ago (it used to be a day). A reconnect — the network blinked,
  the computer or the relay restarted — logs in with a one-time key the computer gave that window; each use gives the
  next one, and the computer keeps only hashes. An initData that leaked from somewhere is no longer a day-long pass.
- An app login from a network Pult hasn't seen is told in Telegram, with sound and a "Log out everywhere" button.
  Settings → Logins in the app lists recent logins (when, network, device, how) and logs every window out.
- Someone else holding the bot token is told: the app button in your chat is rechecked every 30 minutes and put
  back if changed (a changed button would hand a real login to another page); a webhook on Pult's token is removed;
  Telegram's 409 that persists ("someone else reads this bot") is reported. Each alert says how to change the token.
- The computer can check that the relay hands the phone exactly the files that were deployed: when
  `~/.local/share/pult/web-manifest.json` exists (`pult_web.make_manifest(relay/web)`, written by a deploy script), a
  difference that holds for 90 seconds closes the app — logins refused, windows closed — until the files match
  again, and is told in Telegram.
- Links show where they lead: when a link's words don't show its address, the domain follows in brackets, in
  Telegram and in the app (non-Latin names in their `xn--` form, so a look-alike letter doesn't pass).
- The app's page has a Content-Security-Policy: scripts only from the relay and telegram.org, connections only back
  to the relay.
- The relay tells a stranger nothing about why a login was refused, no longer says in `/healthz` how many windows are
  open, and holds at most 3 unidentified connections per address (30 in all) for at most 10 seconds.
- The relay can listen on a unix socket (`PULT_RELAY_SOCKET`) instead of a port. On a server shared with other
  programs, any of them could take a free port while the relay restarts, and the web server would hand the phone that
  program's page; a socket in a folder only the relay and the web server can enter can't be taken.

## 0.9.22 — 2026-10-20

- The README opens with Home of the web app next to the topic animation: what waits for you, with ready replies,
  and every project's live sessions.

## 0.9.21 — 2026-10-20

- A result's line is no longer cut in the middle of a word: the model often writes a little more than asked, so up
  to 180 characters stay whole and a longer line ends after a whole word. In a session, the outcome card shows up
  only when there is something to do (a question, ready replies, a broken-off turn); a plain report needs no card —
  the whole answer is right above it.

## 0.9.20 — 2026-10-20

- Every signal leads to its cause. A project's screen is its board, large: what waits for you (answer right there),
  what runs, today's outcomes, the earlier sessions folded, a new task under the thumb. A session opens at its
  outcome: a card at the end of the chat says what came out and what is needed, red while it waited for you; long
  messages that are not the last are folded. The Projects tab uses the same rows: who waits, who works, the latest
  outcome.
- Ready replies: the small model that writes the result's line also picks up to three replies from Claude's own
  message ("By popularity", "Yes, go ahead"). One tap sends one, with three seconds to undo — on Home, on the project
  screen, in the session and under a call in Telegram. A "Your move" card also takes your own words and the
  microphone without opening the session.
- Telegram is a pager where the app is set up (Settings → "Telegram: only what needs me"; off — the whole feed as
  before; without the app nothing changes). New messages only for what waits for you while you are neither in the
  app nor at the computer, and for your own messages in a topic — one message per turn. Each call has the line,
  what is needed, the ready replies and a button straight into that session; seen or answered anywhere, it folds
  into "✓ …". Milestones stay in the app. A topic's pinned card shows who works and who waits.
- Where you are: the app tells Pult while it is on your screen; at the computer, a locked screen means away at once,
  and a still keyboard after 5 minutes (2 where the lock can't be read). The modes keep their meaning: 📱 always
  calls, 💻 never, 🔄 only when you are away.
- "While you were away": back in the app after an hour or more, a card on top says how many turns ran, what is
  done and what waits, a line per project.
- A turn broken off by the usage limit offers "▶ Continue at 04:10": Pult says "continue" in the session a minute
  after the 5-hour window resets (cancel any time before).
- Resources: the Usage tab now holds the plan's limits, the computer's load and Pult's own state. The top line of
  Home stays grey while all is well and takes colour only when a limit or the processor runs high.
- A new task starts in the project you were busiest in. `tests/e2e_live.py` checks the pager with a real Claude.

## 0.9.19 — 2026-10-20

- Claude can show you a picture in the app: when its reply names an image in Pult's inbox
  (`~/.local/share/pult/inbox/<month>/…`), the session shows the picture under the message (a tap opens it full
  screen) and the bare path leaves the text. Only the inbox can be shown, as with your own screenshots.

## 0.9.18 — 2026-10-20

- Home is built around whose move it is. On top, "Your move": permission requests and questions to answer right
  there, then sessions that ended and need you, the longest waiting first; "Got it" puts one to rest, and so does
  opening it. Below, "Projects": each project with who works and who waits, today's turns, and a line per live
  session — what Claude is doing now or how its last turn ended, with the context gauge; resting sessions are
  folded. The separate "Recent results" and "Open on the computer" lists are gone: nothing repeats. The "where you
  are" strip and the load line are one line now.
- Whose move: a session is Claude's while a turn runs or a background task will wake it, and yours when it waits
  for an answer, broke off, or ended a turn you haven't seen. A turn you typed at the computer and watched end is
  seen at once. Each session's last outcome and today's turns per project survive a restart.
- An API error that ends a turn (the usage limit, a sign-in problem, an overload) now ends it as a failure: Claude
  Code sends `StopFailure` instead of `Stop` (2.1.301, checked). The result in Telegram says what happened, the
  session waits for you on Home. A new hook event: run `pult hooks on` to add it to your VS Code tabs; sessions
  started from Telegram get it right away.
- Optional (Settings → "A plain line for each result", off by default): a small model reads each result — haiku,
  on your own subscription, no tools, no settings, nothing saved as a session — and writes one plain line for Home
  and whether Claude waits for you. About 5 seconds and 260 MB for a moment per result; when it can't answer, the
  first sentence stays. `tests/probe_brief.py` measures it.

## 0.9.17 — 2026-10-20

- Fable in the model menu: a new session and a session's model switch offer Fable, Opus, Sonnet and Haiku. Claude
  Code 2.1.300 and 2.1.301 take the `fable` alias and run Claude Fable 5.1 (checked with one request).

## 0.9.16 — 2026-10-19

- The load on the computer, in the app. Home gets one line under the "where you are" strip: the computer's processor
  and memory now, and how much memory Claude's sessions hold. A tap opens a screen with the computer's processor
  (cores, load average) and memory, then every Claude session on it, the busiest first, each with the commands
  running under it (⚙️ in the background, ▶ in a turn) and any other busy program; resting sessions are folded.
- A tap on "in the background" (on Home and in a session) shows each background task: how long it has run, the
  processor now and in total, the memory now and at its peak. A subagent says it thinks on Anthropic's servers.
- The processor is shown as a share of the whole computer, so the sessions add up to its figure. Memory on macOS is
  the physical footprint, as Activity Monitor counts it; the peak and the total processor time come from the system
  (`proc_pid_rusage` on macOS, `/proc` on Linux), finished commands included. Programs that are not Claude's commands
  (MCP servers) show only their name: their arguments may hold keys.
- Measured only while the app is open: one process snapshot (about 50 ms) at most every 4 seconds. Windows shows no
  load yet.
- `tests/probe_load.py`: how a background task looks among the processes (Claude Code 2.1.301); `tests/e2e_live.py`
  checks that the load view finds a real background command.

## 0.9.15 — 2026-10-18

- The message field's keys are Telegram's: with a real keyboard (Telegram on a computer, the web), Enter sends and
  Shift+Enter or Cmd/Ctrl+Enter breaks the line; on the phone Enter breaks the line and the button sends. Until now
  Enter always broke the line and Cmd/Ctrl+Enter sent.
- The microphone is asked for once: Telegram on Android shows its "allow the microphone?" dialog at every new request,
  even one already allowed, so the app keeps the microphone (muted between recordings) while it is on the screen and
  lets it go when the app goes to the background or after ten minutes without a recording.
- Docs: the README names all seven hook events (`PostToolUseFailure` was missing) and lists `pult stt` among the
  commands; the relay guide says "computer" where it said "Mac".

## 0.9.14 — 2026-10-18

- The app shows the microphone button only when a Groq key is set; without one the paperclip stands alone, as
  before 0.9.13.

## 0.9.13 — 2026-10-18

- Voice input. A voice message in a project topic (an audio file or a video note too) is recognized and goes on
  exactly as typed text would: to the session you reply to, the topic's current session, or the "which session?"
  question. The turn shows "You: 🎤 …" and Claude is told the words were spoken, so misheard words are expected.
  In the app, a microphone button next to the paperclip (the session and the new task) records up to five
  minutes; the words land in the message field to check and send. Recognition is done by Groq (Whisper
  `whisper-large-v3-turbo`): the recordings go there and are kept nowhere; a free key is made at console.groq.com
  and set in the app's Settings → Voice input or with `pult stt` (`pult stt off` removes it; the daemon picks up
  the change without a restart). The language is Pult's own; `PULT_STT_LANG=auto` lets Whisper guess. Without a
  key nothing changes.

## 0.9.12 — 2026-10-18

- Claude's own lines about its progress, the ones the VS Code tab shows as "summary", now reach the app: they sit
  among the steps of a turn, the collapsed steps block ends with the latest step or line, and a line said before
  any step stands on its own. The turn's "now" line in Telegram takes them too. Claude Code marks such an entry
  in the transcript (`thinkingDisplay: "updates"`, 2.1.296–2.1.301, from the tab and from the SDK alike); plain
  thinking stays private, and only the words leave the transcript, never the block's signature.

## 0.9.11 — 2026-10-18

- A session started from Telegram and then opened from the history in a VS Code tab takes messages from the phone
  straight into that tab right away. Before, the tab wrapper read the session id only from `--resume <id>` as two
  arguments, while the extension (2.1.301) passes `--resume=<id>` as one, so until the first turn typed in the tab
  the app offered a copy instead.
- The message fields of the app take words as typed: no automatic capitals, no autocorrect, no spelling marks, on
  the phone and in Telegram on the computer.
- Cmd+Enter on a Mac (Ctrl+Enter elsewhere) sends the message or starts the new task, as in Telegram; Enter alone
  still adds a line.

## 0.9.10 — 2026-10-18

- The README opens with an animation of a project's topic: Claude at work, a permission request with the phone's
  notification, a tap on Allow, the turn going on, its result. Like every picture there, it is drawn from Pult's own
  messages on the test stand, never from a real project.
- The web app is shown as it is now: the session screen with your message pinned and the model with its effort
  dots, and Home, the model and effort menu and Usage side by side in phone frames.
- The comparison with Remote Control and Channels is a table, checked against their documentation: Remote
  Control works in VS Code tabs too and can connect every session, so the README no longer claims otherwise.
  Install is one line at the top; the Linux notes and troubleshooting fold away. The Russian README matches.
- `tools/media.py` remakes every README picture in both languages, plus a 1280×640 link preview
  (`media/social.png`, for the repository's settings). `tools/chat_shot.py` draws the animation when asked for
  a `.gif`; `tools/shot.py` hides scrollbars and can leave the background transparent (`SHOT_CLEAR=1`).

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
