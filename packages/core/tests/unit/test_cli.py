"""Exit-status contract tests for the Python CLI."""

from __future__ import annotations

from typing import Any

import pytest

from ai_dev_team import cli
from ai_dev_team.orchestration.state import Task, TaskState


class StubOrchestrator:
    def __init__(self, terminal_state: TaskState) -> None:
        self.terminal_state = terminal_state

    async def run_task(self, task: Task) -> Task:
        task.transition(TaskState.PLANNING, agent="test")
        task.transition(TaskState.EXECUTING, agent="test")
        task.transition(self.terminal_state, agent="test")
        if self.terminal_state is TaskState.COMPLETED:
            task.result = "done"
        else:
            task.error = "failed"
        return task


@pytest.mark.parametrize(
    ("state", "expected"),
    [(TaskState.COMPLETED, True), (TaskState.FAILED, False)],
)
async def test_run_task_returns_process_success_contract(
    monkeypatch: Any,
    state: TaskState,
    expected: bool,
) -> None:
    monkeypatch.setattr(cli, "build_orchestrator", lambda: StubOrchestrator(state))
    assert await cli._run_task("inspect") is expected
