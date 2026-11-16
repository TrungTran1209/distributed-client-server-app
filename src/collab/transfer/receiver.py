"""File chunk reception, streaming `.part` reassembly, and SHA-256 verification."""

from __future__ import annotations

import base64
import binascii
from dataclasses import dataclass, field
import hashlib
import math
import os
from pathlib import Path
import threading
import time
from typing import Any, BinaryIO, Callable

from collab.common.errors import TransferError
from collab.common.protocol import MAX_FILE_SIZE, MessageType
from .manifest import (
    TransferManifest,
    TransferProgress,
    allocate_non_colliding_path,
    resolve_part_path,
)

RequestFn = Callable[..., dict[str, Any]]
OfferCallback = Callable[[TransferManifest, str], None]
ProgressCallback = Callable[[TransferProgress], None]
CompleteCallback = Callable[[str, bool, dict[str, Any]], None]


@dataclass(frozen=True)
class _PendingOffer:
    manifest: TransferManifest
    sender: str
    expires_at: float


@dataclass
class _ActiveReceive:
    manifest: TransferManifest
    sender: str
    part_path: Path
    handle: BinaryIO
    hasher: Any = field(default_factory=hashlib.sha256)
    next_index: int = 0
    bytes_received: int = 0
    last_bucket: int = -1
    updated_at: float = field(default_factory=time.monotonic)


