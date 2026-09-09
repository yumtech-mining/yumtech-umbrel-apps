import asyncio
import json
import secrets
import time
from contextlib import asynccontextmanager
from decimal import Decimal
from pathlib import Path

import httpx
from fastapi import Cookie, Depends, FastAPI, Header, HTTPException, Request, Response
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .config import settings
from .coordinator import PaperCoordinator
from .db import Database
from .domain import LiveQualification
from .execution import (ArbitrageExecutionEngine, PaperAdapter,
                        RecoveryLimitExceeded, opportunity_from_mapping)
from .exchanges import BTCTurkPublic
from .hummingbot_status import read_status
from .hummingbot_control import HummingbotControlError, write_control
from .scanner import MarketScanner
from .security import decrypt_secret, encrypt_secret, hash_token, load_or_create_master_key, new_session_token, passwords


db: Database
master_key: bytes
_balance_cache: dict[tuple[int, str], tuple[float, dict]] = {}
scanner = MarketScanner(Decimal(settings.target_try), Decimal(settings.min_net_profit_pct),
                        settings.scanner_interval_seconds)
execution_engine: ArbitrageExecutionEngine | None = None
paper_coordinator: PaperCoordinator | None = None


@asynccontextmanager
async def lifespan(_: FastAPI):
    global db, master_key, execution_engine, paper_coordinator
    db = Database(settings.database_path)
    halted_on_startup = db.halt_incomplete_executions()
    master_key = load_or_create_master_key(settings.master_key_path)
    execution_engine = ArbitrageExecutionEngine(db, {
        "BTCTürk": PaperAdapter("BTCTürk"),
        "Binance TR": PaperAdapter("Binance TR"),
    })
    paper_coordinator = PaperCoordinator(db, scanner, execution_engine)
    if halted_on_startup:
        db.audit(None, "startup_reconciliation", json.dumps({"halted_executions": halted_on_startup}))
    task = asyncio.create_task(scanner.run())
    coordinator_task = asyncio.create_task(paper_coordinator.run())
    yield
    paper_coordinator.stop()
    scanner.stop()
    coordinator_task.cancel()
    task.cancel()
    try:
        await asyncio.gather(task, coordinator_task)
    except asyncio.CancelledError:
        pass


app = FastAPI(title="YUMTECH Arbitrage", version="0.3.1-dev", lifespan=lifespan,
              docs_url=None, redoc_url=None)


class Credentials(BaseModel):
    exchange: str = Field(pattern="^(btcturk|binance_tr)$")
    api_key: str = Field(min_length=8, max_length=512)
    api_secret: str = Field(min_length=8, max_length=1024)


class Login(BaseModel):
    username: str = Field(min_length=3, max_length=40, pattern=r"^[\w.-]+$")
    password: str = Field(min_length=12, max_length=200)


class PaperExecutionRequest(BaseModel):
    pair: str = Field(min_length=5, max_length=30)
    buy_exchange: str = Field(pattern="^(BTCTürk|Binance TR)$")
    sell_exchange: str = Field(pattern="^(BTCTürk|Binance TR)$")


class TestSettingsUpdate(BaseModel):
    active: bool
    max_trade_try: str = Field(pattern=r"^\d+(\.\d{1,2})?$")
    daily_loss_limit_try: str = Field(pattern=r"^\d+(\.\d{1,2})?$")
    max_recovery_loss_try: str = Field(pattern=r"^\d+(\.\d{1,2})?$")


class HummingbotControlRequest(BaseModel):
    action: str = Field(pattern=r"^(start_test|stop|refresh|emergency_stop)$")


def _decimal_text(value) -> str:
    try:
        return format(Decimal(str(value or "0")), "f")
    except Exception:
        return "0"


