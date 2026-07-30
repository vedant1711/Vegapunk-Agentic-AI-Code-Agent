# Vegapunk — Autonomous Coding Agent

Vegapunk takes a GitHub issue URL and produces a pull request. Given an
issue, it clones the repository, classifies the issue, plans an
implementation, writes the code, runs the tests, self-reviews the diff,
and opens a PR — with a live trace UI showing every step.

---

## Pipeline

| # | Step        | Responsibility                                                                                                                                    |
|---|-------------|---------------------------------------------------------------------------------------------------------------------------------------------------|
| 1 | Setup       | Clone the repository, create a working branch, and capture the baseline test-failure set so pre-existing failures aren't blamed on the agent.     |
| 2 | Router      | Classify the issue as one of `bug_fix / feature / refactor / docs / test / chore`.                                                                |
| 3 | Planner     | Walk the repo tree, find relevant files, and produce a markdown implementation plan.                                                              |
| 4 | Coder       | Apply the changes. Hybrid rewrite / line-edit strategy — rewrites small files, does precise line-range edits on larger ones.                      |
| 5 | Tester      | Run the project's tests and linter. Compares failures against the baseline — only **new** failures trigger a retry back to the Coder.             |
| 6 | Reviewer    | Read the diff and self-review for correctness, quality, and security. Can send the run back to the Coder for revisions (bounded).                 |
| 7 | PR Creator  | Commit, push, detect the repository's default branch, and open the pull request.                                                                  |

Both retry loops (Tester → Coder on new test failures, Reviewer → Coder on
rejection) are capped at `max_retries` (default 3) to prevent unbounded
spins.

---

## Architecture

```
+---------------------------+           +-----------------------------+
| Next.js frontend (:3000)  |           | FastAPI backend (:8000)     |
|                           |           |                             |
| - task form               |  POST /api/tasks/from-url               |
| - run header (progress)   +---------->+                             |
| - step cards (trace)      |           |  agent/graph.py             |
|                           |           |  = LangGraph pipeline       |
|                           |  GET /api/tasks/{id}/events (SSE)       |
|                           +<----------+                             |
+---------------------------+           |                             |
                                        |  llm/provider.py            |
                                        |  NVIDIA NIM -> Gemini       |
                                        |                             |
                                        |  tools/                     |
                                        |  git_ops, github_api,       |
                                        |  filesystem, test_runner,   |
                                        |  code_search, sandbox       |
                                        +-----------------------------+
```

The pipeline is a LangGraph `StateGraph` with conditional edges for the
Coder/Tester retry loop and the Reviewer/Coder revision loop.

Every node emits structured events to an in-memory event bus
(`app/events.py`) — `step_start`, `step_end` (with duration and status),
and per-step log lines. The `/api/tasks/{id}/events` endpoint streams
those over Server-Sent Events. The frontend renders them as a trace
timeline with collapsible per-step cards.

---

## Quickstart

### Prerequisites
- Python 3.11+
- Node.js 18+
- One LLM API key: NVIDIA NIM or Google Gemini
- A GitHub Personal Access Token with `repo` scope

### Backend

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

cp .env.example .env
# edit .env with your API keys

uvicorn app.main:app --port 8000 --reload --reload-exclude 'workspaces/*'
```

### Frontend

```bash
cd frontend
npm install
npm run dev -- --port 3000
```

Open http://localhost:3000, paste a GitHub issue URL, and hit **Run agent**.

### Programmatic

```bash
curl -X POST http://localhost:8000/api/tasks/from-url \
  -H "Content-Type: application/json" \
  -d '{"issue_url": "https://github.com/owner/repo/issues/1"}'
```

---

## Environment variables

| Variable                 | Purpose                                                      | Required           |
|--------------------------|--------------------------------------------------------------|--------------------|
| `NVIDIA_API_KEY`         | NVIDIA NIM API key (primary LLM)                             | one of these two   |
| `GEMINI_API_KEY`         | Google Gemini API key (fallback LLM)                         | one of these two   |
| `GITHUB_TOKEN`           | GitHub PAT with `repo` scope                                 | yes                |
| `GITHUB_WEBHOOK_SECRET`  | HMAC-SHA256 secret for `/api/webhooks/github`                | optional           |

See `.env.example` for the full list including sandbox and workspace settings.

---

## Tech stack

**Backend**
- FastAPI (async, CORS, SSE)
- LangGraph — `StateGraph` with conditional edges for retry loops
- LLM providers: NVIDIA NIM (Qwen / Nemotron) primary, Google Gemini fallback
- GitPython + PyGithub
- Docker sandbox with a local-execution fallback for development

**Frontend**
- Next.js 16 (App Router, React 19)
- Tailwind CSS
- Native `EventSource` API for the SSE consumer

---

## Project layout

```
vegapunk/
  agent/
    graph.py           LangGraph pipeline; setup_node lives here
    state.py           AgentState TypedDict
    nodes/
      router.py        classify the issue
      planner.py       generate implementation plan
      coder.py         apply file changes (rewrite / line_edit / edit / delete)
      tester.py        run tests + linter, compare against baseline
      reviewer.py      self-review the diff
      pr_creator.py    commit, push, open PR
  app/
    main.py            FastAPI entry point
    config.py          Pydantic settings
    events.py          in-memory event bus + SSE-friendly AgentEvent
    api/
      tasks.py         REST + SSE endpoints
      webhooks.py      GitHub webhook handler
  llm/
    provider.py        NIM -> Gemini fallback, ModelTier
    nvidia_nim.py      OpenAI-compatible client
    gemini.py          Google generative AI client
  tools/
    git_ops.py         clone, branch, commit, push, diff
    github_api.py      issues, PRs, comments via PyGithub
    filesystem.py      read / write / apply_edit
    test_runner.py     pytest / npm / go auto-detect + linter
    code_search.py     repo tree + text search
    sandbox.py         Docker sandbox with local fallback
  frontend/
    src/
      app/             page.tsx (trace view), layout.tsx, globals.css
      components/      task-form, run-header, step-card
      lib/types.ts     shared types + STEP_DEFS
  tests/
```

---

## Known limitations and follow-ups

Roughly ranked by impact:

1. **Task and event persistence.** Both the task list and the event-bus
   history live in memory. They vanish on server restart. `aiosqlite`
   is already declared in `pyproject.toml` for exactly this migration.
2. **Sandbox network isolation** (`network_mode="none"`) breaks
   repositories whose tests need to `pip install` or `npm install` at
   runtime. Trade-off is documented in `tools/sandbox.py`.
3. **No repo-size cap.** A user pasting a huge repo URL will make the
   Setup step chew disk and time. A shallow clone (`--depth 1`) plus a
   repo-size limit is a small, high-value addition.
4. **Regex-based code retrieval.** `tools/code_search.py` and
   `agent/nodes/coder.py::_read_relevant_files` pick files by regex
   scanning. Tree-sitter + PageRank-style repo-mapping (as popularized
   by Aider) is meaningfully better for large repos and is a natural
   next upgrade.
5. **No API auth.** Anyone reaching the backend can trigger runs that
   spend LLM credits and push commits with the configured GitHub token.
6. **No token / cost metrics per step.** The trace UI shows durations
   but the LLM provider layer doesn't yet thread usage counts back into
   the event bus.
7. **Test isolation.** `tests/test_api.py::test_webhook_with_invalid_payload`
   reads the real `.env`, so it flips to 401 whenever
   `GITHUB_WEBHOOK_SECRET` is set locally. Test fixtures should stub
   settings.

---

## License

MIT
