# Security Audit Report: `neuron`

| | |
|---|---|
| **Repository** | https://github.com/Md-Nisar/neuron |
| **Commit reviewed** | `1c1adf219b7317c43bba7c9543924fe5c69f191b` (branch `main`, 2026-11-10) |
| **Report date** | 2026-11-11 |
| **Method** | Manual source review, configuration review, secret scan of the tree and of all 544 commits on `main`, dependency advisory lookup |
| **Overall rating** | **Low residual risk: 3 / 10** |
| **Findings** | 0 Critical · 0 High · 5 Medium · 10 Low · 5 Informational |

---

## 1. Executive summary

`neuron` is a FastAPI/LangGraph agent service (Python 3.13, about 19,000 lines in `src/`) with a React web client, a Keycloak login theme, a Postgres-backed knowledge (RAG) engine and a Render deployment blueprint.

**The codebase is unusually well defended.** No critical or high-severity vulnerability was found. No injection, authentication bypass, cross-tenant data access, SSRF, path traversal, unsafe deserialization or leaked credential was identified in the code that would ship to production.

The five medium findings are all availability or deployment-hardening issues:

1. **The unauthenticated readiness probe does database work on every call**, with no rate limit, cache or Host check. A modest flood can saturate the 10-connection pool and get healthy instances pulled from rotation.
2. **`CF-Connecting-IP` is trusted from any trusted proxy**, not only Cloudflare. Behind any other proxy a client can choose its own rate-limit key. This was introduced on 2026-11-09 as the fix for an earlier audit finding.
3. **Document downloads are buffered whole in memory with no concurrency cap**, so one authenticated user can exhaust a replica's memory.
4. **The container image serves an unauthenticated API on all interfaces** when started with `APP_ENV=development` and no auth settings.
5. **The Render blueprint gives the internet-facing web service the schema-owner database credential.**

Findings 3, 4 and 5 are already recorded as accepted limitations in the project's own `SECURITY.md` and threat model. Findings 1 and 2 are not documented anywhere in the repository.

**For technical leadership:** the main risk is not in the code but in what has not happened yet. The project's documentation states that no hosted deployment has ever run, so every production control here is validated by tests and local stacks only. Fix findings 1 and 2 before the first hosted deployment, and treat the first deployment as the point at which an external penetration test becomes worthwhile.

### Scope and limits of this audit

- **Reviewed in full:** `src/neuron_agent/` API, auth, authorization, egress, tools, MCP client, knowledge service, parsing, retrieval, blob storage and services; `web/src` auth, request and rendering code; all Dockerfiles, Compose files, `render.yaml`, the Keycloak realm, the OpenTelemetry Collector config, and the triggers, permissions, action pins and secret use of all 11 GitHub workflows.
- **Reviewed by targeted search:** `persistence/migrations.py`, the knowledge worker, `scripts/`, `loadtest/`, `keycloak-theme/` and `tests/`.
- **Static analysis only.** I did not run the application, its test suite or any exploit. Running repository code was not permitted in the audit environment. Every finding is confirmed by reading the code path end to end; none was exercised dynamically. The reproduction steps in section 4 are for you to run on a local stack.
- **No repository file was modified** and nothing was tested against any live system.
- The repository contains an earlier self-audit (`audit/security/`, `docs/security/`). I reviewed the current code independently and note where my findings overlap with, or result from, that work.

---

## 2. Overall security assessment

| Area | Assessment | Notes |
|---|---|---|
| Authentication | **Strong** | Asymmetric-only JWT allow-list, required `iss/aud/exp/nbf/iat/sub`, key-bound algorithm, token size cap, JWKS refresh throttling (`security/auth.py:174-239`) |
| Authorization and tenant isolation | **Strong** | One route dependency for every `/v1` route; owner key is an HMAC of the verified issuer and subject; every knowledge query filters on it; identical `404` for missing and foreign objects |
| Injection | **Strong** | All SQL is parameterized or built with `psycopg.sql` identifiers and literals; no shell, `eval` or template execution on request paths |
| SSRF and egress | **Strong** | Literal-host validation plus a resolve-once, connect-to-checked-IP network backend (`security/egress.py`) |
| File upload | **Strong** | Content sniffing, zip-bomb and macro checks, random storage keys, attachment-only downloads with `nosniff` |
| LLM-specific controls | **Good** | Tool allow-list and scopes enforced in code, human approval for mutating tools, taint tracking, framed retrieval output, citation validation |
| Web client | **Strong** | Tokens in memory only, PKCE S256, state and nonce, no raw HTML, images never loaded |
| Secrets | **Strong** | None in the tree or in history; settings use `SecretStr`; DSN redaction on driver logs |
| Supply chain and CI | **Strong** | All actions pinned by commit SHA, least-privilege tokens, digest-pinned base images, attested and Trivy-scanned image |
| Availability | **Needs work** | Findings M-01, M-03, L-02 |
| Deployment configuration | **Needs work** | Findings M-02, M-04, M-05, L-03, L-04, L-05 |

---

## 3. Findings summary

Status key: **Confirmed** = the code path was read end to end and the behaviour follows directly from it. **Potential** = depends on a deployment choice or configuration not fixed by the repository.

