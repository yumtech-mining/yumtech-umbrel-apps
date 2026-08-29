"""Durable parser for CKPool's normal operational log."""

from __future__ import annotations

import hashlib
import os
import re
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from .storage import Storage


TIMESTAMP_RE = re.compile(r"^\[?(\d{4}-\d\d-\d\d)[T ](\d\d:\d\d:\d\d)(?:\.\d+)?Z?\]?\s*(.*)$")
AUTH_RE = re.compile(
    r"Authori[sz]ed client\s+(\S+)\s+(\S+)\s+worker\s+(\S+)\s+as user\s+(\S+)", re.I
)
SV2_AUTH_RE = re.compile(r"SV2 session instance\s+(\S+)\s+user\s+(\S+)\s+authori[sz]ed=(\d+)", re.I)
SHARE_RE = re.compile(
    r"(Accepted|Rejected) client\s+(\S+)\s+(.+?)\s+diff\s+([^/\s]+)/([^/\s]+)/([^:\s]+):\s*([0-9a-fA-F]+)", re.I
)
INVALID_SHARE_RE = re.compile(r"Rejected client\s+(\S+)\s+invalid share\s+(.+)$", re.I)
BLOCK_RE = re.compile(r"Solved and confirmed block\s+(\d+)\s+by\s+(\S+)\s+on\s+(\S+)", re.I)
GENERIC_BLOCK_RE = re.compile(r"Solved and confirmed block!", re.I)
SV2_BLOCK_RE = re.compile(r"Block\s+(\d+)\s+solved by\s+(\S+)\s+accepted on SV2/JD", re.I)
SV2_GENERIC_BLOCK_RE = re.compile(r"Block\s+(\d+)\s+solved \(SV2/JD\) accepted", re.I)
EFFORT_RE = re.compile(r"Block solved after\s+([^\s]+)\s+shares at\s+([0-9.eE+-]+)%\s+diff", re.I)
SV2_KEY_RE = re.compile(r"SV2 authority URL path[^\r\n]*?/([1-9A-HJ-NP-Za-km-z]{40,100})(?:\)|\s|$)", re.I)


def parse_difficulty(value: Any) -> float:
    text = str(value or "0").strip().replace(",", "")
    multiplier = 1.0
    suffixes = {"K": 1e3, "M": 1e6, "G": 1e9, "T": 1e12, "P": 1e15, "E": 1e18}
    if text and text[-1].upper() in suffixes:
        multiplier = suffixes[text[-1].upper()]
        text = text[:-1]
    try:
        return float(text) * multiplier
    except (TypeError, ValueError):
        return 0.0


def split_timestamp(line: str, fallback: float | None = None) -> tuple[float, str]:
    match = TIMESTAMP_RE.match(line.strip())
    if not match:
        return fallback or time.time(), line.strip()
    try:
        parsed = datetime.fromisoformat(f"{match.group(1)}T{match.group(2)}+00:00")
        return parsed.timestamp(), match.group(3).strip()
    except ValueError:
        return fallback or time.time(), match.group(3).strip()


def parse_line(line: str, fallback: float | None = None) -> dict[str, Any] | None:
    when, message = split_timestamp(line, fallback)
    match = AUTH_RE.search(message)
    if match:
        return {
            "kind": "authorization", "created_at": when, "client_id": match.group(1),
            "ip": match.group(2), "worker_name": match.group(3), "btc_address": match.group(4),
        }
    match = SV2_AUTH_RE.search(message)
    if match and int(match.group(3)):
        identity = match.group(2)
        return {
            "kind": "authorization", "created_at": when, "client_id": match.group(1),
            "ip": "", "worker_name": identity, "btc_address": identity.split(".", 1)[0],
        }
    match = SHARE_RE.search(message)
    if match:
        accepted = match.group(1).casefold() == "accepted"
        return {
            "kind": "share", "created_at": when, "client_id": match.group(2),
            "accepted": accepted, "reason": match.group(3).strip(),
            "share_difficulty": parse_difficulty(match.group(4)),
            "assigned_difficulty": parse_difficulty(match.group(5)),
            "work_difficulty": parse_difficulty(match.group(6)),
            "share_hash": match.group(7).lower(),
        }
    match = INVALID_SHARE_RE.search(message)
    if match:
        return {
            "kind": "share", "created_at": when, "client_id": match.group(1),
            "accepted": False, "reason": match.group(2).strip(),
            "share_difficulty": 0.0, "assigned_difficulty": 0.0,
            "work_difficulty": 0.0, "share_hash": "",
        }
    match = BLOCK_RE.search(message)
    if match:
        return {
            "kind": "block", "created_at": when, "height": int(match.group(1)),
            "worker_name": match.group(2), "protocol": match.group(3),
        }
    if GENERIC_BLOCK_RE.search(message):
        return {"kind": "block", "created_at": when, "height": 0, "worker_name": "", "protocol": ""}
    match = SV2_BLOCK_RE.search(message)
    if match:
        return {"kind": "block", "created_at": when, "height": int(match.group(1)), "worker_name": match.group(2), "protocol": "SV2/JD"}
    match = SV2_GENERIC_BLOCK_RE.search(message)
    if match:
        return {"kind": "block", "created_at": when, "height": int(match.group(1)), "worker_name": "", "protocol": "SV2/JD"}
    match = EFFORT_RE.search(message)
    if match:
        round_diff = parse_difficulty(match.group(1))
        percent = parse_difficulty(match.group(2))
        return {
            "kind": "effort", "created_at": when, "round_diff": round_diff,
            "net_diff": round_diff / (percent / 100.0) if percent > 0 else 0.0,
        }
    return None


