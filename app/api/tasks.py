"""Task API - manual task triggers and status queries."""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from pathlib import Path
from typing import Any

from fastapi import APIRouter, BackgroundTasks
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from agent.graph import run_agent
from app.events import event_bus

# Where the pre-recorded demo transcript lives (repo-root/demo/transcript.json).
_DEMO_TRANSCRIPT_PATH = Path(__file__).resolve().parent.parent.parent / "demo" / "transcript.json"

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/tasks", tags=["tasks"])

# In-memory task store (replace with DB in production)
_tasks: dict[str, dict[str, Any]] = {}


class TaskRequest(BaseModel):
    """Request body for manually triggering the agent."""
    repo_full_name: str        # "owner/repo"
    issue_number: int          # GitHub issue number
    issue_title: str           # Issue title
    issue_body: str = ""       # Issue description
    issue_labels: list[str] = []  # Issue labels


class TaskFromURL(BaseModel):
    """Trigger agent from a GitHub issue URL."""
    issue_url: str  # e.g. "https://github.com/owner/repo/issues/42"


async def _run_task(task_id: str, request: TaskRequest) -> None:
    """Background task to run the agent."""
    _tasks[task_id]["status"] = "running"
    started = time.time()
    event_bus.emit(
        task_id,
        "System",
        f"Task {task_id} started for {request.repo_full_name}#{request.issue_number}",
        "info",
    )

    try:
        result = await run_agent(
            repo_full_name=request.repo_full_name,
            issue_number=request.issue_number,
            issue_title=request.issue_title,
            issue_body=request.issue_body,
            issue_labels=request.issue_labels,
            task_id=task_id,
        )
        _tasks[task_id].update({
            "status": str(result.get("status", "unknown")),
            "pr_url": result.get("pr_url", ""),
            "error": result.get("error", ""),
            "result": {
                "classification": result.get("task_classification", ""),
                "plan_length": len(result.get("implementation_plan", "")),
                "changes_count": len(result.get("code_changes", [])),
                "tests_passed": result.get("test_results", {}).get("passed", False),
                "review_approved": result.get("review_approved", False),
            },
        })
        pr_url = result.get("pr_url", "")
        event_bus.run_end(
            task_id,
            f"Run finished. PR: {pr_url}" if pr_url else "Run finished.",
            level="success",
            duration_seconds=time.time() - started,
        )
    except Exception as e:
        _tasks[task_id].update({"status": "failed", "error": str(e)})
        event_bus.run_end(
            task_id,
            f"Task failed: {e}",
            level="error",
            duration_seconds=time.time() - started,
        )
        logger.error(f"Task {task_id} failed: {e}", exc_info=True)


@router.post("/")
async def create_task(request: TaskRequest, background_tasks: BackgroundTasks):
    """Create a new agent task."""
    task_id = str(uuid.uuid4())[:8]
    _tasks[task_id] = {
        "id": task_id,
        "status": "queued",
        "repo": request.repo_full_name,
        "issue": request.issue_number,
        "pr_url": "",
        "error": "",
    }

    background_tasks.add_task(_run_task, task_id, request)
    logger.info(f"[tasks] Task {task_id} created for {request.repo_full_name}#{request.issue_number}")

    return {"task_id": task_id, "status": "queued"}


@router.post("/from-url")
async def create_task_from_url(request: TaskFromURL, background_tasks: BackgroundTasks):
    """Create a task from a GitHub issue URL."""
    import re

    match = re.match(r"https://github\.com/([^/]+/[^/]+)/issues/(\d+)", request.issue_url)
    if not match:
        return {"error": "Invalid GitHub issue URL format"}

    repo_full_name = match.group(1)
    issue_number = int(match.group(2))

    # Fetch issue details from GitHub API
    from tools.github_api import github_api

    if github_api.available:
        issue_data = await github_api.get_issue(repo_full_name, issue_number)
        if "error" in issue_data:
            return {"error": issue_data["error"]}

        task_request = TaskRequest(
            repo_full_name=repo_full_name,
            issue_number=issue_number,
            issue_title=issue_data.get("title", ""),
            issue_body=issue_data.get("body", ""),
            issue_labels=issue_data.get("labels", []),
        )
    else:
        task_request = TaskRequest(
            repo_full_name=repo_full_name,
            issue_number=issue_number,
            issue_title=f"Issue #{issue_number}",
        )

    return await create_task(task_request, background_tasks)


