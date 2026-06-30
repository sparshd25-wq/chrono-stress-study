"""Participant access-code hashing and verification."""

import hashlib
import hmac
import secrets


def hash_access_code(access_code: str, salt: str | None = None) -> str:
    """Hash an access code with PBKDF2 and a per-participant salt."""
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", access_code.encode("utf-8"), salt.encode("utf-8"), 180_000
    ).hex()
    return f"{salt}${digest}"


def verify_access_code(access_code: str, stored_hash: str) -> bool:
    try:
        salt, expected = stored_hash.split("$", 1)
    except ValueError:
        return False
    actual = hash_access_code(access_code, salt).split("$", 1)[1]
    return hmac.compare_digest(actual, expected)

