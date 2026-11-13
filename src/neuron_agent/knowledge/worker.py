# Copyright 2026 Md Nisar Ahmed
# SPDX-License-Identifier: Apache-2.0

"""The ingestion worker process (ADR 0014 K4; RAG-02.01).

neuron-worker           run jobs until SIGTERM or SIGINT
neuron-worker health    exit 0 while the health file is fresh (the container health check)
neuron-worker check-blobs
                        after a restore, report orphan files and live documents whose file is
                        missing as JSON; exit 1 if any file is missing. Deletes nothing.

It connects as the worker role (`APP_POSTGRES_WORKER_DSN`) with its own pool, runs the tasks
named in `jobs.Task`, and sweeps jobs left `doing` by a worker that stopped sending heartbeats
(Procrastinate 3.10.0 does not, RAG-00.02). The API does not depend on it: `/health/ready`
ignores the worker, whose health is its own container's.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
import uuid
from collections.abc import Awaitable, Callable
from contextlib import suppress
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import procrastinate
import psycopg
import structlog
from procrastinate.sql import queries
from psycopg.rows import dict_row

from neuron_agent.config.settings import Settings, get_settings
from neuron_agent.knowledge.blobs import build_blob_store
from neuron_agent.knowledge.docling_serve import DoclingServeParser
from neuron_agent.knowledge.ingest import Ingestor, connector
from neuron_agent.knowledge.jobs import QUEUE, Task
from neuron_agent.knowledge.parsing import (
    DocumentParser,
    HtmlParser,
    Limits,
    ParsedDocument,
    ParseError,
    PlainTextParser,
)
from neuron_agent.knowledge.providers import (
    EmbeddingError,
    create_embedding_provider,
    create_reindex_embedding_provider,
)
from neuron_agent.knowledge.purge import Purger
from neuron_agent.knowledge.reconcile import check_blobs, reconcile, sweep_blobs
from neuron_agent.knowledge.reindex import Reindexer, ReindexRefusedError
from neuron_agent.observability import metrics
from neuron_agent.observability.logging import configure_logging
from neuron_agent.observability.telemetry import configure_telemetry
from neuron_agent.persistence.dsn_redaction import install_dsn_redaction
from neuron_agent.persistence.roles import AppRoleError, role_problems
from neuron_agent.persistence.startup_checks import ROLE_NOT_APP_USER, StartupCheckError

log = structlog.get_logger(__name__)

# A job released by a drain or a failure runs again; jobs are idempotent (ADR 0014 K4).
MAX_ATTEMPTS = 5
# Procrastinate retries while `job.attempts < max_attempts`, and `attempts` is 0 on the first
# run, so `max_attempts` is the number of retries: one less than the runs a job gets.
RETRY = procrastinate.RetryStrategy(max_attempts=MAX_ATTEMPTS - 1, exponential_wait=5)
# Queue functions and tables are in `knowledge` (migration 25); the role has nothing elsewhere.
_OPTIONS = "-c search_path=knowledge"
# The reconcile task's schedule: every ten minutes, queued once across all workers.
RECONCILE_CRON = "*/10 * * * *"
# The orphan-blob sweep lists the whole store, so it runs hourly.
SWEEP_BLOBS_CRON = "23 * * * *"
# The re-index swap check (RAG-09.04), between the reconcile runs.
REINDEX_SWAP_CRON = "5-59/10 * * * *"
# Retired profiles' vectors, deleted in batches (RAG-09.04): hourly is soon enough.
PURGE_RETIRED_CRON = "41 * * * *"
# The advisory lock key that serialises the stalled-job sweep across workers.
_SWEEP = 0x4E52_5357
# How long the oldest runnable job has waited: since its defer or retry, or since the time it was
# scheduled for if that is later. A job scheduled for later (a retry's back-off) does not count.
_OLDEST_QUEUED = """
SELECT COALESCE(EXTRACT(EPOCH FROM now() - min(GREATEST(j.scheduled_at, e.at))), 0)::float8
    AS age
FROM procrastinate_jobs j
CROSS JOIN LATERAL (
    SELECT max(at) AS at FROM procrastinate_events
    WHERE job_id = j.id AND type IN ('deferred', 'deferred_for_retry', 'retried')
) e
WHERE j.queue_name = %s AND j.status = 'todo'
    AND (j.scheduled_at IS NULL OR j.scheduled_at <= now())
