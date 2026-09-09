"""Local-only control file shared with the Hummingbot runtime container.

The dashboard and the engine do not share the Docker socket and no control
endpoint is exposed by the Hummingbot container. Commands are short-lived,
allow-listed test-mode intents written atomically to a data volume. The
runtime acknowledges them through the non-secret status marker.
"""

import json
import os
import secrets
import time
from pathlib import Path
from typing import Any


CONTROL_VERSION = 1
ALLOWED_ACTIONS = frozenset({"start_test", "stop", "refresh", "emergency_stop"})


class HummingbotControlError(ValueError):
    pass


def write_control(path: Path, *, action: str, user_id: int) -> dict[str, Any]:
    if action not in ALLOWED_ACTIONS:
        raise HummingbotControlError("Bilinmeyen Hummingbot kontrol komutu")
    if not isinstance(user_id, int) or user_id < 1:
        raise HummingbotControlError("Geçersiz kullanıcı")
    now = int(time.time() * 1000)
    command = {
        "version": CONTROL_VERSION,
        "id": secrets.token_hex(12),
        "action": action,
        "mode": "test",
        "issued_by": user_id,
        "issued_at_ms": now,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{secrets.token_hex(6)}.tmp")
    try:
        with temporary.open("w", encoding="utf-8") as handle:
            json.dump(command, handle, separators=(",", ":"))
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass
    return command


def read_control(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            return None
        if value.get("version") != CONTROL_VERSION:
            return None
        if value.get("action") not in ALLOWED_ACTIONS or value.get("mode") != "test":
            return None
        if not isinstance(value.get("id"), str) or not value["id"]:
            return None
        return {
            "version": CONTROL_VERSION,
            "id": value["id"],
            "action": value["action"],
            "mode": "test",
            "issued_at_ms": int(value.get("issued_at_ms", 0)),
        }
    except (OSError, ValueError, TypeError, OverflowError):
        return None

