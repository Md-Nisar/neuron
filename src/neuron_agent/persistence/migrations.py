# Copyright 2026 Md Nisar Ahmed
# SPDX-License-Identifier: Apache-2.0

"""neuron's own schema migrations, recorded in `neuron_migrations` (ADR 0008 decision 7).

LangGraph's `AsyncPostgresSaver.setup()` owns the checkpoint tables. Everything neuron adds
on top is an ordered `Migration` here, applied after LangGraph's `setup()` by `run_setup`.

Compatibility rule (expand/contract): a release's migrations must leave the previous release
working. Add tables, nullable columns and concurrent indexes; remove or rename only in a
later release, as a migration with `contract_release` naming the release whose image stopped
using the old shape. There are no down-migrations: rollback is redeploying the previous image.
`tests/unit/test_migrations_policy.py` enforces the rule.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import time
from collections.abc import Awaitable, Callable, Collection, Sequence
from dataclasses import dataclass

import psycopg
import structlog
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.store.postgres import AsyncPostgresStore
from procrastinate.schema import SchemaManager
from psycopg import sql
from psycopg.rows import dict_row

from neuron_agent.observability.audit import audit
from neuron_agent.persistence.roles import AppRoleError, role_problems
from neuron_agent.persistence.startup_checks import (
    KNOWLEDGE_PROFILE_MISMATCH,
    KNOWLEDGE_SCHEMA_MISSING,
    KNOWLEDGE_SCHEMA_UNTRUSTED,
    VECTOR_EXTENSION_MISSING,
    StartupCheckError,
)

logger = structlog.get_logger(__name__)

# The Procrastinate release whose schema migration 25 installs (pinned in `pyproject.toml`).
PROCRASTINATE_VERSION = "3.10.0"

# DDL waits at most this long for a lock, so a migration behind live traffic fails the
# deploy instead of queueing every request behind it.
DEFAULT_LOCK_TIMEOUT_MS = 5000
# `CREATE INDEX CONCURRENTLY` also waits for every older transaction to finish, and
# `lock_timeout` covers those waits, so the 5 s above would fail the deploy (and leave an
# INVALID index) whenever a session sits idle in a transaction. Concurrent migrations run
# under this longer bound instead: 10 minutes, long enough for a slow transaction to end,
# short enough that a stuck one still fails the deploy rather than hanging it.
CONCURRENT_LOCK_TIMEOUT_MS = 600_000
# How long a second `setup` waits for the first to finish before giving up.
LOCK_WAIT_SECONDS = 300.0
# Session-level advisory lock on the direct (never pooled) migration connection: "neuron".
_ADVISORY_LOCK_KEY = 0x6E6575726F6E

_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS neuron_migrations (
    version integer PRIMARY KEY,
    name text NOT NULL,
    applied_at timestamptz NOT NULL DEFAULT now()
)
"""


# The check value is an HMAC of this fixed label under `APP_IDENTITY_HASH_KEY` (ADR 0008
# decision 16): it identifies the key without revealing it.
_IDENTITY_LABEL = b"neuron.identity-key-check.v1"
_IDENTITY_META_KEY = "identity_key_check"

# What the app role may do on each table (ADR 0008 decision 15). Bookkeeping tables get
# nothing: only the migrator reads them, and `neuron_meta` holds a check value that is an
# offline oracle for a weak identity key, so the app role does not read it either. Leases are
# never updated, only claimed, released and swept.
_DML = frozenset({"SELECT", "INSERT", "UPDATE", "DELETE"})
_APP_PRIVILEGES: dict[str, frozenset[str]] = {
    "checkpoints": _DML,
    "checkpoint_blobs": _DML,
    "checkpoint_writes": _DML,
    "neuron_run_leases": frozenset({"SELECT", "INSERT", "DELETE"}),
    "neuron_token_ledger": _DML,
    "neuron_rate_buckets": _DML,
    # Conversation titles (ADR 0011); present from migration 13 on any database.
    "neuron_thread_meta": _DML,
    # Answer ratings (ADR 0011); present from migration 15.
    "neuron_feedback": _DML,
    # Settled reservation ids are only inserted (idempotent settle) and swept by retention.
    "neuron_token_settlements": frozenset({"SELECT", "INSERT", "DELETE"}),
    "neuron_meta": frozenset(),
    "neuron_migrations": frozenset(),
    "checkpoint_migrations": frozenset(),
    # LangGraph's `AsyncPostgresStore` tables, created only when memory is enabled (ADR 0009).
    "store": _DML,
    "store_migrations": frozenset(),
}
# The table per-user memory lives in; readiness needs it when memory is on.
STORE_TABLE = "store"
# The one function the app role may run: it answers whether a candidate check value matches the
# one in `neuron_meta` without letting the role read that table (migration 12).
_IDENTITY_FUNCTION = "neuron_identity_status"
# The tables the guards (run leases, token budget, rate limiter) read and write, derived from the
# grants above so a new guard table is picked up by readiness without another list.
THREAD_META_TABLE = "neuron_thread_meta"
FEEDBACK_TABLE = "neuron_feedback"
# Tables of per-user content the API reads and writes; readiness needs them on Postgres.
USER_CONTENT_TABLES = (THREAD_META_TABLE, FEEDBACK_TABLE)
GUARD_TABLES = tuple(
    sorted(
        t
        for t, grants in _APP_PRIVILEGES.items()
        if grants and t.startswith("neuron_") and t not in USER_CONTENT_TABLES
    )
)
_CHECKED_PRIVILEGES = (*sorted(_DML), "TRUNCATE", "REFERENCES", "TRIGGER")


class LockWaitTimeout(TimeoutError):
    """Another `setup` held the advisory lock for the whole wait. The text is fixed."""


class IdentityKeyMismatch(Exception):
    """The database holds a different identity key check value. The text is fixed and safe."""


def identity_check_value(identity_hash_key: str) -> str:
    """HMAC-SHA256 of a fixed label under the key: stored in `neuron_meta`, never the key."""
    return hmac.new(identity_hash_key.encode("utf-8"), _IDENTITY_LABEL, hashlib.sha256).hexdigest()


@dataclass(frozen=True)
class Migration:
    """One schema change.

    `concurrent` migrations hold a single `CREATE INDEX CONCURRENTLY` statement and run
    outside a transaction; others run in one transaction together with their record.
    `index` names an index the migration builds, so an `INVALID` leftover can be rebuilt.
    `contract_release` marks a contract step (see the module docstring).
    `feature` names the setting that enables it (`knowledge`): skipped, and left unrecorded,
    until that feature is on, so a database without the feature's extension still sets up.
    """

    version: int
    name: str
    sql: str
    concurrent: bool = False
    index: str | None = None
    contract_release: str | None = None
    feature: str | None = None


# Migration 25 ends with this: every Procrastinate function resolves names in the knowledge schema.
_PIN_QUEUE = """;
DO $do$
DECLARE
    f regprocedure;
BEGIN
    FOR f IN SELECT p.oid::regprocedure FROM pg_proc p
        WHERE p.pronamespace = 'knowledge'::regnamespace AND p.proname LIKE 'procrastinate%'
    LOOP
        EXECUTE format('ALTER FUNCTION %s SET search_path = knowledge, pg_catalog, pg_temp', f);
    END LOOP;
END
$do$
"""

