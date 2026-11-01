# Comprehensive Test Suite Audit Report: Neuron Agent

**Role:** Principal QA Engineer & Test Architect  
**Repository:** `neuron` (`neuron-agent v0.9.0`)  
**Audit Date:** November 1, 2026 (Multi-Pass Iterative Deep Audit)  
**Scope:** Full-stack test architecture (Python backend, FastAPI endpoints, LangGraph/LangChain agent, PostgreSQL persistence, JWT/OIDC authentication, React/Vite web application, Keycloakify theme, and CI/CD pipelines).

---

## 1. Executive Summary

A critical, evidence-based architectural audit was conducted across the entire test suite of the `neuron` repository across multiple iterative passes. The goal was to determine whether existing tests genuinely protect the application against regressions, bugs, edge cases, and security vulnerabilities, or whether passing tests and high coverage numbers provide false confidence.

### Summary Assessment & Verdict

| Metric / Dimension | Value / Status | Assessment |
| :--- | :--- | :--- |
| **Total Automated Tests** | **2,507 tests** (1,948 Python + 529 Web + 30 Theme) | Extensive numerical volume |
| **Python Line Coverage** | **91%** (5,409 / 5,918 statements) | High line coverage |
| **Test Execution Status** | **1,941 passed, 7 skipped, 3 deselected** (Python) | 100% pass rate of executed tests |
| **Integration Test Execution** | **135 tests skipped** in default local test runs | **Major local development blind spot** |
| **Agent / Graph Testing** | Heavy reliance on `HistoryEchoAgent` / `FakeAgent` | **High false confidence** in agent execution |
| **Error & Resilience Testing** | Complete mocking of `AgentService.invoke` | Masks real SDK and database failure modes |
| **Static Type Checking** | Tests excluded from `mypy` (103 errors in `tests/unit`) | Untyped test suite |
| **Overall Maturity Rating** | **Level 3+ (Mature Baseline with Critical Integration Blind Spots)** | **Conditional Protection** |

### Bottom-Line Verdict
The test suite offers **strong protection** in HTTP security headers, JWT token parsing and signature validation, request input validation, and local memory store semantics. However, it **fails to protect** the application against realistic production failures in:
1. **Streaming SSE Client Disconnection & Lease Leaks**: Zero tests verify that `_CleanupEventSourceResponse` releases thread run leases and stream capacity when a client disconnects mid-stream or hits a send timeout.
2. **Unhandled MCP Transport Failures Crash Entire Runs**: `ResponseTooLargeError` inherits from `Exception` rather than `ToolException`. In LangChain, `StructuredTool` only catches `ToolException`. If an MCP server returns a payload exceeding bytes limits or compressed bodies, `tool_failure_isolation_middleware` re-wraps it into `ToolExecutionError` and re-raises, crashing the entire agent run with a 500 error instead of falling back.
3. **Silent Answer Token Suppression in Streaming**: In `AnswerTokenExtractor`, when `chunk.id` is falsy (None or empty string), message states collide on `""`. Once message 1 finishes, `_cursor[""]` is set to `_DONE`, silently silencing all subsequent answer tokens in the stream.
4. **Database Interactions During Local Development**: All 135 Postgres integration tests are skipped by default (`-m 'not integration'`), resulting in 39%–52% coverage in critical persistence modules during local development.
5. **Thread Retention Job Deleting Active Checkpoints**: `retention.prune_threads()` calls `adelete_thread` without claiming a run lease, allowing active runs to be destroyed mid-execution.
6. **False Confidence via Docstring Tests**: `test_safe_url_contract_names_what_fetching_tools_must_do` checks words in a Python docstring rather than validating actual network DNS re-pinning or SSRF redirect behaviors.

---

## 2. Test Suite Inventory

The repository employs a multi-tiered testing structure spanning Python backend services, TypeScript/React frontend components, browser end-to-end automation, and deterministic evaluation benchmarks.

### 2.1 Inventory Breakdown

