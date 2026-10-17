# Pult — notes for coding agents

Pult is a Telegram remote for the Claude Code sessions on a Mac: a per-user launchd daemon (`src/pultd.py`), a
Claude Code hook (`src/pult_hook.py`), an optional VS Code tab wrapper (`src/pult_tab.py`, `src/pult-tab.sh`), the
`pult` command (`src/pultctl.py`, `src/pult_setup.py`) and an optional web app with a relay (`src/pult_web.py`,
`relay/`). Start with [README.md](README.md) and [CONTRIBUTING.md](CONTRIBUTING.md).

## Before you call it done

1. Tests pass: `python tests/test_pult.py`, `tests/test_setup.py`, `tests/test_web.py`, `tests/test_relay.py`.
   They need no Telegram, Claude or user settings. New behaviour gets a test.
2. Say plainly what you could not check for real. The live checks (`tests/e2e_live.py`, `tests/probe_*.py`) use the
   real Claude Code and spend a little of the plan, so run them only when asked.
3. `CHANGELOG.md` gets a line.

## Rules

- **The hook and the tab wrapper never get in the way.** They run in every Claude Code session and every VS Code
  Claude tab. No daemon or any error → exit 0 quietly / exec the real `claude`, byte for byte. Any change there
  keeps `test_tab_wrapper_rules`, `test_hook_without_daemon` and `test_shell_wrapper` green.
- **Facts about Claude Code are checked on a real version**, never assumed from docs: hook payloads, the tab's
  stream-json protocol and the permission race are internals.
- **Never print or log secrets**: the bot token (it's in the Bot API URL), the relay secret, request headers.
  `pult report` stays redacted. Examples and screenshots use made-up data (`tools/stand.py`).
- **Don't edit the user's settings directly.** `~/.claude/settings.json` changes only through `pult hooks` (with a
  backup); VS Code settings are never edited. Don't touch session transcripts in `~/.claude/projects/`.
- Before restarting the service, check that no session started from Telegram is running: a restart interrupts it.

## Style

- Code, comments, logs and commits in English. User-facing strings only through `src/pult_i18n.py` and
  `relay/web/static/i18n.js`, always in English and Russian (`test_i18n_complete`).
- `pult_hook.py`, `pult_tab.py`, `pultctl.py`, `pult_setup.py` use the standard library only.
- Chat messages are for people: no session IDs, paths or tool names where a word will do.
- Match the surrounding code's naming, comment density and idioms.