MIGRATIONS: tuple[Migration, ...] = (
    Migration(
        version=1,
        name="owner_index",
        # Serves the per-owner thread listing (`persistence/thread_index.py`) on the table
        # LangGraph owns.
        sql="""
CREATE INDEX CONCURRENTLY IF NOT EXISTS neuron_checkpoints_owner_idx
ON checkpoints ((metadata->>'owner'), thread_id)
WHERE checkpoint_ns = ''
""",
        concurrent=True,
        index="neuron_checkpoints_owner_idx",
    ),
    Migration(
        version=2,
        name="run_leases",
        # Shared run guard (`persistence/run_guard.py`, ADR 0008 decision 8). The unique
        # constraint on `thread_id` is what makes a second run on a thread fail; a NULL
        # `thread_id` (no persistence) never conflicts. `kind` separates runs, which count
        # against the per-owner cap, from a thread held for deletion, which does not.
        sql="""
CREATE TABLE IF NOT EXISTS neuron_run_leases (
    lease_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    owner_key text NOT NULL,
    thread_id text UNIQUE,
    kind text NOT NULL DEFAULT 'run' CHECK (kind IN ('run', 'delete')),
    expires_at timestamptz NOT NULL
)
""",
    ),
    # Serve the per-owner count and listing, and the expiry sweep, on the table above.
    Migration(
        version=3,
        name="run_leases_owner_idx",
        sql="""
CREATE INDEX CONCURRENTLY IF NOT EXISTS neuron_run_leases_owner_idx
ON neuron_run_leases (owner_key)
""",
        concurrent=True,
        index="neuron_run_leases_owner_idx",
    ),
    Migration(
        version=4,
        name="run_leases_expires_idx",
        sql="""
CREATE INDEX CONCURRENTLY IF NOT EXISTS neuron_run_leases_expires_idx
ON neuron_run_leases (expires_at)
""",
        concurrent=True,
        index="neuron_run_leases_expires_idx",
    ),
    Migration(
        version=5,
        name="neuron_meta",
        # Key/value facts about the deployment; `setup` stores the identity key check value
        # here (ADR 0008 decision 16). No access for the app role (see `table_grant_statements`).
        sql="""
CREATE TABLE IF NOT EXISTS neuron_meta (
    key text PRIMARY KEY,
    value text NOT NULL,
    updated_at timestamptz NOT NULL DEFAULT now()
)
""",
    ),
    Migration(
        version=6,
        name="token_ledger",
        # Shared token budget (`persistence/token_budget.py`, ADR 0008 decision 8): tokens
        # charged per owner per database-clock minute. Logged (not UNLOGGED): a budget must
        # survive a crash. The primary key is what the atomic upsert conflicts on.
        sql="""
CREATE TABLE IF NOT EXISTS neuron_token_ledger (
    owner_key text NOT NULL,
    minute timestamptz NOT NULL,
    tokens bigint NOT NULL DEFAULT 0 CHECK (tokens >= 0),
    PRIMARY KEY (owner_key, minute)
)
""",
    ),
    # Serves the retention job's delete of minutes outside the window.
    Migration(
        version=7,
        name="token_ledger_minute_idx",
        sql="""
CREATE INDEX CONCURRENTLY IF NOT EXISTS neuron_token_ledger_minute_idx
ON neuron_token_ledger (minute)
""",
        concurrent=True,
        index="neuron_token_ledger_minute_idx",
    ),
    Migration(
        version=8,
        name="token_settlements",
        # One row per settled reservation, written in the same transaction as the ledger
        # change, so a settlement replayed after an ambiguous COMMIT changes nothing.
        sql="""
CREATE TABLE IF NOT EXISTS neuron_token_settlements (
    reservation_id uuid PRIMARY KEY,
    settled_at timestamptz NOT NULL DEFAULT clock_timestamp()
)
""",
    ),
    # Serves the retention job's delete of old settlement rows.
    Migration(
        version=9,
        name="token_settlements_settled_idx",
        sql="""
CREATE INDEX CONCURRENTLY IF NOT EXISTS neuron_token_settlements_settled_idx
ON neuron_token_settlements (settled_at)
""",
        concurrent=True,
        index="neuron_token_settlements_settled_idx",
    ),
    Migration(
        version=10,
        name="rate_buckets",
        # Shared request rate limiter (`persistence/rate_limiter.py`, ADR 0008 decision 8):
        # one token bucket per key. UNLOGGED on purpose: no WAL for a write per request, and
        # empty after a crash, failover or restore, which grants a burst (ADR 0004). Keys are
        # `principal:<owner key>` or `ip:<HMAC>`, never a raw address.
        sql="""
CREATE UNLOGGED TABLE IF NOT EXISTS neuron_rate_buckets (
    key text PRIMARY KEY,
    tokens double precision NOT NULL CHECK (tokens >= 0),
    refilled_at timestamptz NOT NULL,
    allowed boolean NOT NULL
) WITH (fillfactor = 70, autovacuum_vacuum_scale_factor = 0.02)
""",
    ),
    # Serves the delete of idle buckets (opportunistic and the retention job).
    Migration(
        version=11,
        name="rate_buckets_refilled_idx",
        sql="""
CREATE INDEX CONCURRENTLY IF NOT EXISTS neuron_rate_buckets_refilled_idx
ON neuron_rate_buckets (refilled_at)
""",
        concurrent=True,
        index="neuron_rate_buckets_refilled_idx",
    ),
    Migration(
        version=12,
        name="identity_status_function",
        # Start-up identity key check (ADR 0008 decision 16). The app role has no access to
        # `neuron_meta`, so it asks this SECURITY DEFINER function (owned by the migrator, so it
        # can read the table) whether its candidate check value matches: 'match', 'mismatch' or
        # 'unset'. It never returns the stored value. `search_path` is pinned so no object the
        # caller can create is resolved in its place; the schema is the migrator's current one.
        sql="""
DO $do$
BEGIN
    EXECUTE format($f$
CREATE OR REPLACE FUNCTION %1$I.neuron_identity_status(candidate text) RETURNS text
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $body$
SELECT coalesce(
    (SELECT CASE WHEN value = candidate THEN 'match' ELSE 'mismatch' END
     FROM %1$I.neuron_meta WHERE key = 'identity_key_check'),
    'unset')
$body$
$f$, current_schema());
    EXECUTE format(
        'REVOKE ALL ON FUNCTION %I.neuron_identity_status(text) FROM PUBLIC', current_schema());
END
$do$
""",
    ),
    Migration(
        version=13,
        name="thread_meta",
        # Conversation titles (`persistence/thread_meta.py`, ADR 0011): content derived from the
        # user's first message, filed under the HMAC owner key and removed with the thread.
        sql="""
CREATE TABLE IF NOT EXISTS neuron_thread_meta (
    owner_key text NOT NULL,
    thread_id text NOT NULL,
    title text NOT NULL CHECK (char_length(title) <= 80),
    updated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (owner_key, thread_id)
)
""",
    ),
    # Serves the delete by thread ID (thread deletion, erasure and retention know no owner).
    Migration(
        version=14,
        name="thread_meta_thread_idx",
        sql="""
CREATE INDEX CONCURRENTLY IF NOT EXISTS neuron_thread_meta_thread_idx
ON neuron_thread_meta (thread_id)
""",
        concurrent=True,
        index="neuron_thread_meta_thread_idx",
    ),
    Migration(
        version=15,
        name="feedback",
        # Answer ratings (`persistence/feedback.py`, ADR 0010 decision 6): a score and a fixed
        # reason per (owner, run), never text. The primary key makes a rating idempotent.
        sql="""
CREATE TABLE IF NOT EXISTS neuron_feedback (
    owner_key text NOT NULL,
    thread_id text NOT NULL,
    run_id text NOT NULL,
    score smallint NOT NULL CHECK (score IN (-1, 1)),
    reason text CHECK (reason IS NULL OR char_length(reason) <= 32),
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (owner_key, run_id)
)
""",
    ),
    # Serves the delete by thread ID (thread deletion, erasure and retention know no owner).
    Migration(
        version=16,
        name="feedback_thread_idx",
        sql="""
CREATE INDEX CONCURRENTLY IF NOT EXISTS neuron_feedback_thread_idx
ON neuron_feedback (thread_id)
""",
        concurrent=True,
        index="neuron_feedback_thread_idx",
    ),
    Migration(
        version=17,
        name="knowledge_schema",
        # Knowledge Engine (ADR 0014; RAG-01.01). pgvector is not a trusted extension, and the
        # migrator has no CREATE on the database, so the operator creates both first as a
        # superuser (OPERATIONS.md, "Database roles"; `run_setup` checks with stable codes).
        # Neither statement then needs a privilege: `CREATE SCHEMA IF NOT EXISTS` would, so the
        # schema is only created when missing. It belongs to the migrator, and no runtime role
        # gets CREATE on it: RAG-01.02 grants table rights only.
        sql="""
CREATE EXTENSION IF NOT EXISTS vector;
DO $do$
BEGIN
    IF to_regnamespace('knowledge') IS NULL THEN
        CREATE SCHEMA knowledge;
    END IF;
END
$do$
""",
        feature="knowledge",
    ),
    Migration(
        version=18,
        name="knowledge_tables",
        # Knowledge Engine tables (ADR 0014; RAG-01.02; the research report's section 8). Every
        # owner column holds the HMAC owner key (64 hex characters), never a raw subject. `kb_id`
        # is copied onto chunks and embeddings for filters and row-level security; composite
        # foreign keys keep each copy equal to its parent's. The RLS policy repeats the SQL
        # filters (RAG-04.01) and reads `neuron.kb_ids`, which callers set with `SET LOCAL`:
        # unset (NULL) or reset to '' after an earlier transaction, it matches no row. The
        # migrator owns the tables, so RLS binds the app and worker roles; foreign-key cascades
        # bypass it. `bases`, `grants` and `documents` have no RLS: the API finds them by owner
        # and grant before it knows the allowed KB ids. The HNSW index per profile is built by
        # `run_setup` once the profile's dimension is known.
        sql="""
CREATE TABLE IF NOT EXISTS knowledge.index_profiles (
    profile_id smallint PRIMARY KEY,
    provider text NOT NULL,
    model text NOT NULL,
    dimensions integer NOT NULL CHECK (dimensions BETWEEN 1 AND 4000),
    chunker text NOT NULL,
    status text NOT NULL CHECK (status IN ('building', 'active', 'retired')),
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS knowledge.bases (
    kb_id uuid PRIMARY KEY,
    owner_key text NOT NULL CHECK (owner_key ~ '^[0-9a-f]{64}$'),
    name text NOT NULL CHECK (char_length(name) BETWEEN 1 AND 80),
    processing text NOT NULL DEFAULT 'hosted' CHECK (processing IN ('hosted', 'self_hosted')),
    ts_config regconfig NOT NULL DEFAULT 'simple',
    profile_id smallint NOT NULL REFERENCES knowledge.index_profiles,
    created_at timestamptz NOT NULL DEFAULT now(),
    deleted_at timestamptz
);
CREATE TABLE IF NOT EXISTS knowledge.grants (
    kb_id uuid NOT NULL REFERENCES knowledge.bases ON DELETE CASCADE,
    subject_type text NOT NULL CHECK (subject_type IN ('owner', 'role')),
    subject text NOT NULL CHECK (
        char_length(subject) BETWEEN 1 AND 200
        AND (subject_type <> 'owner' OR subject ~ '^[0-9a-f]{64}$')
    ),
    access text NOT NULL CHECK (access IN ('read', 'write', 'admin')),
    granted_by text NOT NULL CHECK (granted_by ~ '^[0-9a-f]{64}$'),
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (kb_id, subject_type, subject)
);
CREATE TABLE IF NOT EXISTS knowledge.documents (
    doc_id uuid PRIMARY KEY,
    kb_id uuid NOT NULL REFERENCES knowledge.bases ON DELETE CASCADE,
    uploaded_by text NOT NULL CHECK (uploaded_by ~ '^[0-9a-f]{64}$'),
    title text NOT NULL CHECK (char_length(title) BETWEEN 1 AND 300),
    mime_type text NOT NULL,
    size_bytes bigint NOT NULL CHECK (size_bytes >= 0),
    page_count integer,
    sha256 text NOT NULL CHECK (sha256 ~ '^[0-9a-f]{64}$'),
    blob_key text NOT NULL,
    source_type text NOT NULL DEFAULT 'upload' CHECK (source_type IN ('upload', 'github', 'web')),
    source_ref text,
    idempotency_key text CHECK (char_length(idempotency_key) BETWEEN 1 AND 200),
    status text NOT NULL CHECK (
        status IN ('queued', 'parsing', 'embedding', 'ready', 'failed', 'deleting')
    ),
    error_code text,
    parser_version text,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    deleted_at timestamptz,
    UNIQUE (doc_id, kb_id)
);
CREATE TABLE IF NOT EXISTS knowledge.chunks (
    chunk_id uuid PRIMARY KEY,
    doc_id uuid NOT NULL,
    kb_id uuid NOT NULL,
    ordinal integer NOT NULL CHECK (ordinal >= 0),
    text text NOT NULL,
    headings text[] NOT NULL DEFAULT '{}',
    page_start integer,
    page_end integer,
    bbox jsonb,
    token_count integer NOT NULL CHECK (token_count >= 0),
    ts_config regconfig NOT NULL,
    tsv tsvector GENERATED ALWAYS AS (to_tsvector(ts_config, text)) STORED,
    UNIQUE (chunk_id, kb_id),
    FOREIGN KEY (doc_id, kb_id) REFERENCES knowledge.documents (doc_id, kb_id)
        ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS knowledge.embeddings (
    chunk_id uuid NOT NULL,
    profile_id smallint NOT NULL REFERENCES knowledge.index_profiles,
    kb_id uuid NOT NULL,
    embedding halfvec NOT NULL,
    PRIMARY KEY (chunk_id, profile_id),
    FOREIGN KEY (chunk_id, kb_id) REFERENCES knowledge.chunks (chunk_id, kb_id)
        ON DELETE CASCADE
);
ALTER TABLE knowledge.chunks ENABLE ROW LEVEL SECURITY;
ALTER TABLE knowledge.embeddings ENABLE ROW LEVEL SECURITY;
CREATE POLICY kb_scope ON knowledge.chunks
    USING (kb_id = ANY (string_to_array(current_setting('neuron.kb_ids', true), ',')::uuid[]))
    WITH CHECK (
        kb_id = ANY (string_to_array(current_setting('neuron.kb_ids', true), ',')::uuid[])
    );
CREATE POLICY kb_scope ON knowledge.embeddings
    USING (kb_id = ANY (string_to_array(current_setting('neuron.kb_ids', true), ',')::uuid[]))
    WITH CHECK (
        kb_id = ANY (string_to_array(current_setting('neuron.kb_ids', true), ',')::uuid[])
    )
""",
        feature="knowledge",
    ),
    *(
        Migration(
            version=version,
            name=name,
            sql=f"CREATE {unique}INDEX CONCURRENTLY IF NOT EXISTS {index} ON knowledge.{on}",
            concurrent=True,
            index=f"knowledge.{index}",
            feature="knowledge",
        )
        for version, name, unique, index, on in (
            # One live copy of a file per KB; a deleted one can be uploaded again.
            (
                19,
                "documents_sha_idx",
                "UNIQUE ",
                "documents_live_sha_idx",
                "documents (kb_id, sha256) WHERE deleted_at IS NULL",
            ),
            # Upload retries with the same key return the first document.
            (
                20,
                "documents_idempotency_idx",
                "UNIQUE ",
                "documents_idempotency_idx",
                "documents (uploaded_by, idempotency_key) WHERE idempotency_key IS NOT NULL",
            ),
            (21, "chunks_tsv_idx", "", "chunks_tsv_idx", "chunks USING gin (tsv)"),
            (22, "chunks_kb_idx", "", "chunks_kb_idx", "chunks (kb_id)"),
            # Serves the cascade when a document is deleted.
            (23, "chunks_doc_idx", "", "chunks_doc_idx", "chunks (doc_id)"),
            (
                24,
                "embeddings_profile_kb_idx",
                "",
                "embeddings_profile_kb_idx",
                "embeddings (profile_id, kb_id)",
            ),
        )
    ),
    Migration(
        version=25,
        name="knowledge_job_queue",
        # The ingestion job queue (ADR 0014 K4; RAG-02.01): Procrastinate's own schema at
        # `PROCRASTINATE_VERSION`, created in the knowledge schema, so the worker needs no rights
        # in `public` and operators no second superuser step. Its new, empty tables are indexed
        # here without CONCURRENTLY. Each function gets a pinned search_path, so the API can call
        # the schema-qualified defer function inside its own transaction (RAG-03.02) and the
        # triggers find the queue tables whatever the caller's search_path. An upgrade adds
        # Procrastinate's migration files as new migrations (`test_migrations_policy.py`).
        sql="".join(
            ("SET LOCAL search_path = knowledge, public;\n", SchemaManager.get_schema(), _PIN_QUEUE)
        ),
        feature="knowledge",
    ),
)
# The schema migration 17 creates, and the extension it needs.
KNOWLEDGE_SCHEMA = "knowledge"
VECTOR_EXTENSION = "vector"
# What each runtime role may do on the knowledge tables (RAG-01.02). The API manages bases,
# grants and documents and only reads chunks and embeddings; the worker (RAG-02.01) reads a
# document's metadata, records its progress and writes its chunks and embeddings. Both are also
# bound by the `kb_scope` policy on chunks and embeddings.
_READ = frozenset({"SELECT"})
_KNOWLEDGE_PRIVILEGES: dict[str, dict[str, frozenset[str]]] = {
    "app": {
        "index_profiles": _READ,
        "bases": _DML,
        "grants": _DML,
        "documents": _DML,
        "chunks": _READ,
        "embeddings": _READ,
        # Queues jobs only: the defer function inserts a job (RETURNING its id) and its trigger
        # an event.
        "procrastinate_jobs": frozenset({"SELECT", "INSERT"}),
        "procrastinate_events": frozenset({"INSERT"}),
        "procrastinate_workers": frozenset(),
        "procrastinate_periodic_defers": frozenset(),
    },
    "worker": {
        "index_profiles": _READ,
        "bases": _READ,
        "grants": frozenset(),
        # Plus UPDATE on `_WORKER_DOCUMENT_COLUMNS` only: never `kb_id`, `blob_key` or the owner.
        "documents": _READ,
        "chunks": frozenset({"SELECT", "INSERT", "DELETE"}),
        "embeddings": frozenset({"SELECT", "INSERT", "DELETE"}),
        # Procrastinate's worker fetches, finishes, retries and sweeps jobs and registers itself.
        "procrastinate_jobs": _DML,
        "procrastinate_events": _DML,
        "procrastinate_workers": _DML,
        "procrastinate_periodic_defers": _DML,
    },
}
# The queue tables take their ids from a sequence (`<table>_id_seq`); a role that inserts into
# one gets USAGE on it.
_SERIAL_TABLES = frozenset(
    {
        "procrastinate_jobs",
        "procrastinate_events",
        "procrastinate_workers",
        "procrastinate_periodic_defers",
    }
)
_WORKER_DOCUMENT_COLUMNS = ("status", "error_code", "parser_version", "page_count", "updated_at")
# Recorded in `index_profiles.chunker` (the E02 decision on #408: Docling's hierarchical
# chunker with Neuron's own token split).
CHUNKER = "docling-hierarchical"
KNOWLEDGE_PROFILE_ID = 1


