"""Unit tests for the built-in tools."""

from __future__ import annotations

import os
import tempfile

import pytest

from ai_dev_team.tools.base import ToolResult
from ai_dev_team.tools.filesystem import FilesystemTool
from ai_dev_team.tools.search import SearchTool
from ai_dev_team.tools.shell import ShellTool


@pytest.fixture
def tmp_dir():
    with tempfile.TemporaryDirectory() as d:
        yield d


@pytest.fixture
def fs_tool(tmp_dir: str):
    return FilesystemTool(root_dir=tmp_dir)


@pytest.fixture
def shell_tool(tmp_dir: str):
    return ShellTool(working_dir=tmp_dir)


class TestFilesystemTool:
    async def test_write_and_read(self, fs_tool: FilesystemTool, tmp_dir: str):
        result = await fs_tool.execute(action="write", path="test.txt", content="hello world")
        assert result.ok
        assert "Wrote" in (result.data or "")

        result = await fs_tool.execute(action="read", path="test.txt")
        assert result.ok
        assert result.data == "hello world"

    async def test_read_nonexistent(self, fs_tool: FilesystemTool):
        result = await fs_tool.execute(action="read", path="nope.txt")
        assert not result.ok
        assert "not found" in (result.error or "").lower()

    async def test_list_directory(self, fs_tool: FilesystemTool, tmp_dir: str):
        os.makedirs(os.path.join(tmp_dir, "subdir"))
        with open(os.path.join(tmp_dir, "file.txt"), "w") as f:
            f.write("content")

        result = await fs_tool.execute(action="list", path=".")
        assert result.ok
        assert isinstance(result.data, list)
        names = [e["path"] for e in result.data]
        assert "file.txt" in names

    async def test_mkdir(self, fs_tool: FilesystemTool, tmp_dir: str):
        result = await fs_tool.execute(action="mkdir", path="new/nested/dir")
        assert result.ok
        assert os.path.isdir(os.path.join(tmp_dir, "new", "nested", "dir"))

    async def test_delete(self, fs_tool: FilesystemTool, tmp_dir: str):
        with open(os.path.join(tmp_dir, "delete_me.txt"), "w") as f:
            f.write("bye")
        result = await fs_tool.execute(action="delete", path="delete_me.txt")
        assert result.ok
        assert not os.path.exists(os.path.join(tmp_dir, "delete_me.txt"))

    async def test_exists(self, fs_tool: FilesystemTool, tmp_dir: str):
        result = await fs_tool.execute(action="exists", path="nope.txt")
        assert result.ok
        assert result.data is False

    async def test_path_traversal_blocked(self, fs_tool: FilesystemTool):
        result = await fs_tool.execute(action="read", path="../../etc/passwd")
        assert not result.ok
        assert "escapes" in (result.error or "").lower()

    async def test_to_definition(self, fs_tool: FilesystemTool):
        defn = fs_tool.to_definition()
        assert defn.name == "filesystem"
        assert "properties" in defn.parameters


class TestShellTool:
    async def test_echo(self, shell_tool: ShellTool):
        result = await shell_tool.execute(command="echo hello")
        assert result.ok
        assert "hello" in (result.data or "")

    async def test_nonzero_exit(self, shell_tool: ShellTool):
        result = await shell_tool.execute(command="false")
        assert not result.ok

    async def test_timeout(self, shell_tool: ShellTool):
        result = await shell_tool.execute(command="sleep 10", timeout=0.5)
        assert not result.ok
        assert "timed out" in (result.error or "").lower()

    async def test_allowed_commands(self, tmp_dir: str):
        tool = ShellTool(working_dir=tmp_dir, allowed_commands=["echo"])
        result = await tool.execute(command="echo allowed")
        assert result.ok

        result = await tool.execute(command="rm -rf /")
        assert not result.ok
        assert "not in allowed" in (result.error or "").lower()
