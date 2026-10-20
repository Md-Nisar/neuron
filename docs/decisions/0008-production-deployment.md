# ADR 0008: Production Deployment

## Status

Proposed (v0.6.0). Amends ADR 0004, ADR 0005 (decision 5) and ADR 0006 where they
put shared, cross-replica limits out of scope (see "Amendments to earlier ADRs").

## Problem

v0.5.0 can measure the agent, but it has never run anywhere except a developer
machine and CI:

- No multi-replica or hosted deployment has ever been verified
  (`docs/releases/v0.5.0-release-verification.md:195`). `OPERATIONS.md:3-10` describes
  deployment in two sentences and rollback in one (`OPERATIONS.md:529-531`); there is
  no runbook for deploy, migration, backup, restore or secret rotation on a platform.
- The image is not reproducible. `Dockerfile:4` falls back to an unlocked resolve
  (`uv sync --no-dev --frozen || uv sync --no-dev`) and `Dockerfile:6` runs
  `uv sync --no-dev` without `--frozen`; neither base image is digest-pinned;
  `.dockerignore` excludes only `.env` and `.dev/`, so `.git`, `.venv`, tests and evals
  enter the build context. The v0.3.0 gate could not build it, and no CI job has built
  it since, so whether it builds today is unknown.
- `Dockerfile:18` starts Uvicorn with no graceful-shutdown timeout and no proxy
  settings, although `OPERATIONS.md:468` tells operators to set
  `--forwarded-allow-ips`. On SIGTERM, `/v1/agent/invoke` runs get no signal and are
  bounded only by `APP_RUN_TIMEOUT_SECONDS=120`, which is longer than common platform
  grace periods, and `/health/ready` does not turn `503` while the process drains
  (`api/main.py:357-361`).
- There is no pipeline: no workflow builds, scans, signs or deploys an image, and
  there are no staging or production environments. GitHub-owned actions are
  tag-pinned and there is no Dependabot configuration.
- Every limit is per process. The rate limiter's bucket dict is never evicted
  (`security/rate_limiter.py:59`), the token budget keeps deques in memory
  (`security/usage_budget.py:27-72`), and `thread_busy` and the per-user run cap live in
  `AgentService` (`services/agent_service.py:130-134`, `:416-478`). With N replicas the
  configured limits become N times larger, and two runs on one thread on different
  replicas both commit (`OPERATIONS.md:365-369`).
- Schema setup is LangGraph's `setup()` plus one `CREATE INDEX CONCURRENTLY`
  (`persistence/checkpointer.py:39`), run by hand (`make db-setup`) or at start-up
  (`APP_CHECKPOINTER_SETUP_ON_STARTUP`), with no versioning of our own. Retention
  (`make prune-threads`) and backups are prose only (`OPERATIONS.md:385`, `:429-434`).
  The runtime image has neither `make` nor `uv`.
- Settings refuse the worst production configurations (`config/settings.py:150-257`)
  but not these: `APP_CHECKPOINTER=auto` silently becomes `none` in production
  (`config/settings.py:182`); `APP_ALLOWED_HOSTS` may be empty; trusted proxies are
  unchecked; rate limiting can be disabled; start-up schema setup is allowed with
  replicas; the Postgres DSN may omit TLS.
- The request-body limit checks `Content-Length` only (`api/main.py:126-139`), so a
  chunked body bypasses `APP_MAX_REQUEST_BODY_BYTES`.
- `api/main.py:600-601` reads `HOST` and `PORT` with `os.getenv`, outside `config/`
  (AGENTS.md).
- The nightly live eval shares one NVIDIA key with `ai-review`; its last run was
  inconclusive (72/72 graded security trials passed, 9 infrastructure errors: 7
  `rate_limit_error`, 2 `run_timeout`), near the workflow's 90-minute cap
  (`.github/workflows/nightly-eval.yml:30`).
- The OpenAI production model has never been run live (`CHANGELOG.md:59`), and the
  SLOs come from the development model only, with a 16-run TTFT sample
  (`docs/releases/v0.5.0-release-verification.md:158-167`).

