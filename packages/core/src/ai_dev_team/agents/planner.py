"""Planner agent — decomposes tasks into structured ExecutionPlans."""

from __future__ import annotations

import json
from typing import Any

from ai_dev_team.agents.base import AgentResult, BaseAgent
from ai_dev_team.llm.provider import ChatMessage, LLMProvider, Role, ToolDefinition
from ai_dev_team.orchestration.plan import ExecutionPlan, PlanStep
from ai_dev_team.tools.registry import ToolRegistry

PLANNER_INSTRUCTIONS = """\
You are the Planner agent in an AI development team. Your role is to decompose
high-level tasks into detailed, actionable execution plans.

When creating a plan:
1. Analyze the task requirements thoroughly
2. Break it down into small, atomic steps that a single agent can execute
3. Identify dependencies between steps
4. Assign each step to the appropriate agent (coder, reviewer, tester)
5. Define clear acceptance criteria for each step
6. List files that will be created or modified

You MUST respond with a valid JSON execution plan using the create_plan tool.
Think carefully about the correct order of operations and dependencies.
"""


class PlannerAgent(BaseAgent):
    name = "planner"
    role = "planner"
    instructions = PLANNER_INSTRUCTIONS
    temperature = 0.1

    def __init__(self, llm: LLMProvider, tools: ToolRegistry | None = None):
        plan_tool = ToolDefinition(
            name="create_plan",
            description="Create a structured execution plan for the task",
            parameters={
                "type": "object",
                "properties": {
                    "title": {
                        "type": "string",
                        "description": "Short title for the plan",
                    },
                    "objective": {
                        "type": "string",
                        "description": "High-level objective of the plan",
                    },
                    "steps": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "id": {"type": "string", "description": "Short unique ID (e.g., s1, s2)"},
                                "title": {"type": "string"},
                                "description": {"type": "string"},
                                "agent": {
                                    "type": "string",
                                    "enum": ["coder", "reviewer", "tester"],
                                },
                                "depends_on": {
                                    "type": "array",
                                    "items": {"type": "string"},
                                    "description": "IDs of steps this depends on",
                                },
                                "acceptance_criteria": {
                                    "type": "array",
                                    "items": {"type": "string"},
                                },
                                "files_to_create": {
                                    "type": "array",
                                    "items": {"type": "string"},
                                },
                                "files_to_modify": {
                                    "type": "array",
                                    "items": {"type": "string"},
                                },
                            },
                            "required": ["id", "title", "description", "agent"],
                            "additionalProperties": False,
                        },
                    },
                },
                "required": ["title", "objective", "steps"],
                "additionalProperties": False,
            },
        )
        super().__init__(llm=llm, tools=tools, extra_tools=[plan_tool])
        self._last_plan: ExecutionPlan | None = None

    async def create_plan(self, task_description: str, context: str = "") -> ExecutionPlan:
        """Create a structured execution plan for the given task."""
        prompt = f"Create an execution plan for:\n\n{task_description}"
        if context:
            prompt += f"\n\nAdditional context:\n{context}"

        result = await self.run(prompt)

        if self._last_plan:
            return self._last_plan

        return ExecutionPlan(
            title=f"Plan for: {task_description[:80]}",
            objective=task_description,
        )

    async def run(
        self,
        user_message: str,
        context: list[ChatMessage] | None = None,
        **kwargs: Any,
    ) -> AgentResult:
        """Override run to intercept create_plan tool calls."""
        original_execute = self.tools.execute

        async def _intercept_execute(tool_call: Any, **kw: Any) -> Any:
            if tool_call.name == "create_plan":
                args = tool_call.arguments
                steps = [
                    PlanStep(
                        id=s.get("id", f"s{i}"),
                        title=s["title"],
                        description=s["description"],
                        agent=s.get("agent", "coder"),
                        depends_on=s.get("depends_on", []),
                        acceptance_criteria=s.get("acceptance_criteria", []),
                        files_to_create=s.get("files_to_create", []),
                        files_to_modify=s.get("files_to_modify", []),
                    )
                    for i, s in enumerate(args.get("steps", []))
                ]
                self._last_plan = ExecutionPlan(
                    title=args.get("title", ""),
                    objective=args.get("objective", ""),
                    steps=steps,
                )
                from ai_dev_team.llm.provider import ToolResult

                return ToolResult(
                    call_id=tool_call.id,
                    output=f"Plan created with {len(steps)} steps: {self._last_plan.title}",
                )
            return await original_execute(tool_call, **kw)

        self.tools.execute = _intercept_execute  # type: ignore[assignment]
        try:
            return await super().run(user_message, context=context, **kwargs)
        finally:
            self.tools.execute = original_execute  # type: ignore[assignment]
