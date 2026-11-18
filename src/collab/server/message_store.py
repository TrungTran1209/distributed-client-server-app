"""SQLite-backed persistent chat history for broadcast and 1-to-1 conversations."""

from __future__ import annotations

from contextlib import closing
from pathlib import Path
import sqlite3
import threading
from typing import Any


class MessageStore:
    """Stores broadcast (`recipient IS NULL`) and direct messages safely using parameterized SQL."""

    def __init__(self, database: str | Path = "data/users.sqlite3") -> None:
        self.path = Path(database)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        with closing(self._connect()) as db, db:
            db.execute(
                """CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    message_id TEXT NOT NULL UNIQUE,
                    sender TEXT NOT NULL,
                    recipient TEXT,
                    text TEXT NOT NULL,
                    sent_at TEXT NOT NULL
                )"""
            )
            db.execute(
                "CREATE INDEX IF NOT EXISTS idx_messages_recipient ON messages(recipient, id)"
            )
            db.execute(
                "CREATE INDEX IF NOT EXISTS idx_messages_sender ON messages(sender, id)"
            )

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.path, timeout=10)
        db.execute("PRAGMA journal_mode=WAL")
        return db

    def save_message(
        self,
        message_id: str,
        sender: str,
        recipient: str | None,
        text: str,
        sent_at: str,
    ) -> None:
        with self._lock, closing(self._connect()) as db, db:
            db.execute(
                """INSERT OR IGNORE INTO messages(message_id, sender, recipient, text, sent_at)
                   VALUES (?, ?, ?, ?, ?)""",
                (message_id, sender, recipient, text, sent_at),
            )

    def get_history_for_user(self, username: str, *, limit: int = 300) -> list[dict[str, Any]]:
        """Return up to `limit` chronological messages visible to `username` (broadcast + 1-to-1)."""
        safe_limit = max(1, min(int(limit), 1000))
        with self._lock, closing(self._connect()) as db:
            rows = db.execute(
                """SELECT id, message_id, sender, recipient, text, sent_at
                   FROM messages
                   WHERE recipient IS NULL OR sender = ? OR recipient = ?
                   ORDER BY id DESC
                   LIMIT ?""",
                (username, username, safe_limit),
            ).fetchall()
        rows_asc = list(reversed(rows))
        return [
            {
                "message_id": str(row[1]),
                "from": str(row[2]),
                "to": str(row[3]) if row[3] is not None else None,
                "text": str(row[4]),
                "sent_at": str(row[5]),
            }
            for row in rows_asc
        ]

    def count_messages(self) -> int:
        with self._lock, closing(self._connect()) as db:
            row = db.execute("SELECT COUNT(*) FROM messages").fetchone()
        return int(row[0]) if row is not None else 0
