#!/usr/bin/env python3

"""Create the persistent SV2 authority identity and publish its x-only key."""

import hashlib
import os
import secrets


PRIVATE_KEY_FILE = os.environ.get(
    "SV2_PRIVATE_KEY_FILE",
    "/data/secrets/sv2-authority-private.hex",
)
PUBLIC_KEY_FILE = os.environ.get(
    "SV2_PUBLIC_KEY_FILE",
    "/data/public/sv2-authority-public.hex",
)
FINGERPRINT_FILE = os.environ.get(
    "SV2_FINGERPRINT_FILE",
    "/data/public/sv2-authority-fingerprint.txt",
)

FIELD = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEFFFFFC2F
ORDER = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEBAAEDCE6AF48A03BBFD25E8CD0364141
GENERATOR = (
    0x79BE667EF9DCBBAC55A06295CE870B07029BFCDB2DCE28D959F2815B16F81798,
    0x483ADA7726A3C4655DA4FBFC0E1108A8FD17B448A68554199C47D08FFB10D4B8,
)


def point_add(left, right):
    if left is None:
        return right
    if right is None:
        return left

    x1, y1 = left
    x2, y2 = right
    if x1 == x2 and (y1 + y2) % FIELD == 0:
        return None

    if left == right:
        slope = (3 * x1 * x1) * pow(2 * y1, FIELD - 2, FIELD) % FIELD
    else:
        slope = (y2 - y1) * pow((x2 - x1) % FIELD, FIELD - 2, FIELD) % FIELD

    x3 = (slope * slope - x1 - x2) % FIELD
    y3 = (slope * (x1 - x3) - y1) % FIELD
    return x3, y3


def scalar_multiply(scalar):
    result = None
    addend = GENERATOR
    while scalar:
        if scalar & 1:
            result = point_add(result, addend)
        addend = point_add(addend, addend)
        scalar >>= 1
    return result


def atomic_write(path, value, mode):
    directory = os.path.dirname(path)
    os.makedirs(directory, mode=0o755, exist_ok=True)
    temporary = f"{path}.tmp"
    descriptor = os.open(
        temporary,
        os.O_WRONLY | os.O_CREAT | os.O_TRUNC,
        mode,
    )
    with os.fdopen(descriptor, "w", encoding="ascii") as output:
        output.write(value + "\n")
        output.flush()
        os.fsync(output.fileno())
    os.chmod(temporary, mode)
    os.replace(temporary, path)


def read_or_create_private_key():
    private_directory = os.path.dirname(PRIVATE_KEY_FILE)
    os.makedirs(private_directory, mode=0o700, exist_ok=True)
    os.chmod(private_directory, 0o700)
    try:
        private_hex = open(
            PRIVATE_KEY_FILE,
            "r",
            encoding="ascii",
        ).read().strip().lower()
        scalar = int(private_hex, 16)
        if len(private_hex) == 64 and 1 <= scalar < ORDER:
            os.chmod(PRIVATE_KEY_FILE, 0o600)
            return scalar, False
    except (OSError, ValueError):
        pass

    scalar = secrets.randbelow(ORDER - 1) + 1
    atomic_write(PRIVATE_KEY_FILE, f"{scalar:064x}", 0o600)
    return scalar, True


def main():
    scalar, created = read_or_create_private_key()
    public_point = scalar_multiply(scalar)
    if public_point is None:
        raise RuntimeError("SV2 public key could not be derived")

    public_hex = f"{public_point[0]:064x}"
    fingerprint = hashlib.sha256(bytes.fromhex(public_hex)).hexdigest()[:16]
    atomic_write(PUBLIC_KEY_FILE, public_hex, 0o644)
    atomic_write(FINGERPRINT_FILE, fingerprint, 0o644)

    action = "Generated" if created else "Using existing"
    print(f"{action} Stratum V2 authority identity.")
    print(f"SV2 authority public key fingerprint: {fingerprint}")


if __name__ == "__main__":
    main()
