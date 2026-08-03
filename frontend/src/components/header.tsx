"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

type RunStatus = "idle" | "queued" | "running" | "completed" | "failed";

interface HeaderProps {
  /** Only shown on pages that host a run (i.e. the dashboard). */
  runStatus?: RunStatus;
}

function statusColor(status: RunStatus): string {
  return status === "running"
    ? "var(--running)"
    : status === "completed"
      ? "var(--success)"
      : status === "failed"
        ? "var(--error)"
        : "var(--border-strong)";
}

export default function Header({ runStatus }: HeaderProps) {
  const pathname = usePathname();

  const navLink = (href: string, label: string) => {
    const active = pathname === href;
    return (
      <Link
        href={href}
        className={`text-xs transition-colors ${
          active
            ? "text-[var(--text)]"
            : "text-[var(--text-muted)] hover:text-[var(--text)]"
        }`}
      >
        {label}
      </Link>
    );
  };

  return (
    <header className="border-b border-[var(--border)] sticky top-0 z-10 bg-[var(--bg)]/90 backdrop-blur">
      <div className="max-w-5xl mx-auto px-6 py-4 flex items-center justify-between gap-4">
        <Link href="/" className="flex items-baseline gap-3 min-w-0">
          <h1 className="text-lg font-semibold tracking-tight">Vegapunk</h1>
          <span className="text-xs text-[var(--text-muted)] truncate">
            Autonomous Coding Agent
          </span>
        </Link>

        <nav className="flex items-center gap-4 flex-shrink-0">
          {navLink("/", "Dashboard")}
          {navLink("/architecture", "Architecture")}
          <a
            href="https://github.com/vedant1711/Vegapunk-Agentic-AI-Code-Agent"
            target="_blank"
            rel="noopener noreferrer"
            className="text-xs text-[var(--text-muted)] hover:text-[var(--text)] transition-colors"
          >
            GitHub
          </a>
          {runStatus !== undefined && (
            <div className="flex items-center gap-2 pl-3 border-l border-[var(--border)]">
              <span
                className="status-dot"
                style={{
                  background: statusColor(runStatus),
                  boxShadow:
                    runStatus === "running"
                      ? `0 0 8px ${statusColor(runStatus)}`
                      : "none",
                }}
              />
              <span className="text-xs text-[var(--text-muted)] capitalize">
                {runStatus}
              </span>
            </div>
          )}
        </nav>
      </div>
    </header>
  );
}
