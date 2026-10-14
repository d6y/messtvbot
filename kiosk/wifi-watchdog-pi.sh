#!/usr/bin/env bash
# Pi-only: nudges wlan0 back up when it's sitting disconnected.
#
# Why this exists: NetworkManager's own `connection.autoconnect-retries`
# (even set to 0/"forever") does not reliably re-attempt activation on its
# own once a connection has fully failed out -- found live, twice, on this
# deployment: wlan0 sat disconnected for 25+ minutes (once for ~5 hours)
# with nothing in `journalctl -u NetworkManager` until a manual
# `nmcli device connect wlan0` was run, which then reconnected within
# seconds. See README.md's Troubleshooting section for the fuller writeup.
#
# Only acts when wlan0 is cleanly "disconnected" -- never touches it
# mid-"connecting"/"unavailable"/already-"connected", so it can't interrupt
# an attempt already in progress or fight with NetworkManager's own retry.
set -euo pipefail

state="$(nmcli -t -f DEVICE,STATE device status | awk -F: '$1 == "wlan0" { print $2 }')"

if [ "$state" = "disconnected" ]; then
  echo "wifi-watchdog: wlan0 is disconnected, nudging it back up"
  nmcli device connect wlan0 || echo "wifi-watchdog: nmcli device connect wlan0 failed, will retry next tick"
fi