## Requirements

- One documented reference deployment, cheap enough for a single maintainer, with
  staging and production, reproducible from the repository.
- Every production image is built from the lockfile, scanned, attested, deployed by
  digest, and promoted unchanged from staging to production after human approval.
- Limits that hold across replicas: thread busy, concurrent runs per user, the token
  budget and request rates. No new stateful service (no Redis), and nothing that
  breaks behind a transaction-mode connection pooler (no session advisory locks).
- Schema changes run once per deploy, before new code takes traffic, and never stop
  the previous release from running (so rollback is redeploying the previous digest).
- An in-flight run survives a deploy or scale-in on the reference platform.
- Unsafe production configuration fails at start-up, not in an incident.
- Backups are restorable, and a restore has been rehearsed.
- `make test` stays deterministic and needs no Postgres; the in-memory implementations
  remain for development and tests.
- Environment variables are read only in `config/settings.py` (AGENTS.md).
- Keep the request flow, the graph and ADR 0001's constraints; this ADR adds no
  queues, retrieval, subgraphs or multi-agent orchestration. The guard tables are the
  custom persistence this ADR explicitly authorises (AGENTS.md).

## Options Considered

### Reference platform

1. **Render web service + Render Postgres.** Zero-downtime rolling deploys gated on a
   health check, a pre-deploy command for migrations, up to 300 s shutdown grace,
   PITR on every paid Postgres plan (3 days on Hobby workspaces, 7 on Pro), a cron job
   service type for retention, and a `render.yaml` blueprint. About $35/month for two
   small replicas and Postgres (list prices, secondary source).
2. **Fly.io + Fly Managed Postgres.** Similar features (`release_command`, up to 300 s
   `kill_timeout`, HA Postgres), from about $50/month; its PITR window is not stated.
3. **Cloud Run + Neon.** Cheapest at low traffic, but a fixed 10 s shutdown window kills
   in-flight `invoke` runs on every deploy.
4. **LangSmith Deployment (Agent Server) as the primary target.** Solves one run per
   thread and retention, but needs a paid plan (Enterprise to self-host), brings Redis,
   and skips the API's limits and input policy (`SECURITY.md:115`).
5. **Kubernetes.** The most control and the most operational load; only sensible if a
   cluster already exists.

Chosen: **1, by owner decision (2026-10-19).** The image stays a plain OCI image, so
other platforms remain possible; only Render is documented and verified.

### Cross-replica guards

1. **Postgres-backed** lease, budget and rate-limit tables. No new service; adds a
   database round trip per request and per run.
2. **Redis-backed.** A second stateful service, a new dependency and a fail-open or
   fail-closed decision.
3. **Keep per-process limits** and document "divide by the replica count", with sticky
   routing by thread. Free, but wrong whenever the platform rebalances.
4. **Delegate to Agent Server.** See platform option 4.

Chosen: **1, by owner decision (2026-10-19)**, with leases as expiring rows and no
session-level advisory locks.

### Supply chain

- Scanner: Trivy or Grype. Either is acceptable if invoked at a full commit SHA; the
  2026-03 Trivy tag compromise is why pinning, not the tool, is the requirement.
  Proposed: **Grype** (`anchore/scan-action`), vulnerability-only, since secrets are
  already scanned by gitleaks (open question 9).
- Signing: GitHub artifact attestations only (Sigstore bundles); a separate cosign step
  is not needed until a verifier requires `cosign verify`.
- SLSA: Build L2 inline; L3 (a reusable build workflow) is deferred.
- Dependency bot: **Dependabot** (native, zero setup) over Renovate (needs an app).
- Release tooling: manual version bump and tag, with the GitHub Release created by the
  pipeline from the `CHANGELOG.md` section; python-semantic-release is not adopted.

## Decisions

### 1. Reference platform

- Two Render environments, `staging` and `production`, each with a web service from
  the published image, a Render Postgres database, a cron job for retention and an
  environment group for its settings and secrets.
