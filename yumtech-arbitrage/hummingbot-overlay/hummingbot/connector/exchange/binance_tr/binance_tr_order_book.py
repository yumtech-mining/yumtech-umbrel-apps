from typing import Dict, Optional

from hummingbot.core.data_type.common import TradeType
from hummingbot.core.data_type.order_book import OrderBook
from hummingbot.core.data_type.order_book_message import OrderBookMessage, OrderBookMessageType


class BinanceTROrderBook(OrderBook):
    @classmethod
    def snapshot_message_from_exchange(cls, msg: Dict, timestamp: float,
                                       metadata: Optional[Dict] = None) -> OrderBookMessage:
        content = dict(msg)
        if metadata:
            content.update(metadata)
        return OrderBookMessage(
            OrderBookMessageType.SNAPSHOT,
            {"trading_pair": content["trading_pair"], "update_id": int(content["lastUpdateId"]),
             "bids": content["bids"], "asks": content["asks"]},
            timestamp=timestamp,
        )

    @classmethod
    def diff_message_from_exchange(cls, msg: Dict, timestamp: float,
                                   metadata: Optional[Dict] = None) -> OrderBookMessage:
        content = dict(msg)
        if metadata:
            content.update(metadata)
        return OrderBookMessage(
            OrderBookMessageType.DIFF,
            {"trading_pair": content["trading_pair"],
             "first_update_id": int(content["U"]), "update_id": int(content["u"]),
             "bids": content["b"], "asks": content["a"]},
            timestamp=timestamp,
        )

    @classmethod
    def trade_message_from_exchange(cls, msg: Dict,
                                    metadata: Optional[Dict] = None) -> OrderBookMessage:
        content = dict(msg)
        if metadata:
            content.update(metadata)
        timestamp_ms = int(content["E"])
        return OrderBookMessage(
            OrderBookMessageType.TRADE,
            {"trading_pair": content["trading_pair"],
             "trade_type": float(TradeType.SELL.value if content["m"] else TradeType.BUY.value),
             "trade_id": content["t"], "update_id": timestamp_ms,
             "price": content["p"], "amount": content["q"]},
            timestamp=timestamp_ms * 1e-3,
        )
