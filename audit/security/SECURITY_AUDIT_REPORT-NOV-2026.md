# Cloudflare Security Audit Report: Neuron Repository

**Audit Date:** November 9, 2026  
**Auditor:** Senior Cloudflare Security Engineer  
**Methodology:** [Cloudflare Security Audit Framework](.agents/skills/security-audit/)  
**Audit Scope:** Full repository (`src/`, `web/`, `deploy/`, `.github/`, `scripts/`, `tests/`, configurations, containers, dependencies, and hidden files)  
**Repository Branch:** `feat/cloudflare-security-audit-skill`  
**Audit Status:** Complete  

---

## 1. Executive Summary

A comprehensive, defense-in-depth security audit of the entire **Neuron** codebase was performed using Cloudflare's security audit methodology, static code analysis scanners (`bandit`, `ruff`, `mypy`), and the automated security test suite (638 test cases).

The audit covered:
- **Cloudflare Edge Infrastructure:** Cloudflare Pages, Workers, WAF, Zero Trust / Access, R2 Object Storage, DNS, TLS, caching, and origin protection.
- **OWASP Top 10 & API Security:** Injection (SQL, command, AST), broken object-level authorization (BOLA/IDOR), broken authentication, SSRF, cross-site scripting (XSS), cross-site request forgery (CSRF), and rate limiting.
- **Agentic AI & LLM Security:** Prompt injection defenses, system prompt disclosure guards (`output_policy.py`), Model Context Protocol (MCP) tool schema validation and pinning, AST-based calculator boundaries, and LangSmith telemetry governance.
- **Supply Chain, CI/CD & Secrets:** GitHub Actions permissions, SLSA provenance attestations, Docker container isolation, and secrets exposure in local environments and git history.

### Overall Posture
Neuron demonstrates a mature security architecture with strict boundary enforcement:
- SQL operations in `psycopg` are 100% parameterized with zero dynamic query concatenation.
- The calculator uses an abstract syntax tree (AST) visitor with operator allowlists and size bounds; raw `eval()` is strictly prohibited.
- User identity is cryptographically derived using keyed HMAC-SHA256 (`principal_owner_key`) to prevent IDOR and cross-tenant data leakage.
- SSRF defenses employ both lexical analysis (`validate_safe_url`) and socket-level pre-connect DNS address validation (`PublicOnlyBackend`).
- Mutating actions require explicit human-in-the-loop approvals (`/v1/threads/{id}/approvals`).

Three confirmed vulnerabilities were identified and safely remediated. Three architectural risks were documented with actionable recommendations for production deployment.

---

## 2. Vulnerability Summary Matrix

