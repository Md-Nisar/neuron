# ADR 0008: Production Deployment

## Status

Accepted (v0.6.0), with three Render facts assumed, not proven (open questions 4, 6
and 20; decision 17). Amends ADR 0004, ADR 0005 (decisions 1 and 5) and ADR 0006 where
they put shared, cross-replica limits out of scope or make checkpointer selection and
schema setup lenient in staging and production (see "Amendments to earlier ADRs").

## Problem

v0.5.0 can measure the agent, but it has never run anywhere except a developer
machine and CI:

- No release gate has run more than one process, or run on a hosted platform: the
  v0.5.0 gate ran on one process on one machine
  (`docs/releases/v0.5.0-release-verification.md:195`), and no earlier gate did more.
  `OPERATIONS.md:3-10` describes deployment in two sentences and rollback in one
  (`OPERATIONS.md:529-531`); there is no runbook for deploy, migration, backup, restore
  or secret rotation on a platform.
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
- The defaults are development defaults: `APP_ENV` defaults to `development`
  (`config/settings.py:37`) and `APP_AUTH_MODE` to `none` (`config/settings.py:94`).
  A missing or mistyped `APP_ENV` on a platform silently turns every production check
  off and serves unauthenticated.
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
  (`APP_CHECKPOINTER_SETUP_ON_STARTUP`), with no versioning of our own, by the same
  database user that serves requests. Retention (`make prune-threads`) and backups are
  prose only (`OPERATIONS.md:385`, `:429-434`). The runtime image has neither `make`
  nor `uv`.
- Settings refuse the worst production configurations (`config/settings.py:150-257`)
  but not these: `APP_CHECKPOINTER=auto` silently becomes `none` in production
  (`config/settings.py:182`); `APP_ALLOWED_HOSTS` may be empty; trusted proxies are
  unchecked; rate limiting can be disabled; start-up schema setup is allowed with
  replicas; the Postgres DSN may omit TLS.
- The request-body limit checks `Content-Length` only (`api/main.py:126-139`), so a
  chunked body bypasses `APP_MAX_REQUEST_BODY_BYTES`.
- `api/main.py:600-601` reads `HOST` and `PORT` with `os.getenv`, and
  `observability/telemetry.py:185` writes `OTEL_SEMCONV_STABILITY_OPT_IN`, both outside
  `config/` and outside AGENTS.md's one documented exception.
