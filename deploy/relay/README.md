# The web app server (relay)

Pult works without a server: the bot, the topics and the buttons need only your computer. The **web app** is an
optional extra — a Telegram Mini App on your phone with every session in full, Claude's questions, new tasks and
usage. Telegram opens Mini Apps only from a public HTTPS address, so the app needs a small server of yours.

```
phone: Telegram → Mini App ──wss /pult/ws──► relay (your server) ◄──wss /pult/agent── Pult on your computer
```

The relay stores nothing: everything the app shows comes from your computer at request time. Strangers are cut off at
the relay by Telegram's signature and your Telegram ID; the computer checks every login again with the bot token, which
never leaves it. The computer connects to the relay by itself, with a shared secret — no ports open on it.

## What you need

- A Linux server with systemd and Python 3.10+ (any small VPS: the relay takes ~50 MB of memory).
- A domain name pointing at it, and HTTPS — nginx with a certificate (for example, certbot) or Caddy.

## 1. On the computer

```
pult app
```

Enter the app's address — `https://your.domain/pult/` — and keep the suggested Mini App link for now
(`https://t.me/<your bot>/pult`; it starts working after step 4). Pult prints three lines for the server's `.env`:
`PULT_RELAY_SECRET` (the computer's key to the relay — keep it private), `PULT_OWNER_ID` and `PULT_BOT_ID`.

## 2. On the server

Copy the Pult folder to the server (`git clone` or `scp`), then as root:

```
sudo bash deploy/relay/install.sh --auto
sudo nano /opt/pult-relay/.env          # paste the three lines from `pult app`
sudo systemctl restart pult-relay
curl -s --unix-socket /run/pult-relay/relay.sock http://relay/pult/healthz
```

The script creates a system user `pult`, puts the relay into `/opt/pult-relay` with its own Python environment and
starts the `pult-relay` service on the socket `/run/pult-relay/relay.sock` — a folder only the relay and your web
server can enter (the script adds the web server's user — `www-data`, `caddy` or `nginx` — to the group `pult`), so no
other program on the server can take the relay's place while it restarts, as one can take a free port. A server set
up before 0.18.7 keeps its port `127.0.0.1:8097`: `PULT_RELAY_SOCKET` in `.env` decides (remove it for the port). The relay
can't change its own code, and its secret in `.env` is read by systemd only; it runs with no network beyond this
machine, no privileges and no devices (`systemd-analyze security pult-relay`: 1.5, "OK"). `--auto` adds the updater: from then on
the server takes each release your computer installs ([Updates](#updates)); without it, re-run the script after a
`git pull` to update. `.env` is kept.

## 3. The web server

**nginx:** copy [nginx-pult.conf](nginx-pult.conf) to `/etc/nginx/snippets/pult.conf`, add
`include /etc/nginx/snippets/pult.conf;` inside the HTTPS `server { … }` block of your domain, and once in
`http { … }` (for example `/etc/nginx/conf.d/pult.conf`) the rate-limit zone and where the relay listens:

```
limit_req_zone $binary_remote_addr zone=pult:1m rate=10r/s;
upstream pult_relay { server unix:/run/pult-relay/relay.sock; }    # set up before 0.18.7: server 127.0.0.1:8097;
```

then `nginx -t && systemctl reload nginx` (the reload also lets nginx in to the socket's folder).

**Caddy:** see [Caddyfile](Caddyfile) — replace the domain; Caddy gets the certificate by itself. Restart Caddy once
after the script, so that it reaches the socket.

Check from anywhere: `curl https://your.domain/pult/healthz` → `{"ok": true, "mac": true}` once the computer is
connected (`mac: false` — see Pult's log, `~/Library/Logs/pult.log` on macOS or `~/.local/state/pult/pult.log` on Linux,
lines starting with `web:`).

## 4. The Mini App in @BotFather

`/newapp` → your bot → a title, a short description and a 640×360 picture → **Web App URL**
`https://your.domain/pult/` → **short name** `pult`. The link is `https://t.me/<your bot>/pult` — the one from step 1
(if you chose another short name, run `pult app` again and change the link).

In Telegram: `/app`, or **📱 Pult** in a topic's pinned bar.

## Updates

With `install.sh --auto` the server follows your computer: once the computer has installed a new release (the app's
**Install**), it tells the relay which one — a tag and a commit, nothing else — and the updater on the server takes
that same release from GitHub. The computer gets no power over the server: no key, no files from it.

```
computer ──"I run v0.18.2 (commit)"──► relay ──want.json──► updater ──git──► github.com/pulthq/pult
```

- The relay only writes the release into `/var/lib/pult-relay/want.json`; a systemd path unit starts the updater
  (`/usr/local/lib/pult-relay/update.py`, the `pult-relay-update` service).
- The updater runs as `pult-update`: it owns the relay's code (`/opt/pult-relay/app`, the Python environment) and
  nothing else — it can't read the secret or touch services.
- Only an official release goes in: the tag on github.com/pulthq/pult must be that very commit, and the commit must be
  in `main`. Never an older one than the server runs — a computer someone took over can't send the server back to a
  release with holes in it.
- It fetches only the release's `relay/` (about half a megabyte), puts it into `/opt/pult-relay/app/releases/` next to
  the one that runs, installs the relay's dependencies if they changed, points `app/current` at it and has systemd
  restart the relay (`pult-relay-restart.path`).
- It counts once the relay answers and the computer is connected again. Otherwise `app/current` goes back to the
  release before — at once when the new relay keeps exiting at start — and the computer says so in Telegram.
- What happened: Settings → Pult and its parts on the phone, or `journalctl -u pult-relay-update` here.
- The computer checks the app files the server hands out against that release, as it does after a deploy: a
  difference closes the app until they match, and Telegram says so — whoever changed the app on the server would
  otherwise run in your window. A CDN or a proxy in front of the server that changes files: `PULT_GUARD=warn` in
  `~/.config/pult/env` on the computer, then a restart — it only warns.

The updater takes the relay's code only. The updater itself and the services change by `install.sh` alone: when a
release changes them, the relay's row in Settings → Pult and its parts says which file is older and asks for
`git pull` and `sudo bash deploy/relay/install.sh` there, once (an updater from before 0.18.6 doesn't say which files
it has — the row asks for the same).

Load: a download of about half a megabyte per release and a second copy on disk; `pip` runs only when the relay's
requirements change. Updating by hand still works: `git pull` and `install.sh` again (it keeps `--auto` on);
`sudo bash deploy/relay/install.sh --no-auto` turns the updater off.

## Turning it off

On the computer: `pult app off`. On the server: `systemctl disable --now pult-relay pult-relay-update.path
pult-relay-restart.path`, remove the nginx include or the Caddy block, `rm -rf /opt/pult-relay /var/lib/pult-relay
/var/lib/pult-relay-update /usr/local/lib/pult-relay`, `userdel pult`, `userdel pult-update`.
