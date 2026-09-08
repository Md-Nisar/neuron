# ADR 0004: Application-Level Rate Limiting

## Status

Accepted.

## Problem

Neuron has no protection against excessive request volume at the API boundary. A single caller (or a misbehaving client) can exhaust upstream model-provider quotas or degrade the service for others. Issue #6 asks for a minimal rate-limiting abstraction — not distributed infrastructure — that defines request identity, window, burst behavior, response status, `Retry-After` behavior, and configuration, while leaving room for a distributed backend later.

## Requirements

- Rate limiting enforced at the API boundary, before the agent graph runs.
- Configurable limits (window, steady rate, burst) via `Settings`.
- Exceeded requests return `429` with a `Retry-After` header.
- Tests cover both normal and exceeded-limit behavior.
- The abstraction must not assume a single process is the permanent deployment target.

## Options Considered

**Request identity**
1. Hashed `user_id`, falling back to client IP — more precise, but `user_id` only exists inside the JSON body, so enforcement would have to move past HTTP-level middleware into the endpoint/service layer, after body parsing.
2. Client IP only (`request.client.host`) — selected. Available before the body is read, consistent with how `limit_request_body_size` already inspects the request pre-handler, and sufficient for the stated goal (protect against volume, not identify individual authenticated users).

**Algorithm**
1. Fixed window counter — simplest state (count + window start per key), but has edge-of-window burst artifacts and no explicit burst control.
2. Token bucket — selected. Directly models the issue's "burst behavior" requirement: a bucket starts full at `capacity` tokens and refills continuously at `requests_per_window / window_seconds` tokens/sec: a caller can burst up to `capacity` immediately, then is limited to the steady rate.

**Scope and storage**
1. All routes, in-memory store — simplest middleware placement, but risks throttling health-check probes used by orchestration/load balancers.
2. Only `/v1/agent/invoke`, in-memory single-process store — selected. Health endpoints stay exempt. In-memory storage matches ADR 0001/0002's stance against premature distributed infrastructure; the limiter is defined behind a `Protocol` so a distributed backend (e.g. Redis-backed token bucket) can implement the same interface later without changing callers.

## Decision

Add `security/rate_limiter.py` defining:

- `RateLimitDecision(allowed: bool, retry_after_seconds: float)`.
- `RateLimiter` (`Protocol`): `check(key: str) -> RateLimitDecision`.
- `InMemoryTokenBucketRateLimiter`: the only implementation for now. One bucket per key, capacity and refill rate derived from configuration, guarded by a single process-local dict (no cross-process coordination).

Configuration (new `Settings` fields, `APP_`-prefixed, matching the existing bounded-`Field` style):

- `rate_limit_enabled: bool = True`
- `rate_limit_requests_per_window: int = Field(default=60, ge=1)`
- `rate_limit_window_seconds: int = Field(default=60, ge=1)`
- `rate_limit_burst: int = Field(default=20, ge=1)` (bucket capacity)

Enforcement is a new `app.middleware("http")` in `api/main.py`, scoped to `request.url.path == "/v1/agent/invoke"`, following the same shape as the existing `limit_request_body_size` middleware. On denial it returns `JSONResponse(429, {"detail": "rate_limited"})` with an integer `Retry-After` header and a `logger.warning("agent_request_rate_limited", ...)` call — handled as a direct response rather than through `AppError`, consistent with how body-size limiting is already handled. The existing `RateLimitError` in `errors/base.py` (upstream-provider 429s) is untouched and unrelated to this enforcement path.

Default configuration values are chosen so the existing test suite (which issues a modest number of sequential requests against a shared `TestClient`/app instance) is not incidentally throttled; tests targeting rate-limit behavior construct or substitute a limiter with a small capacity explicitly.

## Consequences

Callers are protected from a single high-volume source at the cost of only IP-granularity limiting (shared IPs — NAT, proxies — share a bucket). The limiter is process-local: it resets on restart and does not coordinate across multiple worker processes or instances, which is an explicit, documented limitation rather than a hidden one. Moving to a multi-instance deployment requires implementing `RateLimiter` against a shared backend (e.g. Redis) and swapping the instance constructed in `api/main.py` — no other call site changes.
