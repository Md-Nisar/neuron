# RAG implementation tracker

The single place that says what is really done in the Knowledge Engine work. Stories and their
acceptance criteria live in [`NEURON_RAG_PRODUCT_BACKLOG.md`](NEURON_RAG_PRODUCT_BACKLOG.md);
research in `docs/research/rag/`.

**Last verified:** 2026-11-04, against `main` at `c60102a` (RAG-02.01 Done: #424, #425; RAG-02.02 part 1 merged in #426, part 2a on branch `RAG-02.02-part2`).
**Backlog status:** Approved epic by epic. Issues exist for RAG-E00, RAG-E01 and RAG-E02; the Project board has not been created.

## New session protocol

Every Claude session that works on this backlog does this **before writing code**:

1. Read the backlog and this tracker.
2. Inspect the GitHub issues labelled `rag`, their linked PRs, recent commits on `main`, and
   the code itself (`src/neuron_agent/knowledge/`, migrations, routes, `web/src/features/knowledge`).
3. Verify what is genuinely implemented **and tested**: for each story marked In progress or
   Done, find the test that covers each acceptance criterion. Code without such tests is not Done.
4. Classify each touched story as Done, Partial, In progress, Blocked or Pending, and fix this
   tracker where it is wrong.
5. Pick the next unblocked story: lowest phase first, then P0 before P1 before P2, then the
   order in the epic, and only when all its "Depends on" stories are Done.
6. Tell the user the current epic status and the recommended next action, and wait for the go-ahead before coding.
7. Work each story on its own branch named after the story ID (for example `RAG-00.01`), cut
   from `main`, or from the branch of a story it depends on that is not merged yet. Open one PR per
   story titled `[RAG-nn.mm] <title>`, with `Closes #<issue>` and the story issue's labels.
8. After implementing: tick the issue checklist, move the Project item, update this tracker
   (story table, epic counts, implemented functionality, outstanding work, change log).

Never mark a story Done because code exists. Done means every acceptance criterion has a
passing test (or recorded evidence for documentation and spike stories) and the shared
Definition of Done in the backlog is met. Do not change unrelated features.

### Status values

| Status | Meaning |
| --- | --- |
| Pending | Not started |
| In progress | Work on a branch or in an open PR |
| Partial | Some acceptance criteria verified, others not; say which |
| Blocked | Cannot start or continue; the blocker is written in the epic section |
| Done | Every acceptance criterion verified by tests or evidence; PR merged to `main` |
| Dropped | Will not be built; reason recorded |

## Overall status

| Epic | Title | Phase | Release | Total | Done | In progress | Blocked | Pending | Next story |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| RAG-E00 | Readiness and decisions | 0 | v1.1.0 | 4 | 4 | 0 | 0 | 0 | — |
| RAG-E01 | Knowledge storage foundation | 1 | v1.1.0 | 3 | 3 | 0 | 0 | 0 | — |
| RAG-E02 | Durable ingestion pipeline | 1 | v1.1.0 | 5 | 2 | 1 | 2 | 0 | RAG-02.02 (in progress) |
| RAG-E03 | Knowledge API | 1 | v1.1.0 | 5 | 0 | 0 | 0 | 5 | RAG-03.01 (ready) |
| RAG-E04 | Retrieval and agent tools | 1 | v1.1.0 | 4 | 0 | 0 | 0 | 4 | RAG-04.01 (ready) |
| RAG-E05 | Server-validated citations | 1 | v1.1.0 | 2 | 0 | 0 | 0 | 2 | RAG-05.01 (after RAG-04.02) |
| RAG-E06 | Knowledge in the web app | 1 | v1.1.0 | 2 | 0 | 0 | 0 | 2 | RAG-06.01 (after E03) |
| RAG-E07 | Data rights and lifecycle | 1 | v1.1.0 | 3 | 0 | 0 | 0 | 3 | RAG-07.01 (after RAG-03.03) |
| RAG-E08 | Quality, security and release | 1 | v1.1.0 | 5 | 0 | 0 | 0 | 5 | RAG-08.01 (after RAG-04.01, RAG-05.01) |
| RAG-E09 | Retrieval quality and sharing | 2 | v1.2.0 | 8 | 0 | 0 | 0 | 8 | RAG-09.02 (Phase 2) |
| RAG-E10 | External knowledge sources | 3 | later | 5 | 0 | 0 | 0 | 5 | RAG-10.01 (Phase 3) |
| RAG-E11 | Specialised knowledge tools | 4 | later | 5 | 0 | 0 | 0 | 5 | — (evidence-gated) |
| RAG-E12 | Platform and scale | 5 | later | 5 | 0 | 0 | 0 | 5 | — (evidence-gated) |
| **Total** | | | | **56** | **9** | **1** | **2** | **44** | **RAG-02.02** |

v1.1.0 scope (E00–E08): 33 stories, 9 done.

**Recommended next action:** finish RAG-02.02 (#410): part 1 merged (#426); part 2a (the docling-serve parser and its recorded fake) is on branch `RAG-02.02-part2`; part 2b is docling-serve without egress in the reference stack (AC5), an opt-in test against it, and the supported formats in the user docs. RAG-03.01 and RAG-04.01 are also unblocked.

## GitHub synchronisation

| Item | State |
| --- | --- |
| Labels `epic`, `story`, `rag`, `phase:0`–`phase:5`, `v1.1.0`, `v1.2.0` | Created 2026-11-03 |
| Epic issues (13) | RAG-E00 (#398, closed), RAG-E01 (#415, closed), RAG-E02 (#408); the others not created |
| Story issues (56) | RAG-00.01–00.04 (#399–#402, closed), RAG-01.01–01.03 (#416–#418, closed), RAG-02.01–02.05 (#409–#413; #411 closed); the rest not created |
| GitHub Project board (fields: Status, Priority, Epic, Phase, Release) | Not created. Projects use the GraphQL API, which the Claude cloud session could not reach on 2026-11-02 (HTTP 403); the owner may need to create it or allow access |

### Issue map

Filled in when issues are created. The bracketed ID in the issue title is what de-duplication matches on.

| ID | Issue | Project status |
| --- | --- | --- |
| RAG-E00 | #398 | Not on a board |
| RAG-00.01 … RAG-00.04 | #399–#402 | Not on a board |
| RAG-E01 | #415 | Not on a board |
| RAG-01.01 … RAG-01.03 | #416–#418 | Not on a board |
| RAG-E02 | #408 | Not on a board |
| RAG-02.01 … RAG-02.05 | #409–#413 | Not on a board |
| RAG-E03 … RAG-E12 | — | — |

## Epic detail

### RAG-E00 Readiness and decisions

- **Stories:** 4 total · 4 done · 0 in progress · 0 blocked · 0 pending
- **Implemented functionality:** ADR 0014 Accepted 2026-11-02, amending ADR 0001, 0002 and 0005; v1.1.0 in `docs/ROADMAP.md` (RAG-00.01). Labelled corpus and security dataset: 31 documents, 64 answerable, 12 unanswerable, 5 ACL and 4 injection cases, schema-checked in `make test` (RAG-00.03). Spike answers to ADR 0014's five open questions in `docs/releases/v1.1.0-spike.md` (RAG-00.02): Docling on CPU, 1,024 dimensions with `nemotron-3.5-embed-1b`, exact scan up to 10,000 chunks, Procrastinate with a stalled-job sweep, TEI for production. Dependency and image plan in ADR 0014 "Dependencies and images" (RAG-00.04): a `neuron-agent[worker]` extra (+167 MB, API environment unchanged), versions, licences and digests.
- **Outstanding work:** none. Phase 0 is on `main` (#403, then #407 relanding #404–#406); #398–#402 closed.
- **Blockers and decisions:**
  - 2026-11-02: the owner accepted ADR 0014, including the v1.1.0 scope (E00–E08).
  - Decision 2026-11-02: the research's security prerequisites are not all done. #370 is fixed
    in v1.0.0; #364 (SSRF) and #366 (HTTPS-only) are fixed for MCP by #395 (unreleased, on `main`);
    ingestion fetchers must still reuse that control (RAG-10.01), which blocks web ingestion and `research_web` but not Phase 1 (Phase 1 makes no
    outbound fetches of user URLs).
- **Next recommended story:** RAG-01.01 (pgvector image, extension and startup check). The spike scripts stay on `RAG-00.02-spike` and the lock evidence on `RAG-00.04-lock`, both unmerged.

### RAG-E01 Knowledge storage foundation

- **Stories:** 3 total · 3 done · 0 in progress · 0 blocked · 0 pending
- **Implemented functionality:** RAG-01.01 (#419): `APP_KNOWLEDGE_ENABLED` (default off); feature-gated migration 17 (`knowledge_schema`: `vector` extension and migrator-owned `knowledge` schema); a `setup` pre-check and schema-trust check; staging/production start-up and readiness checks with stable codes (`vector_extension_missing`, `knowledge_schema_missing`, `knowledge_schema_untrusted`); `pgvector/pgvector:pg16` pinned in CI, `docker-compose.yml` and the reference stack (with `shm_size` and an init script).
  RAG-01.02 (#420): migrations 18–24 (six `knowledge` tables, unique, GIN and B-tree indexes), RLS policy `kb_scope` on `chunks` and `embeddings`, exact grants for the app role and `APP_POSTGRES_WORKER_ROLE`, index profile 1 seeded from settings with its HNSW index, `knowledge_profile_mismatch`; schema in `ARCHITECTURE.md`.
  RAG-01.03 (#421): `knowledge/blobs.py` (`BlobStore`, `LocalBlobStore`, `S3BlobStore` over `obstore`; random 128-bit hex keys, SHA-256 computed while streaming and re-checked on read, idempotent delete, failed uploads cleaned up), `APP_KNOWLEDGE_BLOB_*` settings.
- **Outstanding work:** none. #415–#418 closed; #421 and #422 labelled.
- **Blockers and decisions:**
  - Decision (RAG-01.01, #416): the migrator has only `CONNECT` on the database, and `CREATE SCHEMA IF NOT EXISTS` checks the database privilege even when the schema exists, so the operator's superuser step creates the extension and `CREATE SCHEMA knowledge AUTHORIZATION neuron_migrator`; the migrator gets no database `CREATE`. `setup` refuses a schema owned by another role or creatable by `PUBLIC` or the app role (security review finding).
  - Assumption (RAG-01.01): "`/health/ready` reports the failing check" is a 503 plus a `knowledge_check_failed` log with the code; the unauthenticated body stays `{"status": "not_ready"}`.
  - Decision (#408): the worker gets its own `neuron_worker` role, whose grants RAG-01.02 adds.
  - Decision (RAG-01.02, ADR 0014 security requirement 2): `bases`, `grants` and `documents` get no RLS. The API reads them to find the allowed KB ids before it can set `neuron.kb_ids`, and every query on them filters on the owner key (RAG-04.01); RLS stays on `chunks` and `embeddings`.
  - Decision (RAG-01.02): the worker gets no RLS bypass. It sets `neuron.kb_ids` to the job's KB, so the same policy binds it (ADR 0014 requirement 1). It gets `SELECT` on `documents` plus `UPDATE` on its progress columns only (not `kb_id`, `blob_key` or the owner), and `SELECT, INSERT, DELETE` on `chunks` and `embeddings`; the app role only reads `chunks` and `embeddings` (cascades delete them).
  - Decision (RAG-01.02): composite foreign keys keep the copied `kb_id` on `chunks` and `embeddings` equal to the parent's, since it is the RLS key. Owner columns have a `CHECK` for the 64-hex HMAC owner key.
  - Decision (RAG-01.02): the migration policy forbids non-concurrent `CREATE INDEX`, so each index is its own concurrent migration (19–24). The HNSW index needs the profile's dimension, so `setup` builds it (concurrently, rebuilt if invalid) after seeding profile 1, not a migration. A later change of provider, model or dimension fails `setup` with `knowledge_profile_mismatch` until a re-index story exists.
  - Assumption (RAG-01.02): while the worker role does not exist, `setup` skips its grants with `worker_role_grants_skipped`, also in production; RAG-02.01, which adds the worker, should make it required there. `chunker` is recorded as `docling-hierarchical`.
  - Security review (RAG-01.02): no high findings. Fixed: `setup` now verifies RLS state (enabled, migrator-owned, `kb_scope` with `USING` and `WITH CHECK`) and refuses drift with `knowledge_schema_untrusted`; the worker is included in the schema `CREATE` check; the worker's `documents` UPDATE is column-level; single-role setups log `knowledge_rls_not_enforced`. Left for later stories: every query on `bases`, `grants` and `documents` must filter on the owner key, with cross-owner tests (RAG-03, RAG-04); callers must use `SET LOCAL`, never a session `SET` (RAG-04.01 test); the worker's reads of `bases` and `documents` are unscoped by design (requirement 2); worker grants are not revoked when knowledge is turned off; role-membership between app and worker is not checked.
  - Not done (RAG-01.02): mutation testing does not apply. The RLS policy is SQL, and `mutmut` mutates only `security/` and `tools/` (`pyproject.toml`), not `persistence/`. The policy and grants are covered by the Postgres integration tests, which fail when `USING`, `WITH CHECK` or a grant changes.
  - Decision (RAG-01.03, ADR 0014 amended): `obstore` is a core dependency, not in the `worker` extra, because the API writes originals at upload (RAG-03.02) and reads them for download (RAG-03.04); about +16 MB in the API image. A plain-filesystem path in the API would rule out `s3` there.
  - Decision (RAG-01.03): `local` in staging/production fails settings validation unless `APP_KNOWLEDGE_BLOB_LOCAL_ALLOWED=true`, and only with `APP_KNOWLEDGE_ENABLED=true`, so v1.0.0 production profiles stay valid.
  - Decision (RAG-01.03): `put` takes no file name at all, so no user path part can reach a key; `get`, `delete` and `exists` refuse any key that is not 32 lowercase hex characters. `get` returns bytes (files are bounded by the upload limit, RAG-03.02). One class over `obstore` serves both backends; `LocalBlobStore` and `S3BlobStore` only build the store.
  - Assumption (RAG-01.03): write-once comes from fresh random keys (the store never writes to an existing key), not from S3 conditional puts, which `obstore` performs without multipart streaming. Server-side encryption and blocked public access are bucket configuration (`OPERATIONS.md`, "Knowledge blob store"), not per-request headers, so S3-compatible servers without KMS still work. Unset S3 credentials use the standard AWS chain.
  - Security review (RAG-01.03): no high findings. Fixed: `put` takes a required `max_bytes` and raises `BlobTooLargeError` (`blob_too_large`) without storing anything; failed-upload clean-up is shielded from cancellation; other storage errors become `blob_backend_error` without the path or URL (logged by type only); the local root is set to `0700` even when it exists; whitespace-only blob settings count as unset. Documented in `OPERATIONS.md`: an S3 lifecycle rule for incomplete multipart uploads, and checking the ambient AWS identity when no keys are set. Left as is: `get` reads the whole blob into memory (bounded by `max_bytes` at `put`); a symlink planted in the root needs write access to it already.
  - Story review (RAG-01.03): the AI review's medium finding (S3 endpoint to internal hosts) is fixed in proportion: link-local addresses (`169.254.0.0/16`, `fe80::/10`), `fd00:ec2::254` and the GCP/Azure metadata names are refused; private hosts stay allowed for self-hosted MinIO, as for the embedding base URL (ADR 0014 requirement 4). Also fixed: the bucket name must be a valid S3 name; with knowledge on, staging/production need an absolute `APP_KNOWLEDGE_BLOB_ROOT` (a relative root follows the working directory, rarely the volume).
  - Assumption (RAG-01.03): the default root `var/knowledge-blobs` is relative, for development; RAG-02.01 or RAG-03.02 wires the store into a process and mounts the volume.
  - Post-merge review (E01, 2026-11-03): no high findings. Fixed: `setup` refused only a missing or clause-less `kb_scope`, so an extra permissive policy (ORed in) or a `kb_scope` rewritten to `USING (true)` passed; it now requires `kb_scope` to be the only permissive policy, with migration 18's expressions (compared as PostgreSQL 16 deparses them). The S3 endpoint check also refuses integer, hex, octal and short IPv4 forms. `run_setup` now requires the knowledge profile instead of defaulting one. Left for RAG-03.02: the idempotency index is per uploader, not per KB, so a replay must check `kb_id` and current access.
- **Next recommended story:** RAG-02.01.

### RAG-E02 Durable ingestion pipeline

- **Stories:** 5 total · 2 done · 1 in progress · 2 blocked · 0 pending
- **Implemented functionality:** RAG-02.03 (merged via #414): `knowledge/providers.py` (`EmbeddingProvider` over LangChain `Embeddings`: `nvidia`, `openai_compatible`, a numpy-free `fake`; batching; count, dimension and finite checks; retries for 429/5xx/connection errors only; sanitised codes) and the `APP_KNOWLEDGE_EMBEDDING_*` and `APP_KNOWLEDGE_PROCESSING_POLICY` settings. A live check against the NVIDIA API catalog with fictional text returned 1,024-dimension passage and query vectors.
  RAG-02.01 part 1 (#424): migration 25 (`knowledge_job_queue`: Procrastinate 3.10.0's schema in the `knowledge` schema, functions with a pinned `search_path`); `knowledge/jobs.py` (`defer` with ids only, refused outside a transaction); app role may only queue, worker role has DML on the queue tables and USAGE on their sequences.
  RAG-02.01 part 2 (#425): `knowledge/worker.py` and the `neuron-worker` console script (worker DSN and pool with `search_path=knowledge`, `jobs.Task` registered by name, the ingest task a UUID-checking stub for RAG-02.04, a stalled-job sweep under an advisory lock that fails a job after 5 attempts, `SIGTERM` drain, `neuron-worker health`); `APP_POSTGRES_WORKER_DSN` and `APP_WORKER_*` settings; production `setup` requires the worker role; reference-stack `worker` service (`knowledge` profile) and `neuron_worker` role; OPERATIONS runbook.
  RAG-02.02 part 1 (#426): `knowledge/parsing.py`: `check_input` (content sniffing against the declared type; byte cap; encrypted PDFs, non-Office zips, macro-enabled OOXML and zip bombs refused), the `ParsedDocument` schema and `validate_output` (page and character caps, `parser_output_invalid`), the `DocumentParser` protocol, `PlainTextParser` (form feeds give `.txt` pages; Markdown headings outside fences); `APP_KNOWLEDGE_PARSE_MAX_*` settings.
  RAG-02.02 part 2a (branch `RAG-02.02-part2`): `knowledge/docling_serve.py`: `DoclingServeParser` posts bytes to docling-serve's `/v1/convert/file` (JSON out, OCR, accurate tables, a page range one past the cap) under a total deadline (`parser_timeout`, final), caps the reply (`parser_output_too_large`), validates the parts of Docling's JSON it reads (`parser_output_invalid`), walks the body's references with its own stack, drops running heads, and maps headings (levels), lists, tables, pages and top-left boxes; `parser_unavailable` (connection refused, 408, 429, 502-504) is the only retryable code. Recorded fake: Docling's reply for `nist-cswp-29` in `tests/fixtures/knowledge/recorded/`. `APP_KNOWLEDGE_PARSER_*` settings.
- **Outstanding work:** RAG-02.02 part 2b (docling-serve on an internal network without egress, AC5; an opt-in test against it; supported formats in the user docs). Follow-up from RAG-02.01: a worker settings profile, so that staging/production validation stops requiring `APP_POSTGRES_DSN` (the app DSN) in the worker's environment (security review of part 2). Then RAG-02.02, 02.04, 02.05.
- **Blockers and decisions:**
  - Unblocked: RAG-02.02 (RAG-02.01 merged in #425). Blocked: RAG-02.04 needs RAG-02.01, 02.02 and RAG-01.03; RAG-02.05 needs RAG-02.04 and the upload route (RAG-03.02, missing from its "Depends on").
  - Assumptions (RAG-02.03, #411): `nvidia` is always hosted; `openai_compatible` is hosted unless `APP_KNOWLEDGE_EMBEDDING_LOCALITY=self_hosted`; the fake provider is refused in staging/production; a keyed endpoint needs https there. `bases.processing` is a RAG-01.02 column; RAG-02.04 and RAG-04.01 must call `ensure_processing_allowed` before every embedding call. A missing NVIDIA key in staging/production now fails at settings load when `APP_KNOWLEDGE_ENABLED=true` (RAG-01.01).
  - Decision (RAG-02.01): the queue tables live in the `knowledge` schema, not `public` or a `procrastinate` schema. The migrator cannot create a schema (only `CONNECT` on the database), the worker then needs no rights in `public` (so a compromised parser cannot reach threads or checkpoints), and `public`'s default privileges do not hand the app role DML on them. Procrastinate's functions get `search_path = knowledge, pg_catalog, pg_temp`, so the API calls `knowledge.procrastinate_defer_jobs_v1` from its own transaction and the triggers resolve their tables. The queue tables have no RLS: rows carry ids only.
  - Decision (RAG-02.01, ADR 0014 amended): `procrastinate` is a core dependency pinned to 3.10.0, not in the `worker` extra, because `setup` runs from the API image and takes the schema from the installed library (+4 pure-Python packages in the API environment). An upgrade must add Procrastinate's migration files as new Neuron migrations; `test_the_job_queue_migration_matches_the_installed_procrastinate` fails until it does. The `worker` extra does not exist yet; RAG-02.02 adds it with `docling-core`.
  - Decision (RAG-02.01): the migration policy allows `CREATE INDEX` without `CONCURRENTLY` on a table the same migration creates with a plain `CREATE TABLE` (it fails if the table exists, so the table is new and empty); Procrastinate's schema needs it.
  - Decision (RAG-02.01): the app role gets `SELECT, INSERT` on `procrastinate_jobs` (the defer function returns the id) and `INSERT` on `procrastinate_events` (its trigger), nothing on `procrastinate_workers` or `procrastinate_periodic_defers`; it cannot change or delete a job. Split: the story is two PRs to stay near 400 lines (part 1 queue, part 2 worker process); the issue closes with part 2.
  - Security review (RAG-02.01 part 1): no high findings. Fixed: `setup` now requires the worker role to hold nothing on the `public` tables and refuses a worker that is a member of the app role or the reverse (either would hand the worker the app's rights to threads and checkpoints); the index-policy lint no longer treats a quoted `"Checkpoints"` as the live `checkpoints`. Left for later stories: the app role can insert any job row directly (Procrastinate's functions run with the caller's rights), so a compromised API could queue arbitrary arguments; RAG-02.04's task must parse its arguments as UUIDs and look the document up, never trust them (a SECURITY DEFINER defer wrapper is the stronger option if the API ever needs less than `INSERT`). Not done, not exploitable today: `EXECUTE` on the queue functions stays with `PUBLIC` (only the app and worker have `USAGE` on the schema, and the functions run as the caller); `setup` does not re-check the functions' pinned `search_path` or the sequence grants. RAG-02.01 part 2 sets the worker's `search_path=knowledge` per connection, never `public`; duplicate ingest jobs for one document are RAG-02.04's idempotency (or `queueing_lock = doc_id`).
  - Decision (RAG-02.01 part 2, ADR 0014 amended): the worker runs from the API image with the command `neuron-worker` until a worker-only dependency exists; RAG-02.02 adds the `worker` target and extra with the parser client. This defers #408's "second Dockerfile target", it does not drop it. `/health/ready` ignores the worker (AC4); the worker's health is its file. The sweep is Neuron's (one transaction under `pg_try_advisory_xact_lock`, Procrastinate's own queries), because Procrastinate's `get_stalled_jobs` then `retry_job` from two workers could requeue a job a third worker had already picked up again.
  - Security review (RAG-02.01 part 2): no blockers. Fixed: the reference worker gets only `APP_ENV` and its DSN, not the API's environment; sweeps never overlap and a job that keeps killing its worker fails after 5 attempts; a start-up connection error prints only the error class; staging also requires the worker role itself; a stale health file is removed at start; the ingest stub logs the canonical UUID. Left: staging/production settings still require the app DSN in the worker's environment (follow-up above); health follows the sweep loop, not Procrastinate's fetch loop; a job with an invalid argument is retried 5 times before failing; RAG-02.04 must take the document's `kb_id` and owner from its row, never from job arguments.
  - Security review (RAG-02.02 part 1): fixed before the PR: a quadratic heading regex (now linear, with a 200 KB-line test); page and block bombs (form feeds counted before splitting, 200 blocks per page, a total-character cap); `/Encrypt` spelled with `#xx` escapes; macros found by content type and part name (percent-decoded), and the main part must be the exact non-macro, non-template type; zip entries counted from the end-of-central-directory record before the directory is read, per-member and compression-method limits; NUL text and NaN boxes invalid; one `parse_document` entry point; work off the event loop; UTF-8 BOM. Decided: embedded objects (`*/embeddings/*`, such as a chart's workbook) are allowed, because docling extracts text only and many ordinary Office files have them; PDF active content (JavaScript, embedded files) is not refused, for the same reason, in a parser container without egress. Left for part 2: cap the docling response size, a timeout and page range on the call, docling without egress. Left for RAG-03.02: the upload must stream with a hard byte cap, since `check_input` sees bytes already in memory.
  - Decision (RAG-02.02): two PRs. Part 1 needs no dependency; part 2 brings docling-serve and the `worker` extra. AC1 (corpus PDF headings and pages) and AC5 (no egress) are part 2's; AC2's "document ends `failed`" is RAG-02.04's pipeline, while part 1 gives the non-retryable `ParseError` codes it records. Encrypted-PDF, zip and macro fixtures are built in the tests rather than stored as files.
  - Decisions (2026-11-03, delegated by the owner, recorded on #408): the API stays ready with the worker down; the worker uses its own `neuron_worker` role; the concurrent-job limit refuses with 429 `ingestion_concurrency_exceeded`; embedding tokens go in a separate ledger kind, not the chat budget; default embedding `nemotron-3.5-embed-1b` at 1,024 for development (TEI in production); the worker is a second Dockerfile target; chunking uses `HierarchicalChunker` with Neuron's own token split instead of `chunking-openai`.
  - Decision (RAG-02.02 part 2a, ADR 0014 amended): the parser client is `httpx2` (core), so the `worker` extra and Dockerfile target move to RAG-02.03, which brings `docling-core`. The recorded reply was produced with the Docling library docling-serve wraps (docling 2.146.0, docling-core 2.105.0) because the 7.57 GB image did not fit the recording machine; its structure matches the spike's docling-serve run (32 pages, 40 section headers, 4 tables), and an opt-in test against docling-serve (part 2b) covers the real service. `parser_timeout` is final rather than retried: the same file would time out again. A `partial_success` reply fails as `parser_failed`, since its missing pages could not be cited. AC1 passes against the recording: all 5 `nist-cswp-29` evidence quotes are on their expected pages. Part 2a is about 650 changed lines: the adapter, its reply schema and its tests are one unit.
  - Security review (RAG-02.02 part 2a): fixed before the PR: references are keyed on the item, with one accepted spelling (`#/texts/N`, no leading zeros), so a reply cannot alias one group under many references for quadratic work in a thread outside the deadline; non-ASCII or over-long indexes and `Content-Length` values are `parser_output_invalid`, not a raw `ValueError`; a 500 or a reply cut off is final (`parser_failed`), not retried, so a file that crashes docling-serve does not crash it five times; `Accept-Encoding: identity` and any other client error is `parser_failed`; docling-serve's own `document_timeout` is 90% of the deadline; the parser URL may not carry credentials; the reply cap defaults to 64 MB (max 512 MB). Left: validating a reply can take several times its size in memory (bounded by the cap); the normalising thread is not cancellable but is now linear in the reply; docling-serve has no API key, it relies on the internal network (part 2b).
- **Next recommended story:** RAG-02.02 part 2b, then RAG-02.04.

### RAG-E03 Knowledge API

- **Stories:** 5 total · 0 done · 0 in progress · 0 blocked · 5 pending
- **Implemented functionality:** none. No `knowledge:*` permissions exist in `security/authorization.py`.
- **Outstanding work:** RAG-03.01 to RAG-03.05.
- **Blockers and decisions:** needs RAG-01.02.
- **Next recommended story:** RAG-03.01.

### RAG-E04 Retrieval and agent tools

- **Stories:** 4 total · 0 done · 0 in progress · 0 blocked · 4 pending
- **Implemented functionality:** none. The building blocks exist: `ToolSpec.taints_run` (`tools/registry.py`), identity through runtime context (`memory/tools.py`).
- **Outstanding work:** RAG-04.01 to RAG-04.04.
- **Blockers and decisions:** exact/HNSW threshold from the spike.
- **Next recommended story:** RAG-04.01.

### RAG-E05 Server-validated citations

- **Stories:** 2 total · 0 done · 0 in progress · 0 blocked · 2 pending
- **Implemented functionality:** none. `_final_answer` (`graphs/main_graph.py`) already recomputes `used_tools`; citations follow the same pattern.
- **Outstanding work:** RAG-05.01, RAG-05.02.
- **Blockers and decisions:** needs RAG-04.02.
- **Next recommended story:** RAG-05.01.

### RAG-E06 Knowledge in the web app

- **Stories:** 2 total · 0 done · 0 in progress · 0 blocked · 2 pending
- **Implemented functionality:** none. `web/src/features/` has `chat`, `data`, `threads`.
- **Outstanding work:** RAG-06.01, RAG-06.02.
- **Blockers and decisions:** needs the E03 routes and the RAG-05.02 contract.
- **Next recommended story:** RAG-06.01.

### RAG-E07 Data rights and lifecycle

- **Stories:** 3 total · 0 done · 0 in progress · 0 blocked · 3 pending
- **Implemented functionality:** none. Existing data-rights routes under `/v1/me` cover threads and memories only.
- **Outstanding work:** RAG-07.01 to RAG-07.03.
- **Blockers and decisions:** needs RAG-03.03.
- **Next recommended story:** RAG-07.01.

### RAG-E08 Quality, security and release

- **Stories:** 5 total · 0 done · 0 in progress · 0 blocked · 5 pending
- **Implemented functionality:** none.
- **Outstanding work:** RAG-08.01 to RAG-08.05.
- **Blockers and decisions:** v1.1.0 gate: zero cross-user results; ≥90% of answerable questions cite a correct page; killed-worker job completes; existing tests green.
- **Next recommended story:** RAG-08.01.

### RAG-E09 Retrieval quality and sharing

- **Stories:** 8 total · 0 done · 0 in progress · 0 blocked · 8 pending
- **Implemented functionality:** none.
- **Outstanding work:** RAG-09.01 to RAG-09.08.
- **Blockers and decisions:** Phase 2 starts after v1.1.0. Release v1.2.0 is a proposal.
- **Next recommended story:** RAG-09.02.

### RAG-E10 External knowledge sources

- **Stories:** 5 total · 0 done · 0 in progress · 0 blocked · 5 pending
- **Implemented functionality:** none. `security/egress.py` (#395) resolves, pins and re-checks redirects for MCP only; no ingestion fetcher exists yet.
- **Outstanding work:** RAG-10.01 to RAG-10.05.
- **Blockers and decisions:** evidence-gated; needs a product requirement per source. RAG-10.01 blocks RAG-10.02, RAG-10.03 and RAG-11.02.
- **Next recommended story:** RAG-10.01.

### RAG-E11 Specialised knowledge tools

- **Stories:** 5 total · 0 done · 0 in progress · 0 blocked · 5 pending
- **Implemented functionality:** none.
- **Outstanding work:** RAG-11.01 to RAG-11.05.
- **Blockers and decisions:** evidence-gated; mutating tools need an ADR 0003 amendment; a subgraph needs a new ADR.
- **Next recommended story:** none until a requirement exists.

### RAG-E12 Platform and scale

- **Stories:** 5 total · 0 done · 0 in progress · 0 blocked · 5 pending
- **Implemented functionality:** none.
- **Outstanding work:** RAG-12.01 to RAG-12.05.
- **Blockers and decisions:** evidence-gated; each needs a measured gain and usually an ADR.
- **Next recommended story:** none until a requirement exists.

## Story status

| ID | Title | Phase | Pri | Status | Issue | PR | Evidence |
| --- | --- | --- | --- | --- | --- | --- | --- |
| RAG-00.01 | ADR 0014: Knowledge Engine | 0 | P0 | Done | #399 | #403 | `docs/decisions/0014-knowledge-engine.md` Accepted 2026-11-02 (AC1); ADR 0001/0002/0005 say "Amended by ADR 0014" (AC2); spike questions listed with working defaults (AC3) |
| RAG-00.02 | Phase 0 spike: parser, vectors, queue | 0 | P0 | Done | #400 | #405 | `docs/releases/v1.1.0-spike.md`: one measured answer per question (AC1); kill-worker test, exactly one completion per job (AC2); exact-scan threshold 10,000 as the RAG-04.01 default (AC3) |
| RAG-00.03 | Labelled eval corpus and knowledge security dataset | 0 | P0 | Done | #401 | #404 | `tests/unit/test_knowledge_cases.py`: schema and references (AC1), counts (AC2), licence and source per document (AC3) |
| RAG-00.04 | Dependency and image plan | 0 | P0 | Done | #402 | #406 | ADR 0014 "Dependencies and images": `uv lock` resolves beside `openai>=3.6.0`, API environment unchanged, worker +167.1 MB (AC1); licence and first release per package (AC2); versions and digests named in RAG-01.01 and RAG-02.01 (AC3) |
| RAG-01.01 | pgvector image, extension and startup check | 1 | P0 | Done | #416 | #419 | `tests/integration/test_postgres_knowledge.py` on pgvector: extension and schema created, migration recorded once (AC1); start-up refused with `vector_extension_missing`, readiness false (AC2); without knowledge, migration 17 not applied and the full Postgres suite passes on plain `postgres:16` (AC3, run locally 2026-11-03) |
| RAG-01.02 | Knowledge tables, role grants and row-level security | 1 | P0 | Done | #417 | #420 | `tests/integration/test_postgres_knowledge_tables.py` on pgvector: only KB A's rows with `neuron.kb_ids = A` (AC1); none when unset or empty (AC2); none in the next transaction on the same connection (AC3); app and worker roles cannot `DROP`, `ALTER`, `TRUNCATE`, disable RLS or drop the policy, and hold exactly the documented grants (AC4); the v1.0.0 schema's columns, indexes, constraints and ACLs are identical after knowledge setup (AC5) |
| RAG-01.03 | BlobStore for original files | 1 | P0 | Done | #418 | #421, #422 | `tests/unit/test_knowledge_blobs.py` (local directory and obstore memory store): keys are 32 hex characters, the only file written is `<root>/<key>`, traversal keys refused (AC1); tampered bytes or a wrong checksum raise `BlobIntegrityError` (AC2); a second `delete` succeeds (AC3); over `max_bytes` stores nothing; backend errors carry no path; production with knowledge on and `local` fails without `APP_KNOWLEDGE_BLOB_LOCAL_ALLOWED=true` (AC4). S3, run 2026-11-03 against a local moto S3 server (the MinIO image could not be pulled here): 9 MB multipart put, get, checksum mismatch, double delete; a failed upload left 0 objects and 0 pending multipart uploads |
| RAG-02.01 | Worker entrypoint and job queue | 1 | P0 | Done | #409 | #424, #425 | `tests/integration/test_postgres_knowledge_jobs.py`: a rolled-back document insert leaves no job, a committed one exactly one (AC3). `tests/integration/test_postgres_knowledge_worker.py` (a `neuron-worker` subprocess): `SIGKILL` mid-job, restart, the job completes once (AC1); `SIGTERM` finishes a 2 s job within a 20 s drain and exits 0, and releases a 60 s job to `todo` after a 1 s drain and exits 0 (AC2); with a job queued and no worker, `/health/ready`'s persistence check is ready (AC4) |
| RAG-02.02 | Document parser adapters | 1 | P0 | In progress | #410 | #426 (part 1), branch `RAG-02.02-part2` (part 2a) | `tests/unit/test_knowledge_parsing.py`: encrypted PDF, non-Office zip, macro-enabled and mislabelled files refused with stable codes (AC4); schema-invalid output fails with `parser_output_invalid` (AC3); corpus Markdown sections parsed as headings. `tests/unit/test_knowledge_docling_serve.py`: corpus PDF evidence on its expected pages, headings with levels (AC1, recorded reply); deadline and read timeout give `parser_timeout`, not retryable (AC2's parser side); invalid Docling JSON gives `parser_output_invalid` (AC3). AC5 in part 2b; AC2's document status in RAG-02.04 |
| RAG-02.03 | Embedding provider and processing locality | 1 | P0 | Done | #411 | #414 | `tests/unit/test_knowledge_providers.py`: staging/production refusal under `self_hosted_only` (AC1); `embedding_dimension_mismatch`, nothing returned (AC2); 429/5xx/connection retried with backoff, 400 terminal (AC3); fake provider, network blocked (AC4) |
| RAG-02.04 | Idempotent ingest task | 1 | P0 | Blocked | #412 | — | — |
| RAG-02.05 | Ingestion quotas and embedding token accounting | 1 | P0 | Blocked | #413 | — | — |
| RAG-03.01 | Knowledge base routes and permissions | 1 | P0 | Pending | — | — | — |
| RAG-03.02 | Document upload, list and status | 1 | P0 | Pending | — | — | — |
| RAG-03.03 | Tombstone delete and purge jobs | 1 | P0 | Pending | — | — | — |
| RAG-03.04 | Chunk inspection and file download | 1 | P0 | Pending | — | — | — |
| RAG-03.05 | Knowledge search endpoint | 1 | P1 | Pending | — | — | — |
| RAG-04.01 | Hybrid retriever with authorisation in the query | 1 | P0 | Pending | — | — | — |
| RAG-04.02 | Knowledge agent tools | 1 | P0 | Pending | — | — | — |
| RAG-04.03 | Abstention and grounding | 1 | P0 | Pending | — | — | — |
| RAG-04.04 | Narrow a run to selected knowledge bases | 1 | P1 | Pending | — | — | — |
| RAG-05.01 | Citation minting and validation | 1 | P0 | Pending | — | — | — |
| RAG-05.02 | Citation contract in API, stream and history | 1 | P0 | Pending | — | — | — |
| RAG-06.01 | Knowledge screen | 1 | P0 | Pending | — | — | — |
| RAG-06.02 | Citation chips and source sheet | 1 | P0 | Pending | — | — | — |
| RAG-07.01 | Erase and export include knowledge | 1 | P0 | Pending | — | — | — |
| RAG-07.02 | Orphan sweep and reconciliation | 1 | P1 | Pending | — | — | — |
| RAG-07.03 | Backup and restore drill covers knowledge | 1 | P1 | Pending | — | — | — |
| RAG-08.01 | Retrieval and citation eval harness | 1 | P0 | Pending | — | — | — |
| RAG-08.02 | Knowledge security test suite | 1 | P0 | Pending | — | — | — |
| RAG-08.03 | Knowledge telemetry and leak scan | 1 | P1 | Pending | — | — | — |
| RAG-08.04 | Reference stack, documentation and runbooks | 1 | P1 | Pending | — | — | — |
| RAG-08.05 | v1.1.0 release verification | 1 | P0 | Pending | — | — | — |
| RAG-09.01 | Optional reranker providers | 2 | P1 | Pending | — | — | — |
| RAG-09.02 | Keep verified roles in Principal | 2 | P1 | Pending | — | — | — |
| RAG-09.03 | Grants API and UI | 2 | P1 | Pending | — | — | — |
| RAG-09.04 | Re-index to a new index profile | 2 | P1 | Pending | — | — | — |
| RAG-09.05 | Nightly retrieval regression gate | 2 | P1 | Pending | — | — | — |
| RAG-09.06 | Load test for ingestion and search | 2 | P1 | Pending | — | — | — |
| RAG-09.07 | Link feedback to citations | 2 | P2 | Pending | — | — | — |
| RAG-09.08 | Multilingual text search evaluation | 2 | P2 | Pending | — | — | — |
| RAG-10.01 | Outbound URL safety for ingestion fetchers (extends #364 and #366) | 3 | P0 | Pending | — | — | — |
| RAG-10.02 | Web page ingestion | 3 | P2 | Pending | — | — | — |
| RAG-10.03 | GitHub repository sync | 3 | P2 | Pending | — | — | — |
| RAG-10.04 | MCP document connectors | 3 | P2 | Pending | — | — | — |
| RAG-10.05 | OpenAI-compatible chat model provider | 3 | P2 | Pending | — | — | — |
| RAG-11.01 | `query_table` over uploaded tables | 4 | P2 | Pending | — | — | — |
| RAG-11.02 | `research_web` tool | 4 | P2 | Pending | — | — | — |
| RAG-11.03 | Mutating knowledge tools with approval | 4 | P2 | Pending | — | — | — |
| RAG-11.04 | `search_repository` tool | 4 | P2 | Pending | — | — | — |
| RAG-11.05 | Optional plan-and-verify retrieval subgraph | 4 | P2 | Pending | — | — | — |
| RAG-12.01 | Semantic recall over memory notes | 5 | P2 | Pending | — | — | — |
| RAG-12.02 | Sandboxed code execution evaluation | 5 | P2 | Pending | — | — | — |
| RAG-12.03 | GraphRAG trial | 5 | P2 | Pending | — | — | — |
| RAG-12.04 | External vector store benchmark | 5 | P2 | Pending | — | — | — |
| RAG-12.05 | Organisation knowledge spaces | 5 | P2 | Pending | — | — | — |

## Change log

| Date | Change | By |
| --- | --- | --- |
| 2026-11-03 | RAG-02.01 Done (#424, #425). RAG-02.02 In progress: part 1 (input checks, output schema, plain-text parser) | Claude session |
| 2026-11-03 | RAG-02.01 part 1 merged (#424); part 2 (`neuron-worker`) in a PR with AC1, AC2 and AC4 tests; ADR 0014 amended (worker in the API image until RAG-02.02; readiness ignores the worker) | Claude session |
| 2026-11-03 | Backlog re-analysed; tracker drift fixed (RAG-01.03 Done, E02 counts). RAG-02.01 In progress: part 1 (queue schema, grants, transactional defer); decisions on queue placement, the core dependency and the index policy recorded | Claude session |
| 2026-11-03 | RAG-01.02 Done (#420). RAG-01.03 In progress; `obstore` moved to core dependencies (ADR 0014 amended), `local` blob store opt-in for staging/production. RAG-02.01, RAG-03.01, RAG-04.01 unblocked | Claude session |
| 2026-11-03 | RAG-01.01 Done (#419). RAG-01.02 In progress; decisions on RLS scope, worker rights, profile seeding recorded | Claude session |
| 2026-11-03 | RAG-02.03 Done (#414). RAG-E01 analysed; issues #415–#418 created; #408 decisions recorded; RAG-01.01 In progress; RAG-01.02 Blocked on it | Claude session |
| 2026-11-03 | E00 confirmed on `main`, #398–#402 closed. RAG-E02 analysed; issues #408–#413 created; RAG-02.01, 02.02, 02.04, 02.05 Blocked on E01; RAG-02.03 In progress | Claude session |
| 2026-11-02 | RAG-00.04: dependency and image plan in ADR 0014; Done when #406 merges | Claude session |
| 2026-11-02 | RAG-00.02: spike record and ADR 0014 answers; Done when #405 merges | Claude session |
| 2026-11-02 | RAG-00.03: corpus, schema and test; Done when #404 merges | Claude session |
| 2026-11-02 | Owner accepted ADR 0014: RAG-00.01 Done when #403 merges | Claude session |
| 2026-11-02 | RAG-00.01: ADR 0014 written as Proposed; amendment notes in ADR 0001/0002/0005; v1.1.0 in the roadmap. Status Partial until the owner accepts | Claude session |
| 2026-11-03 | E00 review: #364/#366 are fixed (#395), not closed as not planned; eval fixture path moved to `tests/fixtures/`; E00 approved for issue creation | Claude session |
| 2026-11-02 | Backlog drafted from the three research reports; tracker created; all stories Pending; repository checked at `4d5a6b5` | Claude session |
