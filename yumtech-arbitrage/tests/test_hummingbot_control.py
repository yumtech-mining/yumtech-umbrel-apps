import json
from pathlib import Path

import pytest

from app.hummingbot_control import (HummingbotControlError, read_control,
                                     write_control, write_paper_config)


def test_control_commands_are_atomic_test_only_and_non_secret(tmp_path: Path):
    path = tmp_path / "nested" / "hummingbot-control.json"
    command = write_control(path, action="start_test", user_id=7)
    assert command["mode"] == "test"
    assert command["action"] == "start_test"
    assert read_control(path)["id"] == command["id"]
    assert "api" not in json.dumps(command).lower()
    assert path.stat().st_mode & 0o777 == 0o600


def test_live_or_unknown_commands_cannot_be_written(tmp_path: Path):
    with pytest.raises(HummingbotControlError):
        write_control(tmp_path / "control.json", action="start_live", user_id=1)
    with pytest.raises(HummingbotControlError):
        write_control(tmp_path / "control.json", action="stop", user_id=0)


def test_paper_config_is_pair_normalized_and_contains_no_credentials(tmp_path: Path):
    path = tmp_path / "paper.json"
    config = write_paper_config(
        path, user_id=7, pairs=["btc/try", "ETH-TRY", "BTC/TRY"],
        profile={"btcturk_budget_try": "750", "binance_tr_budget_try": "900"},
        fee_status={"mode": "taker"}, min_profit_pct="0.40",
    )
    assert config["trading_pairs"] == ["BTC-TRY", "ETH-TRY"]
    assert config["btcturk_budget_try"] == "750"
    assert "api_key" not in path.read_text().lower()
    assert path.stat().st_mode & 0o777 == 0o600