| ID | Severity | Title | Status | Known to project? |
|---|---|---|---|---|
| M-01 | Medium | Unauthenticated readiness probe queries the database on every request | Confirmed | No |
| M-02 | Medium | `CF-Connecting-IP` trusted from any trusted proxy: rate-limit key spoofing | Confirmed, exploitable only behind a non-Cloudflare trusted proxy | No (introduced 2026-11-09) |
| M-03 | Medium | Document downloads buffered in memory with no concurrency cap | Confirmed | Yes, as a stated limit |
| M-04 | Medium | Image serves an unauthenticated API on all interfaces in development mode | Potential (operator misconfiguration) | Yes, accepted |
| M-05 | Medium | Schema-owner database credential in the internet-facing web service | Confirmed in `render.yaml` | Yes, accepted |
| L-01 | Low | Data-rights routes exceed their scope names | Confirmed | Partly (erase decided; export not) |
| L-02 | Low | One user can hold every upload slot | Confirmed | No |
| L-03 | Low | Unauthenticated telemetry Collector shared by staging and production | Confirmed in config | Yes, accepted |
| L-04 | Low | Outdated and tag-pinned third-party images in deployment files | Confirmed | No |
| L-05 | Low | Static-site CSP hardcodes loopback origins | Confirmed | No (introduced 2026-11-09) |
| L-06 | Low | JWT type check off by default; no token revocation | Confirmed | Yes |
| L-07 | Low | Throwaway credentials and an HMAC key in tracked development files | Confirmed | Yes, labelled |
| L-08 | Low | AI review workflow runs pull-request code with a provider secret | Confirmed | Partly |
| L-09 | Low | Developer tooling fetches an unpinned package at run time | Confirmed | No |
| L-10 | Low | Document text may cross the internal network in clear text | Potential | Partly |
| I-01 | Info | Readiness response names the environment | Confirmed | Yes |
| I-02 | Info | MCP calls use one operator token for every user | Confirmed (feature off by default) | Yes |
| I-03 | Info | Agent Server deployment path skips rate limits and token budgets | Confirmed | Yes |
| I-04 | Info | Row-level security covers two tables only | Confirmed | Yes |
| I-05 | Info | System-prompt output guard is verbatim-only | Confirmed | Yes |

---

## 4. Detailed findings

### M-01: Unauthenticated readiness probe queries the database on every request

**Severity:** Medium · **Status:** Confirmed · **CWE-400, CWE-770**

**Location**
- `src/neuron_agent/api/main.py:625-629`: `GET /health/ready` calls `service.is_ready()` on every request.
- `src/neuron_agent/persistence/checkpointer.py:258-292`: `is_ready()` takes a pool connection and runs one or two catalog queries, with a 2-second timeout.
- `src/neuron_agent/api/main.py:197`: `/health/` is not in `_RATE_LIMITED_PREFIXES`.
- `src/neuron_agent/api/main.py:426-431`: `/health/*` skips the `Host` allow-list.
- `render.yaml:44,113`: this path is the public service's health check.

**Technical explanation.** The route needs no token, has no rate limit, no cached result and no Host check. Each call borrows a connection from the pool that the checkpointer, rate limiter, token budget and run guard share (`APP_POSTGRES_POOL_MAX_SIZE`, 10 in `render.yaml:204-205`). Under concurrent probes the pool queue grows. Two things follow:

1. The Postgres rate limiter waits at most 0.5 seconds for a slot and then fails closed (`persistence/rate_limiter.py:51,160-165`), so authenticated requests start returning `503`.
2. Probes that wait more than 2 seconds for a connection time out, `is_ready()` returns `False`, and the endpoint itself answers `503`. The platform's own health check hits the same endpoint, so it can mark healthy instances unhealthy and restart or remove them.

A background task already evaluates readiness every 15 seconds for a metric (`api/main.py:142-162`). Its comment notes that a flood of probes cannot move the gauge, but each probe still reaches the database.

**Business impact.** An anonymous client with a few hundred concurrent connections can degrade or take down the API for all tenants, without sending a single request the rate limiter sees.

**Evidence**
```python
# src/neuron_agent/api/main.py:625-629
@app.get("/health/ready")
async def ready() -> JSONResponse:
    if not await service.is_ready() or not await auth_verifier.ready():
        return JSONResponse(status_code=503, content={"status": "not_ready"})
    return JSONResponse(content={"status": "ready", "environment": settings.env})
```

**Safe reproduction (local stack only)**
1. `docker compose up --build`, then wait for the API on `127.0.0.1:8000`.
2. Record the transaction counter: `docker compose exec postgres psql -U neuron_owner -d neuron -c "select xact_commit from pg_stat_database where datname='neuron'"`.
3. Send 50 probes with an arbitrary Host header: `for i in $(seq 50); do curl -s -o /dev/null -H 'Host: not-allowed.example' http://127.0.0.1:8000/health/ready; done`.
4. Repeat step 2. The counter rises by roughly one transaction per probe, every probe returned `200`, and none was rate limited or refused for its Host.

Do not run a high-volume version against anything you do not own.

**Remediation.** Serve the probe from a short-lived cached result, so the database sees at most one check per interval however many probes arrive. Keep the draining check uncached so shutdown still turns the probe to `503` at once.

