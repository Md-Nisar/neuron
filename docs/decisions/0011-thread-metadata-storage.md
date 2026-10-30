# ADR 0011: Thread metadata storage (v0.8.0)

## Status

Accepted (2026-10-28, owner approval of the recommendation). Answers ADR 0010 open question 3
and is the ADR CLAUDE.md requires before any custom persistence.

## Context

The web app needs two kinds of per-user data the checkpointer does not hold: a
conversation title (#277) and an answer rating (#285). ADR 0010 preferred "a column in the
existing thread-ownership table", but no such table exists: a thread's owner is the `owner`
key in checkpoint metadata, and `GET /v1/me/threads` is an aggregate over `checkpoints`
(`persistence/thread_index.py`). The alternative named in ADR 0010 is the LangGraph store
that memories use.

## Decision

1. **Two small tables, created by versioned migrations (ADR 0008 decision 7).**
   - `neuron_thread_meta(owner_key, thread_id, title, updated_at)`, primary key
     `(owner_key, thread_id)`.
   - `neuron_feedback(owner_key, thread_id, run_id, score, reason, created_at)`, primary key
     `(owner_key, run_id)`. An upsert on that key makes a rating idempotent per owner and
     run in the database, not in application code. The stored `thread_id` lets the route
     refuse a `run_id` that does not belong to the thread the caller owns.
2. **Why not the LangGraph store.** The thread list must return titles, which with the store
   is one lookup per thread; a join on the owner index is one query. The store has no unique
   constraint and no query by field, so "once per (owner, run)" would be application logic
   with a race.
3. **Keys and content.** Rows carry the HMAC owner key, never the subject. A title is
   content derived from user text: it is covered by thread delete, erase, export and
   retention pruning, and never appears in logs, spans or metrics. Feedback holds a score
   and a fixed reason enum, no free text.
4. **App role.** `SELECT, INSERT, UPDATE, DELETE` on both tables (decision 15 grant list).
5. **No Postgres in dev and tests.** An in-memory implementation behind the same interface
   serves `APP_CHECKPOINTER=memory`; the Postgres one is exercised by the existing
   integration path.
6. **Order.** Titles first (#277), then feedback (#285, #289). Each is its own migration and
   PR, additive (expand only), so the previous release keeps working.

## Consequences

- Two new tables and one interface to keep in step with every deletion path. A test per
  path (thread delete, erase, export, retention) is part of the titles issue.
- Cross-thread queries ("all rated answers") stay possible later without a new store.

## Alternatives considered

- **LangGraph store.** Rejected above.
- **Title in checkpoint state.** Needs a `MainGraphState` change and the `add-graph-node`
  checklist, cannot be renamed without a graph write, and is invisible to the list query.
- **Client-side titles.** Not shared across devices; rejected by the owner (ADR 0010 status).
