# Security

Pult lets a Telegram account run Claude Code on a Mac, so security problems matter more here than in a typical
chat bot. Thank you for reporting them carefully.

## Reporting a vulnerability

Please **don't open a public issue**. Report it privately through GitHub:
[Security → Report a vulnerability](https://github.com/pulthq/pult/security/advisories/new).

Include what an attacker needs and what they get: a short description, steps to reproduce, and the Pult version and your
system (`pult report`, with anything private removed). We'll confirm we got it, keep you posted on the fix, and
credit you in the release notes if you'd like.

## What counts

For example:

- someone other than the owner gets Pult to start or continue a Claude Code session, answer a permission request,
  or read session content;
- the web app relay lets in a login that Telegram didn't sign for the owner, or passes data to anyone else;
- the bot token, the relay secret or session content leaks into logs, `pult report`, the relay or anywhere it
  shouldn't;
- the hook or the tab wrapper can be made to change what Claude Code does without the owner's say;
- `pult uninstall`, `pult setup` or the installer touching files that aren't Pult's;
- "New project" in the web app making a folder outside the owner's home folder, writing into a folder that already
  exists, or handing git a link that isn't https;
- `pult send` or the app's "To Telegram" sending a file from outside the session's project folder or one that looks
  like keys or settings, or a file from Telegram landing outside the project's `inbox/`.

Things that are by design and not vulnerabilities:

- whoever controls the owner's Telegram account controls Pult;
- messages in Telegram are stored in Telegram's cloud;
- sessions started from Telegram use the permission mode set in `PULT_PERMISSION_MODE` (`auto` by default).

## Supported versions

The latest release. Pult is young (0.x), and fixes land in the next version.
