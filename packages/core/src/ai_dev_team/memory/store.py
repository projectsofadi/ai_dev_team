"""SQLite-based state persistence for tasks and execution history."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import aiosqlite

from ai_dev_team.config import get_settings

SCHEMA = """
CREATE TABLE IF NOT EXISTS tasks (
    id TEXT PRIMARY KEY,
    description TEXT NOT NULL,
    state TEXT NOT NULL DEFAULT 'submitted',
    plan_json TEXT,
    result TEXT,
    error TEXT,
    metadata_json TEXT DEFAULT '{}',
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS task_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id TEXT NOT NULL REFERENCES tasks(id),
    from_state TEXT NOT NULL,
    to_state TEXT NOT NULL,
    agent TEXT DEFAULT '',
    detail TEXT DEFAULT '',
    timestamp REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS agent_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id TEXT,
    agent_name TEXT NOT NULL,
    iteration INTEGER,
    input_tokens INTEGER DEFAULT 0,
    output_tokens INTEGER DEFAULT 0,
    tool_calls_json TEXT DEFAULT '[]',
    output_text TEXT DEFAULT '',
    timestamp REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_task_events_task ON task_events(task_id);
CREATE INDEX IF NOT EXISTS idx_agent_logs_task ON agent_logs(task_id);
"""


class StateStore:
    """Async SQLite store for persisting task state and agent logs."""

    def __init__(self, db_path: str | Path | None = None):
        settings = get_settings()
        self._db_path = str(db_path or settings.memory.sqlite_db_path)

    async def initialize(self) -> None:
        Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        async with aiosqlite.connect(self._db_path) as db:
            await db.executescript(SCHEMA)
            await db.commit()

    async def save_task(self, task_data: dict[str, Any]) -> None:
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(
                """
                INSERT OR REPLACE INTO tasks
                    (id, description, state, plan_json, result, error,
                     metadata_json, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    task_data["id"],
                    task_data["description"],
                    task_data["state"],
                    json.dumps(task_data.get("plan")),
                    task_data.get("result"),
                    task_data.get("error"),
                    json.dumps(task_data.get("metadata", {})),
                    task_data["created_at"],
                    task_data["updated_at"],
                ),
            )
            await db.commit()

    async def get_task(self, task_id: str) -> dict[str, Any] | None:
        async with aiosqlite.connect(self._db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)) as cursor:
                row = await cursor.fetchone()
                if row is None:
                    return None
                return dict(row)

    async def list_tasks(self, limit: int = 50, state: str | None = None) -> list[dict[str, Any]]:
        async with aiosqlite.connect(self._db_path) as db:
            db.row_factory = aiosqlite.Row
            if state:
                query = "SELECT * FROM tasks WHERE state = ? ORDER BY updated_at DESC LIMIT ?"
                params: tuple[Any, ...] = (state, limit)
            else:
                query = "SELECT * FROM tasks ORDER BY updated_at DESC LIMIT ?"
                params = (limit,)

            async with db.execute(query, params) as cursor:
                rows = await cursor.fetchall()
                return [dict(r) for r in rows]

    async def save_event(self, event_data: dict[str, Any]) -> None:
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(
                """
                INSERT INTO task_events (task_id, from_state, to_state, agent, detail, timestamp)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    event_data["task_id"],
                    event_data["from_state"],
                    event_data["to_state"],
                    event_data.get("agent", ""),
                    event_data.get("detail", ""),
                    event_data["timestamp"],
                ),
            )
            await db.commit()

    async def save_agent_log(self, log_data: dict[str, Any]) -> None:
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(
                """
                INSERT INTO agent_logs
                    (task_id, agent_name, iteration, input_tokens, output_tokens,
                     tool_calls_json, output_text, timestamp)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    log_data.get("task_id"),
                    log_data["agent_name"],
                    log_data.get("iteration", 0),
                    log_data.get("input_tokens", 0),
                    log_data.get("output_tokens", 0),
                    json.dumps(log_data.get("tool_calls", [])),
                    log_data.get("output_text", ""),
                    log_data["timestamp"],
                ),
            )
            await db.commit()

    async def get_task_events(self, task_id: str) -> list[dict[str, Any]]:
        async with aiosqlite.connect(self._db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM task_events WHERE task_id = ? ORDER BY timestamp",
                (task_id,),
            ) as cursor:
                rows = await cursor.fetchall()
                return [dict(r) for r in rows]