- Production runs **two instances** of a small paid instance type; staging runs one.
  Instance size is confirmed from memory measured at the release gate.
- A `render.yaml` blueprint in the repository is the source of truth for services,
  plans, health check path, pre-deploy command, shutdown delay, cron schedule and
  non-secret settings. Secret values never appear in it (`sync: false`).
- The web service's health check path is `/health/ready`; liveness stays
  `/health/live`.
- `maxShutdownDelaySeconds: 150`: above Uvicorn's graceful timeout (decision 3),
  which is above `APP_RUN_TIMEOUT_SECONDS`.
- Agent Server (`langgraph.json`) remains a supported second path: not deployed, not
  release-gating. Its missing limits and input policy (`SECURITY.md:113,115`) and its
  log issues (`CHANGELOG.md:60-61`) stay documented known issues.

### 2. Image

- `uv sync --frozen --no-dev --no-editable` only: a stale or missing lock fails the
  build. The runtime stage copies only the virtual environment, which holds the
  installed package (prompts are package data, loaded with `importlib.resources`);
  no source tree, tests, evals or `.git` in the image.
- A real `.dockerignore`: `.git`, `.venv`, `.claude/`, `tests/`, `evals/`, `docs/`,
  caches and local files.
- Both base images pinned by digest (with the tag in a comment, so Dependabot can
  update them).
- OCI labels, including `org.opencontainers.image.source` and the revision.
- Non-root user (kept), exec-form `CMD ["neuron-api"]` (decision 3).
- A test builds the image in CI and checks the layout: no `tests/` or `.git`, the
  package importable, the prompt loadable, the process running as non-root.

### 3. Server entrypoint and Uvicorn settings

- The image runs `neuron-api` (`api/main.py:main`, already a `[project.scripts]`
  entry), which builds Uvicorn's configuration from `Settings`, so every knob is
  validated and env reads stay in `config/`:
  - `APP_HOST` and `APP_PORT` replace the `os.getenv("HOST"/"PORT")` reads
    (`api/main.py:600-601`); `APP_PORT` also accepts Render's `PORT`.
  - `timeout_graceful_shutdown = APP_RUN_TIMEOUT_SECONDS + 10`.
  - One process per container; no `--workers`.
  - Proxy headers are parsed in exactly one place. Proposed: the app's existing
    `_client_ip` (`api/main.py:283`), driven by `APP_TRUSTED_PROXIES`, stays the only
    parser and Uvicorn's proxy-header rewriting is turned off, replacing the
    "configure `--forwarded-allow-ips` to the same set" instruction in ADR 0004 and
    `OPERATIONS.md:468` (open question 5).
- `make api` and local development keep working unchanged.

### 4. Graceful shutdown for invoke

- On SIGTERM the entrypoint marks the service as draining before Uvicorn stops: from
  then on `/health/ready` returns `503`, new `/v1/agent/*` runs are refused with
  `503 service_shutting_down` (retryable, `Retry-After`), in-flight `invoke` runs
  finish (up to the graceful timeout), and streams keep today's 2 s
  `service_shutting_down` behaviour.
- Telemetry flushes on shutdown as today; an abrupt kill still loses up to one export
  interval (`OPERATIONS.md:198-204`), accepted.

### 5. Request-body limit for chunked bodies

The body-size middleware also counts bytes as they arrive and answers
`413 payload_too_large` once `APP_MAX_REQUEST_BODY_BYTES` is exceeded, whether or not
`Content-Length` was sent.

### 6. CI/CD pipeline

One workflow, every step pinned by full commit SHA, least-privilege permissions per
job:

1. **Gates.** The existing `ci.yml` checks pass for the commit.
2. **Build and push** with buildx to `ghcr.io/md-nisar/neuron`, tagged `sha-<sha>`,
   with `provenance: mode=max` and `sbom: true`. Pull requests build without pushing.
3. **Scan** the pushed digest with the SHA-pinned scanner; fail on fixable HIGH or
   CRITICAL findings, with reviewed, dated ignores like `AUDIT_IGNORES`.