```python
# src/neuron_agent/api/main.py
_READY_TTL_SECONDS = 2.0
_ready_at: float | None = None
_ready_value = False
_ready_lock = asyncio.Lock()


async def _cached_ready() -> bool:
    global _ready_at, _ready_value
    if service.draining:
        return False
    now = time.monotonic()
    if _ready_at is not None and now - _ready_at < _READY_TTL_SECONDS:
        return _ready_value
    async with _ready_lock:  # concurrent probes share one evaluation
        if _ready_at is None or time.monotonic() - _ready_at >= _READY_TTL_SECONDS:
            _ready_value = await service.is_ready() and await auth_verifier.ready()
            _ready_at = time.monotonic()
        return _ready_value


@app.get("/health/ready")
async def ready() -> JSONResponse:
    if not await _cached_ready():
        return JSONResponse(status_code=503, content={"status": "not_ready"})
    return JSONResponse(content={"status": "ready"})
```

Also restrict `/health/*` to the platform's probe source at the edge where the platform allows it.

---

### M-02: `CF-Connecting-IP` trusted from any trusted proxy: rate-limit key spoofing

**Severity:** Medium · **Status:** Confirmed in code; exploitable when `APP_TRUSTED_PROXIES` names a proxy that is not Cloudflare · **CWE-348, CWE-290**

**Location**
- `src/neuron_agent/api/main.py:498-507`: the header is honoured whenever the TCP peer is in `APP_TRUSTED_PROXIES`.
- `tests/security/test_rate_limit_keys.py:213-232`: a test asserts this behaviour.
- Introduced by commit `d78b493` (2026-11-09) as the remediation for the earlier audit's finding CF-SEC-02.

**Technical explanation.** `_client_ip` handles `X-Forwarded-For` correctly: it walks the list from the right and stops at the first untrusted hop, so a client cannot prepend an address. The new `CF-Connecting-IP` branch runs before that walk and returns the header's value directly. Only Cloudflare overwrites this header. Render's load balancer, nginx, an AWS ALB and most other proxies forward a client-supplied `CF-Connecting-IP` unchanged. In any deployment where the trusted proxy is one of those, or where the origin is reachable without passing through Cloudflare, the client picks the address the API attributes to it.

The value becomes the `ip:` rate-limit key (`security/auth.py:96-106`, `402-434`). An attacker who sends a fresh value per request gets a fresh, full token bucket each time, so:
- the limit on failed authentication attempts no longer applies to them;
- the in-memory pre-limiter that is meant to shed floods never trips, so every junk request becomes a Postgres write (`persistence/rate_limiter.py:63-81`) and competes for the limiter slots that authenticated requests also need;
- in `APP_AUTH_MODE=none`, the whole request rate limit is bypassed.

The checked-in `render.yaml` sets `APP_TRUSTED_PROXIES` to `[]` (lines 211-212, 270-271), so the reference deployment is not exposed today. The setting is explicitly marked as pending ("until Render's proxy range is confirmed"); the moment that range is filled in, this becomes exploitable.

**Business impact.** Loss of the unauthenticated abuse control and a cheap path to database write pressure, from a single host.

**Evidence**
```python
# src/neuron_agent/api/main.py:498-507
if _trusted_proxy(address):
    cf_connecting_ip = request.headers.get("CF-Connecting-IP")
    if cf_connecting_ip:
        try:
            cf_address = _unmapped(ipaddress.ip_address(cf_connecting_ip.strip()))
            ...
            return str(cf_address)
```

**Safe reproduction (unit level, no network).** Save as a scratch test outside the repository's tracked files and run it with the project's own `pytest`:

```python
from fastapi import Request
from neuron_agent.api import main as api_main

def test_client_can_choose_its_rate_limit_key(monkeypatch):
    # A generic load balancer at 10.2.3.4 appended the real client address to X-Forwarded-For.
    monkeypatch.setattr(api_main.settings, "trusted_proxies", ["10.0.0.0/8"])
    def request(spoofed: bytes) -> Request:
        return Request({"type": "http", "method": "GET", "path": "/",
                        "headers": [(b"cf-connecting-ip", spoofed),      # sent by the client
                                    (b"x-forwarded-for", b"203.0.113.8")],  # set by the proxy
                        "client": ("10.2.3.4", 1234), "server": ("test", 80)})
    assert api_main._client_ip(request(b"198.51.100.1")) == "198.51.100.1"
    assert api_main._client_ip(request(b"198.51.100.2")) == "198.51.100.2"  # a new bucket each time
```

Both assertions pass: the proxy-supplied `203.0.113.8` is ignored in favour of the client's header.

**Remediation.** Make the header an explicit, off-by-default setting, and honour it only when the peer is in a separate list of Cloudflare ranges.

```python
# config/settings.py
client_ip_header: Literal["x-forwarded-for", "cf-connecting-ip"] = "x-forwarded-for"
cloudflare_proxies: list[str] = Field(default_factory=list)   # Cloudflare's published ranges

# api/main.py, in _client_ip
if settings.client_ip_header == "cf-connecting-ip" and _in_networks(address, settings.cloudflare_proxies):
    value = request.headers.get("CF-Connecting-IP")
    ...  # parse as today; on a missing or malformed value fall back to the peer address
```

Refuse `client_ip_header=cf-connecting-ip` with an empty `cloudflare_proxies` at settings load, replace the test at `tests/security/test_rate_limit_keys.py:213` with one that asserts a non-Cloudflare trusted peer ignores the header, and document the setting in `OPERATIONS.md`.

---

