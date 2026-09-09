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
CREATE TABLE IF NOT EXISTS execution_intents (
 id TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
 mode TEXT NOT NULL CHECK(mode IN ('paper','live')), pair TEXT NOT NULL,
 buy_exchange TEXT NOT NULL, sell_exchange TEXT NOT NULL,
 requested_base TEXT NOT NULL, max_recovery_loss_try TEXT NOT NULL,
 state TEXT NOT NULL, expected_profit_try TEXT NOT NULL,
 realized_profit_try TEXT, error TEXT, created_at INTEGER NOT NULL, updated_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS execution_legs (
 id INTEGER PRIMARY KEY, intent_id TEXT NOT NULL REFERENCES execution_intents(id) ON DELETE CASCADE,
 exchange TEXT NOT NULL, side TEXT NOT NULL CHECK(side IN ('buy','sell')),
 requested_base TEXT NOT NULL, requested_price TEXT NOT NULL,
 filled_base TEXT NOT NULL DEFAULT '0', average_price TEXT,
 fee_try TEXT NOT NULL DEFAULT '0', external_order_id TEXT, status TEXT NOT NULL,
 created_at INTEGER NOT NULL, updated_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS execution_events (
 id INTEGER PRIMARY KEY, intent_id TEXT NOT NULL REFERENCES execution_intents(id) ON DELETE CASCADE,
 state TEXT NOT NULL, detail TEXT NOT NULL DEFAULT '{}', created_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_execution_intents_user_time
 ON execution_intents(user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_execution_events_intent
 ON execution_events(intent_id, id);
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

    def create_execution_intent(self, values: dict, legs: list[dict]) -> None:
        """Persist the intent and both legs atomically before any submission."""
        now = int(time.time() * 1000)
        with self.connect() as db:
            db.execute(
                "INSERT INTO execution_intents(id,user_id,mode,pair,buy_exchange,sell_exchange,"
                "requested_base,max_recovery_loss_try,state,expected_profit_try,created_at,updated_at) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                (values["id"], values["user_id"], values["mode"], values["pair"],
                 values["buy_exchange"], values["sell_exchange"], values["requested_base"],
                 values["max_recovery_loss_try"], values["state"], values["expected_profit_try"], now, now),
            )
            for leg in legs:
                db.execute(
                    "INSERT INTO execution_legs(intent_id,exchange,side,requested_base,requested_price,"
                    "status,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)",
                    (values["id"], leg["exchange"], leg["side"], leg["requested_base"],
                     leg["requested_price"], "PLANNED", now, now),
                )
            db.execute("INSERT INTO execution_events(intent_id,state,detail,created_at) VALUES(?,?,?,?)",
                       (values["id"], values["state"], "{}", now))

    def update_execution_state(self, intent_id: str, state: str, detail: str = "{}",
                               realized_profit_try: str | None = None, error: str | None = None) -> None:
        now = int(time.time() * 1000)
        with self.connect() as db:
            db.execute("UPDATE execution_intents SET state=?,realized_profit_try=COALESCE(?,realized_profit_try),"
                       "error=COALESCE(?,error),updated_at=? WHERE id=?",
                       (state, realized_profit_try, error, now, intent_id))
            db.execute("INSERT INTO execution_events(intent_id,state,detail,created_at) VALUES(?,?,?,?)",
                       (intent_id, state, detail, now))

    def update_execution_leg(self, intent_id: str, exchange: str, side: str, values: dict) -> None:
        with self.connect() as db:
            db.execute(
                "UPDATE execution_legs SET filled_base=?,average_price=?,fee_try=?,external_order_id=?,"
                "status=?,updated_at=? WHERE intent_id=? AND exchange=? AND side=?",
                (values["filled_base"], values.get("average_price"), values["fee_try"],
                 values.get("external_order_id"), values["status"], int(time.time() * 1000),
                intent_id, exchange, side),
            )

    def add_execution_leg(self, intent_id: str, leg: dict) -> None:
        now = int(time.time() * 1000)
        with self.connect() as db:
            db.execute(
                "INSERT INTO execution_legs(intent_id,exchange,side,requested_base,requested_price,"
                "filled_base,average_price,fee_try,external_order_id,status,created_at,updated_at) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                (intent_id, leg["exchange"], leg["side"], leg["requested_base"], leg["requested_price"],
                 leg["filled_base"], leg["average_price"], leg["fee_try"], leg["external_order_id"],
                 leg["status"], now, now),
            )

    def list_executions(self, user_id: int, limit: int = 100) -> list[dict]:
        with self.connect() as db:
            intents = [dict(row) for row in db.execute(
                "SELECT * FROM execution_intents WHERE user_id=? ORDER BY created_at DESC LIMIT ?",
                (user_id, min(max(limit, 1), 500)),
            )]
            for intent in intents:
                intent["legs"] = [dict(row) for row in db.execute(
                    "SELECT exchange,side,requested_base,requested_price,filled_base,average_price,"
                    "fee_try,external_order_id,status FROM execution_legs WHERE intent_id=? ORDER BY id",
                    (intent["id"],),
                )]
            return intents

    def halt_incomplete_executions(self) -> int:
        """Fail closed after a process restart; never resubmit an unknown leg."""
        now = int(time.time() * 1000)
        active_states = ("READY", "SUBMITTING", "PARTIAL_IMBALANCE", "RECOVERY")
        with self.connect() as db:
            rows = db.execute(
                f"SELECT id FROM execution_intents WHERE state IN ({','.join('?' for _ in active_states)})",
                active_states,
            ).fetchall()
            for row in rows:
                db.execute("UPDATE execution_intents SET state='HALTED',error=?,updated_at=? WHERE id=?",
                           ("Process restarted during execution; manual reconciliation required", now, row["id"]))
                db.execute("INSERT INTO execution_events(intent_id,state,detail,created_at) VALUES(?,?,?,?)",
                           (row["id"], "HALTED", '{"reason":"startup_reconciliation"}', now))
            return len(rows)