"""


class IngestError(Exception):
    """What a failed ingest job raises to the queue: the original error's class name only."""


class PurgeError(Exception):
    """What a failed purge job raises to the queue, to be retried: the class name only."""


class ReconcileError(Exception):
    """What a failed reconcile run raises to the queue: the class name only."""


class ReindexError(Exception):
    """What a failed re-index job raises to the queue, to be retried: the class name only."""


class _Unconfigured:
    """PDF and Office files without `APP_KNOWLEDGE_PARSER_URL`: a clear code, not a crash."""

    media_types = DoclingServeParser.media_types

    async def parse(self, data: bytes, media_type: str, limits: Limits) -> ParsedDocument:
        raise ParseError("parser_not_configured")


def build_ingestor(settings: Settings) -> Ingestor:
    assert settings.postgres_worker_dsn is not None  # nosec B101 - main() checks it
    office: DocumentParser = (
        DoclingServeParser.from_settings(settings)
        if settings.knowledge_parser_url is not None
        else _Unconfigured()
    )
    return Ingestor(
        connect=connector(settings.postgres_worker_dsn.get_secret_value(), _OPTIONS),
        blobs=build_blob_store(settings),
        parsers=(PlainTextParser(), HtmlParser(), office),
        embeddings=create_embedding_provider(settings),
        limits=Limits.from_settings(settings),
        chunk_max_tokens=settings.knowledge_chunk_max_tokens,
        policy=settings.knowledge_processing_policy,
        reindex=create_reindex_embedding_provider(settings),
    )


