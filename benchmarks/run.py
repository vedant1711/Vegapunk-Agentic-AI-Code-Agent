"""Run every benchmark and write results.json + a markdown summary.

Usage:
    python -m benchmarks.run                    # all measurements
    python -m benchmarks.run --skip-e2e         # skip slow E2E timing
    python -m benchmarks.run --n-build-runs 60  # more graph-build samples
"""
from __future__ import annotations

import argparse
import asyncio
import json
import platform
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from benchmarks import build_perf, e2e_perf, retrieval

RESULTS_PATH = Path(__file__).parent / "results.json"


def _git_sha() -> str:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, check=True,
        )
        return out.stdout.strip()
    except Exception:
        return "unknown"


async def _collect(args: argparse.Namespace) -> dict[str, Any]:
    print("[bench] retrieval (regex vs tree-sitter graph)...", file=sys.stderr)
    retrieval_result = await retrieval.run()

    print(f"[bench] graph build perf (n={args.n_build_runs} per workspace)...", file=sys.stderr)
    build_result = await build_perf.run(n_runs=args.n_build_runs)

    e2e_result: dict[str, Any] | None = None
    if not args.skip_e2e:
        print(f"[bench] E2E pipeline latency (n={args.n_e2e_runs})...", file=sys.stderr)
        e2e_result = e2e_perf.run(n_runs=args.n_e2e_runs)

    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "git_sha": _git_sha(),
        "python": sys.version.split()[0],
        "platform": {
            "system": platform.system(),
            "release": platform.release(),
            "machine": platform.machine(),
        },
        "retrieval": retrieval_result,
        "build_perf": build_result,
        "e2e": e2e_result,
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--skip-e2e", action="store_true", help="skip E2E timing (which spawns pytest subprocesses)")
    ap.add_argument("--n-build-runs", type=int, default=30, help="graph-build sample size")
    ap.add_argument("--n-e2e-runs", type=int, default=10, help="E2E sample size")
    ap.add_argument("--out", type=Path, default=RESULTS_PATH, help="results.json output path")
    args = ap.parse_args()

    results = asyncio.run(_collect(args))
    args.out.write_text(json.dumps(results, indent=2, default=str) + "\n", encoding="utf-8")
    print(f"[bench] wrote {args.out}", file=sys.stderr)
    print(json.dumps(results["retrieval"]["summary"], indent=2))


if __name__ == "__main__":
    main()
