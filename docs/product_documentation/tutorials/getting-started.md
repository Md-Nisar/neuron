# Tutorial: Getting Started with Neuron Agent

> **Document ID:** DOC-TUT-001  
> **Diátaxis Mode:** Tutorial (Learning-Oriented)  
> **Standard Alignment:** Structured in alignment with ISO/IEC/IEEE 26514:2022 §7.4 (Instructional / Procedural Information) and Diátaxis (Tutorial)  
> **Audience:** Developers and Evaluators new to Neuron Agent  
> **Estimated Completion Time:** 15 minutes  
> **Prerequisites:** Python 3.13+, `uv` 0.11+, `curl`, `jq` (optional: Docker Compose)

---

## 1. Learning Objectives

By completing this tutorial, you will:
1. Initialize the Neuron Agent development environment using `uv`.
2. Start the local FastAPI service using the deterministic local fake model (no external API keys required).
3. Execute a single-turn agent invocation using `POST /v1/agent/invoke`.
4. Continue a multi-turn conversation using the server-generated `thread_id`.
5. Trigger bounded tool execution using the built-in `calculator` tool.
6. Consume real-time streaming tokens via the Server-Sent Events (SSE) protocol on `POST /v1/agent/stream`.
7. Configure a live model provider (NVIDIA API Catalog or OpenAI).

---

## 2. Step 1: Workspace Initialization

Clone the repository and install dependencies using `uv`:

### Unix / macOS (bash / zsh)
```bash
git clone https://github.com/Md-Nisar/neuron.git
cd neuron
uv sync
cp .env.example .env
```

### Windows (PowerShell)
```powershell
git clone https://github.com/Md-Nisar/neuron.git
cd neuron
uv sync
Copy-Item .env.example .env
```

> [!NOTE]
> `.env.example` defaults to `APP_ENV=development` and `APP_AUTH_MODE=none`. In this mode, authentication is disabled on loopback (`127.0.0.1`), allowing immediate local exploration without configuring an identity provider.

---

## 3. Step 2: Start the Development API Server

Start the API service on `127.0.0.1:8000`:

```bash
make api
```
*(Alternative direct command: `uv run uvicorn neuron_agent.api.main:app --host 127.0.0.1 --port 8000 --no-proxy-headers`)*

### Verify Health Endpoints
Open a second terminal window and verify service health:

```bash
curl -s http://127.0.0.1:8000/health/live
# Expected: {"status":"ok"}

curl -s http://127.0.0.1:8000/health/ready
# Expected: {"status":"ready"}
```

---

## 4. Step 3: Execute Your First Agent Request

Send an initial prompt to `POST /v1/agent/invoke`:

```bash
curl -X POST http://127.0.0.1:8000/v1/agent/invoke \
  -H "Content-Type: application/json" \
  -d '{"message": "Hello! What are you?"}'
```

### Expected Response
```json
{
  "status": "completed",
  "request_id": "req-...",
  "thread_id": "019318b2-5f6e-7b3c-8a12-abcdef123456",
  "run_id": "run-...",
  "answer": "I am Neuron Agent, a production-oriented LangChain/LangGraph agent.",
  "used_tools": [],
  "confidence": 1.0,
  "refused": false,
  "clarification_needed": false,
  "citations": null,
  "citation_schema_version": null,
  "grounded": null
}
```

Notice the `thread_id` field in the response. This is a server-minted UUIDv4 that uniquely identifies this conversation thread.

---

## 5. Step 4: Continue a Multi-Turn Conversation

To continue the conversation, supply the `thread_id` returned from the first turn:

```bash
# Save thread ID to an environment variable
THREAD_ID="019318b2-5f6e-7b3c-8a12-abcdef123456"

# Send a follow-up message referencing earlier context
curl -X POST http://127.0.0.1:8000/v1/agent/invoke \
  -H "Content-Type: application/json" \
  -d "{
    \"thread_id\": \"$THREAD_ID\",
    \"message\": \"My favorite programming language is Python. Remember this.\"
  }"
```

Now verify that the agent remembers previous turns in the thread:

```bash
curl -X POST http://127.0.0.1:8000/v1/agent/invoke \
  -H "Content-Type: application/json" \
  -d "{
    \"thread_id\": \"$THREAD_ID\",
    \"message\": \"What is my favorite programming language?\"
  }"
```

The agent loads the thread history from its in-memory checkpointer and answers:
> "Your favorite programming language is Python."

---

## 6. Step 5: Trigger Built-In Tool Execution

Neuron includes two default read-only tools:
- `utc_now`: Returns current UTC time.
- `calculator`: Evaluates bounded mathematical expressions.

Ask a question requiring calculation:

