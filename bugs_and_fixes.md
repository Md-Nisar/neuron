# Bugs and Fixes Log

This document records all bugs, architectural bottlenecks, cross-platform issues, and runtime failures identified and resolved across the three testing cycles of the Neuron Knowledge (RAG) system audit.

---

## Summary of Defects

| Defect ID | Category | Severity | Component | Status |
| :--- | :--- | :--- | :--- | :--- |
| **BUG-01** | Test Infrastructure | High | Pytest / `pyproject.toml` | **Resolved** |
| **BUG-02** | Platform Compatibility | High | Windows / `loadtest/knowledge.py` | **Resolved** |
| **BUG-03** | Platform Compatibility | Medium | Windows / `tests/unit/test_web_headers.py` | **Resolved** |
| **BUG-04** | Configuration & State | High | `tests/e2e/conftest.py` & `web/playwright.config.ts` | **Resolved** |
| **BUG-05** | Environment & Ports | Medium | Local Vite Dev Server | **Resolved** |
| **BUG-06** | Build & Deployment | High | `Dockerfile` | **Resolved** |
| **BUG-07** | Networking & Performance | Medium | Windows IPv6 Loopback / `scripts/dev_keycloak.py` | **Resolved** |
| **BUG-08** | Limits & Token Budget | High | `docker-compose.yml` (`APP_USER_TOKEN_BUDGET`) | **Resolved** |
| **BUG-09** | Browser Test Automation | Low | `web/e2e/live_stack.spec.ts` | **Resolved** |
| **BUG-10** | Schema & E2E Validation | Low | `web/e2e/live_stack.spec.ts` | **Resolved** |

---

## Detailed Root Cause Analysis & Resolutions

### BUG-01: Pytest Test Collection ModuleNotFoundError
- **Symptom:** Running `uv run python -m pytest tests/unit` resulted in collection errors: `ModuleNotFoundError: No module named 'tests'` and `cannot import name 'scripts'`.
- **Root Cause:** In modern `pytest 8+`, imports outside the standard installed package root require explicit `pythonpath` declarations in `[tool.pytest.ini_options]` in `pyproject.toml`.
- **Fix:** Added `pythonpath = ["src", "."]` to `pyproject.toml`.
- **Verification:** All 1,753 unit tests collected and executed cleanly without import errors.

### BUG-02: POSIX-Only `os.sysconf` Usage in `loadtest/knowledge.py`
- **Symptom:** Strict Mypy typechecking failed on Windows with:
  ```
  loadtest\knowledge.py:127: error: Module has no attribute "sysconf"  [attr-defined]
  loadtest\knowledge.py:133: error: Returning Any from function declared to return "int | None"  [no-any-return]
  ```
- **Root Cause:** `os.sysconf` is a POSIX-only operating system call unavailable in Windows Python runtimes.
- **Fix:** Refactored `_memory_gb()` in `loadtest/knowledge.py`:
  ```python
  def _memory_gb() -> int | None:
      sysconf = getattr(os, "sysconf", None)
      if callable(sysconf):
          try:
              pages = int(sysconf("SC_PHYS_PAGES"))
              page_size = int(sysconf("SC_PAGE_SIZE"))
              return (pages * page_size) // (1024**3)
          except (OSError, ValueError):
              pass
      return None
  ```
- **Verification:** `uv run python -m mypy ...` passed with zero issues across all 122 source and script files.

### BUG-03: WinError 1314 Symlink Privilege and Missing `make` Utility
- **Symptom:** `tests/unit/test_web_headers.py:234` failed on Windows with `OSError: [WinError 1314] A required privilege is not held by the client` and `FileNotFoundError: 'make'`.
- **Root Cause:** Windows non-Developer Mode environments require elevated administrative privileges to create symbolic links via `Path.symlink_to`. Additionally, `make` is not a native Windows binary.
- **Fix:** In `_hosted_build()` in `tests/unit/test_web_headers.py`:
  1. Checked `shutil.which("make")` and cleanly skipped the test with `pytest.skip("make is not available on this platform")`.
  2. Wrapped `symlink_to` in a `try...except OSError:` block falling back to `shutil.copytree()`.
- **Verification:** Unit test suite passed cleanly with 1,749 passed and 4 skipped.

