from pathlib import Path

from app.hummingbot_status import read_status


def test_missing_hummingbot_marker_fails_closed_to_test_mode(tmp_path: Path):
    status = read_status(tmp_path / "missing.json")
    assert status["state"] == "not-installed"
    assert status["mode"] == "test"
    assert status["telemetry_disabled"] is True
    assert status["live_orders_enabled"] is False


def test_hummingbot_runtime_is_pinned_idle_and_reporting_disabled():
    dockerfile = (Path(__file__).parents[1] / "hummingbot-runtime" / "Dockerfile").read_text()
    entrypoint = (Path(__file__).parents[1] / "hummingbot-runtime" / "entrypoint.sh").read_text()
    compose = (Path(__file__).parents[1] / "docker-compose.yml").read_text()
    assert "hummingbot/hummingbot:version-2.16.0" in dockerfile
    assert "0001-disable-telemetry-by-default.patch" in dockerfile
    assert "YUMTECH_LIVE_TRADING_ENABLED=false" in dockerfile
    assert "YUMTECH_LIVE_TRADING_ENABLED,," in entrypoint
    assert "anonymized_metrics_mode: anonymized_metrics_disabled" in entrypoint
    assert "YUMTECH_TELEMETRY_DISABLED: \"true\"" in compose
    assert 'command: ["tail", "-f", "/dev/null"]' in compose
