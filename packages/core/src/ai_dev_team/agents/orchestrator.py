"""Orchestrator agent — supervisor that coordinates the dev team via handoffs."""

from __future__ import annotations

import json
from typing import Any

from ai_dev_team.agents.base import AgentResult, BaseAgent
from ai_dev_team.llm.provider import ChatMessage, LLMProvider, Role, ToolCall, ToolDefinition
from ai_dev_team.llm.provider import ToolResult as LLMToolResult
from ai_dev_team.orchestration.plan import ExecutionPlan
from ai_dev_team.orchestration.state import Task, TaskState
from ai_dev_team.tools.registry import ToolRegistry

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
        super().__init__(llm=llm, tools=ToolRegistry(), extra_tools=handoff_tools)

    async def run(
        self,
        user_message: str,
        context: list[ChatMessage] | None = None,
        **kwargs: Any,
    ) -> AgentResult:
        """Override run to intercept handoff tool calls and delegate to sub-agents."""
        original_execute = self.tools.execute

        async def _intercept_execute(tool_call: ToolCall, **kw: Any) -> LLMToolResult:
            if tool_call.name.startswith("transfer_to_"):
                agent_name = tool_call.name.replace("transfer_to_", "")
                agent = self._agents.get(agent_name)
                if not agent:
                    return LLMToolResult(
                        call_id=tool_call.id,
                        output=f"Unknown agent: {agent_name}",
                        is_error=True,
                    )

                task = tool_call.arguments.get("task", "")
                ctx = tool_call.arguments.get("context", "")
                prompt = task
                if ctx:
                    prompt = f"{task}\n\nContext:\n{ctx}"

                sub_result = await agent.run(prompt)
                return LLMToolResult(
                    call_id=tool_call.id,
                    output=(
                        f"[{agent_name.upper()} RESULT]\n"
                        f"Success: {sub_result.success}\n"
                        f"Iterations: {sub_result.iterations}\n"
                        f"Output:\n{sub_result.output}"
                    ),
                )

            return await original_execute(tool_call, **kw)

        self.tools.execute = _intercept_execute  # type: ignore[assignment]
        try:
            return await super().run(user_message, context=context, **kwargs)
        finally:
            self.tools.execute = original_execute  # type: ignore[assignment]

    async def run_task(self, task: Task) -> Task:
        """Convenience: run a Task object through the orchestrator."""
        result = await self.run(
            f"Execute this development task:\n\n{task.description}",
        )
        if result.success:
            try:
                task.transition(TaskState.COMPLETED, agent="orchestrator")
            except ValueError:
                pass
            task.result = result.output
        else:
            try:
                task.transition(TaskState.FAILED, agent="orchestrator", detail=result.error or "")
            except ValueError:
                pass
            task.error = result.error
        return task
