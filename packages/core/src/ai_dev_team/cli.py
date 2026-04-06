"""Python CLI entry point for running the agent system directly."""

from __future__ import annotations

import asyncio
import sys

import structlog

from ai_dev_team.config import get_settings


def main() -> None:
    """Entry point for the ai-dev-team Python CLI."""
    structlog.configure(
        processors=[
            structlog.stdlib.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.dev.ConsoleRenderer(),
        ],
    )

    if len(sys.argv) < 2:
        print("Usage: ai-dev-team <task_description>")
        print("\nExample:")
        print('  ai-dev-team "Create a REST API with user authentication"')
        sys.exit(1)

    task_description = " ".join(sys.argv[1:])
    asyncio.run(_run_task(task_description))


async def _run_task(description: str) -> None:
    settings = get_settings()

    if settings.llm.default_provider == "openai":
        from ai_dev_team.llm.openai import OpenAIProvider
        llm = OpenAIProvider()
    else:
        from ai_dev_team.llm.anthropic import AnthropicProvider
        llm = AnthropicProvider()

    from ai_dev_team.agents.coder import CoderAgent
    from ai_dev_team.agents.orchestrator import OrchestratorAgent
    from ai_dev_team.agents.planner import PlannerAgent
    from ai_dev_team.agents.reviewer import ReviewerAgent
    from ai_dev_team.agents.tester import TesterAgent
    from ai_dev_team.orchestration.state import Task

    planner = PlannerAgent(llm=llm)
    coder = CoderAgent(llm=llm)
    reviewer = ReviewerAgent(llm=llm)
    tester = TesterAgent(llm=llm)
    orchestrator = OrchestratorAgent(
        llm=llm,
        planner=planner,
        coder=coder,
        reviewer=reviewer,
        tester=tester,
    )

    task = Task(description=description)
    print(f"\nTask ID: {task.id}")
    print(f"Description: {description}\n")

    result = await orchestrator.run_task(task)

    print(f"\nState: {result.state.value}")
    if result.result:
        print(f"\nResult:\n{result.result}")
    if result.error:
        print(f"\nError: {result.error}")
    print(f"\nElapsed: {result.elapsed_seconds:.1f}s")


if __name__ == "__main__":
    main()
