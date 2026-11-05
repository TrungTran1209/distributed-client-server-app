"""Chat and online-user routing helpers."""

from __future__ import annotations

from datetime import datetime, timezone
import uuid
from typing import Any, Callable

from collab.common.protocol import MessageType, make_message
from .sessions import SessionRegistry

Send = Callable[[Any, dict[str, Any]], None]


class MessageRouter:
    def __init__(self, sessions: SessionRegistry, send: Send) -> None:
        self.sessions = sessions
        self.send = send

    def user_list(self) -> list[dict[str, Any]]:
        return [
            {"username": s.username, "host": s.host, "port": s.port}
            for s in sorted(self.sessions.snapshot(), key=lambda s: s.username)
        ]

    def broadcast_presence(self, kind: MessageType, username: str, exclude=None) -> None:
        message = make_message(kind, username=username)
        for session in self.sessions.snapshot():
            if session.sock is not exclude:
                self.send(session, message)

    def chat(self, sender: str, recipient: str | None, text: str) -> tuple[bool, str | None, str | None]:
        message_id = str(uuid.uuid4())
        sent_at = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
        message = make_message(
            MessageType.CHAT_MESSAGE,
            message_id=message_id,
            **{"from": sender, "to": recipient, "text": text, "sent_at": sent_at},
        )
        if recipient is None:
            for session in self.sessions.snapshot():
                if session.username != sender:
                    self.send(session, message)
            return True, message_id, None
        target = self.sessions.get_user(recipient)
        if target is None or target.username == sender:
            return False, None, "recipient_unavailable"
        self.send(target, message)
        return True, message_id, None
