import importlib.util
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]


def test_upstream_lock_is_exact_and_not_latest():
    lock = (ROOT / "hummingbot-overlay" / "UPSTREAM.lock").read_text()
    assert "tag=v2.16.0" in lock
    assert "commit=8f1906145ba7840c9935cb2151d669e6af21564f" in lock
    assert "latest" not in lock.lower()


def test_runtime_and_source_defaults_disable_reporting():
    runtime_config = (ROOT / "hummingbot" / "conf_client.yml").read_text()
    privacy_patch = (
        ROOT / "hummingbot-overlay" / "patches" / "0001-disable-telemetry-by-default.patch"
    ).read_text()
    assert "anonymized_metrics_mode: anonymized_metrics_disabled" in runtime_config
    assert "send_error_logs: false" in runtime_config
    assert "default=AnonymizedMetricsDisabledMode()" in privacy_patch
    assert "default=False" in privacy_patch


def test_btcturk_signature_matches_known_vector():
    signing_path = (
        ROOT
        / "hummingbot-overlay"
        / "hummingbot"
        / "connector"
        / "exchange"
        / "btcturk"
        / "btcturk_signing.py"
    )
    spec = importlib.util.spec_from_file_location("btcturk_signing", signing_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    assert module.generate_signature(
        "test-key", "dGVzdC1zZWNyZXQ=", 1700000000123
    ) == "XORLW3AaT5ikKu+tz7ToTvU+f6jr7ndvb/gZ4aPBlx0="


def test_btcturk_private_endpoints_share_a_global_throttle_pool():
    constants = (
        ROOT
        / "hummingbot-overlay"
        / "hummingbot"
        / "connector"
        / "exchange"
        / "btcturk"
        / "btcturk_constants.py"
    ).read_text()
    assert "LinkedLimitWeightPair(PRIVATE_POOL)" in constants
    assert "USER_TRADES_PATH_URL" in constants


def test_btcturk_order_lifecycle_parsers():
    parser_path = (
        ROOT
        / "hummingbot-overlay"
        / "hummingbot"
        / "connector"
        / "exchange"
        / "btcturk"
        / "btcturk_parsers.py"
    )
    spec = importlib.util.spec_from_file_location("btcturk_parsers", parser_path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)

    balances = module.parse_balances({"data": [
        {"asset": "try", "balance": "250.25", "free": "200.10"}
    ]})
    assert balances[0].asset == "TRY"
    assert str(balances[0].available) == "200.10"
    assert module.normalize_order_status("PARTIALLY_FILLED") == "partial"
    assert module.order_id({"orderId": 42}) == "42"


def test_btcturk_exchange_implements_rest_lifecycle_contract():
    exchange = (
        ROOT
        / "hummingbot-overlay"
        / "hummingbot"
        / "connector"
        / "exchange"
        / "btcturk"
        / "btcturk_exchange.py"
    ).read_text()
    for method in (
        "_place_order",
        "_place_cancel",
        "_request_order_status",
        "_all_trade_updates_for_order",
        "_update_balances",
        "_update_trading_fees",
        "_format_trading_rules",
    ):
        assert f"def {method}(" in exchange
