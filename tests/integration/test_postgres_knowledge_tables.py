"""Knowledge tables, grants and row-level security on Postgres (RAG-01.02, ADR 0014).

Needs pgvector (the pinned `pgvector/pgvector:pg16` image, as in CI). Rows are written by the
migrator, which owns the tables and so is not bound by RLS; reads and writes then run as the app
and worker roles, which are.
"""

from __future__ import annotations

import secrets
import uuid
from collections.abc import Iterator
from typing import Any

import psycopg
import pytest
from psycopg import sql
from psycopg.conninfo import make_conninfo
from test_postgres_roles import (  # noqa: F401
    _DSN,
    RoleDatabase,
    _denied,
    _rows,
    _setup,
    role_db,
    roles,
)

from neuron_agent.persistence.migrations import MIGRATIONS, KnowledgeProfile
from neuron_agent.persistence.roles import AppRoleError
from neuron_agent.persistence.startup_checks import KNOWLEDGE_PROFILE_MISMATCH, StartupCheckError

pytestmark = [pytest.mark.integration, pytest.mark.postgres, pytest.mark.anyio]

_TABLES = ("index_profiles", "bases", "grants", "documents", "chunks", "embeddings")
_OWNER = "a" * 64
_INSERT_EMBEDDING = (
    "INSERT INTO knowledge.embeddings (chunk_id, profile_id, kb_id, embedding)"
    " VALUES (%s, 1, %s, array_fill(0.5, ARRAY[1024])::halfvec)"
)


@pytest.fixture(scope="session")
def worker() -> Iterator[tuple[str, str]]:
    """A third login role for the ingestion worker; dropped when the session ends."""
    if not _DSN:
        pytest.skip("APP_TEST_POSTGRES_DSN is not set; see OPERATIONS.md for a local Postgres.")
    name, password = f"neuron_t{uuid.uuid4().hex[:10]}_worker", secrets.token_hex(16)
    with psycopg.connect(_DSN, autocommit=True) as admin:
        admin.execute(
            sql.SQL("CREATE ROLE {} LOGIN PASSWORD {}").format(
                sql.Identifier(name), sql.Literal(password)
            )
        )
        try:
            yield name, password
        finally:
            admin.execute(sql.SQL("DROP ROLE IF EXISTS {}").format(sql.Identifier(name)))


async def _superuser(db: RoleDatabase, statement: str) -> None:
    assert _DSN
    async with await psycopg.AsyncConnection.connect(
        make_conninfo(_DSN, dbname=db.name), autocommit=True
    ) as conn:
        await conn.execute(statement)  # type: ignore[call-overload]


async def _knowledge_db(db: RoleDatabase, worker: tuple[str, str] | None = None) -> str | None:
    """The operator's one-off step, then setup with knowledge; returns the worker's DSN."""
    await _superuser(db, "CREATE EXTENSION vector")
    await _superuser(db, f'CREATE SCHEMA knowledge AUTHORIZATION "{db.roles.migrator}"')
    await _setup(db, knowledge=True, worker_role=worker[0] if worker else None)
    if worker is None:
        return None
    assert _DSN
    return make_conninfo(_DSN, dbname=db.name, user=worker[0], password=worker[1])


async def _seed(db: RoleDatabase) -> tuple[str, str]:
    """Two knowledge bases, A and B, each with one document, chunk and embedding."""
    kbs = (str(uuid.uuid4()), str(uuid.uuid4()))
    async with await psycopg.AsyncConnection.connect(db.migrator_dsn, autocommit=True) as conn:
        for kb in kbs:
            doc = str(uuid.uuid4())
            chunk = str(uuid.uuid4())
            await conn.execute(
                "INSERT INTO knowledge.bases (kb_id, owner_key, name, profile_id)"
                " VALUES (%s, %s, 'kb', 1)",
                (kb, _OWNER),
            )
            await conn.execute(
                "INSERT INTO knowledge.documents (doc_id, kb_id, uploaded_by, title, mime_type,"
                " size_bytes, sha256, blob_key, status)"
                " VALUES (%s, %s, %s, 't', 'text/plain', 1, %s, 'k', 'ready')",
                (doc, kb, _OWNER, "b" * 64),
            )
            await conn.execute(
                "INSERT INTO knowledge.chunks (chunk_id, doc_id, kb_id, ordinal, text,"
                " token_count, ts_config) VALUES (%s, %s, %s, 0, 'fictional text', 2, 'simple')",
                (chunk, doc, kb),
            )
            await conn.execute(
                _INSERT_EMBEDDING,
                (chunk, kb),
            )
    return kbs


