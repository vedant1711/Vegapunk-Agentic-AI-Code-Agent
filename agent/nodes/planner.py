"""Planner node - analyzes the issue and creates an implementation plan."""

from __future__ import annotations

import logging
import time
from typing import Any

from agent.state import AgentState, TaskStatus
from app.events import event_bus
from llm.provider import ModelTier, llm
from tools.code_search import find_relevant_files, get_file_structure

logger = logging.getLogger(__name__)

STEP_NAME = "Planner"

PLANNER_SYSTEM_PROMPT = """You are a senior software engineer planning the implementation for a GitHub issue. You have access to the repository structure and can search for relevant code.

Your job is to create a clear, actionable implementation plan that a coder agent can follow.

Your plan should include:
1. **Analysis** - What the issue is asking for, root cause (for bugs), or scope (for features)
2. **Files to modify** - List specific files that need changes
3. **Changes per file** - Describe exactly what needs to change in each file
4. **New files** - Any new files that need to be created
5. **Testing approach** - How to verify the changes work
6. **Potential risks** - Edge cases or things that could go wrong

Be specific and precise. Reference actual file paths, function names, and line numbers where possible.
Format your plan in markdown."""


async def planner_node(state: AgentState) -> dict[str, Any]:
    """Analyze the codebase and create an implementation plan.

    Reads: workspace_path, issue_title, issue_body, task_classification
    Writes: implementation_plan, status, current_step
    """
    workspace = state.get("workspace_path", "")
    task_id = state.get("task_id", "")
    started = time.time()

    logger.info(f"[Planner] Starting analysis for {state.get('issue_title', '?')}")
    event_bus.step_start(task_id, STEP_NAME)
    event_bus.emit(task_id, STEP_NAME, f"Analyzing: {state.get('issue_title', '?')}", "info")

    # Step 1: Get repository structure (used for the tree overview)
    structure = await get_file_structure(workspace)
    tree = structure.get("tree", "Unable to read structure")

    # Step 2: Rank relevant files. Prefer the tree-sitter repo graph
    # (tools/repo_graph.py) - it combines keyword overlap with PageRank on
    # the file-level reference graph. Fall back to the legacy regex-based
    # find_relevant_files if the graph didn't build for any reason
    # (unsupported language, empty workspace, grammar ABI mismatch, etc.).
    relevant_context = ""
    query = f"{state.get('issue_title', '')} {state.get('issue_body', '')}"
    try:
        from tools.repo_graph import get_or_build_graph
        graph = await get_or_build_graph(workspace)
        if graph.stats.files_parsed > 0:
            matches = graph.relevant_files_for(query, limit=15)
            relevant_context = "\n".join(
                (
                    f"- `{m.path}` (score={m.combined_score:.2f}"
                    + (f"; symbols: {', '.join(m.matched_symbols[:3])}" if m.matched_symbols else "")
                    + ")"
                )
                for m in matches
            )
    except Exception as e:
        logger.warning(f"[Planner] Graph retrieval failed, falling back to legacy: {e}")

    if not relevant_context:
        keywords = _extract_keywords(state.get("issue_title", ""), state.get("issue_body", ""))
        legacy_files: list[dict[str, Any]] = []
        for keyword in keywords[:5]:
            results = await find_relevant_files(workspace, keyword)
            if "files" in results:
                legacy_files.extend(results["files"])
        seen_paths: set[str] = set()
        unique_files: list[dict[str, Any]] = []
        for f in legacy_files:
            if f["path"] not in seen_paths:
                seen_paths.add(f["path"])
                unique_files.append(f)
        relevant_context = "\n".join(
            f"- `{f['path']}` ({f['match_count']} matches)"
            for f in unique_files[:15]
        )

    # Step 3: Ask the LLM to create the plan
    messages = [
        {"role": "system", "content": PLANNER_SYSTEM_PROMPT},
        {
            "role": "user",
            "content": f"""Create an implementation plan for this issue:

**Issue #{state.get('issue_number', '?')}: {state.get('issue_title', 'No title')}**
**Type:** {state.get('task_classification', 'unknown')}

**Description:**
{state.get('issue_body', 'No description')}

---

**Repository Structure:**
```
{tree[:3000]}
```

**Relevant Files Found:**
{relevant_context or 'No specific files found - search the codebase for more context.'}

---

Create a detailed implementation plan.""",
        },
    ]

    plan = await llm.chat(messages=messages, tier=ModelTier.HEAVY, temperature=0.2, max_tokens=4096)

    logger.info(f"[Planner] Plan created ({len(plan)} chars)")
    event_bus.emit(task_id, STEP_NAME, f"Plan created ({len(plan)} chars)", "success")
    event_bus.step_end(task_id, STEP_NAME, "success", time.time() - started)

    return {
        "implementation_plan": plan,
        "status": TaskStatus.CODING,
        "current_step": "Plan created - starting code implementation",
        "messages": [{"role": "assistant", "content": f"Implementation plan:\n{plan}"}],
    }


def _extract_keywords(title: str, body: str) -> list[str]:
    """Extract search keywords from the issue title and body."""
    import re

    text = f"{title} {body}"

    # Extract code references (backtick contents)
    code_refs = re.findall(r"`([^`]+)`", text)

    # Extract common programming terms
    words = re.findall(r"\b[A-Za-z_][A-Za-z0-9_]{2,}\b", text)

    # Filter out common English stop words
    stop_words = {
        "the", "and", "for", "that", "this", "with", "from", "are", "was",
        "been", "have", "has", "had", "not", "but", "all", "can", "her",
        "his", "they", "them", "their", "would", "should", "could",
        "when", "where", "what", "which", "who", "how", "why", "there",
        "also", "some", "into", "about", "than", "then", "its", "like",
        "just", "over", "such", "after", "before", "more", "other",
    }

    keywords = code_refs + [w for w in words if w.lower() not in stop_words]

    # Deduplicate while preserving order
    seen: set[str] = set()
    unique: list[str] = []
    for kw in keywords:
        lower = kw.lower()
        if lower not in seen:
            seen.add(lower)
            unique.append(kw)

    return unique[:10]
