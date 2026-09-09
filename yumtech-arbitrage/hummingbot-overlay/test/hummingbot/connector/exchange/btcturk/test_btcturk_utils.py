import unittest
from decimal import Decimal

from hummingbot.connector.exchange.btcturk.btcturk_utils import (
    InsufficientQuoteBalance,
    OrderSemanticsError,
    build_limit_order_payload,
    build_market_order_payload,
    build_side_aware_order_payload,
    market_buy_quote_for_base,
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

    def test_market_buy_converts_base_to_try_and_rounds_up(self):
        quote = market_buy_quote_for_base(
            base_amount=Decimal("0.001"),
            reference_price=Decimal("1000000.001"),
            fee_rate=Decimal("0.0015"),
            safety_buffer_rate=Decimal("0.001"),
            available_try=Decimal("1005"),
            min_quote_try=Decimal("100"),
            quote_step=Decimal("0.01"),
        )
        self.assertEqual(Decimal("1002.51"), quote.quote_quantity_try)
        payload = build_market_order_payload(
            client_order_id="YUMTECH-M-1",
            symbol="btctry",
            side="BUY",
            base_amount=Decimal("0.001"),
            market_buy_quote=quote,
        )
        self.assertEqual("1002.51", payload["quantity"])
        self.assertEqual("market", payload["orderMethod"])
        self.assertEqual("buy", payload["orderType"])

    def test_market_buy_requires_balance_and_never_accepts_base_quantity(self):
        with self.assertRaises(InsufficientQuoteBalance):
            market_buy_quote_for_base(
                base_amount=Decimal("0.001"), reference_price=Decimal("1000000"),
                fee_rate=Decimal("0.0015"), safety_buffer_rate=Decimal("0.001"),
                available_try=Decimal("100"), min_quote_try=Decimal("100"),
                quote_step=Decimal("0.01"))
        with self.assertRaises(OrderSemanticsError):
            build_market_order_payload(
                client_order_id="YUMTECH-M-2", symbol="BTCTRY", side="buy",
                base_amount=Decimal("0.001"))

    def test_market_sell_stays_base_sized_and_limit_path_stays_base_sized(self):
        sell = build_side_aware_order_payload(
            client_order_id="YUMTECH-M-3", symbol="BTCTRY", side="sell",
            order_method="market", base_amount=Decimal("0.001"))
        self.assertEqual("0.001", sell["quantity"])
        limit = build_side_aware_order_payload(
            client_order_id="YUMTECH-L-1", symbol="BTCTRY", side="buy",
            order_method="limit", base_amount=Decimal("0.001"), price=Decimal("1000000"))
        self.assertEqual("0.001", limit["quantity"])
