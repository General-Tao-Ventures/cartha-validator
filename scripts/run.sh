#!/bin/bash
# Interactive installation script for validator manager
# One-stop setup for validators
#
# This script will:
# - Install dependencies (Node.js, PM2, Python, uv)
# - Configure your validator (wallet, hotkey, network)
# - Start the validator via PM2
#
# If already configured, it will skip interactive setup and just restart.
# For updates only (no reconfiguration), use: ./scripts/update.sh

set -e  # Exit on error

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
ECOSYSTEM_FILE="$SCRIPT_DIR/ecosystem.config.js"
ECOSYSTEM_EXAMPLE="$SCRIPT_DIR/ecosystem.config.example.js"

# Check if already configured (ecosystem.config.js exists and has no placeholders)
ALREADY_CONFIGURED=false
if [ -f "$ECOSYSTEM_FILE" ]; then
    if ! grep -q "YOUR_WALLET_NAME\|YOUR_HOTKEY_SS58\|YOUR_HOTKEY_NAME" "$ECOSYSTEM_FILE"; then
        ALREADY_CONFIGURED=true
    fi
fi

echo "=========================================="
echo "Cartha Validator Manager Installation"
echo "=========================================="
echo ""

if [ "$ALREADY_CONFIGURED" = true ]; then
    echo "✓ Existing configuration detected!"
    echo ""
    echo "Your ecosystem.config.js is already configured."
    echo "Running update and restart..."
    echo ""
    
    # Run the update script instead
    if [ -f "$SCRIPT_DIR/update.sh" ]; then
        chmod +x "$SCRIPT_DIR/update.sh"
        exec "$SCRIPT_DIR/update.sh"
    else
        # Fallback if update.sh doesn't exist
        cd "$PROJECT_ROOT"
        uv sync
        pm2 restart cartha-validator cartha-validator-manager 2>/dev/null || pm2 start "$ECOSYSTEM_FILE"
        pm2 save --force
        echo ""
        echo "✓ Validator restarted!"
        echo ""
        echo "To reconfigure, delete ecosystem.config.js and run this script again:"
        echo "  rm $ECOSYSTEM_FILE"
        echo "  ./scripts/run.sh"
        exit 0
    fi
fi

# Check if running as root (Linux/macOS only - skip on Windows)
if [[ "$OSTYPE" != "msys" ]] && [[ "$OSTYPE" != "cygwin" ]] && [[ "$OSTYPE" != "win32" ]]; then
    if [ "$EUID" -eq 0 ] 2>/dev/null; then
        echo "Warning: Running as root. Consider using a non-root user."
        echo ""
    fi
fi

# 1. Check Node.js and install PM2
echo "Step 1: Checking Node.js and PM2..."

# Function to detect OS and suggest Node.js installation
install_nodejs() {
    echo ""
    echo "Node.js is required but not installed."
    echo ""
    
    # Detect OS
    if [[ "$OSTYPE" == "darwin"* ]]; then
        # macOS
        if command -v brew &> /dev/null; then
            echo "Detected: macOS with Homebrew"
            read -p "Install Node.js via Homebrew? [Y/n]: " INSTALL_NODE
            INSTALL_NODE=${INSTALL_NODE:-Y}
            if [[ "$INSTALL_NODE" =~ ^[Yy]$ ]]; then
                echo "Installing Node.js..."
                brew install node
                return 0
            fi
        else
            echo "Detected: macOS"
            echo ""
            echo "Install Node.js using one of these methods:"
            echo "  1. Install Homebrew first: /bin/bash -c \"\$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)\""
            echo "     Then run: brew install node"
            echo "  2. Download from: https://nodejs.org/"
        fi
    elif [[ "$OSTYPE" == "linux-gnu"* ]]; then
        # Linux
        if command -v apt &> /dev/null; then
            echo "Detected: Linux (Debian/Ubuntu)"
            read -p "Install Node.js via apt? [Y/n]: " INSTALL_NODE
            INSTALL_NODE=${INSTALL_NODE:-Y}
            if [[ "$INSTALL_NODE" =~ ^[Yy]$ ]]; then
                echo "Installing Node.js..."
                sudo apt update && sudo apt install -y nodejs npm
                return 0
            fi
        elif command -v yum &> /dev/null; then
            echo "Detected: Linux (CentOS/RHEL)"
            read -p "Install Node.js via yum? [Y/n]: " INSTALL_NODE
            INSTALL_NODE=${INSTALL_NODE:-Y}
            if [[ "$INSTALL_NODE" =~ ^[Yy]$ ]]; then
                echo "Installing Node.js..."
                sudo yum install -y nodejs npm
                return 0
            fi
        elif command -v dnf &> /dev/null; then
            echo "Detected: Linux (Fedora)"
            read -p "Install Node.js via dnf? [Y/n]: " INSTALL_NODE
            INSTALL_NODE=${INSTALL_NODE:-Y}
            if [[ "$INSTALL_NODE" =~ ^[Yy]$ ]]; then
                echo "Installing Node.js..."
                sudo dnf install -y nodejs npm
                return 0
            fi
        elif command -v pacman &> /dev/null; then
            echo "Detected: Linux (Arch)"
            read -p "Install Node.js via pacman? [Y/n]: " INSTALL_NODE
            INSTALL_NODE=${INSTALL_NODE:-Y}
            if [[ "$INSTALL_NODE" =~ ^[Yy]$ ]]; then
                echo "Installing Node.js..."
                sudo pacman -S --noconfirm nodejs npm
                return 0
            fi
        else
            echo "Detected: Linux"
            echo ""
            echo "Install Node.js using one of these methods:"
            echo "  1. Use nvm: curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.39.0/install.sh | bash"
            echo "     Then run: nvm install --lts"
            echo "  2. Download from: https://nodejs.org/"
        fi
    elif [[ "$OSTYPE" == "msys" ]] || [[ "$OSTYPE" == "cygwin" ]] || [[ "$OSTYPE" == "win32" ]]; then
        # Windows
        echo "Detected: Windows"
        echo ""
        echo "Install Node.js using one of these methods:"
        echo "  1. Download from: https://nodejs.org/"
        echo "  2. Use Chocolatey: choco install nodejs"
        echo "  3. Use Scoop: scoop install nodejs"
    else
        echo "Unknown OS: $OSTYPE"
        echo "Please install Node.js from: https://nodejs.org/"
    fi
    
    echo ""
    echo "After installing Node.js, run this script again."
    return 1
}

