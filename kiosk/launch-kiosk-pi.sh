#!/usr/bin/env bash
# Launches Chromium in kiosk mode pointed at the local Mess TV Bot server,
# and relaunches it if it ever crashes or is closed. Intended to be run
# from an XDG autostart entry (see install/install-pi.sh) inside the
# Pi's graphical session -- it needs a display, so don't run it as a
# headless systemd service.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# shellcheck disable=SC1090
[ -f "$REPO_DIR/config/kiosk.env" ] && source "$REPO_DIR/config/kiosk.env"

KIOSK_PORT="${KIOSK_PORT:-8420}"
URL="http://127.0.0.1:${KIOSK_PORT}/"

# Screen/cursor housekeeping -- best effort, don't fail the script if
# these aren't available (e.g. running under Wayland/labwc instead of X).
xset s off        2>/dev/null || true
xset s noblank     2>/dev/null || true
xset -dpms         2>/dev/null || true
command -v unclutter >/dev/null 2>&1 && (unclutter -idle 0.5 -root &)

BROWSER_BIN=""
for candidate in chromium chromium-browser; do
  if command -v "$candidate" >/dev/null 2>&1; then
    BROWSER_BIN="$candidate"
    break
  fi
done

if [ -z "$BROWSER_BIN" ]; then
  echo "kiosk: no chromium binary found on PATH" >&2
  exit 1
fi

# Wait for the local server to actually be up before the first launch
# (useful right after boot, when kiosk-serve may still be starting).
for _ in $(seq 1 30); do
  curl -sf "$URL" >/dev/null 2>&1 && break
  sleep 1
done

# --disable-gpu: the Pi 3's VC4 GPU driver only supports GLES2, but
# Chromium's default EGL path requests a GLES3 context and fails outright
# (blank/white window, eglCreateContext errors in the log). Software
# rendering is plenty for a 2D slideshow and sidesteps that entirely.
while true; do
  "$BROWSER_BIN" \
    --kiosk "$URL" \
    --noerrdialogs \
    --disable-infobars \
    --disable-session-crashed-bubble \
    --disable-translate \
    --no-first-run \
    --overscroll-history-navigation=disabled \
    --autoplay-policy=no-user-gesture-required \
    --check-for-update-interval=31536000 \
    --password-store=basic \
    --disable-gpu \
    || true
  echo "kiosk: browser exited, relaunching in 2s"
  sleep 2
done
