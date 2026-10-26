# Installing Pult

[README](../README.md) · **Install** · [Using it](usage.md) · [Troubleshooting](troubleshooting.md) · [Русский](install.ru.md)

## What you need

- macOS, Linux or Windows; tested on macOS 26 (Apple Silicon), Ubuntu 24.04 (arm64) and Windows 11 (x64).
- Claude Code, signed in: the VS Code extension, the CLI or both. Tested with the extension 2.1.301 (on Windows,
  2.1.306) and the Agent SDK 0.2.167.
- Python 3.10+: `brew install python@3.12`, `sudo apt install python3 python3-venv`, or on Windows
  [python.org](https://www.python.org/downloads/windows/) / `winget install Python.Python.3.12` (not the Microsoft
  Store one).
- Telegram and a bot of your own, created in @BotFather; the setup walks you through it.

## Install

```
git clone https://github.com/pulthq/pult.git
cd pult
./install.sh
```

The installer makes its own Python environment in `~/.local/share/pult`, puts the `pult` command into
`~/.local/bin` and adds a background service (launchd on macOS, a systemd user service on Linux). Then a wizard:

1. **Bot.** In @BotFather: `/newbot`, paste the token.
2. **You.** Open the link it shows on your phone and tap **Start**: Pult learns your ID and language.
3. **Group.** Create a group with **Topics** on, add the bot as an admin with **Manage Topics** and **Pin
   Messages**, send `/bind@your_bot` there. The wizard checks it and says what's missing.
4. **Hooks.** Pult adds its hooks to `~/.claude/settings.json`, keeping your other settings and a backup.

Then **Developer: Reload Window** in VS Code, so open tabs pick up the hooks. Optional:

- `pult tab setup` — writing into open tabs: one line for the VS Code settings;
- `pult app` — the web app (below);
- `pult stt` — voice messages as text, with a free Groq key.

## The web app (optional)

A Telegram Mini App on a small server of yours, one tap from any topic — the comfortable way to work from the
phone. It needs a Linux server with a domain and HTTPS: [deploy/relay/README.md](../deploy/relay/README.md). The
server only relays: it stores nothing. Without it, everything else works in the chat alone.

## On Linux

- **A desktop with VS Code or a terminal:** the same as on a Mac.
- **A server opened in VS Code through Remote-SSH:** Claude Code runs on the server, so install Pult there; the line
  from `pult tab setup` goes into the server's settings (**Preferences: Open Remote Settings (JSON)**).
- **Claude Code in a terminal over SSH:** sessions, permissions and questions come to Telegram the same way.
- A user's services stop when they log out: `sudo loginctl enable-linger $USER` keeps Pult running and starts it at
  boot (the installer reminds you).
- "Away from the computer" comes from GNOME, KDE or X11; elsewhere, from what you do in sessions.

## On Windows

Get Pult with `git clone` or as the ZIP from [Releases](https://github.com/pulthq/pult/releases), then in PowerShell,
in its folder:

```
powershell -ExecutionPolicy Bypass -File install.ps1
```

- **Python** is found with the `py` launcher; the Microsoft Store one runs sandboxed and won't do.
- **The service** is a Task Scheduler task, "Pult", that starts at logon, with no admin rights.
- **The `pult` command** goes to `~\.local\bin`, added to your PATH: open a new terminal after installing.
- **No console windows:** the hooks and the tab wrapper (`pult-tab.exe`) run without one.
- **The wrapper line** that `pult tab setup` prints doubles each backslash, as JSON wants. If VS Code says "Claude
  Code native binary not found at C:sers…", the line lost its backslashes: `pult status` shows the right one.
- **Without Git Bash** Claude Code runs commands through PowerShell; their permission requests come the same way.
- **Behind a VPN** Telegram may be out of reach right after logon; Pult waits for it.
- **Not on Windows yet:** the computer's load on Resources. The log: `~\.local\state\pult\pult.log`.

## Update

Pult looks for a new release on GitHub every 5 minutes and fetches it into the folder you installed from (nothing
there changes; a switch in Settings turns this off). When one is out, Home says so: tap **Install** in the web app
(Settings → Pult and its parts → Computer). Without the app, or with the switch off:

```
cd pult
git pull
./install.sh
```

The button installs a release, or, in a folder with commits of your own, what is committed there — and only once a
commit changed Pult's own files. If a restart would cut off sessions started from the phone, it lists them and offers
**Install once they're free**. A new version that doesn't come up is replaced by the old one on its own, and
Telegram says why. The Computer row keeps the last installs. On Windows, run `install.ps1` again.

The app and the relay on your server follow the computer by themselves once the server has the updater — once, there:
`git pull`, then `sudo bash deploy/relay/install.sh --auto` ([how it works](../deploy/relay/README.md#updates)). Without
it, run `deploy/relay/install.sh` there again after a `git pull`. The same table shows every other part against this
folder's branch: this phone's copy of the app (it reloads by itself when nothing is typed; else **Refresh the app**),
the wrapper in open VS Code tabs (Reload Window), the hooks (`pult hooks on`) and the Claude Code version.

## Turn it off, remove it

- `pult hooks off`, then Reload Window: Pult stops seeing sessions. `pult tab off`: new tabs start without the
  wrapper.
- `pult stop` / `pult start`. While sessions started from the phone are at work, stopping or restarting would cut
  them off: in a terminal Pult asks first, without one it refuses (`pult busy` shows what runs; `PULT_FORCE=1` stops
  anyway).
- `pult uninstall` removes the service, the hooks, the command and Pult's files, and asks about your settings with
  the bot token. The bot and the group stay in Telegram.

Claude Code works exactly as before without Pult.
