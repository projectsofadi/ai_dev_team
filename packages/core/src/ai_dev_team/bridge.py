"""Machine-readable subprocess bridge used by the TypeScript API server."""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import signal
import sys
from pathlib import Path
from typing import Any

import structlog

from ai_dev_team.orchestration.state import Task
from ai_dev_team.runtime import build_orchestrator

RESULT_PREFIX = "AI_DEV_TEAM_RESULT="


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run one AI Dev Team task")
    parser.add_argument("--task-id", required=True)
    parser.add_argument("--working-dir", required=True)
    return parser


def _emit(payload: dict[str, Any]) -> None:
    print(RESULT_PREFIX + json.dumps(payload, separators=(",", ":")), flush=True)


def _validated_working_dir(raw_path: str) -> Path:
    working_dir = Path(raw_path).expanduser().resolve()
    if not working_dir.is_dir() or working_dir == Path(working_dir.anchor):
        raise ValueError("Configured working directory must be an existing non-root directory")
    return working_dir


async def _run(task_id: str, description: str, working_dir: Path) -> int:
    try:
        orchestrator = build_orchestrator(str(working_dir))
        task = await orchestrator.run_task(Task(id=task_id, description=description))
        _emit(
            {
                "id": task.id,
                "state": task.state.value,
                "result": task.result,
                "error": task.error,
            }
        )
        return 0 if task.state.value == "completed" else 1
    except Exception as exc:
        _emit(
            {
                "id": task_id,
                "state": "failed",
                "result": None,
                "error": f"{type(exc).__name__}: task execution failed",
            }
        )
        return 1


async def _run_with_signal_handling(
    task_id: str,
    description: str,
    working_dir: Path,
) -> int:
    loop = asyncio.get_running_loop()
    task = asyncio.create_task(_run(task_id, description, working_dir))
    supported_signals = (signal.SIGTERM, signal.SIGINT)
    for sig in supported_signals:
        with contextlib.suppress(NotImplementedError):
            loop.add_signal_handler(sig, task.cancel)
    try:
        return await task
    except asyncio.CancelledError:
        _emit(
            {
                "id": task_id,
                "state": "failed",
                "result": None,
                "error": "Task cancelled by the API server",
            }
        )
        return 130
    finally:
        for sig in supported_signals:
            with contextlib.suppress(NotImplementedError):
                loop.remove_signal_handler(sig)


def main() -> None:
    args = _parser().parse_args()
    try:
        working_dir = _validated_working_dir(args.working_dir)
    except ValueError as exc:
        _emit(
            {
                "id": args.task_id,
                "state": "failed",
                "result": None,
                "error": str(exc),
            }
        )
        raise SystemExit(2) from None

    description = sys.stdin.read(10_001)
    if not description or len(description) > 10_000:
        _emit(
            {
                "id": args.task_id,
                "state": "failed",
                "result": None,
                "error": "Task description must contain 1-10,000 characters",
            }
        )
        raise SystemExit(2)

    structlog.configure(logger_factory=structlog.PrintLoggerFactory(file=sys.stderr))
    raise SystemExit(asyncio.run(_run_with_signal_handling(args.task_id, description, working_dir)))


if __name__ == "__main__":
    main()
