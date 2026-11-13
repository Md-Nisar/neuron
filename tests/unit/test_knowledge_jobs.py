"""Job arguments and the worker process (RAG-02.01; the Postgres side is in tests/integration)."""

from __future__ import annotations

import asyncio
import os
import time
import uuid
from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import InMemoryMetricReader
from pydantic import SecretStr, ValidationError
from tests.unit.test_production_feature_guards import jwt_settings

from neuron_agent.config.settings import Settings, get_settings
from neuron_agent.knowledge import jobs, worker
from neuron_agent.knowledge.parsing import PDF, ParseError
from neuron_agent.knowledge.reindex import ReindexRefusedError
from neuron_agent.observability import metrics, semconv

pytestmark = pytest.mark.anyio


@pytest.mark.parametrize("value", ["a document title", 7, b"bytes", None])
async def test_defer_refuses_anything_but_ids(value: Any) -> None:
    # Checked before the connection is touched: no text, file name or identity reaches a job.
    with pytest.raises(TypeError, match="ids only"):
        await jobs.defer(object(), jobs.Task.INGEST_DOCUMENT, doc_id=value)  # type: ignore[arg-type]


class _Ingestor:
    connect = blobs = embeddings = reindex = policy = None  # the purger's, unused here

    def __init__(self, error: Exception | None = None) -> None:
        self.error, self.calls, self.failed = error, [], []  # type: ignore[var-annotated]

    async def ingest(self, doc_id: uuid.UUID, *, last_attempt: bool) -> str:
        self.calls.append((doc_id, last_attempt))
        if self.error:
            raise self.error
        return "ready"

    async def fail(self, doc_id: uuid.UUID, code: str) -> str:
        self.failed.append((doc_id, code))
        return "failed"


def _task(ingestor: _Ingestor) -> Any:
    settings = Settings(env="test", postgres_worker_dsn=SecretStr("postgresql://w@h/d"))
    app = worker.build_app(settings, ingestor)  # type: ignore[arg-type]
    return app.tasks[jobs.Task.INGEST_DOCUMENT.value].func


def _context(attempts: int) -> Any:
    return SimpleNamespace(job=SimpleNamespace(attempts=attempts))


async def test_the_ingest_task_parses_its_argument() -> None:
    # The app role can insert any job row: a non-UUID argument fails the job.
    ingestor = _Ingestor()
    await _task(ingestor)(_context(0), "../../etc/passwd")  # ends the job; a retry cannot help
    doc = uuid.uuid4()
    await _task(ingestor)(_context(0), str(doc))
    await _task(ingestor)(_context(worker.MAX_ATTEMPTS - 1), str(doc))
    assert ingestor.calls == [(doc, False), (doc, True)]


async def test_an_unexpected_error_on_the_last_attempt_fails_the_document() -> None:
    doc = uuid.uuid4()
    ingestor = _Ingestor(RuntimeError("a row of chunk text"))
    task, first, doc_id = _task(ingestor), _context(0), str(doc)
    with pytest.raises(worker.IngestError) as caught:
        await task(first, doc_id)
    # The queue logs what the job raised: the class name, never the message or its cause.
    assert (str(caught.value), caught.value.__cause__) == ("RuntimeError", None)
    assert caught.value.__suppress_context__
    assert ingestor.failed == []  # retried, so the document stays in progress
    last = _context(worker.MAX_ATTEMPTS - 1)
    with pytest.raises(worker.IngestError):
        await task(last, doc_id)
    assert ingestor.failed == [(doc, "ingest_failed")]


async def test_office_files_without_a_parser_url_fail_with_a_clear_code(tmp_path: Path) -> None:
    settings = Settings(
        env="test",
        postgres_worker_dsn=SecretStr("postgresql://w@h/d"),
        knowledge_blob_root=str(tmp_path),
    )
    ingestor = worker.build_ingestor(settings)
    office = ingestor.parsers[1]
    with pytest.raises(ParseError, match="parser_not_configured"):
        await office.parse(b"%PDF", PDF, ingestor.limits)


