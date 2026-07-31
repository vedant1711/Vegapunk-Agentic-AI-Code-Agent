# Glossary

Vocabulary used across the code and the docs. If a term reads as
overloaded elsewhere, this file is the source of truth for what it
means in this project.

## Agent / Pipeline

- **Pipeline** — the LangGraph `StateGraph` compiled at
  [`agent/graph.py`](../agent/graph.py). Runs seven **Steps** end-to-end.
- **Step** (aka **Node**) — one unit of work in the pipeline. Each has
  a file in [`agent/nodes/`](../agent/nodes/).
- **AgentState** — the shared TypedDict flowing between steps.
  Definitions in [`agent/state.py`](../agent/state.py).

## Steps

- **Setup** — clone the target repo, create a working branch, capture
  the baseline test failure set, build the tree-sitter repo graph.
- **Router** — classify the issue as `bug_fix / feature / refactor /
  docs / test / chore` via a single LLM call.
- **Planner** — retrieve relevant files, ask the LLM for a markdown
  implementation plan.
- **Coder** — produce actual code changes. Single-shot when
  `CODER_BON_K=1`; **Best-of-N** when `CODER_BON_K>=2`.
- **Tester** — run pytest + linter; compare against baseline; retry
  Coder on any **new** failure.
- **Reviewer** — LLM self-review; may loop back to Coder for revisions.
- **PR Creator** — commit, push, detect default branch, open PR,
  comment on the source issue.

## Retrieval

- **Repo graph** — the in-memory index built at Setup by
  [`tools/repo_graph.py::RepoGraph`](../tools/repo_graph.py).
- **Symbol** — a definition (function, class, method) extracted via
  tree-sitter.
- **Reference** — a use site of a symbol (call, import) extracted via
  tree-sitter.
- **File graph** — a `networkx.DiGraph` where edge `(a, b)` means
  "file *a* references at least one symbol defined in *b*". Feeds
  PageRank.
- **Hybrid ranking** — `combined = alpha * keyword_score + (1 - alpha)
  * pagerank_score` with default `alpha = 0.7`. Neither signal alone
  is enough; keyword is query-sensitive but shallow, PageRank is
  query-independent but structural.

## Best-of-N

- **Candidate** — one of K parallel diffs the Coder generates at
  different sampling temperatures.
- **Worktree** — a `git worktree` at `<repo>-wt-<uuid>` where a single
  Candidate applies its changes and runs its tests, isolated from
  every other Candidate and from the main workspace.
- **Selector** — [`tools/best_of_n.py::select_best_candidate`](../tools/best_of_n.py).
  Ranks candidates by `(parsed, tests_ran, new_failures asc,
  changes_applied desc, diff_size asc, index)`.
- **Baseline** — the set of test failures captured at Setup, **before**
  any code change. Used by both Tester and Best-of-N so pre-existing
  bugs never count as regressions of the agent's work.

## Events / Trace

- **step_start** — event emitted when a Step begins its work.
- **step_end** — emitted when a Step finishes; carries `duration_ms`
  and `step_status` (`success` / `warning` / `error`).
- **log** — free-form log line during a Step.
- **run_end** — terminal event for the whole run; carries total
  duration and (if any) a PR URL in the message body.
- **AgentEvent** — the dataclass in [`app/events.py`](../app/events.py)
  that carries all of the above over SSE.

## MCP

- **Tool** — a procedural verb the MCP client can invoke
  (e.g. `read_file`, `run_tests`). Definitions in
  [`mcp_server/tools.py`](../mcp_server/tools.py).
- **Resource** — a URI-addressable piece of state the client can
  fetch. Definitions in
  [`mcp_server/resources.py`](../mcp_server/resources.py). Novel to
  Vegapunk: the repo graph is exposed *as resources*, not just tools.
- **Resource template** — a URI pattern the client fills in
  (e.g. `vegapunk://graph/symbols?q={query}`). The reader dispatches
  on scheme + authority + path.

## Modes

- **Demo mode** — `POST /api/tasks/demo` replays
  [`demo/transcript.json`](../demo/transcript.json) into the SSE
  stream. No LLM calls, no credentials. ~17 seconds end-to-end.
- **E2E test** — `make test-e2e` runs the *real* pipeline against
  [`tests/fixtures/seed_repo/`](../tests/fixtures/seed_repo) with the
  LLM, GitHub API, and `git push` mocked. Real git worktrees, real
  pytest, no external services. See
  [`tests/test_pipeline_e2e.py`](../tests/test_pipeline_e2e.py).
- **Single-shot Coder** — `CODER_BON_K=1`. One LLM call per Coder
  step, applied directly to the main workspace. Fast + cheap.
- **Best-of-N Coder** — `CODER_BON_K>=2`. K parallel LLM calls;
  winner chosen by execution-verified criteria.

## Configuration

- **Model tier** — `FAST` / `STANDARD` / `HEAVY`. Maps to different
  models per LLM provider in [`llm/provider.py`](../llm/provider.py).
  Router uses `FAST`; Coder + Planner use `HEAVY`; Reviewer uses
  `STANDARD`.
- **SANDBOX_ALLOW_NETWORK** — default `true`. Lets cloned projects
  install their own deps at test time. Flip to `false` for hardened
  isolation at the cost of most real repos not being able to run
  their tests.
- **VEGAPUNK_WORKSPACE** — used by the MCP server to know which repo
  to index. Defaults to `$PWD`.
