"""Integration tests for the Best-of-N Coder flow.

Real git worktrees + real change application + mocked LLM and test runner.
The worktree machinery is the part most likely to regress silently, so
we deliberately let it run for real against a tmp_path fixture repo.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from git import Repo

from agent.nodes.coder import coder_node

# --- Fixtures -------------------------------------------------------------


@pytest.fixture
def repo_workspace(tmp_path: Path) -> str:
    """A tiny git repo used as the Coder's main workspace."""
    repo_path = tmp_path / "workspace"
    repo_path.mkdir()
    repo = Repo.init(repo_path)
    with repo.config_writer() as cw:
        cw.set_value("user", "name", "Test")
        cw.set_value("user", "email", "test@example.com")
    (repo_path / "src.py").write_text("def existing(): return 1\n")
    repo.index.add(["src.py"])
    repo.index.commit("initial")
    return str(repo_path)


def _state(workspace: str) -> dict:
    """Minimal AgentState for coder_node."""
    return {
        "workspace_path": workspace,
        "implementation_plan": "Add `new_file.py` with a hello function",
        "review_feedback": "",
        "test_results": {},
        "baseline_test_failures": [],
        "task_id": "test",
        "retry_count": 0,
    }


def _rewrite_json(path: str, content: str) -> str:
    """Format an LLM response the parser expects (JSON array of ops)."""
    return json.dumps([{"action": "rewrite", "file_path": path, "content": content}])


# --- K=1 fast path --------------------------------------------------------

async def test_coder_k1_applies_change_directly(repo_workspace, monkeypatch):
    """K=1 skips worktrees entirely and mutates the main workspace directly."""
    monkeypatch.setattr("app.config.settings.coder_bon_k", 1)

    call_count = {"n": 0}

    async def _fake_chat(**kwargs):
        call_count["n"] += 1
        return _rewrite_json("new_file.py", "def hello(): return 42\n")
    monkeypatch.setattr("llm.provider.llm.chat", _fake_chat)

    result = await coder_node(_state(repo_workspace))

    assert result["status"].value == "testing"
    assert len(result["code_changes"]) == 1
    assert (Path(repo_workspace) / "new_file.py").read_text() == "def hello(): return 42\n"
    assert call_count["n"] == 1, "K=1 must make exactly ONE LLM call"


# --- K=3 Best-of-N: happy path -------------------------------------------

async def test_coder_k3_generates_three_candidates_and_applies_one(
    repo_workspace, monkeypatch
):
    monkeypatch.setattr("app.config.settings.coder_bon_k", 3)
    monkeypatch.setattr("app.config.settings.coder_bon_temperatures_csv", "0.1,0.5,0.9")

    call_count = {"n": 0}

    async def _fake_chat(**kwargs):
        idx = call_count["n"]
        call_count["n"] += 1
        return _rewrite_json(f"cand_{idx}.py", f"def c{idx}(): pass\n")
    monkeypatch.setattr("llm.provider.llm.chat", _fake_chat)

    async def _fake_run(workspace, **kwargs):
        return {"passed": True, "output": "", "exit_code": 0}
    monkeypatch.setattr("agent.nodes.coder.run_tests", _fake_run)

    await coder_node(_state(repo_workspace))

    assert call_count["n"] == 3, "K=3 must make three LLM calls"
    cand_files = list(Path(repo_workspace).glob("cand_*.py"))
    assert len(cand_files) == 1, f"Exactly one winner should reach main, got {cand_files}"


# --- K=N: winner selection semantics -------------------------------------

