"""Knowledge telemetry: ids, counts and timings, and no content (RAG-08.03, #508).

A real search, upload and ingestion on Postgres, with spans, metrics and logs captured, then
searched for what must never leave: the query, the text, the title or file name and the vector.
"""

from __future__ import annotations

import dataclasses
import json
from collections.abc import Callable
from typing import Any

import pytest
import structlog.testing
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import InMemoryMetricReader
from opentelemetry.sdk.trace import ReadableSpan, TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from test_postgres_knowledge_api import _SCOPES, _create, api  # noqa: F401
from test_postgres_knowledge_ingest import _document as _queued
from test_postgres_knowledge_ingest import _Flaky, setup  # noqa: F401
from test_postgres_knowledge_search import (
    _A,
    _FAKE,
    _base,
    _Counting,
    _document,
    _migrator,
    _retriever,
)
from test_postgres_knowledge_tables import _knowledge_db, worker  # noqa: F401
from test_postgres_roles import RoleDatabase, role_db, roles  # noqa: F401
from tests.conftest import JwtApi, bearer

from neuron_agent.knowledge.ingest import Ingestor
from neuron_agent.knowledge.parsing import ParseError
from neuron_agent.knowledge.providers import EmbeddingError, EmbeddingProvider
from neuron_agent.observability import metrics, semconv, telemetry

pytestmark = [pytest.mark.integration, pytest.mark.postgres, pytest.mark.anyio]

_TEXT = "the vault code telemetry-marker-query-4410 is telemetry-marker-passage-7731"
_QUERY = "telemetry-marker-query-4410 vault code"
_TITLE = "telemetry-marker-title-5592.pdf"


@pytest.fixture
def captured(monkeypatch: pytest.MonkeyPatch) -> tuple[InMemorySpanExporter, Any]:
    exporter, reader = InMemorySpanExporter(), InMemoryMetricReader()
    tracer_provider = TracerProvider()
    tracer_provider.add_span_processor(SimpleSpanProcessor(exporter))
    meter_provider = MeterProvider(metric_readers=[reader], views=metrics.metric_views())
    monkeypatch.setattr(telemetry, "tracer", lambda: tracer_provider.get_tracer(__name__))
    monkeypatch.setattr(metrics, "_meter", lambda: meter_provider.get_meter(__name__))
    return exporter, reader


def _search_span(exporter: InMemorySpanExporter) -> ReadableSpan:
    [span] = [s for s in exporter.get_finished_spans() if s.name == semconv.KNOWLEDGE_SEARCH_SPAN]
    return span


def _points(reader: InMemoryMetricReader, name: str) -> list[Any]:
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


async def test_a_search_span_has_ids_counts_and_timings_only(
    role_db: RoleDatabase,  # noqa: F811
    captured: tuple[InMemorySpanExporter, InMemoryMetricReader],
) -> None:
    exporter, reader = captured
    await _knowledge_db(role_db)
    kb = await _base(role_db, _A)
    await _document(role_db, kb, _A, [_TEXT])

    result = await _retriever(role_db).search(_A, _TEXT, k=5)

    span = _search_span(exporter)
    assert dict(span.attributes or {}) == {
        semconv.NEURON_KNOWLEDGE_SEARCH_MODE: "hybrid",
        semconv.NEURON_OWNER_KEY_PREFIX: _A[:12],
        semconv.NEURON_KNOWLEDGE_KB_IDS: (str(kb),),
        semconv.NEURON_KNOWLEDGE_SEARCH_PATH: result.path,
        semconv.NEURON_KNOWLEDGE_RESULTS: 1,
        semconv.NEURON_KNOWLEDGE_RERANKED: False,
        semconv.NEURON_OUTCOME: "success",
    }
    assert span.end_time is not None
    assert span.start_time is not None
    assert span.end_time > span.start_time
    [duration] = _points(reader, semconv.METRIC_KNOWLEDGE_SEARCH_DURATION)
    assert duration.count == 1
    assert dict(duration.attributes) == {
        semconv.NEURON_KNOWLEDGE_SEARCH_MODE: "hybrid",
        semconv.NEURON_OUTCOME: "success",
    }
    [results] = _points(reader, semconv.METRIC_KNOWLEDGE_SEARCH_RESULTS)
    assert (results.count, results.sum) == (1, 1)