class FileReceiver:
    """Manages incoming file offers, `.part` chunk writes, SHA-256 verification, and cleanup."""

    def __init__(
        self,
        request_fn: RequestFn,
        download_dir: str | Path = "downloads",
        *,
        auto_accept: bool = False,
        offer_timeout: float = 60.0,
        idle_timeout: float = 30.0,
        max_file_size: int = MAX_FILE_SIZE,
        max_concurrent: int = 8,
        on_offer: OfferCallback | None = None,
        on_progress: ProgressCallback | None = None,
        on_complete: CompleteCallback | None = None,
    ) -> None:
        self._request = request_fn
        self.download_dir = Path(download_dir)
        self.auto_accept = auto_accept
        self.offer_timeout = offer_timeout
        self.idle_timeout = idle_timeout
        self.max_file_size = max_file_size
        self.max_concurrent = max_concurrent
        self.on_offer = on_offer
        self.on_progress = on_progress
        self.on_complete = on_complete
        self._lock = threading.RLock()
        self._async_gate = threading.BoundedSemaphore(max(4, max_concurrent * 2))
        self._offers: dict[str, _PendingOffer] = {}
        self._receiving: dict[str, _ActiveReceive] = {}

    def handle_event(self, message: dict[str, Any]) -> bool:
        """Handle incoming transfer events without blocking the reader thread."""
        kind = message.get("type")
        if kind == MessageType.FILE_OFFER_EVENT:
            self.reap_expired()
            self._handle_offer_event(message)
            return True
        if kind == MessageType.FILE_CHUNK_EVENT:
            self._handle_chunk_event(message)
            return True
        if kind == MessageType.FILE_END_EVENT:
            self._handle_end_event(message)
            return True
        if kind == MessageType.FILE_STATUS:
            self._handle_status_event(message)
            return True
        return False

    def accept(self, transfer_id_or_prefix: str | None = None) -> TransferManifest:
        """Accept a pending offer, open its `.part` file exclusively, then send `file_accept`."""
        offer = self._pop_matching_offer(transfer_id_or_prefix)
        manifest = offer.manifest
        try:
            part_path = resolve_part_path(self.download_dir, manifest.transfer_id, manifest.filename)
            handle = part_path.open("xb")
        except (TransferError, OSError) as exc:
            self._async_request(MessageType.FILE_REJECT, transfer_id=manifest.transfer_id, reason="local_io_error")
            if isinstance(exc, TransferError):
                raise
            raise TransferError("io_error", f"Cannot create temporary receive file: {exc}") from exc

        active = _ActiveReceive(
            manifest=manifest,
            sender=offer.sender,
            part_path=part_path,
            handle=handle,
        )
        with self._lock:
            self._receiving[manifest.transfer_id] = active

        try:
            resp = self._request(
                MessageType.FILE_ACCEPT,
                timeout=10.0,
                transfer_id=manifest.transfer_id,
            )
        except Exception:
            self._cleanup_receive(manifest.transfer_id)
            raise

        if not resp.get("ok"):
            self._cleanup_receive(manifest.transfer_id)
            code = str(resp.get("code", "accept_failed"))
            raise TransferError(code, str(resp.get("message", f"Could not accept transfer: {code}")))
        return manifest

    def reject(
        self,
        transfer_id_or_prefix: str | None = None,
        reason: str = "rejected_by_user",
    ) -> TransferManifest:
        """Decline a pending incoming file offer."""
        offer = self._pop_matching_offer(transfer_id_or_prefix)
        resp = self._request(
            MessageType.FILE_REJECT,
            timeout=10.0,
            transfer_id=offer.manifest.transfer_id,
            reason=reason,
        )
        if not resp.get("ok"):
            code = str(resp.get("code", "reject_failed"))
            raise TransferError(code, f"Could not reject transfer: {code}")
        return offer.manifest

    def cancel(self, transfer_id_or_prefix: str | None = None) -> str:
        """Abort an in-progress incoming transfer and delete its `.part` file."""
        tid = self._match_receiving_id(transfer_id_or_prefix)
        self._cleanup_receive(tid)
        self._critical_async_request(MessageType.FILE_CANCEL, transfer_id=tid, reason="cancelled_by_receiver")
        return tid

    def reap_expired(self) -> list[str]:
        """Remove expired offers and stalled `.part` transfers."""
        now = time.monotonic()
        reaped: list[str] = []
        with self._lock:
            expired_offers = [tid for tid, o in self._offers.items() if o.expires_at < now]
            for tid in expired_offers:
                self._offers.pop(tid, None)
                reaped.append(tid)
            stalled = [
                tid
                for tid, r in self._receiving.items()
                if now - r.updated_at > self.idle_timeout
            ]
        for tid in stalled:
            self._cleanup_receive(tid)
            reaped.append(tid)
            self._notify_complete(tid, False, {"ok": False, "transfer_id": tid, "code": "transfer_timeout"})
        return reaped

    def abort_all(self, reason: str = "connection_lost") -> None:
        """Close and delete all temporary `.part` files immediately."""
        with self._lock:
            self._offers.clear()
            tids = list(self._receiving.keys())
        for tid in tids:
            self._cleanup_receive(tid)
            self._notify_complete(tid, False, {"ok": False, "transfer_id": tid, "code": reason})

    def _handle_offer_event(self, message: dict[str, Any]) -> None:
        sender = message.get("from")
        if not isinstance(sender, str) or not sender:
            return
        try:
            manifest = TransferManifest.from_offer(message, max_file_size=self.max_file_size)
        except TransferError as exc:
            tid = message.get("transfer_id")
            if isinstance(tid, str):
                self._async_request(MessageType.FILE_REJECT, transfer_id=tid, reason=exc.code)
            return

        raw_ttl = message.get("expires_in_sec", self.offer_timeout)
        ttl = (
            float(raw_ttl)
            if isinstance(raw_ttl, (int, float)) and not isinstance(raw_ttl, bool) and math.isfinite(raw_ttl)
            else self.offer_timeout
        )
        pending = _PendingOffer(
            manifest=manifest,
            sender=sender,
            expires_at=time.monotonic() + max(1.0, ttl),
        )
        with self._lock:
            if len(self._offers) + len(self._receiving) >= self.max_concurrent:
                self._async_request(
                    MessageType.FILE_REJECT,
                    transfer_id=manifest.transfer_id,
                    reason="receiver_busy",
                )
                return
            self._offers[manifest.transfer_id] = pending

        if self.on_offer is not None:
            self.on_offer(manifest, sender)
        if self.auto_accept:
            self._spawn_bounded(lambda: self._auto_accept_worker(manifest.transfer_id))

    def _auto_accept_worker(self, transfer_id: str) -> None:
        try:
            self.accept(transfer_id)
        except Exception as exc:  # noqa: BLE001
            self._notify_complete(
                transfer_id,
                False,
                {"ok": False, "transfer_id": transfer_id, "code": "accept_failed", "message": str(exc)},
            )

    def _handle_chunk_event(self, message: dict[str, Any]) -> None:
        tid = message.get("transfer_id")
        if not isinstance(tid, str):
            return
        progress_to_emit: TransferProgress | None = None
        error_outcome: tuple[str, str] | None = None
        with self._lock:
            active = self._receiving.get(tid)
            if active is None:
                return
            try:
                progress_to_emit = self._write_validated_chunk(active, message)
            except (TransferError, OSError) as exc:
                code = exc.code if isinstance(exc, TransferError) else "io_error"
                error_outcome = (code, str(exc))

        if error_outcome is not None:
            code, err_text = error_outcome
            self._cleanup_receive(tid)
            self._async_request(MessageType.FILE_CANCEL, transfer_id=tid, reason=code)
            self._notify_complete(tid, False, {"ok": False, "transfer_id": tid, "code": code, "message": err_text})
            return

        if progress_to_emit is not None and self.on_progress is not None:
            self.on_progress(progress_to_emit)

    def _write_validated_chunk(
        self,
        active: _ActiveReceive,
        message: dict[str, Any],
    ) -> TransferProgress | None:
        index = message.get("index")
        raw_b64 = message.get("data")
        if type(index) is not int or index != active.next_index:
            raise TransferError("chunk_out_of_order", "Received unexpected chunk index")
        if not isinstance(raw_b64, str):
            raise TransferError("invalid_chunk", "Chunk data must be Base64 text")
        try:
            chunk = base64.b64decode(raw_b64.encode("ascii"), validate=True)
        except (ValueError, binascii.Error) as exc:
            raise TransferError("invalid_chunk", "Invalid Base64 chunk payload") from exc

        if len(chunk) != active.manifest.expected_chunk_length(index):
            raise TransferError("invalid_chunk", "Chunk byte length does not match manifest")

        active.handle.write(chunk)
        active.hasher.update(chunk)
        active.next_index += 1
        active.bytes_received += len(chunk)
        active.updated_at = time.monotonic()
        return self._build_progress_if_milestone(active)

    def _handle_end_event(self, message: dict[str, Any]) -> None:
        tid = message.get("transfer_id")
        if not isinstance(tid, str):
            return
        with self._lock:
            active = self._receiving.pop(tid, None)
        if active is None:
            return

        try:
            active.handle.flush()
            active.handle.close()
            final_path = self._verify_and_promote(active, message)
        except (TransferError, OSError) as exc:
            code = exc.code if isinstance(exc, TransferError) else "io_error"
            _safe_unlink(active.part_path)
            self._critical_async_request(MessageType.FILE_ACK, transfer_id=tid, ok=False, code=code)
            self._notify_complete(tid, False, {"ok": False, "transfer_id": tid, "code": code, "message": str(exc)})
            return

        actual_hash = active.hasher.hexdigest()
        self._critical_async_request(MessageType.FILE_ACK, transfer_id=tid, ok=True, sha256=actual_hash)
        self._notify_complete(
            tid,
            True,
            {
                "ok": True,
                "transfer_id": tid,
                "filename": final_path.name,
                "path": str(final_path),
                "size": active.bytes_received,
                "sha256": actual_hash,
                "from": active.sender,
            },
        )

    def _verify_and_promote(self, active: _ActiveReceive, message: dict[str, Any]) -> Path:
        manifest = active.manifest
        if active.next_index != manifest.total_chunks or active.bytes_received != manifest.size:
            raise TransferError("size_mismatch", "Incomplete chunk count or byte length")
        if message.get("size") != manifest.size:
            raise TransferError("size_mismatch", "End marker size does not match offer")

        actual_sha256 = active.hasher.hexdigest()
        if actual_sha256 != manifest.sha256 or str(message.get("sha256", "")).lower() != manifest.sha256:
            raise TransferError("checksum_mismatch", "SHA-256 digest mismatch")

        with self._lock:
            final_path = allocate_non_colliding_path(self.download_dir, manifest.filename)
            os.replace(active.part_path, final_path)
        return final_path

    def _handle_status_event(self, message: dict[str, Any]) -> None:
        tid = message.get("transfer_id")
        if not isinstance(tid, str) or message.get("ok", False):
            return
        had_state = False
        with self._lock:
            if self._offers.pop(tid, None) is not None:
                had_state = True
            if tid in self._receiving:
                had_state = True
        self._cleanup_receive(tid)
        if had_state:
            self._notify_complete(tid, False, dict(message))

    def _build_progress_if_milestone(self, active: _ActiveReceive) -> TransferProgress | None:
        if self.on_progress is None:
            return None
        progress = TransferProgress(
            transfer_id=active.manifest.transfer_id,
            filename=active.manifest.filename,
            peer=active.sender,
            direction="receive",
            chunks_done=active.next_index,
            total_chunks=active.manifest.total_chunks,
            bytes_done=active.bytes_received,
            total_bytes=active.manifest.size,
        )
        bucket = int(progress.percent // 25)
        is_edge = active.next_index <= 1 or active.next_index == active.manifest.total_chunks
        if is_edge or bucket > active.last_bucket:
            active.last_bucket = bucket
            return progress
        return None

    def _pop_matching_offer(self, prefix: str | None) -> _PendingOffer:
        now = time.monotonic()
        with self._lock:
            expired = [tid for tid, o in self._offers.items() if o.expires_at < now]
            for tid in expired:
                self._offers.pop(tid, None)
            if not self._offers:
                raise TransferError("unknown_transfer", "No pending file offer")
            if not prefix:
                if len(self._offers) == 1:
                    tid = next(iter(self._offers))
                    return self._offers.pop(tid)
                raise TransferError("ambiguous_transfer", "Multiple pending offers; specify ID prefix")
            matches = [tid for tid in self._offers if tid.startswith(prefix)]
            if len(matches) != 1:
                raise TransferError("unknown_transfer", f"No unique pending offer matching '{prefix}'")
            return self._offers.pop(matches[0])

    def _match_receiving_id(self, prefix: str | None) -> str:
        with self._lock:
            if not self._receiving:
                raise TransferError("unknown_transfer", "No active incoming transfer")
            if not prefix:
                if len(self._receiving) == 1:
                    return next(iter(self._receiving))
                raise TransferError("ambiguous_transfer", "Specify transfer ID prefix")
            matches = [tid for tid in self._receiving if tid.startswith(prefix)]
        if len(matches) != 1:
            raise TransferError("unknown_transfer", f"No unique incoming transfer matching '{prefix}'")
        return matches[0]

    def _cleanup_receive(self, transfer_id: str) -> None:
        with self._lock:
            active = self._receiving.pop(transfer_id, None)
        if active is not None:
            try:
                active.handle.close()
            except OSError:
                pass
            _safe_unlink(active.part_path)

    def _async_request(self, kind: str, **fields: Any) -> None:
        def _send() -> None:
            try:
                self._request(kind, timeout=5.0, **fields)
            except Exception:  # noqa: BLE001
                pass

        self._spawn_bounded(_send)

    def _critical_async_request(self, kind: str, **fields: Any) -> None:
        """Send a post-accept control message (ACK/CANCEL) without dropping under gate load."""

        def _send() -> None:
            try:
                self._request(kind, timeout=10.0, **fields)
            except Exception:  # noqa: BLE001
                pass

        threading.Thread(target=_send, daemon=True).start()

    def _spawn_bounded(self, fn: Callable[[], None]) -> None:
        if not self._async_gate.acquire(blocking=False):
            return

        def _wrapped() -> None:
            try:
                fn()
            finally:
                self._async_gate.release()

        threading.Thread(target=_wrapped, daemon=True).start()

    def _notify_complete(self, transfer_id: str, ok: bool, detail: dict[str, Any]) -> None:
        if self.on_complete is not None:
            self.on_complete(transfer_id, ok, detail)


def _safe_unlink(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass
