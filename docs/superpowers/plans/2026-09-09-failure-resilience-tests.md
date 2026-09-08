# Failure and Resilience Test Suite Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the specific, verified gaps in the failure/resilience test coverage for GitHub issue #7 and add one new `tests/resilience/` suite that proves, at the HTTP boundary, that every one of the issue's 13 failure categories fails safely (correct status code, correct stable error code, no leaked internal detail).

**Architecture:** No production code changes. Every failure category in issue #7 is already classified by the existing `AppError` taxonomy (`src/neuron_agent/errors/base.py`) and centralized HTTP mapping (`src/neuron_agent/api/main.py:93-127`); most categories already have deterministic unit/graph-level tests. This plan (a) adds the handful of unit-level tests proving specific mappings that exist in code but were never exercised (`openai.InternalServerError` → `ProviderError`, `langgraph.errors.GraphRecursionError` → `AgentExecutionError`, the structured-output graceful-fallback branch, a `staging`-env config-key check), and (b) adds a new `tests/resilience/test_failure_catalog.py` that drives every category through the real FastAPI app (mocking only at the `AgentService.invoke` boundary, matching the existing pattern in `tests/unit/test_api.py`), with explicit assertions that no injected secret string ever appears in the HTTP response body.

**Tech Stack:** pytest, `fastapi.testclient.TestClient`, `pytest.MonkeyPatch`, `openai` SDK exception classes, `langgraph.errors.GraphRecursionError`, `pydantic.ValidationError`. No new dependencies.

**Spec:** GitHub issue #7, "Expand Failure and Resilience Test Suite" (https://github.com/Md-Nisar/neuron/issues/7).

## Global Constraints

- No live OpenAI credentials — every test either mocks at `AgentService.invoke`, constructs `openai.*Error`/`GraphRecursionError` instances directly, or hits validation logic that never reaches the model (per `tests/conftest.py`, `APP_ENV=test` is already set for the whole suite).
- No production code changes — every mapping this plan tests already exists and is already correct (verified interactively against the current `main` branch); this plan only adds missing test coverage.
- Follow existing repo conventions exactly: inline `async def raise_error(...)` closures per test (no shared conftest helpers — `tests/unit/test_api.py` does not use one), `httpx.Request`/`httpx.Response` to construct real `openai.*Error` instances (no HTTP-mocking library), `TestClient(app)` instantiated per test function.
- `make test` currently runs `pytest tests/unit tests/graph tests/security tests/evals` (Makefile:24-25) by explicit directory list — the new `tests/resilience/` directory must be added to that list and given its own `test-resilience` target, matching `test-graph`/`test-security`.
- Run `make format lint typecheck test security` before the final task's acceptance-criteria check.

---

### Task 1: Provider 5xx classification test

**Files:**
- Modify: `tests/unit/test_model_factory.py`

**Interfaces:**
- Consumes: `neuron_agent.models.factory.classify_agent_error` (existing, unchanged), `neuron_agent.errors.base.ProviderError` (existing, unchanged).
- Produces: nothing new for later tasks.

- [ ] **Step 1: Write the test**

Add to `tests/unit/test_model_factory.py`, directly after `test_classify_agent_error_maps_generic_provider_error` (currently ending at line 100):

```python
def test_classify_agent_error_maps_internal_server_error() -> None:
    response = httpx.Response(status_code=500, request=_REQUEST)
    error = openai.InternalServerError("internal error", response=response, body=None)
    assert isinstance(classify_agent_error(error), ProviderError)
```

- [ ] **Step 2: Run the test**

