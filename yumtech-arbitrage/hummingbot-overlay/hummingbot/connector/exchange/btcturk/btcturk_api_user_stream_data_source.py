import asyncio
import time

from hummingbot.core.data_type.user_stream_tracker_data_source import UserStreamTrackerDataSource


class BtcTurkAPIUserStreamDataSource(UserStreamTrackerDataSource):
    """REST lifecycle polling is authoritative until the private WS protocol is certified."""

    async def listen_for_user_stream(self, output: asyncio.Queue):
        while True:
            await self._sleep(3600)

    async def _connected_websocket_assistant(self):
        raise NotImplementedError

    async def _subscribe_channels(self, websocket_assistant):
        raise NotImplementedError
    @property
    def last_recv_time(self) -> float:
        # Order and balance state is deliberately refreshed by ExchangePyBase's
        # authenticated REST status loop. This marks that fallback as ready.
        return time.time()

