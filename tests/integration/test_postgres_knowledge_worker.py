"""`neuron-worker` under fault injection (RAG-02.01 AC1, AC2, AC4; ADR 0014 K4).

The worker runs as a subprocess (`knowledge_worker_child.py`) on the worker role, with a task
that sleeps and then appends to a file, so a job that completed twice would show.
"""

from __future__ import annotations

import os
import signal
import subprocess  # nosec B404
import sys
import time
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import procrastinate
import psycopg
import pytest
from pydantic import SecretStr
from test_postgres_knowledge import _settings
from test_postgres_knowledge_tables import _knowledge_db, worker  # noqa: F401
from test_postgres_roles import RoleDatabase, _rows, role_db, roles  # noqa: F401

from neuron_agent.config.settings import Settings
from neuron_agent.knowledge import jobs
from neuron_agent.knowledge import worker as neuron_worker
from neuron_agent.persistence.checkpointer import build_persistence
from neuron_agent.persistence.roles import AppRoleError
from neuron_agent.persistence.startup_checks import ROLE_NOT_APP_USER

pytestmark = [pytest.mark.integration, pytest.mark.postgres, pytest.mark.anyio]

_CHILD = Path(__file__).with_name("knowledge_worker_child.py")


class _Stack:
    def __init__(self, db: RoleDatabase, worker_dsn: str, tmp: Path) -> None:
        self.role_db, self.worker_dsn, self.done = db, worker_dsn, tmp / "done"
        self.health = tmp / "health"
        self.children: list[subprocess.Popen[bytes]] = []

    def start(self, **settings: str) -> subprocess.Popen[bytes]:
        env = {
            **os.environ,
            "APP_ENV": "test",
            "APP_CHECKPOINTER": "postgres",
            "APP_KNOWLEDGE_ENABLED": "true",
            "APP_POSTGRES_DSN": self.role_db.app_dsn,
            "APP_POSTGRES_WORKER_DSN": self.worker_dsn,
            "APP_WORKER_STALLED_SECONDS": "3",
            "APP_WORKER_HEALTH_FILE": str(self.health),
            **{f"APP_WORKER_{name.upper()}": value for name, value in settings.items()},
        }
        child = subprocess.Popen([sys.executable, str(_CHILD), str(self.done)], env=env)  # noqa: S603  # nosec B603
        self.children.append(child)
        return child

    async def defer_sleep(self, seconds: float) -> int:
        app = procrastinate.App(
            connector=procrastinate.PsycopgConnector(
                conninfo=self.worker_dsn, kwargs={"options": "-c search_path=knowledge"}
            )
        )
        async with app.open_async():
            return await app.configure_task("sleep", queue=neuron_worker.QUEUE).defer_async(
                seconds=seconds
            )

    async def status(self, job: int) -> Any:
        rows = await _rows(
            self.role_db.migrator_dsn,
            "SELECT status FROM knowledge.procrastinate_jobs WHERE id = %s",
            (job,),
        )
        return rows[0][0]

    async def wait_for(self, job: int, status: str, timeout: float) -> None:
        deadline = time.monotonic() + timeout
        while (current := await self.status(job)) != status:
            assert time.monotonic() < deadline, f"job is {current}, not {status}"
            time.sleep(0.2)

    def completions(self) -> int:
        return len(self.done.read_text().splitlines()) if self.done.exists() else 0


@pytest.fixture
async def stack(
    role_db: RoleDatabase,  # noqa: F811
    worker: tuple[str, str],  # noqa: F811
    tmp_path: Path,
) -> Iterator[_Stack]:
    worker_dsn = await _knowledge_db(role_db, worker)
    assert worker_dsn is not None
    stack = _Stack(role_db, worker_dsn, tmp_path)
    yield stack  # type: ignore[misc]
    for child in stack.children:
        if child.poll() is None:
            child.kill()
            child.wait()


async def test_a_killed_workers_job_is_retried_and_completes_once(stack: _Stack) -> None:
    first = stack.start()
    job = await stack.defer_sleep(3)
    await stack.wait_for(job, "doing", timeout=15)
    first.kill()
    first.wait()
    assert stack.completions() == 0

    second = stack.start()
    # The sweep finds the job once the dead worker's heartbeat is 3 s old, then it runs again.
    await stack.wait_for(job, "succeeded", timeout=30)
    assert stack.completions() == 1
    assert stack.health.exists()
    second.send_signal(signal.SIGTERM)
    assert second.wait(timeout=15) == 0
    assert not stack.health.exists()


async def test_sigterm_finishes_the_running_job_within_the_drain(stack: _Stack) -> None:
    child = stack.start(drain_seconds="20")
    job = await stack.defer_sleep(2)
    await stack.wait_for(job, "doing", timeout=15)
    child.send_signal(signal.SIGTERM)
    assert child.wait(timeout=20) == 0
    assert await stack.status(job) == "succeeded"
    assert stack.completions() == 1


async def test_sigterm_releases_a_job_longer_than_the_drain(stack: _Stack) -> None:
    child = stack.start(drain_seconds="1")
    job = await stack.defer_sleep(60)
    await stack.wait_for(job, "doing", timeout=15)
    child.send_signal(signal.SIGTERM)
    assert child.wait(timeout=15) == 0
    # Released for another worker to run again, not lost and not left `doing`.
    assert await stack.status(job) == "todo"
    assert stack.completions() == 0


async def test_the_api_is_ready_while_the_worker_is_down(stack: _Stack) -> None:
    await stack.defer_sleep(1)  # queued, and no worker is running
    persistence = build_persistence(_settings(stack.role_db))
    persistence.check_knowledge = True
    await persistence.open()
    try:
        assert await persistence.is_ready() is True
    finally:
        await persistence.close()


