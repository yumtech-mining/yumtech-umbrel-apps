import unittest
from decimal import Decimal

from hummingbot.connector.exchange.btcturk.btcturk_utils import (
    build_limit_order_payload,
    parse_trading_rule,
)


class BtcTurkUtilsTests(unittest.TestCase):
    def setUp(self):
        self.exchange_info = {
            "name": "BTCTRY",
            "numerator": "BTC",
            "denominator": "TRY",
            "numeratorScale": 8,
            "denominatorScale": 2,
            "hasMarketOrder": True,
            "status": "TRADING",
            "filters": [{"minExchangeValue": "100.00"}],
        }

    def test_parses_pair_precision_and_minimum_notional(self):
        rule = parse_trading_rule(self.exchange_info)
        self.assertEqual("BTC-TRY", rule.trading_pair)
        self.assertEqual(Decimal("0.00000001"), rule.min_base_amount_increment)
        self.assertEqual(Decimal("0.01"), rule.min_price_increment)
        self.assertEqual(Decimal("100.00"), rule.min_notional_size)

    def test_builds_decimal_safe_limit_payload(self):
        payload = build_limit_order_payload(
            client_order_id="YUMTECH-1",
            symbol="btctry",
            side="BUY",
            quantity=Decimal("0.00123000"),
            price=Decimal("3500000.10"),
        )
        self.assertEqual("0.00123000", payload["quantity"])
        self.assertEqual("3500000.10", payload["price"])
        self.assertEqual("BTCTRY", payload["pairSymbol"])
        self.assertEqual("limit", payload["orderMethod"])