def test_every_task_is_registered_by_name() -> None:
    settings = Settings(env="test", postgres_worker_dsn=SecretStr("postgresql://w@h/d"))
    app = worker.build_app(settings, _Ingestor())  # type: ignore[arg-type]
    assert {task.value for task in jobs.Task} <= set(app.tasks)
    for task in jobs.Task:
        assert app.tasks[task.value].queue == jobs.QUEUE
        periodic = task in {
            jobs.Task.RECONCILE,
            jobs.Task.SWEEP_BLOBS,
            jobs.Task.REINDEX_SWAP,
            jobs.Task.PURGE_RETIRED,
        }
        assert app.tasks[task.value].retry_strategy == (None if periodic else worker.RETRY)
    # The periodic tasks are not retried: the next run replaces a failed one.
    assert {(p.task.name, p.cron) for p in app.periodic_registry.periodic_tasks.values()} == {
        (jobs.Task.RECONCILE.value, worker.RECONCILE_CRON),
        (jobs.Task.SWEEP_BLOBS.value, worker.SWEEP_BLOBS_CRON),
        (jobs.Task.REINDEX_SWAP.value, worker.REINDEX_SWAP_CRON),
        (jobs.Task.PURGE_RETIRED.value, worker.PURGE_RETIRED_CRON),
    }


async def test_a_blob_sweep_counts_deletions_and_raises_the_class_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings(env="test", postgres_worker_dsn=SecretStr("postgresql://w@h/d"))
    func = worker.build_app(settings, _Ingestor()).tasks[jobs.Task.SWEEP_BLOBS.value].func  # type: ignore[arg-type]
    calls: list[float] = []
    recorded: list[dict[str, int]] = []
    monkeypatch.setattr(worker.metrics, "record_knowledge_reconciled", recorded.append)

    async def sweep(connect: Any, blobs: Any, grace: float) -> int:
        calls.append(grace)
        if len(calls) > 1:
            raise OSError("/var/lib/neuron/knowledge-blobs/ab12")
        return 3

    monkeypatch.setattr(worker, "sweep_blobs", sweep)
    await func(timestamp=0)
    assert (calls, recorded) == ([86_400.0], [{"blob_deleted": 3}])
    with pytest.raises(worker.ReconcileError) as raised:
        await func(timestamp=0)
    assert str(raised.value) == "OSError"


async def test_a_reconcile_run_counts_its_actions_and_raises_the_class_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings(env="test", postgres_worker_dsn=SecretStr("postgresql://w@h/d"))
    func = worker.build_app(settings, _Ingestor()).tasks[jobs.Task.RECONCILE.value].func  # type: ignore[arg-type]
    calls: list[Any] = []
    recorded: list[dict[str, int]] = []
    monkeypatch.setattr(worker.metrics, "record_knowledge_reconciled", recorded.append)

    async def reconcile(connect: Any, seconds: float) -> dict[str, int]:
        calls.append(seconds)
        if len(calls) > 1:
            raise RuntimeError("detail that could echo a row")
        return {"ingest_requeued": 1, "ingest_stalled": 0, "purge_requeued": 2}

    monkeypatch.setattr(worker, "reconcile", reconcile)
    await func(timestamp=0)
    assert calls == [settings.worker_reconcile_after_seconds]
    assert recorded == [{"ingest_requeued": 1, "ingest_stalled": 0, "purge_requeued": 2}]
    with pytest.raises(worker.ReconcileError) as raised:
        await func(timestamp=0)
    assert str(raised.value) == "RuntimeError"


def test_reconciled_rows_are_counted_by_action_only(monkeypatch: pytest.MonkeyPatch) -> None:
    reader = InMemoryMetricReader()
    provider = MeterProvider(metric_readers=[reader])
    monkeypatch.setattr(metrics, "_meter", lambda: provider.get_meter("test"))
    metrics.record_knowledge_reconciled({"ingest_requeued": 2, "ingest_stalled": 0})
    data = reader.get_metrics_data()
    assert data is not None
    [counter] = [
        m
        for r in data.resource_metrics
        for s in r.scope_metrics
        for m in s.metrics
        if m.name == semconv.METRIC_KNOWLEDGE_RECONCILED
    ]
    [point] = counter.data.data_points
    assert (point.value, dict(point.attributes)) == (2, {semconv.NEURON_OUTCOME: "ingest_requeued"})


class _Purges:
    def __init__(self, error: Exception | None = None) -> None:
        self.error, self.calls = error, []  # type: ignore[var-annotated]

    async def purge(self, key: uuid.UUID) -> int:
        self.calls.append(key)
        if self.error:
            raise self.error
        return 1


async def test_a_purge_parses_its_argument_and_raises_the_class_only() -> None:
    purges = _Purges()
    await worker._purge(purges.purge, "../../etc/passwd")  # ends the job; a retry cannot help
    key = uuid.uuid4()
    await worker._purge(purges.purge, str(key))
    assert purges.calls == [key]
    with pytest.raises(worker.PurgeError) as caught:
        await worker._purge(_Purges(OSError("/blobs/ab/cd: permission denied")).purge, str(key))
    assert (str(caught.value), caught.value.__cause__) == ("OSError", None)


