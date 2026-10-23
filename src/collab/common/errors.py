"""Domain-specific exceptions."""


class CollabError(Exception):
    """Base exception for expected application errors."""


class ProtocolError(CollabError):
    """Raised when a message does not conform to the protocol."""