Run: `uv run pytest tests/unit/test_model_factory.py::test_classify_agent_error_maps_internal_server_error -v`
Expected: PASS (no production code change needed — `openai.InternalServerError` already falls through `classify_agent_error`'s generic `openai.OpenAIError` branch to `ProviderError`; this test locks that mapping in place).

- [ ] **Step 3: Commit**

```bash
git add tests/unit/test_model_factory.py
git commit -m "test: cover provider 5xx classification (openai.InternalServerError -> ProviderError)"
```

---

### Task 2: Agent iteration limit tests

**Files:**
- Modify: `tests/unit/test_model_factory.py`
- Modify: `tests/graph/test_main_graph.py`

**Interfaces:**
- Consumes: `langgraph.errors.GraphRecursionError` (third-party, already a transitive dependency — `models/factory.py` already imports `GraphBubbleUp` from the same module), `classify_agent_error`, `call_agent`, `FailingAgent` (existing test helper in `test_main_graph.py`).
- Produces: nothing new for later tasks.

- [ ] **Step 1: Write the classification test**

Add to `tests/unit/test_model_factory.py`, add this import alongside the existing `from neuron_agent.errors.base import (...)` block (insert `AgentExecutionError` is already imported at line 12 — no import change needed there) and add near the top of the file, after the existing imports (after line 25, before `_REQUEST = ...`):

```python
from langgraph.errors import GraphRecursionError
```

Then add the test after `test_classify_agent_error_falls_back_to_agent_execution_error`:

```python
def test_classify_agent_error_maps_recursion_limit_exceeded() -> None:
    error = GraphRecursionError("Recursion limit of 5 reached")
    assert isinstance(classify_agent_error(error), AgentExecutionError)
```

- [ ] **Step 2: Run the classification test**

Run: `uv run pytest tests/unit/test_model_factory.py::test_classify_agent_error_maps_recursion_limit_exceeded -v`
Expected: PASS (no production code change needed — `GraphRecursionError` isn't an `AppError`, `openai.*Error`, or `LangChainStructuredOutputError`, so it already falls through to `classify_agent_error`'s final `return AgentExecutionError(...)` line, matching the documented behavior in `ARCHITECTURE.md:94`).

- [ ] **Step 3: Write the graph-level test**

Add to `tests/graph/test_main_graph.py`, add this import alongside the existing imports (after line 7, before the `from neuron_agent.errors.base import (...)` block):

```python
from langgraph.errors import GraphRecursionError
```

Then add the test after `test_call_agent_wraps_generic_provider_error`:

```python
async def test_call_agent_wraps_recursion_limit_error() -> None:
    error = GraphRecursionError("Recursion limit of 5 reached")
    with pytest.raises(AgentExecutionError):
        await call_agent(_state(), agent=FailingAgent(error))
```

- [ ] **Step 4: Run the graph-level test**

Run: `uv run pytest tests/graph/test_main_graph.py::test_call_agent_wraps_recursion_limit_error -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add tests/unit/test_model_factory.py tests/graph/test_main_graph.py
git commit -m "test: cover agent iteration limit (GraphRecursionError -> AgentExecutionError)"
```

---

### Task 3: Structured-output graceful-fallback test

**Files:**
- Modify: `tests/graph/test_main_graph.py`

**Interfaces:**
- Consumes: `call_agent` (existing, unchanged) — specifically its fallback branch at `src/neuron_agent/graphs/main_graph.py:50-55`, which returns a synthetic `AgentAnswer(answer=<raw text>, used_tools=[], confidence=0.5)` when `result["structured_response"]` is missing or not an `AgentAnswer` instance, instead of raising.
- Produces: nothing new for later tasks.

- [ ] **Step 1: Write the test**

Add to `tests/graph/test_main_graph.py`, add a new fake agent class after `FakeAgent` (after line 36) and a test after `test_call_agent_uses_structured_response`:

```python
class RawTextAgent:
    async def ainvoke(
        self, _: dict[str, object], *, config: dict[str, object]
    ) -> dict[str, object]:
        return {"messages": [AIMessage(content="raw text answer")]}
```

```python
async def test_call_agent_falls_back_to_raw_text_when_structured_response_missing() -> None:
    result = await call_agent(_state(), agent=RawTextAgent())
    assert result["answer"].answer == "raw text answer"
    assert result["answer"].used_tools == []
    assert result["answer"].confidence == 0.5
```

- [ ] **Step 2: Run the test**

Run: `uv run pytest tests/graph/test_main_graph.py::test_call_agent_falls_back_to_raw_text_when_structured_response_missing -v`
Expected: PASS (verified interactively — this is existing, intentional graceful-degradation behavior, not a bug; this test documents and locks it in so a future change to that branch is caught as a deliberate decision, not an accident).

- [ ] **Step 3: Commit**

```bash
git add tests/graph/test_main_graph.py
git commit -m "test: cover graceful fallback when agent omits structured_response"
```

---

### Task 4: Missing API configuration — staging environment variant

**Files:**
- Modify: `tests/unit/test_settings.py`

**Interfaces:**
- Consumes: `Settings` (existing, unchanged) — `require_provider_key_outside_tests` validator already covers both `staging` and `production`; only `production` has a test today.
- Produces: nothing new for later tasks.

- [ ] **Step 1: Write the test**

Add to `tests/unit/test_settings.py`, after `test_settings_require_openai_key_in_production`:

```python
def test_settings_require_openai_key_in_staging() -> None:
    with pytest.raises(ValidationError):
        Settings(env="staging", default_model="openai:gpt-5.4-mini", openai_api_key=None)
```

- [ ] **Step 2: Run the test**

Run: `uv run pytest tests/unit/test_settings.py::test_settings_require_openai_key_in_staging -v`
Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add tests/unit/test_settings.py
git commit -m "test: cover missing API configuration for staging environment"
```

---

### Task 5: Scaffold the `tests/resilience/` suite directory

**Files:**
- Create: `tests/resilience/test_failure_catalog.py` (empty placeholder module with a single trivial passing test, replaced with real content in Task 6-7)
- Modify: `Makefile`

**Interfaces:**
- Consumes: nothing new.
- Produces: `tests/resilience/` as a pytest-discoverable directory (`testpaths = ["tests"]` in `pyproject.toml` already covers it — no `pyproject.toml` change needed since no new marker is used, matching how `tests/graph` and `tests/security` are already plain directories with no custom marker).

- [ ] **Step 1: Create the directory with a smoke test**

Create `tests/resilience/test_failure_catalog.py`:

```python
"""Deterministic failure-and-resilience regression suite (issue #7).

Each test forces a failure at the same boundary the production code already
classifies it at (AgentService.invoke, the rate limiter, or Settings
construction) and asserts the HTTP contract plus the absence of leaked
internal detail. Deeper unit-level coverage for each error's classification
lives alongside the module that owns it: `tests/unit/test_model_factory.py`,
`tests/graph/test_main_graph.py`, `tests/unit/test_tool_timeout_middleware.py`,
`tests/unit/test_tool_failure_isolation_middleware.py`,
`tests/unit/test_rate_limiter.py`, `tests/unit/test_settings.py`.
"""

from __future__ import annotations


def test_suite_is_collected() -> None:
    assert True
```

- [ ] **Step 2: Wire the new directory into the Makefile**

In `Makefile`, change the `test:` target (lines 24-25) from:

```makefile
test:
	uv run python -m pytest tests/unit tests/graph tests/security tests/evals
```

to:

```makefile
test:
	uv run python -m pytest tests/unit tests/graph tests/security tests/resilience tests/evals
```

Add a new `test-resilience` target after `test-security` (after line 34), matching the existing `test-graph`/`test-security` style:

```makefile
test-resilience:
	uv run python -m pytest tests/resilience
```

Add `test-resilience` to the `.PHONY` line (line 1), inserting it after `test-security`:

```makefile
.PHONY: install dev run api format lint typecheck test test-unit test-graph test-security test-resilience test-integration eval security build
```

- [ ] **Step 3: Run the smoke test and the full make test target**

Run: `uv run pytest tests/resilience -v`
Expected: PASS (1 test).

Run: `make test`
Expected: PASS (all existing suites plus the new smoke test).

- [ ] **Step 4: Commit**

```bash
git add tests/resilience/test_failure_catalog.py Makefile
git commit -m "test: scaffold tests/resilience failure-and-resilience suite"
```

---

### Task 6: Failure catalog — provider, tool, and agent-execution categories with leakage assertions

**Files:**
- Modify: `tests/resilience/test_failure_catalog.py`

**Interfaces:**
- Consumes: `neuron_agent.api.main` (module, for `AgentService`/`app` monkeypatching, existing, unchanged), `neuron_agent.errors.base.{ProviderTimeoutError, RateLimitError, ProviderError, ConfigurationError, StructuredOutputError, ToolExecutionError, AgentExecutionError}` (existing, unchanged).
- Produces: `_SECRET_MARKER` module-level constant, reused by Task 7's additions to this same file.

- [ ] **Step 1: Replace the smoke test with the real imports and the AppError+leakage table**

Replace the full content of `tests/resilience/test_failure_catalog.py` with:

```python
"""Deterministic failure-and-resilience regression suite (issue #7).

Each test forces a failure at the same boundary the production code already
classifies it at (AgentService.invoke, the rate limiter, or Settings
construction) and asserts the HTTP contract plus the absence of leaked
internal detail. Deeper unit-level coverage for each error's classification
lives alongside the module that owns it: `tests/unit/test_model_factory.py`,
`tests/graph/test_main_graph.py`, `tests/unit/test_tool_timeout_middleware.py`,
`tests/unit/test_tool_failure_isolation_middleware.py`,
`tests/unit/test_rate_limiter.py`, `tests/unit/test_settings.py`.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from neuron_agent.api import main as api_main
from neuron_agent.api.main import app
from neuron_agent.errors.base import (
    AgentExecutionError,
    ConfigurationError,
    ProviderError,
    ProviderTimeoutError,
    RateLimitError,
    StructuredOutputError,
    ToolExecutionError,
)

_SECRET_MARKER = "sk-test-secret-should-never-leak"


@pytest.mark.parametrize(
    ("error", "expected_status", "expected_detail"),
    [
        (
            ProviderTimeoutError(f"model provider timed out: {_SECRET_MARKER}"),
            504,
            "provider_timeout_error",
        ),
        (
            RateLimitError(f"model provider rate limit exceeded: {_SECRET_MARKER}"),
            429,
            "rate_limit_error",
        ),
        (
            ProviderError(f"model provider request failed: {_SECRET_MARKER}"),
            502,
            "internal_server_error",
        ),
        (
            ConfigurationError(f"model provider authentication failed: {_SECRET_MARKER}"),
            500,
            "internal_server_error",
        ),
        (
            StructuredOutputError(f"agent produced invalid structured output: {_SECRET_MARKER}"),
            502,
            "internal_server_error",
        ),
        (
            ToolExecutionError(f"tool 'calculator' exceeded 20s timeout: {_SECRET_MARKER}"),
            502,
            "internal_server_error",
        ),
        (
            ToolExecutionError(f"tool 'calculator' failed unexpectedly: {_SECRET_MARKER}"),
            502,
            "internal_server_error",
        ),
        (
            AgentExecutionError(f"agent execution failed: {_SECRET_MARKER}"),
            500,
            "internal_server_error",
        ),
    ],
    ids=[
        "provider-timeout",
        "provider-rate-limit-429",
        "provider-5xx",
        "provider-authentication-failure",
        "malformed-structured-output",
        "tool-timeout",
        "tool-failure",
        "agent-iteration-limit-exceeded",
    ],
)
def test_agent_invoke_fails_safely_without_leaking_detail(
    monkeypatch: pytest.MonkeyPatch,
    error: Exception,
    expected_status: int,
    expected_detail: str,
) -> None:
    async def raise_error(self: object, request: object) -> None:
        raise error

    monkeypatch.setattr(api_main.AgentService, "invoke", raise_error)
    client = TestClient(app)
    response = client.post("/v1/agent/invoke", json={"message": "hi"})
    assert response.status_code == expected_status
    assert response.json() == {"detail": expected_detail}
    assert _SECRET_MARKER not in response.text
```

- [ ] **Step 2: Run the tests to verify they fail for the right reason first**

Run: `uv run pytest tests/resilience/test_failure_catalog.py -v`

This should already PASS on first run since it exercises existing, correct production behavior — there is no red step here because the plan is testing already-implemented mappings (verified interactively in the exploration phase). If any case fails, stop and re-check the corresponding row in `ARCHITECTURE.md`'s failure-handling table against `src/neuron_agent/errors/base.py` and `src/neuron_agent/api/main.py:110-119` before changing the test.

- [ ] **Step 3: Run and confirm pass**

Run: `uv run pytest tests/resilience/test_failure_catalog.py -v`
Expected: PASS (8 parametrized cases).

- [ ] **Step 4: Commit**

```bash
git add tests/resilience/test_failure_catalog.py
git commit -m "test: catalog provider/tool/agent failure categories with no-leak assertions"
```

---

### Task 7: Failure catalog — config, request-shape, and client-rate-limit categories

**Files:**
- Modify: `tests/resilience/test_failure_catalog.py`

**Interfaces:**
- Consumes: `neuron_agent.config.settings.Settings`, `neuron_agent.schemas.agent.AgentResponse`, `neuron_agent.security.rate_limiter.InMemoryTokenBucketRateLimiter` (all existing, unchanged). Continues from Task 6's imports and `_SECRET_MARKER`.
- Produces: a complete, self-contained mapping from every one of issue #7's 13 categories to a test in this file.

- [ ] **Step 1: Add imports**

At the top of `tests/resilience/test_failure_catalog.py`, extend the existing import block (added in Task 6) to also import:

```python
from pydantic import ValidationError

from neuron_agent.config.settings import Settings
from neuron_agent.schemas.agent import AgentResponse
from neuron_agent.security.rate_limiter import InMemoryTokenBucketRateLimiter
```

- [ ] **Step 2: Add the unexpected-internal-exception table**

Append after `test_agent_invoke_fails_safely_without_leaking_detail`:

```python
@pytest.mark.parametrize(
    "error",
    [
        RuntimeError(f"boom: {_SECRET_MARKER}"),
        KeyError(_SECRET_MARKER),
        MemoryError(_SECRET_MARKER),
    ],
    ids=["runtime-error", "key-error", "memory-error"],
)
def test_agent_invoke_hides_unexpected_exceptions(
    monkeypatch: pytest.MonkeyPatch, error: Exception
) -> None:
    async def raise_error(self: object, request: object) -> None:
        raise error

    monkeypatch.setattr(api_main.AgentService, "invoke", raise_error)
    client = TestClient(app)
    response = client.post("/v1/agent/invoke", json={"message": "hi"})
    assert response.status_code == 500
    assert response.json() == {"detail": "internal_server_error"}
    assert _SECRET_MARKER not in response.text
```

- [ ] **Step 3: Add the missing-API-configuration test**

```python
def test_missing_api_configuration_blocks_settings_construction() -> None:
    with pytest.raises(ValidationError):
        Settings(env="production", default_model="openai:gpt-5.4-mini", openai_api_key=None)
```

- [ ] **Step 4: Add invalid-request-shape and oversized-message tests**

```python
@pytest.mark.parametrize(
    "payload",
    [
        {"message": 12345},
        {"message": "hi", "thread_id": "x" * 256},
        {"message": "hi", "user_id": "x" * 129},
    ],
    ids=["wrong-type", "thread-id-too-long", "user-id-too-long"],
)
def test_agent_invoke_rejects_invalid_request_shapes(payload: dict[str, object]) -> None:
    client = TestClient(app)
    response = client.post("/v1/agent/invoke", json=payload)
    assert response.status_code == 422
    assert response.json() == {"detail": "validation_error"}


def test_agent_invoke_rejects_message_over_max_prompt_chars() -> None:
    client = TestClient(app)
    oversized_message = "x" * (api_main.settings.max_prompt_chars + 1)
    response = client.post("/v1/agent/invoke", json={"message": oversized_message})
    assert response.status_code == 400
    assert response.json() == {"detail": "validation_error"}
```

- [ ] **Step 5: Add the client-facing rate-limit test**

```python
def test_agent_invoke_returns_429_when_client_rate_limited(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fast_invoke(self: object, request: object) -> AgentResponse:
        return AgentResponse(
            request_id="request-1",
            thread_id="thread-1",
            answer="ok",
            used_tools=[],
            confidence=1.0,
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
```

- [ ] **Step 6: Run the full file**

Run: `uv run pytest tests/resilience/test_failure_catalog.py -v`
Expected: PASS (verified interactively for the oversized-message and wrong-type/too-long cases during plan authoring — all pass against current `main` with no production code changes).

- [ ] **Step 7: Commit**

```bash
git add tests/resilience/test_failure_catalog.py
git commit -m "test: catalog config, request-shape, and client rate-limit failure categories"
```

---

### Task 8: Final verification against issue #7's acceptance criteria

**Files:**
- None (verification only).

**Interfaces:**
- Consumes: everything from Tasks 1-7.
- Produces: nothing (terminal task).

- [ ] **Step 1: Run every quality gate**

Run: `make format lint typecheck test security`
Expected: all five pass with zero errors/warnings that weren't already present before this plan.

- [ ] **Step 2: Run the new suite in isolation**

Run: `make test-resilience`
Expected: PASS, 17 tests (AppError table x8 + unexpected-exception table x3 + 1 missing-config + invalid-shape table x3 + 1 oversized-message + 1 client-rate-limit).

- [ ] **Step 3: Walk the issue's acceptance criteria and confirm each is met**

- Tests are deterministic: every test either mocks `AgentService.invoke`, constructs exception objects directly, or exercises pure validation logic — no network calls, no timing races. Confirm by running `make test-resilience` twice in a row and diffing output (should be identical modulo timestamps in log lines).
- Tests do not require live OpenAI credentials: confirm by running `APP_OPENAI_API_KEY= make test-resilience` (empty key) and observing the same pass result.
- Provider behavior is mocked/faked at the appropriate boundary: confirmed — `openai.*Error`/`GraphRecursionError` instances constructed directly for classification tests (Tasks 1-2), `AgentService.invoke` monkeypatched for HTTP-contract tests (Tasks 6-7), matching the pre-existing pattern in `tests/unit/test_api.py`.
- Error response contracts are asserted: every HTTP-level test in `tests/resilience/test_failure_catalog.py` asserts both `status_code` and the exact `{"detail": ...}` body.
- Sensitive information leakage is tested: `_SECRET_MARKER` is embedded in every injected error message across Task 6 and Task 7's unexpected-exception table, and every one of those tests asserts `_SECRET_MARKER not in response.text`.
- Full deterministic suite passes: confirmed by Step 1's `make test` run (which now includes `tests/resilience`).

- [ ] **Step 4: Update the issue**

Report back to the user with the final `make format lint typecheck test security` output before closing or commenting on issue #7 — do not close the issue without explicit confirmation from the user.
