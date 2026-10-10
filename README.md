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

Full walkthrough, including troubleshooting, is in
[`docs/SETUP.md`](docs/SETUP.md).

## Repo layout

```
bin/        socket_listener.py (real-time Slack ingestion, production), refresh.py (manual/debug poll+render+manifest), slack_source.py (Slack ingestion), serve.sh, admin_server.py
web/        the kiosk webpage (index.html, style.css, app.js), admin/ (no-auth admin page)
kiosk/      browser launch scripts + Pi autostart entry
systemd/    Pi: user service/timer units
launchd/    Mac: optional background agents
install/    install-pi.sh, install-mac.sh
config/     kiosk.env.example (copy to kiosk.env, gitignored)
docs/       full setup walkthrough
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
