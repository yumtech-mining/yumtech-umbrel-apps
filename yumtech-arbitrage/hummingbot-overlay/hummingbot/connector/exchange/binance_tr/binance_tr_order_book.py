from typing import Dict, Optional

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

