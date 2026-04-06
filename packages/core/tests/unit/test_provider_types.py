"""Unit tests for LLM provider types and abstractions."""

from __future__ import annotations

from ai_dev_team.llm.provider import (
    ChatMessage,
    LLMResponse,
    Role,
    StreamChunk,
    TokenUsage,
    ToolCall,
    ToolDefinition,
)


class TestTokenUsage:
    def test_total_tokens(self):
        usage = TokenUsage(input_tokens=100, output_tokens=50)
        assert usage.total_tokens == 150

    def test_defaults(self):
        usage = TokenUsage()
        assert usage.input_tokens == 0
        assert usage.output_tokens == 0
        assert usage.total_tokens == 0


class TestToolCall:
    def test_auto_id(self):
        tc = ToolCall(name="test", arguments={"key": "val"})
        assert tc.id
        assert tc.name == "test"
        assert tc.arguments == {"key": "val"}


class TestChatMessage:
    def test_user_message(self):
        msg = ChatMessage(role=Role.USER, content="Hello")
        assert msg.role == Role.USER
        assert msg.content == "Hello"
        assert msg.tool_calls == []
        assert msg.tool_result is None

    def test_assistant_with_tool_calls(self):
        tc = ToolCall(name="search", arguments={"q": "test"})
        msg = ChatMessage(role=Role.ASSISTANT, tool_calls=[tc])
        assert len(msg.tool_calls) == 1
        assert msg.tool_calls[0].name == "search"


class TestToolDefinition:
    def test_creation(self):
        defn = ToolDefinition(
            name="my_tool",
            description="Does stuff",
            parameters={"type": "object", "properties": {}},
        )
        assert defn.name == "my_tool"
        assert defn.strict is True


class TestLLMResponse:
    def test_basic_response(self):
        resp = LLMResponse(
            message=ChatMessage(role=Role.ASSISTANT, content="Hi"),
            usage=TokenUsage(input_tokens=10, output_tokens=5),
            model="gpt-4o",
            finish_reason="stop",
        )
        assert resp.message.content == "Hi"
        assert resp.usage.total_tokens == 15
        assert resp.finish_reason == "stop"


class TestStreamChunk:
    def test_text_chunk(self):
        chunk = StreamChunk(delta_content="hello")
        assert chunk.delta_content == "hello"
        assert chunk.tool_calls == []
        assert chunk.finish_reason is None
