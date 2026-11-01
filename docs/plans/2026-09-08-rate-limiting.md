# Application-Level Rate Limiting Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a configurable, token-bucket rate limiter enforced at the `/v1/agent/invoke` API boundary, keyed by client IP, returning `429` with `Retry-After` when exceeded.

**Architecture:** A `RateLimiter` protocol and one `InMemoryTokenBucketRateLimiter` implementation live in a new `security/rate_limiter.py`. A new FastAPI HTTP middleware in `api/main.py` (same shape as the existing `limit_request_body_size` middleware) calls it before the handler runs and short-circuits with a `JSONResponse` on denial. Settings gain four new bounded fields controlling the limiter.

**Tech Stack:** FastAPI/Starlette middleware, Pydantic `Settings`, stdlib `time.monotonic` (injectable for tests), pytest.

**Spec:** `docs/decisions/0004-rate-limiting.md`

## Global Constraints

- Request identity is client IP (`request.client.host`) only — no `user_id` involvement (spec §Options Considered, Request identity).
- Algorithm is token bucket: capacity = burst, refill rate = `requests_per_window / window_seconds` (spec §Decision).
- Enforcement applies only to `POST /v1/agent/invoke`; health endpoints stay exempt (spec §Options Considered, Scope and storage).
- Storage is in-memory, single-process, behind a `Protocol` boundary — no distributed backend now (spec §Decision, §Consequences).
- Denial returns `JSONResponse(429, {"detail": "rate_limited"})` with an integer `Retry-After` header, via direct response (no new `AppError` subclass) — matches how `limit_request_body_size` already handles its 4xx (spec §Decision).
- New `Settings` fields: `rate_limit_enabled: bool = True`, `rate_limit_requests_per_window: int = Field(default=60, ge=1, le=10_000)`, `rate_limit_window_seconds: int = Field(default=60, ge=1, le=3600)`, `rate_limit_burst: int = Field(default=20, ge=1, le=10_000)` — `APP_`-prefixed, matching existing bounded-`Field` style in `config/settings.py`.
- Defaults (60 req/window, 60s window, burst 20) must not break the existing test suite, which issues ~13 sequential requests to `/v1/agent/invoke` from one shared `TestClient` (same IP key) across `tests/unit/test_api.py`.
- `mypy --strict` must pass on all new/modified code (full type hints, no untyped defs). `ruff` rule set is `B, E, F, I, S, UP, W` (line length 100). Tests must not require network/model credentials — env is `test` with no `OPENAI_API_KEY`, so `/v1/agent/invoke` already resolves to a `FakeListChatModel` end-to-end (`models/factory.py:149-150`).

---

### Task 1: Rate-limit configuration

**Files:**
- Modify: `src/neuron_agent/config/settings.py:41-42` (insert new fields between `max_request_body_bytes` and `enable_langsmith`)
- Modify: `tests/unit/test_settings.py`
- Modify: `.env.example` (insert a new `RATE LIMITING` section after the `AGENT EXECUTION` section, i.e. after line 29)

**Interfaces:**
- Produces: `Settings.rate_limit_enabled: bool`, `Settings.rate_limit_requests_per_window: int`, `Settings.rate_limit_window_seconds: int`, `Settings.rate_limit_burst: int` — consumed by Task 3.

- [ ] **Step 1: Write the failing tests**

Add these assertions inside the existing `test_settings_defaults_are_openai_production_safe` function in `tests/unit/test_settings.py`:

```python
    assert settings.rate_limit_enabled is True
    assert settings.rate_limit_requests_per_window == 60
    assert settings.rate_limit_window_seconds == 60
    assert settings.rate_limit_burst == 20
```

Add a new test at the end of the file:

```python
def test_settings_rejects_rate_limit_burst_out_of_bounds() -> None:
    with pytest.raises(ValidationError):
        Settings(env="test", openai_api_key=None, rate_limit_burst=0)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_settings.py -v`
