from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Dict

from pydantic import ConfigDict, Field, SecretStr

from hummingbot.client.config.config_data_types import BaseConnectorConfigMap
from hummingbot.core.data_type.trade_fee import TradeFeeSchema

from .btcturk_order_semantics import (
    InsufficientQuoteBalance,
    MarketBuyQuote,
    OrderSemanticsError,
    build_market_order_payload,
    build_side_aware_order_payload,
    market_buy_quote_for_base,
    quantize_up,
)


CENTRALIZED = True
EXAMPLE_PAIR = "BTC-TRY"

# Used only until authenticated account fee data is available. Execution must
# use the profile's verified fee tier before live mode can be unlocked.
DEFAULT_FEES = TradeFeeSchema(
    maker_percent_fee_decimal=Decimal("0.0015"),
    taker_percent_fee_decimal=Decimal("0.0015"),
)


class BtcTurkConfigMap(BaseConnectorConfigMap):
    connector: str = "btcturk"
    btcturk_api_key: SecretStr = Field(
        default=...,
        json_schema_extra={
            "prompt": "Enter your BTCTurk API key",
            "is_secure": True,
            "is_connect_key": True,
            "prompt_on_new": True,
        },
    )
    btcturk_api_secret: SecretStr = Field(
        default=...,
        json_schema_extra={
            "prompt": "Enter your BTCTurk API secret",
            "is_secure": True,
            "is_connect_key": True,
            "prompt_on_new": True,
        },
    )
    model_config = ConfigDict(title="btcturk")


KEYS = BtcTurkConfigMap.model_construct()


@dataclass(frozen=True)
class BtcTurkTradingRule:
    symbol: str
    trading_pair: str
    min_order_size: Decimal
    min_price_increment: Decimal
    min_base_amount_increment: Decimal
    min_notional_size: Decimal
    supports_market_order: bool
    # BTCTurk's denominator scale is also the precision used by a TRY-sized
    # market BUY quantity. Keep this separate from base amount precision.
    min_quote_amount_increment: Decimal = Decimal("0.01")


def _increment(scale: Any) -> Decimal:
    return Decimal("1").scaleb(-int(scale))


def is_exchange_information_valid(info: Dict[str, Any]) -> bool:
    return (
        bool(info.get("name"))
        and bool(info.get("numerator"))
        and bool(info.get("denominator"))
        and info.get("status", "TRADING").upper() not in {"CLOSED", "SUSPENDED", "DISABLED"}
    )


def trading_pair_from_exchange_info(info: Dict[str, Any]) -> str:
    return f"{str(info['numerator']).upper()}-{str(info['denominator']).upper()}"


def parse_trading_rule(info: Dict[str, Any]) -> BtcTurkTradingRule:
    if not is_exchange_information_valid(info):
        raise ValueError("BTCTurk symbol is not active or is missing required fields")

    filters = info.get("filters") or []
    min_notional = next(
        (Decimal(str(item["minExchangeValue"])) for item in filters if "minExchangeValue" in item),
        Decimal("0"),
    )
    amount_increment = _increment(info["numeratorScale"])
    return BtcTurkTradingRule(
        symbol=str(info["name"]).upper(),
        trading_pair=trading_pair_from_exchange_info(info),
        min_order_size=amount_increment,
        min_price_increment=_increment(info["denominatorScale"]),
        min_base_amount_increment=amount_increment,
        min_notional_size=min_notional,
        supports_market_order=bool(info.get("hasMarketOrder", False)),
        min_quote_amount_increment=_increment(info["denominatorScale"]),
    )


def decimal_to_api(value: Decimal) -> str:
    return format(value, "f")


def build_limit_order_payload(
    *, client_order_id: str, symbol: str, side: str, quantity: Decimal, price: Decimal
) -> Dict[str, str]:
    normalized_side = side.lower()
    if normalized_side not in {"buy", "sell"}:
        raise ValueError("side must be buy or sell")
    if quantity <= 0 or price <= 0:
        raise ValueError("quantity and price must be positive")
    return {
        "quantity": decimal_to_api(quantity),
        "price": decimal_to_api(price),
        "newOrderClientId": client_order_id,
        "orderMethod": "limit",
        "orderType": normalized_side,
        "pairSymbol": symbol.upper(),
    }
