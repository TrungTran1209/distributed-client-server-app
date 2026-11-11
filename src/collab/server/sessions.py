"""Thread-safe registry of authenticated TCP sessions."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class Session:
    username: str
    sock: Any
    host: str
    port: int
    session_id: str
    send_lock: threading.Lock = field(default_factory=threading.Lock)
    last_seen: float = field(default_factory=time.monotonic)
    send_started_at: float | None = None


class SessionRegistry:
    def __init__(self) -> None:
        self._by_username: dict[str, Session] = {}
        self._by_socket: dict[Any, Session] = {}
        self._lock = threading.RLock()

    def add(self, session: Session) -> bool:
        with self._lock:
            if session.username in self._by_username:
                return False
            self._by_username[session.username] = session
            self._by_socket[session.sock] = session
            return True

    def remove(self, sock: Any) -> Session | None:
        with self._lock:
            session = self._by_socket.pop(sock, None)
            if session is not None and self._by_username.get(session.username) is session:
                del self._by_username[session.username]
                return session
            return None

    def get_user(self, username: str) -> Session | None:
        with self._lock:
            return self._by_username.get(username)

    def get_socket(self, sock: Any) -> Session | None:
        with self._lock:
            return self._by_socket.get(sock)

    def snapshot(self) -> list[Session]:
        with self._lock:
            return list(self._by_username.values())

    def touch(self, sock: Any) -> None:
        with self._lock:
            session = self._by_socket.get(sock)
            if session:
                session.last_seen = time.monotonic()

    def expired(self, idle_seconds: float) -> list[Session]:
        cutoff = time.monotonic() - idle_seconds
        with self._lock:
            return [s for s in self._by_username.values() if s.last_seen < cutoff]

    def stalled_sends(self, send_timeout: float) -> list[Session]:
        cutoff = time.monotonic() - send_timeout
        with self._lock:
            return [
                s
                for s in self._by_username.values()
                if s.send_started_at is not None and s.send_started_at < cutoff
            ]
