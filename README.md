# Mess TV Bot

A digital signage kiosk.
Reads messages from a Slack channel and turns posts into notices on the display.

Try text-only, images-only, text and images, and PDFs (each PDF page becomes its own slide).

Each post is its own page, the kiosk mode browser cycles through them.


## How it works

It connects out to Slack (Socket Mode, or polling for manual runs), only so we don't
need to be addressable on the public internet.

- `bin/socket_listener.py` is the production process: a real-time connection to Slack
  (Socket Mode) that reacts to new posts/replies/removal commands the moment they
  arrive, updating `data/manifest.json`. It also runs its own periodic reconciliation
  poll underneath that, to catch anything missed during a disconnect and to handle
  TTL expiry.
- `bin/refresh.py` is a manual/debug entrypoint only -- one poll-or-skip + render +
  manifest pass, handy for testing without the real-time connection running.
- `bin/serve.sh` provides an API, and hosts an /admin page.
- `kiosk/launch-kiosk` opens full-screen in Chromium/Chrome to show the pages.

Slides remove `KIOSK_SLACK_TTL_DAYS` (30 by default), or when removed via a thread reply or the admin page.

**End users** (people posting to Slack): see the
[user guide](https://d6y.github.io/messtvbot/) (`docs/` in this repo) --
introduction, commands, FAQ. That site isn't live until GitHub Pages is
enabled for this repo (Settings → Pages → deploy from `docs/` on `main`).


# User guide

To remove a message, reply to it in its thread with "remove" -- a bare
"remove" (or "remove now") removes it immediately, while a trailing time
phrase schedules the removal instead: "remove in 1 week", "remove
thursday", "remove 3 Sept", "remove 3 Sept 10am". A time phrase that can't
be understood doesn't remove anything -- the bot replies saying so and
restates the post's existing removal date, so nothing is removed by
surprise on a typo. Any reply stating a removal date (on posting, on
scheduling, or after an unparseable reply) also says how far off that
date is, e.g. "until 14 Aug 2026 09:00 (in 13 days)". The admin page at `/admin/` lists active entries
and can remove one immediately -- it has no authentication, so access
control is whoever's on the same network/host.

The bot also posts back to Slack so it's clear what happened to a
post: a thread reply when a post is accepted onto the display, a
thread reply when it's removed or scheduled for removal by a command
reply, and a new top-level message ("I've removed: ... by ...") when a
post expires via the TTL timeout or a scheduled removal.

## Slack app setup (get your token and channel ID)

Mess TV Bot needs a Slack app with a bot token, invited into whichever
channel you want to source content from. These steps work the same
whether that channel is public or private -- just pick the matching
scope in step 2.

1. Go to [api.slack.com/apps](https://api.slack.com/apps) → **Create
   New App** → **Blank App** Give it a name (e.g. "Mess TV Bot") and
   pick your workspace.
2. In the app's settings, open **OAuth & Permissions** (left sidebar)
   and scroll to **Scopes → Bot Token Scopes**. Add:
   - `groups:history` -- if your channel is **private** (this is your
     case for initial testing)
   - `channels:history` -- if your channel is **public** (add this
     instead of, or alongside, `groups:history` if you plan to switch
     to a public channel later)
   - `groups:read` / `channels:read` -- same public-vs-private choice as
     above, lets the bot resolve a `#channel` mention in a post to its
     name (otherwise it falls back to showing the raw channel ID)
   - `files:read` -- lets the bot download image/PDF attachments
   - `users:read` -- lets the bot show the poster's name on text slides,
     and resolve an `@user` mention in a post to their name
   - `chat:write` -- lets the bot reply in-thread when it accepts or
     removes a post, and announce when a post expires
3. Scroll back up to the top of **OAuth & Permissions** and click
   **Install to Workspace** (you'll be asked to approve the scopes).
   Once installed, copy the **Bot User OAuth Token** shown there --
   it starts with `xoxb-`. This is your `KIOSK_SLACK_TOKEN`.
4. In Slack itself, create (or pick) the channel to test with -- for
   a private test channel: create it, set it to **Private**, and
   make sure you're a member. Then invite the bot into it by typing
   `/invite @MessTVBot` (or whatever you named the app) in that
   channel. **This step is required** -- without it the bot can't see
   any messages, even with the right scopes.
5. Get the channel's ID: open the channel in Slack, click the channel
   name at the top to open **Channel details**, and scroll to the
   bottom of that panel -- the ID looks like `C0123456789` (private
   channels get an ID in the same format, just starting with `G` on
   some older workspaces). This is your `KIOSK_SLACK_CHANNEL`.
6. Enable Socket Mode -- this is how the bot receives messages in real time,
   rather than waiting for a poll tick:
   - **Socket Mode** (left sidebar) → toggle on → generate an
     app-level token (starts `xapp-`, scope `connections:write`).
     This is your `KIOSK_SLACK_APP_TOKEN`.
   - **Event Subscriptions** → toggle on → under "Subscribe to bot
     events" add `message.channels` (or `message.groups` for a
     private channel). No Request URL needed -- Socket Mode handles
     delivery.
   - This may prompt a reinstall of the app, which issues a **new**
     bot token -- update `KIOSK_SLACK_TOKEN` if so. Your existing
     Bot Token Scopes from step 2 already cover what these events need.

With all three values in hand:

```
cp config/kiosk.env.example config/kiosk.env
$EDITOR config/kiosk.env   # set KIOSK_SLACK_TOKEN, KIOSK_SLACK_CHANNEL, and KIOSK_SLACK_APP_TOKEN
```

## Quick start

**Raspberry Pi** (the actual kiosk display):

```
git clone <this repo> ~/messtvbot
cd ~/messtvbot
cp config/kiosk.env.example config/kiosk.env
$EDITOR config/kiosk.env   # set KIOSK_SLACK_TOKEN and KIOSK_SLACK_CHANNEL
./install/install-pi.sh
```

**macOS** (development/testing -- same repo, no kiosk lockdown):

```
git clone <this repo> messtvbot && cd messtvbot
cp config/kiosk.env.example config/kiosk.env
$EDITOR config/kiosk.env
./install/install-mac.sh
```

To connect to Slack in real time (the production path -- `install-pi.sh` sets this up
as a systemd service automatically):

```
uv run bin/socket_listener.py config/kiosk.env
```

Or, for a one-off manual poll + render without the real-time connection (handy for
testing/debugging):

```
uv run bin/refresh.py config/kiosk.env
```

To run the server:

```
bin/serve.sh
```

...and open `http://127.0.0.1:8420/` (or /admin for the admin panel).

## Troubleshooting

- **Mouse cursor visible on the kiosk display**: `kiosk/launch-kiosk-pi.sh` hides it via
  `unclutter` (and blanks the screen via `xset`), but both are X11-only and silently do
  nothing under Wayland. Recent Raspberry Pi OS images default to a Wayland session
  (`loginctl list-sessions` / `loginctl show-session <id> -p Type` will show
  `Type=wayland`). Switch the Pi to X11:
  ```
  sudo raspi-config nonint do_wayland W1
  sudo reboot
  ```
  (GUI equivalent: `sudo raspi-config` -> Advanced Options -> Wayland -> X11.) The nonint
  value codes for `do_wayland` vary by image -- if `W1` errors as an unrecognised option,
  check what your image actually supports with
  `grep -o 'do_[a-z_]*' /usr/bin/raspi-config` or just use the interactive menu instead.

- **WiFi drop takes the kiosk offline for hours, not seconds**: `kiosk-socket.service`
  itself recovers fine on its own once WiFi actually reconnects -- `slack_sdk`'s Socket
  Mode client keeps retrying every few seconds and picks up where it left off, no restart
  needed. The real problem is NetworkManager not reliably retrying *WiFi* reconnection on
  its own once an activation attempt has fully failed out -- found live, twice: once left
  the Pi offline for ~5 hours overnight, the other for 25+ minutes with a clean terminal
  (no errors, no retry attempts logged in `journalctl -u NetworkManager`) until a manual
  `nmcli device connect wlan0` was run, which then reconnected within seconds both times.
  Setting `connection.autoconnect-retries` to `0` ("forever", instead of the default
  `-1`, which defers to a small global limit) was tried first, and is still worth
  having set, but on its own did **not** reliably make it retry again within a useful
  window after a full failure -- so this alone isn't the fix:
  ```
  sudo nmcli connection modify "<your-SSID>" connection.autoconnect-retries 0
  ```
  The actual fix is `kiosk/wifi-watchdog-pi.sh` + `systemd/kiosk-wifi-watchdog.timer`
  (installed and enabled automatically by `install-pi.sh`): every 2 minutes it checks
  for any WiFi device sitting cleanly `disconnected` and, if found, runs
  `nmcli device connect <device>` itself -- the same manual nudge that worked instantly
  both times this was debugged live. It only acts on a clean `disconnected` state, so
  it's very unlikely to interrupt an in-progress `connecting` attempt or fight with
  NetworkManager's own reconnect logic (there's a small window between checking and
  acting where NetworkManager could start its own attempt first, but `nmcli device
  connect` on an already-activating device just errors harmlessly or restarts that one
  attempt -- it can't loop). The service unit sets `TimeoutStartSec=2min`, since
  `Type=oneshot` otherwise has *no* default timeout at all -- without it, a wedged
  NetworkManager (the exact fault this exists to work around) could leave `nmcli`
  hanging forever and silently stop the timer from ever firing the service again.
  **Depends on the user being in the `netdev` group** (Raspberry Pi OS's default `pi`/
  first-boot-wizard user is; a manually-created user might not be) -- that's what lets
  a `systemd --user` unit call `nmcli device connect` via polkit without needing root
  or an interactive auth prompt. Confirm with `nmcli general permissions` --
  `org.freedesktop.NetworkManager.network-control` should read `yes`. If this was ever
  set up with a non-default user, test the actual timer-fired path once rather than
  trusting it: `nmcli device disconnect wlan0 && systemctl --user start
  kiosk-wifi-watchdog.service`, then confirm it reconnects. Occasional brief wlan0
  re-associate/scan blips in `journalctl -u NetworkManager` that resolve within a
  couple of seconds on their own are normal (routine WPA rekeying/AP housekeeping) and
  not something to chase -- only a `link timed out` / repeated `Activation: failed`
  pattern, or a WiFi device sitting `disconnected` for more than a couple of minutes,
  is the real failure mode the watchdog exists for.

- **Kiosk display goes white/blank** (separately from the cursor/Wayland issue above):
  one real, confirmed cause is Raspberry Pi OS's **console-level screen blanking**,
  which is independent of X11's own DPMS settings (`launch-kiosk-pi.sh` already
  disables those via `xset`, but that doesn't touch this). Check and fix:
  ```
  raspi-config nonint get_blanking
  ```
  `0` means it's enabled (the likely culprit); disable it with:
  ```
  sudo raspi-config nonint do_blanking 1
  ```
  Ruled out as *not* the cause, if you're auditing this again: WiFi power-saving
  (`iw wlan0 get power_save` was already `off`), USB autosuspend (only matters for
  USB-attached peripherals -- the Pi's onboard WiFi is SDIO, not USB, so this never
  affects `wlan0`), systemd sleep/suspend/hibernate targets (all `inactive` by
  default on a Pi with no battery), and HDMI-CEC (no explicit config either way in
  `/boot/firmware/config.txt`, so this is on defaults -- worth a closer look only if
  blanking and DPMS are both confirmed off and the screen still goes dark). Also
  checked and clean: `vcgencmd get_throttled` showed no undervoltage ever and no
  *currently* active throttling (only a historical soft-temperature-limit bit, not
  something actively happening) -- re-check this one specifically if the white-screen
  or WiFi issues recur, since a genuinely overloaded/throttled Pi could plausibly
  explain both at once (the Pi 3B+ is modest hardware for running a full X11 desktop
  plus Chromium simultaneously). Note that `launch-kiosk-pi.sh`'s `while true`
  relaunch loop only recovers from Chromium actually *exiting* -- if blanking/DPMS
  are both off and the screen still goes white, that's more likely a genuine Chromium
  hang/GPU crash that leaves the process alive but unresponsive, which nothing here
  currently detects or recovers from automatically; see that script's own header
  comment for the known `--disable-gpu`/GLES2 angle on this.

## Repo layout

```
bin/        socket_listener.py (real-time Slack ingestion, production), refresh.py (manual/debug poll+render+manifest), slack_source.py (Slack ingestion), serve.sh, admin_server.py
web/        the kiosk webpage (index.html, style.css, app.js), admin/ (no-auth admin page)
kiosk/      browser launch scripts + Pi autostart entry
systemd/    Pi: user service/timer units
launchd/    Mac: optional background agents
install/    install-pi.sh, install-mac.sh
config/     kiosk.env.example (copy to kiosk.env, gitignored)
docs/       published end-user site (index.md, commands.md, faq.md), built via Jekyll/GitHub Pages
```

## Testing without Slack

`refresh.py` accepts `--skip-slack-poll` (or
`KIOSK_SKIP_SLACK_POLL=1`) to rebuild the manifest from whatever's
already in `$KIOSK_DIR/data/slack-state.json` without touching the
Slack API -- handy for testing the render/manifest/webpage logic with
a hand-edited fixture file. For example:

```
mkdir -p $KIOSK_DIR/data
cat > $KIOSK_DIR/data/slack-state.json <<'EOF'
{
  "100.1": {
    "ts": "100.1", "status": "active", "kind": "text",
    "text": "Pizza in the kitchen at 1pm!", "author": "Jane",
    "posted_at": "2026-08-01T12:00:00+00:00", "local_files": []
  }
}
EOF
uv run bin/refresh.py config/kiosk.env --skip-slack-poll
```

This writes `manifest.json` straight from that fixture, so you can
open `web/index.html` (served via `serve.sh`) and see the
slideshow without a live Slack connection.

## Configuration

All settings live in `config/kiosk.env` (see
`config/kiosk.env.example` for the full list): the Slack token and
channel, where local content is cached, the web server port, PDF render
width, and slide/poll timing.
