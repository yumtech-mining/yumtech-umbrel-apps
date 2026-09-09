import asyncio
import time
from typing import Dict, List, Optional

from hummingbot.core.data_type.order_book_message import OrderBookMessage
from hummingbot.core.data_type.order_book_tracker_data_source import OrderBookTrackerDataSource
from hummingbot.core.web_assistant.connections.data_types import RESTMethod
from hummingbot.core.web_assistant.web_assistants_factory import WebAssistantsFactory

from . import binance_tr_constants as CONSTANTS
from . import binance_tr_web_utils as web_utils
from .binance_tr_order_book import BinanceTROrderBook
from .binance_tr_parsers import unwrap_response
from .binance_tr_utils import api_symbol


class BinanceTRAPIOrderBookDataSource(OrderBookTrackerDataSource):
    SNAPSHOT_INTERVAL = 1.0

    def __init__(self, trading_pairs: List[str], connector, api_factory: WebAssistantsFactory):
        super().__init__(trading_pairs)
        self._connector = connector
        self._api_factory = api_factory

    async def get_last_traded_prices(self, trading_pairs: List[str], domain: Optional[str] = None) -> Dict[str, float]:
        return await self._connector.get_last_traded_prices(trading_pairs=trading_pairs)

    async def _order_book_snapshot(self, trading_pair: str) -> OrderBookMessage:
        symbol = api_symbol(await self._connector.exchange_symbol_associated_to_pair(trading_pair))
        assistant = await self._api_factory.get_rest_assistant()
        response = await assistant.execute_request(
            url=web_utils.public_rest_url(CONSTANTS.DEPTH_PATH_URL),
            params={"symbol": symbol, "limit": 100}, method=RESTMethod.GET,
            throttler_limit_id=CONSTANTS.DEPTH_PATH_URL,
        )
        snapshot = unwrap_response(response)
        timestamp = float(response.get("timestamp", time.time() * 1e3)) * 1e-3
        return BinanceTROrderBook.snapshot_message_from_exchange(
            snapshot, timestamp, {"trading_pair": trading_pair})

    async def listen_for_order_book_snapshots(self, ev_loop, output: asyncio.Queue):
        while True:
            for pair in self._trading_pairs:
                output.put_nowait(await self._order_book_snapshot(pair))
                await self._sleep(self.SNAPSHOT_INTERVAL)

    async def listen_for_subscriptions(self):
        while True: await self._sleep(3600)

    async def listen_for_order_book_diffs(self, ev_loop, output: asyncio.Queue):
        while True: await self._sleep(3600)

    async def listen_for_trades(self, ev_loop, output: asyncio.Queue):
        while True: await self._sleep(3600)

    async def _connected_websocket_assistant(self): raise NotImplementedError
    async def _subscribe_channels(self, ws): raise NotImplementedError
    def _channel_originating_message(self, event_message): return ""
    async def _parse_trade_message(self, raw_message, message_queue): return None
    async def _parse_order_book_diff_message(self, raw_message, message_queue): return None
    async def _parse_order_book_snapshot_message(self, raw_message, message_queue): return None