### BUG-04: Settings Validation Error in In-Memory Test Environments
- **Symptom:** Initializing `AgentService` in E2E tests triggered `pydantic_core.ValidationError: APP_KNOWLEDGE_ENABLED needs APP_CHECKPOINTER=postgres`.
- **Root Cause:** The project's settings model enforces that Knowledge/RAG features can only be enabled when PostgreSQL checkpointer is active (`APP_CHECKPOINTER="postgres"`). When `.env` contains `APP_KNOWLEDGE_ENABLED=true`, any test fixture attempting to run in-memory crashed on settings initialization.
- **Fix:** Explicitly set `"APP_KNOWLEDGE_ENABLED": "false"` in the mock environment dictionary in `tests/e2e/conftest.py` and `web/playwright.config.ts`.
- **Verification:** Both in-memory E2E tests and live PostgreSQL integration tests run cleanly without schema/validation conflict.

### BUG-05: Port 5173 Collision from Orphan Vite Process
- **Symptom:** Starting `docker compose up` or local web server failed because port 5173 was in use.
- **Root Cause:** An orphan Vite process (PID 18324) remained running from a previous terminal session.
- **Fix:** Identified the process via `netstat -ano | findstr :5173` and terminated it using `Stop-Process -Id 18324 -Force`.
- **Verification:** Port 5173 freed; `neuron-web-1` container bound to `127.0.0.1:5173->8080/tcp` without conflict.

### BUG-06: UV Network Timeout during Multi-Stage Docker Build
- **Symptom:** Building `neuron:local` image via Docker failed with:
  ```
  Failed to download distribution due to network timeout. Try increasing UV_HTTP_TIMEOUT (current value: 30s)
  ```
- **Root Cause:** Complex C-extension packages and dependencies exceeded the default 30-second download window on high-latency connections.
- **Fix:** Added `ENV UV_HTTP_TIMEOUT=120` to `Dockerfile`.
- **Verification:** `docker compose build` completed cleanly; all container images generated and tagged.

### BUG-07: Windows IPv6 Loopback Latency on Keycloak Calls
- **Symptom:** Requests to `http://localhost:8180` in Python tests took ~12 seconds each to establish a connection.
- **Root Cause:** On Windows, `localhost` resolves to IPv6 address `::1` first. Docker on Windows binds ports to IPv4 `127.0.0.1` only by default. Windows `urllib` attempted to connect to `[::1]:8180` and waited for the operating system connection timeout before falling back to IPv4.
- **Fix:** Configured test suites and connection endpoints to use IPv4 literal `http://127.0.0.1:8180` directly.
- **Verification:** Token retrieval latency dropped from 12.1 seconds to 0.171 seconds.

### BUG-08: Token Budget Exhaustion During Repeated E2E Runs
- **Symptom:** Agent chat turns in Playwright tests were rejected with HTTP 429 and error message: `Too many requests. Try again in 2955 seconds.`.
- **Root Cause:** `docker-compose.yml` did not set `APP_USER_TOKEN_BUDGET`, defaulting to the production limit of 100,000 tokens per hour. Successive automated test runs exhausted Alice's hourly budget.
- **Fix:** Added `APP_USER_TOKEN_BUDGET: "10000000"` to `x-api-env` in `docker-compose.yml` (matching `playwright.config.ts:49`), and restarted the API container.
- **Verification:** Subsequent chat turns and RAG queries succeeded without rate-limiting interruptions.

### BUG-09: Playwright Strict Mode Locator Ambiguity on Keycloak Login Form
- **Symptom:** `web/e2e/live_stack.spec.ts` failed with:
  ```
  Error: strict mode violation: getByText(/Invalid username or password/i) resolved to 2 elements:
    1) <span id="input-error-username">Invalid username or password.</span>
    2) <span id="input-error-password">Invalid username or password.</span>
  ```
- **Root Cause:** Keycloak's login template renders an identical error message for both the username field and password field for accessibility compliance.
- **Fix:** Targeted the specific input error element `#input-error-password` directly.
- **Verification:** Test passed in 6.6 seconds.

### BUG-10: Schema Field Mismatch in Data Export Assertion
- **Symptom:** Test 4 asserted `expect(Array.isArray(data.conversations)).toBe(true)` and failed because `data.conversations` was undefined.
- **Root Cause:** The API schema `UserDataExportResponse` defines the conversation list as `threads` (not `conversations`), alongside `memories` and `knowledge_bases`.
- **Fix:** Updated test assertions to check `data.threads`, `data.memories`, and `data.knowledge_bases`.
- **Verification:** GDPR export verified successfully with all three structured data arrays.
