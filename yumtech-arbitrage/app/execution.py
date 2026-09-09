import asyncio
import json
import uuid
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from typing import Protocol

from .db import Database
from .domain import ExecutionState, Opportunity, transition


class Side(StrEnum):
    BUY = "buy"
    SELL = "sell"


@dataclass(frozen=True)
class LegRequest:
    exchange: str
    side: Side
    pair: str
    base_amount: Decimal
    limit_price: Decimal


@dataclass(frozen=True)
class LegFill:
    exchange: str
    side: Side
    requested_base: Decimal
    filled_base: Decimal
    average_price: Decimal
    fee_try: Decimal
    order_id: str
    status: str

    @property
    def quote_value(self) -> Decimal:
        return self.filled_base * self.average_price


@dataclass(frozen=True)
class ExecutionResult:
    intent_id: str
    state: ExecutionState
    buy_fill: LegFill
    sell_fill: LegFill
    recovery_fill: LegFill | None
    realized_profit_try: Decimal
    exposure_base: Decimal


class ExecutionAdapter(Protocol):
    async def submit_limit(self, request: LegRequest) -> LegFill: ...
    async def recover_market(self, request: LegRequest) -> LegFill: ...


class PaperAdapter:
    """Deterministic adapter used for tests and the default dashboard mode."""

    def __init__(self, name: str, fee_rate: Decimal = Decimal("0.0015"),
                 fill_ratio: Decimal = Decimal("1"), recovery_slippage: Decimal = Decimal("0.001")):
        self.name = name
        self.fee_rate = fee_rate
        self.fill_ratio = fill_ratio
        self.recovery_slippage = recovery_slippage

    async def submit_limit(self, request: LegRequest) -> LegFill:
        filled = request.base_amount * self.fill_ratio
        fee = filled * request.limit_price * self.fee_rate
        return LegFill(self.name, request.side, request.base_amount, filled, request.limit_price,
                       fee, f"paper-{uuid.uuid4().hex[:12]}", "FILLED" if filled == request.base_amount else "PARTIAL")

    async def recover_market(self, request: LegRequest) -> LegFill:
        factor = Decimal("1") - self.recovery_slippage if request.side is Side.SELL else Decimal("1") + self.recovery_slippage
        price = request.limit_price * factor
        fee = request.base_amount * price * self.fee_rate
        return LegFill(self.name, request.side, request.base_amount, request.base_amount, price,
                       fee, f"paper-recovery-{uuid.uuid4().hex[:10]}", "FILLED")


