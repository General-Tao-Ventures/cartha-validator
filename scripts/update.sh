#!/bin/bash
# Automatic update script for Cartha Validator
# This script updates the validator code while preserving your configuration
#
# Usage: ./scripts/update.sh
#
# This is called automatically by the validator manager for auto-updates,
# but can also be run manually.

set -e  # Exit on error

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
ECOSYSTEM_FILE="$SCRIPT_DIR/ecosystem.config.js"
ECOSYSTEM_BACKUP="$SCRIPT_DIR/.ecosystem.config.js.local"

echo "=========================================="
echo "Cartha Validator Update"
echo "=========================================="
echo ""

cd "$PROJECT_ROOT"

# Step 1: Backup ecosystem.config.js if it exists and has custom config
if [ -f "$ECOSYSTEM_FILE" ]; then
    # Check if it's configured (not containing placeholder values)
    if ! grep -q "YOUR_WALLET_NAME\|YOUR_HOTKEY_SS58\|YOUR_HOTKEY_NAME" "$ECOSYSTEM_FILE"; then
        echo "✓ Backing up your ecosystem.config.js..."
        cp "$ECOSYSTEM_FILE" "$ECOSYSTEM_BACKUP"
    fi
fi

# Step 2: Stop PM2 processes temporarily
echo ""
echo "Step 1: Stopping validator processes..."
pm2 stop cartha-validator cartha-validator-manager 2>/dev/null || true
echo "✓ Processes stopped"

# Step 3: Fetch and pull latest changes
echo ""
echo "Step 2: Fetching latest code..."
git fetch origin

# Check if there are local changes to tracked files (excluding ecosystem.config.js)
if git diff --quiet HEAD && git diff --cached --quiet; then
    echo "✓ No local changes to tracked files"
else
    echo "Note: Local changes detected in tracked files. Attempting merge..."
fi

# Pull with rebase to handle any minor conflicts gracefully
if git pull --rebase origin main 2>/dev/null; then
    echo "✓ Code updated successfully"
elif git pull origin main 2>/dev/null; then
    echo "✓ Code updated successfully"
else
    echo "⚠ Git pull failed. Attempting reset..."
    # If ecosystem.config.js is causing issues, temporarily move it
    if [ -f "$ECOSYSTEM_FILE" ]; then
        mv "$ECOSYSTEM_FILE" "${ECOSYSTEM_FILE}.tmp"
    fi
    git reset --hard origin/main
    # Restore ecosystem.config.js
    if [ -f "${ECOSYSTEM_FILE}.tmp" ]; then
        mv "${ECOSYSTEM_FILE}.tmp" "$ECOSYSTEM_FILE"
    fi
    echo "✓ Code reset to latest"
fi

# Step 4: Restore ecosystem.config.js from backup if needed
if [ -f "$ECOSYSTEM_BACKUP" ]; then
    # Check if ecosystem.config.js was deleted or replaced with template
    if [ ! -f "$ECOSYSTEM_FILE" ] || grep -q "YOUR_WALLET_NAME\|YOUR_HOTKEY_SS58\|YOUR_HOTKEY_NAME" "$ECOSYSTEM_FILE"; then
        echo ""
        echo "Step 3: Restoring your ecosystem.config.js..."
        cp "$ECOSYSTEM_BACKUP" "$ECOSYSTEM_FILE"
        echo "✓ Configuration restored"
    fi
fi

# Step 5: Sync Python dependencies
echo ""
echo "Step 4: Syncing Python dependencies..."
if command -v uv &> /dev/null; then
    uv sync
    echo "✓ Dependencies synced"
else
    echo "⚠ uv not found. Please run: curl -LsSf https://astral.sh/uv/install.sh | sh"
    echo "  Then run this script again."
    exit 1
fi

# Step 6: Verify ecosystem.config.js exists and is configured
echo ""
echo "Step 5: Verifying configuration..."
if [ ! -f "$ECOSYSTEM_FILE" ]; then
    # Try to copy from example
    if [ -f "$SCRIPT_DIR/ecosystem.config.example.js" ]; then
        echo "⚠ ecosystem.config.js not found. Copying from template..."
        cp "$SCRIPT_DIR/ecosystem.config.example.js" "$ECOSYSTEM_FILE"
        echo ""
        echo "IMPORTANT: Please configure $ECOSYSTEM_FILE with your wallet details!"
        echo "Then run: pm2 start $ECOSYSTEM_FILE"
        exit 1
    else
        echo "✗ No ecosystem.config.js found and no template available."
        echo "  Please run ./scripts/run.sh for initial setup."
        exit 1
    fi
fi

# Check if ecosystem.config.js has placeholder values
if grep -q "YOUR_WALLET_NAME\|YOUR_HOTKEY_SS58\|YOUR_HOTKEY_NAME" "$ECOSYSTEM_FILE"; then
    echo "⚠ ecosystem.config.js contains placeholder values."
    echo "  Please configure it with your wallet details!"
    echo "  Then run: pm2 start $ECOSYSTEM_FILE"
    exit 1
fi

echo "✓ Configuration verified"

# Step 7: Restart PM2 processes
echo ""
echo "Step 6: Restarting validator..."
pm2 restart cartha-validator cartha-validator-manager 2>/dev/null || pm2 start "$ECOSYSTEM_FILE"
pm2 save --force
echo "✓ Validator restarted"

# Step 8: Show current version
echo ""
echo "=========================================="
CURRENT_VERSION=$(grep -E "^__version__" "$PROJECT_ROOT/cartha_validator/__init__.py" | cut -d'"' -f2 2>/dev/null || echo "unknown")
echo "✓ Update complete! Version: $CURRENT_VERSION"
echo "=========================================="
echo ""
echo "Check status with: pm2 status"
echo "View logs with:    pm2 logs cartha-validator"
echo ""
