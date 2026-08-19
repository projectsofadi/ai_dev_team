"""Python CLI entry point for running the agent system directly."""

from __future__ import annotations

import asyncio
import sys

import structlog

from ai_dev_team.runtime import build_orchestrator


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
    succeeded = asyncio.run(_run_task(task_description))
    raise SystemExit(0 if succeeded else 1)


async def _run_task(description: str) -> bool:
    from ai_dev_team.orchestration.state import Task

    orchestrator = build_orchestrator()

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
    return result.state.value == "completed"


if __name__ == "__main__":
    main()
