"""Filesystem operations tool with path validation."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from ai_dev_team.tools.base import BaseTool, ToolResult


class FilesystemTool(BaseTool):
    """Read, write, list, and manage files within a sandboxed root."""

    def __init__(self, root_dir: str | None = None):
        self._root = Path(root_dir or os.getcwd()).resolve()

    @property
    def name(self) -> str:
        return "filesystem"

    @property
    def description(self) -> str:
        return (
            "Perform filesystem operations: read, write, list, mkdir, delete files. "
            "All paths are relative to the project root."
        )

    @property
    def parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["read", "write", "list", "mkdir", "delete", "exists"],
                    "description": "The filesystem operation to perform",
                },
                "path": {
                    "type": "string",
                    "description": "Relative file/directory path",
                },
                "content": {
                    "type": "string",
                    "description": "Content to write (for 'write' action)",
                },
            },
            "required": ["action", "path"],
            "additionalProperties": False,
        }

    @property
    def requires_approval(self) -> bool:
        return True

    def _resolve_safe(self, path: str) -> Path | None:
        """Resolve path ensuring it stays within root."""
        resolved = (self._root / path).resolve()
        try:
            resolved.relative_to(self._root)
        except ValueError:
            return None
        return resolved

    async def execute(  # type: ignore[override]
        self, action: str, path: str, content: str | None = None, **kwargs: Any
    ) -> ToolResult:
        target = self._resolve_safe(path)
        if target is None:
            return ToolResult(ok=False, error=f"Path escapes project root: {path}")

        try:
            if action == "read":
                if not target.exists():
                    return ToolResult(ok=False, error=f"File not found: {path}")
                if target.stat().st_size > 1_000_000:
                    return ToolResult(ok=False, error="File too large (>1MB)")
                text = target.read_text(encoding="utf-8", errors="replace")
                return ToolResult(ok=True, data=text)

            elif action == "write":
                if content is None:
                    return ToolResult(ok=False, error="'content' required for write action")
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(content, encoding="utf-8")
                return ToolResult(ok=True, data=f"Wrote {len(content)} chars to {path}")

            elif action == "list":
                if not target.exists():
                    return ToolResult(ok=False, error=f"Directory not found: {path}")
                entries = []
                for entry in sorted(target.iterdir()):
                    rel = entry.relative_to(self._root)
                    kind = "dir" if entry.is_dir() else "file"
                    size = entry.stat().st_size if entry.is_file() else 0
                    entries.append({"path": str(rel), "type": kind, "size": size})
                return ToolResult(ok=True, data=entries)

            elif action == "mkdir":
                target.mkdir(parents=True, exist_ok=True)
                return ToolResult(ok=True, data=f"Created directory: {path}")

            elif action == "delete":
                if not target.exists():
                    return ToolResult(ok=False, error=f"Path not found: {path}")
                if target.is_dir():
                    import shutil

                    shutil.rmtree(target)
                else:
                    target.unlink()
                return ToolResult(ok=True, data=f"Deleted: {path}")

            elif action == "exists":
                return ToolResult(ok=True, data=target.exists())

            else:
                return ToolResult(ok=False, error=f"Unknown action: {action}")

        except PermissionError:
            return ToolResult(ok=False, error=f"Permission denied: {path}")
        except Exception as exc:
            return ToolResult(ok=False, error=f"{type(exc).__name__}: {exc}")
