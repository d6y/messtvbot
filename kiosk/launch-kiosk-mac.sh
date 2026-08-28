#!/usr/bin/env bash
# Opens Chrome in kiosk mode against the local Masthead server, for
# dev/testing on macOS. This is NOT meant to lock down the whole Mac the
# way it does on the Pi -- it's just so you can preview the slideshow
# full-screen. Press Cmd+Q (or Option+Cmd+Esc) to quit.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# shellcheck disable=SC1090
[ -f "$REPO_DIR/config/masthead.env" ] && source "$REPO_DIR/config/masthead.env"

MASTHEAD_PORT="${MASTHEAD_PORT:-8420}"
URL="http://127.0.0.1:${MASTHEAD_PORT}/"

CHROME_APP="Google Chrome"
if ! osascript -e "id of application \"$CHROME_APP\"" >/dev/null 2>&1; then
  echo "masthead: '$CHROME_APP' not found. Install Chrome, or open $URL manually." >&2
  exit 1
fi

# Use a scratch profile dir so this never touches your real Chrome profile.
PROFILE_DIR="$(mktemp -d -t masthead-kiosk)"

open -na "$CHROME_APP" --args \
  --kiosk "$URL" \
  --user-data-dir="$PROFILE_DIR" \
  --no-first-run \
  --disable-infobars \
  --autoplay-policy=no-user-gesture-required
