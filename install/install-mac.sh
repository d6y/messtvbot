#!/usr/bin/env bash
# Sets up Masthead on macOS for local development/testing: dependencies
# and (optionally) launchd agents so the refresh loop and web server run
# in the background like they would on the Pi.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if ! command -v brew >/dev/null 2>&1; then
  echo "Homebrew not found. Install it from https://brew.sh first." >&2
  exit 1
fi

echo "==> Installing packages (poppler)"
brew install poppler

echo "==> Making scripts executable"
chmod +x "$REPO_DIR"/bin/*.sh "$REPO_DIR"/kiosk/*.sh

if [ ! -f "$REPO_DIR/config/masthead.env" ]; then
  cp "$REPO_DIR/config/masthead.env.example" "$REPO_DIR/config/masthead.env"
  echo "==> Created config/masthead.env -- edit MASTHEAD_SLACK_TOKEN and MASTHEAD_SLACK_CHANNEL before continuing!"
fi

read -r -p "Install launchd agents to run refresh+server automatically in the background? [y/N] " ans
if [ "$ans" = "y" ] || [ "$ans" = "Y" ]; then
  mkdir -p "$HOME/Library/LaunchAgents"
  for plist in com.masthead.refresh.plist com.masthead.serve.plist; do
    sed "s|__REPO_DIR__|$REPO_DIR|g" "$REPO_DIR/launchd/$plist" \
      > "$HOME/Library/LaunchAgents/$plist"
    launchctl unload "$HOME/Library/LaunchAgents/$plist" 2>/dev/null || true
    launchctl load "$HOME/Library/LaunchAgents/$plist"
  done
  echo "==> Loaded. Logs: /tmp/masthead-refresh.log, /tmp/masthead-serve.log"
  echo "    To stop: launchctl unload ~/Library/LaunchAgents/com.masthead.*.plist"
else
  cat <<EOF
==> Skipped. Run things manually instead, e.g.:
      python3 bin/masthead-refresh.py config/masthead.env
      bin/masthead-serve.sh
      kiosk/launch-kiosk-mac.sh
EOF
fi
