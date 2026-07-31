"""Coder node - implements changes based on the plan, optionally via Best-of-N.

Two execution modes:

  * K = 1 (fast path) - single LLM call, apply changes directly to the main
    workspace. Same behavior as pre-Best-of-N Vegapunk.

  * K > 1 (Best-of-N) - K parallel LLM calls at varied temperatures. Each
    candidate is applied to a fresh git worktree and its test suite runs
    independently. The candidate with the fewest NEW test failures (vs
    baseline) wins and is re-applied to the main workspace. Rooted in the
    DeepSWE / ACECoder line of research on execution-verified rewards.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import time
from pathlib import Path
from typing import Any

from agent.state import AgentState, TaskStatus
from app.config import settings
from app.events import event_bus
from llm.provider import ModelTier, llm
from tools.best_of_n import (
    CandidateResult,
    new_failures_against,
    select_best_candidate,
)
from tools.filesystem import read_file, write_file
from tools.git_ops import create_worktree, get_diff, remove_worktree
from tools.test_runner import run_tests

logger = logging.getLogger(__name__)

STEP_NAME = "Coder"

# Files at or under this line count are rewritten wholesale; larger files
# use line-number-based edits so we don't blow the token budget rewriting
# 2000-line modules to fix a 3-line bug.
SMALL_FILE_THRESHOLD = 150

CODER_SYSTEM_PROMPT = """You are an expert software engineer implementing code changes.

You will be given:
1. An implementation plan
2. File contents WITH LINE NUMBERS
3. Any previous feedback

Respond with ONLY a JSON array. For each file, use ONE of these strategies:

**For small files or major changes - REWRITE the whole file:**
```
{"action": "rewrite", "file_path": "src/file.py", "content": "complete new file content"}
```

