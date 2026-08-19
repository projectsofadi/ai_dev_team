"""Token and cost budget enforcement."""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from ai_dev_team.config import get_settings

# Approximate cost per 1M tokens (as of 2026 pricing)
COST_PER_MILLION: dict[str, dict[str, float]] = {
    "gpt-4o": {"input": 2.50, "output": 10.00},
    "gpt-4o-mini": {"input": 0.15, "output": 0.60},
    "claude-sonnet-4-20250514": {"input": 3.00, "output": 15.00},
    "claude-haiku-3-20250722": {"input": 0.25, "output": 1.25},
}

DEFAULT_COST = {"input": 5.00, "output": 15.00}


@dataclass
class BudgetTracker:
    """Tracks token usage and estimated costs across an agent run."""

    max_tokens: int = 100_000
    max_cost_usd: float = 5.00
    max_iterations: int = 25
    max_wall_seconds: float = 300.0

    total_input_tokens: int = 0
    total_output_tokens: int = 0
    total_cost_usd: float = 0.0
    iteration_count: int = 0
    start_time: float = field(default_factory=time.monotonic)

    @classmethod
    def from_settings(cls) -> BudgetTracker:
        settings = get_settings()
        return cls(
            max_tokens=settings.agent.max_tokens_per_task,
            max_cost_usd=settings.guardrails.max_cost_per_task_usd,
            max_iterations=settings.agent.max_agent_iterations,
            max_wall_seconds=settings.agent.agent_timeout_seconds,
        )

    def record_usage(self, model: str, input_tokens: int, output_tokens: int) -> None:
        self.total_input_tokens += input_tokens
        self.total_output_tokens += output_tokens
        self.iteration_count += 1

        costs = COST_PER_MILLION.get(model, DEFAULT_COST)
        self.total_cost_usd += (
            input_tokens * costs["input"] / 1_000_000 + output_tokens * costs["output"] / 1_000_000
        )

    @property
    def total_tokens(self) -> int:
        return self.total_input_tokens + self.total_output_tokens

    @property
    def elapsed_seconds(self) -> float:
        return time.monotonic() - self.start_time

    @property
    def tokens_exceeded(self) -> bool:
        return self.total_tokens > self.max_tokens

    @property
    def cost_exceeded(self) -> bool:
        return self.total_cost_usd > self.max_cost_usd

    @property
    def iterations_exceeded(self) -> bool:
        return self.iteration_count > self.max_iterations

    @property
    def time_exceeded(self) -> bool:
        return self.elapsed_seconds > self.max_wall_seconds

    def check(self) -> str | None:
        """Return an error after measured usage has exceeded a budget."""
        if self.tokens_exceeded:
            return f"Token budget exceeded: {self.total_tokens:,}/{self.max_tokens:,}"
        if self.cost_exceeded:
            return f"Cost budget exceeded: ${self.total_cost_usd:.4f}/${self.max_cost_usd:.2f}"
        if self.iterations_exceeded:
            return f"Iteration limit exceeded: {self.iteration_count}/{self.max_iterations}"
        if self.time_exceeded:
            return f"Time limit exceeded: {self.elapsed_seconds:.0f}s/{self.max_wall_seconds:.0f}s"
        return None

    def check_before_call(self) -> str | None:
        """Prevent a new provider call when no measured budget remains."""
        if self.total_tokens >= self.max_tokens:
            return f"Token budget exhausted: {self.total_tokens:,}/{self.max_tokens:,}"
        if self.total_cost_usd >= self.max_cost_usd:
            return f"Cost budget exhausted: ${self.total_cost_usd:.4f}/${self.max_cost_usd:.2f}"
        if self.iteration_count >= self.max_iterations:
            return f"Iteration limit reached: {self.iteration_count}/{self.max_iterations}"
        if self.elapsed_seconds >= self.max_wall_seconds:
            return f"Time limit reached: {self.elapsed_seconds:.0f}s/{self.max_wall_seconds:.0f}s"
        return None

    @property
    def summary(self) -> dict[str, str | int | float]:
        return {
            "total_input_tokens": self.total_input_tokens,
            "total_output_tokens": self.total_output_tokens,
            "total_tokens": self.total_tokens,
            "estimated_cost_usd": round(self.total_cost_usd, 6),
            "iterations": self.iteration_count,
            "elapsed_seconds": round(self.elapsed_seconds, 1),
        }
