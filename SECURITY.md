# Security

## Threat Model

Primary risks are prompt injection, unsafe tool use, sensitive logging, SSRF, dependency vulnerabilities, and accidental exposure of provider secrets.

## Trust Boundaries

- User input is untrusted.
- Tool output is untrusted.
- Retrieved or external content is untrusted.
- The system prompt is guidance, not an enforcement mechanism.
- Enforcement must happen in code and infrastructure.

## Current Controls

- Typed request validation with Pydantic, including a request body size limit, a rejected-unknown-fields policy, and control-character rejection in user messages.
- Centralized settings and `.env.example`.
- Read-only initial tools.
- AST-based calculator without `eval`.
- Tool allow-list helper and high-impact tool deny list.
- Localhost URL rejection helper.
- Hashed user IDs before entering graph state.
- Conversation thread isolation (ADR 0005):
  - thread IDs are server-minted UUIDv4s, and malformed IDs are rejected;
  - a supplied thread must already exist and belong to the same hashed `user_id`;
  - a missing thread and another user's thread return the same `404 thread_not_found`, so thread IDs can't be probed.

  **Limitation until v0.4.0:** `user_id` comes from the request body and is not authenticated. The guard prevents accidental cross-use, and the unguessable server-minted thread ID is the effective access control.
- Token-bucket rate limiting at `/v1/agent/invoke`, keyed by client IP, returning `429` with `Retry-After` when exceeded (ADR 0004).
- Bounded provider/tool timeouts and capped provider retries (`APP_REQUEST_TIMEOUT_SECONDS`, `APP_TOOL_TIMEOUT_SECONDS`, `APP_PROVIDER_MAX_RETRIES`) and an agent-loop recursion limit (`APP_MAX_AGENT_ITERATIONS`) as resource-exhaustion controls, alongside rate limiting (see `OPERATIONS.md`'s Timeouts and Retries section).
- Structured logging with no deliberate raw secret logging: log fields are limited to IDs, names, stable error codes/types, durations, and retry counts — never raw user prompts, tool arguments, exception text, or provider API keys (see `ARCHITECTURE.md#observability`).
- Bandit security scan in CI.

## Future Mutating Tools

Mutating or high-impact tools require:

- authorization checks outside the model
- human approval if impact is high
- idempotency keys
- retry policy
- audit logs
- tests for unauthorized calls and duplicate execution

## Streaming Output Policy

`POST /v1/agent/stream` (ADR 0005) applies the same controls as `/invoke`: validation, body limit, rate limit, thread ownership. In addition:

- **Tool calls:** `tool_call` events carry the tool's **name only**. Tool arguments and tool results are never streamed; both are untrusted.
- **Tokens:** `token` events carry only the growth of the `answer` field of the structured output. Raw JSON and other fields aren't streamed.
- **Errors:** `error` events use the same visibility rule as HTTP errors: internal failures appear only as `internal_server_error`, never with exception text or stack traces.
- **Resource exhaustion:** runs are bounded by `APP_RUN_TIMEOUT_SECONDS`, `APP_MAX_CONCURRENT_STREAMS` and a send timeout. Disconnected clients' runs are cancelled.

## Conversation Data at Rest

With thread persistence enabled (`APP_CHECKPOINTER=memory` or `postgres`, ADR 0005), checkpoints store user prompts and model answers. Treat them as user data.

- **What is stored.** Per thread:
  - the user turns and final answers (`messages`);
  - per-run fields, including the latest raw `user_message`;
  - the hashed `user_id` of the owner.

  The nested agent's tool calls and tool results aren't checkpointed. LangGraph keeps a checkpoint per step, so earlier versions of the state remain until the thread is deleted.
- **Where.**
  - `memory`: process memory only, gone on restart.
  - `postgres`: the `checkpoints`, `checkpoint_blobs` and `checkpoint_writes` tables.
- **Deletion.** `DELETE /v1/threads/{thread_id}` removes every checkpoint of a thread, for the owner only.
- **Retention.** `make prune-threads` deletes threads inactive for longer than `APP_THREAD_RETENTION_DAYS` (default `30`). Run it on a schedule; Postgres has no built-in TTL.
- **Backups.** Deleted or pruned threads persist in database backups until those backups expire. Align backup retention with `APP_THREAD_RETENTION_DAYS`.
- **Encryption.** Encryption at rest is the database's responsibility (managed-service or disk encryption). LangGraph's `EncryptedSerializer` is available if application-level encryption is required; it isn't enabled by default.
- **Access.** Thread history is exposed only through `GET /v1/threads/{thread_id}/messages`, with the same owner check as conversations. System prompts, tool calls and tool output are never returned. Until v0.4.0, owner identity comes from the unauthenticated `X-User-Id` header, or `user_id` in the body (see Current Controls).

## Secrets

Secrets must come from environment variables or deployment secret stores. `.env` is ignored by git.
