# Contributing to Pult

Thanks for helping. Bug reports, ideas and pull requests are all welcome.

## Reporting

- **A bug:** [open an issue](https://github.com/pulthq/pult/issues/new/choose) and paste the output of
  `pult report`. It prints versions and state with tokens, IDs, folder names and message text removed. Read it
  before posting anyway.
- **An idea:** describe the moment when you needed it. A real situation helps more than a feature name.
- **A security problem:** don't open a public issue. See [SECURITY.md](SECURITY.md).

## Working on the code

```
git clone https://github.com/pulthq/pult.git && cd pult
python3.12 -m venv .venv && .venv/bin/pip install -r requirements.txt -r relay/requirements.txt
.venv/bin/python tests/test_pult.py      # daemon, hook, tab wrapper, rendering, both languages
.venv/bin/python tests/test_setup.py     # install, setup wizard, report, uninstall — in a temporary folder
.venv/bin/python tests/test_web.py       # web app data, the phone → relay → computer chain
.venv/bin/python tests/test_relay.py     # relay
```

None of these need Telegram, Claude or your settings. They use a fake Bot API and temporary folders, and the same
four run on GitHub Actions (macOS, Ubuntu and Windows). `./install.sh` (on Windows, `install.ps1`) installs your
working copy to `~/.local/share/pult` and restarts the service.

Checks that use the real Claude Code, and spend a little of your plan:

- `tests/e2e_live.py` runs sessions from "Telegram" end to end on haiku.
- `tests/probe_tab.py` checks the tab wrapper against a Claude Code binary.
- `tests/probe_race.py` checks the hook racing the permission dialog.
- `tests/probe_background.py` checks what Claude Code reports about background tasks.

`tools/stand.py` serves the web app with made-up sessions (`STAND_LANG=en|ru`), and `tools/shot.py` takes phone-size
screenshots of it. The README pictures come from there. `tools/check.py` runs every check of the app in headless
Chrome with real taps, each on a stand of its own (about 7 minutes; `tools/check.py copy tags` — only those); the
checks share `tools/_cdp.py`, which finds Chrome (`CHROME=<path>` for another one) and takes free ports.

## Where things are

How the parts fit together, with diagrams of each path: [ARCHITECTURE.md](ARCHITECTURE.md).

| | |
|---|---|
| `src/pultd.py` | the daemon: topics, the turn feed, buttons, the Telegram queue, sessions through the Agent SDK |
| `src/pult_hook.py` | the Claude Code hook. Standard library only; it runs on every event of every session |
| `src/pult_tab.py`, `src/pult-tab.sh` | the optional VS Code tab wrapper |
| `src/pult_render.py`, `src/pult_i18n.py` | message rendering; every user-facing string in English and Russian |
| `src/pult_web.py`, `relay/` | the web app: the daemon's side, the relay, the Mini App (Preact + htm, no build step) |
| `src/pultctl.py`, `src/pult_setup.py` | the `pult` command: install, setup, service, report, uninstall |
| `src/pult_spend.py` | usage pace on Resources: a week of transcripts in 5-minute slots, the curve through Claude Code's readings, the forecast |
| `src/pult_attn.py`, `src/pult_brief.py`, `src/pult_load.py`, `src/pult_stt.py` | whose move it is; the optional one-line summary; the computer's load; voice to text |
| `src/pult_new.py` | a new project from the phone: the folder's name from any title, the name checks, the clone link; the daemon makes the folder |
| `src/pult_files.py` | files to and from the phone: safe names, the project's inbox, what `pult send` may send, the files a turn made |
| `src/pult_os.py` | what differs between systems: paths, the service (launchd, systemd, a logon task), idle, the system language |
| `deploy/relay/` | running the relay on a Linux server |

## Rules that keep Pult safe to run

1. **The hook and the tab wrapper never get in the way.** They sit in every Claude Code session and every VS Code
   Claude tab. If there's no daemon, or anything is wrong, they exit quietly or run the real `claude`. A change
   to `pult_hook.py`, `pult_tab.py` or `pult-tab.sh` comes with a check that, with the daemon off, everything
   behaves byte for byte as without Pult (`test_tab_wrapper_rules`, `test_hook_without_daemon`,
   `test_shell_wrapper`).
2. **Verify facts about Claude Code on a real version.** Hook payloads, the tab's message stream and permission
   races are internals. Anything Pult relies on is checked with a probe, and the PR says which version it was
   checked on.
3. **Nothing personal leaves the computer by accident.** Logs never get request headers or tokens. `pult report`
   stays redacted. Screenshots and examples use made-up data.
4. **Other people's settings stay theirs.** Pult changes `~/.claude/settings.json` only through `pult hooks`
   (with a backup) and never edits VS Code settings itself.

## Style

- Code, comments, logs and commit messages in English. Commit subject: `Pult x.y.z: what changed` for a release,
  a plain sentence otherwise.
- User-facing strings only through `src/pult_i18n.py` (bot, `pult` command) and `relay/web/static/i18n.js` (web
  app), always in both English and Russian. `test_i18n_complete` checks this.
- Messages in the chat are for people: no session IDs, paths or tool names where a word will do.
- Match the code around you; keep `pult_hook.py`, `pult_tab.py`, `pultctl.py` and `pult_setup.py` on the
  standard library.

## Pull requests

Keep them small and focused. Say what changes for the person using Pult and how you checked it, including what
you could not check for real. The PR template has the checklist.
