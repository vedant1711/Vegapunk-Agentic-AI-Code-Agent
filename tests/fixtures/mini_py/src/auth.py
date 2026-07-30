"""Auth primitives - the most-referenced module in this fixture.

By design, auth.py is the leaf that db.py, api.py, and tests all import
from. In PageRank terms it should have the highest incoming edge count,
so RepoGraph.relevant_files_for("password") must rank it first.
"""
from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass


@dataclass
class User:
    id: int
    username: str
    password_hash: str


def hash_password(plain: str, salt: str | None = None) -> str:
    """Hash a plaintext password using SHA-256 with an optional salt."""
    salt = salt or secrets.token_hex(16)
    digest = hashlib.sha256(f"{salt}:{plain}".encode()).hexdigest()
    return f"{salt}${digest}"


def verify_password(plain: str, stored_hash: str) -> bool:
    """Verify a plaintext password against a previously stored hash."""
    try:
        salt, _ = stored_hash.split("$", 1)
    except ValueError:
        return False
    return hash_password(plain, salt=salt) == stored_hash


def orphan_helper() -> int:
    """Never called from anywhere. Used to assert unused-symbol behavior."""
    return 42
