# How-To: Operate, Monitor, and Maintain Neuron in Production

> **Document ID:** DOC-HOW-007  
> **Diátaxis Mode:** How-To Guide (Task-Oriented)  
> **Standard Alignment:** Structured in alignment with ISO/IEC/IEEE 26514:2022 §7.4 (Procedural Task Information) and Diátaxis (How-To Guide)  
> **Audience:** SREs, DevOps Engineers, Platform Administrators  
> **Code Traceability:** `src/neuron_agent/observability/`, `src/neuron_agent/knowledge/worker.py`, `OPERATIONS.md`, ADR 0008

---

## 1. Production Deployment Topology

In production, Neuron runs as a distributed multi-instance deployment composed of two decoupled services sharing a PostgreSQL database cluster:

```mermaid
graph TD
    subgraph Edge ["Edge / Ingress"]
        LB[Load Balancer / Cloudflare]
    end

    subgraph APITier ["API Service Tier (neuron-api)"]
        API1["neuron-api (Replica 1)"]
        API2["neuron-api (Replica 2)"]
    end

    subgraph WorkerTier ["Background Worker Tier (neuron-worker)"]
        Worker1["neuron-worker (Replica 1)"]
    end

    subgraph ParserTier ["Document Parser Tier (Isolated Network)"]
        Docling["docling-serve (No Internet Route)"]
    end

    subgraph DataTier ["Persistence Tier"]
        Postgres[(PostgreSQL 16+ pgvector)]
        BlobStorage[(S3 / Private Object Storage)]
    end

    LB -->|HTTPS| API1
    LB -->|HTTPS| API2
    API1 -->|APP_POSTGRES_DSN| Postgres
    API2 -->|APP_POSTGRES_DSN| Postgres
    Worker1 -->|APP_POSTGRES_WORKER_DSN| Postgres
    Worker1 -->|Internal HTTP| Docling
    Worker1 -->|S3 API| BlobStorage
    API1 -->|S3 API| BlobStorage
    API2 -->|S3 API| BlobStorage
```

### Component Roles
- **`neuron-api` (API Service):** Horizontally scalable stateless FastAPI process. Handles HTTP/SSE client connections, JWT validation, rate limiting, and graph invocation. Does not run heavy ingestion tasks.
- **`neuron-worker` (Background Worker):** Distributed task processor running Procrastinate jobs (`ingest_document`, `purge_document`, `purge_knowledge_base`, `reconcile_knowledge`, `sweep_knowledge_blobs`). Connects as `neuron_worker` role.
- **`docling-serve` (Parser Container):** Runs on an internal unroutable Docker network (`parser`) without internet access. Converts complex PDF and Office files to structured text.

---

## 2. Health Checks and Readiness Probes

Neuron exposes two unauthenticated probe endpoints:

### Liveness Probe (`GET /health/live`)
- **Purpose:** Verifies that the FastAPI process is responsive and event loops are not blocked.
- **Probe Config (Kubernetes):**
  ```yaml
  livenessProbe:
    httpGet:
      path: /health/live
      port: 8000
    initialDelaySeconds: 5
    periodSeconds: 10
  ```
- **Response:** `200 {"status": "ok"}`

### Readiness Probe (`GET /health/ready`)
- **Purpose:** Verifies that external dependencies required to serve requests are fully functional:
  1. PostgreSQL connection pool is alive and responds to query probes.
  2. JWKS signing keys from the Identity Provider are cached and valid.
- **Probe Config (Kubernetes):**
  ```yaml
  readinessProbe:
    httpGet:
      path: /health/ready
      port: 8000
    initialDelaySeconds: 5
    periodSeconds: 10
    failureThreshold: 3
  ```
- **Response:** `200 {"status": "ready"}` or `503 {"status": "not_ready"}`

> [!NOTE]
> `/health/ready` deliberately ignores the state of `neuron-worker`. The API can serve chat, memory, and direct queries even if background ingestion is temporarily queued.

---

## 3. Monitoring, Telemetry, and Alerting

Neuron exports OpenTelemetry (OTel) traces and metrics over OTLP/HTTP to any standard collector (Prometheus, Grafana Tempo, Datadog).

