#!/usr/bin/env python3
"""Fail-closed supervisor for the native Hummingbot PaperTrade engine.

The dashboard can only write four test-mode commands to the shared volume. On
``start_test`` this process builds a paper-only Hummingbot configuration and
starts the pinned v2.16 engine with the YUMTECH strategy. No connector API keys
are copied into the generated files; paper connectors consume public order
books and use synthetic balances.
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import yaml


CONTROL_VERSION = 1
PAPER_CONFIG_VERSION = 1
ALLOWED_ACTIONS = {"start_test", "stop", "refresh", "emergency_stop"}
PAPER_PASSWORD = "yumtech-paper-local"
running = True
engine: subprocess.Popen | None = None
engine_name = "yumtech-paper"


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
        issued_by = int(value.get("issued_by", 0))
        return value if isinstance(command_id, str) and command_id and issued_by > 0 else None
    except (OSError, ValueError, TypeError):
        return None


def _read_paper_config(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(value, dict) or value.get("version") != PAPER_CONFIG_VERSION:
            return {}
        value["trading_pairs"] = sorted({str(p).upper().replace("/", "-")
                                          for p in value.get("trading_pairs", []) if p})
        return value
    except (OSError, ValueError, TypeError):
        return {}


def _write(path: Path, *, state: str, action: str | None, command_id: str | None,
           reason: str, process_running: bool = False, orders_submitted: int = 0) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "state": state,
        "mode": "test",
        "engine_version": os.environ.get("YUMTECH_ENGINE_VERSION", "v2.16.0"),
        "telemetry_disabled": True,
        "live_orders_enabled": False,
        "strategy": "yumtech_paper_arbitrage" if process_running else "idle",
        "control_action": action,
        "orders_submitted": int(orders_submitted),
        "engine_process_running": bool(process_running),
        "updated_at_ms": int(time.time() * 1000),
        "last_control_id": command_id,
        "reason": reason,
    }
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(json.dumps(payload, separators=(",", ":")) + "\n", encoding="utf-8")
    os.chmod(temporary, 0o600)
    os.replace(temporary, path)


def _write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    os.chmod(temporary, 0o600)
    os.replace(temporary, path)


def _ensure_password(conf_dir: Path) -> None:
    """Create the local paper keystore marker without logging the password."""
    marker = conf_dir / ".password_verification"
    marker.unlink(missing_ok=True)
    code = (
        "from hummingbot.client.config.config_crypt import "
        "ETHKeyFileSecretManger, store_password_verification; "
        f"store_password_verification(ETHKeyFileSecretManger({PAPER_PASSWORD!r}))"
    )
    subprocess.run([sys.executable, "-c", code], cwd="/home/hummingbot", check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def _prepare_configs(config: dict, conf_dir: Path, data_dir: Path) -> Path:
    conf_dir.mkdir(parents=True, exist_ok=True)
    # The conf directory is a bind mount on Umbrel; Hummingbot expects this
    # child directory during Security.login even before connector secrets exist.
    (conf_dir / "connectors").mkdir(parents=True, exist_ok=True)
    scripts_dir = conf_dir / "scripts"
    scripts_dir.mkdir(parents=True, exist_ok=True)
    pairs = config.get("trading_pairs", [])
    budget_bt = float(config.get("btcturk_budget_try", "1000"))
    budget_bn = float(config.get("binance_tr_budget_try", "1000"))
    multiplier = max(float(config.get("paper_initial_try_multiplier", "10")), 1.0)
    balances = {"TRY": max(budget_bt, budget_bn) * multiplier}
    for pair in pairs:
        base = pair.split("-", 1)[0].upper()
        balances[base] = max(balances.get(base, 0.0), 100.0)

    client = {}
    client_path = conf_dir / "conf_client.yml"
    if client_path.exists():
        try:
            client = yaml.safe_load(client_path.read_text(encoding="utf-8")) or {}
        except (OSError, yaml.YAMLError):
            client = {}
    client["anonymized_metrics_mode"] = "anonymized_metrics_disabled"
    client["send_error_logs"] = False
    client["fetch_pairs_from_all_exchanges"] = False
    client["kill_switch_mode"] = "kill_switch_disabled"
    client["paper_trade"] = {
        "paper_trade_exchanges": ["btcturk", "binance_tr"],
        "paper_trade_account_balance": balances,
    }
    _write_json(client_path, client)

    strategy = {
        "script_file_name": "yumtech_paper_arbitrage.py",
        "controllers_config": [],
        "trading_pairs": pairs,
        "btcturk_budget_try": str(config.get("btcturk_budget_try", "1000")),
        "binance_tr_budget_try": str(config.get("binance_tr_budget_try", "1000")),
        "min_profitability": str(float(config.get("min_profit_pct", "0.40")) / 100),
        "safety_buffer_rate": "0.001",
        "btcturk_maker_fee_rate": str(config.get("btcturk_maker_fee_rate", "0.0015")),
        "btcturk_taker_fee_rate": str(config.get("btcturk_taker_fee_rate", "0.0015")),
        "binance_tr_maker_fee_rate": str(config.get("binance_tr_maker_fee_rate", "0.0015")),
        "binance_tr_taker_fee_rate": str(config.get("binance_tr_taker_fee_rate", "0.0015")),
        "fee_mode": str(config.get("fee_mode", "taker")),
        "max_recovery_loss_try": str(config.get("max_recovery_loss_try", "100")),
        "cooldown_seconds": 30,
        "event_path": str(config.get("event_path", data_dir / "hummingbot-paper-events.jsonl")),
        "user_id": int(config.get("user_id", 1)),
    }
    strategy_path = scripts_dir / "yumtech_paper_arbitrage.yml"
    _write_json(strategy_path, strategy)

    # Hummingbot's fee override file stores human percentages (0.15 means
    # 0.15%), while the strategy and dashboard store decimal rates.
    fee_overrides = {
        "btcturk_maker_percent_fee": float(config.get("btcturk_maker_fee_rate", "0.0015")) * 100,
        "btcturk_taker_percent_fee": float(config.get("btcturk_taker_fee_rate", "0.0015")) * 100,
        "binance_tr_maker_percent_fee": float(config.get("binance_tr_maker_fee_rate", "0.0015")) * 100,
        "binance_tr_taker_percent_fee": float(config.get("binance_tr_taker_fee_rate", "0.0015")) * 100,
        "binance_tr_buy_percent_fee_deducted_from_returns": True,
    }
    _write_json(conf_dir / "conf_fee_overrides.yml", fee_overrides)
    _ensure_password(conf_dir)
    return strategy_path


def _terminate_engine() -> None:
    global engine
    if engine is None:
        return
    if engine.poll() is None:
        engine.terminate()
        try:
            engine.wait(timeout=15)
        except subprocess.TimeoutExpired:
            engine.kill()
            engine.wait(timeout=5)
    engine = None


def _orders_submitted(events_path: Path) -> int:
    try:
        return sum(2 for line in events_path.read_text(encoding="utf-8").splitlines()
                   if line and json.loads(line).get("type") == "submitted")
    except (OSError, ValueError, TypeError):
        return 0


def _start_engine(config: dict, conf_dir: Path, data_dir: Path) -> bool:
    global engine
    if not config.get("trading_pairs"):
        return False
    strategy_path = _prepare_configs(config, conf_dir, data_dir)
    log_path = Path("/home/hummingbot/logs/yumtech-paper-engine.log")
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_handle = log_path.open("a", encoding="utf-8")
    env = dict(os.environ)
    env.pop("CONFIG_PASSWORD", None)
    env["HBOT_PASSWORD"] = PAPER_PASSWORD
    env["YUMTECH_LIVE_TRADING_ENABLED"] = "false"
    env["YUMTECH_TELEMETRY_DISABLED"] = "true"
    try:
        engine = subprocess.Popen(
            [sys.executable, "-m", "hummingbot.cli.engine", "--name", engine_name,
             "--script-config", strategy_path.name],
            cwd="/home/hummingbot", env=env, stdout=log_handle, stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    finally:
        log_handle.close()
    return engine.poll() is None


def _safe_start_engine(config: dict, conf_dir: Path, data_dir: Path) -> bool | None:
    """Return ``None`` when config/engine startup raises instead of killing the supervisor."""
    try:
        return _start_engine(config, conf_dir, data_dir)
    except Exception:
        return None


def _try_start_waiting(status_path: Path, paper_config_path: Path, conf_dir: Path,
                       data_dir: Path, events_path: Path, command_id: str | None) -> bool | None:
    """Start a previously requested test once the scanner publishes pairs.

    Umbrel installations can boot while a public exchange is rate-limited or
    its websocket is still warming up. That is a normal *waiting* state, not a
    broken strategy; retrying here avoids asking the user to click Start again.
    """
    global engine
    config = _read_paper_config(paper_config_path)
    if engine is not None:
        return False
    if not config.get("trading_pairs"):
        return False
    result = _safe_start_engine(config, conf_dir, data_dir)
    if result is True:
        _write(status_path, state="running", action="start_test", command_id=command_id,
               reason="Hummingbot v2.16 PaperTrade stratejisi çalışıyor; canlı emir kapalı",
               process_running=True, orders_submitted=_orders_submitted(events_path))
        return True
    return None


def main() -> None:
    global engine
    status_path = Path(os.environ.get("YUMTECH_STATUS_FILE", "/home/hummingbot/yumtech-data/hummingbot-status.json"))
    control_path = Path(os.environ.get("YUMTECH_CONTROL_FILE", "/home/hummingbot/yumtech-data/hummingbot-control.json"))
    paper_config_path = Path(os.environ.get("YUMTECH_PAPER_CONFIG_FILE", "/home/hummingbot/yumtech-data/hummingbot-paper-config.json"))
    data_dir = paper_config_path.parent
    conf_dir = Path("/home/hummingbot/conf")
    events_path = data_dir / "hummingbot-paper-events.jsonl"
    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)
    last_id = None
    state = "idle"
    _write(status_path, state=state, action=None, command_id=None,
           reason="Hummingbot PaperTrade host hazır; Test motorunu başlatabilirsiniz")
    while running:
        command = _read(control_path)
        if command and command["id"] != last_id:
            last_id = command["id"]
            action = command["action"]
            if action == "start_test":
                _terminate_engine()
                config = _read_paper_config(paper_config_path)
                if not config.get("trading_pairs"):
                    state = "waiting"
                    _write(status_path, state=state, action=action, command_id=last_id,
                           reason="Public ortak TRY pariteleri bekleniyor; veri gelince PaperTrade otomatik başlayacak")
                elif _safe_start_engine(config, conf_dir, data_dir) is True:
                    state = "running"
                    _write(status_path, state=state, action=action, command_id=last_id,
                           reason="Hummingbot v2.16 PaperTrade stratejisi çalışıyor; canlı emir kapalı",
                           process_running=True, orders_submitted=_orders_submitted(events_path))
                else:
                    state = "error"
                    _write(status_path, state=state, action=action, command_id=last_id,
                           reason="Paper stratejisi başlatılamadı; Hummingbot logu kontrol edilmeli")
            elif action in {"stop", "emergency_stop"}:
                _terminate_engine()
                state = "emergency-stopped" if action == "emergency_stop" else "stopped"
                _write(status_path, state=state, action=action, command_id=last_id,
                       reason="Acil durdurma uygulandı; yeni paper emri gönderilmiyor" if action == "emergency_stop"
                       else "Hummingbot PaperTrade durduruldu", orders_submitted=_orders_submitted(events_path))
            else:
                state = "running" if engine is not None and engine.poll() is None else "idle"
                _write(status_path, state=state, action=action, command_id=last_id,
                       reason="Hummingbot PaperTrade durumu yenilendi", process_running=state == "running",
                       orders_submitted=_orders_submitted(events_path))

        if state == "waiting":
            waiting_result = _try_start_waiting(status_path, paper_config_path, conf_dir, data_dir,
                                                events_path, last_id)
            if waiting_result is True:
                state = "running"
            elif waiting_result is None:
                state = "error"
                _write(status_path, state=state, action="engine-exited", command_id=last_id,
                       reason="Paper stratejisi başlatılamadı; Hummingbot logu kontrol edilmeli",
                       orders_submitted=_orders_submitted(events_path))
        if engine is not None and engine.poll() is not None and state == "running":
            state = "error"
            _write(status_path, state=state, action="engine-exited", command_id=last_id,
                   reason="Paper motoru beklenmedik şekilde durdu; Hummingbot logu incelenmeli",
                   orders_submitted=_orders_submitted(events_path))
            engine = None
        elif state == "running":
            _write(status_path, state=state, action="heartbeat", command_id=last_id,
                   reason="Hummingbot v2.16 PaperTrade stratejisi çalışıyor; canlı emir kapalı",
                   process_running=True, orders_submitted=_orders_submitted(events_path))
        time.sleep(0.5)

    _terminate_engine()
    _write(status_path, state="stopped", action="shutdown", command_id=last_id,
           reason="Hummingbot PaperTrade hostu durduruldu", orders_submitted=_orders_submitted(events_path))


if __name__ == "__main__":
    main()
