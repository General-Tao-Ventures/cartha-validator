/**
 * PM2 Ecosystem Configuration Template
 * 
 * This file is a TEMPLATE. Copy it to ecosystem.config.js and configure it.
 * 
 * SETUP OPTIONS:
 *   1. Run: ./scripts/run.sh (interactive setup - recommended for first time)
 *   2. Or manually copy and edit:
 *      cp scripts/ecosystem.config.example.js scripts/ecosystem.config.js
 *      # Edit ecosystem.config.js with your wallet details
 *      pm2 start scripts/ecosystem.config.js
 * 
 * IMPORTANT: ecosystem.config.js is gitignored - your config won't be overwritten by updates!
 */

const path = require('path');

module.exports = {
  apps: [
    {
      name: 'cartha-validator-manager',
      script: 'scripts/validator_manager.py',
      // REQUIRED: Replace YOUR_HOTKEY_SS58 with your actual hotkey SS58 address
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
      // REQUIRED: Replace YOUR_WALLET_NAME and YOUR_HOTKEY_NAME with your values
      // For mainnet (netuid 35):
      //   'run python -m cartha_validator.main --wallet-name my-wallet --wallet-hotkey my-hotkey --netuid 35'
      // For testnet (netuid 78), add --subtensor.network test:
      //   'run python -m cartha_validator.main --wallet-name my-wallet --wallet-hotkey my-hotkey --netuid 78 --subtensor.network test'
      args: 'run python -m cartha_validator.main --wallet-name YOUR_WALLET_NAME --wallet-hotkey YOUR_HOTKEY_NAME --netuid 35',
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
