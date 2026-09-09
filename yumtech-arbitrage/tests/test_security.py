from pathlib import Path

from app.security import decrypt_secret, encrypt_secret, load_or_create_master_key


def test_vault_round_trip_and_user_separation(tmp_path: Path):
    key = load_or_create_master_key(tmp_path / "secrets" / "master.key")
    encrypted = encrypt_secret(key, 7, "btcturk", "private-value")
    assert "private-value" not in encrypted
    assert decrypt_secret(key, 7, "btcturk", encrypted) == "private-value"
