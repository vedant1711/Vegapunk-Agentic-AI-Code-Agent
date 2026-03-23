"""Pythagoras (Coder) node — implements changes based on the plan using tools."""

from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path
from typing import Any

from agent.state import AgentState, TaskStatus
from llm.provider import llm, ModelTier
from tools.filesystem import read_file, write_file
from app.events import event_bus

logger = logging.getLogger(__name__)

# Files under this threshold → full rewrite (most reliable, low token cost)
# Files over this threshold → line-number based edits (efficient for large files)
SMALL_FILE_THRESHOLD = 150

CODER_SYSTEM_PROMPT = """You are an expert software engineer implementing code changes.

You will be given:
1. An implementation plan
2. File contents WITH LINE NUMBERS
3. Any previous feedback

Respond with ONLY a JSON array. For each file, use ONE of these strategies:

**For small files or major changes — REWRITE the whole file:**
```
{"action": "rewrite", "file_path": "src/file.py", "content": "complete new file content"}
```

**For surgical changes to specific lines — use LINE-BASED EDIT:**
```
{"action": "line_edit", "file_path": "src/file.py", "start_line": 19, "end_line": 24, "new_content": "replacement lines here"}
```
start_line and end_line are 1-indexed and inclusive. The lines from start_line to end_line are REPLACED with new_content.

**For new files:**
```
{"action": "rewrite", "file_path": "src/new_file.py", "content": "full file content"}
```

RULES:
- Use "line_edit" for precise changes (fixing a function, adding a check)
- Use "rewrite" for small files (<100 lines) or when changing most of the file
- Line numbers are shown as "L1:", "L2:", etc. — reference those exact numbers
- Preserve indentation from the original file
- Output ONLY the JSON array, nothing else
"""


async def coder_node(state: AgentState) -> dict[str, Any]:
    """Implement code changes based on the plan.

    Uses a hybrid strategy:
    - Small files → full rewrite (most reliable)
    - Large files → line-number based edits (cost efficient)
    """
    workspace = state.get("workspace_path", "")
    plan = state.get("implementation_plan", "")
    review_feedback = state.get("review_feedback", "")
    test_results = state.get("test_results", {})

    logger.info(f"💻 Pythagoras (Coder): Implementing changes (retry #{state.get('retry_count', 0)})")
    task_id = state.get("task_id", "")
    event_bus.emit(task_id, "Pythagoras (Coder)", f"Implementing changes (retry #{state.get('retry_count', 0)})", "info")

    # Step 1: Read relevant files WITH line numbers
    file_contents = await _read_relevant_files(workspace, plan)

    # Step 2: Build prompt with numbered file contents
    context_parts = [f"**Implementation Plan:**\n{plan}"]

    if file_contents:
        context_parts.append("\n**Files (with line numbers):**")
        for fpath, content in file_contents.items():
            lines = content.splitlines()
            numbered = "\n".join(f"L{i+1}: {line}" for i, line in enumerate(lines))
            size_note = "SMALL" if len(lines) <= SMALL_FILE_THRESHOLD else f"LARGE ({len(lines)} lines)"
            context_parts.append(f"\n📄 `{fpath}` [{size_note}]:\n```\n{numbered}\n```")

    if review_feedback:
        context_parts.append(f"\n**Reviewer Feedback:**\n{review_feedback}")

    if test_results and not test_results.get("passed", True):
        context_parts.append(
            f"\n**Test Failures:**\n```\n{test_results.get('output', '')[:2000]}\n```"
        )

    context = "\n\n".join(context_parts)

    messages = [
        {"role": "system", "content": CODER_SYSTEM_PROMPT},
        {"role": "user", "content": f"{context}\n\nImplement the changes now. JSON array only."},
    ]

    response = await llm.chat(messages=messages, tier=ModelTier.HEAVY, temperature=0.1, max_tokens=8192)

    # Parse and apply
    changes = _parse_changes(response)

    if not changes:
        logger.warning(f"💻 Pythagoras (Coder): No valid changes parsed. Raw:\n{response[:500]}")

    applied_changes = []
    for change in changes:
        result = await _apply_change(workspace, change)
        applied_changes.append({**change, "result": result})
        ok = result.get("success", False)
        err = result.get("error", "")
        logger.info(f"💻 Pythagoras (Coder): {change.get('action','?')} → {change.get('file_path','?')}: {'✅' if ok else f'❌ {err}'}")
        event_bus.emit(task_id, "Pythagoras (Coder)", f"{change.get('action','?')} → {change.get('file_path','?')}: {'✅' if ok else f'❌ {err}'}", "success" if ok else "error")

    return {
        "code_changes": applied_changes,
        "status": TaskStatus.TESTING,
        "current_step": f"Applied {len(applied_changes)} changes — running tests",
        "messages": [{"role": "assistant", "content": f"Applied {len(applied_changes)} code changes."}],
    }


