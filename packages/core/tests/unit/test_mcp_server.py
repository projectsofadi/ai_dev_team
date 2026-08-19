"""Security contract tests for the MCP facade."""

from __future__ import annotations

import shutil

import pytest

import ai_dev_team.config as config_module
from ai_dev_team.tools.mcp_server import (
    code_search,
    file_delete,
    file_read,
    file_write,
    git_status,
    shell_exec,
)


@pytest.fixture(autouse=True)
def safe_approval_defaults(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("REQUIRE_APPROVAL_FOR_WRITES", "true")
    monkeypatch.setenv("REQUIRE_APPROVAL_FOR_SHELL", "true")
    config_module._settings = None
    yield
    config_module._settings = None


async def test_mcp_write_and_delete_fail_closed_without_approval() -> None:
    assert "Approval required" in await file_write("should-not-exist.txt", "content")
    assert "Approval required" in await file_delete("should-not-exist.txt")


async def test_mcp_shell_and_git_fail_closed_without_approval() -> None:
    assert "Approval required" in await shell_exec("echo should-not-run")
    assert "Approval required" in await git_status()


async def test_mcp_read_and_search_remain_available() -> None:
    read_result = await file_read("README.md")
    assert "AI Dev Team" in read_result

    if shutil.which("rg") is None:
        pytest.skip("ripgrep (rg) not installed - search availability needs the binary")

    search_result = await code_search(
        "class SearchTool",
        path="packages/core/src/ai_dev_team/tools/search.py",
    )
    assert "Found 1 matches" in search_result