async def _visible(conn: psycopg.AsyncConnection[Any], kb_ids: str | None) -> dict[str, set[str]]:
    """The KB ids of the chunks and embeddings one transaction sees."""
    seen: dict[str, set[str]] = {}
    async with conn.transaction():
        if kb_ids is not None:
            await conn.execute("SELECT set_config('neuron.kb_ids', %s, true)", (kb_ids,))
        for table in ("chunks", "embeddings"):
            query = sql.SQL("SELECT kb_id::text FROM {}").format(sql.Identifier("knowledge", table))
            cursor = await conn.execute(query)
            seen[table] = {row[0] for row in await cursor.fetchall()}
    return seen


async def test_the_app_role_sees_only_the_knowledge_bases_it_sets(role_db: RoleDatabase) -> None:  # noqa: F811
    await _knowledge_db(role_db)
    a, b = await _seed(role_db)
    async with await psycopg.AsyncConnection.connect(role_db.app_dsn) as conn:
        assert await _visible(conn, a) == {"chunks": {a}, "embeddings": {a}}
        assert await _visible(conn, f"{a},{b}") == {"chunks": {a, b}, "embeddings": {a, b}}


async def test_unset_kb_ids_return_no_rows(role_db: RoleDatabase) -> None:  # noqa: F811
    await _knowledge_db(role_db)
    await _seed(role_db)
    async with await psycopg.AsyncConnection.connect(role_db.app_dsn) as conn:
        assert await _visible(conn, None) == {"chunks": set(), "embeddings": set()}
        assert await _visible(conn, "") == {"chunks": set(), "embeddings": set()}


async def test_the_setting_does_not_outlive_its_transaction(role_db: RoleDatabase) -> None:  # noqa: F811
    await _knowledge_db(role_db)
    a, _ = await _seed(role_db)
    # One connection, as a pool hands it out to request after request.
    async with await psycopg.AsyncConnection.connect(role_db.app_dsn) as conn:
        assert await _visible(conn, a) == {"chunks": {a}, "embeddings": {a}}
        assert await _visible(conn, None) == {"chunks": set(), "embeddings": set()}


async def test_runtime_roles_cannot_alter_drop_or_disable_rls(
    role_db: RoleDatabase,  # noqa: F811
    worker: tuple[str, str],
) -> None:
    worker_dsn = await _knowledge_db(role_db, worker)
    assert worker_dsn is not None
    for dsn in (role_db.app_dsn, worker_dsn):
        for table in _TABLES:
            name = f"knowledge.{table}"
            await _denied(dsn, f"DROP TABLE {name}")
            await _denied(dsn, f"ALTER TABLE {name} ADD COLUMN probe int")
            await _denied(dsn, f"ALTER TABLE {name} DISABLE ROW LEVEL SECURITY")
            await _denied(dsn, f"ALTER TABLE {name} NO FORCE ROW LEVEL SECURITY")
            await _denied(dsn, f"TRUNCATE {name}")
        await _denied(dsn, "DROP POLICY kb_scope ON knowledge.chunks")
        await _denied(dsn, "CREATE TABLE knowledge.probe (a int)")
    # RLS stays on, and the migrator owns every table, the job queue's too (migration 25; its
    # rows carry ids only, so it has no RLS).
    queue = ("procrastinate_events", "procrastinate_jobs", "procrastinate_periodic_defers")
    assert await _rows(
        role_db.migrator_dsn,
        "SELECT relname::text, relrowsecurity, pg_get_userbyid(relowner)::text FROM pg_class"
        " WHERE relnamespace = 'knowledge'::regnamespace AND relkind = 'r' ORDER BY 1",
    ) == [
        (t, t in {"chunks", "embeddings"}, role_db.roles.migrator)
        for t in sorted((*_TABLES, *queue, "procrastinate_workers"))
    ]


