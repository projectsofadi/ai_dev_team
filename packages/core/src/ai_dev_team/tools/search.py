"""Code search tool using ripgrep."""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import re
import signal
from pathlib import Path
from typing import Any

from ai_dev_team.tools.base import BaseTool, ToolResult

MAX_SEARCH_OUTPUT_BYTES = 1_000_000
_SAFE_ENV_KEYS: tuple[str, ...] = (
    "LANG",
    "LC_ALL",
    "PATH",
    "TMPDIR",
)


class SearchTool(BaseTool):
    """Search code using ripgrep (rg) with structured results."""

    def __init__(self, root_dir: str | None = None):
        self._root = Path(root_dir or os.getcwd()).resolve()

    def _resolve_safe(self, path: str | None) -> Path | None:
        candidate = Path(path) if path else self._root
        if not candidate.is_absolute():
            candidate = self._root / candidate
        candidate = candidate.resolve()
        try:
            candidate.relative_to(self._root)
        except ValueError:
            return None
        return candidate if candidate.exists() else None

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

    @property
    def name(self) -> str:
        return "search"

    @property
    def description(self) -> str:
        return (
            "Search for patterns in code files using ripgrep. "
            "Supports regex patterns, file type filtering, and context lines."
        )

    @property
    def parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "pattern": {
                    "type": "string",
                    "description": "Regex pattern to search for",
                },
                "path": {
                    "type": "string",
                    "description": "Subdirectory or file to search in (relative to root)",
                },
                "file_type": {
                    "type": "string",
                    "description": "File type filter (e.g., 'py', 'ts', 'js', 'json')",
                },
                "context_lines": {
                    "type": "integer",
                    "description": "Number of context lines around matches (default: 2)",
                },
                "case_insensitive": {
                    "type": "boolean",
                    "description": "Case-insensitive search (default: false)",
                },
                "max_results": {
                    "type": "integer",
                    "description": "Maximum number of matches to return (default: 50)",
                },
            },
            "required": ["pattern"],
            "additionalProperties": False,
        }

    @property
    def is_idempotent(self) -> bool:
        return True

    async def execute(  # type: ignore[override]
        self,
        pattern: str,
        path: str | None = None,
        file_type: str | None = None,
        context_lines: int = 2,
        case_insensitive: bool = False,
        max_results: int = 50,
        **kwargs: Any,
    ) -> ToolResult:
        search_path = self._resolve_safe(path)
        if search_path is None:
            return ToolResult(
                ok=False,
                error="Search path must exist within the configured project root",
            )
        if not 0 <= context_lines <= 20:
            return ToolResult(ok=False, error="context_lines must be between 0 and 20")
        if not 1 <= max_results <= 500:
            return ToolResult(ok=False, error="max_results must be between 1 and 500")

        if not pattern or len(pattern) > 2_000:
            return ToolResult(ok=False, error="pattern must contain 1-2,000 characters")
        if file_type and not re.fullmatch(r"[A-Za-z0-9_+.-]{1,32}", file_type):
            return ToolResult(ok=False, error="Invalid file_type")

        cmd = ["rg", "--json", "-C", str(context_lines)]

        if case_insensitive:
            cmd.append("-i")
        if file_type:
            cmd.extend(["-t", file_type])

        # `--` is a security boundary: without it a model-controlled pattern
        # such as `--pre=...` is parsed as an rg option and can execute a helper.
        cmd.extend(["--", pattern, str(search_path)])

        proc: asyncio.subprocess.Process | None = None
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                cwd=str(self._root),
                env=self._subprocess_env(),
                start_new_session=True,
            )
            matches: list[dict[str, Any]] = []
            total_bytes = 0
            diagnostics: list[str] = []
            truncated = False

            assert proc.stdout is not None
            async with asyncio.timeout(15):
                while raw_line := await proc.stdout.readline():
                    total_bytes += len(raw_line)
                    if total_bytes > MAX_SEARCH_OUTPUT_BYTES:
                        await self._kill_process_group(proc)
                        return ToolResult(
                            ok=False,
                            error="Search output exceeded the 1 MB safety limit",
                        )

                    line = raw_line.decode("utf-8", errors="replace").strip()
                    if not line:
                        continue
                    try:
                        entry = json.loads(line)
                        if entry.get("type") != "match":
                            continue
                        data = entry["data"]
                        rel_path = data["path"]["text"]
                        if Path(rel_path).is_relative_to(self._root):
                            rel_path = os.path.relpath(rel_path, self._root)
                        matches.append(
                            {
                                "file": rel_path,
                                "line": data["line_number"],
                                "text": data["lines"]["text"].rstrip("\n"),
                            }
                        )
                        if len(matches) >= max_results:
                            truncated = True
                            await self._kill_process_group(proc)
                            break
                    except (json.JSONDecodeError, KeyError, TypeError):
                        diagnostics.append(line[:500])

                if proc.returncode is None:
                    await proc.wait()

            if not matches and proc.returncode == 1:
                return ToolResult(ok=True, data="No matches found")
            if not matches and proc.returncode not in (0, 1):
                detail = "\n".join(diagnostics[-5:])
                return ToolResult(ok=False, error=f"ripgrep error: {detail}")

            summary = f"Found {len(matches)} matches"
            if truncated:
                summary += f" (truncated at global limit {max_results})"
            formatted = [summary, ""]
            for m in matches:
                formatted.append(f"{m['file']}:{m['line']}: {m['text']}")

            output = "\n".join(formatted)
            if len(output) > 50_000:
                output = output[:50_000] + "\n... (truncated)"

            return ToolResult(
                ok=True,
                data=output,
                meta={"count": len(matches), "truncated": truncated},
            )

        except FileNotFoundError:
            return ToolResult(
                ok=False,
                error="ripgrep (rg) not found. Install via: brew install ripgrep",
            )
        except TimeoutError:
            await self._kill_process_group(proc)
            return ToolResult(ok=False, error="Search timed out")
        except asyncio.CancelledError:
            await self._kill_process_group(proc)
            raise
        except Exception as exc:
            await self._kill_process_group(proc)
            return ToolResult(ok=False, error=f"Search error: {type(exc).__name__}: {exc}")