4. **Attest** the digest with `actions/attest` (push to the registry).
5. **Deploy staging by digest** on every push to `main`. The deploy job verifies the
   attestation (`gh attestation verify`) before deploying, waits for Render to report
   the deploy live, then runs a smoke test: `/health/ready` and one authenticated
   request.
6. **Promote the same digest to production** on a `v*` tag pointing at a `main`
   commit whose digest passed staging. The job runs in the `production` GitHub
   Environment with a required reviewer (self-review allowed while there is one
   maintainer) and a tag-only deployment rule; it never rebuilds.
7. **Publish the GitHub Release** from the `CHANGELOG.md` section (draft first, then
   published, for immutable releases).

GitHub Environments `staging` and `production` hold only what the deploy job needs
(the Render deploy credential and the smoke-test client credentials). The repository
turns on the "require full-length SHA pins" actions policy and immutable releases
(owner actions).

### 7. Migrations

- Render's **pre-deploy command** runs `python -m neuron_agent.persistence.cli setup`
  on the new image before it takes traffic; a failure cancels the deploy. It uses
  `APP_POSTGRES_MIGRATION_DSN` when set (a direct, non-pooled connection, required for
  `CREATE INDEX CONCURRENTLY`), else `APP_POSTGRES_DSN`.
- `APP_CHECKPOINTER_SETUP_ON_STARTUP=true` is refused in staging and production.
- neuron's own tables get a minimal versioned migration list in `persistence/` (a
  `neuron_migrations` table recording applied versions, applied in order after
  LangGraph's `setup()`). No migration framework dependency.
- `setup` detects an `INVALID` concurrently built index (which `IF NOT EXISTS` would
  skip) and rebuilds it, or fails loudly.
- **Compatibility rule (expand/contract).** A release's migrations must leave the
  previous release working: add tables, nullable columns and concurrent indexes;
  remove or rename only in a later release, after no running image uses the old shape.
  There are no down-migrations. Rollback is redeploying the previous digest.

### 8. Cross-replica guards in Postgres

All three sit behind Protocols, with the in-memory implementations kept for
development and tests. `RateLimiter` (`security/rate_limiter.py:22`) and `TokenBudget`
(`security/usage_budget.py:21`) exist but are synchronous; they become async. The run
guard has no Protocol today (it is inline in `AgentService._claim`), so one is
extracted. The Postgres implementations live in `persistence/` and share its pool.

- **Selection.** `APP_LIMITS_BACKEND`: `auto` (default) resolves to `memory` in
  development and test; staging and production must choose `postgres` or an explicit
  `memory` (single instance only, logged at start-up as per-process). `postgres`
  requires `APP_POSTGRES_DSN`, even with `APP_CHECKPOINTER=none`.
- **Run leases** (thread busy and per-user concurrent runs). A lease row
  `(lease_id, owner_key, thread_id NULL, expires_at)`, unique on `thread_id`. A claim is
  one short transaction serialised per owner with a transaction-level advisory lock
  (`pg_advisory_xact_lock`, released at commit, safe behind a transaction-mode pooler):
  delete the owner's expired leases, count live ones against
  `APP_MAX_CONCURRENT_RUNS_PER_USER`, insert the lease (`409 thread_busy` on a live
  lease for the thread). Release deletes the row. `expires_at = now() +
  APP_RUN_TIMEOUT_SECONDS + 15 s`: a run cannot outlive its timeout, so no heartbeat is
  needed; after a replica crash its leases block for at most that long. `DELETE
  /v1/threads/{id}` checks the same table.
- **Token budget.** A logged ledger `(owner_key, minute, tokens)`: admission sums the
  window, a charge upserts the current minute. The rolling window has one-minute
  granularity (documented).
