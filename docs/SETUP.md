# Masthead setup walkthrough

## 1. Create the Dropbox folder

Make (or pick) a folder in Dropbox that the people updating signage will
have access to, e.g. `Masthead`. Anything they drop in there (images or
PDFs) becomes a slide; anything they remove drops out of rotation.

## 2. Connect rclone to Dropbox

rclone needs its own OAuth token -- run this once per machine (Pi and
Mac each need their own, or you can copy `~/.config/rclone/rclone.conf`
between them):

```
rclone config
```

Walk through the prompts:
- `n` for a new remote
- name it (e.g. `dropbox`) -- this is what goes before the `:` in
  `MASTHEAD_REMOTE`
- storage type: `dropbox`
- leave client_id/client_secret blank to use rclone's default app
  (fine for personal use; register your own Dropbox app if you want
  Masthead's access scoped down further)
- it'll open a browser to authorize -- if you're on a headless Pi,
  either run `rclone config` from a machine with a browser and copy
  the resulting `rclone.conf` over, or use `rclone authorize` per
  rclone's headless-auth instructions
- confirm, and you should see your remote listed in `rclone listremotes`

Sanity-check it can see your folder:

```
rclone lsf dropbox:Masthead
```

## 3. Configure Masthead

```
cp config/masthead.env.example config/masthead.env
```

Edit `config/masthead.env`:
- `MASTHEAD_REMOTE=dropbox:Masthead` -- match the remote name from step 2
  and the folder path
- everything else has a reasonable default; see the comments in the
  file for what each one does

## 4. Install

**Pi:** `./install/install-pi.sh` -- installs `rclone`/`poppler-utils`/
`chromium`/`unclutter`, sets up two systemd **user** services
(`masthead-serve`, always running the web server) and a timer
(`masthead-refresh`, syncing/rendering every 2 minutes by default), and
adds a kiosk autostart entry so Chromium launches full-screen after
login. It also enables "linger" so those services keep running even
without an active graphical login.

**Mac:** `./install/install-mac.sh` -- installs `rclone`/`poppler` via
Homebrew, and optionally installs `launchd` agents so the refresh loop
and web server run in the background the same way they do on the Pi
(you'll be prompted; say no if you'd rather just run things manually
while developing).

## 5. Verify

```
systemctl --user status masthead-refresh.service   # Pi
cat ~/masthead-data/data/manifest.json
curl http://127.0.0.1:8420/data/manifest.json
```

Add a test image to your Dropbox folder, wait for the next refresh
interval (or force one -- see below), and confirm it shows up in
`manifest.json`.

Forcing an immediate refresh:
```
systemctl --user start masthead-refresh.service   # Pi
python3 bin/masthead-refresh.py config/masthead.env   # Mac / manual
```

## 6. See it full-screen

**Pi:** reboot, or run `kiosk/launch-kiosk-pi.sh` directly to test
without rebooting.

**Mac:** `kiosk/launch-kiosk-mac.sh` (Cmd+Q to quit -- this is a
preview, not a real lockdown).

## Ordering and naming content

Slides play in filename order. Prefix files to control sequence:
`01-welcome.jpg`, `02-monthly-flyer.pdf`, `03-photo.png`. A multi-page
PDF expands into one slide per page, in page order, at the point its
filename sorts.

Hidden files (dotfiles, e.g. `.DS_Store`) and anything that isn't a
recognized image type or `.pdf` are ignored.

## Troubleshooting

- **Nothing shows up / stuck on "Waiting for content"**: check
  `systemctl --user status masthead-refresh.service` (Pi) or
  `/tmp/masthead-refresh.log` (Mac) for sync errors -- most commonly a
  stale/missing rclone token (`rclone config reconnect dropbox:`) or a
  typo in `MASTHEAD_REMOTE`.
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
  then serves your Dropbox content to anyone on that network.
