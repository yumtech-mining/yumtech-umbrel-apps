import asyncio
import json
import logging
import time
from decimal import Decimal
from typing import Iterable

import websockets

from .domain import Level
from .exchanges import Market


log = logging.getLogger(__name__)


class OrderBookStore:
    """Small, bounded top-of-book cache shared by the scanner and WS workers."""

    def __init__(self, max_levels: int = 100):
        self.max_levels = max_levels
        self._books: dict[tuple[str, str], dict] = {}
        self.status = {
            "btcturk": {"connected": False, "last_message_ms": None, "error": None},
            "binance_tr": {"connected": False, "last_message_ms": None, "error": None},
        }

    @staticmethod
    def _side(levels: Iterable, deleted: bool = False) -> dict[Decimal, Decimal]:
        result = {}
        for level in levels:
            if isinstance(level, dict):
                raw_price, raw_amount = level.get("P"), level.get("A")
            elif hasattr(level, "price") and hasattr(level, "amount"):
                # REST adapters return domain ``Level`` objects, while the
                # websocket handlers use exchange-native tuples/dicts. Keep
                # both representations in the bounded cache so a REST
                # fallback is immediately available to PaperTrade too.
                raw_price, raw_amount = level.price, level.amount
            else:
                raw_price, raw_amount = level[0], level[1]
            price = Decimal(str(raw_price))
            amount = Decimal("0") if deleted else Decimal(str(raw_amount))
            if isinstance(level, dict) and int(level.get("CP", 0)) == 3:
                amount = Decimal("0")
            if amount > 0:
                result[price] = amount
        return result

    def replace(self, exchange: str, base: str, asks: Iterable, bids: Iterable,
                update_id: int | None = None) -> None:
        now_ms = int(time.time() * 1000)
        self._books[(exchange, base)] = {
            "asks": self._side(asks), "bids": self._side(bids),
            "update_id": update_id, "updated_ms": now_ms,
        }
        self.mark_message(exchange, now_ms)

    def apply(self, exchange: str, base: str, asks: Iterable, bids: Iterable,
              update_id: int | None = None, deleted: bool = False,
              require_contiguous: bool = False) -> bool:
        book = self._books.get((exchange, base))
        if book is None:
            return False
        previous = book.get("update_id")
        if update_id is not None and previous is not None and update_id <= previous:
            return False
        if require_contiguous and update_id is not None and previous is not None and update_id != previous + 1:
            # Never calculate against a book with an unknown missing delta.
            self._books.pop((exchange, base), None)
            return False
        for name, levels in (("asks", asks), ("bids", bids)):
            for level in levels:
                price = Decimal(str(level.get("P") if isinstance(level, dict) else level[0]))
                amount = Decimal("0") if deleted else Decimal(str(level.get("A") if isinstance(level, dict) else level[1]))
                if isinstance(level, dict) and int(level.get("CP", 0)) == 3:
                    amount = Decimal("0")
                if amount <= 0:
                    book[name].pop(price, None)
                else:
                    book[name][price] = amount
        book["update_id"] = update_id if update_id is not None else previous
        book["updated_ms"] = int(time.time() * 1000)
        self.mark_message(exchange, book["updated_ms"])
        return True

    def get(self, exchange: str, base: str, max_age_ms: int = 10_000):
        book = self._books.get((exchange, base))
        if not book or int(time.time() * 1000) - book["updated_ms"] > max_age_ms:
            return None
        asks = [Level(price, amount) for price, amount in sorted(book["asks"].items())[:self.max_levels]]
        bids = [Level(price, amount) for price, amount in sorted(book["bids"].items(), reverse=True)[:self.max_levels]]
        return asks, bids

    def mark_connected(self, exchange: str, connected: bool, error: str | None = None):
        self.status[exchange]["connected"] = connected
        self.status[exchange]["error"] = error

    def mark_message(self, exchange: str, timestamp_ms: int):
        self.status[exchange].update(connected=True, last_message_ms=timestamp_ms, error=None)

    def health(self) -> dict:
        now_ms = int(time.time() * 1000)
        return {name: {**state,
                       "age_ms": None if state["last_message_ms"] is None else now_ms - state["last_message_ms"]}
                for name, state in self.status.items()}


