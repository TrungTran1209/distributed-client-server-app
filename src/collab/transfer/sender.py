"""Chunked file transmission over an authenticated TCP/TLS client connection."""

from __future__ import annotations

import base64
from dataclasses import dataclass, field
import hashlib
from pathlib import Path
import threading
from typing import Any, Callable

from collab.common.errors import TransferError
from collab.common.protocol import (
    DEFAULT_CHUNK_SIZE,
    MAX_FILE_SIZE,
    MessageType,
    normalize_username,
)
from .manifest import TransferManifest, TransferProgress

RequestFn = Callable[..., dict[str, Any]]
ProgressCallback = Callable[[TransferProgress], None]
CompleteCallback = Callable[[str, bool, dict[str, Any]], None]


@dataclass
class _OutgoingTransfer:
    manifest: TransferManifest
    source_path: Path
    recipient: str
    decision_event: threading.Event = field(default_factory=threading.Event)
    status_event: threading.Event = field(default_factory=threading.Event)
    done_event: threading.Event = field(default_factory=threading.Event)
    cancelled: threading.Event = field(default_factory=threading.Event)
    decision: dict[str, Any] | None = None
    final_status: dict[str, Any] | None = None
    outcome: dict[str, Any] | None = None


class FileSender:
    """Manages outgoing 1-to-1 file offers, chunk streaming, and verification waits."""

    def __init__(
        self,
        request_fn: RequestFn,
        *,
        chunk_size: int = DEFAULT_CHUNK_SIZE,
        max_file_size: int = MAX_FILE_SIZE,
        offer_timeout: float = 60.0,
        chunk_timeout: float = 15.0,
        ack_timeout: float = 15.0,
        on_progress: ProgressCallback | None = None,
        on_complete: CompleteCallback | None = None,
    ) -> None:
        self._request = request_fn
        self.chunk_size = chunk_size
        self.max_file_size = max_file_size
        self.offer_timeout = offer_timeout
        self.chunk_timeout = chunk_timeout
        self.ack_timeout = ack_timeout
        self.on_progress = on_progress
        self.on_complete = on_complete
        self._lock = threading.RLock()
        self._active: dict[str, _OutgoingTransfer] = {}
        self._completed: dict[str, dict[str, Any]] = {}

    def start_send(self, file_path: str | Path, recipient: str) -> TransferManifest:
        """Validate file, send `file_offer`, and launch background streaming worker."""
        target = normalize_username(recipient)
        source = Path(file_path)
        manifest = TransferManifest.from_file(
            source,
            chunk_size=self.chunk_size,
            max_file_size=self.max_file_size,
        )
        state = _OutgoingTransfer(manifest=manifest, source_path=source, recipient=target)
        with self._lock:
            self._active[manifest.transfer_id] = state

        try:
            response = self._request(
                MessageType.FILE_OFFER,
                timeout=self.chunk_timeout,
                **manifest.to_offer_fields(target),
            )
        except Exception:
            with self._lock:
                self._active.pop(manifest.transfer_id, None)
            raise

        if not response.get("ok"):
            with self._lock:
                self._active.pop(manifest.transfer_id, None)
            code = str(response.get("code", "offer_failed"))
            raise TransferError(code, str(response.get("message", f"File offer rejected: {code}")))

        worker = threading.Thread(
            target=self._stream_worker,
            args=(state,),
            name=f"file-sender-{manifest.transfer_id[:8]}",
            daemon=True,
        )
        worker.start()
        return manifest

    def send_blocking(
        self,
        file_path: str | Path,
        recipient: str,
        *,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        """Start a transfer and wait for its final outcome dictionary."""
        try:
            manifest = self.start_send(file_path, recipient)
        except TransferError as exc:
            return {"ok": False, "code": exc.code, "message": str(exc)}
        return self.wait(manifest.transfer_id, timeout=timeout)

    def wait(self, transfer_id: str, *, timeout: float | None = None) -> dict[str, Any]:
        """Wait for an active or completed transfer to finish."""
        with self._lock:
            state = self._active.get(transfer_id)
            if state is None and transfer_id in self._completed:
                return dict(self._completed[transfer_id])
        if state is None:
            return {"ok": False, "transfer_id": transfer_id, "code": "unknown_transfer"}
        wait_sec = timeout if timeout is not None else (self.offer_timeout + self.ack_timeout + 30.0)
        if not state.done_event.wait(wait_sec):
            return {"ok": False, "transfer_id": transfer_id, "code": "transfer_timeout"}
        return dict(state.outcome or {"ok": False, "transfer_id": transfer_id, "code": "aborted"})

    def handle_event(self, message: dict[str, Any]) -> bool:
        """Process server push events correlated to outgoing transfers."""
        kind = message.get("type")
        tid = message.get("transfer_id")
        if not isinstance(tid, str):
            return False
        with self._lock:
            state = self._active.get(tid)
        if state is None:
            return kind in {MessageType.FILE_DECISION, MessageType.FILE_STATUS}

        if kind == MessageType.FILE_DECISION:
            state.decision = dict(message)
            state.decision_event.set()
            return True
        if kind == MessageType.FILE_STATUS:
            state.final_status = dict(message)
            state.status_event.set()
            if not message.get("ok", False):
                state.cancelled.set()
                state.decision_event.set()
            return True
        return False

    def cancel(self, transfer_id_or_prefix: str | None = None) -> str:
        """Cancel an outgoing transfer and notify the server."""
        state = self._match_active(transfer_id_or_prefix)
        tid = state.manifest.transfer_id
        state.cancelled.set()
        state.final_status = {"ok": False, "transfer_id": tid, "code": "cancelled"}
        state.decision_event.set()
        state.status_event.set()
        try:
            self._request(
                MessageType.FILE_CANCEL,
                timeout=5.0,
                transfer_id=tid,
                reason="cancelled_by_sender",
            )
        except Exception:  # noqa: BLE001
            pass
        return tid

    def abort_all(self, reason: str = "connection_lost") -> None:
        """Unblock all active outgoing transfers when connection drops."""
        with self._lock:
            items = list(self._active.values())
        for state in items:
            state.cancelled.set()
            state.final_status = {
                "ok": False,
                "transfer_id": state.manifest.transfer_id,
                "code": reason,
            }
            state.decision_event.set()
            state.status_event.set()

    def _match_active(self, prefix: str | None) -> _OutgoingTransfer:
        with self._lock:
            if not self._active:
                raise TransferError("unknown_transfer", "No active outgoing transfer")
            if not prefix:
                if len(self._active) == 1:
                    return next(iter(self._active.values()))
                raise TransferError("ambiguous_transfer", "Specify transfer ID prefix")
            matches = [s for tid, s in self._active.items() if tid.startswith(prefix)]
        if len(matches) != 1:
            raise TransferError("unknown_transfer", f"No unique transfer matching '{prefix}'")
        return matches[0]

    def _stream_worker(self, state: _OutgoingTransfer) -> None:
        tid = state.manifest.transfer_id
        try:
            outcome = self._execute_transfer(state)
        except Exception as exc:  # noqa: BLE001
            code = exc.code if isinstance(exc, TransferError) else "transfer_failed"
            outcome = {"ok": False, "transfer_id": tid, "code": code, "message": str(exc)}
        self._finish(state, outcome)

    def _execute_transfer(self, state: _OutgoingTransfer) -> dict[str, Any]:
        tid = state.manifest.transfer_id
        if not state.decision_event.wait(self.offer_timeout):
            self._best_effort_cancel(tid, "offer_timeout")
            return {"ok": False, "transfer_id": tid, "code": "transfer_timeout"}

        if state.cancelled.is_set() and state.final_status:
            return dict(state.final_status)

        decision = state.decision or {}
        if not decision.get("accepted"):
            return {
                "ok": False,
                "transfer_id": tid,
                "code": str(decision.get("code", "rejected")),
                "message": str(decision.get("message", "Recipient declined file transfer")),
            }

        self._send_all_chunks(state)
        if state.cancelled.is_set() and state.final_status:
            return dict(state.final_status)

        end_resp = self._request(
            MessageType.FILE_END,
            timeout=self.chunk_timeout,
            transfer_id=tid,
            size=state.manifest.size,
            sha256=state.manifest.sha256,
        )
        if not end_resp.get("ok"):
            return {
                "ok": False,
                "transfer_id": tid,
                "code": str(end_resp.get("code", "file_end_failed")),
            }

        if not state.status_event.wait(self.ack_timeout):
            return {"ok": False, "transfer_id": tid, "code": "ack_timeout"}
        status = state.final_status or {"ok": False, "code": "unknown_status"}
        return {**status, "transfer_id": tid}

    def _send_all_chunks(self, state: _OutgoingTransfer) -> None:
        manifest = state.manifest
        if manifest.total_chunks == 0:
            self._emit_progress(state, 0, 0, 0)
            return

        hasher = hashlib.sha256()
        bytes_sent = 0
        last_bucket = -1
        with state.source_path.open("rb") as handle:
            for index in range(manifest.total_chunks):
                if state.cancelled.is_set():
                    return
                raw = handle.read(manifest.chunk_size)
                expected_len = manifest.expected_chunk_length(index)
                if len(raw) != expected_len:
                    self._best_effort_cancel(manifest.transfer_id, "source_modified")
                    raise TransferError("source_modified", "Source file changed during transfer")
                hasher.update(raw)
                encoded = base64.b64encode(raw).decode("ascii")
                resp = self._request(
                    MessageType.FILE_CHUNK,
                    timeout=self.chunk_timeout,
                    transfer_id=manifest.transfer_id,
                    index=index,
                    data=encoded,
                )
                if not resp.get("ok"):
                    raise TransferError(
                        str(resp.get("code", "chunk_failed")),
                        str(resp.get("message", "Chunk rejected by server")),
                    )
                bytes_sent += len(raw)
                last_bucket = self._emit_progress(state, index + 1, bytes_sent, last_bucket)

        if hasher.hexdigest() != manifest.sha256:
            self._best_effort_cancel(manifest.transfer_id, "source_modified")
            raise TransferError("source_modified", "Source file checksum changed while reading")

    def _emit_progress(
        self,
        state: _OutgoingTransfer,
        chunks_done: int,
        bytes_sent: int,
        last_bucket: int,
    ) -> int:
        if self.on_progress is None:
            return last_bucket
        progress = TransferProgress(
            transfer_id=state.manifest.transfer_id,
            filename=state.manifest.filename,
            peer=state.recipient,
            direction="send",
            chunks_done=chunks_done,
            total_chunks=state.manifest.total_chunks,
            bytes_done=bytes_sent,
            total_bytes=state.manifest.size,
        )
        bucket = int(progress.percent // 25)
        is_edge = chunks_done <= 1 or chunks_done == state.manifest.total_chunks
        if is_edge or bucket > last_bucket:
            self.on_progress(progress)
            return bucket
        return last_bucket

    def _best_effort_cancel(self, transfer_id: str, reason: str) -> None:
        try:
            self._request(MessageType.FILE_CANCEL, timeout=3.0, transfer_id=transfer_id, reason=reason)
        except Exception:  # noqa: BLE001
            pass

    def _finish(self, state: _OutgoingTransfer, outcome: dict[str, Any]) -> None:
        tid = state.manifest.transfer_id
        state.outcome = outcome
        with self._lock:
            self._active.pop(tid, None)
            self._completed[tid] = outcome
        state.done_event.set()
        if self.on_complete is not None:
            self.on_complete(tid, bool(outcome.get("ok")), outcome)
