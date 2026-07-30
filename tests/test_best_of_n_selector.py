"""Unit tests for the Best-of-N selector.

The selector is a pure function so it's the easiest layer to lock down
tightly. Integration tests for the full parallel flow live in
test_best_of_n_integration.py (Phase 2d).
"""
from __future__ import annotations

import pytest

from tools.best_of_n import (
    CandidateResult,
    extract_failures,
    new_failures_against,
    select_best_candidate,
)


def _c(
    index: int = 0,
    parsed: bool = True,
    tests_ran: bool = True,
    new_failures: list[str] | None = None,
    changes_applied: int = 1,
    diff_size: int = 100,
    temp: float = 0.1,
) -> CandidateResult:
    return CandidateResult(
        candidate_index=index,
        temperature=temp,
        parsed=parsed,
        tests_ran=tests_ran,
        new_failures=new_failures or [],
        changes_applied=changes_applied,
        diff_size=diff_size,
    )


# --- Selector ranking rules ------------------------------------------------

def test_selector_prefers_no_new_failures():
    losing = _c(index=0, new_failures=["tests/test_x.py::test_a"])
    winning = _c(index=1, new_failures=[])
    assert select_best_candidate([losing, winning]) is winning


def test_selector_prefers_more_successful_applies_on_failure_tie():
    a = _c(index=0, changes_applied=1)
    b = _c(index=1, changes_applied=3)
    assert select_best_candidate([a, b]) is b


def test_selector_prefers_smaller_diff_on_apply_tie():
    a = _c(index=0, changes_applied=2, diff_size=500)
    b = _c(index=1, changes_applied=2, diff_size=50)
    assert select_best_candidate([a, b]) is b


def test_selector_prefers_parsed_output_over_unparsed():
    a = _c(index=0, parsed=False)
    b = _c(index=1, parsed=True)
    assert select_best_candidate([a, b]) is b


def test_selector_prefers_ran_tests_over_did_not_run():
    """A candidate we couldn't verify is strictly worse than one that ran
    tests, even if the verified one has some new failures."""
    unverified = _c(index=0, tests_ran=False, new_failures=[])
    verified_with_failures = _c(index=1, tests_ran=True, new_failures=["a"])
    assert select_best_candidate([unverified, verified_with_failures]) is verified_with_failures


def test_selector_returns_first_on_full_tie():
    a = _c(index=0)
    b = _c(index=1)
    assert select_best_candidate([a, b]) is a


def test_selector_raises_on_empty_input():
    with pytest.raises(ValueError):
        select_best_candidate([])


def test_selector_composite_ranking_over_three_candidates():
    """The classic Best-of-N scenario: A parses but breaks a test, B parses
    and adds nothing useful, C parses and applies more with no regressions."""
    a = _c(index=0, changes_applied=2, new_failures=["x"], diff_size=100)
    b = _c(index=1, changes_applied=0, new_failures=[], diff_size=0)
    c = _c(index=2, changes_applied=3, new_failures=[], diff_size=80)
    assert select_best_candidate([a, b, c]) is c


# --- extract_failures ------------------------------------------------------

def test_extract_failures_pulls_named_tests_from_pytest_output():
    output = """
tests/test_foo.py::test_alpha PASSED
tests/test_bar.py::test_beta FAILED
some noise
tests/test_baz.py::test_gamma FAILED
""".strip()
    assert extract_failures(output) == [
        "tests/test_bar.py::test_beta",
        "tests/test_baz.py::test_gamma",
    ]


def test_extract_failures_returns_empty_on_no_matches():
    assert extract_failures("everything passed") == []


def test_new_failures_against_filters_out_baseline():
    baseline = ["tests/test_bar.py::test_beta"]
    current = """
tests/test_bar.py::test_beta FAILED
tests/test_baz.py::test_gamma FAILED
""".strip()
    # test_beta is pre-existing, only test_gamma is new
    assert new_failures_against(current, baseline) == ["tests/test_baz.py::test_gamma"]


def test_new_failures_against_returns_all_when_no_baseline():
    current = "tests/test_x.py::test_y FAILED"
    assert new_failures_against(current, []) == ["tests/test_x.py::test_y"]
