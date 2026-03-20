"""Code search tool — semantic and text search across codebases."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from tools.filesystem import search_files

logger = logging.getLogger(__name__)


async def find_relevant_files(
    repo_path: str,
    query: str,
    file_extensions: list[str] | None = None,
    max_results: int = 20,
) -> dict[str, Any]:
    """Find files relevant to a query using text search.

    Args:
        repo_path: Path to the repository root.
        query: Search query (text pattern or keyword).
        file_extensions: Filter by extensions (e.g. [".py", ".js"]).
        max_results: Maximum results to return.

    Returns:
        Dict with matched files and relevant lines.
    """
    results = []

    if file_extensions:
        for ext in file_extensions:
            pattern = f"*{ext}"
            search_result = await search_files(
                directory=repo_path,
                pattern=query,
                file_pattern=pattern,
                max_results=max_results,
            )
            if "matches" in search_result:
                results.extend(search_result["matches"])
    else:
        search_result = await search_files(
            directory=repo_path,
            pattern=query,
            max_results=max_results,
        )
        if "matches" in search_result:
            results = search_result["matches"]

    # Deduplicate by file and sort by relevance (number of matches per file)
    file_scores: dict[str, list] = {}
    for match in results[:max_results]:
        fname = match["file"]
        if fname not in file_scores:
            file_scores[fname] = []
        file_scores[fname].append(match)

    ranked_files = sorted(file_scores.items(), key=lambda x: len(x[1]), reverse=True)

    return {
        "files": [
            {
                "path": path,
                "match_count": len(matches),
                "sample_matches": matches[:3],  # Show top 3 matches per file
            }
            for path, matches in ranked_files
        ],
        "total_matches": len(results),
    }


async def get_file_structure(
    repo_path: str,
    ignore_patterns: list[str] | None = None,
) -> dict[str, Any]:
    """Get a tree-style overview of the repository structure.

    Args:
        repo_path: Path to the repository root.
        ignore_patterns: Directories/files to ignore.

    Returns:
        Dict with a formatted tree string and file list.
    """
    default_ignore = {
        "node_modules", ".git", "__pycache__", ".venv", "venv",
        ".mypy_cache", ".pytest_cache", "dist", "build", ".eggs",
        ".tox", "htmlcov", ".next", ".nuxt",
    }

    if ignore_patterns:
        default_ignore.update(ignore_patterns)

    root = Path(repo_path)
    if not root.exists():
        return {"error": f"Path not found: {repo_path}"}

    tree_lines = []
    file_list = []

    def _walk(path: Path, prefix: str = "", depth: int = 0):
        if depth > 4:  # Max depth
            return

        entries = sorted(
            [e for e in path.iterdir() if e.name not in default_ignore and not e.name.startswith(".")],
            key=lambda e: (not e.is_dir(), e.name.lower()),
        )

        for i, entry in enumerate(entries):
            is_last = i == len(entries) - 1
            connector = "└── " if is_last else "├── "
            new_prefix = prefix + ("    " if is_last else "│   ")

            if entry.is_dir():
                tree_lines.append(f"{prefix}{connector}📁 {entry.name}/")
                _walk(entry, new_prefix, depth + 1)
            else:
                size = entry.stat().st_size
                tree_lines.append(f"{prefix}{connector}{entry.name} ({_human_size(size)})")
                file_list.append(str(entry.relative_to(root)))

    _walk(root)

    tree = f"📂 {root.name}/\n" + "\n".join(tree_lines)
    return {"tree": tree, "files": file_list, "total_files": len(file_list)}


def _human_size(size: int) -> str:
    """Convert bytes to human-readable size."""
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024:
            return f"{size:.0f}{unit}"
        size /= 1024
    return f"{size:.1f}TB"


# Tool definitions for LLM function calling
CODE_SEARCH_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "find_relevant_files",
            "description": "Search for files relevant to a query in the repository. Ranks files by match count.",
            "parameters": {
                "type": "object",
                "properties": {
                    "repo_path": {"type": "string", "description": "Path to the repository root"},
                    "query": {"type": "string", "description": "Search query (text pattern or keyword)"},
                    "file_extensions": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Filter by file extensions (e.g. ['.py', '.js'])",
                    },
                },
                "required": ["repo_path", "query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_file_structure",
            "description": "Get a tree-style overview of the repository file structure.",
            "parameters": {
                "type": "object",
                "properties": {
                    "repo_path": {"type": "string", "description": "Path to the repository root"},
                },
                "required": ["repo_path"],
            },
        },
    },
]
