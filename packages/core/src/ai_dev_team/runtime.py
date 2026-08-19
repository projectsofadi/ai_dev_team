"""Runtime construction shared by the CLI and the API bridge."""

from __future__ import annotations

from ai_dev_team.agents.coder import CoderAgent
from ai_dev_team.agents.orchestrator import OrchestratorAgent
from ai_dev_team.agents.planner import PlannerAgent
from ai_dev_team.agents.reviewer import ReviewerAgent
from ai_dev_team.agents.tester import TesterAgent
from ai_dev_team.config import get_settings
from ai_dev_team.llm.anthropic import AnthropicProvider
from ai_dev_team.llm.openai import OpenAIProvider


def build_orchestrator(working_dir: str | None = None) -> OrchestratorAgent:
    """Build one configured agent team rooted at ``working_dir``."""
    settings = get_settings()
    llm = OpenAIProvider() if settings.llm.default_provider == "openai" else AnthropicProvider()

    planner = PlannerAgent(llm=llm)
    coder = CoderAgent(llm=llm, working_dir=working_dir)
    reviewer = ReviewerAgent(llm=llm, working_dir=working_dir)
    tester = TesterAgent(llm=llm, working_dir=working_dir)
    return OrchestratorAgent(
        llm=llm,
        planner=planner,
        coder=coder,
        reviewer=reviewer,
        tester=tester,
    )
