"""Trivial calculator with a deliberate bug for the E2E test.

`divide(a, 0)` raises ZeroDivisionError instead of handling the case
gracefully. `tests/test_calc.py::test_divide_by_zero` expects the fix.
"""


def divide(a, b):
    return a / b


def multiply(a, b):
    return a * b
