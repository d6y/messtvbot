# Masthead setup walkthrough

## 1. Create a Slack app

In your Slack workspace, create a new app (api.slack.com/apps →
"Create New App" → "From scratch"). Under **OAuth & Permissions**, add
these Bot Token Scopes:
- `channels:history` (or `groups:history` if the channel is private)
- `files:read`
- `users:read`
- `chat:write` (so it can reply in-thread when accepting/removing a
  post, and announce expirations)

Install the app to your workspace, then copy the **Bot User OAuth
Token** (starts `xoxb-`) -- this is `MASTHEAD_SLACK_TOKEN`.

Invite the bot to the channel people will post signage content to
(`/invite @YourAppName` in that channel), then find the channel's ID
(right-click the channel → "View channel details" → the ID is at the
bottom, or use the Slack API's `conversations.list`) -- this is
`MASTHEAD_SLACK_CHANNEL`.

## 2. Configure Masthead

```
cp config/masthead.env.example config/masthead.env
```

Edit `config/masthead.env`:
- `MASTHEAD_SLACK_TOKEN` and `MASTHEAD_SLACK_CHANNEL` -- from step 1
- everything else has a reasonable default; see the comments in the
  file for what each one does

## 3. Install

**Pi:** `./install/install-pi.sh` -- installs `poppler-utils`/
`chromium`/`unclutter`, sets up two systemd **user** services
(`masthead-serve`, always running the web server) and a timer
(`masthead-refresh`, polling/rendering every 2 minutes by default), and
adds a kiosk autostart entry so Chromium launches full-screen after
login. It also enables "linger" so those services keep running even
without an active graphical login.

**Mac:** `./install/install-mac.sh` -- installs `poppler` via
Homebrew, and optionally installs `launchd` agents so the refresh loop
and web server run in the background the same way they do on the Pi
(you'll be prompted; say no if you'd rather just run things manually
while developing).

Both scripts also run `pip3 install --user --break-system-packages -r
requirements.txt`, which installs `dateparser` (used to parse the
scheduling phrases in thread-reply commands, see below). The
`--break-system-packages` flag is needed because newer Debian
(Bookworm+) and macOS Python builds refuse `pip install` outside a
virtualenv by default (PEP 668) -- `--user` keeps the install scoped to
your account rather than touching the system Python.

## 4. Verify

```
systemctl --user status masthead-refresh.service   # Pi
cat ~/masthead-data/data/manifest.json
curl http://127.0.0.1:8420/data/manifest.json
```

Post a message with an image or some text in your Slack channel, wait for the next refresh
interval (or force one -- see below), and confirm it shows up in
`manifest.json`.

Forcing an immediate refresh:
```
systemctl --user start masthead-refresh.service   # Pi
python3 bin/masthead-refresh.py config/masthead.env   # Mac / manual
```

## 5. See it full-screen

**Pi:** reboot, or run `kiosk/launch-kiosk-pi.sh` directly to test
without rebooting.

**Mac:** `kiosk/launch-kiosk-mac.sh` (Cmd+Q to quit -- this is a
preview, not a real lockdown).

## Ordering and removing content

Slides play in the order they were posted to the Slack channel
(oldest first). A message remains in rotation for `MASTHEAD_SLACK_TTL_DAYS`
(30 days by default), then automatically expires.

To remove a message from the rotation, reply to it in its thread with
"cancel", "delete", "undo", or "remove". A bare command word (or one
followed by "now") removes it immediately. Add a time phrase after the
command word to schedule the removal instead:

- `remove` / `remove now` -- remove immediately
- `remove in 1 week` -- remove 7 days from now
- `remove thursday` -- remove on the next Thursday
- `remove 3 Sept` -- remove on that date
- `remove 3 Sept 10am` -- remove at that date and time

Time phrases are parsed with `dateparser`, so a fair amount of natural
language works; if a phrase can't be parsed, the command falls back to
an immediate removal rather than erroring. Multi-page PDFs expand into
one slide per page, in page order, at the point the message was posted.

The bot posts back to Slack so it's obvious what happened to a post:
a thread reply when it's accepted onto the display, a thread reply
when it's removed or scheduled for removal via a command reply, and a
new top-level message when a post is auto-removed after its TTL (or a
scheduled removal) expires (since the original thread may be long gone
from anyone's view by then).

## Admin page

A no-authentication admin page is served at
`http://<pi-or-mac-host>:<MASTHEAD_PORT>/admin/` (port 8420 by
default) by `bin/masthead-admin-server.py`, which now replaces the
plain `python -m http.server` that used to serve the kiosk page --
`masthead-serve.sh` execs it directly, so no separate setup is needed.
The page lists currently active entries (oldest first) and lets you
remove one immediately, without needing to find and reply to its
original Slack thread.

There is **no authentication** on this page -- anyone who can reach
`MASTHEAD_PORT` on the Pi or Mac's network interface can use it.
Access control is entirely "who's on this network/host": the server
binds to `127.0.0.1` by default (see the LAN-access note in
Troubleshooting below), so in the default configuration it's only
reachable from the device itself. Don't expose `MASTHEAD_PORT` to an
untrusted network without adding your own access control in front of
it.

## Audit trail

Every inbound Slack message the bot processes -- new posts, command
replies (cancel/delete/undo/remove), and removals made via the admin
page -- is appended as one JSON line to
`$MASTHEAD_DIR/data/audit.jsonl`. It's an append-only log, so it's
useful for answering "who removed this, and when" or for debugging
unexpected behaviour after the fact; nothing in Masthead reads it back
in normally.

## Troubleshooting

- **Nothing shows up / stuck on "Waiting for content"**: check
  `systemctl --user status masthead-refresh.service` (Pi) or
  `/tmp/masthead-refresh.log` (Mac) for poll errors -- most commonly an
  invalid/revoked `MASTHEAD_SLACK_TOKEN`, the bot not being invited to
  `MASTHEAD_SLACK_CHANNEL`, or a typo in the channel ID.
- **PDFs don't render**: confirm `pdftoppm -v` works; it comes from
  `poppler-utils` (Pi/apt) or `poppler` (Mac/brew).
  `install-pi.sh`/`install-mac.sh` install it, but double-check if you
  set things up manually.
- **Kiosk browser doesn't autostart on the Pi**: the exact autostart
  mechanism can vary by Raspberry Pi OS version/desktop (LXDE vs.
  labwc vs. wayfire). The XDG autostart entry in
  `~/.config/autostart/masthead-kiosk.desktop` (installed by
  `install-pi.sh`) works on most current images; if yours doesn't pick
  it up, add `kiosk/launch-kiosk-pi.sh &` to your desktop environment's
  own autostart config instead (e.g. `~/.config/wayfire.ini` under
  `[autostart]`, or `~/.config/labwc/autostart`).
- **Screen still sleeps/blanks**: some Pi OS versions manage this via
  the compositor rather than `xset`; check your desktop's power/screen
  settings if `launch-kiosk-pi.sh`'s `xset` calls don't stick.
- **Want to see it from another device on your network** (debugging
  only): `masthead-serve.sh` binds to `127.0.0.1` by default; change
  the `--bind` argument if you need LAN access, but keep in mind it
  then serves your Slack channel content to anyone on that network.
