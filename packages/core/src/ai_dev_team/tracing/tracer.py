"""OpenTelemetry tracer setup for the agent system."""

from __future__ import annotations

from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import (
    BatchSpanProcessor,
    ConsoleSpanExporter,
    SpanExporter,
)

from ai_dev_team.config import get_settings

_initialized = False


def init_tracing(
    exporter: SpanExporter | None = None,
    use_console: bool = False,
) -> trace.Tracer:
    """
    Initialize OpenTelemetry tracing.

    Falls back to console exporter in dev mode, OTLP in production.
    """
    global _initialized
    if _initialized:
        return trace.get_tracer("ai-dev-team")

    settings = get_settings()

    resource = Resource.create({
        "service.name": settings.observability.otel_service_name,
        "service.version": "0.1.0",
    })

    provider = TracerProvider(resource=resource)

    if exporter:
        provider.add_span_processor(BatchSpanProcessor(exporter))
    elif use_console:
        provider.add_span_processor(BatchSpanProcessor(ConsoleSpanExporter()))
    else:
        try:
            from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import (
                OTLPSpanExporter,
            )

            otlp_exporter = OTLPSpanExporter(
                endpoint=settings.observability.otel_exporter_otlp_endpoint,
            )
            provider.add_span_processor(BatchSpanProcessor(otlp_exporter))
        except ImportError:
            provider.add_span_processor(BatchSpanProcessor(ConsoleSpanExporter()))

    trace.set_tracer_provider(provider)
    _initialized = True

    return trace.get_tracer("ai-dev-team")


def get_tracer() -> trace.Tracer:
    """Get the configured tracer, initializing if needed."""
    if not _initialized:
        return init_tracing(use_console=True)
    return trace.get_tracer("ai-dev-team")
