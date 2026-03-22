// Vegapunk Satellite definitions and types

export type SatelliteStatus = "idle" | "active" | "done" | "error";

export interface Satellite {
  id: string;
  name: string;
  role: string;
  number: string;
  emoji: string;
  color: string;
  glowColor: string;
  description: string;
  status: SatelliteStatus;
  lastMessage?: string;
}

export interface LogEntry {
  id: string;
  timestamp: string;
  satellite: string;
  message: string;
  level: "info" | "warning" | "error" | "success";
}

export interface TaskState {
  taskId: string;
  status: "idle" | "queued" | "running" | "completed" | "failed";
  issueUrl: string;
  activeSatellite: string | null;
  satellites: Record<string, SatelliteStatus>;
  logs: LogEntry[];
  prUrl?: string;
}

export const SATELLITES: Satellite[] = [
  {
    id: "stella",
    name: "Stella",
    role: "Setup",
    number: "PUNK-00",
    emoji: "⚙️",
    color: "#f5c542",
    glowColor: "rgba(245, 197, 66, 0.4)",
    description: "The Original — orchestrates all satellites",
    status: "idle",
  },
  {
    id: "shaka",
    name: "Shaka",
    role: "Router",
    number: "PUNK-01",
    emoji: "🧠",
    color: "#3498db",
    glowColor: "rgba(52, 152, 219, 0.4)",
    description: "The Good — logically classifies issues",
    status: "idle",
  },
  {
    id: "edison",
    name: "Edison",
    role: "Planner",
    number: "PUNK-03",
    emoji: "💡",
    color: "#e67e22",
    glowColor: "rgba(230, 126, 34, 0.4)",
    description: "The Thinker — generates implementation plans",
    status: "idle",
  },
  {
    id: "pythagoras",
    name: "Pythagoras",
    role: "Coder",
    number: "PUNK-04",
    emoji: "💻",
    color: "#9b59b6",
    glowColor: "rgba(155, 89, 182, 0.4)",
    description: "The Wise — writes code with deep knowledge",
    status: "idle",
  },
  {
    id: "atlas",
    name: "Atlas",
    role: "Tester",
    number: "PUNK-05",
    emoji: "🔨",
    color: "#e74c3c",
    glowColor: "rgba(231, 76, 60, 0.4)",
    description: "The Violent — breaks things to find bugs",
    status: "idle",
  },
  {
    id: "lilith",
    name: "Lilith",
    role: "Reviewer",
    number: "PUNK-02",
    emoji: "😈",
    color: "#e91e8c",
    glowColor: "rgba(233, 30, 140, 0.4)",
    description: "The Evil — harshly reviews code quality",
    status: "idle",
  },
  {
    id: "york",
    name: "York",
    role: "PR Creator",
    number: "PUNK-06",
    emoji: "🎯",
    color: "#2ecc71",
    glowColor: "rgba(46, 204, 113, 0.4)",
    description: "The Greedy — ships code to production",
    status: "idle",
  },
];

// Map log patterns to satellite IDs
export const LOG_SATELLITE_MAP: Record<string, string> = {
  "Stella": "stella",
  "Shaka": "shaka",
  "Edison": "edison",
  "Pythagoras": "pythagoras",
  "Atlas": "atlas",
  "Lilith": "lilith",
  "York": "york",
};
