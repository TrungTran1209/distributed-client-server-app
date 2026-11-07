"""Version 1 application protocol definitions and validation helpers."""

from __future__ import annotations

import json
import re
import unicodedata
import uuid
from enum import StrEnum
from typing import Any

from .errors import ProtocolError

PROTOCOL_VERSION = 1
MAX_FRAME_SIZE = 1_048_576
MAX_CHAT_LENGTH = 4_000

DEFAULT_CHUNK_SIZE = 65_536
MAX_CHUNK_SIZE = 262_144
MAX_FILE_SIZE = 67_108_864
MAX_FILENAME_LENGTH = 200


class MessageType(StrEnum):
    HELLO = "hello"
    WELCOME = "welcome"
    REGISTER = "register"
    REGISTER_RESULT = "register_result"
    LOGIN = "login"
    LOGIN_RESULT = "login_result"
    LOGOUT = "logout"
    LOGOUT_RESULT = "logout_result"
    USER_LIST = "user_list"
    PRESENCE_ONLINE = "presence_online"
    PRESENCE_OFFLINE = "presence_offline"
    CHAT_SEND = "chat_send"
    CHAT_RESULT = "chat_result"
    CHAT_MESSAGE = "chat_message"
    FILE_OFFER = "file_offer"
    FILE_OFFER_RESULT = "file_offer_result"
    FILE_ACCEPT = "file_accept"
    FILE_ACCEPT_RESULT = "file_accept_result"
    FILE_REJECT = "file_reject"
    FILE_REJECT_RESULT = "file_reject_result"
    FILE_CHUNK = "file_chunk"
    FILE_CHUNK_RESULT = "file_chunk_result"
    FILE_END = "file_end"
    FILE_RESULT = "file_result"
    FILE_ACK = "file_ack"
    FILE_ACK_RESULT = "file_ack_result"
    FILE_CANCEL = "file_cancel"
    FILE_CANCEL_RESULT = "file_cancel_result"
    FILE_OFFER_EVENT = "file_offer_event"
    FILE_DECISION = "file_decision"
    FILE_CHUNK_EVENT = "file_chunk_event"
    FILE_END_EVENT = "file_end_event"
    FILE_STATUS = "file_status"
    PING = "ping"
    PONG = "pong"
    ERROR = "error"


REQUEST_MESSAGE_TYPES = frozenset(
    {
        MessageType.HELLO,
        MessageType.REGISTER,
        MessageType.LOGIN,
        MessageType.LOGOUT,
        MessageType.CHAT_SEND,
        MessageType.FILE_OFFER,
        MessageType.FILE_ACCEPT,
        MessageType.FILE_REJECT,
        MessageType.FILE_CHUNK,
        MessageType.FILE_END,
        MessageType.FILE_ACK,
        MessageType.FILE_CANCEL,
        MessageType.PING,
    }
)


def new_request_id() -> str:
    return str(uuid.uuid4())


def encode_message(message: dict[str, Any]) -> bytes:
    validate_message(message)
    payload = json.dumps(message, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if len(payload) > MAX_FRAME_SIZE:
        raise ProtocolError("message exceeds maximum frame size")
    return payload


def decode_message(payload: bytes) -> dict[str, Any]:
    if not payload or len(payload) > MAX_FRAME_SIZE:
        raise ProtocolError("invalid frame size")
    try:
        message = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProtocolError("invalid JSON payload") from exc
    validate_message(message)
    return message


def validate_message(message: Any) -> None:
    if not isinstance(message, dict):
        raise ProtocolError("message must be a JSON object")
    if type(message.get("v")) is not int or message["v"] != PROTOCOL_VERSION:
        raise ProtocolError("unsupported protocol version")
    if not isinstance(message.get("type"), str):
        raise ProtocolError("message type is required")
    request_id = message.get("request_id")
    if message["type"] in REQUEST_MESSAGE_TYPES and request_id is None:
        raise ProtocolError("request_id is required for requests")
    if request_id is not None:
        if not isinstance(request_id, str):
            raise ProtocolError("request_id must be a UUID string")
        try:
            uuid.UUID(request_id)
        except ValueError as exc:
            raise ProtocolError("request_id must be a UUID string") from exc


def make_message(message_type: MessageType | str, **fields: Any) -> dict[str, Any]:
    return {"v": PROTOCOL_VERSION, "type": str(message_type), **fields}


_USERNAME = re.compile(r"^[\w.-]{1,32}$", re.UNICODE)


def normalize_username(value: Any) -> str:
    if not isinstance(value, str):
        raise ProtocolError("username must be a string")
    value = unicodedata.normalize("NFC", value)
    if not _USERNAME.fullmatch(value) or value in {".", ".."}:
        raise ProtocolError("username must be 1-32 letters, numbers, '.', '_' or '-'")
    return value
