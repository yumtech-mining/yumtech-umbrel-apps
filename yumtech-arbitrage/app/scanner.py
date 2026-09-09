import asyncio
import logging
import time
from dataclasses import asdict
from decimal import Decimal

import httpx

from .domain import calculate_opportunity
from .exchanges import BTCTurkPublic, BinanceTRPublic, common_try_markets


log = logging.getLogger(__name__)


class MarketScanner:
    """Public-data scanner. It has no credential or order access by design."""
    def __init__(self, target_try: Decimal, min_profit_pct: Decimal):
        self.target_try = target_try
        self.min_profit_rate = min_profit_pct / Decimal("100")
        self.common_pairs: list[str] = []
        self.opportunities: list[dict] = []
        self.last_success_ms: int | None = None
        self.last_error: str | None = None
        self.running = False

    async def run(self) -> None:
        self.running = True
        timeout = httpx.Timeout(8, connect=5)
        async with httpx.AsyncClient(timeout=timeout, headers={"User-Agent": "YUMTECH-Arbitrage/0.2"}, trust_env=False) as client:
            bt, bn = BTCTurkPublic(client), BinanceTRPublic(client)
            while self.running:
                try:
                    bt_markets, bn_markets = await asyncio.gather(bt.markets(), bn.markets())
                    self.common_pairs = common_try_markets(bt_markets, bn_markets)
                    results = []
                    for base in self.common_pairs:
                        bt_book, bn_book = await asyncio.gather(
                            bt.order_book(bt_markets[base]), bn.order_book(bn_markets[base]))
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
                        await asyncio.sleep(0.10)
                    self.opportunities = sorted(results, key=lambda x: Decimal(x["net_profit_try"]), reverse=True)
                    self.last_success_ms = int(time.time() * 1000)
                    self.last_error = None
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    self.last_error = type(exc).__name__
                    log.warning("market scan failed: %s", type(exc).__name__)
                await asyncio.sleep(30)

    def stop(self) -> None:
        self.running = False
