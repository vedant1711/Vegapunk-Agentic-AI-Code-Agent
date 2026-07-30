# Vegapunk MCP server

Exposes the internal `tools/*` layer and the tree-sitter repo graph over
the [Model Context Protocol](https://modelcontextprotocol.io) so any
MCP-capable client (Claude Code, Cursor, Cline, Continue.dev, Windsurf,
Codex CLI, etc.) can drive Vegapunk without a custom SDK.

## What it exposes

**Tools** (verbs the client can invoke):

| Name | Purpose |
|---|---|
| `read_file` | Read a file, optionally sliced by 1-indexed line range |
| `write_file` | Write content to a file (creates parent dirs) |
| `list_directory` | Recursive directory listing to `max_depth` |
| `search_files` | ripgrep-backed text search |
| `run_tests` | Auto-detects pytest / jest / go test / cargo test |
| `run_linter` | Auto-detects ruff / eslint |
| `git_diff` | Uncommitted changes in a repo |

Destructive / credential-requiring operations (`clone_repo`, `push_branch`,
`create_pull_request`) are deliberately **not** in the MCP surface — orchestrate
those through the FastAPI pipeline instead.

**Resources** (URI-addressable state — the novel part):

| URI | Content |
|---|---|
| `vegapunk://graph/summary` | Build stats + per-file PageRank map |
| `vegapunk://repo/tree` | ASCII file tree of the workspace |

**Resource templates** (parameterized URIs the client constructs):

| Template | Returns |
|---|---|
| `vegapunk://graph/symbols?q={query}` | Symbols matching a substring (exact-match-first) |
| `vegapunk://graph/references/{symbol}` | Every call/import site for a symbol |
| `vegapunk://graph/neighborhood/{file_path}` | Files that import or are imported by the given file |
| `vegapunk://graph/relevant?q={query}` | Top-15 files by hybrid keyword + PageRank score |

Most MCP servers expose only tools. Exposing the repo graph as
**URI-addressable resources** lets clients subscribe, cite, and cache
specific graph slices without invoking a procedural tool every time.

## Install

```bash
pip install .          # from the repo root, installs the `vegapunk-mcp` console script
```

Or via editable install (development):

```bash
pip install -e ".[dev]"
```

## Connect from your IDE

### Claude Code

Add to `~/.config/claude/mcp.json` (or the platform-equivalent path):

```json
{
  "mcpServers": {
    "vegapunk": {
      "command": "vegapunk-mcp",
      "env": {
        "VEGAPUNK_WORKSPACE": "/absolute/path/to/your/project"
      }
    }
  }
}
```

### Cursor

Cursor reads `.cursor/mcp.json` at the project root:

```json
{
  "mcpServers": {
    "vegapunk": {
      "command": "vegapunk-mcp",
      "env": {
        "VEGAPUNK_WORKSPACE": "${workspaceFolder}"
      }
    }
  }
}
```

Alternatively, configure through the Cursor UI: **Settings → MCP → Add server**.

### Cline (VS Code extension)

Cline reads MCP config from its VS Code settings. Add:

```json
"cline.mcpServers": {
  "vegapunk": {
    "command": "vegapunk-mcp",
    "env": {
      "VEGAPUNK_WORKSPACE": "${workspaceFolder}"
    }
  }
}
```

### Any other MCP client (stdio)

The universal shape: run `vegapunk-mcp` as a subprocess and talk to it
over stdio. Alternate invocation if the console script isn't on PATH:

```bash
python -m mcp_server.server
```

## Environment

| Variable | Default | Meaning |
|---|---|---|
| `VEGAPUNK_WORKSPACE` | `$PWD` | Which directory the graph indexes |
| `LOG_LEVEL` | `INFO` | Python logging level. Logs go to **stderr**; stdout is reserved for the MCP protocol stream. |

## Try it manually

Once wired up in a client, ask questions that would be expensive with
plain retrieval:

- *"What files reference `hash_password`?"* → client calls `graph/references/hash_password`
- *"Which files are most relevant to `user login`?"* → `graph/relevant?q=user%20login`
- *"Show me symbols matching `password`."* → `graph/symbols?q=password`
- *"Read `src/api.py` and its neighbors."* → `graph/neighborhood/src/api.py` then `read_file` on each result

The [2026 Codebase-Memory study](https://anthonywest.co.uk/research/code-intelligence-indexing-2026-openai)
reports **~10x fewer tokens and ~2x fewer tool calls** on real repos when
retrieval goes through a tree-sitter graph over MCP vs regex scans.

## Verify locally

```bash
# Import + registration smoke test
python -c "from mcp_server import main; print('ok')"

# Direct read of a resource (bypasses the stdio protocol)
python -c "
import asyncio
import os
os.environ['VEGAPUNK_WORKSPACE'] = 'tests/fixtures/mini_py'
from mcp_server.resources import read_resource
content, mime = asyncio.run(read_resource('vegapunk://graph/summary'))
print(content[:400])
"

# Full test suite
pytest tests/test_mcp_server.py -v
```

## Troubleshooting

- **Client says "server exited"**: check the client's log for the MCP
  server's stderr output (we log there, since stdout is protocol).
- **Empty graph results**: verify `VEGAPUNK_WORKSPACE` points at the
  intended directory and that it contains source files in a supported
  language (py / ts / js / go / rs).
- **`vegapunk-mcp: command not found`**: run `pip install .` in the repo
  (`-e` is fine) so setuptools registers the console script.
