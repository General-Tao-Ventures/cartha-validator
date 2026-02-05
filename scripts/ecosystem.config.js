/**
 * PM2 Ecosystem Configuration Template
 * 
 * This file configures PM2 to manage both the validator manager and validator processes.
 * 
 * IMPORTANT: Run scripts/run.sh to configure this file with your wallet details.
 * The script will prompt for your wallet name, hotkey, and network.
 * 
 * Usage:
 *   1. Run: ./scripts/run.sh (interactive setup)
 *   2. Or manually edit the PLACEHOLDER values below
 *   3. Then: pm2 start scripts/ecosystem.config.js
 * 
 * Both processes will run via PM2 and survive SSH disconnect and system restarts.
 */

const path = require('path');

module.exports = {
  apps: [
    {
      name: 'cartha-validator-manager',
      script: 'scripts/validator_manager.py',
      // PLACEHOLDER: Replace YOUR_HOTKEY_SS58 with your actual hotkey SS58 address
      // Example: '--hotkey-ss58 5GrwvaEF5zXb26Fz9rcQpDWS57CtERHpNehXCPcNoHGKutQY --netuid 35'
      args: '--hotkey-ss58 YOUR_HOTKEY_SS58 --netuid 35',
      cwd: path.resolve(__dirname, '..'),
      interpreter: 'python3',
      autorestart: true,
      watch: false,
      max_memory_restart: '500M',
      env: {
        NODE_ENV: 'production'
      },
      log_date_format: 'YYYY-MM-DD HH:mm:ss Z',
      merge_logs: true,
      time: true
    },
    {
      name: 'cartha-validator',
      script: 'uv',
      // PLACEHOLDER: Replace YOUR_WALLET_NAME and YOUR_HOTKEY_NAME with your actual values
      // Example: 'run python -m cartha_validator.main --wallet-name my-wallet --wallet-hotkey my-hotkey --netuid 35'
      // For testnet, add: --subtensor.network test
      args: 'run python -m cartha_validator.main --wallet-name sn35 --wallet-hotkey default --netuid 35',
      cwd: path.resolve(__dirname, '..'),
      interpreter: 'none',
      autorestart: true,
      watch: false,
      max_memory_restart: '1G',
      env: {
        NODE_ENV: 'production'
      },
      log_date_format: 'YYYY-MM-DD HH:mm:ss Z',
      merge_logs: true,
      time: true
    }
  ]
};
