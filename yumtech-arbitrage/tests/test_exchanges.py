from decimal import Decimal

import httpx
import pytest

from app.exchanges import BinanceTRPublic


@pytest.mark.anyio
async def test_binance_tr_current_symbol_schema_maps_private_and_public_symbols():
    async def handler(request: httpx.Request):
        assert request.url.path == "/open/v1/common/symbols"
        return httpx.Response(200, json={"code": 0, "data": {"list": [{
            "type": 1, "symbol": "BTC_TRY", "baseAsset": "BTC", "quoteAsset": "TRY",
            "spotTradingEnable": 1,
            "filters": [{"filterType": "LOT_SIZE", "stepSize": "0.00001000"}],
        }]}})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        markets = await BinanceTRPublic(client).markets()
    assert markets["BTC"].symbol == "BTCTRY"
    assert markets["BTC"].amount_step == Decimal("0.00001000")
    assert markets["BTC"].active is True

