from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Dict

from pydantic import ConfigDict, Field, SecretStr

from hummingbot.client.config.config_data_types import BaseConnectorConfigMap
from hummingbot.core.data_type.trade_fee import TradeFeeSchema

CENTRALIZED = True
EXAMPLE_PAIR = "BTC-TRY"
DEFAULT_FEES = TradeFeeSchema(
    maker_percent_fee_decimal=Decimal("0.0015"),
    taker_percent_fee_decimal=Decimal("0.0015"),
    buy_percent_fee_deducted_from_returns=True,
)


class BinanceTRConfigMap(BaseConnectorConfigMap):
    connector: str = "binance_tr"
    binance_tr_api_key: SecretStr = Field(
        default=...,
        json_schema_extra={"prompt": "Enter your Binance TR API key", "is_secure": True,
                           "is_connect_key": True, "prompt_on_new": True},
    )
    binance_tr_api_secret: SecretStr = Field(
        default=...,
        json_schema_extra={"prompt": "Enter your Binance TR API secret", "is_secure": True,
                           "is_connect_key": True, "prompt_on_new": True},
    )
    model_config = ConfigDict(title="binance_tr")


KEYS = BinanceTRConfigMap.model_construct()


@dataclass(frozen=True)
class BinanceTRTradingRule:
    symbol: str
    trading_pair: str
    min_order_size: Decimal
    max_order_size: Decimal
    price_increment: Decimal
    amount_increment: Decimal
    min_notional: Decimal


def is_exchange_information_valid(info: Dict[str, Any]) -> bool:
    return int(info.get("spotTradingEnable", 0)) == 1 and int(info.get("type", 0)) == 1


def parse_trading_rule(info: Dict[str, Any]) -> BinanceTRTradingRule:
    if not is_exchange_information_valid(info):
        raise ValueError("Binance TR symbol is not enabled for main spot trading")
    filters = {item["filterType"]: item for item in info.get("filters", [])}
    price = filters["PRICE_FILTER"]
    lot = filters["LOT_SIZE"]
    notional = filters.get("NOTIONAL", filters.get("MIN_NOTIONAL", {}))
    return BinanceTRTradingRule(
        symbol=str(info["symbol"]).upper(),
        trading_pair=f"{str(info['baseAsset']).upper()}-{str(info['quoteAsset']).upper()}",
        min_order_size=Decimal(str(lot["minQty"])),
        max_order_size=Decimal(str(lot["maxQty"])),
        price_increment=Decimal(str(price["tickSize"])),
        amount_increment=Decimal(str(lot["stepSize"])),
        min_notional=Decimal(str(notional.get("minNotional", "0"))),
    )


def api_symbol(symbol: str) -> str:
    return symbol.replace("_", "").upper()


def decimal_to_api(value: Decimal) -> str:
    return format(value, "f")

