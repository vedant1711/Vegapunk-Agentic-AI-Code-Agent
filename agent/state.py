"""Agent state schema — the shared state that flows through the LangGraph workflow."""

from __future__ import annotations

from enum import Enum
from typing import Annotated, Any

from langgraph.graph.message import add_messages
from typing_extensions import TypedDict


class TaskStatus(str, Enum):
    """Overall task lifecycle status."""
    PENDING = "pending"
    PLANNING = "planning"
    CODING = "coding"
    TESTING = "testing"
    REVIEWING = "reviewing"
    CREATING_PR = "creating_pr"
    COMPLETED = "completed"
    FAILED = "failed"


class AgentState(TypedDict):
    """Shared state for the LangGraph coding agent workflow.

    This flows through every node. Nodes read what they need and write
    their outputs back into the state.
    """

    # --- Task Input ---
    repo_full_name: str               # "owner/repo"
    issue_number: int                  # GitHub issue number
    issue_title: str                   # Issue title
    issue_body: str                    # Issue description
    issue_labels: list[str]           # Issue labels
    repo_clone_url: str               # HTTPS clone URL

    # --- Workspace ---
    workspace_path: str               # Local path to cloned repo
    branch_name: str                  # Working branch name

    # --- Agent Outputs ---
    task_classification: str          # "bug_fix", "feature", "refactor", "docs", etc.
    implementation_plan: str          # Planner's detailed plan
    code_changes: list[dict[str, Any]]  # List of {file, action, content} changes made
    test_results: dict[str, Any]      # Test execution results
    review_feedback: str              # Self-review feedback
    review_approved: bool             # Whether the self-review passed

    # --- PR Output ---
    pr_title: str                     # Pull request title
    pr_body: str                      # Pull request body (markdown)
    pr_url: str                       # Created PR URL

    # --- Control Flow ---
    status: TaskStatus                # Current pipeline status
    current_step: str                 # Human-readable current step
    retry_count: int                  # Number of test-fix retry cycles
    max_retries: int                  # Maximum retries before failing
    error: str                        # Error message if failed

    # --- Conversation ---
    messages: Annotated[list, add_messages]  # Full message history for context

    # --- Baseline ---
    baseline_test_failures: list[str]  # Test names that were already failing before changes
