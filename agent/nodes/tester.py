"""Atlas (Tester) node — runs tests and reports results."""

from __future__ import annotations

import logging
import os
import re
from typing import Any

from agent.state import AgentState, TaskStatus
from tools.test_runner import run_tests, run_linter
from app.events import event_bus

logger = logging.getLogger(__name__)


def _extract_failures(output: str) -> list[str]:
    """Extract failed test names from pytest output."""
    failures = []
    for line in output.splitlines():
        if "FAILED" in line:
            match = re.match(r"^([\w/\.\:]+)\s+FAILED", line.strip())
            if match:
                failures.append(match.group(1))
    return failures


async def tester_node(state: AgentState) -> dict[str, Any]:
    """Run tests and linting on the modified code.

    Compares results against baseline to ignore pre-existing failures.

    Reads: workspace_path, code_changes, baseline_test_failures
    Writes: test_results, status, current_step, retry_count
    """
    workspace = state.get("workspace_path", "")
    retry_count = state.get("retry_count", 0)
    baseline_failures = state.get("baseline_test_failures", [])
    task_id = state.get("task_id", "")

    logger.info(f"🔨 Atlas (Tester): Running tests (attempt #{retry_count + 1}) in {workspace}")
    event_bus.emit(task_id, "Atlas (Tester)", f"Running tests (attempt #{retry_count + 1})", "info")

    # Validate workspace
    if not workspace or not os.path.isdir(workspace):
        logger.error(f"🔨 Atlas (Tester): Invalid workspace path: '{workspace}'")
        return {
            "test_results": {"passed": False, "output": f"Invalid workspace: {workspace}"},
            "retry_count": retry_count + 1,
            "status": TaskStatus.FAILED,
            "current_step": "Invalid workspace path",
            "error": f"Workspace path is invalid: '{workspace}'",
        }

    # Run linter first
    lint_result = await run_linter(workspace)
    logger.info(f"🔨 Atlas (Tester): Lint {'passed' if lint_result.get('clean') else 'failed'}")

    # Run test suite
    test_result = await run_tests(workspace)
    raw_passed = test_result.get("passed", False)
    test_output = test_result.get("output", "")

    # Compare against baseline — only NEW failures count
    if not raw_passed and baseline_failures:
        current_failures = _extract_failures(test_output)
        new_failures = [f for f in current_failures if f not in baseline_failures]

        if not new_failures:
            # All failures are pre-existing! The agent's changes didn't break anything.
            logger.info(
                f"🔨 Atlas (Tester): {len(current_failures)} failures are all PRE-EXISTING "
                f"(baseline had {len(baseline_failures)}). Treating as PASS ✅"
            )
            all_passed = True
        else:
            logger.info(
                f"🔨 Atlas (Tester): {len(new_failures)} NEW failures (not in baseline): {new_failures}"
            )
            all_passed = False
    else:
        all_passed = raw_passed

    logger.info(f"🔨 Atlas (Tester): Final verdict: {'PASSED ✅' if all_passed else 'FAILED ❌'}")
    event_bus.emit(task_id, "Atlas (Tester)", f"Final verdict: {'PASSED ✅' if all_passed else 'FAILED ❌'}", "success" if all_passed else "error")

    if not all_passed:
        # Log output for debugging
        logger.info(f"🔨 Atlas (Tester): Test output:\n{test_output[:1500]}")

    # Combine results
    combined_output = ""

    if not lint_result.get("clean", True):
        combined_output += f"**Lint Issues:**\n```\n{lint_result.get('output', '')[:1500]}\n```\n\n"

    combined_output += f"**Test Results (exit code {test_result.get('exit_code', '?')}):**\n```\n{test_output[:2000]}\n```"

    results = {
        "passed": all_passed,
        "lint_clean": lint_result.get("clean", True),
        "test_passed": all_passed,
        "output": combined_output,
        "exit_code": test_result.get("exit_code", -1),
    }

    if all_passed:
        return {
            "test_results": results,
            "status": TaskStatus.REVIEWING,
            "current_step": "Tests passed — starting self-review",
            "messages": [{"role": "assistant", "content": "✅ All tests passed!"}],
        }
    else:
        new_retry = retry_count + 1
        max_retries = state.get("max_retries", 3)

        if new_retry >= max_retries:
            return {
                "test_results": results,
                "retry_count": new_retry,
                "status": TaskStatus.FAILED,
                "current_step": f"Tests failed after {max_retries} attempts",
                "error": f"Tests failed after {max_retries} retry attempts",
                "messages": [
                    {"role": "assistant", "content": f"❌ Tests failed after {max_retries} attempts."}
                ],
            }

        return {
            "test_results": results,
            "retry_count": new_retry,
            "status": TaskStatus.CODING,
            "current_step": f"Tests failed — retrying ({new_retry}/{max_retries})",
            "messages": [
                {"role": "assistant", "content": f"❌ Tests failed (attempt {new_retry}/{max_retries}). Retrying..."}
            ],
        }
