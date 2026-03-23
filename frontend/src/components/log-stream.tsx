"use client";

import { useEffect, useRef } from "react";
import { motion } from "framer-motion";
import type { LogEntry } from "@/lib/types";

interface LogStreamProps {
  logs: LogEntry[];
}

const SATELLITE_COLORS: Record<string, string> = {
  "Stella": "#f5c542",
  "Shaka": "#3498db",
  "Edison": "#e67e22",
  "Pythagoras": "#9b59b6",
  "Atlas": "#e74c3c",
  "Lilith": "#e91e8c",
  "York": "#2ecc71",
  "System": "#00d4ff",
};

function getSatelliteColor(name: string): string {
  for (const [key, color] of Object.entries(SATELLITE_COLORS)) {
    if (name.includes(key)) return color;
  }
  return "#888";
}

export default function LogStream({ logs }: LogStreamProps) {
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [logs]);

  const levelIcons = {
    info: "○",
    warning: "◉",
    error: "✕",
    success: "✓",
  };

  const levelColors = {
    info: "text-blue-300",
    warning: "text-yellow-300",
    error: "text-red-400",
    success: "text-green-400",
  };

  return (
    <div className="card-glow p-5 flex flex-col" style={{ minHeight: "500px" }}>
      <div className="flex items-center justify-between mb-4">
        <h2 className="text-base font-bold text-white flex items-center gap-2">
          <span className="w-2 h-2 rounded-full bg-green-400 animate-pulse" />
          Live Activity
        </h2>
        <span className="text-xs text-gray-500 font-mono">
          {logs.length} events
        </span>
      </div>

      <div
        ref={scrollRef}
        className="flex-1 overflow-y-auto space-y-0.5 min-h-0 font-mono"
      >
        {logs.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-48 text-gray-600">
            <span className="text-3xl mb-3">📡</span>
            <p className="text-sm">Waiting for satellite activity...</p>
            <p className="text-xs text-gray-700 mt-1">Submit an issue URL above to start</p>
          </div>
        ) : (
          logs.map((log) => {
            const color = getSatelliteColor(log.satellite);
            return (
              <motion.div
                key={log.id}
                initial={{ opacity: 0, x: -8 }}
                animate={{ opacity: 1, x: 0 }}
                transition={{ duration: 0.15 }}
                className="flex items-start gap-3 px-3 py-2.5 rounded-lg hover:bg-white/[0.03] transition-colors group"
              >
                {/* Level icon */}
                <span className={`text-xs shrink-0 pt-0.5 font-bold ${levelColors[log.level]}`}>
                  {levelIcons[log.level]}
                </span>

                {/* Timestamp */}
                <span className="text-[11px] text-gray-600 shrink-0 pt-px tabular-nums">
                  {log.timestamp}
                </span>

                {/* Satellite name */}
                <span
                  className="text-[11px] font-bold shrink-0 pt-px min-w-[120px]"
                  style={{ color }}
                >
                  {log.satellite}
                </span>

                {/* Message */}
                <span className="text-[12px] text-gray-200 break-words min-w-0 leading-relaxed">
                  {log.message}
                </span>
              </motion.div>
            );
          })
        )}
      </div>
    </div>
  );
}
