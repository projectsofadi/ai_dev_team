"""Git operations tool."""

from __future__ import annotations

import asyncio
from typing import Any

from ai_dev_team.tools.base import BaseTool, ToolResult


class GitTool(BaseTool):
    """Perform git operations: status, diff, commit, branch, log."""

    def __init__(self, repo_dir: str | None = None):
        self._repo_dir = repo_dir

    @property
    def name(self) -> str:
        return "git"

    @property
    def description(self) -> str:
        return (
            "Perform git operations on the project repository. "
            "Supports: status, diff, log, add, commit, branch, checkout, stash."
        )

    @property
    def parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": [
                        "status", "diff", "log", "add", "commit",
                        "branch", "checkout", "stash", "show",
                    ],
                    "description": "The git operation to perform",
                },
                "args": {
                    "type": "string",
                    "description": "Additional arguments (e.g., file paths, commit message, branch name)",
                },
            },
            "required": ["action"],
            "additionalProperties": False,
        }

    @property
    def is_idempotent(self) -> bool:
        return False

    @property
    def requires_approval(self) -> bool:
        return True

    async def _run_git(self, *args: str) -> tuple[int, str, str]:
        cmd = ["git"] + list(args)
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=self._repo_dir,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=15)
        return (
            proc.returncode or 0,
            stdout.decode("utf-8", errors="replace"),
            stderr.decode("utf-8", errors="replace"),
        )

    async def execute(
        self, action: str, args: str | None = None, **kwargs: Any
    ) -> ToolResult:
        extra = args.split() if args else []

        try:
            if action == "status":
                code, out, err = await self._run_git("status", "--short", *extra)
            elif action == "diff":
                code, out, err = await self._run_git("diff", *extra)
            elif action == "log":
                default_log = ["--oneline", "-20"]
                code, out, err = await self._run_git("log", *(extra or default_log))
            elif action == "add":
                targets = extra or ["."]
                code, out, err = await self._run_git("add", *targets)
            elif action == "commit":
                if not extra:
                    return ToolResult(ok=False, error="Commit message required in args")
                code, out, err = await self._run_git("commit", "-m", " ".join(extra))
            elif action == "branch":
                code, out, err = await self._run_git("branch", *extra)
            elif action == "checkout":
                if not extra:
                    return ToolResult(ok=False, error="Branch name required in args")
                code, out, err = await self._run_git("checkout", *extra)
            elif action == "stash":
                code, out, err = await self._run_git("stash", *extra)
            elif action == "show":
                code, out, err = await self._run_git("show", *extra)
            else:
                return ToolResult(ok=False, error=f"Unknown git action: {action}")

            output = out.strip()
            if err.strip():
                output += f"\nSTDERR: {err.strip()}"

            if len(output) > 50_000:
                output = output[:50_000] + "\n... (truncated)"

            return ToolResult(
                ok=code == 0,
                data=output or "(no output)",
                error=f"Git exited with code {code}" if code != 0 else None,
                meta={"action": action},
            )

        except asyncio.TimeoutError:
            return ToolResult(ok=False, error="Git command timed out")
        except Exception as exc:
            return ToolResult(ok=False, error=f"Git error: {type(exc).__name__}: {exc}")
