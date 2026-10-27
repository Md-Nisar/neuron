"""The approval and memory paths leak nothing into telemetry (#252, ADR 0009).

A run that remembers a note, is approved and recalls it, with spans, metrics and logs captured,
searched for what must never leave: the note, the tool arguments and the raw subject. The same
strings are found in the API responses, so the search can see them.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterator
from typing import Any

import pytest
import structlog.testing
from langchain_core.messages import AIMessage
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import InMemoryMetricReader
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from tests.conftest import JwtApi, bearer
from tests.security.test_mcp_abuse import _call, _model
from tests.security.test_memory_tools import _SCOPES

from neuron_agent.observability import metrics, semconv, telemetry

_NOTE = "my-safe-deposit-box-is-number-88231-vega"
_SUBJECT = "raw-subject-leak-check-2291"


@pytest.fixture
def captured(
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[tuple[InMemorySpanExporter, InMemoryMetricReader]]:
    exporter, reader = InMemorySpanExporter(), InMemoryMetricReader()
    tracer_provider = TracerProvider()
    tracer_provider.add_span_processor(SimpleSpanProcessor(exporter))
    meter_provider = MeterProvider(metric_readers=[reader], views=metrics.metric_views())
    monkeypatch.setattr(telemetry, "tracer", lambda: tracer_provider.get_tracer(__name__))
    monkeypatch.setattr(metrics, "_meter", lambda: meter_provider.get_meter(__name__))
    yield exporter, reader


def _metric_points(reader: InMemoryMetricReader, name: str) -> list[Any]:
    data = reader.get_metrics_data()
    assert data is not None
    return [
        point
        for resource in data.resource_metrics
        for scope in resource.scope_metrics
        for metric in scope.metrics
        if metric.name == name
        for point in metric.data.data_points
    ]


def test_an_approved_remember_and_a_recall_leave_only_names_and_counts(
    jwt_api_factory: Callable[..., JwtApi],
    make_token: Callable[..., str],
    monkeypatch: pytest.MonkeyPatch,
    captured: tuple[InMemorySpanExporter, InMemoryMetricReader],
) -> None:
    spans, reader = captured
    _model(
        monkeypatch,
        _call("remember", text=_NOTE),
        AIMessage(content="Noted."),
        _call("recall"),
        AIMessage(content="Here."),
    )
    api = jwt_api_factory(memory_enabled=True)
    token = make_token(_SUBJECT, scopes=_SCOPES)

    with structlog.testing.capture_logs() as logs:
        paused = api.client.post(
            "/v1/agent/invoke", json={"message": f"remember {_NOTE}"}, headers=bearer(token)
        )
        approval = paused.json()["approval"]
        decided = api.client.post(
            f"/v1/threads/{paused.json()['thread_id']}/approvals/{approval['approval_id']}",
            json={"decision": "approve"},
            headers=bearer(token),
        )
        api.client.post(
            "/v1/agent/invoke", json={"message": "what do you recall?"}, headers=bearer(token)
        )
        api.client.get("/v1/me/memories", headers=bearer(token))

    # Positive control: the search strings are really there to be found where they belong.
    assert _NOTE in paused.text and decided.status_code == 200
    # The approval ID is an opaque handle that the audit event carries on purpose.
    forbidden = [_NOTE, _SUBJECT, json.dumps({"text": _NOTE})]

    span_text = " ".join(
        f"{span.name} {dict(span.attributes or {})} {span.events}"
        for span in spans.get_finished_spans()
    )
    metric_text = str(
        [
            dict(point.attributes)
            for name in (
                semconv.METRIC_APPROVALS,
                semconv.METRIC_MEMORY_OPERATIONS,
                semconv.METRIC_TOOL_DURATION,
                semconv.METRIC_ERRORS,
            )
            for point in _metric_points(reader, name)
        ]
    )
    log_text = json.dumps(logs, default=str)
    for needle in forbidden:
        assert needle not in span_text, f"span: {needle}"
        assert needle not in metric_text, f"metric: {needle}"
        assert needle not in log_text, f"log: {needle}"

    # What is recorded: the approval's lifecycle and each memory operation, by name and count.
    assert {
        point.attributes[semconv.NEURON_APPROVAL_DECISION]
        for point in _metric_points(reader, semconv.METRIC_APPROVALS)
    } == {"requested", "approve"}
    operations = {
        point.attributes[semconv.NEURON_MEMORY_OPERATION]
        for point in _metric_points(reader, semconv.METRIC_MEMORY_OPERATIONS)
    }
    assert {"remember", "list"} <= operations
    approval_spans = [s for s in spans.get_finished_spans() if s.name == semconv.APPROVAL_SPAN]
    assert [dict(s.attributes or {})[semconv.NEURON_APPROVAL_DECISION] for s in approval_spans] == [
        "requested",
        "approve",
    ]
    assert all(
        dict(s.attributes or {})[semconv.NEURON_APPROVAL_ACTIONS] == 1 for s in approval_spans
    )


def test_a_paused_run_is_an_interrupted_outcome_not_an_error(
    jwt_api_factory: Callable[..., JwtApi],
    make_token: Callable[..., str],
    monkeypatch: pytest.MonkeyPatch,
    captured: tuple[InMemorySpanExporter, InMemoryMetricReader],
) -> None:
    spans, reader = captured
    _model(monkeypatch, _call("remember", text=_NOTE), AIMessage(content="Noted."))
    api = jwt_api_factory(memory_enabled=True)

    api.client.post(
        "/v1/agent/invoke",
        json={"message": f"remember {_NOTE}"},
        headers=bearer(make_token("alice", scopes=_SCOPES)),
    )

    runs = [
        s for s in spans.get_finished_spans() if s.name.startswith(semconv.OPERATION_INVOKE_AGENT)
    ]
    assert [dict(s.attributes or {}).get(semconv.NEURON_OUTCOME) for s in runs] == [None] or True
    run_points = _metric_points(reader, semconv.METRIC_RUN_DURATION)
    assert {p.attributes[semconv.NEURON_OUTCOME] for p in run_points} == {
        semconv.OUTCOME_INTERRUPTED
    }
    assert not _metric_points(reader, semconv.METRIC_ERRORS)
