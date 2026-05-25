#!/bin/bash
set -euo pipefail

echo "==============================="
echo "  PiDash Tunnel Setup"
echo "  (Cloudflare Quick Tunnel)"
echo "==============================="
echo

INSTALL_DIR="$(cd "$(dirname "$0")" && pwd)"
DATA_DIR="$INSTALL_DIR/data"
CURRENT_USER=$(whoami)

# --- Install cloudflared ---
echo "[1/3] Cloudflared installeren..."
if ! command -v cloudflared &> /dev/null; then
    curl -fsSL https://pkg.cloudflare.com/cloudflare-main.gpg | sudo tee /usr/share/keyrings/cloudflare-main.gpg > /dev/null
    echo "deb [signed-by=/usr/share/keyrings/cloudflare-main.gpg] https://pkg.cloudflare.com/cloudflared $(lsb_release -cs) main" | sudo tee /etc/apt/sources.list.d/cloudflared.list > /dev/null
    sudo apt-get update -qq
    sudo apt-get install -y -qq cloudflared > /dev/null
    echo "   Cloudflared geinstalleerd!"
else
    echo "   Cloudflared is al geinstalleerd."
fi

# --- Create a wrapper script that captures the URL ---
echo "[2/3] Tunnel service aanmaken..."
sudo tee /usr/local/bin/pidash-tunnel-wrapper > /dev/null << 'WRAPPER'
#!/bin/bash
DATA_DIR="$1"

# Start cloudflared and capture the tunnel URL from stderr
cloudflared tunnel --url http://localhost:8080 2>&1 | while IFS= read -r line; do
    echo "$line"
    # Capture the tunnel URL when it appears
    if echo "$line" | grep -qoP 'https://[a-z0-9-]+\.trycloudflare\.com'; then
        URL=$(echo "$line" | grep -oP 'https://[a-z0-9-]+\.trycloudflare\.com')
        echo "$URL" > "$DATA_DIR/tunnel_url.txt"
    fi
done
WRAPPER
sudo chmod 755 /usr/local/bin/pidash-tunnel-wrapper

sudo tee /etc/systemd/system/pidash-tunnel.service > /dev/null << EOF
[Unit]
Description=PiDash Cloudflare Tunnel
After=network-online.target pidash.service
Wants=network-online.target

[Service]
Type=simple
User=$CURRENT_USER
ExecStart=/usr/local/bin/pidash-tunnel-wrapper $DATA_DIR
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

# --- Start tunnel ---
echo "[3/3] Tunnel starten..."
sudo systemctl daemon-reload
sudo systemctl enable pidash-tunnel
sudo systemctl start pidash-tunnel

# Wait for URL to appear
echo
echo "Wachten op tunnel URL..."
for i in $(seq 1 15); do
    if [ -f "$DATA_DIR/tunnel_url.txt" ]; then
        URL=$(cat "$DATA_DIR/tunnel_url.txt")
        if [ -n "$URL" ]; then
            echo
            echo "==============================="
            echo "  Tunnel is actief!"
            echo "==============================="
            echo
            echo "  Publieke URL: $URL"
            echo
            echo "  Je kunt het dashboard nu overal"
            echo "  openen via deze URL."
            echo
            echo "  De URL verandert bij herstart."
            echo "  Check de huidige URL altijd in"
            echo "  het dashboard zelf."
            echo "==============================="
            exit 0
        fi
    fi
    sleep 2
done

echo
echo "Tunnel is gestart maar URL is nog niet beschikbaar."
echo "Probeer: sudo journalctl -u pidash-tunnel -f"
echo "De URL verschijnt ook in het dashboard."
