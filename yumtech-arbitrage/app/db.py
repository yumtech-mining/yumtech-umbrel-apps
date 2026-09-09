import sqlite3
import threading
import time
from contextlib import contextmanager
from decimal import Decimal
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
 max_recovery_loss_try TEXT NOT NULL DEFAULT '100', active INTEGER NOT NULL DEFAULT 0,
 observation_started_at INTEGER, observation_last_success_at INTEGER,
 paper_opportunities INTEGER NOT NULL DEFAULT 0, paper_trades INTEGER NOT NULL DEFAULT 0,
 failure_drills_ok INTEGER NOT NULL DEFAULT 0,
 btcturk_market_buy_conversion_safe INTEGER NOT NULL DEFAULT 0
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
            # Existing Umbrel installations predate qualification counters.
            # SQLite has no IF NOT EXISTS form for columns, so migrate each
            # field explicitly while retaining all prior user data.
            settings_columns = {row[1] for row in db.execute("PRAGMA table_info(user_settings)")}
            migrations = {
                "observation_started_at": "ALTER TABLE user_settings ADD COLUMN observation_started_at INTEGER",
                "observation_last_success_at": "ALTER TABLE user_settings ADD COLUMN observation_last_success_at INTEGER",
                "paper_opportunities": "ALTER TABLE user_settings ADD COLUMN paper_opportunities INTEGER NOT NULL DEFAULT 0",
                "paper_trades": "ALTER TABLE user_settings ADD COLUMN paper_trades INTEGER NOT NULL DEFAULT 0",
                "failure_drills_ok": "ALTER TABLE user_settings ADD COLUMN failure_drills_ok INTEGER NOT NULL DEFAULT 0",
                "btcturk_market_buy_conversion_safe": "ALTER TABLE user_settings ADD COLUMN btcturk_market_buy_conversion_safe INTEGER NOT NULL DEFAULT 0",
            }
            for column, statement in migrations.items():
                if column not in settings_columns:
                    db.execute(statement)

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

    def active_paper_profiles(self) -> list[dict]:
        with self.connect() as db:
            return [dict(row) for row in db.execute(
                "SELECT user_id,max_trade_try,daily_loss_limit_try,max_recovery_loss_try "
                "FROM user_settings WHERE mode='test' AND active=1 ORDER BY user_id"
            )]

    def has_recent_execution(self, user_id: int, pair: str, since_ms: int) -> bool:
        with self.connect() as db:
            return db.execute(
                "SELECT 1 FROM execution_intents WHERE user_id=? AND pair=? AND created_at>=? LIMIT 1",
                (user_id, pair, since_ms),
            ).fetchone() is not None

    def realized_loss_since(self, user_id: int, since_ms: int) -> str:
        with self.connect() as db:
            values = [row[0] for row in db.execute(
                "SELECT realized_profit_try FROM execution_intents WHERE user_id=? AND created_at>=? "
                "AND realized_profit_try IS NOT NULL", (user_id, since_ms))]
        loss = sum((-Decimal(value) for value in values if Decimal(value) < 0), Decimal("0"))
        return str(loss)

    def record_observation(self, timestamp_ms: int, max_gap_ms: int = 15 * 60 * 1000) -> int:
        """Advance continuous public observation for every local profile.

        A long outage resets the observation and paper counters. This prevents
        a restarted or stale scanner from satisfying the 72-hour gate with
        disconnected historical samples.
        """

        timestamp_ms = int(timestamp_ms)
        with self.connect() as db:
            rows = db.execute(
                "SELECT user_id,observation_started_at,observation_last_success_at FROM user_settings"
            ).fetchall()
            reset = 0
            for row in rows:
                last = row["observation_last_success_at"]
                interrupted = last is None or timestamp_ms - int(last) > max_gap_ms
                if row["observation_started_at"] is None or interrupted:
                    db.execute(
                        "UPDATE user_settings SET observation_started_at=?,observation_last_success_at=?,"
                        "paper_opportunities=0,paper_trades=0 WHERE user_id=?",
                        (timestamp_ms, timestamp_ms, row["user_id"]),
                    )
                    reset += 1
                else:
                    db.execute("UPDATE user_settings SET observation_last_success_at=? WHERE user_id=?",
                               (timestamp_ms, row["user_id"]))
            return reset

    def record_paper_opportunities(self, user_id: int, count: int = 1) -> None:
        count = max(int(count), 0)
        if count == 0:
            return
        with self.connect() as db:
            db.execute("UPDATE user_settings SET paper_opportunities=paper_opportunities+? WHERE user_id=?",
                       (count, user_id))

    def record_paper_trade(self, user_id: int) -> None:
        with self.connect() as db:
            db.execute("UPDATE user_settings SET paper_trades=paper_trades+1 WHERE user_id=?", (user_id,))

    def qualification_metrics(self, user_id: int, now_ms: int | None = None) -> dict:
        now_ms = int(time.time() * 1000) if now_ms is None else int(now_ms)
        with self.connect() as db:
            row = db.execute("SELECT observation_started_at,observation_last_success_at,"
                             "paper_opportunities,paper_trades,failure_drills_ok,"
                             "btcturk_market_buy_conversion_safe FROM user_settings WHERE user_id=?",
                             (user_id,)).fetchone()
        if not row:
            return {"observation_hours": "0", "paper_opportunities": 0, "paper_trades": 0,
                    "failure_drills_ok": False, "btcturk_market_buy_conversion_safe": False,
                    "observation_started_at": None, "observation_last_success_at": None}
        start = row["observation_started_at"]
        last = row["observation_last_success_at"]
        hours = Decimal("0")
        if start is not None and last is not None and int(last) <= now_ms:
            # Count through the last successful snapshot, not wall-clock time
            # after the scanner went offline.
            hours = (Decimal(int(last) - int(start)) / Decimal(3_600_000)).quantize(Decimal("0.01"))
        return {
            "observation_hours": str(max(hours, Decimal("0"))),
            "paper_opportunities": int(row["paper_opportunities"] or 0),
            "paper_trades": int(row["paper_trades"] or 0),
            "failure_drills_ok": bool(row["failure_drills_ok"]),
            "btcturk_market_buy_conversion_safe": bool(row["btcturk_market_buy_conversion_safe"]),
            "observation_started_at": start,
            "observation_last_success_at": last,
        }

    def execution_summary(self, user_id: int) -> dict:
        """Return dashboard-safe aggregate execution metrics for one profile."""

        with self.connect() as db:
            row = db.execute(
                "SELECT COUNT(*) AS total,"
                "SUM(CASE WHEN state='BALANCED_FILL' THEN 1 ELSE 0 END) AS balanced,"
                "SUM(CASE WHEN state IN ('PARTIAL_IMBALANCE','RECOVERY','FAILED_SAFE','HALTED') THEN 1 ELSE 0 END) AS recovery_events,"
                "SUM(CASE WHEN realized_profit_try IS NOT NULL AND CAST(realized_profit_try AS REAL)>0 THEN 1 ELSE 0 END) AS profitable,"
                "COALESCE(SUM(CAST(COALESCE(realized_profit_try,'0') AS REAL)),0) AS realized_profit_try,"
                "COALESCE(SUM(CASE WHEN CAST(COALESCE(realized_profit_try,'0') AS REAL)<0 THEN CAST(realized_profit_try AS REAL) ELSE 0 END),0) AS realized_loss_try "
                "FROM execution_intents WHERE user_id=?", (user_id,)
            ).fetchone()
            now_ms = int(time.time() * 1000)
            day_start = now_ms - (now_ms % 86_400_000)
            week_start = day_start - 6 * 86_400_000
            month_start = day_start - 29 * 86_400_000
            windows = {}
            for name, start in (("today", day_start), ("seven_days", week_start), ("thirty_days", month_start)):
                value = db.execute(
                    "SELECT COALESCE(SUM(CAST(COALESCE(realized_profit_try,'0') AS REAL)),0) "
                    "FROM execution_intents WHERE user_id=? AND created_at>=?", (user_id, start)
                ).fetchone()[0]
                windows[f"{name}_realized_profit_try"] = str(
                    Decimal(str(value or 0)).quantize(Decimal("0.01"))
                )
        return {
            "total": int(row["total"] or 0),
            "balanced": int(row["balanced"] or 0),
            "recovery_events": int(row["recovery_events"] or 0),
            "profitable": int(row["profitable"] or 0),
            "realized_profit_try": str(Decimal(str(row["realized_profit_try"] or 0)).quantize(Decimal("0.01"))),
            "realized_loss_try": str(Decimal(str(row["realized_loss_try"] or 0)).quantize(Decimal("0.01"))),
            **windows,
        }
