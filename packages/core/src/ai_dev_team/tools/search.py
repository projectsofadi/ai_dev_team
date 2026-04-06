"""Code search tool using ripgrep."""

from __future__ import annotations

import asyncio
import os
from typing import Any

from ai_dev_team.tools.base import BaseTool, ToolResult


class SearchTool(BaseTool):
    """Search code using ripgrep (rg) with structured results."""

    def __init__(self, root_dir: str | None = None):
        self._root = root_dir or os.getcwd()

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

    async def execute(
        self,
        pattern: str,
        path: str | None = None,
        file_type: str | None = None,
        context_lines: int = 2,
        case_insensitive: bool = False,
        max_results: int = 50,
        **kwargs: Any,
    ) -> ToolResult:
        cmd = ["rg", "--json", "-C", str(context_lines), "-m", str(max_results)]

        if case_insensitive:
            cmd.append("-i")
        if file_type:
            cmd.extend(["-t", file_type])

        cmd.append(pattern)

        search_path = os.path.join(self._root, path) if path else self._root
        cmd.append(search_path)

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=self._root,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=15)

            if proc.returncode == 1:
                return ToolResult(ok=True, data="No matches found")

            if proc.returncode and proc.returncode > 1:
                err = stderr.decode("utf-8", errors="replace")
                return ToolResult(ok=False, error=f"ripgrep error: {err}")

            import json

            lines = stdout.decode("utf-8", errors="replace").strip().split("\n")
            matches: list[dict[str, Any]] = []
            for line in lines:
                if not line.strip():
                    continue
                try:
                    entry = json.loads(line)
                    if entry.get("type") == "match":
                        data = entry["data"]
                        rel_path = data["path"]["text"]
                        if rel_path.startswith(self._root):
                            rel_path = os.path.relpath(rel_path, self._root)
                        matches.append({
                            "file": rel_path,
                            "line": data["line_number"],
                            "text": data["lines"]["text"].rstrip("\n"),
                        })
                except (json.JSONDecodeError, KeyError):
                    continue

            summary = f"Found {len(matches)} matches"
            formatted = [summary, ""]
            for m in matches:
                formatted.append(f"{m['file']}:{m['line']}: {m['text']}")

            output = "\n".join(formatted)
            if len(output) > 50_000:
                output = output[:50_000] + "\n... (truncated)"

            return ToolResult(ok=True, data=output, meta={"count": len(matches)})

        except FileNotFoundError:
            return ToolResult(
                ok=False,
                error="ripgrep (rg) not found. Install via: brew install ripgrep",
            )
        except asyncio.TimeoutError:
            return ToolResult(ok=False, error="Search timed out")
        except Exception as exc:
            return ToolResult(ok=False, error=f"Search error: {type(exc).__name__}: {exc}")
