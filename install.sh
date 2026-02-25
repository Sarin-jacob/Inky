#!/bin/bash

# 1. Check for root privileges
if [ "$EUID" -ne 0 ]; then
  echo "[-] Please run this script with sudo: sudo bash install.sh"
  exit 1
fi

# 2. Get the absolute path of the current directory
PROJECT_DIR=$(pwd)
VENV_PYTHON="$PROJECT_DIR/.venv/bin/python"
APP_SCRIPT="$PROJECT_DIR/app.py"

echo "[*] Setting up Inky systemd service..."

# 3. Verify the virtual environment exists
if [ ! -f "$VENV_PYTHON" ]; then
    echo "[-] Virtual environment not found at $VENV_PYTHON"
    echo "[-] Please ensure you have run 'uv sync' before installing the service."
    exit 1
fi

# 4. Generate the systemd service file
SERVICE_FILE="/etc/systemd/system/Inky.service"

cat <<EOF > $SERVICE_FILE
[Unit]
Description=Inky E-Ink Display and Web Server
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
# Must run as root to access hardware SPI and GPIO edge detection
User=root
WorkingDirectory=$PROJECT_DIR
ExecStart=$VENV_PYTHON $APP_SCRIPT
Restart=on-failure
RestartSec=10
Environment="PYTHONUNBUFFERED=1"

[Install]
WantedBy=multi-user.target
EOF

echo "[+] Service file created at $SERVICE_FILE"

# 5. Reload systemd, enable, and start the service
echo "[*] Reloading systemd daemon..."
systemctl daemon-reload

echo "[*] Enabling Inky.service to start on boot..."
systemctl enable Inky.service

echo "[*] Starting Inky.service..."
systemctl start Inky.service

echo ""
echo "[SUCCESS] Inky service installed and running!"
echo "--------------------------------------------------------"
echo "To check the status:  sudo systemctl status Inky"
echo "To view live logs:    sudo journalctl -u Inky -f"
echo "To stop the service:  sudo systemctl stop Inky"
echo "--------------------------------------------------------"