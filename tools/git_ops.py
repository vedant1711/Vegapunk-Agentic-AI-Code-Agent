"""Git operations - clone, branch, commit, push, worktree via GitPython."""

from __future__ import annotations

import asyncio
import logging
import uuid
from pathlib import Path
from typing import Any

from git import Repo
from git.exc import GitCommandError

from app.config import settings

logger = logging.getLogger(__name__)


async def clone_repo(repo_url: str, workspace_name: str | None = None) -> dict[str, Any]:
    """Clone a GitHub repository into the workspace directory.

    Args:
        repo_url: HTTPS URL of the repository.
        workspace_name: Optional subfolder name (defaults to repo name).

    Returns:
        Dict with 'path' to the cloned repo.
    """
    if not workspace_name:
        workspace_name = repo_url.rstrip("/").split("/")[-1].replace(".git", "")

    clone_path = settings.workspace_path / workspace_name

    if clone_path.exists():
        logger.info(f"Repo already exists at {clone_path}, pulling latest...")
        try:
            repo = Repo(str(clone_path))
            origin = repo.remotes.origin
            await asyncio.to_thread(origin.pull)
            return {"path": str(clone_path), "status": "updated"}
        except Exception as e:
            return {"error": f"Failed to pull existing repo: {e}"}

    try:
        # Inject token for private repos
        auth_url = repo_url
        if settings.has_github and "github.com" in repo_url:
            auth_url = repo_url.replace(
                "https://", f"https://x-access-token:{settings.github_token}@"
            )

        logger.info(f"Cloning {repo_url} → {clone_path}")
        await asyncio.to_thread(Repo.clone_from, auth_url, str(clone_path))
        return {"path": str(clone_path), "status": "cloned"}
    except GitCommandError as e:
        return {"error": f"Clone failed: {e}"}


async def create_branch(repo_path: str, branch_name: str) -> dict[str, Any]:
    """Create and checkout a new branch.

    Args:
        repo_path: Path to the local repository.
        branch_name: Name of the new branch.

    Returns:
        Dict with 'branch' name.
    """
    try:
        repo = Repo(repo_path)
        # Create branch from current HEAD
        new_branch = repo.create_head(branch_name)
        new_branch.checkout()
        logger.info(f"Created and checked out branch: {branch_name}")
        return {"branch": branch_name, "status": "created"}
    except Exception as e:
        return {"error": f"Failed to create branch: {e}"}


async def commit_changes(
    repo_path: str,
    message: str,
    files: list[str] | None = None,
) -> dict[str, Any]:
    """Stage and commit changes.

    Args:
        repo_path: Path to the local repository.
        message: Commit message.
        files: Optional list of specific files to stage. Stages all if None.

    Returns:
        Dict with commit details.
    """
    try:
        repo = Repo(repo_path)

        if files:
            repo.index.add(files)
        else:
            repo.git.add(A=True)

        if not repo.index.diff("HEAD") and not repo.untracked_files:
            return {"status": "nothing_to_commit"}

        commit = repo.index.commit(message)
        logger.info(f"Committed: {commit.hexsha[:8]} — {message}")
        return {
            "status": "committed",
            "sha": commit.hexsha,
            "message": message,
            "files_changed": len(commit.stats.files),
        }
    except Exception as e:
        return {"error": f"Commit failed: {e}"}


async def push_branch(repo_path: str, branch_name: str | None = None) -> dict[str, Any]:
    """Push the current branch to origin.

    Args:
        repo_path: Path to the local repository.
        branch_name: Branch to push (defaults to current branch).

    Returns:
        Dict with push status.
    """
    try:
        repo = Repo(repo_path)
        branch = branch_name or repo.active_branch.name
        origin = repo.remotes.origin

        # Set upstream and push
        await asyncio.to_thread(
            origin.push, refspec=f"{branch}:{branch}", set_upstream=True
        )
        logger.info(f"Pushed branch: {branch}")
        return {"status": "pushed", "branch": branch}
    except Exception as e:
        return {"error": f"Push failed: {e}"}


async def get_diff(repo_path: str) -> dict[str, Any]:
    """Get the current diff of uncommitted changes.

    Args:
        repo_path: Path to the local repository.

    Returns:
        Dict with 'diff' string.
    """
    try:
        repo = Repo(repo_path)
        diff = repo.git.diff()
        staged_diff = repo.git.diff("--staged")
        full_diff = f"{diff}\n{staged_diff}".strip()
        return {"diff": full_diff, "has_changes": bool(full_diff)}
    except Exception as e:
        return {"error": f"Failed to get diff: {e}"}


