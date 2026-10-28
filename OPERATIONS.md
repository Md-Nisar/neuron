# Operations

## Deployment

Two deployment paths are supported: the self-hosted container (`Dockerfile`) deployed on Render by the `render.yaml` Blueprint below, and LangGraph Agent Server/LangSmith using `langgraph.json` (not deployed, not release-gating). Production deployments must inject secrets through the platform secret manager.

### Reference deployment (Render)

`render.yaml` (ADR 0008 decisions 1, 10 and 15) defines both environments. Everything in it is an assumption about Render until a staging deploy from it reaches `ready` and Render's validation passes; neither has been done (#150 acceptance criterion 2).

| Piece | Staging | Production |
| --- | --- | --- |
| Web service (image `ghcr.io/md-nisar/neuron`) | `neuron-staging`, 1 instance | `neuron-production`, 2 instances |
| Health check, pre-deploy | `/health/ready`; `python -m neuron_agent.persistence.cli setup` | same |
| `maxShutdownDelaySeconds` | 180 | 180 |
| Postgres 16 | `neuron-staging-db`, `ipAllowList: []` | `neuron-production-db`, `ipAllowList: []` |
| Retention | cron `neuron-prune-staging`, daily 03:17 UTC, `... cli prune` | `neuron-prune-production` |
| Collector (private service) | `neuron-collector-staging` | `neuron-collector-production` |
| Limits backend | `postgres` | `postgres` |

Plan names (`starter`, `basic-256mb`, `basic-1gb`) are placeholders for the owner's choice (ADR 0008 open question 1). Free plans suit a disposable staging only (decision 17): they have no pre-deploy command or cron plan, so for a free staging remove `preDeployCommand` and the cron service, run `setup` and `prune` by hand against the external connection, and accept `sslmode=require`.

**First deploy, in order**

1. Pick an image digest built from `main` and verify it (see "Published image and attestation"). Replace each `image.url` of the three web and cron services with `ghcr.io/md-nisar/neuron@sha256:<digest>`. A private package also needs a registry credential in the Render workspace (open question 14).
2. Create the Blueprint in Render. It prompts for every `sync: false` value; leave the DSNs for step 4 (or enter placeholders and edit them later) because the roles do not exist yet.
3. **Create the database roles**, once per environment, with the owner connection string from the Render Dashboard (`psql` from a shell inside Render, since `ipAllowList` is empty): run the `roles.sql` in "Database roles" (`neuron_migrator`, `neuron_app`; choose both passwords yourself).
4. Set the secrets in the Dashboard. Each DSN is the **role's**, not the owner's, with `sslmode` in the string (`verify-full` in production; staging also accepts `require`; the Render internal connection string supports `require` only, so staging only until verified TLS is proven):
   - web: `APP_POSTGRES_DSN` (`neuron_app`), `APP_POSTGRES_MIGRATION_DSN` (`neuron_migrator`), `APP_IDENTITY_HASH_KEY` (32+ characters, different per environment, identical on every instance), `OPENAI_API_KEY`, `APP_AUTH_ISSUER`, `APP_AUTH_JWKS_URL`.
   - cron: the same except the migration DSN. `prune` loads the whole settings, so it needs the identity key, the issuer, the JWKS URL and the provider key too.
   - Collector: `OTEL_BACKEND_ENDPOINT` and optionally `OTEL_BACKEND_AUTH_HEADER`, plus a secret file named `otel-collector.yaml` holding `deploy/observability/otel-collector.yaml`.
5. Deploy. The pre-deploy `setup` runs as the migrator and grants the app role; a failure cancels the deploy and the previous release keeps serving. Run the smoke test (below).

