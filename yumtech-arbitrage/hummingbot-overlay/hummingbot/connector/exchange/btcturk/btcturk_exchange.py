import asyncio
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple

from bidict import bidict

from hummingbot.connector.constants import s_decimal_NaN
from hummingbot.connector.exchange_py_base import ExchangePyBase
from hummingbot.connector.trading_rule import TradingRule
from hummingbot.core.data_type.common import OrderType, TradeType
from hummingbot.core.data_type.in_flight_order import InFlightOrder, OrderUpdate, TradeUpdate
from hummingbot.core.data_type.trade_fee import TokenAmount, TradeFeeBase
from hummingbot.core.utils.estimate_fee import build_trade_fee
from hummingbot.core.web_assistant.connections.data_types import RESTMethod

from . import btcturk_constants as CONSTANTS
from . import btcturk_utils as utils
from . import btcturk_web_utils as web_utils
from .btcturk_api_order_book_data_source import BtcTurkAPIOrderBookDataSource
from .btcturk_api_user_stream_data_source import BtcTurkAPIUserStreamDataSource
from .btcturk_auth import BtcTurkAuth
from .btcturk_parsers import (
    iter_order_trades,
    normalize_order_status,
    order_id,
    order_timestamp,
    parse_balances,
    trade_id,
    unwrap_response,
)


