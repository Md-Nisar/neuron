"""Answer ratings: owner-scoped, once per run, fixed reasons only, and nothing else leaks
(#285, ADR 0010 decision 6)."""

from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import Callable, Iterator
from datetime import timedelta
from typing import Any

import pytest
import structlog.testing
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import InMemoryMetricReader
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from tests.conftest import HistoryEchoAgent, JwtApi, bearer

from neuron_agent.observability import metrics, semconv, telemetry
from neuron_agent.persistence.retention import prune_threads

_NOT_FOUND = {"detail": "thread_not_found"}


@pytest.fixture
def api(jwt_api_factory: Callable[..., JwtApi], echo_agent: HistoryEchoAgent) -> JwtApi:
    return jwt_api_factory()


def _ask(api: JwtApi, token: str, message: str = "hello") -> dict[str, Any]:
    response = api.client.post("/v1/agent/invoke", json={"message": message}, headers=bearer(token))
    assert response.status_code == 200, response.text
    result: dict[str, Any] = response.json()
    return result


def _rate(api: JwtApi, token: str, thread_id: str, run_id: str | None = None, **body: Any) -> Any:
    return api.client.post(
        f"/v1/threads/{thread_id}/runs/{run_id or uuid.uuid4()}/feedback",
        json=body or {"score": 1},
        headers=bearer(token),
    )


def _owners_of(api: JwtApi, thread_id: str) -> set[Any]:
    return {owner for (owner, _), row in _rows(api).items() if row[0] == thread_id}


def _rows(api: JwtApi) -> dict[Any, Any]:
    return dict(api.service._persistence.feedback._rows)  # type: ignore[attr-defined]


def test_the_owner_rates_an_answer_and_the_first_rating_of_a_run_stands(
    api: JwtApi, make_token: Callable[..., str]
) -> None:
    alice = make_token("alice")
    thread = _ask(api, alice)["thread_id"]
    run = str(uuid.uuid4())

    with structlog.testing.capture_logs() as logs:
        first = _rate(api, alice, thread, run, score=-1, reason="inaccurate")
        second = _rate(api, alice, thread, run, score=1, reason="helpful")
        third = _rate(api, alice, thread, run, score=-1, reason="inaccurate")

    expected = {"run_id": run, "score": -1, "reason": "inaccurate"}
    assert [r.status_code for r in (first, second, third)] == [200, 200, 200]
    assert first.json() == second.json() == third.json() == expected
    assert len(_rows(api)) == 1
    [event] = [log for log in logs if log["event"] == "user_feedback"]
    assert (event["score"], event["reason"]) == ("down", "inaccurate")
    [audit] = [log for log in logs if log["event"] == "feedback_recorded"]
    assert (audit["action"], audit["resource_id"]) == ("feedback:write", run)


def test_a_rating_without_a_reason_is_accepted(api: JwtApi, make_token: Callable[..., str]) -> None:
    alice = make_token("alice")
    thread = _ask(api, alice)["thread_id"]

    response = _rate(api, alice, thread, score=1)

    assert response.status_code == 200
    assert response.json()["reason"] is None


@pytest.mark.parametrize(
    "body",
    [
        {"score": 1, "comment": "free text"},
        {"score": 1, "reason": "free text"},
        {"score": 1, "reason": "unsafe"},  # a negative reason on a positive score
        {"score": -1, "reason": "helpful"},  # and the other way round
        {"score": 0},
        {"score": 2},
        {"score": "1"},
        {"score": True},
        {"reason": "helpful"},
        {},
    ],
)
def test_only_a_score_and_a_fixed_reason_are_accepted(
    api: JwtApi, make_token: Callable[..., str], body: dict[str, Any]
) -> None:
    alice = make_token("alice")
    thread = _ask(api, alice)["thread_id"]

    response = api.client.post(
        f"/v1/threads/{thread}/runs/{uuid.uuid4()}/feedback", json=body, headers=bearer(alice)
    )

    assert response.status_code == 422
    assert _rows(api) == {}


def test_a_run_id_that_is_not_a_uuid_is_refused(
    api: JwtApi, make_token: Callable[..., str]
) -> None:
    alice = make_token("alice")
    thread = _ask(api, alice)["thread_id"]

    response = api.client.post(
        f"/v1/threads/{thread}/runs/not-a-uuid/feedback", json={"score": 1}, headers=bearer(alice)
    )

    assert response.status_code == 422


def test_another_users_or_an_unknown_thread_is_the_same_404_and_records_nothing(
    api: JwtApi, make_token: Callable[..., str]
) -> None:
    alice, mallory = make_token("alice"), make_token("mallory")
    thread = _ask(api, alice)["thread_id"]

    stolen = _rate(api, mallory, thread)
    unknown = _rate(api, mallory, str(uuid.uuid4()))

    assert (stolen.status_code, stolen.json()) == (404, _NOT_FOUND)
    assert (unknown.status_code, unknown.json()) == (404, _NOT_FOUND)
    assert _rows(api) == {}


