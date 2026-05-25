#!/bin/bash
set -euo pipefail

echo "==============================="
echo "  PiDash Installer"
echo "==============================="
echo

CURRENT_USER=$(whoami)
INSTALL_DIR="$(cd "$(dirname "$0")" && pwd)"

# --- System packages ---
echo "[1/6] Systeempakketten installeren..."
sudo apt-get update -qq
sudo apt-get install -y -qq python3-pip python3-venv git > /dev/null

# --- Python venv ---
echo "[2/6] Python environment opzetten..."
cd "$INSTALL_DIR"
python3 -m venv venv
source venv/bin/activate
pip install -q -r requirements.txt

# --- Directories ---
echo "[3/6] Mappen aanmaken..."
mkdir -p ~/bots
mkdir -p "$INSTALL_DIR/data"
if [ ! -f "$INSTALL_DIR/data/config.json" ]; then
    echo '{"bots":{}}' > "$INSTALL_DIR/data/config.json"
fi

# --- Helper script ---
echo "[4/6] Helper script installeren..."
sudo cp "$INSTALL_DIR/pidash-helper.sh" /usr/local/bin/pidash-helper
sudo chmod 755 /usr/local/bin/pidash-helper

# --- Sudoers ---
echo "[5/6] Permissies instellen..."
sudo tee /etc/sudoers.d/pidash > /dev/null << EOF
$CURRENT_USER ALL=(ALL) NOPASSWD: /usr/local/bin/pidash-helper
EOF
sudo chmod 440 /etc/sudoers.d/pidash

# --- Systemd service for the dashboard itself ---
echo "[6/6] Dashboard service aanmaken..."
sudo tee /etc/systemd/system/pidash.service > /dev/null << EOF
[Unit]
Description=PiDash - Bot Management Dashboard
After=network.target

[Service]
Type=simple
User=$CURRENT_USER
WorkingDirectory=$INSTALL_DIR
ExecStart=$INSTALL_DIR/venv/bin/python app.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable pidash
sudo systemctl start pidash

# --- Done ---
IP=$(hostname -I | awk '{print $1}')

echo
echo "==============================="
echo "  PiDash is geinstalleerd!"
echo "==============================="
echo
echo "  Dashboard:  http://$IP:8080"
echo "  Bots map:   ~/bots"
echo
echo "  Open het adres hierboven in je browser."
echo "==============================="