def _normalize_balances(exchange: str, body: dict) -> list[dict]:
    """Normalize both exchange response shapes without exposing credentials."""

    data = body.get("data", body) if isinstance(body, dict) else {}
    if exchange == "btcturk":
        rows = data if isinstance(data, list) else data.get("balances", [])
    else:
        rows = data if isinstance(data, list) else data.get("balances", data.get("list", [])) if isinstance(data, dict) else []
    normalized = []
    for item in rows or []:
        if not isinstance(item, dict):
            continue
        asset = str(item.get("asset", item.get("coin", ""))).upper()
        if not asset:
            continue
        available = item.get("free", item.get("available", item.get("availableBalance", "0")))
        locked = item.get("locked", item.get("freeze", item.get("frozen", "0")))
        total = item.get("balance", item.get("total", item.get("walletBalance")))
        if total is None:
            try:
                total = Decimal(str(available or "0")) + Decimal(str(locked or "0"))
            except Exception:
                total = "0"
        normalized.append({"asset": asset, "available": _decimal_text(available),
                           "locked": _decimal_text(locked), "total": _decimal_text(total)})
    return sorted(normalized, key=lambda value: value["asset"])


async def _fetch_authenticated_balances(user_id: int, exchange: str) -> dict:
    cached = _balance_cache.get((user_id, exchange))
    if cached and time.monotonic() - cached[0] < 20:
        return cached[1]
    with db.connect() as conn:
        row = conn.execute("SELECT api_key_enc,secret_enc,validated_at FROM credentials "
                           "WHERE user_id=? AND exchange=?", (user_id, exchange)).fetchone()
    if not row:
        return {"exchange": exchange, "state": "not-configured", "balances": []}
    if not row["validated_at"]:
        return {"exchange": exchange, "state": "unvalidated", "balances": []}
    try:
        api_key = decrypt_secret(master_key, user_id, exchange, row["api_key_enc"])
        secret = decrypt_secret(master_key, user_id, exchange, row["secret_enc"])
        async with httpx.AsyncClient(timeout=8, trust_env=False) as client:
            if exchange == "btcturk":
                response = await client.get("https://api.btcturk.com/api/v1/users/balances",
                                            headers=BTCTurkPublic.auth_headers(api_key, secret))
                response.raise_for_status()
                body = response.json()
            else:
                timestamp = int(time.time() * 1000)
                query = f"timestamp={timestamp}&recvWindow=5000"
                import hashlib, hmac
                signature = hmac.new(secret.encode(), query.encode(), hashlib.sha256).hexdigest()
                response = await client.get(
                    f"https://www.binance.tr/open/v1/account/spot?{query}&signature={signature}",
                    headers={"X-MBX-APIKEY": api_key})
                response.raise_for_status()
                body = response.json()
                if int(body.get("code", 0)) != 0:
                    raise ValueError("account response rejected")
        result = {"exchange": exchange, "state": "ok", "validated": bool(row["validated_at"]),
                  "balances": _normalize_balances(exchange, body),
                  "updated_at_ms": int(time.time() * 1000)}
    except Exception:
        result = {"exchange": exchange, "state": "error", "validated": bool(row["validated_at"]),
                  "balances": [], "updated_at_ms": int(time.time() * 1000),
                  "error": "Bakiye alınamadı; bağlantı ve API izinlerini kontrol edin"}
    _balance_cache[(user_id, exchange)] = (time.monotonic(), result)
    return result


def current_user(session: str | None = Cookie(default=None, alias="yumtech_session")) -> dict:
    if not session:
        raise HTTPException(401, "Oturum gerekli")
    with db.connect() as conn:
        row = conn.execute(
            "SELECT u.id,u.username,u.is_admin,s.csrf_token FROM sessions s JOIN users u ON u.id=s.user_id "
            "WHERE s.token_hash=? AND s.expires_at>?", (hash_token(session), int(time.time()))).fetchone()
    if not row:
        raise HTTPException(401, "Oturum geçersiz")
    return dict(row)


