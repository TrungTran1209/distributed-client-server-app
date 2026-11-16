"""Registration and login policy."""

from __future__ import annotations

import unicodedata

from collab.common.protocol import normalize_username
from collab.common.errors import ProtocolError
from .user_store import UserStore


class AuthService:
    def __init__(self, users: UserStore) -> None:
        self.users = users

    @staticmethod
    def validate_password(password: object) -> str:
        if not isinstance(password, str):
            raise ProtocolError("password must be 8-128 characters")
        normalized = unicodedata.normalize("NFKC", password)
        if not 8 <= len(normalized) <= 128:
            raise ProtocolError("password must be 8-128 characters")
        return normalized

    def register(self, username: object, password: object) -> tuple[bool, str]:
        name = normalize_username(username)
        secret = self.validate_password(password)
        return self.users.create_user(name, secret), name

    def login(self, username: object, password: object) -> tuple[bool, str]:
        name = normalize_username(username)
        secret = self.validate_password(password)
        if self.users.authenticate(name, secret):
            return True, name
        if isinstance(password, str) and password != secret and 8 <= len(password) <= 128:
            if self.users.authenticate(name, password):
                return True, name
        return False, name
