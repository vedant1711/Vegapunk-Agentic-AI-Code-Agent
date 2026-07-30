"use client";

import type { RunState } from "@/lib/types";

interface RunHeaderProps {
  run: RunState;
  now: number; // milliseconds since epoch, ticks while running
}

const statusColor: Record<string, string> = {
  pending: "var(--border-strong)",
  running: "var(--running)",
  success: "var(--success)",
  warning: "var(--warning)",
  error: "var(--error)",
};

function formatDuration(ms: number): string {
  if (ms < 1000) return `${Math.round(ms)}ms`;
  const s = ms / 1000;
  if (s < 60) return `${s.toFixed(1)}s`;
  const m = Math.floor(s / 60);
  const rem = Math.floor(s % 60);
  return `${m}m ${rem}s`;
}

export default function RunHeader({ run, now }: RunHeaderProps) {
  const done = run.steps.filter(
    (s) => s.status === "success" || s.status === "warning" || s.status === "error",
  ).length;
  const total = run.steps.length;

  const totalMs =
    run.totalDurationMs ??
    (run.startedAt ? (run.endedAt ?? now) - run.startedAt : 0);

  const showTotal = run.startedAt !== undefined;

  return (
    <div className="panel p-4">
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-baseline gap-3 min-w-0">
          <span className="text-xs text-[var(--text-subtle)] uppercase tracking-wider">Run</span>
          <span className="mono text-sm text-[var(--text)]">
            {run.taskId || "—"}
          </span>
          {showTotal && (
            <>
              <span className="text-[var(--text-subtle)]">·</span>
              <span className="text-xs text-[var(--text-muted)] mono">
                {formatDuration(totalMs)}
              </span>
            </>
          )}
        </div>
        <div className="flex items-center gap-3">
          <span className="text-xs text-[var(--text-muted)] mono">
            {done}/{total} steps
          </span>
          {run.prUrl && run.status === "completed" && run.prUrl.startsWith("http") && (
            <a
              href={run.prUrl}
              target="_blank"
              rel="noopener noreferrer"
              className="px-3 py-1 text-xs rounded-md bg-[var(--success)]/15 text-[var(--success)]
                border border-[var(--success)]/30 hover:bg-[var(--success)]/25 transition-colors"
            >
              View pull request
            </a>
          )}
        </div>
      </div>

      {/* Progress dots + connectors */}
      <div className="flex items-center gap-1">
        {run.steps.map((step, i) => (
          <div key={step.id} className="flex items-center flex-1 last:flex-initial">
            <div
              className="w-3 h-3 rounded-full transition-colors duration-300 flex-shrink-0"
              style={{
                background: statusColor[step.status] ?? statusColor.pending,
                boxShadow:
                  step.status === "running" ? `0 0 8px ${statusColor.running}` : "none",
              }}
              title={`${step.name}: ${step.status}`}
            />
            {i < run.steps.length - 1 && (
              <div
                className="flex-1 h-px mx-1 transition-colors duration-300"
                style={{
                  background:
                    step.status === "success" || step.status === "warning"
                      ? statusColor[step.status]
                      : "var(--border-strong)",
                }}
              />
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
