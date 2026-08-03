"""Retrieval benchmark: tree-sitter repo graph vs legacy regex retrieval.

Two metrics per query:

  1. Char reduction (proxy for LLM token cost) - sum of file contents
     that would be sent to the LLM for the top-K files returned.
     Measured as a ratio (legacy_chars / graph_chars). Higher is better
     for the graph.

  2. Mean Reciprocal Rank against a ground-truth relevant-file set.
     For each query, find the rank of the first ground-truth file in
     the retrieval output; RR = 1/rank; MRR = mean across queries.

Runs on two workspaces:

  - tests/fixtures/mini_py (6 files, tight ground truth)
  - the Vegapunk repo itself (real-world scale, self-referential)

Emits a paired t-test p-value on log(char_ratio) so we know whether the
reduction is statistically significant vs no-reduction (H0: ratio = 1).
"""
from __future__ import annotations

import asyncio
import math
import statistics
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from scipy import stats

from tools.code_search import find_relevant_files as legacy_find
from tools.repo_graph import RepoGraph, clear_cache

REPO_ROOT = Path(__file__).resolve().parent.parent

# Query set: (workspace_path, query, ground_truth_files).
# Ground truth is the minimum set of files a competent engineer would say
# are directly relevant to the query. Files outside the ground truth
# aren't necessarily wrong to return - they just don't count for MRR.
QUERIES: list[tuple[str, str, list[str]]] = [
    # mini_py fixture (tiny, hand-annotated)
    (
        "tests/fixtures/mini_py",
        "user login password verification",
        ["src/auth.py", "src/api.py"],
    ),
    (
        "tests/fixtures/mini_py",
        "hash password for authentication",
        ["src/auth.py"],
    ),
    (
        "tests/fixtures/mini_py",
        "save user to database",
        ["src/db.py", "src/auth.py"],
    ),
    # Vegapunk repo (self-referential; realistic scale)
    (
        ".",
        "coder best of N candidate selection worktree",
        ["agent/nodes/coder.py", "tools/best_of_n.py"],
    ),
    (
        ".",
        "tree sitter repo graph pagerank ranking",
        ["tools/repo_graph.py"],
    ),
    (
        ".",
        "server sent events bus subscribe replay",
        ["app/events.py", "app/api/tasks.py"],
    ),
    (
        ".",
        "reviewer approve diff revise coder",
        ["agent/nodes/reviewer.py"],
    ),
    (
        ".",
        "run tests baseline comparison failure",
        ["agent/nodes/tester.py", "tools/best_of_n.py"],
    ),
    (
        ".",
        "MCP tool resource repo graph server",
        ["mcp_server/server.py", "mcp_server/resources.py", "mcp_server/tools.py"],
    ),
]

TOP_K = 5


@dataclass
class MethodResult:
    method: str
    n_files_returned: int
    top_files: list[str]
    total_chars: int
    rank_of_first_ground_truth: int | None  # None if no ground-truth file returned
    elapsed_ms: float


@dataclass
class QueryResult:
    workspace: str
    query: str
    ground_truth: list[str]
    legacy: MethodResult
    graph: MethodResult
    char_reduction_x: float  # legacy / graph
    graph_build_ms: float


@dataclass
class Summary:
    n_queries: int
    mean_char_reduction_x: float
    median_char_reduction_x: float
    min_char_reduction_x: float
    max_char_reduction_x: float
    ci_95_char_reduction_x: tuple[float, float]
    p_value_reduction_ge_1: float
    mrr_legacy: float
    mrr_graph: float
    mrr_uplift_absolute: float
    n_queries_where_graph_wins: int


def _read_chars(workspace: str, relative_paths: list[str]) -> int:
    """Sum of characters for a list of files (missing files count as 0)."""
    total = 0
    root = Path(workspace)
    for rp in relative_paths:
        try:
            full = root / rp
            if full.is_file():
                total += len(full.read_text(encoding="utf-8", errors="replace"))
        except (OSError, UnicodeError):
            pass
    return total


def _rank_of_first_match(top_files: list[str], ground_truth: list[str]) -> int | None:
    gt = set(ground_truth)
    for i, f in enumerate(top_files, start=1):
        if f in gt:
            return i
    return None


def _normalize_to_workspace(path: str, workspace: str) -> str:
    """Reduce a returned path to be relative to `workspace`.

    ripgrep returns paths relative to the CWD (the repo root), which for
    fixture workspaces means they carry the workspace prefix. RepoGraph
    already returns workspace-relative paths. This lets ground-truth
    intersection compare apples to apples.
    """
    p = Path(path)
    ws_abs = Path(workspace).resolve()
    try:
        if p.is_absolute():
            return str(p.relative_to(ws_abs))
    except (ValueError, OSError):
        pass
    # Try to strip a leading workspace directory from a relative path.
    ws_norm = Path(workspace).as_posix().rstrip("/")
    p_str = p.as_posix()
    if ws_norm and p_str.startswith(ws_norm + "/"):
        return p_str[len(ws_norm) + 1:]
    return p_str


