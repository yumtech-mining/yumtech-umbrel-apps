"""Minimal dependency-free Bitcoin JSON-RPC client and telemetry adapter."""

from __future__ import annotations

import base64
import json
import time
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class BitcoinRpcError(RuntimeError):
    pass


def _number(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def node_identity(subversion: str) -> tuple[str, str]:
    normalized = str(subversion or "").casefold()
    if "knots" in normalized:
        return "knots", "Bitcoin Knots"
    if "satoshi" in normalized or "bitcoin core" in normalized:
        return "core", "Bitcoin Core"
    return "unknown", "Bitcoin Node"


class BitcoinRpc:
    def __init__(self, url: str, user: str, password: str, timeout: float = 4.0):
        self.url = url
        self.user = user
        self.password = password
        self.timeout = timeout

    def call(self, method: str, params: list[Any] | None = None) -> Any:
        payload = json.dumps({"jsonrpc": "1.0", "id": "yumtech", "method": method, "params": params or []}).encode()
        request = Request(self.url, data=payload, headers={"Content-Type": "application/json"})
        token = base64.b64encode(f"{self.user}:{self.password}".encode()).decode()
        request.add_header("Authorization", f"Basic {token}")
        try:
            with urlopen(request, timeout=self.timeout) as response:
                body = json.loads(response.read().decode("utf-8"))
        except (OSError, HTTPError, URLError, ValueError) as exc:
            raise BitcoinRpcError(str(exc)) from exc
        if body.get("error"):
            raise BitcoinRpcError(str(body["error"]))
        return body.get("result")

    def optional(self, method: str, params: list[Any] | None = None, default: Any = None) -> Any:
        try:
            return self.call(method, params)
        except BitcoinRpcError:
            return default

    def node_data(self) -> dict[str, Any]:
        chain = self.optional("getblockchaininfo")
        if not isinstance(chain, dict):
            return {"online": False, "node_name": "Bitcoin Node", "node_kind": "unknown"}
        network = self.optional("getnetworkinfo", default={}) or {}
        mempool = self.optional("getmempoolinfo", default={}) or {}
        mining = self.optional("getmininginfo", default={}) or {}
        network_hashrate = _number(mining.get("networkhashps"))
        if not network_hashrate:
            network_hashrate = _number(self.optional("getnetworkhashps", default=0))
        indexes = self.optional("getindexinfo", default={}) or {}
        tips = self.optional("getchaintips", default=[]) or []
        uptime = self.optional("uptime", default=0) or 0
        subversion = str(network.get("subversion") or "")
        kind, name = node_identity(subversion)
        tip_counts: dict[str, int] = {}
        for tip in tips if isinstance(tips, list) else []:
            status = str(tip.get("status") or "unknown")
            tip_counts[status] = tip_counts.get(status, 0) + 1
        progress = _number(chain.get("verificationprogress"))
        return {
            "online": True,
            "node_kind": kind,
            "node_name": name,
            "chain": chain.get("chain"),
            "blocks": int(chain.get("blocks") or 0),
            "headers": int(chain.get("headers") or 0),
            "bestblockhash": str(chain.get("bestblockhash") or ""),
            "sync_percent": max(0.0, min(100.0, progress * 100.0)),
            "initial_block_download": bool(chain.get("initialblockdownload")),
            "difficulty": _number(chain.get("difficulty") or mining.get("difficulty")),
            "size_on_disk": int(chain.get("size_on_disk") or 0),
            "pruned": bool(chain.get("pruned")),
            "prune_height": int(chain.get("pruneheight") or 0),
            "tip_age_seconds": max(0, int(time.time()) - int(chain.get("time") or time.time())),
            "subversion": subversion,
            "protocol_version": int(network.get("protocolversion") or 0),
            "network_active": bool(network.get("networkactive", True)),
            "connections": int(network.get("connections") or 0),
            "connections_in": int(network.get("connections_in") or 0),
            "connections_out": int(network.get("connections_out") or 0),
            "uptime_seconds": int(uptime),
            "mempool": {
                "transactions": int(mempool.get("size") or 0),
                "bytes": int(mempool.get("bytes") or 0),
                "usage": int(mempool.get("usage") or 0),
                "total_fee": _number(mempool.get("total_fee")),
            },
            "indexes": indexes if isinstance(indexes, dict) else {},
            "chain_tips": tip_counts,
            "network_hashrate": network_hashrate,
            "pooled_transactions": int(mining.get("pooledtx") or 0),
        }

    def block_hash(self, height: int) -> str:
        return str(self.optional("getblockhash", [height], "") or "")

    def block_reward_sats(self, height: int, block_hash: str = "") -> int:
        if block_hash:
            stats = self.optional("getblockstats", [block_hash, ["subsidy", "totalfee"]], {}) or {}
            if isinstance(stats, dict) and "subsidy" in stats:
                return int(stats.get("subsidy") or 0) + int(stats.get("totalfee") or 0)
        halvings = max(0, height // 210_000)
        return 0 if halvings >= 64 else (50 * 100_000_000) >> halvings
