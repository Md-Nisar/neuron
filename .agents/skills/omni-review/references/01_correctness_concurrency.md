# Pass 1: Correctness, State, Concurrency and Resources

Trace every state transition, shared-state access, and resource lifetime in scope. For each item
below, the **Verify** line says what evidence turns a suspicion into a finding.

## 1. Logic and Intent
- Behavior differs from the PR description, ticket, or function name/docstring.
- Inverted or incomplete conditions: `&&` vs `||`, `<` vs `<=`, negation slips, wrong variable
  compared (copy-paste), missing `else`/`default`, non-exhaustive `switch`/`match` on enums
  (a new enum value silently falls through).
- Early `return`/`continue`/`break` that skips required work (audit write, cleanup, event emit).
- Return values ignored: `Optional`/`Result`/error codes dropped, Go `err` shadowed or unchecked,
  Promises not awaited, `list.sort()` vs `sorted()` confusion, immutable-string methods whose
  result is discarded.
- **Verify:** construct the concrete input that takes the wrong branch and state the wrong output.

## 2. Boundaries and Invariants
- Null/None/undefined dereference on values that can legitimately be absent (DB nullable columns,
  optional JSON fields, map lookups, `find*` results).
- Empty inputs: division by zero in averages/percentages, `max()` of empty, first element of empty list.
- Off-by-one in pagination, ranges, slicing, retries ("retry 3 times" executing 4).
- Integer overflow or truncation (int32 IDs, `int` cast of `long`, JS numbers above 2^53 for
  64-bit IDs), and unit mismatches (ms vs s, cents vs dollars, bytes vs KB).
- Money in binary floating point; rounding mode not specified; currency mixing.
- Time: naive vs aware datetimes, server-local time instead of UTC, DST gaps/overlaps, "end of
  day" computed in the wrong zone, clock skew between services, `now()` called twice in one
  logical operation.
- Strings: case-sensitive comparison of emails/usernames, Unicode normalization, byte vs char
  length, locale-dependent parsing (`"1,5"`), trimming.
- **Verify:** show the realistic value (from schema, API contract, or upstream code) that hits it.

## 3. State and Lifecycle
- Partial mutation: state changed in memory or DB before a step that can throw, with no rollback
  or compensation; objects left half-initialized.
- Illegal state transitions: status changes that skip validation (e.g. `CANCELLED -> SHIPPED`).
- Non-idempotent operations reachable by retries, double-clicks, or redelivery (charges,
  emails, counters, inventory).
- Aliasing: returning internal mutable collections; mutating arguments the caller still uses;
  Python mutable default arguments; shared config objects mutated per request.
- Broken `equals`/`hashCode`/`__eq__`/`__hash__` contracts, mutable objects used as map keys.

## 4. Concurrency and Thread Safety
- **Shared mutable state** in singletons, Spring beans, module-level globals, static fields,
  class attributes, or closures captured by request handlers or workers.
- **Check-then-act / read-modify-write** without atomicity: `if not exists: insert`,
  `balance = get(); set(balance - x)`, `count++` on shared fields. Remedies: unique constraint +
  handle conflict, `UPDATE ... SET x = x - ? WHERE x >= ?`, `SELECT ... FOR UPDATE`, optimistic
  locking (`@Version`, ETags), atomic types, or a distributed lock with a fencing token.
- **Distributed races:** multiple instances or pods running the same scheduled job with no
  leader election or lock; cache-then-DB updates racing.
- **Deadlocks:** inconsistent lock ordering, nested locks, locks held across I/O or callbacks,
  DB rows updated in different orders by different code paths.
- **Event-loop blocking:** sync I/O, CPU-heavy work, `time.sleep`, or blocking clients inside
  `async` functions, Node handlers, or reactive pipelines.
- **Async pitfalls:** fire-and-forget tasks whose errors vanish; unawaited coroutines;
  `Promise.all` cancelling nothing on failure; goroutines with no exit path (leak on context
  cancellation or a blocked channel); unbounded `go`/`asyncio.create_task` fan-out; thread pool
  starvation by blocking tasks in a shared pool; `ThreadLocal`/context leaking between pooled
  requests; missing context or deadline propagation.
- **Visibility and thread-unsafe types:** non-volatile flags, `HashMap`/`SimpleDateFormat`/
  `ArrayList` shared across threads, lazy singleton init without synchronization.
- **Verify:** describe the interleaving step by step (Thread A reads 5, Thread B reads 5, ...)
  and confirm nothing serializes it (single-threaded worker, DB constraint, lock upstream).

## 5. Transaction Boundaries
- Network, RPC, queue publish, or slow file I/O inside an open DB transaction: holds connections
  and locks, and exhausts the pool under load.
- Side effects (emails, events, external calls) executed before commit, so they fire even when
  the transaction later rolls back. Prefer after-commit hooks or a transactional outbox.
- Dual writes (DB + queue, DB + cache, DB + search index) with no outbox or reconciliation.
- Transaction annotations that do not apply: Spring self-invocation bypassing the proxy,
  `@Transactional` on private methods, checked exceptions not triggering rollback, missing
  `atomic()`/session scope in Python, transactions spanning async boundaries.
- Isolation assumptions: code that relies on serializable semantics under READ COMMITTED.
- **Verify:** identify where the transaction begins and ends, and what runs between.

## 6. Resources and Memory
- Unbounded in-memory accumulation: loading whole tables, files, or API result sets into lists or
  maps; per-key caches or maps without eviction; listeners/subscriptions never removed.
- Streams, connections, cursors, response bodies, file handles, or locks not released on error
  paths (missing `finally`, `try-with-resources`, `with`, `defer`, `using`).
- Temp files never deleted; large buffers re-allocated in loops.
- **Verify:** show the input size is user-controlled or grows with data, and estimate the peak.

## 7. Error Semantics
- Exceptions mapped to the wrong outcome (validation error surfaced as 500, or a 500 reported as
  success); retries on non-retryable errors; errors converted to `null`/empty results that look
  like valid "no data".

## Common False Positives in This Pass
- Request-scoped or prototype beans flagged as shared state.
- Races already prevented by a DB unique constraint, a single-consumer queue, or a partition key.
- Resources closed by the framework (Spring `JdbcTemplate`, Django connections, HTTP client pools).
- "Null" fields guaranteed non-null by validation, a `NOT NULL` column, or the type system.
