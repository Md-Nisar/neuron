# Harden Configuration and Runtime Limits (Issue #2) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `APP_TOOL_TIMEOUT_SECONDS` an actually-enforced runtime limit, and keep configuration/docs consistent with real behavior.

**Architecture:** Investigation (see Findings below) showed `request_timeout_seconds`, `max_output_tokens`, `max_agent_iterations`, and `max_prompt_chars` are already genuinely enforced and tested. `tool_timeout_seconds` is the one limit that is defined, range-validated, and threaded into a config dict — but that dict key (`"timeout"`) is not a real `RunnableConfig`/LangGraph field, so it is silently ignored: a hanging tool call is never bounded today. Fix: enforce it with a LangChain agent middleware hook (`wrap_tool_call`/`awrap_tool_call`), which is the framework's real extension point for intercepting tool execution, and delete the dead config key instead of leaving it looking functional.

**Tech Stack:** Python 3.13, LangChain `create_agent` + `AgentMiddleware`/`wrap_tool_call`, LangGraph, pytest (`anyio` mode), pydantic-settings.

**Spec:** GitHub issue #2, "Harden Configuration and Runtime Limits" (v0.2.0 milestone; body sourced from `scripts/create-v020-issues.ps1` key `02`, since `gh` auth was unavailable in this session). Acceptance criteria:
- Every configured limit is actually enforced.
- Limits have unit/integration coverage.
- Exceeding a limit produces a predictable error.
- No unbounded agent loop is possible.
- Documentation matches actual behavior.
- Development/test/production configuration is consistent.

## Findings (investigation already done — do not re-derive)

