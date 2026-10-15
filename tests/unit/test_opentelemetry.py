from __future__ import annotations

import ast
import re
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest
import structlog
import structlog.testing
from fastapi.testclient import TestClient
from opentelemetry import trace
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.sdk.trace.sampling import ParentBased

from neuron_agent.api import main as api_main
from neuron_agent.api.main import app
from neuron_agent.config.settings import Settings
from neuron_agent.observability import semconv, telemetry
from neuron_agent.observability.logging import add_trace_context
from neuron_agent.schemas.agent import AgentResponse

_TRACE_ID = "0af7651916cd43dd8448eb211c80319c"
_TRACEPARENT = f"00-{_TRACE_ID}-b7ad6b7169203331-01"
_SRC = Path(__file__).parents[2] / "src" / "neuron_agent"


@contextmanager
def _instrumented(provider: TracerProvider) -> Iterator[TestClient]:
    """Re-instrument the app with `provider`, then restore the default instrumentation."""
    FastAPIInstrumentor.uninstrument_app(app)
    telemetry.instrument_app(app, tracer_provider=provider)
    # Instrumenting patches how the stack is built; a built stack would keep the old one.
    app.middleware_stack = None
    try:
        yield TestClient(app)
    finally:
        FastAPIInstrumentor.uninstrument_app(app)
        telemetry.instrument_app(app)
        app.middleware_stack = None


def _in_memory_provider() -> tuple[TracerProvider, InMemorySpanExporter]:
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    return provider, exporter


_PROVIDER, _SPANS = _in_memory_provider()


@pytest.fixture
def spans() -> Iterator[InMemorySpanExporter]:
    _SPANS.clear()
    yield _SPANS
    _SPANS.clear()


@pytest.fixture
def fast_invoke(monkeypatch: pytest.MonkeyPatch) -> None:
    async def invoke(self: object, request: object) -> AgentResponse:
        return AgentResponse(
            request_id="request-1", thread_id="thread-1", answer="ok", used_tools=[], confidence=1.0
        )

    monkeypatch.setattr(api_main.AgentService, "invoke", invoke)


def test_disabled_telemetry_creates_no_exporter_and_keeps_no_op_providers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def no_exporter(*_: Any, **__: Any) -> None:
        raise AssertionError("no exporter may be created when telemetry is disabled")

    monkeypatch.setattr(telemetry, "OTLPSpanExporter", no_exporter)
    monkeypatch.setattr(telemetry, "OTLPMetricExporter", no_exporter)

    assert telemetry.configure_telemetry(Settings(env="test")) is None
    assert not isinstance(trace.get_tracer_provider(), TracerProvider)
    assert not trace.get_current_span().get_span_context().is_valid


