## What and why

<!-- What changes for the person using Pult, and why. Link the issue if there is one. -->

## Checked

- [ ] `python tests/test_pult.py`, `test_setup.py`, `test_web.py`, `test_relay.py` pass
- [ ] New behaviour has tests; anything not checked for real is written here
- [ ] User-facing strings are in both `src/pult_i18n.py` / `relay/web/static/i18n.js` languages (en, ru)
- [ ] If this touches the hook (`pult_hook.py`) or the tab wrapper (`pult_tab.py`, `pult-tab.sh`): with the daemon
      off, Claude Code sessions and VS Code tabs work exactly as without Pult
- [ ] If this relies on Claude Code behaviour: checked on a real Claude Code version (which one?)