- `request_timeout_seconds` → `ChatOpenAI(timeout=...)`: real, enforced by the OpenAI/httpx client. Tested in `tests/unit/test_model_factory.py::test_create_chat_model_configures_openai_model_limits`.
- `max_output_tokens` → `ChatOpenAI(max_tokens=...)`: real, same test.
- `max_agent_iterations` → passed as `recursion_limit` in `agent_invocation_config()`, consumed by `agent.ainvoke(config=...)` in `graphs/main_graph.py::call_agent`. `recursion_limit` **is** a real `RunnableConfig` key (confirmed via `RunnableConfig.__annotations__`). LangGraph raises `GraphRecursionError` when exceeded; `classify_agent_error` falls back to `AgentExecutionError` for anything unrecognized (already documented in `ARCHITECTURE.md` line 94). No change needed here.
- `max_prompt_chars` → enforced by `security/input_policy.py::validate_user_message`, called from `services/agent_service.py`. Real, tested in `tests/security/test_input_policy.py`. No change needed.
- `tool_timeout_seconds` → **confirmed dead**. `agent_invocation_config()` returns `{"recursion_limit": ..., "timeout": ...}`; this dict is passed as the `config=` argument to `agent.ainvoke()` (in `call_agent`) and, separately, a `"timeout"` key is also passed at the top level of the outer `graph.ainvoke(config=...)` call in `services/agent_service.py`. Verified via `uv run python`: `RunnableConfig.__annotations__.keys()` is `{tags, metadata, callbacks, run_name, max_concurrency, recursion_limit, configurable, run_id}` — no `timeout` key exists, and `langgraph.pregel`'s source has no handling of a `"timeout"` config key either. The key is silently dropped. Nothing today bounds how long a single tool call may run — a hanging tool would block the whole request indefinitely, which also violates "no unbounded agent loop is possible".
- The `errors/base.py::ToolExecutionError` taxonomy entry ("Tool failed after local validation", `http_status=502`, `retryable=True`, `user_visible=False`) already exists from issue #1 and is already wired end-to-end to HTTP in `api/main.py` (see `tests/unit/test_api.py::test_agent_invoke_maps_app_errors_to_http`). It is the correct error to raise on a tool timeout — no new error type needed.
- `langchain.agents.create_agent` accepts a `middleware: Sequence[AgentMiddleware]` argument. `AgentMiddleware` (and the `@wrap_tool_call` decorator, confirmed present in `langchain.agents.middleware`) exposes an `awrap_tool_call(request: ToolCallRequest, handler)` hook that wraps every tool call; exceptions raised inside it propagate out of `agent.ainvoke()` unless `handle_tool_errors` is set on the `ToolNode` (it isn't, here). This is the correct, idiomatic place to enforce a per-tool-call timeout — confirmed via `uv run python -c "..."` introspection of the installed `langchain` version, not guessed from memory.
- Gap: `models/factory.py::classify_agent_error` does not check `isinstance(exc, AppError)` first. If our new middleware raises `ToolExecutionError` (an `AppError` subclass) from inside `agent.ainvoke()`, `call_agent`'s `except Exception` will pass it through `classify_agent_error`, which today would **misclassify it** as the generic `AgentExecutionError` (500, wrong code) because none of the existing `isinstance` branches match. This must be fixed as part of this change or the new timeout error loses its correct `tool_execution_error` / 502 classification.
- `.env.example` is missing `APP_MAX_PROMPT_CHARS` even though `max_prompt_chars` is a real, enforced setting — a documentation/config-consistency gap called out by the issue's own acceptance criteria.
- `ARCHITECTURE.md`'s Failure Handling section documents the recursion-limit fallback but says nothing about tool-call timeouts — needs one sentence once enforcement exists.

## Global Constraints

- Module boundaries from `AGENTS.md`/`CLAUDE.md` are enforced: this is a `models/` concern (`create_agent`/provider boundary + harness exception classification), not `tools/` or `agents/`. Do not create a new top-level module for a two-function change.
- No new error type: reuse `ToolExecutionError` from `errors/base.py`.
- No new settings field: `tool_timeout_seconds` already exists with `ge=1, le=60` bounds in `config/settings.py` — do not touch that file.
- Python 3.13: `asyncio.TimeoutError` is the builtin `TimeoutError`; catch `TimeoutError`, not a separate alias.
- Follow existing test conventions: `pytestmark = pytest.mark.anyio` for async tests (see `tests/graph/test_main_graph.py`), plain `def test_...()` for sync ones (see `tests/unit/test_model_factory.py`).
- Run `make format lint typecheck test security` before considering any task done (per `CLAUDE.md`).

---

### Task 1: Enforce `tool_timeout_seconds` with a real middleware hook, remove the dead config key

**Files:**
- Modify: `src/neuron_agent/models/factory.py`
- Modify: `src/neuron_agent/services/agent_service.py`
- Modify: `tests/unit/test_model_factory.py`
- Modify: `tests/graph/test_main_graph.py`

**Interfaces:**
- Consumes: `neuron_agent.errors.base.{AppError, ToolExecutionError}` (existing), `neuron_agent.config.settings.Settings.tool_timeout_seconds` (existing, already range-validated).
- Produces: `neuron_agent.models.factory.tool_timeout_middleware(timeout_seconds: float) -> AgentMiddleware` — used by `create_main_agent`. `classify_agent_error(exc: Exception) -> AppError` now returns `exc` unchanged when `exc` is already an `AppError`. `agent_invocation_config(settings: Settings) -> dict[str, int]` now returns only `{"recursion_limit": ...}` (the `"timeout"` key is removed — it never did anything).

- [ ] **Step 1: Write the failing tests**

Add to `tests/unit/test_model_factory.py` (new imports at top: `import asyncio`, `import pytest`, and `from neuron_agent.errors.base import ToolExecutionError` — `ToolExecutionError` is not yet imported in that file; add it to the existing `from neuron_agent.errors.base import (...)` block):

```python
def test_agent_invocation_config_uses_max_agent_iterations() -> None:
    settings = Settings(env="test", max_agent_iterations=5, openai_api_key=None)
    assert agent_invocation_config(settings) == {"recursion_limit": 5}


def test_classify_agent_error_passes_through_app_errors() -> None:
    error = ToolExecutionError("tool timed out")
    assert classify_agent_error(error) is error
```

(This replaces the existing `test_agent_invocation_config_uses_max_agent_iterations` body, which currently asserts `{"recursion_limit": 5, "timeout": 20}` — update it in place rather than adding a duplicate test name.)

Add a new test file `tests/unit/test_tool_timeout_middleware.py`:

```python
from __future__ import annotations

import asyncio

import pytest
from langchain_core.messages import ToolMessage

from neuron_agent.errors.base import ToolExecutionError
from neuron_agent.models.factory import tool_timeout_middleware

pytestmark = pytest.mark.anyio


class _FakeRequest:
    def __init__(self, name: str) -> None:
        self.tool_call = {"name": name, "args": {}, "id": "call-1"}


async def test_tool_timeout_middleware_allows_fast_tool() -> None:
    middleware = tool_timeout_middleware(timeout_seconds=0.2)

    async def fast_handler(request: object) -> ToolMessage:
        return ToolMessage(content="ok", tool_call_id="call-1")

    result = await middleware.awrap_tool_call(_FakeRequest("fast_tool"), fast_handler)
    assert result.content == "ok"


async def test_tool_timeout_middleware_raises_on_slow_tool() -> None:
    middleware = tool_timeout_middleware(timeout_seconds=0.05)

    async def slow_handler(request: object) -> ToolMessage:
        await asyncio.sleep(1)
        return ToolMessage(content="too late", tool_call_id="call-1")

    with pytest.raises(ToolExecutionError):
        await middleware.awrap_tool_call(_FakeRequest("slow_tool"), slow_handler)
```

Update `tests/graph/test_main_graph.py`: in `FakeAgent.ainvoke`, change the assertion from
`assert config == {"recursion_limit": 5, "timeout": 20}` to `assert config == {"recursion_limit": 5}`.

- [ ] **Step 2: Run the new/changed tests to verify they fail**

Run: `uv run pytest tests/unit/test_model_factory.py tests/unit/test_tool_timeout_middleware.py tests/graph/test_main_graph.py -q`
Expected: FAIL — `tool_timeout_middleware` does not exist (ImportError/collection error), and the two updated assertions fail against current code (`{"recursion_limit": 5, "timeout": 20}` mismatch; `classify_agent_error` returns a new `AgentExecutionError` instance rather than the same object).

- [ ] **Step 3: Implement the middleware and wire it in**

In `src/neuron_agent/models/factory.py`:

1. Add imports:

```python
import asyncio
from collections.abc import Awaitable, Callable

from langchain.agents.middleware import AgentMiddleware, ToolCallRequest, wrap_tool_call
from langchain_core.messages import ToolMessage
from langgraph.types import Command
```

2. Add `ToolExecutionError` to the existing `from neuron_agent.errors.base import (...)` block.

3. Add the middleware factory (place it above `create_main_agent`, since `create_main_agent` will call it):

```python
def tool_timeout_middleware(timeout_seconds: float) -> AgentMiddleware:
    """Bound every tool call to `timeout_seconds`, raising ToolExecutionError past it."""

    @wrap_tool_call
    async def enforce_tool_timeout(
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], Awaitable[ToolMessage | Command]],
    ) -> ToolMessage | Command:
        try:
            return await asyncio.wait_for(handler(request), timeout=timeout_seconds)
        except TimeoutError as exc:
            tool_name = request.tool_call.get("name", "unknown")
            raise ToolExecutionError(
                f"tool '{tool_name}' exceeded {timeout_seconds}s timeout"
            ) from exc

    return enforce_tool_timeout
```

4. Wire it into `create_main_agent`:

```python
def create_main_agent(settings: Settings, tools: Sequence[BaseTool]) -> Any:
    """Create the configurable LangChain agent harness."""
    model = create_chat_model(settings)
    return create_agent(
        model=model,
        tools=list(tools),
        system_prompt=load_prompt("system/main.md"),
        response_format=AgentAnswer,
        middleware=[tool_timeout_middleware(settings.tool_timeout_seconds)],
        name="neuron_main_agent",
    )
```

5. Remove the dead key from `agent_invocation_config`:

```python
def agent_invocation_config(settings: Settings) -> dict[str, int]:
    """Return the runtime recursion budget for the agent loop."""
    return {"recursion_limit": settings.max_agent_iterations}
```

6. Fix `classify_agent_error` to pass through already-classified errors, as the first check:

```python
def classify_agent_error(exc: Exception) -> AppError:
    """Map a raw exception from the agent harness to the application error taxonomy."""
    if isinstance(exc, AppError):
        return exc
    if isinstance(exc, openai.RateLimitError):
        return AppRateLimitError("model provider rate limit exceeded")
```

Insert only the new `if isinstance(exc, AppError): return exc` check as the first line of the function body — the existing `if isinstance(exc, openai.RateLimitError): ...` branch and everything below it in the current file stay exactly as they are.

In `src/neuron_agent/services/agent_service.py`: remove the now-documented-dead `"timeout": self._settings.tool_timeout_seconds` line from the `config=` dict passed to `self._graph.ainvoke(...)`, leaving just `{"configurable": {"thread_id": thread_id}}`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_model_factory.py tests/unit/test_tool_timeout_middleware.py tests/graph/test_main_graph.py tests/unit/test_api.py -q`
Expected: PASS (all of them — `test_api.py` is included because it already asserts `ToolExecutionError` maps to 502/`internal_server_error`, and must keep passing since `classify_agent_error` changed).

- [ ] **Step 5: Run full quality gates**

Run: `make format lint typecheck test security`
Expected: all pass. Fix any `ruff`/`mypy --strict` findings surfaced by the new code (e.g. missing return-type annotations) before moving on.

- [ ] **Step 6: Commit**

```bash
git add src/neuron_agent/models/factory.py src/neuron_agent/services/agent_service.py tests/unit/test_model_factory.py tests/unit/test_tool_timeout_middleware.py tests/graph/test_main_graph.py
git commit -m "fix: enforce tool_timeout_seconds via agent middleware

The 'timeout' key previously stuffed into agent/graph invocation
config was never a real RunnableConfig field, so tool_timeout_seconds
was silently unenforced. Bound tool calls with a wrap_tool_call
middleware instead, and stop misclassifying AppErrors raised inside
the agent loop as generic AgentExecutionError."
```

---

### Task 2: Documentation and environment-config consistency

**Files:**
- Modify: `.env.example`
- Modify: `ARCHITECTURE.md`

**Interfaces:**
- Consumes: nothing new — this task only documents Task 1's behavior and an existing (already-enforced) setting.
- Produces: nothing consumed by later tasks (this is the last task).

- [ ] **Step 1: Add the missing `max_prompt_chars` example var**

In `.env.example`, under the `## AGENT EXECUTION` section, add a line after `APP_MAX_AGENT_ITERATIONS=5`:

```
APP_MAX_PROMPT_CHARS=12000
```

- [ ] **Step 2: Document tool-call timeout enforcement in ARCHITECTURE.md**

In `ARCHITECTURE.md`, append a sentence to the existing paragraph that starts with `` `graphs/main_graph.py::call_agent` classifies failures... `` (currently the last paragraph of the "Failure Handling" section, around line 94):

```
Every tool call is bounded by `APP_TOOL_TIMEOUT_SECONDS` via a `wrap_tool_call` agent middleware (`models/factory.py::tool_timeout_middleware`); a tool that exceeds it raises `ToolExecutionError` directly, which `classify_agent_error` now passes through unchanged instead of reclassifying.
```

- [ ] **Step 3: Verify no other doc references the old behavior**

Run: `grep -rn "tool_timeout_seconds\|TOOL_TIMEOUT" README.md DEVELOPMENT.md docs/ 2>/dev/null`
Expected: no stale claims contradicting the new enforcement (informational check; fix in place if anything surfaces).

- [ ] **Step 4: Final full verification**

Run: `make format lint typecheck test security`
Expected: all pass, no formatting diffs left uncommitted.

- [ ] **Step 5: Commit**

```bash
git add .env.example ARCHITECTURE.md
git commit -m "docs: document tool-call timeout enforcement and add missing env example"
```