class PublicMarketStreams:
    BTCTURK_URL = "wss://ws-feed-pro.btcturk.com/"
    BINANCE_TR_URL = "wss://stream-cloud.binance.tr/stream?streams="

    def __init__(self, store: OrderBookStore):
        self.store = store
        self._tasks: list[asyncio.Task] = []
        self._signature: tuple = ()

    def sync(self, bt_markets: dict[str, Market], bn_markets: dict[str, Market], bases: list[str]):
        signature = tuple((base, bt_markets[base].symbol, bn_markets[base].symbol) for base in bases)
        if signature == self._signature:
            return
        self.stop()
        self._signature = signature
        if bases:
            self._tasks = [asyncio.create_task(self._btcturk(bt_markets, bases)),
                           asyncio.create_task(self._binance_tr(bn_markets, bases))]

    def stop(self):
        for task in self._tasks:
            task.cancel()
        self._tasks = []
        self.store.mark_connected("btcturk", False)
        self.store.mark_connected("binance_tr", False)

    async def _btcturk(self, markets: dict[str, Market], bases: list[str]):
        symbol_to_base = {markets[base].symbol.upper(): base for base in bases}
        delay = 1
        while True:
            try:
                async with websockets.connect(self.BTCTURK_URL, ping_interval=20, ping_timeout=20,
                                              open_timeout=10, proxy=None) as ws:
                    for symbol in symbol_to_base:
                        for channel in ("orderbook", "obdiff"):
                            await ws.send(json.dumps([151, {"type": 151, "channel": channel,
                                                           "event": symbol, "join": True}]))
                    self.store.mark_connected("btcturk", True)
                    delay = 1
                    async for raw in ws:
                        message = json.loads(raw)
                        if not isinstance(message, list) or len(message) != 2 or message[0] not in (431, 432):
                            continue
                        payload = message[1]
                        base = symbol_to_base.get(str(payload.get("PS", "")).upper())
                        if not base:
                            continue
                        update_id = int(payload["CS"])
                        if message[0] == 431:
                            self.store.replace("btcturk", base, payload.get("AO", []), payload.get("BO", []), update_id)
                        else:
                            applied = self.store.apply(
                                "btcturk", base, payload.get("AO", []), payload.get("BO", []),
                                update_id, int(payload.get("CP", 0)) == 3, require_contiguous=True)
                            if not applied and self.store.get("btcturk", base) is None:
                                raise ConnectionError("BTCTurk order book sequence gap")
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self.store.mark_connected("btcturk", False, type(exc).__name__)
                log.warning("BTCTurk websocket disconnected: %s", type(exc).__name__)
                await asyncio.sleep(delay)
                delay = min(delay * 2, 30)

    async def _binance_tr(self, markets: dict[str, Market], bases: list[str]):
        streams = {f"{markets[base].symbol.lower()}@depth20@100ms": base for base in bases}
        url = self.BINANCE_TR_URL + "/".join(streams)
        delay = 1
        while True:
            try:
                async with websockets.connect(url, ping_interval=120, ping_timeout=30,
                                              open_timeout=10, proxy=None) as ws:
                    self.store.mark_connected("binance_tr", True)
                    delay = 1
                    async for raw in ws:
                        message = json.loads(raw)
                        stream = str(message.get("stream", ""))
                        payload = message.get("data", {})
                        base = streams.get(stream)
                        if base and "lastUpdateId" in payload:
                            self.store.replace("binance_tr", base, payload.get("asks", []), payload.get("bids", []),
                                               int(payload["lastUpdateId"]))
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self.store.mark_connected("binance_tr", False, type(exc).__name__)
                log.warning("Binance TR websocket disconnected: %s", type(exc).__name__)
                await asyncio.sleep(delay)
                delay = min(delay * 2, 30)
