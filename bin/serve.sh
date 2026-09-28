#!/usr/bin/env bash
# Serves the Mess TV Bot site (webpage + synced content + rendered PDFs) over
# plain HTTP on localhost, for the kiosk browser to point at.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# shellcheck disable=SC1090
[ -f "$REPO_DIR/config/kiosk.env" ] && source "$REPO_DIR/config/kiosk.env"

KIOSK_DIR="${KIOSK_DIR:-$HOME/kiosk-data}"
KIOSK_PORT="${KIOSK_PORT:-8420}"

mkdir -p "$KIOSK_DIR/data" "$KIOSK_DIR/source" "$KIOSK_DIR/rendered"

echo "kiosk-serve: serving $KIOSK_DIR on http://127.0.0.1:${KIOSK_PORT}/ (admin at /admin/)"
export KIOSK_DIR KIOSK_PORT
exec "$REPO_DIR/.venv/bin/python3" "$REPO_DIR/bin/admin_server.py"