def sv2_public_identity(log_path: str | Path) -> tuple[str, str]:
    path = Path(log_path)
    try:
        with path.open("rb") as handle:
            size = path.stat().st_size
            handle.seek(max(0, size - 2 * 1024 * 1024))
            text = handle.read().decode("utf-8", "replace")
    except OSError:
        return "", ""
    matches = SV2_KEY_RE.findall(text)
    if not matches:
        return "", ""
    key = matches[-1]
    return key, hashlib.sha256(key.encode()).hexdigest()[:16]


class LogCollector(threading.Thread):
    def __init__(
        self,
        log_path: str | Path,
        storage: Storage,
        block_enricher: Callable[[int, str, float], dict[str, Any]],
        retention_days: int = 30,
        poll_seconds: float = 1.0,
    ):
        super().__init__(name="ckpool-log-collector", daemon=True)
        self.log_path = Path(log_path)
        self.storage = storage
        self.block_enricher = block_enricher
        self.retention_days = retention_days
        self.poll_seconds = poll_seconds
        self.stop_event = threading.Event()
        self.last_block_height = 0
        self.last_block_time = 0.0
        self.pending_effort: dict[str, Any] | None = None
        self.last_error = ""
        self.last_cleanup = 0.0

    def stop(self) -> None:
        self.stop_event.set()

    def run(self) -> None:
        while not self.stop_event.wait(self.poll_seconds):
            try:
                self.collect_once()
                self.last_error = ""
            except Exception as exc:  # keep telemetry alive if CKPool rotates or writes a partial line
                self.last_error = str(exc)
            if time.time() - self.last_cleanup > 3600:
                self.storage.cleanup(self.retention_days)
                self.last_cleanup = time.time()

    def collect_once(self) -> int:
        try:
            stat = self.log_path.stat()
        except OSError:
            return 0
        stored = self.storage.log_state(str(self.log_path))
        fresh = not stored or stored[0] != stat.st_ino or stored[1] > stat.st_size
        offset = max(0, stat.st_size - 10 * 1024 * 1024) if fresh else stored[1]
        processed = 0
        with self.log_path.open("rb") as handle:
            handle.seek(offset)
            if fresh and offset:
                handle.readline()
            while True:
                start = handle.tell()
                raw = handle.readline()
                if not raw:
                    break
                if not raw.endswith(b"\n"):
                    handle.seek(start)
                    break
                self.process_line(raw.decode("utf-8", "replace").rstrip("\r\n"))
                processed += 1
            offset = handle.tell()
        self.storage.set_log_state(str(self.log_path), stat.st_ino, offset)
        return processed

    def process_line(self, raw: str) -> None:
        event = parse_line(raw)
        if not event:
            return
        if event["kind"] == "authorization":
            self.storage.authorize(
                event["client_id"], event["worker_name"], event["btc_address"], event["ip"], event["created_at"]
            )
            return
        if event["kind"] == "share":
            auth = self.storage.authorization(event["client_id"])
            event["worker_name"] = auth.get("worker_name", "")
            event["btc_address"] = auth.get("btc_address", "")
            event["event_key"] = hashlib.sha256(raw.encode("utf-8", "replace")).hexdigest()
            self.storage.insert_share(event)
            return
        if event["kind"] == "block":
            block = self.block_enricher(event["height"], event["worker_name"], event["created_at"])
            if block.get("height"):
                self.storage.insert_block(block)
                self.last_block_height = int(block["height"])
                self.last_block_time = float(event["created_at"])
                if self.pending_effort and 0 <= self.last_block_time - self.pending_effort["created_at"] <= 5:
                    self.storage.update_block_effort(
                        self.last_block_height,
                        self.pending_effort["round_diff"],
                        self.pending_effort["net_diff"],
                    )
                    self.pending_effort = None
            return
        if event["kind"] == "effort":
            if self.last_block_height and 0 <= event["created_at"] - self.last_block_time <= 5:
                self.storage.update_block_effort(self.last_block_height, event["round_diff"], event["net_diff"])
            else:
                self.pending_effort = event
