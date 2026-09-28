#!/usr/bin/env bash
# Sets up Mess TV Bot on macOS for local development/testing: dependencies
# only. Everything is run manually (see the printed instructions at the
# end) -- there's no background service/launchd setup on Mac.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if ! command -v brew >/dev/null 2>&1; then
  echo "Homebrew not found. Install it from https://brew.sh first." >&2
  exit 1
fi

echo "==> Installing packages (poppler, uv)"
brew install poppler uv

echo "==> Installing Python dependencies"
uv sync --project "$REPO_DIR"

echo "==> Making scripts executable"
chmod +x "$REPO_DIR"/bin/*.sh "$REPO_DIR"/kiosk/*.sh

if [ ! -f "$REPO_DIR/config/kiosk.env" ]; then
  cp "$REPO_DIR/config/kiosk.env.example" "$REPO_DIR/config/kiosk.env"
  echo "==> Created config/kiosk.env -- edit KIOSK_SLACK_TOKEN and KIOSK_SLACK_CHANNEL before continuing!"
fi

cat <<EOF
==> Done. Run things manually, e.g.:
      uv run bin/refresh.py config/kiosk.env
      bin/serve.sh
      kiosk/launch-kiosk-mac.sh
EOF
