import base64
import hashlib
import hmac


def generate_signature(api_key: str, api_secret: str, timestamp_ms: int) -> str:
    """Create BTCTurk's base64(HMAC-SHA256(apiKey + timestamp)) signature."""
    try:
        secret = base64.b64decode(api_secret, validate=True)
    except (ValueError, TypeError) as exc:
        raise ValueError("BTCTurk API secret must be valid base64") from exc

    payload = f"{api_key}{timestamp_ms}".encode("utf-8")
    digest = hmac.new(secret, payload, hashlib.sha256).digest()
    return base64.b64encode(digest).decode("ascii")