### M-03: Document downloads buffered in memory with no concurrency cap

**Severity:** Medium · **Status:** Confirmed · **CWE-770**

**Location**
- `src/neuron_agent/api/main.py:1235-1251`: `GET /v1/knowledge/documents/{doc_id}/file` returns the whole file as one `Response`.
- `src/neuron_agent/knowledge/service.py:483-498` and `src/neuron_agent/knowledge/blobs.py:146-160`: the blob is read fully into memory and then hashed.
- `docs/security/threat-model.md:110-112` records that downloads have no concurrency cap.

**Technical explanation.** Uploads are limited to four at a time per process because each holds a file in memory (`api/main.py:239-256`). Downloads have no equivalent. A stored file can be up to `APP_KNOWLEDGE_PARSE_MAX_BYTES` (default 50 MB, configurable to 200 MB, `config/settings.py:208`). The per-principal rate limit allows a burst of 20 requests (`config/settings.py:137`). Twenty concurrent downloads of one 50 MB document hold at least 1 GB, plus the copy made by `bytes(...)` at `blobs.py:153`. The Render blueprint uses the `starter` plan for the web service.

**Business impact.** Any user with `knowledge:read` and one large document can crash a replica repeatedly, interrupting every tenant's in-flight runs and streams on it. Requires an account, and the Knowledge Engine must be enabled.

**Safe reproduction (local stack only).** Sign in as the full-access test user, upload one text file close to the size cap, then start 20 downloads of it at once (`xargs -P 20 curl ...`) while watching `docker stats` for the `api` container. Memory rises by roughly the file size times the number of in-flight downloads.

**Remediation.** Bound concurrent downloads per process and per owner, in the same way uploads are bounded, and prefer streaming for the S3 backend.

```python
# api/main.py: reuse the upload pattern
class _DownloadSlots:
    def __init__(self, total: int, per_owner: int) -> None:
        self._total, self._per_owner = total, per_owner
        self._in_flight = 0
        self._by_owner: dict[str, int] = {}

    @contextmanager
    def take(self, owner_key: str) -> Iterator[None]:
        if self._in_flight >= self._total or self._by_owner.get(owner_key, 0) >= self._per_owner:
            raise UploadBusyError("too many downloads in progress")   # 429 with Retry-After
        self._in_flight += 1
        self._by_owner[owner_key] = self._by_owner.get(owner_key, 0) + 1
        try:
            yield
        finally:
            self._in_flight -= 1
            self._by_owner[owner_key] -= 1
            if not self._by_owner[owner_key]:
                del self._by_owner[owner_key]
```

