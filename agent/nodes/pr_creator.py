"""PR Creator node - commits, pushes, and opens a GitHub pull request."""

from __future__ import annotations

import logging
import time
from typing import Any

from agent.state import AgentState, TaskStatus
from app.events import event_bus
from tools.git_ops import commit_changes, push_branch
from tools.github_api import github_api

logger = logging.getLogger(__name__)

STEP_NAME = "PR Creator"


async def pr_creator_node(state: AgentState) -> dict[str, Any]:
    """Create a git commit, push the branch, and open a pull request.

    Reads: workspace_path, branch_name, repo_full_name, pr_title, pr_body
    Writes: pr_url, status, current_step
    """
    workspace = state.get("workspace_path", "")
    branch = state.get("branch_name", "")
    repo_name = state.get("repo_full_name", "")
    task_id = state.get("task_id", "")
    started = time.time()

    logger.info(f"[PR Creator] Committing and pushing to {branch}")
    event_bus.step_start(task_id, STEP_NAME)
    event_bus.emit(task_id, STEP_NAME, f"Committing to {branch}", "info")

    # Step 1: Commit all changes
    issue_num = state.get("issue_number", "")
    commit_msg = f"fix(#{issue_num}): {state.get('issue_title', 'Issue fix')}\n\nAutomated by Vegapunk."

    commit_result = await commit_changes(workspace, commit_msg)
    if "error" in commit_result:
        event_bus.step_end(task_id, STEP_NAME, "error", time.time() - started)
        return {
            "status": TaskStatus.FAILED,
            "error": f"Commit failed: {commit_result['error']}",
            "current_step": "Failed to commit changes",
        }

    logger.info(f"[PR Creator] Committed {commit_result.get('sha', '?')[:8]}")

    # Step 2: Push the branch
    push_result = await push_branch(workspace, branch)
    if "error" in push_result:
        event_bus.step_end(task_id, STEP_NAME, "error", time.time() - started)
        return {
            "status": TaskStatus.FAILED,
            "error": f"Push failed: {push_result['error']}",
            "current_step": "Failed to push branch",
        }

    logger.info(f"[PR Creator] Pushed branch {branch}")

    # Step 3: Create the pull request
    pr_title = state.get("pr_title", f"Fix #{issue_num}: {state.get('issue_title', '')}")
    pr_body = state.get("pr_body", f"Resolves #{issue_num}")

    if github_api.available:
        # Detect the repo's default branch instead of hard-coding "main"
        default_branch = "main"
        repo_info = await github_api.get_repo_info(repo_name)
        if "error" not in repo_info:
            default_branch = repo_info.get("default_branch") or "main"

        pr_result = await github_api.create_pull_request(
            repo_full_name=repo_name,
            title=pr_title,
            body=pr_body,
            head=branch,
            base=default_branch,
        )

        if "error" in pr_result:
            event_bus.step_end(task_id, STEP_NAME, "error", time.time() - started)
            return {
                "status": TaskStatus.FAILED,
                "error": f"PR creation failed: {pr_result['error']}",
                "current_step": "Failed to create pull request",
            }

        pr_url = pr_result.get("url", "")
        logger.info(f"[PR Creator] Created PR: {pr_url}")
        event_bus.emit(task_id, STEP_NAME, f"PR created: {pr_url}", "success")
        event_bus.step_end(task_id, STEP_NAME, "success", time.time() - started)

        # Post a comment on the original issue
        await github_api.post_comment(
            repo_full_name=repo_name,
            issue_number=issue_num,
            body=f"Vegapunk has created a pull request to address this issue: {pr_url}\n\nPlease review the changes.",
        )

        return {
            "pr_url": pr_url,
            "status": TaskStatus.COMPLETED,
            "current_step": f"PR created: {pr_url}",
            "messages": [
                {"role": "assistant", "content": f"Pull request created: {pr_url}"}
            ],
        }
    else:
        logger.warning("[PR Creator] GitHub API not configured - skipping PR creation")
        event_bus.step_end(task_id, STEP_NAME, "warning", time.time() - started)
        return {
            "pr_url": f"Branch '{branch}' pushed - create PR manually",
            "status": TaskStatus.COMPLETED,
            "current_step": f"Branch '{branch}' pushed. Create PR manually on GitHub.",
            "messages": [
                {"role": "assistant", "content": f"Branch '{branch}' pushed. Create the PR manually."}
            ],
        }
