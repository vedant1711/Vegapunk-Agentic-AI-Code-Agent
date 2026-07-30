"""Filesystem tools for reading, writing, searching, and listing files."""

from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


async def read_file(file_path: str, start_line: int | None = None, end_line: int | None = None) -> dict[str, Any]:
    """Read the contents of a file.

    Args:
        file_path: Absolute or relative path to the file.
        start_line: Optional start line (1-indexed).
        end_line: Optional end line (1-indexed, inclusive).

    Returns:
        Dict with 'content', 'total_lines', and 'path'.
    """
    path = Path(file_path)
    if not path.exists():
        return {"error": f"File not found: {file_path}"}
    if not path.is_file():
        return {"error": f"Not a file: {file_path}"}

    try:
        content = path.read_text(encoding="utf-8", errors="replace")
        lines = content.splitlines(keepends=True)
        total_lines = len(lines)

        if start_line or end_line:
            start = max(1, start_line or 1) - 1
            end = min(total_lines, end_line or total_lines)
            lines = lines[start:end]
            content = "".join(lines)

        return {
            "content": content,
            "total_lines": total_lines,
            "path": str(path.resolve()),
        }
    except Exception as e:
        return {"error": f"Failed to read {file_path}: {e}"}


async def write_file(file_path: str, content: str, create_dirs: bool = True) -> dict[str, Any]:
    """Write content to a file.

    Args:
        file_path: Path to the file to write.
        content: Content to write.
        create_dirs: Whether to create parent directories.

    Returns:
        Dict with 'success' and 'path'.
    """
    path = Path(file_path)

    try:
        if create_dirs:
            path.parent.mkdir(parents=True, exist_ok=True)

        path.write_text(content, encoding="utf-8")
        logger.info(f"Wrote {len(content)} bytes to {file_path}")
        return {"success": True, "path": str(path.resolve()), "bytes_written": len(content)}
    except Exception as e:
        return {"error": f"Failed to write {file_path}: {e}"}


async def list_directory(dir_path: str, max_depth: int = 2) -> dict[str, Any]:
    """List contents of a directory recursively up to max_depth.

    Args:
        dir_path: Path to the directory.
        max_depth: Maximum depth to recurse.

    Returns:
        Dict with 'entries' list of {name, type, size}.
    """
    path = Path(dir_path)
    if not path.exists():
        return {"error": f"Directory not found: {dir_path}"}
    if not path.is_dir():
        return {"error": f"Not a directory: {dir_path}"}

    entries = []

    def _walk(current: Path, depth: int, relative: str = ""):
        if depth > max_depth:
            return
        try:
            for item in sorted(current.iterdir()):
                rel_path = f"{relative}/{item.name}" if relative else item.name
                if item.name.startswith("."):
                    continue
                if item.is_dir():
                    entries.append({"name": rel_path, "type": "directory"})
                    _walk(item, depth + 1, rel_path)
                else:
                    entries.append({
                        "name": rel_path,
                        "type": "file",
                        "size": item.stat().st_size,
                    })
        except PermissionError:
            pass

    _walk(path, 0)
    return {"entries": entries, "total": len(entries)}


async def search_files(
    directory: str,
    pattern: str,
    file_pattern: str = "*",
    max_results: int = 50,
) -> dict[str, Any]:
    """Search for a text pattern in files using ripgrep.

    Args:
        directory: Directory to search in.
        pattern: Text or regex pattern to search for.
        file_pattern: Glob pattern to filter files (e.g. "*.py").
        max_results: Maximum number of results.

    Returns:
        Dict with 'matches' list of {file, line, content}.
    """
    try:
        cmd = [
            "rg",
            "--json",
            "--max-count", str(max_results),
            "--glob", file_pattern,
            pattern,
            directory,
        ]

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()

        if proc.returncode not in (0, 1):  # 1 = no matches
            return {"error": f"Search failed: {stderr.decode()}"}

        import json
        matches = []
        for line in stdout.decode().strip().split("\n"):
            if not line:
                continue
            try:
                data = json.loads(line)
                if data.get("type") == "match":
                    match_data = data["data"]
                    matches.append({
                        "file": match_data["path"]["text"],
                        "line": match_data["line_number"],
                        "content": match_data["lines"]["text"].strip(),
                    })
            except (json.JSONDecodeError, KeyError):
                continue

        return {"matches": matches, "total": len(matches)}
    except FileNotFoundError:
        # ripgrep not installed — fallback to Python grep
        return await _python_search(directory, pattern, file_pattern, max_results)


