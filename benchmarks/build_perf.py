"""Graph build time distribution across N runs.

Each run rebuilds the graph from scratch (cache cleared) so we're
measuring the true cold-build cost, not a memoized fetch.

Reports mean, median, p95, min, max, and a 95% CI on the mean via the
student-t distribution. `n_runs=30` gives reasonable CI width.
"""
from __future__ import annotations

import asyncio
import math
import statistics
import time
from dataclasses import asdict, dataclass
from typing import Any

from scipy import stats

from tools.repo_graph import RepoGraph, clear_cache


@dataclass
class BuildDistribution:
    label: str
    n_runs: int
    files_parsed: int
    mean_ms: float
    median_ms: float
    p95_ms: float
    min_ms: float
    max_ms: float
    stdev_ms: float
    ci_95_mean_ms: tuple[float, float]


async def _distribution(label: str, workspace: str, n_runs: int = 30) -> BuildDistribution:
    times_ms: list[float] = []
    files = 0
    for _ in range(n_runs):
        clear_cache()
        graph = RepoGraph(workspace)
        t0 = time.perf_counter()
        stats_obj = await graph.build()
        times_ms.append((time.perf_counter() - t0) * 1000)
        files = stats_obj.files_parsed

    mean = statistics.mean(times_ms)
    sd = statistics.stdev(times_ms) if len(times_ms) > 1 else 0.0
    sem = sd / math.sqrt(len(times_ms)) if len(times_ms) > 1 else 0.0
    t_crit = stats.t.ppf(0.975, df=max(1, len(times_ms) - 1)) if len(times_ms) > 1 else 0.0

    p95 = statistics.quantiles(times_ms, n=20)[18] if len(times_ms) >= 20 else max(times_ms)

    return BuildDistribution(
        label=label,
        n_runs=n_runs,
        files_parsed=files,
        mean_ms=round(mean, 1),
        median_ms=round(statistics.median(times_ms), 1),
        p95_ms=round(p95, 1),
        min_ms=round(min(times_ms), 1),
        max_ms=round(max(times_ms), 1),
        stdev_ms=round(sd, 1),
        ci_95_mean_ms=(
            round(mean - t_crit * sem, 1),
            round(mean + t_crit * sem, 1),
        ),
    )


async def run(n_runs: int = 30) -> dict[str, Any]:
    return {
        "mini_py_fixture": asdict(await _distribution("mini_py_fixture", "tests/fixtures/mini_py", n_runs)),
        "vegapunk_self": asdict(await _distribution("vegapunk_self", ".", n_runs)),
    }


if __name__ == "__main__":
    import json
    import sys

    result = asyncio.run(run())
    json.dump(result, sys.stdout, indent=2)
    sys.stdout.write("\n")
