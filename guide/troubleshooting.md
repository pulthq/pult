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
| A message to an open tab went to a copy | The tab was opened before the wrapper (Reload Window), or the extension just updated (Pult said so in General). |
| Something else | `pult report`, then [open an issue](https://github.com/pulthq/pult/issues/new/choose). |

**Several people?** No: one Pult has one owner. **Extra cost?** No: Pult uses only what the sessions use; reading
your limits makes no model request.
