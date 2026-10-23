"""Password derivation and verification using scrypt."""

from __future__ import annotations

import hashlib
import hmac
import os


def derive_password(password: str, salt: bytes | None = None) -> tuple[bytes, bytes]:
    """Return a random salt and scrypt-derived password digest."""
    salt = os.urandom(16) if salt is None else salt
    digest = hashlib.scrypt(
        password.encode("utf-8"), salt=salt, n=2**14, r=8, p=1, dklen=32
    )
    return salt, digest


def verify_password(password: str, salt: bytes, expected: bytes) -> bool:
    """Constant-time comparison of a password-derived digest."""
    _, actual = derive_password(password, salt)
    return hmac.compare_digest(actual, expected)
