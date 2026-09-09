from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Dict, Iterable, List


def unwrap_response(payload: Any) -> Any:
    if isinstance(payload, dict) and int(payload.get("code", 0)) != 0:
        raise IOError(f"Binance TR API error {payload.get('code')}: {payload.get('msg', payload.get('message', 'unknown'))}")
    return payload.get("data", payload) if isinstance(payload, dict) else payload


def list_payload(payload: Any) -> List[Dict[str, Any]]:
    data = unwrap_response(payload)
    if isinstance(data, dict):
        return data.get("list", [])
    return data or []


@dataclass(frozen=True)
class ParsedBalance:
    asset: str
    available: Decimal
    total: Decimal


def parse_balances(payload: Any) -> List[ParsedBalance]:
    data = unwrap_response(payload) or {}
    result = []
    for row in data.get("accountAssets", []):
        free = Decimal(str(row.get("free", "0")))
        locked = Decimal(str(row.get("locked", "0")))
        result.append(ParsedBalance(str(row["asset"]).upper(), free, free + locked))
    return result


def parse_fee_rates(payload: Any) -> tuple[Decimal, Decimal]:
    data = unwrap_response(payload) or {}
    return Decimal(str(data["fiatMakerCommission"])), Decimal(str(data["fiatTakerCommission"]))


def iter_fills(payload: Any, order_id: str) -> Iterable[Dict[str, Any]]:
    for row in list_payload(payload):
        if str(row.get("orderId")) == str(order_id):
            yield row