class ArbitrageExecutionEngine:
    def __init__(self, db: Database, adapters: dict[str, ExecutionAdapter]):
        self.db = db
        self.adapters = adapters
        self._lock = asyncio.Lock()

    @staticmethod
    def _leg_dict(leg: LegFill) -> dict:
        return {"filled_base": str(leg.filled_base), "average_price": str(leg.average_price),
                "fee_try": str(leg.fee_try), "external_order_id": leg.order_id, "status": leg.status}

    async def execute_paper(self, user_id: int, opportunity: Opportunity,
                            max_recovery_loss_try: Decimal) -> ExecutionResult:
        if not opportunity.executable:
            raise ValueError("Opportunity is not executable")
        if max_recovery_loss_try <= 0:
            raise ValueError("Recovery loss limit must be positive")
        async with self._lock:
            return await self._execute_locked(user_id, opportunity, max_recovery_loss_try)

    async def _execute_locked(self, user_id: int, opportunity: Opportunity,
                              max_recovery_loss_try: Decimal) -> ExecutionResult:
        intent_id = uuid.uuid4().hex
        buy_request = LegRequest(opportunity.buy_exchange, Side.BUY, opportunity.pair,
                                 opportunity.base_amount, opportunity.buy_vwap)
        sell_request = LegRequest(opportunity.sell_exchange, Side.SELL, opportunity.pair,
                                  opportunity.base_amount, opportunity.sell_vwap)
        self.db.create_execution_intent(
            {"id": intent_id, "user_id": user_id, "mode": "paper", "pair": opportunity.pair,
             "buy_exchange": opportunity.buy_exchange, "sell_exchange": opportunity.sell_exchange,
             "requested_base": str(opportunity.base_amount),
             "max_recovery_loss_try": str(max_recovery_loss_try), "state": ExecutionState.READY.value,
             "expected_profit_try": str(opportunity.net_profit_try)},
            [{"exchange": buy_request.exchange, "side": buy_request.side.value,
              "requested_base": str(buy_request.base_amount), "requested_price": str(buy_request.limit_price)},
             {"exchange": sell_request.exchange, "side": sell_request.side.value,
              "requested_base": str(sell_request.base_amount), "requested_price": str(sell_request.limit_price)}],
        )
        state = transition(ExecutionState.READY, ExecutionState.SUBMITTING)
        self.db.update_execution_state(intent_id, state.value)
        buy_result, sell_result = await asyncio.gather(
            self.adapters[buy_request.exchange].submit_limit(buy_request),
            self.adapters[sell_request.exchange].submit_limit(sell_request),
            return_exceptions=True,
        )
        buy_fill = self._coerce_result(buy_request, buy_result)
        sell_fill = self._coerce_result(sell_request, sell_result)
        self.db.update_execution_leg(intent_id, buy_request.exchange, Side.BUY.value, self._leg_dict(buy_fill))
        self.db.update_execution_leg(intent_id, sell_request.exchange, Side.SELL.value, self._leg_dict(sell_fill))

        exposure = buy_fill.filled_base - sell_fill.filled_base
        recovery_fill = None
        if exposure == 0 and buy_fill.filled_base == opportunity.base_amount:
            state = transition(state, ExecutionState.BALANCED_FILL)
        elif exposure != 0:
            state = transition(state, ExecutionState.PARTIAL_IMBALANCE)
            self.db.update_execution_state(intent_id, state.value,
                                           json.dumps({"exposure_base": str(exposure)}))
            state = transition(state, ExecutionState.RECOVERY)
            self.db.update_execution_state(intent_id, state.value)
            recovery_fill = await self._recover(intent_id, opportunity, exposure, max_recovery_loss_try)
            self.db.add_execution_leg(intent_id, {
                "exchange": recovery_fill.exchange, "side": recovery_fill.side.value,
                "requested_base": str(recovery_fill.requested_base),
                "requested_price": str(reference_price(opportunity, recovery_fill.side)),
                **self._leg_dict(recovery_fill),
            })
            exposure += recovery_fill.filled_base if recovery_fill.side is Side.BUY else -recovery_fill.filled_base
            state = transition(state, ExecutionState.BALANCED_FILL) if exposure == 0 else transition(state, ExecutionState.FAILED_SAFE)
        else:
            state = transition(state, ExecutionState.FAILED_SAFE)

        profit = self._realized_profit(buy_fill, sell_fill, recovery_fill)
        detail = json.dumps({"exposure_base": str(exposure), "recovered": recovery_fill is not None})
        self.db.update_execution_state(intent_id, state.value, detail, str(profit),
                                       None if state is ExecutionState.BALANCED_FILL else "Unbalanced execution")
        return ExecutionResult(intent_id, state, buy_fill, sell_fill, recovery_fill, profit, exposure)

    @staticmethod
    def _coerce_result(request: LegRequest, result) -> LegFill:
        if isinstance(result, LegFill):
            return result
        return LegFill(request.exchange, request.side, request.base_amount, Decimal("0"),
                       request.limit_price, Decimal("0"), "", f"FAILED:{type(result).__name__}")

    async def _recover(self, intent_id: str, opportunity: Opportunity, exposure: Decimal,
                       max_loss: Decimal) -> LegFill:
        side = Side.SELL if exposure > 0 else Side.BUY
        amount = abs(exposure)
        exchange = opportunity.buy_exchange if side is Side.SELL else opportunity.sell_exchange
        reference = opportunity.buy_vwap if side is Side.SELL else opportunity.sell_vwap
        adapter = self.adapters[exchange]
        slippage = getattr(adapter, "recovery_slippage", Decimal("0.01"))
        worst_case_loss = amount * reference * (slippage + getattr(adapter, "fee_rate", Decimal("0.002")))
        if worst_case_loss > max_loss:
            self.db.update_execution_state(intent_id, ExecutionState.FAILED_SAFE.value,
                                           json.dumps({"estimated_recovery_loss_try": str(worst_case_loss)}),
                                           error="Recovery loss limit exceeded")
            raise RecoveryLimitExceeded(str(worst_case_loss))
        return await adapter.recover_market(LegRequest(exchange, side, opportunity.pair, amount, reference))

    @staticmethod
    def _realized_profit(buy: LegFill, sell: LegFill, recovery: LegFill | None) -> Decimal:
        cash = sell.quote_value - buy.quote_value - buy.fee_try - sell.fee_try
        if recovery:
            cash += recovery.quote_value if recovery.side is Side.SELL else -recovery.quote_value
            cash -= recovery.fee_try
        return cash


class RecoveryLimitExceeded(RuntimeError):
    pass


def reference_price(opportunity: Opportunity, side: Side) -> Decimal:
    return opportunity.buy_vwap if side is Side.SELL else opportunity.sell_vwap


def opportunity_from_mapping(item: dict) -> Opportunity:
    decimal_fields = {"base_amount", "buy_vwap", "sell_vwap", "gross_profit_try", "fees_try",
                      "safety_buffer_try", "net_profit_try", "net_profit_pct"}
    return Opportunity(**{key: Decimal(value) if key in decimal_fields else value
                          for key, value in item.items()})
