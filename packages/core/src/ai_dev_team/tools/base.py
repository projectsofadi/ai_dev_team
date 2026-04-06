"""Base tool interface and result types."""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from typing import Any

from pydantic import BaseModel, Field

from ai_dev_team.llm.provider import ToolDefinition


class ToolResult(BaseModel):
    """Structured result from tool execution."""

    ok: bool = True
    data: Any = None
    error: str | None = None
    meta: dict[str, Any] = Field(default_factory=dict)

    def to_text(self) -> str:
        if self.error:
            return f"ERROR: {self.error}"
        if isinstance(self.data, str):
            return self.data
        return json.dumps(self.data, indent=2, default=str)


class BaseTool(ABC):
    """Abstract base for all tools."""

    @property
    @abstractmethod
    def name(self) -> str: ...

    @property
    @abstractmethod
    def description(self) -> str: ...

    @property
    @abstractmethod
    def parameters_schema(self) -> dict[str, Any]:
        """JSON Schema for the tool's input parameters."""
        ...

    @property
    def is_idempotent(self) -> bool:
        return False

    @property
    def requires_approval(self) -> bool:
        return False

    @abstractmethod
    async def execute(self, **kwargs: Any) -> ToolResult:
        """Run the tool with validated arguments."""
        ...

    def to_definition(self) -> ToolDefinition:
        return ToolDefinition(
            name=self.name,
            description=self.description,
            parameters=self.parameters_schema,
        )
