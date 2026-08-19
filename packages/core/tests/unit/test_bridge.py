"""Contract tests for the machine-readable API bridge."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from ai_dev_team import bridge
from ai_dev_team.orchestration.state import Task, TaskState


class SuccessfulOrchestrator:
    async def run_task(self, task: Task) -> Task:
        task.transition(TaskState.PLANNING, agent="test")
        task.transition(TaskState.EXECUTING, agent="test")
        task.transition(TaskState.COMPLETED, agent="test")
        task.result = "complete"
        return task


async def test_bridge_emits_completed_machine_readable_result(
    monkeypatch: Any,
    capsys: Any,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        bridge,
        "build_orchestrator",
        lambda _working_dir: SuccessfulOrchestrator(),
    )

    exit_code = await bridge._run("task-1", "do work", tmp_path)
    output = capsys.readouterr().out.strip()

    assert exit_code == 0
    assert output.startswith(bridge.RESULT_PREFIX)
    payload = json.loads(output.removeprefix(bridge.RESULT_PREFIX))
    assert payload == {
        "id": "task-1",
        "state": "completed",
        "result": "complete",
        "error": None,
    }


def test_bridge_rejects_root_and_missing_workspaces(tmp_path: Path) -> None:
    assert bridge._validated_working_dir(str(tmp_path)) == tmp_path.resolve()
    with pytest.raises(ValueError, match="non-root"):
        bridge._validated_working_dir(Path(tmp_path.anchor).as_posix())
    with pytest.raises(ValueError, match="non-root"):
        bridge._validated_working_dir(str(tmp_path / "missing"))
