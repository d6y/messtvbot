#!/usr/bin/env bash
# Pi-only: nudges a disconnected WiFi device back up.
#
# Why this exists: NetworkManager's own `connection.autoconnect-retries`
# (even set to 0/"forever") does not reliably re-attempt activation on its
# own once a connection has fully failed out -- found live, twice, on this
# deployment: wlan0 sat disconnected for 25+ minutes (once for ~5 hours)
# with nothing in `journalctl -u NetworkManager` until a manual
# `nmcli device connect wlan0` was run, which then reconnected within
# seconds. See README.md's Troubleshooting section for the fuller writeup.
#
# Only acts on a device that's cleanly "disconnected" -- never mid-
# "connecting"/"unavailable"/already-"connected", so it can't interrupt an
# attempt already in progress or fight with NetworkManager's own retry.
#
# Selects by TYPE=wifi rather than the literal name "wlan0", so it still
# works if the interface is ever renamed; LC_ALL=C pins `nmcli`'s output to
# English regardless of the system locale, since its device-status strings
# ("disconnected" etc.) are translated and a non-English locale would make
# the state comparison below silently never match.
set -euo pipefail

disconnected="$(LC_ALL=C nmcli -t -f DEVICE,TYPE,STATE device status | awk -F: '$2 == "wifi" && $3 == "disconnected" { print $1 }')"

for device in $disconnected; do
  echo "wifi-watchdog: $device is disconnected, nudging it back up"
  # Diagnostic breadcrumb for next time: NetworkManager's own reason for the
  # disconnect, and whether the configured SSID is even visible in the last
  # scan -- cheap to capture here, and the one moment this is easy to see.
  LC_ALL=C nmcli -g GENERAL.STATE,GENERAL.REASON device show "$device" | sed "s/^/wifi-watchdog: $device state: /"
  LC_ALL=C nmcli -g SSID,BSSID,SIGNAL,CHAN device wifi list --rescan no | sed "s/^/wifi-watchdog: visible: /"
  nmcli device connect "$device" || echo "wifi-watchdog: nmcli device connect $device failed, will retry next tick"
done
