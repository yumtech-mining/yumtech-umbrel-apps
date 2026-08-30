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
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
                sock.settimeout(self.timeout)
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
        value = self.command("poolstats")
        if "dsps1" not in value or "dsps5" not in value:
            raise CkpoolError("CKPool did not return pool statistics")
        return value

    def stats(self) -> dict[str, Any]:
        value = self.command("stats")
        if not isinstance(value.get("clients"), dict) or "count" not in value["clients"]:
            raise CkpoolError("CKPool did not return native stats")
        return value

    def _list(self, command: str) -> list[dict[str, Any]]:
        value = self.command(command).get(command)
        if not isinstance(value, list):
            raise CkpoolError(f"CKPool did not return {command}")
        return value

    def clients(self) -> list[dict[str, Any]]:
        return self._list("clients")

    def workers(self) -> list[dict[str, Any]]:
        return self._list("workers")

    def users(self) -> list[dict[str, Any]]:
        return self._list("users")

    def uptime(self) -> int:
        try:
            return int(self.command("uptime")["uptime"])
        except (KeyError, TypeError, ValueError) as exc:
            raise CkpoolError("CKPool did not return uptime") from exc
