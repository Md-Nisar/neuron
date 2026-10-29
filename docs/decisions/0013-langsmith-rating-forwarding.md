# ADR 0013: Forwarding answer ratings to LangSmith (proposed, after v1.0.0)

## Status

**Proposed. Not accepted and not implemented.** The owner deferred #285 until after v1.0.0
(`docs/ROADMAP.md`), and the release freeze (ADR 0012 decision 11) starts at the v0.9.0 tag. This
file records what a local check found, so the decision can be made later with the facts. It
changes no code.

## Context

Ratings (`POST /v1/threads/{id}/runs/{run_id}/feedback`, ADR 0010 decision 6) are stored in
`neuron_feedback` and reported as a log event, a span and a counter. #285 asks for them to reach
LangSmith too, "only when enabled". The v0.8.0 notes say this "needs a LangSmith run ID the
service does not keep". A local check (`docs/releases/v0.9.0-gate/langsmith-stub/`) against a stub
endpoint, with `langsmith` 0.14.13, shows otherwise:

- `AgentService` generates the run ID and passes it as `config["run_id"]`
  (`models/factory.py`, `agent_invocation_config`). With tracing on, the root run LangSmith
  receives carries **that same ID**. A rating's `run_id` is therefore already the LangSmith run
  ID, and no new column, table or migration is needed.
- `Client.create_feedback(run_id, key=..., score=...)` posts to `/feedback` with that ID.
- It also warns: "Creating feedback for a run without session_id is deprecated and will stop
  working in a future release". A forwarder must pass the tracing project's ID (`session_id`),
  which means reading the project once (by `LANGSMITH_PROJECT`, default `default`) and caching it.
- What the stub cannot show: how a real LangSmith workspace treats the feedback (the project
  lookup, retention, quotas, a rating that arrives after the trace was sampled out or expired).

## Proposed decision (for the owner, after v1.0.0)

1. Forward only when `APP_ENABLE_LANGSMITH=true`, in addition to storing the rating. The stored
   rating stays the source of truth: forwarding failure never fails or slows the `POST`.
2. Send the score (as `user_score`: 1 or 0, or -1 and 1) and the fixed reason enum as `value` or
   `extra`. Never a comment, the thread ID, the owner key, a subject or any content.
3. Forward once per new rating (the route already stores once per (owner, run), so a repeat sends
   nothing), from a background task with a short timeout and one log event on failure.
4. Content approval: ratings carry no content, so `APP_LANGSMITH_CONTENT_APPROVED` does not
   gate them, but production still needs `LANGSMITH_API_KEY`, as for tracing.
5. Tests: a stub endpoint (as in the check) proving the payload has the run ID, score and reason
   only; failure and timeout paths; no call when LangSmith is disabled; the leak scan.

## Open questions

1. Is the cost of the project lookup acceptable, or should `LANGSMITH_PROJECT_ID` be a setting?
2. Should a rating that arrives after the trace expired be dropped silently?
3. After the freeze this is a feature, not a fix: it needs an owner exception or waits for v1.1.

## Alternatives considered

- **Store a separate LangSmith run ID.** Unnecessary, per the check above.
- **Forward from the browser.** Would put a LangSmith key in the web app; rejected.
- **Do nothing.** Ratings stay in Postgres and telemetry; LangSmith gets traces only.
