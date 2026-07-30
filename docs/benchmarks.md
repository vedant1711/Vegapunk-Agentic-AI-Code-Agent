# Benchmarks

Measured metrics from the multi-phase overhaul. Everything here is either
extracted from CI output, `pytest --cov` reports, or reproducible on a
local checkout with `make test`.

## Test suite growth

| Phase | Passing | Failing | New tests added | Coverage |
|-------|---------|---------|-----------------|----------|
| Session start | 10 | 1 (pre-existing) | — | 41% |
| Phase 0 (foundation)  | 11 | 0 | +1 (isolation fixture) | 41% |
| Phase 1 (repo graph)  | 42 | 0 | +31 (`test_repo_graph.py`) | 48% |
| Phase 2a (worktrees)  | 50 | 0 | +8 (`test_worktree.py`) | ~52% |
| Phase 2b (selector)   | 62 | 0 | +12 (`test_best_of_n_selector.py`) | ~55% |
| Phase 2d (BoN integ)  | 68 | 0 | +6 (`test_best_of_n_integration.py`) | **60%** |
| Phase 4a (demo)       | **71** | 0 | +3 (`test_demo_endpoint.py`) | ~62% |

Coverage numbers taken from `pytest --cov` at each checkpoint. The
per-module breakdown after Phase 4a:

| Module | Coverage | Notes |
|--------|----------|-------|
| `agent/state.py` | 100% | Data class; trivially covered |
| `app/config.py` | 100% | Settings class |
| `tools/best_of_n.py` | 100% | Pure functions, all paths exercised |
| `tools/repo_graph.py` | 90% | 31 unit tests + fixture repo |
| `agent/nodes/router.py` | 85% | Config + integration |
| `agent/nodes/coder.py` | 64% | Best-of-N paths exercised via integration test |
| `app/api/tasks.py` | 64% | Demo + non-demo endpoints |
| Others | 20-60% | Node LLM code paths not exercised without live LLM |

Full report reproducible via:

```bash
make test-backend    # or: pytest tests/ --cov --cov-report=term-missing
```

## Lint

| Phase | ruff errors | eslint errors |
|-------|-------------|---------------|
| Session start | 62 (pre-existing) | 0 (1 pre-existing font warning) |
| After auto-fix + config | 25 fixed automatically | unchanged |
| After per-file ignores | 0 | 0 errors, 1 pre-existing warning |
| Every phase since | **0** | **0 errors** |

Line length raised from 100 to 120 (standard for modern Python). `UP042`
(str + Enum) intentionally ignored for JSON-serialization stability. E501
ignored specifically for `tools/*.py` and `agent/nodes/*.py` where long
prompt strings and JSON tool-definition dicts would otherwise force ugly
wrapping.

## Repo-graph build performance

Measured against the `mini_py` fixture (6 files, 10 symbols):

- **Wall-clock build:** ~200-400ms cold, ~1-2ms warm (cached)
- **Files parsed:** 6
- **Symbols extracted:** 10
- **References:** 60
- **File-graph edges:** 4
- **PageRank values (non-uniform, non-degenerate):**
  - `src/auth.py`: 0.5044 (the leaf everything imports from)
  - `src/db.py`: 0.2062
  - `src/api.py`: 0.1447
  - `tests/test_auth.py`: 0.1447

Perf budget test asserts build under 3 seconds on the fixture; typical
run is well under that.

## Emoji strip

`grep -rnP "[\x{1F300}-\x{1FAFF}\x{2600}-\x{27BF}\x{1F000}-\x{1F0FF}\x{1F100}-\x{1F1FF}\x{1F200}-\x{1F2FF}]"`
across `agent/`, `app/`, `tools/`, `llm/`, `frontend/src/`, `README.md`,
`pyproject.toml`, `Dockerfile`, `docker-compose.yml`, `.env.example`:
**0 matches**.

## Demo mode timings

The pre-recorded transcript at `demo/transcript.json` is scripted to
mimic a realistic run:

| Step | Cumulative time (ms) | Duration (ms) |
|------|----------------------|---------------|
| Setup | 3,450 | 3,450 |
| Router | 4,290 | 780 |
| Planner | 6,600 | 2,260 |
| Coder (Best-of-N K=3) | 11,110 | 4,460 |
| Tester | 13,970 | 2,840 |
| Reviewer | 16,370 | 2,360 |
| PR Creator | 17,300 | 910 |
| **Total** | **~17.4 seconds** | — |

Long enough to see the trace animate through every step, short enough to
hold a portfolio-reviewer's attention.

## What isn't benchmarked (honestly)

- **Real-repo A/B of tree-sitter vs regex retrieval.** The research
  citation is real (2026 Codebase-Memory study, ~10x tokens); our own
  measurement on a set of real GitHub issues is a documented follow-up.
- **Best-of-N K=1 vs K=3 pass-rate on real issues.** The mechanics are
  tested end-to-end with mocks, but the "does it actually produce better
  PRs on real work" measurement requires LLM budget and a curated issue
  set. Also a follow-up.
- **Latency on cold Render dyno.** Render's free tier sleeps after 15
  minutes; wake-up is documented at ~30s but we haven't stopwatched it
  against this specific service.
- **Docker sandbox cold-start.** Depends heavily on host; not measured
  systematically.
