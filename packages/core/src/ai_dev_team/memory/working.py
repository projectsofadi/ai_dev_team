"""Working memory — token-aware conversation context management."""

from __future__ import annotations

from ai_dev_team.llm.provider import ChatMessage, Role


def estimate_tokens(text: str) -> int:
    """Fast heuristic: ~4 chars per token for English text."""
    return max(1, len(text) // 4)


def message_tokens(msg: ChatMessage) -> int:
    """Estimate token count for a single message."""
    count = estimate_tokens(msg.content)
    if msg.tool_calls:
        for tc in msg.tool_calls:
            count += estimate_tokens(tc.name) + estimate_tokens(str(tc.arguments))
    if msg.tool_result:
        count += estimate_tokens(msg.tool_result.output)
    return count + 4  # role/formatting overhead


class WorkingMemory:
    """
    Manages conversation context with token-aware truncation.

    Preserves the system message and most recent messages, truncating
    from the middle when the token budget is exceeded.
    """

    def __init__(self, max_tokens: int = 32_000):
        self.max_tokens = max_tokens
        self._messages: list[ChatMessage] = []

    @property
    def messages(self) -> list[ChatMessage]:
        return list(self._messages)

    @property
    def token_count(self) -> int:
        return sum(message_tokens(m) for m in self._messages)

    def add(self, message: ChatMessage) -> None:
        self._messages.append(message)
        self._truncate_if_needed()

    def add_many(self, messages: list[ChatMessage]) -> None:
        self._messages.extend(messages)
        self._truncate_if_needed()

    def clear(self) -> None:
        self._messages.clear()

    def get_context(self) -> list[ChatMessage]:
        """Return the current message list, ready for LLM consumption."""
        return list(self._messages)

    def _truncate_if_needed(self) -> None:
        """Truncate from the middle, preserving system prompt and recent messages."""
        if self.token_count <= self.max_tokens:
            return

        system_msgs = [m for m in self._messages if m.role == Role.SYSTEM]
        non_system = [m for m in self._messages if m.role != Role.SYSTEM]

        system_tokens = sum(message_tokens(m) for m in system_msgs)
        remaining_budget = self.max_tokens - system_tokens

        # Keep recent messages, drop from the front of non-system
        kept: list[ChatMessage] = []
        total = 0
        for msg in reversed(non_system):
            msg_tok = message_tokens(msg)
            if total + msg_tok > remaining_budget:
                break
            kept.insert(0, msg)
            total += msg_tok

        if kept and non_system and kept[0] != non_system[0]:
            summary = ChatMessage(
                role=Role.SYSTEM,
                content=(
                    "[Earlier conversation truncated to fit context window. "
                    f"Removed {len(non_system) - len(kept)} messages.]"
                ),
            )
            self._messages = system_msgs + [summary] + kept
        else:
            self._messages = system_msgs + kept

    def compact_for_handoff(self, summary: str) -> list[ChatMessage]:
        """Create a compact message list for handing off to another agent."""
        system_msgs = [m for m in self._messages if m.role == Role.SYSTEM]
        return system_msgs + [
            ChatMessage(
                role=Role.USER,
                content=f"[Handoff context]\n{summary}",
            ),
        ]
