#!/usr/bin/env bash
# Set up the wallet bot (PAPER mode) on your always-on Linux server. Separate service, separate config dir from the call-out bot.
# Run from the project folder:  bash deploy/wallet-setup.sh
set -e
cd "$(dirname "$0")/.."
APP="$(pwd)"; ME="$(whoami)"
sudo apt-get install -y python3 python3-pip git
pip3 install --user -r requirements-wallet.txt || pip3 install --user --break-system-packages -r requirements-wallet.txt
mkdir -p ~/.config/cliperz-wallet wallet/state
chmod 700 ~/.config/cliperz-wallet
[ -f ~/.config/cliperz-wallet/keys.env ] || cat > ~/.config/cliperz-wallet/keys.env <<'ENVF'
# Fill these in on the server (never paste them in chat):
WALLET_TG_TOKEN=
WALLET_OWNER_ID=
# WALLET_RPC_URL=
ENVF
chmod 600 ~/.config/cliperz-wallet/keys.env
sudo tee /etc/systemd/system/cliperz-wallet.service >/dev/null <<UNIT
[Unit]
Description=Cliperz wallet bot (paper)
After=network-online.target
[Service]
User=$ME
WorkingDirectory=$APP
ExecStart=/usr/bin/python3 -m wallet.run
Restart=on-failure
RestartSec=10
[Install]
WantedBy=multi-user.target
UNIT
sudo systemctl daemon-reload
sudo systemctl enable cliperz-wallet
echo
echo "Next: edit ~/.config/cliperz-wallet/keys.env, then:  sudo systemctl start cliperz-wallet"
echo "Kill switch: touch $APP/STOP   (blocks new buys).  Resume: rm $APP/STOP"
echo "Burner key is NOT created here. Phase 3 only: python3 -m wallet.keygen"