def build_app(
    settings: Settings, ingestor: Ingestor | None = None, reindexer: Reindexer | None = None
) -> procrastinate.App:
    """A Procrastinate app on the worker DSN with every `Task` registered by name."""
    assert settings.postgres_worker_dsn is not None  # nosec B101 - main() checks it
    ingestor = ingestor or build_ingestor(settings)

    async def ingest_document(context: procrastinate.JobContext, doc_id: str) -> None:
        # The app role can insert any job row, so the argument is parsed, never trusted, and
        # the knowledge base and file come from the document's row.
        try:
            parsed = uuid.UUID(doc_id)
        except ValueError:
            log.warning("knowledge.job.invalid_argument")  # retrying cannot fix it
            return
        last_attempt = context.job.attempts + 1 >= MAX_ATTEMPTS
        try:
            await ingestor.ingest(parsed, last_attempt=last_attempt)
        except Exception as exc:
            if last_attempt:  # an unexpected error: the document must not stay `parsing`
                await ingestor.fail(parsed, "ingest_failed")
            # Procrastinate logs a failed job's exception, and a database error's detail can
            # echo a row of chunk text: only the class goes on.
            log.warning("knowledge.job.failed", doc_id=str(parsed), error=type(exc).__name__)
            raise IngestError(type(exc).__name__) from None

    purger = Purger(connect=ingestor.connect, blobs=ingestor.blobs)

    async def purge_document(doc_id: str) -> None:
        await _purge(purger.purge_document, doc_id)

    async def purge_knowledge_base(kb_id: str) -> None:
        await _purge(purger.purge_base, kb_id)

    app = procrastinate.App(
        connector=procrastinate.PsycopgConnector(
            conninfo=settings.postgres_worker_dsn.get_secret_value(),
            min_size=1,
            max_size=settings.worker_concurrency + 2,
            timeout=settings.postgres_pool_timeout_seconds,
            kwargs={"options": _OPTIONS},
        )
    )
    app.task(name=Task.INGEST_DOCUMENT.value, queue=QUEUE, retry=RETRY, pass_context=True)(
        ingest_document
    )
    for task, func in (
        (Task.PURGE_DOCUMENT, purge_document),
        (Task.PURGE_KNOWLEDGE_BASE, purge_knowledge_base),
    ):
        app.task(name=task.value, queue=QUEUE, retry=RETRY)(func)

    reindexer = reindexer or Reindexer(
        connect=ingestor.connect,
        embeddings=ingestor.embeddings,
        reindex=ingestor.reindex,
        policy=ingestor.policy,
    )

    async def reindex_kb(context: procrastinate.JobContext, kb_id: str) -> None:
        try:
            parsed = uuid.UUID(kb_id)
        except ValueError:
            log.warning("knowledge.job.invalid_argument")
            return
        try:
            done = await reindexer.reindex_base(parsed)
        except ReindexRefusedError as exc:
            await reindexer.fail(exc.code)  # retrying cannot fix it
            return
        except Exception as exc:
            if context.job.attempts + 1 >= MAX_ATTEMPTS:
                code = exc.code if isinstance(exc, EmbeddingError) else "reindex_failed"
                await reindexer.fail(code)
            log.warning("knowledge.reindex.job_failed", kb_id=kb_id, error=type(exc).__name__)
            raise ReindexError(type(exc).__name__) from None
        log.info("knowledge.reindex.base_done", kb_id=kb_id, documents=done)

    app.task(name=Task.REINDEX_KB.value, queue=QUEUE, retry=RETRY, pass_context=True)(reindex_kb)

    async def reindex_swap(timestamp: int) -> None:
        try:
            await reindexer.swap()
        except Exception as exc:
            log.warning("knowledge.reindex.swap_failed", error=type(exc).__name__)
            raise ReconcileError(type(exc).__name__) from None

    async def purge_retired_embeddings(timestamp: int) -> None:
        try:
            deleted = await reindexer.purge_retired()
        except Exception as exc:
            log.warning("knowledge.reindex.purge_failed", error=type(exc).__name__)
            raise ReconcileError(type(exc).__name__) from None
        if deleted:
            log.info("knowledge.reindex.purged", embeddings=deleted)

    async def reconcile_knowledge(timestamp: int) -> None:
        # Not retried: the next run, ten minutes later, starts over.
        try:
            counts = await reconcile(ingestor.connect, settings.worker_reconcile_after_seconds)
        except Exception as exc:
            log.warning("knowledge.reconcile.failed", error=type(exc).__name__)
            raise ReconcileError(type(exc).__name__) from None
        metrics.record_knowledge_reconciled(counts)
        if any(counts.values()):
            log.info("knowledge.reconcile.done", **counts)

    async def sweep_knowledge_blobs(timestamp: int) -> None:
        try:
            deleted = await sweep_blobs(
                ingestor.connect, ingestor.blobs, settings.worker_orphan_blob_grace_seconds
            )
        except Exception as exc:
            log.warning("knowledge.blob_sweep.failed", error=type(exc).__name__)
            raise ReconcileError(type(exc).__name__) from None
        metrics.record_knowledge_reconciled({"blob_deleted": deleted})
        if deleted:
            log.info("knowledge.blob_sweep.done", deleted=deleted)

    for name, cron, periodic in (
        (Task.RECONCILE, RECONCILE_CRON, reconcile_knowledge),
        (Task.SWEEP_BLOBS, SWEEP_BLOBS_CRON, sweep_knowledge_blobs),
        (Task.REINDEX_SWAP, REINDEX_SWAP_CRON, reindex_swap),
        (Task.PURGE_RETIRED, PURGE_RETIRED_CRON, purge_retired_embeddings),
    ):
        app.periodic(cron=cron)(app.task(name=name.value, queue=QUEUE)(periodic))
    return app


async def _purge(purge: Callable[[uuid.UUID], Awaitable[int]], value: str) -> None:
    """Run a purge on the id a job carries; a failure is raised for the queue to retry."""
    try:
        parsed = uuid.UUID(value)
    except ValueError:
        log.warning("knowledge.job.invalid_argument")  # retrying cannot fix it
        return
    try:
        removed = await purge(parsed)
    except Exception as exc:
        log.warning("knowledge.purge.failed", id=str(parsed), error=type(exc).__name__)
        raise PurgeError(type(exc).__name__) from None
    log.info("knowledge.purge.done", id=str(parsed), documents=removed)


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
            if job["attempts"] + 1 >= MAX_ATTEMPTS:
                await conn.execute(
                    queries["finish_job"],
                    {"job_id": job["id"], "status": "failed", "delete_job": False},
                )
                if job["task_name"] == Task.INGEST_DOCUMENT.value:
                    await _worker_lost(conn, job["args"])
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


async def oldest_queued_seconds(dsn: str) -> float:
    """Seconds the oldest runnable job of the queue has waited; 0 when none waits (RAG-08.03)."""
    async with await psycopg.AsyncConnection.connect(
        dsn, row_factory=dict_row, options=_OPTIONS
    ) as conn:
        cursor = await conn.execute(_OLDEST_QUEUED, (QUEUE,))
        row = await cursor.fetchone()
    return float(row["age"]) if row else 0.0


