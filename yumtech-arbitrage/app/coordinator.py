import asyncio
import json
import time
from decimal import Decimal

from .db import Database
from .execution import ArbitrageExecutionEngine, RecoveryLimitExceeded, opportunity_from_mapping


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
            selected = next((item for item in candidates
                             if Decimal(item["base_amount"]) * Decimal(item["buy_vwap"])
                             <= Decimal(profile["max_trade_try"])
                             and not self.db.has_recent_execution(
                                 profile["user_id"], item["pair"], now_ms - self.cooldown_seconds * 1000)), None)
            if selected is None:
                continue
            try:
                result = await self.engine.execute_paper(
                    profile["user_id"], opportunity_from_mapping(selected),
                    Decimal(profile["max_recovery_loss_try"]))
                self.last_execution_id = result.intent_id
                if result.state.value == "BALANCED_FILL":
                    self.db.record_paper_trade(profile["user_id"])
                self.db.audit(profile["user_id"], "auto_paper_execution",
                              json.dumps({"intent_id": result.intent_id, "pair": selected["pair"]}))
            except RecoveryLimitExceeded:
                self.db.audit(profile["user_id"], "auto_paper_recovery_blocked",
                              json.dumps({"pair": selected["pair"]}))
