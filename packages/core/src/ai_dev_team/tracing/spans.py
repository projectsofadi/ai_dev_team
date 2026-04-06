"""GenAI semantic convention span helpers."""

from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Generator

from opentelemetry import trace
from opentelemetry.trace import Span, StatusCode

from ai_dev_team.llm.provider import LLMResponse, TokenUsage
from ai_dev_team.tracing.tracer import get_tracer

GEN_AI_OPERATION_NAME = "gen_ai.operation.name"
GEN_AI_PROVIDER_NAME = "gen_ai.provider.name"
GEN_AI_REQUEST_MODEL = "gen_ai.request.model"
GEN_AI_RESPONSE_MODEL = "gen_ai.response.model"
GEN_AI_USAGE_INPUT = "gen_ai.usage.input_tokens"
GEN_AI_USAGE_OUTPUT = "gen_ai.usage.output_tokens"
GEN_AI_RESPONSE_FINISH = "gen_ai.response.finish_reasons"
GEN_AI_CONVERSATION_ID = "gen_ai.conversation.id"
GEN_AI_TOOL_NAME = "gen_ai.tool.name"
GEN_AI_TOOL_CALL_ID = "gen_ai.tool.call.id"


@contextmanager
def agent_span(
    agent_name: str,
    task_id: str = "",
    conversation_id: str = "",
) -> Generator[Span, None, None]:
    """Root span for an agent execution."""
    tracer = get_tracer()
    with tracer.start_as_current_span(
        f"agent.run {agent_name}",
        kind=trace.SpanKind.INTERNAL,
    ) as span:
        span.set_attribute("agent.name", agent_name)
        if task_id:
            span.set_attribute("agent.task.id", task_id)
        if conversation_id:
            span.set_attribute(GEN_AI_CONVERSATION_ID, conversation_id)
        yield span


@contextmanager
def llm_span(
    model: str,
    provider: str,
    operation: str = "chat",
) -> Generator[Span, None, None]:
    """Child span for an LLM API call."""
    tracer = get_tracer()
    with tracer.start_as_current_span(
        f"{operation} {model}",
        kind=trace.SpanKind.CLIENT,
    ) as span:
        span.set_attribute(GEN_AI_OPERATION_NAME, operation)
        span.set_attribute(GEN_AI_PROVIDER_NAME, provider)
        span.set_attribute(GEN_AI_REQUEST_MODEL, model)
        yield span


def record_llm_response(span: Span, response: LLMResponse) -> None:
    """Record LLM response attributes on a span."""
    span.set_attribute(GEN_AI_RESPONSE_MODEL, response.model)
    span.set_attribute(GEN_AI_USAGE_INPUT, response.usage.input_tokens)
    span.set_attribute(GEN_AI_USAGE_OUTPUT, response.usage.output_tokens)
    span.set_attribute(GEN_AI_RESPONSE_FINISH, [response.finish_reason])


@contextmanager
def tool_span(
    tool_name: str,
    call_id: str = "",
) -> Generator[Span, None, None]:
    """Child span for tool execution."""
    tracer = get_tracer()
    with tracer.start_as_current_span(
        f"execute_tool {tool_name}",
        kind=trace.SpanKind.INTERNAL,
    ) as span:
        span.set_attribute(GEN_AI_OPERATION_NAME, "execute_tool")
        span.set_attribute(GEN_AI_TOOL_NAME, tool_name)
        if call_id:
            span.set_attribute(GEN_AI_TOOL_CALL_ID, call_id)
        yield span


def record_tool_error(span: Span, error: str) -> None:
    """Record a tool execution error."""
    span.set_status(StatusCode.ERROR, error)
    span.record_exception(Exception(error))
