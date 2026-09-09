import unittest
from decimal import Decimal

from hummingbot.connector.exchange.btcturk.btcturk_parsers import (
    iter_order_trades,
    normalize_order_status,
    order_id,
    parse_balances,
    unwrap_response,
)


class BtcTurkParserTests(unittest.TestCase):
    def test_unwraps_success_and_rejects_api_error(self):
        self.assertEqual([1], unwrap_response({"success": True, "data": [1]}))
        with self.assertRaisesRegex(IOError, "bad key"):
            unwrap_response({"success": False, "message": "bad key"})

    def test_parses_available_and_total_balances(self):
        rows = parse_balances({"success": True, "data": [
            {"asset": "try", "balance": "125.40", "free": "100.10"},
        ]})
        self.assertEqual("TRY", rows[0].asset)
        self.assertEqual(Decimal("100.10"), rows[0].available)
        self.assertEqual(Decimal("125.40"), rows[0].total)

    def test_normalizes_order_states(self):
        self.assertEqual("partial", normalize_order_status("PARTIALLY_FILLED"))
        self.assertEqual("closed", normalize_order_status("filled"))
        self.assertEqual("123", order_id({"id": 123}))

    def test_filters_fills_by_exchange_order_id(self):
        fills = list(iter_order_trades({"data": [
            {"id": 1, "orderId": 10}, {"id": 2, "orderId": 11}
        ]}, "11"))
        self.assertEqual([2], [row["id"] for row in fills])

