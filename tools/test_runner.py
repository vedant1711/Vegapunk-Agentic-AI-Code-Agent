"""Test runner — executes project tests in the sandbox and parses results."""

from __future__ import annotations

import logging
from typing import Any

from tools.sandbox import sandbox

logger = logging.getLogger(__name__)


async def run_tests(
    working_dir: str,
    test_command: str | None = None,
    test_framework: str = "auto",
) -> dict[str, Any]:
    """Run tests for a project in the sandbox.

    Auto-detects the test framework if not specified.

    Args:
        working_dir: Path to the project root.
        test_command: Explicit test command to run. Auto-detected if None.
        test_framework: "pytest", "jest", "npm", "auto".

    Returns:
        Dict with test results: passed, failed, errors, output.
    """
    if not test_command:
        test_command = await _detect_test_command(working_dir, test_framework)

    logger.info(f"Running tests: {test_command} in {working_dir}")

    result = await sandbox.execute(
        command=test_command,
        working_dir=working_dir,
        timeout=120,
    )

    # Parse results
    passed = "error" not in result and result.get("exit_code", 1) == 0
    output = result.get("stdout", "") + "\n" + result.get("stderr", "")

    return {
        "passed": passed,
        "exit_code": result.get("exit_code", -1),
        "output": output.strip(),
        "command": test_command,
    }


async def _detect_test_command(working_dir: str, framework: str) -> str:
    """Auto-detect the appropriate test command for a project."""
    from pathlib import Path

    project = Path(working_dir)

    if framework != "auto":
        commands = {
            "pytest": "PYTHONPATH=. python -m pytest --rootdir=. -c /dev/null -v --tb=short 2>&1",
            "jest": "npx jest --verbose 2>&1",
            "npm": "npm test 2>&1",
            "go": "go test ./... 2>&1",
        }
        return commands.get(framework, f"{framework} 2>&1")

    # Auto-detect based on project files
    if (project / "pytest.ini").exists() or (project / "setup.py").exists():
        return "PYTHONPATH=. python -m pytest --rootdir=. -c /dev/null -v --tb=short 2>&1"
    if (project / "pyproject.toml").exists():
        return "PYTHONPATH=. python -m pytest --rootdir=. -c /dev/null -v --tb=short 2>&1"
    if (project / "package.json").exists():
        return "npm test 2>&1"
    if (project / "go.mod").exists():
        return "go test ./... 2>&1"
    if (project / "Cargo.toml").exists():
        return "cargo test 2>&1"

    # Check for Python test files
    test_dirs = ["tests", "test"]
    for td in test_dirs:
        if (project / td).is_dir():
            return "PYTHONPATH=. python -m pytest --rootdir=. -c /dev/null -v --tb=short 2>&1"

    # Check for any test_*.py files
    if list(project.rglob("test_*.py")):
        return "PYTHONPATH=. python -m pytest --rootdir=. -c /dev/null -v --tb=short 2>&1"

    # Default
    return "PYTHONPATH=. python -m pytest --rootdir=. -c /dev/null -v --tb=short 2>&1"


async def run_linter(
    working_dir: str,
    linter: str = "auto",
) -> dict[str, Any]:
    """Run a linter/formatter check on the project.

    Lint results are INFORMATIONAL ONLY — they do not block the pipeline.

    Args:
        working_dir: Path to the project root.
        linter: "ruff", "eslint", "auto".

    Returns:
        Dict with lint results.
    """
    from pathlib import Path

    project = Path(working_dir)

    if linter == "auto":
        # Only lint if the project has its own linter config
        has_ruff_config = (
            (project / "ruff.toml").exists()
            or (project / ".ruff.toml").exists()
        )
        has_pyproject_ruff = False
        pyproject = project / "pyproject.toml"
        if pyproject.exists():
            try:
                content = pyproject.read_text()
                has_pyproject_ruff = "[tool.ruff]" in content
            except Exception:
                pass

        if has_ruff_config or has_pyproject_ruff:
            linter = "ruff"
        elif (project / ".eslintrc.js").exists() or (project / ".eslintrc.json").exists():
            linter = "eslint"
        else:
            # No linter config found — skip
            logger.info("No linter config found in project — skipping lint")
            return {"clean": True, "output": "Skipped (no linter config in project)", "linter": "none"}

    commands = {
        "ruff": "ruff check . 2>&1",
        "eslint": "npx eslint . 2>&1",
        "mypy": "mypy . 2>&1",
    }

    command = commands.get(linter, f"{linter} . 2>&1")
    result = await sandbox.execute(command=command, working_dir=working_dir, timeout=60)

    return {
        "clean": result.get("exit_code", 1) == 0,
        "output": result.get("stdout", "") + "\n" + result.get("stderr", ""),
        "linter": linter,
    }


# Tool definitions for LLM function calling
TEST_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "run_tests",
            "description": "Run the project's test suite. Auto-detects pytest, jest, npm test, etc.",
            "parameters": {
                "type": "object",
                "properties": {
                    "working_dir": {"type": "string", "description": "Path to the project root"},
                    "test_command": {"type": "string", "description": "Explicit test command (optional, auto-detected)"},
                },
                "required": ["working_dir"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_linter",
            "description": "Run a linter/formatter check (ruff, eslint, etc.).",
            "parameters": {
                "type": "object",
                "properties": {
                    "working_dir": {"type": "string", "description": "Path to the project root"},
                    "linter": {"type": "string", "description": "Linter to use (auto, ruff, eslint)"},
                },
                "required": ["working_dir"],
            },
        },
    },
]
