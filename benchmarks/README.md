# Benchmark suite

Reproducible measurements backing every performance claim in
[`docs/benchmarks.md`](../docs/benchmarks.md) and the **Evidence**
section of the deployed
[`/architecture`](https://vegapunk-agentic-ai-code-agent.vercel.app/architecture)
page.

## Run everything

```bash
make bench                  # or: python -m benchmarks.run
```

Writes `benchmarks/results.json` and prints the retrieval summary to
stdout. Full run takes about 90 seconds on an M-series Mac (most of
it is the 10 E2E-pytest subprocess invocations).

## Individual modules

| Module | Metric | Approx duration |
|---|---|---|
| `python -m benchmarks.retrieval` | tree-sitter graph vs regex baseline (char reduction + MRR + t-test) | ~15 s |
| `python -m benchmarks.build_perf` | graph build time distribution (n=30 per workspace) | ~3 s |
| `python -m benchmarks.e2e_perf` | E2E pipeline latency + determinism (n=10) | ~40 s |

Skip the slow one:

```bash
python -m benchmarks.run --skip-e2e
```

## What we're measuring, and why

### Retrieval

Two metrics per query:

- **Char reduction** — sum of file contents that would be sent to the
  LLM for the top-K files, compared between methods. Ratio of
  legacy / graph. Proxy for token cost. Paired one-sided t-test on
  log-ratios (H0: ratio = 1) gives the p-value.
- **MRR** — Mean Reciprocal Rank against hand-annotated
  ground-truth files. Rewards putting the right file first.

Ground-truth queries are in `benchmarks/retrieval.py::QUERIES`.
Add a query + expected files there to grow the sample.

### Build performance

Wall-clock `RepoGraph.build()` time across 30 fresh (cache-cleared)
runs on each of two workspaces. Reports mean, median, p95, and a
95% CI on the mean via the student-t distribution.

### E2E

Runs `pytest tests/test_pipeline_e2e.py` 10 times in a subprocess.
Measures success rate (should be 100% - it's fully mocked) and
latency distribution. Any non-100% success rate = real regression to
investigate.

## Statistical framing

Where numbers are compared to research citations (e.g. "~10x token
reduction" from the 2026 Codebase-Memory study), we report our
measurement with a confidence interval and note whether it matches
or diverges. Our sample size is much smaller than published studies,
so the confidence intervals are wider - that's honest reporting, not
a weakness of the method.
