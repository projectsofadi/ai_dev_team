"""Unit tests for task state machine."""

from __future__ import annotations

import pytest

from ai_dev_team.orchestration.state import Task, TaskState


class TestTask:
    def test_initial_state(self):
        task = Task(description="Test task")
        assert task.state == TaskState.SUBMITTED
        assert not task.is_terminal
        assert task.id

    def test_valid_transition(self):
        task = Task(description="Test")
        task.transition(TaskState.PLANNING, agent="planner")
        assert task.state == TaskState.PLANNING
        assert len(task.events) == 1
        assert task.events[0].from_state == TaskState.SUBMITTED
        assert task.events[0].to_state == TaskState.PLANNING

    def test_invalid_transition(self):
        task = Task(description="Test")
        with pytest.raises(ValueError, match="Invalid transition"):
            task.transition(TaskState.COMPLETED)

    def test_terminal_states(self):
        task = Task(description="Test")
        task.transition(TaskState.PLANNING)
        task.transition(TaskState.FAILED, detail="oops")
        assert task.is_terminal
        assert task.state == TaskState.FAILED

    def test_full_lifecycle(self):
        task = Task(description="Build a feature")
        task.transition(TaskState.PLANNING, agent="planner")
        task.transition(TaskState.EXECUTING, agent="coder")
        task.transition(TaskState.REVIEWING, agent="reviewer")
        task.transition(TaskState.TESTING, agent="tester")
        task.transition(TaskState.COMPLETED, agent="orchestrator")

        assert task.is_terminal
        assert task.state == TaskState.COMPLETED
        assert len(task.events) == 5

    def test_review_cycle(self):
        task = Task(description="Build something")
        task.transition(TaskState.PLANNING)
        task.transition(TaskState.EXECUTING)
        task.transition(TaskState.REVIEWING)
        task.transition(TaskState.EXECUTING)  # changes requested
        task.transition(TaskState.REVIEWING)
        task.transition(TaskState.COMPLETED)
        assert len(task.events) == 6

    def test_elapsed_time(self):
        task = Task(description="Test")
        assert task.elapsed_seconds >= 0
