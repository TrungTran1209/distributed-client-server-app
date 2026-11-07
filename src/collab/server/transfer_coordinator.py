"""Server-side file transfer state machine and O(1)-memory TLS chunk relay."""

from __future__ import annotations

import base64
import binascii
from dataclasses import dataclass, field
import threading
import time
from typing import Any, Callable

from collab.common.errors import ProtocolError, TransferError
from collab.common.protocol import (
    MAX_CHUNK_SIZE,
    MAX_FILE_SIZE,
    MessageType,
    make_message,
    normalize_username,
)
from collab.transfer.manifest import TransferManifest, validate_uuid_str
from .sessions import Session, SessionRegistry

Send = Callable[[Session, dict[str, Any]], None]

FILE_REQUEST_TYPES = frozenset(
    {
        MessageType.FILE_OFFER,
        MessageType.FILE_ACCEPT,
        MessageType.FILE_REJECT,
        MessageType.FILE_CHUNK,
        MessageType.FILE_END,
        MessageType.FILE_ACK,
        MessageType.FILE_CANCEL,
    }
)


@dataclass
class _RelaySession:
    manifest: TransferManifest
    sender: str
    recipient: str
    state: str = "offered"
    next_index: int = 0
    bytes_relayed: int = 0
    updated_at: float = field(default_factory=time.monotonic)