```bash
curl -X POST http://127.0.0.1:8000/v1/agent/invoke \
  -H "Content-Type: application/json" \
  -d '{"message": "Calculate 42 * 1337."}'
```

### Expected Response
```json
{
  "status": "completed",
  "request_id": "req-...",
  "thread_id": "...",
  "run_id": "...",
  "answer": "56154",
  "used_tools": ["calculator"],
  "confidence": 1.0,
  "refused": false,
  "clarification_needed": false
}
```

Observe that `used_tools` contains `["calculator"]`. The calculation was executed in an AST sandbox, bounded by `APP_TOOL_TIMEOUT_SECONDS` (default 20 seconds).

---

## 7. Step 6: Stream Tokens with Server-Sent Events (SSE)

For interactive user experiences, `POST /v1/agent/stream` emits real-time Server-Sent Events.

Send a request using `curl -N` (unbuffered):

```bash
curl -N -X POST http://127.0.0.1:8000/v1/agent/stream \
  -H "Content-Type: application/json" \
  -d '{"message": "Write a short haiku about compilers."}'
```

### Raw SSE Stream Output
```http
event: run_started
data: {"request_id":"req-1","thread_id":"019318b2-...","run_id":"run-1"}

event: token
data: {"text":"Code "}

event: token
data: {"text":"becomes "}

event: token
data: {"text":"machine,\n"}

event: token
data: {"text":"Logic "}

event: token
data: {"text":"flows "}

event: token
data: {"text":"through silicon,\n"}

event: token
data: {"text":"Silent "}

event: token
data: {"text":"speed "}

event: token
data: {"text":"awakes."}

event: final
data: {"status":"completed","request_id":"req-1","thread_id":"019318b2-...","run_id":"run-1","answer":"Code becomes machine,\nLogic flows through silicon,\nSilent speed awakes.","used_tools":[],"confidence":1.0,"refused":false,"clarification_needed":false}

event: done
data: {}
```

### Stream Event Order Guarantee
1. `run_started`: Emitted immediately upon thread claim, providing correlation IDs.
2. `token` (zero or more): Emits incremental text deltas for the `answer` field.
3. `tool_call` (zero or more): Emits the tool name when a tool starts executing.
4. `final` or `error`: Contains the authoritative validated response payload.
5. `done`: Terminal signal closing the stream.

---

## 8. Step 7: Connecting Live LLM Providers

By default, Neuron uses an internal `FakeChatModel` that generates pre-canned answers without external network egress. To connect a live model:

### Option A: NVIDIA API Catalog (Free-tier Development)
1. Obtain an API key from [NVIDIA Build](https://build.nvidia.com).
2. Configure `.env`:
   ```bash
   NVIDIA_API_KEY=nvapi-your-key-here
   APP_DEFAULT_MODEL=nvidia:meta/llama-3.3-70b-instruct
   ```
3. Restart `make api`. Neuron calls NVIDIA's OpenAI-compatible endpoint at `https://integrate.api.nvidia.com/v1`.

### Option B: OpenAI
1. Obtain an API key from [platform.openai.com](https://platform.openai.com).
2. Configure `.env`:
   ```bash
   OPENAI_API_KEY=sk-proj-your-key-here
   APP_DEFAULT_MODEL=openai:gpt-5.4-mini
   ```
3. Restart `make api`.

---

## 9. Step 8: Full-Stack Docker Compose Run

To run the entire ecosystem locally (PostgreSQL + pgvector, Keycloak IAM, FastAPI, Ingestion Worker, and React Web App):

```bash
docker compose up --build
```
*(Or detached: `make up`)*

### Access the Stack
- **Web Chat Application:** [http://localhost:5173](http://localhost:5173)  
  - Sign in as `alice` / password: `dev-only-alice` (full invoke, approval, and knowledge privileges).
  - Sign in as `bob` / password: `dev-only-bob` (read-only thread viewer).
- **Neuron API:** [http://127.0.0.1:8000](http://127.0.0.1:8000)
- **Keycloak IAM:** [http://localhost:8180](http://localhost:8180) (`admin` / `admin-local-only`)

To stop and remove containers:
```bash
make down
# To clean up persisted PostgreSQL volumes:
docker compose down -v
```

---

## 10. Next Steps

Now that you have executed agent runs and inspected the event stream:
- Read [How to Configure Authentication & Scopes](../how-to/authentication-and-authorization.md) for production security.
- Read [How to Set Up PostgreSQL Persistence](../how-to/persistence-and-storage.md) for durable checkpoints and multi-instance concurrency.
- Read [How to Ingest Documents into Knowledge Bases](../how-to/knowledge-engine-rag.md) to explore the RAG subsystem.
- Inspect the [REST API Reference](../reference/rest-api.md) for the full 26-endpoint contract.
