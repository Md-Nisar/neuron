# Changelog

## 0.2.0

"Reliable Agent Runtime" — predictable failures, bounded execution, and operational visibility.

- Runtime error taxonomy: `AppError` subclasses with stable codes, HTTP mapping, retryability, and visibility metadata (#1).
- Enforced runtime limits: request/tool timeouts, agent iteration cap, prompt/body size limits (#2).
- Bounded provider retry with exponential backoff and jitter for transient model-provider failures (#3).
- Hardened tool execution boundaries: per-call timeout and failure isolation so a tool bug can never crash the agent loop (#4).
- Hardened request validation: body size limits, rejected-unknown-fields policy, control-character rejection (#5).
- Application-level token-bucket rate limiting at `/v1/agent/invoke`, keyed by client IP, with `429`/`Retry-After` (#6, ADR 0004).
- Expanded failure-and-resilience regression test suite covering every classified failure mode (#7).
- Agent evaluation dataset v1 with deterministic shape checks and live agent-quality scoring (#8).
- Structured logging and error telemetry: correlation IDs (`request_id`/`thread_id`/`run_id`) propagated via `structlog` contextvars and the LangSmith trace, plus `model`, `error_type`, `duration_ms`, and `retry_count` on key log events (#9).
- Documented reliability behavior and operations: timeout/retry/rate-limit configuration, the full failure-response taxonomy, production configuration expectations, and local troubleshooting across `README.md`, `OPERATIONS.md`, `DEVELOPMENT.md`, `SECURITY.md`, `ARCHITECTURE.md`, and ADR 0003 (#10).
- Fixed a defect found during release verification: the documented no-credentials fallback (a fake local chat model) crashed every `/v1/agent/invoke` call, because `create_agent` always binds tools and the fake model didn't support it (#11).

## 0.1.0

- Initial production-oriented LangChain/LangGraph agent service baseline.