@dataclass(frozen=True)
class KnowledgeProfile:
    """The embedding model of index profile 1, seeded from settings by the first knowledge setup.

    A different model or dimension later needs a re-index into a new profile, so setup refuses
    one that differs from the stored row.
    """

    provider: str = "nvidia"
    model: str = "nvidia/nemotron-3.5-embed-1b"
    dimensions: int = 1024


async def run_setup(
    dsn: str,
    *,
    migrations: Sequence[Migration] | None = None,
    lock_timeout_ms: int | None = None,
    concurrent_lock_timeout_ms: int | None = None,
    lock_wait_seconds: float = LOCK_WAIT_SECONDS,
    app_role: str | None = None,
    require_app_role: bool = False,
    identity_hash_key: str | None = None,
    rotate_identity_key: bool = False,
    memory_store: bool = False,
    knowledge: bool = False,
    knowledge_profile: KnowledgeProfile | None = None,
    worker_role: str | None = None,
) -> list[int]:
    """Run LangGraph's `setup()`, then every unapplied migration. Returns the versions applied.

    One direct connection holds a session-level advisory lock for the whole run, so
    concurrent `setup` runs serialise and each migration is applied once. Raises on any
    failure; callers must not print the exception text, which can echo connection details.

    The connection's user is the migrator and owns what it creates. With `app_role`, the
    run also grants that role DML only (ADR 0008 decision 15), on every run, so tables a
    LangGraph upgrade adds are covered. A missing role, or the migrator itself (the
    single-role free-tier profile, decision 17), skips the grants with a log line, or raises
    `AppRoleError` with `require_app_role`. With `identity_hash_key`, the key's check value
    is stored the first time; a different stored value raises `IdentityKeyMismatch` unless
    `rotate_identity_key` is set. With `memory_store`, LangGraph's store tables are created too
    (per-user memory, ADR 0009); without it a database that never enabled memory gets none.
    With `knowledge`, the `knowledge` migrations run too, after checking that the `vector`
    extension and schema exist or this role can create them (`StartupCheckError` with a
    stable code); index profile 1 is seeded from `knowledge_profile` (required) and its HNSW index
    built.
    `worker_role`, when it exists, gets the worker's knowledge-table rights (skipped with a log
    line otherwise: the worker arrives in RAG-02.01).
    """
    if knowledge and knowledge_profile is None:
        # Seeded once and fixed afterwards, so it must come from settings, never a default here.
        raise ValueError("knowledge setup needs the knowledge_profile from settings")
    timeout_ms = DEFAULT_LOCK_TIMEOUT_MS if lock_timeout_ms is None else lock_timeout_ms
    concurrent_ms = (
        CONCURRENT_LOCK_TIMEOUT_MS
        if concurrent_lock_timeout_ms is None
        else concurrent_lock_timeout_ms
    )
    conn = await psycopg.AsyncConnection.connect(
        dsn, autocommit=True, row_factory=dict_row, prepare_threshold=None
    )
    try:
        await _acquire_lock(conn, lock_wait_seconds)
        await _set_lock_timeout(conn, timeout_ms)
        target = await _resolve_app_role(
            conn, app_role, require_app_role, worker_role if knowledge else None
        )
        await AsyncPostgresSaver(conn).setup()
        if memory_store:
            await AsyncPostgresStore(conn).setup()
        await conn.execute(_CREATE_TABLE_SQL)
        features = {"knowledge"} if knowledge else set()
        if knowledge:
            await _check_knowledge_prerequisites(conn)
            # Before the tables go in, too: an untrusted schema would otherwise fail them first.
            await _verify_knowledge_schema(conn, _runtime_roles(target), missing_ok=True)
            if target is None:
                logger.warning(
                    "knowledge_rls_not_enforced",
                    reason="no separate app role: the runtime role owns the knowledge tables",
                )
        # Tables made so far had no default privileges (first run) or are tightened here.
        # Later tables are tightened in the transaction that creates them.
        after_ddl = (lambda c: _grant(c, target)) if target is not None else None
        if after_ddl is not None:
            await after_ddl(conn)
        applied = await _apply(
            conn,
            MIGRATIONS if migrations is None else migrations,
            timeout_ms,
            concurrent_ms,
            after_ddl,
            features,
        )
        if knowledge and knowledge_profile is not None:
            await _verify_knowledge_schema(conn, _runtime_roles(target))
            await _verify_row_security(conn)
            await _seed_profile(conn, knowledge_profile, timeout_ms, concurrent_ms)
        if identity_hash_key:
            await _check_identity(conn, identity_hash_key, rotate_identity_key)
        else:
            logger.info("identity_key_check_skipped", reason="no key configured")
        if target is not None:
            await _verify_role(conn, target, required=require_app_role)
            if await _verify_grants(conn, target, required=require_app_role):
                logger.info("app_role_grants_applied", app_role=target.name)
        return applied
    finally:
        await conn.close()  # also releases the session advisory lock


