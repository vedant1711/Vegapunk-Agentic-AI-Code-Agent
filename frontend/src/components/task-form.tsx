"use client";

import { useState } from "react";

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
    <form onSubmit={handleSubmit} className="panel p-4 flex gap-2">
      <input
        type="url"
        value={url}
        onChange={(e) => setUrl(e.target.value)}
        placeholder="https://github.com/owner/repo/issues/1"
        disabled={isRunning}
        className="mono flex-1 bg-transparent border border-[var(--border)] rounded-md px-3 py-2 text-sm
          text-[var(--text)] placeholder:text-[var(--text-subtle)]
          focus:outline-none focus:border-[var(--accent)]
          disabled:opacity-50"
      />
      <button
        type="submit"
        disabled={isRunning || !url.trim()}
        className="px-4 py-2 rounded-md text-sm font-medium bg-[var(--accent)] text-white
          hover:opacity-90 transition-opacity
          disabled:opacity-40 disabled:cursor-not-allowed"
      >
        {isRunning ? "Running..." : "Run agent"}
      </button>
    </form>
  );
}
