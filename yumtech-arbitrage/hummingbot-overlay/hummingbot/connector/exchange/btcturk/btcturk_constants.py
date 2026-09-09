from hummingbot.core.api_throttler.data_types import LinkedLimitWeightPair, RateLimit
from hummingbot.core.data_type.in_flight_order import OrderState

EXCHANGE_NAME = "btcturk"
DEFAULT_DOMAIN = "com"

REST_URL = "https://api.btcturk.com"
WSS_PUBLIC_URL = "wss://ws-feed-pro.btcturk.com"
WSS_PRIVATE_URL = "wss://ws-feed-pro.btcturk.com"

PUBLIC_API_VERSION = "/api/v2"
PRIVATE_API_VERSION = "/api/v1"

EXCHANGE_INFO_PATH_URL = "/server/exchangeinfo"
ORDER_BOOK_PATH_URL = "/orderbook"
TICKER_PATH_URL = "/ticker"
TRADES_PATH_URL = "/trades"
BALANCES_PATH_URL = "/users/balances"
ORDER_PATH_URL = "/order"
OPEN_ORDERS_PATH_URL = "/openOrders"
ALL_ORDERS_PATH_URL = "/allOrders"
USER_TRADES_PATH_URL = "/users/transactions/trade"

ORDER_STATE = {
    "untouched": OrderState.OPEN,
    "partial": OrderState.PARTIALLY_FILLED,
    "closed": OrderState.FILLED,
    "canceled": OrderState.CANCELED,
    "cancelled": OrderState.CANCELED,
    "rejected": OrderState.FAILED,
}

# Conservative defaults. They intentionally keep one process well below the
# published exchange ceiling and can be tightened without connector changes.
PUBLIC_POOL = "BTCTURK_PUBLIC"
PRIVATE_POOL = "BTCTURK_PRIVATE"
RATE_LIMITS = [
    RateLimit(limit_id=PUBLIC_POOL, limit=60, time_interval=60),
    RateLimit(limit_id=PRIVATE_POOL, limit=30, time_interval=60),
    RateLimit(limit_id=EXCHANGE_INFO_PATH_URL, limit=60, time_interval=60,
              linked_limits=[LinkedLimitWeightPair(PUBLIC_POOL)]),
    RateLimit(limit_id=ORDER_BOOK_PATH_URL, limit=60, time_interval=60,
              linked_limits=[LinkedLimitWeightPair(PUBLIC_POOL)]),
    RateLimit(limit_id=TICKER_PATH_URL, limit=60, time_interval=60,
              linked_limits=[LinkedLimitWeightPair(PUBLIC_POOL)]),
    RateLimit(limit_id=TRADES_PATH_URL, limit=60, time_interval=60,
              linked_limits=[LinkedLimitWeightPair(PUBLIC_POOL)]),
    RateLimit(limit_id=BALANCES_PATH_URL, limit=30, time_interval=60,
              linked_limits=[LinkedLimitWeightPair(PRIVATE_POOL)]),
    RateLimit(limit_id=ORDER_PATH_URL, limit=30, time_interval=60,
              linked_limits=[LinkedLimitWeightPair(PRIVATE_POOL)]),
    RateLimit(limit_id=OPEN_ORDERS_PATH_URL, limit=30, time_interval=60,
              linked_limits=[LinkedLimitWeightPair(PRIVATE_POOL)]),
    RateLimit(limit_id=ALL_ORDERS_PATH_URL, limit=30, time_interval=60,
              linked_limits=[LinkedLimitWeightPair(PRIVATE_POOL)]),
    RateLimit(limit_id=USER_TRADES_PATH_URL, limit=30, time_interval=60,
              linked_limits=[LinkedLimitWeightPair(PRIVATE_POOL)]),
]
