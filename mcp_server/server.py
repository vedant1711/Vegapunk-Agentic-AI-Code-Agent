"""Vegapunk MCP server - stdio transport, exposes tools + repo-graph resources.

Launch via the `vegapunk-mcp` console script (declared in pyproject) or
`python -m mcp_server.server`. Standard MCP clients (Claude Code, Cursor,
Cline) connect over stdio.

Environment:
    VEGAPUNK_WORKSPACE - workspace path to index. Defaults to $PWD, which
        matches what MCP clients do when they launch the server from a
        project root.
    LOG_LEVEL - logging level (default INFO). Server logs go to stderr so
        the stdout protocol stream stays clean.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import sys

import mcp.types as types
from mcp.server import NotificationOptions, Server
from mcp.server.models import InitializationOptions
from mcp.server.stdio import stdio_server
from pydantic import AnyUrl

from mcp_server.resources import (
    RESOURCE_DEFS,
    RESOURCE_TEMPLATES,
)
from mcp_server.resources import (
    read_resource as _read_vegapunk_resource,
)
from mcp_server.tools import TOOL_DEFS, dispatch_tool

# MCP uses stdout for the JSON-RPC protocol stream. Any log output on
# stdout would corrupt it, so all logging goes to stderr instead.
logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO").upper(),
    stream=sys.stderr,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("vegapunk-mcp")


server: Server = Server("vegapunk")


# --- Tools ------------------------------------------------------------------


@server.list_tools()
async def _list_tools() -> list[types.Tool]:
    return TOOL_DEFS


@server.call_tool()
async def _call_tool(name: str, arguments: dict) -> list[types.TextContent]:
    """Dispatch a tool call and wrap the result as MCP TextContent."""
    try:
        result = await dispatch_tool(name, arguments or {})
    except Exception as e:
        logger.exception(f"Tool {name!r} failed")
        return [types.TextContent(type="text", text=json.dumps({"error": str(e)}))]

    return [
        types.TextContent(
            type="text",
            text=json.dumps(result, default=str, indent=2),
        )
    ]


# --- Resources --------------------------------------------------------------


@server.list_resources()
async def _list_resources() -> list[types.Resource]:
    return RESOURCE_DEFS


@server.list_resource_templates()
async def _list_resource_templates() -> list[types.ResourceTemplate]:
    return RESOURCE_TEMPLATES


@server.read_resource()
async def _read_resource(uri: AnyUrl) -> str:
    content, _mime = await _read_vegapunk_resource(str(uri))
    return content


# --- Entry point ------------------------------------------------------------


async def _serve() -> None:
    logger.info("Vegapunk MCP server starting on stdio (workspace=%s)",
                os.environ.get("VEGAPUNK_WORKSPACE", os.getcwd()))
    async with stdio_server() as (read, write):
        await server.run(
            read,
            write,
            InitializationOptions(
                server_name="vegapunk",
                server_version="0.1.0",
                capabilities=server.get_capabilities(
                    notification_options=NotificationOptions(),
                    experimental_capabilities={},
                ),
            ),
        )


def main() -> None:
    """Console entry point registered as `vegapunk-mcp` in pyproject.toml."""
    asyncio.run(_serve())


if __name__ == "__main__":
    main()