def require_csrf(user: dict = Depends(current_user), x_csrf_token: str | None = Header(default=None)) -> dict:
    if not x_csrf_token or not secrets.compare_digest(x_csrf_token, user["csrf_token"]):
        raise HTTPException(403, "CSRF doğrulaması başarısız")
    return user


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["Content-Security-Policy"] = "default-src 'self'; style-src 'self'; script-src 'self'; img-src 'self' data:; connect-src 'self'"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "SAMEORIGIN"
    response.headers["Referrer-Policy"] = "no-referrer"
    return response


@app.get("/api/health")
def health():
    return {"status": "ok", "mode": "test", "live_orders_enabled": False,
            "scanner": scanner.running, "last_success_ms": scanner.last_success_ms,
            "market_snapshot_id": scanner.snapshot_id,
            "paper_coordinator": bool(paper_coordinator and paper_coordinator.running),
            "paper_coordinator_enabled": bool(paper_coordinator and paper_coordinator.enabled),
            "last_paper_execution_id": paper_coordinator.last_execution_id if paper_coordinator else None,
            "market_data": scanner.market_data_health(),
            "hummingbot": read_status(settings.hummingbot_status_path)}


@app.get("/api/hummingbot/status")
def hummingbot_status(user: dict = Depends(current_user)):
    return read_status(settings.hummingbot_status_path)


@app.get("/api/balances")
async def balances(user: dict = Depends(current_user)):
    """Read-only authenticated balances, normalized for the dashboard."""

    values = await asyncio.gather(
        _fetch_authenticated_balances(user["id"], "btcturk"),
        _fetch_authenticated_balances(user["id"], "binance_tr"),
    )
    try_balance = Decimal("0")
    for exchange in values:
        for item in exchange.get("balances", []):
            if item["asset"] == "TRY":
                try_balance += Decimal(item["available"])
    return {"exchanges": values, "available_try_total": str(try_balance)}


@app.post("/api/hummingbot/control")
def hummingbot_control(payload: HummingbotControlRequest, user: dict = Depends(require_csrf)):
    """Send an allow-listed test-mode command over the local shared volume."""

    try:
        command = write_control(settings.hummingbot_control_path,
                                action=payload.action, user_id=user["id"])
    except HummingbotControlError as exc:
        raise HTTPException(422, str(exc))
    if paper_coordinator:
        if payload.action == "start_test":
            paper_coordinator.set_enabled(True)
        elif payload.action in {"stop", "emergency_stop"}:
            paper_coordinator.set_enabled(False)
    db.audit(user["id"], "hummingbot_control", json.dumps({"action": payload.action,
                                                               "command_id": command["id"]}))
    return {"command": command, "status": read_status(settings.hummingbot_status_path)}


@app.get("/api/bootstrap")
def bootstrap_status():
    with db.connect() as conn:
        count = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    return {"needs_owner": count == 0}


@app.post("/api/bootstrap", status_code=201)
def bootstrap(payload: Login, response: Response):
    with db.connect() as conn:
        if conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]:
            raise HTTPException(409, "İlk kullanıcı zaten oluşturuldu")
        cursor = conn.execute("INSERT INTO users(username,password_hash,is_admin,created_at) VALUES(?,?,1,?)",
                              (payload.username, passwords.hash(payload.password), int(time.time())))
        user_id = cursor.lastrowid
        conn.execute("INSERT INTO user_settings(user_id) VALUES(?)", (user_id,))
    db.audit(user_id, "owner_created")
    return login(payload, response)