async def test_the_worker_refuses_a_privileged_or_wrong_role(stack: _Stack) -> None:
    def settings(dsn: str, env: str = "test") -> Settings:
        return Settings.model_construct(
            env=env, postgres_worker_dsn=SecretStr(dsn), postgres_worker_role="neuron_worker"
        )

    await neuron_worker.verify_worker_role(settings(stack.worker_dsn))
    # The migrator owns `knowledge` and can create in it.
    migrator = settings(stack.role_db.migrator_dsn)
    with pytest.raises(AppRoleError, match="too privileged"):
        await neuron_worker.verify_worker_role(migrator)
    # Production runs as APP_POSTGRES_WORKER_ROLE only, not the app role.
    app_in_production = settings(stack.role_db.app_dsn, "production")
    with pytest.raises(AppRoleError) as caught:
        await neuron_worker.verify_worker_role(app_in_production)
    assert caught.value.code == ROLE_NOT_APP_USER


async def _stall(stack: _Stack, attempts: int) -> int:
    """A job left `doing` by a worker that is gone (its row pruned: `worker_id` is NULL)."""
    job = await stack.defer_sleep(1)
    async with await psycopg.AsyncConnection.connect(stack.role_db.migrator_dsn) as conn:
        await conn.execute(
            "UPDATE knowledge.procrastinate_jobs SET status = 'doing', attempts = %s WHERE id = %s",
            (attempts, job),
        )
    return job


async def test_sweeps_never_overlap_and_a_job_that_keeps_stalling_fails(stack: _Stack) -> None:
    job = await _stall(stack, attempts=0)
    async with await psycopg.AsyncConnection.connect(stack.worker_dsn) as other:
        # Another worker is sweeping: this one does nothing, so it cannot use an old list.
        await other.execute("SELECT pg_advisory_xact_lock(%s)", (neuron_worker._SWEEP,))
        assert await neuron_worker.sweep(stack.worker_dsn, 3) == 0
        assert await stack.status(job) == "doing"
    assert await neuron_worker.sweep(stack.worker_dsn, 3) == 1
    assert await stack.status(job) == "todo"

    poison = await _stall(stack, attempts=neuron_worker.MAX_ATTEMPTS - 1)
    assert await neuron_worker.sweep(stack.worker_dsn, 3) == 1
    assert await stack.status(poison) == "failed"


async def test_the_document_of_a_job_that_keeps_stalling_ends_failed(stack: _Stack) -> None:
    kb, doc = uuid.uuid4(), uuid.uuid4()
    async with await psycopg.AsyncConnection.connect(stack.role_db.app_dsn) as conn:
        await conn.execute(
            "INSERT INTO knowledge.bases (kb_id, owner_key, name, profile_id)"
            " VALUES (%s, %s, 'kb', 1)",
            (kb, "c" * 64),
        )
        await conn.execute(
            "INSERT INTO knowledge.documents (doc_id, kb_id, uploaded_by, title, mime_type,"
            " size_bytes, sha256, blob_key, status)"
            " VALUES (%s, %s, %s, 't', 'text/plain', 1, %s, 'k', 'parsing')",
            (doc, kb, "c" * 64, "d" * 64),
        )
        job = await jobs.defer(conn, jobs.Task.INGEST_DOCUMENT, doc_id=doc)
    # Its worker died on every attempt: the last one is left `doing`.
    async with await psycopg.AsyncConnection.connect(stack.role_db.migrator_dsn) as conn:
        await conn.execute(
            "UPDATE knowledge.procrastinate_jobs SET status = 'doing', attempts = %s WHERE id = %s",
            (neuron_worker.MAX_ATTEMPTS - 1, job),
        )
    assert await neuron_worker.sweep(stack.worker_dsn, 3) == 1
    assert await stack.status(job) == "failed"
    rows = await _rows(
        stack.role_db.migrator_dsn,
        "SELECT status, error_code FROM knowledge.documents WHERE doc_id = %s",
        (doc,),
    )
    assert rows == [("failed", "worker_lost")]


async def _age_events(stack: _Stack, job: int, seconds: int, sql: str = "") -> None:
    """Date `job`'s events `seconds` back, then run `sql` on it (RAG-08.03 queue age)."""
    async with await psycopg.AsyncConnection.connect(stack.role_db.migrator_dsn) as conn:
        await conn.execute(
            "UPDATE knowledge.procrastinate_events SET at = now() - make_interval(secs => %s)"
            " WHERE job_id = %s",
            (seconds, job),
        )
        if sql:
            await conn.execute(sql, (job,))


async def test_queue_age_is_the_wait_of_the_oldest_runnable_job(stack: _Stack) -> None:
    assert await neuron_worker.oldest_queued_seconds(stack.worker_dsn) == 0
    waiting = await stack.defer_sleep(1)
    await _age_events(stack, waiting, 600)
    # Older, but not waiting: one runs, one is a retry backing off until later.
    await _age_events(
        stack,
        await stack.defer_sleep(1),
        3600,
        "UPDATE knowledge.procrastinate_jobs SET status = 'doing' WHERE id = %s",
    )
    await _age_events(
        stack,
        await stack.defer_sleep(1),
        3600,
        "UPDATE knowledge.procrastinate_jobs SET scheduled_at = now() + interval '1 hour'"
        " WHERE id = %s",
    )
    assert 600 <= await neuron_worker.oldest_queued_seconds(stack.worker_dsn) < 660

    # A retry waits from the time it was scheduled for, not from its first defer.
    await _age_events(
        stack,
        waiting,
        3600,
        "UPDATE knowledge.procrastinate_jobs SET scheduled_at = now() - interval '60 seconds'"
        " WHERE id = %s",
    )
    assert 60 <= await neuron_worker.oldest_queued_seconds(stack.worker_dsn) < 120