@dataclass(frozen=True)
class _AppRole:
    name: str
    migrator: str
    schema: str
    worker: str | None = None


async def _resolve_app_role(
    conn: psycopg.AsyncConnection[dict[str, object]],
    app_role: str | None,
    required: bool,
    worker_role: str | None = None,
) -> _AppRole | None:
    """The role to grant to, or None to skip (logged) when there is none or it is the migrator."""
    if app_role is None:
        logger.info("app_role_grants_skipped", reason="no app role configured")
        return None
    cursor = await conn.execute(
        "SELECT current_user::text AS migrator, current_schema()::text AS schema,"
        " EXISTS (SELECT 1 FROM pg_roles WHERE rolname = %s) AS found",
        (app_role,),
    )
    row = await cursor.fetchone()
    assert row is not None  # nosec B101
    if row["migrator"] == app_role:
        reason = "the app role is the migration role (single-role profile, staging only)"
    elif not row["found"]:
        reason = "the app role does not exist"
    else:
        return _AppRole(
            name=app_role,
            migrator=str(row["migrator"]),
            schema=str(row["schema"]),
            worker=await _resolve_worker_role(conn, worker_role, str(row["migrator"]), app_role),
        )
    if required:
        raise AppRoleError(f"cannot grant to the app role: {reason}")
    logger.warning("app_role_grants_skipped", reason=reason)
    return None


