"""Read CKPool's native snapshots without changing the running pool.

pool.status is JSON Lines (three required objects, optional SV2 objects),
not one JSON document. Worker `shares` is accumulated difficulty, not a
count of submissions. File snapshots are normally rewritten every minute.
"""

from __future__ import annotations

import json
import math
import re
import time
from pathlib import Path
from typing import Any


FRESH_SECONDS = 180
DIFF_TO_HASHRATE = 2**32


def numeric(value: Any) -> float:
    try:
        result = float(value)
        return result if math.isfinite(result) and result >= 0 else 0.0
    except (TypeError, ValueError, OverflowError):
        return 0.0


def hashrate(value: Any) -> float:
    match = re.fullmatch(r"\s*([0-9.+eE-]+)\s*([kKmMgGtTpPeEzZ]?)\s*(?:[hH]/s)?\s*", str(value))
    if not match:
        return 0.0
    exponent = " KMGTPEZ".find(match.group(2).upper() or " ")
    return numeric(match.group(1)) * 1000**exponent


def fresh(timestamp: Any, now: float) -> bool:
    return numeric(timestamp) > 0 and -5 <= now - numeric(timestamp) <= FRESH_SECONDS


def read_pool_status(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        text = handle.read(64 * 1024 + 1)
    if len(text) > 64 * 1024:
        raise ValueError("pool.status is unexpectedly large")
    lines = [line for line in text.splitlines() if line.strip()]
    if len(lines) < 3:
        raise ValueError("pool.status snapshot is incomplete")
    records = [json.loads(line) for line in lines[:3]]
    required = ({"runtime", "lastupdate", "Workers"}, {"hashrate1m", "hashrate5m"}, {"accepted", "bestshare"})
    if any(not isinstance(row, dict) or not keys <= row.keys() for row, keys in zip(records, required)):
        raise ValueError("pool.status snapshot has an unsupported format")
    return {key: value for row in records for key, value in row.items()}


class StatusFiles:
    def __init__(self, pool_path: Path, users_dir: Path):
        self.pool_path = pool_path
        self.users_dir = users_dir
        self._pool: dict[str, Any] = {}
        self._user_documents: dict[Path, tuple[float, dict[str, Any]]] = {}
        self._users_cache: tuple[float, dict[str, Any]] = (0, {})

    def pool(self) -> dict[str, Any]:
        # A concurrent truncate/write must not produce a momentary zero graph.
        try:
            self._pool = read_pool_status(self.pool_path)
        except (OSError, ValueError):
            pass
        value = dict(self._pool)
        now = time.time()
        value["fresh"] = fresh(value.get("lastupdate"), now)
        value["age_seconds"] = max(0, now - numeric(value["lastupdate"])) if value.get("lastupdate") else None
        return value

    def users(self) -> dict[str, Any]:
        now = time.time()
        if now - self._users_cache[0] < 5:
            return self._users_cache[1]
        try:
            paths = [path for path in self.users_dir.iterdir() if path.is_file() and not path.is_symlink()][:5000]
        except OSError:
            paths = []
        documents: dict[Path, tuple[float, dict[str, Any]]] = {}
        users, workers = {}, {}
        global_best = 0.0
        for path in paths:
            try:
                mtime = path.stat().st_mtime
                with path.open(encoding="utf-8") as handle:
                    text = handle.read(8 * 1024 * 1024 + 1)
                if len(text) > 8 * 1024 * 1024:
                    raise ValueError("user snapshot is unexpectedly large")
                value = json.loads(text)
                if not isinstance(value, dict):
                    raise ValueError("user snapshot must be an object")
            except (OSError, ValueError):
                previous = self._user_documents.get(path)
                if not previous:
                    continue
                mtime, value = previous
            documents[path] = (mtime, value)
            user_value = value.get("user")
            username = user_value if isinstance(user_value, str) else str(value.get("username") or path.name)
            record = user_value if isinstance(user_value, dict) else value
            best = max(numeric(record.get("bestever")), numeric(record.get("bestshare")))
            global_best = max(global_best, best)
            users[username] = {**record, "best": best, "updated_at": mtime}
            rows = value.get("worker") or value.get("workers") or []
            if isinstance(rows, dict):
                rows = list(rows.values())
            for worker in rows if isinstance(rows, list) else []:
                if not isinstance(worker, dict):
                    continue
                name = str(worker.get("workername") or worker.get("worker") or "")
                if not name:
                    continue
                best = max(numeric(worker.get("bestever")), numeric(worker.get("bestshare")))
                global_best = max(global_best, best)
                workers[name] = {**worker, "best": best, "user": username, "updated_at": mtime}
        self._user_documents = documents
        output = {"users": users, "workers": workers, "global_best": global_best}
        self._users_cache = (now, output)
        return output
