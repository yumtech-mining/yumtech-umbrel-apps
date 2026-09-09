from decimal import Decimal

import pytest

from app.db import Database
from app.domain import ExecutionState, Opportunity
from app.coordinator import PaperCoordinator, apply_quote_budgets
from app.execution import (ArbitrageExecutionEngine, HummingbotPaperAdapter,
                           LegRequest, PaperAdapter, RecoveryLimitExceeded, Side)
from app.market_stream import OrderBookStore
from app.security import passwords


def opportunity() -> Opportunity:
    return Opportunity(
        pair="BTC/TRY", buy_exchange="BTCTürk", sell_exchange="Binance TR",
        base_amount=Decimal("0.01"), buy_vwap=Decimal("1000000"), sell_vwap=Decimal("1010000"),
        gross_profit_try=Decimal("100"), fees_try=Decimal("30.15"), safety_buffer_try=Decimal("10"),
        net_profit_try=Decimal("59.85"), net_profit_pct=Decimal("0.005985"), executable=True,
    )


def test_quote_budgets_cap_both_legs_and_preserve_net_rate():
    capped = apply_quote_budgets(opportunity(), {
        "btcturk_budget_try": "1000", "binance_tr_budget_try": "1000"})
    assert capped is not None
    assert capped.base_amount * capped.buy_vwap <= Decimal("1000")
    assert capped.base_amount * capped.sell_vwap <= Decimal("1000")
    assert capped.net_profit_try < opportunity().net_profit_try
    assert capped.net_profit_pct == opportunity().net_profit_pct


def database(tmp_path) -> Database:
    db = Database(tmp_path / "engine.db")
    with db.connect() as conn:
        conn.execute("INSERT INTO users(id,username,password_hash,is_admin,created_at) VALUES(1,'u',?,1,0)",
                     (passwords.hash("long-test-password"),))
        conn.execute("INSERT INTO user_settings(user_id) VALUES(1)")
    return db


@pytest.mark.anyio
async def test_balanced_paper_execution_is_journaled(tmp_path):
    db = database(tmp_path)
    engine = ArbitrageExecutionEngine(db, {
        "BTCTürk": PaperAdapter("BTCTürk"), "Binance TR": PaperAdapter("Binance TR")})
    result = await engine.execute_paper(1, opportunity(), Decimal("100"))
    assert result.state is ExecutionState.BALANCED_FILL
    assert result.exposure_base == 0
    saved = db.list_executions(1)[0]
    assert saved["state"] == "BALANCED_FILL"
    assert len(saved["legs"]) == 2


@pytest.mark.anyio
async def test_hummingbot_paper_adapter_walks_depth_applies_fee_and_updates_wallet():
    books = OrderBookStore()
    books.replace("btcturk", "BTC", [(100, 0.01), (101, 0.02)], [(99, 1)])
    adapter = HummingbotPaperAdapter("BTCTürk", books, execution_delay_seconds=0,
                                    initial_try=Decimal("1000"))
    fill = await adapter.submit_limit(LegRequest("BTCTürk", Side.BUY, "BTC/TRY",
                                                  Decimal("0.02"), Decimal("101")))
    assert fill.status == "FILLED"
    assert fill.filled_base == Decimal("0.02")
    assert fill.average_price == Decimal("100.5")
    assert fill.fee_rate == Decimal("0.0015")
    assert fill.fee_try == Decimal("0.003015")
    assert adapter.balances()["TRY"] == Decimal("1000") - Decimal("2.01") * Decimal("1.0015")
    assert adapter.balances()["BTC"] == Decimal("0.02")


@pytest.mark.anyio
async def test_hummingbot_paper_adapter_rejects_missing_or_stale_depth():
    books = OrderBookStore()
    adapter = HummingbotPaperAdapter("Binance TR", books, execution_delay_seconds=0)
    fill = await adapter.submit_limit(LegRequest("Binance TR", Side.BUY, "ETH/TRY",
                                                  Decimal("1"), Decimal("100")))
    assert fill.status == "NO_LIQUIDITY"
    assert fill.filled_base == Decimal("0")


@pytest.mark.anyio
async def test_single_leg_partial_fill_is_recovered_and_recorded(tmp_path):
    db = database(tmp_path)
    engine = ArbitrageExecutionEngine(db, {
        "BTCTürk": PaperAdapter("BTCTürk", fill_ratio=Decimal("1")),
        "Binance TR": PaperAdapter("Binance TR", fill_ratio=Decimal("0.5")),
    })
    result = await engine.execute_paper(1, opportunity(), Decimal("100"))
    assert result.state is ExecutionState.BALANCED_FILL
    assert result.recovery_fill is not None
    assert result.recovery_fill.side.value == "sell"
    assert result.exposure_base == 0
    assert len(db.list_executions(1)[0]["legs"]) == 3


@pytest.mark.anyio
async def test_recovery_limit_fails_closed_before_market_recovery(tmp_path):
    db = database(tmp_path)
    engine = ArbitrageExecutionEngine(db, {
        "BTCTürk": PaperAdapter("BTCTürk", fill_ratio=Decimal("1"), recovery_slippage=Decimal("0.10")),
        "Binance TR": PaperAdapter("Binance TR", fill_ratio=Decimal("0")),
    })
    with pytest.raises(RecoveryLimitExceeded):
        await engine.execute_paper(1, opportunity(), Decimal("1"))
    saved = db.list_executions(1)[0]
    assert saved["state"] == "FAILED_SAFE"
    assert saved["error"] == "Recovery loss limit exceeded"


def test_startup_reconciliation_halts_unknown_inflight_intent(tmp_path):
    db = database(tmp_path)
    db.create_execution_intent(
        {"id": "crash-intent", "user_id": 1, "mode": "paper", "pair": "BTC/TRY",
         "buy_exchange": "BTCTürk", "sell_exchange": "Binance TR", "requested_base": "0.01",
         "max_recovery_loss_try": "100", "state": "SUBMITTING", "expected_profit_try": "10"},
        [{"exchange": "BTCTürk", "side": "buy", "requested_base": "0.01", "requested_price": "1"},
         {"exchange": "Binance TR", "side": "sell", "requested_base": "0.01", "requested_price": "2"}],
    )
    assert db.halt_incomplete_executions() == 1
    saved = db.list_executions(1)[0]
    assert saved["state"] == "HALTED"
    assert "manual reconciliation" in saved["error"]


@pytest.mark.anyio
async def test_coordinator_uses_live_snapshot_once_per_cooldown(tmp_path):
    db = database(tmp_path)
    with db.connect() as conn:
        conn.execute("UPDATE user_settings SET active=1,max_trade_try='20000' WHERE user_id=1")
    item = {key: str(value) if isinstance(value, Decimal) else value
            for key, value in opportunity().__dict__.items()}
    scanner = type("Scanner", (), {"opportunities": [item], "snapshot_id": 1})()
    engine = ArbitrageExecutionEngine(db, {
        "BTCTürk": PaperAdapter("BTCTürk"), "Binance TR": PaperAdapter("Binance TR")})
    coordinator = PaperCoordinator(db, scanner, engine, cooldown_seconds=60)
    await coordinator.process_snapshot()
    await coordinator.process_snapshot()
    assert coordinator.last_execution_id is not None
    assert len(db.list_executions(1)) == 1
