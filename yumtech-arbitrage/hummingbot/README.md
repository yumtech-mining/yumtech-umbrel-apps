# Hummingbot execution boundary

Production execution is pinned to upstream `hummingbot/hummingbot` v2.16.0.
The web process never submits an exchange order. This directory holds the
telemetry-off client configuration and the two audited CLOB connector overlays.

The runtime image starts a small local control supervisor. It accepts only
`start_test`, `stop`, `refresh` and `emergency_stop` commands through the
shared data volume and acknowledges them in `hummingbot-status.json`. In v0.4
`start_test` launches the reviewed `yumtech_paper_arbitrage.py` strategy on
the official paper connectors. The dashboard paper coordinator remains a
safe local fallback for the first unseeded API-test snapshot; it is not used
after public order-book data is available.

The execution image is started by `docker-compose.yml` as a paper-only host.
BTCTürk and Binance TR are local connector overlays registered as official
Hummingbot paper connectors. No API keys are copied into the paper config and
no live connector can be selected by the supervisor; live order submission
remains a separate release gate.

Required engine controls:

- upstream tag and image digest pinned;
- `anonymized_metrics_mode: anonymized_metrics_disabled`;
- `send_error_logs: false`;
- PaperTrade uses the official five-second market-order queue; any future live
  route must use bounded IOC limit orders, never unbounded market orders;
- BTCTürk market-BUY recovery uses a side-aware TRY quote converter with fresh
  balance, fee, precision, minimum and maximum preflight checks;
- persisted per-leg order IDs and a deterministic recovery state machine;
- one active user lease on Raspberry Pi 5 4 GB;
- egress denial for CoinAlpha reporting hosts.
