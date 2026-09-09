import unittest
from decimal import Decimal

from hummingbot.connector.exchange.binance_tr.binance_tr_parsers import (
    iter_fills, parse_balances, parse_fee_rates, unwrap_response,
)


class BinanceTRParserTests(unittest.TestCase):
    def test_unwraps_envelope_and_rejects_error(self):
        self.assertEqual({"x": 1}, unwrap_response({"code": 0, "data": {"x": 1}}))
        with self.assertRaisesRegex(IOError, "bad signature"):
            unwrap_response({"code": -1, "msg": "bad signature"})

    def test_parses_balances_and_try_fee_rates(self):
        payload = {"code": 0, "data": {"fiatMakerCommission": "0.0010",
                   "fiatTakerCommission": "0.0015", "accountAssets": [
                       {"asset": "TRY", "free": "100.25", "locked": "20.00"}]}}
        balance = parse_balances(payload)[0]
        self.assertEqual(Decimal("120.25"), balance.total)
        self.assertEqual((Decimal("0.0010"), Decimal("0.0015")), parse_fee_rates(payload))

    def test_filters_fills_for_order(self):
        payload = {"code": 0, "data": {"list": [
            {"tradeId": "1", "orderId": "7"}, {"tradeId": "2", "orderId": "8"}]}}
        self.assertEqual(["2"], [x["tradeId"] for x in iter_fills(payload, "8")])

