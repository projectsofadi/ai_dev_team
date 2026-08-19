"""Tool registry for managing available tools."""

from __future__ import annotations

import asyncio
import inspect
import time
from collections.abc import Awaitable, Callable
from typing import Any

import structlog

from ai_dev_team.config import get_settings
from ai_dev_team.guardrails.validators import validate_output, validate_tool_args
from ai_dev_team.llm.provider import ToolCall, ToolDefinition
from ai_dev_team.llm.provider import ToolResult as LLMToolResult
from ai_dev_team.tools.base import BaseTool, ToolResult

logger = structlog.get_logger()

ApprovalCallback = Callable[[BaseTool, ToolCall], bool | Awaitable[bool]]


class ToolRegistry:
    """Registry that holds tools and executes them by name."""

    def __init__(
        self,
        tools: list[BaseTool] | None = None,
        *,
        enforce_configured_approvals: bool = False,
        approval_callback: ApprovalCallback | None = None,
    ):
        self._tools: dict[str, BaseTool] = {}
        self._enforce_configured_approvals = enforce_configured_approvals
        self._approval_callback = approval_callback
        if tools:
            for tool in tools:
                self.register(tool)

    @staticmethod
    def _is_mutating_call(tool: BaseTool, tool_call: ToolCall) -> bool:
        if tool.name == "filesystem":
            return tool_call.arguments.get("action") in {"write", "mkdir", "delete"}
        if tool.name == "git":
            return tool_call.arguments.get("action") in {
                "add",
                "commit",
                "branch",
                "checkout",
                "stash",
            }
        return tool.requires_approval

    def _approval_is_required(self, tool: BaseTool, tool_call: ToolCall) -> bool:
        if not self._enforce_configured_approvals:
            return False

        settings = get_settings().guardrails
        if tool.name == "shell":
            return settings.require_approval_for_shell
        if tool.name == "git":
            # Even nominally read-only git subcommands accept flags/config that
            # can write files or invoke external helpers. Treat the whole tool as
            # privileged instead of attempting a brittle argv classification.
            return settings.require_approval_for_writes
        if self._is_mutating_call(tool, tool_call):
            return settings.require_approval_for_writes
        return False

    async def _is_approved(self, tool: BaseTool, tool_call: ToolCall) -> bool:
        if not self._approval_is_required(tool, tool_call):
            return True
        if self._approval_callback is None:
            return False

        decision = self._approval_callback(tool, tool_call)
        if inspect.isawaitable(decision):
            decision = await decision
        return bool(decision)

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

        validation = validate_tool_args(tool_call.arguments, tool.parameters_schema)
        if not validation.valid:
            return LLMToolResult(
                call_id=tool_call.id,
                output="Invalid tool arguments: " + "; ".join(validation.violations),
                is_error=True,
            )

        if not await self._is_approved(tool, tool_call):
            return LLMToolResult(
                call_id=tool_call.id,
                output=(
                    f"Approval required for tool '{tool_call.name}'. "
                    "No approval was supplied; the call was not executed."
                ),
                is_error=True,
                error_code="approval_denied",
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
            output = result.to_text()
            output_validation = validate_output(output)
            if not output_validation.valid:
                return LLMToolResult(
                    call_id=tool_call.id,
                    output="Tool output blocked: " + "; ".join(output_validation.violations),
                    is_error=True,
                )

            return LLMToolResult(
                call_id=tool_call.id,
                output=output,
                is_error=not result.ok,
            )
        except TimeoutError:
            return LLMToolResult(
                call_id=tool_call.id,
                output=f"Tool '{tool_call.name}' timed out after {timeout}s",
                is_error=True,
            )
        except Exception as exc:
            logger.error("tool_error", tool=tool_call.name, error_type=type(exc).__name__)
            return LLMToolResult(
                call_id=tool_call.id,
                output=f"Tool '{tool_call.name}' failed: {type(exc).__name__}",
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
