"""Tests for filesystem tools."""

import os
import tempfile

import pytest

from tools.filesystem import list_directory, read_file, search_files, write_file


@pytest.mark.asyncio
async def test_write_and_read_file():
    """Test writing and reading a file."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
        tmp_path = f.name

    try:
        # Write
        result = await write_file(tmp_path, "Hello, World!\nLine 2\nLine 3")
        assert result["success"] is True

        # Read all
        result = await read_file(tmp_path)
        assert "Hello, World!" in result["content"]
        assert result["total_lines"] == 3

        # Read specific lines
        result = await read_file(tmp_path, start_line=2, end_line=3)
        assert "Line 2" in result["content"]
        assert "Line 3" in result["content"]
    finally:
        os.unlink(tmp_path)


@pytest.mark.asyncio
async def test_read_nonexistent_file():
    """Test reading a file that doesn't exist."""
    result = await read_file("/nonexistent/path/file.txt")
    assert "error" in result


@pytest.mark.asyncio
async def test_list_directory():
    """Test listing a temporary directory."""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create some test files
        open(os.path.join(tmpdir, "test.py"), "w").close()
        open(os.path.join(tmpdir, "README.md"), "w").close()
        os.makedirs(os.path.join(tmpdir, "src"))
        open(os.path.join(tmpdir, "src", "main.py"), "w").close()

        result = await list_directory(tmpdir)
        assert result["total"] >= 3
        names = [e["name"] for e in result["entries"]]
        assert "test.py" in names
        assert "README.md" in names


@pytest.mark.asyncio
async def test_search_files():
    """Test searching within files."""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create files with searchable content
        with open(os.path.join(tmpdir, "app.py"), "w") as f:
            f.write("def main():\n    print('hello')\n")
        with open(os.path.join(tmpdir, "utils.py"), "w") as f:
            f.write("def helper():\n    return 42\n")

        result = await search_files(tmpdir, "def main")
        assert result["total"] >= 1
        assert any("app.py" in m["file"] for m in result["matches"])
