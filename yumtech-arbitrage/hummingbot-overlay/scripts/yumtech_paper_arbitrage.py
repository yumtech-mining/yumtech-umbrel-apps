"""YUMTECH two-leg arbitrage script for Hummingbot PaperTrade.

The script deliberately uses the official paper connectors (``*_paper_trade``)
and market orders. Hummingbot then applies its normal five-second execution
queue, order-book depth matching, balance checks, connector fee schema and
bounded one-leg recovery. The JSONL event stream is consumed by the local
dashboard; it contains no API keys.
"""

from __future__ import annotations

import json
import os
import time
import uuid
from decimal import Decimal, ROUND_DOWN
from pathlib import Path
from typing import Any, Dict, List

from pydantic import Field, field_validator

from hummingbot.connector.connector_base import ConnectorBase
from hummingbot.core.data_type.common import MarketDict, OrderType, TradeType
from hummingbot.core.event.events import (
    BuyOrderCompletedEvent,
    MarketOrderFailureEvent,
    OrderFilledEvent,
    SellOrderCompletedEvent,
)
from hummingbot.strategy.strategy_v2_base import StrategyV2Base, StrategyV2ConfigBase


ZERO = Decimal("0")


class YumtechPaperArbitrageConfig(StrategyV2ConfigBase):
    script_file_name: str = os.path.basename(__file__)
    trading_pairs: List[str] = Field(default_factory=list)
    btcturk_budget_try: Decimal = Field(default=Decimal("1000"), gt=ZERO)
    binance_tr_budget_try: Decimal = Field(default=Decimal("1000"), gt=ZERO)
    min_profitability: Decimal = Field(default=Decimal("0.004"), ge=ZERO)
    safety_buffer_rate: Decimal = Field(default=Decimal("0.001"), ge=ZERO)
    btcturk_maker_fee_rate: Decimal = Field(default=Decimal("0.0015"), ge=ZERO)
    btcturk_taker_fee_rate: Decimal = Field(default=Decimal("0.0015"), ge=ZERO)
    binance_tr_maker_fee_rate: Decimal = Field(default=Decimal("0.0015"), ge=ZERO)
    binance_tr_taker_fee_rate: Decimal = Field(default=Decimal("0.0015"), ge=ZERO)
    fee_mode: str = Field(default="taker", pattern="^(maker|taker)$")
    max_recovery_loss_try: Decimal = Field(default=Decimal("100"), gt=ZERO)
    cooldown_seconds: int = Field(default=30, ge=5, le=3600)
    event_path: str = "/home/hummingbot/yumtech-data/hummingbot-paper-events.jsonl"
    user_id: int = Field(default=1, ge=1)

    @field_validator("trading_pairs", mode="before")
    @classmethod
    def normalize_pairs(cls, value):
        if value is None:
            return []
        return sorted({str(pair).upper().replace("/", "-") for pair in value if str(pair).strip()})

    def update_markets(self, markets: MarketDict) -> MarketDict:
        for pair in self.trading_pairs:
            markets.add_or_update("btcturk_paper_trade", pair)
            markets.add_or_update("binance_tr_paper_trade", pair)
        return markets


