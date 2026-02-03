#!/bin/bash
# Interactive installation script for validator manager
# One-stop setup for validators

set -e  # Exit on error

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

echo "=========================================="
echo "Cartha Validator Manager Installation"
echo "=========================================="
echo ""

# Check if running as root
if [ "$EUID" -eq 0 ]; then
    echo "Warning: Running as root. Consider using a non-root user."
    echo ""
fi

# 1. Check Node.js and install PM2
echo "Step 1: Installing PM2..."
if ! command -v node &> /dev/null; then
    echo "Error: Node.js is not installed."
    echo "Please install Node.js first: https://nodejs.org/"
    exit 1
fi

if ! command -v pm2 &> /dev/null; then
    echo "Installing PM2 globally..."
    npm install -g pm2
    echo "✓ PM2 installed"
else
    echo "✓ PM2 is already installed: $(pm2 --version)"
fi
echo ""

# 2. Check Python and uv
echo "Step 2: Checking Python and uv..."
if ! command -v python3 &> /dev/null; then
    echo "Error: Python 3 is not installed."
    exit 1
fi

if ! command -v uv &> /dev/null; then
    echo "Error: uv is not installed."
    echo "Install with: curl -LsSf https://astral.sh/uv/run.sh | sh"
    exit 1
fi
echo "✓ Python: $(python3 --version)"
echo "✓ uv: $(uv --version)"
echo ""

# 3. Install Python dependencies
echo "Step 3: Installing Python dependencies..."
cd "$PROJECT_ROOT"
uv sync
echo "✓ Dependencies installed"
echo ""

# 4. Verify ecosystem.config.js exists
echo "Step 4: Verifying PM2 ecosystem config..."
ECOSYSTEM_FILE="$SCRIPT_DIR/ecosystem.config.js"
if [ ! -f "$ECOSYSTEM_FILE" ]; then
    echo "Error: ecosystem.config.js not found at $ECOSYSTEM_FILE"
    exit 1
fi
echo "✓ Ecosystem config found"
echo "  (Using dynamic path resolution via path.resolve)"
echo ""

# 5. Interactive configuration
echo "=========================================="
echo "Configuration"
echo "=========================================="
echo ""

# Prompt for wallet name
read -p "Enter your wallet name (coldkey): " WALLET_NAME
if [ -z "$WALLET_NAME" ]; then
    echo "Error: Wallet name is required"
    exit 1
fi

# Prompt for hotkey
read -p "Enter your hotkey name: " WALLET_HOTKEY
if [ -z "$WALLET_HOTKEY" ]; then
    echo "Error: Hotkey name is required"
    exit 1
fi

# Prompt for netuid
echo ""
echo "Select network:"
echo "  1) Mainnet (netuid 35)"
echo "  2) Testnet (netuid 78)"
read -p "Enter choice [1]: " NETUID_CHOICE
NETUID_CHOICE=${NETUID_CHOICE:-1}

if [ "$NETUID_CHOICE" = "2" ]; then
    NETUID="78"
else
    NETUID="35"
fi

echo ""
echo "✓ Configuration:"
echo "  Wallet: $WALLET_NAME"
echo "  Hotkey: $WALLET_HOTKEY"
echo "  NetUID: $NETUID"
echo ""

# 6. Update ecosystem.config.js with wallet/hotkey/netuid
echo "Step 5: Updating ecosystem.config.js..."
# Create a backup
cp "$ECOSYSTEM_FILE" "$ECOSYSTEM_FILE.backup"

# Use Python to update the JavaScript file properly
python3 << EOF
import re

ecosystem_file = "$ECOSYSTEM_FILE"
wallet_name = "$WALLET_NAME"
wallet_hotkey = "$WALLET_HOTKEY"
netuid = "$NETUID"

# Read the file
with open(ecosystem_file, 'r') as f:
    content = f.read()

# Build args string with proper flags
# For testnet (netuid 78), add --subtensor.network test
args_parts = [
    "run python -m cartha_validator.main",
    f"--wallet-name {wallet_name}",
    f"--wallet-hotkey {wallet_hotkey}",
    f"--netuid {netuid}",
]

# Add --subtensor.network test for testnet
if netuid == "78":
    args_parts.append("--subtensor.network test")

# Join all args
new_args_str = " ".join(args_parts)
new_args_line = f"      args: '{new_args_str}',"

# Simple line-by-line replacement - most reliable approach
# Find the line containing both 'args:' and 'cartha_validator.main'
lines = content.split('\n')
replaced = False

for i, line in enumerate(lines):
    if 'args:' in line and 'cartha_validator.main' in line:
        lines[i] = new_args_line
        replaced = True
        print(f"✓ Updated cartha-validator args in ecosystem.config.js")
        break

if not replaced:
    print("Warning: Could not find cartha-validator args line to replace.")
    print("Please update ecosystem.config.js manually with:")
    print(f"  {new_args_line}")

if netuid == "78":
    print("  Added --subtensor.network test for testnet")

