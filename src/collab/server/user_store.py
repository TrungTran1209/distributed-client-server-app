"""SQLite-backed account storage. Passwords are stored only as scrypt hashes."""

from __future__ import annotations

import sqlite3
import threading
from contextlib import closing
from pathlib import Path

from collab.common.crypto import derive_password, verify_password


class UserStore:
    def __init__(self, database: str | Path = "data/users.sqlite3") -> None:
        self.path = Path(database)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        with closing(self._connect()) as db, db:
            db.execute("""CREATE TABLE IF NOT EXISTS users (
                username TEXT PRIMARY KEY COLLATE BINARY,
                salt BLOB NOT NULL,
                password_hash BLOB NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )""")

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.path, timeout=10)
        db.execute("PRAGMA journal_mode=WAL")
        return db

    def create_user(self, username: str, password: str) -> bool:
        salt, digest = derive_password(password)
        with self._lock, closing(self._connect()) as db:
            try:
                with db:
                    db.execute(
                        "INSERT INTO users(username, salt, password_hash) VALUES (?, ?, ?)",
                        (username, salt, digest),
                    )
                return True
            except sqlite3.IntegrityError:
                return False

    def authenticate(self, username: str, password: str) -> bool:
        with self._lock, closing(self._connect()) as db:
            row = db.execute(
                "SELECT salt, password_hash FROM users WHERE username = ?", (username,)
            ).fetchone()
        if row is None:
            # Perform a derivation for unknown users to reduce timing differences.
            derive_password(password, b"collab-unknown-user-salt")
            return False
        return verify_password(password, bytes(row[0]), bytes(row[1]))
