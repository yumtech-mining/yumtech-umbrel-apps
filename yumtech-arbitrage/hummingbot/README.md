# Hummingbot execution boundary

Production execution is pinned to upstream `hummingbot/hummingbot` v2.16.0.
The web process never submits an exchange order. This directory holds the
telemetry-off client configuration and will hold the two audited CLOB connector
overlays plus `SafeArbitrageExecutor`.

The execution image is intentionally not started by `docker-compose.yml` yet.
BTCTürk and Binance TR are not official upstream connectors, so enabling an
unqualified engine would turn an installation step into a live-money risk.
Public scanning, encrypted credential storage and paper qualification can run
now; live order submission remains a release gate.

Required engine controls:

- upstream tag and image digest pinned;
- `anonymized_metrics_mode: anonymized_metrics_disabled`;
- `send_error_logs: false`;
- IOC limit orders with a bounded price, never unbounded market orders;
- persisted per-leg order IDs and a deterministic recovery state machine;
- one active user lease on Raspberry Pi 5 4 GB;
- egress denial for CoinAlpha reporting hosts.
