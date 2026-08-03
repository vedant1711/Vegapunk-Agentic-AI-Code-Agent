import Link from "next/link";

import Header from "@/components/header";
import MermaidDiagram from "@/components/mermaid-diagram";

export const metadata = {
  title: "Architecture - Vegapunk",
  description:
    "How Vegapunk works: the seven-step pipeline, Best-of-N Coder, the tree-sitter repo graph, and the trace UI you're looking at.",
};

// --- Diagram sources (rendered client-side via Mermaid) ------------------

const SEQUENCE_DIAGRAM = `sequenceDiagram
    autonumber
    participant UI as Frontend
    participant API as Backend API
    participant Bus as Event Bus
    participant Pipe as Pipeline
    participant LLM as LLM Provider
    participant GH as GitHub

    UI->>API: POST /api/tasks/from-url
    API->>GH: fetch issue
    GH-->>API: title, body, labels
    API-->>UI: task_id
    UI->>Bus: subscribe (SSE)
    activate Bus

    API->>Pipe: run_agent
    activate Pipe

    Note over Pipe: Setup - clone + baseline + graph
    Pipe->>Bus: step events
    Bus-->>UI: rendered live

    Note over Pipe: Router - classify
    Pipe->>LLM: chat
    LLM-->>Pipe: classification

    Note over Pipe: Planner - plan
    Pipe->>LLM: chat
    LLM-->>Pipe: markdown plan

    Note over Pipe: Coder - Best-of-N (K parallel calls)
    par
        Pipe->>LLM: temp = 0.1
    and
        Pipe->>LLM: temp = 0.5
    and
        Pipe->>LLM: temp = 0.9
    end
    LLM-->>Pipe: K candidate diffs

    Note over Pipe: Tester + Reviewer
    Pipe->>Bus: step events

    Note over Pipe: PR Creator
    Pipe->>GH: create pull request
    GH-->>Pipe: PR URL
    Pipe->>Bus: run_end
    deactivate Pipe

    Bus-->>UI: run_end + PR URL
    deactivate Bus`;

const BEST_OF_N_DIAGRAM = `flowchart TB
    Plan[Plan from Planner] --> Ctx[Prompt context]
    Ctx --> C0[LLM #0<br/>temp 0.1]
    Ctx --> C1[LLM #1<br/>temp 0.5]
    Ctx --> C2[LLM #2<br/>temp 0.9]
    C0 --> W0[Fresh worktree A]
    C1 --> W1[Fresh worktree B]
    C2 --> W2[Fresh worktree C]
    W0 --> T0[Apply + Test]
    W1 --> T1[Apply + Test]
    W2 --> T2[Apply + Test]
    T0 --> S{Selector}
    T1 --> S
    T2 --> S
    S --> Win[Winning candidate]
    Win --> Main[Re-apply to<br/>main workspace]`;

const REPO_GRAPH_DIAGRAM = `flowchart LR
    Files[(Workspace<br/>py / ts / js / go / rs)] --> TS[tree-sitter parse]
    TS --> Sym[Symbols<br/>defs]
    TS --> Ref[References<br/>calls / imports]
    Sym --> Idx[Symbol index]
    Ref --> FG[File graph]
    FG --> PR[NetworkX<br/>PageRank]
    Query[Issue title + body] --> Tok[Tokenize]
    Tok --> Rank
    Idx --> Rank
    PR --> Rank[Hybrid ranking<br/>0.7 kw + 0.3 pr]
    Rank --> Top[Top-15 files]
    Top --> Planner[Planner prompt]`;

// --- Content -------------------------------------------------------------

const STEPS = [
  {
    name: "Setup",
    description:
      "Clone the target repo, create a working branch, capture the baseline test failure set, build the tree-sitter repo graph.",
  },
  {
    name: "Router",
    description:
      "Classify the issue as bug_fix / feature / refactor / docs / test / chore via one LLM call.",
  },
  {
    name: "Planner",
    description:
      "Retrieve relevant files via the repo graph, ask the LLM for a markdown implementation plan.",
  },
  {
    name: "Coder",
    description:
      "Generate K candidate diffs in parallel (Best-of-N), evaluate each in an isolated git worktree, keep the one with fewest new test failures.",
  },
  {
    name: "Tester",
    description:
      "Run tests on the main workspace. Only failures NEW vs the baseline trigger a retry back to Coder.",
  },
  {
    name: "Reviewer",
    description:
      "Self-review the diff for correctness, quality, and security; revise via Coder if needed (bounded).",
  },
  {
    name: "PR Creator",
    description:
      "Commit, push, detect the repo's default branch, open the PR, comment on the source issue.",
  },
];

