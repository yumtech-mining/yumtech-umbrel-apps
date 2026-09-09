from typing import Callable, Optional

from hummingbot.connector.time_synchronizer import TimeSynchronizer
from hummingbot.connector.utils import TimeSynchronizerRESTPreProcessor
from hummingbot.core.api_throttler.async_throttler import AsyncThrottler
from hummingbot.core.web_assistant.auth import AuthBase
from hummingbot.core.web_assistant.connections.data_types import RESTMethod
from hummingbot.core.web_assistant.web_assistants_factory import WebAssistantsFactory

from . import binance_tr_constants as CONSTANTS


def public_rest_url(path_url: str, domain: str = CONSTANTS.DEFAULT_DOMAIN) -> str:
    base = CONSTANTS.OPEN_REST_URL if path_url.startswith("/open/") else CONSTANTS.PUBLIC_REST_URL
    return f"{base}{path_url}"


def private_rest_url(path_url: str, domain: str = CONSTANTS.DEFAULT_DOMAIN) -> str:
    return f"{CONSTANTS.OPEN_REST_URL}{path_url}"


def create_throttler() -> AsyncThrottler:
    return AsyncThrottler(CONSTANTS.RATE_LIMITS)


def build_api_factory(
    throttler: Optional[AsyncThrottler] = None,
    time_synchronizer: Optional[TimeSynchronizer] = None,
    time_provider: Optional[Callable] = None,
    auth: Optional[AuthBase] = None,
) -> WebAssistantsFactory:
    throttler = throttler or create_throttler()
    synchronizer = time_synchronizer or TimeSynchronizer()
    provider = time_provider or (lambda: get_current_server_time(throttler))
    return WebAssistantsFactory(
        throttler=throttler,
        auth=auth,
        rest_pre_processors=[TimeSynchronizerRESTPreProcessor(synchronizer=synchronizer, time_provider=provider)],
    )


async def get_current_server_time(throttler: Optional[AsyncThrottler] = None) -> float:
    factory = WebAssistantsFactory(throttler=throttler or create_throttler())
    assistant = await factory.get_rest_assistant()
    response = await assistant.execute_request(
        url=public_rest_url(CONSTANTS.SERVER_TIME_PATH_URL),
        method=RESTMethod.GET,
        throttler_limit_id=CONSTANTS.SERVER_TIME_PATH_URL,
    )
    return float(response["timestamp"])

