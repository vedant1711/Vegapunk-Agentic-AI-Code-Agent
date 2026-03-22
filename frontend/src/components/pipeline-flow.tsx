"use client";

import { motion } from "framer-motion";
import { SATELLITES } from "@/lib/types";
import type { SatelliteStatus } from "@/lib/types";

interface PipelineFlowProps {
  satelliteStatuses: Record<string, SatelliteStatus>;
  activeSatellite: string | null;
}

export default function PipelineFlow({ satelliteStatuses, activeSatellite }: PipelineFlowProps) {
  // Order of pipeline execution
  const pipelineOrder = ["stella", "shaka", "edison", "pythagoras", "atlas", "lilith", "york"];

  const getNodeColor = (id: string) => {
    const sat = SATELLITES.find(s => s.id === id);
    const status = satelliteStatuses[id] || "idle";
    if (status === "active") return sat?.color || "#00d4ff";
    if (status === "done") return "#2ecc71";
    if (status === "error") return "#e74c3c";
    return "#333344";
  };

  const getSatStatus = (id: string): SatelliteStatus => {
    return satelliteStatuses[id] ?? "idle";
  };

  const getConnectorStatus = (fromIdx: number): "idle" | "active" | "done" => {
    const fromStatus = getSatStatus(pipelineOrder[fromIdx]);
    const toStatus = getSatStatus(pipelineOrder[fromIdx + 1]);

    if (toStatus === "active") return "active";
    if (fromStatus === "done" && toStatus === "done") return "done";
    return "idle";
  };

  return (
    <div className="card-glow p-6">
      <h2 className="text-sm font-semibold text-gray-400 uppercase tracking-wider mb-5">
        ⚡ Pipeline Flow
      </h2>

      <div className="flex items-center justify-between gap-1 overflow-x-auto pb-2">
        {pipelineOrder.map((satId, idx) => {
          const sat = SATELLITES.find(s => s.id === satId)!;
          const isActive = activeSatellite === satId;
          const status = satelliteStatuses[satId] || "idle";

          return (
            <div key={satId} className="flex items-center">
              {/* Node */}
              <motion.div
                className={`flex flex-col items-center gap-2 px-2 ${
                  isActive ? "satellite-active" : ""
                }`}
                style={{ color: getNodeColor(satId) }}
                animate={isActive ? { scale: [1, 1.05, 1] } : {}}
                transition={{ duration: 1.5, repeat: Infinity }}
              >
                <div
                  className="w-10 h-10 rounded-full flex items-center justify-center text-base border-2 transition-all duration-500"
                  style={{
                    borderColor: getNodeColor(satId),
                    background: status === "active" ? `${sat.color}22` : "transparent",
                    boxShadow: isActive ? `0 0 20px ${sat.glowColor}` : "none",
                  }}
                >
                  {sat.emoji}
                </div>
                <div className="text-center">
                  <p className="text-[10px] font-bold text-white leading-none">{sat.name}</p>
                  <p className="text-[9px] text-gray-500">({sat.role})</p>
                </div>
              </motion.div>

              {/* Connector */}
              {idx < pipelineOrder.length - 1 && (
                <div className="flex-shrink-0 w-8 h-0.5 mx-1 relative">
                  <div className="absolute inset-0 bg-gray-700 rounded-full" />
                  {getConnectorStatus(idx) !== "idle" && (
                    <motion.div
                      className="absolute inset-0 rounded-full origin-left"
                      style={{
                        background:
                          getConnectorStatus(idx) === "active"
                            ? "linear-gradient(90deg, #00d4ff, #00d4ff88)"
                            : "#2ecc71",
                      }}
                      initial={{ scaleX: 0 }}
                      animate={{ scaleX: 1 }}
                      transition={{ duration: 0.5 }}
                    />
                  )}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
