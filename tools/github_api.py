"""GitHub API wrapper — issues, pull requests, comments via PyGithub."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from github import Github, GithubException

from app.config import settings

logger = logging.getLogger(__name__)


class GitHubAPI:
    """Wrapper around PyGithub for GitHub operations.

    Requires a Personal Access Token with repo, issues, and pull_requests permissions.
    """

    def __init__(self) -> None:
        if not settings.has_github:
            logger.warning("GITHUB_TOKEN not set — GitHub API will not be available.")
            self._gh = None
            return
        self._gh = Github(settings.github_token)

    @property
    def available(self) -> bool:
        return self._gh is not None

    async def get_issue(self, repo_full_name: str, issue_number: int) -> dict[str, Any]:
        """Fetch details of a GitHub issue.

        Args:
            repo_full_name: "owner/repo" format.
            issue_number: Issue number.

        Returns:
            Dict with issue title, body, labels, comments.
        """
        if not self._gh:
            return {"error": "GitHub API not configured"}

        try:
            repo = await asyncio.to_thread(self._gh.get_repo, repo_full_name)
            issue = await asyncio.to_thread(repo.get_issue, issue_number)

            comments = []
            for comment in await asyncio.to_thread(lambda: list(issue.get_comments())):
                comments.append({
                    "user": comment.user.login,
                    "body": comment.body,
                    "created_at": comment.created_at.isoformat(),
                })

            return {
                "number": issue.number,
                "title": issue.title,
                "body": issue.body or "",
                "state": issue.state,
                "labels": [label.name for label in issue.labels],
                "assignees": [a.login for a in issue.assignees],
                "comments": comments,
                "url": issue.html_url,
            }
        except GithubException as e:
            return {"error": f"GitHub API error: {e}"}

    async def create_pull_request(
        self,
        repo_full_name: str,
        title: str,
        body: str,
        head: str,
        base: str = "main",
    ) -> dict[str, Any]:
        """Create a pull request.

        Args:
            repo_full_name: "owner/repo" format.
            title: PR title.
            body: PR description (markdown).
            head: Source branch name.
            base: Target branch (defaults to "main").

        Returns:
            Dict with PR URL and number.
        """
        if not self._gh:
            return {"error": "GitHub API not configured"}

        try:
            repo = await asyncio.to_thread(self._gh.get_repo, repo_full_name)
            pr = await asyncio.to_thread(
                repo.create_pull, title=title, body=body, head=head, base=base
            )
            logger.info(f"Created PR #{pr.number}: {title}")
            return {
                "number": pr.number,
                "url": pr.html_url,
                "title": title,
                "head": head,
                "base": base,
            }
        except GithubException as e:
            return {"error": f"Failed to create PR: {e}"}

    async def post_comment(
        self,
        repo_full_name: str,
        issue_number: int,
        body: str,
    ) -> dict[str, Any]:
        """Post a comment on an issue or PR.

        Args:
            repo_full_name: "owner/repo" format.
            issue_number: Issue/PR number.
            body: Comment body (markdown).

        Returns:
            Dict with comment ID and URL.
        """
        if not self._gh:
            return {"error": "GitHub API not configured"}

        try:
            repo = await asyncio.to_thread(self._gh.get_repo, repo_full_name)
            issue = await asyncio.to_thread(repo.get_issue, issue_number)
            comment = await asyncio.to_thread(issue.create_comment, body)
            return {"id": comment.id, "url": comment.html_url}
        except GithubException as e:
            return {"error": f"Failed to post comment: {e}"}

    async def add_labels(
        self,
        repo_full_name: str,
        issue_number: int,
        labels: list[str],
    ) -> dict[str, Any]:
        """Add labels to an issue or PR.

        Args:
            repo_full_name: "owner/repo" format.
            issue_number: Issue/PR number.
            labels: List of label names to add.

        Returns:
            Dict with updated labels.
        """
        if not self._gh:
            return {"error": "GitHub API not configured"}

        try:
            repo = await asyncio.to_thread(self._gh.get_repo, repo_full_name)
            issue = await asyncio.to_thread(repo.get_issue, issue_number)
            for label in labels:
                await asyncio.to_thread(issue.add_to_labels, label)
            return {"labels": labels, "status": "added"}
        except GithubException as e:
            return {"error": f"Failed to add labels: {e}"}

    async def get_repo_info(self, repo_full_name: str) -> dict[str, Any]:
        """Get basic information about a repository.

        Args:
            repo_full_name: "owner/repo" format.

        Returns:
            Dict with repo metadata.
        """
        if not self._gh:
            return {"error": "GitHub API not configured"}

        try:
            repo = await asyncio.to_thread(self._gh.get_repo, repo_full_name)
            return {
                "full_name": repo.full_name,
                "description": repo.description,
                "default_branch": repo.default_branch,
                "language": repo.language,
                "clone_url": repo.clone_url,
                "topics": repo.get_topics(),
            }
        except GithubException as e:
            return {"error": f"GitHub API error: {e}"}


# Module-level singleton
github_api = GitHubAPI()


# Tool definitions for LLM function calling
GITHUB_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "get_issue",
            "description": "Fetch details of a GitHub issue including title, body, labels, and comments.",
            "parameters": {
                "type": "object",
                "properties": {
                    "repo_full_name": {"type": "string", "description": "Repository in 'owner/repo' format"},
                    "issue_number": {"type": "integer", "description": "Issue number"},
                },
                "required": ["repo_full_name", "issue_number"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_pull_request",
            "description": "Create a pull request in a GitHub repository.",
            "parameters": {
                "type": "object",
                "properties": {
                    "repo_full_name": {"type": "string", "description": "Repository in 'owner/repo' format"},
                    "title": {"type": "string", "description": "PR title"},
                    "body": {"type": "string", "description": "PR description (markdown)"},
                    "head": {"type": "string", "description": "Source branch name"},
                    "base": {"type": "string", "description": "Target branch (default: main)"},
                },
                "required": ["repo_full_name", "title", "body", "head"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "post_comment",
            "description": "Post a comment on a GitHub issue or pull request.",
            "parameters": {
                "type": "object",
                "properties": {
                    "repo_full_name": {"type": "string", "description": "Repository in 'owner/repo' format"},
                    "issue_number": {"type": "integer", "description": "Issue/PR number"},
                    "body": {"type": "string", "description": "Comment body (markdown)"},
                },
                "required": ["repo_full_name", "issue_number", "body"],
            },
        },
    },
]
