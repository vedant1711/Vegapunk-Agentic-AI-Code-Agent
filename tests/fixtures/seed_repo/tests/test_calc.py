"""Tests for the seed_repo calc module.

`test_divide_by_zero` FAILS on the shipped code (divide raises
ZeroDivisionError). The E2E test verifies that the agent's pipeline
makes it pass.
"""
from src.calc import divide, multiply


def test_divide_normal():
    assert divide(10, 2) == 5


def test_multiply_normal():
    assert multiply(3, 4) == 12


def test_divide_by_zero():
    # Expected behaviour after the fix: divide(x, 0) returns None
    assert divide(10, 0) is None
