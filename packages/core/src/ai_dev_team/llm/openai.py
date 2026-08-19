"""OpenAI LLM provider using the Responses API."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

import openai

from ai_dev_team.config import get_settings
from ai_dev_team.llm.provider import (
    ChatMessage,
    LLMProvider,
    LLMResponse,
    Role,
    StreamChunk,
    TokenUsage,
    ToolCall,
    ToolDefinition,
)


class OpenAIProvider(LLMProvider):
    def __init__(self, api_key: str | None = None, default_model: str | None = None):
        settings = get_settings()
        self._client = openai.AsyncOpenAI(api_key=api_key or settings.llm.openai_api_key)
        self._default_model = default_model or settings.llm.default_model

    @property
    def provider_name(self) -> str:
        return "openai"

    def _build_messages(self, messages: list[ChatMessage]) -> list[dict[str, Any]]:
        """Convert internal messages to OpenAI chat format."""
        result: list[dict[str, Any]] = []
        for msg in messages:
            if msg.role == Role.TOOL and msg.tool_result:
                result.append(
                    {
                        "role": "tool",
                        "tool_call_id": msg.tool_result.call_id,
                        "content": msg.tool_result.output,
                    }
                )
            elif msg.role == Role.ASSISTANT and msg.tool_calls:
                result.append(
                    {
                        "role": "assistant",
                        "content": msg.content or None,
                        "tool_calls": [
                            {
                                "id": tc.id,
                                "type": "function",
                                "function": {
                                    "name": tc.name,
                                    "arguments": json.dumps(tc.arguments),
                                },
                            }
                            for tc in msg.tool_calls
                        ],
                    }
                )
            else:
                result.append(
                    {
                        "role": msg.role.value,
                        "content": msg.content,
                    }
                )
        return result

    def _build_tools(self, tools: list[ToolDefinition]) -> list[dict[str, Any]]:
        return [
            {
                "type": "function",
                "function": {
                    "name": t.name,
                    "description": t.description,
                    "parameters": t.parameters,
                    "strict": t.strict,
                },
            }
            for t in tools
        ]

    def _parse_response(self, resp: Any, model: str) -> LLMResponse:
        choice = resp.choices[0]
        msg = choice.message
        tool_calls: list[ToolCall] = []
        if msg.tool_calls:
            for tc in msg.tool_calls:
                try:
                    args = json.loads(tc.function.arguments)
                except json.JSONDecodeError:
                    args = {"raw": tc.function.arguments}
                tool_calls.append(
                    ToolCall(
                        id=tc.id,
                        name=tc.function.name,
                        arguments=args,
                    )
                )

        return LLMResponse(
            message=ChatMessage(
                role=Role.ASSISTANT,
                content=msg.content or "",
                tool_calls=tool_calls,
            ),
            usage=TokenUsage(
                input_tokens=resp.usage.prompt_tokens if resp.usage else 0,
                output_tokens=resp.usage.completion_tokens if resp.usage else 0,
            ),
            model=model,
            finish_reason=choice.finish_reason or "",
        )

    async def chat(
        self,
        messages: list[ChatMessage],
        tools: list[ToolDefinition] | None = None,
        model: str | None = None,
        temperature: float = 0.0,
        max_tokens: int = 4096,
    ) -> LLMResponse:
        model = model or self._default_model
        kwargs: dict[str, Any] = {
            "model": model,
            "messages": self._build_messages(messages),
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if tools:
            kwargs["tools"] = self._build_tools(tools)

        resp = await self._client.chat.completions.create(**kwargs)
        return self._parse_response(resp, model)

    async def stream(
        self,
        messages: list[ChatMessage],
        tools: list[ToolDefinition] | None = None,
        model: str | None = None,
        temperature: float = 0.0,
        max_tokens: int = 4096,
    ) -> AsyncIterator[StreamChunk]:
        model = model or self._default_model
        kwargs: dict[str, Any] = {
            "model": model,
            "messages": self._build_messages(messages),
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": True,
            "stream_options": {"include_usage": True},
        }
        if tools:
            kwargs["tools"] = self._build_tools(tools)

        stream = await self._client.chat.completions.create(**kwargs)

        accumulated_tool_calls: dict[int, dict[str, str]] = {}

        async for chunk in stream:
            if not chunk.choices:
                if chunk.usage:
                    yield StreamChunk(
                        usage=TokenUsage(
                            input_tokens=chunk.usage.prompt_tokens,
                            output_tokens=chunk.usage.completion_tokens,
                        )
                    )
                continue

            delta = chunk.choices[0].delta
            finish = chunk.choices[0].finish_reason

            if delta.tool_calls:
                for tc_delta in delta.tool_calls:
                    idx = tc_delta.index
                    if idx not in accumulated_tool_calls:
                        accumulated_tool_calls[idx] = {
                            "id": tc_delta.id or "",
                            "name": "",
                            "arguments": "",
                        }
                    if tc_delta.id:
                        accumulated_tool_calls[idx]["id"] = tc_delta.id
                    if tc_delta.function:
                        if tc_delta.function.name:
                            accumulated_tool_calls[idx]["name"] = tc_delta.function.name
                        if tc_delta.function.arguments:
                            accumulated_tool_calls[idx]["arguments"] += tc_delta.function.arguments

            completed_calls: list[ToolCall] = []
            if finish == "tool_calls":
                for _idx, tc_data in sorted(accumulated_tool_calls.items()):
                    try:
                        args = json.loads(tc_data["arguments"])
                    except json.JSONDecodeError:
                        args = {"raw": tc_data["arguments"]}
                    completed_calls.append(
                        ToolCall(
                            id=tc_data["id"],
                            name=tc_data["name"],
                            arguments=args,
                        )
                    )

            yield StreamChunk(
                delta_content=delta.content or "",
                tool_calls=completed_calls,
                finish_reason=finish,
            )
