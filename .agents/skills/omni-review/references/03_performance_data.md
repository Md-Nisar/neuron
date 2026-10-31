# Pass 3: Database, Caching and Performance

Analyze cost under production scale, not test-fixture scale. Every finding in this pass needs a
**size estimate**: how big N is (rows, items, fan-out, requests/sec), where that number comes
from (schema, limits, product reality), and what it costs (queries, latency, memory).

## 1. Query Patterns
- **N+1:** lazy-loaded relations accessed in loops; repository or API calls inside `for`/`map`;
  GraphQL resolvers without a dataloader. Fix with joins/fetch graphs, `select_related`/
  `prefetch_related`, batch `IN (...)` lookups, or dataloaders.
- **Unbounded reads:** `findAll()`, `.all()`, `SELECT` without `LIMIT` on tables that grow;
  endpoints with no pagination or with an uncapped `limit` parameter.
- **Deep OFFSET pagination** on large tables; prefer keyset/cursor pagination.
- **Over-fetching:** `SELECT *` pulling blobs/JSON columns that are not used; loading entities
  only to read an ID or count them.

## 2. Query Execution Efficiency
- Predicates, joins, or sorts on columns with no supporting index. Check migrations, schema
  files, or entity annotations; a composite index must match column order.
- Non-sargable predicates: functions on indexed columns (`LOWER(email) = ?`, `DATE(created_at)`),
  leading-wildcard `LIKE '%x'`, implicit type casts (string column compared to a number),
  `OR` across different columns.
- Heavy `COUNT(*)`, `GROUP BY`, or `DISTINCT` on hot request paths; consider precomputation,
  approximate counts, or async jobs.
- Huge `IN` lists (thousands of parameters); chunk them.
- **Verify:** name the table, its expected row count, and the predicate; reference the index
  definition or its absence.

## 3. Write Path and Locking
- Row-by-row inserts/updates in loops instead of batch operations.
- Large `UPDATE`/`DELETE` statements without batching, which lock many rows and bloat replication.
- Hot-row contention: global counters, "last updated" rows, or sequence tables updated on every
  request.
- Long-running transactions holding locks during computation or external calls (cross-check
  Pass 1, section 5).

## 4. Fetching and Streaming
- Large result sets materialized fully instead of streamed (missing cursors, `fetchSize`,
  `yield_per`, `iterator()`, server-side cursors).
- Large files or payloads read entirely into memory instead of streamed.

## 5. Caching
- **Key collisions:** keys missing tenant, user, locale, permission scope, pagination, or filter
  parameters, so one user sees another's data (also a Pass 2 issue; report once, as Security).
- **Stampede / thundering herd:** cold or expiring hot keys with no singleflight, lock, early
  refresh, or jittered TTL.
- **Staleness:** writes, updates, or deletes that do not invalidate or update the cache;
  invalidation that runs before the DB commit (a racing reader re-caches the old value).
- Missing TTLs; unbounded local caches; caching exceptions, or not caching negative results
  when misses are expensive.
- Caching mutable objects that callers then modify (aliasing).
- Serialization cost of large cached values exceeding the saved query cost.

## 6. Compute and Serialization
- O(N²) nested loops, `list.contains`/`in list` inside loops, repeated linear searches; use
  sets or maps.
- Regex compilation, JSON (de)serialization, reflection, or formatter construction inside hot
  loops.
- String concatenation in loops in languages where it is quadratic.
- Expensive logging (string building, serialization) on hot paths even when the level is off.
- Synchronous CPU-heavy work on request threads or event loops.

## 7. Network and Downstream Calls
- Sequential remote calls that could be batched or run concurrently (with bounded concurrency).
- Chatty APIs: one call per item where a bulk endpoint exists.
- Missing pagination when consuming downstream list APIs (silently truncated data, or memory).
- Very large request/response payloads; missing compression on large transfers.

## 8. Capacity and Backpressure
- Unbounded thread pools, executors, queues, or goroutine/task fan-out.
- Connection pool sizes that do not match concurrency (or a pool per request).
- No backpressure between fast producers and slow consumers.

## 9. Frontend (when in scope)
- Unvirtualized long lists; re-renders from unstable props or context; waterfalls of dependent
  fetches; large bundles from whole-library imports.

## Common False Positives in This Pass
- Loops over small, bounded collections (enum values, config entries, fixed-size pages); state
  the bound when dismissing.
- N+1 already solved by ORM batch-fetch settings, `@BatchSize`, or a dataloader.
- Queries on tiny lookup tables where a full scan is cheaper than an index.
- Unindexed queries in one-off migrations or admin scripts that run off-peak.
