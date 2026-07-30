"""Main LangGraph workflow - the coding agent pipeline."""

from __future__ import annotations

import logging
import time
from typing import Any

from langgraph.graph import END, StateGraph

from agent.nodes.coder import coder_node
from agent.nodes.planner import planner_node
from agent.nodes.pr_creator import pr_creator_node
from agent.nodes.reviewer import reviewer_node
from agent.nodes.router import router_node
from agent.nodes.tester import tester_node
from agent.state import AgentState, TaskStatus
from app.events import event_bus
from tools.git_ops import clone_repo, create_branch

logger = logging.getLogger(__name__)

STEP_NAME = "Setup"


# --- Setup Node (workspace prep, not an LLM step) ---

async def setup_node(state: AgentState) -> dict[str, Any]:
    """Clone the repo, create a working branch, and capture baseline tests.

    Reads: repo_full_name, repo_clone_url, issue_number
    Writes: workspace_path, branch_name, baseline_test_failures
    """
    repo_name = state.get("repo_full_name", "")
    clone_url = state.get("repo_clone_url", "")
    issue_num = state.get("issue_number", 0)
    task_id = state.get("task_id", "")

    started = time.time()
    logger.info(f"[Setup] Cloning {repo_name}")
    event_bus.step_start(task_id, STEP_NAME)
    event_bus.emit(task_id, STEP_NAME, f"Cloning {repo_name}", "info")

    clone_result = await clone_repo(clone_url)
    if "error" in clone_result:
        event_bus.step_end(task_id, STEP_NAME, "error", time.time() - started)
        return {
            "status": TaskStatus.FAILED,
            "error": f"Failed to clone: {clone_result['error']}",
        }

    workspace = clone_result["path"]
    branch_name = f"agent/fix-issue-{issue_num}"

    branch_result = await create_branch(workspace, branch_name)
    if "error" in branch_result:
        # Branch may already exist - try to checkout
        from git import Repo
        try:
            repo = Repo(workspace)
            repo.git.checkout(branch_name)
        except Exception:
            event_bus.step_end(task_id, STEP_NAME, "error", time.time() - started)
            return {
                "status": TaskStatus.FAILED,
                "error": f"Failed to create branch: {branch_result['error']}",
            }

    logger.info(f"[Setup] Ready at {workspace} on branch {branch_name}")
    event_bus.emit(task_id, STEP_NAME, f"Ready on branch {branch_name}", "success")

    # Capture baseline test failures so downstream steps can distinguish
    # pre-existing failures from ones introduced by our changes.
    import re as _re

    from tools.test_runner import run_tests

    baseline_failures: list[str] = []
    try:
        baseline = await run_tests(workspace)
        output = baseline.get("output", "")
        for line in output.splitlines():
            if "FAILED" in line:
                match = _re.match(r"^([\w/\.\:]+)\s+FAILED", line.strip())
                if match:
                    baseline_failures.append(match.group(1))
        if baseline_failures:
            logger.info(
                f"[Setup] Baseline has {len(baseline_failures)} pre-existing failures: {baseline_failures}"
            )
            event_bus.emit(
                task_id,
                STEP_NAME,
                f"Baseline: {len(baseline_failures)} pre-existing failures captured",
                "warning",
            )
        else:
            logger.info("[Setup] Baseline: all tests pass")
            event_bus.emit(task_id, STEP_NAME, "Baseline: all tests pass", "success")
    except Exception as e:
        logger.warning(f"[Setup] Baseline test run failed: {e}")

    # Build the tree-sitter repo graph now so downstream steps see it warm.
    # Best-effort: if the build fails for any reason the planner falls back
    # to legacy regex retrieval.
    try:
        event_bus.emit(task_id, STEP_NAME, "Indexing repository (tree-sitter)...", "info")
        from tools.repo_graph import get_or_build_graph
        graph = await get_or_build_graph(workspace)
        gs = graph.stats
        event_bus.emit(
            task_id,
            STEP_NAME,
            (
                f"Indexed: {gs.files_parsed} files, {gs.symbols} symbols, "
                f"{gs.references} refs, {gs.edges} edges, {gs.wall_time_ms:.0f}ms"
            ),
            "success" if gs.files_parsed > 0 else "warning",
        )
    except Exception as e:
        logger.warning(f"[Setup] Graph indexing failed: {e}")
        event_bus.emit(task_id, STEP_NAME, f"Graph indexing failed: {e}", "warning")

    event_bus.step_end(task_id, STEP_NAME, "success", time.time() - started)

    return {
        "workspace_path": workspace,
        "branch_name": branch_name,
        "current_step": "Repository cloned and branch created",
        "baseline_test_failures": baseline_failures,
    }


