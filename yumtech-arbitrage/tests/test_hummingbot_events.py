import json
from pathlib import Path

from app.db import Database
from app.hummingbot_events import HummingbotPaperEventBridge
from app.security import passwords


def _database(path: Path) -> Database:
    db = Database(path / "events.db")
    with db.connect() as conn:
        conn.execute("INSERT INTO users(id,username,password_hash,is_admin,created_at) VALUES(1,'u',?,1,0)",
                     (passwords.hash("long-test-password"),))
        conn.execute("INSERT INTO user_settings(user_id) VALUES(1)")
    return db


def test_hummingbot_event_bridge_is_idempotent_and_keeps_recovery_leg(tmp_path: Path):
    events = tmp_path / "paper.jsonl"
    event = {
        "type": "completed", "intent_id": "hb-intent", "user_id": 1,
        "pair": "BTC-TRY", "buy_exchange": "btcturk_paper_trade",
        "sell_exchange": "binance_tr_paper_trade", "requested_base": "0.01",
        "expected_profit_try": "4", "max_recovery_loss_try": "100",
        "realized_profit_try": "2.5", "state": "BALANCED_FILL",
        "legs": [
            {"exchange": "btcturk_paper_trade", "side": "buy", "requested_base": "0.01",
             "filled_base": "0.01", "average_price": "100", "fee_try": "0.0015",
             "fee_rate": "0.0015", "fee_asset": "TRY", "fill_source": "hummingbot-paper",
             "status": "FILLED"},
            {"exchange": "binance_tr_paper_trade", "side": "sell", "requested_base": "0.01",
             "filled_base": "0.009", "average_price": "101", "fee_try": "0.00136",
             "fee_rate": "0.0015", "fee_asset": "TRY", "fill_source": "hummingbot-paper",
             "status": "PARTIAL"},
            {"exchange": "btcturk_paper_trade", "side": "sell", "requested_base": "0.001",
             "filled_base": "0.001", "average_price": "99", "fee_try": "0.00015",
             "fee_rate": "0.0015", "fee_asset": "TRY", "fill_source": "hummingbot-paper-recovery",
             "status": "FILLED"},
        ],
    }
    events.write_text(json.dumps(event) + "\n", encoding="utf-8")
    db = _database(tmp_path)
    bridge = HummingbotPaperEventBridge(db, events)
    assert bridge._consume() == 1
    assert bridge._consume() == 0
    saved = db.list_executions(1)[0]
    assert saved["state"] == "BALANCED_FILL"
    assert len(saved["legs"]) == 3
    assert saved["legs"][2]["fill_source"] == "hummingbot-paper-recovery"
