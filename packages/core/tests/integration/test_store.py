"""Integration tests for SQLite state store."""

from __future__ import annotations

import tempfile
import time

import pytest

from ai_dev_team.memory.store import StateStore


@pytest.fixture
async def store():
    with tempfile.TemporaryDirectory() as d:
        s = StateStore(db_path=f"{d}/test.db")
        await s.initialize()
        yield s


class TestStateStore:
    async def test_save_and_get_task(self, store: StateStore):
        task = {
            "id": "t1",
            "description": "Test task",
            "state": "submitted",
            "plan": None,
            "result": None,
            "error": None,
            "metadata": {"key": "value"},
            "created_at": time.time(),
            "updated_at": time.time(),
        }
        await store.save_task(task)

        fetched = await store.get_task("t1")
        assert fetched is not None
        assert fetched["description"] == "Test task"
        assert fetched["state"] == "submitted"

    async def test_get_nonexistent(self, store: StateStore):
        result = await store.get_task("nonexistent")
        assert result is None

    async def test_list_tasks(self, store: StateStore):
        now = time.time()
        for i in range(5):
            await store.save_task(
                {
                    "id": f"t{i}",
                    "description": f"Task {i}",
                    "state": "submitted" if i % 2 == 0 else "completed",
                    "plan": None,
                    "result": None,
                    "error": None,
                    "metadata": {},
                    "created_at": now,
                    "updated_at": now + i,
                }
            )

        all_tasks = await store.list_tasks()
        assert len(all_tasks) == 5

        submitted = await store.list_tasks(state="submitted")
        assert len(submitted) == 3

    async def test_save_event(self, store: StateStore):
        await store.save_task(
            {
                "id": "t1",
                "description": "Test",
                "state": "submitted",
                "plan": None,
                "result": None,
                "error": None,
                "metadata": {},
                "created_at": time.time(),
                "updated_at": time.time(),
            }
        )

        await store.save_event(
            {
                "task_id": "t1",
                "from_state": "submitted",
                "to_state": "planning",
                "agent": "planner",
                "detail": "",
                "timestamp": time.time(),
            }
        )

        events = await store.get_task_events("t1")
        assert len(events) == 1
        assert events[0]["to_state"] == "planning"

    async def test_save_agent_log(self, store: StateStore):
        await store.save_agent_log(
            {
                "task_id": "t1",
                "agent_name": "coder",
                "iteration": 1,
                "input_tokens": 100,
                "output_tokens": 50,
                "tool_calls": [{"name": "shell", "args": {"cmd": "echo hi"}}],
                "output_text": "Done",
                "timestamp": time.time(),
            }
        )
