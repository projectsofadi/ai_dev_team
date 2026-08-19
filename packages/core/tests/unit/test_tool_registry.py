"""Unit tests for the ToolRegistry."""

from __future__ import annotations

from typing import Any

import pytest

from ai_dev_team.llm.provider import ToolCall
from ai_dev_team.tools.base import BaseTool, ToolResult
from ai_dev_team.tools.registry import ToolRegistry


class EchoTool(BaseTool):
    @property
    def name(self) -> str:
        return "echo"

    @property
    def description(self) -> str:
        return "Echoes input"

    @property
    def parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {"text": {"type": "string"}},
            "required": ["text"],
            "additionalProperties": False,
        }

    @property
    def is_idempotent(self) -> bool:
        return True

    async def execute(self, text: str = "", **kwargs: Any) -> ToolResult:
        return ToolResult(ok=True, data=text)


class SlowTool(BaseTool):
    @property
    def name(self) -> str:
        return "slow"

    @property
    def description(self) -> str:
        return "Takes forever"

    @property
    def parameters_schema(self) -> dict[str, Any]:
        return {"type": "object", "properties": {}}

    async def execute(self, **kwargs: Any) -> ToolResult:
        import asyncio

        await asyncio.sleep(100)
        return ToolResult(ok=True)


class FailTool(BaseTool):
    @property
    def name(self) -> str:
        return "fail"

    @property
    def description(self) -> str:
        return "Always fails"

    @property
    def parameters_schema(self) -> dict[str, Any]:
        return {"type": "object", "properties": {}}

    async def execute(self, **kwargs: Any) -> ToolResult:
        raise RuntimeError("boom")


class ApprovalTool(EchoTool):
    @property
    def name(self) -> str:
        return "approval"

    @property
    def requires_approval(self) -> bool:
        return True


@pytest.fixture
def registry():
    return ToolRegistry([EchoTool(), SlowTool(), FailTool()])


class TestToolRegistry:
    def test_register_and_list(self, registry: ToolRegistry):
        assert "echo" in registry.tool_names
        assert "slow" in registry.tool_names
        assert len(registry.list_definitions()) == 3

    def test_get_tool(self, registry: ToolRegistry):
        assert registry.get("echo") is not None
        assert registry.get("nonexistent") is None

    def test_unregister(self, registry: ToolRegistry):
        registry.unregister("slow")
        assert "slow" not in registry.tool_names

    async def test_execute_success(self, registry: ToolRegistry):
        call = ToolCall(id="c1", name="echo", arguments={"text": "hello"})
        result = await registry.execute(call)
        assert not result.is_error
        assert "hello" in result.output

    async def test_execute_unknown_tool(self, registry: ToolRegistry):
        call = ToolCall(id="c2", name="nope", arguments={})
        result = await registry.execute(call)
        assert result.is_error
        assert "Unknown tool" in result.output

    async def test_rejects_invalid_arguments_before_execution(self, registry: ToolRegistry):
        call = ToolCall(id="bad", name="echo", arguments={"text": 123})
        result = await registry.execute(call)
        assert result.is_error
        assert "Invalid tool arguments" in result.output

    async def test_blocks_secret_bearing_tool_output(self, registry: ToolRegistry):
        call = ToolCall(
            id="secret",
            name="echo",
            arguments={"text": "sk-abc123def456ghi789jkl012mno345"},
        )
        result = await registry.execute(call)
        assert result.is_error
        assert "Tool output blocked" in result.output
        assert "sk-abc" not in result.output

    async def test_configured_approval_fails_closed_without_callback(self):
        registry = ToolRegistry(
            [ApprovalTool()],
            enforce_configured_approvals=True,
        )
        call = ToolCall(id="approval", name="approval", arguments={"text": "hello"})
        result = await registry.execute(call)
        assert result.is_error
        assert "Approval required" in result.output
        assert result.error_code == "approval_denied"

    async def test_configured_approval_callback_can_allow_call(self):
        registry = ToolRegistry(
            [ApprovalTool()],
            enforce_configured_approvals=True,
            approval_callback=lambda _tool, _call: True,
        )
        call = ToolCall(id="approval", name="approval", arguments={"text": "hello"})
        result = await registry.execute(call)
        assert not result.is_error
        assert result.output == "hello"

    async def test_execute_timeout(self, registry: ToolRegistry):
        call = ToolCall(id="c3", name="slow", arguments={})
        result = await registry.execute(call, timeout=0.1)
        assert result.is_error
        assert "timed out" in result.output

    async def test_execute_exception(self, registry: ToolRegistry):
        call = ToolCall(id="c4", name="fail", arguments={})
        result = await registry.execute(call)
        assert result.is_error
        assert "RuntimeError" in result.output
        assert "boom" not in result.output

    async def test_execute_batch(self, registry: ToolRegistry):
        calls = [
            ToolCall(id="b1", name="echo", arguments={"text": "a"}),
            ToolCall(id="b2", name="echo", arguments={"text": "b"}),
        ]
        results = await registry.execute_batch(calls)
        assert len(results) == 2
        assert all(not r.is_error for r in results)

    def test_to_json_schema(self, registry: ToolRegistry):
        schemas = registry.to_json_schema()
        assert len(schemas) == 3
        assert schemas[0]["name"] == "echo"
        assert schemas[0]["idempotent"] is True
