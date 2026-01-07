/**
 * PM2 Ecosystem Configuration
 * 
 * This file configures PM2 to manage both the validator manager and validator processes.
 * 
 * IMPORTANT: This is a template file. Run scripts/run.sh to configure it with your wallet details.
 * 
 * Usage:
 *   pm2 start ecosystem.config.js
 * 
 * Both processes will run via PM2 and survive SSH disconnect and system restarts.
 */

const path = require('path');

module.exports = {
  apps: [
    {
      name: 'cartha-validator-manager',
      script: 'scripts/validator_manager.py',
      args: '--hotkey-ss58 YOUR_HOTKEY_SS58 --netuid 35',
      cwd: path.resolve(__dirname, '..'),
      interpreter: 'python3',
      autorestart: true,
      watch: false,
      max_memory_restart: '500M',
      env: {
        NODE_ENV: 'production'
      },
      error_file: '~/.pm2/logs/cartha-validator-manager-error.log',
      out_file: '~/.pm2/logs/cartha-validator-manager-out.log',
      log_date_format: 'YYYY-MM-DD HH:mm:ss Z',
      merge_logs: true,
      time: true
    },
    {
      name: 'cartha-validator',
      script: 'uv',
      // NOTE: This is a placeholder. Run scripts/run.sh to configure with your wallet details.
      // The install script will replace this with your actual wallet-name, wallet-hotkey, and netuid
      args: 'run python -m cartha_validator.main --wallet-name YOUR_WALLET --wallet-hotkey YOUR_HOTKEY --netuid 35 --use-verified-amounts',
      cwd: path.resolve(__dirname, '..'),
      interpreter: 'none',
      autorestart: true,
      watch: false,
      max_memory_restart: '1G',
      env: {
        NODE_ENV: 'production'
        // Set these environment variables before running PM2:
        // WALLET_NAME: 'your-wallet-name',
        // WALLET_HOTKEY: 'your-hotkey-name',
        // NETUID: '35'
      },
      error_file: '~/.pm2/logs/cartha-validator-error.log',
      out_file: '~/.pm2/logs/cartha-validator-out.log',
      log_date_format: 'YYYY-MM-DD HH:mm:ss Z',
      merge_logs: true,
      time: true
    }
  ]
};
