"""Length-prefixed framing for messages transported over TCP."""

from __future__ import annotations

import struct

from .errors import ProtocolError
from .protocol import MAX_FRAME_SIZE

HEADER_SIZE = 4


def encode_frame(payload: bytes) -> bytes:
    """Prefix a payload with its unsigned 32-bit network-order length."""
    if not payload or len(payload) > MAX_FRAME_SIZE:
        raise ProtocolError("invalid frame size")
    return struct.pack("!I", len(payload)) + payload


def recv_exact(sock, size: int) -> bytes:
    """Read exactly size bytes, raising EOFError on a clean/partial close."""
    chunks = bytearray()
    while len(chunks) < size:
        chunk = sock.recv(size - len(chunks))
        if not chunk:
            raise EOFError("connection closed while reading frame")
        chunks.extend(chunk)
    return bytes(chunks)


def recv_frame(sock) -> bytes:
    """Read and validate one length-prefixed frame from a socket."""
    header = recv_exact(sock, HEADER_SIZE)
    (length,) = struct.unpack("!I", header)
    if length == 0 or length > MAX_FRAME_SIZE:
        raise ProtocolError("invalid frame size")
    return recv_exact(sock, length)