### Enable OpenTelemetry in `.env`
```bash
APP_OTEL_ENABLED=true
APP_OTEL_SERVICE_NAME=neuron-api
APP_OTEL_EXPORTER_OTLP_ENDPOINT=http://otel-collector:4318
APP_OTEL_TRACES_SAMPLE_RATIO=1.0
```

### Core Service Level Indicators (SLIs)

| Metric Instrument | Type | Description & Alert Threshold |
| :--- | :--- | :--- |
| `neuron.requests` | Counter | Total incoming requests by status code and endpoint. Alert on sustained 5xx > 1%. |
| `neuron.agent.duration` | Histogram | End-to-end agent run duration in seconds. Target: p95 < 15s. |
| `neuron.agent.ttft` | Histogram | Time To First Token for SSE streams in milliseconds. Target: p95 < 1500ms. |
| `neuron.errors` | Counter | System failures partitioned by stable `error_code`. Alert on `persistence_error` or `provider_error`. |
| `neuron.postgres.pool.utilization` | Gauge | Active connections / pool max size. Alert when > 0.85. |
| `neuron.knowledge.queue.age` | Gauge | Age of oldest queued ingestion job in seconds. Alert when > 300s. |

---

## 4. Operational Runbooks

### Runbook 1: PostgreSQL Connection Pool Starvation
**Symptom:** `neuron.errors` records spikes of `persistence_error`; logs indicate `PoolTimeout`.  
**Remediation:**
1. Check current connection usage in PostgreSQL:
   ```sql
   SELECT count(*), state FROM pg_stat_activity WHERE datname = 'neuron_prod' GROUP BY state;
   ```
2. If total connections approach PostgreSQL `max_connections`, scale up database hardware or deploy a connection pooler (PgBouncer in transaction mode).
3. Increase pool size per replica in `.env`:
   ```bash
   APP_POSTGRES_POOL_MAX_SIZE=30
   APP_POSTGRES_POOL_TIMEOUT_SECONDS=15
   ```
4. Perform rolling restart of `neuron-api`.

---

### Runbook 2: Ingestion Queue Stalled / Worker Down
**Symptom:** Documents remain in `queued` status indefinitely; `neuron.knowledge.queue.age` > 600s.  
**Remediation:**
1. Check `neuron-worker` container logs:
   ```bash
   docker logs neuron-worker --tail 100
   ```
2. Verify worker container health check:
   ```bash
   uv run neuron-worker health
   # Returns 0 if healthy, 1 if health file stale
   ```
3. Check Procrastinate queue table for lock contention:
   ```sql
   SELECT status, count(*) FROM knowledge.procrastinate_jobs GROUP BY status;
   ```
4. If jobs are stuck in `doing` from an unclean container restart, the worker's automated periodic periodic task (`reconcile_knowledge`) releases them automatically after `APP_WORKER_STALLED_SECONDS` (default 30s) during normal worker operation (`uv run neuron-worker run`).

---

### Runbook 3: Model Provider Outage and Fallback Chain
**Symptom:** Spikes of `provider_timeout_error` or `provider_error` on OpenAI or NVIDIA.  
**Remediation:**
1. Neuron supports automated fallback chains configured via `APP_FALLBACK_MODELS`.
2. Configure ordered fallbacks in `.env`:
   ```bash
   APP_DEFAULT_MODEL=openai:gpt-5.4-mini
   APP_FALLBACK_MODELS='["nvidia:meta/llama-3.3-70b-instruct", "anthropic:claude-3-5-sonnet-latest"]'
   ```
3. When the primary model fails after its retries, Neuron logs `model_fallback_triggered` and routes the turn to the first available backup model without failing the user's turn.

---

### Runbook 4: Database Point-In-Time Restore (PITR) Drill
**Symptom:** Disaster recovery drill or database corruption restore.  
**Validation Procedure:**
1. Restore PostgreSQL database from backup snapshot.
2. Run database migration verification using the setup command (idempotent, checks and applies any missing migrations):
   ```bash
   uv run python -m neuron_agent.persistence.cli setup
   ```
3. Audit blob store consistency using the worker verification tool:
   ```bash
   uv run neuron-worker check-blobs
   ```
   This outputs a JSON report identifying:
   - Live documents whose blob files are missing from storage.
   - Orphaned blob files that have no matching document row.
4. If orphan files exist, the worker's hourly sweep (`sweep_knowledge_blobs`) will safely clean them up.
