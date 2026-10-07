#!/usr/bin/env bash
# Sets up Mess TV Bot on a Raspberry Pi: dependencies, systemd user units,
# and kiosk autostart. Assumes this repo is cloned to ~/messtvbot (the
# systemd units use %h/messtvbot, so keep it there or edit the units).
#
# Run as the user who will be auto-logged-in on the kiosk (usually "pi"),
# NOT as root. It will ask for sudo when it actually needs it.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
if [ "$REPO_DIR" != "$HOME/messtvbot" ]; then
  echo "Warning: this repo is at $REPO_DIR, not \$HOME/messtvbot."
  echo "The systemd units assume \$HOME/messtvbot. Move the repo there," \
       "or edit systemd/*.service and kiosk/kiosk-autostart.desktop accordingly."
  read -r -p "Continue anyway? [y/N] " ans
  [ "$ans" = "y" ] || [ "$ans" = "Y" ] || exit 1
fi

echo "==> Installing packages (poppler-utils, chromium, unclutter, emoji font)"
sudo apt-get update
# fonts-noto-color-emoji: without it, Chromium renders the real emoji glyphs
# that convert_emoji_shortcodes() produces (see bin/slack_source.py) as empty
# boxes -- Raspberry Pi OS doesn't ship a color emoji font by default.
sudo apt-get install -y poppler-utils unclutter curl fonts-noto-color-emoji
if ! command -v chromium >/dev/null 2>&1 && ! command -v chromium-browser >/dev/null 2>&1; then
  sudo apt-get install -y chromium-browser || sudo apt-get install -y chromium
fi

if ! command -v uv >/dev/null 2>&1; then
  echo "==> Installing uv"
  curl -LsSf https://astral.sh/uv/install.sh | sh
  export PATH="$HOME/.local/bin:$PATH"
fi

echo "==> Installing Python dependencies"
uv sync --project "$REPO_DIR"

echo "==> Making scripts executable"
chmod +x "$REPO_DIR"/bin/*.sh "$REPO_DIR"/kiosk/*.sh

if [ ! -f "$REPO_DIR/config/kiosk.env" ]; then
  cp "$REPO_DIR/config/kiosk.env.example" "$REPO_DIR/config/kiosk.env"
  echo "==> Created config/kiosk.env -- edit KIOSK_SLACK_TOKEN and KIOSK_SLACK_CHANNEL before continuing!"
fi

echo "==> Installing systemd user units"
mkdir -p "$HOME/.config/systemd/user"
cp "$REPO_DIR"/systemd/kiosk-refresh.service "$HOME/.config/systemd/user/"
cp "$REPO_DIR"/systemd/kiosk-refresh.timer "$HOME/.config/systemd/user/"
cp "$REPO_DIR"/systemd/kiosk-serve.service "$HOME/.config/systemd/user/"

systemctl --user daemon-reload
systemctl --user enable --now kiosk-serve.service
systemctl --user enable --now kiosk-refresh.timer

echo "==> Allowing user services to run without an active login (linger)"
sudo loginctl enable-linger "$USER"

echo "==> Installing kiosk autostart entry"
mkdir -p "$HOME/.config/autostart"
sed "s|__REPO_DIR__|$REPO_DIR|g" "$REPO_DIR/kiosk/kiosk-autostart.desktop" \
  > "$HOME/.config/autostart/kiosk-autostart.desktop"

cat <<EOF

==> Done.

Next steps:
  1. If you haven't yet, create a Slack app and fill in KIOSK_SLACK_TOKEN
     and KIOSK_SLACK_CHANNEL in config/kiosk.env (see docs/SETUP.md):
       systemctl --user restart kiosk-refresh.timer
  2. Check it worked:
       systemctl --user status kiosk-refresh.service
       cat ~/kiosk-data/data/manifest.json
  3. Reboot to see the kiosk autostart, or test it now without rebooting:
       $REPO_DIR/kiosk/launch-kiosk-pi.sh
EOF
