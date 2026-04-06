"""Tool registry for managing available tools."""

from __future__ import annotations

import asyncio
import time
from typing import Any

import structlog

from ai_dev_team.llm.provider import ToolCall, ToolDefinition
from ai_dev_team.llm.provider import ToolResult as LLMToolResult
from ai_dev_team.tools.base import BaseTool, ToolResult

logger = structlog.get_logger()


class ToolRegistry:
    """Registry that holds tools and executes them by name."""

    def __init__(self, tools: list[BaseTool] | None = None):
        self._tools: dict[str, BaseTool] = {}
        if tools:
            for tool in tools:
                self.register(tool)

    def register(self, tool: BaseTool) -> None:
        self._tools[tool.name] = tool

    def unregister(self, name: str) -> None:
        self._tools.pop(name, None)

    def get(self, name: str) -> BaseTool | None:
        return self._tools.get(name)

    def list_definitions(self) -> list[ToolDefinition]:
        return [t.to_definition() for t in self._tools.values()]

    @property
    def tool_names(self) -> list[str]:
        return list(self._tools.keys())

    async def execute(
        self,
        tool_call: ToolCall,
        timeout: float = 30.0,
    ) -> LLMToolResult:
        """Execute a tool call and return a result suitable for the LLM."""
        tool = self._tools.get(tool_call.name)
        if tool is None:
            return LLMToolResult(
                call_id=tool_call.id,
                output=f"Unknown tool: {tool_call.name}. Available: {', '.join(self.tool_names)}",
                is_error=True,
            )

        start = time.monotonic()
        try:
            result: ToolResult = await asyncio.wait_for(
                tool.execute(**tool_call.arguments),
                timeout=timeout,
            )
            elapsed = time.monotonic() - start
            logger.info(
                "tool_executed",
                tool=tool_call.name,
                ok=result.ok,
                elapsed_ms=round(elapsed * 1000),
            )
            return LLMToolResult(
                call_id=tool_call.id,
                output=result.to_text(),
                is_error=not result.ok,
            )
        except asyncio.TimeoutError:
            return LLMToolResult(
                call_id=tool_call.id,
                output=f"Tool '{tool_call.name}' timed out after {timeout}s",
                is_error=True,
            )
        except Exception as exc:
            logger.error("tool_error", tool=tool_call.name, error=str(exc))
            return LLMToolResult(
                call_id=tool_call.id,
                output=f"Tool '{tool_call.name}' failed: {type(exc).__name__}: {exc}",
                is_error=True,
            )

    async def execute_batch(
        self,
        tool_calls: list[ToolCall],
        timeout: float = 30.0,
        max_concurrency: int = 5,
    ) -> list[LLMToolResult]:
        """Execute multiple tool calls with bounded concurrency."""
        semaphore = asyncio.Semaphore(max_concurrency)

        async def _run(tc: ToolCall) -> LLMToolResult:
            async with semaphore:
                return await self.execute(tc, timeout=timeout)

        return await asyncio.gather(*[_run(tc) for tc in tool_calls])

    def to_json_schema(self) -> list[dict[str, Any]]:
        """Export all tools as JSON-serializable schemas."""
        return [
            {
                "name": t.name,
                "description": t.description,
                "parameters": t.parameters_schema,
                "idempotent": t.is_idempotent,
                "requires_approval": t.requires_approval,
            }
            for t in self._tools.values()
        ]