async def test_grants_are_exactly_what_each_role_needs(
    role_db: RoleDatabase,  # noqa: F811
    worker: tuple[str, str],
) -> None:
    await _knowledge_db(role_db, worker)
    privileges = ("SELECT", "INSERT", "UPDATE", "DELETE", "TRUNCATE", "REFERENCES", "TRIGGER")

    async def granted(role: str) -> dict[str, set[str]]:
        rows = await _rows(
            role_db.migrator_dsn,
            "SELECT t, p FROM unnest(%s::text[]) t, unnest(%s::text[]) p"
            " WHERE has_table_privilege(%s, 'knowledge.' || t, p)",
            (list(_TABLES), list(privileges), role),
        )
        found: dict[str, set[str]] = {t: set() for t in _TABLES}
        for table, privilege in rows:
            found[table].add(privilege)
        return found

    dml = {"SELECT", "INSERT", "UPDATE", "DELETE"}
    assert await granted(role_db.roles.app) == {
        "index_profiles": {"SELECT"},
        "bases": dml,
        "grants": dml,
        "documents": dml,
        "chunks": {"SELECT"},
        "embeddings": {"SELECT"},
    }
    assert await granted(worker[0]) == {
        "index_profiles": {"SELECT"},
        "bases": {"SELECT", "DELETE"},  # the purge (RAG-03.03)
        "grants": set(),
        "documents": {"SELECT", "DELETE"},
        "chunks": {"SELECT", "INSERT", "DELETE"},
        "embeddings": {"SELECT", "INSERT", "DELETE"},
    }
    # The worker records progress on a document but cannot move it or repoint its blob.
    assert await _rows(
        role_db.migrator_dsn,
        "SELECT c FROM unnest(%s::text[]) c"
        " WHERE has_column_privilege(%s, 'knowledge.documents', c, 'UPDATE') ORDER BY c",
        (
            [
                "status",
                "error_code",
                "parser_version",
                "page_count",
                "embedding_tokens",
                "updated_at",
                "kb_id",
                "blob_key",
                "sha256",
                "uploaded_by",
            ],
            worker[0],
        ),
    ) == [
        ("embedding_tokens",),
        ("error_code",),
        ("page_count",),
        ("parser_version",),
        ("status",),
        ("updated_at",),
    ]
    # A right granted by hand is taken back by the next setup; production then verifies.
    await _superuser(role_db, f'GRANT INSERT ON knowledge.chunks TO "{role_db.roles.app}"')
    await _setup(role_db, knowledge=True, worker_role=worker[0], require_app_role=True)
    assert (await granted(role_db.roles.app))["chunks"] == {"SELECT"}


async def test_the_worker_writes_only_inside_the_kb_it_sets(
    role_db: RoleDatabase,  # noqa: F811
    worker: tuple[str, str],
) -> None:
    worker_dsn = await _knowledge_db(role_db, worker)
    assert worker_dsn is not None
    a, b = await _seed(role_db)
    doc = (
        await _rows(
            role_db.migrator_dsn, "SELECT doc_id FROM knowledge.documents WHERE kb_id = %s", (a,)
        )
    )[0][0]
    insert = (
        "INSERT INTO knowledge.chunks (chunk_id, doc_id, kb_id, ordinal, text, token_count,"
        " ts_config) VALUES (gen_random_uuid(), %s, %s, 1, 'more', 1, 'simple')"
    )
    async with await psycopg.AsyncConnection.connect(worker_dsn) as conn:
        async with conn.transaction():
            await conn.execute("SELECT set_config('neuron.kb_ids', %s, true)", (a,))
            await conn.execute(insert, (doc, a))
        # WITH CHECK: a row for a KB the transaction did not set is refused.
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            async with conn.transaction():
                await conn.execute("SELECT set_config('neuron.kb_ids', %s, true)", (b,))
                await conn.execute(insert, (doc, a))
    # The app role reads chunks but never writes them.
    await _denied(role_db.app_dsn, "DELETE FROM knowledge.chunks")


async def test_the_copied_kb_id_must_match_the_parent(role_db: RoleDatabase) -> None:  # noqa: F811
    await _knowledge_db(role_db)
    a, b = await _seed(role_db)
    async with await psycopg.AsyncConnection.connect(role_db.migrator_dsn, autocommit=True) as conn:
        doc = (
            await (
                await conn.execute("SELECT doc_id FROM knowledge.documents WHERE kb_id = %s", (a,))
            ).fetchone()
        )[0]  # type: ignore[index]
        chunk = (
            await (
                await conn.execute("SELECT chunk_id FROM knowledge.chunks WHERE kb_id = %s", (a,))
            ).fetchone()
        )[0]  # type: ignore[index]
        with pytest.raises(psycopg.errors.ForeignKeyViolation):
            await conn.execute(
                "INSERT INTO knowledge.chunks (chunk_id, doc_id, kb_id, ordinal, text,"
                " token_count, ts_config) VALUES (gen_random_uuid(), %s, %s, 1, 'x', 1, 'simple')",
                (doc, b),
            )
        await conn.execute("DELETE FROM knowledge.embeddings WHERE chunk_id = %s", (chunk,))
        with pytest.raises(psycopg.errors.ForeignKeyViolation):
            await conn.execute(
                _INSERT_EMBEDDING,
                (chunk, b),
            )
        # Owner columns take only the HMAC owner key, never a raw subject.
        with pytest.raises(psycopg.errors.CheckViolation):
            await conn.execute(
                "INSERT INTO knowledge.bases (kb_id, owner_key, name, profile_id)"
                " VALUES (gen_random_uuid(), 'alice@example.test', 'kb', 1)"
            )
        # Deleting a document removes its chunks and embeddings.
        await conn.execute("DELETE FROM knowledge.documents WHERE doc_id = %s", (doc,))
        for table in ("chunks", "embeddings"):
            query = sql.SQL("SELECT count(*) FROM {} WHERE kb_id = %s").format(
                sql.Identifier("knowledge", table)
            )
            cursor = await conn.execute(query, (a,))
            assert await cursor.fetchone() == (0,)


