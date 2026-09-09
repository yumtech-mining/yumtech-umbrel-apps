import json
from pathlib import Path


def read_status(path: Path) -> dict:
    """Read the non-secret shared Hummingbot status marker, failing closed."""
    fallback = {
        "state": "not-installed", "mode": "test", "engine_version": "v2.16.0",
        "telemetry_disabled": True, "live_orders_enabled": False,
        "strategy": "idle", "control_action": None, "orders_submitted": 0,
        "engine_process_running": False, "updated_at_ms": None,
        "last_control_id": None, "reason": "Hummingbot durum işareti bulunamadı",
    }
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            return fallback
        # Only expose the fixed, non-secret status contract to the dashboard.
        result = {key: value.get(key, fallback[key]) for key in fallback}
        # Keep the public status contract typed and non-secret even if an old
        # runtime marker contains arbitrary extra fields.
        result["orders_submitted"] = int(result["orders_submitted"] or 0)
        result["engine_process_running"] = bool(result["engine_process_running"])
        return result
    except (OSError, ValueError, TypeError):
        return fallback
