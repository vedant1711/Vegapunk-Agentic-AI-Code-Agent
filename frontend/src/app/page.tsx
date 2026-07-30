"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import RunHeader from "@/components/run-header";
import StepCard from "@/components/step-card";
import TaskForm from "@/components/task-form";
import {
  STEP_DEFS,
  STEP_NAME_TO_ID,
  type AgentEventPayload,
  type RunState,
  type Step,
} from "@/lib/types";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

let logSeq = 0;

function initialSteps(): Step[] {
  return STEP_DEFS.map((def) => ({
    ...def,
    status: "pending",
    logs: [],
  }));
}

function initialRun(): RunState {
  return {
    taskId: "",
    status: "idle",
    issueUrl: "",
    steps: initialSteps(),
    activeStepId: null,
  };
}

function formatTs(unixSeconds: number): string {
  const d = new Date(unixSeconds * 1000);
  const pad = (n: number) => n.toString().padStart(2, "0");
  return `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
}

export default function Dashboard() {
  const [run, setRun] = useState<RunState>(initialRun());
  const [now, setNow] = useState<number>(() => Date.now());
  const eventSourceRef = useRef<EventSource | null>(null);

  // Tick every ~500ms while running so the header duration updates live.
  useEffect(() => {
    if (run.status !== "running") return;
    const id = setInterval(() => setNow(Date.now()), 500);
    return () => clearInterval(id);
  }, [run.status]);

  const handleEvent = useCallback((data: AgentEventPayload) => {
    setRun((prev) => {
      const steps = prev.steps.map((s) => ({ ...s, logs: [...s.logs] }));
      const stepId = STEP_NAME_TO_ID[data.step];
      const target = stepId ? steps.find((s) => s.id === stepId) ?? null : null;

      let activeStepId = prev.activeStepId;
      let status = prev.status;
      let prUrl = prev.prUrl;
      let endedAt = prev.endedAt;
      let totalDurationMs = prev.totalDurationMs;

      if (data.event_type === "step_start" && target) {
        target.status = "running";
        target.startedAt = data.timestamp * 1000;
        activeStepId = target.id;
      } else if (data.event_type === "step_end" && target) {
        target.status = (data.step_status ?? "success") as Step["status"];
        target.endedAt = data.timestamp * 1000;
        target.durationMs = data.duration_ms ?? undefined;
        if (activeStepId === target.id) activeStepId = null;
      } else if (data.event_type === "run_end") {
        status = data.level === "error" ? "failed" : "completed";
        endedAt = data.timestamp * 1000;
        totalDurationMs = data.duration_ms ?? undefined;
        activeStepId = null;

        const prMatch = data.message.match(/https:\/\/github\.com\/[^\s]+/);
        if (prMatch) prUrl = prMatch[0];
      }

      // Log lines get attached to whichever step emitted them (if identifiable).
      if (target && data.message !== "keepalive" && data.event_type !== "step_end") {
        target.logs.push({
          id: `log-${logSeq++}`,
          timestamp: formatTs(data.timestamp),
          message: data.message,
          level: data.level,
        });
      }

      return {
        ...prev,
        steps,
        activeStepId,
        status,
        prUrl,
        endedAt,
        totalDurationMs,
      };
    });
  }, []);

  const connectSSE = useCallback(
    (taskId: string) => {
      if (eventSourceRef.current) eventSourceRef.current.close();
      const es = new EventSource(`${API_BASE}/api/tasks/${taskId}/events`);
      eventSourceRef.current = es;

      es.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data) as AgentEventPayload;
          handleEvent(data);
          if (data.event_type === "run_end") es.close();
        } catch {
          /* ignore parse errors on keepalive comments */
        }
      };

      es.onerror = () => {
        // The stream can drop momentarily on the FastAPI dev server. If the
        // connection is fully closed, fall back to a one-shot poll so we can
        // still learn about the PR URL / final status.
        setTimeout(() => {
          if (es.readyState === EventSource.CLOSED) {
            fetch(`${API_BASE}/api/tasks/${taskId}`)
              .then((r) => r.json())
              .then((data) => {
                if (data.pr_url) {
                  setRun((prev) => ({
                    ...prev,
                    status: "completed",
                    prUrl: data.pr_url,
                  }));
                }
              })
              .catch(() => {});
          }
        }, 2000);
      };
    },
    [handleEvent],
  );

  useEffect(() => {
    return () => {
      if (eventSourceRef.current) eventSourceRef.current.close();
    };
  }, []);

  const handleSubmit = useCallback(
    async (issueUrl: string) => {
      logSeq = 0;
      setRun({
        ...initialRun(),
        issueUrl,
        status: "running",
        startedAt: Date.now(),
      });

      try {
        const res = await fetch(`${API_BASE}/api/tasks/from-url`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ issue_url: issueUrl }),
        });

        if (res.ok) {
          const data = await res.json();
          if (data.error) {
            setRun((prev) => ({ ...prev, status: "failed", error: data.error }));
            return;
          }
          setRun((prev) => ({ ...prev, taskId: data.task_id }));
          connectSSE(data.task_id);
          return;
        }

        setRun((prev) => ({
          ...prev,
          status: "failed",
          error: `HTTP ${res.status}`,
        }));
      } catch {
        setRun((prev) => ({
          ...prev,
          status: "failed",
          error: "Backend not reachable - is uvicorn running on port 8000?",
        }));
      }
    },
    [connectSSE],
  );

  const statusDotColor =
    run.status === "running"
      ? "var(--running)"
      : run.status === "completed"
      ? "var(--success)"
      : run.status === "failed"
      ? "var(--error)"
      : "var(--border-strong)";

  return (
    <div className="min-h-screen">
      <header className="border-b border-[var(--border)]">
        <div className="max-w-5xl mx-auto px-6 py-4 flex items-center justify-between">
          <div className="flex items-baseline gap-3">
            <h1 className="text-lg font-semibold tracking-tight">Vegapunk</h1>
            <span className="text-xs text-[var(--text-muted)]">Autonomous Coding Agent</span>
          </div>
          <div className="flex items-center gap-2">
            <span
              className="status-dot"
              style={{
                background: statusDotColor,
                boxShadow: run.status === "running" ? `0 0 8px ${statusDotColor}` : "none",
              }}
            />
            <span className="text-xs text-[var(--text-muted)] capitalize">{run.status}</span>
          </div>
        </div>
      </header>

      <main className="max-w-5xl mx-auto px-6 py-6 space-y-4">
        <TaskForm onSubmit={handleSubmit} isRunning={run.status === "running"} />

        {run.status !== "idle" && (
          <>
            <RunHeader run={run} now={now} />
            <div className="space-y-2">
              {run.steps.map((step) => (
                <StepCard key={step.id} step={step} />
              ))}
            </div>

            {run.error && (
              <div
                className="panel p-4 mono text-sm"
                style={{ color: "var(--error)", borderColor: "var(--error)" }}
              >
                Error: {run.error}
              </div>
            )}
          </>
        )}
      </main>

      <footer className="border-t border-[var(--border)] mt-8 py-4 text-center">
        <p className="text-xs text-[var(--text-subtle)]">
          Vegapunk · Autonomous Coding Agent · LangGraph · FastAPI · Next.js
        </p>
      </footer>
    </div>
  );
}
