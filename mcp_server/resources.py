"""MCP resource providers backed by the tree-sitter repo graph.

Novel angle: most MCP servers expose only tools (procedural verbs). We
expose the repo graph as first-class URI-addressable resources so
clients can subscribe, fetch, or cite specific graph slices instead of
calling a procedural tool every time.

URI scheme: `vegapunk://<authority>/<path>?<query>`

Concrete resources (enumerable via `list_resources`):
    vegapunk://graph/summary            - build stats + PageRank map
    vegapunk://repo/tree                - ASCII file tree of the workspace

Resource templates (constructible by the client):
    vegapunk://graph/symbols?q={query}       - symbols matching a keyword
    vegapunk://graph/references/{symbol}     - call/import sites of a symbol
    vegapunk://graph/neighborhood/{path}     - files that import or are imported by `path`
    vegapunk://graph/relevant?q={query}      - hybrid keyword+PageRank ranking
"""
from __future__ import annotations

import json
import os
import urllib.parse
from dataclasses import asdict

import mcp.types as types
from pydantic import AnyUrl

from tools.repo_graph import get_or_build_graph


def _workspace() -> str:
    """Path to the repo the server should index.

    Defaults to $PWD, which matches what MCP clients do when they launch
    the server from a project root. Override via VEGAPUNK_WORKSPACE.
    """
    return os.environ.get("VEGAPUNK_WORKSPACE", os.getcwd())


# --- Definitions surfaced to clients -----------------------------------------

RESOURCE_DEFS: list[types.Resource] = [
    types.Resource(
        uri=AnyUrl("vegapunk://graph/summary"),
        name="Repository graph summary",
        description=(
            "Stats + PageRank map for the tree-sitter code graph of the "
            "current workspace (file count, symbol count, edges, wall time, "
            "per-file PageRank scores)."
        ),
        mimeType="application/json",
    ),
    types.Resource(
        uri=AnyUrl("vegapunk://repo/tree"),
        name="Repository file tree",
        description="ASCII tree overview of the current workspace, respecting standard ignore dirs.",
        mimeType="text/plain",
    ),
]

RESOURCE_TEMPLATES: list[types.ResourceTemplate] = [
    types.ResourceTemplate(
        uriTemplate="vegapunk://graph/symbols?q={query}",
        name="Symbol lookup by keyword",
        description=(
            "Return symbols (functions, classes, methods) whose name contains "
            "the given substring. Exact matches rank first."
        ),
        mimeType="application/json",
    ),
    types.ResourceTemplate(
        uriTemplate="vegapunk://graph/references/{symbol}",
        name="Symbol references",
        description="Every call/import site for the named symbol across the repo.",
        mimeType="application/json",
    ),
    types.ResourceTemplate(
        uriTemplate="vegapunk://graph/neighborhood/{file_path}",
        name="File neighborhood",
        description=(
            "Files reachable within radius=1 in the reference graph "
            "(files that import or are imported by the given file)."
        ),
        mimeType="application/json",
    ),
    types.ResourceTemplate(
        uriTemplate="vegapunk://graph/relevant?q={query}",
        name="Hybrid relevance ranking",
        description=(
            "Rank files by combined keyword + PageRank score for a natural-language "
            "query. Returns the top 15 with matched symbols and per-file scores."
        ),
        mimeType="application/json",
    ),
]


# --- Reader ------------------------------------------------------------------


async def read_resource(uri: str) -> tuple[str, str]:
    """Return `(content, mime_type)` for a Vegapunk resource URI.

    Raises `ValueError` on unknown URIs so the server can surface a proper
    MCP error to the client instead of crashing.
    """
    parsed = urllib.parse.urlparse(uri)

    if parsed.scheme != "vegapunk":
        raise ValueError(f"Unknown URI scheme: {parsed.scheme!r}. Expected 'vegapunk://'.")

    authority = parsed.netloc
    path = parsed.path.lstrip("/")
    qs = urllib.parse.parse_qs(parsed.query)

    if authority == "graph":
        return await _handle_graph(path, qs)
    if authority == "repo":
        return await _handle_repo(path)

    raise ValueError(f"Unknown resource authority: {authority!r}")


async def _handle_graph(path: str, qs: dict[str, list[str]]) -> tuple[str, str]:
    graph = await get_or_build_graph(_workspace())

    if path == "" or path == "summary":
        payload = {
            "workspace": _workspace(),
            "stats": asdict(graph.stats),
            "pagerank": graph.pagerank,
        }
        return json.dumps(payload, indent=2), "application/json"

    if path == "symbols":
        q = _first(qs, "q")
        if not q:
            raise ValueError("vegapunk://graph/symbols requires ?q=<keyword>")
        results = [asdict(s) for s in graph.symbols_matching(q)]
        return json.dumps(results, indent=2), "application/json"

    if path.startswith("references/"):
        symbol = urllib.parse.unquote(path[len("references/"):])
        if not symbol:
            raise ValueError("vegapunk://graph/references/<symbol> requires a symbol name")
        results = [asdict(r) for r in graph.references_of(symbol)]
        return json.dumps(results, indent=2), "application/json"

    if path.startswith("neighborhood/"):
        file_path = urllib.parse.unquote(path[len("neighborhood/"):])
        if not file_path:
            raise ValueError("vegapunk://graph/neighborhood/<path> requires a file path")
        neighbors = graph.file_neighborhood(file_path)
        return json.dumps(neighbors, indent=2), "application/json"

    if path == "relevant":
        q = _first(qs, "q")
        if not q:
            raise ValueError("vegapunk://graph/relevant requires ?q=<query>")
        matches = [asdict(m) for m in graph.relevant_files_for(q)]
        return json.dumps(matches, indent=2), "application/json"

    raise ValueError(f"Unknown graph resource path: {path!r}")


async def _handle_repo(path: str) -> tuple[str, str]:
    if path == "tree":
        # Local import to avoid loading code_search unless this resource is used.
        from tools.code_search import get_file_structure

        result = await get_file_structure(_workspace())
        return result.get("tree", ""), "text/plain"

    raise ValueError(f"Unknown repo resource path: {path!r}")


def _first(qs: dict[str, list[str]], key: str) -> str | None:
    """Return the first value for a query-string key, or None if absent/empty."""
    vals = qs.get(key) or []
    if not vals:
        return None
    v = vals[0].strip()
    return v or None
