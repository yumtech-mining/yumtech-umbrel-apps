from typing import Dict

from hummingbot.connector.time_synchronizer import TimeSynchronizer
from hummingbot.core.web_assistant.auth import AuthBase
from hummingbot.core.web_assistant.connections.data_types import RESTRequest, WSRequest

from .btcturk_signing import generate_signature


class BtcTurkAuth(AuthBase):
    def __init__(self, api_key: str, api_secret: str, time_provider: TimeSynchronizer):
        self.api_key = api_key
        self.api_secret = api_secret
        self.time_provider = time_provider

    def authentication_headers(self) -> Dict[str, str]:
        timestamp_ms = int(self.time_provider.time() * 1e3)
        return {
            "X-PCK": self.api_key,
            "X-Stamp": str(timestamp_ms),
            "X-Signature": generate_signature(self.api_key, self.api_secret, timestamp_ms),
            "Content-Type": "application/json",
        }

    async def rest_authenticate(self, request: RESTRequest) -> RESTRequest:
        headers = dict(request.headers or {})
        headers.update(self.authentication_headers())
        request.headers = headers
        return request

    async def ws_authenticate(self, request: WSRequest) -> WSRequest:
        return request

