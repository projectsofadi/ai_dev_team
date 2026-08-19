"""Git operations tool."""

from __future__ import annotations

import asyncio
import contextlib
import os
import signal
from typing import Any

from ai_dev_team.tools.base import BaseTool, ToolResult

MAX_GIT_OUTPUT_BYTES = 1_000_000
GIT_TIMEOUT_SECONDS = 15.0
_READ_CHUNK_BYTES = 64 * 1024
_SAFE_ENV_KEYS: tuple[str, ...] = (
    "LANG",
    "LC_ALL",
    "PATH",
    "TMPDIR",
)


class _GitOutputLimitError(RuntimeError):
    pass


class GitTool(BaseTool):
    """Perform git operations: status, diff, commit, branch, log."""

    def __init__(
        self,
        repo_dir: str | None = None,
        *,
        timeout_seconds: float = GIT_TIMEOUT_SECONDS,
        max_output_bytes: int = MAX_GIT_OUTPUT_BYTES,
    ):
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        if max_output_bytes <= 0:
            raise ValueError("max_output_bytes must be positive")
        self._repo_dir = repo_dir
        self._timeout_seconds = timeout_seconds
        self._max_output_bytes = max_output_bytes

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
                        "status",
                        "diff",
                        "log",
                        "add",
                        "commit",
                        "branch",
                        "checkout",
                        "stash",
                        "show",
                    ],
                    "description": "The git operation to perform",
                },
                "args": {
                    "type": "string",
                    "description": (
                        "Additional arguments (for example file paths, "
                        "commit message, or branch name)"
                    ),
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

    @staticmethod
    def _subprocess_env() -> dict[str, str]:
        env = {key: os.environ[key] for key in _SAFE_ENV_KEYS if key in os.environ}
        env.update(
            {
                "GIT_CONFIG_NOSYSTEM": "1",
                "GIT_CONFIG_GLOBAL": os.devnull,
                "GIT_TERMINAL_PROMPT": "0",
                "GIT_PAGER": "cat",
                "PAGER": "cat",
            }
        )
        return env

    @staticmethod
    async def _kill_process_group(proc: asyncio.subprocess.Process | None) -> None:
        if proc is None:
            return
        # The direct Git process may already have exited while a configured
        # helper still owns inherited pipes. Always target the whole session.
        with contextlib.suppress(ProcessLookupError):
            os.killpg(proc.pid, signal.SIGKILL)
        with contextlib.suppress(ProcessLookupError):
            await proc.wait()

    async def _read_bounded(
        self,
        stream: asyncio.StreamReader,
        total_bytes: list[int],
    ) -> bytes:
        chunks: list[bytes] = []
        while chunk := await stream.read(_READ_CHUNK_BYTES):
            total_bytes[0] += len(chunk)
            if total_bytes[0] > self._max_output_bytes:
                raise _GitOutputLimitError(
                    f"Git output exceeded the {self._max_output_bytes:,}-byte safety limit"
                )
            chunks.append(chunk)
        return b"".join(chunks)

    async def _communicate_bounded(
        self,
        proc: asyncio.subprocess.Process,
    ) -> tuple[bytes, bytes]:
        assert proc.stdout is not None
        assert proc.stderr is not None
        total_bytes = [0]
        stdout_task = asyncio.create_task(self._read_bounded(proc.stdout, total_bytes))
        stderr_task = asyncio.create_task(self._read_bounded(proc.stderr, total_bytes))
        try:
            stdout, stderr = await asyncio.gather(stdout_task, stderr_task)
            await proc.wait()
            return stdout, stderr
        finally:
            stdout_task.cancel()
            stderr_task.cancel()
            await asyncio.gather(stdout_task, stderr_task, return_exceptions=True)

    async def _run_git(self, *args: str) -> tuple[int, str, str]:
        cmd = ["git"] + list(args)
        proc: asyncio.subprocess.Process | None = None
        try:
            async with asyncio.timeout(self._timeout_seconds):
                proc = await asyncio.create_subprocess_exec(
                    *cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    cwd=self._repo_dir,
                    env=self._subprocess_env(),
                    start_new_session=True,
                )
                stdout, stderr = await self._communicate_bounded(proc)
                assert proc.returncode is not None
                return (
                    proc.returncode,
                    stdout.decode("utf-8", errors="replace"),
                    stderr.decode("utf-8", errors="replace"),
                )
        except BaseException:
            await self._kill_process_group(proc)
            raise

    async def execute(  # type: ignore[override]
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

        except TimeoutError:
            return ToolResult(ok=False, error="Git command timed out")
        except _GitOutputLimitError as exc:
            return ToolResult(ok=False, error=str(exc))
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            return ToolResult(ok=False, error=f"Git error: {type(exc).__name__}: {exc}")
