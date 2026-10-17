# The web app server (relay)

Pult works without a server: the bot, the topics and the buttons need only your Mac. The **web app** is an
optional extra — a Telegram Mini App on your phone with every session in full, Claude's questions, new tasks and
usage. Telegram opens Mini Apps only from a public HTTPS address, so the app needs a small server of yours.

```
phone: Telegram → Mini App ──wss /pult/ws──► relay (your server) ◄──wss /pult/agent── Pult on your Mac
```

The relay stores nothing: everything the app shows comes from the Mac at request time. Strangers are cut off at
the relay by Telegram's signature and your Telegram ID; the Mac checks every login again with the bot token, which
never leaves the Mac. The Mac connects to the relay by itself, with a shared secret — no ports open on the Mac.

## What you need

- A Linux server with systemd and Python 3.10+ (any small VPS: the relay takes ~50 MB of memory).
- A domain name pointing at it, and HTTPS — nginx with a certificate (for example, certbot) or Caddy.

## 1. On the Mac

```
pult app
```

Enter the app's address — `https://your.domain/pult/` — and keep the suggested Mini App link for now
(`https://t.me/<your bot>/pult`; it starts working after step 4). Pult prints three lines for the server's `.env`:
`PULT_RELAY_SECRET` (the Mac's key to the relay — keep it private), `PULT_OWNER_ID` and `PULT_BOT_ID`.

## 2. On the server

Copy the Pult folder to the server (`git clone` or `scp`), then as root:

```
sudo bash deploy/relay/install.sh
sudo nano /opt/pult-relay/.env          # paste the three lines from `pult app`
sudo systemctl restart pult-relay
curl -s http://127.0.0.1:8097/pult/healthz
```

The script creates a system user `pult`, puts the relay into `/opt/pult-relay` with its own Python environment and
starts the `pult-relay` service on `127.0.0.1:8097` (only locally — the web server faces the internet). Re-run it
to update; `.env` is kept.

## 3. The web server

**nginx:** copy [nginx-pult.conf](nginx-pult.conf) to `/etc/nginx/snippets/pult.conf`, add
`include /etc/nginx/snippets/pult.conf;` inside the HTTPS `server { … }` block of your domain, and the rate-limit
zone once in `http { … }`:

```
limit_req_zone $binary_remote_addr zone=pult:1m rate=10r/s;
```

then `nginx -t && systemctl reload nginx`.

**Caddy:** see [Caddyfile](Caddyfile) — replace the domain; Caddy gets the certificate by itself.

Check from anywhere: `curl https://your.domain/pult/healthz` → `{"ok": true, "mac": true, …}` once the Mac is
connected (`mac: false` — see the Mac's log, `~/Library/Logs/pult.log`, lines starting with `web:`).

## 4. The Mini App in @BotFather

`/newapp` → your bot → a title, a short description and a 640×360 picture → **Web App URL**
`https://your.domain/pult/` → **short name** `pult`. The link is `https://t.me/<your bot>/pult` — the one from step 1
(if you chose another short name, run `pult app` again and change the link).

In Telegram: `/app`, or **Open Pult** in the pinned panel of the group.

## Turning it off

On the Mac: `pult app off`. On the server: `systemctl disable --now pult-relay`, remove the nginx include or the
Caddy block, `rm -rf /opt/pult-relay`, `userdel pult`.