@app.post("/api/login")
def login(payload: Login, response: Response):
    with db.connect() as conn:
        row = conn.execute("SELECT id,password_hash FROM users WHERE username=? COLLATE NOCASE", (payload.username,)).fetchone()
        try:
            if not row: raise ValueError()
            passwords.verify(row["password_hash"], payload.password)
        except Exception:
            raise HTTPException(401, "Kullanıcı adı veya parola hatalı")
        raw, digest = new_session_token()
        csrf = secrets.token_urlsafe(24)
        conn.execute("DELETE FROM sessions WHERE expires_at<=?", (int(time.time()),))
        conn.execute("INSERT INTO sessions(token_hash,user_id,csrf_token,expires_at) VALUES(?,?,?,?)",
                     (digest, row["id"], csrf, int(time.time()) + settings.session_ttl_seconds))
    response.set_cookie("yumtech_session", raw, httponly=True, samesite="strict", secure=False,
                        max_age=settings.session_ttl_seconds, path="/")
    db.audit(row["id"], "login")
    return {"username": payload.username, "csrf_token": csrf}


@app.post("/api/logout", status_code=204)
def logout(response: Response, session: str | None = Cookie(default=None, alias="yumtech_session"), user: dict = Depends(require_csrf)):
    with db.connect() as conn: conn.execute("DELETE FROM sessions WHERE token_hash=?", (hash_token(session or ""),))
    response.delete_cookie("yumtech_session", path="/")
    db.audit(user["id"], "logout")


@app.get("/api/me")
def me(user: dict = Depends(current_user)):
    with db.connect() as conn:
        settings_row = dict(conn.execute("SELECT * FROM user_settings WHERE user_id=?", (user["id"],)).fetchone())
        keys = [dict(row) for row in conn.execute("SELECT exchange,key_hint,validated_at FROM credentials WHERE user_id=?", (user["id"],))]
    return {"username": user["username"], "is_admin": bool(user["is_admin"]), "csrf_token": user["csrf_token"], "settings": settings_row, "credentials": keys}


@app.post("/api/users", status_code=201)
def add_user(payload: Login, user: dict = Depends(require_csrf)):
    if not user["is_admin"]:
        raise HTTPException(403, "Yalnızca cihaz yöneticisi kullanıcı ekleyebilir")
    try:
        with db.connect() as conn:
            cursor = conn.execute("INSERT INTO users(username,password_hash,is_admin,created_at) VALUES(?,?,0,?)",
                                  (payload.username, passwords.hash(payload.password), int(time.time())))
            conn.execute("INSERT INTO user_settings(user_id) VALUES(?)", (cursor.lastrowid,))
    except Exception as exc:
        if "UNIQUE" in str(exc): raise HTTPException(409, "Bu kullanıcı adı zaten var")
        raise
    db.audit(user["id"], "user_created", json.dumps({"username": payload.username}))
    return {"username": payload.username}


@app.put("/api/credentials")
def save_credentials(payload: Credentials, user: dict = Depends(require_csrf)):
    api_enc = encrypt_secret(master_key, user["id"], payload.exchange, payload.api_key)
    secret_enc = encrypt_secret(master_key, user["id"], payload.exchange, payload.api_secret)
    hint = f"{payload.api_key[:4]}…{payload.api_key[-4:]}"
    with db.connect() as conn:
        conn.execute("INSERT INTO credentials(user_id,exchange,api_key_enc,secret_enc,key_hint,validated_at) VALUES(?,?,?,?,?,NULL) "
                     "ON CONFLICT(user_id,exchange) DO UPDATE SET api_key_enc=excluded.api_key_enc,secret_enc=excluded.secret_enc,key_hint=excluded.key_hint,validated_at=NULL",
                     (user["id"], payload.exchange, api_enc, secret_enc, hint))
    db.audit(user["id"], "credentials_updated", json.dumps({"exchange": payload.exchange}))
    return {"exchange": payload.exchange, "key_hint": hint, "validated": False}


