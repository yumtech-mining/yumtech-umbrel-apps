from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Dict, Iterable, List, Optional


def unwrap_response(payload: Any) -> Any:
    if isinstance(payload, dict) and payload.get("success") is False:
        raise IOError(f"BTCTurk API error: {payload.get('message') or payload.get('code') or 'unknown'}")
    if isinstance(payload, dict) and "data" in payload:
        return payload["data"]
    return payload


@dataclass(frozen=True)
class ParsedBalance:
    asset: str
    available: Decimal
    total: Decimal


def parse_balances(payload: Any) -> List[ParsedBalance]:
    rows = unwrap_response(payload) or []
    result = []
    for row in rows:
        total = Decimal(str(row.get("balance", "0")))
        available = Decimal(str(row.get("free", row.get("available", row.get("freeBalance", total)))))
        result.append(ParsedBalance(str(row["asset"]).upper(), available, total))
    return result


def normalize_order_status(value: Any) -> str:
    normalized = str(value or "untouched").strip().lower().replace("_", " ")
    aliases = {
        "open": "untouched",
        "new": "untouched",
        "partially filled": "partial",
        "partial fill": "partial",
        "filled": "closed",
        "cancelled": "cancelled",
        "canceled": "canceled",
    }
    return aliases.get(normalized, normalized)


def order_id(row: Dict[str, Any]) -> str:
    value = row.get("id", row.get("orderId"))
    if value is None:
        raise ValueError("BTCTurk order response has no order id")
    return str(value)


def order_timestamp(row: Dict[str, Any], fallback: float) -> float:
    value = row.get("timestamp", row.get("time", row.get("updateTime")))
    if value is None:
        return fallback
    parsed = float(value)
    return parsed * 1e-3 if parsed > 10_000_000_000 else parsed


def iter_order_trades(payload: Any, exchange_order_id: str) -> Iterable[Dict[str, Any]]:
    rows = unwrap_response(payload) or []
    for row in rows:
        candidate = row.get("orderId", row.get("order_id"))
        if candidate is None or str(candidate) == str(exchange_order_id):
            yield row


def trade_id(row: Dict[str, Any]) -> str:
    value: Optional[Any] = row.get("id", row.get("tradeId"))
    if value is None:
        raise ValueError("BTCTurk trade response has no trade id")
    return str(value)