Expected: FAIL — `AttributeError: 'Settings' object has no attribute 'rate_limit_enabled'` (and the new test fails because `rate_limit_burst` is not a recognized field, so no `ValidationError` bound is enforced yet — pydantic's `extra="ignore"` means it silently drops the kwarg instead of raising, so this assertion fails with `Failed: DID NOT RAISE`).

- [ ] **Step 3: Add the settings fields**

In `src/neuron_agent/config/settings.py`, insert immediately after the `max_request_body_bytes` field (currently line 41, before `enable_langsmith`):

```python
    rate_limit_enabled: bool = True
    rate_limit_requests_per_window: int = Field(default=60, ge=1, le=10_000)
    rate_limit_window_seconds: int = Field(default=60, ge=1, le=3600)
    rate_limit_burst: int = Field(default=20, ge=1, le=10_000)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_settings.py -v`
Expected: PASS

- [ ] **Step 5: Update `.env.example`**

In `.env.example`, insert a new section after the `AGENT EXECUTION` block (after `APP_MAX_REQUEST_BODY_BYTES=65536`):

```
# =============================================================================
# RATE LIMITING
# =============================================================================

APP_RATE_LIMIT_ENABLED=true
APP_RATE_LIMIT_REQUESTS_PER_WINDOW=60
APP_RATE_LIMIT_WINDOW_SECONDS=60
APP_RATE_LIMIT_BURST=20
```

- [ ] **Step 6: Commit**

```bash
git add src/neuron_agent/config/settings.py tests/unit/test_settings.py .env.example
git commit -m "feat: add rate-limit configuration"
```

---

### Task 2: Token-bucket rate limiter

**Files:**
- Create: `src/neuron_agent/security/rate_limiter.py`
- Test: `tests/unit/test_rate_limiter.py`

**Interfaces:**
- Produces: `RateLimitDecision(allowed: bool, retry_after_seconds: float)`; `RateLimiter` protocol with `check(self, key: str) -> RateLimitDecision`; `InMemoryTokenBucketRateLimiter(*, capacity: int, requests_per_window: int, window_seconds: int, clock: Callable[[], float] = time.monotonic)` implementing `RateLimiter` — consumed by Task 3.

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_rate_limiter.py`:

```python
from __future__ import annotations

import pytest

from neuron_agent.security.rate_limiter import InMemoryTokenBucketRateLimiter


class _FakeClock:
    def __init__(self, start: float = 0.0) -> None:
        self._now = start

    def __call__(self) -> float:
        return self._now

    def advance(self, seconds: float) -> None:
        self._now += seconds


def test_allows_requests_up_to_capacity() -> None:
    clock = _FakeClock()
    limiter = InMemoryTokenBucketRateLimiter(
        capacity=3, requests_per_window=3, window_seconds=60, clock=clock
    )
    for _ in range(3):
        assert limiter.check("client-a").allowed is True


def test_denies_once_capacity_is_exhausted() -> None:
    clock = _FakeClock()
    limiter = InMemoryTokenBucketRateLimiter(
        capacity=1, requests_per_window=1, window_seconds=60, clock=clock
    )
    assert limiter.check("client-a").allowed is True
    decision = limiter.check("client-a")
    assert decision.allowed is False
    assert decision.retry_after_seconds == pytest.approx(60.0)


def test_refills_over_time() -> None:
    clock = _FakeClock()
    limiter = InMemoryTokenBucketRateLimiter(
        capacity=1, requests_per_window=1, window_seconds=60, clock=clock
    )
    assert limiter.check("client-a").allowed is True
    assert limiter.check("client-a").allowed is False
    clock.advance(60.0)
    assert limiter.check("client-a").allowed is True


def test_tracks_keys_independently() -> None:
    clock = _FakeClock()
    limiter = InMemoryTokenBucketRateLimiter(
        capacity=1, requests_per_window=1, window_seconds=60, clock=clock
    )
    assert limiter.check("client-a").allowed is True
    assert limiter.check("client-b").allowed is True


@pytest.mark.parametrize(
    "kwargs",
    [
        {"capacity": 0, "requests_per_window": 1, "window_seconds": 60},
        {"capacity": 1, "requests_per_window": 0, "window_seconds": 60},
        {"capacity": 1, "requests_per_window": 1, "window_seconds": 0},
    ],
)
def test_rejects_invalid_configuration(kwargs: dict[str, int]) -> None:
    with pytest.raises(ValueError):
        InMemoryTokenBucketRateLimiter(**kwargs)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_rate_limiter.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'neuron_agent.security.rate_limiter'`

- [ ] **Step 3: Implement the rate limiter**

Create `src/neuron_agent/security/rate_limiter.py`:

```python
"""In-process rate limiting for the API boundary (ADR 0004)."""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class RateLimitDecision:
    """Outcome of a single rate-limit check."""

    allowed: bool
    retry_after_seconds: float


class RateLimiter(Protocol):
    """Decides whether a request identified by `key` may proceed."""

    def check(self, key: str) -> RateLimitDecision: ...


@dataclass
class _Bucket:
    tokens: float
    last_refill: float


class InMemoryTokenBucketRateLimiter:
    """Single-process token-bucket limiter keyed by an opaque string.

    Not safe across multiple worker processes or instances. A distributed
    backend must implement the `RateLimiter` protocol to replace this for
    multi-instance deployments (see ADR 0004).
    """

    def __init__(
        self,
        *,
        capacity: int,
        requests_per_window: int,
        window_seconds: int,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if capacity < 1:
            raise ValueError("capacity must be >= 1")
        if requests_per_window < 1:
            raise ValueError("requests_per_window must be >= 1")
        if window_seconds < 1:
            raise ValueError("window_seconds must be >= 1")
        self._capacity = float(capacity)
        self._refill_rate = requests_per_window / window_seconds
        self._clock = clock
        self._buckets: dict[str, _Bucket] = {}

    def check(self, key: str) -> RateLimitDecision:
        now = self._clock()
        bucket = self._buckets.get(key)
        if bucket is None:
            bucket = _Bucket(tokens=self._capacity, last_refill=now)
            self._buckets[key] = bucket
        else:
            elapsed = max(0.0, now - bucket.last_refill)
            bucket.tokens = min(self._capacity, bucket.tokens + elapsed * self._refill_rate)
            bucket.last_refill = now

        if bucket.tokens >= 1.0:
            bucket.tokens -= 1.0
            return RateLimitDecision(allowed=True, retry_after_seconds=0.0)

        missing = 1.0 - bucket.tokens
        return RateLimitDecision(allowed=False, retry_after_seconds=missing / self._refill_rate)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_rate_limiter.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/neuron_agent/security/rate_limiter.py tests/unit/test_rate_limiter.py
git commit -m "feat: add in-memory token-bucket rate limiter"
```

---

### Task 3: Enforce rate limiting at the API boundary

**Files:**
- Modify: `src/neuron_agent/api/main.py`
- Modify: `tests/unit/test_api.py`

**Interfaces:**
- Consumes: `Settings.rate_limit_enabled`, `Settings.rate_limit_requests_per_window`, `Settings.rate_limit_window_seconds`, `Settings.rate_limit_burst` (Task 1); `InMemoryTokenBucketRateLimiter(*, capacity, requests_per_window, window_seconds, clock=...)`, `RateLimitDecision(allowed, retry_after_seconds)` (Task 2).
- Produces: module-level `neuron_agent.api.main.rate_limiter` (an `InMemoryTokenBucketRateLimiter`), replaceable via `monkeypatch.setattr(api_main, "rate_limiter", ...)` in tests, matching the existing `api_main.settings` / `api_main.service` singleton pattern.

- [ ] **Step 1: Write the failing test**

Add to `tests/unit/test_api.py`. First, add these imports alongside the existing ones:

```python
from neuron_agent.schemas.agent import AgentResponse
from neuron_agent.security.rate_limiter import InMemoryTokenBucketRateLimiter
```

Then add (mocking `AgentService.invoke` the same way `test_agent_invoke_maps_app_errors_to_http` already does, so this test isolates rate-limiting behavior from agent/model correctness rather than depending on the fake chat model producing valid structured output end-to-end):

```python
def test_agent_invoke_returns_429_when_rate_limited(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fast_invoke(self: object, request: object) -> AgentResponse:
        return AgentResponse(
            request_id="request-1", thread_id="thread-1", answer="ok", used_tools=[], confidence=1.0
        )

    monkeypatch.setattr(api_main.AgentService, "invoke", fast_invoke)
    monkeypatch.setattr(
        api_main,
        "rate_limiter",
        InMemoryTokenBucketRateLimiter(capacity=1, requests_per_window=1, window_seconds=60),
    )
    client = TestClient(app)
    first = client.post("/v1/agent/invoke", json={"message": "hi"})
    assert first.status_code == 200

    second = client.post("/v1/agent/invoke", json={"message": "hi"})
    assert second.status_code == 429
    assert second.json() == {"detail": "rate_limited"}
    assert 1 <= int(second.headers["Retry-After"]) <= 60


def test_health_endpoints_are_not_rate_limited(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        api_main,
        "rate_limiter",
        InMemoryTokenBucketRateLimiter(capacity=1, requests_per_window=1, window_seconds=60),
    )
    client = TestClient(app)
    for _ in range(3):
        response = client.get("/health/live")
        assert response.status_code == 200
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_api.py -v`
Expected: FAIL — `AttributeError: <module 'neuron_agent.api.main'> does not have the attribute 'rate_limiter'` on both new tests (raised by `monkeypatch.setattr`, since the module has no `rate_limiter` attribute yet).

- [ ] **Step 3: Add the middleware**

In `src/neuron_agent/api/main.py`, add `import math` near the top with the other stdlib import (`import os`, alphabetically before it):

```python
import math
import os
```

Add the new import with the other `neuron_agent` imports, between `schemas.agent` and `services.agent_service` (alphabetical order matches the existing block):

```python
from neuron_agent.schemas.agent import AgentRequest, AgentResponse
from neuron_agent.security.rate_limiter import InMemoryTokenBucketRateLimiter
from neuron_agent.services.agent_service import AgentService
```

Immediately after `service = AgentService(settings)`, add:

```python
rate_limiter = InMemoryTokenBucketRateLimiter(
    capacity=settings.rate_limit_burst,
    requests_per_window=settings.rate_limit_requests_per_window,
    window_seconds=settings.rate_limit_window_seconds,
)
```

Add a new middleware function immediately after `limit_request_body_size` (before the `handle_request_validation_error` exception handler):

```python
@app.middleware("http")
async def enforce_rate_limit(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    if settings.rate_limit_enabled and request.url.path == "/v1/agent/invoke":
        client_host = request.client.host if request.client else "unknown"
        decision = rate_limiter.check(client_host)
        if not decision.allowed:
            retry_after = max(1, math.ceil(decision.retry_after_seconds))
            logger.warning(
                "agent_request_rate_limited", client=client_host, retry_after=retry_after
            )
            return JSONResponse(
                status_code=429,
                content={"detail": "rate_limited"},
                headers={"Retry-After": str(retry_after)},
            )
    return await call_next(request)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_api.py -v`
Expected: PASS (all tests in the file, including the pre-existing ones — confirms the default burst of 20 doesn't throttle the existing ~13 sequential requests in this file)

- [ ] **Step 5: Commit**

```bash
git add src/neuron_agent/api/main.py tests/unit/test_api.py
git commit -m "feat: enforce token-bucket rate limiting on /v1/agent/invoke"
```

---

### Task 4: Documentation and full verification

**Files:**
- Modify: `SECURITY.md`

- [ ] **Step 1: Update `SECURITY.md`**

Add this bullet to the `## Current Controls` list, after the "Hashed user IDs before entering graph state." line:

```
- Token-bucket rate limiting at `/v1/agent/invoke`, keyed by client IP, returning `429` with `Retry-After` when exceeded (ADR 0004).
```

- [ ] **Step 2: Run all quality gates**

Run: `make format lint typecheck test security`
Expected: all pass with no errors. If `make format` reformats anything, review the diff before proceeding.

- [ ] **Step 3: Commit**

```bash
git add SECURITY.md
git commit -m "docs: document rate-limiting control in SECURITY.md"
```

- [ ] **Step 4: Verify acceptance criteria from issue #6**

Confirm each item from the issue is satisfied:
- [ ] Rate limiting exists at the API boundary — Task 3.
- [ ] Limits are configurable — Task 1.
- [ ] Exceeded requests return 429 — Task 3.
- [ ] Retry-After behavior is defined — Task 3.
- [ ] Tests cover normal and exceeded limits — Task 2 (unit) and Task 3 (API-level).
- [ ] Design documents the future distributed implementation — `docs/decisions/0004-rate-limiting.md`.