async def _worker_lost(conn: psycopg.AsyncConnection[Any], args: object) -> None:
    """The document of a job that killed its worker five times ends `failed`, not `parsing`."""
    try:
        doc_id = uuid.UUID(str(args["doc_id"]))  # type: ignore[index]
    except (KeyError, TypeError, ValueError):
        return  # not a job the API queued
    await conn.execute(
        "UPDATE documents SET status = 'failed', error_code = 'worker_lost', updated_at = now()"
        " WHERE doc_id = %s AND deleted_at IS NULL AND status IN ('parsing', 'embedding')",
        (doc_id,),
    )


async def _maintain(settings: Settings) -> None:
    assert settings.postgres_worker_dsn is not None  # nosec B101
    dsn = settings.postgres_worker_dsn.get_secret_value()
    health = Path(settings.worker_health_file)
    # The queue-age gauge: reported after each sample, nothing while the database is unreachable.
    age: list[float | None] = [None]
    metrics.observe_knowledge_queue_age(lambda: age[0])
    while True:
        try:
            retried = await sweep(dsn, settings.worker_stalled_seconds)
        except Exception as exc:  # noqa: BLE001 - the health file goes stale instead
            log.warning("knowledge.worker.sweep_failed", error=type(exc).__name__)
        else:
            if retried:
                log.info("knowledge.worker.stalled_jobs_retried", count=retried)
            health.touch()
        try:  # a metric only: its failure leaves the worker healthy
            age[0] = await oldest_queued_seconds(dsn)
        except Exception as exc:  # noqa: BLE001
            age[0] = None
            log.warning("knowledge.worker.queue_age_failed", error=type(exc).__name__)
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


def _check_blobs(settings: Settings) -> int:
    assert settings.postgres_worker_dsn is not None  # nosec B101 - main() checks it
    # Read-only in the session too, not only in the code: the worker role may write.
    options = f"{_OPTIONS} -c default_transaction_read_only=on"
    connect = connector(settings.postgres_worker_dsn.get_secret_value(), options)
    root = Path(settings.knowledge_blob_root)
    if settings.knowledge_blob_backend == "local" and not root.is_dir():
        # The store would create it, and an empty root reports every document as missing.
        print("check-blobs failed: APP_KNOWLEDGE_BLOB_ROOT does not exist", file=sys.stderr)
        return 2
    try:
        report = asyncio.run(check_blobs(connect, build_blob_store(settings)))
    except Exception as exc:  # noqa: BLE001
        # Any failure: print the class only, as below.
        print(f"check-blobs failed: {type(exc).__name__}", file=sys.stderr)
        return 2
    print(json.dumps(report, indent=2))
    return 1 if report["missing_blobs"] else 0


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="neuron-worker")
    parser.add_argument(
        "command", nargs="?", choices=("run", "health", "check-blobs"), default="run"
    )
    command = parser.parse_args(argv).command
    settings = get_settings()
    if command == "health":
        raise SystemExit(0 if healthy(settings) else 1)
    if settings.postgres_worker_dsn is None:
        raise SystemExit("neuron-worker needs APP_POSTGRES_WORKER_DSN")
    if command == "check-blobs":
        raise SystemExit(_check_blobs(settings))
    configure_logging(
        level=settings.log_level,
        service=f"{settings.name}-worker",
        version=settings.version,
        environment=settings.env,
    )
    # Spans and metrics over OTLP when `APP_OTEL_ENABLED`, as the API does (RAG-08.03); set
    # `APP_OTEL_SERVICE_NAME` to tell the worker's series from the API's.
    otel = configure_telemetry(settings)
    try:
        asyncio.run(run(settings))
    except StartupCheckError as exc:
        print(f"worker failed: {exc}", file=sys.stderr)
        raise SystemExit(1) from None
    except Exception as exc:  # noqa: BLE001 - as `persistence.cli`: no traceback, no text
        # The class only: a driver or library message can echo the host, the user or the DSN.
        print(f"worker failed: {type(exc).__name__}", file=sys.stderr)
        raise SystemExit(1) from None
    finally:
        if otel is not None:
            otel.shutdown()  # flush what the last jobs recorded