class TransferCoordinator:
    """Validates and relays 1-to-1 file transfers between authenticated TLS sessions."""

    def __init__(
        self,
        sessions: SessionRegistry,
        send: Send,
        *,
        offer_timeout: float = 60.0,
        chunk_idle_timeout: float = 30.0,
        ack_timeout: float = 15.0,
        max_file_size: int = MAX_FILE_SIZE,
        max_chunk_size: int = MAX_CHUNK_SIZE,
        max_active_per_user: int = 3,
    ) -> None:
        self.sessions = sessions
        self.send = send
        self.offer_timeout = offer_timeout
        self.chunk_idle_timeout = chunk_idle_timeout
        self.ack_timeout = ack_timeout
        self.max_file_size = max_file_size
        self.max_chunk_size = max_chunk_size
        self.max_active_per_user = max_active_per_user
        self._lock = threading.RLock()
        self._transfers: dict[str, _RelaySession] = {}

    def handle_request(self, session: Session, request: dict[str, Any]) -> dict[str, Any]:
        """Dispatch a file-transfer request and return the correlated response."""
        kind = request["type"]
        request_id = request.get("request_id")
        handlers = {
            MessageType.FILE_OFFER: self._handle_offer,
            MessageType.FILE_ACCEPT: self._handle_accept,
            MessageType.FILE_REJECT: self._handle_reject,
            MessageType.FILE_CHUNK: self._handle_chunk,
            MessageType.FILE_END: self._handle_end,
            MessageType.FILE_ACK: self._handle_ack,
            MessageType.FILE_CANCEL: self._handle_cancel,
        }
        handler = handlers.get(kind)
        if handler is None:
            raise ProtocolError("Unsupported file transfer message")
        return handler(session, request, request_id)

    def on_disconnect(self, username: str) -> None:
        """Abort all active transfers involving `username` and notify surviving peers."""
        notifications: list[tuple[str, dict[str, Any]]] = []
        with self._lock:
            affected = [
                tid
                for tid, rel in self._transfers.items()
                if username in {rel.sender, rel.recipient}
            ]
            for tid in affected:
                rel = self._transfers.pop(tid)
                peer = rel.recipient if username == rel.sender else rel.sender
                notifications.append(
                    (
                        peer,
                        make_message(
                            MessageType.FILE_STATUS,
                            transfer_id=tid,
                            ok=False,
                            code="peer_disconnected",
                            by=username,
                        ),
                    )
                )
        for peer_name, msg in notifications:
            peer_session = self.sessions.get_user(peer_name)
            if peer_session is not None:
                self.send(peer_session, msg)

    def reap_expired(self) -> int:
        """Clean up timed-out offers, stalled chunk streams, and unacknowledged transfers."""
        now = time.monotonic()
        expired_items: list[_RelaySession] = []
        with self._lock:
            for tid, rel in list(self._transfers.items()):
                limit = self._timeout_for_state(rel.state)
                if now - rel.updated_at > limit:
                    expired_items.append(self._transfers.pop(tid))

        for rel in expired_items:
            notice = make_message(
                MessageType.FILE_STATUS,
                transfer_id=rel.manifest.transfer_id,
                ok=False,
                code="transfer_timeout",
            )
            for uname in (rel.sender, rel.recipient):
                target = self.sessions.get_user(uname)
                if target is not None:
                    self.send(target, notice)
        return len(expired_items)

    def _timeout_for_state(self, state: str) -> float:
        if state == "offered":
            return self.offer_timeout
        if state == "accepted":
            return self.chunk_idle_timeout
        return self.ack_timeout

    def _handle_offer(
        self,
        session: Session,
        request: dict[str, Any],
        request_id: str | None,
    ) -> dict[str, Any]:
        try:
            recipient = normalize_username(request.get("to"))
            manifest = TransferManifest.from_offer(
                request,
                max_file_size=self.max_file_size,
                max_chunk_size=self.max_chunk_size,
            )
        except (ProtocolError, TransferError) as exc:
            code = exc.code if isinstance(exc, TransferError) else "invalid_message"
            return make_message(
                MessageType.FILE_OFFER_RESULT,
                request_id=request_id,
                ok=False,
                code=code,
                message=str(exc),
            )

        target = self.sessions.get_user(recipient)
        if target is None or target.username == session.username:
            return make_message(
                MessageType.FILE_OFFER_RESULT,
                request_id=request_id,
                ok=False,
                code="recipient_unavailable",
            )

        with self._lock:
            if manifest.transfer_id in self._transfers:
                return make_message(
                    MessageType.FILE_OFFER_RESULT,
                    request_id=request_id,
                    ok=False,
                    code="duplicate_transfer",
                )
            sender_active = sum(
                1 for r in self._transfers.values() if r.sender == session.username
            )
            if sender_active >= self.max_active_per_user:
                return make_message(
                    MessageType.FILE_OFFER_RESULT,
                    request_id=request_id,
                    ok=False,
                    code="too_many_transfers",
                )
            self._transfers[manifest.transfer_id] = _RelaySession(
                manifest=manifest,
                sender=session.username,
                recipient=recipient,
            )

        self.send(
            target,
            make_message(
                MessageType.FILE_OFFER_EVENT,
                transfer_id=manifest.transfer_id,
                **{"from": session.username},
                filename=manifest.filename,
                size=manifest.size,
                sha256=manifest.sha256,
                chunk_size=manifest.chunk_size,
                total_chunks=manifest.total_chunks,
                expires_in_sec=int(self.offer_timeout),
            ),
        )
        return make_message(
            MessageType.FILE_OFFER_RESULT,
            request_id=request_id,
            ok=True,
            transfer_id=manifest.transfer_id,
        )

    def _handle_accept(
        self,
        session: Session,
        request: dict[str, Any],
        request_id: str | None,
    ) -> dict[str, Any]:
        tid, err = self._parse_tid(request, MessageType.FILE_ACCEPT_RESULT, request_id)
        if err is not None:
            return err
        with self._lock:
            rel = self._transfers.get(tid)
            if rel is None or rel.recipient != session.username or rel.state != "offered":
                return make_message(
                    MessageType.FILE_ACCEPT_RESULT,
                    request_id=request_id,
                    ok=False,
                    code="invalid_transfer_state",
                )
            sender_session = self.sessions.get_user(rel.sender)
            if sender_session is None:
                self._transfers.pop(tid, None)
                return make_message(
                    MessageType.FILE_ACCEPT_RESULT,
                    request_id=request_id,
                    ok=False,
                    code="peer_disconnected",
                )
            rel.state = "accepted"
            rel.updated_at = time.monotonic()

        self.send(
            sender_session,
            make_message(
                MessageType.FILE_DECISION,
                transfer_id=tid,
                accepted=True,
                by=session.username,
            ),
        )
        return make_message(
            MessageType.FILE_ACCEPT_RESULT,
            request_id=request_id,
            ok=True,
            transfer_id=tid,
        )

    def _handle_reject(
        self,
        session: Session,
        request: dict[str, Any],
        request_id: str | None,
    ) -> dict[str, Any]:
        tid, err = self._parse_tid(request, MessageType.FILE_REJECT_RESULT, request_id)
        if err is not None:
            return err
        reason = str(request.get("reason") or "rejected")[:120]
        with self._lock:
            rel = self._transfers.get(tid)
            if rel is None or rel.recipient != session.username or rel.state != "offered":
                return make_message(
                    MessageType.FILE_REJECT_RESULT,
                    request_id=request_id,
                    ok=False,
                    code="invalid_transfer_state",
                )
            self._transfers.pop(tid, None)

        sender_session = self.sessions.get_user(rel.sender)
        if sender_session is not None:
            self.send(
                sender_session,
                make_message(
                    MessageType.FILE_DECISION,
                    transfer_id=tid,
                    accepted=False,
                    by=session.username,
                    code="rejected",
                    message=reason,
                ),
            )
        return make_message(
            MessageType.FILE_REJECT_RESULT,
            request_id=request_id,
            ok=True,
            transfer_id=tid,
        )

    def _handle_chunk(
        self,
        session: Session,
        request: dict[str, Any],
        request_id: str | None,
    ) -> dict[str, Any]:
        tid, err = self._parse_tid(request, MessageType.FILE_CHUNK_RESULT, request_id)
        if err is not None:
            return err

        index = request.get("index")
        data_b64 = request.get("data")
        if type(index) is not int or not isinstance(data_b64, str):
            return make_message(
                MessageType.FILE_CHUNK_RESULT,
                request_id=request_id,
                ok=False,
                code="invalid_chunk",
            )

        with self._lock:
            rel = self._transfers.get(tid)
            if rel is None or rel.sender != session.username or rel.state != "accepted":
                return make_message(
                    MessageType.FILE_CHUNK_RESULT,
                    request_id=request_id,
                    ok=False,
                    code="invalid_transfer_state",
                )
            if index != rel.next_index or index >= rel.manifest.total_chunks:
                return make_message(
                    MessageType.FILE_CHUNK_RESULT,
                    request_id=request_id,
                    ok=False,
                    code="chunk_out_of_order",
                )
            try:
                decoded = base64.b64decode(data_b64.encode("ascii"), validate=True)
            except (ValueError, binascii.Error):
                return make_message(
                    MessageType.FILE_CHUNK_RESULT,
                    request_id=request_id,
                    ok=False,
                    code="invalid_chunk",
                )
            if len(decoded) != rel.manifest.expected_chunk_length(index):
                return make_message(
                    MessageType.FILE_CHUNK_RESULT,
                    request_id=request_id,
                    ok=False,
                    code="invalid_chunk",
                )
            recipient_session = self.sessions.get_user(rel.recipient)
            if recipient_session is None:
                self._transfers.pop(tid, None)
                return make_message(
                    MessageType.FILE_CHUNK_RESULT,
                    request_id=request_id,
                    ok=False,
                    code="peer_disconnected",
                )
            rel.next_index += 1
            rel.bytes_relayed += len(decoded)
            rel.updated_at = time.monotonic()

        self.send(
            recipient_session,
            make_message(
                MessageType.FILE_CHUNK_EVENT,
                transfer_id=tid,
                **{"from": session.username},
                index=index,
                data=data_b64,
            ),
        )
        return make_message(
            MessageType.FILE_CHUNK_RESULT,
            request_id=request_id,
            ok=True,
            transfer_id=tid,
            index=index,
        )

    def _handle_end(
        self,
        session: Session,
        request: dict[str, Any],
        request_id: str | None,
    ) -> dict[str, Any]:
        tid, err = self._parse_tid(request, MessageType.FILE_RESULT, request_id)
        if err is not None:
            return err

        with self._lock:
            rel = self._transfers.get(tid)
            if rel is None or rel.sender != session.username or rel.state != "accepted":
                return make_message(
                    MessageType.FILE_RESULT,
                    request_id=request_id,
                    ok=False,
                    code="invalid_transfer_state",
                )
            if (
                rel.next_index != rel.manifest.total_chunks
                or rel.bytes_relayed != rel.manifest.size
                or request.get("size") != rel.manifest.size
                or str(request.get("sha256", "")).lower() != rel.manifest.sha256
            ):
                self._transfers.pop(tid, None)
                return make_message(
                    MessageType.FILE_RESULT,
                    request_id=request_id,
                    ok=False,
                    code="size_mismatch",
                )
            recipient_session = self.sessions.get_user(rel.recipient)
            if recipient_session is None:
                self._transfers.pop(tid, None)
                return make_message(
                    MessageType.FILE_RESULT,
                    request_id=request_id,
                    ok=False,
                    code="peer_disconnected",
                )
            rel.state = "verifying"
            rel.updated_at = time.monotonic()

        self.send(
            recipient_session,
            make_message(
                MessageType.FILE_END_EVENT,
                transfer_id=tid,
                **{"from": session.username},
                size=rel.manifest.size,
                sha256=rel.manifest.sha256,
                total_chunks=rel.manifest.total_chunks,
            ),
        )
        return make_message(
            MessageType.FILE_RESULT,
            request_id=request_id,
            ok=True,
            transfer_id=tid,
            stage="verifying",
        )

    def _handle_ack(
        self,
        session: Session,
        request: dict[str, Any],
        request_id: str | None,
    ) -> dict[str, Any]:
        tid, err = self._parse_tid(request, MessageType.FILE_ACK_RESULT, request_id)
        if err is not None:
            return err

        with self._lock:
            rel = self._transfers.get(tid)
            if rel is None or rel.recipient != session.username or rel.state != "verifying":
                return make_message(
                    MessageType.FILE_ACK_RESULT,
                    request_id=request_id,
                    ok=False,
                    code="invalid_transfer_state",
                )
            self._transfers.pop(tid, None)

        ok = bool(request.get("ok"))
        status_fields: dict[str, Any] = {
            "transfer_id": tid,
            "ok": ok,
            "by": session.username,
        }
        if ok:
            status_fields["sha256"] = rel.manifest.sha256
        else:
            status_fields["code"] = str(request.get("code", "verification_failed"))[:64]

        sender_session = self.sessions.get_user(rel.sender)
        if sender_session is not None:
            self.send(sender_session, make_message(MessageType.FILE_STATUS, **status_fields))

        return make_message(
            MessageType.FILE_ACK_RESULT,
            request_id=request_id,
            ok=True,
            transfer_id=tid,
        )

    def _handle_cancel(
        self,
        session: Session,
        request: dict[str, Any],
        request_id: str | None,
    ) -> dict[str, Any]:
        tid, err = self._parse_tid(request, MessageType.FILE_CANCEL_RESULT, request_id)
        if err is not None:
            return err
        reason = str(request.get("reason", "cancelled"))[:120]
        with self._lock:
            rel = self._transfers.get(tid)
            if rel is None or session.username not in {rel.sender, rel.recipient}:
                return make_message(
                    MessageType.FILE_CANCEL_RESULT,
                    request_id=request_id,
                    ok=False,
                    code="unknown_transfer",
                )
            self._transfers.pop(tid, None)

        peer_name = rel.recipient if session.username == rel.sender else rel.sender
        peer_session = self.sessions.get_user(peer_name)
        if peer_session is not None:
            self.send(
                peer_session,
                make_message(
                    MessageType.FILE_STATUS,
                    transfer_id=tid,
                    ok=False,
                    code="transfer_cancelled",
                    by=session.username,
                    message=reason,
                ),
            )
        return make_message(
            MessageType.FILE_CANCEL_RESULT,
            request_id=request_id,
            ok=True,
            transfer_id=tid,
        )

    @staticmethod
    def _parse_tid(
        request: dict[str, Any],
        response_type: MessageType,
        request_id: str | None,
    ) -> tuple[str, dict[str, Any] | None]:
        try:
            return validate_uuid_str(request.get("transfer_id")), None
        except TransferError as exc:
            return "", make_message(
                response_type,
                request_id=request_id,
                ok=False,
                code=exc.code,
                message=str(exc),
            )