async def _resolve_worker_role(
    conn: psycopg.AsyncConnection[dict[str, object]],
    worker_role: str | None,
    migrator: str,
    app_role: str,
) -> str | None:
    """The worker role to grant knowledge rights to, or None (logged) when it does not exist."""
    if worker_role is None:
        return None
    if worker_role in {migrator, app_role}:
        raise AppRoleError("the worker role must differ from the app and migration roles")
    cursor = await conn.execute(
        "SELECT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = %(worker)s) AS found,"
        " EXISTS (SELECT 1 FROM pg_roles w, pg_roles a WHERE w.rolname = %(worker)s"
        " AND a.rolname = %(app)s AND (pg_has_role(w.oid, a.oid, 'MEMBER')"
        " OR pg_has_role(a.oid, w.oid, 'MEMBER'))) AS shared",
        {"worker": worker_role, "app": app_role},
    )
    row = await cursor.fetchone()
    if row is not None and row["shared"]:
        # Membership would hand the worker the app role's rights in `public`, or the reverse.
        raise AppRoleError("the worker role must not be a member of the app role, or the reverse")
    if row is not None and row["found"]:
        return worker_role
    logger.warning("worker_role_grants_skipped", reason="the worker role does not exist")
    return None


def knowledge_grant_statements(
    roles: dict[str, str], present: Collection[str] | None = None
) -> list[sql.Composed]:
    """Exact rights on the knowledge tables for each runtime role (`{"app": name, ...}`).

    REVOKE ALL first, so a right granted by hand is taken back on the next setup.
    """
    schema = sql.Identifier(KNOWLEDGE_SCHEMA)
    statements: list[sql.Composed] = []
    for kind, name in roles.items():
        role = sql.Identifier(name)
        statements.append(sql.SQL("GRANT USAGE ON SCHEMA {} TO {}").format(schema, role))
        for table, privileges in _KNOWLEDGE_PRIVILEGES[kind].items():
            if present is None or table in present:
                statements.extend(_table_grants(kind, table, privileges, role))
    return statements


def _table_grants(
    kind: str, table: str, privileges: frozenset[str], role: sql.Identifier
) -> list[sql.Composed]:
    """One knowledge table's grants for one role, its id sequence's and its column grants."""
    target = sql.Identifier(KNOWLEDGE_SCHEMA, table)
    statements = [sql.SQL("REVOKE ALL ON {} FROM {}").format(target, role)]
    if privileges:
        statements.append(
            sql.SQL("GRANT {} ON {} TO {}").format(
                sql.SQL(", ").join(sql.SQL(p) for p in sorted(privileges)), target, role
            )
        )
    if table in _SERIAL_TABLES:
        sequence = sql.Identifier(KNOWLEDGE_SCHEMA, f"{table}_id_seq")
        statements.append(sql.SQL("REVOKE ALL ON SEQUENCE {} FROM {}").format(sequence, role))
        if "INSERT" in privileges:
            statements.append(sql.SQL("GRANT USAGE ON SEQUENCE {} TO {}").format(sequence, role))
    if kind == "worker" and table == "documents":
        statements.append(
            sql.SQL("GRANT UPDATE ({}) ON {} TO {}").format(
                sql.SQL(", ").join(map(sql.Identifier, _WORKER_DOCUMENT_COLUMNS)), target, role
            )
        )
    return statements


def default_privilege_statements(migrator: str, schema: str, app: str) -> list[sql.Composed]:
    """Default privileges: tables and sequences the migrator creates later reach the app role."""
    target = {
        "migrator": sql.Identifier(migrator),
        "schema": sql.Identifier(schema),
        "app": sql.Identifier(app),
    }
    return [
        sql.SQL(statement).format(**target)
        for statement in (
            "GRANT USAGE ON SCHEMA {schema} TO {app}",
            "ALTER DEFAULT PRIVILEGES FOR ROLE {migrator} IN SCHEMA {schema}"
            " GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO {app}",
            "ALTER DEFAULT PRIVILEGES FOR ROLE {migrator} IN SCHEMA {schema}"
            " GRANT USAGE, SELECT ON SEQUENCES TO {app}",
        )
    ]


