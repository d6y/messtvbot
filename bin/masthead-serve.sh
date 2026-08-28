#!/usr/bin/env bash
# Serves the Masthead site (webpage + synced content + rendered PDFs) over
# plain HTTP on localhost, for the kiosk browser to point at.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# shellcheck disable=SC1090
[ -f "$REPO_DIR/config/masthead.env" ] && source "$REPO_DIR/config/masthead.env"

MASTHEAD_DIR="${MASTHEAD_DIR:-$HOME/masthead-data}"
MASTHEAD_PORT="${MASTHEAD_PORT:-8420}"

mkdir -p "$MASTHEAD_DIR/data" "$MASTHEAD_DIR/source" "$MASTHEAD_DIR/rendered"

echo "masthead-serve: serving $MASTHEAD_DIR on http://127.0.0.1:${MASTHEAD_PORT}/"
exec python3 -m http.server "$MASTHEAD_PORT" --bind 127.0.0.1 --directory "$MASTHEAD_DIR"
