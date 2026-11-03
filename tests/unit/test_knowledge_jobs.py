"""Job arguments and the worker process (RAG-02.01; the Postgres side is in tests/integration)."""

from __future__ import annotations

import os
import time
import uuid
from pathlib import Path
from typing import Any

import pytest
from pydantic import SecretStr, ValidationError
from tests.unit.test_production_feature_guards import jwt_settings

from neuron_agent.config.settings import Settings, get_settings
from neuron_agent.knowledge import jobs, worker

pytestmark = pytest.mark.anyio


@pytest.mark.parametrize("value", ["a document title", 7, b"bytes", None])
async def test_defer_refuses_anything_but_ids(value: Any) -> None:
    # Checked before the connection is touched: no text, file name or identity reaches a job.
    with pytest.raises(TypeError, match="ids only"):
        await jobs.defer(object(), jobs.Task.INGEST_DOCUMENT, doc_id=value)  # type: ignore[arg-type]


async def test_the_ingest_task_parses_its_argument() -> None:
    # The app role can insert any job row: a non-UUID argument fails the job.
    with pytest.raises(ValueError):
        await worker.ingest_document("../../etc/passwd")
    await worker.ingest_document(str(uuid.uuid4()))


def test_every_task_is_registered_by_name() -> None:
    settings = Settings(env="test", postgres_worker_dsn=SecretStr("postgresql://w@h/d"))
    app = worker.build_app(settings)
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
