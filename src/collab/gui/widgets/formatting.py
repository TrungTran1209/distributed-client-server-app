"""Small display helpers shared by GUI widgets."""
from __future__ import annotations

import unicodedata


def human_size(size: int | float) -> str:
    """Friendly byte size: ``0 B``, ``1.5 KB``, ``64.0 MB``."""
    value = float(size)
    if value < 1024:
        return f"{int(value)} B"
    for unit in ("KB", "MB", "GB"):
        value /= 1024
        if value < 1024 or unit == "GB":
            return f"{value:.1f} {unit}"
    return f"{value:.1f} GB"  # pragma: no cover


def sanitize(value: object) -> str:
    """Strip control characters from untrusted network text (keeps tabs)."""
    text = "" if value is None else str(value)
    return "".join(ch for ch in text if ch == "\t" or not unicodedata.category(ch).startswith("C"))


TRANSFER_ERRORS = {
    "rejected": "Người nhận đã từ chối",
    "transfer_timeout": "Hết thời gian chờ",
    "peer_disconnected": "Đối phương đã ngắt kết nối",
    "transfer_cancelled": "Đã bị hủy",
    "cancelled": "Đã hủy",
    "checksum_mismatch": "Sai mã SHA-256",
    "size_mismatch": "Sai kích thước tệp",
    "invalid_chunk": "Dữ liệu chunk không hợp lệ",
    "file_too_large": "Tệp quá lớn",
    "connection_lost": "Mất kết nối",
    "disconnected": "Đã ngắt kết nối",
    "ack_timeout": "Người nhận không xác nhận kịp",
    "source_modified": "Tệp nguồn bị thay đổi khi đang gửi",
    "io_error": "Lỗi ghi tệp",
}


def describe_transfer_error(code: str | None) -> str:
    code = str(code or "unknown")
    return f"{TRANSFER_ERRORS.get(code, 'Lỗi')} ({code})"
