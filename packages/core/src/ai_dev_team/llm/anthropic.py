"""Anthropic LLM provider using the Messages API."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import anthropic

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


class AnthropicProvider(LLMProvider):
    def __init__(self, api_key: str | None = None, default_model: str | None = None):
        settings = get_settings()
        self._client = anthropic.AsyncAnthropic(api_key=api_key or settings.llm.anthropic_api_key)
        self._default_model = default_model or settings.llm.anthropic_model

    @property
    def provider_name(self) -> str:
        return "anthropic"

    def _build_messages(self, messages: list[ChatMessage]) -> tuple[str, list[dict[str, Any]]]:
        """Split system prompt from conversation and convert to Anthropic format."""
        system_prompt = ""
        anthropic_msgs: list[dict[str, Any]] = []

        for msg in messages:
            if msg.role == Role.SYSTEM:
                system_prompt = msg.content
                continue

            if msg.role == Role.TOOL and msg.tool_result:
                anthropic_msgs.append(
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "tool_result",
                                "tool_use_id": msg.tool_result.call_id,
                                "content": msg.tool_result.output,
                                "is_error": msg.tool_result.is_error,
                            }
                        ],
                    }
                )
            elif msg.role == Role.ASSISTANT and msg.tool_calls:
                content: list[dict[str, Any]] = []
                if msg.content:
                    content.append({"type": "text", "text": msg.content})
                for tc in msg.tool_calls:
                    content.append(
                        {
                            "type": "tool_use",
                            "id": tc.id,
                            "name": tc.name,
                            "input": tc.arguments,
                        }
                    )
                anthropic_msgs.append({"role": "assistant", "content": content})
            elif msg.role == Role.ASSISTANT:
                anthropic_msgs.append(
                    {
                        "role": "assistant",
                        "content": msg.content,
                    }
                )
            elif msg.role == Role.USER:
                anthropic_msgs.append(
                    {
                        "role": "user",
                        "content": msg.content,
                    }
                )

        return system_prompt, anthropic_msgs

    def _build_tools(self, tools: list[ToolDefinition]) -> list[dict[str, Any]]:
        return [
            {
                "name": t.name,
                "description": t.description,
                "input_schema": t.parameters,
            }
            for t in tools
        ]

    def _parse_response(self, resp: Any, model: str) -> LLMResponse:
        text_parts: list[str] = []
        tool_calls: list[ToolCall] = []

        for block in resp.content:
            if block.type == "text":
                text_parts.append(block.text)
            elif block.type == "tool_use":
                tool_calls.append(
                    ToolCall(
                        id=block.id,
                        name=block.name,
                        arguments=block.input if isinstance(block.input, dict) else {},
                    )
                )

        return LLMResponse(
            message=ChatMessage(
                role=Role.ASSISTANT,
                content="\n".join(text_parts),
                tool_calls=tool_calls,
            ),
            usage=TokenUsage(
                input_tokens=resp.usage.input_tokens,
                output_tokens=resp.usage.output_tokens,
            ),
            model=model,
            finish_reason=resp.stop_reason or "",
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
        system_prompt, anthropic_msgs = self._build_messages(messages)

        kwargs: dict[str, Any] = {
            "model": model,
            "messages": anthropic_msgs,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        if system_prompt:
            kwargs["system"] = system_prompt
        if tools:
            kwargs["tools"] = self._build_tools(tools)

        resp = await self._client.messages.create(**kwargs)
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
        system_prompt, anthropic_msgs = self._build_messages(messages)

        kwargs: dict[str, Any] = {
            "model": model,
            "messages": anthropic_msgs,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        if system_prompt:
            kwargs["system"] = system_prompt
        if tools:
            kwargs["tools"] = self._build_tools(tools)

        current_tool: dict[str, Any] | None = None

        async with self._client.messages.stream(**kwargs) as stream:
            async for event in stream:
                if (
                    event.type == "content_block_start"
                    and hasattr(event.content_block, "type")
                    and event.content_block.type == "tool_use"
                ):
                    current_tool = {
                        "id": event.content_block.id,
                        "name": event.content_block.name,
                        "arguments": "",
                    }

                elif event.type == "content_block_delta":
                    if hasattr(event.delta, "text"):
                        yield StreamChunk(delta_content=event.delta.text)
                    elif hasattr(event.delta, "partial_json") and current_tool is not None:
                        current_tool["arguments"] += event.delta.partial_json

                elif event.type == "content_block_stop":
                    if current_tool is not None:
                        import json

                        try:
                            args = json.loads(current_tool["arguments"])
                        except json.JSONDecodeError:
                            args = {}
                        yield StreamChunk(
                            tool_calls=[
                                ToolCall(
                                    id=current_tool["id"],
                                    name=current_tool["name"],
                                    arguments=args,
                                )
                            ]
                        )
                        current_tool = None

                elif event.type == "message_delta":
                    finish = getattr(event.delta, "stop_reason", None)
                    usage_info = getattr(event, "usage", None)
                    yield StreamChunk(
                        finish_reason=finish,
                        usage=TokenUsage(output_tokens=usage_info.output_tokens)
                        if usage_info
                        else None,
                    )
