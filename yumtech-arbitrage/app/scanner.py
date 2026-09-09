import asyncio
import logging
import time
from dataclasses import asdict
from decimal import Decimal

import httpx

from .domain import calculate_opportunity
from .exchanges import BTCTurkPublic, BinanceTRPublic, common_try_markets
from .market_stream import OrderBookStore, PublicMarketStreams


log = logging.getLogger(__name__)


class MarketScanner:
    """Public-data scanner. It has no credential or order access by design."""
    def __init__(self, target_try: Decimal, min_profit_pct: Decimal, cycle_pause_seconds: float = 5.0):
        self.target_try = target_try
        self.min_profit_rate = min_profit_pct / Decimal("100")
        self.common_pairs: list[str] = []
        self.opportunities: list[dict] = []
        self.last_success_ms: int | None = None
        self.last_error: str | None = None
        self.running = False
        self.snapshot_id = 0
        self.cycle_pause_seconds = max(cycle_pause_seconds, 1.0)
        self._markets_refreshed_at = 0.0
        self._bt_markets = {}
        self._bn_markets = {}
        self.books = OrderBookStore()
        self.streams = PublicMarketStreams(self.books)
        self.rest_fallback_count = 0

    async def run(self) -> None:
        self.running = True
        timeout = httpx.Timeout(8, connect=5)
        async with httpx.AsyncClient(timeout=timeout, headers={"User-Agent": "YUMTECH-Arbitrage/0.3.2"}, trust_env=False) as client:
            bt, bn = BTCTurkPublic(client), BinanceTRPublic(client)
            while self.running:
                try:
                    now = time.monotonic()
                    if not self._bt_markets or now - self._markets_refreshed_at >= 900:
                        self._bt_markets, self._bn_markets = await asyncio.gather(bt.markets(), bn.markets())
                        self._markets_refreshed_at = now
                    bt_markets, bn_markets = self._bt_markets, self._bn_markets
                    self.common_pairs = common_try_markets(bt_markets, bn_markets)
                    self.streams.sync(bt_markets, bn_markets, self.common_pairs)
                    results = []
                    for base in self.common_pairs:
                        bt_book = self.books.get("btcturk", base)
                        bn_book = self.books.get("binance_tr", base)
                        missing = []
                        if bt_book is None:
                            missing.append(("btcturk", bt.order_book(bt_markets[base])))
                        if bn_book is None:
                            missing.append(("binance_tr", bn.order_book(bn_markets[base])))
                        if missing:
                            fallback = await asyncio.gather(*(request for _, request in missing))
                            self.rest_fallback_count += len(fallback)
                            for (exchange, _), book in zip(missing, fallback):
                                if exchange == "btcturk":
                                    bt_book = book
                                else:
                                    bn_book = book
                        directions = (
                            ("BTCTürk", "Binance TR", bt_book[0], bn_book[1], bt_markets[base].amount_step),
                            ("Binance TR", "BTCTürk", bn_book[0], bt_book[1], bn_markets[base].amount_step),
                        )
                        for buy_name, sell_name, asks, bids, step in directions:
                            item = calculate_opportunity(
                                pair=f"{base}/TRY", buy_exchange=buy_name, sell_exchange=sell_name,
                                asks=asks, bids=bids, quote_budget=self.target_try, amount_step=step,
                                buy_fee_rate=Decimal("0.0015"), sell_fee_rate=Decimal("0.0015"),
                                safety_buffer_rate=Decimal("0.0010"), min_profit_rate=self.min_profit_rate)
                            raw = asdict(item)
                            results.append({key: str(value) if isinstance(value, Decimal) else value for key, value in raw.items()})
                        # REST fallback remains deliberately slow; WS books do
                        # not need this pause.
                        if missing:
                            await asyncio.sleep(1.05)
                    self.opportunities = sorted(results, key=lambda x: Decimal(x["net_profit_try"]), reverse=True)
                    self.last_success_ms = int(time.time() * 1000)
                    self.snapshot_id += 1
                    self.last_error = None
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    self.last_error = type(exc).__name__
                    log.warning("market scan failed: %s", type(exc).__name__)
                    if isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code in {418, 429}:
                        retry_after = int(exc.response.headers.get("Retry-After", "60"))
                        await asyncio.sleep(min(max(retry_after, 30), 300))
                await asyncio.sleep(self.cycle_pause_seconds)

    def stop(self) -> None:
        self.running = False
        self.streams.stop()

    def market_data_health(self) -> dict:
        return {"feeds": self.books.health(), "rest_fallback_count": self.rest_fallback_count,
                "common_pair_count": len(self.common_pairs)}
