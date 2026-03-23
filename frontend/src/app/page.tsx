"use client";

import { useState, useCallback, useRef, useEffect } from "react";
import { motion, AnimatePresence } from "framer-motion";
import AgentCard from "@/components/agent-card";
import PipelineFlow from "@/components/pipeline-flow";
import LogStream from "@/components/log-stream";
import TaskForm from "@/components/task-form";
import { SATELLITES, LOG_SATELLITE_MAP } from "@/lib/types";
import type { Satellite, SatelliteStatus, LogEntry, TaskState } from "@/lib/types";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

// Map satellite names from backend events to satellite IDs
function satelliteNameToId(name: string): string | null {
  for (const [key, id] of Object.entries(LOG_SATELLITE_MAP)) {
    if (name.includes(key)) return id;
  }
  return null;
}

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
  const eventSourceRef = useRef<EventSource | null>(null);

  const addLog = useCallback((satellite: string, message: string, level: LogEntry["level"]) => {
    const now = new Date();
    const ts = `${now.getHours().toString().padStart(2, "0")}:${now.getMinutes().toString().padStart(2, "0")}:${now.getSeconds().toString().padStart(2, "0")}`;
    const entry: LogEntry = {
      id: `log-${logIdCounter.current++}`,
      timestamp: ts,
      satellite,
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

  // Connect to real-time SSE stream for a task
  const connectSSE = useCallback((taskId: string) => {
    if (eventSourceRef.current) {
      eventSourceRef.current.close();
    }

    const es = new EventSource(`${API_BASE}/api/tasks/${taskId}/events`);
    eventSourceRef.current = es;

    let lastSatelliteId: string | null = null;

    es.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        const satId = satelliteNameToId(data.satellite);

        // If satellite changed, mark previous as done and new as active
        if (satId && satId !== lastSatelliteId) {
          if (lastSatelliteId) {
            updateSatelliteStatus(lastSatelliteId, "done");
          }
          updateSatelliteStatus(satId, "active", data.message);
          lastSatelliteId = satId;
        } else if (satId) {
          updateSatelliteStatus(satId, "active", data.message);
        }

        addLog(data.satellite, data.message, data.level || "info");

        // Check if finished
        if (data.message.includes("finished") || data.message.includes("Task failed")) {
          if (lastSatelliteId) {
            updateSatelliteStatus(lastSatelliteId, data.message.includes("failed") ? "error" : "done");
          }
          setTaskState(prev => ({
            ...prev,
            status: data.message.includes("failed") ? "failed" : "completed",
            activeSatellite: null,
          }));

          // Extract PR URL if present
          const prMatch = data.message.match(/https:\/\/github\.com\/[^\s]+/);
          if (prMatch) {
            setTaskState(prev => ({ ...prev, prUrl: prMatch[0] }));
          }

          es.close();
        }
      } catch {
        // Ignore parse errors
      }
    };

    es.onerror = () => {
      // Reconnect or close
      setTimeout(() => {
        if (es.readyState === EventSource.CLOSED) {
          // Check task status via poll
          fetch(`${API_BASE}/api/tasks/${taskId}`)
            .then(r => r.json())
            .then(data => {
              if (data.pr_url) {
                setTaskState(prev => ({
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
  }, [addLog, updateSatelliteStatus]);

  // Cleanup SSE on unmount
  useEffect(() => {
    return () => {
      if (eventSourceRef.current) {
        eventSourceRef.current.close();
      }
    };
  }, []);

  const handleSubmit = useCallback(async (issueUrl: string) => {
    // Reset state
    setSatellites(SATELLITES.map(s => ({ ...s, status: "idle", lastMessage: undefined })));
    setTaskState({
      taskId: "",
      status: "running",
      issueUrl,
      activeSatellite: null,
      satellites: {},
      logs: [],
    });

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
          status: "running",
        }));
        addLog("System", `Task ${data.task_id} queued — connecting to live stream...`, "info");

        // Connect to SSE for real-time events
        connectSSE(data.task_id);
        return;
      }
    } catch {
      addLog("System", "Backend not available — check that uvicorn is running on port 8000", "error");
      setTaskState(prev => ({ ...prev, status: "failed" }));
    }
  }, [addLog, connectSSE]);

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

        {/* Two-column: Log Stream (main) + Agent Cards (side) */}
        <div className="grid grid-cols-1 lg:grid-cols-5 gap-6">
          {/* Log Stream — takes 3 columns, prominent */}
          <div className="lg:col-span-3 lg:order-1">
            <LogStream logs={taskState.logs} />
          </div>

          {/* Agent Cards — takes 2 columns */}
          <div className="lg:col-span-2 lg:order-2 grid grid-cols-1 sm:grid-cols-2 gap-3">
            {satellites.map((sat, idx) => (
              <AgentCard
                key={sat.id}
                satellite={sat}
                isActive={taskState.activeSatellite === sat.id}
                index={idx}
              />
            ))}
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
