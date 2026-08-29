"""Small durable SQLite store for CKPool log-derived history."""

from __future__ import annotations

import sqlite3
import time
from pathlib import Path
from typing import Any


def _iso(epoch: float | int | None) -> str | None:
    if epoch is None:
        return None
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(float(epoch)))


class Storage:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout=10000")
        return connection

    def _initialize(self) -> None:
        with self.connect() as db:
            db.executescript(
                """
                PRAGMA journal_mode=WAL;
                PRAGMA synchronous=NORMAL;
                CREATE TABLE IF NOT EXISTS log_state (
                    path TEXT PRIMARY KEY,
                    inode INTEGER NOT NULL,
                    offset INTEGER NOT NULL,
                    updated_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS authorizations (
                    client_id TEXT PRIMARY KEY,
                    worker_name TEXT NOT NULL,
                    btc_address TEXT NOT NULL DEFAULT '',
                    ip TEXT NOT NULL DEFAULT '',
                    updated_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS shares (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_key TEXT NOT NULL UNIQUE,
                    created_at REAL NOT NULL,
                    client_id TEXT NOT NULL DEFAULT '',
                    worker_name TEXT NOT NULL DEFAULT '',
                    btc_address TEXT NOT NULL DEFAULT '',
                    accepted INTEGER NOT NULL,
                    reason TEXT NOT NULL DEFAULT '',
                    share_difficulty REAL NOT NULL DEFAULT 0,
                    assigned_difficulty REAL NOT NULL DEFAULT 0,
                    work_difficulty REAL NOT NULL DEFAULT 0,
                    share_hash TEXT NOT NULL DEFAULT '',
                    block_found INTEGER NOT NULL DEFAULT 0
                );
                CREATE INDEX IF NOT EXISTS shares_created_idx ON shares(created_at DESC);
                CREATE INDEX IF NOT EXISTS shares_worker_idx ON shares(worker_name, created_at DESC);
                CREATE TABLE IF NOT EXISTS blocks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    height INTEGER NOT NULL UNIQUE,
                    block_hash TEXT NOT NULL DEFAULT '',
                    worker_name TEXT NOT NULL DEFAULT '',
                    btc_address TEXT NOT NULL DEFAULT '',
                    reward_value INTEGER NOT NULL DEFAULT 0,
                    round_effort REAL NOT NULL DEFAULT 0,
                    net_difficulty REAL NOT NULL DEFAULT 0,
                    found_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS history (
                    bucket INTEGER PRIMARY KEY,
                    hashrate REAL NOT NULL DEFAULT 0,
                    workers INTEGER NOT NULL DEFAULT 0,
                    connections INTEGER NOT NULL DEFAULT 0
                );
                """
            )

    def log_state(self, path: str) -> tuple[int, int] | None:
        with self.connect() as db:
            row = db.execute("SELECT inode, offset FROM log_state WHERE path=?", (path,)).fetchone()
        return (int(row["inode"]), int(row["offset"])) if row else None

    def set_log_state(self, path: str, inode: int, offset: int) -> None:
        with self.connect() as db:
            db.execute(
                "INSERT INTO log_state(path,inode,offset,updated_at) VALUES(?,?,?,?) "
                "ON CONFLICT(path) DO UPDATE SET inode=excluded.inode,offset=excluded.offset,updated_at=excluded.updated_at",
                (path, inode, offset, time.time()),
            )

    def authorize(self, client_id: str, worker: str, address: str, ip: str, when: float) -> None:
        with self.connect() as db:
            db.execute(
                "INSERT INTO authorizations(client_id,worker_name,btc_address,ip,updated_at) VALUES(?,?,?,?,?) "
                "ON CONFLICT(client_id) DO UPDATE SET worker_name=excluded.worker_name,"
                "btc_address=excluded.btc_address,ip=excluded.ip,updated_at=excluded.updated_at",
                (client_id, worker, address, ip, when),
            )

    def authorization(self, client_id: str) -> dict[str, Any]:
        with self.connect() as db:
            row = db.execute("SELECT * FROM authorizations WHERE client_id=?", (client_id,)).fetchone()
        return dict(row) if row else {}

    def insert_share(self, share: dict[str, Any]) -> bool:
        values = (
            share["event_key"], share["created_at"], share.get("client_id", ""),
            share.get("worker_name", ""), share.get("btc_address", ""),
            int(bool(share.get("accepted"))), share.get("reason", ""),
            float(share.get("share_difficulty", 0)), float(share.get("assigned_difficulty", 0)),
            float(share.get("work_difficulty", 0)), share.get("share_hash", ""),
            int(bool(share.get("block_found"))),
        )
        with self.connect() as db:
            cursor = db.execute(
                "INSERT OR IGNORE INTO shares(event_key,created_at,client_id,worker_name,btc_address,accepted,reason,"
                "share_difficulty,assigned_difficulty,work_difficulty,share_hash,block_found) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                values,
            )
        return cursor.rowcount > 0

    def insert_block(self, block: dict[str, Any]) -> None:
        with self.connect() as db:
            db.execute(
                "INSERT INTO blocks(height,block_hash,worker_name,btc_address,reward_value,round_effort,net_difficulty,found_at) "
                "VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(height) DO UPDATE SET "
                "block_hash=CASE WHEN excluded.block_hash<>'' THEN excluded.block_hash ELSE blocks.block_hash END,"
                "worker_name=CASE WHEN excluded.worker_name<>'' THEN excluded.worker_name ELSE blocks.worker_name END,"
                "btc_address=CASE WHEN excluded.btc_address<>'' THEN excluded.btc_address ELSE blocks.btc_address END,"
                "reward_value=MAX(blocks.reward_value,excluded.reward_value),"
                "round_effort=MAX(blocks.round_effort,excluded.round_effort),"
                "net_difficulty=MAX(blocks.net_difficulty,excluded.net_difficulty)",
                (
                    int(block["height"]), block.get("block_hash", ""), block.get("worker_name", ""),
                    block.get("btc_address", ""), int(block.get("reward_value", 0)),
                    float(block.get("round_effort", 0)), float(block.get("net_difficulty", 0)),
                    float(block.get("found_at", time.time())),
                ),
            )
            where, params = "accepted=1 AND created_at BETWEEN ? AND ?", [float(block.get("found_at", time.time())) - 180, float(block.get("found_at", time.time())) + 10]
            if block.get("worker_name"):
                where += " AND worker_name=?"
                params.append(block["worker_name"])
            row = db.execute(f"SELECT id FROM shares WHERE {where} ORDER BY created_at DESC LIMIT 1", params).fetchone()
            if row:
                db.execute("UPDATE shares SET block_found=1 WHERE id=?", (row["id"],))

    def update_block_effort(self, height: int, round_diff: float, net_diff: float = 0) -> None:
        with self.connect() as db:
            db.execute(
                "UPDATE blocks SET round_effort=?,net_difficulty=CASE WHEN ?>0 THEN ? ELSE net_difficulty END WHERE height=?",
                (round_diff, net_diff, net_diff, height),
            )

    def record_history(self, hashrate: float, workers: int, connections: int, epoch: float | None = None) -> None:
        bucket = int((epoch or time.time()) // 60 * 60)
        with self.connect() as db:
            db.execute(
                "INSERT INTO history(bucket,hashrate,workers,connections) VALUES(?,?,?,?) "
                "ON CONFLICT(bucket) DO UPDATE SET hashrate=excluded.hashrate,workers=excluded.workers,connections=excluded.connections",
                (bucket, hashrate, workers, connections),
            )

    def history(self, hours: int) -> list[dict[str, Any]]:
        cutoff = time.time() - max(1, min(hours, 168)) * 3600
        with self.connect() as db:
            rows = db.execute("SELECT bucket,hashrate FROM history WHERE bucket>=? ORDER BY bucket", (cutoff,)).fetchall()
        return [{"time": int(row["bucket"]), "hashrate": float(row["hashrate"])} for row in rows]

    def shares(self, limit: int = 100) -> list[dict[str, Any]]:
        with self.connect() as db:
            rows = db.execute("SELECT * FROM shares ORDER BY created_at DESC LIMIT ?", (max(1, min(limit, 500)),)).fetchall()
        return [
            {
                "worker_name": row["worker_name"], "btc_address": row["btc_address"],
                "accepted": bool(row["accepted"]), "block_found": bool(row["block_found"]),
                "share_difficulty": float(row["share_difficulty"]), "client_id": row["client_id"],
                "job_id": row["client_id"], "share_hash": row["share_hash"], "reason": row["reason"],
                "created_at": _iso(row["created_at"]),
            }
            for row in rows
        ]

    def blocks(self) -> list[dict[str, Any]]:
        with self.connect() as db:
            rows = db.execute("SELECT * FROM blocks ORDER BY height DESC").fetchall()
        result = []
        for row in rows:
            value = dict(row)
            value["found_at"] = _iso(value["found_at"])
            result.append(value)
        return result

    def block_count(self) -> int:
        with self.connect() as db:
            return int(db.execute("SELECT COUNT(*) FROM blocks").fetchone()[0])

    def analytics(self) -> dict[str, Any]:
        now = time.time()
        output: dict[str, Any] = {}
        with self.connect() as db:
            for label, seconds in (("1h", 3600), ("24h", 86400)):
                row = db.execute(
                    "SELECT SUM(CASE WHEN accepted=1 THEN 1 ELSE 0 END) accepted,"
                    "SUM(CASE WHEN accepted=0 THEN 1 ELSE 0 END) rejected,"
                    "SUM(CASE WHEN accepted=1 THEN share_difficulty ELSE 0 END) accepted_diff,"
                    "SUM(CASE WHEN accepted=0 THEN share_difficulty ELSE 0 END) rejected_diff "
                    "FROM shares WHERE created_at>=?", (now - seconds,),
                ).fetchone()
                output[f"accepted_{label}"] = int(row["accepted"] or 0)
                output[f"rejected_{label}"] = int(row["rejected"] or 0)
                output[f"accepted_diff_{label}"] = float(row["accepted_diff"] or 0)
                output[f"rejected_diff_{label}"] = float(row["rejected_diff"] or 0)
            row = db.execute("SELECT MAX(created_at) value FROM shares").fetchone()
            output["last_share_at"] = _iso(row["value"])
            row = db.execute("SELECT AVG(hashrate) avg,MAX(hashrate) peak FROM history WHERE bucket>=?", (now - 21600,)).fetchone()
            output["avg_hashrate_6h"] = float(row["avg"] or 0)
            output["peak_hashrate_6h"] = float(row["peak"] or 0)
        return output

    def worker_stats(self) -> dict[str, dict[str, Any]]:
        with self.connect() as db:
            rows = db.execute(
                "SELECT worker_name,"
                "SUM(CASE WHEN accepted=1 THEN 1 ELSE 0 END) accepted,"
                "SUM(CASE WHEN accepted=0 THEN 1 ELSE 0 END) rejected,"
                "MAX(share_difficulty) best,MAX(created_at) last_share "
                "FROM shares GROUP BY worker_name"
            ).fetchall()
            best_rows = db.execute(
                "SELECT s.worker_name,s.share_hash FROM shares s JOIN "
                "(SELECT worker_name,MAX(share_difficulty) best FROM shares GROUP BY worker_name) b "
                "ON s.worker_name=b.worker_name AND s.share_difficulty=b.best GROUP BY s.worker_name"
            ).fetchall()
        hashes = {row["worker_name"]: row["share_hash"] for row in best_rows}
        return {
            row["worker_name"]: {
                "accepted": int(row["accepted"] or 0), "rejected": int(row["rejected"] or 0),
                "best": float(row["best"] or 0), "best_hash": hashes.get(row["worker_name"], ""),
                "last_share": float(row["last_share"] or 0),
            }
            for row in rows
        }

    def global_best(self) -> float:
        with self.connect() as db:
            row = db.execute("SELECT MAX(share_difficulty) FROM shares").fetchone()
        return float(row[0] or 0)

    def cleanup(self, retention_days: int) -> None:
        cutoff = time.time() - retention_days * 86400
        with self.connect() as db:
            db.execute("DELETE FROM shares WHERE created_at<? AND block_found=0", (cutoff,))
            db.execute("DELETE FROM history WHERE bucket<?", (cutoff,))
