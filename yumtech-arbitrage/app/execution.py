import asyncio
import json
import time
import uuid
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from typing import Callable, Iterable, Protocol

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
    fee_rate: Decimal = Decimal("0")
    fee_asset: str = "TRY"
    fill_source: str = "paper"
    slippage_try: Decimal = Decimal("0")
    latency_ms: int = 0

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
    """Deterministic adapter reserved for unit tests and bootstrap fixtures."""

    def __init__(self, name: str, fee_rate: Decimal = Decimal("0.0015"),
                 fill_ratio: Decimal = Decimal("1"), recovery_slippage: Decimal = Decimal("0.001")):
        self.name = name
        self.fee_rate = fee_rate
        self.fill_ratio = fill_ratio
        self.recovery_slippage = recovery_slippage

    async def submit_limit(self, request: LegRequest) -> LegFill:
        started = time.monotonic()
        filled = request.base_amount * self.fill_ratio
        fee = filled * request.limit_price * self.fee_rate
        return LegFill(self.name, request.side, request.base_amount, filled, request.limit_price,
                       fee, f"paper-{uuid.uuid4().hex[:12]}", "FILLED" if filled == request.base_amount else "PARTIAL",
                       self.fee_rate, "TRY", "deterministic-paper", Decimal("0"),
                       int((time.monotonic() - started) * 1000))

    async def recover_market(self, request: LegRequest) -> LegFill:
        factor = Decimal("1") - self.recovery_slippage if request.side is Side.SELL else Decimal("1") + self.recovery_slippage
        price = request.limit_price * factor
        fee = request.base_amount * price * self.fee_rate
        return LegFill(self.name, request.side, request.base_amount, request.base_amount, price,
                       fee, f"paper-recovery-{uuid.uuid4().hex[:10]}", "FILLED", self.fee_rate,
                       "TRY", "deterministic-paper-recovery", abs(price - request.limit_price) * request.base_amount, 0)


