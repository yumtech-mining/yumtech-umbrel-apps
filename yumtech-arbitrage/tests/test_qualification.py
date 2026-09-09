from decimal import Decimal

from app.db import Database
from app.security import passwords


def database(tmp_path):
    db = Database(tmp_path / "qualification.db")
    with db.connect() as conn:
        conn.execute("INSERT INTO users(id,username,password_hash,is_admin,created_at) VALUES(1,'u',?,1,0)",
                     (passwords.hash("long-test-password"),))
        conn.execute("INSERT INTO user_settings(user_id) VALUES(1)")
    return db


def test_observation_and_paper_counters_reset_after_a_real_gap(tmp_path):
    db = database(tmp_path)
    start = 1_000_000
    db.record_observation(start, max_gap_ms=7_200_000)
    db.record_observation(start + 72 * 3_600_000, max_gap_ms=72 * 3_600_000)
    db.record_paper_opportunities(1, 12)
    db.record_paper_trade(1)
    metrics = db.qualification_metrics(1, now_ms=start + 72 * 3_600_000)
    assert metrics["observation_hours"] == "72.00"
    assert metrics["paper_opportunities"] == 12
    assert metrics["paper_trades"] == 1

    db.record_observation(start + 72 * 3_600_000 + 20 * 60_000)
    reset = db.qualification_metrics(1)
    assert reset["observation_hours"] == "0.00"
    assert reset["paper_opportunities"] == 0
    assert reset["paper_trades"] == 0


def test_execution_summary_is_dashboard_safe(tmp_path):
    db = database(tmp_path)
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO execution_intents(id,user_id,mode,pair,buy_exchange,sell_exchange,requested_base,"
            "max_recovery_loss_try,state,expected_profit_try,realized_profit_try,created_at,updated_at) "
            "VALUES('a',1,'paper','BTC/TRY','BTCTürk','Binance TR','0.01','10','BALANCED_FILL','5','4.20',1,1)"
        )
        conn.execute(
            "INSERT INTO execution_intents(id,user_id,mode,pair,buy_exchange,sell_exchange,requested_base,"
            "max_recovery_loss_try,state,expected_profit_try,realized_profit_try,created_at,updated_at) "
            "VALUES('b',1,'paper','ETH/TRY','Binance TR','BTCTürk','1','10','FAILED_SAFE','5','-2.10',2,2)"
        )
    summary = db.execution_summary(1)
    assert summary["total"] == 2
    assert summary["balanced"] == 1
    assert summary["recovery_events"] == 1
    assert summary["profitable"] == 1
    assert Decimal(summary["realized_profit_try"]) == Decimal("2.10")
    assert Decimal(summary["realized_loss_try"]) == Decimal("-2.10")