- **Request rate limiting.** An `UNLOGGED` token-bucket table, one atomic
  `INSERT … ON CONFLICT DO UPDATE … RETURNING` per rate-limited request. Trade-off,
  accepted: one database write in front of every `/v1` request, and a crash or unclean
  shutdown truncates the table, granting every caller a fresh burst. Keys are owner
  keys (already an HMAC) or an HMAC of the client IP with a key derived from
  `APP_IDENTITY_HASH_KEY`; raw IPs are never stored. The in-memory limiter gains idle
  eviction, so its dict is bounded.
- **Failure mode.** A guard query that fails is `503 persistence_error`, like a
  checkpoint failure: fail closed (open question 7).
- **Stays per process, by design:** `APP_MAX_CONCURRENT_STREAMS` (a per-instance
  resource cap) and the JWKS cache.
- The daily retention job also deletes expired leases, ledger minutes outside the
  window and idle buckets.
- An integration test runs two app processes against one Postgres and shows that a
  per-user cap, `thread_busy` and the budget hold across them.

### 9. Production settings validation

In staging and production, start-up fails when:

- `APP_CHECKPOINTER` is `auto` (it must be `postgres` or an explicit `none`);
- `APP_LIMITS_BACKEND` is `auto`;
- `APP_ALLOWED_HOSTS` is empty;
- `APP_TRUSTED_PROXIES` is unset (an explicit empty list is allowed) or contains a
  catch-all range (`0.0.0.0/0`, `::/0`);
- `APP_RATE_LIMIT_ENABLED=false`;
- `APP_CHECKPOINTER_SETUP_ON_STARTUP=true`;
- a Postgres DSN lacks `sslmode=require`, `verify-ca` or `verify-full` (open question
  6).

Each is a breaking change for existing staging and production configurations and is
listed in the CHANGELOG.

### 10. Secrets

- Runtime secrets (`OPENAI_API_KEY`, `APP_POSTGRES_DSN`, `APP_POSTGRES_MIGRATION_DSN`,
  `APP_IDENTITY_HASH_KEY`) live in Render environment groups, one per environment.
  The Postgres DSN comes from the blueprint's database reference, not a pasted value.
- GitHub Environments hold only the deploy credential and smoke-test client
  credentials; no runtime secret passes through CI.
- `APP_IDENTITY_HASH_KEY` is identical on every replica of an environment, differs
  between staging and production, and is rotated only on exposure
  (`OPERATIONS.md:58-60`).

### 11. Dependency automation

`.github/dependabot.yml` for `uv`, `github-actions` and `docker`: weekly, grouped,
with a 7-day cooldown. GitHub-owned actions are SHA-pinned like third-party ones, each
with a `# vX.Y.Z` comment. The 90-day rule for new packages (`new-dependencies` job)
is unchanged; version bumps go through all gates.

### 12. Operations

- **Backups.** Render Postgres PITR. The workspace plan sets the window (3 or 7 days,
  open question 1); backups hold deleted threads until they age out, which the data
  rights section of `OPERATIONS.md` states.
- **Restore rehearsal.** Once for v0.6.0: restore production's database to a new
  instance at a recorded point in time, point staging at it, run `setup` and the smoke
  test, and record RTO and RPO in the release verification. Regular drills are v0.9.0.
- **Retention.** A Render cron job runs `python -m neuron_agent.persistence.cli
  prune` daily on the same image and environment group.
- **Runbooks** in `OPERATIONS.md`: deploy, rollback (previous digest), migration
  (expand/contract, an invalid index), secret and key rotation (provider key, database
  password, `APP_IDENTITY_HASH_KEY`, IdP signing keys), connection budget
  (`instances × APP_POSTGRES_POOL_MAX_SIZE` plus pre-deploy and cron, under the plan's
  `max_connections`), table growth (a size query for the checkpoint tables).
- **Alerts** added to `deploy/observability/prometheus-alerts.yaml`, each with a
  runbook entry: no metrics from any instance (absent), an instance not ready, Postgres
  errors and pool saturation, and denied or unknown tool attempts (`CHANGELOG.md:57`).
  CI validates the alert rules (`promtool check rules`) and the Collector configuration
  (`otelcol-contrib validate`), which the repository has never run.
