from decimal import Decimal

import pytest

from app.domain import (ExecutionState, InvalidTransition, Level,
                        LiveQualification, calculate_opportunity, transition)


def test_depth_fees_rounding_and_profit_are_decimal():
    result = calculate_opportunity(
        pair="BTC/TRY", buy_exchange="A", sell_exchange="B",
        asks=[Level(Decimal("100"), Decimal("5")), Level(Decimal("101"), Decimal("10"))],
        bids=[Level(Decimal("103"), Decimal("4")), Level(Decimal("102"), Decimal("10"))],
        quote_budget=Decimal("1000"), amount_step=Decimal("0.01"),
        buy_fee_rate=Decimal("0.001"), sell_fee_rate=Decimal("0.001"),
        safety_buffer_rate=Decimal("0.001"), min_profit_rate=Decimal("0.005"))
    assert result.base_amount == Decimal("9.95")
    assert result.sell_vwap > result.buy_vwap
    assert result.net_profit_try > 0
    assert result.executable


def test_incomplete_depth_is_never_executable():
    result = calculate_opportunity(
        pair="X/TRY", buy_exchange="A", sell_exchange="B",
        asks=[Level(Decimal("10"), Decimal("1"))], bids=[Level(Decimal("20"), Decimal("1"))],
        quote_budget=Decimal("100"), amount_step=Decimal("0.1"),
        buy_fee_rate=Decimal("0"), sell_fee_rate=Decimal("0"),
        safety_buffer_rate=Decimal("0"), min_profit_rate=Decimal("0"))
    assert not result.executable


def test_recovery_state_machine_rejects_unsafe_shortcut():
    assert transition(ExecutionState.READY, ExecutionState.SUBMITTING) == ExecutionState.SUBMITTING
    assert transition(ExecutionState.SUBMITTING, ExecutionState.PARTIAL_IMBALANCE) == ExecutionState.PARTIAL_IMBALANCE
    assert transition(ExecutionState.PARTIAL_IMBALANCE, ExecutionState.RECOVERY) == ExecutionState.RECOVERY
    with pytest.raises(InvalidTransition):
        transition(ExecutionState.READY, ExecutionState.BALANCED_FILL)


def test_live_qualification_reports_every_missing_gate():
    q = LiveQualification(False, Decimal("10"), 4, 0, False, False, False)
    assert len(q.failures()) == 7
