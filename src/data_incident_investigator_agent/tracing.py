import base64
import os

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor


def setup_tracing() -> trace.Tracer:
    """Send OpenTelemetry spans to Langfuse (keys come from .env).

    Without Langfuse keys (e.g. in CI or tests) this returns a no-op tracer, so the code still runs.
    """
    public, secret = os.environ.get("LANGFUSE_PUBLIC_KEY"), os.environ.get("LANGFUSE_SECRET_KEY")
    if not (public and secret):
        return trace.get_tracer("incident-agent")  # no provider set -> spans go nowhere

    host = os.environ.get("LANGFUSE_HOST", "https://cloud.langfuse.com")
    auth = base64.b64encode(f"{public}:{secret}".encode()).decode()
    exporter = OTLPSpanExporter(
        endpoint=f"{host}/api/public/otel/v1/traces",
        headers={"Authorization": f"Basic {auth}"},
    )
    provider = TracerProvider(resource=Resource.create({"service.name": "incident-agent"}))
    provider.add_span_processor(BatchSpanProcessor(exporter))  # sends spans in batches, in the background
    trace.set_tracer_provider(provider)
    return trace.get_tracer("incident-agent")


def flush() -> None:
    """Send any spans still waiting in the batch before the program exits."""
    provider = trace.get_tracer_provider()
    if hasattr(provider, "force_flush"):
        provider.force_flush()