# --- Worktrees (used by best-of-N candidate generation) ----------------------


async def create_worktree(
    repo_path: str,
    branch_name: str | None = None,
) -> dict[str, Any]:
    """Create a git worktree with a fresh scratch branch.

    Best-of-N generates K candidate diffs and needs each candidate to apply
    changes independently, so we can't share the main repo's working tree
    or its index. `git worktree add -b <branch> <path>` creates the branch
    AND checks it out into a new worktree atomically.

    Args:
        repo_path: Path to the main repository.
        branch_name: Optional explicit branch name. If None, generates
            `agent/candidate-<8-hex>` which is guaranteed unique.

    Returns:
        Dict with 'worktree_path' and 'branch'. On error: {'error': str}.
    """
    try:
        if not Path(repo_path).is_dir():
            return {"error": f"Repo path is not a directory: {repo_path}"}
        repo = Repo(repo_path)

        if branch_name is None:
            branch_name = f"agent/candidate-{uuid.uuid4().hex[:8]}"

        # Worktree lives beside the main clone, not inside it.
        parent = Path(repo_path).resolve().parent
        wt_name = f"{Path(repo_path).name}-wt-{uuid.uuid4().hex[:8]}"
        wt_path = parent / wt_name

        await asyncio.to_thread(
            repo.git.worktree, "add", "-b", branch_name, str(wt_path)
        )
        logger.info(f"[worktree] Created {wt_path} on branch {branch_name}")
        return {"worktree_path": str(wt_path), "branch": branch_name}
    except Exception as e:
        return {"error": f"Failed to create worktree: {e}"}


async def remove_worktree(
    repo_path: str,
    worktree_path: str,
    branch_name: str | None = None,
) -> dict[str, Any]:
    """Remove a git worktree and optionally delete its scratch branch.

    Uses --force so a dirty worktree (with uncommitted candidate changes)
    still gets removed on the cleanup path. Missing branches during delete
    are logged at debug level, not raised - the caller has already used
    the candidate's result.

    Args:
        repo_path: Path to the main repository that owns the worktree.
        worktree_path: Absolute path of the worktree to remove.
        branch_name: If provided, force-delete this branch after removal.

    Returns:
        Dict with 'status' or 'error'.
    """
    try:
        repo = Repo(repo_path)
        await asyncio.to_thread(
            repo.git.worktree, "remove", "--force", worktree_path
        )
        if branch_name:
            try:
                await asyncio.to_thread(repo.git.branch, "-D", branch_name)
            except Exception as e:
                logger.debug(f"[worktree] Branch delete skipped: {e}")
        logger.info(f"[worktree] Removed {worktree_path}")
        return {"status": "removed", "path": worktree_path}
    except Exception as e:
        return {"error": f"Failed to remove worktree: {e}"}


# Tool definitions for LLM function calling
GIT_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "clone_repo",
            "description": "Clone a GitHub repository into the workspace.",
            "parameters": {
                "type": "object",
                "properties": {
                    "repo_url": {"type": "string", "description": "HTTPS URL of the repository"},
                },
                "required": ["repo_url"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_branch",
            "description": "Create and checkout a new git branch.",
            "parameters": {
                "type": "object",
                "properties": {
                    "repo_path": {"type": "string", "description": "Path to the local repository"},
                    "branch_name": {"type": "string", "description": "Name for the new branch"},
                },
                "required": ["repo_path", "branch_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "commit_changes",
            "description": "Stage and commit all current changes.",
            "parameters": {
                "type": "object",
                "properties": {
                    "repo_path": {"type": "string", "description": "Path to the local repository"},
                    "message": {"type": "string", "description": "Commit message"},
                },
                "required": ["repo_path", "message"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "push_branch",
            "description": "Push the current branch to the remote origin.",
            "parameters": {
                "type": "object",
                "properties": {
                    "repo_path": {"type": "string", "description": "Path to the local repository"},
                },
                "required": ["repo_path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_diff",
            "description": "Get the diff of uncommitted changes in the repo.",
            "parameters": {
                "type": "object",
                "properties": {
                    "repo_path": {"type": "string", "description": "Path to the local repository"},
                },
                "required": ["repo_path"],
            },
        },
    },
]
