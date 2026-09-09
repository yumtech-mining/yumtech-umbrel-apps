import asyncio
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple

from bidict import bidict

from hummingbot.connector.constants import s_decimal_NaN
from hummingbot.connector.exchange_py_base import ExchangePyBase
from hummingbot.connector.trading_rule import TradingRule
from hummingbot.core.data_type.common import OrderType, TradeType
from hummingbot.core.data_type.in_flight_order import InFlightOrder, OrderUpdate, TradeUpdate
from hummingbot.core.data_type.trade_fee import DeductedFromReturnsTradeFee, TokenAmount

from . import binance_tr_constants as CONSTANTS
from . import binance_tr_utils as utils
from . import binance_tr_web_utils as web_utils
from .binance_tr_api_order_book_data_source import BinanceTRAPIOrderBookDataSource
from .binance_tr_api_user_stream_data_source import BinanceTRAPIUserStreamDataSource
from .binance_tr_auth import BinanceTRAuth
from .binance_tr_parsers import iter_fills, parse_balances, parse_fee_rates, unwrap_response


class BinanceTRExchange(ExchangePyBase):
    UPDATE_ORDER_STATUS_MIN_INTERVAL = 5.0
    web_utils = web_utils

    def __init__(self, binance_tr_api_key: str, binance_tr_api_secret: str,
                 balance_asset_limit: Optional[Dict[str, Dict[str, Decimal]]] = None,
                 rate_limits_share_pct: Decimal = Decimal("100"),
                 trading_pairs: Optional[List[str]] = None, trading_required: bool = True):
        self._api_key = binance_tr_api_key
        self._api_secret = binance_tr_api_secret
        self._trading_pairs = trading_pairs or []
        self._trading_required = trading_required
        self._maker_fee = Decimal("0.0015")
        self._taker_fee = Decimal("0.0015")
        super().__init__(balance_asset_limit, rate_limits_share_pct)
        self._real_time_balance_update = False

    @property
    def authenticator(self):
        return BinanceTRAuth(self._api_key, self._api_secret, self._time_synchronizer)

    @property
    def name(self): return CONSTANTS.EXCHANGE_NAME
    @property
    def domain(self): return CONSTANTS.DEFAULT_DOMAIN
    @property
    def rate_limits_rules(self): return CONSTANTS.RATE_LIMITS
    @property
    def client_order_id_max_length(self): return CONSTANTS.MAX_ORDER_ID_LEN
    @property
    def client_order_id_prefix(self): return CONSTANTS.HBOT_ORDER_ID_PREFIX
    @property
    def trading_rules_request_path(self): return CONSTANTS.SYMBOLS_PATH_URL
    @property
    def trading_pairs_request_path(self): return CONSTANTS.SYMBOLS_PATH_URL
    @property
    def check_network_request_path(self): return CONSTANTS.SERVER_TIME_PATH_URL
    @property
    def trading_pairs(self): return self._trading_pairs
    @property
    def is_cancel_request_in_exchange_synchronous(self): return True
    @property
    def is_trading_required(self): return self._trading_required

    def supported_order_types(self):
        return [OrderType.LIMIT, OrderType.LIMIT_MAKER, OrderType.MARKET]

    def _create_web_assistants_factory(self):
        return web_utils.build_api_factory(self._throttler, self._time_synchronizer, auth=self._auth)

    def _create_order_book_data_source(self):
        return BinanceTRAPIOrderBookDataSource(self._trading_pairs, self, self._web_assistants_factory)

    def _create_user_stream_data_source(self): return BinanceTRAPIUserStreamDataSource()

    def _is_request_exception_related_to_time_synchronizer(self, request_exception: Exception):
        return "timestamp" in str(request_exception).lower() or "-1021" in str(request_exception)

    def _is_order_not_found_during_status_update_error(self, status_update_exception: Exception):
        return "not found" in str(status_update_exception).lower() or "-2013" in str(status_update_exception)

    def _is_order_not_found_during_cancelation_error(self, cancelation_exception: Exception):
        return self._is_order_not_found_during_status_update_error(cancelation_exception)

    @staticmethod
    def _order_type(order_type: OrderType) -> int:
        return {OrderType.LIMIT: CONSTANTS.ORDER_TYPE_LIMIT,
                OrderType.LIMIT_MAKER: CONSTANTS.ORDER_TYPE_LIMIT_MAKER,
                OrderType.MARKET: CONSTANTS.ORDER_TYPE_MARKET}[order_type]

    async def _place_order(self, order_id: str, trading_pair: str, amount: Decimal,
                           trade_type: TradeType, order_type: OrderType, price: Decimal, **kwargs) -> Tuple[str, float]:
        symbol = await self.exchange_symbol_associated_to_pair(trading_pair)
        payload = {"symbol": symbol, "side": CONSTANTS.SIDE_BUY if trade_type is TradeType.BUY else CONSTANTS.SIDE_SELL,
                   "type": self._order_type(order_type), "quantity": utils.decimal_to_api(amount),
                   "clientId": order_id, "selfTradePreventionMode": 2}
        if order_type in {OrderType.LIMIT, OrderType.LIMIT_MAKER}:
            payload["price"] = utils.decimal_to_api(price)
            payload["timeInForce"] = (CONSTANTS.TIME_IN_FORCE_GTC if order_type is OrderType.LIMIT
                                       else CONSTANTS.TIME_IN_FORCE_GTX)
        response = await self._api_post(path_url=CONSTANTS.ORDER_PATH_URL, data=payload,
                                        is_auth_required=True, limit_id=CONSTANTS.ORDER_PATH_URL)
        data = unwrap_response(response)
        return str(data["orderId"]), float(data.get("createTime", response.get("timestamp", 0))) * 1e-3

    async def _place_cancel(self, order_id: str, tracked_order: InFlightOrder):
        exchange_order_id = await tracked_order.get_exchange_order_id()
        response = await self._api_post(path_url=CONSTANTS.ORDER_CANCEL_PATH_URL,
                                        data={"orderId": exchange_order_id},
                                        is_auth_required=True, limit_id=CONSTANTS.ORDER_CANCEL_PATH_URL)
        # The current documentation's successful cancel example still shows
        # status=NEW, so endpoint success + matching ID is authoritative.
        return str(unwrap_response(response).get("orderId")) == str(exchange_order_id)

    async def _request_order_status(self, tracked_order: InFlightOrder) -> OrderUpdate:
        exchange_order_id = await tracked_order.get_exchange_order_id()
        response = await self._api_get(path_url=CONSTANTS.ORDER_DETAIL_PATH_URL,
                                       params={"orderId": exchange_order_id}, is_auth_required=True,
                                       limit_id=CONSTANTS.ORDER_DETAIL_PATH_URL)
        data = unwrap_response(response)
        status = int(data["status"])
        return OrderUpdate(trading_pair=tracked_order.trading_pair,
                           update_timestamp=float(response.get("timestamp", data.get("createTime", 0))) * 1e-3,
                           new_state=CONSTANTS.ORDER_STATE[status], client_order_id=tracked_order.client_order_id,
                           exchange_order_id=exchange_order_id)

    async def _all_trade_updates_for_order(self, order: InFlightOrder) -> List[TradeUpdate]:
        exchange_order_id = await order.get_exchange_order_id()
        symbol = await self.exchange_symbol_associated_to_pair(order.trading_pair)
        response = await self._api_get(path_url=CONSTANTS.TRADES_PATH_URL,
                                       params={"symbol": symbol, "orderId": exchange_order_id},
                                       is_auth_required=True, limit_id=CONSTANTS.TRADES_PATH_URL)
        result = []
        for row in iter_fills(response, exchange_order_id):
            qty, price = Decimal(str(row["qty"])), Decimal(str(row["price"]))
            commission = Decimal(str(row.get("commission", "0")))
            fee_asset = str(row.get("commissionAsset", order.quote_asset))
            result.append(TradeUpdate(
                trade_id=str(row["tradeId"]), client_order_id=order.client_order_id,
                exchange_order_id=exchange_order_id, trading_pair=order.trading_pair,
                fee=DeductedFromReturnsTradeFee(flat_fees=[TokenAmount(fee_asset, commission)]),
                fill_base_amount=qty, fill_quote_amount=Decimal(str(row.get("quoteQty", qty * price))),
                fill_price=price, fill_timestamp=float(row["time"]) * 1e-3))
        return result

    async def _update_balances(self):
        response = await self._api_get(path_url=CONSTANTS.ACCOUNT_PATH_URL, is_auth_required=True,
                                       limit_id=CONSTANTS.ACCOUNT_PATH_URL)
        local, remote = set(self._account_balances), set()
        for item in parse_balances(response):
            self._account_available_balances[item.asset] = item.available
            self._account_balances[item.asset] = item.total
            remote.add(item.asset)
        for asset in local - remote:
            self._account_available_balances.pop(asset, None)
            self._account_balances.pop(asset, None)

    async def _update_trading_fees(self):
        response = await self._api_get(path_url=CONSTANTS.ACCOUNT_PATH_URL, is_auth_required=True,
                                       limit_id=CONSTANTS.ACCOUNT_PATH_URL)
        self._maker_fee, self._taker_fee = parse_fee_rates(response)

    def _get_fee(self, base_currency: str, quote_currency: str, order_type: OrderType,
                 order_side: TradeType, amount: Decimal, price: Decimal = s_decimal_NaN,
                 is_maker: Optional[bool] = None):
        maker = order_type is OrderType.LIMIT_MAKER if is_maker is None else is_maker
        return DeductedFromReturnsTradeFee(percent=self._maker_fee if maker else self._taker_fee)

    async def _format_trading_rules(self, exchange_info: Dict[str, Any]) -> List[TradingRule]:
        rules = []
        for info in unwrap_response(exchange_info).get("list", []):
            try:
                parsed = utils.parse_trading_rule(info)
                rules.append(TradingRule(parsed.trading_pair, min_order_size=parsed.min_order_size,
                                         max_order_size=parsed.max_order_size,
                                         min_price_increment=parsed.price_increment,
                                         min_base_amount_increment=parsed.amount_increment,
                                         min_notional_size=parsed.min_notional))
            except Exception:
                self.logger().exception(f"Error parsing Binance TR trading rule {info}")
        return rules

    def _initialize_trading_pair_symbols_from_exchange_info(self, exchange_info: Dict[str, Any]):
        mapping = bidict()
        for info in unwrap_response(exchange_info).get("list", []):
            if utils.is_exchange_information_valid(info):
                parsed = utils.parse_trading_rule(info)
                mapping[parsed.symbol] = parsed.trading_pair
        self._set_trading_pair_symbol_map(mapping)

    async def _get_last_traded_price(self, trading_pair: str) -> float:
        symbol = utils.api_symbol(await self.exchange_symbol_associated_to_pair(trading_pair))
        response = await self._api_get(path_url=CONSTANTS.TICKER_PATH_URL, params={"symbol": symbol},
                                       limit_id=CONSTANTS.TICKER_PATH_URL)
        data = unwrap_response(response)
        if isinstance(data, list): data = data[0]
        return float(data["price"])

    async def _user_stream_event_listener(self):
        while True: await asyncio.sleep(3600)