def table_grant_statements(
    schema: str, app: str, present: Collection[str] | None = None
) -> list[sql.Composed]:
    """Per-table grants, DML only: no CREATE, DROP, TRUNCATE, REFERENCES, TRIGGER or ownership.

    Idempotent and expand-only (the lint in `tests/unit/test_migrations_policy.py` runs on
    these statements too). They also take back what the default privileges gave the
    bookkeeping tables. `present` limits them to tables (and the identity function) that
    exist (None: all of them).
    """

    def names(*tables: str) -> sql.Composed | None:
        wanted = [t for t in tables if present is None or t in present]
        return sql.SQL(", ").join(sql.Identifier(schema, t) for t in wanted) if wanted else None

    role = sql.Identifier(app)
    dml = names("checkpoints", "checkpoint_blobs", "checkpoint_writes")
    leases = names("neuron_run_leases", "neuron_token_settlements")
    ledger = names("neuron_token_ledger", "neuron_rate_buckets", *USER_CONTENT_TABLES)
    memory = names(STORE_TABLE)
    bookkeeping = names(
        "neuron_migrations", "checkpoint_migrations", "neuron_meta", "store_migrations"
    )
    statements: list[sql.Composed] = []
    if present is None or _IDENTITY_FUNCTION in present:
        statements.append(
            sql.SQL("GRANT EXECUTE ON FUNCTION {}(text) TO {}").format(
                sql.Identifier(schema, _IDENTITY_FUNCTION), role
            )
        )
    if dml is not None:
        statements.append(
            sql.SQL("GRANT SELECT, INSERT, UPDATE, DELETE ON {} TO {}").format(dml, role)
        )
    if memory is not None:
        statements.append(
            sql.SQL("GRANT SELECT, INSERT, UPDATE, DELETE ON {} TO {}").format(memory, role)
        )
    if leases is not None:
        statements.append(sql.SQL("GRANT SELECT, INSERT, DELETE ON {} TO {}").format(leases, role))
        statements.append(sql.SQL("REVOKE UPDATE ON {} FROM {}").format(leases, role))
    if ledger is not None:
        statements.append(
            sql.SQL("GRANT SELECT, INSERT, UPDATE, DELETE ON {} TO {}").format(ledger, role)
        )
    if bookkeeping is not None:
        statements.append(sql.SQL("REVOKE ALL ON {} FROM {}").format(bookkeeping, role))
    return statements


async def _grant(conn: psycopg.AsyncConnection[dict[str, object]], role: _AppRole) -> None:
    """Default privileges and the table grants for the tables that exist, in one transaction,
    so a crash cannot leave DML granted without the REVOKEs that follow it."""
    async with conn.transaction():
        cursor = await conn.execute(
            "SELECT tablename::text AS name FROM pg_tables WHERE schemaname = %s", (role.schema,)
        )
        present = {str(row["name"]) for row in await cursor.fetchall()}
        if await _identity_function_exists(conn, role.schema):
            present.add(_IDENTITY_FUNCTION)
        cursor = await conn.execute(
            "SELECT tablename::text AS name FROM pg_tables WHERE schemaname = %s",
            (KNOWLEDGE_SCHEMA,),
        )
        knowledge = {str(row["name"]) for row in await cursor.fetchall()}
        runtime = {"app": role.name} | ({"worker": role.worker} if role.worker else {})
        statements = [
            *default_privilege_statements(role.migrator, role.schema, role.name),
            *table_grant_statements(role.schema, role.name, present),
            *(knowledge_grant_statements(runtime, knowledge) if knowledge else []),
        ]
        for statement in statements:
            await conn.execute(statement)


async def _identity_function_exists(
    conn: psycopg.AsyncConnection[dict[str, object]], schema: str
) -> bool:
    cursor = await conn.execute(
        "SELECT to_regprocedure(format('%%I.%%I(text)', %s::text, %s::text)) IS NOT NULL AS found",
        (schema, _IDENTITY_FUNCTION),
    )
    row = await cursor.fetchone()
    return bool(row and row["found"])


async def _verify_grants(
    conn: psycopg.AsyncConnection[dict[str, object]], role: _AppRole, *, required: bool
) -> bool:
    """Check the privilege matrix with `has_table_privilege`: a GRANT by a role that does not
    own the table only warns, so success of the statement proves nothing."""
    checks = [(role.name, role.schema, _APP_PRIVILEGES)]
    checks.append((role.name, KNOWLEDGE_SCHEMA, _KNOWLEDGE_PRIVILEGES["app"]))
    if role.worker is not None:
        checks.append((role.worker, KNOWLEDGE_SCHEMA, _KNOWLEDGE_PRIVILEGES["worker"]))
        # The worker parses untrusted files: it must not reach threads, checkpoints or memory.
        checks.append((role.worker, role.schema, dict.fromkeys(_APP_PRIVILEGES, frozenset())))
    wrong: list[str] = []
    for grantee, schema, matrix in checks:
        for table, expected in matrix.items():
            granted = await _table_privileges(conn, grantee, schema, table)
            if granted is not None and granted != expected:
                wrong.append(table if schema == role.schema else f"{schema}.{table}")
    if await _identity_function_exists(conn, role.schema):
        cursor = await conn.execute(
            "SELECT has_function_privilege(%s, to_regprocedure(format('%%I.%%I(text)',"
            " %s::text, %s::text)), 'EXECUTE') AS ok",
            (role.name, role.schema, _IDENTITY_FUNCTION),
        )
        executable = await cursor.fetchone()
        if not (executable and executable["ok"]):
            wrong.append(_IDENTITY_FUNCTION)
        # Hardened as migration 12 made it: SECURITY DEFINER, pinned search_path, no PUBLIC.
        hardened = await conn.execute(
            "SELECT p.prosecdef"
            " AND coalesce(p.proconfig, '{}') @> ARRAY['search_path=pg_catalog, pg_temp']"
            " AND NOT EXISTS (SELECT 1"
            " FROM aclexplode(coalesce(p.proacl, acldefault('f', p.proowner))) a"
            " WHERE a.grantee = 0) AS ok"
            " FROM pg_proc p"
            " WHERE p.oid = to_regprocedure(format('%%I.%%I(text)', %s::text, %s::text))",
            (role.schema, _IDENTITY_FUNCTION),
        )
        row = await hardened.fetchone()
        if not (row and row["ok"]) and _IDENTITY_FUNCTION not in wrong:
            wrong.append(_IDENTITY_FUNCTION)
    if wrong:
        logger.warning("app_role_grants_mismatch", tables=wrong)
        if required:
            raise AppRoleError("the app role's table privileges are not what setup grants")
        return False
    return True


async def _table_privileges(
    conn: psycopg.AsyncConnection[dict[str, object]], role: str, schema: str, table: str
) -> set[str] | None:
    """What `role` holds on `schema.table` of the checked privileges; None when it is absent."""
    cursor = await conn.execute(
        "SELECT p AS priv FROM unnest(%(privs)s::text[]) AS p"
        " WHERE to_regclass(format('%%I.%%I', %(schema)s::text, %(table)s::text)) IS NOT NULL"
        " AND has_table_privilege(%(role)s, format('%%I.%%I', %(schema)s::text,"
        " %(table)s::text), p)",
        {"privs": list(_CHECKED_PRIVILEGES), "schema": schema, "table": table, "role": role},
    )
    granted = {str(row["priv"]) for row in await cursor.fetchall()}
    exists = await conn.execute(
        "SELECT to_regclass(format('%%I.%%I', %(schema)s::text, %(table)s::text)) IS NOT NULL"
        " AS found",
        {"schema": schema, "table": table},
    )
    found = await exists.fetchone()
    return granted if found and found["found"] else None


