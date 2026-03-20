"""GitHub webhook handler — receives events and triggers the agent."""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
from typing import Any

from fastapi import APIRouter, Request, HTTPException, BackgroundTasks

from app.config import settings
from agent.graph import run_agent

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/webhooks", tags=["webhooks"])


def _verify_signature(payload: bytes, signature: str) -> bool:
    """Verify GitHub webhook signature (HMAC-SHA256)."""
    if not settings.github_webhook_secret:
        return True  # Skip verification if no secret configured

    expected = hmac.new(
        settings.github_webhook_secret.encode(),
        payload,
        hashlib.sha256,
    ).hexdigest()

    return hmac.compare_digest(f"sha256={expected}", signature)


async def _process_issue(payload: dict[str, Any]) -> None:
    """Background task: process a GitHub issue with the agent."""
    issue = payload.get("issue", {})
    repo = payload.get("repository", {})

    result = await run_agent(
        repo_full_name=repo.get("full_name", ""),
        issue_number=issue.get("number", 0),
        issue_title=issue.get("title", ""),
        issue_body=issue.get("body", ""),
        issue_labels=[label.get("name", "") for label in issue.get("labels", [])],
        repo_clone_url=repo.get("clone_url", ""),
    )

    logger.info(
        f"Agent completed: status={result.get('status')}, "
        f"pr_url={result.get('pr_url', 'N/A')}"
    )


@router.post("/github")
async def github_webhook(request: Request, background_tasks: BackgroundTasks):
    """Receive GitHub webhook events.

    Listens for:
    - issues.opened — Auto-triggered when a new issue is created
    - issues.labeled — Triggered when a specific label (e.g. "agent") is added
    - issue_comment.created — Triggered when someone comments "/agent" on an issue
    """
    payload = await request.body()

    # Verify webhook signature
    signature = request.headers.get("X-Hub-Signature-256", "")
    if not _verify_signature(payload, signature):
        raise HTTPException(status_code=401, detail="Invalid webhook signature")

    event = request.headers.get("X-GitHub-Event", "")
    data = json.loads(payload)

    logger.info(f"🔔 Webhook received: event={event}, action={data.get('action', '?')}")

    # Handle issue events
    if event == "issues" and data.get("action") in ("opened", "labeled"):
        issue = data.get("issue", {})
        labels = [l.get("name", "") for l in issue.get("labels", [])]

        # Only auto-trigger for issues with "agent" label, or if configured to trigger on all
        if "agent" in labels or data.get("action") == "opened":
            background_tasks.add_task(_process_issue, data)
            return {
                "status": "accepted",
                "message": f"Agent triggered for issue #{issue.get('number')}",
            }

    # Handle issue comment events (trigger via "/agent" command)
    if event == "issue_comment" and data.get("action") == "created":
        comment_body = data.get("comment", {}).get("body", "")
        if comment_body.strip().lower().startswith("/agent"):
            background_tasks.add_task(_process_issue, data)
            return {
                "status": "accepted",
                "message": "Agent triggered via comment command",
            }

    return {"status": "ignored", "event": event}
