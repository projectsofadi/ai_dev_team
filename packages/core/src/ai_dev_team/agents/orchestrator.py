"""Orchestrator agent — supervisor that coordinates the dev team via handoffs."""

from __future__ import annotations

import asyncio
from typing import Any

from ai_dev_team.agents.base import AgentResult, BaseAgent
from ai_dev_team.guardrails.budget import BudgetTracker
from ai_dev_team.guardrails.validators import validate_output, validate_tool_args
from ai_dev_team.llm.provider import ChatMessage, LLMProvider, ToolCall, ToolDefinition
from ai_dev_team.llm.provider import ToolResult as LLMToolResult
from ai_dev_team.orchestration.state import Task, TaskState
from ai_dev_team.tools.registry import ToolRegistry

REQUIRED_HANDOFF_SEQUENCE: tuple[str, ...] = ("planner", "coder", "reviewer", "tester")


def _incomplete_handoff_error(ledger: tuple[str, ...]) -> str:
    completed = " -> ".join(ledger) if ledger else "(none)"
    required = " -> ".join(REQUIRED_HANDOFF_SEQUENCE)
    return f"Incomplete handoff sequence: completed {completed}; required {required}"


ORCHESTRATOR_INSTRUCTIONS = """\
You are the Orchestrator — the lead coordinator of an AI development team.

Your team consists of:
- **Planner**: Breaks down tasks into execution plans
- **Coder**: Writes and modifies code
- **Reviewer**: Reviews code for quality, security, and correctness
- **Tester**: Writes and runs tests

Your workflow:
1. Receive a task from the user
2. Hand off to the Planner to create an execution plan
3. Execute plan steps by handing off to the appropriate agent
4. Hand off to the Reviewer for code review
5. Hand off to the Tester for test verification
6. Synthesize results and report back to the user

Rules:
- Always start by planning before coding
- After coding, always review before testing
- If review requests changes, hand back to coder
- If tests fail, analyze and hand back to coder
- Provide clear context when handing off to agents
- Track overall progress and report status

Use the transfer_to_* tools to delegate to your team members.
Provide a clear summary of the context and what you need them to do.
"""


def _make_handoff_tools() -> list[ToolDefinition]:
    """Create handoff tool definitions for each specialist agent."""
    agents = [
        ("planner", "Break down a task into an execution plan"),
        ("coder", "Write or modify code according to a plan or instructions"),
        ("reviewer", "Review code changes for quality and correctness"),
        ("tester", "Write and run tests for the code changes"),
    ]
    return [
        ToolDefinition(
            name=f"transfer_to_{name}",
            description=f"Hand off to the {name.title()} agent. {desc}.",
            parameters={
                "type": "object",
                "properties": {
                    "task": {
                        "type": "string",
                        "description": "Clear description of what the agent should do",
                    },
                    "context": {
                        "type": "string",
                        "description": "Relevant context, prior results, or constraints",
                    },
                },
                "required": ["task"],
                "additionalProperties": False,
            },
        )
        for name, desc in agents
    ]


