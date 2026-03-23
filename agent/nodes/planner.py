"""Edison (Planner) node — analyzes the issue and creates an implementation plan."""

from __future__ import annotations

import logging
from typing import Any

from agent.state import AgentState, TaskStatus
from llm.provider import llm, ModelTier
from tools.code_search import get_file_structure, find_relevant_files
from tools.github_api import github_api
from app.events import event_bus

logger = logging.getLogger(__name__)

PLANNER_SYSTEM_PROMPT = """You are a senior software engineer planning the implementation for a GitHub issue. You have access to the repository structure and can search for relevant code.

Your job is to create a clear, actionable implementation plan that a coder agent can follow.

Your plan should include:
1. **Analysis** — What the issue is asking for, root cause (for bugs), or scope (for features)
2. **Files to modify** — List specific files that need changes
3. **Changes per file** — Describe exactly what needs to change in each file
4. **New files** — Any new files that need to be created
5. **Testing approach** — How to verify the changes work
6. **Potential risks** — Edge cases or things that could go wrong

Be specific and precise. Reference actual file paths, function names, and line numbers where possible.
Format your plan in markdown."""


async def planner_node(state: AgentState) -> dict[str, Any]:
    """Analyze the codebase and create an implementation plan.

    Reads: workspace_path, issue_title, issue_body, task_classification
    Writes: implementation_plan, status, current_step
    """
    workspace = state.get("workspace_path", "")
    task_id = state.get("task_id", "")
    logger.info(f"💡 Edison (Planner): Starting analysis for {state.get('issue_title', '?')}")
    event_bus.emit(task_id, "Edison (Planner)", f"Analyzing: {state.get('issue_title', '?')}", "info")

    # Step 1: Get repository structure
    structure = await get_file_structure(workspace)
    tree = structure.get("tree", "Unable to read structure")

    # Step 2: Search for relevant files based on issue keywords
    keywords = _extract_keywords(state.get("issue_title", ""), state.get("issue_body", ""))
    relevant_files = []
    for keyword in keywords[:5]:  # Search top 5 keywords
        results = await find_relevant_files(workspace, keyword)
        if "files" in results:
            relevant_files.extend(results["files"])

    # Deduplicate
    seen_paths = set()
    unique_files = []
    for f in relevant_files:
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
{relevant_context or 'No specific files found — search the codebase for more context.'}

---

Create a detailed implementation plan.""",
        },
    ]

    plan = await llm.chat(messages=messages, tier=ModelTier.HEAVY, temperature=0.2, max_tokens=4096)

    logger.info(f"💡 Edison (Planner): Plan created ({len(plan)} chars)")
    event_bus.emit(task_id, "Edison (Planner)", f"Plan created ({len(plan)} chars)", "success")

    return {
        "implementation_plan": plan,
        "status": TaskStatus.CODING,
        "current_step": "Plan created — starting code implementation",
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
    seen = set()
    unique = []
    for kw in keywords:
        lower = kw.lower()
        if lower not in seen:
            seen.add(lower)
            unique.append(kw)

    return unique[:10]
