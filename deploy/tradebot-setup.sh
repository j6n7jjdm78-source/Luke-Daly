#!/usr/bin/env bash
# Sets up the multi-user trading bot on your always-on Linux server (NOT run in the cloud sandbox).
# Two OS users: tradebot-signer (owns the master key + wallet DB, signs) and tradebot (Telegram app, no secrets).
# Run from the project folder as a sudo-capable user:  bash deploy/tradebot-setup.sh
set -euo pipefail
cd "$(dirname "$0")/.."
SRC="$(pwd)"; APP=/opt/tradebot
sudo apt-get install -y python3 python3-venv rsync
getent group tradebot >/dev/null || sudo groupadd --system tradebot
id tradebot >/dev/null 2>&1        || sudo useradd --system --gid tradebot --home /var/lib/tradebot --create-home --shell /usr/sbin/nologin tradebot
id tradebot-signer >/dev/null 2>&1 || sudo useradd --system --gid tradebot --home /var/lib/tradebot-signer --create-home --shell /usr/sbin/nologin tradebot-signer
sudo mkdir -p "$APP"; sudo rsync -a --delete --exclude .git --exclude 'wallet/state' --exclude drafts "$SRC"/ "$APP"/
sudo python3 -m venv "$APP/venv"; sudo "$APP/venv/bin/pip" install -q -r "$APP/requirements-tradebot.txt"
sudo chown -R root:root "$APP"; sudo chmod -R go-w "$APP"
# signer state: only the signer user can even enter this directory
sudo chown tradebot-signer:tradebot-signer /var/lib/tradebot-signer; sudo chmod 700 /var/lib/tradebot-signer
# master key: created once, readable only by the signer. BACK IT UP OFFLINE: losing it loses every wallet.
if ! sudo test -f /var/lib/tradebot-signer/master.key; then
  sudo -u tradebot-signer sh -c 'umask 077; /opt/tradebot/venv/bin/python -m tradebot.keystore > /var/lib/tradebot-signer/master.key' 
  echo "Master key created at /var/lib/tradebot-signer/master.key (not shown here). Back it up offline NOW:  sudo cat /var/lib/tradebot-signer/master.key"
fi
sudo chmod 400 /var/lib/tradebot-signer/master.key
# app config (Telegram token etc.); the app user has no access to anything in the signer directory
sudo -u tradebot mkdir -p /var/lib/tradebot/.config/tradebot /var/lib/tradebot/.local/share/tradebot
if ! sudo test -f /var/lib/tradebot/.config/tradebot/keys.env; then
  sudo -u tradebot sh -c 'umask 077; cat > /var/lib/tradebot/.config/tradebot/keys.env' <<'ENVF'
# Fill in on the server (never paste these in chat). Use a DEVNET rpc until you have reviewed everything.
TRADEBOT_TG_TOKEN=
TRADEBOT_ADMIN_ID=
TRADEBOT_RPC_URL=https://api.devnet.solana.com
ENVF
fi
sudo tee /etc/systemd/system/tradebot-signer.service >/dev/null <<'UNIT'
[Unit]
Description=Tradebot signer (holds master key; only component that signs)
After=network-online.target
[Service]
User=tradebot-signer
Group=tradebot
WorkingDirectory=/opt/tradebot
Environment=TRADEBOT_STATE=/var/lib/tradebot-signer TRADEBOT_SOCKET=/run/tradebot/signer.sock TRADEBOT_SOCKET_MODE=660
EnvironmentFile=/var/lib/tradebot-signer/rpc.env
RuntimeDirectory=tradebot
RuntimeDirectoryMode=0750
ExecStart=/opt/tradebot/venv/bin/python -m tradebot.signer serve
Restart=on-failure
RestartSec=5
NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=true
PrivateTmp=true
ReadWritePaths=/var/lib/tradebot-signer
[Install]
WantedBy=multi-user.target
UNIT
sudo tee /etc/systemd/system/tradebot-app.service >/dev/null <<'UNIT'
[Unit]
Description=Tradebot Telegram app (no keys, no PIN hashes)
After=tradebot-signer.service
Requires=tradebot-signer.service
[Service]
User=tradebot
Group=tradebot
WorkingDirectory=/opt/tradebot
Environment=HOME=/var/lib/tradebot
ExecStart=/opt/tradebot/venv/bin/python -m tradebot.app
Restart=on-failure
RestartSec=5
NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=read-only
PrivateTmp=true
ReadWritePaths=/var/lib/tradebot
[Install]
WantedBy=multi-user.target
UNIT
# the signer's RPC url lives in a file only it can read
sudo test -f /var/lib/tradebot-signer/rpc.env || sudo sh -c 'umask 077; echo "TRADEBOT_RPC_URL=https://api.devnet.solana.com" > /var/lib/tradebot-signer/rpc.env; chown tradebot-signer:tradebot /var/lib/tradebot-signer/rpc.env'
sudo systemctl daemon-reload; sudo systemctl enable tradebot-signer tradebot-app
echo
echo "Next: edit /var/lib/tradebot/.config/tradebot/keys.env (bot token, your Telegram id), then:"
echo "  sudo systemctl start tradebot-signer tradebot-app"
echo "Emergency: pause everything from the server:  sudo -u tradebot-signer touch /var/lib/tradebot-signer/PAUSE"
echo "Resume: sudo -u tradebot-signer env TRADEBOT_STATE=/var/lib/tradebot-signer /opt/tradebot/venv/bin/python -m tradebot.signer resume"
echo "Network is DEVNET and tradebot/config.json has mainnet_enabled=false. Do not enable mainnet before the security review."
