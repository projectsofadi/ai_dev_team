"""Shell command execution tool with sandboxing."""

from __future__ import annotations

import asyncio
import os
from typing import Any

from ai_dev_team.tools.base import BaseTool, ToolResult


class ShellTool(BaseTool):
    """Execute shell commands with timeout and output capture."""

    def __init__(self, working_dir: str | None = None, allowed_commands: list[str] | None = None):
        self._working_dir = working_dir or os.getcwd()
        self._allowed_commands = allowed_commands

    @property
    def name(self) -> str:
        return "shell"

    @property
    def description(self) -> str:
        return (
            "Execute a shell command and return its output. "
            "Use for running tests, installing packages, building code, or checking system state."
        )

    @property
    def parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "The shell command to execute",
                },
                "working_dir": {
                    "type": "string",
                    "description": "Working directory for the command (defaults to project root)",
                },
                "timeout": {
                    "type": "number",
                    "description": "Timeout in seconds (default: 30)",
                },
            },
            "required": ["command"],
            "additionalProperties": False,
        }

    @property
    def requires_approval(self) -> bool:
        return True

    async def execute(
        self,
        command: str,
        working_dir: str | None = None,
        timeout: float = 30.0,
        **kwargs: Any,
    ) -> ToolResult:
        cwd = working_dir or self._working_dir

        if self._allowed_commands:
            base_cmd = command.split()[0] if command.split() else ""
            if base_cmd not in self._allowed_commands:
                return ToolResult(
                    ok=False,
                    error=f"Command '{base_cmd}' not in allowed list: {self._allowed_commands}",
                )

        try:
            proc = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=cwd,
            )
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=timeout
            )

            output_parts: list[str] = []
            if stdout:
                output_parts.append(stdout.decode("utf-8", errors="replace"))
            if stderr:
                output_parts.append(f"STDERR:\n{stderr.decode('utf-8', errors='replace')}")

            output = "\n".join(output_parts) if output_parts else "(no output)"

            # Truncate very long outputs
            max_len = 50_000
            if len(output) > max_len:
                output = output[:max_len] + f"\n... (truncated, {len(output)} chars total)"

            return ToolResult(
                ok=proc.returncode == 0,
                data=output,
                error=f"Exit code: {proc.returncode}" if proc.returncode != 0 else None,
                meta={"exit_code": proc.returncode, "command": command},
            )

        except asyncio.TimeoutError:
            return ToolResult(ok=False, error=f"Command timed out after {timeout}s")
        except Exception as exc:
            return ToolResult(ok=False, error=f"Shell error: {type(exc).__name__}: {exc}")
