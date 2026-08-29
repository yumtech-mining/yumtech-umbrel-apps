"""Application service joining CKPool live data, logs, SQLite and Bitcoin RPC."""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Any

from .bitcoin import BitcoinRpc
from .ckpool import CkpoolClient, CkpoolError
from .collector import LogCollector, sv2_public_identity
from .config import Settings
from .storage import Storage


DIFF_TO_HASHRATE = 2**32


def number(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def integer(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def truthy(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, str):
        return value.casefold() not in {"", "0", "false", "no", "off"}
    return bool(value)


def iso(epoch: float | int | None) -> str | None:
    if not epoch:
        return None
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(float(epoch)))


def worker_label(full_name: str, user: str = "") -> str:
    name = str(full_name or "worker")
    if user and name.startswith(user):
        suffix = name[len(user) :].lstrip("._")
        return suffix or name
    if "." in name:
        return name.split(".", 1)[1] or name
    return name


def address_from_worker(worker: str) -> str:
    return str(worker or "").split(".", 1)[0].split("_", 1)[0]


class DashboardService:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.settings.state_dir.mkdir(parents=True, exist_ok=True)
        self.storage = Storage(self.settings.state_dir / "dashboard.db")
        self.ckpool = CkpoolClient(self.settings.socket_path)
        self.rpc = BitcoinRpc(
            settings.rpc_url, settings.rpc_user, settings.rpc_password, settings.rpc_timeout
        )
        self._lock = threading.RLock()
        self._pool_cache: tuple[float, dict[str, Any]] = (0.0, {})
        self._node_cache: tuple[float, dict[str, Any]] = (0.0, {})
        self._status_cache: tuple[float, dict[str, Any]] = (0.0, {})
        self._last_history_bucket = 0
        self._stop_event = threading.Event()
        self._metrics_thread = threading.Thread(target=self._metrics_loop, name="dashboard-metrics", daemon=True)
        self.collector = LogCollector(
            settings.log_path, self.storage, self._enrich_block, settings.retention_days
        )

    def start(self) -> None:
        self.collector.collect_once()
        self.collector.start()
        self._metrics_thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        self.collector.stop()
        self.collector.join(timeout=3)
        self._metrics_thread.join(timeout=3)

    def _metrics_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                self.overview()
            except Exception:
                pass
            self._stop_event.wait(30)

    def _pool(self, force: bool = False) -> dict[str, Any]:
        with self._lock:
            if not force and time.time() - self._pool_cache[0] < 2:
                return self._pool_cache[1]
            try:
                clients = self.ckpool.clients()
                value = {
                    "online": True,
                    "poolstats": self.ckpool.poolstats(),
                    "clients": clients,
                    "workers": self.ckpool.workers(),
                    "users": self.ckpool.users(),
                    "uptime": self.ckpool.uptime(),
                }
                now = time.time()
                for client in clients:
                    if not isinstance(client, dict):
                        continue
                    worker = str(client.get("workername") or "")
                    if worker:
                        self.storage.authorize(
                            str(client.get("id") or ""), worker, address_from_worker(worker),
                            str(client.get("address") or ""), now,
                        )
            except CkpoolError as exc:
                value = {"online": False, "error": str(exc), "poolstats": {}, "clients": [], "workers": [], "users": [], "uptime": 0}
            self._pool_cache = (time.time(), value)
            return value

    def node(self, force: bool = False) -> dict[str, Any]:
        with self._lock:
            if not force and time.time() - self._node_cache[0] < 5:
                return self._node_cache[1]
            value = self.rpc.node_data()
            self._node_cache = (time.time(), value)
            return value

    def _status_records(self) -> dict[str, Any]:
        with self._lock:
            if time.time() - self._status_cache[0] < 10:
                return self._status_cache[1]
            users: dict[str, dict[str, Any]] = {}
            workers: dict[str, dict[str, Any]] = {}
            global_best = 0.0
            try:
                files = [path for path in self.settings.users_dir.iterdir() if path.is_file()][:5000]
            except OSError:
                files = []
            for path in files:
                try:
                    value = json.loads(path.read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    continue
                if not isinstance(value, dict):
                    continue
                user_value = value.get("user")
                user_name = user_value if isinstance(user_value, str) else str(value.get("username") or path.name)
                user_record = user_value if isinstance(user_value, dict) else value
                user_best = max(number(user_record.get("bestever")), number(user_record.get("bestshare")))
                global_best = max(global_best, user_best)
                users[user_name] = {"best": user_best, "shares": integer(user_record.get("shares")), "lastshare": number(user_record.get("lastshare"))}
                worker_values = value.get("worker") or value.get("workers") or []
                if isinstance(worker_values, dict):
                    worker_values = list(worker_values.values())
                for record in worker_values if isinstance(worker_values, list) else []:
                    if not isinstance(record, dict):
                        continue
                    name = str(record.get("workername") or record.get("worker") or "")
                    if not name:
                        continue
                    best = max(number(record.get("bestever")), number(record.get("bestshare")))
                    global_best = max(global_best, best)
                    workers[name] = {"best": best, "shares": integer(record.get("shares")), "lastshare": number(record.get("lastshare"))}
            output = {"users": users, "workers": workers, "global_best": global_best}
            self._status_cache = (time.time(), output)
            return output

    def _protocol(self, client: dict[str, Any]) -> str:
        server = client.get("server", 0)
        if "sv2" in str(server).casefold():
            return "SV2"
        index = integer(server)
        has_sv2 = bool(self.settings.config.get("sv2url"))
        return "SV2" if has_sv2 and index >= max(1, self.settings.sv1_servers) else "SV1"

    def miners(self) -> list[dict[str, Any]]:
        pool = self._pool()
        clients = [client for client in pool.get("clients", []) if isinstance(client, dict)]
        worker_rows = [worker for worker in pool.get("workers", []) if isinstance(worker, dict)]
        live = [
            client for client in clients
            if truthy(client.get("authorised", client.get("authorized")), True)
            and truthy(client.get("subscribed"), True)
            and not truthy(client.get("idle"), False)
        ]
        worker_api: dict[str, dict[str, Any]] = {}
        for row in worker_rows:
            name = str(row.get("worker") or row.get("workername") or "")
            if name:
                worker_api[name] = row
        status = self._status_records()
        local = self.storage.worker_stats()
        groups: dict[str, list[dict[str, Any]]] = {}
        for client in live:
            name = str(client.get("workername") or client.get("worker") or client.get("user") or "worker")
            groups.setdefault(name, []).append(client)

        result = []
        now = time.time()
        for full_name, group in groups.items():
            first = group[0]
            user = str(first.get("user") or address_from_worker(full_name))
            api = worker_api.get(full_name, {})
            persistent = status["workers"].get(full_name, {})
            local_stats = local.get(full_name, {})
            dsps1 = number(api.get("dsps1")) or sum(number(item.get("dsps1")) for item in group)
            dsps5 = number(api.get("dsps5")) or sum(number(item.get("dsps5")) for item in group)
            best_api = max(number(api.get("bestdiff")), *(number(item.get("bestdiff")) for item in group))
            best = max(best_api, number(persistent.get("best")), number(local_stats.get("best")))
            lastshare = max(number(api.get("lastshare")), number(persistent.get("lastshare")), number(local_stats.get("last_share")), *(number(item.get("lastshare")) for item in group))
            starts = [number(item.get("starttime")) for item in group if number(item.get("starttime")) > 0]
            protocols = sorted({self._protocol(item) for item in group})
            result.append({
                "worker_name": worker_label(full_name, user), "worker_full_name": full_name,
                "btc_address": user, "user_agent": str(first.get("useragent") or ""),
                "protocol": " + ".join(protocols), "ip": str(first.get("address") or ""),
                "connections": len(group), "hashrate": dsps1 * DIFF_TO_HASHRATE,
                "hashrate_5m": dsps5 * DIFF_TO_HASHRATE,
                "difficulty": max(number(item.get("diff")) for item in group),
                "best_share_difficulty": best,
                "best_share_hash": str(local_stats.get("best_hash") or ""),
                "shares_accepted": max(integer(local_stats.get("accepted")), integer(persistent.get("shares"))),
                "shares_rejected": integer(local_stats.get("rejected")),
                "last_share_at": iso(lastshare),
                "connected_seconds": int(now - min(starts)) if starts else 0,
                "status": "online",
            })
        return sorted(result, key=lambda item: item["hashrate"], reverse=True)

    def overview(self) -> dict[str, Any]:
        pool = self._pool()
        stats = pool.get("poolstats", {})
        miners = self.miners() if pool.get("online") else []
        status = self._status_records()
        node = self.node()
        hashrate1 = number(stats.get("dsps1")) * DIFF_TO_HASHRATE
        hashrate5 = number(stats.get("dsps5")) * DIFF_TO_HASHRATE
        best = max(
            self.storage.global_best(), number(status.get("global_best")),
            *(number(worker.get("best_share_difficulty")) for worker in miners),
        )
        current_bucket = int(time.time() // 60)
        if current_bucket != self._last_history_bucket:
            self.storage.record_history(hashrate1, len(miners), sum(item["connections"] for item in miners))
            self._last_history_bucket = current_bucket
        return {
            "hashrate_1m": hashrate1, "hashrate_5m": hashrate5,
            "workers": len(miners), "connections": sum(item["connections"] for item in miners),
            "best_share": best, "blocks": self.storage.block_count(),
            "uptime_seconds": integer(pool.get("uptime")), "online": bool(pool.get("online")),
            "template_height": integer(node.get("blocks")) + 1 if node.get("online") else 0,
            "engine": "CKPool",
        }

    def analytics(self) -> dict[str, Any]:
        output = self.storage.analytics()
        stats = self._pool().get("poolstats", {})
        node = self.node()
        round_diff = number(stats.get("accepted"))
        network_diff = number(node.get("difficulty"))
        output.update({
            "round_diff": round_diff, "network_difficulty": network_diff,
            "round_effort_pct": round_diff / network_diff * 100 if network_diff else 0.0,
        })
        return output

    def config(self) -> dict[str, Any]:
        config = self.settings.config
        public_key, fingerprint = sv2_public_identity(self.settings.log_path)
        minimum = number(config.get("mindiff"), 1)
        maximum = number(config.get("maxdiff"), 0) or 1e18
        starting = number(config.get("startdiff"), minimum)
        return {
            "name": "YUMTECH", "coin": "BTC", "mode": "Solo",
            "coinbase_signature": str(config.get("btcsig") or "/YUMTECH/"),
            "sv1_port": self.settings.sv1_port, "sv2_port": self.settings.sv2_port,
            "sv2_enabled": bool(config.get("sv2url")),
            "starting_difficulty": starting, "vardiff_min": minimum, "vardiff_max": maximum,
            "version_rolling_mask": str(config.get("versionmask") or config.get("version_mask") or "1fffe000"),
            "engine": "CKPool", "engine_build": "Native Unix-socket API",
            "sv2_public_key": public_key, "sv2_public_key_fingerprint": fingerprint,
            "retention_days": self.settings.retention_days,
        }

    def _enrich_block(self, height: int, worker: str, found_at: float) -> dict[str, Any]:
        node = self.node(force=True)
        if not height:
            height = integer(node.get("blocks"))
        block_hash = self.rpc.block_hash(height) if height else ""
        return {
            "height": height, "block_hash": block_hash, "worker_name": worker_label(worker),
            "btc_address": address_from_worker(worker),
            "reward_value": self.rpc.block_reward_sats(height, block_hash) if height else 0,
            "round_effort": 0.0, "net_difficulty": number(node.get("difficulty")),
            "found_at": found_at,
        }

    def blocks(self) -> list[dict[str, Any]]:
        rows = self.storage.blocks()
        for row in rows:
            if row.get("block_hash") and row.get("reward_value"):
                continue
            enriched = self._enrich_block(integer(row.get("height")), str(row.get("worker_name") or ""), time.time())
            enriched["found_at"] = time.time()
            self.storage.insert_block(enriched)
        return self.storage.blocks()
