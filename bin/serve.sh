#!/usr/bin/env bash
# Serves the Mess TV Bot site (webpage + synced content + rendered PDFs) over
# plain HTTP on localhost, for the kiosk browser to point at.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# set -a: export every variable kiosk.env sets (KIOSK_BIND_HOST,
# ADMIN_USER/ADMIN_PASS, etc), not just the ones named explicitly here --
# admin_server.py reads these straight from its environment, and a
# variable sourced-but-not-exported silently falls back to its default.
set -a
# shellcheck disable=SC1090
[ -f "$REPO_DIR/config/kiosk.env" ] && source "$REPO_DIR/config/kiosk.env"
set +a

KIOSK_DIR="${KIOSK_DIR:-$HOME/kiosk-data}"
KIOSK_PORT="${KIOSK_PORT:-8420}"
KIOSK_BIND_HOST="${KIOSK_BIND_HOST:-127.0.0.1}"

mkdir -p "$KIOSK_DIR/data" "$KIOSK_DIR/source" "$KIOSK_DIR/rendered"

echo "kiosk-serve: serving $KIOSK_DIR on http://${KIOSK_BIND_HOST}:${KIOSK_PORT}/ (admin at /admin/)"
export KIOSK_DIR KIOSK_PORT KIOSK_BIND_HOST
exec "$REPO_DIR/.venv/bin/python3" "$REPO_DIR/bin/admin_server.py"