@app.post("/api/credentials/{exchange}/test")
async def test_credentials(exchange: str, user: dict = Depends(require_csrf)):
    if exchange not in {"btcturk", "binance_tr"}: raise HTTPException(404)
    with db.connect() as conn:
        row = conn.execute("SELECT api_key_enc,secret_enc FROM credentials WHERE user_id=? AND exchange=?", (user["id"], exchange)).fetchone()
    if not row: raise HTTPException(404, "Anahtar bulunamadı")
    api_key = decrypt_secret(master_key, user["id"], exchange, row["api_key_enc"])
    secret = decrypt_secret(master_key, user["id"], exchange, row["secret_enc"])
    try:
        async with httpx.AsyncClient(timeout=8, trust_env=False) as client:
            if exchange == "btcturk":
                result = await client.get("https://api.btcturk.com/api/v1/users/balances", headers=BTCTurkPublic.auth_headers(api_key, secret))
            else:
                timestamp = int(time.time() * 1000)
                query = f"timestamp={timestamp}&recvWindow=5000"
                import hashlib, hmac
                signature = hmac.new(secret.encode(), query.encode(), hashlib.sha256).hexdigest()
                result = await client.get(f"https://www.binance.tr/open/v1/account/spot?{query}&signature={signature}",
                                          headers={"X-MBX-APIKEY": api_key})
            result.raise_for_status()
            body = result.json()
            if exchange == "binance_tr" and int(body.get("code", 0)) != 0:
                raise ValueError("Binance TR API rejected credentials")
    except Exception as exc:
        db.audit(user["id"], "credential_test_failed", json.dumps({"exchange": exchange, "error": type(exc).__name__}))
        raise HTTPException(400, "Borsa bağlantısı doğrulanamadı")
    now = int(time.time())
    with db.connect() as conn: conn.execute("UPDATE credentials SET validated_at=? WHERE user_id=? AND exchange=?", (now, user["id"], exchange))
    db.audit(user["id"], "credential_test_passed", json.dumps({"exchange": exchange}))
    return {"exchange": exchange, "validated_at": now}


@app.get("/api/opportunities")
def opportunities(user: dict = Depends(current_user)):
    return {"common_pair_count": len(scanner.common_pairs), "pairs": scanner.common_pairs,
            "items": scanner.opportunities, "last_success_ms": scanner.last_success_ms,
            "snapshot_id": scanner.snapshot_id, "error": scanner.last_error,
            "market_data": scanner.market_data_health()}


@app.put("/api/settings/test")
def update_test_settings(payload: TestSettingsUpdate, user: dict = Depends(require_csrf)):
    amounts = [Decimal(payload.max_trade_try), Decimal(payload.daily_loss_limit_try),
               Decimal(payload.max_recovery_loss_try)]
    if any(value <= 0 for value in amounts):
        raise HTTPException(422, "Risk limitleri sıfırdan büyük olmalı")
    if amounts[2] > amounts[0]:
        raise HTTPException(422, "Kurtarma zarar limiti işlem limitini aşamaz")
    with db.connect() as conn:
        if payload.active:
            # Pi 5 resource and account safety: only one active profile may trade.
            conn.execute("UPDATE user_settings SET active=0 WHERE user_id<>?", (user["id"],))
        conn.execute("UPDATE user_settings SET mode='test',active=?,max_trade_try=?,daily_loss_limit_try=?,"
                     "max_recovery_loss_try=? WHERE user_id=?",
                     (int(payload.active), payload.max_trade_try, payload.daily_loss_limit_try,
                      payload.max_recovery_loss_try, user["id"]))
    db.audit(user["id"], "test_settings_updated", json.dumps(payload.model_dump()))
    return {"mode": "test", **payload.model_dump()}


