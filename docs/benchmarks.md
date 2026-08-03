# Benchmarks

Every number here comes from a reproducible script in
[`benchmarks/`](../benchmarks). Regenerate them locally with:

```bash
make bench      # writes benchmarks/results.json
```

Most-recent run was against git `3105092` on Darwin 24.6.0 arm64,
Python 3.13.7.

---

## Summary at a glance

| Area | Metric | Value | 95% CI | Sample size |
|---|---|---|---|---|
| Retrieval | Char reduction (graph vs regex) | **2.92×** mean | [1.09×, 3.63×] | n = 9 queries |
| Retrieval | Best-case reduction | 12.85× | — | 1 query |
| Retrieval | MRR — legacy retrieval | 0.281 | — | n = 9 |
| Retrieval | MRR — tree-sitter graph | **0.656** (+133%) | — | n = 9 |
| Retrieval | Paired one-sided t-test on log-ratio | **p = 0.015** | H0: ratio = 1 rejected | n = 9 |
| Graph build | Vegapunk repo (81 files) | **68.5 ms** mean | [66.9, 70.2] ms | n = 30 |
| Graph build | Vegapunk repo p95 | 79.0 ms | — | n = 30 |
| Graph build | mini_py fixture (6 files) | 0.9 ms mean | [0.9, 0.9] ms | n = 30 |
| E2E pipeline | Success rate | **10 / 10 (100%)** | — | n = 10 mocked runs |
| E2E pipeline | Latency mean | 3.42 s | [3.24, 3.59] s | n = 10 |
| E2E pipeline | Latency p95 | 4.10 s | — | n = 10 |
| Test suite | Total tests | 92 passing | — | — |
| Test suite | Line coverage | 72% | — | — |
| Static | Ruff / TypeScript / ESLint | 0 errors | — | — |

---

## 1. Retrieval — tree-sitter repo graph vs regex baseline

**Question we're answering:** does the tree-sitter graph actually
retrieve fewer, more relevant files than the legacy regex retrieval
we replaced?

**Method:** for each of 9 hand-annotated queries (3 on the mini_py
fixture, 6 on the Vegapunk repo itself), we run both retrieval
methods and measure:

1. **Char reduction ratio** — total file characters that would flow
   into the LLM prompt for the top-5 returned files. Ratio =
   `legacy_chars / graph_chars`. > 1 means graph is more efficient.
2. **Mean Reciprocal Rank** — for each query, rank of the first
   ground-truth file in the retrieval output. RR = 1/rank; MRR is
   the average.

Ground-truth files are hand-annotated in
[`benchmarks/retrieval.py::QUERIES`](../benchmarks/retrieval.py).

### Per-query breakdown

| Workspace | Query | Graph files | Legacy files | Char ratio | Legacy rank | Graph rank |
|---|---|---:|---:|---:|:---:|:---:|
| mini_py | `user login password verification` | 4 | 4 | 1.00× | 2 | **1** |
| mini_py | `hash password for authentication` | 2 | 4 | 1.60× | 1 | 1 |
| mini_py | `save user to database` | 2 | 3 | 1.27× | 2 | **1** |
| vegapunk | `coder best of N candidate selection worktree` | 5 | 14 | 1.79× | miss | 4 |
| vegapunk | `tree sitter repo graph pagerank ranking` | 5 | 8 | 0.99× | 3 | **1** |
| vegapunk | `server sent events bus subscribe replay` | 3 | 29 | 2.30× | 5 | **1** |
| vegapunk | `reviewer approve diff revise coder` | 5 | 40 | 1.62× | miss | 5 |
| vegapunk | `run tests baseline comparison failure` | 5 | 16 | 2.84× | miss | 5 |
| vegapunk | `MCP tool resource repo graph server` | 5 | 17 | **12.85×** | miss | 4 |

Graph wins on **7 / 9** queries by char count, and finds a
ground-truth file in the top-5 for **9 / 9** queries. Legacy finds
ground truth in top-5 for **5 / 9**.

### Statistical significance

Paired one-sided t-test on the log-transformed reduction ratios
(H0: ratio = 1, i.e. no reduction; H1: ratio > 1) yields
**t = 2.60, p = 0.015** — we reject the null at α = 0.05. The
geometric-mean 95% CI is `[1.09×, 3.63×]`; the entire interval is
above 1.

MRR uplift is **+0.374 absolute** (+133% relative), which is a large
effect size given the small sample.

### Comparison to research

