from typing import Dict, Optional

from hummingbot.core.data_type.common import TradeType
from hummingbot.core.data_type.order_book import OrderBook
from hummingbot.core.data_type.order_book_message import OrderBookMessage, OrderBookMessageType


class BtcTurkOrderBook(OrderBook):
    @staticmethod
    def _levels(levels, deleted: bool = False):
        normalized = []
        for level in levels:
            if isinstance(level, dict):
                is_deleted = deleted or int(level.get("CP", 0)) == 3
                normalized.append([level["P"], "0" if is_deleted else level["A"]])
            else:
                normalized.append([level[0], "0" if deleted else level[1]])
        return normalized

    @classmethod
    def snapshot_message_from_exchange(
        cls, msg: Dict, timestamp: float, metadata: Optional[Dict] = None
    ) -> OrderBookMessage:
        content = dict(msg)
        if metadata:
            content.update(metadata)
        update_id = int(content.get("timestamp", timestamp * 1e3))
        return OrderBookMessage(
            OrderBookMessageType.SNAPSHOT,
            {
                "trading_pair": content["trading_pair"],
                "update_id": update_id,
                "bids": content["bids"],
                "asks": content["asks"],
            },
            timestamp=timestamp,
        )

    @classmethod
    def ws_snapshot_message_from_exchange(cls, msg: Dict, timestamp: float,
                                          metadata: Optional[Dict] = None) -> OrderBookMessage:
        content = dict(msg)
        if metadata:
            content.update(metadata)
        return OrderBookMessage(
            OrderBookMessageType.SNAPSHOT,
            {"trading_pair": content["trading_pair"], "update_id": int(content["CS"]),
             "bids": cls._levels(content.get("BO", [])),
             "asks": cls._levels(content.get("AO", []))},
            timestamp=timestamp,
        )

    @classmethod
    def diff_message_from_exchange(cls, msg: Dict, timestamp: float,
                                   metadata: Optional[Dict] = None) -> OrderBookMessage:
        content = dict(msg)
        if metadata:
            content.update(metadata)
        update_id = int(content["CS"])
        deleted = int(content.get("CP", 0)) == 3
        return OrderBookMessage(
            OrderBookMessageType.DIFF,
            {"trading_pair": content["trading_pair"], "first_update_id": update_id,
             "update_id": update_id, "bids": cls._levels(content.get("BO", []), deleted),
             "asks": cls._levels(content.get("AO", []), deleted)},
            timestamp=timestamp,
        )

    @classmethod
    def trade_message_from_exchange(cls, msg: Dict,
                                    metadata: Optional[Dict] = None) -> OrderBookMessage:
        content = dict(msg)
        if metadata:
            content.update(metadata)
        timestamp_ms = int(content["D"])
        return OrderBookMessage(
            OrderBookMessageType.TRADE,
            {"trading_pair": content["trading_pair"],
             "trade_type": float(TradeType.BUY.value if int(content["S"]) == 0 else TradeType.SELL.value),
             "trade_id": content["I"], "update_id": timestamp_ms,
             "price": content["P"], "amount": content["A"]},
            timestamp=timestamp_ms * 1e-3,
        )