- **Telemetry on Render.** One Collector, as a Render private service, receives OTLP
  from the instances and exports to a backend that evaluates the alert rules (open
  question 10). One Collector replica, so trace-ID load balancing is not needed yet.
  Logs stay JSON on stdout, collected by the platform; OTLP log export stays deferred.

### 13. Nightly eval reliability

`ai-review` and `nightly-eval` stop sharing a provider key: `ai-review` uses its own
secret and skips without it (never falling back to the nightly key). Without a second
key, `ai-review` skips while the nightly run is scheduled. The nightly timeout gets
headroom over the measured run time (about 74 minutes for 3 trials). Both stay within
NVIDIA's API terms (ADR 0007 section 6).

### 14. Release gate evidence

- The live regression and security suites run with `--trials 3` and `compare` on the
  development baseline model; a run that is inconclusive or failing is recorded
  honestly with reasons, as in v0.5.0.
- The production model (OpenAI) is run at the gate if a funded key exists; otherwise
  it stays a known issue (ADR 0007 section 6).
- SLOs are re-checked on the deployed instance (staging, or production with synthetic
  traffic), not only on eval runs.

### Amendments to earlier ADRs

This ADR changes decisions that put shared backends out of scope. The documents
themselves are edited by the issues that implement each guard, not by this ADR:

