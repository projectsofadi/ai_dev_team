"""Shell command execution tool.

Commands run via ``asyncio.create_subprocess_exec`` (NOT a shell), so shell
metacharacters supplied by the LLM (``;`` ``|`` ``&`` ``$()`` `` ` `` redirects)
are never interpreted and cannot chain or inject additional commands. Commands
are further restricted to an allow-list of program names, deny-by-default.

This is a guardrail, not a hermetic sandbox: allow-listed interpreters
(``python``, ``make``, ``npm`` …) can still execute arbitrary code. For real
isolation, run the agent inside a container/VM and enforce approval at the
registry layer (see ``require_approval_for_shell`` in ``config.py``).
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import shlex
import signal
from pathlib import Path
from typing import Any

from ai_dev_team.tools.base import BaseTool, ToolResult

# Program names permitted when no explicit allow-list is supplied. Scoped to
# read / build / test / VCS tooling; destructive (``rm``/``mv``), network
# (``curl``/``wget``/``nc``), privilege-escalation (``sudo``), and shell-reentry
# (``bash``/``sh``) commands are intentionally excluded. File mutations should go
# through ``FilesystemTool``, which is path-traversal guarded.
DEFAULT_ALLOWED_COMMANDS: frozenset[str] = frozenset(
    {
        # inspection
        "ls",
        "cat",
        "head",
        "tail",
        "wc",
        "sort",
        "uniq",
        "cut",
        "tr",
        "grep",
        "egrep",
        "fgrep",
        "rg",
        "find",
        "diff",
        "stat",
        "file",
        "which",
        "env",
        "date",
        "echo",
        "printf",
        "pwd",
        "basename",
        "dirname",
        "realpath",
        "tree",
        "true",
        "false",
        "test",
        "sleep",
        # python
        "python",
        "python3",
        "pip",
        "pip3",
        "uv",
        "pytest",
        "ruff",
        "mypy",
        "black",
        "isort",
        "flake8",
        # node / typescript
        "node",
        "npm",
        "npx",
        "pnpm",
        "yarn",
        "tsc",
        "eslint",
        "prettier",
        "vitest",
        "jest",
        # build / other languages / VCS
        "make",
        "go",
        "cargo",
        "rustc",
        "java",
        "javac",
        "mvn",
        "gradle",
        "git",
    }
)

# Shell control operators that signal an attempt to chain, substitute, background,
# or redirect additional commands. Rejected up-front with a clear error;
# ``create_subprocess_exec`` already neutralises them, but failing loud beats
# silently passing them through as literal arguments.
_SHELL_OPERATORS: tuple[str, ...] = (";", "|", "&", "`", "$(", ">", "<", "\n", "\r")

_SAFE_ENV_KEYS: tuple[str, ...] = (
    "LANG",
    "LC_ALL",
    "PATH",
    "PYTHONPATH",
    "TMPDIR",
    "VIRTUAL_ENV",
)


class ShellTool(BaseTool):
    """Execute a single allow-listed command with timeout and output capture."""

    def __init__(self, working_dir: str | None = None, allowed_commands: list[str] | None = None):
        self._working_dir = Path(working_dir or os.getcwd()).resolve()
        # ``None`` -> safe default allow-list; an explicit list (even empty) is
        # honoured verbatim, so ``allowed_commands=[]`` denies everything.
        self._allowed_commands: frozenset[str] = (
            DEFAULT_ALLOWED_COMMANDS if allowed_commands is None else frozenset(allowed_commands)
        )

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

    def _resolve_working_dir(self, requested: str | None) -> Path | None:
        candidate = Path(requested) if requested else self._working_dir
        if not candidate.is_absolute():
            candidate = self._working_dir / candidate
        candidate = candidate.resolve()
        try:
            candidate.relative_to(self._working_dir)
        except ValueError:
            return None
        return candidate if candidate.is_dir() else None

    @staticmethod
    def _subprocess_env() -> dict[str, str]:
        return {key: os.environ[key] for key in _SAFE_ENV_KEYS if key in os.environ}

    @staticmethod
    async def _kill_process_group(proc: asyncio.subprocess.Process | None) -> None:
        if proc is None or proc.returncode is not None:
            return
        with contextlib.suppress(ProcessLookupError):
            os.killpg(proc.pid, signal.SIGKILL)
        with contextlib.suppress(ProcessLookupError):
            await proc.wait()

    async def execute(  # type: ignore[override]
        self,
        command: str,
        working_dir: str | None = None,
        timeout: float = 30.0,
        **kwargs: Any,
    ) -> ToolResult:
        cwd = self._resolve_working_dir(working_dir)
        if cwd is None:
            return ToolResult(
                ok=False,
                error="Working directory must exist within the configured project root",
            )
        if timeout <= 0 or timeout > 300:
            return ToolResult(ok=False, error="Timeout must be between 0 and 300 seconds")

        # Layer 1: reject shell control operators (chaining / substitution /
        # redirection). Fail loud rather than run one command and silently drop
        # the rest.
        for op in _SHELL_OPERATORS:
            if op in command:
                return ToolResult(
                    ok=False,
                    error=(
                        f"Refused: shell operator {op!r} is not permitted. Run one "
                        "command at a time; use the filesystem tool for file I/O."
                    ),
                )

        # Layer 2: parse without any shell interpretation.
        try:
            argv = shlex.split(command)
        except ValueError as exc:
            return ToolResult(ok=False, error=f"Could not parse command: {exc}")
        if not argv:
            return ToolResult(ok=False, error="Empty command")

        # Layer 3: deny-by-default allow-list on the program name.
        program = argv[0]
        if program not in self._allowed_commands:
            return ToolResult(
                ok=False,
                error=(
                    f"Command '{program}' not in allowed commands: {sorted(self._allowed_commands)}"
                ),
            )

        # Execute directly — no /bin/sh, so metacharacters cannot inject.
        proc: asyncio.subprocess.Process | None = None
        try:
            proc = await asyncio.create_subprocess_exec(
                *argv,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=cwd,
                env=self._subprocess_env(),
                start_new_session=True,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)

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

        except TimeoutError:
            await self._kill_process_group(proc)
            return ToolResult(ok=False, error=f"Command timed out after {timeout}s")
        except asyncio.CancelledError:
            await self._kill_process_group(proc)
            raise
        except FileNotFoundError:
            return ToolResult(ok=False, error=f"Command not found: {argv[0]}")
        except Exception as exc:
            return ToolResult(ok=False, error=f"Shell error: {type(exc).__name__}: {exc}")
