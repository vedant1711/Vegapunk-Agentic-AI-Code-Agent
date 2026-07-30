"""Tests for the auth module - creates another incoming edge to auth.py."""
from __future__ import annotations

from src.auth import hash_password, verify_password


def test_hash_and_verify_roundtrip():
    stored = hash_password("hunter2")
    assert verify_password("hunter2", stored)


def test_verify_rejects_wrong_password():
    stored = hash_password("hunter2")
    assert not verify_password("wrong", stored)
