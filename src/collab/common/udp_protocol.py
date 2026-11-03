"""Strict, size-limited JSON datagrams for LAN discovery and heartbeat."""

from __future__ import annotations

import json
import uuid
from typing import Any

from .errors import ProtocolError
from .protocol import PROTOCOL_VERSION

MAX_DATAGRAM_SIZE = 1_200


def encode_datagram(message: dict[str, Any]) -> bytes:
    if not isinstance(message, dict) or type(message.get("v")) is not int or message["v"] != PROTOCOL_VERSION:
        raise ProtocolError("invalid UDP message")
    if message.get("type") not in {
        "discover", "server_announcement", "client_heartbeat", "heartbeat_ack"
    }:
        raise ProtocolError("unsupported UDP message type")
    payload = json.dumps(message, separators=(",", ":")).encode("utf-8")
    if len(payload) > MAX_DATAGRAM_SIZE:
        raise ProtocolError("UDP datagram exceeds 1200 bytes")
    return payload


def decode_datagram(payload: bytes) -> dict[str, Any]:
    if not payload or len(payload) > MAX_DATAGRAM_SIZE:
        raise ProtocolError("invalid UDP datagram size")
    try:
        message = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProtocolError("invalid UDP JSON") from exc
    if not isinstance(message, dict) or message.get("v") != PROTOCOL_VERSION:
        raise ProtocolError("invalid UDP message")
    kind = message.get("type")
    required = {
        "discover": ("request_id",),
        "server_announcement": ("request_id", "server_id", "host", "tcp_port"),
        "client_heartbeat": ("client_id",),
        "heartbeat_ack": ("client_id", "server_id"),
    }
    if kind not in required or any(key not in message for key in required[kind]):
        raise ProtocolError("invalid UDP message schema")
    if "tcp_port" in message and (type(message["tcp_port"]) is not int or not 1 <= message["tcp_port"] <= 65535):
        raise ProtocolError("invalid TCP port")
    for field in ("host", "server_name"):
        if field in message and (not isinstance(message[field], str) or not message[field]):
            raise ProtocolError(f"invalid {field}")
    if kind == "server_announcement" and (
        not isinstance(message.get("host"), str)
        or not isinstance(message.get("server_name"), str)
    ):
        raise ProtocolError("invalid server announcement")
    for key in ("request_id", "server_id", "client_id"):
        if key in message:
            try:
                uuid.UUID(message[key])
            except (ValueError, TypeError, AttributeError) as exc:
                raise ProtocolError(f"invalid {key}") from exc
    return message
