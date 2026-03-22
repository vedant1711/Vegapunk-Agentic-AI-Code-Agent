"use client";

import { useState, useCallback, useRef } from "react";
import { motion, AnimatePresence } from "framer-motion";
import AgentCard from "@/components/agent-card";
import PipelineFlow from "@/components/pipeline-flow";
import LogStream from "@/components/log-stream";
import TaskForm from "@/components/task-form";
import { SATELLITES, LOG_SATELLITE_MAP } from "@/lib/types";
import type { Satellite, SatelliteStatus, LogEntry, TaskState } from "@/lib/types";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

// Simulated pipeline for demo mode
const DEMO_SEQUENCE = [
  { satellite: "stella", delay: 500, message: "Cloning repository...", level: "info" as const },
  { satellite: "stella", delay: 1500, message: "Repository cloned. Branch created: agent/fix-issue-1", level: "success" as const },
  { satellite: "stella", delay: 800, message: "Running baseline tests...", level: "info" as const },
  { satellite: "stella", delay: 2000, message: "Baseline captured: 1 pre-existing failure", level: "info" as const },
  { satellite: "shaka", delay: 1000, message: "Classifying issue #1...", level: "info" as const },
  { satellite: "shaka", delay: 2000, message: "Classified as 'bug_fix' — confidence: high", level: "success" as const },
  { satellite: "edison", delay: 800, message: "Analyzing codebase structure...", level: "info" as const },
  { satellite: "edison", delay: 1500, message: "Searching for relevant files: calculator, divide, zero", level: "info" as const },
  { satellite: "edison", delay: 2500, message: "Implementation plan created (4,200 chars)", level: "success" as const },
  { satellite: "pythagoras", delay: 800, message: "Reading src/calculator.py (31 lines) [SMALL]", level: "info" as const },
  { satellite: "pythagoras", delay: 600, message: "Reading tests/test_calculator.py (34 lines) [SMALL]", level: "info" as const },
  { satellite: "pythagoras", delay: 2000, message: "line_edit: replaced L19-L24 in calculator.py ✅", level: "success" as const },
  { satellite: "pythagoras", delay: 1000, message: "line_edit: replaced L28-L31 in test_calculator.py ✅", level: "success" as const },
  { satellite: "atlas", delay: 800, message: "Running tests (attempt #1)...", level: "info" as const },
  { satellite: "atlas", delay: 500, message: "Lint: skipped (no linter config)", level: "info" as const },
  { satellite: "atlas", delay: 2000, message: "1 failure is PRE-EXISTING. Treating as PASS ✅", level: "success" as const },
  { satellite: "lilith", delay: 800, message: "Starting self-review...", level: "info" as const },
  { satellite: "lilith", delay: 2500, message: "✅ Approved — changes are correct and clean", level: "success" as const },
  { satellite: "york", delay: 600, message: "Committing changes...", level: "info" as const },
  { satellite: "york", delay: 1000, message: "Committed 2bb6efc", level: "info" as const },
  { satellite: "york", delay: 1500, message: "Pushed branch agent/fix-issue-1", level: "info" as const },
  { satellite: "york", delay: 2000, message: "✅ PR created → github.com/...#2", level: "success" as const },
];