# --- File reading ---

async def _read_relevant_files(workspace: str, plan: str) -> dict[str, str]:
    """Extract file paths from the plan and read their contents."""
    contents = {}

    path_patterns = [
        r"`([a-zA-Z0-9_/\-\.]+\.[a-zA-Z]{1,5})`",
        r"(?:^|\s)((?:src|tests|lib|app|utils)/[a-zA-Z0-9_/\-\.]+\.[a-zA-Z]{1,5})",
    ]

    found_paths = set()
    for pattern in path_patterns:
        found_paths.update(re.findall(pattern, plan))

    if not found_paths:
        workspace_path = Path(workspace)
        if workspace_path.exists():
            for ext in ("*.py", "*.js", "*.ts"):
                for f in workspace_path.rglob(ext):
                    rel = str(f.relative_to(workspace_path))
                    if not any(s in rel for s in ("__pycache__", "node_modules", ".git", "venv")):
                        found_paths.add(rel)

    for fpath in sorted(found_paths)[:20]:
        full_path = os.path.join(workspace, fpath)
        if os.path.isfile(full_path):
            result = await read_file(full_path)
            if "content" in result and len(result["content"]) < 100000:
                contents[fpath] = result["content"]
                logger.info(f"💻 Pythagoras (Coder): Read {fpath} ({result.get('total_lines', '?')} lines)")

    return contents


# --- Response parsing ---

def _parse_changes(response: str) -> list[dict[str, Any]]:
    """Parse LLM response into file operations."""
    try:
        clean = response.strip()

        if "```json" in clean:
            start = clean.index("```json") + 7
            end = clean.index("```", start)
            clean = clean[start:end].strip()
        elif "```" in clean:
            parts = clean.split("```")
            for part in parts[1::2]:
                stripped = part.strip()
                if stripped.startswith("json"):
                    stripped = stripped[4:].strip()
                if stripped.startswith("["):
                    clean = stripped
                    break

        if clean.startswith("["):
            parsed = json.loads(clean)
        else:
            s, e = clean.find("["), clean.rfind("]")
            if s != -1 and e != -1:
                parsed = json.loads(clean[s : e + 1])
            else:
                return []

        valid = {"rewrite", "create", "line_edit", "edit", "delete"}
        return [c for c in parsed if c.get("action") in valid and c.get("file_path")]

    except (json.JSONDecodeError, ValueError, IndexError) as e:
        logger.warning(f"Parse failed: {e}")
        return []


# --- Applying changes ---

async def _apply_change(workspace: str, change: dict[str, Any]) -> dict[str, Any]:
    """Apply a single file operation."""
    action = change.get("action", "")
    file_path = change.get("file_path", "")

    if not file_path:
        return {"error": "No file_path"}

    full_path = os.path.join(workspace, file_path)

    if action in ("rewrite", "create"):
        content = change.get("content", "")
        if not content:
            return {"error": "No content for rewrite"}
        return await write_file(full_path, content)

    elif action == "line_edit":
        return await _apply_line_edit(full_path, change)

    elif action == "edit":
        # Legacy find-and-replace (fallback)
        from tools.filesystem import apply_edit
        original = change.get("original", "")
        replacement = change.get("replacement", "")
        if not original:
            return {"error": "No 'original' text"}
        return await apply_edit(full_path, original, replacement)

    elif action == "delete":
        try:
            os.remove(full_path)
            return {"success": True, "path": full_path}
        except OSError as e:
            return {"error": str(e)}

    return {"error": f"Unknown action: {action}"}


async def _apply_line_edit(file_path: str, change: dict) -> dict[str, Any]:
    """Apply a line-number based edit.

    Replaces lines [start_line, end_line] (1-indexed, inclusive) with new_content.
    """
    if not os.path.isfile(file_path):
        return {"error": f"File not found: {file_path}"}

    start = change.get("start_line", 0)
    end = change.get("end_line", 0)
    new_content = change.get("new_content", "")

    if start < 1 or end < start:
        return {"error": f"Invalid line range: {start}-{end}"}

    with open(file_path, "r", encoding="utf-8") as f:
        lines = f.readlines()

    total = len(lines)
    if start > total:
        return {"error": f"start_line {start} > file length {total}"}

    # Clamp end to file length
    end = min(end, total)

    # Ensure new_content ends with newline
    if new_content and not new_content.endswith("\n"):
        new_content += "\n"

    # Splice: keep lines before start, insert new content, keep lines after end
    new_lines = lines[: start - 1] + [new_content] + lines[end:]

    with open(file_path, "w", encoding="utf-8") as f:
        f.writelines(new_lines)

    logger.info(f"line_edit: replaced L{start}-L{end} in {os.path.basename(file_path)}")

    return {
        "success": True,
        "path": file_path,
        "lines_replaced": f"{start}-{end}",
        "match_type": "line_number",
    }
