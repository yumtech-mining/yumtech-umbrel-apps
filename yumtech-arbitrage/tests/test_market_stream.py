from decimal import Decimal

from app.market_stream import OrderBookStore


def test_store_replaces_sorts_and_applies_absolute_deltas():
    store = OrderBookStore(max_levels=2)
    store.replace("binance_tr", "BTC", [["102", "1"], ["101", "2"]],
                  [["99", "3"], ["100", "4"]], 10)
    asks, bids = store.get("binance_tr", "BTC")
    assert [level.price for level in asks] == [Decimal("101"), Decimal("102")]
    assert [level.price for level in bids] == [Decimal("100"), Decimal("99")]

    assert store.apply("binance_tr", "BTC", [["101", "0"], ["103", "5"]],
                       [["100", "6"]], 11)
    asks, bids = store.get("binance_tr", "BTC")
    assert [level.price for level in asks] == [Decimal("102"), Decimal("103")]
    assert bids[0].amount == Decimal("6")
    assert not store.apply("binance_tr", "BTC", [], [], 11)


def test_btcturk_delete_event_zeroes_levels_and_health_is_reported():
    store = OrderBookStore()
    store.replace("btcturk", "ETH", [{"P": "10", "A": "2"}],
                  [{"P": "9", "A": "3"}], 50)
    assert store.apply("btcturk", "ETH", [{"P": "10", "A": "2"}], [], 51, deleted=True)
    asks, bids = store.get("btcturk", "ETH")
    assert asks == [] and len(bids) == 1
    health = store.health()["btcturk"]
    assert health["connected"] is True
    assert health["age_ms"] is not None


def test_sequence_gap_invalidates_book_instead_of_exposing_stale_prices():
    store = OrderBookStore()
    store.replace("btcturk", "BTC", [["11", "1"]], [["10", "1"]], 100)
    assert not store.apply("btcturk", "BTC", [], [["10", "2"]], 102,
                           require_contiguous=True)
    assert store.get("btcturk", "BTC") is None
