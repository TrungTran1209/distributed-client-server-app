"""Domain-specific exceptions."""

from __future__ import annotations


class CollabError(Exception):
    """Base exception for expected application errors."""


class ProtocolError(CollabError):
    """Raised when a message does not conform to the protocol."""


class TransferError(CollabError):
    """Raised when file metadata, path safety, or transfer state is invalid."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
