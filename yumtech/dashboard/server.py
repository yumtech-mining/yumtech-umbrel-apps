#!/usr/bin/env python3

"""YUMTECH mining dashboard API and static web server.

Only allow-listed operational data is returned to the browser. Bitcoin RPC and
database credentials always remain inside the dashboard container.
"""

import base64
import hashlib
import json
import os
import posixpath
import subprocess
import threading
import time
from datetime import datetime, timedelta, timezone
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, unquote, urlparse
from urllib.request import Request, urlopen

import psycopg2
import psycopg2.extras


HOST = "0.0.0.0"
PORT = int(os.environ.get("DASHBOARD_PORT", "8095"))

DB_HOST = os.environ.get("DB_HOST", "127.0.0.1")
DB_PORT = int(os.environ.get("DB_PORT", "5432"))
DB_NAME = os.environ.get("DB_NAME", "mkpool")
DB_USER = os.environ.get("DB_USER", "mkpool_user")
DB_PASS = os.environ.get("DB_PASS", "")

MKPOOL_CTL = os.environ.get(
    "MKPOOL_CTL",
    "/opt/yumtech/mkpool-src/scripts/mkpool-ctl.py",
)
MKPOOL_SOCKET = os.environ.get(
    "MKPOOL_SOCKET",
    "/run/mkpool/mkpool.sock",
)

BITCOIN_RPC_HOST = os.environ.get("BITCOIN_RPC_HOST", "127.0.0.1")
BITCOIN_RPC_PORT = int(os.environ.get("BITCOIN_RPC_PORT", "8332"))
BITCOIN_RPC_USER = os.environ.get("BITCOIN_RPC_USER", "")
BITCOIN_RPC_PASS = os.environ.get("BITCOIN_RPC_PASS", "")
BITCOIN_RPC_TIMEOUT = float(os.environ.get("BITCOIN_RPC_TIMEOUT", "4"))
SV2_PUBLIC_KEY_FILE = os.environ.get(
    "SV2_PUBLIC_KEY_FILE",
    "/data/public/sv2-authority-public.hex",
)

STATIC_DIR = os.path.realpath(os.path.join(os.path.dirname(__file__), "static"))
BITCOIN_DIFF1_TARGET = 0xFFFF << 208

POOL_CONFIG = {
    "name": "YUMTECH",
    "coin": "BTC",
    "mode": "Solo",
    "coinbase_signature": "/YUMTECH/",
    "sv1_port": 3333,
    "sv2_port": 3340,
    "starting_difficulty": 16_384,
    "vardiff_min": 1024,
    "vardiff_max": 10_000_000,
    "target_shares_per_minute": 12,
    "vardiff_tau_seconds": 30,
    "block_poll_seconds": 10,
    "version_rolling_mask": "1fffe000",
    "share_retention_hours": 6,
}

_node_cache = {"updated": 0.0, "data": None}
_node_cache_lock = threading.Lock()


def db():
    return psycopg2.connect(
        host=DB_HOST,
        port=DB_PORT,
        dbname=DB_NAME,
        user=DB_USER,
        password=DB_PASS,
        connect_timeout=3,
        application_name="yumtech-dashboard",
    )


def ctl(command):
    """Read one allow-listed command from mkpool's owner-only control socket."""
    try:
        output = subprocess.check_output(
            [
                "python3",
                MKPOOL_CTL,
                "--socket",
                MKPOOL_SOCKET,
                command,
            ],
            text=True,
            timeout=3,
            stderr=subprocess.DEVNULL,
        )
        parsed = json.loads(output)
        return parsed if isinstance(parsed, dict) else {}
    except (OSError, ValueError, subprocess.SubprocessError):
        return {}


