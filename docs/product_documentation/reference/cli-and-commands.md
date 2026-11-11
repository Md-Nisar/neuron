# Reference: Command-Line Interface (CLI) and Makefile Reference

> **Document ID:** DOC-REF-006  
> **Diátaxis Mode:** Reference (Information-Oriented)  
> **Standard Alignment:** Structured in alignment with ISO/IEC/IEEE 26514:2022 §7.3 (Reference Information) and Diátaxis (Reference)  
> **Scope:** CLI commands, console scripts, and Makefile automation targets  
> **Code Traceability:** `pyproject.toml`, `Makefile`, `scripts/`

---

## 1. Installed Console Entrypoints

The following scripts are registered in `pyproject.toml` and installed into the virtual environment by `uv sync`:

### 1.1 `neuron-api`
Launches the FastAPI HTTP and SSE streaming server.

```bash
uv run neuron-api
```
- **Equivalent Command:**
  ```bash
  uv run uvicorn neuron_agent.api.main:app --host 127.0.0.1 --port 8000 --no-proxy-headers
  ```
- **Options:** Controlled via `APP_HOST`, `APP_PORT`, and `APP_LOG_LEVEL`.

---

### 1.2 `neuron-worker`
Runs the background ingestion and maintenance task worker.

```bash
uv run neuron-worker [COMMAND]
```

#### Commands
| Command | Description | Exit Codes |
| :--- | :--- | :--- |
| `run` *(default)* | Starts the Procrastinate distributed task consumer. Processes ingestion, purges, sweeps, and drains tasks cleanly on SIGTERM. | 0 on clean exit |
| `health` | Checks whether the worker's internal health heartbeat file is fresh (<60s old). Used by Docker container health checks. | 0: healthy<br>1: unhealthy |
| `check-blobs` | Audits consistency between database document rows and blob storage files. Outputs JSON report. | 0: consistent<br>1: missing blobs |

---

### 1.3 `neuron-mcp-pin`
Connects to a remote Streamable HTTP MCP server, reads tool schemas, and generates cryptographic SHA-256 pins.

```bash
uv run neuron-mcp-pin <SERVER_URL> --name <SERVER_NAME> [OPTIONS]
```

#### Arguments & Options
- `SERVER_URL` (positional, required): HTTP/HTTPS URL of the MCP server.
- `--name` (string, optional, default: `"server"`): Short identifier for the server entry.
- `--token-file` (path, optional): Path to file holding bearer token (avoids leaking credentials in process tables).
- `--env` (choice, default: `"development"`): Applies URL rules for target environment (`development`, `test`, `staging`, `production`).
- `--timeout` (float, default: `20.0`): Seconds to wait for server response.

---

### 1.4 `neuron-eval`
Executes agent benchmark evaluations and quality regression tests against configured suites.

```bash
uv run neuron-eval [OPTIONS]
# Or compare two evaluation runs:
uv run neuron-eval compare <REPORT_A.json> <REPORT_B.json>
```

#### Options
- `--trials` (int, default: `1`): Number of runs per evaluation test case.
- `--suite` (repeatable): Specific suite name to execute.
- `--category` (repeatable): Filter evaluation cases by specific category tag.
- `--output` (path): Path to write the structured evaluation JSON report.
- `--max-requests-per-minute` (int, default: `60`): Throttle model provider requests across the evaluation run (0 disables).

---

### 1.5 Persistence Management CLI
Direct database maintenance commands (`neuron_agent.persistence.cli`):

```bash
uv run python -m neuron_agent.persistence.cli [COMMAND] [OPTIONS]
```

| Command | Options | Description |
| :--- | :--- | :--- |
| `setup` | `[--rotate-identity-key]` | Applies all pending migrations up to version 27 and configures database roles. Requires `APP_POSTGRES_MIGRATION_DSN`. `--rotate-identity-key` replaces the stored identity key check value (orphaning existing threads). |
| `prune` | `[--older-than-days N]` | Deletes inactive threads older than `N` days (defaults to `APP_THREAD_RETENTION_DAYS`). Requires `APP_POSTGRES_DSN`. |

---

## 2. Makefile Target Reference

Neuron uses a top-level `Makefile` to standardize development, quality gates, and deployment workflows:

### 2.1 Quality Gates & Verification
| Target | Command | Purpose |
| :--- | :--- | :--- |
| `make format` | `uv run ruff format src tests loadtest` | Formats all Python code. |
| `make lint` | `uv run ruff check src tests loadtest` | Checks lint rules and import ordering. |
| `make typecheck`| `uv run mypy src loadtest ...` | Enforces strict static type checking. |
| `make test` | `uv run pytest tests/unit ...` | Runs all deterministic unit, graph, security, resilience, and e2e tests. |
| `make test-unit` | `uv run pytest tests/unit` | Runs fast isolated unit tests. |
| `make test-security`| `uv run pytest tests/security` | Runs security isolation, RLS, and auth tests. |
| `make test-resilience`| `uv run pytest tests/resilience` | Runs fault injection and timeout tests. |
| `make test-integration`| `uv run pytest tests/integration -m integration` | Runs tests requiring live database or model credentials. |
| `make security` | Bandit + pip-audit scans | Audits code for AST security vulnerabilities and dependency CVEs. |

---

### 2.2 Local Development & Services
| Target | Command | Purpose |
| :--- | :--- | :--- |
| `make dev` | `uv sync` | Installs all core and development dependencies. |
| `make api` | Runs Uvicorn API server | Starts `neuron-api` on `127.0.0.1:8000`. |
| `make up` | `docker compose up --build -d` | Starts the full local Docker Compose stack (API, Keycloak, Postgres, Worker, Web). |
| `make down` | `docker compose down` | Stops the local Docker Compose stack. |
| `make db-setup` | `persistence.cli setup` | Runs database migrations. |
| `make prune-threads`| `persistence.cli prune` | Prunes expired threads. |

---

### 2.3 Local Development Authentication Tools
| Target | Command | Purpose |
| :--- | :--- | :--- |
| `make dev-auth` | `scripts/dev_token.py setup` | Generates local RSA signing key in `.dev/`. |
| `make dev-jwks` | `scripts/dev_token.py serve` | Serves local JWKS server on `127.0.0.1:8765`. |
| `make dev-token`| `scripts/dev_token.py` | Mints a 1-hour signed test JWT token with full scopes. |
| `make dev-keycloak`| `scripts/dev_keycloak.py` | Prints environment variables for Docker Compose Keycloak realm. |

---

### 2.4 Web Frontend Development
| Target | Command | Purpose |
| :--- | :--- | :--- |
| `make web-install` | `cd web && npm install` | Installs frontend npm packages. |
| `make web-dev` | `cd web && npm run dev` | Starts Vite development server on `http://localhost:5173`. |
| `make web-lint` | `cd web && npm run lint` | Runs ESLint on frontend code. |
| `make web-test` | `cd web && npm test` | Runs Vitest unit and accessibility tests. |
| `make web-build` | `cd web && npm run build` | Compiles production assets into `web/dist/`. |
| `make web-audit` | `cd web && npm audit` | Audits npm dependencies for known vulnerabilities. |
