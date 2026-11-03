"""The knowledge job queue on Postgres (RAG-02.01, ADR 0014 K4).

Procrastinate's tables live in the `knowledge` schema (migration 25). The API role queues a job
inside the transaction that writes its document; the worker role runs it. Needs pgvector, as the
other knowledge tests do.
"""

from __future__ import annotations

import uuid
from typing import Any

import procrastinate
import psycopg
import pytest
from test_postgres_knowledge_tables import _knowledge_db, worker  # noqa: F401
from test_postgres_roles import _DSN, RoleDatabase, _denied, _rows, role_db, roles  # noqa: F401

from neuron_agent.knowledge import jobs
from neuron_agent.persistence.roles import AppRoleError

pytestmark = [pytest.mark.integration, pytest.mark.postgres, pytest.mark.anyio]

_OWNER = "c" * 64
_QUEUE_TABLES = (
    "procrastinate_jobs",
    "procrastinate_events",
    "procrastinate_workers",
    "procrastinate_periodic_defers",
)


async def _upload(conn: psycopg.AsyncConnection[Any]) -> uuid.UUID:
    """What RAG-03.02's upload does in one transaction: a base, a queued document, its job."""
    kb, doc = uuid.uuid4(), uuid.uuid4()
    await conn.execute(
        "INSERT INTO knowledge.bases (kb_id, owner_key, name, profile_id) VALUES (%s, %s, 'kb', 1)",
        (kb, _OWNER),
    )
    await conn.execute(
        "INSERT INTO knowledge.documents (doc_id, kb_id, uploaded_by, title, mime_type,"
        " size_bytes, sha256, blob_key, status)"
        " VALUES (%s, %s, %s, 't', 'text/plain', 1, %s, 'k', 'queued')",
        (doc, kb, _OWNER, "d" * 64),
    )
    await jobs.defer(conn, jobs.Task.INGEST_DOCUMENT, doc_id=doc)
    return doc


async def _jobs(db: RoleDatabase) -> list[tuple[Any, ...]]:
    return await _rows(
        db.migrator_dsn,
        "SELECT queue_name, task_name, args, status FROM knowledge.procrastinate_jobs ORDER BY id",
    )


async def test_a_job_exists_only_if_its_document_insert_commits(
    role_db: RoleDatabase,  # noqa: F811
) -> None:
    await _knowledge_db(role_db)
    async with await psycopg.AsyncConnection.connect(role_db.app_dsn) as conn:
        await _upload(conn)
        await conn.rollback()
        assert await _jobs(role_db) == []
        assert await _rows(role_db.migrator_dsn, "SELECT count(*) FROM knowledge.documents") == [
            (0,)
        ]
        doc = await _upload(conn)
        await conn.commit()
    assert await _jobs(role_db) == [("knowledge", "ingest_document", {"doc_id": str(doc)}, "todo")]


async def test_the_worker_role_may_not_share_the_app_roles_rights(
    role_db: RoleDatabase,  # noqa: F811
    worker: tuple[str, str],  # noqa: F811
) -> None:
    # Membership would hand the worker the app role's rights in `public`. The roles live for
    # the whole session, so the grant is taken back.
    assert _DSN
    app, member = f'"{role_db.roles.app}"', f'"{worker[0]}"'
    async with await psycopg.AsyncConnection.connect(_DSN, autocommit=True) as admin:
        await admin.execute(f"GRANT {app} TO {member}")  # type: ignore[call-overload]
        try:
            with pytest.raises(AppRoleError, match="member of the app role"):
                await _knowledge_db(role_db, worker)
        finally:
            await admin.execute(f"REVOKE {app} FROM {member}")  # type: ignore[call-overload]


async def test_defer_needs_the_callers_transaction(role_db: RoleDatabase) -> None:  # noqa: F811
    await _knowledge_db(role_db)
    async with await psycopg.AsyncConnection.connect(role_db.app_dsn, autocommit=True) as conn:
        with pytest.raises(ValueError, match="inside the transaction"):
            await jobs.defer(conn, jobs.Task.INGEST_DOCUMENT, doc_id=uuid.uuid4())
    assert await _jobs(role_db) == []


async def test_the_api_queues_and_the_worker_runs_with_exact_rights(
    role_db: RoleDatabase,  # noqa: F811
    worker: tuple[str, str],  # noqa: F811
) -> None:
    worker_dsn = await _knowledge_db(role_db, worker)
    assert worker_dsn is not None
    privileges = ("SELECT", "INSERT", "UPDATE", "DELETE", "TRUNCATE", "REFERENCES", "TRIGGER")

    async def granted(role: str) -> dict[str, set[str]]:
        rows = await _rows(
            role_db.migrator_dsn,
            "SELECT t, p FROM unnest(%s::text[]) t, unnest(%s::text[]) p"
            " WHERE has_table_privilege(%s, 'knowledge.' || t, p)",
            (list(_QUEUE_TABLES), list(privileges), role),
        )
        found: dict[str, set[str]] = {t: set() for t in _QUEUE_TABLES}
        for table, privilege in rows:
            found[table].add(privilege)
        return found

    assert await granted(role_db.roles.app) == {
        "procrastinate_jobs": {"SELECT", "INSERT"},
        "procrastinate_events": {"INSERT"},
        "procrastinate_workers": set(),
        "procrastinate_periodic_defers": set(),
    }
    dml = {"SELECT", "INSERT", "UPDATE", "DELETE"}
    assert await granted(worker[0]) == dict.fromkeys(_QUEUE_TABLES, dml)
    # The worker reaches nothing in `public`: no threads, checkpoints or token ledger.
    for table in ("checkpoints", "checkpoint_writes", "neuron_thread_meta", "neuron_token_ledger"):
        await _denied(worker_dsn, f"SELECT 1 FROM public.{table}")  # noqa: S608
    # The API cannot change or drop a queued job.
    await _denied(role_db.app_dsn, "UPDATE knowledge.procrastinate_jobs SET status = 'todo'")
    await _denied(role_db.app_dsn, "DELETE FROM knowledge.procrastinate_jobs")

    async with await psycopg.AsyncConnection.connect(role_db.app_dsn) as conn:
        doc = await _upload(conn)
        await conn.commit()
    ran: list[str] = []
    app = procrastinate.App(
        connector=procrastinate.PsycopgConnector(
            conninfo=worker_dsn, kwargs={"options": "-c search_path=knowledge"}
        )
    )

    @app.task(name=jobs.Task.INGEST_DOCUMENT.value, queue=jobs.QUEUE)
    async def ingest(doc_id: str) -> None:
        ran.append(doc_id)

    async with app.open_async():
        await app.run_worker_async(queues=[jobs.QUEUE], wait=False, install_signal_handlers=False)
    assert ran == [str(doc)]
    assert [row[3] for row in await _jobs(role_db)] == ["succeeded"]
