"""In-memory user store. Imports from src.auth."""
from __future__ import annotations

from src.auth import User, hash_password

_STORE: dict[int, User] = {}
_next_id = 1


def get_user(user_id: int) -> User | None:
    return _STORE.get(user_id)


def save_user(username: str, plain_password: str) -> User:
    global _next_id
    user = User(id=_next_id, username=username, password_hash=hash_password(plain_password))
    _STORE[user.id] = user
    _next_id += 1
    return user
