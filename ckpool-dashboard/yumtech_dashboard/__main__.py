"""Run the YUMTECH CKPool dashboard."""

from __future__ import annotations

import signal
import sys
import threading

from .config import Settings
from .httpd import make_server
from .service import DashboardService


def main() -> int:
    settings = Settings.load()
    service = DashboardService(settings)
    service.start()
    server = make_server(service)
    stopping = threading.Event()

    def stop(_signum: int, _frame: object) -> None:
        if stopping.is_set():
            return
        stopping.set()
        threading.Thread(target=server.shutdown, daemon=True).start()

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    print(f"YUMTECH CKPool dashboard listening on http://{settings.host}:{settings.port}", flush=True)
    print(f"CKPool socket: {settings.socket_path}", flush=True)
    print(f"CKPool log: {settings.log_path}", flush=True)
    try:
        server.serve_forever(poll_interval=0.5)
    finally:
        server.server_close()
        service.stop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
