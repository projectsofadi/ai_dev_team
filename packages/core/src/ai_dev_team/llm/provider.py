"""Abstract LLM provider interface and common types."""

from __future__ import annotations

import uuid
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class Role(StrEnum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


class ToolCall(BaseModel):
    """A tool invocation requested by the model."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str
    arguments: dict[str, Any]


class ToolResult(BaseModel):
    """Result of executing a tool."""

    call_id: str
    output: str
    is_error: bool = False
    error_code: str | None = None


class ChatMessage(BaseModel):
    """Provider-agnostic message representation."""

    role: Role
    content: str = ""
    tool_calls: list[ToolCall] = Field(default_factory=list)
    tool_result: ToolResult | None = None
    name: str | None = None


class ToolDefinition(BaseModel):
    """Schema for a tool the model can call."""

    name: str
    description: str
    parameters: dict[str, Any]
    # Most project tools intentionally have optional properties. OpenAI strict
    # schemas require every property to be listed in `required`, so opt out and
    # enforce the schema again inside ToolRegistry before execution.
    strict: bool = False


class TokenUsage(BaseModel):
    """Token counts from a single LLM call."""

    input_tokens: int = 0
    output_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


class LLMResponse(BaseModel):
    """Unified response from any LLM provider."""

    message: ChatMessage
    usage: TokenUsage = Field(default_factory=TokenUsage)
    model: str = ""
    finish_reason: str = ""
    raw: dict[str, Any] = Field(default_factory=dict)


class StreamChunk(BaseModel):
    """A single chunk from a streaming response."""

    delta_content: str = ""
    tool_calls: list[ToolCall] = Field(default_factory=list)
    finish_reason: str | None = None
    usage: TokenUsage | None = None


class LLMProvider(ABC):
    """Abstract base for LLM providers."""

    @property
    @abstractmethod
    def provider_name(self) -> str: ...

    @abstractmethod
    async def chat(
        self,
        messages: list[ChatMessage],
        tools: list[ToolDefinition] | None = None,
        model: str | None = None,
        temperature: float = 0.0,
        max_tokens: int = 4096,
    ) -> LLMResponse:
        """Single-turn completion."""
        ...

    @abstractmethod
    def stream(
        self,
        messages: list[ChatMessage],
        tools: list[ToolDefinition] | None = None,
        model: str | None = None,
        temperature: float = 0.0,
        max_tokens: int = 4096,
    ) -> AsyncIterator[StreamChunk]:
        """Streaming completion yielding chunks."""
        raise NotImplementedError
