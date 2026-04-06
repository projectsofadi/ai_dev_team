"""BaseAgent with provider-agnostic ReAct execution loop."""

from __future__ import annotations

import asyncio
import hashlib
import time
from typing import Any

import structlog
from pydantic import BaseModel, Field

from ai_dev_team.config import get_settings
from ai_dev_team.llm.provider import (
    ChatMessage,
    LLMProvider,
    LLMResponse,
    Role,
    TokenUsage,
    ToolDefinition,
)
from ai_dev_team.tools.registry import ToolRegistry

logger = structlog.get_logger()


class AgentResult(BaseModel):
    """Final result of an agent run."""

    output: str
    total_usage: TokenUsage = Field(default_factory=TokenUsage)
    iterations: int = 0
    elapsed_seconds: float = 0.0
    tool_calls_made: int = 0
    success: bool = True
    error: str | None = None


class BaseAgent:
    """
    Abstract agent with a ReAct execution loop.

    Subclasses set name, role, instructions, and optionally override
    hooks like on_tool_result or should_continue.
    """

    name: str = "agent"
    role: str = "general"
    instructions: str = "You are a helpful assistant."
    model: str | None = None
    temperature: float = 0.0
    max_tokens: int = 4096

    def __init__(
        self,
        llm: LLMProvider,
        tools: ToolRegistry | None = None,
        extra_tools: list[ToolDefinition] | None = None,
    ):
        self.llm = llm
        self.tools = tools or ToolRegistry()
        self._extra_tool_defs = extra_tools or []

    def _get_tool_definitions(self) -> list[ToolDefinition]:
        defs = self.tools.list_definitions()
        defs.extend(self._extra_tool_defs)
        return defs

    def _build_system_message(self) -> ChatMessage:
        return ChatMessage(role=Role.SYSTEM, content=self.instructions)

    async def run(
        self,
        user_message: str,
        context: list[ChatMessage] | None = None,
        max_iterations: int | None = None,
        max_tokens_budget: int | None = None,
        timeout: float | None = None,
    ) -> AgentResult:
        """Execute the ReAct loop until completion or limits are hit."""
        settings = get_settings()
        max_iter = max_iterations or settings.agent.max_agent_iterations
        budget = max_tokens_budget or settings.agent.max_tokens_per_task
        wall_timeout = timeout or settings.agent.agent_timeout_seconds

        messages: list[ChatMessage] = [self._build_system_message()]
        if context:
            messages.extend(context)
        messages.append(ChatMessage(role=Role.USER, content=user_message))

        tool_defs = self._get_tool_definitions()
        total_usage = TokenUsage()
        total_tool_calls = 0
        recent_hashes: list[str] = []
        start_time = time.monotonic()

        for iteration in range(1, max_iter + 1):
            elapsed = time.monotonic() - start_time
            if elapsed > wall_timeout:
                return AgentResult(
                    output="",
                    total_usage=total_usage,
                    iterations=iteration,
                    elapsed_seconds=elapsed,
                    tool_calls_made=total_tool_calls,
                    success=False,
                    error=f"Wall-clock timeout after {wall_timeout}s",
                )

            if total_usage.total_tokens > budget:
                return AgentResult(
                    output="",
                    total_usage=total_usage,
                    iterations=iteration,
                    elapsed_seconds=elapsed,
                    tool_calls_made=total_tool_calls,
                    success=False,
                    error=f"Token budget exceeded: {total_usage.total_tokens}/{budget}",
                )

            try:
                response: LLMResponse = await asyncio.wait_for(
                    self.llm.chat(
                        messages=messages,
                        tools=tool_defs if tool_defs else None,
                        model=self.model,
                        temperature=self.temperature,
                        max_tokens=self.max_tokens,
                    ),
                    timeout=max(wall_timeout - elapsed, 5),
                )
            except asyncio.TimeoutError:
                return AgentResult(
                    output="",
                    total_usage=total_usage,
                    iterations=iteration,
                    elapsed_seconds=time.monotonic() - start_time,
                    tool_calls_made=total_tool_calls,
                    success=False,
                    error="LLM call timed out",
                )
            except Exception as exc:
                return AgentResult(
                    output="",
                    total_usage=total_usage,
                    iterations=iteration,
                    elapsed_seconds=time.monotonic() - start_time,
                    tool_calls_made=total_tool_calls,
                    success=False,
                    error=f"LLM error: {type(exc).__name__}: {exc}",
                )

            total_usage.input_tokens += response.usage.input_tokens
            total_usage.output_tokens += response.usage.output_tokens

            logger.info(
                "agent_iteration",
                agent=self.name,
                iteration=iteration,
                tool_calls=len(response.message.tool_calls),
                finish_reason=response.finish_reason,
                tokens_used=response.usage.total_tokens,
            )

            if not response.message.tool_calls:
                return AgentResult(
                    output=response.message.content,
                    total_usage=total_usage,
                    iterations=iteration,
                    elapsed_seconds=time.monotonic() - start_time,
                    tool_calls_made=total_tool_calls,
                    success=True,
                )

            # Stuck-loop detection: hash the tool calls and check for repeats
            call_hash = hashlib.md5(
                str([(tc.name, tc.arguments) for tc in response.message.tool_calls]).encode()
            ).hexdigest()
            recent_hashes.append(call_hash)
            if len(recent_hashes) > 3:
                recent_hashes.pop(0)
            if len(recent_hashes) == 3 and len(set(recent_hashes)) == 1:
                messages.append(ChatMessage(
                    role=Role.SYSTEM,
                    content=(
                        "You appear to be repeating the same tool calls. "
                        "Try a different approach or provide a final answer."
                    ),
                ))
                recent_hashes.clear()

            messages.append(response.message)

            results = await self.tools.execute_batch(response.message.tool_calls)
            total_tool_calls += len(results)

            for result in results:
                messages.append(ChatMessage(
                    role=Role.TOOL,
                    tool_result=result,
                ))

        return AgentResult(
            output="",
            total_usage=total_usage,
            iterations=max_iter,
            elapsed_seconds=time.monotonic() - start_time,
            tool_calls_made=total_tool_calls,
            success=False,
            error=f"Max iterations ({max_iter}) reached",
        )
