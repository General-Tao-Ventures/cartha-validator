/**
 * PM2 Ecosystem Configuration
 * 
 * This file configures PM2 to manage both the validator manager and validator processes.
 * 
 * Usage:
 *   pm2 start ecosystem.config.js
 * 
 * Both processes will run via PM2 and survive SSH disconnect and system restarts.
 */

module.exports = {
  apps: [
    {
      name: 'cartha-validator-manager',
      script: 'scripts/validator_manager.py',
      args: '',
      cwd: '/Users/tonyle/developer/GTV-Taoshi/cartha-subnet/cartha-validator',
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
      // NOTE: Update these args with your actual wallet name, hotkey, and netuid
      // Example: 'run python -m cartha_validator.main --wallet-name cold --wallet-hotkey hot --netuid 35'
      // You can also set WALLET_NAME, WALLET_HOTKEY, NETUID as environment variables
      // and use them via process.env.WALLET_NAME in the args string
            args: 'run python -m cartha_validator.main --wallet-name demo --wallet-hotkey h4 --netuid 78 --use-verified-amounts --subtensor.network test',
      cwd: '/Users/tonyle/developer/GTV-Taoshi/cartha-subnet/cartha-validator',
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
