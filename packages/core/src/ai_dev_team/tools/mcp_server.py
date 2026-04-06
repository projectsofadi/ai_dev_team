"""MCP server exposing all built-in tools via FastMCP."""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from ai_dev_team.tools.filesystem import FilesystemTool
from ai_dev_team.tools.git import GitTool
from ai_dev_team.tools.search import SearchTool
from ai_dev_team.tools.shell import ShellTool

_fs = FilesystemTool()
_shell = ShellTool()
_git = GitTool()
_search = SearchTool()

mcp = FastMCP(
    name="ai-dev-team-tools",
    version="0.1.0",
)


@mcp.tool()
async def shell_exec(command: str, working_dir: str | None = None, timeout: float = 30.0) -> str:
    """Execute a shell command and return its output."""
    result = await _shell.execute(command=command, working_dir=working_dir, timeout=timeout)
    return result.to_text()


@mcp.tool()
async def file_read(path: str) -> str:
    """Read the contents of a file."""
    result = await _fs.execute(action="read", path=path)
    return result.to_text()


@mcp.tool()
async def file_write(path: str, content: str) -> str:
    """Write content to a file, creating parent directories as needed."""
    result = await _fs.execute(action="write", path=path, content=content)
    return result.to_text()


@mcp.tool()
async def file_list(path: str = ".") -> str:
    """List files and directories at the given path."""
    result = await _fs.execute(action="list", path=path)
    return result.to_text()


@mcp.tool()
async def file_mkdir(path: str) -> str:
    """Create a directory and any necessary parents."""
    result = await _fs.execute(action="mkdir", path=path)
    return result.to_text()


@mcp.tool()
async def file_delete(path: str) -> str:
    """Delete a file or directory."""
    result = await _fs.execute(action="delete", path=path)
    return result.to_text()


@mcp.tool()
async def git_status(args: str | None = None) -> str:
    """Show the working tree status."""
    result = await _git.execute(action="status", args=args)
    return result.to_text()


@mcp.tool()
async def git_diff(args: str | None = None) -> str:
    """Show changes between commits, commit and working tree, etc."""
    result = await _git.execute(action="diff", args=args)
    return result.to_text()


@mcp.tool()
async def git_log(args: str | None = None) -> str:
    """Show commit history."""
    result = await _git.execute(action="log", args=args)
    return result.to_text()


@mcp.tool()
async def git_add(args: str | None = None) -> str:
    """Stage files for commit."""
    result = await _git.execute(action="add", args=args)
    return result.to_text()


@mcp.tool()
async def git_commit(message: str) -> str:
    """Create a commit with the given message."""
    result = await _git.execute(action="commit", args=message)
    return result.to_text()


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
    result = await _search.execute(
        pattern=pattern,
        path=path,
        file_type=file_type,
        context_lines=context_lines,
        case_insensitive=case_insensitive,
        max_results=max_results,
    )
    return result.to_text()


def run_mcp_server() -> None:
    """Entry point for running the MCP tool server."""
    mcp.run(transport="stdio")


if __name__ == "__main__":
    run_mcp_server()
