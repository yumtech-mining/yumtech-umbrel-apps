from hummingbot.connector.exchange.binance.binance_auth import BinanceAuth


class BinanceTRAuth(BinanceAuth):
    """Binance TR uses the standard X-MBX-APIKEY + HMAC-SHA256 scheme."""