async def _verify_role(
    conn: psycopg.AsyncConnection[dict[str, object]], role: _AppRole, *, required: bool
) -> None:
    """After granting in production: the app role must not be able to undo the split."""
    if not required:
        return
    problems = await role_problems(conn, role.name, migrator=role.migrator)
    if problems:
        raise AppRoleError("the app role is too privileged: " + "; ".join(problems))
    if role.worker is not None:
        problems = await role_problems(conn, role.worker, migrator=role.migrator)
        if problems:
            raise AppRoleError("the worker role is too privileged: " + "; ".join(problems))


async def _check_identity(
    conn: psycopg.AsyncConnection[dict[str, object]], identity_hash_key: str, rotate: bool
) -> None:
    """Store the key's check value once; refuse a different one unless rotating."""
    value = identity_check_value(identity_hash_key)
    async with conn.transaction():
        cursor = await conn.execute(
            "INSERT INTO neuron_meta (key, value) VALUES (%s, %s)"
            " ON CONFLICT (key) DO NOTHING RETURNING value",
            (_IDENTITY_META_KEY, value),
        )
        if await cursor.fetchone() is not None:
            logger.info("identity_key_check_written")
            audit(
                "identity_key_check_written",
                outcome="allowed",
                action="identity_key:record",
                resource_type="identity_key",
            )
            return
        cursor = await conn.execute(
            "SELECT value FROM neuron_meta WHERE key = %s", (_IDENTITY_META_KEY,)
        )
        row = await cursor.fetchone()
        stored = str(row["value"]) if row else ""
        if hmac.compare_digest(stored, value):
            logger.info("identity_key_check_verified")
            return
        if not rotate:
            raise IdentityKeyMismatch(
                "APP_IDENTITY_HASH_KEY differs from the key this database was set up with;"
                " rotating it orphans existing threads (OPERATIONS.md), so pass"
                " --rotate-identity-key to replace the stored check value"
            )
        await conn.execute(
            "UPDATE neuron_meta SET value = %s, updated_at = now() WHERE key = %s",
            (value, _IDENTITY_META_KEY),
        )
        logger.warning("identity_key_check_rotated")
        audit(
            "identity_key_check_rotated",
            outcome="allowed",
            action="identity_key:rotate",
            resource_type="identity_key",
        )


async def _check_knowledge_prerequisites(
    conn: psycopg.AsyncConnection[dict[str, object]],
) -> None:
    """Refuse knowledge setup, with a stable code, when migration 17 would fail on privileges."""
    cursor = await conn.execute(
        "SELECT EXISTS (SELECT 1 FROM pg_extension WHERE extname = %(ext)s) AS installed,"
        " EXISTS (SELECT 1 FROM pg_available_extensions WHERE name = %(ext)s) AS available,"
        " (SELECT rolsuper FROM pg_roles WHERE rolname = current_user) AS superuser,"
        " to_regnamespace(%(schema)s) IS NOT NULL AS schema,"
        " has_database_privilege(current_database(), 'CREATE') AS can_create_schema",
        {"ext": VECTOR_EXTENSION, "schema": KNOWLEDGE_SCHEMA},
    )
    row = await cursor.fetchone()
    assert row is not None  # nosec B101
    if not row["installed"] and not row["available"]:
        raise StartupCheckError(
            "the vector extension is not available on this server; use a Postgres with "
            "pgvector (the pinned pgvector/pgvector:pg16 image)",
            VECTOR_EXTENSION_MISSING,
        )
    if not row["installed"] and not row["superuser"]:
        raise StartupCheckError(
            "the vector extension is not installed and the migration role cannot create it; "
            "run CREATE EXTENSION vector as a superuser first",
            VECTOR_EXTENSION_MISSING,
        )
    if not row["schema"] and not row["can_create_schema"]:
        raise StartupCheckError(
            "the knowledge schema does not exist and the migration role cannot create it; "
            "run CREATE SCHEMA knowledge AUTHORIZATION <migration role> as a superuser first",
            KNOWLEDGE_SCHEMA_MISSING,
        )


def _runtime_roles(target: _AppRole | None) -> list[str]:
    if target is None:
        return []
    return [target.name] + ([target.worker] if target.worker else [])


async def _verify_knowledge_schema(
    conn: psycopg.AsyncConnection[dict[str, object]],
    runtime_roles: Sequence[str],
    *,
    missing_ok: bool = False,
) -> None:
    """On every knowledge setup: the schema is this role's, and nobody else may create in it.

    A schema created earlier by another role is skipped by migration 17, so its owner or a CREATE
    grantee could plant objects beside the knowledge tables RAG-01.02 adds.
    """
    cursor = await conn.execute(
        "SELECT n.nspowner = (SELECT oid FROM pg_roles WHERE rolname = current_user) AS owned,"
        " EXISTS (SELECT 1 FROM aclexplode(coalesce(n.nspacl, acldefault('n', n.nspowner))) a"
        " WHERE a.grantee = 0 AND a.privilege_type = 'CREATE') AS public_create,"
        " EXISTS (SELECT 1 FROM pg_roles r WHERE r.rolname = ANY(%(roles)s::text[])"
        " AND has_schema_privilege(r.oid, n.oid, 'CREATE')) AS app_create"
        " FROM pg_namespace n WHERE n.nspname = %(schema)s",
        {"schema": KNOWLEDGE_SCHEMA, "roles": list(runtime_roles)},
    )
    row = await cursor.fetchone()
    if row is None and missing_ok:
        return
    if row is None or not row["owned"] or row["public_create"] or row["app_create"]:
        raise StartupCheckError(
            "the knowledge schema must be owned by the migration role, and no other role may "
            "create objects in it; run ALTER SCHEMA knowledge OWNER TO <migration role> and "
            "REVOKE CREATE ON SCHEMA knowledge FROM PUBLIC as a superuser",
            KNOWLEDGE_SCHEMA_UNTRUSTED,
        )


_RLS_TABLES = ("chunks", "embeddings")
# Migration 18's `kb_scope` expression as PostgreSQL 16 deparses it (`pg_get_expr`); a Postgres
# major upgrade that deparses it differently fails the integration tests, not silently here.
_KB_SCOPE_EXPR = (
    "(kb_id = ANY ((string_to_array(current_setting('neuron.kb_ids'::text, true),"
    " ','::text))::uuid[]))"
)