class OrchestratorAgent(BaseAgent):
    name = "orchestrator"
    role = "orchestrator"
    instructions = ORCHESTRATOR_INSTRUCTIONS
    temperature = 0.1

    def __init__(
        self,
        llm: LLMProvider,
        planner: BaseAgent,
        coder: BaseAgent,
        reviewer: BaseAgent,
        tester: BaseAgent,
    ):
        self._agents: dict[str, BaseAgent] = {
            "planner": planner,
            "coder": coder,
            "reviewer": reviewer,
            "tester": tester,
        }
        handoff_tools = _make_handoff_tools()
        self._handoff_schemas = {tool.name: tool.parameters for tool in handoff_tools}
        self._last_handoff_ledger: tuple[str, ...] = ()
        super().__init__(llm=llm, tools=ToolRegistry(), extra_tools=handoff_tools)

    @property
    def successful_handoff_ledger(self) -> tuple[str, ...]:
        """Successful required stages from the most recent run, in execution order."""
        return self._last_handoff_ledger

    async def run(
        self,
        user_message: str,
        context: list[ChatMessage] | None = None,
        max_iterations: int | None = None,
        max_tokens_budget: int | None = None,
        timeout: float | None = None,
        budget_tracker: BudgetTracker | None = None,
    ) -> AgentResult:
        """Override run to intercept handoff tool calls and delegate to sub-agents."""
        shared_budget = budget_tracker or BudgetTracker.from_settings()
        original_execute = self.tools.execute
        handoff_lock = asyncio.Lock()
        handoff_errors: list[str] = []
        successful_handoffs: list[str] = []
        self._last_handoff_ledger = ()

        async def _intercept_execute(tool_call: ToolCall, **kw: Any) -> LLMToolResult:
            if tool_call.name.startswith("transfer_to_"):
                schema = self._handoff_schemas.get(tool_call.name)
                validation = validate_tool_args(tool_call.arguments, schema or {})
                if schema is None or not validation.valid:
                    error = "Invalid handoff arguments: " + "; ".join(
                        validation.violations or ["unknown handoff tool"]
                    )
                    handoff_errors.append(error)
                    return LLMToolResult(
                        call_id=tool_call.id,
                        output=error,
                        is_error=True,
                    )
                agent_name = tool_call.name.replace("transfer_to_", "")
                agent = self._agents.get(agent_name)
                if not agent:
                    error = f"Unknown agent: {agent_name}"
                    handoff_errors.append(error)
                    return LLMToolResult(
                        call_id=tool_call.id,
                        output=error,
                        is_error=True,
                    )

                task = tool_call.arguments.get("task", "")
                ctx = tool_call.arguments.get("context", "")
                prompt = task
                if ctx:
                    prompt = f"{task}\n\nContext:\n{ctx}"

                async with handoff_lock:
                    is_completed_stage = agent_name in successful_handoffs
                    if not is_completed_stage:
                        expected = REQUIRED_HANDOFF_SEQUENCE[len(successful_handoffs)]
                        if agent_name != expected:
                            error = f"Out-of-order handoff: expected {expected}, got {agent_name}"
                            handoff_errors.append(error)
                            return LLMToolResult(
                                call_id=tool_call.id,
                                output=error,
                                is_error=True,
                            )
                    sub_result = await agent.run(prompt, budget_tracker=shared_budget)
                    if sub_result.success and not is_completed_stage:
                        successful_handoffs.append(agent_name)
                        self._last_handoff_ledger = tuple(successful_handoffs)
                safe_output = sub_result.output
                output_validation = validate_output(safe_output)
                if not output_validation.valid:
                    safe_output = "[sub-agent output blocked by secret-leak guardrail]"
                safe_error = sub_result.error or "none"
                if not validate_output(safe_error).valid:
                    safe_error = "[sub-agent error blocked by secret-leak guardrail]"
                if not sub_result.success:
                    handoff_errors.append(f"{agent_name}: {safe_error}")
                return LLMToolResult(
                    call_id=tool_call.id,
                    output=(
                        f"[{agent_name.upper()} RESULT]\n"
                        f"Success: {sub_result.success}\n"
                        f"Iterations: {sub_result.iterations}\n"
                        f"Error: {safe_error}\n"
                        f"Output:\n{safe_output}"
                    ),
                    is_error=not sub_result.success,
                )

            return await original_execute(tool_call, **kw)

        self.tools.execute = _intercept_execute  # type: ignore[assignment]
        try:
            result = await super().run(
                user_message,
                context=context,
                max_iterations=max_iterations,
                max_tokens_budget=max_tokens_budget,
                timeout=timeout,
                budget_tracker=shared_budget,
            )
            if handoff_errors:
                return result.model_copy(
                    update={
                        "output": "",
                        "success": False,
                        "error": "Handoff failed: " + "; ".join(handoff_errors),
                    }
                )
            ledger = tuple(successful_handoffs)
            self._last_handoff_ledger = ledger
            if result.success and ledger != REQUIRED_HANDOFF_SEQUENCE:
                return result.model_copy(
                    update={
                        "output": "",
                        "success": False,
                        "error": _incomplete_handoff_error(ledger),
                    }
                )
            return result
        finally:
            self.tools.execute = original_execute  # type: ignore[method-assign]

    async def run_task(self, task: Task) -> Task:
        """Convenience: run a Task object through the orchestrator."""
        self._last_handoff_ledger = ()
        task.transition(TaskState.PLANNING, agent="orchestrator")
        task.transition(TaskState.EXECUTING, agent="orchestrator")
        result = await self.run(
            f"Execute this development task:\n\n{task.description}",
        )
        sequence_complete = self._last_handoff_ledger == REQUIRED_HANDOFF_SEQUENCE
        if result.success and sequence_complete:
            task.transition(TaskState.COMPLETED, agent="orchestrator")
            task.result = result.output
        else:
            error = result.error or _incomplete_handoff_error(self._last_handoff_ledger)
            task.transition(TaskState.FAILED, agent="orchestrator", detail=error)
            task.error = error
        return task
