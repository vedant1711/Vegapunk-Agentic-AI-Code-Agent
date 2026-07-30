"""HTTP-facing surface. Depends on both auth and db."""
from __future__ import annotations

from src.auth import User, verify_password
from src.db import get_user, save_user


def register(username: str, password: str) -> User:
    return save_user(username, password)


def login(user_id: int, password: str) -> bool:
    user = get_user(user_id)
    if user is None:
        return False
    return verify_password(password, user.password_hash)
