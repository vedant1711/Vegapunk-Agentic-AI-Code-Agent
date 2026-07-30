"""Tests for git worktree helpers in tools/git_ops.py.

Worktrees are the primitive underneath Best-of-N: each candidate diff runs
in its own worktree so the K parallel candidates don't race on the shared
index / working tree.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from git import Repo

from tools.git_ops import create_worktree, remove_worktree


@pytest.fixture
def bare_repo(tmp_path: Path) -> str:
    """A minimal repo with one commit so `git worktree add` can succeed."""
    repo_path = tmp_path / "main_repo"
    repo_path.mkdir()
    repo = Repo.init(repo_path)
    # Author config so commits don't error on CI runners without git config.
    with repo.config_writer() as cw:
        cw.set_value("user", "name", "Test")
        cw.set_value("user", "email", "test@example.com")
    (repo_path / "README.md").write_text("hello\n")
    repo.index.add(["README.md"])
    repo.index.commit("initial")
    return str(repo_path)


async def test_create_worktree_returns_path_and_branch(bare_repo):
    result = await create_worktree(bare_repo)
    try:
        assert "error" not in result, result
        assert Path(result["worktree_path"]).is_dir()
        assert result["branch"].startswith("agent/candidate-")
    finally:
        await remove_worktree(bare_repo, result["worktree_path"], result.get("branch"))


async def test_create_worktree_honours_explicit_branch_name(bare_repo):
    result = await create_worktree(bare_repo, "test-branch-explicit")
    try:
        assert result["branch"] == "test-branch-explicit"
    finally:
        await remove_worktree(bare_repo, result["worktree_path"], "test-branch-explicit")


async def test_worktree_is_independent_of_main_repo(bare_repo):
    """Files written in the worktree must not appear in the main clone."""
    result = await create_worktree(bare_repo)
    try:
        wt = Path(result["worktree_path"])
        (wt / "candidate_file.py").write_text("x = 1\n")
        assert (wt / "candidate_file.py").exists()
        assert not (Path(bare_repo) / "candidate_file.py").exists()
    finally:
        await remove_worktree(bare_repo, result["worktree_path"], result["branch"])


async def test_remove_worktree_deletes_dir_and_branch(bare_repo):
    result = await create_worktree(bare_repo)
    wt = result["worktree_path"]
    branch = result["branch"]
    assert Path(wt).exists()

    rm = await remove_worktree(bare_repo, wt, branch)
    assert "error" not in rm, rm
    assert rm["status"] == "removed"
    assert not Path(wt).exists()

    remaining = [h.name for h in Repo(bare_repo).branches]
    assert branch not in remaining


async def test_remove_worktree_survives_uncommitted_changes(bare_repo):
    """--force lets us clean up even if the candidate produced a dirty tree."""
    result = await create_worktree(bare_repo)
    wt = Path(result["worktree_path"])
    (wt / "dirty.py").write_text("uncommitted candidate output\n")
    rm = await remove_worktree(bare_repo, str(wt), result["branch"])
    assert "error" not in rm, rm


async def test_multiple_worktrees_have_unique_paths_and_branches(bare_repo):
    """Best-of-N with K=3 must not have any pair of candidates collide."""
    results = []
    try:
        for _ in range(3):
            results.append(await create_worktree(bare_repo))
        assert all("error" not in r for r in results)
        assert len({r["branch"] for r in results}) == 3
        assert len({r["worktree_path"] for r in results}) == 3
    finally:
        for r in results:
            if "worktree_path" in r:
                await remove_worktree(bare_repo, r["worktree_path"], r.get("branch"))


async def test_create_worktree_on_missing_repo_returns_error(tmp_path):
    result = await create_worktree(str(tmp_path / "does-not-exist"))
    assert "error" in result


async def test_remove_nonexistent_worktree_returns_error(bare_repo, tmp_path):
    result = await remove_worktree(bare_repo, str(tmp_path / "never-existed"))
    assert "error" in result