async def test_profile_one_is_seeded_once_with_its_hnsw_index(role_db: RoleDatabase) -> None:  # noqa: F811
    await _knowledge_db(role_db)
    assert await _rows(
        role_db.migrator_dsn,
        "SELECT profile_id, provider, model, dimensions, status FROM knowledge.index_profiles",
    ) == [(1, "nvidia", "nvidia/nemotron-3.5-embed-1b", 1024, "active")]
    index = await _rows(
        role_db.migrator_dsn,
        "SELECT i.indisvalid, pg_get_indexdef(i.indexrelid) FROM pg_index i"
        " WHERE i.indexrelid = to_regclass('knowledge.embeddings_p1_hnsw')",
    )
    assert index and index[0][0] is True
    assert "hnsw" in index[0][1] and "halfvec(1024)" in index[0][1]
    assert "WHERE (profile_id = 1)" in index[0][1]
    assert await _setup(role_db, knowledge=True) == []
    with pytest.raises(StartupCheckError) as caught:
        await _setup(role_db, knowledge=True, knowledge_profile=KnowledgeProfile(dimensions=2048))
    assert caught.value.code == KNOWLEDGE_PROFILE_MISMATCH


async def test_the_worker_role_must_be_its_own(role_db: RoleDatabase) -> None:  # noqa: F811
    await _superuser(role_db, "CREATE EXTENSION vector")
    with pytest.raises(AppRoleError):
        await _setup(role_db, knowledge=True, worker_role=role_db.roles.app)


async def _public_schema(dsn: str) -> list[tuple[Any, ...]]:
    """Every column, index, constraint and grant in the v1.0.0 schema."""
    return await _rows(
        dsn,
        "SELECT 'col', table_name::text, column_name::text, data_type::text,"
        " coalesce(column_default, '')"
        " FROM information_schema.columns WHERE table_schema = 'public'"
        " UNION ALL SELECT 'idx', tablename::text, indexname::text, indexdef, ''"
        " FROM pg_indexes WHERE schemaname = 'public'"
        " UNION ALL SELECT 'con', conrelid::regclass::text, conname::text,"
        " pg_get_constraintdef(oid), '' FROM pg_constraint"
        " WHERE connamespace = 'public'::regnamespace"
        " UNION ALL SELECT 'acl', relname::text, coalesce(relacl::text, ''), '', ''"
        " FROM pg_class WHERE relnamespace = 'public'::regnamespace"
        " ORDER BY 1, 2, 3",
    )


async def test_upgrading_a_v1_0_0_database_leaves_its_tables_unchanged(
    role_db: RoleDatabase,  # noqa: F811
) -> None:
    core = [m.version for m in MIGRATIONS if m.feature is None]
    assert await _setup(role_db) == core
    before = await _public_schema(role_db.migrator_dsn)
    await _knowledge_db(role_db)
    assert await _public_schema(role_db.migrator_dsn) == before


@pytest.mark.parametrize(
    "tamper",
    [
        "ALTER TABLE knowledge.chunks DISABLE ROW LEVEL SECURITY",
        "DROP POLICY kb_scope ON knowledge.embeddings",
        # A second permissive policy is ORed with kb_scope.
        "CREATE POLICY open ON knowledge.chunks USING (true)",
        "ALTER POLICY kb_scope ON knowledge.embeddings USING (true) WITH CHECK (true)",
        "GRANT CREATE ON SCHEMA knowledge TO {worker}",
    ],
)
async def test_setup_refuses_row_security_or_schema_drift(
    role_db: RoleDatabase,  # noqa: F811
    worker: tuple[str, str],
    tamper: str,
) -> None:
    await _knowledge_db(role_db, worker)
    await _superuser(role_db, tamper.format(worker=f'"{worker[0]}"'))
    with pytest.raises(StartupCheckError) as caught:
        await _setup(role_db, knowledge=True, worker_role=worker[0])
    assert caught.value.code == "knowledge_schema_untrusted"
