"""York (PR Creator) node — commits, pushes, and creates a GitHub pull request."""

from __future__ import annotations

import logging
from typing import Any

from agent.state import AgentState, TaskStatus
from tools.git_ops import commit_changes, push_branch
from tools.github_api import github_api

logger = logging.getLogger(__name__)


async def pr_creator_node(state: AgentState) -> dict[str, Any]:
    """Create a git commit, push the branch, and open a pull request.

    Reads: workspace_path, branch_name, repo_full_name, pr_title, pr_body
    Writes: pr_url, status, current_step
    """
    workspace = state.get("workspace_path", "")
    branch = state.get("branch_name", "")
    repo_name = state.get("repo_full_name", "")

    logger.info(f"🎯 York (PR Creator): Committing and pushing to {branch}")

    # Step 1: Commit all changes
    issue_num = state.get("issue_number", "")
    commit_msg = f"fix(#{issue_num}): {state.get('issue_title', 'Issue fix')}\n\nAutomated by Vegapunk 🏴\u200d☠️"

    commit_result = await commit_changes(workspace, commit_msg)
    if "error" in commit_result:
        return {
            "status": TaskStatus.FAILED,
            "error": f"Commit failed: {commit_result['error']}",
            "current_step": "Failed to commit changes",
        }

    logger.info(f"🎯 York (PR Creator): Committed {commit_result.get('sha', '?')[:8]}")

    # Step 2: Push the branch
    push_result = await push_branch(workspace, branch)
    if "error" in push_result:
        return {
            "status": TaskStatus.FAILED,
            "error": f"Push failed: {push_result['error']}",
            "current_step": "Failed to push branch",
        }

    logger.info(f"🎯 York (PR Creator): Pushed branch {branch}")

    # Step 3: Create the pull request
    pr_title = state.get("pr_title", f"Fix #{issue_num}: {state.get('issue_title', '')}")
    pr_body = state.get("pr_body", f"Resolves #{issue_num}")

    if github_api.available:
        pr_result = await github_api.create_pull_request(
            repo_full_name=repo_name,
            title=pr_title,
            body=pr_body,
            head=branch,
            base="main",
        )

        if "error" in pr_result:
            return {
                "status": TaskStatus.FAILED,
                "error": f"PR creation failed: {pr_result['error']}",
                "current_step": "Failed to create pull request",
            }

        pr_url = pr_result.get("url", "")
        logger.info(f"🎯 York (PR Creator): Created PR → {pr_url}")

        # Post a comment on the original issue
        await github_api.post_comment(
            repo_full_name=repo_name,
            issue_number=issue_num,
            body=f"🏴‍☠️ Vegapunk has created a pull request to address this issue: {pr_url}\n\nPlease review the changes.",
        )

        return {
            "pr_url": pr_url,
            "status": TaskStatus.COMPLETED,
            "current_step": f"✅ PR created: {pr_url}",
            "messages": [
                {"role": "assistant", "content": f"✅ Pull request created: {pr_url}"}
            ],
        }
    else:
        logger.warning("GitHub API not configured — skipping PR creation")
        return {
            "pr_url": f"Branch '{branch}' pushed — create PR manually",
            "status": TaskStatus.COMPLETED,
            "current_step": f"Branch '{branch}' pushed. Create PR manually on GitHub.",
            "messages": [
                {"role": "assistant", "content": f"Branch '{branch}' pushed. Create the PR manually."}
            ],
        }
