"use client";

import { useEffect, useRef } from "react";
import { motion } from "framer-motion";
import type { LogEntry } from "@/lib/types";

interface LogStreamProps {
  logs: LogEntry[];
}

export default function LogStream({ logs }: LogStreamProps) {
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [logs]);

  const levelColors = {
    info: "text-blue-400",
    warning: "text-yellow-400",
    error: "text-red-400",
    success: "text-green-400",
  };

  const levelBg = {
    info: "bg-blue-500/10",
    warning: "bg-yellow-500/10",
    error: "bg-red-500/10",
    success: "bg-green-500/10",
  };

  return (
    <div className="card-glow p-5 flex flex-col h-full">
      <div className="flex items-center justify-between mb-4">
        <h2 className="text-sm font-semibold text-gray-400 uppercase tracking-wider">
          📡 Live Activity
        </h2>
        <span className="text-[10px] text-gray-500 font-mono">
          {logs.length} events
        </span>
      </div>

      <div
        ref={scrollRef}
        className="flex-1 overflow-y-auto space-y-1.5 min-h-0"
        style={{ maxHeight: "400px" }}
      >
        {logs.length === 0 ? (
          <div className="flex items-center justify-center h-32 text-gray-600 text-sm">
            Waiting for activity...
          </div>
        ) : (
          logs.map((log, i) => (
            <motion.div
              key={log.id}
              initial={{ opacity: 0, x: -10 }}
              animate={{ opacity: 1, x: 0 }}
              transition={{ duration: 0.2 }}
              className={`log-entry flex items-start gap-2 px-3 py-2 rounded-lg ${levelBg[log.level]}`}
            >
              <span className="text-[10px] font-mono text-gray-500 shrink-0 pt-0.5">
                {log.timestamp}
              </span>
              <span className={`text-[10px] font-bold shrink-0 pt-0.5 uppercase tracking-wider ${levelColors[log.level]}`}>
                {log.satellite}
              </span>
              <span className="text-xs text-gray-300 break-words min-w-0">
                {log.message}
              </span>
            </motion.div>
          ))
        )}
      </div>
    </div>
  );
}
