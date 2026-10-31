# Pass 4: Architecture, Resilience and Observability

Evaluate how the code behaves when its dependencies misbehave, how it will be debugged at 3 a.m.,
and whether it keeps its promises to callers. Architecture findings must cite a **concrete
cost** (a bug it causes, a change it makes hard, a failure it hides). Taste alone is not a finding.

## 1. Boundaries and Design
- **Leaky abstractions:** ORM entities returned directly from APIs (couples schema to contract,
  risks lazy-load exceptions and field exposure); HTTP request/response objects inside domain or
  repository layers; SQL in controllers.
- **Layering and dependency direction:** domain depending on infrastructure; circular
  dependencies between modules.
- **Duplication of existing capability:** new helpers re-implementing an existing utility,
  client, or policy check in the repo (search for it). Duplicates drift apart and one copy
  stays unpatched.
- **Responsibility sprawl:** one class or function mixing validation, persistence, external
  calls, and formatting, which makes the error paths hard to reason about.

## 2. Contract Integrity
- Breaking changes to public APIs (REST/gRPC/GraphQL), library signatures, or event/message
  schemas: removed or renamed fields, type changes, new required fields, changed semantics or
  units, nullability changes, new enum values that strict consumers reject.
- Response shape or status code changes that clients depend on; pagination behavior changes.
- Missing versioning or compatibility path (expand/contract, tolerant readers, defaults).
- **Verify:** find at least one consumer (upstream caller, client SDK, event subscriber) that the
  change breaks, or state that consumers are external and unknown.

## 3. Fault Tolerance
- Outbound calls (HTTP, gRPC, DB, cache, queue, cloud SDK) without explicit **connect and read
  timeouts** or an overall deadline. Many default clients wait forever (Go `http.DefaultClient`,
  Python `requests` without `timeout=`, default `RestTemplate`, `fetch`).
- Retries that are unbounded, immediate (no exponential backoff + jitter), applied to
  non-idempotent operations, or layered (client, SDK, and mesh all retrying, which multiplies load).
- No circuit breaker or bulkhead on a dependency that can take the whole service down when slow.
- No fallback or graceful degradation where a non-critical dependency fails (recommendations
  failing should not fail checkout).
- **Idempotency:** webhook handlers, queue consumers, and retryable endpoints that duplicate side
  effects on redelivery. Look for idempotency keys, dedup tables, or natural idempotency.
- Messaging: no dead-letter queue, poison messages blocking a partition forever, at-least-once
  delivery assumed to be exactly-once, ordering assumed where the broker does not guarantee it.
- Lifecycle: no graceful shutdown (in-flight requests or jobs killed mid-write); liveness probes
  that depend on downstream services (cascading restarts); startup that crashes on a transient
  dependency outage.

## 4. Error Handling
- Swallowed exceptions (`catch (e) {}`, `except: pass`, `_ = err`), or catch-all blocks that log
  and continue as if successful.
- Root cause lost: rethrowing without the original exception as `cause`, or replacing it with a
  generic message.
- Catch blocks that break caller recovery (converting retryable errors into non-retryable ones,
  or the reverse).
- Error responses that are inconsistent with the API's error contract.

## 5. Observability
- Critical failure paths with no log, metric, or trace, so the failure is invisible.
- Error logs missing structured context: correlation/trace ID, tenant or entity IDs, operation
  name. (Context IDs yes; PII and secrets no.)
- Wrong log levels: expected conditions at ERROR (alert fatigue), real failures at DEBUG.
- **Metric cardinality explosion:** user IDs, emails, URLs, or raw paths used as metric labels.
- Trace context not propagated across async boundaries, queues, or thread pools.
- Security-relevant actions (permission changes, exports, admin actions, login failures) with no
  audit log.

## 6. Configuration
- Environment-specific values hardcoded (URLs, bucket names, limits).
- Config not validated at startup, so typos fail at first use in production.
- Feature-flag defaults that are unsafe when the flag service is unreachable.

## Common False Positives in This Pass
- Timeouts configured centrally (client factory, service mesh, SDK config); check before flagging.
- Retries and breakers provided by a resilience library or sidecar on this path.
- Entities returned from APIs in an internal admin tool where that is an explicit project choice
  (still mention field exposure if relevant).
- Pure style preferences about layering in small codebases with no concrete cost.