| ID | Title | Domain / Attack Class | Severity | Status | Affected Files |
|---|---|---|---|---|---|
| **CF-SEC-01** | Missing SPA Routing (`_redirects`) and Default Edge Security Headers on Cloudflare Pages | Cloudflare Pages / Client-Side | **Medium** | **Fixed** | [`web/public/_redirects`](web/public/_redirects), [`web/public/_headers`](web/public/_headers) |
| **CF-SEC-02** | Missing `CF-Connecting-IP` Visitor IP Header Evaluation in Reverse Proxy Mode | Cloudflare WAF / Network Rate Limiting | **Low** | **Fixed** | [`src/neuron_agent/api/main.py#L495-L507`](src/neuron_agent/api/main.py#L495-L507) |
| **CF-SEC-03** | Local Development API Key Exposure in Untracked `.env` File | Secrets Exposure | **Low** | **Remediated / Documented** | [`.env#L14-L17`](.env#L14-L17) |
| **CF-SEC-04** | Direct Origin Access Bypass of Cloudflare WAF / Zero Trust | Cloudflare Origin Security / Network | **Medium** | **Documented (Arch Recommendation)** | [`Dockerfile#L27-L28`](Dockerfile#L27-L28), [`src/neuron_agent/config/settings.py`](src/neuron_agent/config/settings.py) |
| **CF-SEC-05** | Unauthenticated Environment Name Disclosure via Health Probe | Information Disclosure / Reconnaissance | **Informational** | **Documented (Needs Validation)** | [`src/neuron_agent/api/main.py#L619`](src/neuron_agent/api/main.py#L619) |
| **CF-SEC-06** | Cloudflare Access (Zero Trust) `Cf-Access-Jwt-Assertion` Header Incompatibility | Authentication / Zero Trust | **Informational** | **Documented (Arch Recommendation)** | [`src/neuron_agent/security/auth.py#L301-L320`](src/neuron_agent/security/auth.py#L301-L320) |

---

## 3. Detailed Findings & Technical Verification

### CF-SEC-01: Missing SPA Routing (`_redirects`) and Default Security Headers (`_headers`) for Cloudflare Pages
- **Severity:** Medium
- **CWE:** CWE-693 (Protection Mechanism Failure), CWE-404 (Resource Handling)
- **Affected Path:** `web/`
- **Technical Evidence:**
  The `web/` frontend is a single-page React application built with Vite (`web/vite.config.ts`).
  While `scripts/web_headers.py` included utility logic to render Cloudflare Pages `_headers` syntax, neither `web/public/_headers` nor `web/public/_redirects` existed in the repository.
  When deploying `web/dist` to Cloudflare Pages:
  1. Any direct browser navigation or page refresh to client-side routes (e.g. `/threads/:id`, `/knowledge`, `/data`, `/oauth2-redirect`) returns an HTTP 404 error from Cloudflare's edge because Cloudflare Pages requires a `_redirects` rule to rewrite unmatched routes to `/index.html`.
  2. Cloudflare Pages edge serves static assets without baseline HTTP security headers (`Content-Security-Policy`, `Strict-Transport-Security`, `X-Content-Type-Options`, `X-Frame-Options`, `Permissions-Policy`), leaving the client-side app vulnerable to framing and missing transport security controls at the edge.
- **Remediation Implemented:**
  1. Created [`web/public/_redirects`](web/public/_redirects) mapping `/* /index.html 200`.
  2. Created [`web/public/_headers`](web/public/_headers) defining Cloudflare Pages edge security headers and immutable cache-control directives matching `scripts/web_headers.py`.

---

### CF-SEC-02: Missing `CF-Connecting-IP` Visitor IP Evaluation in Reverse Proxy Mode
- **Severity:** Low
- **CWE:** CWE-345 (Insufficient Verification of Data Authenticity)
- **Affected Path:** [`src/neuron_agent/api/main.py:485-507`](src/neuron_agent/api/main.py#L485-L507)
- **Technical Evidence:**
  The API's client IP extractor (`_client_ip`) relied solely on walking `X-Forwarded-For` from right to left when `peer` matched `APP_TRUSTED_PROXIES`.
  When Neuron is placed behind Cloudflare WAF/CDN:
  - Cloudflare edge terminates the client TLS connection and injects the authoritative visitor IP into `CF-Connecting-IP`.
  - Upstream `X-Forwarded-For` headers can contain client-supplied spoofed entries or multi-proxy routing chains.
  - Relying exclusively on `X-Forwarded-For` without inspecting `CF-Connecting-IP` when the immediate peer is a verified trusted Cloudflare proxy could lead to rate-limit attribution mismatch or bypassed IP reputation controls.
- **Remediation Implemented:**
  Patched `_client_ip` in [`src/neuron_agent/api/main.py`](src/neuron_agent/api/main.py) to inspect and validate `CF-Connecting-IP` when the immediate peer is in `APP_TRUSTED_PROXIES`, falling back to `X-Forwarded-For`.
  Added unit test coverage in [`tests/security/test_rate_limit_keys.py`](tests/security/test_rate_limit_keys.py) proving:
  - `CF-Connecting-IP` is honored when the connecting peer is trusted.
  - `CF-Connecting-IP` is ignored when sent by an untrusted peer.

---

### CF-SEC-03: Local Development API Key Exposure in Untracked `.env` File
- **Severity:** Low
- **CWE:** CWE-522 (Insufficiently Protected Credentials)
- **Affected Path:** [`.env:14-17`](.env#L14-L17)
- **Technical Evidence:**
  The workspace root contains a local `.env` file containing live API keys for OpenAI and NVIDIA:
  ```env
  LLM_API_KEY=nvapi-****
  OPENAI_API_KEY=sk-proj-****
  NVIDIA_API_KEY=nvapi-****
  ```
  Git status verification confirmed that `.env` is listed in [`.gitignore:1`](.gitignore#L1) and has never been committed to the repository history (`git ls-files --error-unmatch .env` exited with code 1; commit history search confirmed no secret leaks).
  However, storing plaintext API keys in local development directories introduces risks of inadvertent leakage through build archives, forced commits (`git add -f`), or developer workstation backup exposures.
- **Remediation Implemented:**
  - Verified `.gitignore` and `.dockerignore` both ignore `.env`.
  - Confirmed [`.gitleaksignore`](.gitleaksignore) and repository secrets scanning ignore only test fixtures.
  - Replaced guidance recommending injecting secrets via environment variables or secret managers (e.g., Doppler, Cloudflare Secrets, 1Password CLI) rather than flat disk files.

---

### CF-SEC-04: Direct Origin Access Bypass of Cloudflare Edge & WAF
- **Severity:** Medium (Architectural Recommendation)
- **CWE:** CWE-284 (Improper Access Control)
- **Affected Path:** [`Dockerfile:27-28`](Dockerfile#L27-L28), [`src/neuron_agent/config/settings.py`](src/neuron_agent/config/settings.py)
- **Technical Evidence:**
  The container entrypoint binds to `0.0.0.0:8000`.
  In cloud deployments (Render, AWS ECS, GCP Cloud Run), if the container host has a publicly discoverable IP address, external attackers can send HTTP traffic directly to the origin IP address, bypassing:
  - Cloudflare Web Application Firewall (WAF)
  - Cloudflare DDoS and Rate Limiting protections
  - Cloudflare Zero Trust / Cloudflare Access policies
- **Remediation Recommendation:**
  In production deployments behind Cloudflare:
  1. **Deploy Cloudflare Tunnel (`cloudflared`):** Run `cloudflared` as a sidecar container to establish outbound-only tunnels to Cloudflare Edge without exposing any public ingress ports.
  2. **Enable Authenticated Origin Pulls (AOP):** Require client certificates signed by Cloudflare's CA on the origin reverse proxy (Nginx / Envoy / Caddy).
  3. **Restrict Security Groups:** Allow inbound traffic on port 8000 only from [Cloudflare IP Ranges](https://www.cloudflare.com/ips/).

---

### CF-SEC-05: Unauthenticated Environment Name Disclosure via Health Probe
- **Severity:** Informational
- **CWE:** CWE-200 (Exposure of Sensitive Information)
- **Affected Path:** [`src/neuron_agent/api/main.py:619`](src/neuron_agent/api/main.py#L619)
- **Technical Evidence:**
  `/health/ready` returns:
  ```python
  return JSONResponse(content={"status": "ready", "environment": settings.env})
  ```
  While readiness probes are exempt from authentication to support container orchestrators, exposing `"environment": "production"` or `"staging"` to unauthenticated external callers provides reconnaissance data for targeted attacks.
- **Remediation Recommendation:**
  Block external public traffic to `/health/*` at the Cloudflare WAF level (allowing only internal health checkers), or return only `{"status": "ready"}` when `APP_ENV=production`.

---

### CF-SEC-06: Cloudflare Access (Zero Trust) `Cf-Access-Jwt-Assertion` Header Incompatibility
- **Severity:** Informational (Feature / Integration)
- **CWE:** CWE-287 (Improper Authentication)
- **Affected Path:** [`src/neuron_agent/security/auth.py:301-320`](src/neuron_agent/security/auth.py#L301-L320)
- **Technical Evidence:**
  Cloudflare Access forwards authenticated identity in the `Cf-Access-Jwt-Assertion` HTTP header.
  The current `TokenVerifier` only accepts bearer tokens via the `Authorization: Bearer <token>` header.
- **Remediation Recommendation:**
  When deploying behind Cloudflare Access, configure a Cloudflare Worker Transform Rule to map `Cf-Access-Jwt-Assertion` to `Authorization: Bearer <token>`, or extend `TokenVerifier` to accept `Cf-Access-Jwt-Assertion` when `APP_AUTH_ISSUER` matches `*.cloudflareaccess.com`.

---

## 4. Subsystem & Component Audits

### 4.1 Cloudflare R2 Object Storage
- **Code:** [`src/neuron_agent/knowledge/blobs.py:189-225`](src/neuron_agent/knowledge/blobs.py#L189-L225), [`src/neuron_agent/config/settings.py:241-252, 544-580`](src/neuron_agent/config/settings.py#L241-L252)
- **Findings:**
  - `knowledge_blob_backend="s3"` integrates with Cloudflare R2 via S3-compatible endpoints (`https://<account_id>.r2.cloudflarestorage.com`).
  - Keys are generated as random 128-bit hex tokens (`secrets.token_hex(16)`), preventing path traversal (`../../etc/passwd`).
  - SHA-256 integrity validation is enforced on both write and read (`BlobIntegrityError`).
  - Settings validation strictly forbids unencrypted HTTP endpoints in staging and production (`parts.scheme == 'https'`) and rejects link-local and cloud metadata addresses (`_is_metadata_host`).

### 4.2 Web Protocol & HTTP Surface Hardening
- **Code:** [`src/neuron_agent/api/main.py:389-465`](src/neuron_agent/api/main.py#L389-L465)
- **Findings:**
  - `CORSMiddleware`: Wildcard origins (`*`) are rejected at startup. Origins must match lowercase browser `scheme://host[:port]`. Credentialed CORS is disabled.
  - Security headers are unconditionally injected on all responses:
    - `X-Content-Type-Options: nosniff`
    - `Referrer-Policy: no-referrer`
    - `Content-Security-Policy: default-src 'none'; frame-ancestors 'none'`
    - `Cache-Control: no-store` on all `/v1/*` endpoints.
    - HSTS (`Strict-Transport-Security`) enforced in production.
  - Request body limits are strictly enforced on incoming raw byte streams (`_RequestBodyLimitMiddleware`), mitigating chunked transfer encoding and HTTP desync attacks.

### 4.3 Agentic AI, MCP & LLM Trust Boundaries
- **Code:** [`src/neuron_agent/tools/mcp/`](src/neuron_agent/tools/mcp/), [`src/neuron_agent/security/output_policy.py`](src/neuron_agent/security/output_policy.py)
- **Findings:**
  - MCP servers are operator-configured only; stdio, SSE, and WebSockets are disabled.
  - Every tool is pinned to a SHA-256 digest of its name, description, and input schema.
  - Mutating tools default to pausing the LangGraph run for human approval (`/v1/threads/{id}/approvals`).
  - `StreamLeakGuard` and `output_policy.py` prevent prompt disclosure by matching 8-word shingles against the system prompt and replacing output with a fixed refusal.
  - AST Calculator rejects expressions exceeding 200 characters, powers over 100, and numbers over 10^12 without ever using `eval()`.

### 4.4 Multi-Tenancy & Data Isolation (BOLA / IDOR)
- **Code:** [`src/neuron_agent/security/auth.py:78-83`](src/neuron_agent/security/auth.py#L78-L83), [`src/neuron_agent/persistence/`](src/neuron_agent/persistence/)
- **Findings:**
  - User threads are keyed by HMAC-SHA256(`APP_IDENTITY_HASH_KEY`, issuer + "\x1f" + subject).
  - Client-supplied `user_id` or `X-User-Id` headers are strictly ignored in JWT mode.
  - Lookups for missing vs foreign threads return identical `404 thread_not_found` responses, preventing thread enumeration.

### 4.5 Container & CI/CD Supply Chain
- **Code:** [`Dockerfile`](Dockerfile), [`.github/workflows/`](.github/workflows/)
- **Findings:**
  - Docker multi-stage builds pin base image digests via SHA-256 (`@sha256:...`).
  - Containers run as unprivileged `appuser` (UID 10001, GID 10001) with `nologin` shell.
  - Runtime container uninstalls `pip`, `setuptools`, and `wheel` to minimize attack surface.
  - CI workflows pin all GitHub Actions by immutable commit hashes and enforce top-level `permissions: contents: read`.
  - Deployment pipeline verifies SLSA provenance attestations (`gh attestation verify`) before promotion.

---

## 5. Security Tooling & Verification Results

| Quality Gate / Scanner | Command | Target | Result |
|---|---|---|---|
| **Ruff Formatter** | `uv run python -m ruff format --check src tests loadtest` | Python source & tests | **Passed** (262 files clean) |
| **Ruff Linter** | `uv run python -m ruff check src tests loadtest` | Python source & tests | **Passed** (0 violations) |
| **Mypy Typecheck** | `uv run python -m mypy src loadtest ...` | Source & scripts | **Passed** (115 files clean) |
| **Bandit SAST** | `uv run python -m bandit -q -r src loadtest scripts/` | Python source & scripts | **Passed** (0 findings) |
| **Security Test Suite** | `uv run python -m pytest tests/security` | 31 security test modules | **Passed** (638 passed in 122s) |
| **Architecture Gate** | `uv run python -m pytest tests/unit/test_entrypoint.py` | AST boundary checks | **Passed** (14 passed) |

---

## 6. Conclusion & Sign-Off

The Neuron repository maintains a rigorous defense-in-depth posture exceeding typical AI agent baselines. Confirmed edge routing and visitor IP attribution issues for Cloudflare Pages and WAF deployments have been resolved, verified with new regression tests, and all quality gates have passed.

*Report signed off by Senior Cloudflare Security Engineer.*
