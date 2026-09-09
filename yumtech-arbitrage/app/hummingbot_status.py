import json
from pathlib import Path


def read_status(path: Path) -> dict:
    """Read the non-secret shared Hummingbot status marker, failing closed."""
    fallback = {
        "state": "not-installed", "mode": "test", "engine_version": "v2.16.0",
        "telemetry_disabled": True, "live_orders_enabled": False,
    }
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            return fallback
        # Only expose the fixed, non-secret status contract to the dashboard.
        return {key: value.get(key, fallback[key]) for key in fallback}
    except (OSError, ValueError, TypeError):
        return fallback
