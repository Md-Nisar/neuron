# How-To: Set Up Persistence and PostgreSQL Storage

> **Document ID:** DOC-HOW-002  
> **Diátaxis Mode:** How-To Guide (Task-Oriented)  
> **Standard Alignment:** Structured in alignment with ISO/IEC/IEEE 26514:2022 §7.4 (Procedural Task Information) and Diátaxis (How-To Guide)  
> **Audience:** Database Administrators, SREs, Backend Developers  
> **Code Traceability:** `src/neuron_agent/persistence/`, `docs/decisions/0002-persistence-and-memory.md`, `docs/decisions/0008-production-deployment.md`

---

## 1. Overview and Architecture

Neuron Agent uses PostgreSQL 16+ (with `pgvector` 0.7+) as its durable persistence engine across all production and staging deployments (`APP_CHECKPOINTER=postgres`). 

PostgreSQL stores:
1. **LangGraph Checkpoints:** Multi-turn conversation message history and interrupt states (`checkpoints`, `checkpoint_blobs`, `checkpoint_writes`).
2. **Conversation Metadata:** User-facing thread titles (`neuron_thread_meta`) and run feedback ratings (`neuron_feedback`).
3. **Multi-Instance Guards:** Distributed run leases (`neuron_run_leases`), shared token budget ledger (`neuron_token_ledger`, `neuron_token_settlements`), and unlogged rate buckets (`neuron_rate_buckets`).
4. **Knowledge Engine (RAG):** Isolated `knowledge` schema containing knowledge bases, documents, parsed chunks, embeddings, and the Procrastinate background job queue.

---

## 2. Least-Privilege Database Roles

In production, never configure the API service or background worker with database owner or superuser credentials. Follow the three-role security architecture:

```mermaid
graph TD
    subgraph Roles ["PostgreSQL Database Roles"]
        Migrator["neuron_migrator (Owner / DDL)"]
        App["neuron_app (API Runtime DML)"]
        Worker["neuron_worker (Ingestion Worker DML)"]
    end

    subgraph Tables ["Database Objects"]
        Migrations["neuron_migrations (DDL only)"]
        Checkpoints["checkpoints, checkpoint_blobs (DML)"]
        Guards["neuron_run_leases, token_ledger (DML)"]
        KnowledgeSchema["knowledge.* (DML + RLS)"]
        Queue["knowledge.procrastinate_* (Queue DML)"]
    end

    Migrator -->|Full DDL Ownership| Migrations
    Migrator -->|Creates & Grants| Checkpoints
    Migrator -->|Creates & Grants| KnowledgeSchema
    App -->|SELECT, INSERT, UPDATE, DELETE| Checkpoints
    App -->|SELECT, INSERT, DELETE| Guards
    App -->|SELECT, INSERT on bases, documents| KnowledgeSchema
    Worker -->|DML on chunks, embeddings| KnowledgeSchema
    Worker -->|Worker DML on queue| Queue
```

### Role Provisioning Script (Run Once by Superuser)
Execute the following SQL against your PostgreSQL cluster:

```sql
-- 1. Create dedicated database
CREATE DATABASE neuron_prod;
\connect neuron_prod

-- 2. Install required pgvector extension (schema public)
CREATE EXTENSION IF NOT EXISTS vector;

-- 3. Create Migrator Role (runs migrations during deployment)
CREATE ROLE neuron_migrator WITH LOGIN PASSWORD 'strong-migrator-password';
GRANT ALL ON DATABASE neuron_prod TO neuron_migrator;
GRANT ALL ON SCHEMA public TO neuron_migrator;

-- 4. Create Runtime Application Role (used by neuron-api)
CREATE ROLE neuron_app WITH LOGIN PASSWORD 'strong-app-password';
GRANT CONNECT ON DATABASE neuron_prod TO neuron_app;
GRANT USAGE ON SCHEMA public TO neuron_app;

-- 5. Create Worker Role (used by neuron-worker)
CREATE ROLE neuron_worker WITH LOGIN PASSWORD 'strong-worker-password';
GRANT CONNECT ON DATABASE neuron_prod TO neuron_worker;
```

---

## 3. Environment Configuration

Configure connection strings and pool sizing in your service environment:

```bash
# Set checkpointer to postgres
APP_CHECKPOINTER=postgres

# Runtime application DSN (neuron_app role, pooled)
APP_POSTGRES_DSN=postgresql://neuron_app:strong-app-password@db.example.com:5432/neuron_prod?sslmode=verify-full&sslrootcert=/etc/ssl/certs/ca.crt

# Migration DSN (neuron_migrator role, direct/non-pooled)
APP_POSTGRES_MIGRATION_DSN=postgresql://neuron_migrator:strong-migrator-password@db.example.com:5432/neuron_prod?sslmode=verify-full&sslrootcert=/etc/ssl/certs/ca.crt

# Worker DSN (neuron_worker role, dedicated pool)
APP_POSTGRES_WORKER_DSN=postgresql://neuron_worker:strong-worker-password@db.example.com:5432/neuron_prod?sslmode=verify-full&sslrootcert=/etc/ssl/certs/ca.crt

# Named roles (used by migration grant statements)
APP_POSTGRES_APP_ROLE=neuron_app
APP_POSTGRES_WORKER_ROLE=neuron_worker

# Connection Pool Tuning
APP_POSTGRES_POOL_MAX_SIZE=20
APP_POSTGRES_POOL_TIMEOUT_SECONDS=10
```

> [!IMPORTANT]
> **Production Database Invariants:**
> 1. In `APP_ENV=production`, `APP_POSTGRES_DSN` and `APP_POSTGRES_MIGRATION_DSN` **must use different database users** (e.g., `neuron_app` vs `neuron_migrator`). Reusing the same role fails startup validation (`APP_POSTGRES_DSN and APP_POSTGRES_MIGRATION_DSN must use different database users in production`).
> 2. `APP_POSTGRES_MIGRATION_DSN` is strictly required in staging and production.
> 3. Production connection strings must specify an encrypted SSL mode (`sslmode=require`, `sslmode=verify-ca`, or `sslmode=verify-full`). Plaintext connections are rejected at startup.

---

## 4. Running Database Migrations

Neuron manages database schema evolution through an ordered sequence of 27 forward-only migrations recorded in `neuron_migrations`.

### Execute Migrations via Makefile
```bash
make db-setup
```

### Direct CLI Execution
```bash
uv run python -m neuron_agent.persistence.cli setup
```

### Migration Execution Behavior
1. Acquires a session-level advisory lock (`0x6E6575726F6E`) on the non-pooled migration connection to prevent race conditions during multi-instance rolling deploys.
2. Initializes LangGraph checkpoint tables via `AsyncPostgresSaver.setup()`.
3. Sequentially applies unapplied migrations (from version 1 to 27) inside explicit transactions.
4. Creates indexes concurrently using `CONCURRENT_LOCK_TIMEOUT_MS` (10 minutes) to avoid locking production traffic.
5. Issues explicit `GRANT` statements configuring least-privilege DML rights for `neuron_app` and `neuron_worker`.
6. Releases advisory lock.

---

## 5. Thread Retention and Conversation Pruning

Neuron enforces a strict data retention policy governed by `APP_THREAD_RETENTION_DAYS` (default 30 days).

### Automated Pruning Command
Run this command periodically via a Kubernetes CronJob or systemd timer:

```bash
make prune-threads
# Or directly:
uv run python -m neuron_agent.persistence.cli prune
```

### What Pruning Removes
1. Identifies conversation threads whose latest root checkpoint is older than $T_{now} - \text{APP\_THREAD\_RETENTION\_DAYS}$.
2. Deletes associated rows from `checkpoints`, `checkpoint_blobs`, and `checkpoint_writes`.
3. Deletes associated conversation titles from `neuron_thread_meta`.
4. Deletes associated ratings from `neuron_feedback`.
5. Cleans expired rows from `neuron_token_ledger` and `neuron_rate_buckets`.

---

## 6. Distributed Multi-Instance Concurrency Controls

When deploying multiple replicas of `neuron-api`, set:
```bash
APP_LIMITS_BACKEND=postgres
```

This activates PostgreSQL-backed coordination:

### 1. Active Run Leases (`neuron_run_leases`)
Prevents race conditions on threads. Before executing an agent turn, the API claims a run lease under a per-owner `pg_advisory_xact_lock`. A concurrent turn on the same thread is immediately rejected with `409 thread_busy`. Leases automatically expire after `APP_RUN_TIMEOUT_SECONDS + 15s`.

### 2. Rolling Token Budget (`neuron_token_ledger`)
Tracks per-user token consumption within a sliding window (`APP_USER_TOKEN_BUDGET_WINDOW_SECONDS`, default 3600s). Runs reserve estimated tokens upon admission and settle exact usage upon turn completion. Exceeding the budget returns `429 quota_exceeded` with `Retry-After`.

### 3. Distributed Token-Bucket Rate Limiter (`neuron_rate_buckets`)
Maintains rate limits across all replicas using an `UNLOGGED` PostgreSQL table. Each request executes an atomic upsert with database-clock timestamps (`clock_timestamp()`). If the database becomes unreachable, the limiter fails closed (`503 persistence_error`).