- The nightly live eval shares one NVIDIA key with `ai-review`; its last run was
  inconclusive (72/72 graded security trials passed, 9 infrastructure errors: 7
  `rate_limit_error`, 2 `run_timeout`; about 74 minutes:
  https://github.com/Md-Nisar/neuron/actions/runs/39225629460), near the workflow's
  90-minute cap (`.github/workflows/nightly-eval.yml:30`).
- The OpenAI production model has never been run live (`CHANGELOG.md:59`), and the
  SLOs come from the development model only, with a 16-run TTFT sample
  (`docs/releases/v0.5.0-release-verification.md:158-167`).

## Requirements

- One documented reference deployment, cheap enough for a single maintainer (the
  owner confirms the priced topology below, open question 1), with staging and
  production, reproducible from the repository.
- Every production image is built from the lockfile, scanned, attested by this
  repository's build workflow, deployed by digest, and promoted unchanged from staging
  to production after human approval. An unattested digest never deploys.
- Limits that hold across replicas: thread busy, concurrent runs per user, the token
  budget and request rates. No new stateful service (no Redis), and nothing that
  breaks behind a transaction-mode connection pooler (no session advisory locks on
  pooled connections).
- Guards fail closed: when the guard store cannot answer, no model call runs.
- Schema changes run once per deploy, before new code takes traffic, under a role the
  web process does not hold, and never stop the previous release from running (so
  rollback is redeploying the previous digest).
- An in-flight run survives a deploy or scale-in on the reference platform.
- Unsafe production configuration, including a missing `APP_ENV`, fails at start-up,
  not in an incident.
- Backups are restorable, and a restore has been rehearsed (scope: open question 15).
- `make test` stays deterministic and needs no Postgres; the in-memory implementations
  remain for development and tests.
- Environment variables are read or written only in `config/settings.py`, plus the
  exceptions AGENTS.md lists (AGENTS.md).
- Keep the request flow, the graph and ADR 0001's scope; this ADR adds no queues,
  retrieval, subgraphs or multi-agent orchestration. The guard and migration tables are
  the custom persistence AGENTS.md and CLAUDE.md require an ADR for; this ADR is that
  ADR.

## Options Considered

### Reference platform

1. **Render web service + Render Postgres.** Zero-downtime rolling deploys gated on a
   health check, a pre-deploy command for migrations, up to 300 s shutdown grace,
   PITR on every paid Postgres plan (3 days on Hobby workspaces, 7 on Pro), a cron job
   service type for retention, private services, and a `render.yaml` blueprint.
2. **Fly.io + Fly Managed Postgres.** Similar features (`release_command`, up to 300 s
   `kill_timeout`, HA Postgres), from about $50/month for two replicas and Postgres;
   its PITR window is not stated.
3. **Cloud Run + Neon.** Cheapest at low traffic, but a fixed 10 s shutdown window kills
   in-flight `invoke` runs on every deploy.
4. **LangSmith Deployment (Agent Server) as the primary target.** Solves one run per
   thread and retention, but needs a paid plan (Enterprise to self-host), brings Redis,
   and skips the API's limits and input policy (`SECURITY.md:115`).
5. **Kubernetes.** The most control and the most operational load; only sensible if a
   cluster already exists.

Chosen: **1, by owner decision (2026-10-19).** The image stays a plain OCI image, so
other platforms remain possible; only Render is documented and verified.

**Cost of the full topology on Render** (list prices seen 2026-10-19/20, perishable,
partly from a secondary source; `docs/research-notes.md`, "v0.6.0 Research",
"Deployment targets" and "Render addendum"):

| Item | Production | Staging |
| --- | --- | --- |
| Web service, Starter ($7 each) | 2 instances, $14 | 1 instance, $7 |
| Render Postgres | Basic-1gb $19 + $0.30/GB | Basic-256mb $6 + $0.30/GB |
| Retention cron job (per-second billing, $1 minimum) | about $1 | about $1 |
| Collector private service (assumed Starter; private services are "just like web services", no separate price found) | $7 | $7, or shared with production (open question 10) |
| Subtotal | about $42 + storage | about $14-21 + storage |

About **$56-63/month plus storage**, before three unpriced items: the Render workspace
plan (Hobby or Pro, open question 1), the telemetry backend (open question 10) and
model usage. If measured memory needs a larger instance than Starter (decision 1), the
web line grows. The earlier "about $35/month" covered only two replicas and one
database.

### Cross-replica guards

1. **Postgres-backed** lease, budget and rate-limit tables. No new service; adds a
   database round trip per request and per run.
2. **Redis-backed.** A second stateful service, a new dependency and a fail-open or
   fail-closed decision.
3. **Keep per-process limits** and document "divide by the replica count", with sticky
   routing by thread. Free, but wrong whenever the platform rebalances.
4. **Delegate to Agent Server.** See platform option 4.

Chosen: **1, by owner decision (2026-10-19)**, with leases as expiring rows and no
session-level advisory locks on pooled connections.

### Migrations

1. **Alembic.** The standard, but it brings SQLAlchemy as a new runtime dependency,
   models LangGraph's tables it does not own, and still needs custom handling for
   `CREATE INDEX CONCURRENTLY` outside a transaction.
2. **yoyo-migrations.** Small, plain SQL with its own lock and log tables, but a new
   dependency for a handful of statements, and it runs each migration in a
   transaction by default (concurrent index builds need a per-migration opt-out).
3. **Plain SQL files applied by hand** (`psql -f`). No dependency, but no record of
   what was applied, no ordering guarantee and no pre-deploy entry point.
4. **A minimal runner in `persistence/`**: an ordered list of statements, a
   `neuron_migrations` table, autocommit for concurrent builds. About 100 lines, no
   dependency, the same CLI that already runs LangGraph's `setup()`.

Chosen: **4** (decision 7). Revisit if neuron owns more than a few tables.

### Infrastructure as code and the deploy trigger

Infrastructure: (a) **dashboard** configuration (nothing reviewable or reproducible);
(b) **scripts against the Render API** (reproducible, but needs an API key, which is
account-wide and can read every environment group); (c) a **`render.yaml`
blueprint** in the repository (reviewable, testable, no credential in CI).
Chosen: **(c)**.

Deploy trigger: (a) a **per-service deploy hook** with an `imgURL` naming the digest
(narrow: one secret per service, can only deploy that service); (b) the **Render
API** (status and rollback, but an account-wide key); (c) **Render builds from the
repository** (auto-deploy; no attested digest, staging and production build twice).
Chosen: **(a)**, pending the proof in open question 4; (b) only with the scoping open
question 4 asks for; (c) rejected because it breaks "promote the same digest".

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
  the published image, a Render Postgres database, a cron job for retention, a
  Collector private service (decision 12) and environment groups for its settings and
  secrets, split per service role (decision 10).
- Production runs **two instances** of a small paid instance type; staging runs one.
  Instance size is confirmed from memory measured at the release gate.
- A `render.yaml` blueprint in the repository is the source of truth for services,
  plans, health check path, pre-deploy command, shutdown delay, cron schedule and
  non-secret settings, including `APP_ENV` (`staging` or `production`, never left to
  the default) and `APP_AUTH_MODE=jwt` on every web service. Secret values never appear
  in it (`sync: false`).
- Render Postgres databases accept no connections from outside Render: `ipAllowList`
  is empty (internal connections only).
- Production sets `APP_LIMITS_BACKEND=postgres`. Staging may run
  `APP_LIMITS_BACKEND=memory` with one instance until the Postgres guards land
  (drafts 11b, 12, 13); it switches to `postgres` before the release gate.
- Staging and production are separate trust domains: each has its own
  `APP_IDENTITY_HASH_KEY`, database and audience (`APP_AUTH_AUDIENCE` differs, a
  separate IdP tenant where the IdP allows it; open question 2), so a staging token is
  never accepted by production.
- The web service's health check path is `/health/ready`; liveness stays
  `/health/live`.
- `maxShutdownDelaySeconds: 150`: above Uvicorn's graceful timeout plus the drain delay
  (decisions 3 and 4), which is above `APP_RUN_TIMEOUT_SECONDS`. The application cannot
  read the platform's value, so the blueprint test (not a start-up check) enforces the
  ordering.
- Agent Server (`langgraph.json`) remains a supported second path: not deployed, not
  release-gating. Its missing limits and input policy (`SECURITY.md:115`), its unguarded
  live `stream_mode=messages` chunks (`SECURITY.md:113`) and its log issues
  (`CHANGELOG.md:60-61`) stay documented known issues.

### 2. Image

- `uv sync --locked --no-dev --no-editable` only (`--frozen` does not check the lock against
  `pyproject.toml`, so it cannot meet this): a stale or missing lock fails the
  build. The runtime stage copies only the virtual environment, which holds the
  installed package (prompts are package data, loaded with `importlib.resources`);
  no source tree, tests, evals or `.git` in the image.
- `.dockerignore` is an **allowlist** (`*`, then `!pyproject.toml`, `!uv.lock`,
  `!src/` and the files the build needs), so a new local file never enters the build
  context by default.
- No secret is passed as a build argument (max-mode provenance records build
  arguments); if a build ever needs one, it uses a BuildKit secret mount.
- Both base images pinned by digest (with the tag in a comment, so Dependabot can
  update them).
- OCI labels, including `org.opencontainers.image.source` and the revision.
- Non-root user with a fixed numeric UID, exec-form `CMD ["neuron-api"]` (decision 3),
  and `ENV APP_HOST=0.0.0.0` with `APP_PORT=8000` (decision 3).
- A test builds the image in CI and checks the layout: no `tests/`, `.git`, `.env*`,
  `*.pem` or `*.key`; the package importable; the prompt loadable; a numeric non-root
  UID; the exact `CMD` and `HEALTHCHECK`.

### 3. Server entrypoint and Uvicorn settings

- The image runs `neuron-api` (`api/main.py:main`, already a `[project.scripts]`
  entry), which builds Uvicorn's configuration from `Settings`, so every knob is
  validated and env reads stay in `config/`:
  - `APP_HOST` and `APP_PORT` replace the `os.getenv("HOST"/"PORT")` reads
    (`api/main.py:600-601`); `APP_PORT` also accepts Render's `PORT`. The image sets
    `APP_HOST=0.0.0.0` and `APP_PORT=8000`, and its `HEALTHCHECK` targets the
    configured port.
  - **No public bind without an explicit environment.** `neuron-api` refuses to start
    on a non-loopback `APP_HOST` unless `APP_ENV` was set explicitly (not defaulted).
    So an image started without `APP_ENV` exits non-zero instead of serving as
    `development` with `AUTH_MODE=none`. `docker-compose.yml` sets
    `APP_ENV=development` explicitly.
  - `timeout_graceful_shutdown = APP_RUN_TIMEOUT_SECONDS + 10`.
  - One process per container; no `--workers`.
  - Proxy headers are parsed in exactly one place. Proposed: the app's existing
    `_client_ip` (`api/main.py:283`), driven by `APP_TRUSTED_PROXIES`, stays the only
    parser (rightmost untrusted `X-Forwarded-For` hop) and Uvicorn's proxy-header
    rewriting is turned off, replacing the "configure `--forwarded-allow-ips` to the
    same set" instruction in ADR 0004 and `OPERATIONS.md:468` (open question 5). A
    forged `X-Forwarded-For` from an untrusted peer never reaches logs or telemetry.
- `observability/telemetry.py:185` (`os.environ.setdefault` of
  `OTEL_SEMCONV_STABILITY_OPT_IN`, a variable the OpenTelemetry library reads itself)
  becomes AGENTS.md's second documented exception, so a test can forbid every other
  env read or write outside `config/`.
- `make api` and local development keep working unchanged.

### 4. Graceful shutdown for invoke

- `AgentService` owns a draining flag; `AgentService.prepare` honours it by raising a
  shutdown error that `api/` maps to `503 service_shutting_down` (retryable,
  `Retry-After`). The service does not know about HTTP.
- On SIGTERM a `uvicorn.Server` subclass built by `neuron-api` (overriding
  `handle_exit`) sets the flag **before** Uvicorn stops accepting connections:
  1. `/health/ready` returns `503` at once, so the platform stops routing new traffic;
  2. new `/v1/agent/*` runs are still accepted for a short drain delay (a few seconds,
     while the load balancer converges), then refused with `503
     service_shutting_down`;
  3. in-flight `invoke` runs finish, up to the graceful timeout; streams keep today's
     2 s `service_shutting_down` behaviour;
  4. before exit, pending budget charges are written and leases are deleted. Lease
     release is best effort: a SIGKILL leaves leases that expiry (decision 8) clears.
- Telemetry flushes on shutdown as today; an abrupt kill still loses up to one export
  interval (`OPERATIONS.md:198-204`), accepted.

### 5. Request-body limit for chunked bodies

The body-size middleware wraps the ASGI `receive` channel: it counts bytes as they
arrive and answers `413 payload_too_large` as soon as `APP_MAX_REQUEST_BODY_BYTES + 1`
bytes have been read, before any parsing or buffering, whether or not
`Content-Length` was sent (and when a declared length understates the body). It runs
before authentication, on every `/v1` route. Uvicorn serves HTTP/1.1 only (Render's
edge terminates HTTP/2), so HTTP/2 framing is out of scope. A proxy-level limit is
defence in depth where the platform offers one; Render's was not found.

### 6. CI/CD pipeline

One workflow, every step pinned by full commit SHA, least-privilege permissions per
job; it is the only workflow with `id-token: write` or `attestations: write`:

1. **Gates.** The existing `ci.yml` checks pass for the commit.
2. **Build and push** with buildx to `ghcr.io/md-nisar/neuron`, tagged `sha-<sha>`,
   with `provenance: mode=max` and `sbom: true`. Pull requests build without pushing.
3. **Scan** the pushed digest with the SHA-pinned scanner; fail on fixable HIGH or
   CRITICAL findings, with reviewed, dated ignores like `AUDIT_IGNORES`. The scanner's
   vulnerability database is downloaded at run time; a failed database update fails
   the scan (no stale-database pass).
4. **Attest** the digest with `actions/attest` (push to the registry).
5. **Deploy staging by digest** on every push to `main`. The deploy job verifies the
   attestation and pins its signer:
   `gh attestation verify oci://ghcr.io/md-nisar/neuron@<digest> -R Md-Nisar/neuron
   --signer-workflow Md-Nisar/neuron/.github/workflows/<file>.yml --source-ref
   refs/heads/main --predicate-type https://slsa.dev/provenance/v1`. A digest whose
   verification fails never deploys. It then deploys every staging service (web, cron,
   Collector where it runs our image) by that digest, confirms the pre-deploy
   migration ran on the new digest, waits for Render to report each deploy live, and
   runs the smoke test (decision 12).
6. **Promote the same digest to production** on a `v*` tag. The job resolves the digest
   from the `main` workflow run that built and attested the tagged commit (its run
   record and attestation), never from the mutable `sha-` tag; checks with `git
   merge-base --is-ancestor <tag> origin/main` that the tag is on `main`; requires
   that digest's staging deploy and smoke test to have passed; re-verifies the
   attestation with the same pinned signer; re-scans the digest (reported, not
   blocking, since new CVEs appear between staging and promotion); and deploys it to
   every production service. It runs in the `production` GitHub Environment with a
   required reviewer and a tag-only deployment rule, and never rebuilds. With one
   maintainer, self-approval is allowed and is a speed bump, not a second pair of eyes.
7. **Publish the GitHub Release** from the `CHANGELOG.md` section (draft first, then
   published, for immutable releases).

Deploy credentials (decision 10): one per Render service and environment (deploy hook
URLs), never an account-wide Render API key, unless open question 4 shows it can be
scoped or isolated in its own workspace. Hook URLs are masked in logs
(`::add-mask::`). The `staging` Environment accepts deployments from `main` only; the
`production` Environment from `v*` tags only, which a tag ruleset protects (owner
action). The repository turns on the "require full-length SHA pins" actions policy and
immutable releases (owner actions).

If open question 4's proof shows that Render does not run the pre-deploy command for a
prebuilt-image deploy, the fallback is decided before draft 14: a Render one-off job
(API-triggered, which re-opens the API-key question) or a separate migration service,
not a migration run from GitHub Actions (no runtime database credential passes through
CI).

### 7. Migrations

- Render's **pre-deploy command** runs `python -m neuron_agent.persistence.cli setup`
  on the new image before it takes traffic; a failure cancels the deploy. In staging
  and production it uses `APP_POSTGRES_MIGRATION_DSN` only (a direct, non-pooled
  connection as the migrator role, decision 15); there is no fallback to the runtime
  DSN, and `setup` exits non-zero without it. Development keeps the fallback.
- `APP_CHECKPOINTER_SETUP_ON_STARTUP=true` is refused in staging and production.
- neuron's own tables get a minimal versioned migration list in `persistence/` (a
  `neuron_migrations` table recording applied versions, applied in order after
  LangGraph's `setup()`). No migration framework dependency (see Options).
- **One `setup` at a time.** `setup` takes a session-level advisory lock on its own
  direct, non-pooled migration connection for its whole run, so two concurrent
  pre-deploys (or a pre-deploy and an operator) serialise. This is the only session
  advisory lock in neuron, and it is outside the owner's "no session advisory locks"
  decision only in letter: that decision protects pooled connections, and the
  migration connection is never pooled (open question 19 asks the owner to confirm).
- DDL runs with a `lock_timeout` (a few seconds) so a migration waiting behind live
  traffic fails the deploy instead of queueing every request behind it.
- `setup` detects an `INVALID` concurrently built index (which `IF NOT EXISTS` would
  skip) and rebuilds it, or fails loudly.
- **Compatibility rule (expand/contract).** A release's migrations must leave the
  previous release working: add tables, nullable columns and concurrent indexes;
  remove or rename only in a later release, after no running image uses the old shape.
  A lint test refuses `DROP`, `RENAME`, `ALTER ... TYPE`, `ADD COLUMN ... NOT NULL`
  (without a default), `SET NOT NULL`, `ADD CONSTRAINT` (unless `NOT VALID`) and
  `CREATE [UNIQUE] INDEX` without `CONCURRENTLY` unless the migration is marked as a
  contract step naming the release that stopped using the old shape. There are no
  down-migrations. Rollback is redeploying the previous digest.
- A `langgraph-checkpoint-postgres` bump can change LangGraph's own schema; it needs a
  rollback test (the previous image runs against the migrated schema) and is never
  auto-merged.
- `setup` and `prune` are operator commands (pre-deploy and cron), not HTTP routes;
  their errors never print a DSN or password.

### 8. Cross-replica guards in Postgres

**Protocols, and the call sites that change.** `RateLimiter`
(`security/rate_limiter.py:22`) and `TokenBudget` (`security/usage_budget.py:21`) exist
but are synchronous; they become async. ADR 0004 promised that a shared backend needs
"no other call site changes" (`docs/decisions/0004-rate-limiting.md:73`); an async
Protocol does change them, and this ADR replaces that promise. The call sites are
`rate_limiter.check` at `api/main.py:150` and `security/auth.py:328`, `:392`;
`TokenBudget.check` at `services/agent_service.py:176` and `charge` at `:482`; and the
run guard's claim (`services/agent_service.py:199`, `_claim` at `:416-478`) and
`RunLease.release` at `api/main.py:467` and `services/agent_service.py:259`, `:338`.
The run guard has no Protocol today, so one is extracted. All three Protocols live in
`security/` (admission control); the Postgres implementations live in `persistence/`,
which imports `security/`, never the reverse. The existing reverse import
(`security/auth.py:315`, `:374` import `api.main` to reach `rate_limiter`) is replaced
by injection. Release on cancellation is shielded (`asyncio.shield`) so a cancelled
task still deletes its lease.

- **Selection.** `APP_LIMITS_BACKEND`: `auto` (default) resolves to `memory` in
  development and test; staging and production must choose explicitly. `memory` is
  refused in production, and allowed in staging only with one instance (logged at
  start-up as per-process). `postgres` requires `APP_POSTGRES_DSN`, even with
  `APP_CHECKPOINTER=none`; then `persistence/` still opens its one pool for the guards,
  and `/health/ready` includes the guard store.
- **Database clock only.** Every guard timestamp (`expires_at`, window minutes, bucket
  refill) comes from `now()` in the database, never the application clock, so replica
  clock skew does not matter.
- **Run leases** (thread busy and per-user concurrent runs). A lease row
  `(lease_id, owner_key, thread_id NULL, expires_at)`, unique on `thread_id`. A claim is
  one short `READ COMMITTED` transaction serialised per owner with a transaction-level
  advisory lock (`pg_advisory_xact_lock`, released at commit, safe behind a
  transaction-mode pooler; open question 19): delete the owner's expired leases, count
  live ones against `APP_MAX_CONCURRENT_RUNS_PER_USER`, insert the lease. A unique
  violation on `thread_id` is `409 thread_busy`, never `500`. Release deletes the row;
  it is best effort, and expiry covers a failed release. `expires_at =
  clock_timestamp() + APP_RUN_TIMEOUT_SECONDS + 15 s` (`clock_timestamp()`, not `now()`: `now()`
  is the transaction start, so a wait for the owner lock would shorten the lease). There is no heartbeat and no fencing: the run is
  cancelled at `APP_RUN_TIMEOUT_SECONDS`, 15 s before its lease can expire, and the
  checkpoint write cannot share the lease's transaction (LangGraph's saver owns it);
  a test pins cancellation at the timeout boundary (open question 8). After a replica
  crash its leases block for at most the run timeout plus 15 s. `DELETE
  /v1/threads/{id}` and the bulk erase hold a lease (or the thread's row lock) for
  their whole duration, so no run can start on a thread being deleted.
- **Token budget.** A logged ledger `(owner_key, minute, tokens)` with an explicit
  window (`APP_USER_TOKEN_BUDGET_WINDOW_SECONDS`, one-minute granularity, documented).
  Admission **reserves** `APP_MAX_OUTPUT_TOKENS` plus a prompt estimate before the run
  and fails when the window plus the reservation exceeds the budget; the run
  **settles** the reservation to the real usage in a `finally` on every path (success,
  error, cancellation, timeout, client disconnect), with partial usage, or the
  estimate when the provider omits usage. Charges are one atomic `INSERT … ON CONFLICT
  DO UPDATE SET tokens = <table>.tokens + EXCLUDED.tokens`. If the ledger write fails
  after the answer exists, the answer is delivered, a metric counts the failure, and
  the next admission for that owner fails closed until the store answers. The
  retention job deletes minutes outside the window.
  *Implemented in #147 (`persistence/token_budget.py`).* Details the design left open:
  admission is one `READ COMMITTED` transaction under a per-owner
  `pg_advisory_xact_lock` (so concurrent admissions never exceed the budget, not even by
  one reservation); the reservation is capped at the budget so a budget smaller than
  one reservation still admits a run from an empty window; the prompt estimate is the
  message's UTF-8 bytes / 3; a minute counts until its end plus the window has passed
  (usage is never forgotten early and is held up to 60 s longer); settling writes only
  the difference (an upsert when the run used more, a clamped decrement of the
  reservation's minute when less); a run that never started gives its reservation back;
  a failed settlement is kept in the process and retried at that owner's next admission,
  which fails closed until it succeeds. A crash loses that retry, and the reservation
  stays counted, so the ledger errs high. The application role needs `SELECT`, `INSERT`,
  `UPDATE` and `DELETE` on `neuron_token_ledger` and `neuron_token_settlements`
  (decision 15 / #144); the #144 grant phase covers the token tables (migrations 6 to 9).
  The budget is enforced **at admission and settled afterwards**: nothing stops a run
  mid-way, so a run can overshoot by its real cost (iterations, history, tool output;
  `APP_MAX_HISTORY_TOKENS` bounds each model call, not the number of calls), and the
  excess is charged at settlement. A run that reports no usage (cancelled, timed out, or
  a provider that omits usage) keeps its whole reservation; only a run that never reached
  the model gives it back. Each reservation has an id recorded with its settlement in
  one transaction (`neuron_token_settlements`), so a settlement retried after an
  ambiguous `COMMIT` is applied once. A reserve cancelled after its commit leaves its
  reservation counted until the window passes (conservative). A per-owner in-process gate
  bounds the pool connections one owner's admissions can hold. Settings validation
  requires `APP_USER_TOKEN_BUDGET_WINDOW_SECONDS` of at least `APP_RUN_TIMEOUT_SECONDS`
  + 15 with the Postgres backend.
- **Request rate limiting.** An `UNLOGGED` token-bucket table, one atomic
  `INSERT … ON CONFLICT DO UPDATE … RETURNING` per rate-limited request (or the
  bounded per-process limiter, if open question 7 chooses it). Accepted trade-offs: one
  database write in front of every `/v1` request; and an `UNLOGGED` table is empty
  after a crash, an unclean shutdown, a failover or a point-in-time restore, granting
  every caller a fresh burst.
  - **Keys.** Keys keep today's namespaces, `principal:<owner key>` (already an HMAC)
    and `ip:<HMAC of the client IP>`. The IP key is derived from
    `APP_IDENTITY_HASH_KEY` with HKDF and its own `info` label, so it differs from the
    owner-key derivation. IPv6 addresses are truncated to their /64 first. Because the
    IPv4 space is only 2^32, anyone holding the key can reverse an IP key by brute force,
    so it is **pseudonymisation, not anonymisation**: the table is personal data,
    `SECURITY.md:112` says so, and rows idle longer than the refill time are deleted
    (opportunistically on write and by the retention job), which bounds its size.
  - **Order.** A cheap bounded in-memory IP pre-limit (draft 13a) runs first, in front
    of pre-authentication and failed-authentication traffic, so an unauthenticated
    flood is shed before it writes to the database; the shared limiter runs after it.
  *Implemented in #148 (`persistence/rate_limiter.py`).* Details the design left open: the
  table holds `(key, tokens, refilled_at, allowed)`; the upsert takes its time from the
  statement's own `clock_timestamp()` and never moves `refilled_at` backwards, so a
  statement that waited on a row lock can withhold tokens but never grant extra; about one
  write in 64 deletes up to 200 idle rows, and the retention job deletes the rest (with a
  one-hour floor); the pre-limit exists only with the Postgres backend (the memory limiter
  is itself bounded) and runs for `AUTH_MODE=none` requests and failed authentication, not
  for verified callers; the app does not start with the Postgres backend and rate limiting
  enabled unless `APP_IDENTITY_HASH_KEY` is set; `security/auth.py` receives the limiters
  through `app.state.request_security` instead of importing `api/main.py`.
  - **Proxy.** IP keys are only as good as `APP_TRUSTED_PROXIES` on Render
    (open question 5): a request through Render's real proxy is keyed by the real client
    IP.
- **Failure mode: fail closed** for every guard (lease claim, budget admission, rate
  limiter, delete check), as the checkpointer already does. Every guard transaction sets
  `lock_timeout` and `statement_timeout`; a database error, a lock wait past the
  timeout or a pool checkout timeout is `503 persistence_error`, and no model call runs
  (open question 7 keeps only the rate-limiter variant open).
- **Stays per process, by design:** `APP_MAX_CONCURRENT_STREAMS` (a per-instance
  resource cap) and the JWKS cache.
- The daily retention job also deletes expired leases, ledger minutes outside the
  window and idle buckets.
- Integration tests run **two app processes** against one Postgres and show that a
  per-user cap, `thread_busy`, the budget and the rate limit hold across them, under a
  concurrency barrier (with a cap of k, exactly k of many simultaneous claims succeed;
  on one thread, exactly one).

### 9. Production settings validation

In staging and production, start-up fails when:

- `APP_ENV` was not set explicitly (decision 3 enforces this for a public bind; the
  settings test covers the image case);
- `APP_CHECKPOINTER` is `auto` (it must be `postgres` or an explicit `none`; `none` is
  logged at warning level as stateless);
- `APP_LIMITS_BACKEND` is `auto`, or `memory` in production (decision 8);
- `APP_ALLOWED_HOSTS` is empty;
- `APP_TRUSTED_PROXIES` is unset (an explicit empty list is allowed; told apart with
  `model_fields_set`, since the field defaults to an empty list,
  `config/settings.py:51`) or contains a catch-all range (`0.0.0.0/0`, `::/0`);
- `APP_RATE_LIMIT_ENABLED=false`;
- `APP_CHECKPOINTER_SETUP_ON_STARTUP=true`;
- a Postgres DSN (runtime or migration), parsed with psycopg's `conninfo_to_dict`
  rather than string matching, has an `sslmode` below `verify-full` (`verify-ca`, or
  `require` on a private network, only as open question 6 decides);
- in production, `APP_EXPOSE_API_DOCS=true`;
- the JWKS URL's host is loopback, link-local or private;
- in production, `APP_HSTS_MAX_AGE_SECONDS=0` (open question 13, resolved: the
  production API is TLS-only, so HSTS is always safe);
- `APP_LANGSMITH_CONTENT_APPROVED=true` in production without an explicit
  acknowledgement that names the approval record.

`APP_AUTH_REQUIRE_TYP=false` is deliberately not refused (open question 2, resolved):
no identity provider is chosen, and a refusal would force `at+jwt` on providers that
do not issue it. Issuer, audience, scope and expiry checks apply either way; set
`APP_AUTH_REQUIRE_TYP=true` once the provider is known to issue RFC 9068 tokens.

At every start-up the effective limit values (rate, burst, concurrency, budget,
timeouts, limits backend) are logged once. Start-up database checks (decision 15)
follow once the database is reachable. Each rule is a breaking change for existing
staging and production configurations and is listed in the CHANGELOG.

### 10. Secrets

- Runtime secrets (`OPENAI_API_KEY`, `APP_POSTGRES_DSN`, `APP_POSTGRES_MIGRATION_DSN`,
  `APP_IDENTITY_HASH_KEY`) live in Render environment groups, split per service role:
  the web service, the cron job and the Collector each get only the groups they need
  (the Collector never sees the database or provider keys). The migration DSN is in no
  group the cron job or Collector reads; see decision 15 and open question 20 for the
  web process.
- Who can read Render environment groups (workspace members, any account-wide API key)
  is listed in `OPERATIONS.md`; that set is the set that can read production secrets.
- GitHub Environments hold only the per-service deploy hooks and the smoke-test client
  credentials; no runtime secret passes through CI. Deploy credentials are rotated
  with a stated maximum age.
- `APP_IDENTITY_HASH_KEY` is identical on every replica of an environment, differs
  between staging and production, and is rotated only on exposure
  (`OPERATIONS.md:58-60`); see decision 16.

### 11. Dependency automation

`.github/dependabot.yml` for `uv`, `github-actions` and `docker` (base image digests):
weekly, grouped, with a 7-day cooldown, and never auto-merged. GitHub-owned actions are
SHA-pinned like third-party ones, each with a `# vX.Y.Z` comment. The 90-day rule for
new packages (`new-dependencies` job) is unchanged; version bumps go through all gates.
A `langgraph-checkpoint-postgres` bump also needs decision 7's rollback test.

### 12. Operations

- **Backups.** Render Postgres PITR, encrypted and keyed by Render (custody is the
  platform's, documented). The workspace plan sets the window (3 or 7 days, open
  question 1); backups hold deleted threads until they age out, which the data rights
  section of `OPERATIONS.md` states, and the restore runbook says how erasures made
  after the restore point are replayed.
- **Restore rehearsal.** Proposed: once for v0.6.0 (owner sign-off, open question 15):
  restore production's database to a new instance at a recorded point in time, under
  the same access controls and role split, point staging at it, run `setup` and the
  smoke test, record RTO and RPO in the release verification, then delete the
  restored instance and record that. Regular drills are v0.9.0.
- **Retention.** A Render cron job runs `python -m neuron_agent.persistence.cli
  prune` daily on the same image, with its own environment group and a DML-only role.
- **Smoke test.** A script hits `/health/ready` and makes one authenticated request as
  a dedicated smoke-test principal holding only `agent:invoke`, with a small token
  budget and a low output cap. Its request is stateless (no thread persisted), or it
  deletes its thread afterwards; its token is short-lived, masked in the job log and
  never stored or printed. Workload identity federation from GitHub's OIDC token to
  the IdP is preferred over a stored client secret where the IdP supports it;
  otherwise the secret's rotation is in the runbook.
- **Runbooks** in `OPERATIONS.md`: deploy, rollback (previous digest), migration
  (expand/contract, an invalid index, lock timeouts), secret and key rotation (provider
  key, database passwords for both roles, `APP_IDENTITY_HASH_KEY`, IdP signing keys,
  deploy hooks), role creation (decision 15), connection budget
  (`instances × APP_POSTGRES_POOL_MAX_SIZE` plus pre-deploy and cron, under the plan's
  `max_connections`), table growth (a size query for the checkpoint and guard tables),
  log retention and access on Render, and egress: the service can reach the internet,
  and the SSRF helper is the only control on tool fetches.
- **Alerts** added to `deploy/observability/prometheus-alerts.yaml`, each with a
  runbook entry: no metrics from any instance (absent), an instance not ready, Postgres
  errors and pool saturation (guard failures surface as `persistence_error`, which the
  existing error-class alerts cover), anomalies in `thread_busy` and
  `too_many_concurrent_runs`, leases still present past `expires_at`, and denied or
  unknown tool attempts (`CHANGELOG.md:57`). CI validates the alert rules (`promtool
  check rules`) and the Collector configuration (`otelcol-contrib validate`), which the
  repository has never run.
- **Readiness.** `/health/ready` already refreshes the JWKS itself after a failure,
  throttled (`security/auth.py:162-169`, #98), so recovery follows the platform's health
  checks, not user traffic. An instance whose cached keys still verify stays ready
  during a JWKS outage (an IdP blip must not take every instance out at once); with
  `APP_LIMITS_BACKEND=postgres` readiness includes the guard store.
- **Telemetry on Render.** One Collector, as a Render private service, receives OTLP
  from the instances and exports to a backend that evaluates the alert rules (open
  question 10). One Collector replica, so trace-ID load balancing is not needed yet.
  Logs stay JSON on stdout, collected by the platform; OTLP log export stays deferred.
  The IP log prefix key (`api/main.py:100`) stays random per process (decision 16).

### 13. Nightly eval reliability

`ai-review` and `nightly-eval` stop competing for one provider key's rate limit. The
default fix (owner sign-off, open question 17) needs no new key: a schedule gap and a
concurrency rule so `ai-review` does not run during the nightly window. A second
NVIDIA key for `ai-review` is optional, only after checking NVIDIA's terms (ADR 0007
section 6); if one is added, `ai-review` never falls back to the nightly key. The
nightly timeout gets headroom over the measured run time (about 74 minutes for 3
trials, run 39225629460). Both stay within NVIDIA's API terms.

### 14. Release gate evidence

- The live regression and security suites run with `--trials 3` and `compare` on the
  development baseline model. A run that is inconclusive or failing is recorded
  honestly with reasons, as in v0.5.0, and shipping with one needs the owner's
  sign-off (open question 18).
- The production model (OpenAI) is run at the gate if a funded key exists; otherwise
  it stays a known issue (ADR 0007 section 6).
- SLOs are re-checked on the deployed instance (staging, or production with synthetic
  traffic), not only on eval runs. Synthetic traffic means a handful of scripted
  requests to collect latency and error samples; it is **not** load testing, which
  stays v0.9.0 (open question 16).
- The gate also records: a live `make test-integration` (or the Postgres integration
  suite plus the smoke test, if no funded key exists), one linked trace, its logs and
  its metrics through the Collector, the deployed digest (with the command used), and
  the owner pre-actions (SHA-pin policy, Environments, tag ruleset, branch protection)
  as verified.

### 15. Database roles and connection security

- **Two roles per environment.** `neuron_migrator` owns the schema and is used only by
  `setup`. `neuron_app` has DML on the tables it needs (`SELECT`, `INSERT`, `UPDATE`,
  `DELETE`) and no `CREATE`, `DROP`, `TRUNCATE` or ownership; migrations emit the
  `GRANT`s, and default privileges cover tables LangGraph's `setup()` creates. The
  retention job uses `neuron_app` (it only deletes rows). Render's blueprint reference
  (`fromDatabase`) yields the database owner, and Render has no declarative role
  resource, so the roles are created once per environment by a documented operator
  step (runbook), and the runtime DSN is the app role's, pasted as a secret
  (open question 20 confirms Render allows it).
- At start-up in staging and production (after settings validation), the web process
  refuses to become ready if its runtime role is a superuser or can `CREATE` in the
  database or schema, or if the runtime and migration DSN usernames are equal.
- **Keeping the migration DSN from the web process.** Render runs the pre-deploy
  command with the web service's environment, so a migration DSN set for pre-deploy is
  visible to the web process. Proposed (open question 20): accept that, with the
  application reading it only in `persistence.cli` (a test enforces it), unless the
  proof in open question 4 shows a cheap way to run `setup` in a separate service with
  its own group.
- **TLS.** `sslmode=verify-full` (with Render's CA) is the default requirement for
  every DSN (runtime, migration, cron), unless open question 6 shows the internal
  connection is a private link where `require` is acceptable. At start-up the process
  checks `pg_stat_ssl` for its own connection and refuses to become ready without TLS.

### 16. Identity hash key consistency

- `setup` stores an HMAC check value of `APP_IDENTITY_HASH_KEY` (an HMAC of a fixed
  label, not the key) in a `neuron_meta` table the first time it runs. Every process
  compares its key's check value at start-up and refuses to become ready on mismatch,
  so a replica with a different key cannot orphan threads or split limits.
- **Implementation (#139).** "Refuses to become ready" is implemented as refusing
  start-up: the pool's first connection runs the TLS, role and identity checks, and a
  failure closes the pool, logs one stable `error_code` and stops the process, as the role
  check already did. The platform then keeps the previous release; a process that never
  starts cannot answer `/health/ready`. The app role has no access to `neuron_meta` (the
  check value is an offline oracle for a weak key), so the comparison is a migration-12
  `SECURITY DEFINER` function, `neuron_identity_status(text)`, with a pinned
  `search_path`, `EXECUTE` revoked from `PUBLIC` and granted to the app role only. It
  returns `match`, `mismatch` or `unset` for the candidate and never the stored value. The
  residual risk is a boolean guessing oracle for a holder of the app role, who already
  holds the key's consumer (the web process) and is rate-limited by the database; keys
  are at least 32 characters.
- Rotating the key is a maintenance operation, not a rolling deploy: scale the web
  service to zero, update the key, update the check value, start again. It resets
  owner keys, budgets, rate-limit buckets and leases, and orphans existing threads
  (`OPERATIONS.md:58-60`).
- The IP log prefix key (`api/main.py:100`) stays random per process: a stable key
  would make IP prefixes linkable over time; the rate limiter derives its own key
  (decision 8).

### Amendments to earlier ADRs

This ADR changes decisions that put shared backends out of scope or kept staging and
production lenient. The documents themselves are edited by the issues that implement
each change, not by this ADR:

| Document | Current text | Amended by |
| --- | --- | --- |
| ADR 0004, "v0.4.0 Resource Limits" and Consequences | "each replica enforces its own limits; cross-replica coordination remains out of scope"; a shared backend means "e.g. Redis" and needs "no other call site changes" (`:73`) | Decision 8: Postgres-backed rate limits and budget, async Protocols with the listed call sites; proxy-header handling (decision 3) |
| ADR 0005, decision 1 | `auto` resolves to `none` in staging and production to keep upgrades safe; schema setup is an explicit operator step (`make db-setup`) with an opt-in start-up setup | Decision 9: `auto` refused in staging and production; decision 7: setup is the pre-deploy step under the migrator role, start-up setup refused there |
| ADR 0005, decision 5 and Consequences | the `thread_busy` guard is process-local and doesn't coordinate across replicas | Decision 8: run leases |
| ADR 0006, Non-goals | "Distributed rate limiting or concurrency coordination; issue #56 retains that deployment decision" (#56 chose in-process, v0.4.0) | Decision 8 |
| `OPERATIONS.md:365-369`, `:468`, `:472`, `:519` | per-process guards; Uvicorn `--forwarded-allow-ips`; "a shared Redis/Postgres backend is intentionally out of scope"; "limits are per-instance" | Decisions 3 and 8 |
| `ARCHITECTURE.md:189`, `:284`; `SECURITY.md:110`, `:112` | per-process guards and limiter; key exposure links threads only | Decision 8 (IP keys are pseudonymous personal data) |
| AGENTS.md env-read rule | one exception, `observability/langsmith_governance.py` | Decision 3: `observability/telemetry.py:185` added as a second exception |

### 17. Free-tier profile (staging and demo only)

**Decided (owner, 2026-10-20):** only Render's free plans are available for now. They
are a staging and demo target, **not** a production reference; decisions 1-16 stay the
production design and need paid services. Facts below are from Render's documentation
(`render.com/docs/free`, `/docs/deploys`) as read on 2026-10-20 and are not yet proven
on a deployed service.

| Area | Free plan | Consequence |
| --- | --- | --- |
| Pre-deploy command | Paid web services, private services and workers only | Decision 7's pre-deploy step does not exist; migrations run as an operator step (below) |
| Instances | One; no scaling | Run `APP_LIMITS_BACKEND=memory` with one instance, as decision 1 already allows for staging |
| Spin-down | After 15 min idle; about 1 min to wake; suspended after 750 instance hours a month | Not a place for SLO or latency evidence; the smoke test must tolerate a cold start |
| Disk | None | Nothing is written locally |
| Postgres | Expires 30 days after creation (14-day grace, then deleted); 1 GB; no backups or PITR; no managed pooler; one free database per workspace | Staging data is disposable; no restore rehearsal here; the database is recreated before expiry |
| Database TLS | Internal connections do not support `verify-ca` or `verify-full`; external connections need `sslmode=require` | Decision 9's verified-TLS rule cannot be met; see below |

Rules for the profile:

- **Migrations.** Run `python -m neuron_agent.persistence.cli setup` from a manual
  GitHub Actions job (or `make db-setup`) against the database's connection string,
  before promoting a digest. Start-up setup stays refused. The job needs the database's
  external connection, which Render only allows if the database's allow-list admits the
  runner; not yet proven, and decision 1's empty allow-list does not hold here.
- **Roles.** Whether `neuron_migrator` and `neuron_app` can be created is unknown
  (open question 20). Until proven, one role is used and the "runtime role must not own
  the schema" check is skipped only when `APP_ENV=staging`; it stays enforced in
  production.
- **Database TLS.** `require` is accepted in staging only, as a documented exception to
  decision 9; production still needs verified TLS.
- **Promotion.** There is no production on the free plan. The pipeline stops at staging,
  and the release gate cannot claim a production deployment, a restore rehearsal or SLO
  evidence from it. Release notes must say so.
- **Deploy hooks** and rollback to the last two deploys are available. Whether an
  image-backed (prebuilt image) service is allowed on the free plan is not stated in
  the documentation and must be proven first.

### Implementation note: `render.yaml` assumptions (#150)

The owner's standing direction is to assume Render facts work and fix on the first deploy. The Blueprint keys were checked against Render's Blueprint reference and its published JSON schema (`render.com/schema/render.yaml.json`, read 2026-10-26; `render.yaml` validates against it). Everything else below is assumed, not proven, and not yet exercised by a Render validation or a staging deploy:

- `preDeployCommand` works on `runtime: image` services, runs with the web service's environment, and cancels the deploy on a non-zero exit (open questions 4 and 20). The reference does not say.
- `image.url` accepts `ghcr.io/md-nisar/neuron@sha256:<digest>`; the file ships an untagged URL that must be replaced before the first sync. A private package needs a registry credential (open question 14).
- A cron job accepts `runtime: image` with `dockerCommand`, and a private service can run the Collector image with a secret file at `/etc/secrets/otel-collector.yaml` and listen on 4318 at `http://<service-name>:4318`.
- `sync: false` is not allowed in an environment group (documented), so groups hold non-secret settings and every secret is a service-level `sync: false` variable. Secret groups created in the Dashboard are not used.
- `ipAllowList: []` blocks external connections but keeps internal ones (documented for external only).
- Plan names (`starter`, `basic-256mb`, `basic-1gb`) and each plan's `max_connections` are unconfirmed (open question 1); services share one region (`oregon`) so the private network applies.
- Default hostnames are `<service-name>.onrender.com` for `APP_ALLOWED_HOSTS`; `APP_TRUSTED_PROXIES=[]` until the proxy range is confirmed (open question 5); `APP_HSTS_MAX_AGE_SECONDS=31536000` in production (open question 13).
- Open question 12 is answered by one `render.yaml` defining both environments.
- Amendment to decision 1: `maxShutdownDelaySeconds` is 180, not 150. With OpenTelemetry on and the Collector down the shutdown needs 5 + 120 + 10 + 20 = 155 s plus the pool close; the blueprint test requires the value to exceed that sum (maximum 300).
- `prune` loads the full settings, so the cron job also holds the provider key, identity key, issuer and JWKS URL, though it only deletes rows.
- The staging Blueprint uses paid plans so the pre-deploy path is exercised; decision 17's free profile needs the edits listed in `OPERATIONS.md`.

## Migration and rollout

1. Image, entrypoint and pipeline first (decisions 2, 3, 6), deploying to staging with
   one instance and `APP_LIMITS_BACKEND=memory`, only after open question 4's proof.
2. Versioned migrations and the role split (decisions 7, 15), then the guard Protocols
   and tables (decision 8), each table landing with its expand-only migration.
3. Settings hardening (decision 9) last among code changes, since it breaks existing
   staging and production configuration. Breaking for operators:
   - `APP_ENV` must be set explicitly for a public bind;
   - `APP_CHECKPOINTER` and `APP_LIMITS_BACKEND` must be set explicitly, and
     `memory` limits are refused in production;
   - `APP_ALLOWED_HOSTS` and `APP_TRUSTED_PROXIES` must be set; rate limiting can't be
     disabled; start-up setup is refused; DSNs need verified TLS; the runtime role must
     not own the schema; API docs stay hidden in production.
   - The image runs `neuron-api`; `HOST`/`PORT` become `APP_HOST`/`APP_PORT` (Render's
     `PORT` still works).
   - If proxy headers move to the app only (open question 5), Uvicorn's
     `--forwarded-allow-ips` no longer applies.
   - `RateLimiter` and `TokenBudget` are async (code that implements them changes).
4. Staging switches to `APP_LIMITS_BACKEND=postgres`. Production goes live with two
   instances only after the two-process tests pass in CI and staging has run the same
   digest.
- New runtime dependencies: none. CI gains pinned actions for buildx, the scanner and
  attestations, and pinned `promtool` and `otelcol-contrib` binaries.

## Non-goals (v0.6.0)

- Kubernetes manifests, Helm charts or other platforms' configuration.
- Redis or any new stateful service.
- Multi-region deployment, autoscaling policy tuning.
- Load testing, capacity planning and disaster-recovery drills beyond one restore
  rehearsal (v0.9.0, `docs/ROADMAP.md:11`; open questions 15 and 16).
- Rate limits, budgets and the input policy on Agent Server (known issue).
- LLM-judge quality evals (#103) and the feedback endpoint (#104), both still
  deferred.
- SLSA Build L3, cosign signatures, hardened base images.
- Billing-grade or estimated cost (still no verifiable, dated price data); re-deferred
  to v0.7.0, and `CHANGELOG.md:28,62` updated to say so.

## Consequences

- Every production image is reproducible from the lockfile, scanned and attested by a
  pinned workflow, and production runs exactly the digest staging ran.
- Limits mean what they say across replicas, at the cost of a database round trip per
  request and per run, and of fail-closed behaviour when Postgres is down (the
  checkpointer already fails then).
- neuron owns five small tables (`neuron_migrations`, `neuron_meta`, run leases, the
  token ledger and rate-limit buckets) and a minimal migration list. AGENTS.md and
  CLAUDE.md require an ADR before adding custom persistence; this ADR is that ADR, for
  these tables only.
- The web process no longer owns its schema; operators create two roles per
  environment by hand once.
- Deploys need a paid Render plan (pre-deploy commands); the free plan is a
  staging and demo profile only (decision 17) and Postgres even for a
  stateless deployment that uses the shared guards; the full topology costs about
  $56-63/month plus storage, workspace plan and telemetry backend (perishable).
- Operators get stricter start-up validation and must update existing staging and
  production settings.
- A crashed replica's leases block its users' threads for up to the run timeout plus
  15 s.
- Rotating `APP_IDENTITY_HASH_KEY` needs a short maintenance window.

## Open questions for review

Questions 4-8, 19 and 20 are security-relevant and **block** the drafts they gate
(listed in draft 1). Questions 15-18 are owner sign-offs that this ADR does not decide.

On 2026-10-20 the owner decided questions 5, 7, 8 and 19 and signed off 15-18, each
as recommended below (marked **Decided**). Questions 4, 6 and 20 still block: they
need facts from the Render account. Also on 2026-10-20 the owner said only free Render
plans are available for now: decision 17 records the free-tier profile and what it
answers for 4, 6 and 20 (pre-deploy is paid-only; internal connections lack verified
TLS; roles unknown).

1. **Render workspace and Postgres plan.** Hobby (3-day PITR) or Pro (7-day PITR), and
   which Postgres plan (its `max_connections` sets the pool budget). The Pro price is
   not in the research; the owner confirms the priced topology is acceptable.
2. **Identity provider for staging and production.** `APP_AUTH_MODE=jwt` is required
   there; which IdP issues tokens; separate tenants (or at least distinct audiences)
   per environment; whether it issues `typ: at+jwt`; and whether the smoke-test
   principal can use workload identity federation from GitHub OIDC instead of a stored
   client secret (recommended).
3. **Provider keys.** Production needs a funded OpenAI key; staging could use the
   NVIDIA development model (no user data in staging). Without an OpenAI key,
   production can deploy but not serve.
4. **Deploy by digest on Render (blocking).** Render's deploy hooks accept an `imgURL`
   with a tag or digest and are per-service secrets (Render addendum in the research
   notes). Not yet shown: whether a hook deploy of a prebuilt image runs the pre-deploy
   command and cancels on its failure; how the pipeline learns a deploy is live
   without an account-wide API key (options: Render API with a key isolated in its own
   workspace, or polling `/health/ready` for a revision field); and whether a Render
   rollback re-runs the pre-deploy command. Recommendation: per-service hooks, and draft
   1 records a throwaway-service proof; if pre-deploy does not run, choose decision 6's
   fallback before draft 14.
   **Assumed (owner, 2026-10-21), not proven:** the free plan can run an image-backed
   service and a deploy hook can deploy a specific digest; there is no pre-deploy
   command, so migrations run as the operator step in decision 17 (a documented
   exception to decision 6's fallback, for free-plan staging only); the pipeline
   learns a deploy is live by polling `/health/ready` for the running revision (a
   revision field is added with the pipeline work). Render already builds this
   repository's `Dockerfile` from a public repository URL, which is the fallback if
   image-backed services are not available on the free plan. If an assumption is
   wrong, it is fixed on the first staging deploy and this entry is updated.
5. **Proxy headers (blocking).** Render's proxy addresses for `APP_TRUSTED_PROXIES`,
   and whether the app or Uvicorn parses `X-Forwarded-For` (proposed: the app only,
   rightmost untrusted hop).
   **Decided (owner, 2026-10-20):** the app only, rightmost untrusted hop; Uvicorn
   does not parse proxy headers. Render's proxy addresses are still to be confirmed
   on the deployment.
6. **Database TLS and pooling on Render (blocking).** Whether Render's internal
   connection string supports `sslmode=verify-full` with a published CA (or only
   `require`, and whether the internal network counts as a private link), and whether
   any pooler sits in front (affects `prepare_threshold=0` and the migration DSN).
   **Assumed (owner, 2026-10-21), not proven:** the internal connection string supports
   `sslmode=require` only (Render's documentation says `verify-ca` and `verify-full`
   are not supported internally) and no pooler sits in front on the free plan. The
   `require` exception applies to free-plan staging only (decision 17); production
   still needs verified TLS and is not deployed on the free plan.
7. **Guard failure mode (blocking).** Fail closed for every guard is decided (decision
   8). Still open: whether the per-request rate-limit write is acceptable or the rate
   limiter stays a bounded per-process one with "divide by instances" documented (the
   owner decision allows either). Recommendation: the Postgres limiter.
   **Decided (owner, 2026-10-20):** the Postgres limiter.
8. **Lease expiry (blocking).** Run timeout plus 15 s, no heartbeat and no fencing
   (proposed, with the boundary test), or a shorter expiry with a heartbeat.
   **Decided (owner, 2026-10-20):** run timeout plus 15 s, no heartbeat and no
   fencing, with the boundary test.
9. **Scanner.** Grype (proposed) or Trivy.
10. **Telemetry backend.** Where the Collector exports and the alert rules are
    evaluated for the reference deployment, and its cost; one Collector per
    environment or a shared one; and whether the Collector image is built here (its
    config baked in) or configured with Render secret files.
11. **Staging trigger.** Every push to `main` (proposed) or manual.
12. **Blueprint layout.** One `render.yaml` defining both environments, or one per
    environment.
13. **HSTS.** Whether production must set `APP_HSTS_MAX_AGE_SECONDS` (Render serves
    HTTPS; whether it redirects plain HTTP was not checked).
14. **GHCR visibility and attestations.** A public package (Render pulls without
    credentials; only with a public repository and draft 2's layout test passing) or a
    private one with a registry credential in Render; and confirming artifact
    attestations are available for the repository's visibility and plan.
15. **Restore rehearsal scope (owner sign-off).** One restore rehearsal with RTO/RPO in
    v0.6.0 (proposed, decision 12), or all restore work in v0.9.0 with DR.
    Recommendation: keep the one rehearsal; a backup that was never restored is not a
    backup. **Decided (owner, 2026-10-20):** one rehearsal in v0.6.0.
16. **SLO re-check (owner sign-off).** Confirm that re-checking SLOs with a few
    synthetic requests on the deployed instance is enough for v0.6.0, knowing it is not
    load testing (v0.9.0). Recommendation: yes, with the sample size recorded.
    **Decided (owner, 2026-10-20):** yes, with the sample size recorded.
17. **Nightly eval and `ai-review` keys (owner sign-off).** Default: a schedule gap and
    concurrency rule so `ai-review` does not run during the nightly window, no new key.
    A second NVIDIA key only after checking NVIDIA's terms (ADR 0007 section 6).
    Recommendation: the default. **Decided (owner, 2026-10-20):** the default; no
    new key.
18. **Inconclusive or failing `compare` at the gate (owner sign-off).** Whether v0.6.0
    may ship with an inconclusive or failing live `compare`, recorded as a known issue
    as in v0.5.0. Recommendation: allow it only for infrastructure errors, with the
    owner's sign-off recorded in the release verification. **Decided (owner,
    2026-10-20):** allowed only for infrastructure errors, with the sign-off recorded.
19. **Advisory locks (blocking, owner to confirm).** That transaction-level advisory
    locks (`pg_advisory_xact_lock`) for lease claims, and one session-level advisory
    lock on the direct, never-pooled migration connection, are within the "no session
    advisory locks" decision. Recommendation: yes; the alternative for migrations is
    `LOCK TABLE neuron_migrations`, which cannot cover the concurrent index builds.
    **Decided (owner, 2026-10-20):** yes; both are within the decision.
20. **Database roles on Render (blocking).** Whether Render Postgres lets the owner
    create `neuron_migrator` and `neuron_app` roles with the needed grants, and how the
    migration DSN is kept from the web process when pre-deploy shares its environment
    (proposed: accept it, with a test that only `persistence.cli` reads it).

## References

- `docs/research-notes.md`, "v0.6.0 Research: Production Deployment".
- https://render.com/docs/deploys, https://render.com/docs/deploy-hooks,
  https://render.com/docs/cronjobs, https://render.com/docs/private-services,
  https://render.com/docs/postgresql-refresh
- https://github.com/Md-Nisar/neuron/actions/runs/39225629460 (last nightly eval run)
- https://docs.github.com/en/actions/how-tos/secure-your-work/use-artifact-attestations/use-artifact-attestations
- https://docs.github.com/en/actions/reference/workflows-and-actions/deployments-and-environments
- https://docs.docker.com/build/ci/github-actions/attestations/
- https://www.postgresql.org/docs/current/explicit-locking.html
- https://www.postgresql.org/docs/current/sql-createtable.html
- https://www.postgresql.org/docs/current/sql-createindex.html
- https://www.pgbouncer.org/features.html
- https://fastapi.tiangolo.com/deployment/docker/
- https://sre.google/sre-book/data-integrity/
- ADR 0001, ADR 0004, ADR 0005, ADR 0006, ADR 0007.

   **Assumed (owner, 2026-10-21), not proven:** the owner can create `neuron_migrator`
   and `neuron_app` and grant to them. If Render denies `CREATE ROLE`, free-plan
   staging runs with one role and skips the "runtime role must not own the schema"
   check under `APP_ENV=staging` only (decision 17); production keeps the split.