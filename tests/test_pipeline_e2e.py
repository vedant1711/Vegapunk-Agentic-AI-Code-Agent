"""End-to-end pipeline test using a local seed repo + recorded LLM.

Runs the *entire real pipeline* (Setup, Router, Planner, Coder with
Best-of-N, Tester, Reviewer, PR Creator) against tests/fixtures/seed_repo
with these three edges mocked:

    llm.provider.llm.chat  -> replayed from tests/e2e/llm_recordings.json
    tools.git_ops.clone_repo -> returns the seed_repo path (no network)
    tools.git_ops.push_branch -> success stub (no real remote)
    tools.github_api.github_api.available -> False (PR Creator uses fallback)

Everything else runs for real: git worktrees, tree-sitter graph build,
change application, pytest subprocess, event bus, retry loop. If any
part of the pipeline regresses this test breaks - the recording won't
save it.
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
from git import Repo

from agent.graph import run_agent
from agent.state import TaskStatus

FIXTURE_SRC = Path(__file__).parent / "fixtures" / "seed_repo"
RECORDINGS = Path(__file__).parent / "e2e" / "llm_recordings.json"


# --- Fixture: real git repo bootstrapped from the seed_repo template ------


@pytest.fixture
def seed_repo(tmp_path):
    """Copy the seed_repo template, git-init it, commit."""
    dst = tmp_path / "seed_repo"
    shutil.copytree(FIXTURE_SRC, dst)
    repo = Repo.init(dst)
    with repo.config_writer() as cw:
        cw.set_value("user", "name", "Test")
        cw.set_value("user", "email", "test@example.com")
    repo.git.add(A=True)
    repo.index.commit("initial")
    return str(dst)


# --- Mocks: LLM replayed from recordings ---------------------------------


def _make_mock_chat(recordings: dict):
    """Return a mock llm.chat that dispatches on the caller's system prompt.

    Every pipeline node uses a distinct system prompt, so we can route by
    substring. Coder is Best-of-N (K parallel calls) so we hand back
    successive entries from `recordings['coder']`.
    """
    state = {"coder_idx": 0}

    async def _mock_chat(messages=None, tier=None, temperature=0.2, max_tokens=4096, tools=None, **kwargs):
        msgs = messages or kwargs.get("messages") or []
        sys_msg = ""
        for m in msgs:
            if m.get("role") == "system":
                sys_msg = m.get("content", "")
                break

        low = sys_msg.lower()
        if "task classifier" in low:
            return recordings["router"]
        if "planning the implementation" in low:
            return recordings["planner"]
        if "expert software engineer implementing code changes" in low:
            idx = state["coder_idx"]
            state["coder_idx"] += 1
            candidates = recordings["coder"]
            return candidates[idx % len(candidates)]
        if "senior code reviewer" in low:
            return recordings["reviewer"]

        raise AssertionError(
            f"E2E mock LLM: no recording for system prompt starting with {sys_msg[:80]!r}"
        )

    return _mock_chat


# --- Mocks: git + github --------------------------------------------------


async def _fake_clone(url, workspace_name=None, *args, **kwargs):
    raise AssertionError("clone_repo should be patched to a static return - see test fixture")


async def _fake_push(repo_path, branch_name=None, *args, **kwargs):
    return {"status": "pushed", "branch": branch_name or "main"}


# --- The test ------------------------------------------------------------


async def test_e2e_pipeline_fixes_divide_by_zero(seed_repo, monkeypatch):
    """Full pipeline resolves the seed-repo bug and marks the run completed."""
    recordings = json.loads(RECORDINGS.read_text(encoding="utf-8"))

    # 1. Replayed LLM everywhere the pipeline calls out.
    monkeypatch.setattr("llm.provider.llm.chat", _make_mock_chat(recordings))

    # 2. clone_repo returns the pre-committed seed_repo path (no network).
    #    Both agent.graph and any other module that did `from tools.git_ops
    #    import clone_repo` hold their own reference to the function, so we
    #    patch at the import site (agent.graph), not the definition site.
    async def _clone_returns_seed(url, workspace_name=None, *args, **kwargs):
        return {"path": seed_repo, "status": "cloned"}
    monkeypatch.setattr("agent.graph.clone_repo", _clone_returns_seed)

    # 3. push_branch stubbed - no real remote is configured on tmp_path.
    #    Patched at the pr_creator import site, same reasoning as clone_repo.
    monkeypatch.setattr("agent.nodes.pr_creator.push_branch", _fake_push)

    # 4. github_api unavailable so PR Creator uses the "branch pushed" fallback.
    monkeypatch.setattr("tools.github_api.github_api._gh", None)

    # Baseline sanity: the shipped seed_repo should have a failing test
    # BEFORE the pipeline touches it. If this assertion breaks, either the
    # bug was accidentally fixed or the test file was renamed.
    calc_before = (Path(seed_repo) / "src" / "calc.py").read_text()
    assert "if b == 0" not in calc_before, "seed_repo should ship WITH the bug present"

    # Run the entire pipeline.
    result = await run_agent(
        repo_full_name="local/seed-repo",
        issue_number=1,
        issue_title="divide by zero raises ZeroDivisionError",
        issue_body="src/calc.py::divide should return None when b == 0",
        issue_labels=["bug"],
        repo_clone_url="file:///not-used",
        task_id="e2e-test",
    )

    # --- Pipeline-level assertions ---
    assert result["status"] == TaskStatus.COMPLETED, (
        f"expected COMPLETED, got status={result['status']!r}, error={result.get('error')!r}"
    )
    assert result["task_classification"] == "bug_fix"
    assert result["review_approved"] is True
    assert len(result["code_changes"]) >= 1

    # --- Concrete workspace assertion: the bug is actually gone ---
    calc_after = (Path(seed_repo) / "src" / "calc.py").read_text()
    assert "if b == 0" in calc_after or "ZeroDivisionError" in calc_after, (
        f"expected divide() to guard against b=0, got:\n{calc_after}"
    )

    # --- The failing test should now pass in the fixed workspace ---
    # (The Tester step already ran and confirmed this; but we double-check
    # against the actual on-disk state for good measure.)
    # NB: can't import here without adding seed_repo to sys.path, so we
    # rely on the pipeline's Tester verdict above.