class HummingbotPaperAdapter:
    """Order-book backed adapter with Hummingbot PaperTrade semantics.

    Hummingbot's paper connector waits five seconds before a market order is
    matched and walks the live order book rather than filling at a ticker price.
    The dashboard uses the same rules for its local journal: depth can run out,
    fills can be partial, fees are applied to the quote value, and a synthetic
    paper wallet is debited/credited for every fill. No API key or order route
    is available from this adapter.
    """

    def __init__(self, name: str, books, fee_provider: Callable[[], Decimal] | None = None,
                 *, execution_delay_seconds: float = 5.0, max_book_age_ms: int = 10_000,
                 initial_try: Decimal = Decimal("10_000"), initial_base_multiplier: Decimal = Decimal("10")):
        self.name = name
        self.books = books
        self.fee_provider = fee_provider or (lambda: Decimal("0.0015"))
        self.execution_delay_seconds = max(float(execution_delay_seconds), 0.0)
        self.max_book_age_ms = max(int(max_book_age_ms), 500)
        self.initial_try = max(Decimal(str(initial_try)), Decimal("0"))
        self.initial_base_multiplier = max(Decimal(str(initial_base_multiplier)), Decimal("1"))
        self.recovery_slippage = Decimal("0.001")
        self._balances: dict[str, Decimal] = {"TRY": self.initial_try}
        self._seeded_assets: set[str] = {"TRY"}
        self._lock = asyncio.Lock()

    def configure_profile(self, profile: dict) -> None:
        """Refresh fee and virtual-wallet parameters from the active profile."""
        try:
            multiplier = Decimal(str(profile.get("paper_initial_try_multiplier", "10")))
            if Decimal("1") <= multiplier <= Decimal("100"):
                self.initial_try = max(Decimal(str(profile.get(
                    "btcturk_budget_try" if self.name == "BTCTürk" else "binance_tr_budget_try", "1000"))) * multiplier,
                                       Decimal("0"))
                self.initial_base_multiplier = multiplier
                self._balances["TRY"] = max(self._balances.get("TRY", Decimal("0")), self.initial_try)
                self._seeded_assets.add("TRY")
        except (ArithmeticError, TypeError, ValueError):
            pass

    @property
    def fee_rate(self) -> Decimal:
        try:
            value = Decimal(str(self.fee_provider()))
            return value if Decimal("0") <= value <= Decimal("0.10") else Decimal("0.0015")
        except (ArithmeticError, TypeError, ValueError):
            return Decimal("0.0015")

    @property
    def exchange_key(self) -> str:
        return "btcturk" if self.name == "BTCTürk" else "binance_tr"

    def _base_asset(self, pair: str) -> str:
        return pair.split("/", 1)[0].split("-", 1)[0].upper()

    def _ensure_seed(self, asset: str, amount: Decimal) -> None:
        if asset in self._seeded_assets:
            return
        if asset == "TRY":
            seed = self.initial_try
        else:
            seed = max(amount * self.initial_base_multiplier, Decimal("0"))
        self._balances[asset] = max(self._balances.get(asset, Decimal("0")), seed)
        self._seeded_assets.add(asset)

    def balances(self) -> dict[str, Decimal]:
        return dict(self._balances)

    def _book(self, pair: str):
        return self.books.get(self.exchange_key, self._base_asset(pair), max_age_ms=self.max_book_age_ms)

    @staticmethod
    def _walk(levels: Iterable, amount: Decimal, side: Side, limit_price: Decimal | None = None):
        remaining = max(amount, Decimal("0"))
        filled = Decimal("0")
        quote = Decimal("0")
        best = None
        for level in levels:
            price = Decimal(str(level.price))
            available = Decimal(str(level.amount))
            if price <= 0 or available <= 0:
                continue
            if best is None:
                best = price
            if limit_price and ((side is Side.BUY and price > limit_price) or
                                (side is Side.SELL and price < limit_price)):
                break
            take = min(available, remaining)
            filled += take
            quote += take * price
            remaining -= take
            if remaining <= Decimal("0.00000000000001"):
                break
        average = quote / filled if filled else Decimal("0")
        return filled, quote, average, best or Decimal("0")

    async def submit_limit(self, request: LegRequest) -> LegFill:
        # The dashboard's limit request is an IOC-style, immediately crossing
        # quote. Waiting here mirrors PaperTradeExchange.TRADE_EXECUTION_DELAY.
        return await self._execute(request, limit_price=request.limit_price, recovery=False)

    async def recover_market(self, request: LegRequest) -> LegFill:
        return await self._execute(request, limit_price=None, recovery=True)

    async def _execute(self, request: LegRequest, *, limit_price: Decimal | None,
                       recovery: bool) -> LegFill:
        started = time.monotonic()
        if self.execution_delay_seconds:
            await asyncio.sleep(self.execution_delay_seconds)
        async with self._lock:
            base_asset = self._base_asset(request.pair)
            self._ensure_seed("TRY", request.base_amount * max(request.limit_price, Decimal("1")))
            if request.side is Side.SELL:
                self._ensure_seed(base_asset, request.base_amount)
            book = self._book(request.pair)
            levels = (book[0] if request.side is Side.BUY else book[1]) if book else []
            filled, quote, average, best = self._walk(levels, request.base_amount, request.side, limit_price)
            rate = self.fee_rate

            # Respect the synthetic wallet. A shortage is represented as a
            # partial fill instead of silently minting funds.
            if request.side is Side.BUY and filled:
                available_try = self._balances.get("TRY", Decimal("0"))
                affordable = available_try / (average * (Decimal("1") + rate)) if average else Decimal("0")
                if affordable < filled:
                    filled, quote, average, _ = self._walk(levels, affordable, request.side, limit_price)
            elif request.side is Side.SELL and filled:
                available_base = self._balances.get(base_asset, Decimal("0"))
                if available_base < filled:
                    filled, quote, average, _ = self._walk(levels, available_base, request.side, limit_price)

            fee = quote * rate
            if filled:
                if request.side is Side.BUY:
                    self._balances["TRY"] = self._balances.get("TRY", Decimal("0")) - quote - fee
                    self._balances[base_asset] = self._balances.get(base_asset, Decimal("0")) + filled
                else:
                    self._balances[base_asset] = self._balances.get(base_asset, Decimal("0")) - filled
                    self._balances["TRY"] = self._balances.get("TRY", Decimal("0")) + quote - fee

            slippage = Decimal("0")
            if filled and best:
                slippage = (average - best) * filled if request.side is Side.BUY else (best - average) * filled
            status = "FILLED" if filled == request.base_amount else ("PARTIAL" if filled > 0 else "NO_LIQUIDITY")
            source = "hummingbot-paper-recovery" if recovery else "hummingbot-paper"
            return LegFill(
                self.name, request.side, request.base_amount, filled, average, fee,
                f"hb-paper-{uuid.uuid4().hex[:12]}", status, rate, "TRY", source,
                max(slippage, Decimal("0")), int((time.monotonic() - started) * 1000),
            )


class ArbitrageExecutionEngine:
    def __init__(self, db: Database, adapters: dict[str, ExecutionAdapter]):
        self.db = db
        self.adapters = adapters
        self._lock = asyncio.Lock()

    def configure_profile(self, profile: dict) -> None:
        for adapter in self.adapters.values():
            configure = getattr(adapter, "configure_profile", None)
            if configure:
                configure(profile)

    @staticmethod
    def _leg_dict(leg: LegFill) -> dict:
        return {"filled_base": str(leg.filled_base), "average_price": str(leg.average_price),
                "fee_try": str(leg.fee_try), "external_order_id": leg.order_id, "status": leg.status,
                "fee_rate": str(leg.fee_rate), "fee_asset": leg.fee_asset,
                "fill_source": leg.fill_source, "slippage_try": str(leg.slippage_try),
                "latency_ms": leg.latency_ms}

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
                      "safety_buffer_try", "net_profit_try", "net_profit_pct", "buy_fee_rate",
                      "sell_fee_rate"}
    return Opportunity(**{key: Decimal(value) if key in decimal_fields else value
                          for key, value in item.items()})
