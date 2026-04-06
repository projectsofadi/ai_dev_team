"""ExecutionPlan data model — serializable, inspectable task decomposition."""

from __future__ import annotations

import uuid
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class StepStatus(str, Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class PlanStep(BaseModel):
    """A single actionable step within an execution plan."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4())[:8])
    title: str
    description: str
    agent: str = "coder"
    status: StepStatus = StepStatus.PENDING
    depends_on: list[str] = Field(default_factory=list)
    acceptance_criteria: list[str] = Field(default_factory=list)
    files_to_create: list[str] = Field(default_factory=list)
    files_to_modify: list[str] = Field(default_factory=list)
    output: str | None = None
    error: str | None = None


class ExecutionPlan(BaseModel):
    """A full plan decomposing a task into ordered steps."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    title: str
    objective: str
    steps: list[PlanStep] = Field(default_factory=list)
    context: dict[str, Any] = Field(default_factory=dict)

    def get_ready_steps(self) -> list[PlanStep]:
        """Return steps whose dependencies are all completed."""
        completed_ids = {s.id for s in self.steps if s.status == StepStatus.COMPLETED}
        return [
            s
            for s in self.steps
            if s.status == StepStatus.PENDING
            and all(dep in completed_ids for dep in s.depends_on)
        ]

    def mark_step(self, step_id: str, status: StepStatus, output: str | None = None) -> None:
        for step in self.steps:
            if step.id == step_id:
                step.status = status
                if output:
                    step.output = output
                return

    @property
    def is_complete(self) -> bool:
        return all(
            s.status in (StepStatus.COMPLETED, StepStatus.SKIPPED) for s in self.steps
        )

    @property
    def has_failures(self) -> bool:
        return any(s.status == StepStatus.FAILED for s in self.steps)

    @property
    def progress_summary(self) -> str:
        total = len(self.steps)
        done = sum(1 for s in self.steps if s.status == StepStatus.COMPLETED)
        failed = sum(1 for s in self.steps if s.status == StepStatus.FAILED)
        return f"{done}/{total} completed, {failed} failed"
