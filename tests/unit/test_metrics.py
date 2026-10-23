"""Metrics (ADR 0007 decision 2, #92): instruments, label allow-list and buckets."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import InMemoryMetricReader
from opentelemetry.sdk.metrics.export import Metric as SdkMetric
from pydantic import SecretStr
from tests.conftest import HistoryEchoAgent, JwtApi, bearer

from neuron_agent.api.main import app
from neuron_agent.config.settings import Settings
from neuron_agent.graphs import main_graph
from neuron_agent.models.factory import tracing_middleware
from neuron_agent.observability import metrics, semconv, telemetry
from neuron_agent.persistence.checkpointer import build_persistence
from neuron_agent.services.agent_service import AgentService, PreparedRun

_SUB = "raw-subject-7f3a"
_EXPRESSION = "987654321*3"
_ROUTES = {"/v1/agent/invoke", "/v1/agent/stream"}


class Collector:
    """An in-memory metric reader that also records the IDs a test must never see as labels."""

    def __init__(self, reader: InMemoryMetricReader) -> None:
        self.reader = reader
        self.identifiers: set[str] = {_SUB}

    def metrics(self) -> dict[str, SdkMetric]:
        data = self.reader.get_metrics_data()
        assert data is not None
        return {
            metric.name: metric
            for resource in data.resource_metrics
            for scope in resource.scope_metrics
            for metric in scope.metrics
        }

    def points(self, name: str) -> list[Any]:
        return list(self.metrics()[name].data.data_points)


@pytest.fixture
def collected(monkeypatch: pytest.MonkeyPatch) -> Iterator[Collector]:
    """Send agent and HTTP metrics to an in-memory reader, and note every ID that is minted."""
    reader = InMemoryMetricReader()
    provider = MeterProvider(metric_readers=[reader], views=metrics.metric_views())
    monkeypatch.setattr(metrics, "_meter", lambda: provider.get_meter("test"))
    collector = Collector(reader)

    original = AgentService.prepare

    async def prepare(self: AgentService, *args: Any, **kwargs: Any) -> PreparedRun:
        run = await original(self, *args, **kwargs)
        collector.identifiers.update(
            {run.request_id, run.thread_id, run.run_id, run.budget_key}
            | ({run.checkpoint_owner} if run.checkpoint_owner else set())
        )
        return run

    monkeypatch.setattr(AgentService, "prepare", prepare)
    FastAPIInstrumentor.uninstrument_app(app)
    telemetry.instrument_app(app, meter_provider=provider)
    # Instrumenting patches how the stack is built; a built stack would keep the old one.
    app.middleware_stack = None
    yield collector
    FastAPIInstrumentor.uninstrument_app(app)
    telemetry.instrument_app(app)
    app.middleware_stack = None


def _drive_service(api: JwtApi, token: str) -> None:
    """A tool call, a stream and a policy block."""
    headers = bearer(token)
    assert api.client.post("/v1/agent/invoke", json={"message": "hi"}, headers=headers).is_success
    with api.client.stream(
        "POST", "/v1/agent/stream", json={"message": "again"}, headers=headers
    ) as stream:
        assert any(line.startswith("event: final") for line in stream.iter_lines())
    blocked = api.client.post("/v1/agent/invoke", json={"message": "   "}, headers=headers)
    assert blocked.status_code in {400, 422}


def test_every_instrument_is_emitted_with_only_allow_listed_labels(
    collected: Collector,
    stream_replies: Callable[..., Any],
    jwt_api_factory: Callable[..., JwtApi],
    make_token: Callable[..., str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    call = {"name": "calculator", "args": {"expression": _EXPRESSION}, "id": "call-1"}
    stream_replies(
        AIMessage(content="", tool_calls=[call]),
        AIMessage(content="first answer"),
        AIMessage(content="streamed answer"),
    )
    _drive_service(jwt_api_factory(), make_token(_SUB))

    # A failed run, on a second app whose agent raises.
    agent = HistoryEchoAgent()
    agent.fail_next = True
    monkeypatch.setattr(main_graph, "build_agent", lambda settings: agent)
    failing = jwt_api_factory()
    response = failing.client.post(
        "/v1/agent/invoke", json={"message": "boom"}, headers=bearer(make_token(_SUB))
    )
    assert response.status_code == 500

    found = collected.metrics()
    expected = {
        semconv.METRIC_OPERATION_DURATION,
        semconv.METRIC_RUN_DURATION,
        semconv.METRIC_STREAM_TTFT,
        semconv.METRIC_TOOL_DURATION,
        semconv.METRIC_ERRORS,
        semconv.METRIC_POLICY_BLOCKS,
        semconv.METRIC_CHECKPOINT_DURATION,
        semconv.METRIC_HTTP_REQUEST_DURATION,
        semconv.METRIC_HTTP_RESPONSE_BODY_SIZE,
        semconv.METRIC_HTTP_ACTIVE_REQUESTS,
    }
    assert expected <= set(found)

    def attribute_sets(name: str) -> list[dict[str, Any]]:
        return [dict(point.attributes) for point in collected.points(name)]

    assert {"calculator"} == {
        a[semconv.GEN_AI_TOOL_NAME] for a in attribute_sets(semconv.METRIC_TOOL_DURATION)
    }
    assert {"success", "error"} >= {
        a[semconv.NEURON_OUTCOME] for a in attribute_sets(semconv.METRIC_RUN_DURATION)
    }
    assert {"agent_execution_error"} <= {
        a[semconv.ERROR_TYPE] for a in attribute_sets(semconv.METRIC_ERRORS)
    }
    assert {"empty_message"} == {
        a[semconv.NEURON_RULE] for a in attribute_sets(semconv.METRIC_POLICY_BLOCKS)
    }
    assert _ROUTES <= {
        a[semconv.HTTP_ROUTE] for a in attribute_sets(semconv.METRIC_HTTP_REQUEST_DURATION)
    }
    assert collected.points(semconv.METRIC_STREAM_TTFT)[0].count == 1

    assert len(collected.identifiers) > 5
    for name, metric in found.items():
        for point in metric.data.data_points:
            attributes = dict(point.attributes)
            assert set(attributes) <= semconv.METRIC_ATTRIBUTE_ALLOW_LIST, name
            for value in attributes.values():
                assert not any(
                    str(value) == known or known in str(value) for known in collected.identifiers
                ), (name, value)


@pytest.mark.anyio
async def test_token_usage_is_recorded_by_type_for_each_model_call(
    collected: Collector,
) -> None:
    message = AIMessage(
        content="ok",
        usage_metadata={"input_tokens": 120, "output_tokens": 30, "total_tokens": 150},
    )

    async def handler(_: object) -> Any:
        return SimpleNamespace(result=[message])

    middleware = tracing_middleware(Settings(env="test"))
    await middleware.awrap_model_call(object(), handler)

    points = {
        point.attributes[semconv.GEN_AI_USAGE_TYPE]: point
        for point in collected.points(semconv.METRIC_USAGE)
    }
    assert {name: point.sum for name, point in points.items()} == {"input": 120, "output": 30}
    assert set(points["input"].attributes) <= semconv.METRIC_ATTRIBUTE_ALLOW_LIST
    [operation] = collected.points(semconv.METRIC_OPERATION_DURATION)
    assert dict(operation.attributes) == {
        semconv.GEN_AI_OPERATION_NAME: "chat",
        semconv.GEN_AI_PROVIDER_NAME: "openai",
        semconv.GEN_AI_REQUEST_MODEL: "gpt-5.4-mini",
    }


@pytest.mark.anyio
async def test_failed_model_call_is_labelled_with_its_error_code(collected: Collector) -> None:
    async def handler(_: object) -> Any:
        raise RuntimeError("provider detail that must not leak")

    middleware = tracing_middleware(Settings(env="test"))
    with pytest.raises(RuntimeError):
        await middleware.awrap_model_call(object(), handler)

    [operation] = collected.points(semconv.METRIC_OPERATION_DURATION)
    assert operation.attributes[semconv.ERROR_TYPE] == "agent_execution_error"
    assert semconv.METRIC_USAGE not in collected.metrics()


def test_duration_buckets_cover_llm_latencies_up_to_two_minutes(collected: Collector) -> None:
    assert metrics.LLM_LATENCY_BUCKETS[0] <= 0.01
    assert metrics.LLM_LATENCY_BUCKETS[-1] == 120.0
    assert list(metrics.LLM_LATENCY_BUCKETS) == sorted(set(metrics.LLM_LATENCY_BUCKETS))

    metrics.record_model_call(0.3, provider="openai", model="m", error_type=None)
    metrics.record_run(45.0, outcome="success", error_type=None)
    metrics.record_stream_ttft(0.2, outcome="completed")
    metrics.record_tool_call(0.002, tool="calculator", outcome="success", error_type=None)
    metrics.record_checkpoint(0.004, outcome="success", error_type=None)
    TestClient(app).get("/health/live")  # excluded: no HTTP data point from probes

    for name in (
        semconv.METRIC_OPERATION_DURATION,
        semconv.METRIC_RUN_DURATION,
        semconv.METRIC_STREAM_TTFT,
    ):
        [point] = collected.points(name)
        assert tuple(point.explicit_bounds) == metrics.LLM_LATENCY_BUCKETS
    for name in (semconv.METRIC_TOOL_DURATION, semconv.METRIC_CHECKPOINT_DURATION):
        [point] = collected.points(name)
        assert tuple(point.explicit_bounds) == metrics.FAST_OPERATION_BUCKETS
    assert semconv.METRIC_HTTP_REQUEST_DURATION not in collected.metrics()


def test_http_metrics_keep_only_route_and_status(collected: Collector) -> None:
    assert TestClient(app).get("/openapi.json").status_code == 200
    [point] = collected.points(semconv.METRIC_HTTP_REQUEST_DURATION)
    assert dict(point.attributes) == {
        semconv.HTTP_ROUTE: "/openapi.json",
        semconv.HTTP_RESPONSE_STATUS_CODE: 200,
    }
    assert tuple(point.explicit_bounds) == metrics.LLM_LATENCY_BUCKETS


def _reported(collected: Collector, name: str) -> bool:
    """Whether the metric has a data point now (the reader has no data at all if none does)."""
    return collected.reader.get_metrics_data() is not None and name in collected.metrics()


def test_readiness_gauge_reports_the_latest_probe_with_no_labels(
    collected: Collector, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(metrics, "_last_ready", None)
    metrics.observe_pool_waiting(None)  # builds the instruments
    assert not _reported(collected, semconv.METRIC_SERVICE_READY)  # nothing probed yet

    client = TestClient(app)
    assert client.get("/health/ready").status_code == 200
    [point] = collected.points(semconv.METRIC_SERVICE_READY)
    assert point.value == 1 and dict(point.attributes) == {}

    async def not_ready(self: object) -> bool:
        return False

    monkeypatch.setattr(AgentService, "is_ready", not_ready)
    assert client.get("/health/ready").status_code == 503
    [point] = collected.points(semconv.METRIC_SERVICE_READY)
    assert point.value == 0 and dict(point.attributes) == {}


@pytest.mark.anyio
async def test_pool_waiting_gauge_follows_the_pool_and_stops_when_it_closes(
    collected: Collector, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(metrics, "_pool_waiting_source", None)
    settings = Settings(
        env="test",
        checkpointer="postgres",
        postgres_dsn=SecretStr("postgresql://neuron:pw@127.0.0.1:1/neuron"),
        postgres_pool_timeout_seconds=1,
        openai_api_key=None,
    )
    persistence = build_persistence(settings)
    assert persistence.pool is not None
    assert not _reported(collected, semconv.METRIC_DB_POOL_WAITING)  # not opened yet

    await persistence.open()
    try:
        [point] = collected.points(semconv.METRIC_DB_POOL_WAITING)
        assert point.value == persistence.pool.get_stats()["requests_waiting"] == 0
        assert dict(point.attributes) == {}
        metrics.observe_pool_waiting(lambda: 4)  # the pool's own statistic, as the pool reports it
        [point] = collected.points(semconv.METRIC_DB_POOL_WAITING)
        assert point.value == 4
    finally:
        await persistence.close()
    assert not _reported(collected, semconv.METRIC_DB_POOL_WAITING)


def test_configure_telemetry_runs_once_per_process(monkeypatch: pytest.MonkeyPatch) -> None:
    builds: list[Settings] = []
    monkeypatch.setattr(telemetry, "_configured", [])
    monkeypatch.setattr(telemetry, "build_telemetry", lambda s: builds.append(s))

    settings = Settings(env="test", otel_enabled=True)
    assert telemetry.configure_telemetry(settings) is None
    assert telemetry.configure_telemetry(settings) is None
    assert builds == [settings]


def test_each_process_has_its_own_service_instance_id() -> None:
    settings = Settings(env="test", otel_enabled=True)
    first, second = telemetry.build_telemetry(settings), telemetry.build_telemetry(settings)
    assert first is not None and second is not None
    try:
        ids = {
            t.tracer_provider.resource.attributes[semconv.SERVICE_INSTANCE_ID]
            for t in (first, second)
        }
        assert len(ids) == 2
    finally:
        first.shutdown()
        second.shutdown()
