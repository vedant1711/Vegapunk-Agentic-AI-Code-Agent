"""MCP tool definitions - thin wrappers around the internal tools/* layer.

Tools listed here are read-only or workspace-local. Destructive /
credential-requiring operations (`clone_repo`, `push_branch`,
`create_pull_request`) are deliberately NOT exposed via MCP - external
clients should orchestrate those through the FastAPI pipeline instead.
"""
from __future__ import annotations

from typing import Any

import mcp.types as types

from tools.filesystem import (
    list_directory,
    read_file,
    search_files,
    write_file,
)
from tools.git_ops import get_diff
from tools.test_runner import run_linter, run_tests

# Every tool here has:
#   - a JSON-Schema input spec so MCP clients can validate before calling
#   - a corresponding branch in dispatch_tool() below
TOOL_DEFS: list[types.Tool] = [
    types.Tool(
        name="read_file",
        description=(
            "Read the contents of a file. Optionally slice by 1-indexed "
            "line range via start_line / end_line."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "file_path": {"type": "string", "description": "Path to the file."},
                "start_line": {"type": "integer", "description": "1-indexed start line (optional)."},
                "end_line": {"type": "integer", "description": "1-indexed end line, inclusive (optional)."},
            },
            "required": ["file_path"],
        },
    ),
    types.Tool(
        name="write_file",
        description="Write content to a file. Creates parent directories if needed.",
        inputSchema={
            "type": "object",
            "properties": {
                "file_path": {"type": "string"},
                "content": {"type": "string"},
            },
            "required": ["file_path", "content"],
        },
    ),
    types.Tool(
        name="list_directory",
        description="List directory contents recursively up to `max_depth` (default 2).",
        inputSchema={
            "type": "object",
            "properties": {
                "dir_path": {"type": "string"},
                "max_depth": {"type": "integer", "default": 2},
            },
            "required": ["dir_path"],
        },
    ),
    types.Tool(
        name="search_files",
        description=(
            "Search files for a text pattern (uses ripgrep when available, "
            "falls back to Python)."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "directory": {"type": "string"},
                "pattern": {"type": "string", "description": "Text or regex pattern to search for."},
                "file_pattern": {
                    "type": "string",
                    "default": "*",
                    "description": "Glob to filter which files to search (e.g. '*.py').",
                },
                "max_results": {"type": "integer", "default": 50},
            },
            "required": ["directory", "pattern"],
        },
    ),
    types.Tool(
        name="run_tests",
        description=(
            "Run the project's test suite. Auto-detects pytest / jest / go test / "
            "cargo test based on manifest files. Explicit test_command overrides."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "working_dir": {"type": "string"},
                "test_command": {"type": "string", "description": "Explicit command (optional)."},
                "test_framework": {"type": "string", "default": "auto"},
            },
            "required": ["working_dir"],
        },
    ),
    types.Tool(
        name="run_linter",
        description="Run a linter check (auto-detects ruff / eslint based on project config).",
        inputSchema={
            "type": "object",
            "properties": {
                "working_dir": {"type": "string"},
                "linter": {"type": "string", "default": "auto"},
            },
            "required": ["working_dir"],
        },
    ),
    types.Tool(
        name="git_diff",
        description="Get the diff of uncommitted changes in a git repository.",
        inputSchema={
            "type": "object",
            "properties": {"repo_path": {"type": "string"}},
            "required": ["repo_path"],
        },
    ),
]


async def dispatch_tool(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """Route an MCP tool call to the underlying tools/* function.

    Returns the raw dict the underlying function produces. The MCP server
    wraps this into `TextContent` for the wire protocol.
    """
    args = arguments or {}

    if name == "read_file":
        return await read_file(**args)
    if name == "write_file":
        return await write_file(**args)
    if name == "list_directory":
        return await list_directory(**args)
    if name == "search_files":
        return await search_files(**args)
    if name == "run_tests":
        return await run_tests(**args)
    if name == "run_linter":
        return await run_linter(**args)
    if name == "git_diff":
        return await get_diff(args["repo_path"])

    raise ValueError(f"Unknown tool: {name}")
