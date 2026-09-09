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
PAPER_CONFIG_VERSION = 1


class HummingbotControlError(ValueError):
    pass


def write_paper_config(path: Path, *, user_id: int, pairs: list[str], profile: dict,
                       fee_status: dict, min_profit_pct: str, event_path: str | None = None) -> dict[str, Any]:
    """Write a non-secret native Hummingbot PaperTrade configuration.

    Only the active user's id, public pair names, quote budgets and fee rates
    cross the dashboard/runtime volume. Exchange credentials never belong in
    this file because paper connectors use public order books.
    """
    if not isinstance(user_id, int) or user_id < 1:
        raise HummingbotControlError("Geçersiz kullanıcı")
    safe_pairs = sorted({str(pair).upper().replace("/", "-") for pair in pairs if pair})
    payload = {
        "version": PAPER_CONFIG_VERSION,
        "user_id": user_id,
        "trading_pairs": safe_pairs,
        "btcturk_budget_try": str(profile.get("btcturk_budget_try", "1000")),
        "binance_tr_budget_try": str(profile.get("binance_tr_budget_try", "1000")),
        "max_recovery_loss_try": str(profile.get("max_recovery_loss_try", "100")),
        "min_profit_pct": str(min_profit_pct),
        "fee_mode": str(profile.get("fee_mode", "taker")),
        "fee_source": str(profile.get("fee_source") or fee_status.get("mode") or "connector-default"),
        "btcturk_maker_fee_rate": str(profile.get("btcturk_maker_fee_rate", "0.0015")),
        "btcturk_taker_fee_rate": str(profile.get("btcturk_taker_fee_rate", "0.0015")),
        "binance_tr_maker_fee_rate": str(profile.get("binance_tr_maker_fee_rate", "0.0015")),
        "binance_tr_taker_fee_rate": str(profile.get("binance_tr_taker_fee_rate", "0.0015")),
        "paper_initial_try_multiplier": str(profile.get("paper_initial_try_multiplier", "10")),
        "event_path": event_path or "/home/hummingbot/yumtech-data/hummingbot-paper-events.jsonl",
        "written_at_ms": int(time.time() * 1000),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{secrets.token_hex(6)}.tmp")
    try:
        with temporary.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, separators=(",", ":"))
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
    return payload


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
        if (not isinstance(value.get("id"), str) or not value["id"]
                or int(value.get("issued_by", 0)) < 1):
            return None
        return {
            "version": CONTROL_VERSION,
            "id": value["id"],
            "action": value["action"],
            "mode": "test",
            "issued_by": int(value.get("issued_by", 0)),
            "issued_at_ms": int(value.get("issued_at_ms", 0)),
        }
    except (OSError, ValueError, TypeError, OverflowError):
        return None
