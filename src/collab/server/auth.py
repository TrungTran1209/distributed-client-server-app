"""Registration and login policy."""

from __future__ import annotations

from collab.common.protocol import normalize_username
from collab.common.errors import ProtocolError
from .user_store import UserStore


class AuthService:
    def __init__(self, users: UserStore) -> None:
        self.users = users

    @staticmethod
    def validate_password(password: object) -> str:
        if not isinstance(password, str) or not 8 <= len(password) <= 128:
            raise ProtocolError("password must be 8-128 characters")
        return password

    def register(self, username: object, password: object) -> tuple[bool, str]:
        name = normalize_username(username)
        secret = self.validate_password(password)
        return self.users.create_user(name, secret), name

    def login(self, username: object, password: object) -> tuple[bool, str]:
        name = normalize_username(username)
        secret = self.validate_password(password)
        return self.users.authenticate(name, secret), name
