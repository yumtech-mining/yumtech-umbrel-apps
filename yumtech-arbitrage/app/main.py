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
from .db import Database
from .domain import LiveQualification
from .exchanges import BTCTurkPublic
from .scanner import MarketScanner
from .security import decrypt_secret, encrypt_secret, hash_token, load_or_create_master_key, new_session_token, passwords


db: Database
master_key: bytes
scanner = MarketScanner(Decimal(settings.target_try), Decimal(settings.min_net_profit_pct))


@asynccontextmanager
async def lifespan(_: FastAPI):
    global db, master_key
    db = Database(settings.database_path)
    master_key = load_or_create_master_key(settings.master_key_path)
    task = asyncio.create_task(scanner.run())
    yield
    scanner.stop()
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


app = FastAPI(title="YUMTECH Arbitrage", version="0.2.0", lifespan=lifespan,
              docs_url=None, redoc_url=None)


class Credentials(BaseModel):
    exchange: str = Field(pattern="^(btcturk|binance_tr)$")
    api_key: str = Field(min_length=8, max_length=512)
    api_secret: str = Field(min_length=8, max_length=1024)


class Login(BaseModel):
    username: str = Field(min_length=3, max_length=40, pattern=r"^[\w.-]+$")
    password: str = Field(min_length=12, max_length=200)


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
            "scanner": scanner.running, "last_success_ms": scanner.last_success_ms}


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
        async with httpx.AsyncClient(timeout=8) as client:
            if exchange == "btcturk":
                result = await client.get("https://api.btcturk.com/api/v1/users/balances", headers=BTCTurkPublic.auth_headers(api_key, secret))
            else:
                timestamp = int(time.time() * 1000)
                query = f"timestamp={timestamp}&recvWindow=5000"
                import hashlib, hmac
                signature = hmac.new(secret.encode(), query.encode(), hashlib.sha256).hexdigest()
                result = await client.get(f"https://api.binance.me/api/v3/account?{query}&signature={signature}", headers={"X-MBX-APIKEY": api_key})
            result.raise_for_status()
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
            "items": scanner.opportunities, "last_success_ms": scanner.last_success_ms, "error": scanner.last_error}


@app.get("/api/live/qualification")
def qualification(user: dict = Depends(current_user)):
    with db.connect() as conn:
        validated = conn.execute("SELECT COUNT(*) FROM credentials WHERE user_id=? AND validated_at IS NOT NULL", (user["id"],)).fetchone()[0]
        risk = conn.execute("SELECT max_trade_try,daily_loss_limit_try,max_recovery_loss_try FROM user_settings WHERE user_id=?", (user["id"],)).fetchone()
    q = LiveQualification(validated == 2, Decimal("0"), len(scanner.opportunities), 0, False,
                          all(Decimal(value) > 0 for value in risk), True)
    failures = q.failures()
    return {"eligible": not failures and settings.live_trading_armed, "failures": failures + ([] if settings.live_trading_armed else ["Cihaz canlı işlem için silahlı değil"])}


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