export default function ArchitecturePage() {
  return (
    <div className="min-h-screen">
      <Header />

      <main className="max-w-4xl mx-auto px-6 py-8 space-y-10">
        {/* Intro */}
        <section>
          <h1 className="text-2xl font-semibold tracking-tight mb-3">
            How Vegapunk works
          </h1>
          <p className="text-[var(--text-muted)] leading-relaxed">
            Vegapunk takes a GitHub issue URL and produces a pull request
            end-to-end. A LangGraph pipeline in a FastAPI backend runs seven
            steps and streams typed events to this frontend over Server-Sent
            Events. Everything below is what makes that work — no code
            reading required.
          </p>
        </section>

        {/* The 7 steps */}
        <section>
          <h2 className="text-lg font-semibold mb-4">The 7 pipeline steps</h2>
          <div className="panel divide-y divide-[var(--border)]">
            {STEPS.map((s, i) => (
              <div key={s.name} className="p-4 flex gap-4">
                <span className="mono text-[var(--text-subtle)] w-6 flex-shrink-0 text-right">
                  {i + 1}
                </span>
                <div className="min-w-0">
                  <div className="text-sm font-medium text-[var(--text)]">
                    {s.name}
                  </div>
                  <div className="text-xs text-[var(--text-muted)] mt-1 leading-relaxed">
                    {s.description}
                  </div>
                </div>
              </div>
            ))}
          </div>
          <p className="text-xs text-[var(--text-subtle)] mt-3">
            Both retry loops (Tester → Coder on new test failures, Reviewer →
            Coder on rejection) cap at <span className="mono">max_retries</span>{" "}
            so the pipeline can&apos;t spin forever.
          </p>
        </section>

        {/* Diagram 1: sequence */}
        <section>
          <h2 className="text-lg font-semibold mb-2">
            1. End-to-end sequence
          </h2>
          <p className="text-[var(--text-muted)] text-sm mb-4 leading-relaxed">
            The request timeline from click to PR link, across every process
            boundary. Coder invokes K parallel LLM calls (Best-of-N — detail
            in the next diagram).
          </p>
          <MermaidDiagram id="seq-diagram" chart={SEQUENCE_DIAGRAM} />
        </section>

        {/* Diagram 2: Best-of-N */}
        <section>
          <h2 className="text-lg font-semibold mb-2">
            2. Best-of-N Coder — the quality-lifting mechanic
          </h2>
          <p className="text-[var(--text-muted)] text-sm mb-4 leading-relaxed">
            Instead of trusting a single LLM sample, the Coder generates K
            parallel candidates at different temperatures, verifies each
            against real tests in an isolated git worktree, and keeps the
            winner. Rooted in the DeepSWE and ACECoder research on
            execution-verified rewards.
          </p>
          <MermaidDiagram id="bon-diagram" chart={BEST_OF_N_DIAGRAM} />
          <p className="text-xs text-[var(--text-subtle)] mt-3">
            K is configurable via <span className="mono">CODER_BON_K</span>{" "}
            (default 3; set to 1 to disable and use the fast path).
          </p>
        </section>

        {/* Diagram 3: Repo graph */}
        <section>
          <h2 className="text-lg font-semibold mb-2">
            3. Repo graph — the retrieval mechanic
          </h2>
          <p className="text-[var(--text-muted)] text-sm mb-4 leading-relaxed">
            Before the Planner writes anything, we build a tree-sitter graph
            of the workspace and rank files by a hybrid of keyword overlap
            and PageRank on the reference graph. Grounded in a 2026 study
            reporting ~10× token reduction over regex scans on real repos.
          </p>
          <MermaidDiagram id="graph-diagram" chart={REPO_GRAPH_DIAGRAM} />
        </section>

        {/* What runs where */}
        <section>
          <h2 className="text-lg font-semibold mb-4">What runs where</h2>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            <div className="panel p-4">
              <h3 className="text-sm font-medium mb-2">
                Frontend (this app)
              </h3>
              <p className="text-xs text-[var(--text-muted)] leading-relaxed">
                Next.js 16 + React 19 on Vercel. Consumes the backend&apos;s
                SSE stream and renders each step as a live-updating card. No
                stateful backend on the frontend itself.
              </p>
            </div>
            <div className="panel p-4">
              <h3 className="text-sm font-medium mb-2">
                Backend (FastAPI on Render)
              </h3>
              <p className="text-xs text-[var(--text-muted)] leading-relaxed">
                Hosts the LangGraph pipeline, the event bus, and the MCP
                server. Free tier sleeps after 15 min of inactivity — first
                request after wake takes ~30 s.
              </p>
            </div>
            <div className="panel p-4">
              <h3 className="text-sm font-medium mb-2">LLM providers</h3>
              <p className="text-xs text-[var(--text-muted)] leading-relaxed">
                NVIDIA NIM primary, Google Gemini fallback. Auto-failover on
                rate-limit or 5xx so a single provider going down doesn&apos;t
                kill a run.
              </p>
            </div>
            <div className="panel p-4">
              <h3 className="text-sm font-medium mb-2">MCP server</h3>
              <p className="text-xs text-[var(--text-muted)] leading-relaxed">
                Optional. Exposes tools + the repo graph as MCP resources so
                Claude Code / Cursor / Cline can drive Vegapunk without a
                custom SDK. Launched via{" "}
                <span className="mono">vegapunk-mcp</span>.
              </p>
            </div>
          </div>
        </section>

        {/* Testing story */}
        <section>
          <h2 className="text-lg font-semibold mb-4">
            Confidence — how it&apos;s tested
          </h2>
          <div className="panel p-5 space-y-3 text-sm">
            <p className="text-[var(--text-muted)] leading-relaxed">
              <span className="mono text-[var(--text)]">make test-e2e</span>{" "}
              runs the <strong>entire real pipeline</strong> against a
              bundled seed repo — real git worktrees, real tree-sitter, real
              pytest — with only the LLM, GitHub API, and{" "}
              <span className="mono">git push</span> mocked. Whole thing
              takes ~4 seconds and needs no API keys or external repos.
            </p>
            <p className="text-[var(--text-muted)] leading-relaxed">
              Plus 92 unit + integration tests (60% → 72% coverage after the
              E2E landed), ruff + tsc + eslint gates, all green on every push
              via GitHub Actions.
            </p>
          </div>
        </section>

        {/* Try it */}
        <section>
          <h2 className="text-lg font-semibold mb-4">Try it yourself</h2>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            <Link
              href="/"
              className="panel p-5 hover:bg-white/[0.02] transition-colors block"
            >
              <div className="text-sm font-medium mb-2">Run the demo</div>
              <div className="text-xs text-[var(--text-muted)] leading-relaxed">
                Click <strong>Try demo</strong> on the dashboard to replay a
                pre-recorded run against a fixture issue — no keys needed.
                ~17 seconds end-to-end.
              </div>
            </Link>
            <a
              href="https://github.com/vedant1711/Vegapunk-Agentic-AI-Code-Agent"
              target="_blank"
              rel="noopener noreferrer"
              className="panel p-5 hover:bg-white/[0.02] transition-colors block"
            >
              <div className="text-sm font-medium mb-2">Read the code</div>
              <div className="text-xs text-[var(--text-muted)] leading-relaxed">
                Source on GitHub. See{" "}
                <span className="mono">docs/WALKTHROUGH.md</span> for a
                code-level tour with file:line references.
              </div>
            </a>
          </div>
        </section>
      </main>

      <footer className="border-t border-[var(--border)] mt-8 py-4 text-center">
        <p className="text-xs text-[var(--text-subtle)]">
          Vegapunk · Autonomous Coding Agent · LangGraph · FastAPI · Next.js
        </p>
      </footer>
    </div>
  );
}
