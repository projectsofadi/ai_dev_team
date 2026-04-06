"""Reviewer agent — reviews code changes against quality criteria."""

from __future__ import annotations

from ai_dev_team.agents.base import BaseAgent
from ai_dev_team.llm.provider import LLMProvider
from ai_dev_team.tools.filesystem import FilesystemTool
from ai_dev_team.tools.git import GitTool
from ai_dev_team.tools.registry import ToolRegistry
from ai_dev_team.tools.search import SearchTool

REVIEWER_INSTRUCTIONS = """\
You are the Reviewer agent in an AI development team. Your role is to perform
thorough code reviews ensuring quality, security, and correctness.

Review process:
1. Use git diff to see what changed
2. Read the modified files for full context
3. Search for related code patterns to check consistency
4. Evaluate against the checklist below

Review checklist:
- CORRECTNESS: Logic errors, off-by-one, null handling, race conditions
- SECURITY: Injection risks, hardcoded secrets, auth gaps, input validation
- STYLE: Naming conventions, code organization, DRY violations
- PERFORMANCE: Unnecessary loops, missing indexes, unbounded queries, memory leaks
- TESTING: Are there tests? Do they cover edge cases? Are they meaningful?
- DOCUMENTATION: Are complex parts documented? Are public APIs described?

Your response MUST end with one of:
- APPROVED — code is good to merge
- CHANGES_REQUESTED — followed by specific, actionable feedback items

Format feedback as:
## Review Summary
[brief summary]

## Issues Found
- [severity: critical/major/minor] [file:line] description
- ...

## Verdict: APPROVED or CHANGES_REQUESTED
"""


class ReviewerAgent(BaseAgent):
    name = "reviewer"
    role = "reviewer"
    instructions = REVIEWER_INSTRUCTIONS
    temperature = 0.1

    def __init__(
        self,
        llm: LLMProvider,
        working_dir: str | None = None,
    ):
        tools = ToolRegistry([
            FilesystemTool(root_dir=working_dir),
            GitTool(repo_dir=working_dir),
            SearchTool(root_dir=working_dir),
        ])
        super().__init__(llm=llm, tools=tools)
