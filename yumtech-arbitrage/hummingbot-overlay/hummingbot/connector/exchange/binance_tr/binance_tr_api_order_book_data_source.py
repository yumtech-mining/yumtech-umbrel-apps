import asyncio
import time
from typing import Dict, List, Optional

from hummingbot.core.data_type.order_book_message import OrderBookMessage
from hummingbot.core.data_type.order_book_tracker_data_source import OrderBookTrackerDataSource
from hummingbot.core.web_assistant.connections.data_types import RESTMethod, WSJSONRequest
from hummingbot.core.web_assistant.web_assistants_factory import WebAssistantsFactory
from hummingbot.core.web_assistant.ws_assistant import WSAssistant

from . import binance_tr_constants as CONSTANTS
from . import binance_tr_web_utils as web_utils
from .binance_tr_order_book import BinanceTROrderBook
from .binance_tr_parsers import unwrap_response
from .binance_tr_utils import api_symbol


class BinanceTRAPIOrderBookDataSource(OrderBookTrackerDataSource):
    HEARTBEAT_INTERVAL = 30.0

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

    async def _connected_websocket_assistant(self) -> WSAssistant:
        ws = await self._api_factory.get_ws_assistant()
        await ws.connect(ws_url=CONSTANTS.PUBLIC_WS_URL, ping_timeout=self.HEARTBEAT_INTERVAL)
        return ws

    async def _subscribe_channels(self, ws: WSAssistant):
        symbols = [api_symbol(await self._connector.exchange_symbol_associated_to_pair(pair)).lower()
                   for pair in self._trading_pairs]
        await ws.send(WSJSONRequest(payload={
            "method": "SUBSCRIBE", "params": [f"{symbol}@depth@100ms" for symbol in symbols], "id": 1}))
        await ws.send(WSJSONRequest(payload={
            "method": "SUBSCRIBE", "params": [f"{symbol}@trade" for symbol in symbols], "id": 2}))

    def _channel_originating_message(self, event_message):
        if "result" in event_message:
            return ""
        event_type = event_message.get("e")
        if event_type == "depthUpdate":
            return self._diff_messages_queue_key
        if event_type == "trade":
            return self._trade_messages_queue_key
        return ""

    async def _parse_trade_message(self, raw_message, message_queue):
        pair = await self._connector.trading_pair_associated_to_exchange_symbol(raw_message["s"])
        message_queue.put_nowait(BinanceTROrderBook.trade_message_from_exchange(
            raw_message, {"trading_pair": pair}))

    async def _parse_order_book_diff_message(self, raw_message, message_queue):
        pair = await self._connector.trading_pair_associated_to_exchange_symbol(raw_message["s"])
        timestamp = float(raw_message.get("E", time.time() * 1e3)) * 1e-3
        message_queue.put_nowait(BinanceTROrderBook.diff_message_from_exchange(
            raw_message, timestamp, {"trading_pair": pair}))

    async def _parse_order_book_snapshot_message(self, raw_message, message_queue): return None