if ! command -v node &> /dev/null; then
    if ! install_nodejs; then
        exit 1
    fi
    # Verify installation worked
    if ! command -v node &> /dev/null; then
        echo "Error: Node.js installation failed or not in PATH."
        echo "Please install manually and run this script again."
        exit 1
    fi
fi
echo "✓ Node.js: $(node --version)"

if ! command -v pm2 &> /dev/null; then
    echo "Installing PM2 globally..."
    
    # Try installing without sudo first
    if npm install -g pm2 2>/dev/null; then
        echo "✓ PM2 installed"
    else
        # Permission denied - handle based on OS
        if [[ "$OSTYPE" == "msys" ]] || [[ "$OSTYPE" == "cygwin" ]] || [[ "$OSTYPE" == "win32" ]]; then
            # Windows - no sudo, need to run as Administrator
            echo ""
            echo "Permission denied. On Windows, please either:"
            echo "  1. Run this script from an Administrator terminal (right-click -> Run as Administrator)"
            echo "  2. Or install PM2 manually in an Administrator terminal: npm install -g pm2"
            echo ""
            echo "After installing PM2, run this script again."
            exit 1
        else
            # Linux/macOS - try with sudo
            echo "Permission denied. Trying with sudo..."
            if sudo npm install -g pm2; then
                echo "✓ PM2 installed (with sudo)"
            else
                echo ""
                echo "Failed to install PM2. You can try manually:"
                echo "  Option 1: sudo npm install -g pm2"
                echo "  Option 2: Configure npm to use a user directory:"
                echo "            mkdir -p ~/.npm-global"
                echo "            npm config set prefix '~/.npm-global'"
                echo "            echo 'export PATH=~/.npm-global/bin:\$PATH' >> ~/.bashrc"
                echo "            source ~/.bashrc"
                echo "            npm install -g pm2"
                exit 1
            fi
        fi
    fi
else
    echo "✓ PM2 is already installed: $(pm2 --version)"
fi
echo ""

# 2. Check Python and uv
echo "Step 2: Checking Python and uv..."

# On Windows, python3 might be called 'python'
PYTHON_CMD="python3"
if ! command -v python3 &> /dev/null; then
    if command -v python &> /dev/null; then
        # Check if 'python' is Python 3
        PYTHON_VERSION=$(python --version 2>&1)
        if [[ "$PYTHON_VERSION" == *"Python 3"* ]]; then
            PYTHON_CMD="python"
        else
            PYTHON_CMD=""
        fi
    else
        PYTHON_CMD=""
    fi
fi

if [ -z "$PYTHON_CMD" ] || ! command -v $PYTHON_CMD &> /dev/null; then
    echo ""
    echo "Python 3 is required but not installed."
    echo ""
    if [[ "$OSTYPE" == "darwin"* ]]; then
        echo "Install Python on macOS:"
        echo "  brew install python3"
    elif [[ "$OSTYPE" == "linux-gnu"* ]]; then
        if command -v apt &> /dev/null; then
            echo "Install Python on Ubuntu/Debian:"
            echo "  sudo apt install python3 python3-pip"
        else
            echo "Install Python using your package manager or from: https://www.python.org/"
        fi
    elif [[ "$OSTYPE" == "msys" ]] || [[ "$OSTYPE" == "cygwin" ]] || [[ "$OSTYPE" == "win32" ]]; then
        echo "Install Python on Windows:"
        echo "  1. Download from: https://www.python.org/downloads/"
        echo "  2. Or use: winget install Python.Python.3.11"
        echo "  3. Or use: choco install python"
    else
        echo "Install Python from: https://www.python.org/"
    fi
    exit 1
fi
echo "✓ Python: $($PYTHON_CMD --version)"

