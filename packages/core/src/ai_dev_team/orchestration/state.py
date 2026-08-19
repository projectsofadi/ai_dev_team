"""Task state machine for tracking agent workflow lifecycle."""

from __future__ import annotations

import time
import uuid
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

from ai_dev_team.orchestration.plan import ExecutionPlan


class TaskState(StrEnum):
    SUBMITTED = "submitted"
    PLANNING = "planning"
    EXECUTING = "executing"
    REVIEWING = "reviewing"
    TESTING = "testing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


VALID_TRANSITIONS: dict[TaskState, set[TaskState]] = {
    TaskState.SUBMITTED: {TaskState.PLANNING, TaskState.FAILED, TaskState.CANCELLED},
    TaskState.PLANNING: {TaskState.EXECUTING, TaskState.FAILED, TaskState.CANCELLED},
    TaskState.EXECUTING: {
        TaskState.REVIEWING,
        TaskState.TESTING,
        TaskState.COMPLETED,
        TaskState.FAILED,
        TaskState.CANCELLED,
    },
    TaskState.REVIEWING: {
        TaskState.EXECUTING,
        TaskState.TESTING,
        TaskState.COMPLETED,
        TaskState.FAILED,
        TaskState.CANCELLED,
    },
    TaskState.TESTING: {
        TaskState.EXECUTING,
        TaskState.REVIEWING,
        TaskState.COMPLETED,
        TaskState.FAILED,
        TaskState.CANCELLED,
    },
    TaskState.COMPLETED: set(),
    TaskState.FAILED: set(),
    TaskState.CANCELLED: set(),
}


class TaskEvent(BaseModel):
    """A state transition event in the task lifecycle."""

    timestamp: float = Field(default_factory=time.time)
    from_state: TaskState
    to_state: TaskState
    agent: str = ""
    detail: str = ""


class Task(BaseModel):
    """A tracked task flowing through the agent pipeline."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    description: str
    state: TaskState = TaskState.SUBMITTED
    plan: ExecutionPlan | None = None
    events: list[TaskEvent] = Field(default_factory=list)
    result: str | None = None
    error: str | None = None
    created_at: float = Field(default_factory=time.time)
    updated_at: float = Field(default_factory=time.time)
    metadata: dict[str, Any] = Field(default_factory=dict)

    def transition(self, new_state: TaskState, agent: str = "", detail: str = "") -> None:
        if new_state not in VALID_TRANSITIONS.get(self.state, set()):
            raise ValueError(f"Invalid transition: {self.state.value} -> {new_state.value}")
        event = TaskEvent(
            from_state=self.state,
            to_state=new_state,
            agent=agent,
            detail=detail,
        )
        self.events.append(event)
        self.state = new_state
        self.updated_at = time.time()

    @property
    def is_terminal(self) -> bool:
        return self.state in (TaskState.COMPLETED, TaskState.FAILED, TaskState.CANCELLED)

    @property
    def elapsed_seconds(self) -> float:
        return self.updated_at - self.created_at
