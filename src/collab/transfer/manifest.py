"""Transfer metadata, safe filenames, chunk calculations, and SHA-256 helpers."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import math
from pathlib import Path
import re
from typing import Any
import unicodedata
import uuid

from collab.common.errors import TransferError
from collab.common.protocol import (
    DEFAULT_CHUNK_SIZE,
    MAX_CHUNK_SIZE,
    MAX_FILENAME_LENGTH,
    MAX_FILE_SIZE,
)

_FORBIDDEN_CHARS = frozenset('<>:"/\\|?*')
_SHA256_HEX = re.compile(r"^[0-9a-f]{64}$")
_WINDOWS_RESERVED_NAMES = frozenset(
    {
        "CON",
        "PRN",
        "AUX",
        "NUL",
        *(f"COM{i}" for i in range(1, 10)),
        *(f"LPT{i}" for i in range(1, 10)),
    }
)


def sanitize_filename(raw_name: Any) -> str:
    """Extract and validate a safe base filename across POSIX and Windows."""
    if not isinstance(raw_name, str):
        raise TransferError("invalid_filename", "Filename must be a string")
    normalized = unicodedata.normalize("NFC", raw_name)
    if not normalized or normalized.endswith(("/", "\\")):
        raise TransferError("invalid_filename", "Filename must not be empty or a directory")

    base = re.split(r"[\\/]", normalized)[-1]
    if not base or not base.strip() or base in {".", ".."} or base.endswith((" ", ".")):
        raise TransferError("invalid_filename", "Invalid base filename")
    if len(base) > MAX_FILENAME_LENGTH or len(base.encode("utf-8")) > MAX_FILENAME_LENGTH:
        raise TransferError("invalid_filename", "Filename exceeds maximum length")
    if any(
        unicodedata.category(ch).startswith("C") or ch in _FORBIDDEN_CHARS
        for ch in base
    ):
        raise TransferError("invalid_filename", "Filename contains forbidden characters")

    stem = base.split(".", 1)[0].upper()
    if stem in _WINDOWS_RESERVED_NAMES:
        raise TransferError("invalid_filename", "Filename uses a reserved system name")
    return base


def validate_uuid_str(value: Any, field_name: str = "transfer_id") -> str:
    """Validate and return a canonical UUID string."""
    if not isinstance(value, str):
        raise TransferError("invalid_transfer", f"{field_name} must be a UUID string")
    try:
        return str(uuid.UUID(value))
    except ValueError as exc:
        raise TransferError("invalid_transfer", f"{field_name} must be a valid UUID") from exc


def compute_file_sha256(
    path: str | Path,
    *,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    max_bytes: int | None = None,
) -> tuple[int, str]:
    """Stream a file from disk and return (total_bytes, sha256_hex)."""
    file_path = Path(path)
    hasher = hashlib.sha256()
    total = 0
    read_size = max(4096, chunk_size)
    with file_path.open("rb") as handle:
        while True:
            block = handle.read(read_size)
            if not block:
                break
            total += len(block)
            if max_bytes is not None and total > max_bytes:
                raise TransferError("file_too_large", "File exceeds maximum allowed size")
            hasher.update(block)
    return total, hasher.hexdigest()


def expected_total_chunks(size: int, chunk_size: int) -> int:
    """Return the exact chunk count for a file of `size` bytes."""
    if size == 0:
        return 0
    return math.ceil(size / chunk_size)


@dataclass(frozen=True)
class TransferManifest:
    """Immutable metadata describing a file transfer session."""

    transfer_id: str
    filename: str
    size: int
    sha256: str
    chunk_size: int = DEFAULT_CHUNK_SIZE
    total_chunks: int = 0

    @classmethod
    def from_file(
        cls,
        path: str | Path,
        *,
        chunk_size: int = DEFAULT_CHUNK_SIZE,
        max_file_size: int = MAX_FILE_SIZE,
        transfer_id: str | None = None,
    ) -> TransferManifest:
        if type(chunk_size) is not int or not 1 <= chunk_size <= MAX_CHUNK_SIZE:
            raise TransferError("invalid_chunk_size", "Chunk size out of allowed bounds")
        file_path = Path(path)
        if not file_path.exists() or not file_path.is_file():
            raise TransferError("file_not_found", f"File not found: {file_path}")
        if file_path.stat().st_size > max_file_size:
            raise TransferError("file_too_large", "File exceeds maximum allowed size")
        filename = sanitize_filename(file_path.name)
        size, digest = compute_file_sha256(
            file_path,
            chunk_size=chunk_size,
            max_bytes=max_file_size,
        )
        tid = validate_uuid_str(transfer_id) if transfer_id else str(uuid.uuid4())
        return cls(
            transfer_id=tid,
            filename=filename,
            size=size,
            sha256=digest,
            chunk_size=chunk_size,
            total_chunks=expected_total_chunks(size, chunk_size),
        )

    @classmethod
    def from_offer(
        cls,
        payload: dict[str, Any],
        *,
        max_file_size: int = MAX_FILE_SIZE,
        max_chunk_size: int = MAX_CHUNK_SIZE,
    ) -> TransferManifest:
        tid = validate_uuid_str(payload.get("transfer_id"))
        raw_filename = payload.get("filename")
        if not isinstance(raw_filename, str) or any(sep in raw_filename for sep in ("/", "\\", ":")):
            raise TransferError("invalid_filename", "Wire filename must not contain path separators")
        filename = sanitize_filename(raw_filename)

        size = payload.get("size")
        chunk_size = payload.get("chunk_size")
        total_chunks = payload.get("total_chunks")
        if type(size) is not int or size < 0:
            raise TransferError("invalid_transfer", "size must be a non-negative integer")
        if size > max_file_size:
            raise TransferError("file_too_large", "Offered file exceeds maximum allowed size")
        if type(chunk_size) is not int or not 1 <= chunk_size <= max_chunk_size:
            raise TransferError("invalid_chunk_size", "chunk_size is out of bounds")
        if type(total_chunks) is not int or total_chunks != expected_total_chunks(size, chunk_size):
            raise TransferError("invalid_transfer", "total_chunks does not match size and chunk_size")

        raw_hash = payload.get("sha256")
        if not isinstance(raw_hash, str) or not _SHA256_HEX.fullmatch(raw_hash.lower()):
            raise TransferError("invalid_transfer", "sha256 must be a 64-character hex digest")

        return cls(
            transfer_id=tid,
            filename=filename,
            size=size,
            sha256=raw_hash.lower(),
            chunk_size=chunk_size,
            total_chunks=total_chunks,
        )

    def expected_chunk_length(self, index: int) -> int:
        if not 0 <= index < self.total_chunks:
            raise TransferError("chunk_out_of_order", f"Chunk index {index} out of range")
        if index < self.total_chunks - 1:
            return self.chunk_size
        remainder = self.size % self.chunk_size
        return self.chunk_size if remainder == 0 else remainder

    def to_offer_fields(self, recipient: str) -> dict[str, Any]:
        return {
            "transfer_id": self.transfer_id,
            "to": recipient,
            "filename": self.filename,
            "size": self.size,
            "sha256": self.sha256,
            "chunk_size": self.chunk_size,
            "total_chunks": self.total_chunks,
        }


@dataclass(frozen=True)
class TransferProgress:
    """Immutable snapshot of send or receive progress."""

    transfer_id: str
    filename: str
    peer: str
    direction: str
    chunks_done: int
    total_chunks: int
    bytes_done: int
    total_bytes: int

    @property
    def percent(self) -> float:
        if self.total_bytes == 0:
            return 100.0
        return round(min(100.0, (self.bytes_done / self.total_bytes) * 100.0), 1)


def _ensure_confined(base_dir: Path, candidate: Path) -> Path:
    resolved_base = base_dir.resolve()
    resolved_target = candidate.resolve()
    if not resolved_target.is_relative_to(resolved_base):
        raise TransferError("invalid_filename", "Resolved path escapes target directory")
    return resolved_target


def allocate_non_colliding_path(download_dir: str | Path, filename: str) -> Path:
    """Return a confined destination path inside `download_dir` without overwriting existing files."""
    safe_name = sanitize_filename(filename)
    base_dir = Path(download_dir)
    base_dir.mkdir(parents=True, exist_ok=True)
    candidate = _ensure_confined(base_dir, base_dir / safe_name)
    if not candidate.exists() and not candidate.is_symlink():
        return candidate

    stem = Path(safe_name).stem
    suffix = Path(safe_name).suffix
    counter = 1
    while True:
        numbered = f"{stem} ({counter}){suffix}"
        alt = _ensure_confined(base_dir, base_dir / numbered)
        if not alt.exists() and not alt.is_symlink():
            return alt
        counter += 1


def resolve_part_path(download_dir: str | Path, transfer_id: str, filename: str) -> Path:
    """Return a confined temporary `.part` path inside `download_dir`."""
    tid = validate_uuid_str(transfer_id)
    safe_name = sanitize_filename(filename)
    base_dir = Path(download_dir)
    base_dir.mkdir(parents=True, exist_ok=True)
    return _ensure_confined(base_dir, base_dir / f".{safe_name}.{tid}.part")


def resolve_safe_paths(
    download_dir: str | Path,
    transfer_id: str,
    filename: str,
) -> tuple[Path, Path]:
    """Return `(part_path, final_path)` strictly confined inside `download_dir`."""
    part_path = resolve_part_path(download_dir, transfer_id, filename)
    final_path = allocate_non_colliding_path(download_dir, filename)
    return part_path, final_path