# --- Conditional Edge Functions ---

def should_retry_coding(state: AgentState) -> str:
    """After testing, decide whether to retry coding or proceed to review."""
    if state.get("status") == TaskStatus.FAILED:
        return "failed"
    if state.get("test_results", {}).get("passed", False):
        return "review"
    return "retry_code"


def should_revise_after_review(state: AgentState) -> str:
    """After review, decide whether to revise code or create PR."""
    if state.get("review_approved", False):
        return "create_pr"
    return "revise_code"


# --- Build the Graph ---

def create_agent_graph() -> StateGraph:
    """Create the LangGraph StateGraph for the coding agent workflow.

    Flow:
        setup -> router -> planner -> coder -> tester
                                          ^      |
                                          +-[retry]-+
                                                 | [pass]
                                              reviewer
                                          ^      |
                                          +-[revise]-+
                                                 | [approve]
                                             pr_creator -> END
    """
    graph = StateGraph(AgentState)

    graph.add_node("setup", setup_node)
    graph.add_node("router", router_node)
    graph.add_node("planner", planner_node)
    graph.add_node("coder", coder_node)
    graph.add_node("tester", tester_node)
    graph.add_node("reviewer", reviewer_node)
    graph.add_node("pr_creator", pr_creator_node)

    graph.set_entry_point("setup")
    graph.add_edge("setup", "router")
    graph.add_edge("router", "planner")
    graph.add_edge("planner", "coder")
    graph.add_edge("coder", "tester")

    graph.add_conditional_edges(
        "tester",
        should_retry_coding,
        {
            "retry_code": "coder",
            "review": "reviewer",
            "failed": END,
        },
    )

    graph.add_conditional_edges(
        "reviewer",
        should_revise_after_review,
        {
            "revise_code": "coder",
            "create_pr": "pr_creator",
        },
    )

    graph.add_edge("pr_creator", END)

    return graph


agent_graph = create_agent_graph().compile()


async def run_agent(
    repo_full_name: str,
    issue_number: int,
    issue_title: str,
    issue_body: str = "",
    issue_labels: list[str] | None = None,
    repo_clone_url: str = "",
    task_id: str = "",
) -> dict[str, Any]:
    """Run the full agent pipeline for a GitHub issue.

    Args:
        repo_full_name: Repository in "owner/repo" format.
        issue_number: GitHub issue number.
        issue_title: Issue title.
        issue_body: Issue description.
        issue_labels: Optional issue labels.
        repo_clone_url: HTTPS clone URL (auto-generated if not provided).
        task_id: Task ID for SSE event streaming.

    Returns:
        Final agent state with results.
    """
    if not repo_clone_url:
        repo_clone_url = f"https://github.com/{repo_full_name}.git"

    initial_state: AgentState = {
        "repo_full_name": repo_full_name,
        "issue_number": issue_number,
        "issue_title": issue_title,
        "issue_body": issue_body,
        "issue_labels": issue_labels or [],
        "repo_clone_url": repo_clone_url,
        "workspace_path": "",
        "branch_name": "",
        "task_classification": "",
        "implementation_plan": "",
        "code_changes": [],
        "test_results": {},
        "review_feedback": "",
        "review_approved": False,
        "pr_title": "",
        "pr_body": "",
        "pr_url": "",
        "status": TaskStatus.PENDING,
        "current_step": "Starting agent pipeline",
        "retry_count": 0,
        "review_retry_count": 0,
        "max_retries": 3,
        "error": "",
        "messages": [],
        "baseline_test_failures": [],
        "task_id": task_id,
    }

    logger.info(f"[run] Starting agent for {repo_full_name}#{issue_number}: {issue_title}")

    final_state = await agent_graph.ainvoke(initial_state)

    logger.info(
        f"[run] Finished: status={final_state.get('status')}, "
        f"pr_url={final_state.get('pr_url', 'N/A')}"
    )

    return final_state
