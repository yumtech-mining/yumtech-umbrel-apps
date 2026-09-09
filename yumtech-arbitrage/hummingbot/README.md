# Hummingbot execution boundary

Production execution is pinned to upstream `hummingbot/hummingbot` v2.16.0.
The web process never submits an exchange order. This directory holds the
telemetry-off client configuration and the two audited CLOB connector overlays.

The runtime image starts a small local control supervisor. It accepts only
`start_test`, `stop`, `refresh` and `emergency_stop` commands through the
shared data volume and acknowledges them in `hummingbot-status.json`. It does
not launch a strategy or accept live commands in v0.3; the dashboard paper
coordinator is the only executable test engine until the reviewed controller
is released.

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
- BTCTürk market-BUY recovery uses a side-aware TRY quote converter with fresh
  balance, fee, precision, minimum and maximum preflight checks;
- persisted per-leg order IDs and a deterministic recovery state machine;
- one active user lease on Raspberry Pi 5 4 GB;
- egress denial for CoinAlpha reporting hosts.
