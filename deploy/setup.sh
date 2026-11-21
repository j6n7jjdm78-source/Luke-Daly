#!/usr/bin/env bash
# One-command setup on a fresh Ubuntu/Debian server. Run from the unzipped project folder:  bash deploy/setup.sh
set -e
cd "$(dirname "$0")/.."
APP="$(pwd)"; ME="$(whoami)"
sudo apt-get update
sudo apt-get install -y python3 nodejs npm fonts-liberation unzip
npm install playwright                       # used to draw the card pictures
npx playwright install --with-deps chromium
mkdir -p ~/.config/cliperz-bot state drafts
chmod 700 ~/.config/cliperz-bot
# systemd service: starts on boot and restarts itself if it ever crashes
sudo tee /etc/systemd/system/cliperz-bot.service >/dev/null <<UNIT
[Unit]
Description=Cliperz call-out bot
After=network-online.target
[Service]
User=$ME
WorkingDirectory=$APP
ExecStart=/usr/bin/python3 $APP/bot/run_loop.py
Restart=always
RestartSec=10
[Install]
WantedBy=multi-user.target
UNIT
sudo systemctl daemon-reload
sudo systemctl enable cliperz-bot
echo
echo "Installed. Next: put your keys in ~/.config/cliperz-bot/keys.env, run  python3 bot/auth.py  once, then:"
echo "  sudo systemctl start cliperz-bot"
echo "  sudo journalctl -u cliperz-bot -f      (to watch it)"
