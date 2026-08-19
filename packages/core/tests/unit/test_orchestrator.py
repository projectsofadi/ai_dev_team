"""Lifecycle regression tests for the orchestrator task bridge."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any, cast
from unittest.mock import AsyncMock

import pytest

import ai_dev_team.config as config_module
from ai_dev_team.agents.base import AgentResult, BaseAgent
from ai_dev_team.agents.orchestrator import OrchestratorAgent
from ai_dev_team.llm.provider import (
    ChatMessage,
    LLMProvider,
    LLMResponse,
    Role,
    StreamChunk,
    ToolCall,
    ToolDefinition,
)
from ai_dev_team.orchestration.state import Task, TaskState
from ai_dev_team.tools.base import BaseTool, ToolResult
from ai_dev_team.tools.registry import ToolRegistry


def orchestrator_with_result(result: AgentResult) -> OrchestratorAgent:
    orchestrator = cast(OrchestratorAgent, object.__new__(OrchestratorAgent))
    orchestrator.run = AsyncMock(return_value=result)  # type: ignore[method-assign]
    return orchestrator


async def test_zero_handoffs_cannot_reach_completed_state() -> None:
    orchestrator = orchestrator_with_result(AgentResult(output="done"))
    task = await orchestrator.run_task(Task(description="do work"))

    assert task.state is TaskState.FAILED
    assert task.result is None
    assert task.error
    assert "Incomplete handoff sequence" in task.error
    assert [event.to_state for event in task.events] == [
        TaskState.PLANNING,
        TaskState.EXECUTING,
        TaskState.FAILED,
    ]


async def test_failed_task_reaches_failed_state() -> None:
    orchestrator = orchestrator_with_result(
        AgentResult(output="", success=False, error="provider failed")
    )
    task = await orchestrator.run_task(Task(description="do work"))

    assert task.state is TaskState.FAILED
    assert task.error == "provider failed"


class SequencedProvider(LLMProvider):
    def __init__(self, responses: list[LLMResponse]):
        self.responses = responses

    @property
    def provider_name(self) -> str:
        return "test"

    async def chat(
        self,
        messages: list[ChatMessage],
        tools: list[ToolDefinition] | None = None,
        model: str | None = None,
        temperature: float = 0.0,
        max_tokens: int = 4096,
    ) -> LLMResponse:
        return self.responses.pop(0)

    async def stream(
        self,
        messages: list[ChatMessage],
        tools: list[ToolDefinition] | None = None,
        model: str | None = None,
        temperature: float = 0.0,
        max_tokens: int = 4096,
    ) -> AsyncIterator[StreamChunk]:
        if False:
            yield StreamChunk()


def handoff_response(agent_name: str, call_id: str) -> LLMResponse:
    return LLMResponse(
        message=ChatMessage(
            role=Role.ASSISTANT,
            tool_calls=[
                ToolCall(
                    id=call_id,
                    name=f"transfer_to_{agent_name}",
                    arguments={"task": f"run {agent_name} stage"},
                )
            ],
        )
    )


class StubSpecialist:
    def __init__(self, result: AgentResult | None = None):
        self.result = result or AgentResult(output="stage complete")
        self.calls = 0

    async def run(self, *_args: Any, **_kwargs: Any) -> AgentResult:
        self.calls += 1
        return self.result


class MutationTool(BaseTool):
    def __init__(self) -> None:
        self.executed = False

    @property
    def name(self) -> str:
        return "mutation"

    @property
    def description(self) -> str:
        return "Mutates the workspace"

    @property
    def parameters_schema(self) -> dict[str, Any]:
        return {"type": "object", "properties": {}, "additionalProperties": False}

    @property
    def requires_approval(self) -> bool:
        return True

    async def execute(self, **kwargs: Any) -> ToolResult:
        self.executed = True
        return ToolResult(ok=True, data="mutated")


class FailedSpecialist:
    async def run(self, *_args: Any, **_kwargs: Any) -> AgentResult:
        return AgentResult(output="", success=False, error="coder failed")


async def test_ordered_successful_handoffs_reach_completed_state() -> None:
    provider = SequencedProvider(
        [
            handoff_response("planner", "handoff-planner"),
            handoff_response("coder", "handoff-coder"),
            handoff_response("reviewer", "handoff-reviewer"),
            handoff_response("tester", "handoff-tester"),
            LLMResponse(message=ChatMessage(role=Role.ASSISTANT, content="all stages complete")),
        ]
    )
    specialists = {name: StubSpecialist() for name in ("planner", "coder", "reviewer", "tester")}
    orchestrator = OrchestratorAgent(
        llm=provider,
        planner=cast(Any, specialists["planner"]),
        coder=cast(Any, specialists["coder"]),
        reviewer=cast(Any, specialists["reviewer"]),
        tester=cast(Any, specialists["tester"]),
    )

    task = await orchestrator.run_task(Task(description="do work"))

    assert task.state is TaskState.COMPLETED
    assert task.result == "all stages complete"
    assert orchestrator.successful_handoff_ledger == (
        "planner",
        "coder",
        "reviewer",
        "tester",
    )
    assert all(specialist.calls == 1 for specialist in specialists.values())


async def test_skipped_stage_is_rejected_and_cannot_complete() -> None:
    provider = SequencedProvider(
        [
            handoff_response("planner", "handoff-planner"),
            handoff_response("reviewer", "handoff-reviewer"),
            LLMResponse(message=ChatMessage(role=Role.ASSISTANT, content="done")),
        ]
    )
    succeeded = cast(Any, StubSpecialist())
    orchestrator = OrchestratorAgent(
        llm=provider,
        planner=succeeded,
        coder=succeeded,
        reviewer=succeeded,
        tester=succeeded,
    )

    task = await orchestrator.run_task(Task(description="do work"))

    assert task.state is TaskState.FAILED
    assert task.error
    assert "Out-of-order handoff: expected coder, got reviewer" in task.error
    assert orchestrator.successful_handoff_ledger == ("planner",)


async def test_failed_handoff_cannot_be_reported_as_success() -> None:
    provider = SequencedProvider(
        [
            handoff_response("planner", "handoff-planner"),
            handoff_response("coder", "handoff-coder"),
            LLMResponse(message=ChatMessage(role=Role.ASSISTANT, content="Everything succeeded")),
        ]
    )
    succeeded = cast(Any, StubSpecialist())
    failed = cast(Any, FailedSpecialist())
    orchestrator = OrchestratorAgent(
        llm=provider,
        planner=succeeded,
        coder=failed,
        reviewer=failed,
        tester=failed,
    )

    task = await orchestrator.run_task(Task(description="do work"))

    assert task.state is TaskState.FAILED
    assert task.result is None
    assert task.error == "Handoff failed: coder: coder failed"
    assert orchestrator.successful_handoff_ledger == ("planner",)


async def test_denied_specialist_tool_call_cannot_be_reported_as_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    previous_settings = config_module._settings
    monkeypatch.setenv("REQUIRE_APPROVAL_FOR_WRITES", "true")
    config_module._settings = None
    try:
        mutation = MutationTool()
        denied_provider = SequencedProvider(
            [
                LLMResponse(
                    message=ChatMessage(
                        role=Role.ASSISTANT,
                        tool_calls=[ToolCall(id="mutation-1", name="mutation", arguments={})],
                    )
                )
            ]
        )
        denied_specialist = BaseAgent(
            llm=denied_provider,
            tools=ToolRegistry(
                [mutation],
                enforce_configured_approvals=True,
            ),
        )
        main_provider = SequencedProvider(
            [
                handoff_response("planner", "handoff-planner"),
                handoff_response("coder", "handoff-coder"),
                LLMResponse(message=ChatMessage(role=Role.ASSISTANT, content="done")),
            ]
        )
        succeeded = cast(Any, StubSpecialist())
        orchestrator = OrchestratorAgent(
            llm=main_provider,
            planner=succeeded,
            coder=denied_specialist,
            reviewer=succeeded,
            tester=succeeded,
        )

        task = await orchestrator.run_task(Task(description="mutate workspace"))

        assert task.state is TaskState.FAILED
        assert task.error
        assert "Tool approval denied" in task.error
        assert not mutation.executed
        assert orchestrator.successful_handoff_ledger == ("planner",)
    finally:
        config_module._settings = previous_settings


async def test_malformed_handoff_arguments_are_rejected() -> None:
    provider = SequencedProvider(
        [
            LLMResponse(
                message=ChatMessage(
                    role=Role.ASSISTANT,
                    tool_calls=[
                        ToolCall(
                            id="handoff-1",
                            name="transfer_to_coder",
                            arguments={"task": 123},
                        )
                    ],
                )
            ),
            LLMResponse(message=ChatMessage(role=Role.ASSISTANT, content="done")),
        ]
    )
    failed = cast(Any, FailedSpecialist())
    orchestrator = OrchestratorAgent(
        llm=provider,
        planner=failed,
        coder=failed,
        reviewer=failed,
        tester=failed,
    )

    result = await orchestrator.run("do work")

    assert not result.success
    assert result.error
    assert "Invalid handoff arguments" in result.error
