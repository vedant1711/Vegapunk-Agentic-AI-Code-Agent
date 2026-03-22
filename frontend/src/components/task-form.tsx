"use client";

import { useState } from "react";
import { motion } from "framer-motion";

interface TaskFormProps {
  onSubmit: (issueUrl: string) => void;
  isRunning: boolean;
}

export default function TaskForm({ onSubmit, isRunning }: TaskFormProps) {
  const [url, setUrl] = useState("");

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (url.trim() && !isRunning) {
      onSubmit(url.trim());
    }
  };

  return (
    <div className="card-glow p-5">
      <h2 className="text-sm font-semibold text-gray-400 uppercase tracking-wider mb-4">
        🏴‍☠️ Submit Issue
      </h2>

      <form onSubmit={handleSubmit} className="flex gap-3">
        <input
          type="url"
          value={url}
          onChange={(e) => setUrl(e.target.value)}
          placeholder="https://github.com/owner/repo/issues/1"
          disabled={isRunning}
          className="flex-1 bg-white/5 border border-white/10 rounded-xl px-4 py-3 text-sm text-white
            placeholder-gray-600 focus:outline-none focus:border-[#f5c542]/50 focus:ring-1 focus:ring-[#f5c542]/30
            transition-all duration-300 disabled:opacity-50 font-mono"
        />
        <motion.button
          type="submit"
          disabled={isRunning || !url.trim()}
          whileHover={{ scale: 1.02 }}
          whileTap={{ scale: 0.98 }}
          className="px-6 py-3 rounded-xl font-semibold text-sm
            bg-gradient-to-r from-[#f5c542] to-[#e67e22] text-black
            hover:shadow-[0_0_20px_rgba(245,197,66,0.3)] transition-all duration-300
            disabled:opacity-40 disabled:cursor-not-allowed"
        >
          {isRunning ? (
            <span className="flex items-center gap-2">
              <span className="w-4 h-4 border-2 border-black/30 border-t-black rounded-full animate-spin" />
              Running...
            </span>
          ) : (
            "Deploy Satellites 🚀"
          )}
        </motion.button>
      </form>
    </div>
  );
}
