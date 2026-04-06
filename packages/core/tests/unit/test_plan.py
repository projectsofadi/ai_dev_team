"""Unit tests for ExecutionPlan."""

from __future__ import annotations

from ai_dev_team.orchestration.plan import ExecutionPlan, PlanStep, StepStatus


class TestPlanStep:
    def test_defaults(self):
        step = PlanStep(title="Do thing", description="Details")
        assert step.status == StepStatus.PENDING
        assert step.agent == "coder"
        assert step.depends_on == []
        assert step.id


class TestExecutionPlan:
    def make_plan(self) -> ExecutionPlan:
        return ExecutionPlan(
            title="Test Plan",
            objective="Test things",
            steps=[
                PlanStep(id="s1", title="Step 1", description="First"),
                PlanStep(id="s2", title="Step 2", description="Second", depends_on=["s1"]),
                PlanStep(id="s3", title="Step 3", description="Third", depends_on=["s1"]),
                PlanStep(id="s4", title="Step 4", description="Fourth", depends_on=["s2", "s3"]),
            ],
        )

    def test_get_ready_steps_initial(self):
        plan = self.make_plan()
        ready = plan.get_ready_steps()
        assert len(ready) == 1
        assert ready[0].id == "s1"

    def test_get_ready_steps_after_s1(self):
        plan = self.make_plan()
        plan.mark_step("s1", StepStatus.COMPLETED)
        ready = plan.get_ready_steps()
        ids = {s.id for s in ready}
        assert ids == {"s2", "s3"}

    def test_get_ready_steps_after_s2_s3(self):
        plan = self.make_plan()
        plan.mark_step("s1", StepStatus.COMPLETED)
        plan.mark_step("s2", StepStatus.COMPLETED)
        plan.mark_step("s3", StepStatus.COMPLETED)
        ready = plan.get_ready_steps()
        assert len(ready) == 1
        assert ready[0].id == "s4"

    def test_is_complete(self):
        plan = self.make_plan()
        assert not plan.is_complete
        for step in plan.steps:
            plan.mark_step(step.id, StepStatus.COMPLETED)
        assert plan.is_complete

    def test_has_failures(self):
        plan = self.make_plan()
        assert not plan.has_failures
        plan.mark_step("s1", StepStatus.FAILED)
        assert plan.has_failures

    def test_progress_summary(self):
        plan = self.make_plan()
        plan.mark_step("s1", StepStatus.COMPLETED)
        plan.mark_step("s2", StepStatus.FAILED)
        summary = plan.progress_summary
        assert "1/4 completed" in summary
        assert "1 failed" in summary