async def test_a_failed_search_is_an_error_span_with_its_code(
    role_db: RoleDatabase,  # noqa: F811
    captured: tuple[InMemorySpanExporter, InMemoryMetricReader],
) -> None:
    exporter, reader = captured
    await _knowledge_db(role_db)
    kb = await _base(role_db, _A)
    await _document(role_db, kb, _A, [_TEXT])

    retriever = _retriever(role_db)
    failing = _Counting(fail=True)
    retriever._embeddings = EmbeddingProvider(
        failing, failing, dimensions=1024, locality="self_hosted", batch_size=8, max_retries=0
    )
    with pytest.raises(EmbeddingError):
        await retriever.search(_A, _QUERY, k=5, mode="dense")

    span = _search_span(exporter)
    assert (span.attributes or {})[semconv.ERROR_TYPE] == "embedding_error"
    assert span.status.status_code.name == "ERROR"
    [duration] = _points(reader, semconv.METRIC_KNOWLEDGE_SEARCH_DURATION)
    assert duration.attributes[semconv.NEURON_OUTCOME] == "error"
    assert _points(reader, semconv.METRIC_KNOWLEDGE_SEARCH_RESULTS) == []


async def test_a_search_leaks_no_query_passage_title_or_vector(
    role_db: RoleDatabase,  # noqa: F811
    captured: tuple[InMemorySpanExporter, InMemoryMetricReader],
) -> None:
    exporter, reader = captured
    await _knowledge_db(role_db)
    kb = await _base(role_db, _A)
    await _document(role_db, kb, _A, [_TEXT])
    await _migrator(role_db, "UPDATE knowledge.documents SET title = %s", _TITLE)
    vector = _FAKE.embed_query(_QUERY)

    with structlog.testing.capture_logs() as logs:
        found = await _retriever(role_db).search(_A, _QUERY, k=5)

    # Positive control: what is searched for is in the result the caller gets.
    assert [p.text for p in found.passages] == [_TEXT]
    assert [p.title for p in found.passages] == [_TITLE]
    spans = [
        {"name": s.name, "attributes": dict(s.attributes or {})}
        for s in exporter.get_finished_spans()
    ]
    data = reader.get_metrics_data()
    assert data is not None
    telemetry_text = json.dumps([spans, logs], default=str) + data.to_json()
    for secret in (_QUERY, "telemetry-marker-query", "telemetry-marker-passage", _TITLE):
        assert secret not in telemetry_text, secret
    assert repr(float(vector[0])) not in telemetry_text


async def test_an_unknown_mode_is_refused_before_it_labels_a_metric(
    role_db: RoleDatabase,  # noqa: F811
    captured: tuple[InMemorySpanExporter, InMemoryMetricReader],
) -> None:
    exporter, reader = captured
    retriever = _retriever(role_db)
    with pytest.raises(ValueError, match="search mode"):
        await retriever.search(_A, _QUERY, k=5, mode="anything")  # type: ignore[arg-type]
    assert exporter.get_finished_spans() == ()
    assert reader.get_metrics_data() is None  # nothing recorded


def _telemetry_text(exporter: InMemorySpanExporter, reader: InMemoryMetricReader, logs: Any) -> str:
    spans = [{"name": s.name, **dict(s.attributes or {})} for s in exporter.get_finished_spans()]
    data = reader.get_metrics_data()
    return json.dumps([spans, logs], default=str) + (data.to_json() if data else "")


async def test_an_upload_span_has_ids_and_size_but_no_file_name_or_content(
    api: tuple[JwtApi, RoleDatabase],  # noqa: F811
    make_token: Callable[..., str],
    captured: tuple[InMemorySpanExporter, InMemoryMetricReader],
) -> None:
    exporter, reader = captured
    client, _ = api
    alice = make_token("alice", scopes=_SCOPES)
    base = _create(client, alice)
    content = b"telemetry-marker-upload-content 9014"

    with structlog.testing.capture_logs() as logs:
        response = client.client.post(
            f"/v1/knowledge/bases/{base['kb_id']}/documents",
            files={"file": (_TITLE, content, "text/plain")},
            headers=bearer(alice),
        )

    assert response.status_code == 202, response.text
    [span] = [s for s in exporter.get_finished_spans() if s.name == semconv.KNOWLEDGE_UPLOAD_SPAN]
    assert dict(span.attributes or {}) == {
        semconv.NEURON_KNOWLEDGE_KB_ID: base["kb_id"],
        semconv.NEURON_KNOWLEDGE_BYTES: len(content),
        semconv.NEURON_KNOWLEDGE_DOC_ID: response.json()["doc_id"],
        semconv.NEURON_OUTCOME: "queued",
    }
    text = _telemetry_text(exporter, reader, logs)
    for secret in ("telemetry-marker-upload-content", "telemetry-marker-title"):
        assert secret not in text, secret


