# Stack-Specific Pitfalls

Read only the sections for the stack in scope. These are the framework traps that generic
checklists miss; each one has caused real production incidents.

## Contents
- Java / Spring / JPA-Hibernate
- Kotlin
- Python (Django, FastAPI, Flask, SQLAlchemy, Celery)
- Node.js / TypeScript (Express, NestJS, Next.js, Prisma, TypeORM)
- React / Frontend
- Go
- Rust
- C# / .NET
- Ruby on Rails
- SQL (PostgreSQL, MySQL)
- Rego / OPA

## Java / Spring / JPA-Hibernate
- `@Transactional` ignored on self-invocation (`this.method()`), on private methods, and on
  classes not managed by Spring. Checked exceptions do not roll back unless `rollbackFor` is set.
- `@Async` and `@Cacheable` have the same proxy self-invocation problem.
- Singleton beans with mutable instance fields are shared across all requests.
- Lazy loading outside a session (`LazyInitializationException`), or Open-Session-In-View hiding
  N+1 by keeping sessions open through rendering.
- `FetchType.EAGER` on collections causing cartesian explosions; `JOIN FETCH` with pagination
  paginating in memory (Hibernate warning HHH90003004/HHH000104).
- `equals`/`hashCode` on entities using generated IDs (breaks sets before persist) or all fields
  (triggers lazy loads).
- `@Version` missing on entities with concurrent edits; `save()` on detached entities silently
  overwriting.
- Bulk `@Modifying` queries bypassing the persistence context (stale entities afterward).
- `RestTemplate`/`WebClient` built without timeouts; `WebClient` `.block()` on Netty event loops.
- Jackson default typing or `@JsonTypeInfo(use = CLASS)` on untrusted input (deserialization RCE).
- `SimpleDateFormat`, `HashMap` shared across threads; `CompletableFuture` on the common
  ForkJoinPool for blocking I/O.
- Spring Security matchers ordered so a broad `permitAll()` shadows narrower rules; path-matching
  differences (trailing slash, `/api` vs `/api/`).

## Kotlin
- `!!` on platform types from Java APIs; `lateinit` accessed before init.
- Coroutines: `runBlocking` inside request threads or other coroutines; `GlobalScope` launches
  that leak; blocking calls on `Dispatchers.Default`; swallowed exceptions in `launch` without a
  handler.
- Data classes as JPA entities (`equals`/`hashCode`/`toString` triggering lazy loads).

## Python (Django, FastAPI, Flask, SQLAlchemy, Celery)
- Mutable default arguments; module-level mutable state shared across requests and threads.
- Django: missing `select_related`/`prefetch_related` (N+1); `.objects.get()` without tenant
  filter; `extra()`/`raw()`/`RawSQL` with interpolation; `mark_safe` on user data; side effects
  before commit (use `transaction.on_commit`); `update_or_create`/`get_or_create` races without a
  unique constraint.
- FastAPI/async: sync DB drivers, `requests`, or `time.sleep` inside `async def` (blocks the loop);
  CPU-heavy work in async handlers; dependency-injected sessions not closed on error.
- SQLAlchemy: session shared across threads/tasks; lazy loads in async (`MissingGreenlet`);
  `text()` with f-strings; `expire_on_commit` surprises.
- Celery: tasks not idempotent despite `acks_late`/retries; passing ORM objects instead of IDs;
  task enqueued inside a transaction that later rolls back.
- `pickle`, `yaml.load` without `SafeLoader`, `eval`, `subprocess(..., shell=True)`.
- `requests` calls without `timeout=`; `verify=False`.
- Naive `datetime.now()`/`utcnow()` mixed with aware datetimes.

## Node.js / TypeScript (Express, NestJS, Next.js, Prisma, TypeORM)
- Unawaited promises (lost errors, out-of-order writes); `forEach` with async callbacks (not
  awaited); unhandled rejections crashing the process.
- CPU-heavy or sync work (`fs.*Sync`, `JSON.parse` of huge bodies, crypto in a loop) blocking
  the event loop.
- Express: error middleware missing or registered before routes; async handlers throwing without
  `next(err)` (Express 4); `req.query` values being arrays or objects (type confusion,
  NoSQL injection).
