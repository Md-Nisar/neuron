# Copyright 2026 Md Nisar Ahmed
# SPDX-License-Identifier: Apache-2.0

"""The ingestion worker process (ADR 0014 K4; RAG-02.01).

neuron-worker           run jobs until SIGTERM or SIGINT
neuron-worker health    exit 0 while the health file is fresh (the container health check)

It connects as the worker role (`APP_POSTGRES_WORKER_DSN`) with its own pool, runs the tasks
named in `jobs.Task`, and sweeps jobs left `doing` by a worker that stopped sending heartbeats
(Procrastinate 3.10.0 does not, RAG-00.02). The API does not depend on it: `/health/ready`
ignores the worker, whose health is its own container's.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import time
import uuid
from contextlib import suppress
from datetime import UTC, datetime
from pathlib import Path

import procrastinate
import psycopg
import structlog
from procrastinate.sql import queries
from psycopg.rows import dict_row

from neuron_agent.config.settings import Settings, get_settings
from neuron_agent.knowledge.jobs import QUEUE, Task
from neuron_agent.observability.logging import configure_logging
from neuron_agent.persistence.dsn_redaction import install_dsn_redaction
from neuron_agent.persistence.roles import AppRoleError, role_problems
from neuron_agent.persistence.startup_checks import ROLE_NOT_APP_USER, StartupCheckError

log = structlog.get_logger(__name__)

# A job released by a drain or a failure runs again; jobs are idempotent (ADR 0014 K4).
RETRY = procrastinate.RetryStrategy(max_attempts=5, exponential_wait=5)
# Queue functions and tables are in `knowledge` (migration 25); the role has nothing elsewhere.
_OPTIONS = "-c search_path=knowledge"
# The advisory lock key that serialises the stalled-job sweep across workers.
_SWEEP = 0x4E52_5357


async def ingest_document(doc_id: str) -> None:
    # The app role can insert any job row, so the argument is parsed, never trusted.
    parsed = uuid.UUID(doc_id)
    log.info("knowledge.job.ingest_document", doc_id=str(parsed))  # RAG-02.04 does the work


def build_app(settings: Settings) -> procrastinate.App:
    """A Procrastinate app on the worker DSN with every `Task` registered by name."""
    assert settings.postgres_worker_dsn is not None  # nosec B101 - main() checks it
    app = procrastinate.App(
        connector=procrastinate.PsycopgConnector(
            conninfo=settings.postgres_worker_dsn.get_secret_value(),
            min_size=1,
            max_size=settings.worker_concurrency + 2,
            timeout=settings.postgres_pool_timeout_seconds,
            kwargs={"options": _OPTIONS},
        )
    )
    app.task(name=Task.INGEST_DOCUMENT.value, queue=QUEUE, retry=RETRY)(ingest_document)
    return app


async def verify_worker_role(settings: Settings) -> None:
    """Connected as a role that is not privileged; in staging/production, the worker role.

    `role_problems` checks the current schema, `knowledge` here; `setup` checks that the worker
    role holds nothing in `public`.
    """
    assert settings.postgres_worker_dsn is not None  # nosec B101
    async with await psycopg.AsyncConnection.connect(
        settings.postgres_worker_dsn.get_secret_value(), row_factory=dict_row, options=_OPTIONS
    ) as conn:
        cursor = await conn.execute("SELECT current_user::text AS name")
        row = await cursor.fetchone()
        user = row["name"] if row else ""
        if settings.env in {"staging", "production"} and user != settings.postgres_worker_role:
            raise AppRoleError(
                "the database user is not APP_POSTGRES_WORKER_ROLE", ROLE_NOT_APP_USER
            )
        problems = await role_problems(conn, user)
    if problems:
        raise AppRoleError("the worker database role is too privileged: " + "; ".join(problems))


async def sweep(dsn: str, stalled_seconds: float) -> int:
    """Put jobs of workers without a recent heartbeat back in the queue; return how many.

    One transaction under an advisory lock, so sweeps never overlap: a second sweep with an old
    list could otherwise requeue a job another worker has picked up again. A job that already
    used its attempts (a parser that kills its worker each time) fails instead.
    """
    async with (
        await psycopg.AsyncConnection.connect(dsn, row_factory=dict_row, options=_OPTIONS) as conn,
        conn.transaction(),
    ):
        cursor = await conn.execute("SELECT pg_try_advisory_xact_lock(%s) AS locked", (_SWEEP,))
        if not (row := await cursor.fetchone()) or not row["locked"]:
            return 0  # another worker is sweeping
        cursor = await conn.execute(
            queries["select_stalled_jobs_by_heartbeat"],
            {"seconds_since_heartbeat": stalled_seconds, "queue": QUEUE, "task_name": None},
        )
        stalled = await cursor.fetchall()
        for job in stalled:
            if job["attempts"] + 1 >= RETRY.max_attempts:
                await conn.execute(
                    queries["finish_job"],
                    {"job_id": job["id"], "status": "failed", "delete_job": False},
                )
            else:
                await conn.execute(
                    queries["retry_job"],
                    {
                        "job_id": job["id"],
                        "retry_at": datetime.now(UTC),
                        "new_priority": None,
                        "new_queue_name": None,
                        "new_lock": None,
                    },
                )
    return len(stalled)


async def _maintain(settings: Settings) -> None:
    assert settings.postgres_worker_dsn is not None  # nosec B101
    health = Path(settings.worker_health_file)
    while True:
        try:
            retried = await sweep(
                settings.postgres_worker_dsn.get_secret_value(), settings.worker_stalled_seconds
            )
        except Exception as exc:  # noqa: BLE001 - the health file goes stale instead
            log.warning("knowledge.worker.sweep_failed", error=type(exc).__name__)
        else:
            if retried:
                log.info("knowledge.worker.stalled_jobs_retried", count=retried)
            health.touch()
        await asyncio.sleep(settings.worker_stalled_seconds / 3)


async def run(settings: Settings, app: procrastinate.App | None = None) -> None:
    """Run until SIGTERM or SIGINT, then drain for `worker_drain_seconds`."""
    assert settings.postgres_worker_dsn is not None  # nosec B101
    install_dsn_redaction(settings.postgres_worker_dsn.get_secret_value())
    # A file left by a killed run in the same container must not report this one healthy.
    Path(settings.worker_health_file).unlink(missing_ok=True)
    await verify_worker_role(settings)
    app = app or build_app(settings)
    async with app.open_async():
        maintenance = asyncio.create_task(_maintain(settings))
        try:
            await app.run_worker_async(
                queues=[QUEUE],
                concurrency=settings.worker_concurrency,
                shutdown_graceful_timeout=settings.worker_drain_seconds,
                update_heartbeat_interval=settings.worker_stalled_seconds / 3,
                stalled_worker_timeout=settings.worker_stalled_seconds,
            )
        finally:
            maintenance.cancel()
            with suppress(asyncio.CancelledError):
                await maintenance
            Path(settings.worker_health_file).unlink(missing_ok=True)
    log.info("knowledge.worker.stopped")


def healthy(settings: Settings) -> bool:
    try:
        age = time.time() - Path(settings.worker_health_file).stat().st_mtime
    except OSError:
        return False
    return age <= settings.worker_stalled_seconds


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="neuron-worker")
    parser.add_argument("command", nargs="?", choices=("run", "health"), default="run")
    command = parser.parse_args(argv).command
    settings = get_settings()
    if command == "health":
        raise SystemExit(0 if healthy(settings) else 1)
    if settings.postgres_worker_dsn is None:
        raise SystemExit("neuron-worker needs APP_POSTGRES_WORKER_DSN")
    configure_logging(
        level=settings.log_level,
        service=f"{settings.name}-worker",
        version=settings.version,
        environment=settings.env,
    )
    try:
        asyncio.run(run(settings))
    except StartupCheckError as exc:
        print(f"worker failed: {exc}", file=sys.stderr)
        raise SystemExit(1) from None
    except psycopg.Error as exc:
        # The class only: a driver message can echo the host, the user or the DSN.
        print(f"worker failed: {type(exc).__name__}", file=sys.stderr)
        raise SystemExit(1) from None