if ! command -v uv &> /dev/null; then
    echo ""
    echo "uv (Python package manager) is required but not installed."
    read -p "Install uv now? [Y/n]: " INSTALL_UV
    INSTALL_UV=${INSTALL_UV:-Y}
    if [[ "$INSTALL_UV" =~ ^[Yy]$ ]]; then
        echo "Installing uv..."
        
        if [[ "$OSTYPE" == "msys" ]] || [[ "$OSTYPE" == "cygwin" ]] || [[ "$OSTYPE" == "win32" ]]; then
            # Windows - use PowerShell installer
            if command -v powershell &> /dev/null; then
                powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
            else
                echo "Please install uv manually using PowerShell:"
                echo "  powershell -ExecutionPolicy ByPass -c \"irm https://astral.sh/uv/install.ps1 | iex\""
                exit 1
            fi
        else
            # Linux/macOS - use curl
            curl -LsSf https://astral.sh/uv/install.sh | sh
        fi
        
        # Source the shell config to get uv in PATH
        if [ -f "$HOME/.cargo/env" ]; then
            source "$HOME/.cargo/env"
        fi
        # Also check common uv install locations
        if [ -f "$HOME/.local/bin/uv" ]; then
            export PATH="$HOME/.local/bin:$PATH"
        fi
        # Windows uv location
        if [ -f "$USERPROFILE/.local/bin/uv.exe" ] 2>/dev/null; then
            export PATH="$USERPROFILE/.local/bin:$PATH"
        fi
        
        # Verify installation
        if ! command -v uv &> /dev/null; then
            echo ""
            echo "uv installed but not in PATH. Please restart your terminal and run this script again."
            if [[ "$OSTYPE" == "msys" ]] || [[ "$OSTYPE" == "cygwin" ]] || [[ "$OSTYPE" == "win32" ]]; then
                echo "On Windows, you may need to restart your terminal or add uv to PATH."
            else
                echo "Or manually add to PATH: export PATH=\"\$HOME/.local/bin:\$PATH\""
            fi
            exit 1
        fi
        echo "✓ uv installed"
    else
        if [[ "$OSTYPE" == "msys" ]] || [[ "$OSTYPE" == "cygwin" ]] || [[ "$OSTYPE" == "win32" ]]; then
            echo "Install uv with PowerShell: irm https://astral.sh/uv/install.ps1 | iex"
        else
            echo "Install uv with: curl -LsSf https://astral.sh/uv/install.sh | sh"
        fi
        exit 1
    fi
fi
echo "✓ uv: $(uv --version)"
echo ""

# 3. Install Python dependencies
echo "Step 3: Installing Python dependencies..."
cd "$PROJECT_ROOT"
uv sync
echo "✓ Dependencies installed"
echo ""

# 4. Prepare ecosystem.config.js
echo "Step 4: Preparing PM2 ecosystem config..."
if [ ! -f "$ECOSYSTEM_FILE" ]; then
    if [ -f "$ECOSYSTEM_EXAMPLE" ]; then
        echo "Creating ecosystem.config.js from template..."
        cp "$ECOSYSTEM_EXAMPLE" "$ECOSYSTEM_FILE"
    else
        echo "Error: No ecosystem config template found at $ECOSYSTEM_EXAMPLE"
        exit 1
    fi
fi
echo "✓ Ecosystem config ready"
echo ""

# 5. Interactive configuration
echo "=========================================="
echo "Configuration"
echo "=========================================="
echo ""

# Prompt for wallet name (required)
read -p "Enter your wallet name (coldkey): " WALLET_NAME
if [ -z "$WALLET_NAME" ]; then
    echo "Error: Wallet name is required"
    exit 1
fi

# Prompt for hotkey (default: "default")
read -p "Enter your hotkey name [default]: " WALLET_HOTKEY
WALLET_HOTKEY=${WALLET_HOTKEY:-default}

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
$PYTHON_CMD << EOF
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
HOTKEY_SS58=$($PYTHON_CMD << EOF 2>/dev/null
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
    $PYTHON_CMD << EOF 2>/dev/null
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


# 8. Setup PM2 startup (skip on Windows - pm2 startup doesn't work the same way)
echo "Step 7: Setting up PM2 startup..."
if [[ "$OSTYPE" == "msys" ]] || [[ "$OSTYPE" == "cygwin" ]] || [[ "$OSTYPE" == "win32" ]]; then
    echo "Note: On Windows, PM2 startup is handled differently."
    echo "To run PM2 on Windows startup, consider using Task Scheduler or a Windows service."
    echo "See: https://pm2.keymetrics.io/docs/usage/startup/#windows-consideration"
else
    # Use cross-platform temp directory
    TEMP_FILE="${TMPDIR:-/tmp}/pm2_startup.sh"
    pm2 startup > "$TEMP_FILE" 2>&1 || true
    if [ -f "$TEMP_FILE" ]; then
        STARTUP_CMD=$(grep -E "sudo|pm2" "$TEMP_FILE" | head -1)
        if [ -n "$STARTUP_CMD" ]; then
            echo "PM2 startup command generated (save this for later):"
            echo "  $STARTUP_CMD"
            echo ""
        fi
        rm -f "$TEMP_FILE"
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
