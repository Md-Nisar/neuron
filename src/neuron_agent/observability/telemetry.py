"""OpenTelemetry SDK setup (ADR 0007, decisions 1 and 3).

Telemetry is off by default: the global no-op providers stay in place, and no exporter is
created. When enabled, traces and metrics go over OTLP/HTTP to a Collector. Exports run on
background threads, so an unreachable Collector never fails a request.
"""

from __future__ import annotations

import random
from collections.abc import Sequence
from dataclasses import dataclass

from fastapi import FastAPI
from opentelemetry import metrics, trace
from opentelemetry.context import Context
from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.sdk.trace.sampling import (
    Decision,
    ParentBased,
    Sampler,
    SamplingResult,
    TraceIdRatioBased,
)
from opentelemetry.trace import Link, SpanKind, TraceState
from opentelemetry.util.re import parse_env_headers
from opentelemetry.util.types import Attributes

from neuron_agent.config.settings import Settings
from neuron_agent.observability import semconv

# Platform probes are frequent and uninteresting; their requests are not traced.
_EXCLUDED_URLS = "/health/"
_RANDOM = random.SystemRandom()


class _CallerIndependentSampler(Sampler):
    """Sample a request with a remote parent at the configured ratio, by a random draw.

    A caller's `traceparent` is untrusted: its sampled flag would let it force or suppress
    tracing, and its trace id is chosen by the caller, so `TraceIdRatioBased` could be
    gamed too. The trace id is still kept, so the trace stays connected to the caller's.
    """

    def __init__(self, ratio: float) -> None:
        self._ratio = ratio

    def should_sample(
        self,
        parent_context: Context | None,
        trace_id: int,
        name: str,
        kind: SpanKind | None = None,
        attributes: Attributes = None,
        links: Sequence[Link] | None = None,
        trace_state: TraceState | None = None,
    ) -> SamplingResult:
        sampled = _RANDOM.random() < self._ratio
        parent_state = trace.get_current_span(parent_context).get_span_context().trace_state
        return SamplingResult(
            Decision.RECORD_AND_SAMPLE if sampled else Decision.DROP,
            attributes if sampled else None,
            parent_state,
        )

    def get_description(self) -> str:
        return f"CallerIndependentSampler{{{self._ratio}}}"


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
        sampler=_sampler(settings.otel_traces_sample_ratio),
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


def _sampler(ratio: float) -> Sampler:
    """Head-sample new traces at `ratio`; spans with a local parent follow its decision."""
    remote = _CallerIndependentSampler(ratio)
    return ParentBased(
        TraceIdRatioBased(ratio),
        remote_parent_sampled=remote,
        remote_parent_not_sampled=remote,
    )


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
