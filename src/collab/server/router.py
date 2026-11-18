"""Chat, offline message persistence, and online/offline directory routing helpers."""

from __future__ import annotations

from datetime import datetime, timezone
import uuid
from typing import Any, Callable

from collab.common.protocol import MessageType, make_message
from .message_store import MessageStore
from .sessions import SessionRegistry
from .user_store import UserStore

Send = Callable[[Any, dict[str, Any]], None]


class MessageRouter:
    def __init__(
        self,
        sessions: SessionRegistry,
        send: Send,
        *,
        user_store: UserStore | None = None,
        message_store: MessageStore | None = None,
    ) -> None:
        self.sessions = sessions
        self.send = send
        self.user_store = user_store
        self.message_store = message_store

    def user_list(self) -> list[dict[str, Any]]:
        """Online-only session list (preserved for backward compatibility)."""
        return [
            {"username": s.username, "host": s.host, "port": s.port}
            for s in sorted(self.sessions.snapshot(), key=lambda s: s.username)
        ]

    def directory_list(self) -> list[dict[str, Any]]:
        """Full directory of registered users with live online/offline status."""
        online_by_name = {s.username: s for s in self.sessions.snapshot()}
        registered = set(self.user_store.list_usernames()) if self.user_store is not None else set()
        all_names = sorted(registered | set(online_by_name.keys()))
        result: list[dict[str, Any]] = []
        for name in all_names:
            sess = online_by_name.get(name)
            result.append(
                {
                    "username": name,
                    "online": sess is not None,
                    "host": sess.host if sess is not None else None,
                    "port": sess.port if sess is not None else None,
                }
            )
        return result

    def broadcast_user_list(self, *, exclude=None) -> None:
        payload = make_message(
            MessageType.USER_LIST,
            users=self.user_list(),
            directory=self.directory_list(),
        )
        for session in self.sessions.snapshot():
            if session.sock is not exclude:
                self.send(session, payload)

    def broadcast_presence(self, kind: MessageType, username: str, exclude=None) -> None:
        message = make_message(kind, username=username)
        for session in self.sessions.snapshot():
            if session.sock is not exclude:
                self.send(session, message)

    def route_chat(self, sender: str, recipient: str | None, text: str) -> dict[str, Any]:
        """Route broadcast or 1-to-1 chat; stores history and supports offline registered recipients."""
        message_id = str(uuid.uuid4())
        sent_at = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
        message = make_message(
            MessageType.CHAT_MESSAGE,
            message_id=message_id,
            **{"from": sender, "to": recipient, "text": text, "sent_at": sent_at},
        )
        if recipient is None:
            if self.message_store is not None:
                self.message_store.save_message(message_id, sender, None, text, sent_at)
            for session in self.sessions.snapshot():
                if session.username != sender:
                    self.send(session, message)
            return {"ok": True, "message_id": message_id}

        if recipient == sender:
            return {"ok": False, "code": "recipient_unavailable"}

        target = self.sessions.get_user(recipient)
        if target is not None:
            if self.message_store is not None:
                self.message_store.save_message(message_id, sender, recipient, text, sent_at)
            self.send(target, message)
            return {"ok": True, "message_id": message_id, "queued_offline": False}

        if self.user_store is not None and self.user_store.user_exists(recipient):
            if self.message_store is not None:
                self.message_store.save_message(message_id, sender, recipient, text, sent_at)
            return {"ok": True, "message_id": message_id, "queued_offline": True}

        return {"ok": False, "code": "recipient_unavailable"}

    def chat(self, sender: str, recipient: str | None, text: str) -> tuple[bool, str | None, str | None]:
        out = self.route_chat(sender, recipient, text)
        if out.get("ok"):
            return True, str(out["message_id"]), None
        return False, None, str(out.get("code", "recipient_unavailable"))
