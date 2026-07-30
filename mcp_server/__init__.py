"""Vegapunk MCP server.

Exposes the internal `tools/*` layer plus the tree-sitter repo graph as
MCP tools and resources so external clients (Claude Code, Cursor, Cline)
can drive Vegapunk without any custom SDK.

Launched via the `vegapunk-mcp` console script or `python -m mcp_server.server`.
"""

from mcp_server.server import main

__all__ = ["main"]