def test_enabled_telemetry_sets_resource_sampler_and_exporter_targets(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    exporters: list[dict[str, Any]] = []

    def recording(cls: Any) -> Any:
        def build(**kwargs: Any) -> Any:
            exporters.append(kwargs)
            return cls(**kwargs)

        return build

    monkeypatch.setattr(telemetry, "OTLPSpanExporter", recording(telemetry.OTLPSpanExporter))
    monkeypatch.setattr(telemetry, "OTLPMetricExporter", recording(telemetry.OTLPMetricExporter))
    settings = Settings(
        env="test",
        otel_enabled=True,
        otel_traces_sample_ratio=0.25,
        OTEL_EXPORTER_OTLP_ENDPOINT="https://collector.example:4318/",
        OTEL_EXPORTER_OTLP_HEADERS="authorization=Bearer%20abc,x-tenant=neuron",
    )

    built = telemetry.build_telemetry(settings)
    assert built is not None
    try:
        attributes = built.tracer_provider.resource.attributes
        assert attributes[semconv.SERVICE_NAME] == "neuron-agent"
        assert attributes[semconv.SERVICE_VERSION] == settings.version
        assert attributes[semconv.DEPLOYMENT_ENVIRONMENT_NAME] == "test"
        assert built.meter_provider._sdk_config.resource is built.tracer_provider.resource
        sampler = built.tracer_provider.sampler
        assert isinstance(sampler, ParentBased)
        assert "0.25" in sampler.get_description()
        assert [e["endpoint"] for e in exporters] == [
            "https://collector.example:4318/v1/traces",
            "https://collector.example:4318/v1/metrics",
        ]
        headers = {"authorization": "Bearer abc", "x-tenant": "neuron"}
        assert all(e["headers"] == headers for e in exporters)
    finally:
        built.shutdown()


def test_service_name_setting_overrides_app_name() -> None:
    built = telemetry.build_telemetry(
        Settings(env="test", otel_enabled=True, otel_service_name="neuron-api")
    )
    assert built is not None
    try:
        assert built.tracer_provider.resource.attributes[semconv.SERVICE_NAME] == "neuron-api"
    finally:
        built.shutdown()


@pytest.mark.usefixtures("fast_invoke")
def test_request_honours_traceparent_and_correlates_logs_and_span(
    spans: InMemorySpanExporter,
) -> None:
    with (
        _instrumented(_PROVIDER) as client,
        structlog.testing.capture_logs(
            processors=[structlog.contextvars.merge_contextvars, add_trace_context]
        ) as logs,
    ):
        response = client.post(
            "/v1/agent/invoke",
            json={"message": "hi"},
            headers={"traceparent": _TRACEPARENT, "X-Correlation-ID": "corr-1"},
        )

    assert response.status_code == 200
    [server] = spans.get_finished_spans()
    assert server.kind is trace.SpanKind.SERVER
    assert server.name == "POST /v1/agent/invoke"
    assert format(server.context.trace_id, "032x") == _TRACE_ID
    assert server.attributes is not None
    assert server.attributes[semconv.NEURON_CORRELATION_ID] == "corr-1"
    [completed] = [log for log in logs if log["event"] == "agent_request_completed"]
    assert completed["trace_id"] == _TRACE_ID
    assert completed["span_id"] == format(server.context.span_id, "016x")


def test_spans_use_route_templates_and_skip_health(spans: InMemorySpanExporter) -> None:
    with _instrumented(_PROVIDER) as client:
        assert client.get("/health/live").status_code == 200
        client.get(f"/v1/threads/{'0' * 8}-0000-0000-0000-{'0' * 12}/messages")

    [server] = spans.get_finished_spans()
    assert server.name == "GET /v1/threads/{thread_id}/messages"
    assert server.attributes is not None
    assert server.attributes["http.route"] == "/v1/threads/{thread_id}/messages"


@pytest.mark.usefixtures("fast_invoke")
def test_unreachable_collector_never_fails_a_request(caplog: pytest.LogCaptureFixture) -> None:
    built = telemetry.build_telemetry(
        Settings(
            env="test",
            otel_enabled=True,
            otel_export_timeout_seconds=0.5,
            OTEL_EXPORTER_OTLP_ENDPOINT="http://127.0.0.1:9",
        )
    )
    assert built is not None
    try:
        with _instrumented(built.tracer_provider) as client:
            response = client.post("/v1/agent/invoke", json={"message": "hi"})
        assert response.status_code == 200
    finally:
        started = time.monotonic()
        built.shutdown()
    assert time.monotonic() - started < 5
    assert "Failed to export span batch" in caplog.text


def test_log_lines_outside_a_span_carry_no_trace_ids() -> None:
    with structlog.testing.capture_logs(processors=[add_trace_context]) as logs:
        structlog.get_logger().info("evt")
    assert "trace_id" not in logs[0]
    assert "span_id" not in logs[0]


_TELEMETRY_NAME = re.compile(
    r"(gen_ai|neuron|service|deployment|error|http|url|server|client|network|user_agent)"
    r"(\.[a-z0-9_]+)+"
)


def test_telemetry_names_are_defined_only_in_semconv() -> None:
    """Span, metric and attribute names are string literals in `semconv.py` alone."""
    offenders = [
        f"{path.relative_to(_SRC)}:{node.lineno}: {node.value!r}"
        for path in _SRC.rglob("*.py")
        if path.name != "semconv.py"
        for node in ast.walk(ast.parse(path.read_text()))
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and _TELEMETRY_NAME.fullmatch(node.value)
    ]
    assert offenders == [], "move these names to observability/semconv.py"


def test_configured_logging_adds_trace_context() -> None:
    assert add_trace_context in structlog.get_config()["processors"]
