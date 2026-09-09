import json
from pathlib import Path

import pytest

from app.hummingbot_control import HummingbotControlError, read_control, write_control


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

