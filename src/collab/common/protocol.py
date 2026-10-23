"""Application message types and payload schemas."""

from __future__ import annotations

from enum import StrEnum


class MessageType(StrEnum):
    """Messages exchanged over the authenticated TCP connection."""

    REGISTER = "register"
    LOGIN = "login"
    LOGOUT = "logout"
    CHAT = "chat"
    FILE_MANIFEST = "file_manifest"
    FILE_CHUNK = "file_chunk"
    ERROR = "error"
