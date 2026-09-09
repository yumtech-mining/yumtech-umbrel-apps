import sqlite3
import threading
import time
from contextlib import contextmanager
from pathlib import Path


SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS users (
 id INTEGER PRIMARY KEY, username TEXT NOT NULL UNIQUE COLLATE NOCASE,
 password_hash TEXT NOT NULL, is_admin INTEGER NOT NULL DEFAULT 0, created_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS sessions (
 token_hash TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
 csrf_token TEXT NOT NULL, expires_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS credentials (
 user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE, exchange TEXT NOT NULL,
 api_key_enc TEXT NOT NULL, secret_enc TEXT NOT NULL, key_hint TEXT NOT NULL,
 validated_at INTEGER, PRIMARY KEY(user_id, exchange)
);
CREATE TABLE IF NOT EXISTS user_settings (
 user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
 mode TEXT NOT NULL DEFAULT 'test' CHECK(mode IN ('test','live')),
 max_trade_try TEXT NOT NULL DEFAULT '1000', daily_loss_limit_try TEXT NOT NULL DEFAULT '250',
 max_recovery_loss_try TEXT NOT NULL DEFAULT '100', active INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS audit_log (
 id INTEGER PRIMARY KEY, user_id INTEGER, event TEXT NOT NULL, detail TEXT NOT NULL DEFAULT '{}',
 created_at INTEGER NOT NULL
);
"""


class Database:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self._lock = threading.RLock()
        with self.connect() as db:
            db.executescript(SCHEMA)
            columns = {row[1] for row in db.execute("PRAGMA table_info(users)")}
            if "is_admin" not in columns:
                db.execute("ALTER TABLE users ADD COLUMN is_admin INTEGER NOT NULL DEFAULT 0")

    @contextmanager
    def connect(self):
        with self._lock:
            db = sqlite3.connect(self.path)
            db.row_factory = sqlite3.Row
            try:
                yield db
                db.commit()
            finally:
                db.close()

    def audit(self, user_id: int | None, event: str, detail: str = "{}") -> None:
        with self.connect() as db:
            db.execute("INSERT INTO audit_log(user_id,event,detail,created_at) VALUES(?,?,?,?)",
                       (user_id, event, detail, int(time.time())))