def as_float(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def as_int(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def iso(value):
    return value.isoformat() if value else None


def node_identity(subversion):
    """Return a safe display identity for the connected Bitcoin node."""
    normalized = str(subversion or "").casefold()
    if "knots" in normalized:
        return "knots", "Bitcoin Knots"
    if "satoshi" in normalized or "bitcoin core" in normalized:
        return "core", "Bitcoin Core"
    return "unknown", "Bitcoin Node"


def share_difficulty_from_hash(value, fallback=0.0):
    """Calculate the achieved Bitcoin pdiff from a displayed block hash."""
    try:
        share_hash = int(str(value or ""), 16)
        if share_hash <= 0:
            return as_float(fallback)
        return float(BITCOIN_DIFF1_TARGET / share_hash)
    except (TypeError, ValueError, OverflowError):
        return as_float(fallback)


def overview():
    stats = ctl("stats")
    version = ctl("version")

    best_round = 0.0
    template_height = 0
    template_prevhash = ""
    for coin in stats.get("coins", []):
        if coin.get("name") == "BTC":
            best_round = as_float(coin.get("best_share_round"))
            template_height = as_int(coin.get("template_height"))
            template_prevhash = str(coin.get("template_prevhash") or "")

    data = {
        "hashrate_1m": 0.0,
        "hashrate_5m": 0.0,
        "workers": 0,
        "connections": 0,
        "best_share": best_round,
        "blocks": 0,
        "uptime_seconds": as_int(stats.get("uptime_seconds")),
        "online": bool(stats),
        "template_height": template_height,
        "template_prevhash": template_prevhash,
        "engine": "YUMTECH Engine",
        "engine_build": str(version.get("build") or ""),
    }

    db_hashrate_1m = 0.0
    db_hashrate_5m = 0.0
    db_workers = 0

    try:
        with db() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) FROM blocks WHERE height > 0")
                data["blocks"] = as_int(cur.fetchone()[0])

                cur.execute(
                    """
                    SELECT GREATEST(
                        COALESCE(MAX(best_share_difficulty), 0),
                        COALESCE((
                            SELECT MAX(difficulty)
                            FROM raw_shares
                            WHERE accepted = TRUE
                        ), 0)
                    )
                    FROM miners
                    """
                )
                persistent_best = max(
                    data["best_share"], as_float(cur.fetchone()[0])
                )
                cur.execute(
                    """
                    INSERT INTO yumtech_dashboard_state (
                        id, all_time_best_share, updated_at
                    )
                    VALUES (1, %s, NOW())
                    ON CONFLICT (id) DO UPDATE
                    SET all_time_best_share = GREATEST(
                            yumtech_dashboard_state.all_time_best_share,
                            EXCLUDED.all_time_best_share
                        ),
                        updated_at = NOW()
                    RETURNING all_time_best_share
                    """,
                    (persistent_best,),
                )
                data["best_share"] = as_float(cur.fetchone()[0])

                cur.execute(
                    """
                    SELECT
                        COALESCE(SUM(difficulty) FILTER (
                            WHERE accepted
                              AND created_at >= NOW() - INTERVAL '1 minute'
                        ), 0),
                        COALESCE(SUM(difficulty) FILTER (
                            WHERE accepted
                              AND created_at >= NOW() - INTERVAL '5 minutes'
                        ), 0),
                        COUNT(DISTINCT miner_id) FILTER (
                            WHERE accepted
                              AND created_at >= NOW() - INTERVAL '2 minutes'
                        )
                    FROM raw_shares
                    """
                )
                diff_1m, diff_5m, db_workers = cur.fetchone()
                db_hashrate_1m = as_float(diff_1m) * 4294967296.0 / 60.0
                db_hashrate_5m = as_float(diff_5m) * 4294967296.0 / 300.0
                db_workers = as_int(db_workers)
    except psycopg2.Error:
        pass

    ctl_hashrate_1m = as_float(stats.get("hashrate_1m"))
    ctl_hashrate_5m = as_float(stats.get("hashrate_5m"))
    ctl_workers = as_int(stats.get("authorized"))

    live_clients = []
    if not ctl_hashrate_1m or not ctl_hashrate_5m or not ctl_workers:
        live_clients = [
            client
            for client in ctl("clients").get("clients", [])
            if isinstance(client, dict) and client.get("authorized", True)
        ]
    client_hashrate_1m = sum(
        as_float(client.get("hashrate_1m")) for client in live_clients
    )
    client_hashrate_5m = sum(
        as_float(client.get("hashrate_5m")) for client in live_clients
    )
    client_workers = len(
        {
            (
                str(client.get("address") or ""),
                str(client.get("worker") or "worker"),
            )
            for client in live_clients
        }
    )

    data["hashrate_1m"] = (
        ctl_hashrate_1m or client_hashrate_1m or db_hashrate_1m
    )
    data["hashrate_5m"] = (
        ctl_hashrate_5m or client_hashrate_5m or db_hashrate_5m
    )
    data["workers"] = ctl_workers or client_workers or db_workers
    data["connections"] = (
        as_int(stats.get("connections")) or len(live_clients) or db_workers
    )
    data["online"] = bool(stats) or bool(live_clients) or db_workers > 0
    return data


def analytics():
    data = {
        "accepted_1h": 0,
        "rejected_1h": 0,
        "accepted_24h": 0,
        "rejected_24h": 0,
        "accepted_diff_1h": 0.0,
        "rejected_diff_1h": 0.0,
        "round_diff": 0.0,
        "round_effort_pct": 0.0,
        "network_difficulty": 0.0,
        "network_hashrate": 0.0,
        "block_height": 0,
        "block_reward": 0.0,
        "network_updated_at": None,
        "avg_hashrate_6h": 0.0,
        "peak_hashrate_6h": 0.0,
        "last_share_at": None,
    }

    try:
        with db() as conn:
            with conn.cursor(
                cursor_factory=psycopg2.extras.RealDictCursor
            ) as cur:
                cur.execute(
                    """
                    SELECT
                        COUNT(*) FILTER (
                            WHERE accepted
                              AND created_at >= NOW() - INTERVAL '1 hour'
                        ) AS accepted_1h,
                        COUNT(*) FILTER (
                            WHERE NOT accepted
                              AND created_at >= NOW() - INTERVAL '1 hour'
                        ) AS rejected_1h,
                        COUNT(*) FILTER (
                            WHERE accepted
                              AND created_at >= NOW() - INTERVAL '24 hours'
                        ) AS accepted_24h,
                        COUNT(*) FILTER (
                            WHERE NOT accepted
                              AND created_at >= NOW() - INTERVAL '24 hours'
                        ) AS rejected_24h,
                        COALESCE(SUM(difficulty) FILTER (
                            WHERE accepted
                              AND created_at >= NOW() - INTERVAL '1 hour'
                        ), 0) AS accepted_diff_1h,
                        COALESCE(SUM(difficulty) FILTER (
                            WHERE NOT accepted
                              AND created_at >= NOW() - INTERVAL '1 hour'
                        ), 0) AS rejected_diff_1h,
                        MAX(created_at) FILTER (WHERE accepted) AS last_share_at
                    FROM raw_shares
                    """
                )
                row = cur.fetchone() or {}
                for key in (
                    "accepted_1h",
                    "rejected_1h",
                    "accepted_24h",
                    "rejected_24h",
                ):
                    data[key] = as_int(row.get(key))
                data["accepted_diff_1h"] = as_float(
                    row.get("accepted_diff_1h")
                )
                data["rejected_diff_1h"] = as_float(
                    row.get("rejected_diff_1h")
                )
                data["last_share_at"] = iso(row.get("last_share_at"))

                cur.execute(
                    "SELECT COALESCE(accum_diff, 0) AS accum_diff "
                    "FROM effort_state ORDER BY id LIMIT 1"
                )
                row = cur.fetchone()
                if row:
                    data["round_diff"] = as_float(row["accum_diff"])

                cur.execute(
                    """
                    SELECT network_difficulty, network_hashrate, block_height,
                           block_reward, updated_at
                    FROM network_stats
                    WHERE UPPER(coin) = 'BTC'
                    LIMIT 1
                    """
                )
                row = cur.fetchone()
                if row:
                    data["network_difficulty"] = as_float(
                        row["network_difficulty"]
                    )
                    data["network_hashrate"] = as_float(
                        row["network_hashrate"]
                    )
                    data["block_height"] = as_int(row["block_height"])
                    data["block_reward"] = as_float(row["block_reward"])
                    data["network_updated_at"] = iso(row["updated_at"])

                cur.execute(
                    """
                    SELECT COALESCE(AVG(pool_hr), 0) AS avg_hr,
                           COALESCE(MAX(pool_hr), 0) AS peak_hr
                    FROM (
                        SELECT created_at, SUM(hashrate) AS pool_hr
                        FROM hashrates
                        WHERE created_at >= NOW() - INTERVAL '6 hours'
                        GROUP BY created_at
                    ) q
                    """
                )
                row = cur.fetchone()
                if row:
                    data["avg_hashrate_6h"] = as_float(row["avg_hr"])
                    data["peak_hashrate_6h"] = as_float(row["peak_hr"])

                if not data["avg_hashrate_6h"]:
                    cur.execute(
                        """
                        SELECT COALESCE(AVG(pool_hr), 0) AS avg_hr,
                               COALESCE(MAX(pool_hr), 0) AS peak_hr
                        FROM (
                            SELECT time_bucket(
                                       INTERVAL '5 minutes', created_at
                                   ) AS bucket,
                                   SUM(difficulty) * 4294967296.0 / 300.0
                                       AS pool_hr
                            FROM raw_shares
                            WHERE accepted
                              AND created_at >= NOW() - INTERVAL '6 hours'
                            GROUP BY bucket
                        ) q
                        """
                    )
                    row = cur.fetchone()
                    if row:
                        data["avg_hashrate_6h"] = as_float(row["avg_hr"])
                        data["peak_hashrate_6h"] = as_float(row["peak_hr"])
    except psycopg2.Error:
        pass

    if data["network_difficulty"] <= 0:
        try:
            mining = bitcoin_rpc_batch(("getmininginfo",)).get(
                "getmininginfo"
            ) or {}
            data["network_difficulty"] = as_float(mining.get("difficulty"))
            data["network_hashrate"] = as_float(mining.get("networkhashps"))
            data["block_height"] = as_int(mining.get("blocks"))
        except RuntimeError:
            pass

    if data["network_difficulty"] > 0:
        data["round_effort_pct"] = (
            data["round_diff"] / data["network_difficulty"] * 100.0
        )
    return data


def _live_client_maps():
    payload = ctl("clients")
    by_id = {}
    by_worker = {}

    for client in payload.get("clients", []):
        if not isinstance(client, dict):
            continue
        miner_id = as_int(client.get("miner_id"), -1)
        if miner_id >= 0:
            by_id.setdefault(miner_id, []).append(client)
        worker_key = (
            str(client.get("address") or ""),
            str(client.get("worker") or "worker"),
        )
        by_worker.setdefault(worker_key, []).append(client)
    return by_id, by_worker


def miners():
    by_id, by_worker = _live_client_maps()

    try:
        with db() as conn:
            with conn.cursor(
                cursor_factory=psycopg2.extras.RealDictCursor
            ) as cur:
                cur.execute(
                    """
                    SELECT
                        m.id,
                        m.btc_address,
                        COALESCE(NULLIF(m.worker_name, ''), 'worker') AS worker_name,
                        m.status::text AS status,
                        GREATEST(
                            COALESCE(m.best_share_difficulty, 0),
                            COALESCE((
                                SELECT MAX(rs.difficulty)
                                FROM raw_shares rs
                                WHERE rs.miner_id = m.id
                                  AND rs.accepted = TRUE
                            ), 0)
                        ) AS best_share_difficulty,
                        COALESCE(m.best_share_hash, '') AS best_share_hash,
                        COALESCE((
                            SELECT MAX(rs.created_at)
                            FROM raw_shares rs
                            WHERE rs.miner_id = m.id AND rs.accepted = TRUE
                        ), m.last_share_at) AS last_share_at,
                        COALESCE((
                            SELECT SUM(rs.difficulty) * 4294967296.0 / 300.0
                            FROM raw_shares rs
                            WHERE rs.miner_id = m.id
                              AND rs.accepted = TRUE
                              AND rs.created_at >= NOW() - INTERVAL '5 minutes'
                        ), (
                            SELECT h.hashrate
                            FROM hashrates h
                            WHERE h.miner_id = m.id
                            ORDER BY h.created_at DESC
                            LIMIT 1
                        ), 0) AS hashrate
                    FROM miners m
                    ORDER BY m.updated_at DESC
                    """
                )
                rows = cur.fetchall()
    except psycopg2.Error:
        return []

    result = []
    for row in rows:
        clients = by_id.get(as_int(row["id"])) or by_worker.get(
            (str(row["btc_address"]), str(row["worker_name"])),
            [],
        )

        live_hashrate_1m = sum(as_float(c.get("hashrate_1m")) for c in clients)
        live_hashrate_5m = sum(as_float(c.get("hashrate_5m")) for c in clients)
        accepted = sum(as_int(c.get("shares_accepted")) for c in clients)
        rejected = sum(as_int(c.get("shares_rejected")) for c in clients)
        difficulties = [as_float(c.get("difficulty")) for c in clients]
        protocols = sorted(
            {str(c.get("protocol") or "SV1").upper() for c in clients}
        )
        user_agents = sorted(
            {str(c.get("user_agent") or "").strip() for c in clients}
            - {""}
        )
        ips = sorted({str(c.get("ip") or "") for c in clients} - {""})
        connected_seconds = max(
            [as_int(c.get("connected_secs")) for c in clients] or [0]
        )
        idle_values = [
            as_int(c.get("idle_secs"))
            for c in clients
            if as_int(c.get("idle_secs"), -1) >= 0
        ]
        idle_seconds = min(idle_values or [-1])
        last_share_at = row["last_share_at"]
        if idle_seconds >= 0:
            live_last_share_at = datetime.now(timezone.utc) - timedelta(
                seconds=idle_seconds
            )
            if not last_share_at or live_last_share_at > last_share_at:
                last_share_at = live_last_share_at

        result.append(
            {
                "id": as_int(row["id"]),
                "btc_address": row["btc_address"],
                "worker_name": row["worker_name"],
                "status": "online" if clients else "offline",
                "best_share_difficulty": as_float(
                    row["best_share_difficulty"]
                ),
                "best_share_hash": row["best_share_hash"],
                "last_share_at": iso(last_share_at),
                "hashrate": live_hashrate_1m or as_float(row["hashrate"]),
                "hashrate_1m": live_hashrate_1m,
                "hashrate_5m": live_hashrate_5m,
                "difficulty": max(difficulties or [0]),
                "shares_accepted": accepted,
                "shares_rejected": rejected,
                "connections": len(clients),
                "protocol": ", ".join(protocols) or "—",
                "user_agent": " · ".join(user_agents),
                "ip": ", ".join(ips),
                "connected_seconds": connected_seconds,
                "idle_seconds": idle_seconds,
            }
        )
    return result


def recent_shares(limit=50):
    limit = max(1, min(as_int(limit, 50), 200))
    try:
        with db() as conn:
            with conn.cursor(
                cursor_factory=psycopg2.extras.RealDictCursor
            ) as cur:
                cur.execute(
                    """
                    SELECT rs.created_at, rs.accepted, rs.difficulty,
                           EXISTS (
                               SELECT 1
                               FROM blocks b
                               WHERE b.block_hash = rs.share_hash
                           ) AS block_found,
                           rs.share_hash, rs.job_id,
                           m.worker_name, m.btc_address
                    FROM raw_shares rs
                    JOIN miners m ON m.id = rs.miner_id
                    ORDER BY rs.created_at DESC
                    LIMIT %s
                    """,
                    (limit,),
                )
                rows = cur.fetchall()
    except psycopg2.Error:
        return []

    return [
        {
            "created_at": iso(row["created_at"]),
            "accepted": bool(row["accepted"]),
            "share_difficulty": share_difficulty_from_hash(
                row["share_hash"], row["difficulty"]
            ),
            "assigned_difficulty": as_float(row["difficulty"]),
            "block_found": bool(row["block_found"]),
            "share_hash": str(row["share_hash"] or ""),
            "job_id": str(row["job_id"] or ""),
            "worker_name": str(row["worker_name"] or "worker"),
            "btc_address": str(row["btc_address"] or ""),
        }
        for row in rows
    ]


def blocks():
    try:
        with db() as conn:
            with conn.cursor(
                cursor_factory=psycopg2.extras.RealDictCursor
            ) as cur:
                cur.execute(
                    """
                    SELECT b.height, b.block_hash,
                           COALESCE(m.worker_name, '') AS worker_name,
                           COALESCE(m.btc_address, '') AS btc_address,
                           b.reward_value, b.difficulty, b.round_effort,
                           b.net_difficulty, b.finder_effort, b.found_at
                    FROM blocks b
                    LEFT JOIN miners m ON m.id = b.found_by
                    WHERE b.height > 0
                    ORDER BY b.height DESC
                    LIMIT 50
                    """
                )
                rows = cur.fetchall()
    except psycopg2.Error:
        return []

    return [
        {
            "height": as_int(row["height"]),
            "block_hash": str(row["block_hash"] or ""),
            "worker_name": str(row["worker_name"] or ""),
            "btc_address": str(row["btc_address"] or ""),
            "reward_value": as_int(row["reward_value"]),
            "difficulty": as_float(row["difficulty"]),
            "round_effort": as_float(row["round_effort"]),
            "net_difficulty": as_float(row["net_difficulty"]),
            "finder_effort": as_float(row["finder_effort"]),
            "found_at": iso(row["found_at"]),
        }
        for row in rows
    ]


def history(hours):
    hours = max(1, min(as_int(hours, 1), 168))
    bucket = (
        "1 minute"
        if hours <= 6
        else "5 minutes"
        if hours <= 24
        else "30 minutes"
    )
    bucket_seconds = 60 if hours <= 6 else 300 if hours <= 24 else 1800
    result = []

    try:
        with db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT EXTRACT(EPOCH FROM time_bucket(%s::interval, created_at))::BIGINT,
                           COALESCE(SUM(hashrate), 0)
                    FROM hashrates
                    WHERE created_at >= NOW() - (%s * INTERVAL '1 hour')
                    GROUP BY 1
                    ORDER BY 1
                    """,
                    (bucket, hours),
                )
                result = [
                    {"time": as_int(row[0]), "hashrate": as_float(row[1])}
                    for row in cur.fetchall()
                ]
                if not result:
                    cur.execute(
                        """
                        SELECT EXTRACT(EPOCH FROM time_bucket(
                                   %s::interval, created_at
                               ))::BIGINT,
                               COALESCE(
                                   SUM(difficulty) * 4294967296.0 / %s,
                                   0
                               )
                        FROM raw_shares
                        WHERE accepted
                          AND created_at >= NOW() - (%s * INTERVAL '1 hour')
                        GROUP BY 1
                        ORDER BY 1
                        """,
                        (bucket, bucket_seconds, hours),
                    )
                    result = [
                        {
                            "time": as_int(row[0]),
                            "hashrate": as_float(row[1]),
                        }
                        for row in cur.fetchall()
                    ]
    except psycopg2.Error:
        result = []

    stats = ctl("stats")
    live_hashrate = as_float(
        stats.get("hashrate_1m" if hours <= 1 else "hashrate_5m")
    )
    if live_hashrate > 0:
        now = int(time.time())
        if result and now - result[-1]["time"] < bucket_seconds:
            result[-1] = {"time": now, "hashrate": live_hashrate}
        else:
            result.append({"time": now, "hashrate": live_hashrate})
    return result


def difficulty_history(hours):
    hours = max(1, min(as_int(hours, 24), 720))
    bucket = "5 minutes" if hours <= 24 else "1 hour"
    try:
        with db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT EXTRACT(EPOCH FROM time_bucket(%s::interval, created_at))::BIGINT,
                           AVG(difficulty)
                    FROM network_difficulty_history
                    WHERE UPPER(coin) = 'BTC'
                      AND created_at >= NOW() - (%s * INTERVAL '1 hour')
                    GROUP BY 1
                    ORDER BY 1
                    """,
                    (bucket, hours),
                )
                return [
                    {"time": as_int(row[0]), "difficulty": as_float(row[1])}
                    for row in cur.fetchall()
                ]
    except psycopg2.Error:
        return []


