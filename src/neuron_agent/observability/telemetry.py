"""OpenTelemetry SDK setup (ADR 0007, decisions 1 and 3).

Telemetry is off by default: the global no-op providers stay in place, and no exporter is
created. When enabled, traces and metrics go over OTLP/HTTP to a Collector. Exports run on
background threads, so an unreachable Collector never fails a request.
"""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import FastAPI
from opentelemetry import metrics, trace
from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.sdk.trace.sampling import ParentBased, TraceIdRatioBased
from opentelemetry.util.re import parse_env_headers

from neuron_agent.config.settings import Settings
from neuron_agent.observability import semconv

# Platform probes are frequent and uninteresting; their requests are not traced.
_EXCLUDED_URLS = "/health/"


@dataclass(frozen=True)
class Telemetry:
    """The SDK providers built from `Settings`."""

    tracer_provider: TracerProvider
    meter_provider: MeterProvider

    def shutdown(self) -> None:
        """Flush and stop both providers."""
        self.tracer_provider.shutdown()
        self.meter_provider.shutdown()


def build_telemetry(settings: Settings) -> Telemetry | None:
    """Build OTLP-exporting providers, or return None when telemetry is disabled."""
    if not settings.otel_enabled:
        return None
    resource = Resource(
        {
            semconv.SERVICE_NAME: settings.otel_service_name or settings.name,
            semconv.SERVICE_VERSION: settings.version,
            semconv.DEPLOYMENT_ENVIRONMENT_NAME: settings.env,
        }
    )
    endpoint = settings.otel_exporter_otlp_endpoint.rstrip("/")
    secret_headers = settings.otel_exporter_otlp_headers
    headers = dict(
        parse_env_headers(secret_headers.get_secret_value() if secret_headers else "", liberal=True)
    )
    timeout = settings.otel_export_timeout_seconds

    tracer_provider = TracerProvider(
        resource=resource,
        sampler=ParentBased(TraceIdRatioBased(settings.otel_traces_sample_ratio)),
    )
    tracer_provider.add_span_processor(
        BatchSpanProcessor(
            OTLPSpanExporter(endpoint=f"{endpoint}/v1/traces", headers=headers, timeout=timeout)
        )
    )
    meter_provider = MeterProvider(
        resource=resource,
        metric_readers=[
            PeriodicExportingMetricReader(
                OTLPMetricExporter(
                    endpoint=f"{endpoint}/v1/metrics", headers=headers, timeout=timeout
                )
            )
        ],
    )
    return Telemetry(tracer_provider=tracer_provider, meter_provider=meter_provider)


def configure_telemetry(settings: Settings) -> Telemetry | None:
    """Install the providers globally when telemetry is enabled; once per process."""
    telemetry = build_telemetry(settings)
    if telemetry is not None:
        trace.set_tracer_provider(telemetry.tracer_provider)
        metrics.set_meter_provider(telemetry.meter_provider)
    return telemetry


def instrument_app(
    app: FastAPI,
    *,
    tracer_provider: trace.TracerProvider | None = None,
    meter_provider: metrics.MeterProvider | None = None,
) -> None:
    """Trace HTTP requests, honouring an incoming W3C `traceparent`.

    Spans are named by route template. The per-message ASGI `send`/`receive` spans are
    skipped; an SSE stream would otherwise produce one per event.
    """
    FastAPIInstrumentor.instrument_app(
        app,
        tracer_provider=tracer_provider,
        meter_provider=meter_provider,
        excluded_urls=_EXCLUDED_URLS,
        exclude_spans=["receive", "send"],
    )


def record_correlation_id(correlation_id: str) -> None:
    """Record the request's `X-Correlation-ID` on the current server span."""
    trace.get_current_span().set_attribute(semconv.NEURON_CORRELATION_ID, correlation_id)
