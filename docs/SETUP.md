# Mess TV Bot setup walkthrough

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
Token** (starts `xoxb-`) -- this is `KIOSK_SLACK_TOKEN`.

Invite the bot to the channel people will post signage content to
(`/invite @YourAppName` in that channel), then find the channel's ID
(right-click the channel → "View channel details" → the ID is at the
bottom, or use the Slack API's `conversations.list`) -- this is
`KIOSK_SLACK_CHANNEL`.

**Optional, for later:** Mess TV Bot currently polls Slack rather than
receiving events in real time. If you might move to a real-time
connection (Socket Mode) in future, it costs nothing to enable it on
this same app now, while it's not live yet: toggle on **Socket Mode**
(generates an app-level `xapp-...` token, scope `connections:write`)
and **Event Subscriptions** (subscribe to `message.channels` /
`message.groups`, no Request URL needed). This may trigger a reinstall
that issues a new bot token -- update `KIOSK_SLACK_TOKEN` if so.
Nothing currently uses these; polling keeps working unchanged.

## 2. Configure Mess TV Bot

```
cp config/kiosk.env.example config/kiosk.env
```

Edit `config/kiosk.env`:
- `KIOSK_SLACK_TOKEN` and `KIOSK_SLACK_CHANNEL` -- from step 1
- everything else has a reasonable default; see the comments in the
  file for what each one does

## 3. Install

**Pi:** `./install/install-pi.sh` -- installs `poppler-utils`/
`chromium`/`unclutter`, sets up two systemd **user** services
(`kiosk-serve`, always running the web server) and a timer
(`kiosk-refresh`, polling/rendering every 20 seconds by default), and
adds a kiosk autostart entry so Chromium launches full-screen after
login. It also enables "linger" so those services keep running even
without an active graphical login.

**Mac:** `./install/install-mac.sh` -- installs `poppler` via Homebrew.
Everything is run manually on Mac (`uv run bin/refresh.py`,
`bin/serve.sh`, `kiosk/launch-kiosk-mac.sh`) -- there's no background
service/launchd setup.

Both scripts also run `uv sync`, which creates a `.venv/` in the repo
and installs `dateparser` (used to parse the scheduling phrases in
thread-reply commands, see below) into it, pinned per `uv.lock`. Install
scripts install `uv` itself first if it's not already on `PATH` (Pi:
the official installer script; Mac: Homebrew).

## 4. Verify

```
systemctl --user status kiosk-refresh.service   # Pi
cat ~/kiosk-data/data/manifest.json
curl http://127.0.0.1:8420/data/manifest.json
```

Post a message with an image or some text in your Slack channel, wait for the next refresh
interval (or force one -- see below), and confirm it shows up in
`manifest.json`.

Forcing an immediate refresh:
```
systemctl --user start kiosk-refresh.service   # Pi
uv run bin/refresh.py config/kiosk.env    # Mac / manual
```

## 5. See it full-screen

**Pi:** reboot, or run `kiosk/launch-kiosk-pi.sh` directly to test
without rebooting.

**Mac:** `kiosk/launch-kiosk-mac.sh` (Cmd+Q to quit -- this is a
preview, not a real lockdown).

## Ordering and removing content

Slides play in the order they were posted to the Slack channel
(oldest first). A message remains in rotation for `KIOSK_SLACK_TTL_DAYS`
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
`http://<pi-or-mac-host>:<KIOSK_PORT>/admin/` (port 8420 by
default) by `bin/admin_server.py`, which now replaces the
plain `python -m http.server` that used to serve the kiosk page --
`serve.sh` execs it directly, so no separate setup is needed.
The page lists currently active entries (oldest first) and lets you
remove one immediately, without needing to find and reply to its
original Slack thread.

There is **no authentication** on this page -- anyone who can reach
`KIOSK_PORT` on the Pi or Mac's network interface can use it.
Access control is entirely "who's on this network/host": the server
binds to `127.0.0.1` by default (see the LAN-access note in
Troubleshooting below), so in the default configuration it's only
reachable from the device itself. Don't expose `KIOSK_PORT` to an
untrusted network without adding your own access control in front of
it.

## Audit trail

Every inbound Slack message the bot processes -- new posts, command
replies (cancel/delete/undo/remove), messages it ignores, and removals
made via the admin page -- is appended as one JSON line to
`$KIOSK_DIR/data/audit.jsonl`. It's an append-only log, so it's
useful for answering "who removed this, and when" or for debugging
unexpected behaviour after the fact; nothing in Mess TV Bot reads it back
in normally.

## Troubleshooting

- **Nothing shows up / stuck on "Waiting for content"**: check
  `systemctl --user status kiosk-refresh.service` (Pi) or
  `/tmp/messtvbot-refresh.log` (Mac) for poll errors -- most commonly an
  invalid/revoked `KIOSK_SLACK_TOKEN`, the bot not being invited to
  `KIOSK_SLACK_CHANNEL`, or a typo in the channel ID.
- **PDFs don't render**: confirm `pdftoppm -v` works; it comes from
  `poppler-utils` (Pi/apt) or `poppler` (Mac/brew).
  `install-pi.sh`/`install-mac.sh` install it, but double-check if you
  set things up manually.
- **Kiosk browser doesn't autostart on the Pi**: the exact autostart
  mechanism can vary by Raspberry Pi OS version/desktop (LXDE vs.
  labwc vs. wayfire). The XDG autostart entry in
  `~/.config/autostart/kiosk-autostart.desktop` (installed by
  `install-pi.sh`) works on most current images; if yours doesn't pick
  it up, add `kiosk/launch-kiosk-pi.sh &` to your desktop environment's
  own autostart config instead (e.g. `~/.config/wayfire.ini` under
  `[autostart]`, or `~/.config/labwc/autostart`).
- **Screen still sleeps/blanks**: some Pi OS versions manage this via
  the compositor rather than `xset`; check your desktop's power/screen
  settings if `launch-kiosk-pi.sh`'s `xset` calls don't stick.
- **Want to see it from another device on your network** (debugging
  only): `serve.sh` execs `bin/admin_server.py`,
  which hardcodes binding to `127.0.0.1` -- there's no `--bind` flag or
  any argument parsing. LAN access means editing the `"127.0.0.1"` in
  its `ThreadingHTTPServer((...))` call to `"0.0.0.0"`, but keep in
  mind that then serves both your Slack channel content *and* the
  no-auth admin API (which can remove entries) to anyone on that
  network.
