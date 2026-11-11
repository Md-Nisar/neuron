# Concurrency and lifecycle review, November 2026

Reviewed at `c726975` (main after the security audit fixes, issue #525). Nothing here repeats a finding in `audit/security/FINDINGS-NOV-2026.json`. Render is out of scope.

## Scope and method

Code read end to end, not sampled:

- Run leases and the thread-busy check: `security/run_guard.py`, `persistence/run_guard.py`, `persistence/guards.py`, `services/agent_service.py`.
- Token budget and rate limiter, in memory and on Postgres: `security/usage_budget.py`, `persistence/token_budget.py`, `security/rate_limiter.py`, `persistence/rate_limiter.py`.
- Streaming, cancellation and timeouts: `services/agent_service.py` (`stream`, `_produce`, `_execute`, `_cancel`), `services/streaming.py`, the stream route and `_CleanupEventSourceResponse` in `api/main.py`.
- Shutdown: `begin_drain`, `_DrainingServer`, the lifespan, the worker's `run`.
- Knowledge worker and scheduler: `knowledge/worker.py`, `jobs.py`, `ingest.py`, `reconcile.py`, `purge.py`, the upload, delete and erase paths of `knowledge/service.py`, and Procrastinate 3.10.0's `retry.py`, `periodic.py` and SQL.
- Retention: `persistence/retention.py`, `persistence/cli.py`.

For each area I wrote the invariant first, then looked for an interleaving that breaks it. A candidate became a finding only once a deterministic test failed on main: the test forces the interleaving with a hook at the exact overlap point, or pins the clock. Candidates I could not show are under "Open questions", not in the table.

Environment: the local compose stack, plus a `pgvector/pgvector:pg16` container for the `-m postgres` suite.

## Findings

| ID | Severity | Title | Where | Status |
| --- | --- | --- | --- | --- |
| C-01 | Medium | The retention job deletes a thread that became active after it was listed as stale | `persistence/retention.py:127-152` | Fix PR, see the tracking issue |
| C-02 | Low | The queue retries an ingest once more after the worker has recorded it as failed | `knowledge/worker.py:63-64`, `:135` | Fix PR, see the tracking issue |
| C-03 | Low | A run that checked its thread before a delete recreates the deleted thread | `services/agent_service.py:296-322` | Fix PR, see the tracking issue |
| C-04 | Low | `invoke` stores a new thread's title after releasing its lease, so an erase can report complete and leave the title | `services/agent_service.py:640-664` | Fix PR, see the tracking issue |
| C-05 | Low (test) | `test_the_worker_schedules_one_reconcile_run_per_tick_and_runs_it` fails between hh:23 and hh:33 UTC | `tests/integration/test_postgres_knowledge_reconcile.py:146-165` | Fix PR, see the tracking issue |

Severity reasons, one line each:

- C-01 Medium: silent loss of a user's newest turns and the whole thread, with no error anywhere; narrow window, but it grows with the number of stale threads in a run.
- C-02 Low: a document reported `failed` goes back to `parsing` about 52 minutes later and is embedded (and paid for) once more; no data is lost.
- C-03 Low: only the caller's own data, and only when they delete a thread and send to it at the same moment; the delete still returned `204`.
- C-04 Low: personal data (the first message's opening words) can outlive an erasure that reported nothing skipped; the window is a few milliseconds.
- C-05 Low: CI noise only; production behaviour is correct.

### C-01 The retention job deletes a thread that became active after it was listed

**Invariant.** Retention deletes only threads with no activity since the cutoff.

**Scenario.** `prune_threads` lists every stale thread first, then walks the list. For each thread it checks `is_thread_active`, takes a hold and deletes. It never looks at the thread's activity again. A user returns to a 31-day-old thread while the job is working through the list: their run claims the thread, finishes and releases its lease before the job reaches that entry. The job then finds the thread free, holds it and deletes it, new turn included. The next request on the thread is a `404`. The window is the time from the listing to that thread's turn in the loop, so the first run after retention is enabled on a large table has the widest one.

The hold does not help here: it stops a run that starts during the delete, not one that already finished. Without a shared run guard (`APP_LIMITS_BACKEND=memory`, where the CLI is a separate process and passes `run_guard=None`) the job does not even see a run in flight.

**Evidence.** `persistence/retention.py:113-125` builds `stale`; `:128-146` deletes each entry after `is_thread_active` and `hold_thread` only. Reproduced on main: a test hooks the job's own `hold_thread` to run one turn first; `prune_threads` returned `1` and the thread, with the new turn, was gone (`assert 1 == 0`).

**Fix.** Under the hold, read the thread's latest root checkpoint again and skip the thread if its `ts` is at or after the cutoff. Do the same re-read in the no-guard branch, where it narrows the window from the whole loop to one statement (it cannot close it without a shared guard).

**Test.** `test_prune_keeps_a_thread_that_got_a_turn_after_it_was_listed`: fails on main, passes with the fix.

### C-02 The queue retries an ingest after the worker recorded it as failed

**Invariant.** `failed` is a terminal document status, and a job runs at most `MAX_ATTEMPTS` (5) times, as OPERATIONS.md says.

**Scenario.** The worker treats the run with `job.attempts + 1 >= MAX_ATTEMPTS` as the last: on run 5 (`attempts == 4`) it sets the document `failed` and raises. Procrastinate's `RetryStrategy(max_attempts=5)` retries while `job.attempts < 5`, and `attempts` is 0 on the first run, so it schedules a sixth run, 5^5 = 3125 s later. That run's `_start` sets any live document to `parsing`, so the `failed` document a client has stopped polling re-enters ingestion, is embedded again (hosted embedding spend is charged again, as is the user's ingesting quota slot), and ends `ready` or `failed` a second time. Purge jobs share the strategy and also get six runs. The stalled-job sweep (`worker.py:265`) already counts five, so the three places disagree.

**Evidence.** `knowledge/worker.py:63-64` (`RETRY`), `:135` (`last_attempt`); Procrastinate `retry.py:197` (`if self.max_attempts and job.attempts >= self.max_attempts: return None`). Printed on main for each run: run 5 gives `last_attempt=True` and a retry decision 3125 s ahead; run 6 gives none.

**Fix.** `RetryStrategy(max_attempts=MAX_ATTEMPTS - 1, ...)`, so the strategy stops at the run the worker treats as last.

**Test.** For every `attempts` from 0 to `MAX_ATTEMPTS`, the strategy retries exactly when the worker does not treat the run as its last. Fails on main at `attempts == 4`.

### C-03 A run that checked its thread before a delete recreates it

**Invariant.** After `DELETE /v1/threads/{id}` returns `204`, or an erase reports the thread erased, the thread does not exist.

**Scenario.** `prepare` checks ownership (`_resolve_thread`), then claims the lease. A delete of the same thread can run entirely between the two: it holds the thread, deletes every checkpoint, forgets the title and ratings, and releases. The run's claim then succeeds, the graph runs on the empty thread and writes fresh checkpoints with the owner's metadata. The deleted thread is back in the list with only the new turn and no title. The comment at `agent_service.py:1339-1340` says the hold prevents a run "starting mid-delete"; it does for the claim, not for the ownership check before it. The same holds across replicas with the Postgres guard.

**Evidence.** `services/agent_service.py:296-305` (resolve, then claim); the post-claim re-read at `:314-322` looks only at interrupts and only when a gated tool exists. Reproduced on main with a hook that runs the delete inside the claim: the run completed (`DID NOT RAISE ThreadNotFoundError`).

**Fix.** After the claim, for a caller-supplied thread with persistence on, read the owned snapshot again (this replaces the interrupt-only read, so a service with gated tools pays no extra query). A thread that is gone is the same `404`; the lease and the reservation are given back.

**Test.** `test_a_run_that_resolved_its_thread_before_a_delete_does_not_recreate_it`.

### C-04 `invoke` stores a new thread's title after releasing its lease

**Invariant.** An erase that reports `skipped_busy_count == 0` leaves none of the caller's thread content behind.

**Scenario.** `_execute` releases the lease in its `finally` and only then calls `_name_new_thread`. The title is derived from the first message. An erase that runs between the release and the title write sees the thread free, deletes it, deletes the owner's titles and reports a complete erasure; the title row is written afterwards and stays, attached to no thread. The streaming path is already correct: `_produce` stores the title before the lease goes (`agent_service.py:789-790`, `:801-802`).

**Evidence.** `services/agent_service.py:652-664`. Reproduced on main with a hook on the title write that runs the erase first: the erase reported `erased_count=1, skipped_busy_count=0` and the title was then stored.

**Fix.** Store the title (and emit `thread_created`) before the lease is released, as the stream does.

**Test.** `test_an_erase_never_completes_between_a_runs_lease_and_its_title`.

### C-05 The periodic-deferrer test fails between hh:23 and hh:33 UTC

**Verdict: a test bug, not a scheduler bug.**

**Why it fails.** The test builds a `PeriodicDeferrer(max_delay=600)` over the app's whole periodic registry and asks it what is due at `time.time()`. On a fresh deferrer, Procrastinate defers each task's previous cron tick if it is at most `max_delay` old. `reconcile_knowledge` (`*/10 * * * *`) always has a tick within 600 s. `sweep_knowledge_blobs` (`23 * * * *`) has one only from hh:23:00 to hh:33:00. In that window two jobs are queued and `[(task, args)] = await _jobs(db)` raises `ValueError: too many values to unpack`. Reproduced by pinning the test's clock: passes at hh:05, fails at hh:25.

**Why the scheduler is right.** Catching up a tick missed in the last ten minutes is what should happen when a worker restarts at hh:25: the hourly sweep still runs that hour. It runs once however many workers start, because `procrastinate_periodic_defers` is unique per task and tick; the test's own two-deferrer loop shows that. Nothing in `worker.py` assumes only one periodic task is due.

**Fix.** Pass a fixed `at` (hh:05) instead of the wall clock, and add a second case at hh:25 asserting that both tasks are queued exactly once by two deferrers, so the catch-up is covered instead of being hit by accident.

## Checked and found sound

Nobody needs to re-check these unless the code changes.

**Run leases**
- A lease is always released or expires. `RunLease.release` is idempotent and shielded. `stream` releases in nested `finally` blocks; `_stream_prepared.close` releases even when the generator never started; `_CleanupEventSourceResponse` runs it in a shielded scope however the response ends. A claim cancelled after its `INSERT` was sent deletes the row by its pre-generated id (`_compensate`). Existing tests cover each path (`test_streaming.py`, `test_run_guards.py`, `test_postgres_run_guard.py`).
- The Postgres claim cannot admit k + 1 runs: owner advisory lock, then count, then insert, in one transaction; the unique index on `thread_id` gives `thread_busy` across replicas. Timestamps use `clock_timestamp()`, so a wait on the lock does not shorten the lease.
- `_cancel` cancels the producer once and waits in a shielded scope, so anyio's repeated cancellation after a disconnect does not skip the settle or the release.
- In memory, a lease has no expiry; that is safe because every release path above is in-process and shielded. A leaked lease would need the process to die, which also clears the guard.
- `prepare` gives the reservation back on every refusal, including a pending approval (the lease wrapper from `_count_in_flight` settles it at 0).

**Token budget**
- Never charged twice: `BudgetReservation.settled` makes `settle` idempotent in-process; on Postgres the settlement id and the ledger change commit together, so a replay after an ambiguous commit changes nothing.
- Never under-admitted across replicas: the owner lock serialises sum-then-insert.
- Cancelled or timed-out runs keep the whole reservation when no usage was reported; settle is shielded and never raises; a failed settlement is retried at the owner's next admission, which fails closed until it is written.
- A reservation cannot age out of the window before its run ends: settings refuse a window shorter than the run timeout plus 15 s.

**Rate limiter**
- One atomic upsert per check; a statement that waited on the row lock carries an older time and can only withhold tokens. The in-memory limiter has no `await` between check and update. The slot semaphore keeps a hot key from draining the pool.

**Streaming, cancellation, timeouts**
- The run timeout is enforced in the producer task, so it holds when the client stops reading. On cancellation mid-tool-call the outer graph has only its input checkpoint; the turn's messages commit only when the agent node returns, so history is unchanged and the next run on the thread starts clean (`test_closing_the_stream_cancels_the_run_and_keeps_history`).
- Order on every exit: cancel the producer, settle the budget, release the lease, end the span.

**Shutdown**
- `begin_drain` is safe in a signal handler; readiness turns false at once; new runs are refused after the drain delay; Uvicorn's graceful timeout (run timeout + 10 s) starts after it, so a run admitted at the end of the drain can finish. The lifespan closes the pool only after requests end, then flushes OTel in a thread. The worker cancels its maintenance task, removes its health file, and flushes OTel in `finally`.

**Knowledge worker**
- A job can run on two workers at once (a live worker whose heartbeat went stale is swept), and that is safe: `_write` locks the document row, deletes the old chunk set and inserts the new one in one transaction, so there is always one chunk set.
- Erase and delete cannot leave orphan chunks: chunks and embeddings cascade from the document row; every ingest status change and the final write skip a tombstoned document; the purge's row delete waits for an in-flight write and then removes what it wrote.
- An upload cannot land in a base that is being deleted: the insert takes `FOR SHARE` on the base row, so either the delete waits and tombstones the new document, or the insert finds the base gone and the file is deleted.
- A row never names a missing file through the upload path: the file is stored first, the row and its job commit together, and a failed or cancelled insert deletes the file in a shielded block. The hourly sweep removes the rare orphan after a grace period that settings keep above the upload deadline.
- The stalled-job sweep and the reconcile run are each serialised by an advisory lock and never act on the same job: reconcile ignores any document or tombstone with a live job. Procrastinate's stalled query also finds jobs whose worker row was pruned (`worker_id IS NULL`).
- A periodic tick is queued once across workers (`procrastinate_periodic_defers`).
- Schema setup holds a session advisory lock, so two replicas starting together serialise.

## Open questions

These need a decision or could not be shown, so they are not findings.

1. **An erase while the same user starts a new thread.** A run that has claimed a new thread but not yet written its first checkpoint is not in the erase's listing, so the erase can report nothing skipped and the thread appears afterwards. Closing it means refusing or waiting for the owner's runs during an erase, which is a behaviour change. Is "data created by a request racing the erase" in or out of what erase promises?
2. **A duplicate job re-ingests a `ready` document.** `_start` moves any live document to `parsing`. After a stale-heartbeat sweep of a worker that was only slow, the second run takes a `ready` document out of search until it finishes and pays for embeddings again. Guarding `_start` to in-progress statuses would stop it, but it would also block any future "re-index" that relies on this. Product call.
3. **No lease heartbeat or fencing** (documented in `run_guard.py`). A process stalled for longer than the 15 s grace after its timeout can overlap a new run on the thread. Accepted in ADR 0008; listed so it is a known limit, not a surprise.
4. **Clock mix in the worker.** The stalled-job sweep schedules its retry with the worker's clock (`datetime.now(UTC)`), and the blob sweep compares the worker's clock with file times; everything else uses the database clock. Skew only delays a retry or shifts the 24 h grace by the skew. Not shown to break anything.
5. **Streams end at the drain delay, invokes may run to their timeout.** By design (OPERATIONS.md, "Shutdown"); noting the asymmetry in case it surprises a client author.