**For surgical changes to specific lines - use LINE-BASED EDIT:**
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
- Line numbers are shown as "L1:", "L2:", etc. - reference those exact numbers
- Preserve indentation from the original file
- Output ONLY the JSON array, nothing else
"""


# --- Public entry point ---------------------------------------------------


async def coder_node(state: AgentState) -> dict[str, Any]:
    """Implement code changes based on the plan.

    Chooses between the single-shot fast path (K=1) and Best-of-N based on
    `settings.coder_bon_k`. See module docstring for the rationale.
    """
    workspace = state.get("workspace_path", "")
    plan = state.get("implementation_plan", "")
    review_feedback = state.get("review_feedback", "")
    test_results = state.get("test_results", {})
    baseline_failures = state.get("baseline_test_failures", [])
    task_id = state.get("task_id", "")
    started = time.time()

    logger.info(f"[Coder] Implementing changes (retry #{state.get('retry_count', 0)})")
    event_bus.step_start(task_id, STEP_NAME)
    event_bus.emit(
        task_id,
        STEP_NAME,
        f"Implementing changes (retry #{state.get('retry_count', 0)})",
        "info",
    )

    file_contents = await _read_relevant_files(workspace, plan)
    context = _build_context(plan, file_contents, review_feedback, test_results)

    k = max(1, int(settings.coder_bon_k))
    temperatures = _resolve_temperatures(k)

    if k == 1:
        applied_changes = await _single_shot(workspace, context, temperatures[0], task_id)
    else:
        event_bus.emit(
            task_id, STEP_NAME,
            f"Best-of-N: generating {k} candidates in parallel (temps={temperatures})",
            "info",
        )
        applied_changes = await _best_of_n(
            workspace=workspace,
            context=context,
            temperatures=temperatures,
            baseline_failures=baseline_failures,
            task_id=task_id,
        )

    event_bus.step_end(task_id, STEP_NAME, "success", time.time() - started)

    return {
        "code_changes": applied_changes,
        "status": TaskStatus.TESTING,
        "current_step": f"Applied {len(applied_changes)} changes - running tests",
        "messages": [{"role": "assistant", "content": f"Applied {len(applied_changes)} code changes."}],
    }


# --- Prompt context -------------------------------------------------------


def _build_context(
    plan: str,
    file_contents: dict[str, str],
    review_feedback: str,
    test_results: dict[str, Any],
) -> str:
    """Assemble the LLM user-message context (shared across all candidates)."""
    parts = [f"**Implementation Plan:**\n{plan}"]

    if file_contents:
        parts.append("\n**Files (with line numbers):**")
        for fpath, content in file_contents.items():
            lines = content.splitlines()
            numbered = "\n".join(f"L{i+1}: {line}" for i, line in enumerate(lines))
            size_note = "SMALL" if len(lines) <= SMALL_FILE_THRESHOLD else f"LARGE ({len(lines)} lines)"
            parts.append(f"\n`{fpath}` [{size_note}]:\n```\n{numbered}\n```")

    if review_feedback:
        parts.append(f"\n**Reviewer Feedback:**\n{review_feedback}")

    if test_results and not test_results.get("passed", True):
        parts.append(
            f"\n**Test Failures:**\n```\n{test_results.get('output', '')[:2000]}\n```"
        )

    return "\n\n".join(parts)


def _resolve_temperatures(k: int) -> list[float]:
    """Parse `coder_bon_temperatures_csv` and pad/truncate to exactly K values."""
    raw = [t.strip() for t in settings.coder_bon_temperatures_csv.split(",") if t.strip()]
    temps: list[float] = []
    for t in raw:
        try:
            temps.append(float(t))
        except ValueError:
            logger.warning(f"[Coder] Bad temperature value in config: {t!r}; skipping")
    if not temps:
        temps = [0.1]
    if len(temps) < k:
        # Pad by repeating the last value so we always have K temperatures.
        temps = temps + [temps[-1]] * (k - len(temps))
    return temps[:k]


# --- Single-shot (K=1) fast path -----------------------------------------


async def _single_shot(
    workspace: str,
    context: str,
    temperature: float,
    task_id: str,
) -> list[dict[str, Any]]:
    """Generate one candidate and apply directly to the main workspace."""
    response = await llm.chat(
        messages=[
            {"role": "system", "content": CODER_SYSTEM_PROMPT},
            {"role": "user", "content": f"{context}\n\nImplement the changes now. JSON array only."},
        ],
        tier=ModelTier.HEAVY,
        temperature=temperature,
        max_tokens=8192,
    )
    changes = _parse_changes(response)
    if not changes:
        logger.warning(f"[Coder] No valid changes parsed. Raw:\n{response[:500]}")
        return []

    applied: list[dict[str, Any]] = []
    for change in changes:
        result = await _apply_change(workspace, change)
        applied.append({**change, "result": result})
        ok = result.get("success", False)
        outcome = "ok" if ok else f"error: {result.get('error', '')}"
        logger.info(f"[Coder] {change.get('action','?')} {change.get('file_path','?')}: {outcome}")
        event_bus.emit(
            task_id, STEP_NAME,
            f"{change.get('action','?')} {change.get('file_path','?')}: {outcome}",
            "success" if ok else "error",
        )
    return applied


# --- Best-of-N orchestrator ----------------------------------------------


async def _best_of_n(
    workspace: str,
    context: str,
    temperatures: list[float],
    baseline_failures: list[str],
    task_id: str,
) -> list[dict[str, Any]]:
    """Fan out K candidates, evaluate in worktrees, apply winner to main."""
    max_par = max(1, min(len(temperatures), int(settings.coder_bon_max_parallel)))
    sem = asyncio.Semaphore(max_par)

    async def _one(index: int, temp: float) -> CandidateResult:
        async with sem:
            return await _evaluate_candidate(
                workspace=workspace,
                context=context,
                index=index,
                temperature=temp,
                baseline_failures=baseline_failures,
                task_id=task_id,
            )

    candidates = await asyncio.gather(
        *(_one(i, t) for i, t in enumerate(temperatures)),
        return_exceptions=False,
    )

    if not any(c.parsed for c in candidates):
        # All K failed to parse or errored. Nothing to apply.
        event_bus.emit(task_id, STEP_NAME, "Best-of-N: no candidate produced valid changes", "error")
        return []

    winner = select_best_candidate(candidates)
    event_bus.emit(
        task_id, STEP_NAME,
        (
            f"Best-of-N selected candidate {winner.candidate_index} "
            f"(temp={winner.temperature}, "
            f"new_failures={len(winner.new_failures)}, "
            f"diff_lines={winner.diff_size}, "
            f"applied={winner.changes_applied})"
        ),
        "success",
    )

    # Re-apply winner's changes to the MAIN workspace. Change ops are
    # deterministic so this is idempotent with the worktree apply.
    applied: list[dict[str, Any]] = []
    for change in winner.changes:
        result = await _apply_change(workspace, change)
        applied.append({**change, "result": result})
    return applied


async def _evaluate_candidate(
    workspace: str,
    context: str,
    index: int,
    temperature: float,
    baseline_failures: list[str],
    task_id: str,
) -> CandidateResult:
    """Generate, apply-in-worktree, and test one Best-of-N candidate."""
    cand_started = time.time()
    event_bus.emit(task_id, STEP_NAME, f"Candidate {index}: generating (temp={temperature})", "info")

    # 1. LLM call
    try:
        response = await asyncio.wait_for(
            llm.chat(
                messages=[
                    {"role": "system", "content": CODER_SYSTEM_PROMPT},
                    {"role": "user", "content": f"{context}\n\nImplement the changes now. JSON array only."},
                ],
                tier=ModelTier.HEAVY,
                temperature=temperature,
                max_tokens=8192,
            ),
            timeout=int(settings.coder_bon_timeout_seconds),
        )
    except TimeoutError as e:  # asyncio.TimeoutError == TimeoutError in 3.11+
        logger.warning(f"[Coder] Candidate {index} LLM timed out: {e}")
        event_bus.emit(task_id, STEP_NAME, f"Candidate {index}: LLM timeout", "warning")
        return CandidateResult(
            candidate_index=index, temperature=temperature, parsed=False,
            error="timeout", wall_time_ms=(time.time() - cand_started) * 1000,
        )
    except Exception as e:
        logger.warning(f"[Coder] Candidate {index} LLM failed: {e}")
        event_bus.emit(task_id, STEP_NAME, f"Candidate {index}: LLM error - {e}", "warning")
        return CandidateResult(
            candidate_index=index, temperature=temperature, parsed=False,
            error=str(e), wall_time_ms=(time.time() - cand_started) * 1000,
        )

    # 2. Parse
    changes = _parse_changes(response)
    if not changes:
        event_bus.emit(task_id, STEP_NAME, f"Candidate {index}: LLM output did not parse", "warning")
        return CandidateResult(
            candidate_index=index, temperature=temperature, parsed=False,
            wall_time_ms=(time.time() - cand_started) * 1000,
        )

    # 3. Fresh worktree
    wt_info = await create_worktree(workspace)
    if "error" in wt_info:
        return CandidateResult(
            candidate_index=index, temperature=temperature, parsed=True,
            changes=changes, error=wt_info["error"],
            wall_time_ms=(time.time() - cand_started) * 1000,
        )
    wt_path = wt_info["worktree_path"]
    branch = wt_info["branch"]

    try:
        # 4. Apply changes to the worktree
        applied_ok = 0
        applied_fail = 0
        for change in changes:
            r = await _apply_change(wt_path, change)
            if r.get("success"):
                applied_ok += 1
            else:
                applied_fail += 1

        # 5. Measure diff size (added + removed lines, excluding headers)
        diff_size = 0
        try:
            diff_result = await get_diff(wt_path)
            for line in diff_result.get("diff", "").splitlines():
                if not line:
                    continue
                if line.startswith(("+++", "---")):
                    continue
                if line[0] in ("+", "-"):
                    diff_size += 1
        except Exception as e:
            logger.debug(f"[Coder] Candidate {index}: diff measurement failed: {e}")

        # 6. Run tests in the worktree
        new_failures: list[str] = []
        tests_ran = False
        try:
            test_result = await run_tests(wt_path)
            tests_ran = True
            new_failures = new_failures_against(
                test_result.get("output", ""), baseline_failures
            )
        except Exception as e:
            logger.warning(f"[Coder] Candidate {index}: test run failed: {e}")

        event_bus.emit(
            task_id, STEP_NAME,
            (
                f"Candidate {index}: applied {applied_ok}/{applied_ok+applied_fail} ops, "
                f"diff={diff_size} lines, new_failures={len(new_failures)}"
            ),
            "warning" if new_failures else "success",
        )

        return CandidateResult(
            candidate_index=index,
            temperature=temperature,
            parsed=True,
            changes=changes,
            changes_applied=applied_ok,
            changes_failed=applied_fail,
            diff_size=diff_size,
            new_failures=new_failures,
            tests_ran=tests_ran,
            wall_time_ms=(time.time() - cand_started) * 1000,
        )
    finally:
        await remove_worktree(workspace, wt_path, branch)


# --- File reading --------------------------------------------------------

async def _read_relevant_files(workspace: str, plan: str) -> dict[str, str]:
    """Extract file paths from the plan, expand via repo graph, read contents.

    The plan (written by the Planner LLM) usually names specific files. We
    also want their immediate neighbors in the reference graph so the Coder
    can see callers/callees when reasoning about a change.
    """
    contents: dict[str, str] = {}

    path_patterns = [
        r"`([a-zA-Z0-9_/\-\.]+\.[a-zA-Z]{1,5})`",
        r"(?:^|\s)((?:src|tests|lib|app|utils)/[a-zA-Z0-9_/\-\.]+\.[a-zA-Z]{1,5})",
    ]

    found_paths: set[str] = set()
    for pattern in path_patterns:
        found_paths.update(re.findall(pattern, plan))

    # Expand via repo-graph neighborhood so we include files that import or
    # are imported by the ones the plan explicitly mentions. Best-effort.
    try:
        from tools.repo_graph import get_or_build_graph
        graph = await get_or_build_graph(workspace)
        if graph.stats.files_parsed > 0 and found_paths:
            expanded = set(found_paths)
            for path in list(found_paths):
                expanded.update(graph.file_neighborhood(path, radius=1))
            found_paths = expanded
    except Exception as e:
        logger.debug(f"[Coder] Graph expansion skipped: {e}")

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
                logger.info(f"[Coder] Read {fpath} ({result.get('total_lines', '?')} lines)")

    return contents


# --- Response parsing ----------------------------------------------------

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

        valid = {"rewrite", "create", "line_edit", "delete"}
        return [c for c in parsed if c.get("action") in valid and c.get("file_path")]

    except (json.JSONDecodeError, ValueError, IndexError) as e:
        logger.warning(f"Parse failed: {e}")
        return []


# --- Applying changes ----------------------------------------------------

async def _apply_change(workspace: str, change: dict[str, Any]) -> dict[str, Any]:
    """Apply a single file operation to the given workspace root."""
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

    with open(file_path, encoding="utf-8") as f:
        lines = f.readlines()

    total = len(lines)
    if start > total:
        return {"error": f"start_line {start} > file length {total}"}

    end = min(end, total)

    if new_content and not new_content.endswith("\n"):
        new_content += "\n"

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