def test_the_health_file_must_be_fresh(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    health = tmp_path / "health"
    settings = Settings(env="test", worker_health_file=str(health), worker_stalled_seconds=30)
    # `main` reads its own settings: these, not the default file a local worker may be writing.
    monkeypatch.setattr(worker, "get_settings", lambda: settings)
    assert worker.healthy(settings) is False
    health.touch()
    assert worker.healthy(settings) is True
    os.utime(health, (time.time() - 31, time.time() - 31))
    assert worker.healthy(settings) is False
    with pytest.raises(SystemExit) as caught:
        worker.main(["health"])
    assert caught.value.code == 1


def test_the_worker_needs_its_dsn(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.delenv("APP_POSTGRES_WORKER_DSN", raising=False)
    get_settings.cache_clear()
    try:
        with pytest.raises(SystemExit, match="APP_POSTGRES_WORKER_DSN"):
            worker.main([])
    finally:
        get_settings.cache_clear()


def test_a_connection_error_prints_no_dsn(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    dsn = "postgresql://neuron_worker:s3cret@db.internal.example:1/n?connect_timeout=1"
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("APP_POSTGRES_WORKER_DSN", dsn)
    get_settings.cache_clear()
    try:
        with pytest.raises(SystemExit) as caught:
            worker.main([])
    finally:
        get_settings.cache_clear()
    assert caught.value.code == 1
    err = capsys.readouterr().err
    assert err.startswith("worker failed: ")
    for secret in ("s3cret", "db.internal", "neuron_worker"):
        assert secret not in err


def test_check_blobs_prints_only_the_error_class_and_exits_2(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    async def boom(*_: object) -> None:
        raise RuntimeError("postgresql://neuron_worker:s3cret@db.internal/n")

    settings = Settings(
        env="test",
        postgres_worker_dsn=SecretStr("postgresql://w@h/d"),
        knowledge_blob_root=str(tmp_path),
    )
    monkeypatch.setattr(worker, "get_settings", lambda: settings)
    monkeypatch.setattr(worker, "check_blobs", boom)
    with pytest.raises(SystemExit) as caught:
        worker.main(["check-blobs"])
    assert caught.value.code == 2
    assert capsys.readouterr() == ("", "check-blobs failed: RuntimeError\n")
    # A missing local root is not created: it would report every document as missing.
    gone = tmp_path / "unmounted"
    monkeypatch.setattr(
        worker,
        "get_settings",
        lambda: settings.model_copy(update={"knowledge_blob_root": str(gone)}),
    )
    with pytest.raises(SystemExit) as caught:
        worker.main(["check-blobs"])
    assert caught.value.code == 2
    assert "APP_KNOWLEDGE_BLOB_ROOT does not exist" in capsys.readouterr().err
    assert not gone.exists()


def test_the_worker_dsn_needs_tls_in_production() -> None:
    plaintext = SecretStr("postgresql://w@db/n")
    with pytest.raises(ValidationError, match="APP_POSTGRES_WORKER_DSN must set sslmode"):
        jwt_settings(env="production", postgres_worker_dsn=plaintext)


def test_an_unexpected_error_prints_only_its_class(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    async def boom(_: Settings) -> None:
        raise RuntimeError("postgresql://neuron_worker:s3cret@db.internal/n")

    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("APP_POSTGRES_WORKER_DSN", "postgresql://w@h/d")
    monkeypatch.setattr(worker, "run", boom)
    get_settings.cache_clear()
    try:
        with pytest.raises(SystemExit) as caught:
            worker.main([])
    finally:
        get_settings.cache_clear()
    assert caught.value.code == 1
    assert capsys.readouterr().err == "worker failed: RuntimeError\n"


def test_the_worker_exports_telemetry_and_flushes_it_on_exit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    flushed: list[bool] = []

    class _Telemetry:
        def shutdown(self) -> None:
            flushed.append(True)

    async def done(_: Settings) -> None:
        return None

    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("APP_POSTGRES_WORKER_DSN", "postgresql://w@h/d")
    monkeypatch.setattr(worker, "configure_telemetry", lambda settings: _Telemetry())
    monkeypatch.setattr(worker, "run", done)
    get_settings.cache_clear()
    try:
        worker.main([])
    finally:
        get_settings.cache_clear()
    assert flushed == [True]


async def test_the_worker_reports_queue_age_after_each_sample_and_nothing_on_failure(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    gauge: list[Callable[[], float | None]] = []
    reads: list[float | None] = []
    ages: list[Any] = [12.5, RuntimeError("database down")]

    async def sweep(dsn: str, seconds: float) -> int:
        return 0

    async def oldest(dsn: str) -> float:
        age = ages.pop(0)
        if isinstance(age, Exception):
            raise age
        return float(age)

    async def tick(seconds: float) -> None:
        reads.append(gauge[0]())
        if not ages:
            raise asyncio.CancelledError
        (tmp_path / "health").unlink()  # the next iteration must touch it again

    monkeypatch.setattr(worker, "sweep", sweep)
    monkeypatch.setattr(worker, "oldest_queued_seconds", oldest)
    monkeypatch.setattr(worker.metrics, "observe_knowledge_queue_age", gauge.append)
    monkeypatch.setattr(worker.asyncio, "sleep", tick)
    settings = Settings(
        env="test",
        postgres_worker_dsn=SecretStr("postgresql://w@h/d"),
        worker_health_file=str(tmp_path / "health"),
    )
    with pytest.raises(asyncio.CancelledError):
        await worker._maintain(settings)
    assert reads == [12.5, None]  # a failed sample reports nothing rather than a stale age
    assert (tmp_path / "health").exists()  # and does not make the worker unhealthy


def test_the_queue_age_gauge_is_in_seconds_without_attributes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reader = InMemoryMetricReader()
    provider = MeterProvider(metric_readers=[reader])
    monkeypatch.setattr(metrics, "_meter", lambda: provider.get_meter("test"))
    sampled: list[float | None] = [None]
    metrics.observe_knowledge_queue_age(lambda: sampled[0])
    assert reader.get_metrics_data() is None  # not sampled yet: no point
    sampled[0] = 42.0
    data = reader.get_metrics_data()
    assert data is not None
    [gauge] = [m for r in data.resource_metrics for s in r.scope_metrics for m in s.metrics]
    assert gauge.name == semconv.METRIC_KNOWLEDGE_QUEUE_AGE
    assert gauge.unit == "s"
    [point] = gauge.data.data_points
    assert point.value == 42.0
    assert not point.attributes


@pytest.mark.parametrize("attempts", range(worker.MAX_ATTEMPTS + 1))
def test_the_queue_stops_retrying_at_the_run_the_task_treats_as_its_last(attempts: int) -> None:
    # `attempts` is the number of earlier runs. The run the task records as failed must be one
    # the queue does not retry, or a `failed` document is ingested again later.
    last_attempt = attempts + 1 >= worker.MAX_ATTEMPTS
    decision = worker.RETRY.get_retry_decision(exception=RuntimeError(), job=_context(attempts).job)
    assert (decision is None) == last_attempt


class _Reindexer:
    def __init__(self, error: Exception | None = None) -> None:
        self.error, self.failed = error, []  # type: ignore[var-annotated]

    async def reindex_base(self, kb_id: uuid.UUID) -> int:
        if self.error:
            raise self.error
        return 1

    async def fail(self, code: str) -> None:
        self.failed.append(code)


def _reindex_task(reindexer: _Reindexer) -> Any:
    settings = Settings(env="test", postgres_worker_dsn=SecretStr("postgresql://w@h/d"))
    app = worker.build_app(settings, _Ingestor(), reindexer)  # type: ignore[arg-type]
    return app.tasks[jobs.Task.REINDEX_KB.value].func


async def test_a_refused_base_fails_the_reindex_without_a_retry() -> None:
    reindexer = _Reindexer(ReindexRefusedError("processing_locality_forbidden"))
    await _reindex_task(reindexer)(_context(0), str(uuid.uuid4()))
    assert reindexer.failed == ["processing_locality_forbidden"]


async def test_a_reindex_job_fails_the_reindex_on_its_last_attempt_only() -> None:
    reindexer = _Reindexer(RuntimeError("secret chunk text"))
    task = _reindex_task(reindexer)
    with pytest.raises(worker.ReindexError) as caught:
        await task(_context(0), str(uuid.uuid4()))
    assert reindexer.failed == []
    assert str(caught.value) == "RuntimeError"  # the class only, never the message
    with pytest.raises(worker.ReindexError):
        await task(_context(worker.MAX_ATTEMPTS - 1), str(uuid.uuid4()))
    assert reindexer.failed == ["reindex_failed"]
    # A malformed argument is dropped, not retried.
    await task(_context(0), "not-a-uuid")