async def _verify_row_security(conn: psycopg.AsyncConnection[dict[str, object]]) -> None:
    """RLS is on, the migrator owns the table, and its only permissive policy is `kb_scope`
    with migration 18's USING and WITH CHECK expressions.

    A table made by hand before migration 18 (skipped by `IF NOT EXISTS`), RLS disabled later,
    `kb_scope` rewritten, or another permissive policy (ORed with `kb_scope`) would otherwise let
    every knowledge base be read.
    """
    cursor = await conn.execute(
        "SELECT count(*) AS ok FROM pg_class c"
        " WHERE c.relnamespace = to_regnamespace(%(schema)s) AND c.relname = ANY(%(tables)s)"
        " AND c.relrowsecurity AND c.relowner = (SELECT oid FROM pg_roles"
        " WHERE rolname = current_user)"
        " AND (SELECT count(*) FROM pg_policy p WHERE p.polrelid = c.oid AND p.polpermissive) = 1"
        " AND EXISTS (SELECT 1 FROM pg_policy p WHERE p.polrelid = c.oid"
        " AND p.polname = 'kb_scope' AND p.polcmd = '*' AND p.polpermissive"
        " AND pg_get_expr(p.polqual, p.polrelid) = %(expr)s"
        " AND pg_get_expr(p.polwithcheck, p.polrelid) = %(expr)s)",
        {"schema": KNOWLEDGE_SCHEMA, "tables": list(_RLS_TABLES), "expr": _KB_SCOPE_EXPR},
    )
    row = await cursor.fetchone()
    if row is None or row["ok"] != len(_RLS_TABLES):
        raise StartupCheckError(
            "row-level security on knowledge.chunks and knowledge.embeddings is not as setup "
            "made it (enabled, owned by the migration role, kb_scope its only permissive policy)",
            KNOWLEDGE_SCHEMA_UNTRUSTED,
        )


async def _seed_profile(
    conn: psycopg.AsyncConnection[dict[str, object]],
    profile: KnowledgeProfile,
    timeout_ms: int,
    concurrent_ms: int,
) -> None:
    """Record index profile 1 once, refuse a different one, and build its HNSW index.

    The index casts to the profile's dimension (`halfvec` has no typmod in the table), so it is
    built here rather than in a migration. Concurrently: a rebuild after a failed build must not
    block writers.
    """
    cursor = await conn.execute(
        "INSERT INTO knowledge.index_profiles"
        " (profile_id, provider, model, dimensions, chunker, status)"
        " VALUES (%(id)s, %(provider)s, %(model)s, %(dimensions)s, %(chunker)s, 'active')"
        " ON CONFLICT (profile_id) DO NOTHING",
        {
            "id": KNOWLEDGE_PROFILE_ID,
            "provider": profile.provider,
            "model": profile.model,
            "dimensions": profile.dimensions,
            "chunker": CHUNKER,
        },
    )
    if cursor.rowcount:
        logger.info("knowledge_profile_seeded", profile_id=KNOWLEDGE_PROFILE_ID)
    cursor = await conn.execute(
        "SELECT provider, model, dimensions FROM knowledge.index_profiles WHERE profile_id = %s",
        (KNOWLEDGE_PROFILE_ID,),
    )
    row = await cursor.fetchone()
    assert row is not None  # nosec B101
    stored = KnowledgeProfile(str(row["provider"]), str(row["model"]), int(str(row["dimensions"])))
    if stored != profile:
        raise StartupCheckError(
            "the embedding provider, model or dimensions differ from index profile 1, which "
            "this database was set up with; changing them needs a re-index",
            KNOWLEDGE_PROFILE_MISMATCH,
        )
    index = f"embeddings_p{KNOWLEDGE_PROFILE_ID}_hnsw"
    await _set_lock_timeout(conn, concurrent_ms)
    try:
        if await _index_is_invalid(conn, f"{KNOWLEDGE_SCHEMA}.{index}"):
            logger.warning("invalid_index_rebuilt", index=index)
            await conn.execute(
                sql.SQL("DROP INDEX CONCURRENTLY IF EXISTS {}").format(
                    sql.Identifier(KNOWLEDGE_SCHEMA, index)
                )
            )
        await conn.execute(
            sql.SQL(
                "CREATE INDEX CONCURRENTLY IF NOT EXISTS {index} ON {table}"
                " USING hnsw ((embedding::halfvec({dims})) halfvec_cosine_ops)"
                " WHERE profile_id = {id}"
            ).format(
                index=sql.Identifier(index),
                table=sql.Identifier(KNOWLEDGE_SCHEMA, "embeddings"),
                dims=sql.Literal(stored.dimensions),
                id=sql.Literal(KNOWLEDGE_PROFILE_ID),
            )
        )
    finally:
        await _set_lock_timeout(conn, timeout_ms)


async def _acquire_lock(conn: psycopg.AsyncConnection[dict[str, object]], wait: float) -> None:
    deadline = time.monotonic() + wait
    while True:
        cursor = await conn.execute("SELECT pg_try_advisory_lock(%s) AS ok", (_ADVISORY_LOCK_KEY,))
        row = await cursor.fetchone()
        if row is not None and row["ok"]:
            return
        if time.monotonic() >= deadline:
            raise LockWaitTimeout("another setup held the migration lock for too long")
        await asyncio.sleep(0.2)


async def _set_lock_timeout(conn: psycopg.AsyncConnection[dict[str, object]], ms: int) -> None:
    await conn.execute("SELECT set_config('lock_timeout', %s, false)", (f"{ms}ms",))


async def _apply(
    conn: psycopg.AsyncConnection[dict[str, object]],
    migrations: Sequence[Migration],
    timeout_ms: int,
    concurrent_ms: int,
    after_ddl: Callable[[psycopg.AsyncConnection[dict[str, object]]], Awaitable[None]]
    | None = None,
    features: Collection[str] = (),
) -> list[int]:
    cursor = await conn.execute("SELECT version FROM neuron_migrations")
    done = {row["version"] for row in await cursor.fetchall()}
    applied: list[int] = []
    for migration in migrations:
        if migration.feature is not None and migration.feature not in features:
            continue
        recorded = migration.version in done
        if migration.index and await _index_is_invalid(conn, migration.index):
            # `IF NOT EXISTS` would skip a leftover from a failed concurrent build.
            logger.warning("invalid_index_rebuilt", index=migration.index)
            # DROP INDEX CONCURRENTLY waits on older transactions too.
            await _set_lock_timeout(conn, concurrent_ms)
            try:
                await conn.execute(
                    sql.SQL("DROP INDEX CONCURRENTLY IF EXISTS {}").format(
                        sql.Identifier(*migration.index.split("."))
                    )
                )
            finally:
                await _set_lock_timeout(conn, timeout_ms)
            recorded = False
        if recorded:
            continue
        if migration.concurrent:
            await _set_lock_timeout(conn, concurrent_ms)
            try:
                await conn.execute(migration.sql)
            finally:
                await _set_lock_timeout(conn, timeout_ms)
            await _record(conn, migration)
        else:
            async with conn.transaction():
                await conn.execute(migration.sql)
                await _record(conn, migration)
                if after_ddl is not None:
                    # Same transaction: a table the migration made is tightened or not made.
                    await after_ddl(conn)
        applied.append(migration.version)
        logger.info("migration_applied", version=migration.version, name=migration.name)
    return applied


async def _index_is_invalid(conn: psycopg.AsyncConnection[dict[str, object]], name: str) -> bool:
    cursor = await conn.execute(
        "SELECT NOT i.indisvalid AS invalid FROM pg_index i WHERE i.indexrelid = to_regclass(%s)",
        (name,),
    )
    row = await cursor.fetchone()
    return bool(row and row["invalid"])


async def _record(conn: psycopg.AsyncConnection[dict[str, object]], migration: Migration) -> None:
    await conn.execute(
        "INSERT INTO neuron_migrations (version, name) VALUES (%s, %s) "
        "ON CONFLICT (version) DO NOTHING",
        (migration.version, migration.name),
    )
