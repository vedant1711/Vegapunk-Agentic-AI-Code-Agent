import Link from "next/link";

import Header from "@/components/header";
import MermaidDiagram from "@/components/mermaid-diagram";

// Small building block for the evidence cards below. Numbers are
// sourced from benchmarks/results.json - regenerate with `make bench`.
function Metric({
  label,
  value,
  ci,
  note,
}: {
  label: string;
  value: string;
  ci?: string;
  note?: string;
}) {
  return (
    <div className="space-y-1 min-w-0">
      <div className="text-[10px] text-[var(--text-subtle)] uppercase tracking-wider">
        {label}
      </div>
      <div className="text-xl font-semibold mono text-[var(--text)] leading-tight">
        {value}
      </div>
      {ci && (
        <div className="text-[10px] text-[var(--text-muted)] mono">
          95% CI: {ci}
        </div>
      )}
      {note && (
        <div className="text-[10px] text-[var(--text-subtle)]">{note}</div>
      )}
    </div>
  );
}

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

        {/* Evidence — measured performance */}
        <section id="evidence">
          <h2 className="text-lg font-semibold mb-2">
            Evidence — measured performance
          </h2>
          <p className="text-[var(--text-muted)] text-sm mb-6 leading-relaxed">
            Every number below comes from a reproducible script in{" "}
            <span className="mono">benchmarks/</span> — run{" "}
            <span className="mono">make bench</span> to regenerate them
            locally. Values here are from the run at git{" "}
            <span className="mono">3105092</span>. Full detail, per-query
            breakdowns, and statistical framing in{" "}
            <a
              href="https://github.com/vedant1711/Vegapunk-Agentic-AI-Code-Agent/blob/main/docs/benchmarks.md"
              target="_blank"
              rel="noopener noreferrer"
              className="text-[var(--accent)] hover:underline"
            >
              docs/benchmarks.md
            </a>
            .
          </p>

          {/* Retrieval */}
          <div className="panel p-5 mb-4">
            <h3 className="text-sm font-semibold mb-1">
              Retrieval — tree-sitter graph vs regex baseline
            </h3>
            <p className="text-xs text-[var(--text-muted)] mb-4 leading-relaxed">
              9 hand-annotated queries across the mini_py fixture and the
              Vegapunk repo itself. Graph is compared against the legacy
              ripgrep-based retrieval the pipeline used before Phase 1.
            </p>
            <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
              <Metric
                label="Char reduction (mean)"
                value="2.92×"
                ci="[1.09, 3.63]"
              />
              <Metric
                label="MRR — graph"
                value="0.656"
                note="legacy: 0.281 (+133%)"
              />
              <Metric
                label="Best-case query"
                value="12.85×"
                note="MCP resource query"
              />
              <Metric
                label="Graph wins"
                value="7 / 9"
                note="on char reduction"
              />
            </div>
            <div className="mt-4 pt-3 border-t border-[var(--border)] text-xs text-[var(--text-muted)] leading-relaxed">
              Paired one-sided t-test on log(ratio) rejects H0 (no reduction)
              with{" "}
              <span className="mono text-[var(--text)]">
                t = 2.60, p = 0.015
              </span>
              . MRR uplift is +0.374 absolute — the graph finds ground-truth
              files earlier on 6 / 9 queries and never later than legacy.
            </div>
          </div>

          {/* Build perf */}
          <div className="panel p-5 mb-4">
            <h3 className="text-sm font-semibold mb-1">
              Graph build performance
            </h3>
            <p className="text-xs text-[var(--text-muted)] mb-4 leading-relaxed">
              Cold-build wall-clock (cache cleared) over 30 runs per
              workspace. 95% CI via student-t.
            </p>
            <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
              <Metric
                label="Vegapunk mean"
                value="68.5 ms"
                ci="[66.9, 70.2]"
              />
              <Metric
                label="Vegapunk p95"
                value="79.0 ms"
                note="81 files"
              />
              <Metric label="mini_py mean" value="0.9 ms" ci="[0.9, 0.9]" />
              <Metric label="mini_py p95" value="1.1 ms" note="6 files" />
            </div>
            <div className="mt-4 pt-3 border-t border-[var(--border)] text-xs text-[var(--text-muted)] leading-relaxed">
              The unit-test perf budget is &lt;3 s; we clear it by ~40×.
              Aider&apos;s repomap targets sub-second on typical repos; we&apos;re
              15× under that.
            </div>
          </div>

          {/* E2E */}
          <div className="panel p-5 mb-4">
            <h3 className="text-sm font-semibold mb-1">
              End-to-end pipeline determinism
            </h3>
            <p className="text-xs text-[var(--text-muted)] mb-4 leading-relaxed">
              10 fresh runs of{" "}
              <span className="mono">pytest tests/test_pipeline_e2e.py</span>.
              Real git worktrees + tree-sitter + pytest subprocess; only LLM
              / GitHub API / <span className="mono">git push</span> mocked.
            </p>
            <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
              <Metric label="Success rate" value="10 / 10" note="100%" />
              <Metric
                label="Latency mean"
                value="3.42 s"
                ci="[3.24, 3.59]"
              />
              <Metric label="Latency p95" value="4.10 s" note="σ 0.25 s" />
              <Metric
                label="Regression signal"
                value="✓"
                note="any real bug fails"
              />
            </div>
          </div>

          {/* Static gates */}
          <div className="panel p-5 mb-4">
            <h3 className="text-sm font-semibold mb-1">Static gates</h3>
            <p className="text-xs text-[var(--text-muted)] mb-4 leading-relaxed">
              Enforced on every push + PR via GitHub Actions matrix on
              Python 3.11 + 3.12 (backend) and Node 20 (frontend).
            </p>
            <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
              <Metric
                label="Tests passing"
                value="92 / 92"
                note="unit + integration + E2E"
              />
              <Metric label="Line coverage" value="72%" note="was 41%" />
              <Metric
                label="Ruff / tsc / ESLint"
                value="0 errors"
                note="on every push"
              />
              <Metric
                label="Coverage hotspots"
                value="100%"
                note="best_of_n, state, config"
              />
            </div>
          </div>

          {/* Comparison to research */}
          <div className="panel p-5">
            <h3 className="text-sm font-semibold mb-3">
              Comparison to cited research
            </h3>
            <div className="overflow-x-auto">
              <table className="w-full text-xs">
                <thead>
                  <tr className="text-[var(--text-subtle)] text-left">
                    <th className="py-2 pr-3 font-medium">Claim</th>
                    <th className="py-2 pr-3 font-medium">Source</th>
                    <th className="py-2 pr-3 font-medium">Our measurement</th>
                    <th className="py-2 font-medium">Verdict</th>
                  </tr>
                </thead>
                <tbody className="text-[var(--text-muted)]">
                  <tr className="border-t border-[var(--border)] align-top">
                    <td className="py-3 pr-3">
                      ~10× token reduction (tree-sitter graph vs regex)
                    </td>
                    <td className="py-3 pr-3">Codebase-Memory, 2026</td>
                    <td className="py-3 pr-3 mono">
                      2.92× mean, 12.85× max
                    </td>
                    <td className="py-3">
                      <span className="text-[var(--warning)]">
                        smaller but significant
                      </span>{" "}
                      (p = 0.015)
                    </td>
                  </tr>
                  <tr className="border-t border-[var(--border)] align-top">
                    <td className="py-3 pr-3">
                      Sub-second repo-graph build on typical repos
                    </td>
                    <td className="py-3 pr-3">Aider repomap docs</td>
                    <td className="py-3 pr-3 mono">
                      68.5 ms mean on Vegapunk
                    </td>
                    <td className="py-3">
                      <span className="text-[var(--success)]">15× better</span>
                    </td>
                  </tr>
                  <tr className="border-t border-[var(--border)] align-top">
                    <td className="py-3 pr-3">
                      Best-of-N beats single-shot via execution-verified
                      reward
                    </td>
                    <td className="py-3 pr-3">DeepSWE, ACECoder</td>
                    <td className="py-3 pr-3 mono">
                      selector 12 / 12 correct on unit tests + real E2E
                    </td>
                    <td className="py-3">
                      <span className="text-[var(--success)]">
                        mechanic verified
                      </span>{" "}
                      (see caveats)
                    </td>
                  </tr>
                  <tr className="border-t border-[var(--border)] align-top">
                    <td className="py-3 pr-3">
                      MCP as universal tool plane for coding agents
                    </td>
                    <td className="py-3 pr-3">MCP protocol adoption (~9k servers)</td>
                    <td className="py-3 pr-3 mono">
                      7 tools + 6 URI resources; 21 / 21 tests pass
                    </td>
                    <td className="py-3">
                      <span className="text-[var(--success)]">shipped</span>
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>
            <p className="mt-4 pt-3 border-t border-[var(--border)] text-xs text-[var(--text-muted)] leading-relaxed">
              Honest read: the 10× token headline from Codebase-Memory 2026
              was measured on 31 diverse repos. Our 9-query sample on this
              single codebase produces a smaller mean but the reduction is
              statistically significant and the best case matches the
              research ballpark. Direct SWE-bench-style cross-repo evaluation
              is a documented follow-up.
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
