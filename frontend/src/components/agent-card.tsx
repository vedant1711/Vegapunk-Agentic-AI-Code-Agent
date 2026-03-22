"use client";

import { motion } from "framer-motion";
import type { Satellite } from "@/lib/types";

interface AgentCardProps {
  satellite: Satellite;
  isActive: boolean;
  index: number;
}

export default function AgentCard({ satellite, isActive, index }: AgentCardProps) {
  const statusColors = {
    idle: "bg-gray-500/20 text-gray-400",
    active: "bg-cyan-500/20 text-cyan-400",
    done: "bg-green-500/20 text-green-400",
    error: "bg-red-500/20 text-red-400",
  };

  return (
    <motion.div
      initial={{ opacity: 0, y: 30 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay: index * 0.1, duration: 0.5, ease: "easeOut" }}
      className={`card-glow p-5 flex flex-col gap-3 relative overflow-hidden ${
        isActive ? "active" : ""
      }`}
    >
      {/* Active glow background */}
      {isActive && (
        <motion.div
          className="absolute inset-0 rounded-2xl"
          style={{
            background: `radial-gradient(circle at 50% 50%, ${satellite.glowColor}, transparent 70%)`,
          }}
          animate={{ opacity: [0.3, 0.6, 0.3] }}
          transition={{ duration: 2, repeat: Infinity }}
        />
      )}

      {/* Header row */}
      <div className="flex items-center justify-between relative z-10">
        <div className="flex items-center gap-3">
          {/* Avatar circle */}
          <motion.div
            className={`w-12 h-12 rounded-full flex items-center justify-center text-xl
              ${isActive ? "satellite-active" : ""}`}
            style={{
              background: `linear-gradient(135deg, ${satellite.color}22, ${satellite.color}44)`,
              border: `2px solid ${satellite.color}66`,
              color: satellite.color,
            }}
            whileHover={{ scale: 1.1 }}
          >
            {satellite.emoji}
          </motion.div>

          {/* Name and role */}
          <div>
            <h3 className="text-sm font-bold text-white leading-tight">
              {satellite.name}{" "}
              <span className="text-xs font-normal text-gray-400">
                ({satellite.role})
              </span>
            </h3>
            <p className="text-[10px] font-mono tracking-wider" style={{ color: satellite.color }}>
              {satellite.number}
            </p>
          </div>
        </div>

        {/* Status badge */}
        <span
          className={`text-[10px] font-semibold uppercase tracking-wider px-2 py-1 rounded-full ${
            statusColors[satellite.status]
          }`}
        >
          {satellite.status}
        </span>
      </div>

      {/* Description */}
      <p className="text-xs text-gray-500 leading-relaxed relative z-10">
        {satellite.description}
      </p>

      {/* Last message */}
      {satellite.lastMessage && (
        <motion.div
          initial={{ opacity: 0, height: 0 }}
          animate={{ opacity: 1, height: "auto" }}
          className="mt-1 px-3 py-2 rounded-lg bg-white/5 border border-white/5 relative z-10"
        >
          <p className="text-[11px] font-mono text-gray-300 truncate">
            {satellite.lastMessage}
          </p>
        </motion.div>
      )}
    </motion.div>
  );
}
