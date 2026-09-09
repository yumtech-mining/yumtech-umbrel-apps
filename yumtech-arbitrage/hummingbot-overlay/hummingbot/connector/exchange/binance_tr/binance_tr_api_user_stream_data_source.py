import asyncio
import time

from hummingbot.core.data_type.user_stream_tracker_data_source import UserStreamTrackerDataSource


class BinanceTRAPIUserStreamDataSource(UserStreamTrackerDataSource):
    @property
    def last_recv_time(self) -> float:
        return time.time()

    async def listen_for_user_stream(self, output: asyncio.Queue):
        while True: await self._sleep(3600)

    async def _connected_websocket_assistant(self): raise NotImplementedError
    async def _subscribe_channels(self, websocket_assistant): raise NotImplementedError

