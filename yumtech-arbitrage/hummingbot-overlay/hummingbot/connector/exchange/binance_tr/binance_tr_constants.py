from hummingbot.core.api_throttler.data_types import LinkedLimitWeightPair, RateLimit
from hummingbot.core.data_type.in_flight_order import OrderState

EXCHANGE_NAME = "binance_tr"
DEFAULT_DOMAIN = "tr"
HBOT_ORDER_ID_PREFIX = "YUMTECH-BTR-"
MAX_ORDER_ID_LEN = 36

PUBLIC_REST_URL = "https://api.binance.me"
OPEN_REST_URL = "https://www.binance.tr"
PUBLIC_WS_URL = "wss://stream-cloud.binance.tr/ws"

SERVER_TIME_PATH_URL = "/open/v1/common/time"
SYMBOLS_PATH_URL = "/open/v1/common/symbols"
DEPTH_PATH_URL = "/api/v3/depth"
TICKER_PATH_URL = "/api/v3/ticker/price"
ACCOUNT_PATH_URL = "/open/v1/account/spot"
ORDER_PATH_URL = "/open/v1/orders"
ORDER_DETAIL_PATH_URL = "/open/v1/orders/detail"
ORDER_CANCEL_PATH_URL = "/open/v1/orders/cancel"
TRADES_PATH_URL = "/open/v1/orders/trades"
LISTEN_TOKEN_PATH_URL = "/open/v1/user-listen-token"

SIDE_BUY = 0
SIDE_SELL = 1
ORDER_TYPE_LIMIT = 1
ORDER_TYPE_MARKET = 2
ORDER_TYPE_LIMIT_MAKER = 7
TIME_IN_FORCE_GTC = 1
TIME_IN_FORCE_IOC = 2
TIME_IN_FORCE_FOK = 3
TIME_IN_FORCE_GTX = 4

ORDER_STATE = {
    -2: OrderState.PENDING_CREATE,
    0: OrderState.OPEN,
    1: OrderState.PARTIALLY_FILLED,
    2: OrderState.FILLED,
    3: OrderState.CANCELED,
    4: OrderState.PENDING_CANCEL,
    5: OrderState.FAILED,
    6: OrderState.CANCELED,
}

PUBLIC_POOL = "BINANCE_TR_PUBLIC"
PRIVATE_POOL = "BINANCE_TR_PRIVATE"
ORDER_POOL = "BINANCE_TR_ORDERS"

# Conservative local allocations. Response-header adaptive throttling will be
# added before live qualification; these values avoid WAF/IP-ban pressure.
RATE_LIMITS = [
    RateLimit(limit_id=PUBLIC_POOL, limit=600, time_interval=60),
    RateLimit(limit_id=PRIVATE_POOL, limit=300, time_interval=60),
    RateLimit(limit_id=ORDER_POOL, limit=40, time_interval=10),
    RateLimit(limit_id=SERVER_TIME_PATH_URL, limit=600, time_interval=60,
              linked_limits=[LinkedLimitWeightPair(PUBLIC_POOL)]),
    RateLimit(limit_id=SYMBOLS_PATH_URL, limit=600, time_interval=60,
              linked_limits=[LinkedLimitWeightPair(PUBLIC_POOL)]),
    RateLimit(limit_id=DEPTH_PATH_URL, limit=600, time_interval=60,
              linked_limits=[LinkedLimitWeightPair(PUBLIC_POOL, 5)]),
    RateLimit(limit_id=TICKER_PATH_URL, limit=600, time_interval=60,
              linked_limits=[LinkedLimitWeightPair(PUBLIC_POOL, 2)]),
    RateLimit(limit_id=ACCOUNT_PATH_URL, limit=300, time_interval=60,
              linked_limits=[LinkedLimitWeightPair(PRIVATE_POOL)]),
    RateLimit(limit_id=ORDER_PATH_URL, limit=300, time_interval=60,
              linked_limits=[LinkedLimitWeightPair(PRIVATE_POOL), LinkedLimitWeightPair(ORDER_POOL)]),
    RateLimit(limit_id=ORDER_DETAIL_PATH_URL, limit=300, time_interval=60,
              linked_limits=[LinkedLimitWeightPair(PRIVATE_POOL)]),
    RateLimit(limit_id=ORDER_CANCEL_PATH_URL, limit=300, time_interval=60,
              linked_limits=[LinkedLimitWeightPair(PRIVATE_POOL), LinkedLimitWeightPair(ORDER_POOL)]),
    RateLimit(limit_id=TRADES_PATH_URL, limit=300, time_interval=60,
              linked_limits=[LinkedLimitWeightPair(PRIVATE_POOL)]),
]