class BtcTurkExchange(ExchangePyBase):
    UPDATE_ORDER_STATUS_MIN_INTERVAL = 5.0

    web_utils = web_utils

    def __init__(
        self,
        btcturk_api_key: str,
        btcturk_api_secret: str,
        balance_asset_limit: Optional[Dict[str, Dict[str, Decimal]]] = None,
        rate_limits_share_pct: Decimal = Decimal("100"),
        trading_pairs: Optional[List[str]] = None,
        trading_required: bool = True,
    ):
        self._api_key = btcturk_api_key
        self._api_secret = btcturk_api_secret
        self._trading_pairs = trading_pairs or []
        self._trading_required = trading_required
        super().__init__(balance_asset_limit, rate_limits_share_pct)
        self._real_time_balance_update = False

    @property
    def authenticator(self):
        return BtcTurkAuth(self._api_key, self._api_secret, self._time_synchronizer)

    @property
    def name(self):
        return CONSTANTS.EXCHANGE_NAME

    @property
    def domain(self):
        return CONSTANTS.DEFAULT_DOMAIN

    @property
    def rate_limits_rules(self):
        return CONSTANTS.RATE_LIMITS

    @property
    def client_order_id_max_length(self):
        return CONSTANTS.MAX_ORDER_ID_LEN

    @property
    def client_order_id_prefix(self):
        return CONSTANTS.HBOT_ORDER_ID_PREFIX

    @property
    def trading_rules_request_path(self):
        return CONSTANTS.EXCHANGE_INFO_PATH_URL

    @property
    def trading_pairs_request_path(self):
        return CONSTANTS.EXCHANGE_INFO_PATH_URL

    @property
    def check_network_request_path(self):
        return CONSTANTS.PING_PATH_URL

    @property
    def trading_pairs(self):
        return self._trading_pairs

    @property
    def is_cancel_request_in_exchange_synchronous(self):
        return True

    @property
    def is_trading_required(self):
        return self._trading_required

    def supported_order_types(self):
        # Market buy uses quote quantity at BTCTurk and is deliberately kept out
        # of generic Hummingbot order submission. Recovery handles it explicitly.
        return [OrderType.LIMIT]

    def _create_web_assistants_factory(self):
        return web_utils.build_api_factory(throttler=self._throttler, auth=self._auth)

    def _create_order_book_data_source(self):
        return BtcTurkAPIOrderBookDataSource(self._trading_pairs, self, self._web_assistants_factory)

    def _create_user_stream_data_source(self):
        return BtcTurkAPIUserStreamDataSource()

    def _is_request_exception_related_to_time_synchronizer(self, request_exception: Exception):
        return "timestamp" in str(request_exception).lower() or "stamp" in str(request_exception).lower()

    def _is_order_not_found_during_status_update_error(self, status_update_exception: Exception):
        return "not found" in str(status_update_exception).lower()

    def _is_order_not_found_during_cancelation_error(self, cancelation_exception: Exception):
        return self._is_order_not_found_during_status_update_error(cancelation_exception)

    async def _place_order(self, order_id_value: str, trading_pair: str, amount: Decimal,
                           trade_type: TradeType, order_type: OrderType, price: Decimal, **kwargs) -> Tuple[str, float]:
        if order_type is not OrderType.LIMIT:
            raise ValueError("BTCTurk generic connector accepts LIMIT orders only")
        symbol = await self.exchange_symbol_associated_to_pair(trading_pair)
        payload = utils.build_limit_order_payload(
            client_order_id=order_id_value,
            symbol=symbol,
            side="buy" if trade_type is TradeType.BUY else "sell",
            quantity=amount,
            price=price,
        )
        response = unwrap_response(await self._api_post(
            path_url=CONSTANTS.ORDER_PATH_URL,
            data=payload,
            is_auth_required=True,
            limit_id=CONSTANTS.ORDER_PATH_URL,
        ))
        return order_id(response), order_timestamp(response, self.current_timestamp)

    async def _place_cancel(self, order_id_value: str, tracked_order: InFlightOrder):
        exchange_order_id = await tracked_order.get_exchange_order_id()
        response = await self._api_delete(
            path_url=CONSTANTS.ORDER_PATH_URL,
            params={"id": exchange_order_id},
            is_auth_required=True,
            limit_id=CONSTANTS.ORDER_PATH_URL,
        )
        return bool(unwrap_response(response))

    async def _request_order_status(self, tracked_order: InFlightOrder) -> OrderUpdate:
        exchange_order_id = await tracked_order.get_exchange_order_id()
        row = unwrap_response(await self._api_get(
            path_url=f"{CONSTANTS.ORDER_PATH_URL}/{exchange_order_id}",
            is_auth_required=True,
            limit_id=CONSTANTS.ORDER_PATH_URL,
        ))
        status = normalize_order_status(row.get("status"))
        return OrderUpdate(
            trading_pair=tracked_order.trading_pair,
            update_timestamp=order_timestamp(row, self.current_timestamp),
            new_state=CONSTANTS.ORDER_STATE[status],
            client_order_id=tracked_order.client_order_id,
            exchange_order_id=exchange_order_id,
        )

    async def _all_trade_updates_for_order(self, order: InFlightOrder) -> List[TradeUpdate]:
        exchange_order_id = await order.get_exchange_order_id()
        symbol = await self.exchange_symbol_associated_to_pair(order.trading_pair)
        response = await self._api_get(
            path_url=CONSTANTS.USER_TRADES_PATH_URL,
            params={"pairSymbol": symbol},
            is_auth_required=True,
            limit_id=CONSTANTS.USER_TRADES_PATH_URL,
        )
        updates = []
        for row in iter_order_trades(response, exchange_order_id):
            amount = Decimal(str(row.get("amount", row.get("quantity", "0"))))
            price = Decimal(str(row["price"]))
            fee_amount = Decimal(str(row.get("fee", row.get("commission", "0"))))
            fee = TradeFeeBase.new_spot_fee(
                fee_schema=self.trade_fee_schema(),
                trade_type=order.trade_type,
                flat_fees=[TokenAmount(token=order.quote_asset, amount=fee_amount)],
            )
            updates.append(TradeUpdate(
                trade_id=trade_id(row),
                client_order_id=order.client_order_id,
                exchange_order_id=exchange_order_id,
                trading_pair=order.trading_pair,
                fee=fee,
                fill_base_amount=amount,
                fill_quote_amount=amount * price,
                fill_price=price,
                fill_timestamp=order_timestamp(row, self.current_timestamp),
            ))
        return updates

    async def _update_balances(self):
        response = await self._api_get(
            path_url=CONSTANTS.BALANCES_PATH_URL,
            is_auth_required=True,
            limit_id=CONSTANTS.BALANCES_PATH_URL,
        )
        local_assets = set(self._account_balances)
        remote_assets = set()
        for item in parse_balances(response):
            self._account_balances[item.asset] = item.total
            self._account_available_balances[item.asset] = item.available
            remote_assets.add(item.asset)
        for asset in local_assets - remote_assets:
            self._account_balances.pop(asset, None)
            self._account_available_balances.pop(asset, None)

    async def _format_trading_rules(self, exchange_info: Dict[str, Any]) -> List[TradingRule]:
        symbols = unwrap_response(exchange_info).get("symbols", [])
        rules = []
        for info in symbols:
            try:
                parsed = utils.parse_trading_rule(info)
                rules.append(TradingRule(
                    trading_pair=parsed.trading_pair,
                    min_order_size=parsed.min_order_size,
                    min_price_increment=parsed.min_price_increment,
                    min_base_amount_increment=parsed.min_base_amount_increment,
                    min_notional_size=parsed.min_notional_size,
                ))
            except Exception:
                self.logger().exception(f"Error parsing BTCTurk trading rule {info}")
        return rules

    def _initialize_trading_pair_symbols_from_exchange_info(self, exchange_info: Dict[str, Any]):
        mapping = bidict()
        for info in unwrap_response(exchange_info).get("symbols", []):
            if utils.is_exchange_information_valid(info):
                mapping[str(info["name"]).upper()] = utils.trading_pair_from_exchange_info(info)
        self._set_trading_pair_symbol_map(mapping)

    async def _get_last_traded_price(self, trading_pair: str) -> float:
        symbol = await self.exchange_symbol_associated_to_pair(trading_pair)
        response = unwrap_response(await self._api_get(
            path_url=CONSTANTS.TICKER_PATH_URL,
            params={"pairSymbol": symbol},
            limit_id=CONSTANTS.TICKER_PATH_URL,
        ))
        row = response[0] if isinstance(response, list) else response
        return float(row["last"])

    def _get_fee(self, base_currency: str, quote_currency: str, order_type: OrderType,
                 order_side: TradeType, amount: Decimal, price: Decimal = s_decimal_NaN,
                 is_maker: Optional[bool] = None):
        return build_trade_fee(
            self.name,
            bool(is_maker),
            base_currency=base_currency,
            quote_currency=quote_currency,
            order_type=order_type,
            order_side=order_side,
            amount=amount,
            price=price,
        )

    async def _update_trading_fees(self):
        # BTCTurk's documented REST surface does not expose the authenticated
        # account fee tier. Live qualification supplies and verifies it from
        # the user's profile; the connector default remains conservative.
        return None

    async def _user_stream_event_listener(self):
        while True:
            await asyncio.sleep(3600)
