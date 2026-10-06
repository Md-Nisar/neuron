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

## Secrets

Secrets must come from environment variables or deployment secret stores. `.env` is ignored by git.
