"""Task API — manual task triggers and status queries."""

from __future__ import annotations

import json
import logging
import uuid
from typing import Any

from fastapi import APIRouter, BackgroundTasks
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from agent.graph import run_agent
from app.events import event_bus

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
    event_bus.emit(task_id, "System", f"Task {task_id} started for {request.repo_full_name}#{request.issue_number}", "info")

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
        event_bus.emit(task_id, "System", f"🏁 Vegapunk finished — PR: {pr_url}", "success")
    except Exception as e:
        _tasks[task_id].update({"status": "failed", "error": str(e)})
        event_bus.emit(task_id, "System", f"❌ Task failed: {e}", "error")
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
    logger.info(f"📝 Task {task_id} created for {request.repo_full_name}#{request.issue_number}")

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
                yield f": keepalive\n\n"
                continue
            data = json.dumps({
                "timestamp": event.timestamp,
                "satellite": event.satellite,
                "message": event.message,
                "level": event.level,
            })
            yield f"data: {data}\n\n"
            if "finished" in event.message.lower() or event.message.startswith("❌ Task failed"):
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

