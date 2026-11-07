"""SQLite-backed account storage. Passwords are stored only as scrypt hashes with KDF specs."""

from __future__ import annotations

from contextlib import closing
import os
from pathlib import Path
import sqlite3
import threading

from collab.common.crypto import (
    DEFAULT_SCRYPT_PARAMS,
    ScryptParams,
    derive_password,
    needs_rehash,
    verify_password,
)


class UserStore:
    def __init__(
        self,
        database: str | Path = "data/users.sqlite3",
        *,
        kdf_params: ScryptParams = DEFAULT_SCRYPT_PARAMS,
    ) -> None:
        self.path = Path(database)
        self.kdf_params = kdf_params
        self._dummy_salt = os.urandom(kdf_params.salt_len)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        default_spec = DEFAULT_SCRYPT_PARAMS.to_spec()
        with closing(self._connect()) as db, db:
            db.execute(
                f"""CREATE TABLE IF NOT EXISTS users (
                    username TEXT PRIMARY KEY COLLATE BINARY,
                    salt BLOB NOT NULL,
                    password_hash BLOB NOT NULL,
                    kdf_params TEXT NOT NULL DEFAULT '{default_spec}',
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )"""
            )
            columns = {
                row[1]
                for row in db.execute("PRAGMA table_info(users)").fetchall()
            }
            if "kdf_params" not in columns:
                db.execute(
                    f"ALTER TABLE users ADD COLUMN kdf_params TEXT NOT NULL DEFAULT '{default_spec}'"
                )

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.path, timeout=10)
        db.execute("PRAGMA journal_mode=WAL")
        return db

    def create_user(self, username: str, password: str) -> bool:
        salt, digest = derive_password(password, params=self.kdf_params)
        spec = self.kdf_params.to_spec()
        with self._lock, closing(self._connect()) as db:
            try:
                with db:
                    db.execute(
                        "INSERT INTO users(username, salt, password_hash, kdf_params) VALUES (?, ?, ?, ?)",
                        (username, salt, digest, spec),
                    )
                return True
            except sqlite3.IntegrityError:
                return False

    def get_user_kdf_spec(self, username: str) -> str | None:
        """Return the stored KDF parameter specification for `username`, if present."""
        with self._lock, closing(self._connect()) as db:
            row = db.execute(
                "SELECT kdf_params FROM users WHERE username = ?",
                (username,),
            ).fetchone()
        return str(row[0]) if row is not None else None

    def authenticate(self, username: str, password: str) -> bool:
        with self._lock, closing(self._connect()) as db:
            row = db.execute(
                "SELECT salt, password_hash, kdf_params FROM users WHERE username = ?",
                (username,),
            ).fetchone()
        if row is None:
            # Perform a full derivation for unknown users to reduce timing differences.
            derive_password(password, self._dummy_salt, params=self.kdf_params)
            return False

        salt_bytes = bytes(row[0])
        expected_hash = bytes(row[1])
        stored_spec = str(row[2]) if row[2] is not None else None
        try:
            active_params = (
                ScryptParams.from_spec(stored_spec)
                if stored_spec
                else DEFAULT_SCRYPT_PARAMS
            )
        except ValueError:
            return False

        if not verify_password(password, salt_bytes, expected_hash, params=active_params):
            return False

        if needs_rehash(stored_spec, self.kdf_params):
            new_salt, new_digest = derive_password(password, params=self.kdf_params)
            new_spec = self.kdf_params.to_spec()
            with self._lock, closing(self._connect()) as db, db:
                db.execute(
                    "UPDATE users SET salt = ?, password_hash = ?, kdf_params = ? WHERE username = ?",
                    (new_salt, new_digest, new_spec, username),
                )
        return True
