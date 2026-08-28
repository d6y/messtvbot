#!/usr/bin/env bash
# Sets up Masthead on a Raspberry Pi: dependencies, systemd user units,
# and kiosk autostart. Assumes this repo is cloned to ~/masthead (the
# systemd units use %h/masthead, so keep it there or edit the units).
#
# Run as the user who will be auto-logged-in on the kiosk (usually "pi"),
# NOT as root. It will ask for sudo when it actually needs it.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
if [ "$REPO_DIR" != "$HOME/masthead" ]; then
  echo "Warning: this repo is at $REPO_DIR, not \$HOME/masthead."
  echo "The systemd units assume \$HOME/masthead. Move the repo there," \
       "or edit systemd/*.service and kiosk/masthead-kiosk.desktop accordingly."
  read -r -p "Continue anyway? [y/N] " ans
  [ "$ans" = "y" ] || [ "$ans" = "Y" ] || exit 1
fi

echo "==> Installing packages (rclone, poppler-utils, chromium, unclutter)"
sudo apt-get update
sudo apt-get install -y poppler-utils unclutter curl
if ! command -v chromium >/dev/null 2>&1 && ! command -v chromium-browser >/dev/null 2>&1; then
  sudo apt-get install -y chromium-browser || sudo apt-get install -y chromium
fi
if ! command -v rclone >/dev/null 2>&1; then
  curl -fsSL https://rclone.org/install.sh | sudo bash
fi

echo "==> Making scripts executable"
chmod +x "$REPO_DIR"/bin/*.sh "$REPO_DIR"/kiosk/*.sh

if [ ! -f "$REPO_DIR/config/masthead.env" ]; then
  cp "$REPO_DIR/config/masthead.env.example" "$REPO_DIR/config/masthead.env"
  echo "==> Created config/masthead.env -- edit MASTHEAD_REMOTE before continuing!"
fi

if [ ! -f "$HOME/.config/rclone/rclone.conf" ]; then
  echo "==> No rclone config found yet."
  echo "    Run 'rclone config' now to connect your Dropbox account, then re-run this script."
  echo "    (See docs/SETUP.md for the exact steps.)"
fi

echo "==> Installing systemd user units"
mkdir -p "$HOME/.config/systemd/user"
cp "$REPO_DIR"/systemd/masthead-refresh.service "$HOME/.config/systemd/user/"
cp "$REPO_DIR"/systemd/masthead-refresh.timer "$HOME/.config/systemd/user/"
cp "$REPO_DIR"/systemd/masthead-serve.service "$HOME/.config/systemd/user/"

systemctl --user daemon-reload
systemctl --user enable --now masthead-serve.service
systemctl --user enable --now masthead-refresh.timer

echo "==> Allowing user services to run without an active login (linger)"
sudo loginctl enable-linger "$USER"

echo "==> Installing kiosk autostart entry"
mkdir -p "$HOME/.config/autostart"
sed "s|__REPO_DIR__|$REPO_DIR|g" "$REPO_DIR/kiosk/masthead-kiosk.desktop" \
  > "$HOME/.config/autostart/masthead-kiosk.desktop"

cat <<EOF

==> Done.

Next steps:
  1. If you haven't yet, run 'rclone config' to connect Dropbox, then:
       systemctl --user restart masthead-refresh.timer
  2. Check it worked:
       systemctl --user status masthead-refresh.service
       cat ~/masthead-data/data/manifest.json
  3. Reboot to see the kiosk autostart, or test it now without rebooting:
       $REPO_DIR/kiosk/launch-kiosk-pi.sh
EOF