async def _measure_legacy(workspace: str, query: str) -> MethodResult:
    """Emulate the planner's legacy retrieval: split query into keywords,
    run each through find_relevant_files, dedupe by first-seen order.
    """
    kws = [w for w in query.split() if len(w) >= 3][:5]
    seen: dict[str, dict[str, Any]] = {}
    start = time.perf_counter()
    for kw in kws:
        result = await legacy_find(workspace, kw)
        for f in result.get("files", []):
            path = _normalize_to_workspace(f["path"], workspace)
            if path not in seen:
                seen[path] = f
    elapsed_ms = (time.perf_counter() - start) * 1000

    top = list(seen.keys())[:TOP_K]
    return MethodResult(
        method="legacy",
        n_files_returned=len(seen),
        top_files=top,
        total_chars=_read_chars(workspace, top),
        rank_of_first_ground_truth=None,  # filled by caller
        elapsed_ms=elapsed_ms,
    )


async def _measure_graph(workspace: str, query: str) -> tuple[MethodResult, float]:
    """Build the graph, then query. Returns (result, build_ms)."""
    clear_cache()
    graph = RepoGraph(workspace)
    build_start = time.perf_counter()
    await graph.build()
    build_ms = (time.perf_counter() - build_start) * 1000

    query_start = time.perf_counter()
    matches = graph.relevant_files_for(query, limit=TOP_K)
    elapsed_ms = (time.perf_counter() - query_start) * 1000

    top = [m.path for m in matches]
    return (
        MethodResult(
            method="graph",
            n_files_returned=len(matches),
            top_files=top,
            total_chars=_read_chars(workspace, top),
            rank_of_first_ground_truth=None,
            elapsed_ms=elapsed_ms,
        ),
        build_ms,
    )


async def run() -> dict[str, Any]:
    per_query: list[QueryResult] = []

    for workspace, query, ground_truth in QUERIES:
        legacy = await _measure_legacy(workspace, query)
        graph, build_ms = await _measure_graph(workspace, query)

        legacy.rank_of_first_ground_truth = _rank_of_first_match(legacy.top_files, ground_truth)
        graph.rank_of_first_ground_truth = _rank_of_first_match(graph.top_files, ground_truth)

        ratio = legacy.total_chars / max(graph.total_chars, 1)
        per_query.append(QueryResult(
            workspace=workspace,
            query=query,
            ground_truth=ground_truth,
            legacy=legacy,
            graph=graph,
            char_reduction_x=round(ratio, 3),
            graph_build_ms=round(build_ms, 1),
        ))

    # Statistical summary of the char-reduction ratios
    ratios = [q.char_reduction_x for q in per_query]
    log_ratios = [math.log(max(r, 1e-9)) for r in ratios]

    # Paired one-sided t-test: H0 mean(log ratio) = 0 (no reduction).
    # We want to reject in favour of mean(log ratio) > 0 (reduction).
    tstat, p_two_sided = stats.ttest_1samp(log_ratios, popmean=0.0)
    p_one_sided = p_two_sided / 2 if tstat > 0 else 1.0 - p_two_sided / 2

    # 95% CI on the geometric mean of the ratio, back-transformed from log.
    if len(ratios) > 1:
        log_mean = statistics.mean(log_ratios)
        log_sem = statistics.stdev(log_ratios) / math.sqrt(len(log_ratios))
        t_crit = stats.t.ppf(0.975, df=len(ratios) - 1)
        ci_log_low = log_mean - t_crit * log_sem
        ci_log_high = log_mean + t_crit * log_sem
        ci = (round(math.exp(ci_log_low), 2), round(math.exp(ci_log_high), 2))
    else:
        ci = (ratios[0], ratios[0])

    # MRR
    def _rr(rank: int | None) -> float:
        return 1.0 / rank if rank else 0.0

    mrr_legacy = statistics.mean(_rr(q.legacy.rank_of_first_ground_truth) for q in per_query)
    mrr_graph = statistics.mean(_rr(q.graph.rank_of_first_ground_truth) for q in per_query)

    n_graph_wins = sum(1 for q in per_query if q.char_reduction_x > 1)

    summary = Summary(
        n_queries=len(per_query),
        mean_char_reduction_x=round(statistics.mean(ratios), 2),
        median_char_reduction_x=round(statistics.median(ratios), 2),
        min_char_reduction_x=round(min(ratios), 2),
        max_char_reduction_x=round(max(ratios), 2),
        ci_95_char_reduction_x=ci,
        p_value_reduction_ge_1=round(p_one_sided, 6),
        mrr_legacy=round(mrr_legacy, 3),
        mrr_graph=round(mrr_graph, 3),
        mrr_uplift_absolute=round(mrr_graph - mrr_legacy, 3),
        n_queries_where_graph_wins=n_graph_wins,
    )

    return {
        "queries": [
            {
                "workspace": q.workspace,
                "query": q.query,
                "ground_truth": q.ground_truth,
                "legacy": asdict(q.legacy),
                "graph": asdict(q.graph),
                "char_reduction_x": q.char_reduction_x,
                "graph_build_ms": q.graph_build_ms,
            }
            for q in per_query
        ],
        "summary": asdict(summary),
    }


if __name__ == "__main__":
    import json
    import sys

    result = asyncio.run(run())
    json.dump(result, sys.stdout, indent=2)
    sys.stdout.write("\n")