def test_a_run_already_rated_on_another_thread_cannot_be_reused(
    api: JwtApi, make_token: Callable[..., str]
) -> None:
    alice = make_token("alice")
    first, second = _ask(api, alice)["thread_id"], _ask(api, alice)["thread_id"]
    run = str(uuid.uuid4())
    assert _rate(api, alice, first, run, score=1).status_code == 200

    moved = _rate(api, alice, second, run, score=-1)

    assert (moved.status_code, moved.json()) == (404, _NOT_FOUND)
    assert [row[1] for row in _rows(api).values()] == [1]


def test_two_users_may_each_rate_a_run_id(api: JwtApi, make_token: Callable[..., str]) -> None:
    alice, bob = make_token("alice"), make_token("bob")
    mine, theirs = _ask(api, alice)["thread_id"], _ask(api, bob)["thread_id"]
    run = str(uuid.uuid4())

    assert _rate(api, alice, mine, run, score=1).json()["score"] == 1
    assert _rate(api, bob, theirs, run, score=-1).json()["score"] == -1


def test_rating_needs_the_feedback_scope(api: JwtApi, make_token: Callable[..., str]) -> None:
    thread = _ask(api, make_token("alice"))["thread_id"]
    without = make_token("alice", scopes="agent:invoke threads:read")

    response = _rate(api, without, thread)

    assert response.status_code == 403
    assert _rows(api) == {}


def test_deleting_a_thread_removes_its_ratings(api: JwtApi, make_token: Callable[..., str]) -> None:
    alice = make_token("alice")
    gone, kept = _ask(api, alice)["thread_id"], _ask(api, alice)["thread_id"]
    _rate(api, alice, gone)
    _rate(api, alice, kept)

    assert api.client.delete(f"/v1/threads/{gone}", headers=bearer(alice)).status_code == 204

    assert [row[0] for row in _rows(api).values()] == [kept]


def test_erasing_a_users_data_removes_their_ratings_and_only_theirs(
    api: JwtApi, make_token: Callable[..., str]
) -> None:
    alice, bob = make_token("alice"), make_token("bob")
    _rate(api, alice, _ask(api, alice)["thread_id"])
    theirs = _ask(api, bob)["thread_id"]
    _rate(api, bob, theirs)
    # A rating whose thread is already gone (a crash between the two deletes) goes as well.
    (alices_key,) = {owner for owner, _ in _rows(api) if owner not in _owners_of(api, theirs)}
    asyncio.run(
        api.service._persistence.feedback.record(alices_key, "orphan", str(uuid.uuid4()), 1, None)
    )

    assert api.client.delete("/v1/me/threads", headers=bearer(alice)).json()["complete"]

    assert [row[0] for row in _rows(api).values()] == [theirs]


def test_retention_removes_the_ratings_of_the_threads_it_prunes(
    api: JwtApi, make_token: Callable[..., str]
) -> None:
    alice = make_token("alice")
    _rate(api, alice, _ask(api, alice)["thread_id"])

    asyncio.run(prune_threads(api.service._persistence, older_than=timedelta(0)))

    assert _rows(api) == {}


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


def test_a_rating_is_counted_once_by_score_and_reason_and_leaks_nothing(
    api: JwtApi,
    make_token: Callable[..., str],
    captured: tuple[InMemorySpanExporter, InMemoryMetricReader],
) -> None:
    spans, reader = captured
    marker = "private-topic-zebra-4412"
    alice = make_token("raw-subject-feedback-77")
    thread = _ask(api, alice, f"discuss {marker}")["thread_id"]
    run = str(uuid.uuid4())

    with structlog.testing.capture_logs() as logs:
        _rate(api, alice, thread, run, score=-1, reason="unsafe")
        _rate(api, alice, thread, run, score=-1, reason="unsafe")  # a repeat counts nothing

    data = reader.get_metrics_data()
    assert data is not None
    points = [
        point
        for resource in data.resource_metrics
        for scope in resource.scope_metrics
        for metric in scope.metrics
        if metric.name == semconv.METRIC_FEEDBACK
        for point in metric.data.data_points
    ]
    assert [(dict(p.attributes), p.value) for p in points] == [
        ({semconv.NEURON_FEEDBACK_SCORE: "down", semconv.NEURON_FEEDBACK_REASON: "unsafe"}, 1)
    ]
    [span] = [s for s in spans.get_finished_spans() if s.name == semconv.FEEDBACK_SPAN]
    assert dict(span.attributes or {}) == {
        semconv.NEURON_FEEDBACK_SCORE: "down",
        semconv.NEURON_FEEDBACK_REASON: "unsafe",
    }
    everything = json.dumps(logs, default=str) + str(points) + str(span.attributes)
    for secret in (marker, "raw-subject-feedback-77", run, thread):
        assert secret not in str(points) + str(span.attributes), secret
    assert marker not in everything and "raw-subject-feedback-77" not in everything