| Document | Current text | Amended by |
| --- | --- | --- |
| ADR 0004, "v0.4.0 Resource Limits" and Consequences | "each replica enforces its own limits; cross-replica coordination remains out of scope"; a shared backend means "e.g. Redis" | Decision 8: Postgres-backed rate limits and budget; proxy-header handling (decision 3) |
| ADR 0005, decision 5 and Consequences | the `thread_busy` guard is process-local and doesn't coordinate across replicas | Decision 8: run leases |
| ADR 0006, Non-goals | "Distributed rate limiting or concurrency coordination; issue #56 retains that deployment decision" (#56 chose in-process, v0.4.0) | Decision 8 |
| `OPERATIONS.md:365-369`, `:472`, `:519` | per-process guards; "a shared Redis/Postgres backend is intentionally out of scope"; "limits are per-instance" | Decision 8 |
| `ARCHITECTURE.md:189`, `:284`; `SECURITY.md:110` | per-process guards and limiter | Decision 8 |

## Migration and rollout

1. Image, entrypoint and pipeline first (decisions 2, 3, 6), deploying to staging with
   the in-memory guards and one instance.
2. Versioned migrations (decision 7), then the guard tables (decision 8), each landing
   with its expand-only migration.
3. Settings hardening (decision 9) last among code changes, since it breaks existing
   staging and production configuration. Breaking for operators:
   - `APP_CHECKPOINTER` and `APP_LIMITS_BACKEND` must be set explicitly;
     `APP_ALLOWED_HOSTS` and `APP_TRUSTED_PROXIES` must be set; rate limiting can't
     be disabled; start-up setup is refused; the DSN needs TLS.
   - The image runs `neuron-api`; `HOST`/`PORT` become `APP_HOST`/`APP_PORT` (Render's
     `PORT` still works).
   - If proxy headers move to the app only (open question 5), Uvicorn's
     `--forwarded-allow-ips` no longer applies.
4. Production goes live with two instances only after the two-process test passes in
   CI and staging has run the same digest.
- New runtime dependencies: none. CI gains pinned actions for buildx, the scanner and
  attestations, and pinned `promtool` and `otelcol-contrib` binaries.

## Non-goals (v0.6.0)

- Kubernetes manifests, Helm charts or other platforms' configuration.
- Redis or any new stateful service.
- Multi-region deployment, autoscaling policy tuning.
- Load testing, capacity planning and disaster-recovery drills beyond one restore
  rehearsal (v0.9.0, `docs/ROADMAP.md:11`).
- Rate limits, budgets and the input policy on Agent Server (known issue).
- LLM-judge quality evals (#103) and the feedback endpoint (#104), both still
  deferred.
- SLSA Build L3, cosign signatures, hardened base images.
- Billing-grade or estimated cost (still no verifiable, dated price data).

## Consequences

- Every production image is reproducible from the lockfile, scanned and attested, and
  production runs exactly the digest staging ran.
- Limits mean what they say across replicas, at the cost of a database round trip per
  request and per run, and of fail-closed behaviour when Postgres is down (the
  checkpointer already fails then).
- neuron owns three small tables and a minimal migration list; ADR 0001's ban on
  custom persistence is relaxed only for these guards.
- Deploys need a paid Render plan (pre-deploy commands) and Postgres even for a
  stateless deployment that uses the shared guards.
- Operators get stricter start-up validation and must update existing staging and
  production settings.
- A crashed replica's leases block its users' threads for up to the run timeout plus
  15 s.

## Open questions for review

1. **Render workspace and Postgres plan.** Hobby (3-day PITR) or Pro (7-day PITR), and
   which Postgres plan (its `max_connections` sets the pool budget). Cost of Pro is not
   in the research.
2. **Identity provider for staging and production.** `APP_AUTH_MODE=jwt` is required
   there; which IdP issues tokens, and which service account the smoke test uses.
3. **Provider keys.** Production needs a funded OpenAI key; staging could use the
   NVIDIA development model (no user data in staging). Without an OpenAI key,
   production can deploy but not serve.
4. **Deploy by digest on Render.** Whether a deploy hook with an image URL (narrow,
   per service) or the Render API (account-wide key) deploys a given digest and
   reports status, and whether a Render rollback re-runs the pre-deploy command. Not
   covered by the research; verify before draft 15.
5. **Proxy headers.** Render's proxy addresses for `APP_TRUSTED_PROXIES`, and whether
   the app or Uvicorn parses `X-Forwarded-For` (proposed: the app only).
6. **Database TLS and pooling on Render.** Whether Render's internal connection string
   supports `sslmode=require`, and whether any pooler sits in front (affects
   `prepare_threshold=0` and the migration DSN).
7. **Guard failure mode.** Fail closed (`503`) for all guards, or fail open for the
   request rate limiter only; and whether the per-request write is acceptable or the
   rate limiter should stay a bounded per-process one with "divide by instances"
   documented (the owner decision allows either).
8. **Lease expiry.** Run timeout plus 15 s, no heartbeat (proposed), or a shorter
   expiry with a heartbeat.
9. **Scanner.** Grype (proposed) or Trivy.
10. **Telemetry backend.** Where the Collector exports and the alert rules are
    evaluated for the reference deployment, and its cost; and whether the Collector
    image is built here (its config baked in) or configured with Render secret files.
11. **Staging trigger.** Every push to `main` (proposed) or manual.
12. **Blueprint layout.** One `render.yaml` defining both environments, or one per
    environment.
13. **HSTS.** Whether production must set `APP_HSTS_MAX_AGE_SECONDS` (Render serves
    HTTPS; whether it redirects plain HTTP was not checked).
14. **GHCR visibility.** A public package (Render pulls without credentials) or a
    private one with a registry credential in Render.

## References

- `docs/research-notes.md`, "v0.6.0 Research: Production Deployment".
- https://render.com/docs/deploys, https://render.com/docs/postgresql-refresh
- https://docs.github.com/en/actions/how-tos/secure-your-work/use-artifact-attestations/use-artifact-attestations
- https://docs.github.com/en/actions/reference/workflows-and-actions/deployments-and-environments
- https://docs.docker.com/build/ci/github-actions/attestations/
- https://www.postgresql.org/docs/current/explicit-locking.html
- https://www.postgresql.org/docs/current/sql-createtable.html
- https://www.postgresql.org/docs/current/sql-createindex.html
- https://www.pgbouncer.org/features.html
- https://fastapi.tiangolo.com/deployment/docker/
- https://sre.google/sre-book/data-integrity/
- ADR 0004, ADR 0005, ADR 0006, ADR 0007.
