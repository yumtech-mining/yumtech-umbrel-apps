import base64
import hashlib
import os
import secrets
from pathlib import Path

from argon2 import PasswordHasher
from cryptography.hazmat.primitives.ciphers.aead import AESGCM


passwords = PasswordHasher()


def load_or_create_master_key(path: Path) -> bytes:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        key = path.read_bytes()
        if len(key) != 32:
            raise RuntimeError("invalid master key")
        return key
    key = AESGCM.generate_key(bit_length=256)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as handle:
        handle.write(key)
    return key


def encrypt_secret(master_key: bytes, user_id: int, exchange: str, value: str) -> str:
    nonce = os.urandom(12)
    aad = f"{user_id}:{exchange}".encode()
    payload = nonce + AESGCM(master_key).encrypt(nonce, value.encode(), aad)
    return base64.urlsafe_b64encode(payload).decode()


def decrypt_secret(master_key: bytes, user_id: int, exchange: str, value: str) -> str:
    payload = base64.urlsafe_b64decode(value)
    return AESGCM(master_key).decrypt(payload[:12], payload[12:], f"{user_id}:{exchange}".encode()).decode()


def new_session_token() -> tuple[str, str]:
    raw = secrets.token_urlsafe(32)
    return raw, hashlib.sha256(raw.encode()).hexdigest()


def hash_token(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()