def bitcoin_rpc_batch(methods):
    if not BITCOIN_RPC_USER or not BITCOIN_RPC_PASS:
        raise RuntimeError("Bitcoin RPC credentials are not configured")

    payload = [
        {"jsonrpc": "1.0", "id": method, "method": method, "params": []}
        for method in methods
    ]
    credentials = base64.b64encode(
        f"{BITCOIN_RPC_USER}:{BITCOIN_RPC_PASS}".encode("utf-8")
    ).decode("ascii")
    request = Request(
        f"http://{BITCOIN_RPC_HOST}:{BITCOIN_RPC_PORT}/",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Basic {credentials}",
            "Content-Type": "application/json",
            "Connection": "close",
        },
        method="POST",
    )

    try:
        with urlopen(request, timeout=BITCOIN_RPC_TIMEOUT) as response:
            raw = json.loads(response.read().decode("utf-8"))
    except (HTTPError, URLError, OSError, ValueError) as exc:
        raise RuntimeError("Bitcoin RPC is unavailable") from exc

    result = {}
    for item in raw if isinstance(raw, list) else []:
        if isinstance(item, dict) and not item.get("error"):
            result[str(item.get("id"))] = item.get("result")
    return result


def _fresh_node_data():
    methods = (
        "getblockchaininfo",
        "getnetworkinfo",
        "getmempoolinfo",
        "getmininginfo",
        "getindexinfo",
        "getchaintips",
        "uptime",
    )
    try:
        rpc = bitcoin_rpc_batch(methods)
    except RuntimeError:
        return {
            "online": False,
            "checked_at": datetime.now(timezone.utc).isoformat(),
            "node_implementation": "unknown",
            "node_name": "Bitcoin Node",
            "message": "Bitcoin node RPC baglantisi kurulamadi.",
        }

    chain = rpc.get("getblockchaininfo") or {}
    network = rpc.get("getnetworkinfo") or {}
    mempool = rpc.get("getmempoolinfo") or {}
    mining = rpc.get("getmininginfo") or {}
    indexes = rpc.get("getindexinfo") or {}
    tips = rpc.get("getchaintips") or []
    now = int(time.time())

    safe_indexes = {}
    for name, value in indexes.items() if isinstance(indexes, dict) else []:
        if isinstance(value, dict):
            safe_indexes[str(name)] = {
                "synced": bool(value.get("synced")),
                "best_block_height": as_int(value.get("best_block_height")),
            }

    tip_counts = {}
    for tip in tips if isinstance(tips, list) else []:
        if not isinstance(tip, dict):
            continue
        status = str(tip.get("status") or "unknown")
        tip_counts[status] = tip_counts.get(status, 0) + 1

    sync_progress = max(0.0, min(1.0, as_float(chain.get("verificationprogress"))))
    block_time = as_int(chain.get("time"))
    subversion = str(network.get("subversion") or "").strip("/")
    node_implementation, node_name = node_identity(subversion)

    return {
        "online": bool(chain),
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "node_implementation": node_implementation,
        "node_name": node_name,
        "chain": str(chain.get("chain") or mining.get("chain") or ""),
        "blocks": as_int(chain.get("blocks")),
        "headers": as_int(chain.get("headers")),
        "bestblockhash": str(chain.get("bestblockhash") or ""),
        "difficulty": as_float(chain.get("difficulty") or mining.get("difficulty")),
        "verification_progress": sync_progress,
        "sync_percent": sync_progress * 100.0,
        "initial_block_download": bool(chain.get("initialblockdownload")),
        "chainwork": str(chain.get("chainwork") or ""),
        "pruned": bool(chain.get("pruned")),
        "prune_height": as_int(chain.get("pruneheight")),
        "size_on_disk": as_int(chain.get("size_on_disk")),
        "block_time": block_time,
        "tip_age_seconds": max(0, now - block_time) if block_time else 0,
        "version": as_int(network.get("version")),
        "subversion": subversion,
        "protocol_version": as_int(network.get("protocolversion")),
        "network_active": bool(network.get("networkactive", True)),
        "connections": as_int(network.get("connections")),
        "connections_in": as_int(network.get("connections_in")),
        "connections_out": as_int(network.get("connections_out")),
        "relay_fee": as_float(network.get("relayfee")),
        "incremental_fee": as_float(network.get("incrementalfee")),
        "uptime_seconds": as_int(rpc.get("uptime")),
        "network_hashrate": as_float(mining.get("networkhashps")),
        "pooled_transactions": as_int(mining.get("pooledtx")),
        "mempool": {
            "transactions": as_int(mempool.get("size")),
            "bytes": as_int(mempool.get("bytes")),
            "usage": as_int(mempool.get("usage")),
            "max_mempool": as_int(mempool.get("maxmempool")),
            "total_fee": as_float(mempool.get("total_fee")),
            "mempool_min_fee": as_float(mempool.get("mempoolminfee")),
            "min_relay_fee": as_float(mempool.get("minrelaytxfee")),
            "unbroadcast_count": as_int(mempool.get("unbroadcastcount")),
            "full_rbf": bool(mempool.get("fullrbf")),
        },
        "indexes": safe_indexes,
        "chain_tips": tip_counts,
    }


