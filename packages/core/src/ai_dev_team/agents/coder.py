"""Coder agent — generates and modifies code using filesystem and shell tools."""

from __future__ import annotations

from ai_dev_team.agents.base import BaseAgent
from ai_dev_team.llm.provider import LLMProvider
from ai_dev_team.tools.filesystem import FilesystemTool
from ai_dev_team.tools.git import GitTool
from ai_dev_team.tools.registry import ApprovalCallback, ToolRegistry
from ai_dev_team.tools.search import SearchTool
from ai_dev_team.tools.shell import ShellTool

CODER_INSTRUCTIONS = """\
You are the Coder agent in an AI development team. Your role is to write
high-quality, production-ready code.

Guidelines:
1. Write clean, well-structured code following language best practices
2. Use proper error handling and input validation
3. Follow existing project conventions and patterns
4. Create files incrementally — read existing code first to understand context
5. Use the search tool to find relevant code before making changes
6. Run tests after making changes to verify correctness
7. Use git to track your changes

When writing code:
- Prefer explicit over implicit
- Use type hints / type annotations
- Handle edge cases
- Write self-documenting code with meaningful names
- Only add comments for non-obvious logic

Available tools: filesystem (read/write/list), shell (run commands),
git (status/diff/commit), search (find code patterns).
"""


class CoderAgent(BaseAgent):
    name = "coder"
    role = "coder"
    instructions = CODER_INSTRUCTIONS
    max_tokens = 8192

    def __init__(
        self,
        llm: LLMProvider,
        working_dir: str | None = None,
        approval_callback: ApprovalCallback | None = None,
    ):
        tools = ToolRegistry(
            [
                FilesystemTool(root_dir=working_dir),
                ShellTool(working_dir=working_dir),
                GitTool(repo_dir=working_dir),
                SearchTool(root_dir=working_dir),
            ],
            enforce_configured_approvals=True,
            approval_callback=approval_callback,
        )
        super().__init__(llm=llm, tools=tools)
