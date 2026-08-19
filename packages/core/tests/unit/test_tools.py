"""Unit tests for the built-in tools."""

from __future__ import annotations

import os
import tempfile

import pytest

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

    async def test_sibling_with_shared_prefix_blocked(self, tmp_dir: str):
        sibling = f"{tmp_dir}-outside"
        os.makedirs(sibling)
        try:
            outside_file = os.path.join(sibling, "secret.txt")
            with open(outside_file, "w") as f:
                f.write("outside")

            tool = FilesystemTool(root_dir=tmp_dir)
            result = await tool.execute(action="read", path=outside_file)

            assert not result.ok
            assert "escapes" in (result.error or "").lower()
        finally:
            if os.path.exists(outside_file):
                os.unlink(outside_file)
            os.rmdir(sibling)

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

    # --- Security regression tests: shell command injection (RCE) --------------
    # ShellTool must (a) deny by default when no allow-list is supplied and
    # (b) never let LLM-supplied shell metacharacters chain extra commands.
    # Each injection test writes a sentinel file and proves the injected `rm`
    # never runs. These FAIL against a fail-open / `/bin/sh -c` implementation.

    async def test_default_denies_unlisted_command(self, shell_tool: ShellTool):
        # No explicit allow-list must NOT mean "run anything" (fail-safe default).
        # `whoami` is deliberately absent from the default allow-list.
        result = await shell_tool.execute(command="whoami")
        assert not result.ok
        assert "not in allowed" in (result.error or "").lower()

    async def test_injection_via_semicolon_blocked(self, tmp_dir: str):
        sentinel = os.path.join(tmp_dir, "sentinel_semi.txt")
        with open(sentinel, "w") as f:
            f.write("keep me")
        tool = ShellTool(working_dir=tmp_dir, allowed_commands=["echo"])
        result = await tool.execute(command=f"echo pwned ; rm -f {sentinel}")
        assert os.path.exists(sentinel), "command chaining via ';' executed rm (RCE)"
        assert not result.ok

    async def test_injection_via_command_substitution_blocked(self, tmp_dir: str):
        sentinel = os.path.join(tmp_dir, "sentinel_subst.txt")
        with open(sentinel, "w") as f:
            f.write("keep me")
        tool = ShellTool(working_dir=tmp_dir, allowed_commands=["echo"])
        result = await tool.execute(command=f"echo $(rm -f {sentinel})")
        assert os.path.exists(sentinel), "command substitution '$(...)' executed rm (RCE)"
        assert not result.ok

    async def test_injection_via_pipe_blocked(self, tmp_dir: str):
        sentinel = os.path.join(tmp_dir, "sentinel_pipe.txt")
        with open(sentinel, "w") as f:
            f.write("keep me")
        tool = ShellTool(working_dir=tmp_dir, allowed_commands=["echo"])
        result = await tool.execute(command=f"echo x | rm -f {sentinel}")
        assert os.path.exists(sentinel), "pipe executed rm (RCE)"
        assert not result.ok

    async def test_quoted_args_preserved(self, tmp_dir: str):
        # Legitimate single commands with quoted args still work under shlex/exec.
        tool = ShellTool(working_dir=tmp_dir, allowed_commands=["echo"])
        result = await tool.execute(command='echo "hello   world"')
        assert result.ok
        assert "hello   world" in (result.data or "")

    async def test_malformed_quotes_handled(self, shell_tool: ShellTool):
        # Unbalanced quotes must fail cleanly, not raise.
        result = await shell_tool.execute(command='echo "unterminated')
        assert not result.ok
        assert result.error

    async def test_working_directory_escape_blocked(self, shell_tool: ShellTool, tmp_dir: str):
        result = await shell_tool.execute(command="pwd", working_dir=os.path.dirname(tmp_dir))
        assert not result.ok
        assert "project root" in (result.error or "")

    async def test_subprocess_environment_excludes_provider_secrets(
        self,
        shell_tool: ShellTool,
        monkeypatch: pytest.MonkeyPatch,
    ):
        monkeypatch.setenv("OPENAI_API_KEY", "sk-secret-that-must-not-reach-tools")
        result = await shell_tool.execute(command="env")
        assert result.ok
        assert "sk-secret" not in (result.data or "")
        assert "OPENAI_API_KEY" not in (result.data or "")


class TestSearchTool:
    async def test_search_path_traversal_blocked(self, tmp_dir: str):
        tool = SearchTool(root_dir=tmp_dir)
        result = await tool.execute(pattern="secret", path="..")
        assert not result.ok
        assert "project root" in (result.error or "")

    async def test_absolute_search_path_outside_root_blocked(self, tmp_dir: str):
        tool = SearchTool(root_dir=tmp_dir)
        result = await tool.execute(pattern="secret", path="/etc")
        assert not result.ok
        assert "project root" in (result.error or "")

    async def test_option_like_pattern_cannot_execute_ripgrep_preprocessor(
        self,
        tmp_dir: str,
    ):
        preprocessor = os.path.join(tmp_dir, "evil-preprocessor")
        sentinel = os.path.join(tmp_dir, "executed.txt")
        with open(preprocessor, "w") as f:
            f.write(f'#!/bin/sh\nprintf executed > "{sentinel}"\ncat\n')
        os.chmod(preprocessor, 0o700)
        with open(os.path.join(tmp_dir, "source.txt"), "w") as f:
            f.write("ordinary content")

        tool = SearchTool(root_dir=tmp_dir)
        await tool.execute(pattern=f"--pre={preprocessor}")

        assert not os.path.exists(sentinel)
