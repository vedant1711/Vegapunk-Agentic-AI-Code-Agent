"""Router node - classifies the issue and decides the approach."""

from __future__ import annotations

import json
import logging
import time
from typing import Any

from agent.state import AgentState, TaskStatus
from app.events import event_bus
from llm.provider import ModelTier, llm

logger = logging.getLogger(__name__)

STEP_NAME = "Router"

ROUTER_SYSTEM_PROMPT = """You are a task classifier for an AI coding agent. Given a GitHub issue, classify it into exactly one category and provide a brief analysis.

Categories:
- bug_fix: Fixing a bug, error, or unexpected behavior
- feature: Adding new functionality or capability
- refactor: Improving code structure without changing behavior
- docs: Documentation updates, README changes, comments
- test: Adding or fixing tests
- chore: Dependencies, CI/CD, config changes

Respond in JSON format:
{
    "classification": "bug_fix|feature|refactor|docs|test|chore",
    "complexity": "simple|moderate|complex",
    "summary": "One-line summary of what needs to be done",
    "key_files_to_investigate": ["list", "of", "likely", "relevant", "paths"]
}"""


async def router_node(state: AgentState) -> dict[str, Any]:
    """Classify the GitHub issue and decide on the approach.

    Reads: issue_title, issue_body, issue_labels
    Writes: task_classification, status, current_step
    """
    task_id = state.get("task_id", "")
    started = time.time()

    logger.info(f"[Router] Classifying issue #{state.get('issue_number', '?')}")
    event_bus.step_start(task_id, STEP_NAME)
    event_bus.emit(task_id, STEP_NAME, f"Classifying issue #{state.get('issue_number', '?')}", "info")

    messages = [
        {"role": "system", "content": ROUTER_SYSTEM_PROMPT},
        {
            "role": "user",
            "content": f"""Classify this GitHub issue:

**Title:** {state.get('issue_title', 'No title')}

**Labels:** {', '.join(state.get('issue_labels', []))}

**Description:**
{state.get('issue_body', 'No description provided.')}""",
        },
    ]

    response = await llm.chat(messages=messages, tier=ModelTier.FAST, temperature=0.1)

    # Parse classification
    try:
        clean = response.strip()
        if "```" in clean:
            clean = clean.split("```")[1]
            if clean.startswith("json"):
                clean = clean[4:]
        result = json.loads(clean)
        classification = result.get("classification", "feature")
    except (json.JSONDecodeError, IndexError):
        classification = "feature"  # Safe default

    logger.info(f"[Router] Classified as '{classification}'")
    event_bus.emit(task_id, STEP_NAME, f"Classified as '{classification}'", "success")
    event_bus.step_end(task_id, STEP_NAME, "success", time.time() - started)

    return {
        "task_classification": classification,
        "status": TaskStatus.PLANNING,
        "current_step": f"Classified as {classification} - starting planning",
        "messages": [{"role": "assistant", "content": f"Task classified as: {classification}"}],
    }
