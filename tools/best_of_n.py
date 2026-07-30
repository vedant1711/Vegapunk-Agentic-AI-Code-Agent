"""Best-of-N candidate types and selection logic.

Best-of-N is a test-time-compute technique for coding agents: generate K
candidate diffs from the LLM (with varied temperature), evaluate each in
an isolated git worktree, and keep the one that actually passes tests.

Grounded in the DeepSWE / ACECoder line of work - execution-verified
rewards used at inference time rather than during training.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

# Split into its own regex so both this module and other consumers can share it.
_PYTEST_FAILED_RE = re.compile(r"^([\w/\.\:]+)\s+FAILED")


@dataclass
class CandidateResult:
    """Outcome of a single Best-of-N candidate."""

    candidate_index: int                # 0..K-1
    temperature: float                  # temp used to sample this candidate
    parsed: bool                        # did the LLM output parse into changes?
    changes: list[dict[str, Any]] = field(default_factory=list)
    changes_applied: int = 0
    changes_failed: int = 0
    diff_size: int = 0                  # lines added + removed
    new_failures: list[str] = field(default_factory=list)  # tests failing now, not in baseline
    tests_ran: bool = False             # did we get a test result at all?
    wall_time_ms: float = 0.0
    error: str | None = None


def extract_failures(pytest_output: str) -> list[str]:
    """Extract failed test names from pytest verbose output.

    Shared helper - previously duplicated across tester.py and graph.py.
    """
    failures: list[str] = []
    for line in pytest_output.splitlines():
        if "FAILED" in line:
            m = _PYTEST_FAILED_RE.match(line.strip())
            if m:
                failures.append(m.group(1))
    return failures


def new_failures_against(current_output: str, baseline: list[str]) -> list[str]:
    """Return only failures present now that weren't in baseline."""
    current = extract_failures(current_output)
    baseline_set = set(baseline)
    return [f for f in current if f not in baseline_set]


def select_best_candidate(candidates: list[CandidateResult]) -> CandidateResult:
    """Choose the best candidate from a Best-of-N batch.

    Ranking key (all ascending; lower = better):
        1. parse failure (want candidates whose LLM output parsed)
        2. tests did not run (want candidates we actually verified)
        3. count of NEW test failures (fewest wins)
        4. NEGATIVE changes_applied (more successful ops = safer)
        5. diff_size (smaller diff = lower risk of collateral damage)
        6. candidate_index (deterministic tiebreak)

    Raises:
        ValueError: if `candidates` is empty.
    """
    if not candidates:
        raise ValueError("select_best_candidate: no candidates to choose from")

    def _key(c: CandidateResult) -> tuple[int, int, int, int, int, int]:
        return (
            0 if c.parsed else 1,
            0 if c.tests_ran else 1,
            len(c.new_failures),
            -c.changes_applied,
            c.diff_size,
            c.candidate_index,
        )

    return min(candidates, key=_key)