# Write back
content = '\n'.join(lines)
with open(ecosystem_file, 'w') as f:
    f.write(content)
EOF

echo ""

# Extract hotkey SS58 address for validator manager (silent on failure)
HOTKEY_SS58=$(python3 << EOF 2>/dev/null
import sys
try:
    import bittensor as bt
    wallet = bt.wallet(name="$WALLET_NAME", hotkey="$WALLET_HOTKEY")
    print(wallet.hotkey.ss58_address)
except Exception:
    sys.exit(0)  # Silent failure, non-fatal
EOF
)

if [ -n "$HOTKEY_SS58" ]; then
    echo "Step 5.5: Resolved hotkey SS58: $HOTKEY_SS58"
    
    # Update ecosystem.config.js to add hotkey-ss58 and netuid to validator manager args
    python3 << EOF 2>/dev/null
import re

ecosystem_file = "$ECOSYSTEM_FILE"
hotkey_ss58 = "$HOTKEY_SS58"
netuid = "$NETUID"

with open(ecosystem_file, 'r') as f:
    content = f.read()

lines = content.split('\n')
in_manager_section = False

for i, line in enumerate(lines):
    if "name: 'cartha-validator-manager'" in line:
        in_manager_section = True
    elif in_manager_section and "args:" in line:
        lines[i] = re.sub(r"args: '[^']*'", f"args: '--hotkey-ss58 {hotkey_ss58} --netuid {netuid}'", line)
        break
    elif in_manager_section and line.strip().startswith('}'):
        break

content = '\n'.join(lines)
with open(ecosystem_file, 'w') as f:
    f.write(content)
EOF
    echo "✓ Updated validator manager args"
fi

echo ""

# 7. Optional: RPC URL configuration
echo "Step 6: Optional RPC configuration..."
ENV_FILE="$PROJECT_ROOT/.env"

echo ""
echo "Default RPC URL: https://mainnet.base.org"
echo "You can override this if you have your own RPC node."
echo ""
read -p "Do you want to use a custom RPC URL? [y/N]: " OVERRIDE_RPC
OVERRIDE_RPC=${OVERRIDE_RPC:-N}

if [[ "$OVERRIDE_RPC" =~ ^[Yy]$ ]]; then
    read -p "Enter your custom RPC URL: " PARENT_VAULT_RPC_URL
    
    if [ -n "$PARENT_VAULT_RPC_URL" ]; then
        # Write/update .env file
        {
            echo "# Cartha Validator Configuration"
            echo "# Generated by run.sh"
            echo ""
            echo "PARENT_VAULT_RPC_URL=$PARENT_VAULT_RPC_URL"
        } > "$ENV_FILE"
        echo "✓ Created/updated .env file with custom RPC URL"
    fi
else
    # Create empty .env file or leave existing (will use defaults)
    if [ ! -f "$ENV_FILE" ]; then
        touch "$ENV_FILE"
        echo "# Cartha Validator Configuration" > "$ENV_FILE"
        echo "# Using default RPC URL" >> "$ENV_FILE"
    fi
fi
echo ""


# 8. Setup PM2 startup
echo "Step 7: Setting up PM2 startup..."
pm2 startup > /tmp/pm2_startup.sh 2>&1 || true
if [ -f /tmp/pm2_startup.sh ]; then
    STARTUP_CMD=$(cat /tmp/pm2_startup.sh | grep -E "sudo|pm2" | head -1)
    if [ -n "$STARTUP_CMD" ]; then
        echo "PM2 startup command generated (save this for later):"
        echo "  $STARTUP_CMD"
        echo ""
    fi
fi

# 10. Ask if user wants to start validator now
echo "=========================================="
echo "Installation Complete!"
echo "=========================================="
echo ""
read -p "Do you want to start the validator now? [Y/n]: " START_NOW
START_NOW=${START_NOW:-Y}

if [[ "$START_NOW" =~ ^[Yy]$ ]]; then
    echo ""
    echo "Starting validator manager..."
    pm2 start "$ECOSYSTEM_FILE"
    pm2 save
    echo ""
    echo "✓ Validator started!"
    echo ""
    echo "Check status with:"
    echo "  pm2 status"
    echo ""
    echo "View logs with:"
    echo "  pm2 logs cartha-validator"
    echo "  pm2 logs cartha-validator-manager"
    echo ""
else
    echo ""
    echo "To start the validator later, run:"
    echo "  pm2 start $ECOSYSTEM_FILE"
    echo "  pm2 save"
    echo ""
fi

echo "Configuration saved:"
echo "  - Wallet: $WALLET_NAME"
echo "  - Hotkey: $WALLET_HOTKEY"
echo "  - NetUID: $NETUID"
echo "  - Ecosystem config: $ECOSYSTEM_FILE"
[ -f "$ENV_FILE" ] && echo "  - Environment file: $ENV_FILE"
echo ""
echo "The validator manager will:"
echo "  - Keep the validator running (survives SSH disconnect)"
echo "  - Check for GitHub releases and auto-update"
echo ""
