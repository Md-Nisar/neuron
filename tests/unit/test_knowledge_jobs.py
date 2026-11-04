"""Job arguments and the worker process (RAG-02.01; the Postgres side is in tests/integration)."""

from __future__ import annotations

import os
import time
import uuid
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from pydantic import SecretStr, ValidationError
from tests.unit.test_production_feature_guards import jwt_settings

from neuron_agent.config.settings import Settings, get_settings
from neuron_agent.knowledge import jobs, worker
from neuron_agent.knowledge.parsing import PDF, ParseError

pytestmark = pytest.mark.anyio


@pytest.mark.parametrize("value", ["a document title", 7, b"bytes", None])
async def test_defer_refuses_anything_but_ids(value: Any) -> None:
    # Checked before the connection is touched: no text, file name or identity reaches a job.
    with pytest.raises(TypeError, match="ids only"):
        await jobs.defer(object(), jobs.Task.INGEST_DOCUMENT, doc_id=value)  # type: ignore[arg-type]


class _Ingestor:
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
    with pytest.raises(worker.IngestError) as caught:
        await _task(ingestor)(_context(0), str(doc))
    # The queue logs what the job raised: the class name, never the message or its cause.
    assert (str(caught.value), caught.value.__cause__) == ("RuntimeError", None)
    assert caught.value.__suppress_context__
    assert ingestor.failed == []  # retried, so the document stays in progress
    with pytest.raises(worker.IngestError):
        await _task(ingestor)(_context(worker.MAX_ATTEMPTS - 1), str(doc))
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
    assert app.tasks[jobs.Task.INGEST_DOCUMENT.value].queue == jobs.QUEUE


def test_the_health_file_must_be_fresh(tmp_path: Path) -> None:
    health = tmp_path / "health"
    settings = Settings(env="test", worker_health_file=str(health), worker_stalled_seconds=30)
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
