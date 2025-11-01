# Cartha Subnet Validator Architecture

> Draft placeholder – detailed design will be populated as implementation progresses.

## Components

- **Validator (`packages/validator`)** – Pulls the verifier’s read-only API, replays vault events, and submits `set_weights`.
- **Subnet (`packages/subnet`)** – Epoch scheduler utilities that orchestrate freeze → replay → publish flows.
- **ABIs (`packages/abis`)** – Vault ABI definitions leveraged by the indexer for log decoding.

## External Dependencies

- **Cartha Verifier API** – Provides the epoch-frozen verified miner list.
- **EVM Vaults** – Source of on-chain events indexed during replay.
- **Bittensor Subtensor** – Destination for published weights each epoch.

## Next Steps

- Document indexer behaviours (lock updates, partial releases, evictions).
- Capture operational runbooks for scheduling and alerting.
