"""Password derivation, verification, and KDF parameter versioning using scrypt."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import hmac
import os

KDF_SCHEME = "scrypt"
CURRENT_KDF_VERSION = 1


@dataclass(frozen=True)
class ScryptParams:
    """Immutable, serializable scrypt parameter set for account storage."""

    version: int = CURRENT_KDF_VERSION
    n: int = 2**14
    r: int = 8
    p: int = 1
    dklen: int = 32
    salt_len: int = 16
    maxmem: int = 67_108_864

    def __post_init__(self) -> None:
        for field_name in ("version", "n", "r", "p", "dklen", "salt_len", "maxmem"):
            if type(getattr(self, field_name)) is not int:
                raise ValueError(f"{field_name} must be an integer")
        if self.version < 1:
            raise ValueError("KDF version must be >= 1")
        if self.n < 2 or (self.n & (self.n - 1)) != 0 or self.n > 2**20:
            raise ValueError("scrypt n must be a power of two between 2 and 2^20")
        if not 1 <= self.r <= 32:
            raise ValueError("scrypt r must be between 1 and 32")
        if not 1 <= self.p <= 16:
            raise ValueError("scrypt p must be between 1 and 16")
        if not 16 <= self.dklen <= 64:
            raise ValueError("scrypt dklen must be between 16 and 64 bytes")
        if not 16 <= self.salt_len <= 64:
            raise ValueError("scrypt salt_len must be between 16 and 64 bytes")
        required_mem = 128 * self.n * self.r + 1_048_576
        if self.maxmem < required_mem:
            object.__setattr__(self, "maxmem", required_mem)

    def to_spec(self) -> str:
        """Encode KDF parameters into a canonical string for storage."""
        return (
            f"{KDF_SCHEME}$v={self.version}$n={self.n}"
            f"$r={self.r}$p={self.p}$dklen={self.dklen}"
        )

    @classmethod
    def from_spec(cls, spec: str) -> ScryptParams:
        """Parse and validate a stored KDF specification string."""
        if not isinstance(spec, str) or not spec:
            raise ValueError("KDF spec must be a non-empty string")
        parts = spec.split("$")
        if len(parts) != 6 or parts[0] != KDF_SCHEME:
            raise ValueError("Unsupported KDF specification format")
        parsed: dict[str, int] = {}
        expected_keys = ("v", "n", "r", "p", "dklen")
        for item, expected_key in zip(parts[1:], expected_keys, strict=True):
            if "=" not in item:
                raise ValueError("Malformed KDF parameter entry")
            key, raw_val = item.split("=", 1)
            if key != expected_key or not raw_val.isdigit():
                raise ValueError(f"Invalid KDF parameter '{key}'")
            parsed[key] = int(raw_val)
        return cls(
            version=parsed["v"],
            n=parsed["n"],
            r=parsed["r"],
            p=parsed["p"],
            dklen=parsed["dklen"],
        )


DEFAULT_SCRYPT_PARAMS = ScryptParams()


def derive_password(
    password: str,
    salt: bytes | None = None,
    *,
    params: ScryptParams = DEFAULT_SCRYPT_PARAMS,
) -> tuple[bytes, bytes]:
    """Return a salt and scrypt-derived password digest using explicit parameters."""
    if not isinstance(password, str):
        raise ValueError("password must be a string")
    chosen_salt = os.urandom(params.salt_len) if salt is None else bytes(salt)
    if not chosen_salt:
        raise ValueError("salt must not be empty")
    digest = hashlib.scrypt(
        password.encode("utf-8"),
        salt=chosen_salt,
        n=params.n,
        r=params.r,
        p=params.p,
        maxmem=params.maxmem,
        dklen=params.dklen,
    )
    return chosen_salt, digest


def verify_password(
    password: str,
    salt: bytes,
    expected: bytes,
    *,
    params: ScryptParams = DEFAULT_SCRYPT_PARAMS,
) -> bool:
    """Constant-time comparison of a password-derived digest."""
    if not isinstance(password, str) or not salt or not expected:
        return False
    _, actual = derive_password(password, salt, params=params)
    return hmac.compare_digest(actual, bytes(expected))


def needs_rehash(
    stored_spec: str | None,
    target: ScryptParams = DEFAULT_SCRYPT_PARAMS,
) -> bool:
    """Return True if stored KDF parameters are missing, invalid, or outdated."""
    if not stored_spec:
        return True
    try:
        return ScryptParams.from_spec(stored_spec) != target
    except ValueError:
        return True
