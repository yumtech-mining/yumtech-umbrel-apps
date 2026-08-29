"""CKPool's native length-prefixed JSON Unix-socket client."""

from __future__ import annotations

import json
import socket
import struct
from pathlib import Path
from typing import Any


class CkpoolError(RuntimeError):
    pass


def _read_exact(sock: socket.socket, length: int) -> bytes:
    chunks: list[bytes] = []
    remaining = length
    while remaining:
        chunk = sock.recv(remaining)
        if not chunk:
            raise CkpoolError("CKPool closed the socket before completing its response")
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


class CkpoolClient:
    """Issue one command per connection to CKPool's stratifier socket."""

    def __init__(self, path: str | Path, timeout: float = 2.0):
        self.path = str(path)
        self.timeout = timeout

    def command(self, command: str | dict[str, Any]) -> dict[str, Any]:
        payload = command if isinstance(command, str) else json.dumps(command, separators=(",", ":"))
        encoded = payload.encode("utf-8")
        if len(encoded) > 16 * 1024 * 1024:
            raise CkpoolError("CKPool request is unexpectedly large")
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
            sock.settimeout(self.timeout)
            try:
                sock.connect(self.path)
                sock.sendall(struct.pack("<I", len(encoded)) + encoded)
                size = struct.unpack("<I", _read_exact(sock, 4))[0]
                if size > 64 * 1024 * 1024:
                    raise CkpoolError("CKPool response is unexpectedly large")
                raw = _read_exact(sock, size)
            except (OSError, struct.error) as exc:
                raise CkpoolError(str(exc)) from exc
        try:
            value = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise CkpoolError("CKPool returned invalid JSON") from exc
        return value if isinstance(value, dict) else {"result": value}

    def poolstats(self) -> dict[str, Any]:
        return self.command("poolstats")

    def clients(self) -> list[dict[str, Any]]:
        value = self.command("clients").get("clients", [])
        return value if isinstance(value, list) else []

    def workers(self) -> list[dict[str, Any]]:
        value = self.command("workers").get("workers", [])
        return value if isinstance(value, list) else []

    def users(self) -> list[dict[str, Any]]:
        value = self.command("users").get("users", [])
        return value if isinstance(value, list) else []

    def uptime(self) -> int:
        try:
            return int(self.command("uptime").get("uptime", 0))
        except (TypeError, ValueError):
            return 0
