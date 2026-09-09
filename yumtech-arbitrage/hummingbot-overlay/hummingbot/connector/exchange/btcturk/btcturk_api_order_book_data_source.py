import asyncio
import time
from typing import Dict, List, Optional

from hummingbot.core.data_type.order_book_message import OrderBookMessage
from hummingbot.core.data_type.order_book_tracker_data_source import OrderBookTrackerDataSource
from hummingbot.core.web_assistant.connections.data_types import RESTMethod, WSJSONRequest
from hummingbot.core.web_assistant.web_assistants_factory import WebAssistantsFactory
from hummingbot.core.web_assistant.ws_assistant import WSAssistant

from . import btcturk_constants as CONSTANTS
from . import btcturk_web_utils as web_utils
from .btcturk_order_book import BtcTurkOrderBook
from .btcturk_parsers import unwrap_response


class BtcTurkAPIOrderBookDataSource(OrderBookTrackerDataSource):
    """Official 431/432 order book feed with hourly REST resynchronization."""

    HEARTBEAT_INTERVAL = 30.0

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

    async def _connected_websocket_assistant(self) -> WSAssistant:
        ws = await self._api_factory.get_ws_assistant()
        await ws.connect(ws_url=CONSTANTS.WSS_PUBLIC_URL, ping_timeout=self.HEARTBEAT_INTERVAL)
        return ws

    async def _subscribe_channels(self, ws: WSAssistant):
        for pair in self._trading_pairs:
            symbol = (await self._connector.exchange_symbol_associated_to_pair(pair)).upper()
            for channel in ("orderbook", "obdiff", "trade"):
                await ws.send(WSJSONRequest(payload=[151, {
                    "type": 151, "channel": channel, "event": symbol, "join": True}]))

    def _channel_originating_message(self, event_message):
        if not isinstance(event_message, list) or len(event_message) != 2:
            return ""
        message_type = int(event_message[0])
        if message_type == 431:
            return self._snapshot_messages_queue_key
        if message_type == 432:
            return self._diff_messages_queue_key
        if message_type == 422:
            return self._trade_messages_queue_key
        return ""

    async def _parse_trade_message(self, raw_message, message_queue):
        payload = raw_message[1]
        pair = await self._connector.trading_pair_associated_to_exchange_symbol(payload["PS"])
        message_queue.put_nowait(BtcTurkOrderBook.trade_message_from_exchange(
            payload, {"trading_pair": pair}))

    async def _parse_order_book_diff_message(self, raw_message, message_queue):
        payload = raw_message[1]
        pair = await self._connector.trading_pair_associated_to_exchange_symbol(payload["PS"])
        message_queue.put_nowait(BtcTurkOrderBook.diff_message_from_exchange(
            payload, time.time(), {"trading_pair": pair}))

    async def _parse_order_book_snapshot_message(self, raw_message, message_queue):
        payload = raw_message[1]
        pair = await self._connector.trading_pair_associated_to_exchange_symbol(payload["PS"])
        message_queue.put_nowait(BtcTurkOrderBook.ws_snapshot_message_from_exchange(
            payload, time.time(), {"trading_pair": pair}))
