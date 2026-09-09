"""Idempotent bridge from the native Hummingbot PaperTrade JSONL stream."""

from __future__ import annotations

import asyncio
import json
import logging
from decimal import Decimal
from pathlib import Path
from typing import Callable

from .db import Database


log = logging.getLogger(__name__)


class HummingbotPaperEventBridge:
    def __init__(self, db: Database, path: Path, on_balanced: Callable[[int], None] | None = None):
        self.db = db
        self.path = path
        self.on_balanced = on_balanced
        self.running = False
        self.offset = 0
        self.last_error: str | None = None

    @staticmethod
    def _leg(value: dict) -> dict:
        fills = value.get("fills") or []
        filled = Decimal(str(value.get("filled_base", "0")))
        average = Decimal(str(value.get("average_price", "0")))
        fee = Decimal(str(value.get("fee_try", "0")))
        if fills:
            filled = sum((Decimal(str(row.get("filled_base", "0"))) for row in fills), Decimal("0"))
            quote = sum((Decimal(str(row.get("quote_value", "0"))) for row in fills), Decimal("0"))
            average = quote / filled if filled else Decimal("0")
            fee = sum((Decimal(str(row.get("fee_try", "0"))) for row in fills), Decimal("0"))
        return {
            "exchange": value.get("exchange", "unknown"),
            "side": value.get("side", "buy"),
            "requested_base": str(value.get("requested_base", filled)),
            "requested_price": str(average),
            "filled_base": str(filled),
            "average_price": str(average),
            "fee_try": str(fee),
            "external_order_id": value.get("order_id"),
            "status": value.get("status", "FILLED"),
            "fee_rate": str(value.get("fee_rate", "0")),
            "fee_asset": value.get("fee_asset", "TRY"),
            "fill_source": value.get("fill_source", "hummingbot-paper"),
            "slippage_try": str(value.get("slippage_try", "0")),
            "latency_ms": int(value.get("latency_ms", 0) or 0),
        }

    def _consume(self) -> int:
        if not self.path.exists():
            return 0
        count = 0
        with self.path.open("r", encoding="utf-8") as handle:
            handle.seek(self.offset)
            while True:
                line = handle.readline()
                if not line:
                    break
                self.offset = handle.tell()
                try:
                    event = json.loads(line)
                except (ValueError, TypeError):
                    continue
                if not isinstance(event, dict) or event.get("type") != "completed":
                    continue
                try:
                    state = str(event.get("state", "BALANCED_FILL"))
                    if state not in {"BALANCED_FILL", "FAILED_SAFE"}:
                        continue
                    values = {
                        "id": str(event["intent_id"]),
                        "user_id": int(event["user_id"]),
                        "pair": str(event["pair"]),
                        "buy_exchange": str(event["buy_exchange"]),
                        "sell_exchange": str(event["sell_exchange"]),
                        "requested_base": str(event.get("requested_base", "0")),
                        "max_recovery_loss_try": str(event.get("max_recovery_loss_try", "100")),
                        "expected_profit_try": str(event.get("expected_profit_try", "0")),
                        "realized_profit_try": str(event.get("realized_profit_try", "0")),
                        "state": state,
                        "error": event.get("error"),
                        "detail": json.dumps({"source": "hummingbot-paper", "created_at_ms": event.get("created_at_ms")}),
                    }
                    legs = [self._leg(leg) for leg in event.get("legs", []) if isinstance(leg, dict)]
                    if self.db.record_external_paper_execution(values, legs):
                        count += 1
                        if state == "BALANCED_FILL" and self.on_balanced:
                            self.on_balanced(values["user_id"])
                except (KeyError, TypeError, ValueError, ArithmeticError) as exc:
                    self.last_error = type(exc).__name__
                    log.warning("invalid Hummingbot paper event: %s", type(exc).__name__)
        return count

    async def run(self) -> None:
        self.running = True
        while self.running:
            try:
                self._consume()
                self.last_error = None
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self.last_error = type(exc).__name__
                log.warning("Hummingbot event bridge failed: %s", type(exc).__name__)
            await asyncio.sleep(1)

    def stop(self) -> None:
        self.running = False
