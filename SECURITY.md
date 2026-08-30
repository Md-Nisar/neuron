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

- Typed request validation with Pydantic.
- Centralized settings and `.env.example`.
- Read-only initial tools.
- AST-based calculator without `eval`.
- Tool allow-list helper and high-impact tool deny list.
- Localhost URL rejection helper.
- Hashed user IDs before entering graph state.
- Structured logging with no deliberate raw secret logging.
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
