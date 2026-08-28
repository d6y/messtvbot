# Masthead

A small, self-hosted digital signage kiosk. Point it at a Dropbox
folder; anyone who can edit that folder can update what's on screen.
Images and PDFs both work (each PDF page becomes its own slide).
Runs on a Raspberry Pi for the real display, and on macOS for
development/testing -- same code, same web page, both places.

## How it works

```
Dropbox folder  --rclone-->  source/  --pdftoppm-->  rendered/
                                  \                      /
                                   \--> manifest.json <--/
                                            |
                                   local web server
                                            |
                                  Chromium in --kiosk mode
```

1. **`bin/masthead-refresh.py`** syncs your Dropbox folder down with
   `rclone`, renders any PDFs to PNG pages, and writes `manifest.json`
   listing every slide in order. Run on a timer (systemd timer on the
   Pi, launchd or cron on Mac).
2. **`bin/masthead-serve.sh`** serves that content over local HTTP.
3. **`web/`** is a tiny vanilla-JS page that polls `manifest.json` and
   crossfades between slides. It doesn't care whether a slide came
   from an image or a PDF page -- by the time it sees `manifest.json`
   everything is already just an image URL.
4. **`kiosk/launch-kiosk-*.sh`** opens that page full-screen in
   Chromium/Chrome, and (on the Pi) keeps relaunching it if it ever
   crashes or gets closed.

Ordering slides: files are sorted by filename, so prefix them
(`01-welcome.jpg`, `02-flyer.pdf`, `03-photo.png`, ...) to control the
order they play in. Delete something from Dropbox and it disappears
from the rotation on the next sync; drop something new in and it
appears.

## Quick start

**Raspberry Pi** (the actual kiosk display):

```
git clone <this repo> ~/masthead
cd ~/masthead
cp config/masthead.env.example config/masthead.env
rclone config                 # connect your Dropbox account
$EDITOR config/masthead.env   # set MASTHEAD_REMOTE
./install/install-pi.sh
```

**macOS** (development/testing -- same repo, no kiosk lockdown):

```
git clone <this repo> masthead && cd masthead
cp config/masthead.env.example config/masthead.env
rclone config
$EDITOR config/masthead.env
./install/install-mac.sh
```

Full walkthrough, including the Dropbox/rclone token setup, is in
[`docs/SETUP.md`](docs/SETUP.md).

## Repo layout

```
bin/        masthead-refresh.py (sync+render+manifest), masthead-serve.sh
web/        the kiosk webpage (index.html, style.css, app.js)
kiosk/      browser launch scripts + Pi autostart entry
systemd/    Pi: user service/timer units
launchd/    Mac: optional background agents
install/    install-pi.sh, install-mac.sh
config/     masthead.env.example (copy to masthead.env, gitignored)
docs/       full setup walkthrough
```

## Testing without Dropbox

`masthead-refresh.py` accepts `--skip-sync` (or `MASTHEAD_SKIP_SYNC=1`)
to rebuild the manifest from whatever's already in
`$MASTHEAD_DIR/source` without touching rclone -- handy for testing the
render/manifest/webpage logic by just dropping files in by hand:

```
mkdir -p ~/masthead-data/source
cp some-photo.jpg some-flyer.pdf ~/masthead-data/source/
python3 bin/masthead-refresh.py --skip-sync
bin/masthead-serve.sh &
open http://127.0.0.1:8420/          # or: kiosk/launch-kiosk-mac.sh
```

## Configuration

All settings live in `config/masthead.env` (see
`config/masthead.env.example` for the full list): the Dropbox remote,
where local content is cached, the web server port, PDF render width,
and slide/poll timing.
