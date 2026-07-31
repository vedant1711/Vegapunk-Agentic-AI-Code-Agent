# Walkthrough — what happens when you click "Run agent"

Follow along in the code. Every file:line reference below points at what
does the work at each step. If you're just looking for what a term means,
see [`GLOSSARY.md`](GLOSSARY.md) instead.

---

## 1. User submits an issue URL (frontend)

**Where:** [`frontend/src/app/page.tsx`](../frontend/src/app/page.tsx)

The **Run agent** button lives in `TaskForm` and is wired to
`handleSubmit(url)`. That handler delegates to a shared
`startRun(endpoint, body, label)` — the same function used by **Try demo**.
`startRun` resets the run state, posts to `/api/tasks/from-url`, and on
success opens an `EventSource` on `/api/tasks/{task_id}/events`.

Frontend components involved:
- `components/task-form.tsx` — the URL input + two buttons
- `components/run-header.tsx` — the progress dots + total live duration
- `components/step-card.tsx` — collapsible per-step logs with duration

## 2. Backend enqueues a background task

**Where:** [`app/api/tasks.py::create_task_from_url`](../app/api/tasks.py)

- Parses the URL into `repo_full_name` + `issue_number`.
- Optionally hits the GitHub API for title/body (falls back to a stub
  if no `GITHUB_TOKEN`).
- Delegates to `create_task`, which registers the task in the in-memory
  `_tasks` dict and schedules the async `_run_task(task_id, request)`.
- Returns `{task_id}` immediately so the frontend can start streaming.

## 3. Pipeline kicks off

**Where:** [`agent/graph.py::run_agent`](../agent/graph.py)

- Builds `initial_state: AgentState` with the issue metadata.
- Invokes `agent_graph.ainvoke(initial_state)` where `agent_graph` is
  the LangGraph `StateGraph` compiled at module load time.
- Each node returns a partial dict that LangGraph merges into the
  running state; fields not in the return dict pass through unchanged.

Nodes in order:

| Node | File | What it does |
|---|---|---|
| **Setup** | [`agent/graph.py::setup_node`](../agent/graph.py) | clone, create branch, capture baseline tests, build the tree-sitter repo graph |
| **Router** | [`agent/nodes/router.py`](../agent/nodes/router.py) | 1 LLM call to classify the issue type |
| **Planner** | [`agent/nodes/planner.py`](../agent/nodes/planner.py) | repo-graph retrieval + 1 LLM call for the plan |
| **Coder** | [`agent/nodes/coder.py`](../agent/nodes/coder.py) | Best-of-N or single-shot code generation |
| **Tester** | [`agent/nodes/tester.py`](../agent/nodes/tester.py) | real pytest run + baseline comparison |
| **Reviewer** | [`agent/nodes/reviewer.py`](../agent/nodes/reviewer.py) | LLM self-review of the diff |
| **PR Creator** | [`agent/nodes/pr_creator.py`](../agent/nodes/pr_creator.py) | commit, push, open PR |

**Retry loops:**
- Tester → Coder on any **new** test failure (bounded by `max_retries`).
- Reviewer → Coder on rejection (also bounded).

Both caps live on `AgentState` (`retry_count`, `review_retry_count`) — see [`agent/state.py`](../agent/state.py).

## 4. Every step emits typed events

**Where:** [`app/events.py`](../app/events.py)

Each node bookends its work with:

```python
event_bus.step_start(task_id, "Coder")
...
event_bus.emit(task_id, "Coder", "some log line", "info")
...
event_bus.step_end(task_id, "Coder", "success", duration_seconds)
```

The event bus is process-local; it maintains a subscriber list per
`task_id` plus a full history so late subscribers can catch up on
replay. `run_end` is the terminal signal — the SSE endpoint closes on
that event.

Event schema (`AgentEvent` dataclass):
- `timestamp`, `step`, `message`, `level`, `task_id`
- `event_type`: one of `log` / `step_start` / `step_end` / `run_end`
- `duration_ms`, `step_status` — populated on `step_end` / `run_end`

## 5. Frontend renders the trace live

**Where:** [`frontend/src/app/page.tsx::handleEvent`](../frontend/src/app/page.tsx)

The SSE stream deserializes to `AgentEventPayload` (see
[`frontend/src/lib/types.ts`](../frontend/src/lib/types.ts)). Each event
mutates `run.steps[i]`:

- `step_start` → `steps[i].status = "running"`; header starts ticking a live duration
- `step_end` → final `status` + `durationMs` recorded
- `log` → appended to `steps[i].logs`
- `run_end` → whole run done; frontend closes the SSE stream, extracts a PR URL from the message if present, and flips the status pill

`StepCard` auto-expands while a step is running and auto-collapses on
success so the trace stays tidy.

## 6. PR link surfaces back

**Where:** [`app/api/tasks.py::_run_task`](../app/api/tasks.py)

After `run_agent` returns, `_run_task` extracts `pr_url` from the final
state and calls `event_bus.run_end(...)` with a message like
`Run finished. PR: https://github.com/.../pull/42`. The frontend's
`handleEvent` regexes the URL out and enables the **View pull request**
button in the header.

---

## Cross-cutting concerns

### LLM provider — [`llm/provider.py`](../llm/provider.py)

`LLMProvider.chat` tries NVIDIA NIM first; on any failure falls back to
Gemini. Every node calls `llm.chat(...)`, so the failover is
transparent. Model tier (`FAST` / `STANDARD` / `HEAVY`) picks the
model within each provider.

### Retrieval — [`tools/repo_graph.py`](../tools/repo_graph.py)

`RepoGraph.relevant_files_for(query)` combines keyword overlap with
PageRank on the file-level reference graph. Used by Planner (to seed
the plan) and Coder (to expand file context via `file_neighborhood`).
See [`GLOSSARY.md#hybrid-ranking`](GLOSSARY.md#hybrid-ranking).

### Best-of-N — [`agent/nodes/coder.py::_best_of_n`](../agent/nodes/coder.py) + [`tools/best_of_n.py`](../tools/best_of_n.py)

Fresh git worktree per candidate, K parallel LLM calls, tests run in
each worktree, winner selected by `select_best_candidate`, re-applied
to main workspace, worktrees cleaned up. Toggle with `CODER_BON_K`.

### Sandbox — [`tools/sandbox.py`](../tools/sandbox.py)

Prefers a Docker container for shell execution; falls back to local
subprocess when Docker isn't installed (which is the dev default).
`SANDBOX_ALLOW_NETWORK` (default `true`) lets cloned projects run
`pip install` / `npm install`.

### MCP surface — [`mcp_server/`](../mcp_server/)

Exposes seven tools + six graph resources over stdio so external
clients (Claude Code, Cursor, Cline) can drive Vegapunk without a
custom SDK. See [`mcp_server/README.md`](../mcp_server/README.md).

### Demo mode — [`app/api/tasks.py::_run_demo`](../app/api/tasks.py) + [`demo/transcript.json`](../demo/transcript.json)

`POST /api/tasks/demo` replays the transcript into the SSE stream with
realistic per-event delays. Zero LLM calls, zero credentials.

### E2E test — [`tests/test_pipeline_e2e.py`](../tests/test_pipeline_e2e.py) + [`tests/fixtures/seed_repo/`](../tests/fixtures/seed_repo)

`make test-e2e` runs the entire real pipeline against the bundled
seed repo, with LLM + GitHub + push mocked. Verifies the whole flow
in ~15 seconds with no external services.
