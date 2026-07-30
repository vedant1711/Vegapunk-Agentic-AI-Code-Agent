// Types shared between the backend event stream and the trace-style UI.

export type StepStatus = "pending" | "running" | "success" | "warning" | "error";

export type LogLevel = "info" | "warning" | "error" | "success";

export interface LogEntry {
  id: string;
  timestamp: string;   // HH:MM:SS formatted
  message: string;
  level: LogLevel;
}

export interface Step {
  id: string;
  name: string;
  description: string;
  status: StepStatus;
  durationMs?: number;
  logs: LogEntry[];
  startedAt?: number;  // milliseconds since epoch
  endedAt?: number;    // milliseconds since epoch
}

/**
 * Payload of a single Server-Sent Event emitted by the backend.
 * Mirrors app/events.py::AgentEvent.
 */
export interface AgentEventPayload {
  timestamp: number;   // seconds (unix)
  step: string;
  message: string;
  level: LogLevel;
  event_type: "log" | "step_start" | "step_end" | "run_end";
  duration_ms: number | null;
  step_status: StepStatus | null;
}

export interface RunState {
  taskId: string;
  status: "idle" | "queued" | "running" | "completed" | "failed";
  issueUrl: string;
  startedAt?: number;      // milliseconds since epoch
  endedAt?: number;        // milliseconds since epoch
  totalDurationMs?: number;
  steps: Step[];
  activeStepId: string | null;
  prUrl?: string;
  error?: string;
}

// Ordered list of pipeline steps rendered in the UI.
export const STEP_DEFS: Array<{ id: string; name: string; description: string }> = [
  { id: "setup", name: "Setup", description: "Clone repo, create branch, capture baseline tests" },
  { id: "router", name: "Router", description: "Classify the issue type" },
  { id: "planner", name: "Planner", description: "Analyze the codebase and produce an implementation plan" },
  { id: "coder", name: "Coder", description: "Apply code changes based on the plan" },
  { id: "tester", name: "Tester", description: "Run tests and compare against baseline" },
  { id: "reviewer", name: "Reviewer", description: "Self-review the diff for correctness and quality" },
  { id: "pr_creator", name: "PR Creator", description: "Commit, push, and open a pull request" },
];

// Map backend event step names to frontend step IDs.
export const STEP_NAME_TO_ID: Record<string, string> = {
  Setup: "setup",
  Router: "router",
  Planner: "planner",
  Coder: "coder",
  Tester: "tester",
  Reviewer: "reviewer",
  "PR Creator": "pr_creator",
};