async def test_coder_k2_prefers_candidate_without_new_failures(
    repo_workspace, monkeypatch
):
    """One candidate breaks a test, one is clean. Clean one wins even if it
    would lose the deterministic tiebreak."""
    monkeypatch.setattr("app.config.settings.coder_bon_k", 2)
    monkeypatch.setattr("app.config.settings.coder_bon_temperatures_csv", "0.1,0.5")

    call_count = {"n": 0}

    async def _fake_chat(**kwargs):
        idx = call_count["n"]
        call_count["n"] += 1
        if idx == 0:
            return _rewrite_json("bad.py", "def bad(): pass\n")
        return _rewrite_json("good.py", "def good(): pass\n")
    monkeypatch.setattr("llm.provider.llm.chat", _fake_chat)

    async def _fake_run(workspace, **kwargs):
        # Identify which candidate this worktree belongs to by its files
        files = [p.name for p in Path(workspace).iterdir() if p.is_file()]
        if "bad.py" in files:
            return {"passed": False, "output": "tests/test.py::test_x FAILED", "exit_code": 1}
        return {"passed": True, "output": "", "exit_code": 0}
    monkeypatch.setattr("agent.nodes.coder.run_tests", _fake_run)

    await coder_node(_state(repo_workspace))

    assert (Path(repo_workspace) / "good.py").exists(), "clean candidate should win"
    assert not (Path(repo_workspace) / "bad.py").exists(), "losing candidate must not touch main"


# --- K=N: failure modes --------------------------------------------------

async def test_coder_k3_all_candidates_fail_to_parse_returns_empty(
    repo_workspace, monkeypatch
):
    monkeypatch.setattr("app.config.settings.coder_bon_k", 3)

    async def _fake_chat(**kwargs):
        return "this response is not JSON at all"
    monkeypatch.setattr("llm.provider.llm.chat", _fake_chat)

    async def _fake_run(**kwargs):
        return {"passed": True, "output": "", "exit_code": 0}
    monkeypatch.setattr("agent.nodes.coder.run_tests", _fake_run)

    result = await coder_node(_state(repo_workspace))
    assert result["code_changes"] == []


async def test_coder_k3_one_candidate_llm_errors_others_still_used(
    repo_workspace, monkeypatch
):
    """Simulated 429 on candidate #1 - candidates 0 and 2 still complete."""
    monkeypatch.setattr("app.config.settings.coder_bon_k", 3)

    call_count = {"n": 0}

    async def _fake_chat(**kwargs):
        idx = call_count["n"]
        call_count["n"] += 1
        if idx == 1:
            raise RuntimeError("simulated rate limit (429)")
        return _rewrite_json(f"survived_{idx}.py", f"x = {idx}\n")
    monkeypatch.setattr("llm.provider.llm.chat", _fake_chat)

    async def _fake_run(**kwargs):
        return {"passed": True, "output": "", "exit_code": 0}
    monkeypatch.setattr("agent.nodes.coder.run_tests", _fake_run)

    await coder_node(_state(repo_workspace))

    assert call_count["n"] == 3, "All three LLM calls should have been attempted"
    survived = list(Path(repo_workspace).glob("survived_*.py"))
    assert len(survived) == 1, f"Exactly one winner should reach main, got {survived}"


# --- Worktree hygiene ----------------------------------------------------

async def test_coder_k3_cleans_up_all_worktrees_afterwards(
    repo_workspace, monkeypatch
):
    """No sibling `*-wt-*` directories should remain once Coder returns."""
    monkeypatch.setattr("app.config.settings.coder_bon_k", 3)

    async def _fake_chat(**kwargs):
        return _rewrite_json("out.py", "x = 1\n")
    monkeypatch.setattr("llm.provider.llm.chat", _fake_chat)

    async def _fake_run(**kwargs):
        return {"passed": True, "output": "", "exit_code": 0}
    monkeypatch.setattr("agent.nodes.coder.run_tests", _fake_run)

    parent = Path(repo_workspace).parent
    workspace_name = Path(repo_workspace).name

    await coder_node(_state(repo_workspace))

    leftover = [p for p in parent.iterdir() if p.name.startswith(f"{workspace_name}-wt-")]
    assert leftover == [], f"Leftover worktrees on disk: {leftover}"

    # Same for scratch branches on the main repo
    main = Repo(repo_workspace)
    stray_branches = [b.name for b in main.branches if b.name.startswith("agent/candidate-")]
    assert stray_branches == [], f"Leftover scratch branches: {stray_branches}"
