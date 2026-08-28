#!/usr/bin/env bash
# Launches Chromium in kiosk mode pointed at the local Masthead server,
# and relaunches it if it ever crashes or is closed. Intended to be run
# from an XDG autostart entry (see install/install-pi.sh) inside the
# Pi's graphical session -- it needs a display, so don't run it as a
# headless systemd service.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# shellcheck disable=SC1090
[ -f "$REPO_DIR/config/masthead.env" ] && source "$REPO_DIR/config/masthead.env"

MASTHEAD_PORT="${MASTHEAD_PORT:-8420}"
URL="http://127.0.0.1:${MASTHEAD_PORT}/"

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
  echo "masthead: no chromium binary found on PATH" >&2
  exit 1
fi

# Wait for the local server to actually be up before the first launch
# (useful right after boot, when masthead-serve may still be starting).
for _ in $(seq 1 30); do
  curl -sf "$URL" >/dev/null 2>&1 && break
  sleep 1
done

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
    || true
  echo "masthead: browser exited, relaunching in 2s"
  sleep 2
done