The 2026 Codebase-Memory study
([Anthony West](https://anthonywest.co.uk/research/code-intelligence-indexing-2026-openai))
reports **~10× fewer tokens and 2.1× fewer tool calls** across
**31 repositories**. Our measurement is smaller (2.92× mean) but:

- Our sample is 9 queries on 2 codebases; the study's is much broader.
- Our **best case (12.85×) is in the research ballpark**.
- Our p-value confirms the reduction is not noise.
- Both methods agree the graph is directionally the same win.

Honest read: graph retrieval is materially better than the regex
baseline on this codebase, though not by the full 10× the research
sees on their larger sample.

---

## 2. Graph build performance

**Question we're answering:** does the tree-sitter graph build fast
enough to be worth doing on every run?

**Method:** for each workspace, clear the graph cache and time
`RepoGraph.build()`. Repeat 30 times. Report mean / median / p95 /
min / max / stdev, plus a 95% CI on the mean via the student-t
distribution (df = 29).

| Workspace | Files | Mean | Median | p95 | Min | Max | 95% CI on mean |
|---|---:|---:|---:|---:|---:|---:|---|
| mini_py fixture | 6 | 0.9 ms | 0.9 ms | 1.1 ms | 0.8 ms | 1.4 ms | [0.9, 0.9] ms |
| Vegapunk repo | 81 | **68.5 ms** | 66.9 ms | 79.0 ms | 63.5 ms | 92.4 ms | [66.9, 70.2] ms |

Very tight distribution (CI width < 4 ms on 30 samples) — the build
is deterministic modulo OS-level noise.

**Comparison:** Aider's repomap targets "sub-second on typical repos";
our numbers are ~15× under that on a directly comparable codebase.
The unit test perf budget in [`tests/test_repo_graph.py`](../tests/test_repo_graph.py)
asserts `<3 s` on the fixture and we clear it by 3000×.

---

## 3. End-to-end pipeline

**Question we're answering:** does the whole pipeline actually work
reliably without external services, or is it flaky?

**Method:** run `pytest tests/test_pipeline_e2e.py` 10 times in a
subprocess. The E2E test exercises the *entire real pipeline* against
[`tests/fixtures/seed_repo/`](../tests/fixtures/seed_repo) with only
the LLM, GitHub API, and `git push` mocked. Everything else — git
worktrees, tree-sitter graph build, Best-of-N candidate generation,
pytest subprocess, event bus — runs for real.

| Metric | Value |
|---|---|
| Success rate | **10 / 10 (100%)** |
| Latency mean | 3.42 s |
| Latency median | 3.33 s |
| Latency p95 | 4.10 s |
| Latency min / max | 3.29 s / 4.10 s |
| Latency stdev | 0.25 s |
| 95% CI on mean | [3.24, 3.59] s |

**Interpretation:** the pipeline is fully deterministic given the
mocked edges. Any regression that breaks Setup → Router → Planner
→ Coder (K=3 parallel + selector) → Tester → Reviewer → PR Creator
flow will fail this test.

---

## 4. Static gates

Everything below is enforced by
[`.github/workflows/ci.yml`](../.github/workflows/ci.yml) on every
push and PR.

| Gate | Value |
|---|---|
| Tests passing | 92 / 92 |
| Line coverage | 72% (up from 41% pre-Phase-0) |
| Ruff (backend) | 0 errors |
| TypeScript `tsc --noEmit` | 0 errors |
| ESLint (frontend) | 0 errors |
| Next.js build | success (`/`, `/architecture` prerendered) |

Coverage highlights by module:

- `tools/best_of_n.py`: **100%**
- `agent/state.py`: **100%**
- `app/config.py`: **100%**
- `tools/repo_graph.py`: 90%
- `agent/nodes/router.py`: 85%

---

## Reproducibility

Everything above is one command from any checkout with the venv
activated:

```bash
source .venv/bin/activate
pip install -e ".[dev]"        # only first time
make bench                     # regenerates benchmarks/results.json
```

The full run takes ~90 s (most of it is the 10 subprocess E2E runs).
`make bench --skip-e2e` is available for a fast retrieval-focused
loop.

## Caveats — where this evidence is weak

- **9 queries is a small sample.** Wider ground-truth query sets
  would tighten the CI on char reduction, and MRR is very sensitive
  to which queries you pick.
- **We test on our own codebase.** A real cross-project SWE-bench-style
  evaluation would be a stronger claim. Documented follow-up.
- **The Best-of-N mechanics are unit-tested but not benchmarked
  quality-wise.** K=1 vs K=3 on the same real issues (with real LLM)
  would tell us whether the extra cost translates to better PRs.
  That requires LLM budget + a curated issue set; also documented
  follow-up.
- **The E2E pipeline uses recorded LLM responses.** It confirms the
  plumbing works; it can't validate the LLM's own decisions.
