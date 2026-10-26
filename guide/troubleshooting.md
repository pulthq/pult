# When something doesn't work

[README](../README.md) · [Install](install.md) · [Using it](usage.md) · **Troubleshooting** · [Русский](troubleshooting.ru.md)

| | |
|---|---|
| The bot is silent | `pult status` shows the service and the connection to Telegram; `pult restart`. The log: `~/Library/Logs/pult.log` (macOS), `~/.local/state/pult/pult.log` (Linux, Windows). |
| Linux: Pult stops when you log out | `sudo loginctl enable-linger $USER`. |
| VS Code: "Claude Code native binary not found at …" | The wrapper line in the VS Code settings is broken or names a missing file: `pult status` prints the right one; then Reload Window. |
| No sessions from VS Code | The hooks are off: `pult hooks on`, then Reload Window. |
| `409` in the log | Another program reads this bot's updates, such as a second copy of Pult. |
| No permission buttons, but the feed works | Claude Code's `auto` mode decides by itself. That's normal. |
| A message to an open tab went to a copy | The app says why when it offers the copy. The tab was opened before the wrapper: Reload Window. The extension updated: Pult checks a new version on this computer by itself (Settings → Check new Claude Code versions) — while it's being checked, or once it failed (Pult says so in General), messages go as a copy; `pult tab check` checks it again by hand, `pult tab allow <version>` allows it at your own risk; then Reload Window. |
| Something else | `pult report`, then [open an issue](https://github.com/pulthq/pult/issues/new/choose). |

**Several people?** No: one Pult has one owner. **Extra cost?** Hardly: Pult uses what the sessions use, and reading
your limits makes no model request. Its own: a check of each new Claude Code version — about ten short requests every
few days (Settings can turn it off) — and the one-line summary, if you turn it on.
