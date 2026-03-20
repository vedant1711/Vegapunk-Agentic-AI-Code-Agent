"""Main LangGraph workflow — the agentic coding agent pipeline."""

from __future__ import annotations

import logging
from typing import Any

from langgraph.graph import END, StateGraph

from agent.state import AgentState, TaskStatus
from agent.nodes.router import router_node
from agent.nodes.planner import planner_node
from agent.nodes.coder import coder_node
from agent.nodes.tester import tester_node
from agent.nodes.reviewer import reviewer_node
from agent.nodes.pr_creator import pr_creator_node
from tools.git_ops import clone_repo, create_branch
from tools.github_api import github_api

logger = logging.getLogger(__name__)


# --- Setup Node (not an LLM agent — just workspace prep) ---

async def setup_node(state: AgentState) -> dict[str, Any]:
    """Clone the repo and create a working branch.

    Reads: repo_full_name, repo_clone_url, issue_number
    Writes: workspace_path, branch_name
    """
    repo_name = state.get("repo_full_name", "")
    clone_url = state.get("repo_clone_url", "")
    issue_num = state.get("issue_number", 0)

    logger.info(f"⚙️ Stella (Setup): Cloning {repo_name}")

    # Clone the repository
    clone_result = await clone_repo(clone_url)
    if "error" in clone_result:
        return {
            "status": TaskStatus.FAILED,
            "error": f"Failed to clone: {clone_result['error']}",
        }

    workspace = clone_result["path"]
    branch_name = f"agent/fix-issue-{issue_num}"

    # Create working branch
    branch_result = await create_branch(workspace, branch_name)
    if "error" in branch_result:
        # Branch might already exist — try checkout
        from git import Repo
        try:
            repo = Repo(workspace)
            repo.git.checkout(branch_name)
        except Exception:
            return {
                "status": TaskStatus.FAILED,
                "error": f"Failed to create branch: {branch_result['error']}",
            }

    logger.info(f"⚙️ Stella (Setup): Ready at {workspace} on branch {branch_name}")

    # Run baseline tests BEFORE changes to capture pre-existing failures
    from tools.test_runner import run_tests
    import re as _re

    baseline_failures = []
    try:
        baseline = await run_tests(workspace)
        output = baseline.get("output", "")
        # Extract failed test names from pytest output
        for line in output.splitlines():
            if "FAILED" in line:
                # Matches patterns like "tests/test_file.py::test_name FAILED"
                match = _re.match(r"^([\w/\.\:]+)\s+FAILED", line.strip())
                if match:
                    baseline_failures.append(match.group(1))
        if baseline_failures:
            logger.info(f"⚙️ Stella (Setup): Baseline has {len(baseline_failures)} pre-existing failures: {baseline_failures}")
        else:
            logger.info("⚙️ Stella (Setup): Baseline — all tests pass")
    except Exception as e:
        logger.warning(f"⚙️ Stella (Setup): Baseline test run failed: {e}")

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
    setup → router → planner → coder → tester
                                  ↑        ↓
                                  └─[retry]─┘
                                         ↓ [pass]
                                      reviewer
                                  ↑        ↓
                                  └─[revise]┘
                                         ↓ [approve]
                                     pr_creator → END
    """
    graph = StateGraph(AgentState)

    # Add nodes
    graph.add_node("setup", setup_node)
    graph.add_node("router", router_node)
    graph.add_node("planner", planner_node)
    graph.add_node("coder", coder_node)
    graph.add_node("tester", tester_node)
    graph.add_node("reviewer", reviewer_node)
    graph.add_node("pr_creator", pr_creator_node)

    # Define edges
    graph.set_entry_point("setup")
    graph.add_edge("setup", "router")
    graph.add_edge("router", "planner")
    graph.add_edge("planner", "coder")
    graph.add_edge("coder", "tester")

    # Conditional: after tester → retry coder or go to reviewer
    graph.add_conditional_edges(
        "tester",
        should_retry_coding,
        {
            "retry_code": "coder",
            "review": "reviewer",
            "failed": END,
        },
    )

    # Conditional: after reviewer → revise code or create PR
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


# Compile the graph
agent_graph = create_agent_graph().compile()


async def run_agent(
    repo_full_name: str,
    issue_number: int,
    issue_title: str,
    issue_body: str,
    issue_labels: list[str] | None = None,
    repo_clone_url: str | None = None,
) -> dict[str, Any]:
    """Run the full agent pipeline for a GitHub issue.

    Args:
        repo_full_name: Repository in "owner/repo" format.
        issue_number: GitHub issue number.
        issue_title: Issue title.
        issue_body: Issue description.
        issue_labels: Optional issue labels.
        repo_clone_url: HTTPS clone URL (auto-generated if not provided).

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
        "max_retries": 3,
        "error": "",
        "messages": [],
        "baseline_test_failures": [],
    }

    logger.info(f"🏴\u200d☠️ Vegapunk starting agent for {repo_full_name}#{issue_number}: {issue_title}")

    final_state = await agent_graph.ainvoke(initial_state)

    logger.info(
        f"🏁 Vegapunk finished: status={final_state.get('status')}, "
        f"pr_url={final_state.get('pr_url', 'N/A')}"
    )

    return final_state
