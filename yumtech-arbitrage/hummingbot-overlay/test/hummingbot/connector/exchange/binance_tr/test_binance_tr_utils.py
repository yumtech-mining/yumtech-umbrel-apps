import unittest
from decimal import Decimal

from hummingbot.connector.exchange.binance_tr.binance_tr_utils import api_symbol, parse_trading_rule


class BinanceTRUtilsTests(unittest.TestCase):
    def test_parses_current_open_v1_symbol_schema(self):
        rule = parse_trading_rule({"type": 1, "symbol": "BTC_TRY", "baseAsset": "BTC",
            "quoteAsset": "TRY", "spotTradingEnable": 1, "filters": [
                {"filterType": "PRICE_FILTER", "tickSize": "0.10"},
                {"filterType": "LOT_SIZE", "minQty": "0.00001", "maxQty": "100", "stepSize": "0.00001"},
                {"filterType": "NOTIONAL", "minNotional": "100"}]})
        self.assertEqual("BTC-TRY", rule.trading_pair)
        self.assertEqual(Decimal("0.10"), rule.price_increment)
        self.assertEqual(Decimal("100"), rule.min_notional)
        self.assertEqual("BTCTRY", api_symbol(rule.symbol))

