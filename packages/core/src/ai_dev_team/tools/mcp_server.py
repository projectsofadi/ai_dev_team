"""MCP server exposing all built-in tools via FastMCP."""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from ai_dev_team.llm.provider import ToolCall
from ai_dev_team.tools.filesystem import FilesystemTool
from ai_dev_team.tools.git import GitTool
from ai_dev_team.tools.registry import ToolRegistry
from ai_dev_team.tools.search import SearchTool
from ai_dev_team.tools.shell import ShellTool

_registry = ToolRegistry(
    [FilesystemTool(), ShellTool(), GitTool(), SearchTool()],
    enforce_configured_approvals=True,
)

mcp = FastMCP(name="ai-dev-team-tools")


async def _invoke(name: str, arguments: dict[str, object]) -> str:
    cleaned = {key: value for key, value in arguments.items() if value is not None}
    result = await _registry.execute(ToolCall(name=name, arguments=cleaned))
    return result.output


@mcp.tool()
async def shell_exec(command: str, working_dir: str | None = None, timeout: float = 30.0) -> str:
    """Execute a shell command and return its output."""
    return await _invoke(
        "shell",
        {"command": command, "working_dir": working_dir, "timeout": timeout},
    )


@mcp.tool()
async def file_read(path: str) -> str:
    """Read the contents of a file."""
    return await _invoke("filesystem", {"action": "read", "path": path})


@mcp.tool()
async def file_write(path: str, content: str) -> str:
    """Write content to a file, creating parent directories as needed."""
    return await _invoke(
        "filesystem",
        {"action": "write", "path": path, "content": content},
    )


@mcp.tool()
async def file_list(path: str = ".") -> str:
    """List files and directories at the given path."""
    return await _invoke("filesystem", {"action": "list", "path": path})


@mcp.tool()
async def file_mkdir(path: str) -> str:
    """Create a directory and any necessary parents."""
    return await _invoke("filesystem", {"action": "mkdir", "path": path})


@mcp.tool()
async def file_delete(path: str) -> str:
    """Delete a file or directory."""
    return await _invoke("filesystem", {"action": "delete", "path": path})


@mcp.tool()
async def git_status(args: str | None = None) -> str:
    """Show the working tree status."""
    return await _invoke("git", {"action": "status", "args": args})


@mcp.tool()
async def git_diff(args: str | None = None) -> str:
    """Show changes between commits, commit and working tree, etc."""
    return await _invoke("git", {"action": "diff", "args": args})


@mcp.tool()
async def git_log(args: str | None = None) -> str:
    """Show commit history."""
    return await _invoke("git", {"action": "log", "args": args})


@mcp.tool()
async def git_add(args: str | None = None) -> str:
    """Stage files for commit."""
    return await _invoke("git", {"action": "add", "args": args})


@mcp.tool()
async def git_commit(message: str) -> str:
    """Create a commit with the given message."""
    return await _invoke("git", {"action": "commit", "args": message})


@mcp.tool()
async def code_search(
    pattern: str,
    path: str | None = None,
    file_type: str | None = None,
    context_lines: int = 2,
    case_insensitive: bool = False,
    max_results: int = 50,
) -> str:
    """Search code files for a regex pattern using ripgrep."""
    return await _invoke(
        "search",
        {
            "pattern": pattern,
            "path": path,
            "file_type": file_type,
            "context_lines": context_lines,
            "case_insensitive": case_insensitive,
            "max_results": max_results,
        },
    )


def run_mcp_server() -> None:
    """Entry point for running the MCP tool server."""
    mcp.run(transport="stdio")


if __name__ == "__main__":
    run_mcp_server()