async def _python_search(
    directory: str, pattern: str, file_pattern: str, max_results: int
) -> dict[str, Any]:
    """Fallback search using Python when ripgrep isn't available."""
    import fnmatch
    import re

    regex = re.compile(pattern, re.IGNORECASE)
    matches = []

    for root, _, files in os.walk(directory):
        for filename in files:
            if not fnmatch.fnmatch(filename, file_pattern):
                continue
            filepath = os.path.join(root, filename)
            try:
                with open(filepath, encoding="utf-8", errors="replace") as f:
                    for i, line in enumerate(f, 1):
                        if regex.search(line):
                            matches.append({
                                "file": filepath,
                                "line": i,
                                "content": line.strip(),
                            })
                            if len(matches) >= max_results:
                                return {"matches": matches, "total": len(matches)}
            except (PermissionError, OSError):
                continue

    return {"matches": matches, "total": len(matches)}


async def apply_edit(
    file_path: str,
    original: str,
    replacement: str,
) -> dict[str, Any]:
    """Apply a targeted edit to a file by replacing exact text.

    Falls back to whitespace-normalized matching if exact match fails.

    Args:
        file_path: Path to the file.
        original: The exact text to find and replace.
        replacement: The replacement text.

    Returns:
        Dict with 'success' and details.
    """
    path = Path(file_path)
    if not path.exists():
        return {"error": f"File not found: {file_path}"}

    content = path.read_text(encoding="utf-8")

    # Try exact match first
    if original in content:
        new_content = content.replace(original, replacement, 1)
        path.write_text(new_content, encoding="utf-8")
        return {
            "success": True,
            "path": str(path.resolve()),
            "match_type": "exact",
        }

    # Fallback: try whitespace-normalized matching
    # This handles the common case where the LLM generates slightly different
    # indentation or trailing whitespace

    def normalize_ws(text: str) -> str:
        """Normalize whitespace for fuzzy comparison."""
        # Replace tabs with spaces, collapse multiple spaces within lines
        lines = text.strip().splitlines()
        return "\n".join(line.rstrip() for line in lines)

    norm_original = normalize_ws(original)
    content_lines = content.splitlines(keepends=True)

    # Sliding window search — find the best match
    orig_lines = norm_original.splitlines()
    orig_line_count = len(orig_lines)

    best_match = None
    best_score = 0

    for i in range(len(content_lines) - orig_line_count + 1):
        window = content_lines[i : i + orig_line_count]
        window_text = "".join(window)
        norm_window = normalize_ws(window_text)

        if norm_window == norm_original:
            # Perfect normalized match
            new_content = (
                "".join(content_lines[:i])
                + replacement
                + "\n"
                + "".join(content_lines[i + orig_line_count :])
            )
            path.write_text(new_content, encoding="utf-8")
            return {
                "success": True,
                "path": str(path.resolve()),
                "match_type": "normalized",
            }

        # Score partial matches (for debugging)
        matching_lines = sum(
            1 for a, b in zip(norm_window.splitlines(), orig_lines)
            if a.strip() == b.strip()
        )
        score = matching_lines / orig_line_count if orig_line_count > 0 else 0
        if score > best_score:
            best_score = score
            best_match = window_text

    # Log what we couldn't match for debugging
    logger.warning(
        f"apply_edit failed for {file_path}.\n"
        f"  Searched for ({len(orig_lines)} lines):\n"
        f"    {repr(original[:200])}\n"
        f"  Best partial match (score={best_score:.0%}):\n"
        f"    {repr(best_match[:200] if best_match else 'None')}"
    )

    return {"error": f"Original text not found in {file_path}"}


# Tool definitions for LangChain / LLM function calling
FILESYSTEM_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read the contents of a file. Use start_line and end_line to read specific sections.",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {"type": "string", "description": "Path to the file to read"},
                    "start_line": {"type": "integer", "description": "Start line (1-indexed, optional)"},
                    "end_line": {"type": "integer", "description": "End line (1-indexed, inclusive, optional)"},
                },
                "required": ["file_path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "Write content to a file. Creates parent directories if needed.",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {"type": "string", "description": "Path to the file to write"},
                    "content": {"type": "string", "description": "Content to write to the file"},
                },
                "required": ["file_path", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_directory",
            "description": "List contents of a directory tree.",
            "parameters": {
                "type": "object",
                "properties": {
                    "dir_path": {"type": "string", "description": "Path to the directory"},
                    "max_depth": {"type": "integer", "description": "Max recursion depth (default 2)"},
                },
                "required": ["dir_path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_files",
            "description": "Search for a text pattern across files in a directory.",
            "parameters": {
                "type": "object",
                "properties": {
                    "directory": {"type": "string", "description": "Directory to search in"},
                    "pattern": {"type": "string", "description": "Text or regex pattern to search for"},
                    "file_pattern": {"type": "string", "description": "Glob to filter files (e.g. '*.py')"},
                },
                "required": ["directory", "pattern"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "apply_edit",
            "description": "Apply a targeted edit to a file by finding and replacing exact text.",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {"type": "string", "description": "Path to the file to edit"},
                    "original": {"type": "string", "description": "Exact text to find"},
                    "replacement": {"type": "string", "description": "Replacement text"},
                },
                "required": ["file_path", "original", "replacement"],
            },
        },
    },
]
