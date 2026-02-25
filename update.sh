#!/bin/bash

# 1. Get the absolute path of the current directory
PROJECT_DIR=$(pwd)

echo "[*] Starting Inky Update..."

# 2. Check for local changes and stash them
# This prevents the pull from failing if state.json or logs changed
if [[ -n $(git status -s) ]]; then
    echo "[*] Local changes detected. Stashing..."
    git stash
    STASHED=true
else
    STASHED=false
fi

# 3. Pull the latest code
echo "[*] Pulling latest changes from GitHub..."
git pull origin main

# 4. Re-sync dependencies if uv is present
if [ -d ".venv" ]; then
    echo "[*] Syncing Python dependencies with uv..."
    # We use 'uv sync' to ensure the venv matches the updated pyproject.toml/requirements
    uv sync
fi

# 5. Pop the stash if we stashed anything
if [ "$STASHED" = true ]; then
    echo "[*] Re-applying local changes (popping stash)..."
    git stash pop
fi

# 6. Restart the systemd service
echo "[*] Restarting Inky.service..."
if systemctl list-units --full -all | grep -q "Inky.service"; then
    sudo systemctl restart Inky.service
    echo "[SUCCESS] Update complete and service restarted!"
else
    echo "[!] Systemd service not found. Skipping restart."
    echo "[SUCCESS] Code updated successfully."
fi

echo "--------------------------------------------------------"
echo "To check for errors: sudo journalctl -u Inky -f"