| Suite | Technology | Location | Files | Test Functions / Specs | Executed Items |
| :--- | :--- | :--- | :---: | :---: | :---: |
| **Unit Tests** | pytest, pytest-asyncio | [`tests/unit/`](file:///C:/entomo/AI/neuron/tests/unit) | 72 | 875 | 1,418 |
| **Security Tests** | pytest, pytest-asyncio | [`tests/security/`](file:///C:/entomo/AI/neuron/tests/security) | 26 | 252 | 449 |
| **Integration Tests** | pytest, psycopg, docker | [`tests/integration/`](file:///C:/entomo/AI/neuron/tests/integration) | 11 | 124 | 135 (skipped without DSN) |
| **Graph Tests** | pytest, LangGraph | [`tests/graph/`](file:///C:/entomo/AI/neuron/tests/graph) | 5 | 40 | 48 |
| **Deterministic Evals** | pytest, LangChain | [`tests/evals/`](file:///C:/entomo/AI/neuron/tests/evals) | 5 | 42 | 51 (3 live deselected) |
| **End-to-End API** | pytest, httpx, Uvicorn | [`tests/e2e/`](file:///C:/entomo/AI/neuron/tests/e2e) | 1 | 10 | 10 |
| **Failure Resilience** | pytest, TestClient | [`tests/resilience/`](file:///C:/entomo/AI/neuron/tests/resilience) | 1 | 6 | 22 |
| **Web UI Unit/Component** | Vitest, React Testing Library | [`web/src/`](file:///C:/entomo/AI/neuron/web/src) | 33 | 529 | 529 |
| **Web Browser E2E** | Playwright, Chromium | [`web/e2e/`](file:///C:/entomo/AI/neuron/web/e2e) | 1 | 8 | 8 |
| **Keycloak Login Theme** | Vitest, Keycloakify | [`keycloak-theme/src/test/`](file:///C:/entomo/AI/neuron/keycloak-theme/src/test) | 2 | 30 | 30 |
| **Total** | | | **157 files** | **1,916 test definitions** | **2,700 items** |

---

## 3. Test Execution Results

### 3.1 Python Backend Suite
- **Command:** `uv run python -m pytest tests/unit tests/graph tests/security tests/resilience tests/e2e tests/evals --cov=src/neuron_agent --cov-report=term-missing`
- **Duration:** 298.02 seconds (4 min 58 s)
- **Summary:** **1,941 passed, 7 skipped, 3 deselected, 1 warning**
- **Warning:** `LangSmithMissingAPIKeyWarning` in [`tests/unit/test_langsmith_governance.py`](file:///C:/entomo/AI/neuron/tests/unit/test_langsmith_governance.py) (LangSmith client warns when API key is unset).

#### Skipped Tests Analysis (7 skipped)
1. [`tests/unit/test_graceful_shutdown.py:267`](file:///C:/entomo/AI/neuron/tests/unit/test_graceful_shutdown.py#L267): Skipped on Windows (`Popen.send_signal(SIGTERM)` terminates process immediately without invoking signal handler).
2. [`tests/unit/test_graceful_shutdown.py:335`](file:///C:/entomo/AI/neuron/tests/unit/test_graceful_shutdown.py#L335): Skipped on Windows (same POSIX signal semantics).
3. [`tests/unit/test_validate_observability.py:133`](file:///C:/entomo/AI/neuron/tests/unit/test_validate_observability.py#L133): Skipped on Windows (POSIX permission bit verification).
4. [`tests/unit/test_validate_observability.py:146`](file:///C:/entomo/AI/neuron/tests/unit/test_validate_observability.py#L146): Skipped on Windows (symlink creation requires elevated OS privileges).
5. [`tests/unit/test_validate_observability.py:171`](file:///C:/entomo/AI/neuron/tests/unit/test_validate_observability.py#L171): Skipped on Windows (symlink creation).
6. [`tests/unit/test_validate_observability.py:324`](file:///C:/entomo/AI/neuron/tests/unit/test_validate_observability.py#L324): Skipped (`NEURON_OBSERVABILITY_BIN_DIR` not set; promtool binary not present).
7. [`tests/unit/test_validate_observability.py:329`](file:///C:/entomo/AI/neuron/tests/unit/test_validate_observability.py#L329): Skipped (`NEURON_OBSERVABILITY_BIN_DIR` not set; otelcol binary not present).

#### Deselected Tests Analysis (3 deselected)
- [`tests/evals/test_agent_quality.py:23-45`](file:///C:/entomo/AI/neuron/tests/evals/test_agent_quality.py#L23-L45): Deselected because `pytestmark = [pytest.mark.eval, pytest.mark.integration, pytest.mark.anyio]`. In [`pyproject.toml:111`](file:///C:/entomo/AI/neuron/pyproject.toml#L111), default `addopts` contains `-m 'not integration'`. These live LLM tests run only in `nightly-eval.yml` or manual `make eval`.

### 3.2 Python Integration Suite
- **Command:** `uv run python -m pytest tests/integration -m integration -rs`
- **Summary:** **135 skipped in 14.61s**.
- **Root Cause:** All 135 tests require `APP_TEST_POSTGRES_DSN`, `docker`, or live credentials. Without a running PostgreSQL container, the entire integration test layer is skipped.

### 3.3 Frontend Web Unit Suite
- **Command:** `npm --prefix web test` (Vitest v5.0.5)
- **Duration:** 67.08s
- **Summary:** **33 test files passed, 529 tests passed (100%)**.

### 3.4 Keycloak Theme Suite
- **Command:** `npm --prefix keycloak-theme test` (Vitest v5.0.5)
- **Duration:** 18.37s
- **Summary:** **2 test files passed, 30 tests passed (100%)**.

---

## 4. Test Quality Assessment

### 4.1 False Confidence via Excessive Mocking (`HistoryEchoAgent`)
A major architectural finding of this audit is that **`HistoryEchoAgent` dominates the backend test suite**:
- In [`tests/conftest.py#L115-L156`](file:///C:/entomo/AI/neuron/tests/conftest.py#L115-L156), `HistoryEchoAgent` is defined to intercept `main_graph.build_agent` and return a mock reply:
  ```python
  class HistoryEchoAgent:
      def __init__(self, delimiter: str = " | ") -> None:
          self.delimiter = delimiter

      async def ainvoke(self, inputs: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
          messages = inputs.get("messages", [])
          texts = [str(m.content) for m in messages if isinstance(m, (HumanMessage, AIMessage))]
          return {
              "answer": AgentAnswer(
                  answer=self.delimiter.join(texts),
                  used_tools=[],
                  confidence=1.0,
              ),
              "messages": [AIMessage(content=self.delimiter.join(texts))],
          }
  ```
- **Consequence:** Over **80% of API endpoints, thread lifecycle, and security tests** (including [`test_thread_lifecycle.py`](file:///C:/entomo/AI/neuron/tests/unit/test_thread_lifecycle.py), [`test_authorization.py`](file:///C:/entomo/AI/neuron/tests/security/test_authorization.py), and [`test_approval_api.py`](file:///C:/entomo/AI/neuron/tests/security/test_approval_api.py)) use this mock agent.
- **What is bypassed:**
  - The actual LangGraph compilation and node transitions (`call_agent`, `tools`, `human_approval`, `structured_output`).
  - Tool execution middleware (authorization, timeouts, failure isolation).
  - Model provider fallbacks and retries.
  - JSON schema parsing and `StructuredOutputError` validation.
- **Risk:** A major regression in LangGraph node routing or tool message serialization can pass 100% of these tests without detection.

### 4.2 Excessive Mocking in Failure & Resilience Catalog
- In [`tests/resilience/test_failure_catalog.py#L108-L146`](file:///C:/entomo/AI/neuron/tests/resilience/test_failure_catalog.py#L108-L146), every failure scenario is tested by monkeypatching `AgentService.invoke`:
  ```python
  monkeypatch.setattr(service, "invoke", mock_invoke)
  ```
- **What is bypassed:** The service layer itself! The test does not verify how `AgentService` handles underlying network timeouts, database pool errors, or model provider rate limits; it only tests FastAPI's exception-to-HTTP-status mapping.
- **False Confidence:** If an SDK exception changes its internal attributes or is not properly caught by `AgentService`, this test suite will still pass because the service is never invoked.

### 4.3 Meaningless & Tautological Assertions
- In [`tests/security/test_safe_url.py#L149-L152`](file:///C:/entomo/AI/neuron/tests/security/test_safe_url.py#L149-L152):
  ```python
  def test_safe_url_contract_names_what_fetching_tools_must_do() -> None:
      doc = " ".join((validate_safe_url.__doc__ or "").lower().split())
      for required in ("resolve once", "connect to the checked ip", "re-validate", "redirect"):
          assert required in doc, required
  ```
  This test asserts that words exist in a docstring! It does not test that any tool adheres to this behavior. In fact, `mcp/client.py` uses `httpx2.AsyncClient` which connects directly to hostnames without IP pinning.
- In [`tests/unit/test_version_source.py#L10-L16`](file:///C:/entomo/AI/neuron/tests/unit/test_version_source.py#L10-L16), tests verify that `__version__` matches `pyproject.toml`. While useful for release hygiene, this adds zero behavioral protection.

### 4.4 Static Type Checking Exclusion
- In [`pyproject.toml#L102-L106`](file:///C:/entomo/AI/neuron/pyproject.toml#L102-L106):
  ```toml
  [tool.mypy]
  files = ["src"]
  ```
- `tests/` is completely excluded from Mypy type-checking.
- Executing `uv run python -m mypy tests/unit` revealed **103 type errors across 26 files**.
- Unchecked test code allows broken mock setups, un-awaited async coroutines, and wrong method signatures to silently pass through CI.

---

## 5. Coverage Gaps by Module

While overall line coverage is **91%**, several mission-critical infrastructure and persistence modules suffer from severe local test blind spots due to skipped integration tests.

### 5.1 Statements & Branch Coverage Table (Lowest-Covered Modules)

| Module | Statements | Missing Lines | Line Coverage | Critical Missing Functionality |
| :--- | :---: | :---: | :---: | :--- |
| [`src/neuron_agent/persistence/roles.py`](file:///C:/entomo/AI/neuron/src/neuron_agent/persistence/roles.py) | 59 | 36 | **39%** | Postgres role permission enforcement & verification |
| [`src/neuron_agent/persistence/migrations.py`](file:///C:/entomo/AI/neuron/src/neuron_agent/persistence/migrations.py) | 71 | 42 | **41%** | DDL schema migration runner & lock acquisition |
| [`src/neuron_agent/persistence/rate_limiter.py`](file:///C:/entomo/AI/neuron/src/neuron_agent/persistence/rate_limiter.py) | 108 | 53 | **51%** | Postgres token bucket sliding window queries |
| [`src/neuron_agent/persistence/run_guard.py`](file:///C:/entomo/AI/neuron/src/neuron_agent/persistence/run_guard.py) | 90 | 43 | **52%** | Postgres concurrency leases & advisory lock acquisition |
| [`src/neuron_agent/persistence/token_budget.py`](file:///C:/entomo/AI/neuron/src/neuron_agent/persistence/token_budget.py) | 108 | 49 | **55%** | Ledger settlement, over-budget rejection, refund logic |
| [`src/neuron_agent/persistence/retention.py`](file:///C:/entomo/AI/neuron/src/neuron_agent/persistence/retention.py) | 48 | 17 | **65%** | Thread retention pruning & multi-page cleanup |
| [`src/neuron_agent/persistence/checkpointer.py`](file:///C:/entomo/AI/neuron/src/neuron_agent/persistence/checkpointer.py) | 129 | 34 | **74%** | Postgres async checkpoint pool exhaustion & recovery |
| [`src/neuron_agent/services/agent_service.py`](file:///C:/entomo/AI/neuron/src/neuron_agent/services/agent_service.py) | 511 | 48 | **91%** | Approval rollback, lease refund, bulk data erasure races |
| [`src/neuron_agent/api/main.py`](file:///C:/entomo/AI/neuron/src/neuron_agent/api/main.py) | 413 | 41 | **90%** | SSE stream disconnect handling, send timeout cleanups |

---

## 6. Security and Integration Test Gaps

### 6.1 Server-Sent Events (SSE) Run Lease Leak on Client Drop
- **Location:** [`src/neuron_agent/api/main.py#L171-L188`](file:///C:/entomo/AI/neuron/src/neuron_agent/api/main.py#L171-L188), [`src/neuron_agent/api/main.py#L654-L669`](file:///C:/entomo/AI/neuron/src/neuron_agent/api/main.py#L654-L669)
- **Design:** `_CleanupEventSourceResponse` executes `on_close` to call `await stream.aclose()` and `await run.lease.release()`.
- **Gap:** There are **zero tests** verifying that `on_close` is invoked when a client abruptly closes the TCP connection or when `send_timeout` (15s) fires.
- **Production Vulnerability:** In production, clients navigating away or losing mobile connectivity will leak thread leases. Subsequent requests to that thread will fail with `409 Conflict: thread_busy` for the remainder of `run_timeout_seconds` (120s), and the worker will permanently leak concurrent stream slots until hitting `503 Service Unavailable`.

### 6.2 LangGraph Message Eviction ID Omission
- **Location:** [`src/neuron_agent/graphs/main_graph.py#L154`](file:///C:/entomo/AI/neuron/src/neuron_agent/graphs/main_graph.py#L154)
- **Code:**
  ```python
  [RemoveMessage(id=m.id) for m in evicted if m.id]
  ```
- **Gap:** If any evicted message in `evicted` has `m.id is None` or empty string, `if m.id` quietly skips it!
- **Consequence:** Messages without IDs are never evicted from checkpoint state, allowing the thread checkpoint size to grow without bound, violating `max_thread_messages`.

### 6.3 Missing Local Integration Gate for PostgreSQL
- **Location:** [`pyproject.toml#L111`](file:///C:/entomo/AI/neuron/pyproject.toml#L111)
- **Configuration:** `addopts = "-m 'not integration and not loadtest'"`
- **Consequence:** Developers running `pytest` or `make test` locally never execute PostgreSQL integration tests. A SQL syntax error, schema mismatch, or advisory lock regression in `token_budget.py` or `run_guard.py` will not be detected until pushed to CI.

---

## 7. Critical Findings Ranked by Severity

### [TEST-01] CRITICAL: Untested SSE Disconnect & Send Timeout Run Lease Cleanup
- **Location:** [`src/neuron_agent/api/main.py#L171-L188`](file:///C:/entomo/AI/neuron/src/neuron_agent/api/main.py#L171-L188), [`src/neuron_agent/api/main.py#L654-L669`](file:///C:/entomo/AI/neuron/src/neuron_agent/api/main.py#L654-L669)
- **What's Wrong:** `_CleanupEventSourceResponse` wraps `EventSourceResponse` to ensure `run.lease.release()` is called on disconnect or send timeout. No tests in `tests/unit/test_streaming.py` or `tests/security/test_approval_stream.py` simulate client disconnects or send timeouts at the HTTP ASGI layer.
- **Why It Matters:** If `on_close` fails to fire or encounters an unhandled exception during ASGI cancellation, the thread lease remains locked in `RunGuard`. The user is blocked from making further requests on that thread, and `max_concurrent_streams` capacity leaks.
- **Realistic Failure Scenario:** A mobile user opens `/v1/agent/stream` and switches apps, dropping the connection. The server continues streaming in background until `send_timeout`. If cleanup is broken, the thread remains in `thread_busy` state, and subsequent messages return HTTP 409.
- **Recommended Test:** Using `httpx.AsyncClient` with a custom transport or streaming test client, connect to `/v1/agent/stream`, read the first token, close the client response abruptly, and assert that `service._run_guard.is_thread_active(thread_id)` returns `False` within 500ms.

---

### [TEST-02] CRITICAL: Unhandled MCP Transport Errors Crash the Agent Run Instead of Graceful Tool Failure
- **Location:** [`src/neuron_agent/tools/mcp/client.py#L58-L61`](file:///C:/entomo/AI/neuron/src/neuron_agent/tools/mcp/client.py#L58-L61), [`#L79-L105`](file:///C:/entomo/AI/neuron/src/neuron_agent/tools/mcp/client.py#L79-L105), [`src/neuron_agent/models/factory.py#L409-L424`](file:///C:/entomo/AI/neuron/src/neuron_agent/models/factory.py#L409-L424)
- **What's Wrong:** `ResponseTooLargeError` inherits from `Exception` rather than `ToolException`. In LangChain, `StructuredTool.ainvoke` with `handle_tool_error=lambda _: _UNUSABLE_RESULT` only catches `ToolException`. When an MCP server sends a payload exceeding `max_response_bytes`, sends a compressed body (`content-encoding != identity`), or drops TCP, `ResponseTooLargeError` / `httpx2` network errors are NOT caught by `StructuredTool`. Instead, they bubble up to `tool_failure_isolation_middleware`, which re-wraps them in `ToolExecutionError` and re-raises them out of the agent, aborting the entire user run with an unhandled 500 error instead of returning `_UNUSABLE_RESULT` ("Answer without it").
- **Why It Matters:** An external or remote MCP server can crash the entire agent conversation whenever it sends a large response or closes a socket.
- **Realistic Failure Scenario:** An operator configures an external MCP tool. During a conversation, the tool returns a 20KB response exceeding `mcp_max_output_bytes`. Instead of gracefully informing the model to answer without the tool, the entire agent run crashes with `ToolExecutionError`, returning a 500 internal server error to the user.
- **Recommended Test:** In [`tests/unit/test_mcp_client.py`](file:///C:/entomo/AI/neuron/tests/unit/test_mcp_client.py), add a test where a mock MCP server sends a response body larger than `max_response_bytes` or returns `content-encoding: gzip`. Assert that `tool.ainvoke` returns `_UNUSABLE_RESULT` and that `ResponseTooLargeError` inherits from `ToolException`.

---

### [TEST-03] HIGH: Silent Answer Token Suppression in Multi-Message Streaming when Chunk ID is Falsy
- **Location:** [`src/neuron_agent/services/streaming.py#L77-L119`](file:///C:/entomo/AI/neuron/src/neuron_agent/services/streaming.py#L77-L119)
- **What's Wrong:** `AnswerTokenExtractor` indexes chunk state by `key = chunk.id or ""`. If `chunk.id` is None/empty (common in various LLM streaming chunks or fake test models), `key` defaults to `""`. When the first message completes, `self._cursor[""]` is set to `_DONE` (-1). Any subsequent message in the stream or execution that also lacks `id` will hit `if cursor == _DONE: return ""` and silently drop 100% of its answer tokens, emitting empty string deltas (`""`) for the remainder of the session.
- **Why It Matters:** Users experience a completely broken stream where tokens disappear or the stream hangs until the `final` event arrives.
- **Realistic Failure Scenario:** An agent run involves two sequential AI turns (e.g. following a tool execution). The LLM provider emits chunks where `chunk.id` is not set on the second message. The first message streams tokens normally, but the second message's tokens are completely swallowed, giving the user the appearance that the model froze.
- **Recommended Test:** In [`tests/unit/test_streaming.py`](file:///C:/entomo/AI/neuron/tests/unit/test_streaming.py), add a test feeding two sequential AIMessageChunks with `id=None` into `AnswerTokenExtractor`, asserting that tokens from both messages are emitted.

---

### [TEST-04] HIGH: Thread Retention Pruning Deleting Active Checkpoints Without Lease Claims
- **Location:** [`src/neuron_agent/persistence/retention.py#L127-L130`](file:///C:/entomo/AI/neuron/src/neuron_agent/persistence/retention.py#L127-L130)
- **What's Wrong:** While `AgentService.erase_user_data` carefully acquires a run lease (`await self._run_guard.hold_thread(thread_id, ...)`) to prevent deleting an active thread, `retention.prune_threads()` calls `await self._checkpointer.adelete_thread(thread_id)` directly WITHOUT acquiring any thread lease or checking active runs.
- **Why It Matters:** If retention runs while a long-running thread is executing, its checkpoint state is destroyed mid-execution, causing LangGraph checkpointer corruption and runtime crashes.
- **Realistic Failure Scenario:** An automated daily cron job calls `prune_threads` to purge threads older than 30 days. A user resumes a 31-day-old thread right as the cron runs. The retention job deletes the thread checkpoints while the agent is midway through executing tools, resulting in a fatal state deserialization error.
- **Recommended Test:** In [`tests/unit/test_persistence.py`](file:///C:/entomo/AI/neuron/tests/unit/test_persistence.py), add a concurrency test where `prune_threads` attempts to delete a thread currently held by `RunGuard.claim()`, verifying that active threads are skipped.

---

### [TEST-05] HIGH: False Confidence via Pervasive `HistoryEchoAgent` Mocking
- **Location:** [`tests/conftest.py#L115-L156`](file:///C:/entomo/AI/neuron/tests/conftest.py#L115-L156)
- **What's Wrong:** The fixture `echo_agent` replaces the real LangGraph agent with a simplistic string concatenation mock in over 80% of backend tests.
- **Why It Matters:** Passing tests provide zero assurance that LangGraph state transitions, tool execution loops, interrupt resumption, and structured output parsing work under realistic conditions.
- **Realistic Failure Scenario:** An upgrade to `langgraph` changes how `interrupt()` or `StateGraph` merges messages. All unit, security, and thread lifecycle tests continue to pass because `HistoryEchoAgent` is invoked instead of LangGraph.
- **Recommended Test:** Refactor core thread lifecycle and authorization test suites to use `create_main_agent` with deterministic fake chat models (`StreamingFakeModel` or `FakeListChatModel`) instead of replacing the entire agent with `HistoryEchoAgent`.

---

### [TEST-06] HIGH: 135 PostgreSQL Integration Tests Skipped in Default Local Suite
- **Location:** [`pyproject.toml#L111`](file:///C:/entomo/AI/neuron/pyproject.toml#L111), [`tests/integration/conftest.py#L18-L22`](file:///C:/entomo/AI/neuron/tests/integration/conftest.py#L18-L22)
- **What's Wrong:** All 135 PostgreSQL integration tests are skipped in local development environments unless `APP_TEST_POSTGRES_DSN` is explicitly exported.
- **Why It Matters:** Persistence code has severely degraded local coverage (39% in `roles.py`, 41% in `migrations.py`, 51% in `rate_limiter.py`, 52% in `run_guard.py`). Developers receive no feedback on SQL regressions before opening pull requests.
- **Realistic Failure Scenario:** A developer modifies an index or query in `token_budget.py`. Local `pytest` passes with 100% green tests. The bug is only discovered when CI runs against a real database service container.
- **Recommended Test:** Provide an automated Docker Compose or Testcontainers hook in `tests/integration/conftest.py` that spins up a local ephemeral PostgreSQL container when `APP_TEST_POSTGRES_DSN` is not preset.

---

### [TEST-07] HIGH: Complete Mocking of `AgentService.invoke` in Failure & Resilience Catalog
- **Location:** [`tests/resilience/test_failure_catalog.py#L108-L146`](file:///C:/entomo/AI/neuron/tests/resilience/test_failure_catalog.py#L108-L146)
- **What's Wrong:** Tests in `test_failure_catalog.py` monkeypatch `AgentService.invoke` to raise pre-instantiated exceptions, verifying only FastAPI's exception handler rather than the service's error classification logic.
- **Why It Matters:** The service layer's error translation from provider/database exceptions (`openai.RateLimitError`, `psycopg.OperationalError`) into typed `AppError` instances is completely bypassed.
- **Realistic Failure Scenario:** A new provider error type (e.g. Anthropic overload) is introduced. Because `AgentService.invoke` is mocked, the resilience tests report that error 503 is returned, while in production the unclassified exception escapes as an unhandled 500 error.
- **Recommended Test:** Refactor `test_failure_catalog.py` to invoke an unmocked `AgentService` with mock LLM providers that raise realistic provider exceptions, asserting end-to-end exception classification.

---

### [TEST-08] HIGH: Tests Completely Excluded from Static Type Checking (`mypy`)
- **Location:** [`pyproject.toml#L102-L106`](file:///C:/entomo/AI/neuron/pyproject.toml#L102-L106)
- **What's Wrong:** Mypy is configured to check only `src/`. Running Mypy against `tests/unit` produces **103 type errors across 26 files**.
- **Why It Matters:** Test code is prone to subtle bugs: un-awaited async calls, mismatched fixture arguments, or calling nonexistent attributes on mock objects.
- **Realistic Failure Scenario:** A test function forgets to `await` an asynchronous helper. In Python, an un-awaited coroutine object evaluates to truthy in boolean assertions (`assert coroutine`), causing the test to pass without ever executing the check.
- **Recommended Test:** Add `tests` to `tool.mypy.files` in `pyproject.toml`, resolve the 103 type errors, and enforce strict type checking on tests in CI.

---

### [TEST-09] MEDIUM: Untested Rollback Logic in Approval Preparation and Bulk Erasure
- **Location:** [`src/neuron_agent/services/agent_service.py#L509-L517`](file:///C:/entomo/AI/neuron/src/neuron_agent/services/agent_service.py#L509-L517), [`#L1201-L1203`](file:///C:/entomo/AI/neuron/src/neuron_agent/services/agent_service.py#L1201-L1203)
- **What's Wrong:** `prepare_approval` rollback paths (`_token_budget.settle(reservation, 0)` and `lease.release()`) and `erase_all_user_data` busy-thread handling (`except RunClaimDenied: skipped_busy += 1`) have 0% test coverage.
- **Why It Matters:** Compensation and rollback logic in stateful services are notorious sources of leaks (token quota leaks, thread deadlocks, or partial data erasure).
- **Realistic Failure Scenario:** During an approval continuation, an error occurs between reserving tokens and executing the run. Because rollback logic is untested, an unhandled error leaves the token reservation open, permanently reducing the user's available token balance.
- **Recommended Test:** In [`tests/unit/test_thread_lifecycle.py`](file:///C:/entomo/AI/neuron/tests/unit/test_thread_lifecycle.py), add unit tests forcing `RunClaimDenied` during `prepare_approval` and `erase_all_user_data` to assert budget settlement and `skipped_busy_count` reporting.

---

### [TEST-10] MEDIUM: Meaningless Test Assertion in SSRF Policy Verification
- **Location:** [`tests/security/test_safe_url.py#L149-L152`](file:///C:/entomo/AI/neuron/tests/security/test_safe_url.py#L149-L152), [`src/neuron_agent/tools/mcp/client.py#L111-L125`](file:///C:/entomo/AI/neuron/src/neuron_agent/tools/mcp/client.py#L111-L125)
- **What's Wrong:** `test_safe_url_contract_names_what_fetching_tools_must_do()` checks that the words `"resolve once"`, `"connect to the checked ip"`, and `"redirect"` appear in the Python docstring of `validate_safe_url`. However, `src/neuron_agent/tools/mcp/client.py` uses `httpx2.AsyncClient` which connects directly to the domain name without DNS pinning or connecting to the validated IP, violating the contract.
- **Why It Matters:** Tests assert that docstrings contain safety advice rather than verifying that tools actually implement DNS pinning and SSRF redirect protections, creating a false impression of SSRF security.
- **Realistic Failure Scenario:** A malicious MCP configuration points to an external domain that dynamically changes its DNS A record to `169.254.169.254` (cloud metadata). The tool connects directly to the hostname, resulting in SSRF.
- **Recommended Test:** Replace the docstring string-search test with an actual integration test verifying that `mcp/client.py` rejects redirects to private IPs and pins the resolved IP address on connection.

---

### [TEST-11] MEDIUM: Database Connection Pool Exhaustion & Recovery is Untested
- **Location:** [`src/neuron_agent/persistence/checkpointer.py#L170-L245`](file:///C:/entomo/AI/neuron/src/neuron_agent/persistence/checkpointer.py#L170-L245), [`tests/unit/test_persistence.py#L34-L41`](file:///C:/entomo/AI/neuron/tests/unit/test_persistence.py#L34-L41)
- **What's Wrong:** While tests verify pool minimum and maximum size constraints, there are no tests simulating pool starvation when all connections are checked out and a new request arrives.
- **Why It Matters:** Under burst traffic, pool starvation must fail fast with `PersistenceError` (mapped to `503 Service Unavailable`) rather than hanging indefinitely and blocking the Uvicorn event loop.
- **Realistic Failure Scenario:** A surge of concurrent requests consumes all connections in `psycopg_pool`. An incoming request hangs waiting for a connection, exceeding client gateway timeouts and causing cascading socket exhaustion.
- **Recommended Test:** In [`tests/unit/test_persistence.py`](file:///C:/entomo/AI/neuron/tests/unit/test_persistence.py), add a test that checks out all `pool.max_size` connections and verifies that a subsequent checkpointer operation raises `PersistenceError` within `postgres_pool_timeout_seconds`.

---

### [TEST-12] MEDIUM: Truncated Memory History Prevents Legitimate User Recall/Remember
- **Location:** [`src/neuron_agent/memory/tools.py#L50-L60`](file:///C:/entomo/AI/neuron/src/neuron_agent/memory/tools.py#L50-L60), [`src/neuron_agent/graphs/main_graph.py#L93-L111`](file:///C:/entomo/AI/neuron/src/neuron_agent/graphs/main_graph.py#L93-L111)
- **What's Wrong:** `_user_words` inspects `runtime.state["messages"]`, which only holds the trimmed window produced by `bound_model_history`. If a conversation exceeds `max_history_tokens` (8,000 tokens), older user messages are dropped from the active history. When the agent subsequently attempts to call `remember()` on a fact the user stated in an earlier turn, the tool rejects it with `Error: only the user's own words can be remembered`.
- **Why It Matters:** The agent cannot store memories from earlier parts of long conversations; there are zero tests testing memory operations across trimmed history boundaries.
- **Realistic Failure Scenario:** In a multi-turn conversation exceeding 8,000 tokens, the user asks "Remember that fact I told you at the start?". The agent calls `remember(text="...")`. The tool fails with an error because the original human message was trimmed from `runtime.state`.
- **Recommended Test:** In [`tests/security/test_memory_tools.py`](file:///C:/entomo/AI/neuron/tests/security/test_memory_tools.py), add a test where a thread contains 20 turns exceeding `max_history_tokens`, verifying expected behavior when remembering a fact from turn 1.

---

### [TEST-13] LOW: Silent Eviction Bypass When Message ID is Missing in History Eviction
- **Location:** [`src/neuron_agent/graphs/main_graph.py#L154`](file:///C:/entomo/AI/neuron/src/neuron_agent/graphs/main_graph.py#L154), [`tests/graph/test_history_bounds.py`](file:///C:/entomo/AI/neuron/tests/graph/test_history_bounds.py)
- **What's Wrong:** When the thread exceeds `max_thread_messages`, `RemoveMessage(id=m.id) for m in evicted if m.id` silently skips any messages where `id` is None or empty string. Messages without an explicit ID remain in thread checkpoint state forever, defeating the message cap.
- **Why It Matters:** Thread state grows indefinitely, degrading database performance and deserialization memory.
- **Realistic Failure Scenario:** A custom or third-party client produces turns without assigning explicit UUIDs to `HumanMessage` or `AIMessage`. As the thread grows past 200 messages, eviction runs but fails to remove any un-identified messages.
- **Recommended Test:** In [`tests/graph/test_history_bounds.py`](file:///C:/entomo/AI/neuron/tests/graph/test_history_bounds.py), add a test with 250 messages where some messages have `id=None`, verifying that all messages beyond `max_thread_messages` are evicted.

---

### [TEST-14] LOW: Complete Exclusion of Live LLM Evals from Default Test Suites
- **Location:** [`tests/evals/test_agent_quality.py#L18-L45`](file:///C:/entomo/AI/neuron/tests/evals/test_agent_quality.py#L18-L45), [`pyproject.toml#L111`](file:///C:/entomo/AI/neuron/pyproject.toml#L111)
- **What's Wrong:** The entire suite of LLM quality, security, and multi-turn evals is decorated with `pytest.mark.integration`. Because default `addopts` excludes integration tests (`-m 'not integration'`), developers and standard CI PR builds never run quality evals.
- **Why It Matters:** Regressions in model prompts, tool descriptions, or system instructions are never detected during regular PR checks.
- **Realistic Failure Scenario:** A prompt edit inadvertently breaks the agent's ability to resist prompt injection or use calculator tools. The PR merges because standard tests pass and evals are not run.
- **Recommended Test:** Create a mock-based deterministic subset of eval cases that runs under standard `make test` without requiring live API keys.

---

## 8. Prioritized Remediation Roadmap

```mermaid
flowchart TD
    subgraph Phase 1: Critical Reliability & Transport Fixes (Weeks 1-2)
        P1A["Fix & Test ResponseTooLargeError in MCP Client"]
        P1B["Fix & Test AnswerTokenExtractor Missing Chunk ID Leak"]
        P1C["Add SSE Stream Disconnect & Send Timeout Tests"]
        P1D["Add Thread Retention Lease Check in retention.py"]
    end

    subgraph Phase 2: Integration & Realism Hardening (Weeks 3-4)
        P2A["Replace HistoryEchoAgent in Core API & Lifecycle Tests"]
        P2B["Implement Automated Ephemeral Local Postgres Test Runner"]
        P2C["Refactor Failure Catalog to Use Unmocked AgentService"]
        P2D["Add Connection Pool Starvation & Recovery Tests"]
    end

    subgraph Phase 3: Pipeline & Tooling Quality Gates (Weeks 5-6)
        P3A["Fix Mypy Module Setup & Enable Type Checking on tests/"]
        P3B["Add Targeted PR Mutation Testing for security/ and tools/"]
        P3C["Replace Docstring Contract Tests with Real Network Tests"]
        P3D["Add Mock-Backed Fast Quality Eval Suite to PR Gates"]
    end

    Phase 1 --> Phase 2
    Phase 2 --> Phase 3
```

---

## 9. Top 10 Tests That Should Be Added First

1. **`test_mcp_response_too_large_error_handled_gracefully`**
   - **Target:** [`src/neuron_agent/tools/mcp/client.py#L58-L61`](file:///C:/entomo/AI/neuron/src/neuron_agent/tools/mcp/client.py#L58-L61), [`src/neuron_agent/models/factory.py#L409-L424`](file:///C:/entomo/AI/neuron/src/neuron_agent/models/factory.py#L409-L424)
   - **Scenario:** Mock MCP server sends a body larger than `mcp_max_output_bytes` or compressed content; assert `ResponseTooLargeError` inherits from `ToolException`, `tool.ainvoke` catches it, returns `_UNUSABLE_RESULT`, and the agent run does NOT crash.
2. **`test_answer_token_extractor_sequential_messages_without_ids`**
   - **Target:** [`src/neuron_agent/services/streaming.py#L77-L119`](file:///C:/entomo/AI/neuron/src/neuron_agent/services/streaming.py#L77-L119)
   - **Scenario:** Feed two sequential `AIMessageChunk` instances with `id=None` into `AnswerTokenExtractor`; assert that tokens from both messages are decoded and returned.
3. **`test_stream_client_disconnect_releases_lease_and_slot`**
   - **Target:** [`src/neuron_agent/api/main.py#L171-L188`](file:///C:/entomo/AI/neuron/src/neuron_agent/api/main.py#L171-L188)
   - **Scenario:** Client terminates HTTP connection while tokens are streaming; assert `on_close` fires, `lease.release()` is called, and `_open_streams` returns to 0.
4. **`test_stream_send_timeout_aborts_and_cleans_up`**
   - **Target:** [`src/neuron_agent/api/main.py#L662-L669`](file:///C:/entomo/AI/neuron/src/neuron_agent/api/main.py#L662-L669)
   - **Scenario:** Simulate slow consumer triggering `_STREAM_SEND_TIMEOUT_SECONDS`; assert response aborts and run lease is freed.
5. **`test_thread_retention_prune_skips_active_runs`**
   - **Target:** [`src/neuron_agent/persistence/retention.py#L127-L130`](file:///C:/entomo/AI/neuron/src/neuron_agent/persistence/retention.py#L127-L130)
   - **Scenario:** Thread is older than `thread_retention_days` but has an active run claimed in `RunGuard`; assert `prune_threads()` skips deleting it.
6. **`test_end_to_end_agent_invocation_with_real_langgraph`**
   - **Target:** [`tests/e2e/test_flows.py`](file:///C:/entomo/AI/neuron/tests/e2e/test_flows.py)
   - **Scenario:** Exercise full compiled graph (`create_main_agent`) without `HistoryEchoAgent`, verifying tool execution and structured output parsing end-to-end.
7. **`test_agent_service_unmocked_exception_classification`**
   - **Target:** [`tests/resilience/test_failure_catalog.py`](file:///C:/entomo/AI/neuron/tests/resilience/test_failure_catalog.py)
   - **Scenario:** Pass raw SDK exceptions (`openai.APIConnectionError`, `psycopg.OperationalError`) into an unmocked `AgentService.invoke`, asserting classified `AppError` mapping.
8. **`test_postgres_pool_exhaustion_timeout`**
   - **Target:** [`src/neuron_agent/persistence/checkpointer.py#L170-L245`](file:///C:/entomo/AI/neuron/src/neuron_agent/persistence/checkpointer.py#L170-L245)
   - **Scenario:** Exhaust connection pool and verify that subsequent checkpointer operations raise `PersistenceError` within `postgres_pool_timeout_seconds`.
9. **`test_prepare_approval_failure_refunds_token_budget`**
   - **Target:** [`src/neuron_agent/services/agent_service.py#L509-L517`](file:///C:/entomo/AI/neuron/src/neuron_agent/services/agent_service.py#L509-L517)
   - **Scenario:** Force `_claim` failure during `prepare_approval`; assert that `_token_budget.settle(reservation, 0)` is invoked and the lease is released.
10. **`test_erase_user_data_skips_busy_thread_with_audit`**
    - **Target:** [`src/neuron_agent/services/agent_service.py#L1201-L1238`](file:///C:/entomo/AI/neuron/src/neuron_agent/services/agent_service.py#L1201-L1238)
    - **Scenario:** Lock one thread with an active lease while running `erase_all_user_data`; assert `skipped_busy_count == 1` and `audit` records `busy_threads_skipped`.

---

## 10. Overall Test Suite Maturity Rating

### Maturity Scorecard

```
[ Level 1: Initial ]      Ad-hoc tests, low coverage, high flakiness
[ Level 2: Repeatable ]  Standard unit tests, CI automation, happy-path assertions
[ Level 3: Defined ]     High coverage, security & performance testing, contract tests
  >>> NEURON IS HERE (Level 3.6 / 5.0) <<<
[ Level 4: Managed ]     Mutation-tested, unmocked integration suites, strict type-checked tests
[ Level 5: Optimizing ]  Continuous fault injection, automated property-based testing, chaos suites
```

### Detailed Maturity Breakdown
- **Architecture & Discipline: 4.5 / 5.0**  
  Excellent directory structure, strict linters (Ruff), dependency vulnerability gating (pip-audit, Bandit), and ADR-backed governance.
- **Coverage Quantity: 4.5 / 5.0**  
  91% backend line coverage, 529 frontend unit tests, 30 login theme tests.
- **Assertion Fidelity & Mocking: 2.3 / 5.0**  
  Severe false confidence created by pervasive `HistoryEchoAgent`, `AgentService.invoke` monkeypatching, and docstring string-search tests.
- **Integration & Environment Realism: 2.2 / 5.0**  
  All 135 database integration tests and live LLM evals are skipped in local development environments.
- **Error & Resilience Coverage: 2.8 / 5.0**  
  SSE stream disconnect cleanup, MCP transport size limit crashes, and connection pool exhaustion are untested.

### Final Conclusion
The `neuron` test suite is a disciplined testing baseline. However, **passing tests must not be confused with comprehensive protection**. By remediating the critical blind spots—specifically MCP transport exception handling, stream token extraction edge cases, SSE disconnect lease cleanup, reducing `HistoryEchoAgent` mocking in favor of real LangGraph compilation, and running PostgreSQL integration tests locally—the test suite will evolve from a high-coverage baseline into a truly resilient safety net capable of catching realistic production failures before they reach end users.
