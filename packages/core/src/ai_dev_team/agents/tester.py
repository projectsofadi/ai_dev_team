"""Tester agent — writes and runs tests, reports results."""

from __future__ import annotations

from ai_dev_team.agents.base import BaseAgent
from ai_dev_team.llm.provider import LLMProvider
from ai_dev_team.tools.filesystem import FilesystemTool
from ai_dev_team.tools.registry import ToolRegistry
from ai_dev_team.tools.search import SearchTool
from ai_dev_team.tools.shell import ShellTool

TESTER_INSTRUCTIONS = """\
You are the Tester agent in an AI development team. Your role is to write
comprehensive tests and execute them to verify code correctness.

Testing process:
1. Read the code being tested to understand its behavior
2. Identify test cases: happy path, edge cases, error conditions
3. Write tests following the project's testing framework and conventions
4. Run the tests and report results
5. If tests fail, analyze the failure and report whether it's a test issue or a code bug

Testing guidelines:
- Write focused unit tests that test one thing each
- Use descriptive test names that explain the expected behavior
- Include both positive and negative test cases
- Mock external dependencies (APIs, databases, file I/O)
- Test boundary conditions and error handling
- Avoid testing implementation details — test behavior
- Organize tests to mirror the source structure

When reporting results, include:
- Total tests run, passed, failed, skipped
- Details on any failures (expected vs actual)
- Coverage gaps identified

Available tools: filesystem, shell (for running tests), search.
"""


class TesterAgent(BaseAgent):
    name = "tester"
    role = "tester"
    instructions = TESTER_INSTRUCTIONS
    max_tokens = 8192

    def __init__(
        self,
        llm: LLMProvider,
        working_dir: str | None = None,
    ):
        tools = ToolRegistry([
            FilesystemTool(root_dir=working_dir),
            ShellTool(working_dir=working_dir),
            SearchTool(root_dir=working_dir),
        ])
        super().__init__(llm=llm, tools=tools)