Hold the slot until the response body has been sent (a `BackgroundTask` or a streaming response's `finally`), not only while the blob is read.

---

### M-04: Image serves an unauthenticated API on all interfaces in development mode

**Severity:** Medium · **Status:** Potential (requires an operator to set `APP_ENV=development` on a reachable host) · **CWE-1188, CWE-306**

**Location**
- `Dockerfile:27`: the image sets `APP_HOST=0.0.0.0`.
- `src/neuron_agent/config/settings.py:302`: `auth_mode` defaults to `none`.
- `src/neuron_agent/config/settings.py:677-685`: unauthenticated mode on a non-loopback host is refused in every environment except `development`.
- `src/neuron_agent/api/main.py:1428-1434`: the start-up guard only fires when `APP_ENV` was not set at all.
- `src/neuron_agent/security/auth.py:399-400,460-463`: with no auth, every caller receives the full development permission set.
- `src/neuron_agent/api/main.py:761` and `src/neuron_agent/services/agent_service.py:1399,1525-1526`: identity is whatever the caller puts in `X-User-Id` or the body's `user_id`, hashed with unsalted SHA-256.
- `SECURITY.md:214` records this as an accepted residual risk.

**Technical explanation.** `docker run -e APP_ENV=development -p 8000:8000 <image>` starts a fully open API. No warning is logged. Anyone who can reach the port can invoke the agent, read or delete any thread or memory by supplying another user's `X-User-Id`, and, if a provider key is present, spend the operator's model budget. The staging and production profiles refuse this configuration outright, so the exposure is limited to someone trying the image on a cloud host or shared network.

**Business impact.** Data exposure between whoever uses that instance, and provider cost abuse. Likelihood is low; impact on the affected instance is complete.

**Safe reproduction (local).** `docker run --rm -e APP_ENV=development -p 127.0.0.1:8000:8000 neuron:local`, then `curl -s -X POST http://127.0.0.1:8000/v1/agent/invoke -H 'content-type: application/json' -d '{"message":"hi","user_id":"anyone"}'` returns an answer with no token. Inside the container the listener is bound to `0.0.0.0`.

**Remediation.** Require an explicit opt-in for the one combination that is dangerous, and say so loudly at start-up.

```python
# config/settings.py
allow_unauthenticated_public_bind: bool = False   # APP_ALLOW_UNAUTHENTICATED_PUBLIC_BIND

# in validate_authentication
if self.auth_mode == "none":
    if self.env in {"staging", "production"}:
        raise ValueError("APP_AUTH_MODE=none is only allowed in development and test")
    if not _is_loopback_bind(self.host) and not (
        self.env == "development" and self.allow_unauthenticated_public_bind
    ):
        raise ValueError(
            "APP_AUTH_MODE=none must not bind a non-loopback APP_HOST; set "
            "APP_AUTH_MODE=jwt, or APP_ALLOW_UNAUTHENTICATED_PUBLIC_BIND=true for a "
            "development container published on loopback only"
        )
```

`docker-compose.yml` already uses JWT, so it is unaffected.

---

### M-05: Schema-owner database credential in the internet-facing web service

**Severity:** Medium · **Status:** Confirmed in configuration · **CWE-250, CWE-522**

**Location**
- `render.yaml:48,55-56` (staging) and `render.yaml:115,122-123` (production): the web service carries `APP_POSTGRES_MIGRATION_DSN` because its pre-deploy command shares its environment.
- `src/neuron_agent/config/settings.py:265`: the value is loaded into the API process's settings.
- `SECURITY.md` ("Reference deployment") and ADR 0008 open question 20 accept this for now.

**Technical explanation.** The project separates a least-privilege runtime role from a migrator role that owns the schema, verifies at start-up that the runtime role is not privileged, and refuses to let production use the same user for both (`config/settings.py:649-672`). Placing the migrator's DSN in the web service's environment undoes that separation in practice: any bug that discloses the process environment or allows code execution yields owner-level access, including `neuron_meta` and the ability to disable row-level security.

**Business impact.** Raises the blast radius of any future web-process compromise from "one role's DML" to "the whole database".

**Verification.** Read-only: confirm the two `envVars` entries above, and after a deploy confirm in the Render dashboard that the running web service's environment contains the variable.

**Remediation.** Run `python -m neuron_agent.persistence.cli setup` from a separate one-off job (a Render job, or a step in `deploy.yml` that reaches the database through a private runner) whose environment alone holds the migration DSN, and remove the variable from both web services. Until then, give the migrator role a short-lived password that is rotated after each deploy.

---

### L-01: Data-rights routes exceed their scope names

**Severity:** Low · **Status:** Confirmed · **CWE-285**

- `src/neuron_agent/api/main.py:949-969` with `services/agent_service.py:1092-1101`: `GET /v1/me/export` needs only `threads:read` but also returns the caller's memories and knowledge-base and document metadata, which otherwise need `memories:read` and `knowledge:read`.
- `src/neuron_agent/api/main.py:1268-1289` with `services/agent_service.py:1251-1258`: `DELETE /v1/me/threads` and `DELETE /v1/me/knowledge` need only `threads:delete` but erase memories and all knowledge, which otherwise need `memories:write` and `knowledge:write`.

The erase behaviour is a recorded owner decision (`docs/product/RAG_IMPLEMENTATION_TRACKER.md:292`); the export behaviour is not discussed. All data involved is the caller's own, so this is not a cross-tenant issue. It matters when a token is deliberately narrowed, for example the `neuron-reader` role in `docker-compose.yml:37`, which holds only `threads:read` and can still read memories through the export.

**Reproduce (local stack):** sign in as the read-only test user and call `GET /v1/me/export`; the `memories` field is populated although `GET /v1/me/memories` returns `403`.

**Remediation:** include each section only when the token holds its own scope, or add dedicated `data:export` and `data:erase` scopes and document them.

```python
memories = (
    [_memory_item(m) for m in await self._memory.list(owner_key)]
    if self._memory is not None and offset == 0
    and (principal is None or "memories:read" in principal.scopes)
    else []
)
```

### L-02: One user can hold every upload slot

**Severity:** Low · **Status:** Confirmed · **CWE-770**

`src/neuron_agent/api/main.py:239-256,1120-1129`. Upload slots are per process (default 4, `config/settings.py:225`) with no per-user share, and a slot is held for up to 300 seconds while the body arrives. One account can open four slow uploads and keep renewing them, so every other tenant's upload gets `429`.

**Reproduce (local stack):** start four uploads throttled with `curl --limit-rate 1k`, then attempt a fifth as a different user and observe `429`.

**Remediation:** cap slots per owner key (one or two) in `_UploadSlots.take`, as in the M-03 example.

### L-03: Unauthenticated telemetry Collector shared by staging and production

**Severity:** Low · **Status:** Confirmed in configuration · **CWE-306, CWE-319**

- `deploy/observability/otel-collector.yaml:22-28,122-123`: OTLP receivers and the Prometheus exporter have no authentication.
- `render.yaml:245-248,309-312`: the receiver binds `0.0.0.0`.
- `render.yaml:219-220,281-282`: the API exports over plain `http`.
- `render.yaml:25-32`: staging and production share one private network unless placed in separate workspaces.

A staging workload could write spans and metrics into the production Collector (poisoning alerts, or exhausting its memory) and scrape production metrics. The project documents this and instructs operators to use separate workspaces. Telemetry content is allow-listed and carries no prompts.

**Remediation:** enforce the separate-workspace rule before syncing production, and add a bearer-token authenticator extension to the receivers with the token passed through `OTEL_EXPORTER_OTLP_HEADERS`.

### L-04: Outdated and tag-pinned third-party images in deployment files

**Severity:** Low · **Status:** Confirmed · **CWE-1104, CWE-494**

| Location | Issue |
|---|---|
| `render.yaml:91,157` | `otel/opentelemetry-collector-contrib:0.120.0`: a mutable tag, not a digest, on a release from early 2025 |
| `docker-compose.reference.yml:100` | `quay.io/keycloak/keycloak:26.0.7`: tag only |
| `keycloak-theme/Dockerfile:21` | Keycloak 26.0.7, digest-pinned but far behind the current 26.8 line |
| `render.yaml:40,68,109,135` | The API image URL has no tag or digest in the file; it relies on an operator replacing it before the first sync |

Keycloak's maintained branches have received many security fixes since 26.0.x, and that branch no longer appears in the project's fix lists ([Keycloak Advisory Watch, October 2026](https://buttondown.com/keycloak-advisory-watch/archive/keycloak-security-fixes-2674-to-2680-the-catch-up/)). The Keycloak images are used only by the local and reference stacks. Dependabot's `docker` ecosystem covers the three Dockerfiles but not `render.yaml` or the Compose files (`.github/dependabot.yml:25-27`).

**Remediation:** pin the Collector by digest and update it together with `scripts/validate_observability.py`; move Keycloak to a maintained release; add a test in `tests/unit/test_render_blueprint.py` that fails while the API image URL has no `@sha256:` digest.

### L-05: Static-site CSP hardcodes loopback origins

**Severity:** Low · **Status:** Confirmed · **CWE-1021, CWE-16**

`web/public/_headers:10` and `web/nginx.conf:11`. The policy's `connect-src` and `frame-src` list `http://127.0.0.1:8000` and `http://localhost:8180`, while the app reads its real API and identity-provider origins from build-time variables (`web/src/lib/api.ts:17`, `web/src/lib/auth/config.ts:32`). `_headers` was added for hosted static deployment, where this policy both blocks the real API and identity provider, and permits the page to reach services on the visitor's own machine. The likely operational response to a broken sign-in is to loosen or delete the policy. `style-src 'unsafe-inline'` is also present.

**Remediation:** generate `_headers` at build time from `VITE_API_URL` and `VITE_OIDC_ISSUER`, keep the loopback values only in `nginx.conf` for the local stack, and add a unit test that the built policy contains the configured origins and no loopback host.

### L-06: JWT type check off by default; no token revocation

**Severity:** Low · **Status:** Confirmed · **CWE-613**

- `src/neuron_agent/config/settings.py:315` with `security/auth.py:203-204`: `APP_AUTH_REQUIRE_TYP` defaults to `false`, so any JWT from the issuer that carries the API's audience is accepted, not only `at+jwt` access tokens.
- No `jti` deny-list exists; a stolen token is valid until it expires (documented, ADR 0006).
- `deploy/keycloak/neuron-realm.json:68-80,118-130`: the development realm hard-codes `nbf` to `0` to satisfy the API's required-claim check, which makes that check meaningless in that realm.

**Remediation:** set `APP_AUTH_REQUIRE_TYP=true` in the staging and production groups of `render.yaml` (the realm already issues RFC 9068 headers), keep access-token lifetimes at five minutes or less, and plan an issuer-side revocation or short deny-list for incident response.

### L-07: Throwaway credentials and an HMAC key in tracked development files

**Severity:** Low · **Status:** Confirmed · **CWE-798**

All values are development-only, labelled as such, and every published port binds to loopback. Values are redacted here.

| Location | Content |
|---|---|
| `docker-compose.yml:38`, `docker-compose.reference.yml:45` | `APP_IDENTITY_HASH_KEY=[REDACTED]` |
| `docker-compose.yml:42,63,83,114,149`; `docker-compose.reference.yml:54,76,104,132,169` | Database and Keycloak admin passwords `[REDACTED]` |
| `deploy/reference/init-roles.sql:4,6,9` | Three role passwords `[REDACTED]` |
| `deploy/keycloak/neuron-realm.json:142-146,160-164` | Two test users with plain-text passwords `[REDACTED]` |
| `deploy/keycloak/neuron-realm.json:84-92` | Public client with the password grant enabled |
| `scripts/dast_scan.sh:12`, `loadtest/identity.py:18`, `scripts/dr_drill.py:57-58` | The same passwords repeated |

The risk is reuse: someone copying these files as a starting point for a shared environment. The realm import in particular would carry known user passwords and a password-grant client.

**Remediation:** generate the values on first `make up` into an ignored `.dev/` file, or keep them and add a start-up refusal when a known development value is seen with `APP_ENV` in staging or production.

### L-08: AI review workflow runs pull-request code with a provider secret

**Severity:** Low · **Status:** Confirmed · **CWE-829**

`.github/workflows/ai-review.yml:46-70`. On `pull_request`, the job checks out the pull request's merge commit and runs `python scripts/ai_review.py` from it with `NVIDIA_API_KEY` and a token that has `pull-requests: write`. Fork pull requests receive no secrets, but anyone who can push a branch to the repository can change that script and read the key. The diff under review is also untrusted input to the model, whose output is posted as a review. Separately, the `new-dependency-approved` and `large-pr-approved` labels (`.github/workflows/ai-code-verification.yml:54,91`) bypass two gates and can be applied by anyone with triage rights.

**Remediation:** check out the base revision for the script and pass the head only as data (`git fetch` the head SHA and diff against it), or move the job to an environment with required reviewers; restrict who may apply the override labels.

### L-09: Developer tooling fetches an unpinned package at run time

**Severity:** Low · **Status:** Confirmed · **CWE-829**

`.mcp.json:4-8`, `.agents/plugins/chrome-devtools/mcp.json:6-10`, `.agents/plugins/chrome-devtools/mcp_config.json:4-8`: `npx -y chrome-devtools-mcp@latest`. Any contributor whose coding agent loads these files executes whatever version is newest at that moment, with the contributor's privileges. `.claude/settings.json:32-43` also enables several third-party plugins, and its hooks run shell commands on file edits. None of this reaches the production image, but it bypasses the dependency-age and review gates the project applies everywhere else.

**Remediation:** pin an exact version (and ideally an integrity hash) in all three files and review plugin additions like dependency additions.

### L-10: Document text may cross the internal network in clear text

**Severity:** Low · **Status:** Potential · **CWE-319**

- `src/neuron_agent/config/settings.py:236`: `APP_KNOWLEDGE_PARSER_URL` accepts `http://` in every environment, and docling-serve has no authentication (`docker-compose.reference.yml:183-184`).
- `src/neuron_agent/config/settings.py:517-525`: the embedding endpoint must be `https` in staging and production only when an API key is set.

Uploaded files and extracted text therefore travel unencrypted to those services when they are self-hosted. The reference stack isolates the parser on an internal network with no route out, which is the right compensating control.

**Remediation:** document network isolation as a hard requirement for both services, and require `https` in production unless the host is loopback or an explicit `APP_KNOWLEDGE_INTERNAL_PLAINTEXT_ALLOWED=true` is set.

### Informational

| ID | Observation | Location |
|---|---|---|
| I-01 | `/health/ready` returns the environment name to anonymous callers. Removing it is part of the M-01 fix. | `src/neuron_agent/api/main.py:629` |
| I-02 | When MCP servers are configured, every user's tool call uses one operator bearer token, so the remote server cannot tell users apart, and tool descriptions reach the model as written by the server. Pinning, schema validation, public-only egress and approval after tainted input are in place. MCP is off unless `APP_MCP_SERVERS` is set. | `src/neuron_agent/tools/mcp/client.py:129,227,273-274` |
| I-03 | A deployment through `langgraph.json` (Agent Server) gets authentication and owner isolation but not the API's rate limits, concurrency caps, token budget or input policy. | `src/neuron_agent/graphs/main_graph.py:438`, `SECURITY.md` |
| I-04 | Row-level security exists on `knowledge.chunks` and `knowledge.embeddings` only, keyed on a session setting the application role sets itself. It guards against application bugs, not against a compromised application role. Other tables rely on the owner-key filter in each query. | `src/neuron_agent/persistence/migrations.py:507-518` |
| I-05 | The system-prompt disclosure guard matches runs of eight verbatim words; paraphrase, translation and encoding pass. The system prompt should be treated as non-secret. | `src/neuron_agent/security/output_policy.py:22,52-55` |

---

## 5. Reviewed and not vulnerable (false positives)

These are patterns a scanner or a reviewer would flag. Each was checked and is not a vulnerability.

| Pattern | Location | Why it is safe |
|---|---|---|
| SQL built with f-strings or `.format` | `persistence/migrations.py:526,863-975`, `knowledge/reconcile.py:59-98`, `knowledge/retrieval.py:99-109,344-348` | Only module constants and validated role names are interpolated, through `psycopg.sql.Identifier` and `sql.Literal`. All request values are bound parameters. |
| ZAP "SQL Injection" on `/v1/me/threads?limit` | `deploy/reference/zap-rules.tsv:3` | `limit` is an integer bounded by `Query(ge=1, le=100)` (`api/main.py:936`). The project's own false-positive ruling is correct. |
| Expression evaluation in the calculator tool | `tools/calculator.py:47-84` | An AST allow-list of numeric constants and six operators, with length, exponent and magnitude bounds. No names, calls or attributes. |
| `subprocess` use | `evaluation.py:867`, `scripts/ai_review.py:452` | Fixed argument vectors (`git rev-parse HEAD`, `git diff`), no shell. |
| `dangerouslySetInnerHTML` (20 uses) | `keycloak-theme/src/login/**` | Every use passes through Keycloakify's `kcSanitize`. |
| ID token signature not verified in the browser | `web/src/lib/auth/idToken.ts:35-63` | Permitted by OIDC Core 3.1.3.7 for a token received directly from the token endpoint over TLS. Issuer, audience, expiry and nonce are checked, and the API verifies the access token's signature on every request. |
| `X-User-Id` header and body `user_id` | `api/main.py:761`, `schemas/agent.py:35` | Ignored whenever `APP_AUTH_MODE=jwt`; the owner comes only from the verified token (`services/agent_service.py:1391-1398`). See M-04 for the unauthenticated mode. |
| Credential-shaped strings | `tests/unit/test_deploy_tools.py:20`, `tests/resilience/test_failure_catalog.py:34`, `docs/releases/v0.4.0-gate/gate_checks.py:472-481` | Test placeholders. No real credential exists in the tree or in the 544 commits of `main`. |
| `assert` statements marked `# nosec` | `persistence/*`, `knowledge/*` | Type-narrowing invariants, not security checks; the image does not run with `-O`. |
| Client file name in uploads | `api/multipart.py:79-80` | Used only as a default title. Storage keys are 128 random bits (`knowledge/blobs.py:115`). |
| Open redirect after sign-in | `web/src/lib/auth/config.ts:61-71` | The return path is reduced to a same-origin path; protocol-relative, backslash and control-character forms are refused. |

---

## 6. Dependency and third-party package assessment

**Result: no known vulnerable package version in any lockfile on 2026-11-11.**

| Ecosystem | Lockfile | Packages | Known advisories | Method |
|---|---|---|---|---|
| Python (runtime and dev) | `uv.lock` | 174 from PyPI, 1 local | **0**, none yanked | PyPI JSON API (OSV-backed) queried for each locked name and version |
| npm, web app | `web/package-lock.json` | 455 (168 production) | **0** | `npm audit` on a copy of the lockfile |
| npm, Keycloak theme | `keycloak-theme/package-lock.json` | 285 (137 production) | **0** | `npm audit` on a copy of the lockfile |

**Strengths**
- Every Python package resolves from `pypi.org` with recorded hashes; both npm lockfiles carry an integrity hash for every entry.
- npm installs run with scripts disabled (`web/.npmrc:3`, `--ignore-scripts` in both Dockerfiles).
- Security-relevant libraries are current: `cryptography` 50.0.1, `pyjwt` 2.15.1, `starlette` 1.6.0, `python-multipart` 0.0.32, `psycopg` 3.3.6, `jsonschema` 4.26.0.
- `httpx2` and `httpcore2` are unfamiliar names worth a second look; their PyPI metadata points to the `pydantic/httpx2` repository, so they are not typosquats.
- CI runs `pip-audit`, `bandit`, `npm audit`, GitHub dependency review, CodeQL, gitleaks, a new-dependency age check, Trivy on the published image, an SBOM and a build-provenance attestation that the deploy workflow verifies before it deploys.
- Dependabot runs weekly for Python, npm, Actions and Dockerfiles with a seven-day cooldown.

**Gaps**
- Container images referenced outside Dockerfiles are not tracked or current (L-04).
- `pyproject.toml:18-46` uses lower bounds only (one exact pin). The lockfile makes builds reproducible, but anyone installing the package without the lockfile gets unreviewed versions. Acceptable for a service; note it if the package is ever published.
- `keycloak-theme/package.json` has one caret range (`tsafe`) among exact pins, and a `postinstall` script that only runs when installs are not script-disabled.
- Developer tooling pulls an unpinned package (L-09).
- The advisory lookup reflects one day. Keep the weekly automation, since this stack (LangChain, LangGraph, MCP) changes quickly.

---

## 7. Risk score and remediation roadmap

### Overall risk score: 3 / 10 (Low)

| Factor | Assessment |
|---|---|
| Confidentiality | No path to another tenant's data was found. Strong. |
| Integrity | No unauthorized write path was found. Strong. |
| Availability | Three ways to degrade a replica, one of them unauthenticated (M-01). Weakest area. |
| Exploitability | The highest-impact issues need either an account, a specific proxy setup or an operator mistake. |
| Maturity caveat | Nothing has run in a hosted environment, and this audit was static. Treat the score as provisional until M-01 and M-02 are fixed and a deployed instance has been tested. |

### Prioritized roadmap

**Priority 1: before the first hosted deployment**

| Item | Finding | Effort |
|---|---|---|
| Cache the readiness result; drop the environment name from the response | M-01, I-01 | Small |
| Put `CF-Connecting-IP` behind an explicit setting and Cloudflare ranges; replace the test | M-02 | Small |
| Move `setup` to its own job and remove the migration DSN from both web services | M-05 | Medium |
| Put staging and production in separate workspaces; add Collector authentication | L-03 | Small |
| Set `APP_AUTH_REQUIRE_TYP=true` for staging and production | L-06 | Trivial |
| Pin the API and Collector images by digest in `render.yaml`, with a test | L-04 | Small |

**Priority 2: next release**

| Item | Finding | Effort |
|---|---|---|
| Add per-process and per-owner download slots; per-owner upload slots | M-03, L-02 | Small |
| Require an explicit opt-in for unauthenticated non-loopback binds | M-04 | Small |
| Generate the static-site CSP from build-time origins | L-05 | Small |
| Align export and erase with per-resource scopes, or add `data:*` scopes | L-01 | Small |
| Run the AI review script from the base revision | L-08 | Small |

**Priority 3: hygiene**

| Item | Finding | Effort |
|---|---|---|
| Update Keycloak in the local and reference stacks | L-04 | Small |
| Pin developer tooling versions | L-09 | Trivial |
| Generate development credentials instead of tracking them | L-07 | Medium |
| Require TLS or explicit opt-out for the parser and embedding endpoints in production | L-10 | Small |
| Design per-user token exchange for MCP before enabling third-party servers | I-02 | Large |
| Commission an external penetration test of the first deployed environment | all | External |

### Suggested verification after fixes

- M-01: a test that 100 concurrent probes cause at most one `is_ready()` call per TTL window.
- M-02: a test that a trusted non-Cloudflare peer with a `CF-Connecting-IP` header is keyed by `X-Forwarded-For`.
- M-03 and L-02: a test that the (N+1)th concurrent download or upload from one owner receives `429` while a second owner still succeeds.
- M-04: a settings test that `APP_ENV=development`, `APP_AUTH_MODE=none`, `APP_HOST=0.0.0.0` raises without the opt-in.
- M-05 and L-04: extend `tests/unit/test_render_blueprint.py` to fail when a web service lists `APP_POSTGRES_MIGRATION_DSN` or when an image reference lacks a digest.