def node_status():
    now = time.monotonic()
    with _node_cache_lock:
        if _node_cache["data"] is not None and now - _node_cache["updated"] < 8:
            return _node_cache["data"]
        data = _fresh_node_data()
        _node_cache["data"] = data
        _node_cache["updated"] = now
        return data


def sv2_public_identity():
    """Return only the publishable x-only key; never read the private key."""
    try:
        value = open(
            SV2_PUBLIC_KEY_FILE,
            "r",
            encoding="ascii",
        ).read().strip().lower()
        if len(value) != 64:
            return "", ""
        raw = bytes.fromhex(value)
        fingerprint = hashlib.sha256(raw).hexdigest()[:16]
        return value, fingerprint
    except (OSError, ValueError):
        return "", ""


def pool_config():
    version = ctl("version")
    public_key, fingerprint = sv2_public_identity()
    return {
        **POOL_CONFIG,
        "engine": "YUMTECH Engine",
        "engine_build": str(version.get("build") or ""),
        "sv2_public_key": public_key,
        "sv2_public_key_fingerprint": fingerprint,
    }


class Handler(SimpleHTTPRequestHandler):
    server_version = "YumtechDashboard/0.2.7"

    def translate_path(self, path):
        parsed = urlparse(path)
        requested = unquote(parsed.path)
        if requested == "/":
            requested = "/index.html"

        normalized = posixpath.normpath(requested).lstrip("/")
        parts = [
            part
            for part in normalized.split("/")
            if part not in ("", ".", "..")
        ]
        candidate = os.path.realpath(os.path.join(STATIC_DIR, *parts))

        if candidate != STATIC_DIR and not candidate.startswith(STATIC_DIR + os.sep):
            return os.path.join(STATIC_DIR, "404")
        return candidate

    def end_headers(self):
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "SAMEORIGIN")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; img-src 'self' data:; "
            "style-src 'self' 'unsafe-inline'; script-src 'self'; "
            "connect-src 'self'; object-src 'none'; base-uri 'self'",
        )
        super().end_headers()

    def json_response(self, data, status=200):
        body = json.dumps(data, ensure_ascii=False, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        parsed = urlparse(self.path)
        args = parse_qs(parsed.query)

        routes = {
            "/api/overview": overview,
            "/api/analytics": analytics,
            "/api/miners": miners,
            "/api/blocks": blocks,
            "/api/node": node_status,
            "/api/config": pool_config,
        }
        if parsed.path in routes:
            return self.json_response(routes[parsed.path]())
        if parsed.path == "/api/shares":
            return self.json_response(recent_shares(args.get("limit", ["50"])[0]))
        if parsed.path == "/api/history":
            return self.json_response(history(args.get("hours", ["1"])[0]))
        if parsed.path == "/api/difficulty-history":
            return self.json_response(
                difficulty_history(args.get("hours", ["24"])[0])
            )
        if parsed.path.startswith("/api/"):
            return self.json_response({"error": "not found"}, status=404)
        return super().do_GET()

    def log_message(self, fmt, *args):
        return


if __name__ == "__main__":
    print(f"YUMTECH dashboard :{PORT}", flush=True)
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()
