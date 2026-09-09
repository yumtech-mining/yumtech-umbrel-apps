import asyncio
import json
import time
from dataclasses import replace
from decimal import Decimal
from decimal import ROUND_DOWN

from .db import Database
from .domain import Opportunity
from .execution import ArbitrageExecutionEngine, RecoveryLimitExceeded, opportunity_from_mapping


def _quote_budget(profile: dict, exchange: str) -> Decimal:
    """Return the per-exchange TRY cap stored for a user profile.

    The dashboard stores quote currency (TRY) because that is how a person
    naturally budgets a trade. Hummingbot connectors ultimately receive base
    asset size; ``apply_quote_budgets`` performs the deterministic conversion
    against the scanner VWAP before a paper intent is written.
    """

    field = "btcturk_budget_try" if exchange == "BTCTürk" else "binance_tr_budget_try"
    try:
        value = Decimal(str(profile.get(field, "0")))
    except (ArithmeticError, TypeError, ValueError):
        return Decimal("0")
    return max(value, Decimal("0"))


def apply_quote_budgets(opportunity: Opportunity, profile: dict) -> Opportunity | None:
    """Cap both legs to a user's TRY budgets and recompute paper economics.

    A cap never increases an order. If a budget is lower than the scanner's
    target, the base amount is rounded down to eight decimal places (the
    paper precision used by the control plane). Returning ``None`` means the
    cap cannot produce a positive base amount and the opportunity is skipped.
    """

    if opportunity.base_amount <= 0 or opportunity.buy_vwap <= 0 or opportunity.sell_vwap <= 0:
        return None
    buy_budget = _quote_budget(profile, opportunity.buy_exchange)
    sell_budget = _quote_budget(profile, opportunity.sell_exchange)
    if buy_budget <= 0 or sell_budget <= 0:
        return None
    max_base = min(opportunity.base_amount,
                   buy_budget / opportunity.buy_vwap,
                   sell_budget / opportunity.sell_vwap)
    amount = max_base.quantize(Decimal("0.00000001"), rounding=ROUND_DOWN)
    if amount <= 0:
        return None
    if amount == opportunity.base_amount:
        return opportunity
    scale = amount / opportunity.base_amount
    gross = opportunity.gross_profit_try * scale
    fees = opportunity.fees_try * scale
    buffer = opportunity.safety_buffer_try * scale
    net = gross - fees - buffer
    return replace(opportunity, base_amount=amount, gross_profit_try=gross,
                   fees_try=fees, safety_buffer_try=buffer, net_profit_try=net)


class PaperCoordinator:
    """Executes at most one qualified paper opportunity per fresh market snapshot."""

    def __init__(self, db: Database, scanner, engine: ArbitrageExecutionEngine,
                 cooldown_seconds: int = 60):
        self.db = db
        self.scanner = scanner
        self.engine = engine
        self.cooldown_seconds = max(cooldown_seconds, 10)
        self.running = False
        self.last_snapshot_id = 0
        self.last_error: str | None = None
        self.last_execution_id: str | None = None
        self.enabled = True

    async def run(self):
        self.running = True
        while self.running:
            try:
                if self.scanner.snapshot_id > self.last_snapshot_id:
                    self.last_snapshot_id = self.scanner.snapshot_id
                    if self.scanner.last_success_ms:
                        self.db.record_observation(self.scanner.last_success_ms)
                    if self.enabled:
                        await self.process_snapshot()
                    self.last_error = None
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self.last_error = type(exc).__name__
            await asyncio.sleep(1)

    def stop(self):
        self.running = False

    def set_enabled(self, enabled: bool) -> None:
        """Pause/resume automatic paper executions without killing the task."""
        self.enabled = bool(enabled)

    async def process_snapshot(self):
        candidates = [item for item in self.scanner.opportunities if item.get("executable")]
        if not candidates:
            return
        now_ms = int(time.time() * 1000)
        day_start_ms = now_ms - (now_ms % 86_400_000)
        for profile in self.db.active_paper_profiles():
            self.db.record_paper_opportunities(profile["user_id"], len(candidates))
            daily_loss = Decimal(self.db.realized_loss_since(profile["user_id"], day_start_ms))
            if daily_loss >= Decimal(profile["daily_loss_limit_try"]):
                self.db.audit(profile["user_id"], "paper_daily_loss_gate", json.dumps({"loss": str(daily_loss)}))
                continue
            selected = None
            budgeted = None
            for item in candidates:
                if self.db.has_recent_execution(profile["user_id"], item["pair"],
                                                now_ms - self.cooldown_seconds * 1000):
                    continue
                candidate = apply_quote_budgets(opportunity_from_mapping(item), profile)
                if candidate is not None and candidate.base_amount * candidate.buy_vwap <= Decimal(profile["max_trade_try"]):
                    selected, budgeted = item, candidate
                    break
            if selected is None or budgeted is None:
                continue
            try:
                result = await self.engine.execute_paper(
                    profile["user_id"], budgeted,
                    Decimal(profile["max_recovery_loss_try"]))
                self.last_execution_id = result.intent_id
                if result.state.value == "BALANCED_FILL":
                    self.db.record_paper_trade(profile["user_id"])
                self.db.audit(profile["user_id"], "auto_paper_execution",
                              json.dumps({"intent_id": result.intent_id, "pair": selected["pair"]}))
            except RecoveryLimitExceeded:
                self.db.audit(profile["user_id"], "auto_paper_recovery_blocked",
                              json.dumps({"pair": selected["pair"]}))