# --- Demo mode ------------------------------------------------------------
# Replays a pre-recorded transcript over the same SSE channel that real
# runs use. Lets portfolio reviewers see the trace UI animate without
# needing NVIDIA / Gemini / GitHub credentials or burning free-tier quota.


async def _run_demo(task_id: str) -> None:
    """Replay demo/transcript.json into the event bus with realistic timing."""
    _tasks[task_id]["status"] = "running"
    try:
        transcript = json.loads(_DEMO_TRANSCRIPT_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        logger.error(f"[demo] Transcript unavailable at {_DEMO_TRANSCRIPT_PATH}: {e}")
        event_bus.run_end(task_id, f"Demo transcript unavailable: {e}", level="error")
        _tasks[task_id]["status"] = "failed"
        _tasks[task_id]["error"] = str(e)
        return

    pr_url = ""
    for entry in transcript:
        await asyncio.sleep(max(0, int(entry.get("delay_ms", 0))) / 1000)
        etype = entry.get("type", "log")
        step = entry.get("step", "System")

        if etype == "step_start":
            event_bus.step_start(task_id, step)
        elif etype == "step_end":
            event_bus.step_end(
                task_id,
                step,
                entry.get("status", "success"),
                (entry.get("duration_ms") or 0) / 1000,
            )
        elif etype == "run_end":
            msg = entry.get("message", "Run finished.")
            if "http" in msg:
                # Extract PR URL if the run_end message carries one
                import re as _re
                m = _re.search(r"https?://\S+", msg)
                if m:
                    pr_url = m.group(0)
            event_bus.run_end(
                task_id,
                msg,
                level=entry.get("level", "success"),
                duration_seconds=(entry.get("duration_ms") or 0) / 1000,
            )
        else:
            event_bus.emit(
                task_id,
                step,
                entry.get("message", ""),
                entry.get("level", "info"),
            )

    _tasks[task_id].update({
        "status": "completed",
        "pr_url": pr_url,
    })


@router.post("/demo")
async def create_demo_task(background_tasks: BackgroundTasks):
    """Kick off a pre-recorded demo run.

    Same task/SSE contract as a real run, so the frontend needs no special
    casing - it just connects to /api/tasks/{id}/events and watches.
    """
    task_id = "demo-" + uuid.uuid4().hex[:6]
    _tasks[task_id] = {
        "id": task_id,
        "status": "queued",
        "repo": "octocat/timezone-lib",
        "issue": 42,
        "pr_url": "",
        "error": "",
        "demo": True,
    }
    background_tasks.add_task(_run_demo, task_id)
    logger.info(f"[tasks] Demo task {task_id} created")
    return {"task_id": task_id, "status": "queued", "demo": True}


@router.get("/{task_id}")
async def get_task(task_id: str):
    """Get the status of a running task."""
    if task_id not in _tasks:
        return {"error": "Task not found"}
    return _tasks[task_id]


@router.get("/{task_id}/events")
async def stream_events(task_id: str):
    """Stream real-time events for a task via Server-Sent Events."""

    async def event_generator():
        async for event in event_bus.subscribe(task_id):
            if event.message == "keepalive":
                yield ": keepalive\n\n"
                continue
            data = json.dumps({
                "timestamp": event.timestamp,
                "step": event.step,
                "message": event.message,
                "level": event.level,
                "event_type": event.event_type,
                "duration_ms": event.duration_ms,
                "step_status": event.step_status,
            })
            yield f"data: {data}\n\n"
            if event.event_type == "run_end":
                break

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/")
async def list_tasks():
    """List all tasks."""
    return {"tasks": list(_tasks.values())}
