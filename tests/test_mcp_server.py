"""Tests for the MCP server surface (tools + resources).

Unit-tests the dispatch and read_resource layers directly - skips the
stdio boilerplate since that's what the SDK owns and we can't
meaningfully assert against it here. Points the workspace at the same
mini_py fixture the repo_graph tests use so assertions have ground truth.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from mcp_server.resources import (
    RESOURCE_DEFS,
    RESOURCE_TEMPLATES,
    read_resource,
)
from mcp_server.tools import TOOL_DEFS, dispatch_tool
from tools.repo_graph import clear_cache

FIXTURES = Path(__file__).parent / "fixtures" / "mini_py"


@pytest.fixture(autouse=True)
def _point_workspace_at_fixture(monkeypatch):
    """Every test in this file runs against the mini_py fixture repo."""
    monkeypatch.setenv("VEGAPUNK_WORKSPACE", str(FIXTURES))
    clear_cache()
    yield
    clear_cache()


# --- Tools: definitions ----------------------------------------------------

def test_tool_defs_cover_expected_surface():
    names = {t.name for t in TOOL_DEFS}
    assert names == {
        "read_file",
        "write_file",
        "list_directory",
        "search_files",
        "run_tests",
        "run_linter",
        "git_diff",
    }


def test_tool_defs_have_valid_json_schemas():
    """Every tool's inputSchema must be a valid JSON-Schema object."""
    for t in TOOL_DEFS:
        assert isinstance(t.inputSchema, dict)
        assert t.inputSchema.get("type") == "object"
        assert "properties" in t.inputSchema


# --- Tools: dispatch ------------------------------------------------------

async def test_dispatch_read_file_returns_content(tmp_path):
    f = tmp_path / "hello.txt"
    f.write_text("hi there\n")
    result = await dispatch_tool("read_file", {"file_path": str(f)})
    assert "hi there" in result["content"]


async def test_dispatch_write_file_writes(tmp_path):
    f = tmp_path / "out.txt"
    result = await dispatch_tool("write_file", {"file_path": str(f), "content": "wrote-it\n"})
    assert result.get("success") is True
    assert f.read_text() == "wrote-it\n"


async def test_dispatch_git_diff_on_clean_workspace():
    # mini_py fixture is not a git repo - the tool returns an error dict.
    result = await dispatch_tool("git_diff", {"repo_path": str(FIXTURES)})
    assert "error" in result


async def test_dispatch_unknown_tool_raises():
    with pytest.raises(ValueError, match="Unknown tool"):
        await dispatch_tool("no_such_tool", {})


# --- Resources: static ----------------------------------------------------

def test_resource_defs_have_expected_uris():
    uris = {str(r.uri) for r in RESOURCE_DEFS}
    assert "vegapunk://graph/summary" in uris
    assert "vegapunk://repo/tree" in uris


def test_resource_templates_have_expected_patterns():
    patterns = {t.uriTemplate for t in RESOURCE_TEMPLATES}
    assert "vegapunk://graph/symbols?q={query}" in patterns
    assert "vegapunk://graph/references/{symbol}" in patterns
    assert "vegapunk://graph/neighborhood/{file_path}" in patterns
    assert "vegapunk://graph/relevant?q={query}" in patterns


async def test_graph_summary_returns_stats_and_pagerank():
    content, mime = await read_resource("vegapunk://graph/summary")
    assert mime == "application/json"
    payload = json.loads(content)
    assert payload["workspace"].endswith("mini_py")
    assert payload["stats"]["files_parsed"] == 6
    assert payload["stats"]["symbols"] >= 8
    assert len(payload["pagerank"]) > 0


async def test_repo_tree_returns_ascii_tree():
    content, mime = await read_resource("vegapunk://repo/tree")
    assert mime == "text/plain"
    assert "auth.py" in content


# --- Resources: templated -------------------------------------------------

async def test_graph_symbols_lookup():
    content, mime = await read_resource("vegapunk://graph/symbols?q=password")
    assert mime == "application/json"
    payload = json.loads(content)
    names = {s["name"] for s in payload}
    assert "hash_password" in names
    assert "verify_password" in names


async def test_graph_references_finds_callers():
    content, _ = await read_resource("vegapunk://graph/references/hash_password")
    payload = json.loads(content)
    files = {r["file_path"] for r in payload}
    assert "src/db.py" in files


async def test_graph_neighborhood():
    content, _ = await read_resource("vegapunk://graph/neighborhood/src/api.py")
    payload = json.loads(content)
    # api.py imports from auth + db
    assert "src/auth.py" in payload
    assert "src/db.py" in payload


async def test_graph_relevant_ranks_central_module_first():
    content, _ = await read_resource(
        "vegapunk://graph/relevant?q=user%20login%20password"
    )
    payload = json.loads(content)
    assert payload, "expected at least one ranked file"
    assert payload[0]["path"] == "src/auth.py"


# --- Resources: error paths ----------------------------------------------

async def test_unknown_scheme_raises():
    with pytest.raises(ValueError, match="Unknown URI scheme"):
        await read_resource("http://example.com/foo")


async def test_unknown_authority_raises():
    with pytest.raises(ValueError, match="Unknown resource authority"):
        await read_resource("vegapunk://mysteries/x")


async def test_unknown_graph_path_raises():
    with pytest.raises(ValueError, match="Unknown graph resource path"):
        await read_resource("vegapunk://graph/nonsense")


async def test_symbols_without_query_raises():
    with pytest.raises(ValueError, match="requires \\?q="):
        await read_resource("vegapunk://graph/symbols")


async def test_relevant_without_query_raises():
    with pytest.raises(ValueError, match="requires \\?q="):
        await read_resource("vegapunk://graph/relevant")


async def test_neighborhood_without_path_raises():
    with pytest.raises(ValueError, match="requires a file path"):
        await read_resource("vegapunk://graph/neighborhood/")


async def test_references_without_symbol_raises():
    with pytest.raises(ValueError, match="requires a symbol name"):
        await read_resource("vegapunk://graph/references/")