**Settings the Blueprint fixes.** Non-secret settings live in environment groups, one per role and environment (`neuron-web-*`, `neuron-cron-*`, `neuron-collector-*`): `APP_ENV`, `APP_AUTH_MODE=jwt`, a different `APP_AUTH_AUDIENCE` per environment, `APP_CHECKPOINTER=postgres`, `APP_LIMITS_BACKEND=postgres`, `APP_EXPOSE_API_DOCS=false`, `APP_ALLOWED_HOSTS`, `APP_TRUSTED_PROXIES=[]`, `APP_HSTS_MAX_AGE_SECONDS` (production), `APP_POSTGRES_POOL_MAX_SIZE` and `APP_OTEL_*`. Render does not allow `sync: false` in a group, so every secret is a service-level `sync: false` variable. Edit `APP_ALLOWED_HOSTS` to the real hostnames (the defaults assume `<service>.onrender.com`; a custom domain replaces them). `APP_TRUSTED_PROXIES` is `[]` (forwarded headers ignored, so per-IP limits see Render's proxy address) until Render's proxy range is confirmed (open question 5). `tests/unit/test_render_blueprint.py` checks the file: it holds no secret value, no `fromDatabase`, no unknown `APP_*` key, a shutdown delay above the drain formula, and settings that pass `Settings` validation.

**Connection budget.** `max_connections` is set by the database plan; read it with `SHOW max_connections;` (not taken from documentation here). Per environment the peak is

`web instances x APP_POSTGRES_POOL_MAX_SIZE + pre-deploy + cron + admin headroom`

Production steady state: 2 x 10 = 20. During a rolling deploy old and new instances overlap, so budget 4 x 10 = 40, plus `setup` (up to 2), `prune` (a pool of 2) and 5 for admin access: 49 connections must fit under `max_connections`. If not, lower `APP_POSTGRES_POOL_MAX_SIZE` in the group or raise the database plan. More instances multiply the first term.

**Who can read the secrets.** Environment variables and groups on Render are readable by every workspace member with access to the service and by any account-wide API key; that set can read production secrets, including the app DSN, the identity key and the provider key. The migration DSN sits in the web service's environment because pre-deploy shares it (ADR 0008 open question 20); only `persistence.cli` reads it, and a test pins that. Keep the workspace membership list short, keep production and staging in separate workspaces where the account allows, and rotate secrets when a member leaves. The Collector and cron services reference no web group and hold no web-only secret.

### Container image

The `Dockerfile` builds a two-stage image (ADR 0008 decision 2):

- **Contents.** `/app/.venv` only: the locked dependencies and the non-editable installed
  `neuron_agent` package, whose prompts are package data. There is no source tree, `tests/`,
  `evals/`, `.git`, `.env*` or key file in the image, and the build context is an allowlist
  (`.dockerignore`: `pyproject.toml`, `uv.lock`, `README.md`, `LICENSE`, `NOTICE`, `src/`).
- **Reproducible.** `uv sync --locked --no-dev --no-editable` has no fallback: a `uv.lock`
  that is out of date with `pyproject.toml` fails the build. Both bases
  (`ghcr.io/astral-sh/uv:0.13.5-python3.13-trixie-slim` and `python:3.13-slim-trixie`) are
  pinned by index digest; the tag stays beside the digest so Dependabot can bump both.
- **Runtime.** User and group `10001:10001` (non-root), `HEALTHCHECK` on `/health/live` at the
  configured port, `CMD ["neuron-api"]`. It reads `APP_HOST`/`APP_PORT` (image defaults
  `0.0.0.0`/`8000`; `PORT`, which Render sets, also works and wins), runs one process with
  `timeout_graceful_shutdown = APP_RUN_TIMEOUT_SECONDS + 10`, and refuses to start on a
  non-loopback host unless `APP_ENV` is set explicitly. Compose sets `APP_ENV=development` and publishes only on `127.0.0.1`.
  Accepted residual risk: an explicit `APP_ENV=development` on a public host still serves
  unauthenticated. A bare `PORT` wins over `APP_PORT`; an invalid port fails start-up.
  The `HEALTHCHECK` probes `127.0.0.1`, so `APP_HOST` must stay `0.0.0.0` or be reachable on
  loopback for the image. `neuron-api` and `make api` leave proxy-header parsing to
  `_client_ip`; a custom `uvicorn` `CMD` must pass `--no-proxy-headers`.
- **Labels.** `org.opencontainers.image.source`, `.revision` (build argument `GIT_SHA`) and
  `.version` (build argument `VERSION`; default is the release in `pyproject.toml`). Build
  arguments are recorded by provenance, so never pass a secret as one.

Build it from the repository root; settings and secrets arrive as environment at run time:

```bash
docker build \
  --build-arg GIT_SHA="$(git rev-parse HEAD)" \
  --build-arg VERSION="$(uv version --short)" \
  -t neuron-agent .
```

The `docker-build` workflow builds the image on every change that can affect it, checks its
layout with `tests/integration/test_image_layout.py` (run it locally with
`NEURON_TEST_IMAGE=neuron-agent uv run pytest tests/integration/test_image_layout.py -m docker`)
and checks that a stale `uv.lock` fails the build. It pushes nothing.

### Deploy pipeline

`deploy.yml` promotes one attested digest and never rebuilds it (ADR 0008 decision 6, steps 5 to 7). After a successful `image-publish` run on `main`, the `staging` job requires a green `ci` on the commit, reads the digest from that run's `image-digest` artifact, verifies the attestation (signer `image-publish.yml`, source ref `refs/heads/main`, SLSA provenance), calls every staging service's deploy hook with that digest, waits `DEPLOY_SETTLE_SECONDS` (default 300) and runs `scripts/smoke_test.py`. A `v*` tag starts the `production` job in the `production` Environment (required reviewer): it checks the tag is on `main`, equals the `pyproject.toml` version and has a `CHANGELOG.md` section, finds the `image-publish` run that built the tagged commit, requires its staging run (titled `staging <run id>`) to have passed, re-verifies the attestation, re-scans the digest (reported only), deploys every production service with the same digest, smoke-tests, and only then publishes the GitHub Release (draft first) from the changelog section.

Set per Environment (`staging`, `production`): secret `DEPLOY_HOOKS` (JSON `{"<service name>": "<deploy hook URL>"}`, the names in `render.yaml`), secret `SMOKE_TEST_TOKEN`, variable `SMOKE_TEST_URL`. No Render API key is used. Not proven (Render facts are assumed, and no real deployment has run this): that a hook accepts `imgURL` for an image service, that the fixed settle wait covers a rolling deploy, and that the pre-deploy `setup` ran (the smoke test's readiness check fails closed when the guard tables are missing, but Render's own deploy status is not read).

### Shutdown

On SIGTERM `neuron-api` (a `uvicorn.Server` subclass overriding `handle_exit`, the handler Uvicorn 0.53 installs for SIGINT and SIGTERM; ADR 0008 decision 4) does this, in order:

1. `/health/ready` returns `503 {"status": "not_ready"}` at once, and `service_draining` is logged once with `in_flight_runs`. Take the instance out of rotation on that probe.
2. For `APP_SHUTDOWN_DRAIN_SECONDS` (default `5`, `0`-`60`) Uvicorn keeps accepting connections and new runs are still served, while the load balancer converges. Open streams keep running for the whole delay (readiness is already 503); when the delay ends sse-starlette ends them with `service_shutting_down` within 2 s. A stream opened during the delay is cut shortly after the delay ends.
3. After that delay Uvicorn stops accepting, and any `POST /v1/agent/*` on a connection still open gets `503 {"detail": "service_shutting_down"}` with `Retry-After: 1`.
4. In-flight `invoke` runs finish, for up to `APP_RUN_TIMEOUT_SECONDS + 10` s (Uvicorn's graceful timeout, counted from step 3). A run still going then is cancelled: its partial token usage is charged and its thread and per-user slot are released. A SIGKILL skips this; lease expiry (ADR 0008 decision 8) covers it once the Postgres guards exist.
5. The process exits `0`. A second SIGTERM, or a SIGINT, skips the remaining delay and starts Uvicorn's graceful shutdown at once (no force); only a SIGINT while shutdown has already started forces the exit. With `--reload` (development) the delay is 0.

Signal-driven drain is POSIX only: Windows cannot deliver SIGTERM to a process, so the real-signal tests are skipped there (the target platform is Linux).

The platform's termination grace must exceed `APP_SHUTDOWN_DRAIN_SECONDS + APP_RUN_TIMEOUT_SECONDS + 10`, plus the work after the last request ends: the lifespan closes the database pool, and with `APP_OTEL_ENABLED=true` the telemetry flush can take up to `2 * APP_OTEL_EXPORT_TIMEOUT_SECONDS` (default 10 s each) when the Collector is down. Defaults: 5 + 120 + 10 = 135 s, or 155 s with OpenTelemetry on and the Collector down, plus the pool close. `render.yaml` therefore sets `maxShutdownDelaySeconds: 180` (Render allows 1 to 300), not the 150 first proposed, which had no margin with OpenTelemetry on and the Collector down. The app cannot read the platform value; `tests/unit/test_render_blueprint.py` enforces the ordering. Raising any of these settings means raising the grace.

Known gaps, to revisit when the Postgres guards land (#136):

- The test that cancels a run at the graceful timeout cancels at service level, not through Uvicorn's request task and its middleware layers. `_finish_usage` is not shielded from a second cancellation, and lifespan shutdown closes the pool while cancelled tasks' `finally` blocks may still run. All harmless with the in-memory guards.
- `503 service_shutting_down` responses count as 5xx in the availability SLO burn on every deploy.

### Published image and attestation

Every push to `main` runs `image-publish` (ADR 0008 decision 6): it builds with buildx (`provenance: mode=max`, SBOM), pushes `ghcr.io/md-nisar/neuron:sha-<commit>`, scans the pushed digest (SECURITY.md, "Image vulnerabilities"), and only then attests that digest with `actions/attest` (SLSA build provenance, stored in the registry). The run summary and the `attest` job's `digest` output give the digest. Deploy by digest, never by the mutable `sha-` tag. Pull requests build without pushing. The package follows GHCR's default visibility (private for a new package); nothing in the workflow changes it (ADR 0008 open question 14 is undecided).

Verify an image before using it (needs the `gh` CLI and read access to the package):

```bash
gh attestation verify oci://ghcr.io/md-nisar/neuron@<digest> -R Md-Nisar/neuron \
  --signer-workflow Md-Nisar/neuron/.github/workflows/image-publish.yml \
  --source-ref refs/heads/main --predicate-type https://slsa.dev/provenance/v1
```

It must succeed for a digest built from `main`. The same command with another `--signer-workflow` (for example `.../docker-build.yml`) must fail; if it passes, stop and treat the pin as broken. A digest without a passing verification never deploys.

An attestation proves where and how the image was built, not that tests passed: `image-publish` does not run the `ci` gates, so check for a green `ci` on the commit before promoting a digest. `sha-<sha>` is a mutable tag (a re-run of the workflow re-points it to a new digest), so deploy by digest only. The workflow never cancels a run in progress and keeps only the newest pending run per concurrency group, so an intermediate commit on `main` may have no published image.

## Health Checks

- `/health/live`: process is serving requests.
- `/health/ready`: application configuration loaded; not draining for shutdown (see Shutdown); with `APP_CHECKPOINTER=postgres` or `APP_LIMITS_BACKEND=postgres`, the database reachable (and, with the latter, the guard tables created by `setup` present, so an unmigrated database is not ready); and in jwt mode, no unresolved JWKS fetch failure while no usable cached keys remain. Returns `503 {"status": "not_ready"}` otherwise, so take the instance out of rotation. After a failed fetch, a probe retries the JWKS at most once per 5 seconds per process, bounded by `APP_AUTH_JWKS_TIMEOUT_SECONDS`; a healthy instance makes no IdP call (see Signing keys and JWKS caching).

Health checks intentionally avoid LLM calls to prevent cost spikes and dependency coupling.

Separately from the endpoint, each instance evaluates the same readiness every 15 seconds in a background task and exports it as the `neuron.service.ready` gauge (1 ready, 0 not), which the `NeuronInstanceNotReady` and `NeuronNoMetrics` alerts read (see "Service level objectives"). No external prober is needed, and probe traffic does not move the gauge. The gauge reports nothing while the instance is draining and once its last evaluation is more than 60 seconds old (a hung event loop), so a terminating or hung instance goes quiet instead of reading 0 or a frozen 1.

## Identity Provider

Staging and production require `APP_AUTH_MODE=jwt`: every `/v1/*` request carries an OAuth 2.0 access token that is a signed JWT (RFC 9068), issued by one OIDC-compliant identity provider (IdP). Neuron never issues tokens or stores users (ADR 0006).

### Connecting an IdP

1. **Register the API** as a resource (API, audience or resource server, depending on the IdP), with an identifier such as `neuron-api`. Access tokens must carry it in `aud`, be JWTs (not opaque tokens), be signed with RS256/384/512 or ES256/384/512 with a `kid` header, and contain all of `iss`, `aud`, `sub`, `exp`, `nbf` and `iat`; a token missing any of them is rejected (`auth_failed`, `reason="invalid_claims"`). Check that the IdP includes `nbf`, since some omit it by default. ID tokens carry the client ID in `aud`, so they are rejected.
2. **Define the scopes** `agent:invoke`, `agent:approve` (only if you use tools that need approval), `threads:read`, `threads:write` (rename), `feedback:write` (rate answers), `threads:delete` and `tools:calculator` (see README "Authentication"), and grant them to the client applications that need them. If the IdP models permissions as roles instead, map roles to scopes with `APP_AUTH_ROLES_CLAIM` and `APP_AUTH_ROLE_PERMISSIONS`; a role grants nothing unless it's mapped.
3. **Service accounts** use the client-credentials grant and the same scopes. There is no separate API-key path.
4. **Configure Neuron** from the IdP's discovery document (`<issuer>/.well-known/openid-configuration`): `issuer` becomes `APP_AUTH_ISSUER` (compared exactly, including any trailing slash) and `jwks_uri` becomes `APP_AUTH_JWKS_URL`.

```text
APP_AUTH_MODE=jwt
APP_AUTH_ISSUER=https://idp.example.com/
APP_AUTH_AUDIENCE=neuron-api
APP_AUTH_JWKS_URL=https://idp.example.com/.well-known/jwks.json
APP_AUTH_ISSUER_ID=primary
APP_IDENTITY_HASH_KEY=<at least 32 random characters, from the secret manager>
# Only if permissions arrive as roles:
APP_AUTH_ROLES_CLAIM=roles
APP_AUTH_ROLE_PERMISSIONS={"neuron-user":["agent:invoke","threads:read","threads:delete"]}
```

5. **Check it:** call `/v1/me/threads` with a token from the IdP; expect `200`. A `401` is audited as `auth_failed` with a `reason` (`wrong_issuer`, `wrong_audience`, `expired`, ...) that names the mismatch.

`.env.example` lists every other `APP_AUTH_*` setting with its bounds. One issuer per deployment is supported.

### Signing keys and JWKS caching

- Fetched keys are cached for `APP_AUTH_JWKS_CACHE_SECONDS` (default `300`) per process; each fetch times out after `APP_AUTH_JWKS_TIMEOUT_SECONDS`.
- A token with an unknown `kid` triggers a refetch, but not always at once. PyJWT forces a refetch at most once per 30 seconds after any successful fetch (including the first one and cache-expiry fetches), so a key published less than 30 seconds after a fetch is rejected (`401`, `auth_failed` with `reason="unknown_signing_key"`) until that window ends; the release gate measured 30.2 s with default settings. On top of that, when a refetch succeeds but still lacks the `kid`, further unknown-`kid` refetches wait one second per process, so forged `kid`s can't hammer a reachable IdP. While the IdP is unreachable there is no such cooldown: each request that needs a fetch tries one, serialized per process and bounded by `APP_AUTH_JWKS_TIMEOUT_SECONDS`.
- **Rotation:** publish the new key in the JWKS at least a minute before the IdP signs with it (covering the 30-second refetch window), and remove the old key only after every token it signed has expired (plus `APP_AUTH_LEEWAY_SECONDS`). Most IdPs pre-publish keys automatically. An IdP that starts signing with a key the moment it publishes it causes up to 30 seconds of `401`s per API process.
- **Compromised key:** remove it from the JWKS, then restart the API replicas; otherwise each process keeps trusting its cached copy for up to `APP_AUTH_JWKS_CACHE_SECONDS`.
- **IdP outage:** tokens whose key is still cached keep working until the cache expires. After that, requests fail closed with `503 authentication_unavailable`. A verified token whose key is cached needs no fetch, so an instance with cached keys stays ready and keeps verifying such tokens during an outage. A token whose `kid` isn't cached (including a forged one) is still refused with `503 authentication_unavailable` while the fetch fails, but does not make an instance with valid cached keys not ready. `/health/ready` turns `503` only when a fetch fails and no cached keys are usable (for example after the cache expires), and stays so until a fetch succeeds. While not ready, readiness probes retry the JWKS (at most once per 5 seconds per process), so an instance recovers on its own after the IdP does, even with no traffic.

### Rotating `APP_IDENTITY_HASH_KEY`

Thread ownership is HMAC-SHA256(`APP_IDENTITY_HASH_KEY`, issuer + subject). Changing the key changes every owner key: every existing thread then returns `404` to its owner, `/v1/me/*` no longer finds it, and per-principal limits start fresh. There is no dual-key mode.

- Rotate only if the key is exposed. The key alone grants no access (a caller still needs a valid token), but with database access it lets someone link threads to known identities.
- To rotate, deploy the new key to every replica at once and let retention (`make prune-threads`) remove the orphaned threads, as in the v0.3 upgrade below. Tell users their earlier conversations are no longer available.
- Keep the key identical across replicas and restarts; a mismatch makes threads appear and disappear depending on the replica.
- `setup` stores a check value of the key (an HMAC of a fixed label, never the key) in `neuron_meta` the first time, and refuses a different key afterwards. To rotate on purpose, stop the web service, set the new key, then run `python -m neuron_agent.persistence.cli setup --rotate-identity-key` once by hand. Never leave `--rotate-identity-key` in a permanent pre-deploy command: it would accept any key. First write and rotation each emit an audit event (`identity_key_check_written`, `identity_key_check_rotated`; no key or value). Use a high-entropy key (`python -c "import secrets; print(secrets.token_urlsafe(32))"` or better), because the stored check value lets someone with database access test guesses offline. The start-up comparison in every process (ADR 0008 decision 16) is not implemented yet.

Related settings: trusted proxies and per-user limits are under Rate Limiting, audit log routing under Logs and Traces, and the HTTP surface (CORS, docs, headers, hosts) under HTTP Surface.

## Logs and Traces

Logs are JSON and include service metadata, on the FastAPI server and on Agent Server. Known issue (0.5.0): on Agent Server, langgraph-api wraps each of our JSON lines as the string `event` of its own JSON line, so `trace_id`, `span_id` and our other fields are top-level only once a log shipper parses that inner string; langgraph-api's own records also carry our service metadata.

### LangSmith

`APP_ENABLE_LANGSMITH` is the only switch for LangSmith tracing (ADR 0007, section 5). It is
off by default, and nothing is sent to LangSmith until it is enabled:

```text
APP_ENABLE_LANGSMITH=true
LANGSMITH_API_KEY=...
LANGSMITH_PROJECT=neuron-agent-production
APP_LANGSMITH_CONTENT_APPROVED=false   # default
```

- A `LANGSMITH_TRACING`, `LANGSMITH_TRACING_V2`, `LANGCHAIN_TRACING_V2` or `LANGCHAIN_TRACING`
  set to a true value without `APP_ENABLE_LANGSMITH=true` is overridden at startup, and the
  service logs `langsmith_tracing_overridden` naming the variables.
- Staging and production with LangSmith enabled fail at startup without `LANGSMITH_API_KEY`.
- What leaves the service:

  | Environment | `APP_LANGSMITH_CONTENT_APPROVED` | Sent to LangSmith |
  | --- | --- | --- |
  | any, LangSmith disabled | n/a | nothing |
  | `development` | any | full traces, including prompts, answers and tool arguments/results |
  | `test`, `staging`, `production` | `false` (default) | run structure, names, timings, token usage and metadata; inputs and outputs are hidden |
  | `test`, `staging`, `production` | `true` | full traces, as in development |

  Set `APP_LANGSMITH_CONTENT_APPROVED=true` only after the LangSmith workspace has been
  approved to hold user content (retention, access and region). Outside development, shell
  `LANGSMITH_HIDE_INPUTS`/`LANGSMITH_HIDE_OUTPUTS` values are replaced by this setting.
- Both entry points apply this: the FastAPI app at import and the graph module that Agent
  Server loads.
- Agent Server's own platform tracing, when the service runs as a LangSmith deployment, is
  governed by the platform and its project settings, not by these variables. Configure
  tracing and content retention there.

Do not log raw secrets, authorization headers, or sensitive user content.

### OpenTelemetry

The FastAPI server exports OpenTelemetry traces and metrics over OTLP/HTTP to a Collector
(ADR 0007). It is off by default, and nothing is exported until it is enabled:

```text
APP_OTEL_ENABLED=true
OTEL_EXPORTER_OTLP_ENDPOINT=https://otel-collector.internal:4318
OTEL_EXPORTER_OTLP_HEADERS=authorization=Bearer%20<token>   # optional, URL-encoded
APP_OTEL_TRACES_SAMPLE_RATIO=1.0                             # head sampling for new traces
```

- **Resource:** `service.name` (`APP_OTEL_SERVICE_NAME`, default `APP_NAME`),
  `service.version`, `deployment.environment.name` and `service.instance.id`, a random
  UUID per process.
- **Spans:** one HTTP server span per request, named by route template (for example
  `POST /v1/agent/invoke`). `/health/*` is not traced. An incoming W3C `traceparent` is
  honoured for its trace ID, so the span joins the caller's trace, but its sampled flag is
  ignored: callers are untrusted and could otherwise force or suppress tracing. Every
  request is sampled at `APP_OTEL_TRACES_SAMPLE_RATIO` by a random draw that the
  caller-chosen trace ID can't influence. Use the Collector's tail sampling to keep errors
  and slow traces. `X-Correlation-ID` stays the correlation ID and is recorded on the
  server span as `neuron.correlation_id`.
- **Agent spans**, under the request span:
  - `invoke_agent neuron`, one per run, with `gen_ai.conversation.id` (the thread),
    `neuron.run_id`, `neuron.owner_key_prefix` (12 characters) and `neuron.turn`.
  - `chat {model}` (CLIENT), one per model call, its retries included, with
    `gen_ai.provider.name`, `gen_ai.request.model`, `gen_ai.response.model`, token usage by
    kind (`gen_ai.usage.input_tokens`, `.output_tokens`, `.cache_read.input_tokens`,
    `.cache_creation.input_tokens`, `.reasoning.output_tokens`) and `neuron.retry_count`.
  - `execute_tool {tool}`, one per tool call, with `gen_ai.tool.name` and `neuron.outcome`
    (`success`, `error` or `denied`). A tool the agent doesn't have is named `unknown`.
  - `neuron.approval`, one per approval request or decision, with `neuron.approval.decision`
    (`requested`, `approve`, `reject`) and `neuron.approval.actions` (how many tool calls it
    covers). A run or tool call that paused for approval has `neuron.outcome` `interrupted`
    (not an error). `neuron.memory.<operation>` (`remember`, `list`, `forget`, `erase`), one per
    memory operation, with `neuron.memory.operation`, `neuron.outcome` and `neuron.memory.items`
    (a count). None of them carries tool arguments, note text, an approval or memory ID or an
    owner key. No alert rule changes: approvals and memory add no failure mode the existing
    error-rate and latency alerts miss, and a pause is not counted as a failed stream.
  - `neuron.stream` around an SSE stream (the parent of its `invoke_agent` span), with
    `neuron.stream.ttft_ms`, `neuron.stream.events` and `neuron.stream.termination`, which
    takes the `stream_completed` log's values plus `client_disconnect`.
  - A failed span has status `ERROR` and `error.type` set to the `AppError` code, such as
    `authorization_error` for a denied tool. Exceptions are never recorded on spans: their
    messages can carry content.
- **Logs:** every log line written inside a valid span context, sampled or not and audit
  records included, carries `trace_id` and `span_id`, so a log line leads to its trace.
- **Failures:** exports run in the background. An unreachable Collector never fails a
  request; the SDK logs `Failed to export ...` and drops the batch. Each export, retries
  included, gives up after `APP_OTEL_EXPORT_TIMEOUT_SECONDS`.
- **Transport:** in staging and production, an endpoint that carries
  `OTEL_EXPORTER_OTLP_HEADERS` must use HTTPS unless it is a loopback sidecar
  (`localhost`, `127.0.0.1`, `[::1]`), so credentials never cross the network in clear.
- **Privacy:** prompts, answers and tool content are never recorded. HTTP spans do carry
  standard request attributes, such as the URL, user agent and peer address; redact them
  in the Collector where your policy requires it.
- **Agent Server** deployments emit the agent spans and metrics from the graph node, with
  the thread, run and owner taken from the run's config. The graph module configures the
  same exporters when it is loaded, once per process, so the FastAPI app and Agent Server
  never export twice.

#### Metrics

Metrics are pushed over OTLP/HTTP every 60 s (the SDK default) to the same Collector. Durations
are in seconds. Instruments:

| Instrument | Type | Attributes |
| --- | --- | --- |
| `gen_ai.client.operation.duration` | histogram | `gen_ai.operation.name` (`chat`), `gen_ai.provider.name`, `gen_ai.request.model`, `error.type` on failure |
| `gen_ai.client.token.usage` | histogram, `{token}` | the same, plus `gen_ai.token.type` (`input`, `output`; both include cache-read and reasoning tokens) |
| `neuron.agent.run.duration` | histogram | `gen_ai.operation.name` (`invoke_agent`), `neuron.outcome` (`success`, `error`, `cancelled`), `error.type` |
| `neuron.agent.stream.ttft` | histogram | `neuron.outcome` (the stream's termination: `completed`, `approval_required`, `error`, `timeout`, `shutdown`, `client_disconnect`); streams that sent no token are not recorded |
| `neuron.agent.tool.duration` | histogram | `gen_ai.operation.name` (`execute_tool`), `gen_ai.tool.name`, `neuron.outcome` (`success`, `error`, `denied`, `interrupted`), `error.type` |
| `neuron.agent.errors` | counter | `error.type`, an `AppError` code. Counts each failed request or run once, client errors (such as `validation_error`) included; filter on the code |
| `neuron.approvals` | counter | `neuron.approval.decision`: `requested`, `approve`, `reject` |
| `neuron.feedback` | counter | `neuron.feedback.score`: `up`, `down`; `neuron.feedback.reason`: a fixed reason or `none` |
| `neuron.memory.operations` | counter | `neuron.memory.operation`: `remember`, `list`, `forget`, `erase`; `neuron.outcome`: `success`, `error` |
| `neuron.model.fallbacks` | counter | `neuron.fallback.from`, `neuron.fallback.to`: the configured model ids switched from and to |
| `neuron.agent.policy.blocks` | counter | `neuron.rule`: `empty_message`, `message_too_long`, `control_characters`, `token_budget`, `concurrent_runs`, `concurrent_streams`, `request_rate`, `insufficient_scope`, `unknown_tool` |
| `neuron.checkpoint.duration` | histogram | `neuron.outcome`, `error.type` (the exception class) |
| `http.server.request.duration` | histogram | `http.route`, `http.response.status_code` |
| `http.server.request.body.size`, `http.server.response.body.size` | histogram | `http.route`, `http.response.status_code` |
| `http.server.active_requests` | up-down counter | none |
| `neuron.service.ready` | observable gauge | none. `1` if the latest readiness evaluation (every 15 s) passed, `0` if it failed. Not reported before the first evaluation, while draining, or when the last evaluation is over 60 s old |
| `neuron.db.pool.waiting` | observable gauge, `{request}` | none. Requests waiting for a Postgres pool connection (`requests_waiting` of the psycopg pool's `get_stats()`); reported only while a pool is open |

`neuron.agent.cost` (estimated USD, ADR 0007 section 2) is not emitted: the estimated cost is
deferred together with its pricing data.

**Labels.** Only these attribute keys label a metric: `gen_ai.request.model`,
`gen_ai.provider.name`, `gen_ai.operation.name`, `gen_ai.tool.name`, `gen_ai.token.type`,
`error.type`, `http.route`, `http.response.status_code`, `neuron.outcome` and `neuron.rule`.
Users, owner keys, threads, runs and requests never label a metric, because each would
create a time series per value. HTTP metrics use the stable HTTP conventions, so the FastAPI
instrumentation's other attributes (method, scheme, protocol version) are dropped by views.
A test collects metrics from a run and fails on any other key or on any ID as a value.

**Buckets.** Explicit bucket upper bounds, in seconds, set by views in
`observability/metrics.py`:

- Model call, run, time to first token and HTTP request duration:
  0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2, 4, 8, 15, 30, 60, 120. Slower than 120 s is in the
  overflow bucket (`APP_RUN_TIMEOUT_SECONDS` defaults to 120).
- Tool and checkpoint duration: 0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10,
  30, 60 (`APP_TOOL_TIMEOUT_SECONDS` is at most 60).
- Tokens per model call: powers of 4 from 1 to 4^13 (67,108,864).

**Several workers.** Run as many uvicorn workers or replicas as needed: each process has its
own meter provider and pushes its own OTLP stream, with a distinct `service.instance.id`, so
cumulative series from different processes are never merged. Nothing is shared between
workers, and there is no `/metrics` endpoint to scrape (a scrape would reach one worker).
Aggregate across instances in the backend, for example `sum without (service_instance_id)`,
or have the Collector drop the attribute after export. A worker flushes on graceful shutdown;
an abrupt kill loses up to one export interval.

Security audit records use the separate `neuron_agent.audit` logger (also present as the
JSON `logger` field). Route that logger to the SIEM independently from application logs;
do not apply application-log sampling or filtering that drops denials. Records use the
fixed schema in `ARCHITECTURE.md#observability`; authentication success records are off
unless `APP_AUTH_AUDIT_SUCCESS_ENABLED=true`. Configure `APP_AUTH_ISSUER_ID` as a stable,
non-secret alias (for example `primary`), not an issuer URL. Choose SIEM retention under
your security/compliance policy; keep it separate from `APP_THREAD_RETENTION_DAYS`, since
audit records contain metadata and are not deleted with conversation data. Protect audit
sink access and retention against unauthorized modification/deletion.

### Telemetry on the reference deployment

ADR 0008 decision 12; `render.yaml` defines it (Render facts are assumed, and nothing here has run on a real deployment).

- **Path.** Each web instance exports OTLP/HTTP to `http://neuron-collector-<env>:4318`, a Render private service, over the workspace's private network. The Collector runs the shipped `deploy/observability/otel-collector.yaml` (mounted as the secret file `otel-collector.yaml`; upload it in the Dashboard, since a Blueprint cannot declare a secret file) on the pinned `opentelemetry-collector-contrib` release, and forwards traces, metrics and logs to the backend chosen in ADR 0008 open question 10 through `OTEL_BACKEND_ENDPOINT` and, if needed, `OTEL_BACKEND_AUTH_HEADER` (both `sync: false` on the Collector only). The Collector's service has no database, provider or `APP_*` secret.
- **Settings.** The web groups set `APP_OTEL_ENABLED=true`, `APP_OTEL_TRACES_SAMPLE_RATIO=1.0` (tail sampling needs every span; head sampling would discard the errors first) and `APP_OTEL_EXPORTER_OTLP_ENDPOINT`. A test (`tests/unit/test_render_blueprint.py`) pins them and that each environment points at its own Collector.
- **One replica, no load balancing.** Tail sampling decides per trace once all its spans arrive, so every span of a trace must reach the same Collector. With one replica that always holds, so no trace-ID load-balancing exporter is needed. Do not scale the Collector past one instance without adding one (see the Collector notes under "Service level objectives").
- **Staging and production share a private network** when they are in one Render workspace and region, so staging could reach the production Collector. Keep them in separate workspaces (see "Who can read the secrets"); the OTLP receiver has no authentication.
- **Metrics and alerts.** The Collector's Prometheus exporter listens on port 8889 of the private service; a backend that scrapes must run where it can reach it, or use an OTLP metrics endpoint. Load `deploy/observability/prometheus-alerts.yaml` in the backend and check it with `promtool` (the `observability-config` CI job does).
- **Not verified (open until a real deployment).** (1) One streamed run with a tool call on staging shows a linked trace, its logs (by `trace_id`) and its metrics in the backend, and the shipped alert rules load there. (2) The staging telemetry passes the v0.5.0 leak scan. To run the scan, capture the staging telemetry (an export from the backend, or a temporary file exporter on the Collector as in `docs/releases/v0.5.0-gate/otel-collector.gate.yaml`) and search it for the forbidden strings of `docs/releases/v0.5.0-gate/telemetry_gate.py` (the prompt, the answer, the tool expression, its arguments and result, both bearer tokens and their segments, the raw `sub`, and with a live model the provider key), with a positive control that finds the prompt in the client transcript; record the result in the PR. Neither check has been run.

### Service level objectives

SLIs, targets and alerts for the service (ADR 0007, decision 8). **Targets were set at the v0.5.0 release gate (#99)** from live runs on the development model (`nvidia/nemotron-3-super-120b-a12b`, NVIDIA free tier, 2026-10-16/17); re-check them on the production model, which has not been measured (no OpenAI run). The PromQL uses the names the Collector's Prometheus exporter produces from the OTLP metrics above: dots become underscores, unit `s` adds `_seconds`, counters add `_total`, histograms add `_bucket`/`_count`, and attributes become labels (`error.type` is `error_type`). Resource attributes are labels too (`service_instance_id` keeps workers apart), so every query aggregates with `sum(...)`.

| SLO | SLI (good events / valid events) | Target | Error budget |
| --- | --- | --- | --- |
| `availability` | `/v1` requests that did not fail with 5xx, among requests that are not 4xx | 99.5% over 30 days | 0.5% |
| `ttft` | streams whose time to first token is at most 15 s (p90 under 15 s) | 90% over 30 days | 10% |
| `run_duration` | runs that finish within 30 s (p95 under 30 s), cancelled runs excluded | 95% over 30 days | 5% |
| `provider_errors` | model calls that do not fail (provider error rate at most 1%) | 99% over 30 days | 1% |

Evidence from the release gate:

- `availability`: the regression suites had no failed run in the clean live runs; in the release-candidate run 5 of 368 runs across all suites failed with a 5xx-class code (from the run's per-run log events, not committed) (2 `structured_output_error`, 3 `run_timeout`), all on adversarial security-eval inputs.
- `ttft`: 16 streamed single-turn eval prompts had p50 6.4 s and max 20.2 s; none within 2 s, 9 within 8 s, 15 within 15 s. The answer is structured output, so its first token streams only after the model has finished reasoning, and time to first token is close to the run's duration.
- `run_duration`: three live `--trials 3` runs had 95.9%, 97.4% and 93.4% of runs within 30 s (from each run's `agent_execution_completed`/`agent_execution_failed` log events, which are not committed) (p95 28.4 s, 24.5 s, 33.6 s): met in 2 of 3, so tight on the eval workload, which includes adversarial and multi-turn cases.
- `provider_errors`: in the two unthrottled live runs no model call failed after retries; during free-tier throttling 4 of about 440 calls failed after retries (`rate_limit_error`), so throttling alone can burn this budget. Production needs a paid tier or a provider with a higher limit.

Definitions (`w` is a window):

```text
availability error ratio =
  sum(rate(http_server_request_duration_seconds_count{http_route=~"/v1/.*",http_response_status_code=~"5.."}[w]))
  / sum(rate(http_server_request_duration_seconds_count{http_route=~"/v1/.*",http_response_status_code!~"4.."}[w]))

ttft slow ratio =
  1 - sum(rate(neuron_agent_stream_ttft_seconds_bucket{le="15"}[w])) / sum(rate(neuron_agent_stream_ttft_seconds_count[w]))

run duration slow ratio =
  1 - sum(rate(neuron_agent_run_duration_seconds_bucket{le="30",neuron_outcome!="cancelled"}[w]))
      / sum(rate(neuron_agent_run_duration_seconds_count{neuron_outcome!="cancelled"}[w]))

provider error ratio =
  sum(rate(gen_ai_client_operation_duration_seconds_count{error_type!=""}[w]))
  / sum(rate(gen_ai_client_operation_duration_seconds_count[w]))
```

Caveats: a stream that fails after its `200` headers is not an availability failure (see the `neuron.agent.errors` counter, `neuron.outcome` on `neuron.agent.stream.ttft`, and the `stream_completed` log); `le="15"` and `le="30"` must stay bucket bounds in `observability/metrics.py`; a model call's duration and error include its retries, so a provider error is one that outlasted them. Time to first token is recorded only for streams that sent a token.

**Alerts.** `deploy/observability/prometheus-alerts.yaml` holds recording rules for each ratio over 5m, 30m, 1h, 6h and 3d, and the multi-window, multi-burn-rate alerts of the Google SRE Workbook for each SLO: 14.4x over 1h and 5m (page; 2% of a 30-day budget in 1 h), 6x over 6h and 30m (page) and 1x over 3d and 6h (ticket). An alert fires only when both windows exceed `burn x budget`. For `ttft`, whose 10% budget makes 14.4x unreachable (a ratio of 1.44), the 1h and 5m page fires at 10x, when every stream is slow. Each `alert=True` error class in `errors/base.py` (`configuration_error`, `provider_error`, `provider_quota_exhausted`, `tool_execution_error`, `structured_output_error`, `persistence_error`, `agent_execution_error`) has the 14.4x and 6x pair against a provisional budget of 0.1% of `/v1` requests, using `neuron_agent_errors_total{error_type="<code>"}`. A test keeps the rules, the SLO list and the error classes in step. The rules are examples: route `severity` in Alertmanager. The ratios are undefined without requests, so they never alert on no traffic; the service-health alerts below do.

**Service-health and abuse alerts** (groups `neuron-service-health` and `neuron-rejections`; labelled `signal`, not `slo` or `error_type`; runbooks below):

| Alert | Fires when | Severity |
| --- | --- | --- |
| `NeuronNoMetrics` | `absent(neuron_service_ready)`: no instance has reported for at least 10 minutes | page |
| `NeuronInstanceNotReady` | `neuron_service_ready == 0` for 5 minutes, per instance | page |
| `NeuronPostgresPoolSaturated` | `neuron_db_pool_waiting > 0` for 5 minutes, per instance | page |
| `NeuronRunLeasesExpired` | `max(neuron_run_leases_expired) > 0` for 5 minutes (the maximum across replicas, never the sum) | ticket |
| `NeuronThreadBusyAnomaly` | `thread_busy` above 5% of `/v1` requests and 0.05 requests/s for 15 minutes | ticket |
| `NeuronTooManyConcurrentRunsAnomaly` | the same for `too_many_concurrent_runs` | ticket |
| `NeuronDeniedToolCallsSpike` | more than 10 `insufficient_scope` or `unknown_tool` policy blocks in 10 minutes | ticket |

Instances push their metrics (see "Several workers"), so Prometheus has no `up` series per instance; an `up == 0` rule would only watch the Collector, which stays up while every application instance is dead. `NeuronNoMetrics` uses `absent()` on the readiness gauge instead. The Collector's prometheus exporter drops a series 5 minutes after its last update (`metric_expiration: 5m`), so `absent()` turns true at least 5 minutes after the last push from the last instance (plus up to a scrape and an evaluation interval) and `for: 5m` adds 5 more: it fires no sooner than 10 minutes after the last push, in practice a little later (a test checks expiry plus `for` is at least 10 minutes). It also fires when Prometheus cannot scrape the Collector, which is the same blindness. It watches all instances together: one dead instance among several is the `NeuronInstanceNotReady` case, or the gap in `count(neuron_service_ready)`. An instance reports readiness without being probed. A draining instance reports nothing, so a rolling deploy does not page `NeuronInstanceNotReady`; the same goes for the last instance of a service that is being shut down, which `NeuronNoMetrics` then reports once its series expires, as for any other stop. The pool gauge reads one module-level source, because the service has one Persistence (one pool) per process. When one Prometheus serves several environments, add `{deployment_environment_name="<env>"}` to the selectors. The thresholds of the last three alerts are provisional, like the error-class budgets.

**Collector.** `deploy/observability/otel-collector.yaml` (pinned to `opentelemetry-collector-contrib` 0.120.0) receives OTLP and runs, in this order, `memory_limiter`, the attribute allow-list, value redaction, tail sampling (traces only) and `batch`, then exports traces, metrics and logs over OTLP and metrics to Prometheus. Endpoints come from `OTEL_BACKEND_ENDPOINT`, `OTEL_BACKEND_AUTH_HEADER`, `OTEL_RECEIVER_HOST` and `PROMETHEUS_EXPORTER_ENDPOINT`.

**Validation in CI.** The `observability-config` job of the `ci` workflow runs `scripts/validate_observability.py check`: `promtool check rules` on the alert file and `otelcol-contrib validate` on the Collector config, with both binaries downloaded from their GitHub releases at pinned versions (Prometheus 3.5.0, Collector 0.120.0) and verified against a pinned SHA-256 before use. It then runs `reject-broken`, which proves that each tool exits non-zero on a broken fixture (`tests/fixtures/observability/`). To bump a tool, change its version, URL and hash together in the script, taking the hash from the release's published checksums file and from your own `sha256sum` of the download. Run the same command locally to check your edits (Linux amd64 only). `otelcol-contrib validate` needs `OTEL_BACKEND_ENDPOINT` set; the script supplies a placeholder.

- The allow-list drops every attribute not emitted by `semconv.py`: resource, span, metric data point and log record attributes each have their own list, and span events lose all attributes. HTTP spans keep only method, route, status code, scheme and protocol version, which drops the URL path, user agent and peer address. A new attribute is blocked until it is added to `semconv.py`, the Collector list and the test.
- Tail sampling keeps every trace with an error span, every trace slower than 30 s (the `run_duration` target) and 10% of the rest. Run the app with `APP_OTEL_TRACES_SAMPLE_RATIO=1.0` (head sampling would discard the errors first), and put a load-balancing exporter keyed by trace ID in front of several Collector replicas.
- The service does not export logs over OTLP yet. The logs pipeline filters attributes only; it cannot filter a free-text body.
- The development-only Compose stack (Grafana, Tempo, Loki, Prometheus) is deferred; it does not block the release.

#### Runbook: availability

`NeuronAvailabilityBurnRate*`. Look at `sum by (http_route, http_response_status_code) (rate(http_server_request_duration_seconds_count{http_response_status_code=~"5.."}[5m]))` and `neuron_agent_errors_total` by `error_type`. A provider-class error points to the provider runbook; `persistence_error` or a failing `/health/ready` points to Postgres (Thread Persistence); `503 too_many_streams` means scale out or raise `APP_MAX_CONCURRENT_STREAMS`; `service_shutting_down` during a rollout is expected for a short time. Roll back (Rollback) if it began with a deploy.

#### Runbook: ttft

`NeuronTtftBurnRate*`. Slow first tokens come from the provider, from a proxy that buffers (Streaming Behind a Reverse Proxy), or from load. Compare `neuron_agent_stream_ttft_seconds` with `gen_ai_client_operation_duration_seconds` (provider time) and check `neuron.retry_count` on slow `chat` traces: retries add their backoff to time to first token. If only the provider is slow, shed nothing and wait or fail over; if the proxy buffers, fix it.

#### Runbook: run-duration

`NeuronRunDurationBurnRate*`. Open slow traces (tail sampling keeps those over 30 s): `chat` spans dominate when the provider is slow, repeated `execute_tool` spans mean a tool loop (`APP_MAX_AGENT_ITERATIONS`), and a `checkpoint` slowdown (`neuron_checkpoint_duration_seconds`) means the database. Runs that hit `APP_RUN_TIMEOUT_SECONDS` are `run_timeout` errors in the overflow bucket.

#### Runbook: provider-errors

`NeuronProviderErrorsBurnRate*`. Split `gen_ai_client_operation_duration_seconds_count{error_type!=""}` by `error_type`, `gen_ai_provider_name` and `gen_ai_request_model`. `provider_error` and `provider_timeout_error`: check the provider status page and retry settings (Timeouts and Retries). `rate_limit_error`: lower concurrency or raise the provider limit. `provider_quota_exhausted` and `configuration_error`: see below, retrying never helps.

#### Runbook: error classes

`NeuronErrorClass<Code>*`, one pair per `alert=True` class; the label `error_type` names it. Find the failing requests by the `error_code` log field and the `error.type` span attribute, then:

| `error_type` | First response |
| --- | --- |
| `configuration_error` | A bad model identifier, provider authentication failure or a model the account cannot use. Check the last configuration or secret change; fix and redeploy. Never retried. |
| `provider_error` | Upstream 5xx. See the provider-errors runbook. |
| `provider_quota_exhausted` | The provider account has no credit. Add credit or raise the quota; every request fails until then. |
| `tool_execution_error` | A tool timed out or raised. Check `neuron_agent_tool_duration_seconds` by `gen_ai_tool_name`, then the tool's dependency. The failure is isolated to the call. |
| `structured_output_error` | The model returned output that failed the `AgentAnswer` schema or was empty. Check for a model or prompt change; run the evals (`make eval`). |
| `persistence_error` | The checkpointer failed. Check Postgres and pool saturation (Thread Persistence); the pool reconnects once the database is back. |
| `agent_execution_error` | An unclassified failure or the iteration cap. Read the server logs' `error_type`, and the trace for a tool loop. |

#### Runbook: no metrics

`NeuronNoMetrics`. No instance has pushed for at least 10 minutes, so every other alert is blind as well. Check, in order: Prometheus scraping the Collector's exporter (`PROMETHEUS_EXPORTER_ENDPOINT`, default port 8889; its own `up` for that target); the Collector process and its logs (a `memory_limiter` refusing data is logged there); the application's `APP_OTEL_ENABLED` and `OTEL_EXPORTER_OTLP_ENDPOINT` after a configuration change (the SDK logs `Failed to export ...`); and whether the instances are running at all (`/health/live`, the platform's instance list). If the service itself is down, the availability alerts cannot fire either, so treat this one as an outage until shown otherwise. A single instance whose event loop hung also lands here once it is the only one: its readiness evaluation stops, and after 60 seconds its gauge goes quiet.

#### Runbook: not ready

`NeuronInstanceNotReady`, per `service_instance_id`. The instance's own readiness evaluation (the same checks as `/health/ready`) has failed for 5 minutes; a draining instance does not report, so this is not a deploy in progress. Call `/health/ready` and read the logs; the causes are the ones listed under Health Checks: the database unreachable (`checkpointer_unreachable`, see the pool runbook), or in jwt mode no usable signing keys (the IdP or its JWKS URL, see Signing keys and JWKS caching). The platform already stopped routing to it; the risk is lost capacity. If all instances are affected, the cause is shared (database, IdP): expect the availability alerts too. An instance that was replaced stops reporting and its alert resolves after the series expires.

#### Runbook: postgres pool

`NeuronPostgresPoolSaturated`. `neuron_db_pool_waiting` above zero for five 60 s samples in a row: requests wait for a connection, and after `APP_POSTGRES_POOL_TIMEOUT_SECONDS` they fail as `persistence_error`. Compare `neuron_checkpoint_duration_seconds` (a slow database holds connections longer) with the request rate (more load than `APP_POSTGRES_POOL_MAX_SIZE` allows). If the database is slow, fix that first (Thread Persistence); raising the pool only moves the queue. If load is the cause, raise `APP_POSTGRES_POOL_MAX_SIZE` within the database's `max_connections` across all instances, or add instances. A high-water mark that returns to zero between bursts is not this alert.

#### Runbook: run leases

`NeuronRunLeasesExpired`, on `max(neuron_run_leases_expired) > 0` for 5 minutes. Every replica reports the same table-wide count, so the rule uses the maximum; do not change it to a sum. A ticket rather than a page because an expired lease blocks nobody: the next claim by its owner or on its thread deletes it. A value that stays above zero means the rows are not being cleaned up. After a replica crash it is briefly non-zero until the owner's next request, which is why the rule waits 5 minutes. Persistent: run `python -m neuron_agent.persistence.cli prune`, check `thread_prune_job_completed` (`expired_leases`), `run_lease_release_failed` and `run_guard_unavailable` in the logs, and see the Postgres guards section above. The series exists only with `APP_LIMITS_BACKEND=postgres`.

#### Runbook: rejections

`NeuronThreadBusyAnomaly`, `NeuronTooManyConcurrentRunsAnomaly`. A client causes these (`409 thread_busy`: a second run on a thread that has one in flight; `429 too_many_concurrent_runs`: a principal above its concurrent-run allowance), so a few are normal. Above 5% of `/v1` requests for 15 minutes is not. The metrics carry no user, so find the source in the logs: `user_limit_exceeded` with `limit_type=concurrent_runs` and the owner key prefix, and the `limit_exceeded` audit events, for the allowance; `agent_thread_busy` (no owner) for the thread, which points to the thread through the request's correlation ID. Usual causes: a client retrying on timeout while the first run is still going (it should wait or resume the thread), a double submit, a script above its allowance, or runs that are slow so that they overlap (check `run_duration`). Tell the owner of the client. Raise the allowance only for a legitimate workload.

#### Runbook: denied tools

`NeuronDeniedToolCallsSpike`. The model asked for a tool its caller's scopes do not allow (`insufficient_scope`) or one that does not exist (`unknown_tool`) more than ten times in 10 minutes. Tool calls are model output, so this is a signal of prompt injection or a changed model, not of an attacker holding credentials. The metric carries no user or tool; use the `authorization_denied` audit events (`resource_type=tool`, `reason` `insufficient_scope` or `unknown_tool`, with the bounded tool name and the actor) and the `execute_tool` spans with `neuron.outcome=denied`. One actor in most of them is a user probing or injecting; spread across many follows a model or prompt change (check the last deploy and the model identifier) or a scope misconfiguration. Nothing was executed: the denial happens in code before the call. Preserve the audit records, and follow the Security incident runbook if the inputs are hostile.

### Streaming and conversation-state events

Every event carries `request_id`, `thread_id` and `run_id`. None of them contains prompt text, streamed tokens or tool arguments.

| Event | Level | Key fields | Meaning |
| --- | --- | --- | --- |
| `stream_started` | info | — | a `/v1/agent/stream` run began |
| `stream_completed` | info / warning | `termination` (`completed`, `approval_required`, `error`, `timeout`, `shutdown`), `error_code`, `ttft_ms`, `duration_ms`, `tokens_streamed`, `events_streamed` | the stream reached `done`; warning unless `completed` or `approval_required` (the run paused for a decision) |
| `stream_cancelled` | info | `termination=client_disconnect`, plus the same timing and count fields | the client went away before `done`; the run was cancelled |
| `stream_rejected` | warning | `termination` (the error code, e.g. `thread_busy`, `too_many_streams`, `thread_not_found`) | the stream was refused before the first byte |
| `agent_execution_started` | info | `turn`, `history_messages`, `model` | `turn` is the 1-based user-turn number in the thread |
| `model_token_usage` | info | `provider_tokens` (what budgets charge), `input_tokens`, `output_tokens`, `cache_read_tokens`, `reasoning_tokens`, `models` (the same counts and `total_tokens` per model id) | once per run when it ends: `/v1/agent`, `/v1/agent/stream` and Agent Server runs (which have no `request_id` and no per-user budget). A kind the provider doesn't report is 0, and a provider that reports only a total has the kinds at 0. Input includes cache-read and output includes reasoning |
| `history_trimmed` | info | `messages_total`, `messages_sent`, `max_history_tokens` | older turns were left out of the model input |
| `checkpoint_operation_slow` | warning | `operation`, `backend`, `duration_ms` | a checkpointer read or write took at least 250 ms |
| `checkpoint_operation_failed` | warning | `operation`, `backend`, `error_type`, `duration_ms` | a checkpointer read or write raised |
| `checkpointer_unreachable` | warning | `backend`, `error_type` | readiness probe failed |
| `thread_prune_job_completed` | info | `count`, `retention_days` | the retention job finished |
| `threads_pruned` | audit | `count` | the retention run's security audit record |

Suggested alerts:
- **Time to first token:** sustained rise in p95 `ttft_ms`.
- **Failed streams:** `stream_completed` with `termination` other than `completed` or `approval_required` above a few percent of streams.
- **Disconnects:** a spike in `stream_cancelled`. This usually means client or proxy timeouts, so check proxy buffering and timeouts first.
- **Capacity:** any `stream_rejected` with `too_many_streams`, which means you're at capacity; scale out or raise `APP_MAX_CONCURRENT_STREAMS`.
- **Database:** any `checkpoint_operation_failed`, or a sustained `checkpoint_operation_slow` rate.
- **Retention:** `thread_prune_job_completed` missing for longer than the job's schedule interval.

### Security incident runbook

| Response | Meaning | Runbook entry |
| --- | --- | --- |
| `401 authentication_error` | missing, malformed, expired or untrusted token | 401 spike |
| `403 authorization_error` | valid token without the route's scope | 403 spike |
| `503 authentication_unavailable` | the IdP's JWKS can't be fetched | IdP outage |
| `429 quota_exceeded` | the principal's rolling token budget is spent | Quota exhaustion |
| `429 too_many_concurrent_runs` | the principal already has `APP_MAX_CONCURRENT_RUNS_PER_USER` runs | Quota exhaustion |
| `429 rate_limited` | request rate, or failed authentications per IP | Quota exhaustion |

- **401/authentication failure spike:** query `logger="neuron_agent.audit" AND event="auth_failed"`
  and group by `reason`, `issuer_id` and time. `jwks_unavailable` indicates identity-provider
  connectivity trouble; invalid-token reasons indicate caller credentials or abuse. Verify
  issuer/JWKS health and key rotation before changing auth policy. Never copy bearer tokens
  into tickets or logs.
- **403/authorization denial spike:** query `event="authorization_denied"`, group by
  `action` and `reason` (`resource_type="tool"` denials don't fail the run, so they show no
  `403`), and check for repeated scope mismatch or thread-access attempts. Injected tool
  attempts show only as `authorization_denied` with `resource_type="tool"` and in
  `neuron_agent_policy_blocks_total{neuron_rule=~"insufficient_scope|unknown_tool"}`; no
  example alert rule is shipped for them.
  Verify role-to-scope configuration; never broaden permissions as a diagnostic shortcut.
- **IdP outage or JWKS fetch failures (`503 authentication_unavailable`):** query
  `event="auth_failed" AND reason="jwks_unavailable"`; `/health/ready` usually also returns `503`, once the cached keys have expired.
  Check the IdP's status and that `APP_AUTH_JWKS_URL` is reachable from the API (DNS,
  egress rules, TLS). Don't switch to `APP_AUTH_MODE=none` or widen the issuer. Requests
  and readiness recover by themselves once a fetch succeeds; no restart is needed
  (Signing keys and JWKS caching).
- **Signing-key problems:** a spike of `auth_failed` with `reason="unknown_signing_key"` after an
  IdP key rotation means tokens are signed with a key the JWKS doesn't (yet) publish; check
  the IdP's JWKS before Neuron.
- **Quota exhaustion (`429`):** query `event="limit_exceeded"` grouped by `reason` and `actor`.
  `token_budget` is `quota_exceeded`, the per-principal rolling budget; `concurrent_runs` is
  `too_many_concurrent_runs`; `request_rate` and `authentication_attempts` are
  `rate_limited`; `concurrent_streams` is the process-wide stream cap (`503 too_many_streams`).
  One `actor` dominating points at a single client looping or retrying without honouring
  `Retry-After`. Check legitimate
  workload and provider capacity before tuning limits; do not disable guards during an incident.

## Scaling

The API can scale horizontally. Durable conversations require Agent Server managed persistence or `APP_CHECKPOINTER=postgres`. With Postgres, any replica can continue any thread.

With `APP_LIMITS_BACKEND=memory` (the default) two guards are per process (ADR 0005), like the rate limiter:
- the `thread_busy` check, which rejects a concurrent run on the same thread;
- `APP_MAX_CONCURRENT_RUNS_PER_USER`, which is multiplied by the replica count.

Two simultaneous requests for the same thread that land on *different* replicas aren't rejected then. Both run and both commit their turns. Route by `thread_id` (sticky sessions), serialize sends client-side, or use the Postgres guard.

With `APP_LIMITS_BACKEND=postgres` both guards are shared (ADR 0008 decision 8). Each run holds a row in `neuron_run_leases` (migration 2) until it ends; a second run on the same thread gets `409 thread_busy` and a run past the per-user cap gets `429 too_many_concurrent_runs`, whichever replica it lands on. `DELETE /v1/threads/{id}` and the bulk erase hold a lease on each thread while they delete it, so no run starts on it meanwhile and a thread with a live run is refused or skipped.
- **Expiry.** A lease expires at `APP_RUN_TIMEOUT_SECONDS` + 15 s by the *database* clock (`clock_timestamp()` at the insert, so a wait for the owner lock does not shorten it); replica clocks do not matter. A run is cancelled at its timeout, 15 s before its lease can expire, and there is no heartbeat. A replica that dies mid-run leaves its leases; they block the thread and the user's slot for at most that long, and the next claim for the same owner or thread deletes them. The daily retention job (`make prune-threads`) deletes the rest.
- **Fail closed.** Every guard transaction sets `lock_timeout` (2 s) and `statement_timeout` (5 s). A database error, a lock wait past the timeout, or a pool checkout timeout makes the request `503` (error code `persistence_error`, `alert=true`) and the model is not called. A failed release is logged (`run_lease_release_failed`) and never fails the request; expiry covers it.
- **Pool.** The guards share the pool (`APP_POSTGRES_POOL_MAX_SIZE`, per process). Each claim and release holds a connection for a few milliseconds; a claim waits for its owner's other claims on the owner lock, up to `lock_timeout` (2 s), and each waiting claim parks one pool connection meanwhile. A burst of claims from one principal can therefore occupy a share of the pool, which the checkpointer uses too, for up to 2 s; the claims are not made non-blocking (`pg_try_advisory_xact_lock`) because that would break the guarantee that exactly k of many simultaneous claims succeed. The mitigation is the per-replica request rate limiter, which sheds a burst before it reaches the guard.
- **Gauge and runbook.** `neuron.run_leases.expired` is the number of leases past `expires_at` that nothing has deleted yet. Every replica reports the same table-wide value (sampled every 30 s), so an alert must use the maximum across replicas, never the sum (which multiplies the count by the replica count). It is normally 0, and briefly above 0 after a replica crash (until the owner's next request or the retention job removes the rows). A value that stays above 0 for hours means the retention job is not running or deletes are failing: run `python -m neuron_agent.persistence.cli prune`, check `thread_prune_job_completed` (`expired_leases`) and `run_lease_release_failed` / `run_guard_unavailable`. To free one stuck user at once, delete their rows from `neuron_run_leases`. The alert is `NeuronRunLeasesExpired` (runbook: run leases).
- **Erasure is incomplete when a thread is skipped.** `DELETE /v1/me/threads` (bulk erase) skips an owned thread that has a live lease and reports it in `skipped_busy_count`; when that count is above 0 the response has `"complete": false` and the erasure is incomplete, and the caller must retry after the run ends (up to the run timeout + 15 s if a crashed replica left a stale lease). An erase that fails part-way is audited as `user_data_erased` with `outcome=error` and the number erased so far, never thread IDs.
- **Requirements.** Migrations 2 to 4 create `neuron_run_leases` and its two indexes; `gen_random_uuid()` needs Postgres 13 or newer. After the database roles are split (#144), the application role needs `SELECT`, `INSERT` and `DELETE` on `neuron_run_leases`; the migrator creates it. This is a prerequisite of #144; no grants exist yet.
- **Still per process:** `APP_MAX_CONCURRENT_STREAMS` (a per-instance resource cap) and the JWKS cache. The request rate limiter is shared too (#148, see Rate Limiting).

**Token budget in Postgres (#147).** With `APP_LIMITS_BACKEND=postgres` the per-user token budget (`APP_USER_TOKEN_BUDGET` over `APP_USER_TOKEN_BUDGET_WINDOW_SECONDS`) is one ledger `neuron_token_ledger (owner_key, minute, tokens)` shared by every replica and surviving restarts.
- **Reserve, then settle.** Admission reserves `APP_MAX_OUTPUT_TOKENS` plus an estimate of the prompt (the message's UTF-8 bytes / 3) and is refused with `429 quota_exceeded` and `Retry-After` when the window's usage plus the reservation exceeds the budget; a reservation is capped at the budget, so a budget below one reservation still admits a run from an empty window. Admission is one transaction serialised per owner by `pg_advisory_xact_lock`, so concurrent admissions on any replica cannot exceed the budget. When the run ends, on every path (success, error, timeout, cancellation, client disconnect), the reservation is replaced by the real usage: the partial usage recorded so far, or, when the run reported none (cancelled, timed out, or a provider that omits usage), the whole reservation. A run that never started gives its reservation back. A run that used more than it reserved is charged the difference.
- **One-minute window.** Charges go into the database-clock minute they were made in, and a minute counts until its end plus the window has passed. Usage is therefore never forgotten early and is held up to 60 s longer than `APP_USER_TOKEN_BUDGET_WINDOW_SECONDS`; `Retry-After` is the time until enough minutes leave the window for the run to fit. Every timestamp is the database's, so replica clocks do not matter.
- **Fail closed.** Admission has `lock_timeout` 2 s and `statement_timeout` 5 s; any database error, lock wait or pool timeout is `503` (`persistence_error`) and the model is not called. If the ledger write after a run fails, the answer is still delivered, `neuron.token_budget.settle_failures` counts it (log `token_budget_settle_failed`), the reservation stays counted, and that owner's next admission on the same replica retries the write and is refused with `503` until it succeeds. A crash loses that retry; the reservation still counts, so the ledger over-counts rather than under-counts (usage beyond the reservation is the exception).
- **Retention.** The daily prune job (`make prune-threads`) also deletes ledger minutes no admission counts any more, and old settlement rows (`neuron_token_settlements`); a failure is logged (`token_ledger_cleanup_failed`) and never stops thread pruning, so alert on that log event. The job must run with the same `APP_USER_TOKEN_BUDGET_WINDOW_SECONDS` as the replicas; it never deletes rows younger than an hour whatever it is set to, but a longer window on the replicas than on the job would lose usage.
- **Pool and cancellation.** One owner's admissions are limited to `2 x APP_MAX_CONCURRENT_RUNS_PER_USER` pool connections at once (a reserve waits up to 5 s for the gate, then fails closed with `503`), so a burst from one principal cannot drain the pool. A reserve cancelled after its commit leaves its reservation counted until the window passes (conservative). `APP_USER_TOKEN_BUDGET_WINDOW_SECONDS` must be at least `APP_RUN_TIMEOUT_SECONDS` + 15 with `postgres` (start-up refuses otherwise).
- **Requirements.** Migrations 6 to 9 create the logged table `neuron_token_ledger`, `neuron_token_settlements` and their indexes. The `setup` grant phase (#144) gives the application role `SELECT`, `INSERT`, `UPDATE` and `DELETE` on `neuron_token_ledger` and `SELECT`, `INSERT` and `DELETE` on `neuron_token_settlements` (`DELETE` is for the prune job, which runs as the application role); with a single role in staging no grants are needed.

## Thread Persistence (Postgres)

1. **Provision Postgres** 14 or newer; 16 is tested. Create the two roles once per environment (see Database roles below): the migrator owns the schema, the application role only reads and writes rows.
2. **Configure** through the secret manager:

   ```text
   APP_CHECKPOINTER=postgres
   APP_POSTGRES_DSN=postgresql://neuron_app:<app-password>@<host>:5432/neuron?sslmode=require
   APP_POSTGRES_MIGRATION_DSN=postgresql://neuron_migrator:<migrator-password>@<host>:5432/neuron?sslmode=require
   ```

   The runtime DSN must name the **app role** (`neuron_app`), never the database owner or the migrator: a web process running as the schema owner can drop tables. The migration DSN is read by `setup` only. In production, settings refuse start-up when both DSNs use the same user, and the web process refuses to open its pool unless it is connected as `APP_POSTGRES_APP_ROLE` and that role is not a superuser, has no `BYPASSRLS`, is not a member of the schema owner and cannot `CREATE` in the schema. Staging may use one role (ADR 0008 decision 17), so neither check applies there. DSNs are `SecretStr`s and never logged.

   **Start-up checks (staging and production; development and test skip them).** After the pool opens, the process runs the checks below on one connection and stops on the first failure: the pool is closed, the process exits instead of serving (so `/health/ready` never answers and the platform keeps the previous release), and one `database_startup_check_failed` error is logged with an `error_code`. The log and the exception carry no DSN, password, host or key. `python -m neuron_agent.persistence.cli prune` runs the same checks against its own `APP_POSTGRES_DSN`, exits 1 and prints `prune failed: <error_code>: <fixed text>`; give the cron job `APP_IDENTITY_HASH_KEY` too.

   | `error_code` | Meaning | Fix |
   | --- | --- | --- |
   | `tls_required` | `pg_stat_ssl` shows no TLS for this connection (staging and production) | Use `sslmode=verify-full` (or `require`) in the DSN and enable TLS on the server. Behind a transaction pooler this describes the pooler-to-Postgres leg only. |
   | `role_not_app_user` | Production: the database user is not `APP_POSTGRES_APP_ROLE` | Point `APP_POSTGRES_DSN` at the app role. |
   | `role_too_privileged` | Production: the role is a superuser, has `BYPASSRLS`, belongs to the schema owner or can `CREATE` in the schema | Revoke the privilege; re-run `setup`. |
   | `identity_key_mismatch` | This process's `APP_IDENTITY_HASH_KEY` differs from the key `setup` recorded in `neuron_meta` | Fix the replica's secret. To change the key on purpose, follow the rotation steps (it orphans threads) and run `setup --rotate-identity-key`. |
   | `identity_key_unrecorded` | `neuron_meta` has no check value, or migration 12 is missing | Run `setup` with `APP_IDENTITY_HASH_KEY` set, as a deploy step before the new image starts. |
   | `identity_check_unsafe` | The function the session resolves is not the migrator's SECURITY DEFINER `neuron_identity_status` (shadowed or altered) | Run `setup` as the migration role again; investigate who created or changed the function. |
   | `store_missing` | Memory is on (`APP_MEMORY_ENABLED=true`) and the `store` table does not exist | Run `setup` with `APP_MEMORY_ENABLED=true` as the deploy step. |
   | `store_no_access` | The `store` table exists but this role cannot read and write it | Run `setup` as the migrator; it grants the app role DML on `store` only. |
   | `database_check_failed` | The check query itself failed (privileges, connection loss); the log has the exception class only | Check the app role's grants (`setup` re-applies them) and database availability. |

   The app role cannot read `neuron_meta`: the identity check calls `neuron_identity_status(text)`, a `SECURITY DEFINER` function (migration 12) that returns `match`, `mismatch` or `unset` for the check value the caller sends and never the stored one.
3. **Create or migrate the schema** as a deploy step, before the new version serves traffic: `python -m neuron_agent.persistence.cli setup` (`make db-setup` in a checkout; the runtime image has no `make`). It runs LangGraph's `AsyncPostgresSaver.setup()`, then neuron's own ordered migrations (`persistence/migrations.py`), each recorded in the `neuron_migrations` table; migration 1 is `neuron_checkpoints_owner_idx`, the index behind `/v1/me/*`. It exits non-zero on any failure, so a Render pre-deploy command cancels the deploy. Without the index, `/v1/me/*` still works but scans the `checkpoints` table.
   - **Migration DSN.** `APP_POSTGRES_MIGRATION_DSN` (a `SecretStr`, never logged or printed) is a direct, non-pooled connection as the migrator role. In staging and production `setup` requires it and never falls back to `APP_POSTGRES_DSN`; development and test fall back to the runtime DSN. Only `persistence.cli` reads it. Keep it out of the web process where the platform allows; the pre-deploy command shares the service environment on Render, so a test pins that only the CLI reads it (ADR 0008 open question 20).
   - **One at a time, and bounded.** `setup` holds a session-level advisory lock on that connection for its whole run, so concurrent runs (a pre-deploy and an operator) serialise; a second run waits up to five minutes. Transactional DDL runs with a `lock_timeout` of five seconds, so a migration blocked behind live traffic fails instead of queueing requests behind it; run `setup` again when it clears. Concurrent index builds run outside a transaction under a separate `lock_timeout` of ten minutes, because `CREATE INDEX CONCURRENTLY` also waits for older transactions to finish (a session idle in a repeatable-read or write transaction holds it up), and five seconds would fail the deploy and leave an `INVALID` index; a transaction that outlasts ten minutes still fails the deploy. An `INVALID` index left by a failed concurrent build is dropped and rebuilt on the next run, but only for a migration that names its `index`; an index that was recorded as applied and later dropped by hand is not repaired, and LangGraph's own indexes are out of scope.
   - **Lock wait vs. build time.** A second `setup` waits at most 300 seconds for the advisory lock, which can be shorter than a large index build by the first; it then fails with "another setup held the migration lock for too long". Re-run it after the first finishes.
   - **Free plans have no pre-deploy command** (ADR 0008 decision 17): run `python -m neuron_agent.persistence.cli setup` by hand, or from a GitHub Actions step, before promoting the deploy.
   - **Errors** print the exception class and SQLSTATE only, never the DSN, host, password or driver message.
   - **Compatibility rule (expand/contract).** A release's migrations must leave the previous release working: add tables, nullable columns and concurrent indexes; remove or rename only in a later release, after no running image uses the old shape. A test refuses `DROP`, `RENAME`, `ALTER ... TYPE`, `ADD COLUMN ... NOT NULL` without a default, `SET NOT NULL`, `ADD CONSTRAINT` without `NOT VALID` and `CREATE [UNIQUE] INDEX` without `CONCURRENTLY`, unless the migration sets `contract_release` to the release whose image stopped using the old shape. There are no down-migrations; rollback is redeploying the previous image. A `langgraph-checkpoint-postgres` bump follows `docs/rollback-test-checkpoint-postgres.md`.
   - `APP_CHECKPOINTER_SETUP_ON_STARTUP=true` runs the same steps at app startup for local use (and `docker compose`). It is refused in staging and production.
   `APP_LIMITS_BACKEND` (`auto`, `memory`, `postgres`; `auto` is `memory` in development and test and is refused in staging and production; production also refuses `memory`) selects where the rate limit, token budget and run guards live. `postgres` requires `APP_POSTGRES_DSN` even with `APP_CHECKPOINTER=none`; the pool then opens for the guards and `/health/ready` checks it. The run guard (thread busy and per-user concurrent runs), the token budget (see Scaling) and the request rate limiter (see Rate Limiting) all have Postgres implementations, so with `postgres` no guard is per process except the stream cap. The rate limiter's IP keys are HMACs under a key derived from `APP_IDENTITY_HASH_KEY`, so the app refuses to start with `postgres` and `APP_RATE_LIMIT_ENABLED=true` when that key is unset. `auto` never selects `postgres`. Staging and production rules for this setting are still to come (#138).
4. **Size the pool.** `APP_POSTGRES_POOL_MAX_SIZE` (default `10`) is per process. Each run holds a connection only briefly per checkpoint read or write, so a pool of 10 serves far more than 10 concurrent runs. Keep `replicas × workers × pool size` under the database's `max_connections`, leaving headroom for the prune job and admin access. `APP_POSTGRES_POOL_TIMEOUT_SECONDS` (default `10`) bounds the wait for a connection; exceeding it surfaces as `503 persistence_error`.
5. **Back up** like any user-data store, with retention aligned to `APP_THREAD_RETENTION_DAYS` (see below). Restoring a backup restores conversations, including ones deleted after it was taken.
6. **Watch** `checkpoint_operation_slow`, `checkpoint_operation_failed` and `checkpointer_unreachable` (see Logs and Traces).

**Per-user memory** (ADR 0009, off by default). With `APP_MEMORY_ENABLED=true` run `setup` again (it creates the `store` table as the migrator and grants the app role DML on it only) before deploying; readiness (`/health/ready`) stays 503 until the table exists. `APP_MEMORY_TTL_DAYS` makes memories expire; `prune` removes the expired ones of users who never return. Memories are user data: thread deletion does not remove them, the user-data routes do (#247). Back them up with the rest of the database.

Local Postgres for development: `docker compose up` starts the API and Postgres 16 with persistence enabled and the schema created on startup. Integration tests use any reachable database: `APP_TEST_POSTGRES_DSN=postgresql://... make test-integration`.

**Agent Server deployments** don't use any of this: Agent Server provides its own persistence for the `langgraph.json` graph.

### Database roles

ADR 0008 decision 15. Two login roles per environment: `neuron_migrator` owns the schema and is used only by `setup` (`APP_POSTGRES_MIGRATION_DSN`); `neuron_app` is the runtime role (`APP_POSTGRES_DSN`, also used by `prune`). Create them once, as the database owner or an admin role, with `psql -v migrator_password=... -v app_password=... -f roles.sql` (choose the passwords yourself and keep them out of shell history and the repository):

```sql
CREATE ROLE neuron_migrator LOGIN PASSWORD :'migrator_password'
    NOSUPERUSER NOCREATEDB NOCREATEROLE;
CREATE ROLE neuron_app LOGIN PASSWORD :'app_password'
    NOSUPERUSER NOCREATEDB NOCREATEROLE;
GRANT CONNECT ON DATABASE :"DBNAME" TO neuron_migrator, neuron_app;
-- The migrator owns the schema; nobody else may create objects in it. (Before Postgres 15
-- PUBLIC can create in `public`, so this REVOKE is what keeps the app role from it.)
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
ALTER SCHEMA public OWNER TO neuron_migrator;
-- WARNING: ALTER SCHEMA public OWNER TO ... is only safe on a database dedicated to Neuron.
-- If tables already exist and another role owns them, transfer them first (below); setup
-- verifies the grants took effect and fails in production if they did not.
-- Only for a database that already holds neuron tables owned by another role:
-- ALTER TABLE checkpoints, checkpoint_blobs, checkpoint_writes, checkpoint_migrations,
--     neuron_migrations, neuron_run_leases OWNER TO neuron_migrator;
```

- **What `setup` grants.** After every run, as the migrator, `setup` grants the app role `USAGE` on the schema and `SELECT, INSERT, UPDATE, DELETE` on `checkpoints`, `checkpoint_blobs` and `checkpoint_writes`; `SELECT, INSERT, DELETE` on `neuron_run_leases`; nothing on `neuron_migrations`, `checkpoint_migrations` and `neuron_meta` (the identity check value is an offline oracle for a weak key, so the app role does not read it). It also sets default privileges so tables the migrator creates later (LangGraph's `setup()` after an upgrade, a future migration) are readable and writable by the app role. The app role never gets `CREATE`, `DROP`, `TRUNCATE`, `REFERENCES`, `TRIGGER` or ownership. The grants repeat on every run, so they are idempotent and a table added by an upgrade is covered. Each phase runs in one transaction, and a migration that creates a table is tightened in its own transaction, so a failed `setup` never leaves the app role with DML on a bookkeeping table. After granting, `setup` checks the result with `has_table_privilege` and logs `app_role_grants_applied` only if the matrix is what it intended (a `GRANT` by a role that does not own the table only warns); in production a mismatch, or an app role that is a superuser, has `BYPASSRLS`, is a member of the migrator or can `CREATE` in the schema, fails `setup` with a fixed message. A table a new migration adds that needs less than the default DML must be tightened in `persistence/migrations.py` (`table_grant_statements`).
- **Role name.** `APP_POSTGRES_APP_ROLE` (default `neuron_app`) names the role `setup` grants to; it must match the user in `APP_POSTGRES_DSN`.
- **Run as.** `python -m neuron_agent.persistence.cli setup` connects as the migrator; the web service and `prune` (`make prune-threads`) connect as the app role. Both commands are operator-only CLIs with no HTTP route.
- **One role (staging only).** If the platform will not let you create roles (ADR 0008 decision 17, open question 20: not proven on Render's free plan), use one role for both DSNs. `setup` then logs `app_role_grants_skipped` and applies no grants, because the role that owns the tables already has every privilege. This leaves the web process able to drop tables, so it is accepted for a disposable staging database only. With `APP_ENV=production`, `setup` fails if the app role is missing or is the migrator itself.
- **Checks.** `psql` as `neuron_app`: `DROP TABLE checkpoints` and `TRUNCATE checkpoints` must fail, and `CREATE TABLE x (a int)` must fail with `permission denied for schema`. The `postgres` tests run exactly this against a real database.
- Not yet checked: that a managed database whose owner is not a superuser accepts the `ALTER SCHEMA ... OWNER TO` above (it may need `GRANT neuron_migrator TO <owner>` first), and that Render allows `CREATE ROLE` at all.

## Streaming Behind a Reverse Proxy

`/v1/agent/stream` is a long-lived `text/event-stream` response. Proxies must not buffer or time it out:

- **Disable response buffering.** The API sends `X-Accel-Buffering: no`, which nginx honours. Elsewhere, set `proxy_buffering off;` or the equivalent for that proxy.
- **Raise idle and read timeouts** above `APP_STREAM_HEARTBEAT_SECONDS` (default `15`); heartbeats keep idle streams alive. Also allow at least `APP_RUN_TIMEOUT_SECONDS` (default `120`) for the whole response.
- **Don't compress `text/event-stream`.** Compression buffers output.
- **Use HTTP/1.1 or newer** to the upstream, with keep-alive.

```nginx
location /v1/agent/stream {
    proxy_pass http://neuron_api;
    proxy_http_version 1.1;
    proxy_set_header Connection "";
    proxy_buffering off;
    proxy_read_timeout 180s;
    gzip off;
}
```

Clients that disconnect stop their run: model and tool calls are cancelled. A client that stops reading for 30 s is disconnected. On shutdown, open streams keep running for `APP_SHUTDOWN_DRAIN_SECONDS`, then receive `error {"code": "service_shutting_down", "retryable": true}` within 2 s, then `done` (see Shutdown).

## HTTP Surface

| Setting | Default | Meaning |
| --- | --- | --- |
| `APP_CORS_ALLOWED_ORIGINS` | `[]` (CORS off) | JSON list of exact browser origins, such as `["https://app.example.com"]`. Each must be a lowercase `scheme://host[:port]` with no path or trailing slash, because browsers send exactly that. `*` is rejected. |
| `APP_EXPOSE_API_DOCS` | `true` in development/test, `false` in staging/production | Serve `/docs`, `/redoc` and `/openapi.json`; otherwise they return `404`. The schema declares the bearer (`JWT`) scheme on every `/v1/*` route. |
| `APP_ALLOWED_HOSTS` | `[]` (any host) | JSON list of accepted lowercase hostnames, without scheme or port (the port is ignored when matching); `*.example.com` matches subdomains. Other hosts get `400 Invalid host header`. `/health/*` is exempt, since probes usually address the instance by IP. Set it in production for self-hosted deployments. |
| `APP_HSTS_MAX_AGE_SECONDS` | `0` (off) | Sends `Strict-Transport-Security: max-age=N`. Required (> 0) in production; enable elsewhere only when every client reaches the API over HTTPS. |

CORS allows `GET`, `POST` and `DELETE` with the `Authorization`, `Content-Type` and `X-Correlation-ID` request headers, and exposes `Retry-After` and `X-Correlation-ID` to scripts. Preflights are cached for 10 minutes. Credentialed (cookie) CORS is never enabled: browsers send the bearer token in `Authorization`.

Every response carries `X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer` and `Content-Security-Policy: default-src 'none'; frame-ancestors 'none'`. `/v1/*` responses, including errors and streams, carry `Cache-Control: no-store`. Unhandled errors are answered as `500 {"detail": "internal_server_error"}` with the same headers. If the proxy adds security headers of its own, don't repeat these: nginx `add_header` appends rather than replaces, so clients would receive both copies. The stream's `X-Accel-Buffering: no` is consumed by nginx and is unaffected by these headers.

## Web Application

The browser application (`web/`, ADR 0010) is a static single-page app on its own origin. The API image does not serve it, has no static-file route, and cannot contain it (`.dockerignore` is an allowlist). To run it you build `web/dist`, serve it from any static host with the headers below, and point the API and the identity provider at its origin.

### Build

With the Node version in `web/.nvmrc`: `make web-install` (installs from the lockfile only) then `npm --prefix web run build`. These are read at build time (`web/README.md`):

| Variable | Default | Meaning |
| --- | --- | --- |
| `VITE_API_URL` | `http://127.0.0.1:8000` | The API origin. Must be `https`, or `http` on loopback; an origin only, no path. The bearer token is sent only here. |
| `VITE_OIDC_ISSUER` | `http://localhost:8180/realms/neuron` | The identity provider's issuer. `https`, or `http` on loopback. |
| `VITE_OIDC_CLIENT_ID` | `neuron-web` | The public client. |
| `VITE_MAX_PROMPT_CHARS` | `12000` | Mirrors `APP_MAX_PROMPT_CHARS`; the server stays authoritative. |

### The API side

- **CORS:** put the UI's exact origin in `APP_CORS_ALLOWED_ORIGINS` (for example `["https://app.example.com"]`; see HTTP Surface). The app sends only `GET`, `POST` and `DELETE` with `Authorization`, `Content-Type` and `Accept`, and reads `Retry-After`; all are already allowed or exposed. Cookies are never used.
- **Scopes:** the UI needs `agent:invoke`, `agent:approve`, `threads:read`, `threads:write`, `feedback:write`, `threads:delete`, `memories:read` and `memories:write`. A user with fewer sees the matching action refused, not a broken page.

### The identity provider (Keycloak)

`deploy/keycloak/neuron-realm.json` is the **development** realm, not a production export. What a real provider must provide, whichever it is:

- A **public** client with the **authorization code** flow and **PKCE `S256`**; no implicit, password or service-account grants for the browser client.
- **Exact** redirect and post-logout redirect URIs (the UI's origin root, for example `https://app.example.com/`), no wildcard.
- Access tokens with `aud` containing `APP_AUTH_AUDIENCE`, and the user's roles in a top-level `roles` claim (or scopes in `scope`), mapped to permissions with `APP_AUTH_ROLE_PERMISSIONS`. In Keycloak, a client with *Full scope allowed* **off** and no scope mappings drops realm roles from the token, so `roles` arrives empty; either leave it on or map the roles.
- Short access-token lifetimes. The UI keeps the token in memory only and does not use the refresh token.
- The API requires `nbf` in access tokens. If your provider omits it, sign-in succeeds but every API call is a `401`; check this first.

### Headers to serve

`scripts/web_headers.py` prints the content security policy and the other headers for your two origins, in `json`, `nginx` or `headers` (the `_headers` file read by Netlify and Cloudflare Pages) format:

```bash
python scripts/web_headers.py --api-origin https://api.example.com \
    --issuer https://id.example.com/realms/neuron --format nginx
```

The policy: `default-src 'none'`; scripts, styles, images and fonts from `'self'` only (no inline script or style, no `eval`, no `data:`); `connect-src` limited to the API and the identity provider; `frame-src` to `'self'` and the identity provider; `base-uri`, `form-action`, `object-src` and `worker-src` `'none'`; `upgrade-insecure-requests`. With it: `Referrer-Policy: no-referrer` (the sign-in callback URL carries a one-time code), `X-Content-Type-Options: nosniff`, `Cross-Origin-Opener-Policy` and `Cross-Origin-Resource-Policy` `same-origin`, a `Permissions-Policy` that turns off device APIs, and HSTS. `index.html` is `no-cache`; `/assets/*` is hashed and `immutable`.

Two things to know:

- **`frame-src` includes `'self'`.** The silent-renew frame starts at the identity provider and is redirected back to the app root, and a CSP `frame-src` is checked on every redirect hop. Without `'self'` the frame ended on a browser error page and every session ended at token expiry (found by the first real-browser run, `docs/releases/v0.9.0-gate/browser/`).
- **`frame-ancestors 'self'`, not `'none'` as ADR 0010 first said.** Silent renew loads this app inside a hidden frame of itself (the redirect URI is the app root), so `'none'` would block it. `'self'` still stops every other site from framing the app. If you give up silent renew, `'none'` is the stricter choice.
- **nginx does not inherit `add_header` into a block that has its own `add_header`.** The nginx output repeats the full set in every location for that reason; if you write your own, do the same, or a cache rule will silently remove the CSP from the HTML.

The headers are tested as a policy (`tests/unit/test_web_headers.py`), together with a check that the web source needs nothing the policy forbids. They have **not** been enforced by a real browser against a deployed build: no browser test (Playwright) has run, so a directive that is too strict for something the app does would show up only there.

## Conversation Retention and Deletion

- **Schedule retention.** Run `make prune-threads` (`python -m neuron_agent.persistence.cli prune`) daily, for example from cron or a Kubernetes CronJob, using the same `APP_CHECKPOINTER` and `APP_POSTGRES_DSN` as the API.
  - It deletes threads whose last checkpoint is older than `APP_THREAD_RETENTION_DAYS` (default `30`); `--older-than-days N` overrides that.
  - It's idempotent and logs `thread_prune_job_completed` with a count and emits the `threads_pruned` audit record.
  - On Postgres it selects stale threads with one aggregate query over root-namespace checkpoints.
- **User deletion requests.** Handle them with `DELETE /v1/threads/{thread_id}` (`204`). It returns `409 thread_busy` while a run is in flight; retry after it finishes.
- **Backups.** Database backups keep deleted threads until the backups expire. Size backup retention against your data-retention policy.

### Upgrade from v0.3 identity to JWT ownership

v0.3 threads store an unkeyed SHA-256 owner derived from request-provided identity;
JWT mode uses a keyed HMAC of the verified `(iss, sub)`. These formats are
intentionally incompatible, and JWT mode will treat every legacy thread as
not-found. Do not add a dual-hash fallback.

The supported rollout preserves security and lets old threads expire:

1. Before enabling JWT mode, provision the issuer, audience, JWKS URL, and a
   stable `APP_IDENTITY_HASH_KEY` (at least 32 characters) as deployment
   secrets. Keep the key stable across all replicas and restarts.
2. Confirm `make prune-threads` runs at least daily against the same Postgres
   database and `APP_THREAD_RETENTION_DAYS` configuration as the API. Configure
   backup expiration to match the approved conversation retention policy.
3. Record the time of the last v0.3 write, then deploy with `APP_AUTH_MODE=jwt`.
   Legacy conversations are unavailable after the switch; clients start new
   threads. Do not promise old-thread access during the transition.
4. Continue scheduled pruning for one full `APP_THREAD_RETENTION_DAYS` window
   after the last legacy write. After that window, all legacy threads should
   have been pruned; verify the `thread_prune_job_completed` job logs and database state
   before considering the migration complete.

If customers require uninterrupted access, stop the rollout and design a
separately reviewed migration that can authenticate each legacy owner and map
it to a verified principal. Do not infer that mapping from user-controlled
values or rewrite checkpoint ownership in place without an auditable plan.

## Rate Limiting

`/v1/agent/*`, `/v1/threads/*` and `/v1/me/*` enforce token-bucket limits (`APP_RATE_LIMIT_ENABLED=true` by default). Authenticated requests are keyed by the verified principal's opaque owner HMAC; in local `AUTH_MODE=none`, and after failed JWT authentication, the key is the client IP. Defaults: burst capacity `APP_RATE_LIMIT_BURST=20`, refilling at `APP_RATE_LIMIT_REQUESTS_PER_WINDOW=60` per `APP_RATE_LIMIT_WINDOW_SECONDS=60`. Exceeding it returns `429 {"detail": "rate_limited"}` with `Retry-After`; health endpoints are exempt. The limiter's memory is bounded: a bucket idle long enough to have refilled completely (`burst / refill rate`, 20 s by default) is dropped, and at most 10,000 keys are tracked per worker, least recently used dropped first. A dropped key restarts with one full bucket, never more, so a flood of distinct client IPs cannot grow memory without bound and cannot gain extra allowance.

Key scheme: two limiters per worker, each with the same limits and the same 10,000-key cap (with `APP_LIMITS_BACKEND=memory`), so junk client IPs can never evict a principal's bucket.

| Limiter | Key | Used for |
| --- | --- | --- |
| principal | `principal:<owner HMAC>` | requests with a verified token |
| IP | `ip:<HMAC of the address>` (the plain address when `APP_IDENTITY_HASH_KEY` is unset, in memory only) | `AUTH_MODE=none` requests and failed JWT authentication |

The address is the client's IPv4 address, or its IPv6 `/64` network (`ip:2001:db8:1:2::/64`), so one IPv6 subscriber shares one bucket however many addresses it uses. The /64 grouping is a coarse pre-auth guard: an attacker holding a /48 can rotate through 65,536 /64s. An IPv4-mapped IPv6 address (`::ffff:192.0.2.5`) is keyed as the plain IPv4 address. A peer address that does not parse as an IP is used as given.

Behind a trusted proxy, all `X-Forwarded-For` lines are joined and read right to left, skipping trusted hops. Each entry may be a bare IP, `ip:port` (IPv4), `[v6]` or `[v6]:port`; a valid port (0-65535) is stripped. The first entry that does not parse (`203.0.113.8:`, `[2001:db8::1]:x`, `2001:db8::1]:443`, a port above 65535) ends the walk, and the last address read is the key; nothing to the left of it is believed. A bare IPv6 address cannot carry a port.

By default, `X-Forwarded-For` is ignored. Set `APP_TRUSTED_PROXIES` to a JSON list of trusted proxy IP addresses/CIDRs only when the app is reachable exclusively through those proxies. Do not configure Uvicorn's `--forwarded-allow-ips`: `neuron-api` turns Uvicorn's proxy-header rewriting off, so the app's `_client_ip` is the only place proxy headers are parsed. The app uses forwarded addresses only when its immediate peer is in `APP_TRUSTED_PROXIES`, preventing clients from choosing their own IP bucket.

**Shared rate limiting in Postgres (#148).** With `APP_LIMITS_BACKEND=postgres` both limiters keep their buckets in one table, `neuron_rate_buckets (key, tokens, refilled_at, allowed)`, so a burst split across replicas is limited to `APP_RATE_LIMIT_BURST` in total.
   - **One write per request.** Each rate-limited request is one `INSERT ... ON CONFLICT DO UPDATE ... RETURNING` in a short transaction (`lock_timeout` 2 s, `statement_timeout` 5 s), with the time taken from the database clock (`clock_timestamp()`), never from a replica. A refused request writes too. In front of it, for requests that carry no valid identity (`AUTH_MODE=none` and failed JWT authentication), a bounded in-memory IP limiter with the same limits runs first, so a flood from one address is refused after one burst without any database write; authenticated requests go straight to the shared limiter.
   - **Keys.** `principal:<owner HMAC>` as before, and `ip:<HMAC>`: the client address (IPv6 as its /64) hashed under a key derived from `APP_IDENTITY_HASH_KEY` with HKDF and its own label, so it differs from the owner-key derivation. No raw address is stored. The result is pseudonymous, not anonymous (the IPv4 space can be brute-forced by anyone holding the key), so the table is personal data. Behind a trusted proxy the key is that of the real client: `X-Forwarded-For` is read right to left through `APP_TRUSTED_PROXIES` (the app does this itself; Uvicorn's proxy handling stays off), and a spoofed leftmost entry is ignored.
   - **`UNLOGGED` trade-offs.** The table is not written to the write-ahead log, which keeps the write per request cheap, and so it is **empty after a crash, an unclean shutdown, a failover or a point-in-time restore**: every key then starts with a full bucket, granting each caller one fresh burst until it refills. It is not replicated to a standby either. The limiter is a flood control, not a quota, and the token budget (logged) and run guard are unaffected. The cost is one database write for every rate-limited request.
   - **Idle rows.** A bucket idle for `burst / refill rate` has refilled completely, so deleting it changes nothing. About one write in 64 deletes up to 200 such rows, and the daily prune job (`make prune-threads`) deletes the rest (never a bucket idle for less than an hour), so the table stays proportional to the active keys.
   - **Fail closed.** Any database error, lock wait or pool timeout is `503` (`persistence_error`, detail hidden) and the request does not run; `neuron.errors` counts it by code and `rate_limiter_db_unavailable` is logged.
   - **Pool and hot keys.** A check holds a pool connection for a few milliseconds, but requests on one hot key queue on one row lock. Each process therefore allows at most `APP_POSTGRES_POOL_MAX_SIZE // 2` limiter transactions at once, waits up to 0.5 s for a slot and then fails closed (`503`), and the limiter's `lock_timeout` is 500 ms, so a flood on one key cannot drain the pool the checkpointer and the other guards share (during such a flood many requests get `503` rather than queueing).
   - **Bloat.** Every rate-limited request updates a row, so the table churns dead tuples. It is created with `fillfactor = 70` (room for HOT updates, which avoid index writes on the primary key but not on the `refilled_at` index, which changes on every update) and `autovacuum_vacuum_scale_factor = 0.02`. Expect a steady autovacuum load on this table and some bloat between vacuums; it holds at most one row per active key.
   - **Clock damage.** A row dated more than 5 s ahead of the database clock (a restore, a manual edit) is reset to the database time on its next check, with no extra tokens; `tokens >= 0` is a CHECK constraint.
   - **Pre-limit is best effort.** The in-memory IP pre-limit tracks at most 10,000 keys per process; an attacker rotating more distinct addresses evicts old entries and reaches the shared limiter, which still limits each key.
   - **Proxy.** `APP_TRUSTED_PROXIES` works only if the proxy appends the peer address to `X-Forwarded-For` rather than passing the client's header through. An unparseable rightmost entry (for example `203.0.113.8:x`) ends the walk, and the key falls back to the proxy's own address, so all clients share one bucket until the proxy is fixed.
   - **Deploy order.** Run `setup` before deploying a release that uses the Postgres limiter. A replica that starts before migration 10 reports ready but answers every rate-limited `/v1` request with `503` and logs `rate_limiter_db_unavailable` per request.
   - **Requirements.** Migrations 10 and 11 create the table and its index. The `setup` grant phase (#144) gives the application role `SELECT`, `INSERT`, `UPDATE` and `DELETE` on `neuron_rate_buckets`. `APP_IDENTITY_HASH_KEY` is required (see Scaling).

`APP_MAX_CONCURRENT_RUNS_PER_USER=2` caps active invoke and stream runs together per principal; the existing `APP_MAX_CONCURRENT_STREAMS=100` remains a per-process global stream cap. Exceeding the principal cap returns `429 too_many_concurrent_runs` and `Retry-After`.

Provider token usage from model `usage_metadata` is charged to a rolling per-principal window: `APP_USER_TOKEN_BUDGET=100000` tokens per `APP_USER_TOKEN_BUDGET_WINDOW_SECONDS=3600`. Admission reserves `APP_MAX_OUTPUT_TOKENS` plus a prompt estimate and is rejected before a run with `429 quota_exceeded` and `Retry-After` when the window plus that reservation exceeds the budget; the reservation is settled to the real usage after successful, failed, timed-out or cancelled runs (the whole reservation when the run reports no usage). With `APP_LIMITS_BACKEND=memory` each worker keeps independent in-memory counters; they reset on restart and are not coordinated across replicas, so multi-replica deployments must account for per-worker enforcement. With `APP_LIMITS_BACKEND=postgres` the budget is one shared, durable ledger (see Scaling). Tune all limits to provider quotas and workload sizes. Set `APP_RATE_LIMIT_ENABLED=false` only for controlled local diagnostics, not production.

## Timeouts and Retries

- `APP_REQUEST_TIMEOUT_SECONDS` (default 60s): per-attempt timeout on the model provider call (`ChatOpenAI(timeout=...)`).
- `APP_TOOL_TIMEOUT_SECONDS` (default 20s): per-call timeout on tool execution; exceeding it raises `ToolExecutionError` without leaking tool internals to the caller.
- `APP_PROVIDER_MAX_RETRIES` (default 2, i.e. 3 attempts total): retries for transient provider failures only (connection errors, provider timeouts, provider rate limits, 5xx), with exponential backoff and jitter. Non-transient failures (auth errors, malformed requests) are never retried.
- `APP_MAX_AGENT_ITERATIONS` (default 8, max 25): the most model calls one run may make, so at most 7 tool rounds plus the final answer. Each model call and each tool call is one LangGraph step, so the app passes `recursion_limit = 2 * APP_MAX_AGENT_ITERATIONS`. Exceeding it returns `422 agent_step_limit_exceeded` (a stream `error` event with the same code); it is logged as `agent_execution_failed` with `error_type=GraphRecursionError`, and the run and model spans carry it as `error.type`. Parallel tool calls in one model reply count once. The bound on a looping model is this count times `APP_REQUEST_TIMEOUT_SECONDS`, within `APP_RUN_TIMEOUT_SECONDS` and the per-user token budget.

Raise provider timeouts/retries cautiously in production — higher values increase worst-case request latency and hold HTTP connections open longer under provider degradation.

## Common Failures

| Symptom | Cause | Response |
| --- | --- | --- |
| Missing provider key in staging/production | `Settings.require_provider_key_outside_tests` fails fast at startup | process does not start; set `OPENAI_API_KEY` (or `NVIDIA_API_KEY` for `nvidia:` models) |
| Missing provider key in development | expected | fake local chat model serves requests; no live calls made |
| `429 rate_limited` | client exceeded the token bucket | caller retries after `Retry-After` seconds |
| `400 validation_error` | too-long, empty, whitespace-only or control-character message | reject before any model/tool call |
| `422 validation_error` | malformed JSON, unknown fields, wrong field types | reject before any model/tool call |
| `413 payload_too_large` | request body exceeds `APP_MAX_REQUEST_BODY_BYTES`. The limit counts the bytes received, so it applies with or without `Content-Length` (chunked bodies, and a declared length that understates the body, are cut off at the limit) and before authentication | reject before parsing. Uvicorn serves HTTP/1.1 only, so HTTP/2 framing is out of scope. A proxy-level body limit is defence in depth where the platform offers one |
| `504 provider_timeout_error` | model provider did not respond within `APP_REQUEST_TIMEOUT_SECONDS` | retried internally first; surfaces only after retries are exhausted |
| `502 tool_execution_error` | tool exceeded `APP_TOOL_TIMEOUT_SECONDS` or raised an unclassified exception | tool failure is isolated; it cannot crash the agent loop |
| `502 provider_error` / `structured_output_error` | upstream 5xx, or the model returned output that failed the `AgentAnswer` schema or was empty | internal detail is logged, not returned to the caller |
| `422 agent_step_limit_exceeded` | the agent used all `APP_MAX_AGENT_ITERATIONS` model calls without answering (a very long tool chain, or a model repeating tool calls) | the caller may rephrase or split the request; raise the limit only if legitimate requests hit it |
| `500 agent_execution_error` | an unclassified internal failure | check server logs' `error_type`/`error_code` fields |
| `503` with log `error_code=provider_quota_exhausted` | the model provider account has no credit (OpenAI `429 insufficient_quota`) | add credit or raise the quota; never retried, alerts on every request until fixed |
| `500 configuration_error` | unsupported model provider, malformed `provider:model` identifier, provider auth failure, or a model the provider does not offer this account (`404`) | fix configuration; never retried |
| `409 thread_busy` | another run on the same thread is still in flight (same process), or `DELETE` during a run | client retries after the current run finishes; normal for double-submits |
| `404 thread_not_found` | unknown thread, a different `user_id`, or persistence is `none` / was pruned | client starts a new conversation (omit `thread_id`) |
| `503 too_many_streams` | the process is at `APP_MAX_CONCURRENT_STREAMS` | scale out or raise the cap; watch `stream_rejected` |
| `504 run_timeout` / stream `error` `run_timeout` | the whole run exceeded `APP_RUN_TIMEOUT_SECONDS` | check provider latency and tool loops; raise the budget only alongside proxy timeouts |
| `503 persistence_error`, readiness `503` | Postgres unreachable, pool timeout, or a failed checkpoint operation | check the database and pool saturation; the pool reconnects automatically once Postgres is back; thread history is intact (turns commit only on success) |
| Spike in `stream_cancelled` | clients or a proxy dropping connections | check proxy buffering and timeouts (above) and client network; runs are cancelled, so no cost leak |
| Stream delivers everything at once | a proxy is buffering the response | disable buffering (above) |
| LangSmith unavailable | tracing endpoint unreachable | core request handling continues unless tracing is made mandatory by deployment policy |
| `Failed to export span batch` / `metrics` in logs | OTLP Collector unreachable or rejecting the export | requests are unaffected; check `OTEL_EXPORTER_OTLP_ENDPOINT`, headers and Collector health |

Every row above maps to the `AppError` taxonomy in `ARCHITECTURE.md`'s Failure Handling section; use the logged `error_code`/`error_type`/`retry_count`/`duration_ms` fields (see `ARCHITECTURE.md`'s Observability section) to diagnose which layer failed.

## Production Configuration Expectations

Before deploying to `staging`/`production`:

- `OPENAI_API_KEY` (or `APP_OPENAI_API_KEY`) must be set via the platform secret manager — startup fails fast otherwise.
- Use an `openai:` model. `nvidia:` models (NVIDIA API catalog) are meant for development on the free tier; they work in any environment, but the free tier isn't intended for production traffic or user data.
- `APP_ENV=production` (or `staging`).
- Leave `APP_RATE_LIMIT_ENABLED=true` (`false` is refused) and size `APP_RATE_LIMIT_*` for expected traffic; limits are per-instance with `APP_LIMITS_BACKEND=memory` and shared with `postgres`.
- Set `APP_LOG_LEVEL=INFO` (or stricter) — logs never include raw secrets or prompts regardless of level (see `SECURITY.md`).
- Review `APP_REQUEST_TIMEOUT_SECONDS`, `APP_TOOL_TIMEOUT_SECONDS`, and `APP_PROVIDER_MAX_RETRIES` against the deployment's latency SLOs; defaults are development-oriented starting points, not production guarantees.
- Enable LangSmith tracing (above) only if the project/API key are production-scoped; do not point a production deployment at a development LangSmith project.
- **Set `APP_CHECKPOINTER` explicitly.**
  - `postgres` for durable conversations, with the steps above completed. `memory` is rejected in staging and production.
  - `none` for a deliberately stateless deployment; it is logged at warning level at every start-up. `auto` is refused in staging and production.
- **Set `APP_LIMITS_BACKEND` explicitly.** `auto` is refused in staging and production; `memory` is refused in production (per-process guards are not shared across replicas).
- **Set `APP_ALLOWED_HOSTS`** to the served hostnames (an empty list, `*` and a wildcard over a whole TLD such as `*.com` are refused) and **`APP_TRUSTED_PROXIES`** explicitly: unset is refused, `[]` means no trusted proxy, and any range broader than /8 (IPv4) or /16 (IPv6) is refused. Write `APP_TRUSTED_PROXIES=[]`: an empty `APP_TRUSTED_PROXIES=` is a parse error in pydantic-settings, not an empty list.
- **Run schema setup as a deploy step.** `APP_CHECKPOINTER_SETUP_ON_STARTUP=true` is refused.
- **Database TLS.** Both `APP_POSTGRES_DSN` and `APP_POSTGRES_MIGRATION_DSN` must carry `sslmode` in the DSN itself (URI query or keyword form; `PGSSLMODE` is not consulted, and a missing `sslmode` is refused). Production needs `sslmode=verify-full`. **Staging exception (ADR 0008 decision 17, open question 6):** free-plan Render does not support `verify-ca` or `verify-full` on internal connections, so staging also accepts `require` and `verify-ca`; `prefer`, `allow`, `disable` and a missing `sslmode` are refused in both. Production is not deployed on the free plan, so it gets no exception. `require` encrypts but does not authenticate the server, so staging must never point at a production database. A Unix-socket DSN needs `sslmode` too (it is refused without; harmless).
- **API docs stay hidden in production:** `APP_EXPOSE_API_DOCS=true` is refused there.
- **JWKS host.** In staging and production `APP_AUTH_JWKS_URL` must not use `localhost` or a loopback, link-local or private IP literal. Host names are not resolved and redirects are not checked, so a public name that resolves to a private address, or a redirect to one, is not caught (accepted gap, `SECURITY.md`).
- **LangSmith content.** In production `APP_LANGSMITH_CONTENT_APPROVED=true` also needs `APP_LANGSMITH_CONTENT_APPROVAL_RECORD` naming the approval (ticket, ADR or review reference; never a secret).
- **Startup log.** The effective limits are logged once as `effective_limits` (rate, burst, concurrency, token budget, timeouts and the limits backend); check them after every deploy. Only the FastAPI app (`neuron-api`) emits this line, not an Agent Server deployment. With `APP_LANGSMITH_CONTENT_APPROVED=true` the approval record is logged once as `langsmith_content_capture_approved`.
- `APP_HSTS_MAX_AGE_SECONDS=0` is refused in production. `APP_AUTH_REQUIRE_TYP=false` is not refused (no identity provider is chosen); set it to `true` once the provider issues `typ: at+jwt`.
- **Schedule `make prune-threads`** and align `APP_THREAD_RETENTION_DAYS` with your data-retention policy.
- **Size the run guards.** Set `APP_RUN_TIMEOUT_SECONDS` and `APP_MAX_CONCURRENT_STREAMS` per instance, consistent with proxy timeouts and capacity.

## Smoke Test

After each deploy run `SMOKE_TEST_TOKEN=<token> uv run python scripts/smoke_test.py <base-url>` (ADR 0008 decision 12). It checks `/health/ready`, then makes one `POST /v1/agent/invoke` with a one-word prompt, and exits `0` if both pass, `1` if a check fails (non-ready, `401`/`403`, `5xx`, timeout, a non-JSON or wrong body, or a redirect) and `2` for misuse. `SMOKE_TEST_TIMEOUT_SECONDS` (default `60`) bounds each request. Output names the step and HTTP status only: neither the token nor the URL is printed or written to disk, and plain `http://` is refused except for loopback.

- **Smoke principal.** A dedicated IdP client (`sub` such as `smoke-test`), separate from every human and service user, with the single scope `agent:invoke`. Give it its own small `APP_TOKEN_BUDGET_*` allowance so a leaked token can spend little; the reply is capped by `APP_MAX_OUTPUT_TOKENS`.
- **Token lifetime.** Mint the token per run with a lifetime of 10 minutes or less, and mask it in the job log. Never commit it or store it in a long-lived variable.
- **Prefer workload identity federation.** Where the IdP supports it, exchange the CI job's GitHub OIDC token for the access token at run time, so no client secret is stored (ADR 0008, open question 2). Otherwise store the client secret as an Environment secret and add its rotation to the secret rotation runbook.
- **Retention of its requests.** With `APP_CHECKPOINTER=none` (the staging and production default) nothing is stored. With persistence on, the run creates one thread owned by the smoke principal; the script then calls `DELETE /v1/threads/{id}`, which needs `threads:delete`. Without that scope the script warns and the thread stays until `make prune-threads` removes it after `APP_THREAD_RETENTION_DAYS`. Grant `threads:delete` to the smoke principal only on deployments that persist threads; it can delete only its own threads.

## Runbooks

The reference deployment is Render (ADR 0008). Every Render-specific statement below is an **assumption** until a staging deploy has run it, and every procedure here is **unrehearsed**: nothing has been executed on a real deployment, which the owner deferred for this milestone. Commands name the repository's own tools, so they can be checked offline; fix a step when a real run disagrees. Never put a DSN, password, key or hook URL in a ticket, a chat or a shell history.

### Deploy

1. **Path.** Merge to `main`. `ci` and `image-publish` run; when `image-publish` succeeds, `deploy.yml` deploys staging by digest (see "Deploy pipeline"). To release, bump the version in `pyproject.toml` with a matching `CHANGELOG.md` section, merge, then push a `v*` tag on `main`; approve the `production` Environment when prompted.
2. **What pre-deploy does.** Render runs `python -m neuron_agent.persistence.cli setup` as the migrator before the new instances take traffic: LangGraph's schema, neuron's ordered migrations, grants for the app role, and the identity-key check value. A failure cancels the deploy and the previous release keeps serving.
3. **Watch a rolling deploy.** In the Render Dashboard, open the service's Events and Logs. Expect the new instances to pass `/health/ready` before the old ones drain (`maxShutdownDelaySeconds: 180`). Meanwhile, `neuron.service.ready` and the `NeuronInstanceNotReady` alert (`deploy/observability/prometheus-alerts.yaml`) show readiness from the telemetry side. A deploy that never goes ready is rolled back by Render's health check; confirm with the next step.
4. **Read the deployed digest.** The deploy job's log prints each service and its hook status; the digest is the `image-digest` artifact of the `image-publish` run for the commit (or tag). In the Dashboard the service shows the image reference it runs. They must be the same `@sha256:` value for every service of the environment.
5. **Verify.** `SMOKE_TEST_TOKEN=<token> uv run python scripts/smoke_test.py <base-url>` (see "Smoke Test"); exit `0` means ready and one authenticated invoke answered.

### Rollback

Rollback is redeploying the previous digest; there are no down-migrations (ADR 0008 decision 7).

1. **Choose the digest.** The previous release's `image-digest` artifact (the `image-publish` run of the previous tag's commit). Verify it with `gh attestation verify` as in "Published image and attestation".
2. **Redeploy it.** Re-run the `deploy.yml` production job for that tag (a re-run keeps the original digest), or in the Dashboard set each production service to that digest. Do both web and cron to the same digest.
3. **When it is safe.** Only while the previous release works against the current schema. Migrations are expand-only (add tables, nullable columns, concurrent indexes), so the previous release keeps working after a forward migration; a later release that contracts the schema (`contract_release` in `persistence/migrations.py`) cannot be rolled back past the release that stopped using the old shape. Check `neuron_migrations` against the previous release's `MIGRATIONS` list: the previous image must not need a table, column or index the database lacks.
4. **When a migration must be reverted.** Write a new forward migration that undoes it (a release of its own, through the pipeline); never edit LangGraph's tables or `neuron_migrations` by hand, and never `DROP` anything to "fix" a deploy. A `langgraph-checkpoint-postgres` bump follows `docs/rollback-test-checkpoint-postgres.md`.
5. **Verify** with the smoke test and `/health/ready`; record the digest rolled back to.

For a LangSmith/Agent Server deployment (not release-gating), revert to the previous repository revision. Before removing graph nodes or state fields, verify no active threads depend on them.

### Migration failure

`setup` prints the exception class and SQLSTATE only. Find the cause in the pre-deploy log, fix it, and run `setup` again (idempotent).

| Symptom | Cause | Action |
| --- | --- | --- |
| Pre-deploy exits non-zero; the previous release still serves | A migration failed or timed out | Read the class and SQLSTATE, fix, re-run `python -m neuron_agent.persistence.cli setup` as the migrator (a Render one-off job or the external connection). Do not edit `neuron_migrations`. |
| `lock_timeout` (SQLSTATE `55P03`) | A transactional migration waited five seconds behind live traffic | Re-run when the blocking transaction ends; find it with `SELECT pid, state, query_start, left(query, 80) FROM pg_stat_activity WHERE state <> 'idle' ORDER BY query_start;`. |
| "another setup held the migration lock for too long" | A second `setup` waited 300 seconds for the advisory lock while the first built a large index | Wait for the first to finish, then re-run. |
| An `INVALID` index | A concurrent build failed | `setup` drops and rebuilds it on the next run, for a migration that names its `index`. Check with `SELECT indexrelid::regclass FROM pg_index WHERE NOT indisvalid;`. |
| A long-running concurrent index build | Older transactions holding it up (ten-minute lock budget) | Find idle-in-transaction sessions in `pg_stat_activity`, end them with the owner's approval, re-run. |
| Start-up refuses with an `error_code` | See the start-up checks table under "Thread Persistence (Postgres)" | Fix the cause the table names; the pool is closed and the previous release keeps serving. |

### Roles

Create `neuron_migrator` and `neuron_app` once per environment with the `roles.sql` in "Database roles", then set the two DSNs (`APP_POSTGRES_MIGRATION_DSN` for the migrator, `APP_POSTGRES_DSN` for the app role). Verify as `neuron_app`: `DROP TABLE checkpoints` and `CREATE TABLE x (a int)` must fail.

**Rotate a role's password** (both DSNs change, with a short overlap):

1. `ALTER ROLE neuron_app PASSWORD '<new>';` as the owner. Existing pooled connections stay open; new ones need the new password.
2. Update `APP_POSTGRES_DSN` in the web service and the cron job, redeploy, confirm `/health/ready`.
3. Do the same for `neuron_migrator` and `APP_POSTGRES_MIGRATION_DSN` (the web service's environment; the pre-deploy shares it). Run `setup` once to prove the new migrator DSN.
4. Record the date. The old passwords are no longer valid; nothing else to revoke.

### Rotation

Each secret, with a maximum age (a rule for the owner to adjust). Rotate sooner after any suspected exposure or when a person with access leaves.

| Secret | Max age | Procedure |
| --- | --- | --- |
| `OPENAI_API_KEY` (provider key) | 90 days | Create the new key at the provider, set it on the web and cron services, redeploy, confirm a smoke test, revoke the old key. |
| Database role passwords | 90 days | "Roles" above. |
| IdP signing keys | Per the IdP | The IdP publishes the new key in its JWKS before signing with it; the service refetches the JWKS (see "Signing keys and JWKS caching"). Confirm tokens still verify; remove the old key at the IdP after tokens signed with it expire. |
| Smoke-test credential (`SMOKE_TEST_TOKEN` source) | 90 days, or federate | Rotate the IdP client secret, update the Environment secret. Prefer workload identity federation (see "Smoke Test"). |
| Deploy hooks (`DEPLOY_HOOKS`) | 180 days | In the Render Dashboard regenerate each service's deploy hook, update the Environment secret for that environment, and run a staging deploy. A leaked hook can trigger a deploy of the image it is given, not read data. |
| `APP_IDENTITY_HASH_KEY` | Only on exposure | A maintenance operation, below. |

**Rotate `APP_IDENTITY_HASH_KEY`.** It resets owner keys, budgets, buckets and leases, and orphans every thread: owners get `404` for their old threads, so tell users first.

1. Announce the maintenance window. Generate the new key (`python -c "import secrets; print(secrets.token_urlsafe(32))"`).
2. Scale the web service to zero (Dashboard) so no instance runs with the old key; keep the cron job from running during the window.
3. Set the new key on the web and cron services.
4. Run `python -m neuron_agent.persistence.cli setup --rotate-identity-key` once, by hand, as the migrator. Never leave that flag in the pre-deploy command.
5. Scale the web service back up. Run the smoke test. `make prune-threads` removes the orphaned threads at retention.
6. Record the date and that the threads were orphaned.

### Backups and restore

Assumptions to confirm in the Render account: the PITR window of the chosen plan, that backups are encrypted and keyed by Render, and the plan's backup retention. Record them here when known: window ____, encryption ____, retention ____.

- **Relation to retention.** A backup keeps threads that `APP_THREAD_RETENTION_DAYS` or a user's erasure later deleted, until the backup expires; size backup retention against the data-retention policy.
- **Replaying erasures after a restore.** After restoring to a point in time, re-apply every erasure made after that point: the audit log records each erasure (`thread_deleted`, `user_data_erased`; see "Conversation Retention and Deletion") with the actor and time; re-run each one, then `python -m neuron_agent.persistence.cli prune`. Do not return the restored database to service before the replay.
- **Restore to a new database** (the production database is not overwritten):
  1. Start the restore to a new Render Postgres instance from the Dashboard (point in time or latest backup). Keep `ipAllowList: []`.
  2. Create the roles with `roles.sql` and run `setup` as the migrator (it adds grants and is idempotent); the identity key must be the same value as production or every thread is orphaned.
  3. Point a staging copy of the service at it (never production) and run the smoke test; count threads: `SELECT count(*) FROM checkpoints;`.
  4. Record the restore start, the time it was usable (RTO) and the age of the newest restored data (RPO), using the template below.
  5. Delete the restored instance after the drill, and record the deletion.

  | Field | Value |
  | --- | --- |
  | Date, operator | |
  | Backup or PITR timestamp | |
  | Restore started / usable (RTO) | |
  | Newest data restored (RPO) | |
  | Smoke test result | |
  | Restored instance deleted at | |

  Rehearsed on the local reference stack in v0.9.0 (`scripts/dr_drill.py`; `docs/releases/v0.9.0-release-verification.md`): database usable 6.2 s after the restore started, smoke test passed 22.5 s after, newest restored data 2 s before the target time, the `UNLOGGED` rate table empty, the erased user's threads back until the replay. A restore on Render has not been rehearsed (deferred until after v1.0.0). Keep the WAL archive readable by the restoring container, and note that segments older than the base backup's first file are not needed.

### Capacity

**Measured throughput (v0.9.0, not hosted capacity).** `docs/releases/v0.9.0-gate/load-baseline.json`, from the reference stack (two replicas, Postgres, Keycloak, 4 CPUs shared with the load generator) and the fake model at 800 ms to first token, 40 tokens/s, 200 tokens: about 11 to 16 runs/s inside the SLOs (new thread 12.5, follow-up 11.2, approval 15.9, mix 12.4); with real-model latency (2000 ms to first token, 10 tokens/s, 75 tokens; `load-baseline-real-latency.json`) 15.6 to 21.6 runs/s. The real model was not load tested: the free NVIDIA key allows 40 requests per minute. The first failure is `503 too_many_streams` once about 200 streams are open (`APP_MAX_CONCURRENT_STREAMS`, 100 per process). Steps were 90 s, not 10 minutes; no CPU, database or pool metrics were recorded, so the limiting resource is unknown. Repeat with `make reference-up` and `make load`, and compare with `python -m loadtest.baseline compare` (same host and profile only). A load user needs a higher `APP_USER_TOKEN_BUDGET` than the default or its budget, not the stack, sets the rate.

Table sizes against the plan's storage. Run as the owner or migrator:

```sql
SELECT relname, pg_size_pretty(pg_total_relation_size(oid)) AS total
FROM pg_class
WHERE relname IN ('checkpoints', 'checkpoint_blobs', 'checkpoint_writes',
                  'neuron_run_leases', 'neuron_token_ledger',
                  'neuron_token_settlements', 'neuron_rate_buckets',
                  'neuron_thread_meta', 'neuron_feedback')
ORDER BY pg_total_relation_size(oid) DESC;
SELECT pg_size_pretty(pg_database_size(current_database()));
```

Threshold: investigate when the database passes 70% of the plan's storage, and raise the plan or shorten `APP_THREAD_RETENTION_DAYS` before 85%. The checkpoint tables dominate; the guard tables stay small (the daily prune deletes expired rows).

### Platform facts

Assumed for Render until confirmed in the account:

- **Logs.** Retention is set by the plan (record it: ____ days). Anyone with workspace access to a service can read its logs; the app logs no prompt, answer, token, DSN or key, and IP addresses appear only as a keyed prefix hash.
- **Who can read environment groups.** Every workspace member with access to the service, and any account-wide API key (see "Who can read the secrets"). Keep production and staging in separate workspaces.
- **The IP log prefix key is per process.** It is random at start-up (`_LOG_IDENTITY_KEY`), so the same address hashes differently in each process and after each restart; do not correlate across instances or restarts.
- **Egress.** The service can reach the internet. The SSRF helper (`validate_safe_url` in `security/input_policy.py`) is the only control on tool fetches; there is no network egress allow-list.

