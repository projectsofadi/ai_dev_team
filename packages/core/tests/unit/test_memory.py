"""Unit tests for working memory."""

from __future__ import annotations

from ai_dev_team.llm.provider import ChatMessage, Role
from ai_dev_team.memory.working import WorkingMemory, estimate_tokens, message_tokens


class TestEstimateTokens:
    def test_empty(self):
        assert estimate_tokens("") == 1

    def test_basic(self):
        assert estimate_tokens("hello world") > 0

    def test_scales_with_length(self):
        short = estimate_tokens("hi")
        long = estimate_tokens("x" * 1000)
        assert long > short


class TestWorkingMemory:
    def test_add_and_get(self):
        mem = WorkingMemory(max_tokens=100_000)
        mem.add(ChatMessage(role=Role.USER, content="hello"))
        assert len(mem.messages) == 1

    def test_token_count(self):
        mem = WorkingMemory()
        mem.add(ChatMessage(role=Role.USER, content="a" * 100))
        assert mem.token_count > 0

    def test_truncation(self):
        mem = WorkingMemory(max_tokens=100)
        mem.add(ChatMessage(role=Role.SYSTEM, content="You are helpful"))
        for i in range(20):
            mem.add(ChatMessage(role=Role.USER, content=f"Message {i} " + "x" * 50))

        assert mem.token_count <= 100 + 50  # some overhead tolerance

    def test_system_preserved_on_truncation(self):
        mem = WorkingMemory(max_tokens=100)
        mem.add(ChatMessage(role=Role.SYSTEM, content="System prompt"))
        for i in range(20):
            mem.add(ChatMessage(role=Role.USER, content=f"Msg {i} " + "y" * 50))

        messages = mem.messages
        assert messages[0].role == Role.SYSTEM
        assert "System prompt" in messages[0].content

    def test_clear(self):
        mem = WorkingMemory()
        mem.add(ChatMessage(role=Role.USER, content="hi"))
        mem.clear()
        assert len(mem.messages) == 0

    def test_compact_for_handoff(self):
        mem = WorkingMemory()
        mem.add(ChatMessage(role=Role.SYSTEM, content="You are a coder"))
        mem.add(ChatMessage(role=Role.USER, content="Write some code"))
        mem.add(ChatMessage(role=Role.ASSISTANT, content="Here is the code"))

        compact = mem.compact_for_handoff("Summary of prior work")
        assert len(compact) == 2
        assert compact[0].role == Role.SYSTEM
        assert "Handoff" in compact[1].content