- Prototype pollution through deep merges of user JSON; `Object.assign` from request bodies.
- Prisma `$queryRawUnsafe`/`$executeRawUnsafe` with interpolation; TypeORM `query()` with
  template strings; Mongoose queries built from raw `req.body`.
- Module-level variables shared across requests (and across invocations in serverless warm
  starts); in Next.js server components and route handlers, leaking one user's data via
  module caches.
- `fetch` has no default timeout; use `AbortSignal.timeout()`.
- Numbers above 2^53 (64-bit IDs) losing precision in `JSON.parse`.
- TypeScript types erased at runtime: request bodies typed as DTOs but never validated
  (use zod, class-validator, or equivalent).

## React / Frontend
- `dangerouslySetInnerHTML` with user content; `href={userUrl}` allowing `javascript:`.
- Secrets or private API keys in client bundles or `NEXT_PUBLIC_*`/`VITE_*` variables.
- Authorization enforced only by hiding UI elements.
- `useEffect` race conditions (stale responses overwriting newer state; no abort on unmount).
- Tokens stored in `localStorage` (XSS-exfiltratable) when httpOnly cookies are possible.

## Go
- Goroutine leaks: goroutines blocked on channels or I/O with no `ctx.Done()` path.
- Loop variable capture in goroutines/closures (fixed in Go 1.22+; check `go.mod`).
- `http.DefaultClient` / `http.Get` with no timeout; response bodies not closed or not drained.
- Maps accessed concurrently without a mutex (fatal runtime error, not just a race).
- Errors ignored (`_ =`), shadowed (`err :=` in inner scope), or compared with `==` instead of
  `errors.Is`/`errors.As`.
- `defer` inside loops (resources held until function exit).
- Nil interface vs typed nil pointer returned as `error`.
- `sql.Rows` not closed; `rows.Err()` not checked after iteration.
- Context not propagated to DB and HTTP calls (no cancellation on client disconnect).

## Rust
- `unwrap()`/`expect()` on fallible input in request paths (panics take down tasks or threads).
- Blocking calls inside async runtimes (use `spawn_blocking`); holding a `std::sync::Mutex`
  guard across `.await`.
- `unsafe` blocks without documented invariants.
- Integer overflow wraps silently in release builds; use checked/saturating arithmetic where
  values are user-controlled.

## C# / .NET
- `async void`, `.Result`/`.Wait()` deadlocks and thread-pool starvation.
- `HttpClient` created per request (socket exhaustion) or without timeout; prefer
  `IHttpClientFactory`.
- EF Core: N+1 via lazy-loading proxies; `FromSqlRaw` with interpolation (use `FromSqlInterpolated`);
  `DbContext` shared across threads or registered as singleton.
- `BinaryFormatter` and `TypeNameHandling.All` in Newtonsoft on untrusted data.

## Ruby on Rails
- N+1 without `includes`/`preload`; `find` without scoping to `current_user`/tenant.
- Strong parameters bypassed (`permit!`); mass assignment of role fields.
- `where("name = '#{params[:name]}'")`, `order(params[:sort])`, `send(params[:method])`.
- Callbacks with external side effects running inside transactions (use `after_commit`).
- `html_safe`/`raw` on user input.

## SQL (PostgreSQL, MySQL)
- PostgreSQL: `CREATE INDEX` without `CONCURRENTLY` locks writes; `ALTER TABLE ... ADD COLUMN ...
  DEFAULT <volatile>` rewrites the table; adding `NOT NULL` validates the full table (use a
  `CHECK ... NOT VALID` then `VALIDATE`); FK creation without `NOT VALID` locks both tables;
  `SERIAL`/int4 IDs approaching 2^31.
- MySQL: DDL that is not online for the engine/version in use; implicit charset/collation
  conversions defeating indexes; `utf8` (3-byte) instead of `utf8mb4`.
- Both: `NOT IN` with nullable subqueries returning no rows; `OR` conditions defeating indexes;
  missing indexes on foreign-key columns used in joins or cascades.

## Rego / OPA
- Default allow (`default allow = true`) or missing `default allow = false`.
- Rules that evaluate to undefined (treated as deny or allow depending on the caller's handling);
  check how the caller interprets undefined.
- Overly broad wildcards in path or resource matching; input fields trusted without checking that
  the caller populates them from verified identity, not the request body.
- Policies with no unit tests (`opa test`) for the deny cases.
