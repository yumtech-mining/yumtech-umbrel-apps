"""Configuration discovery for an existing native CKPool installation."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any


DEFAULT_CONFIG_PATHS = (
    "/etc/ckpool/ckpool.conf",
    "/etc/ckpool.conf",
    "/usr/local/etc/ckpool.conf",
)


def first_json_object(text: str) -> dict[str, Any]:
    """Decode the first balanced JSON object, tolerating CKPool comments after it."""
    start = text.find("{")
    if start < 0:
        raise ValueError("CKPool configuration does not contain a JSON object")
    depth = 0
    quoted = False
    escaped = False
    for index in range(start, len(text)):
        char = text[index]
        if quoted:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                quoted = False
            continue
        if char == '"':
            quoted = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                value = json.loads(text[start : index + 1])
                if not isinstance(value, dict):
                    raise ValueError("CKPool configuration root must be an object")
                return value
    raise ValueError("CKPool configuration JSON is incomplete")


def read_ckpool_config(path: str | Path) -> dict[str, Any]:
    return first_json_object(Path(path).read_text(encoding="utf-8"))


def _first(value: Any, default: Any = None) -> Any:
    if isinstance(value, list):
        return value[0] if value else default
    return value if value is not None else default


def _port(value: Any, default: int) -> int:
    value = _first(value, "")
    if isinstance(value, dict):
        value = value.get("url") or value.get("address") or ""
    text = str(value or "")
    try:
        return int(text.rsplit(":", 1)[-1])
    except (TypeError, ValueError):
        return default


def find_config_path() -> Path:
    explicit = os.environ.get("CKPOOL_CONFIG")
    candidates = (explicit,) if explicit else DEFAULT_CONFIG_PATHS
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return Path(candidate)
    return Path(explicit or DEFAULT_CONFIG_PATHS[0])


@dataclass(frozen=True)
class Settings:
    host: str
    port: int
    config_path: Path
    socket_path: Path
    log_path: Path
    users_dir: Path
    state_dir: Path
    static_dir: Path
    rpc_url: str
    rpc_user: str
    rpc_password: str
    rpc_timeout: float
    config: dict[str, Any]
    sv1_port: int
    sv2_port: int
    basic_auth_user: str
    basic_auth_password: str
    retention_days: int

    @classmethod
    def load(cls) -> "Settings":
        config_path = find_config_path()
        try:
            config = read_ckpool_config(config_path)
        except (OSError, ValueError, json.JSONDecodeError):
            config = {}

        socket_dir = Path(
            os.environ.get("CKPOOL_SOCKET_DIR")
            or config.get("sockdir")
            or "/tmp/ckpool"
        )
        socket_path = Path(
            os.environ.get("CKPOOL_STRATIFIER_SOCKET")
            or socket_dir / "stratifier"
        )
        log_dir = Path(config.get("logdir") or "/var/log/ckpool")
        log_path = Path(os.environ.get("CKPOOL_LOG") or log_dir / "ckpool.log")
        users_dir = Path(os.environ.get("CKPOOL_USERS_DIR") or log_dir / "users")

        rpc = _first(config.get("btcd"), {})
        rpc = rpc if isinstance(rpc, dict) else {}
        rpc_url = os.environ.get("BITCOIN_RPC_URL") or str(rpc.get("url") or "127.0.0.1:8332")
        if not rpc_url.startswith(("http://", "https://")):
            rpc_url = "http://" + rpc_url

        return cls(
            host=os.environ.get("DASHBOARD_HOST", "0.0.0.0"),
            port=int(os.environ.get("DASHBOARD_PORT", "8096")),
            config_path=config_path,
            socket_path=socket_path,
            log_path=log_path,
            users_dir=users_dir,
            state_dir=Path(os.environ.get("DASHBOARD_STATE_DIR", "/var/lib/yumtech-ckpool-dashboard")),
            static_dir=Path(__file__).resolve().parent / "static",
            rpc_url=rpc_url,
            rpc_user=os.environ.get("BITCOIN_RPC_USER") or str(rpc.get("auth") or ""),
            rpc_password=os.environ.get("BITCOIN_RPC_PASSWORD") or str(rpc.get("pass") or ""),
            rpc_timeout=float(os.environ.get("BITCOIN_RPC_TIMEOUT", "4")),
            config=config,
            sv1_port=_port(config.get("serverurl"), 3333),
            sv2_port=_port(config.get("sv2url"), 3336),
            basic_auth_user=os.environ.get("DASHBOARD_USER", ""),
            basic_auth_password=os.environ.get("DASHBOARD_PASSWORD", ""),
            retention_days=max(1, int(os.environ.get("DASHBOARD_RETENTION_DAYS", "30"))),
        )

    @property
    def sv1_servers(self) -> int:
        value = self.config.get("serverurl")
        return len(value) if isinstance(value, list) else (1 if value else 0)
