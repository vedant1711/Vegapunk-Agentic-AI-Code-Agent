"use client";

import { useState } from "react";
import type { Step } from "@/lib/types";

interface StepCardProps {
  step: Step;
}

const statusColor: Record<string, string> = {
  pending: "var(--text-subtle)",
  running: "var(--running)",
  success: "var(--success)",
  warning: "var(--warning)",
  error: "var(--error)",
};

// ASCII-only status glyphs so nothing looks like an emoji.
const statusGlyph: Record<string, string> = {
  pending: "o",
  running: "*",
  success: "+",
  warning: "!",
  error: "x",
};

function formatDuration(ms?: number): string {
  if (ms === undefined || ms === null) return "";
  if (ms < 1000) return `${Math.round(ms)}ms`;
  const s = ms / 1000;
  if (s < 60) return `${s.toFixed(2)}s`;
  const m = Math.floor(s / 60);
  const rem = (s % 60).toFixed(0);
  return `${m}m ${rem}s`;
}

const levelColor: Record<string, string> = {
  info: "var(--text-muted)",
  success: "var(--success)",
  warning: "var(--warning)",
  error: "var(--error)",
};

export default function StepCard({ step }: StepCardProps) {
  const canExpand = step.status !== "pending";
  const color = statusColor[step.status];

  // Auto-expand while the step is running, auto-collapse on success. Track
  // status transitions during render (React's "derived from props" pattern)
  // to avoid a setState-in-effect anti-pattern, but still let the user
  // override the default by clicking.
  const [expanded, setExpanded] = useState<boolean>(step.status === "running");
  const [prevStatus, setPrevStatus] = useState(step.status);
  if (prevStatus !== step.status) {
    setPrevStatus(step.status);
    if (step.status === "running") setExpanded(true);
    else if (step.status === "success") setExpanded(false);
  }

  return (
    <div className="panel">
      <button
        type="button"
        onClick={() => canExpand && setExpanded((v) => !v)}
        disabled={!canExpand}
        className={`w-full flex items-center gap-3 px-4 py-3 text-left transition-colors ${
          canExpand ? "hover:bg-white/[0.02] cursor-pointer" : "cursor-default"
        }`}
      >
        <span
          className={`mono text-sm flex-shrink-0 w-4 text-center ${
            step.status === "running" ? "animate-pulse" : ""
          }`}
          style={{ color }}
        >
          {statusGlyph[step.status]}
        </span>
        <div className="flex-1 min-w-0">
          <div className="flex items-baseline gap-3 flex-wrap">
            <span className="text-sm font-medium text-[var(--text)]">{step.name}</span>
            <span className="text-xs text-[var(--text-subtle)]">{step.description}</span>
          </div>
        </div>
        <span className="text-xs mono text-[var(--text-muted)] flex-shrink-0">
          {formatDuration(step.durationMs)}
        </span>
        {canExpand && (
          <span className="text-[var(--text-subtle)] text-xs w-3 text-center">
            {expanded ? "▾" : "▸"}
          </span>
        )}
      </button>

      {expanded && (
        <div className="border-t border-[var(--border)] px-4 py-3 space-y-0.5 mono text-xs max-h-80 overflow-y-auto">
          {step.logs.length === 0 ? (
            <div className="text-[var(--text-subtle)]">No log lines yet.</div>
          ) : (
            step.logs.map((log) => (
              <div key={log.id} className="flex gap-3">
                <span className="text-[var(--text-subtle)] flex-shrink-0">{log.timestamp}</span>
                <span
                  className="break-all min-w-0"
                  style={{ color: levelColor[log.level] ?? "var(--text-muted)" }}
                >
                  {log.message}
                </span>
              </div>
            ))
          )}
        </div>
      )}
    </div>
  );
}
