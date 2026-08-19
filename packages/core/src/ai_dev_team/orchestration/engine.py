"""Main orchestration engine that drives the full agent pipeline."""

from __future__ import annotations

import contextlib

import structlog

from ai_dev_team.agents.base import AgentResult, BaseAgent
from ai_dev_team.orchestration.plan import ExecutionPlan, StepStatus
from ai_dev_team.orchestration.state import Task, TaskState

logger = structlog.get_logger()


class OrchestrationEngine:
    """
    Drives a Task through the full agent pipeline:
    submit -> plan -> execute steps -> review -> test -> complete.
    """

    def __init__(
        self,
        orchestrator: BaseAgent,
        planner: BaseAgent,
        coder: BaseAgent,
        reviewer: BaseAgent,
        tester: BaseAgent,
    ):
        self.orchestrator = orchestrator
        self.planner = planner
        self.coder = coder
        self.reviewer = reviewer
        self.tester = tester
        self._agent_map: dict[str, BaseAgent] = {
            "orchestrator": orchestrator,
            "planner": planner,
            "coder": coder,
            "reviewer": reviewer,
            "tester": tester,
        }

    async def run_task(self, task: Task) -> Task:
        """Execute a full task through the agent pipeline."""
        logger.info("engine_start", task_id=task.id, description=task.description)

        try:
            task.transition(TaskState.PLANNING, agent="planner")
            plan = await self._plan(task)
            task.plan = plan

            task.transition(TaskState.EXECUTING, agent="orchestrator")
            await self._execute_plan(task)

            if task.plan and not task.plan.has_failures:
                task.transition(TaskState.REVIEWING, agent="reviewer")
                review_result = await self._review(task)

                if "CHANGES_REQUESTED" in review_result.output.upper():
                    task.transition(TaskState.EXECUTING, agent="coder", detail="Addressing review")
                    await self._address_review(task, review_result.output)

                task.transition(TaskState.TESTING, agent="tester")
                test_result = await self._test(task)

                if test_result.success:
                    task.transition(TaskState.COMPLETED, agent="orchestrator")
                    task.result = self._build_summary(task)
                else:
                    task.transition(
                        TaskState.FAILED,
                        agent="tester",
                        detail=test_result.error or "",
                    )
                    task.error = test_result.error
            else:
                task.transition(
                    TaskState.FAILED,
                    agent="orchestrator",
                    detail="Plan execution had failures",
                )
                task.error = "One or more plan steps failed"

        except ValueError as exc:
            logger.error("engine_state_error", task_id=task.id, error_type=type(exc).__name__)
            with contextlib.suppress(ValueError):
                task.transition(TaskState.FAILED, agent="orchestrator", detail="State error")
            task.error = "Task failed because its state or plan was invalid"
        except Exception as exc:
            logger.error("engine_error", task_id=task.id, error_type=type(exc).__name__)
            with contextlib.suppress(ValueError):
                task.transition(TaskState.FAILED, agent="orchestrator", detail="Execution error")
            task.error = f"{type(exc).__name__}: task execution failed"

        logger.info(
            "engine_complete",
            task_id=task.id,
            state=task.state.value,
            elapsed=task.elapsed_seconds,
        )
        return task

    async def _plan(self, task: Task) -> ExecutionPlan:
        create_plan = getattr(self.planner, "create_plan", None)
        if not callable(create_plan):
            raise TypeError("Planner must implement create_plan(task_description)")

        plan = await create_plan(task.description)
        if not isinstance(plan, ExecutionPlan) or not plan.steps:
            raise ValueError("Planner returned an empty or invalid execution plan")
        return plan

    async def _execute_plan(self, task: Task) -> None:
        if not task.plan:
            return

        while True:
            ready = task.plan.get_ready_steps()
            if not ready:
                if task.plan.is_complete or task.plan.has_failures:
                    break
                raise RuntimeError(
                    "Plan stalled: pending steps have missing or cyclic dependencies"
                )

            for step in ready:
                task.plan.mark_step(step.id, StepStatus.IN_PROGRESS)
                agent = self._agent_map.get(step.agent, self.coder)

                prompt = (
                    f"Execute this step from the plan:\n\n"
                    f"Step: {step.title}\n"
                    f"Description: {step.description}\n"
                    f"Acceptance criteria: {', '.join(step.acceptance_criteria)}\n"
                    f"Files to create: {', '.join(step.files_to_create)}\n"
                    f"Files to modify: {', '.join(step.files_to_modify)}"
                )

                result = await agent.run(prompt)
                if result.success:
                    task.plan.mark_step(step.id, StepStatus.COMPLETED, output=result.output)
                else:
                    task.plan.mark_step(step.id, StepStatus.FAILED, output=result.error)
                    break

            if task.plan.is_complete or task.plan.has_failures:
                break

    async def _review(self, task: Task) -> AgentResult:
        prompt = (
            "Review the code changes made for this task:\n\n"
            f"Task: {task.description}\n\n"
            "Check for:\n"
            "1. Correctness and logic errors\n"
            "2. Code style and best practices\n"
            "3. Security issues\n"
            "4. Performance concerns\n"
            "5. Test coverage gaps\n\n"
            "Respond with APPROVED if the code is good, or CHANGES_REQUESTED "
            "with specific feedback."
        )
        return await self.reviewer.run(prompt)

    async def _address_review(self, task: Task, review_feedback: str) -> None:
        prompt = (
            f"Address this review feedback:\n\n{review_feedback}\n\n"
            "Make the necessary changes to fix the issues identified."
        )
        await self.coder.run(prompt)

    async def _test(self, task: Task) -> AgentResult:
        prompt = (
            "Write and run tests for the code changes:\n\n"
            f"Task: {task.description}\n\n"
            "1. Write appropriate unit tests\n"
            "2. Run the test suite\n"
            "3. Report results"
        )
        return await self.tester.run(prompt)

    def _build_summary(self, task: Task) -> str:
        parts = [f"Task completed: {task.description}"]
        if task.plan:
            parts.append(f"Plan: {task.plan.progress_summary}")
        parts.append(f"Elapsed: {task.elapsed_seconds:.1f}s")
        return "\n".join(parts)
