from dataclasses import dataclass
from decimal import Decimal, ROUND_DOWN
from enum import StrEnum
from typing import Iterable


ZERO = Decimal("0")


@dataclass(frozen=True)
class Level:
    price: Decimal
    amount: Decimal


@dataclass(frozen=True)
class FillEstimate:
    base_amount: Decimal
    quote_amount: Decimal
    vwap: Decimal
    complete: bool


@dataclass(frozen=True)
class Opportunity:
    pair: str
    buy_exchange: str
    sell_exchange: str
    base_amount: Decimal
    buy_vwap: Decimal
    sell_vwap: Decimal
    gross_profit_try: Decimal
    fees_try: Decimal
    safety_buffer_try: Decimal
    net_profit_try: Decimal
    net_profit_pct: Decimal
    executable: bool
    # Rates used by the calculation are kept with the snapshot so the
    # dashboard can explain exactly which fee tier produced the opportunity.
    buy_fee_rate: Decimal = ZERO
    sell_fee_rate: Decimal = ZERO


def buy_for_quote(asks: Iterable[Level], quote_budget: Decimal) -> FillEstimate:
    """Walk asks without exceeding a TRY budget."""
    remaining = quote_budget
    base = ZERO
    quote = ZERO
    for level in asks:
        if level.price <= ZERO or level.amount <= ZERO or remaining <= ZERO:
            continue
        take = min(level.amount, remaining / level.price)
        base += take
        spent = take * level.price
        quote += spent
        remaining -= spent
    return FillEstimate(base, quote, quote / base if base else ZERO, remaining <= Decimal("0.00000001"))


def sell_base(bids: Iterable[Level], base_amount: Decimal) -> FillEstimate:
    remaining = base_amount
    sold = ZERO
    quote = ZERO
    for level in bids:
        if level.price <= ZERO or level.amount <= ZERO or remaining <= ZERO:
            continue
        take = min(level.amount, remaining)
        sold += take
        quote += take * level.price
        remaining -= take
    return FillEstimate(sold, quote, quote / sold if sold else ZERO, remaining <= Decimal("0.00000001"))


def quantize_down(value: Decimal, step: Decimal) -> Decimal:
    if step <= ZERO:
        raise ValueError("step must be positive")
    return (value / step).to_integral_value(rounding=ROUND_DOWN) * step


def calculate_opportunity(
    *, pair: str, buy_exchange: str, sell_exchange: str,
    asks: Iterable[Level], bids: Iterable[Level], quote_budget: Decimal,
    amount_step: Decimal, buy_fee_rate: Decimal, sell_fee_rate: Decimal,
    safety_buffer_rate: Decimal, min_profit_rate: Decimal,
) -> Opportunity:
    buy = buy_for_quote(asks, quote_budget)
    amount = quantize_down(buy.base_amount, amount_step) if buy.base_amount else ZERO
    sell = sell_base(bids, amount)
    buy_cost = amount * buy.vwap
    sell_value = sell.quote_amount
    fees = buy_cost * buy_fee_rate + sell_value * sell_fee_rate
    buffer = buy_cost * safety_buffer_rate
    net = sell_value - buy_cost - fees - buffer
    pct = net / buy_cost if buy_cost else ZERO
    executable = buy.complete and sell.complete and amount > ZERO and pct >= min_profit_rate
    return Opportunity(pair, buy_exchange, sell_exchange, amount, buy.vwap, sell.vwap,
                       sell_value - buy_cost, fees, buffer, net, pct, executable,
                       buy_fee_rate, sell_fee_rate)


class ExecutionState(StrEnum):
    READY = "READY"
    SUBMITTING = "SUBMITTING"
    BALANCED_FILL = "BALANCED_FILL"
    PARTIAL_IMBALANCE = "PARTIAL_IMBALANCE"
    RECOVERY = "RECOVERY"
    FAILED_SAFE = "FAILED_SAFE"
    HALTED = "HALTED"


class InvalidTransition(ValueError):
    pass


_ALLOWED = {
    ExecutionState.READY: {ExecutionState.SUBMITTING, ExecutionState.HALTED},
    ExecutionState.SUBMITTING: {ExecutionState.BALANCED_FILL, ExecutionState.PARTIAL_IMBALANCE, ExecutionState.FAILED_SAFE},
    ExecutionState.PARTIAL_IMBALANCE: {ExecutionState.RECOVERY, ExecutionState.FAILED_SAFE},
    ExecutionState.RECOVERY: {ExecutionState.BALANCED_FILL, ExecutionState.FAILED_SAFE},
    ExecutionState.BALANCED_FILL: set(), ExecutionState.FAILED_SAFE: {ExecutionState.HALTED},
    ExecutionState.HALTED: set(),
}


def transition(current: ExecutionState, target: ExecutionState) -> ExecutionState:
    if target not in _ALLOWED[current]:
        raise InvalidTransition(f"{current} -> {target} is not allowed")
    return target


@dataclass(frozen=True)
class LiveQualification:
    api_connections_ok: bool
    observation_hours: Decimal
    paper_opportunities: int
    paper_trades: int
    failure_drills_ok: bool
    risk_limits_set: bool
    telemetry_blocked: bool
    # BTCTurk market BUY accepts quote TRY, while Hummingbot strategies express
    # size in base asset. Live mode must remain closed until that conversion,
    # balance validation and post-fill reconciliation are proven together.
    btcturk_market_buy_conversion_safe: bool = False

    def failures(self) -> list[str]:
        checks = [
            (self.api_connections_ok, "İki API bağlantısı doğrulanmadı"),
            (self.observation_hours >= 72, "72 saatlik gözlem tamamlanmadı"),
            (self.paper_opportunities >= 100, "100 paper fırsatı tamamlanmadı"),
            (self.paper_trades >= 20, "20 paper işlem tamamlanmadı"),
            (self.failure_drills_ok, "Kesinti ve tek-bacak testleri geçmedi"),
            (self.risk_limits_set, "Risk limitleri tanımlanmadı"),
            (self.telemetry_blocked, "Telemetri engeli doğrulanmadı"),
            (self.btcturk_market_buy_conversion_safe,
             "BTCTürk market alış TRY dönüşümü ve gerçekleşen miktar mutabakatı tamamlanmadı"),
        ]
        return [message for passed, message in checks if not passed]
