import base64
import hashlib
import hmac
import time
from dataclasses import dataclass
from decimal import Decimal

import httpx

from .domain import Level


@dataclass(frozen=True)
class Market:
    base: str
    quote: str
    symbol: str
    amount_step: Decimal
    active: bool


class BTCTurkPublic:
    base_url = "https://api.btcturk.com"

    def __init__(self, client: httpx.AsyncClient): self.client = client

    async def markets(self) -> dict[str, Market]:
        data = (await self.client.get(f"{self.base_url}/api/v2/server/exchangeinfo")).raise_for_status().json()["data"]["symbols"]
        result = {}
        for item in data:
            quote = str(item.get("denominator", "")).upper()
            base = str(item.get("numerator", "")).upper()
            if quote == "TRY":
                result[base] = Market(base, quote, item["name"], Decimal("1").scaleb(-int(item["numeratorScale"])),
                                      bool(item.get("hasMarketOrder", True)))
        return result

    async def order_book(self, market: Market, limit: int = 100) -> tuple[list[Level], list[Level]]:
        response = await self.client.get(f"{self.base_url}/api/v2/orderbook", params={"pairSymbol": market.symbol, "limit": limit})
        data = response.raise_for_status().json()["data"]
        return ([Level(Decimal(x[0]), Decimal(x[1])) for x in data["asks"]],
                [Level(Decimal(x[0]), Decimal(x[1])) for x in data["bids"]])

    @staticmethod
    def auth_headers(api_key: str, api_secret: str, stamp_ms: int | None = None) -> dict[str, str]:
        stamp = str(stamp_ms or int(time.time() * 1000))
        signature = hmac.new(base64.b64decode(api_secret), f"{api_key}{stamp}".encode(), hashlib.sha256).digest()
        return {"X-PCK": api_key, "X-Stamp": stamp, "X-Signature": base64.b64encode(signature).decode()}


class BinanceTRPublic:
    base_url = "https://api.binance.me"

    def __init__(self, client: httpx.AsyncClient): self.client = client

    async def markets(self) -> dict[str, Market]:
        response = await self.client.get(f"{self.base_url}/api/v3/exchangeInfo")
        result = {}
        for item in response.raise_for_status().json()["symbols"]:
            if item["quoteAsset"] != "TRY": continue
            lot = next((f for f in item["filters"] if f["filterType"] == "LOT_SIZE"), None)
            if lot:
                result[item["baseAsset"]] = Market(item["baseAsset"], "TRY", item["symbol"], Decimal(lot["stepSize"]), item["status"] == "TRADING")
        return result

    async def order_book(self, market: Market, limit: int = 100) -> tuple[list[Level], list[Level]]:
        response = await self.client.get(f"{self.base_url}/api/v3/depth", params={"symbol": market.symbol, "limit": limit})
        data = response.raise_for_status().json()
        return ([Level(Decimal(x[0]), Decimal(x[1])) for x in data["asks"]],
                [Level(Decimal(x[0]), Decimal(x[1])) for x in data["bids"]])


def common_try_markets(btcturk: dict[str, Market], binance_tr: dict[str, Market]) -> list[str]:
    return sorted(base for base in btcturk.keys() & binance_tr.keys() if btcturk[base].active and binance_tr[base].active)
