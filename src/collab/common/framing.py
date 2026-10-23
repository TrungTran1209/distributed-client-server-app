"""Length-prefixed framing for messages transported over TCP."""

from __future__ import annotations

import struct

HEADER_SIZE = 4


def encode_frame(payload: bytes) -> bytes:
    """Prefix a payload with its unsigned 32-bit network-order length."""
    return struct.pack("!I", len(payload)) + payload
