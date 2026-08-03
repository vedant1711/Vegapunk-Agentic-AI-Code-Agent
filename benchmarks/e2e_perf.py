"""End-to-end pipeline latency + determinism.

Runs `pytest tests/test_pipeline_e2e.py` N times in a subprocess.

Metric 1: success rate (should be 100% - the E2E is fully mocked so
          any variance means we have a real flakiness bug).
Metric 2: wall-clock latency distribution (mean/median/p95/CI).
"""
from __future__ import annotations

import math
import statistics
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from typing import Any

from scipy import stats


@dataclass
class E2EResult:
    n_runs: int
    n_passed: int
    n_failed: int
    success_rate: float
    mean_s: float
    median_s: float
    p95_s: float
    min_s: float
    max_s: float
    stdev_s: float
    ci_95_mean_s: tuple[float, float]


def _run_once() -> tuple[bool, float]:
    t0 = time.perf_counter()
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "tests/test_pipeline_e2e.py", "-q", "--no-header"],
        capture_output=True,
        text=True,
    )
    elapsed = time.perf_counter() - t0
    passed = proc.returncode == 0 and "1 passed" in (proc.stdout + proc.stderr)
    return passed, elapsed


def run(n_runs: int = 10) -> dict[str, Any]:
    times_s: list[float] = []
    n_passed = 0
    for _ in range(n_runs):
        ok, elapsed = _run_once()
        times_s.append(elapsed)
        n_passed += int(ok)

    mean = statistics.mean(times_s)
    sd = statistics.stdev(times_s) if len(times_s) > 1 else 0.0
    sem = sd / math.sqrt(len(times_s)) if len(times_s) > 1 else 0.0
    t_crit = stats.t.ppf(0.975, df=max(1, len(times_s) - 1)) if len(times_s) > 1 else 0.0

    if len(times_s) >= 20:
        p95 = statistics.quantiles(times_s, n=20)[18]
    else:
        p95 = max(times_s)

    result = E2EResult(
        n_runs=n_runs,
        n_passed=n_passed,
        n_failed=n_runs - n_passed,
        success_rate=round(n_passed / n_runs, 4),
        mean_s=round(mean, 3),
        median_s=round(statistics.median(times_s), 3),
        p95_s=round(p95, 3),
        min_s=round(min(times_s), 3),
        max_s=round(max(times_s), 3),
        stdev_s=round(sd, 3),
        ci_95_mean_s=(
            round(mean - t_crit * sem, 3),
            round(mean + t_crit * sem, 3),
        ),
    )
    return asdict(result)


if __name__ == "__main__":
    import json

    print(json.dumps(run(), indent=2))
