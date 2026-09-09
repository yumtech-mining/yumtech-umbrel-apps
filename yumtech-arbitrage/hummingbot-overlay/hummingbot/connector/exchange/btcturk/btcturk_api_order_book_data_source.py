import asyncio
import time
from typing import Dict, List, Optional

from hummingbot.core.data_type.order_book_message import OrderBookMessage
from hummingbot.core.data_type.order_book_tracker_data_source import OrderBookTrackerDataSource
from hummingbot.core.web_assistant.connections.data_types import RESTMethod
from hummingbot.core.web_assistant.web_assistants_factory import WebAssistantsFactory

from . import btcturk_constants as CONSTANTS
from . import btcturk_web_utils as web_utils
from .btcturk_order_book import BtcTurkOrderBook
from .btcturk_parsers import unwrap_response


class BtcTurkAPIOrderBookDataSource(OrderBookTrackerDataSource):
    """Rate-limited REST snapshots; WebSocket deltas will replace this fallback."""

    SNAPSHOT_INTERVAL = 2.0

    def __init__(self, trading_pairs: List[str], connector, api_factory: WebAssistantsFactory):
        super().__init__(trading_pairs)
        self._connector = connector
        self._api_factory = api_factory

    async def get_last_traded_prices(self, trading_pairs: List[str], domain: Optional[str] = None) -> Dict[str, float]:
        return await self._connector.get_last_traded_prices(trading_pairs=trading_pairs)

    async def get_snapshot(self, trading_pair: str, limit: int = 100) -> Dict:
        symbol = await self._connector.exchange_symbol_associated_to_pair(trading_pair)
        assistant = await self._api_factory.get_rest_assistant()
        response = await assistant.execute_request(
            url=web_utils.public_rest_url(CONSTANTS.ORDER_BOOK_PATH_URL),
            params={"pairSymbol": symbol, "limit": limit},
            method=RESTMethod.GET,
            throttler_limit_id=CONSTANTS.ORDER_BOOK_PATH_URL,
        )
        return unwrap_response(response)

    async def _order_book_snapshot(self, trading_pair: str) -> OrderBookMessage:
        snapshot = await self.get_snapshot(trading_pair)
        timestamp_ms = int(snapshot.get("timestamp", time.time() * 1e3))
        return BtcTurkOrderBook.snapshot_message_from_exchange(
            snapshot,
            timestamp=timestamp_ms * 1e-3,
            metadata={"trading_pair": trading_pair},
        )

    async def listen_for_order_book_snapshots(self, ev_loop, output: asyncio.Queue):
        while True:
            for trading_pair in self._trading_pairs:
                output.put_nowait(await self._order_book_snapshot(trading_pair))
                await self._sleep(self.SNAPSHOT_INTERVAL)

    async def listen_for_subscriptions(self):
        while True:
            await self._sleep(3600)

    async def listen_for_order_book_diffs(self, ev_loop, output: asyncio.Queue):
        while True:
            await self._sleep(3600)

    async def listen_for_trades(self, ev_loop, output: asyncio.Queue):
        while True:
            await self._sleep(3600)

    async def _connected_websocket_assistant(self):
        raise NotImplementedError

    async def _subscribe_channels(self, ws):
        raise NotImplementedError

    def _channel_originating_message(self, event_message):
        return ""

    async def _parse_trade_message(self, raw_message, message_queue):
        return None

    async def _parse_order_book_diff_message(self, raw_message, message_queue):
        return None

    async def _parse_order_book_snapshot_message(self, raw_message, message_queue):
        return None