async def test_an_ingestion_has_a_span_per_stage_and_leaks_no_text(
    setup: tuple[RoleDatabase, Ingestor],  # noqa: F811
    captured: tuple[InMemorySpanExporter, InMemoryMetricReader],
) -> None:
    exporter, reader = captured
    db, ingestor = setup
    doc = await _queued(db, ingestor, text=_TEXT)

    with structlog.testing.capture_logs() as logs:
        assert await ingestor.ingest(doc) == "ready"

    spans = {s.name: s for s in exporter.get_finished_spans()}
    stages = ("policy", "fetch", "parse", "embed", "write")
    assert set(spans) == {semconv.KNOWLEDGE_INGEST_SPAN} | {
        f"{semconv.KNOWLEDGE_INGEST_SPAN}.{stage}" for stage in stages
    }
    attributes = dict(spans[semconv.KNOWLEDGE_INGEST_SPAN].attributes or {})
    assert attributes[semconv.NEURON_KNOWLEDGE_DOC_ID] == str(doc)
    assert attributes[semconv.NEURON_KNOWLEDGE_CHUNKS] == 1
    assert attributes[semconv.NEURON_OUTCOME] == "ready"
    [duration] = _points(reader, semconv.METRIC_KNOWLEDGE_INGEST_DURATION)
    assert dict(duration.attributes) == {semconv.NEURON_OUTCOME: "ready"}
    text = _telemetry_text(exporter, reader, logs)
    assert "telemetry-marker-passage" not in text


async def test_a_failed_stage_counts_its_code_and_the_attempt_is_a_retry(
    setup: tuple[RoleDatabase, Ingestor],  # noqa: F811
    captured: tuple[InMemorySpanExporter, InMemoryMetricReader],
) -> None:
    exporter, reader = captured
    db, ingestor = setup
    doc = await _queued(db, ingestor, text=_TEXT)
    flaky = dataclasses.replace(ingestor, parsers=(_Flaky(),))

    with pytest.raises(ParseError):
        await flaky.ingest(doc, last_attempt=False)

    spans = {s.name: s for s in exporter.get_finished_spans()}
    parse = spans[f"{semconv.KNOWLEDGE_INGEST_SPAN}.parse"]
    assert (parse.attributes or {})[semconv.ERROR_TYPE] == "parser_unavailable"
    [errors] = _points(reader, semconv.METRIC_KNOWLEDGE_STAGE_ERRORS)
    assert (errors.value, dict(errors.attributes)) == (
        1,
        {semconv.NEURON_KNOWLEDGE_STAGE: "parse", semconv.ERROR_TYPE: "parser_unavailable"},
    )
    [duration] = _points(reader, semconv.METRIC_KNOWLEDGE_INGEST_DURATION)
    assert dict(duration.attributes) == {semconv.NEURON_OUTCOME: "retry"}


async def test_an_unknown_errors_code_never_reaches_a_span(
    setup: tuple[RoleDatabase, Ingestor],  # noqa: F811
    captured: tuple[InMemorySpanExporter, InMemoryMetricReader],
) -> None:
    exporter, reader = captured
    db, ingestor = setup
    doc = await _queued(db, ingestor, text=_TEXT)

    class _ProviderError(Exception):
        code = "telemetry-marker-remote-code"

    class _Broken:
        locality = "self_hosted"

        async def embed_documents(self, texts: list[str]) -> list[list[float]]:
            raise _ProviderError

    broken = dataclasses.replace(ingestor, embeddings=_Broken())  # type: ignore[arg-type]
    with pytest.raises(_ProviderError):
        await broken.ingest(doc)

    spans = {s.name: s for s in exporter.get_finished_spans()}
    for name in (semconv.KNOWLEDGE_INGEST_SPAN, f"{semconv.KNOWLEDGE_INGEST_SPAN}.embed"):
        assert (spans[name].attributes or {})[semconv.ERROR_TYPE] == "ingest_failed", name
    assert "telemetry-marker-remote-code" not in _telemetry_text(exporter, reader, [])