export default function Dashboard() {
  const [taskState, setTaskState] = useState<TaskState>({
    taskId: "",
    status: "idle",
    issueUrl: "",
    activeSatellite: null,
    satellites: {},
    logs: [],
  });
  const [satellites, setSatellites] = useState<Satellite[]>(SATELLITES.map(s => ({ ...s })));
  const logIdCounter = useRef(0);

  const addLog = useCallback((satellite: string, message: string, level: LogEntry["level"]) => {
    const now = new Date();
    const ts = `${now.getHours().toString().padStart(2, "0")}:${now.getMinutes().toString().padStart(2, "0")}:${now.getSeconds().toString().padStart(2, "0")}`;
    const entry: LogEntry = {
      id: `log-${logIdCounter.current++}`,
      timestamp: ts,
      satellite: SATELLITES.find(s => s.id === satellite)?.name || satellite,
      message,
      level,
    };
    setTaskState(prev => ({
      ...prev,
      logs: [...prev.logs, entry],
    }));
  }, []);

  const updateSatelliteStatus = useCallback((id: string, status: SatelliteStatus, lastMessage?: string) => {
    setSatellites(prev => prev.map(s =>
      s.id === id ? { ...s, status, lastMessage: lastMessage || s.lastMessage } : s
    ));
    setTaskState(prev => ({
      ...prev,
      activeSatellite: status === "active" ? id : prev.activeSatellite,
      satellites: { ...prev.satellites, [id]: status },
    }));
  }, []);

  const runDemo = useCallback(async () => {
    // Reset state
    setSatellites(SATELLITES.map(s => ({ ...s, status: "idle", lastMessage: undefined })));
    setTaskState({
      taskId: "demo-" + Date.now().toString(36),
      status: "running",
      issueUrl: "https://github.com/vedant1711/test-repo/issues/1",
      activeSatellite: null,
      satellites: {},
      logs: [],
    });

    let currentSatellite = "";

    for (const step of DEMO_SEQUENCE) {
      await new Promise(r => setTimeout(r, step.delay));

      // If satellite changed, mark previous as done
      if (step.satellite !== currentSatellite) {
        if (currentSatellite) {
          updateSatelliteStatus(currentSatellite, "done");
        }
        currentSatellite = step.satellite;
        updateSatelliteStatus(step.satellite, "active");
      }

      addLog(step.satellite, step.message, step.level);
      updateSatelliteStatus(step.satellite, "active", step.message);
    }

    // Mark last satellite as done
    updateSatelliteStatus(currentSatellite, "done");

    setTaskState(prev => ({
      ...prev,
      status: "completed",
      activeSatellite: null,
      prUrl: "https://github.com/vedant1711/test-repo/pull/2",
    }));
  }, [addLog, updateSatelliteStatus]);

  const handleSubmit = useCallback(async (issueUrl: string) => {
    // Try to call the real API first
    try {
      const res = await fetch(`${API_BASE}/api/tasks/from-url`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ issue_url: issueUrl }),
      });

      if (res.ok) {
        const data = await res.json();
        setTaskState(prev => ({
          ...prev,
          taskId: data.task_id,
          status: "queued",
          issueUrl,
          logs: [],
        }));
        addLog("stella", `Task ${data.task_id} queued for ${issueUrl}`, "info");
        // TODO: Connect WebSocket for real-time updates
        // For now, fall through to demo
        setTimeout(() => runDemo(), 1000);
        return;
      }
    } catch {
      // API not available, run demo
    }

    addLog("stella", "Backend not available — running demo simulation", "warning");
    runDemo();
  }, [addLog, runDemo]);

  return (
    <div className="relative z-10 min-h-screen">
      {/* Header */}
      <header className="border-b border-white/5 bg-black/20 backdrop-blur-xl sticky top-0 z-50">
        <div className="max-w-7xl mx-auto px-6 py-4 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <motion.span
              className="text-3xl"
              animate={{ rotate: [0, 5, -5, 0] }}
              transition={{ duration: 3, repeat: Infinity }}
            >
              🏴‍☠️
            </motion.span>
            <div>
              <h1 className="text-xl font-bold bg-gradient-to-r from-[#f5c542] to-[#e67e22] bg-clip-text text-transparent">
                Vegapunk
              </h1>
              <p className="text-[10px] text-gray-500 uppercase tracking-[0.2em]">
                Agentic Coding Agent
              </p>
            </div>
          </div>

          <div className="flex items-center gap-4">
            <AnimatePresence>
              {taskState.status === "completed" && taskState.prUrl && (
                <motion.a
                  initial={{ opacity: 0, scale: 0.8 }}
                  animate={{ opacity: 1, scale: 1 }}
                  href={taskState.prUrl}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="px-4 py-2 rounded-xl bg-green-500/20 text-green-400 text-xs font-semibold hover:bg-green-500/30 transition-colors"
                >
                  ✅ View PR →
                </motion.a>
              )}
            </AnimatePresence>

            <div className={`w-2.5 h-2.5 rounded-full ${
              taskState.status === "running" ? "bg-cyan-400 animate-pulse" :
              taskState.status === "completed" ? "bg-green-400" :
              taskState.status === "failed" ? "bg-red-400" :
              "bg-gray-600"
            }`} />
          </div>
        </div>
      </header>

      {/* Main content */}
      <main className="max-w-7xl mx-auto px-6 py-8 space-y-6">
        {/* Task Form */}
        <TaskForm onSubmit={handleSubmit} isRunning={taskState.status === "running"} />

        {/* Pipeline Flow */}
        <PipelineFlow
          satelliteStatuses={taskState.satellites}
          activeSatellite={taskState.activeSatellite}
        />

        {/* Dashboard Grid: Agent Cards + Log Stream */}
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          {/* Agent Cards */}
          <div className="lg:col-span-2 grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-3 gap-4">
            {satellites.map((sat, idx) => (
              <AgentCard
                key={sat.id}
                satellite={sat}
                isActive={taskState.activeSatellite === sat.id}
                index={idx}
              />
            ))}
          </div>

          {/* Log Stream */}
          <div className="lg:col-span-1">
            <LogStream logs={taskState.logs} />
          </div>
        </div>
      </main>

      {/* Footer */}
      <footer className="border-t border-white/5 mt-12 py-6 text-center">
        <p className="text-xs text-gray-600">
          Powered by Stella 🧬 • NVIDIA NIM + Gemini • LangGraph
        </p>
      </footer>
    </div>
  );
}
