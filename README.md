# Masthead

A small, self-hosted digital signage kiosk. Point it at a Slack
channel; anyone who can post there can update what's on screen.
Images and PDFs both work (each PDF page becomes its own slide), and
plain text messages become their own text slide. Runs on a Raspberry
Pi for the real display, and on macOS for development/testing -- same
code, same web page, both places.

## How it works

```
Slack channel  --Web API poll-->  poller step  --downloads-->  source/  --pdftoppm-->  rendered/
                                        |                                    /
                                        \--> text slides -----> manifest.json <--/
                                                                     |
                                                            local web server
                                                                     |
                                                           Chromium in --kiosk mode
```

1. **`bin/masthead-refresh.py`** polls a Slack channel via the Slack
   Web API, downloads any image/PDF attachments, renders PDFs to PNG
   pages (poppler's `pdftoppm`), and writes `manifest.json` listing
   every slide (images, PDF pages, and text messages) in post order.
   Run on a timer (systemd timer on the Pi, launchd or cron on Mac).
2. **`bin/masthead-serve.sh`** serves that content over local HTTP, via
   **`bin/masthead-admin-server.py`** (which replaced a plain
   `python -m http.server`) -- it also serves the no-auth admin page
   at `/admin/` for removing entries without going through Slack.
3. **`web/`** is a tiny vanilla-JS page that polls `manifest.json` and
   crossfades between slides -- images, PDF pages, and text cards
   alike.
4. **`kiosk/launch-kiosk-*.sh`** opens that page full-screen in
   Chromium/Chrome, and (on the Pi) keeps relaunching it if it ever
   crashes or gets closed.

Ordering slides: slides play oldest-posted-first. A message expires
out of rotation automatically after `MASTHEAD_SLACK_TTL_DAYS` (30 by
default), or when removed via a thread reply or the admin page. To
remove a message, reply to it in its thread with "cancel", "delete",
"undo", or "remove" -- a bare command word (or one followed by "now")
removes it immediately, while a trailing time phrase schedules the
removal instead: "remove in 1 week", "remove thursday", "remove 3
Sept", "remove 3 Sept 10am". An unparseable time phrase falls back to
an immediate removal. The admin page at `/admin/` lists active entries
and can remove one immediately -- it has no authentication, so access
control is whoever's on the same network/host.

The bot also posts back to Slack so it's clear what happened to a
post: a thread reply when a post is accepted onto the display, a
thread reply when it's removed or scheduled for removal by a command
reply, and a new top-level message ("I've removed: ... by ...") when a
post expires via the TTL timeout or a scheduled removal.

## Slack app setup (get your token and channel ID)

Masthead needs a Slack app with a bot token, invited into whichever
channel you want to source content from. These steps work the same
whether that channel is public or private -- just pick the matching
scope in step 2.

1. Go to [api.slack.com/apps](https://api.slack.com/apps) → **Create
   New App** → **Blank App** Give it a name (e.g. "Masthead") and
   pick your workspace.
2. In the app's settings, open **OAuth & Permissions** (left sidebar)
   and scroll to **Scopes → Bot Token Scopes**. Add:
   - `groups:history` -- if your channel is **private** (this is your
     case for initial testing)
   - `channels:history` -- if your channel is **public** (add this
     instead of, or alongside, `groups:history` if you plan to switch
     to a public channel later)
   - `files:read` -- lets the bot download image/PDF attachments
   - `users:read` -- lets the bot show the poster's name on text slides
   - `chat:write` -- lets the bot reply in-thread when it accepts or
     removes a post, and announce when a post expires
3. Scroll back up to the top of **OAuth & Permissions** and click
   **Install to Workspace** (you'll be asked to approve the scopes).
   Once installed, copy the **Bot User OAuth Token** shown there --
   it starts with `xoxb-`. This is your `MASTHEAD_SLACK_TOKEN`.
4. In Slack itself, create (or pick) the channel to test with -- for
   a private test channel: create it, set it to **Private**, and
   make sure you're a member. Then invite the bot into it by typing
   `/invite @Masthead` (or whatever you named the app) in that
   channel. **This step is required** -- without it the bot can't see
   any messages, even with the right scopes.
5. Get the channel's ID: open the channel in Slack, click the channel
   name at the top to open **Channel details**, and scroll to the
   bottom of that panel -- the ID looks like `C0123456789` (private
   channels get an ID in the same format, just starting with `G` on
   some older workspaces). This is your `MASTHEAD_SLACK_CHANNEL`.

With both values in hand:

```
cp config/masthead.env.example config/masthead.env
$EDITOR config/masthead.env   # set MASTHEAD_SLACK_TOKEN and MASTHEAD_SLACK_CHANNEL
```

## Quick start

**Raspberry Pi** (the actual kiosk display):

```
git clone <this repo> ~/masthead
cd ~/masthead
cp config/masthead.env.example config/masthead.env
$EDITOR config/masthead.env   # set MASTHEAD_SLACK_TOKEN and MASTHEAD_SLACK_CHANNEL
./install/install-pi.sh
```

**macOS** (development/testing -- same repo, no kiosk lockdown):

```
git clone <this repo> masthead && cd masthead
cp config/masthead.env.example config/masthead.env
$EDITOR config/masthead.env
./install/install-mac.sh
```

Full walkthrough, including troubleshooting, is in
[`docs/SETUP.md`](docs/SETUP.md).

## Repo layout

```
bin/        masthead-refresh.py (Slack poll+render+manifest), masthead_slack.py (Slack ingestion), masthead-serve.sh, masthead-admin-server.py
web/        the kiosk webpage (index.html, style.css, app.js), admin/ (no-auth admin page)
kiosk/      browser launch scripts + Pi autostart entry
systemd/    Pi: user service/timer units
launchd/    Mac: optional background agents
install/    install-pi.sh, install-mac.sh
config/     masthead.env.example (copy to masthead.env, gitignored)
docs/       full setup walkthrough
```

## Testing without Slack

`masthead-refresh.py` accepts `--skip-slack-poll` (or
`MASTHEAD_SKIP_SLACK_POLL=1`) to rebuild the manifest from whatever's
already in `$MASTHEAD_DIR/data/slack-state.json` without touching the
Slack API -- handy for testing the render/manifest/webpage logic with
a hand-edited fixture file. For example:

```
mkdir -p $MASTHEAD_DIR/data
cat > $MASTHEAD_DIR/data/slack-state.json <<'EOF'
{
  "100.1": {
    "ts": "100.1", "status": "active", "kind": "text",
    "text": "Pizza in the kitchen at 1pm!", "author": "Jane",
    "posted_at": "2026-08-01T12:00:00+00:00", "local_files": []
  }
}
EOF
python3 bin/masthead-refresh.py config/masthead.env --skip-slack-poll
```

This writes `manifest.json` straight from that fixture, so you can
open `web/index.html` (served via `masthead-serve.sh`) and see the
slideshow without a live Slack connection.

## Configuration

All settings live in `config/masthead.env` (see
`config/masthead.env.example` for the full list): the Slack token and
channel, where local content is cached, the web server port, PDF render
width, and slide/poll timing.