class YumtechPaperArbitrage(StrategyV2Base):
    """Depth-aware, one-intent-at-a-time spot arbitrage paper strategy."""

    def __init__(self, connectors: Dict[str, ConnectorBase], config: YumtechPaperArbitrageConfig):
        super().__init__(connectors, config)
        self.config = config
        self._orders: dict[str, dict[str, Any]] = {}
        self._intents: dict[str, dict[str, Any]] = {}
        self._last_submit = 0.0
        self._submitted = 0
        self._event_file = Path(config.event_path)
        self._event_file.parent.mkdir(parents=True, exist_ok=True)

    @property
    def _bt(self):
        return self.connectors["btcturk_paper_trade"]

    @property
    def _bn(self):
        return self.connectors["binance_tr_paper_trade"]

    def _fee_rate(self, connector_name: str) -> Decimal:
        if connector_name == "btcturk_paper_trade":
            return self.config.btcturk_maker_fee_rate if self.config.fee_mode == "maker" else self.config.btcturk_taker_fee_rate
        return self.config.binance_tr_maker_fee_rate if self.config.fee_mode == "maker" else self.config.binance_tr_taker_fee_rate

    def _emit(self, event_type: str, **payload: Any) -> None:
        record = {"type": event_type, "created_at_ms": int(time.time() * 1000), **payload}
        self._event_file.parent.mkdir(parents=True, exist_ok=True)
        with self._event_file.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, separators=(",", ":"), default=str) + "\n")
            handle.flush()
            os.fsync(handle.fileno())

    @staticmethod
    def _walk(levels, amount: Decimal, *, is_buy: bool, quote_budget: Decimal | None = None):
        remaining_base = amount
        remaining_quote = quote_budget
        filled = ZERO
        quote = ZERO
        for row in levels:
            price = Decimal(str(row.price))
            available = Decimal(str(row.amount))
            if price <= ZERO or available <= ZERO:
                continue
            take = available
            if remaining_base is not None:
                take = min(take, remaining_base)
            if remaining_quote is not None:
                take = min(take, remaining_quote / price)
            if take <= ZERO:
                break
            filled += take
            quote += take * price
            if remaining_base is not None:
                remaining_base -= take
            if remaining_quote is not None:
                remaining_quote -= take * price
            if (remaining_base is not None and remaining_base <= Decimal("1e-12")) or \
                    (remaining_quote is not None and remaining_quote <= Decimal("0.00000001")):
                break
        return filled, quote, quote / filled if filled else ZERO

    def _quote_buy(self, connector, pair: str, budget: Decimal):
        return self._walk(connector.order_book_ask_entries(pair), None, is_buy=True, quote_budget=budget)

    def _base_sell(self, connector, pair: str, amount: Decimal):
        return self._walk(connector.order_book_bid_entries(pair), amount, is_buy=False)

    def _base_buy(self, connector, pair: str, amount: Decimal):
        return self._walk(connector.order_book_ask_entries(pair), amount, is_buy=True)

    def _candidate(self, pair: str, buy_name: str, sell_name: str, budget: Decimal):
        buy_conn = self.connectors[buy_name]
        sell_conn = self.connectors[sell_name]
        buy_base, buy_quote, buy_vwap = self._quote_buy(buy_conn, pair, budget)
        if buy_base <= ZERO or buy_vwap <= ZERO:
            return None
        amount = buy_conn.quantize_order_amount(pair, buy_base)
        sell_base, sell_quote, sell_vwap = self._base_sell(sell_conn, pair, amount)
        if sell_base <= ZERO or sell_vwap <= ZERO:
            return None
        amount = min(amount, sell_base)
        # The seller may expose less depth than the initial quote budget. Walk
        # the buy book again for the final common base amount so the VWAP and
        # fee estimate do not accidentally use the larger initial slice.
        _, buy_quote, buy_vwap = self._base_buy(buy_conn, pair, amount)
        sell_quote = amount * sell_vwap
        buy_fee = buy_quote * self._fee_rate(buy_name)
        sell_fee = sell_quote * self._fee_rate(sell_name)
        buffer = buy_quote * self.config.safety_buffer_rate
        net = sell_quote - buy_quote - buy_fee - sell_fee - buffer
        pct = net / buy_quote if buy_quote else ZERO
        if pct < self.config.min_profitability:
            return None
        # Hummingbot strategies express size in base asset. The quote budget
        # is retained in the event for an auditable TRY-to-base conversion.
        return {
            "pair": pair, "buy_exchange": buy_name, "sell_exchange": sell_name,
            "base_amount": amount, "buy_vwap": buy_vwap, "sell_vwap": sell_vwap,
            "buy_quote": buy_quote, "sell_quote": sell_quote,
            "buy_fee": buy_fee, "sell_fee": sell_fee, "buffer": buffer,
            "net": net, "net_pct": pct,
        }

    def on_tick(self):
        if not self.ready_to_trade or self._intents:
            return
        now = float(self.current_timestamp)
        if now - self._last_submit < self.config.cooldown_seconds:
            return
        candidates = []
        for pair in self.config.trading_pairs:
            for buy_name, sell_name, budget in (
                ("btcturk_paper_trade", "binance_tr_paper_trade", self.config.btcturk_budget_try),
                ("binance_tr_paper_trade", "btcturk_paper_trade", self.config.binance_tr_budget_try),
            ):
                try:
                    candidate = self._candidate(pair, buy_name, sell_name, budget)
                    if candidate:
                        # Balance checks use the same quote/base assets that
                        # PaperTradeExchange will debit when the queued order
                        # executes five seconds later.
                        base = pair.split("-", 1)[0]
                        if self.connectors[buy_name].get_available_balance("TRY") < candidate["buy_quote"] + candidate["buy_fee"]:
                            continue
                        if self.connectors[sell_name].get_available_balance(base) < candidate["base_amount"]:
                            continue
                        candidates.append(candidate)
                except Exception:
                    self.logger().debug("paper candidate failed", exc_info=True)
        if not candidates:
            return
        candidate = max(candidates, key=lambda item: item["net"])
        intent_id = uuid.uuid4().hex
        intent = {"id": intent_id, "user_id": self.config.user_id, **candidate, "legs": {},
                  "submitted_at_ms": int(time.time() * 1000)}
        self._intents[intent_id] = intent
        submitted = 0
        for side, exchange in (("buy", candidate["buy_exchange"]), ("sell", candidate["sell_exchange"])):
            try:
                order_id = (self.buy if side == "buy" else self.sell)(
                    exchange, candidate["pair"], candidate["base_amount"], OrderType.MARKET)
            except Exception as exc:
                order_id = None
                intent["legs"][side] = self._failed_leg(
                    intent, side, exchange, error=f"submit_{type(exc).__name__}")
            if order_id:
                self._orders[order_id] = {"order_id": order_id, "intent_id": intent_id,
                                          "role": side, "side": side, "exchange": exchange,
                                          "pair": candidate["pair"], "requested_base": candidate["base_amount"],
                                          "fills": [], "completed": False}
                submitted += 1
            elif side not in intent["legs"]:
                intent["legs"][side] = self._failed_leg(intent, side, exchange, error="missing_order_id")
        self._last_submit = now
        self._submitted += submitted
        self._emit("submitted", intent_id=intent_id, user_id=self.config.user_id, pair=candidate["pair"],
                   buy_exchange=candidate["buy_exchange"], sell_exchange=candidate["sell_exchange"],
                   requested_base=str(candidate["base_amount"]), expected_profit_try=str(candidate["net"]),
                   max_recovery_loss_try=str(self.config.max_recovery_loss_try),
                   orders_submitted=submitted)
        if submitted == 0:
            self._finalize_intent(intent)

    def did_fill_order(self, event: OrderFilledEvent):
        order = self._orders.get(event.order_id)
        if not order:
            return
        fee_percent = Decimal(str(getattr(event.trade_fee, "percent", self._fee_rate(order["exchange"]))))
        quote = Decimal(str(event.price)) * Decimal(str(event.amount))
        fee = quote * fee_percent
        order["fills"].append({"filled_base": str(event.amount), "average_price": str(event.price),
                               "quote_value": str(quote), "fee_try": str(fee),
                               "fee_rate": str(fee_percent), "fee_asset": "TRY"})

    @staticmethod
    def _failed_leg(intent: dict, side: str, exchange: str, *, error: str,
                    requested_base: Decimal | None = None) -> dict:
        requested = requested_base if requested_base is not None else intent["base_amount"]
        return {"exchange": exchange, "side": side, "requested_base": str(requested),
                "fills": [], "filled_base": "0", "average_price": "0", "fee_try": "0",
                "fee_rate": "0", "fee_asset": "TRY", "fill_source": "hummingbot-paper",
                "status": "FAILED", "error": error}

    def _leg_from_order(self, order: dict, intent: dict, event) -> dict:
        fills = order["fills"]
        if not fills:
            amount = Decimal(str(getattr(event, "base_asset_amount", "0") or "0"))
            quote = Decimal(str(getattr(event, "quote_asset_amount", "0") or "0"))
            fee_rate = self._fee_rate(order["exchange"])
            fills = [{"filled_base": str(amount), "average_price": str(quote / amount if amount else ZERO),
                      "quote_value": str(quote), "fee_try": str(quote * fee_rate),
                      "fee_rate": str(fee_rate), "fee_asset": "TRY"}]
        filled = sum((Decimal(row["filled_base"]) for row in fills), ZERO)
        quote = sum((Decimal(row["quote_value"]) for row in fills), ZERO)
        fee = sum((Decimal(row["fee_try"]) for row in fills), ZERO)
        requested = Decimal(str(order.get("requested_base", intent["base_amount"])))
        status = "FILLED" if filled >= requested else ("PARTIAL" if filled > ZERO else "FAILED")
        return {"order_id": order.get("order_id"), "exchange": order["exchange"], "side": order["side"],
                "requested_base": str(requested), "fills": fills, "filled_base": str(filled),
                "average_price": str(quote / filled if filled else ZERO), "fee_try": str(fee),
                "fee_rate": fills[0].get("fee_rate", "0"), "fee_asset": "TRY",
                "fill_source": "hummingbot-paper-recovery" if order.get("role") == "recovery"
                else "hummingbot-paper", "status": status}

    @staticmethod
    def _quote(leg: dict) -> Decimal:
        return sum((Decimal(str(row.get("quote_value", "0"))) for row in leg.get("fills", [])), ZERO)

    def _submit_recovery(self, intent: dict, exposure: Decimal) -> bool:
        if abs(exposure) <= Decimal("1e-12"):
            return False
        side = "sell" if exposure > ZERO else "buy"
        exchange = intent["buy_exchange"] if side == "sell" else intent["sell_exchange"]
        reference = intent["buy_vwap"] if side == "sell" else intent["sell_vwap"]
        amount = abs(exposure)
        rate = self._fee_rate("btcturk_paper_trade" if exchange == "btcturk_paper_trade" else "binance_tr_paper_trade")
        worst_case_loss = amount * reference * (self.config.safety_buffer_rate + rate)
        if worst_case_loss > self.config.max_recovery_loss_try:
            intent["recovery_error"] = "recovery_loss_limit"
            return False
        try:
            order_id = (self.sell if side == "sell" else self.buy)(
                exchange, intent["pair"], amount, OrderType.MARKET)
        except Exception as exc:
            intent["recovery_error"] = f"recovery_{type(exc).__name__}"
            return False
        if not order_id:
            intent["recovery_error"] = "recovery_missing_order_id"
            return False
        intent["recovery_requested"] = True
        self._orders[order_id] = {"order_id": order_id, "intent_id": intent["id"],
                                  "role": "recovery", "side": side, "exchange": exchange,
                                  "pair": intent["pair"], "requested_base": amount,
                                  "fills": [], "completed": False}
        self._submitted += 1
        self._emit("recovery_submitted", intent_id=intent["id"], user_id=intent["user_id"],
                   pair=intent["pair"], exchange=exchange, side=side, requested_base=str(amount),
                   estimated_loss_try=str(worst_case_loss),
                   max_recovery_loss_try=str(self.config.max_recovery_loss_try))
        return True

    def _finalize_intent(self, intent: dict):
        if "buy" not in intent["legs"] or "sell" not in intent["legs"]:
            return
        buy, sell = intent["legs"]["buy"], intent["legs"]["sell"]
        recovery = intent["legs"].get("recovery")
        exposure = Decimal(buy["filled_base"]) - Decimal(sell["filled_base"])
        buy_quote, sell_quote = self._quote(buy), self._quote(sell)
        profit = sell_quote - buy_quote - Decimal(buy["fee_try"]) - Decimal(sell["fee_try"])
        if recovery:
            recovery_quote = self._quote(recovery)
            exposure += Decimal(recovery["filled_base"]) if recovery["side"] == "buy" else -Decimal(recovery["filled_base"])
            profit += recovery_quote if recovery["side"] == "sell" else -recovery_quote
            profit -= Decimal(recovery["fee_try"])
        balanced = abs(exposure) <= Decimal("1e-12")
        legs = [buy, sell] + ([recovery] if recovery else [])
        self._emit("completed", intent_id=intent["id"], user_id=intent["user_id"], pair=intent["pair"],
                   buy_exchange=intent["buy_exchange"], sell_exchange=intent["sell_exchange"],
                   requested_base=str(intent["base_amount"]), expected_profit_try=str(intent["net"]),
                   max_recovery_loss_try=str(self.config.max_recovery_loss_try),
                   realized_profit_try=str(profit), state="BALANCED_FILL" if balanced else "FAILED_SAFE",
                   error=None if balanced else intent.get("recovery_error", "single_leg_recovery_incomplete"),
                   exposure_base=str(exposure), legs=legs)
        intent_id = intent["id"]
        self._intents.pop(intent_id, None)
        for order_id, order in list(self._orders.items()):
            if order.get("intent_id") == intent_id:
                self._orders.pop(order_id, None)

    def _maybe_recover_or_finalize(self, intent: dict):
        if "buy" not in intent["legs"] or "sell" not in intent["legs"]:
            return
        buy, sell = intent["legs"]["buy"], intent["legs"]["sell"]
        exposure = Decimal(buy["filled_base"]) - Decimal(sell["filled_base"])
        if abs(exposure) <= Decimal("1e-12"):
            self._finalize_intent(intent)
        elif "recovery" not in intent["legs"] and not intent.get("recovery_requested"):
            if not self._submit_recovery(intent, exposure):
                self._finalize_intent(intent)
        elif "recovery" in intent["legs"]:
            self._finalize_intent(intent)

    def _complete(self, order_id: str, event):
        order = self._orders.get(order_id)
        if not order or order.get("completed"):
            return
        order["completed"] = True
        intent = self._intents.get(order["intent_id"])
        if not intent:
            return
        intent["legs"][order["role"]] = self._leg_from_order(order, intent, event)
        self._maybe_recover_or_finalize(intent)

    def did_complete_buy_order(self, event: BuyOrderCompletedEvent):
        self._complete(event.order_id, event)

    def did_complete_sell_order(self, event: SellOrderCompletedEvent):
        self._complete(event.order_id, event)

    def did_fail_order(self, event: MarketOrderFailureEvent):
        order = self._orders.get(event.order_id)
        if not order or order.get("completed"):
            return
        order["completed"] = True
        intent = self._intents.get(order["intent_id"])
        if intent:
            intent["legs"][order["role"]] = self._failed_leg(
                intent, order["side"], order["exchange"], error="paper_order_failure",
                requested_base=order.get("requested_base"))
            self._maybe_recover_or_finalize(intent)

    def format_status(self) -> str:
        return (f"YUMTECH Hummingbot PaperTrade | pairs={len(self.config.trading_pairs)} "
                f"submitted={self._submitted} pending={len(self._intents)} "
                f"fee_mode={self.config.fee_mode}")
