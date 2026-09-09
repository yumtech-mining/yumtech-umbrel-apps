#!/usr/bin/env python3
"""A tiny, fail-closed acknowledgement loop for the Hummingbot host.

This release intentionally does not launch a trading strategy. It proves the
dashboard-to-runtime control boundary without giving the web process a Docker
socket or an exchange order path. ``start_test`` marks the pinned Hummingbot
host as test-ready; the application paper coordinator remains the only order
simulator. Live commands are not representable in the control schema.
"""

from __future__ import annotations

import json
import os
import signal
import time
from pathlib import Path


CONTROL_VERSION = 1
ALLOWED_ACTIONS = {"start_test", "stop", "refresh", "emergency_stop"}
running = True


def _stop(*_args):
    global running
    running = False


def _read(path: Path) -> dict | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(value, dict) or value.get("version") != CONTROL_VERSION:
            return None
        if value.get("mode") != "test" or value.get("action") not in ALLOWED_ACTIONS:
            return None
        command_id = value.get("id")
        return value if isinstance(command_id, str) and command_id else None
    except (OSError, ValueError, TypeError):
        return None


def _write(path: Path, *, state: str, action: str | None, command_id: str | None,
           reason: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "state": state,
        "mode": "test",
        "engine_version": os.environ.get("YUMTECH_ENGINE_VERSION", "v2.16.0"),
        "telemetry_disabled": True,
        "live_orders_enabled": False,
        "strategy": "idle",
        "control_action": action,
        "orders_submitted": 0,
        "engine_process_running": False,
        "updated_at_ms": int(time.time() * 1000),
        "last_control_id": command_id,
        "reason": reason,
    }
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(json.dumps(payload, separators=(",", ":")) + "\n", encoding="utf-8")
    os.chmod(temporary, 0o600)
    os.replace(temporary, path)


def main() -> None:
    status_path = Path(os.environ.get("YUMTECH_STATUS_FILE", "/home/hummingbot/yumtech-data/hummingbot-status.json"))
    control_path = Path(os.environ.get("YUMTECH_CONTROL_FILE", "/home/hummingbot/yumtech-data/hummingbot-control.json"))
    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)
    last_id = None
    _write(status_path, state="idle", action=None, command_id=None,
           reason="Test host hazır; strateji başlatılmadı")
    while running:
        command = _read(control_path)
        if command and command["id"] != last_id:
            last_id = command["id"]
            action = command["action"]
            if action == "start_test":
                _write(status_path, state="test-ready", action=action, command_id=last_id,
                       reason="Test komutu alındı; paper motoru dashboard servisinde çalışıyor")
            elif action == "emergency_stop":
                _write(status_path, state="emergency-stopped", action=action, command_id=last_id,
                       reason="Acil durdurma; yeni test komutu bekleniyor")
            elif action == "stop":
                _write(status_path, state="stopped", action=action, command_id=last_id,
                       reason="Test hostu durduruldu")
            else:
                _write(status_path, state="idle", action=action, command_id=last_id,
                       reason="Durum yenilendi")
        time.sleep(0.5)
    _write(status_path, state="stopped", action="shutdown", command_id=last_id,
           reason="Hummingbot hostu durduruldu")


if __name__ == "__main__":
    main()