@app.post("/api/paper/execute", status_code=201)
async def execute_paper(payload: PaperExecutionRequest, user: dict = Depends(require_csrf)):
    match = next((item for item in scanner.opportunities
                  if item["pair"] == payload.pair and item["buy_exchange"] == payload.buy_exchange
                  and item["sell_exchange"] == payload.sell_exchange), None)
    if match is None:
        raise HTTPException(404, "Güncel fırsat bulunamadı")
    if not match.get("executable"):
        raise HTTPException(409, "Fırsat işlem koşullarını karşılamıyor")
    with db.connect() as conn:
        risk = conn.execute("SELECT max_recovery_loss_try FROM user_settings WHERE user_id=?", (user["id"],)).fetchone()
    try:
        result = await execution_engine.execute_paper(
            user["id"], opportunity_from_mapping(match), Decimal(risk["max_recovery_loss_try"]))
    except RecoveryLimitExceeded:
        raise HTTPException(409, "Kurtarma zarar limiti aşıldı; motor güvenli durumda durduruldu")
    db.audit(user["id"], "paper_execution", json.dumps({"intent_id": result.intent_id, "state": result.state.value}))
    if result.state.value == "BALANCED_FILL":
        db.record_paper_trade(user["id"])
    return {"intent_id": result.intent_id, "state": result.state.value,
            "realized_profit_try": str(result.realized_profit_try), "exposure_base": str(result.exposure_base),
            "recovered": result.recovery_fill is not None}


@app.get("/api/executions")
def executions(limit: int = 100, user: dict = Depends(current_user)):
    return {"items": db.list_executions(user["id"], limit)}


@app.get("/api/audit")
def audit_events(limit: int = 80, user: dict = Depends(current_user)):
    return {"items": db.list_audit(user["id"], limit)}


@app.get("/api/metrics/summary")
def metrics_summary(user: dict = Depends(current_user)):
    """Return aggregate, non-secret metrics for the operations dashboard."""

    return {
        "execution": db.execution_summary(user["id"]),
        "qualification": db.qualification_metrics(user["id"]),
        "market_data": scanner.market_data_health(),
        "hummingbot": read_status(settings.hummingbot_status_path),
        "last_success_ms": scanner.last_success_ms,
    }


@app.get("/api/live/qualification")
def qualification(user: dict = Depends(current_user)):
    with db.connect() as conn:
        validated = conn.execute("SELECT COUNT(*) FROM credentials WHERE user_id=? AND validated_at IS NOT NULL", (user["id"],)).fetchone()[0]
        risk = conn.execute("SELECT max_trade_try,daily_loss_limit_try,max_recovery_loss_try FROM user_settings WHERE user_id=?", (user["id"],)).fetchone()
    metrics = db.qualification_metrics(user["id"])
    hb_status = read_status(settings.hummingbot_status_path)
    q = LiveQualification(
        validated == 2,
        Decimal(metrics["observation_hours"]),
        metrics["paper_opportunities"],
        metrics["paper_trades"],
        metrics["failure_drills_ok"],
        bool(risk) and all(Decimal(value) > 0 for value in risk),
        bool(hb_status.get("telemetry_disabled")) and not hb_status.get("live_orders_enabled", True),
        metrics["btcturk_market_buy_conversion_safe"],
    )
    failures = q.failures()
    return {
        "eligible": not failures and settings.live_trading_armed,
        "failures": failures + ([] if settings.live_trading_armed else ["Cihaz canlı işlem için silahlı değil"]),
        "metrics": metrics,
        "gates": {"api_connections": q.api_connections_ok, "observation_72h": q.observation_hours >= 72,
                  "paper_opportunities_100": q.paper_opportunities >= 100,
                  "paper_trades_20": q.paper_trades >= 20, "failure_drills": q.failure_drills_ok,
                  "risk_limits": q.risk_limits_set, "telemetry_blocked": q.telemetry_blocked,
                  "btcturk_market_buy_conversion": q.btcturk_market_buy_conversion_safe},
    }


@app.post("/api/live/enable")
def enable_live(user: dict = Depends(require_csrf)):
    # Deliberately non-bypassable in v0.2: order connectors require qualification evidence.
    raise HTTPException(423, "Canlı işlem kilitli; yeterlilik kapıları tamamlanmadı")


dashboard = settings.dashboard_dir
if dashboard.exists():
    app.mount("/assets", StaticFiles(directory=dashboard), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        candidate = dashboard / path
        return FileResponse(candidate if candidate.is_file() else dashboard / "index.html")
