# ADR 0014: Knowledge Engine (v1.1.0)

## Status

Accepted (2026-11-02, owner approval). Proposed the same day. Not implemented yet. It amends
ADR 0001, 0002 and 0005 (see Amendments), so Phase 1 stories
(`docs/product/NEURON_RAG_PRODUCT_BACKLOG.md`, RAG-E01 to RAG-E08) may now add retrieval, a job
queue and the `knowledge` schema as defined here. The open questions below stay open until the
spike (RAG-00.02) records its numbers.

Inputs: the three research reports in `docs/research/rag/`. Where they disagree, this ADR follows
the resolutions in §4 of `claude_neuron_consolidated_rag_research.md` ("the research" below).
Backlog story: RAG-00.01 (#399).

## Context

Neuron has no retrieval. `AGENTS.md` and ADR 0001 forbid retrieval, queues, custom persistence
and subgraphs without a concrete requirement and an ADR. The requirement is the v1.1.0 release
"Personal Knowledge": a signed-in user creates private knowledge bases (KBs), uploads documents,
and gets answers that cite pages of those documents, with no way to read another user's content.

What exists and is reused (checked against `main` at `e3bc153`):

- Identity reaches tools only through the run's `context`, an `AuthorizationContext` with
  `permissions` and the HMAC `owner_key` (`security/authorization.py`); `memory/tools.py` reads it
  from `runtime.context`. `AuthorizationContext` has no roles today: roles are mapped to scopes
  and dropped (`security/auth.py`).
- `ToolSpec.taints_run` (`tools/registry.py`): after a tainting tool runs, gated tools need
  approval (security review amendment R2, ADR 0009).
- `_final_answer` (`graphs/main_graph.py`) recomputes `used_tools` from the tool calls that ran.
- Versioned SQL migrations (`persistence/migrations.py`), a migrator/app role split
  (`persistence/roles.py`, ADR 0008 decision 15), stable start-up check codes
  (`persistence/startup_checks.py`), a token ledger (`persistence/token_budget.py`).
- Outbound URL safety for MCP (`security/egress.py`, #364, #366); no ingestion fetcher uses it yet.
- The reference stack runs `postgres:16` without pgvector.

## Decisions

### K1. The engine runs inside Neuron, on Neuron's Postgres

A `knowledge` schema in Neuron's existing database holds KBs, documents, chunks and embeddings.
Code lives in `src/neuron_agent/knowledge/` (`service.py`, `authorization.py`, `blobs.py`,
`parsing.py`, `providers.py`, `chunking.py`, `retrieval.py`, `citations.py`, `jobs.py`,
`tools.py`). Routes stay in `api/`, migrations in `persistence/migrations.py`, settings in
`config/settings.py`. Retrieval combines pgvector similarity and Postgres full-text search,
fused with reciprocal rank fusion, in one SQL transaction. Row-level security on `chunks` and
`embeddings`, keyed on a transaction-scoped `SET LOCAL neuron.kb_ids`, repeats the SQL filter;
it works because the app role does not own the tables. Original files go to a `BlobStore`
(local volume or private S3-compatible bucket) under write-once random keys.

Rejected: the NVIDIA RAG Blueprint as a service or an in-process import (its servers have no user
identity, its jobs are in memory, and it pins `openai<2.0` while Neuron needs `openai>=3.6.0`); a
dedicated vector database first (Qdrant, Milvus and others: a second datastore and ACL model
without a measured need; revisit only on a benchmark, RAG-12.04).

### K2. Parsing runs out of process, behind `DocumentParser`

The default parser is a docling-serve container (CPU) reachable only from the worker, with no
network egress. The worker sends bytes, never URLs, with a timeout, and validates the parser's
output against a schema. Plain text and Markdown are parsed in the worker. NV-Ingest is an
optional GPU parser behind the same interface.

Rejected: Docling inside the API process (ML models and memory in the request path, and the
image-layout tests); Unstructured as the default; MinerU and Marker (licence and weight terms
need review; Docling covers the need); PyMuPDF (AGPL).

### K3. Embeddings are `halfvec` rows per index profile

`knowledge.embeddings(chunk_id, profile_id, kb_id, embedding halfvec)` with one partial HNSW
expression index per profile. A KB uses one active profile; changing model or dimensions is a
re-index to a new profile (RAG-09.04), never a schema change, and one search never mixes
profiles. Small allowed sets use an exact scan through the `(profile_id, kb_id)` index; large
ones use HNSW with `hnsw.iterative_scan = relaxed_order`. The threshold is a setting whose
default the spike decides.

Rejected: a `vector(2048)` column (pgvector HNSW indexes `vector` only up to 2,000 dimensions;
`halfvec` indexes up to 4,000 and halves storage); mixed profiles in one search.

Embeddings go through Neuron's `EmbeddingProvider`, built on LangChain `Embeddings` (NVIDIA for
development, TEI or OpenAI-compatible for self-hosting, a fake for tests), like the chat model
factory. Rejected: LiteLLM (a second routing layer beside `models/factory.py`). Reranking is off
until evals show a gain (RAG-09.01).

### K4. Durable jobs on Postgres; the document row is the public status

A `neuron-worker` console script (same Dockerfile and lock, a `worker` build target with the `worker` extra; see [Dependencies and images](#dependencies-and-images-rag-0004)) runs ingestion, delete, re-index and
sweep jobs with Procrastinate, subject to the spike; PGQueuer is the named fallback, and an own
lease table only if both fail. The upload inserts the document (`queued`) and defers the job in
the same transaction. Each step is idempotent per `(doc_id, profile_id)`. There is no public job
resource: `knowledge.documents.status` is what the API reports. Delete is tombstone-first:
retrieval joins only `status = 'ready' AND deleted_at IS NULL`, then a job purges chunks,
embeddings and the blob.

Rejected: an own job table first (rebuilds retries, backoff and scheduling); Celery with Redis;
Temporal, Prefect, Airflow (new infrastructure); a separate `/v1/ingestion-jobs` resource (a
second ACL surface).

### K5. Identity comes only from the runtime `AuthorizationContext`

Knowledge tools read the owner key and permissions from `ToolRuntime.context`, as
`memory/tools.py` does. The model sees only `query`, optional `kb_ids` and `limit`. Allowed KBs
are resolved server-side and any requested ids are intersected with them; a foreign id behaves as
not found. The tools need `tools:search_knowledge`; the routes need `knowledge:read`,
`knowledge:write` and (Phase 2) `knowledge:admin`. Phase 1 KBs are owner-only. Role grants come
in Phase 2, after `Principal` keeps verified roles (RAG-09.02).

Rejected: `RunnableConfig.configurable` with `InjectedToolArg` (on the Agent Server path
`configurable` is client-influenced); identity as a tool argument.

**Agent Server limitation.** Knowledge tools are offered on the FastAPI path only, like memory
(ADR 0009). The graph exported to `langgraph.json` does not get them.

### K6. Citations are minted by the server and validated per run

`search_knowledge` returns results with server-minted `cite_id`s. `AgentAnswer` gains
`citations: list[str]`; `_final_answer` keeps only ids a knowledge tool returned in this run, as
it already does for `used_tools`, and counts the rejected ones. Validated citations (document id,
chunk id, title, page range, optional bounding box; no excerpt text) are stamped on the final
`AIMessage.additional_kwargs`, so history keeps them. `AgentResponse`, the SSE `final` event and
`ThreadMessage` gain an optional `citations` array with `citation_schema_version: 1` and a
`grounded` flag; old clients ignore it. The chunk endpoint re-checks access on every call.

Rejected: sources written by the model; a separate citation table.

### K7. Retrieved content taints the run

`search_knowledge` and `get_document_excerpt` set `taints_run=True`, so any gated tool after them
needs approval. Results are framed as data in a delimited JSON block with `<` escaped, reusing
the pattern of `render_notes()`. Below a score floor the tool returns `no_relevant_results`, and
the system prompt requires the answer to say so (abstention). Upload is a user action, never a
model tool.

Rejected: LLM-Guard or any classifier as the security boundary (bypassable; LLM-Guard's last
release is 2025-05). A scanner may be added later as a logged signal only.

### K8. Processing locality is a KB setting

Each KB has `processing = hosted | self_hosted`. Operators can forbid `hosted`; staging and
production settings validation refuses a hosted embedding provider when policy is self-hosted
only. The UI states where content is processed. Embedding tokens are recorded in the existing
token ledger under a separate kind, and ingestion quotas (bytes, pages, documents, concurrent
jobs) are checked before work is queued.

**Amended by RAG-02.05 (2026-11-04, owner decision):** embedding tokens are recorded per
document in `knowledge.documents.embedding_tokens`, not in `neuron_token_ledger`. The ledger is a
rolling budget window, pruned after `APP_USER_TOKEN_BUDGET_WINDOW_SECONDS`, so it cannot keep a
record; and the worker holds no rights in `public`. The worker adds the estimated tokens it sent
(heading path and text of each chunk, three UTF-8 bytes a token) when a document becomes
`ready`, so a re-run is charged again; a user's total is the sum over their documents. It is
not counted against the chat budget. It is an accounting estimate, not a control: text that
tokenises denser than three bytes a token is under-counted, and an attempt that fails after
calling the provider records nothing. The quotas, checked at upload (RAG-02.05 part 1), are
what bound spend.

Rejected: implicit hosted processing (every chunk would leave Neuron's boundary without a
decision).

### Also rejected

LangMem, Mem0, Letta (model-extracted memories conflict with ADR 0009 decision 7); Phoenix,
OpenInference, Langfuse (licence or a second telemetry vocabulary beside
`observability/semconv.py`); a second agent framework; the Blueprint frontend, Dify and Open WebUI
(duplicate UI, licence clauses). The full list with reasons is §11 of the research.

## Product scope of v1.1.0

In: private KBs; upload of PDF, DOCX, Markdown and text; durable ingestion; hybrid retrieval;
`list_knowledge_bases`, `search_knowledge` and `get_document_excerpt` tools; validated citations
in the API, stream and history; tombstone delete; erase and export include knowledge; the
Knowledge screen with citation chips; the processing locality setting. The feature is behind
`APP_KNOWLEDGE_ENABLED` (default off) until v1.1.0 is released.

Out: sharing and role grants, reranking, re-index (v1.2.0, RAG-E09); web, GitHub and MCP
sources (RAG-E10, blocked on RAG-10.01 reusing `security/egress.py`); mutating knowledge tools,
`query_table`, `research_web`, a retrieval subgraph (RAG-E11, each needs its own requirement, and
mutating tools an ADR 0003 amendment); GraphRAG, an external vector store, organisation spaces
(RAG-E12).

## Release gate targets (measured by RAG-08.01, RAG-08.02 and RAG-08.05)

- Zero cross-user results in the knowledge security suite.
- At least 90% of answerable eval questions cite a correct page (citation precision against
  the labelled corpus of RAG-00.03). Recall@5 is recorded as the baseline v1.2.0 must not
  regress.
- Unanswerable eval questions abstain.
- A job whose worker is killed mid-run completes exactly once.
- All existing tests stay green; `make format lint typecheck test security` passes.

## Security boundary

Strongest first: authorisation inside the retrieval query, with RLS repeating it (K1, K5); taint
and approval (K7); citation validation (K6); framing (K7); ingestion hardening (MIME sniffing;
size, page and decompression limits; no archives or macros; encrypted PDFs rejected; parser
without egress); processing locality (K8); telemetry hygiene (ids, counts, stages and timings
only, never queries, chunk text, file names or vectors). Originals are served only as
`Content-Disposition: attachment` with `X-Content-Type-Options: nosniff`.

Requirements the Phase 1 stories must meet (from the security review of this ADR):

1. **Roles and RLS.** No runtime role has `BYPASSRLS`: `persistence/roles.py` already refuses
   one. The worker uses the app role, or a third role that passes the same `role_problems`
   checks, and sets `neuron.kb_ids` per job. Policies have `WITH CHECK` as well as `USING`.
   An unset `neuron.kb_ids` (`current_setting('neuron.kb_ids', true)` is NULL) returns no rows.
2. **Owner predicate everywhere.** Every query on `bases`, `grants` and `documents` filters on
   the caller's `owner_key` (or, from Phase 2, a grant). RLS is defence in depth on `chunks` and
   `embeddings` only, where the volume is. RAG-01.02 records whether `bases` and `documents` get
   RLS too.
3. **Citations.** A `cite_id` is bound to the run and the owner that minted it, by
   `search_knowledge` or `get_document_excerpt`. `grounded` is computed by the server from the
   validated citations, never taken from the model. Titles and file names are user-controlled,
   so the API, the stream and the web app treat them as plain text. The chunk endpoint returns
   404 for tombstoned documents.
4. **Fixed endpoints, not `egress.py`.** `security/egress.py` refuses private addresses and
   is for user-influenced URLs (RAG-E10). The parser and self-hosted embedding endpoints are
   operator-configured, validated when settings load, and not routed through it.
5. **Audit.** Knowledge base create and delete, document upload and delete, and knowledge erase
   and export emit audit events through `observability/audit.py`, with ids and counts only.
6. **Downloads.** Originals are served with `Content-Type: application/octet-stream` (never the
   uploaded MIME type), a sanitised `filename*`, `Content-Disposition: attachment`,
   `X-Content-Type-Options: nosniff` and `Content-Security-Policy: sandbox`.
7. **Quotas.** Limits per `owner_key` are enforced in code: number of KBs, total stored bytes,
   documents, pages and concurrent ingestion jobs. Search routes are rate-limited like the agent
   routes.
8. **Permissions.** `knowledge:read`, `knowledge:write` and `tools:search_knowledge` are added
   to `DEV_PERMISSIONS` and to the role-to-scope defaults with the routes that need them.
   Production grants them only through configured scopes.

Threat model additions (`docs/security/threat-model.md`, with RAG-08.02): cross-user retrieval,
poisoned documents, fabricated citations, stored XSS through originals, parser exploits and
resource exhaustion, data egress to hosted model APIs, blob and database drift after a restore.
The required tests are the table in §10 of the research.

## Open questions, decided by the spike (RAG-00.02)

Answered on 2026-11-02 with the numbers, hardware and commands in
[the spike record](../releases/v1.1.0-spike.md). The working default before the spike is in
brackets.

1. Docling CPU quality on tables and scanned pages, or a GPU parser needed? (CPU) **CPU.**
   docling-serve-cpu v1.38.2 parsed 0.61 PDF pages/s on 4 vCPU with a 4.7 GiB peak, offline
   (`--network none`). All 43 evidence passages were extracted, including OCR of the scanned
   page; 39 were on the expected page. Plain text has no page provenance, so the worker splits
   RFC-style `.txt` on form feeds itself.
2. Embedding dimensions for `llama-nemotron-embed-1b-v2`: 2,048 or 1,024, by recall@5? (2,048)
   **1,024.** That model is retired from the NVIDIA API catalog (HTTP 410); its successor
   `nvidia/nemotron-3.5-embed-1b` scored recall@5 0.918 at both 1,024 and 2,048 on the eval
   corpus, so the default profile is `nemotron-3.5-embed-1b` at 1,024.
3. The allowed-chunk count above which HNSW with iterative scan beats an exact scan. (20,000)
   **10,000**, the default for an exact-scan threshold setting in RAG-04.01, with
   `hnsw.ef_search = 100`. HNSW is faster from about 2,000 chunks, but below about 5,000 it can
   return too few rows for off-topic queries; the exact scan costs at most about 51 ms p95 at
   10,000. The planner does not pick HNSW for the filtered query by itself, so retrieval chooses
   and forces the path.
4. Procrastinate or PGQueuer: exactly-once completion after a killed worker, under Neuron's pool
   settings and roles? (Procrastinate) **Procrastinate**, with a periodic stalled-job sweep
   (`get_stalled_jobs` + `retry_job`), which 3.10.0 does not run by itself. After `SIGKILL`
   each job completed exactly once and `SIGTERM` drained cleanly. PGQueuer also passed. Both are
   at-least-once, so ingest steps stay idempotent (K4). The lease-table fallback is not needed.
5. NVIDIA API catalog terms, data handling and pricing for production document processing, or
   TEI as the production default? (NVIDIA for development only) **NVIDIA for development only.**
   The trial terms (§1.2) forbid production use without a separate subscription and publish no
   per-token price. TEI (Apache-2.0) is the production default.

The spike also found:

- pgvector is not a trusted extension: `neuron_migrator` cannot run `CREATE EXTENSION vector`.
  A superuser or the platform operator creates it before migrations (RAG-01.01).
- Parallel HNSW builds need more than Docker's default 64 MB `/dev/shm` (`shm_size`), or
  `max_parallel_maintenance_workers = 0` (RAG-01.01).

## Dependencies and images (RAG-00.04)

Decided on 2026-11-02. RAG-01.01 and later stories add these exact versions and digests; a newer
version needs the same checks recorded in its PR.

**Worker dependencies are an optional extra, `neuron-agent[worker]`, in the same `uv.lock`.**
The API image keeps `uv sync --no-dev` without the extra; the worker is a second build target of
the same Dockerfile that adds `--extra worker` and the `neuron-worker` entrypoint. With the extra
in the lock, the API's runtime environment has exactly the same files (141.3 MB); the worker's is 308.4 MB
(+167.1 MB: pandas 43 MB, numpy 56 MB, obstore 16 MB, pillow 20 MB, lxml 12 MB). Rejected: one
image with lazy imports, which would add those 167 MB and the parser libraries' attack surface to
the API image (about 378 MB for the v1.0.0 image). The resolution is on the unmerged branch `RAG-00.04-lock`:
`uv lock` resolves 197 packages with no conflict with `openai>=3.6.0`, and
`uv export --no-dev` is unchanged from the base branch.

| Package | Version (released) | First release | Licence | Role |
| --- | --- | --- | --- | --- |
| `procrastinate` | 3.10.0 (2026-09-23) | 2019-08-15 | MIT | Job queue (K4), worker and migrations |
| `pgvector` | 0.5.1 (2026-10-09) | 2021-06-12 | MIT | psycopg types for `halfvec` |
| `docling-core[chunking-openai]` | 2.105.0 (2026-10-27) | 2024-07-12 | MIT | `DoclingDocument` validation and `HybridChunker` |
| `obstore` | 0.12.1 (2026-10-27) | 2024-10-24 | MIT | `BlobStore` for S3-compatible and local storage |
| `langchain-openai` (already a dependency) | 1.7.3 | 2024-01-05 | MIT | `EmbeddingProvider` for the NVIDIA API catalog and TEI |

Every direct package was released in 2026 and is older than the 90-day `new-dependencies` rule.
The extra brings 29 more transitive packages; none is GPL or AGPL. The licences are BSD, MIT,
ISC, PSF, Apache-2.0, MIT-CMU (pillow), 0BSD, Zlib and CC0 parts (numpy) and MPL-2.0 AND MIT
(tqdm, file-level copyleft, unmodified),
recorded with versions and dates in the RAG-00.04 PR.

- **Job queue.** **Amended by RAG-02.01 (2026-11-03):** `procrastinate` is a core dependency,
  pinned to 3.10.0, not part of the `worker` extra. `setup` runs from the API image and installs
  Procrastinate's schema from the installed library (migration 25), and the API queues a job in
  the transaction that inserts its document (RAG-03.02). The API environment gains four
  pure-Python packages (`procrastinate`, `croniter`, `python-dateutil`, `six`). The queue tables
  live in the `knowledge` schema, so the worker role needs no rights in `public` and operators no
  second superuser step; Procrastinate's functions get a pinned `search_path`. A Procrastinate
  upgrade adds its migration files as new migrations: a test fails while the installed version
  differs from the one migration 25 installs. Rejected: vendoring the schema SQL (it would drift
  from the worker's library), and a `procrastinate` schema (the migrator cannot create one).
- **Worker process.** **Amended by RAG-02.01 (2026-11-03):** `neuron-worker` ships in the API
  image, run with another command, until a worker-only dependency arrives (RAG-02.02's parser
  client): every package it uses today is already in the API's dependencies, so the `worker`
  build target and extra add nothing yet. It connects as the worker role with its own pool,
  sweeps jobs of workers without a heartbeat for `APP_WORKER_STALLED_SECONDS` back into the
  queue (one sweep at a time, under an advisory lock, so a stale list never requeues a job that
  is running again; a job that keeps killing its worker fails after 5 attempts), drains for `APP_WORKER_DRAIN_SECONDS` on `SIGTERM` (jobs still running are released to
  be retried) and keeps a health file fresh for its container's health check. **The API's
  `/health/ready` does not report the worker**: chat does not need it, and a stopped worker
  only delays ingestion, which the document status shows; the worker's health is its own
  container's.
  **Amended by RAG-02.02 (2026-11-04):** the parser client is `httpx2`, already a core
  dependency, so RAG-02.02 brings no worker-only package either. The `worker` extra and build
  target arrive with `docling-core` (RAG-02.03's chunker), the first package only the worker needs.
- **Embedding client.** No new package. `langchain-openai`'s `OpenAIEmbeddings` called the NVIDIA
  API catalog with `dimensions=1024`, `check_embedding_ctx_length=False` and
  `input_type` passed in `extra_body` (the API rejects a request without it, so it is honoured);
  TEI documents the same OpenAI-compatible `/v1/embeddings` route; it was not run here, so the
  TEI profile story checks it, including `dimensions`. Rejected: `langchain-nvidia-ai-endpoints` 1.5.0
  (MIT), a second client with its own `aiohttp` stack for what one client already does.
- **S3 client.** `obstore`: one small Rust-backed package with async calls and local-filesystem
  and S3 stores, so `LocalBlobStore` and `S3BlobStore` share one API and no `botocore` is needed.
  Rejected: `boto3` (heavier, sync), and `minio` 7.2.20 and `aioboto3` 15.5.0, whose last
  releases are from 2025.
  **Amended by RAG-01.03 (2026-11-03):** `obstore` is a core dependency, not part of the
  `worker` extra, because the API writes originals at upload (RAG-03.02) and reads them for
  download (RAG-03.04); the API image grows by about 16 MB. The alternative, a plain-filesystem
  path in the API, would leave the API unable to use the `s3` backend. `LocalBlobStore` with
  `APP_KNOWLEDGE_BLOB_BACKEND=local` fails settings validation in staging and production with
  knowledge on, unless `APP_KNOWLEDGE_BLOB_LOCAL_ALLOWED=true` (one node with a persistent
  volume).
- **Chunking.** `HybridChunker` needs a tokenizer. The `chunking-openai` extra uses `tiktoken`,
  already in the lock, instead of `chunking`, which pulls `transformers`. tiktoken counts are an
  approximation of the embedding model's tokens, so the token limit keeps a margin (RAG-02.03),
  and the image must ship its encoding file because the worker has no general egress. Of the 10
  packages this extra adds, five were last released before 2026 (`mpire` 2024-05, `semchunk`
  2025-10 and three tree-sitter grammars); if that is not acceptable, the fallback is
  docling-core's `HierarchicalChunker` with Neuron's own token split, which drops all 10. Other
  transitive packages released before 2026 are small, stable libraries (`six`, `defusedxml`,
  `python-dateutil`, `colorama`, `jsonref`, `mdurl`, `shellingham`).
  **Amended by RAG-02.04 (2026-11-04):** the owner chose the fallback (#408), and it is Neuron's
  own chunker (`knowledge/chunking.py`, profile `chunker` `neuron-headings-v1`) rather than
  docling-core's `HierarchicalChunker`. The parsers already return one normalised
  `ParsedDocument`, which keeps the headings, levels and pages the chunker needs; the
  `DoclingDocument` is not kept, and plain text and Markdown never had one, so
  `HierarchicalChunker` would need docling-core, the raw Docling JSON and a second path for text.
  The chunker closes a chunk at each heading, records the heading path on every chunk, fills a
  chunk with the blocks under one heading up to `APP_KNOWLEDGE_CHUNK_MAX_TOKENS` (400), and
  splits a longer block at lines, then spaces, then characters. Tokens are estimated as one per
  three UTF-8 bytes, above what embedding tokenizers count for Latin-script text (about four bytes a token; a CJK character, three bytes, can be more than one token, which the 400 default leaves room for below the model's context), because the worker
  has no tokenizer file and no egress (`tiktoken` would download one). No new dependency, so the
  `worker` extra and build target still wait for a worker-only package.

| Image | Pin (multi-arch index digest) | Notes |
| --- | --- | --- |
| `pgvector/pgvector:pg16` | `sha256:0dd3149a06e4579a0d70d8fef9945636cd514005e7237deb27f9b67886f8dc4f` | PostgreSQL 16.15, extension `vector` 0.8.7 (`iterative_scan` needs 0.8.0) |
| `quay.io/docling-project/docling-serve-cpu:v1.38.2` | `sha256:7a480a1604fa3b42efeddc7db9527690d9f9bc903226136013e2bfe6b1a4dfb0` | 7.57 GB with models, the image the spike measured |


## Amendments

This ADR amends:

- **ADR 0001**: retrieval and a background worker with a job queue are now in scope, as defined
  above.
- **ADR 0002**: Neuron owns domain persistence for knowledge (the `knowledge` schema and blobs).
- **ADR 0005**: rejected run queues stay rejected; the job queue here is for ingestion only and
  does not queue agent runs.

### Amendment: reranking (RAG-09.01, 2026-11-12)

Hybrid search may rerank its fused top 40 (or `k`, if larger) before keeping the best `k`
(`knowledge/reranking.py`). The reranker only reorders passages the authorised SQL already
returned, so it adds no access path. It is a new hosted destination for the query and passages
(NVIDIA's retrieval API, the same provider as the default embeddings): the processing policy and
each base's `processing` setting apply to it as to embeddings, and a search over any base that
forbids hosted processing is not reranked. Any error or timeout
(`APP_KNOWLEDGE_RERANKER_TIMEOUT_SECONDS`, 3 s) keeps the RRF order and reports
`reranked: false`. On by default with NVIDIA embeddings and a key, from the measured gain
(`docs/releases/v1.2.0-rerank-eval.md`).

### Amendment: sharing by role (RAG-09.03, 2026-11-12)

Requirement 2's "owner predicate everywhere" becomes "the caller's grants everywhere". A base is
visible to its owner (the `owner` grant written with it) and to the holders of a verified token
role with a `role` grant on it (`read`, `write` or `admin`; roles from RAG-09.02, ADR 0006
amendment). `allowed_kbs` reads both in the same transaction as the statement it guards, and
every query on `bases`, `documents`, `chunks` and `embeddings` filters on its result instead of
on the owner key, so revoking a grant counts from the next request; nothing is cached. Roles
alone never grant access: the caller still needs an owner key, and the route its permission.

- **Access.** `read`: list, search, cite and download. `write`: also upload and delete
  documents. `admin`: also rename (and, in the grants API, manage role grants). Deleting a base
  stays with its owner, as do export and erase of the base.
- **Errors.** A base the caller cannot see is `404`, as before. One they can see but not change
  that way is `403` (`knowledge_access_denied`): its existence is no secret from them.
- **Role names** are the token's values as they are, with no issuer prefix: one issuer is
  accepted (ADR 0006). A second issuer would need prefixed grant subjects first.
- **Grants API** (`GET`/`PUT /v1/knowledge/bases/{kb_id}/grants`, `knowledge:admin`): the owner
  or an `admin` role replaces the role grants, at most 50 per base. Each change is audited as
  `knowledge_grant_changed` with the actor, base, role and access level. A grant's role is a name
  the base's admin chose, not a user's token roles, which stay unlogged (RAG-09.02).
  An `admin` role may revoke any role grant, its own included, but never the owner's access.
  Role names may not contain control or invisible characters.
- **Quotas** stay per uploader (RAG-02.05): a member's upload to a shared base counts against
  the member.
- **Erase** (RAG-07.01): erasing a user's knowledge removes their bases with every upload in
  them, members' included, and their own uploads to bases shared with them. Export still covers
  the user's own bases only (with members' document metadata in them), not the user's uploads to
  others' bases: a follow-up.
- **Limits of revocation.** It is checked per request, not inside one: a grant revoked while an
  upload's transaction runs (milliseconds) does not stop that upload. Passages a member already
  received stay in their thread history; revocation stops new searches and excerpts only.

### Amendment: re-index to a new profile (RAG-09.04, 2026-11-12, owner decision)

K3 said a model or dimension change is a re-index into a new profile. Until now, profile 1 was
fixed in setup, ingestion and retrieval, and `setup` refused other settings
(`knowledge_profile_mismatch`). This amendment says how a change happens without mixing vector
spaces or stopping search.

- **One active profile for the deployment, swapped all at once.** The backlog says "the KB's
  active profile", but a search spans bases and embeds the query once, so per-base swaps would
  mix vector spaces in one search, which K3 rejects. Instead, every live base moves in one
  transaction:
  - the `building` profile becomes `active`;
  - the old profile becomes `retired`;
  - every base's `profile_id` is updated.

  At most one profile can be `building` (a partial unique index).
- **Two models while it runs.** The `APP_KNOWLEDGE_EMBEDDING_*` settings stay the active
  profile's model. The optional `APP_KNOWLEDGE_REINDEX_EMBEDDING_*` settings name the target:
  provider, model, dimensions, base URL, key and locality. Both the API and the worker get both
  sets.
  - A process maps a profile row to whichever configured model matches its provider, model and
    dimensions.
  - It embeds queries for the active profile, so the swap takes effect from the next search with
    no restart.
  - `setup` accepts settings in which either model matches the active profile.
  - Afterwards the operator moves the target settings into the main ones and removes the
    re-index settings (runbook).
  - A process that has no model matching the active profile searches by text only and logs
    `knowledge_profile_mismatch`, rather than embedding into the wrong space.
- **Operator command, no API.** `python -m neuron_agent.persistence.cli reindex start` runs as
  the migration role, because it needs DDL.
  - It inserts the next profile (`building`) and builds its partial HNSW index concurrently.
  - It defers one `reindex_kb` job for each live base.
  - It refuses to start if any live base's `processing` setting, or the operator's policy,
    forbids the target model. Such a base would otherwise lose meaning search after the swap.
    Refusing at start is the processing rule of K8.

  `reindex status` reports progress. `reindex cancel` stops a re-index (see failure below).
- **The job.** `reindex_kb` embeds every ready document's chunks with the target model and
  writes the embeddings under the new profile.
  - It is idempotent per `(doc_id, profile_id)`: documents already covered are skipped.
  - The worker scopes it to the base as it scopes ingestion (`neuron.kb_ids`, RLS).
  - The tokens it uses are recorded on each document, as a re-run's are (RAG-02.05). It is
    never refused for a member's quota: the re-index is the operator's choice.
- **Uploads during a re-index** are embedded for both the active and the building profile.
  - Ingestion's write transaction locks the profile rows it wrote for (`FOR SHARE`).
  - If the set of non-retired profiles changed while it was embedding, the job retries, so a
    document never ends up with only one profile's vectors.
- **The swap.** The job that finishes the last base attempts the swap; a periodic check retries
  it.
  - It locks the building profile (`FOR UPDATE`) and checks that every ready chunk of every live
    base has an embedding under it.
  - If any chunk is missing one, it defers `reindex_kb` for those bases and leaves the old
    profile active.
  - Because the lock is held while it checks, no ingestion can commit between the check and the
    swap.
- **Failure.** If a `reindex_kb` job exhausts its retries, or the operator cancels, the
  building profile becomes `retired` and the old profile stays active throughout.
  - Retired embeddings, after a failure or after a successful swap, are deleted in batches by a
    worker job.
  - The next `setup` drops the HNSW index of every retired profile.
- **Search** keeps using exactly one profile: the active one, as a literal in the query.
  Retrieval reads the active profile's id and dimensions in the transaction it searches in,
  instead of the constant `1`.
- **Roles.** The worker gains `UPDATE` on `index_profiles.status` and on `bases.profile_id`,
  for the swap. It gets no other new privileges, and the API's privileges are unchanged.
- **Audit.** `knowledge_reindex_started`, `knowledge_reindex_swapped` and
  `knowledge_reindex_failed` record the profile ids and the base and chunk counts, and no
  content.
- **Cost.** During a re-index, uploads are embedded twice, and the operator pays to embed
  every chunk once more.
- **Rejected:**
  - per-base swaps, which mix vector spaces in one search;
  - a new column beside the old one (a schema change per model, which K3 rejects);
  - stopping search during the build;
  - a public API for re-indexing (an operator task, with no user need).

### Amendment: text search language (RAG-09.08, 2026-11-13, owner decision)

- **Decision:**
  - Each base chooses its text search language at creation (`language`, one of Postgres's
    built-in text search configurations). The default stays `simple`.
  - The choice is stored as `bases.ts_config`. Every chunk's `tsv` is built with it, and the
    text channel queries the base with it, so it cannot change later. A base in another language
    is a new base.
  - Built-in full-text search stays: `pg_textsearch` BM25 is not adopted.
- **Measured.** `tests/integration/test_postgres_knowledge_multilingual.py` runs a synthetic set
  of 30 questions in 5 languages, each worded with other forms than its passage. The text
  channel alone, with recall@5 (equal to MRR here), finds:

  | Language | `simple` | Language's own config |
  | --- | --- | --- |
  | English | 0.00 | 1.00 |
  | German | 0.00 | 0.33 |
  | French | 0.00 | 0.67 |
  | Spanish | 0.00 | 0.83 |
  | Hindi | 0.00 | 0.83 |

  The figures are in `docs/releases/v1.2.0-gate/multilingual-fts.json`.
  - `simple` misses every case: the query requires every word, and none is folded.
  - The stemmers fold plurals and most noun forms, but not every verb form. In German,
    "reparierten" stems to `repariert` and "reparieren" to `repari`; French "inspectent" is not
    stemmed at all.
  - Dense retrieval and the reranker still find these passages in hybrid search. This table
    measures only the text channel.
- **Why not `pg_textsearch`:**
  - It supports PostgreSQL 17 and 18 only, and the stack runs `pgvector/pgvector:pg16`.
  - Adopting it means a major Postgres upgrade and a custom image with the extension built in.
  - It was not measured: no PostgreSQL 17 could be installed in the evaluation environment.
  - Revisit it with the PostgreSQL 17 upgrade, on this same set.
- **Rejected:** changing a base's language after creation (every chunk would be rebuilt);
  detecting the language per document (a mixed base would then need several configurations per
  query).

### Amendment: external sources (RAG-E10, 2026-11-13, owner decision)

- **Scope (v1.3.0).** Web pages (RAG-10.02) and a self-hosted OpenAI-compatible chat model
  (RAG-10.05), after the fetch control (RAG-10.01). GitHub sync (RAG-10.03) and MCP connectors
  (RAG-10.04) stay out until a product requirement exists. They also need two decisions first:
  how the GitHub token is scoped (one service token reaches every repository it can read, so an
  operator allowlist of repositories or per-user OAuth behind a token-vault ADR), and an
  `AGENTS.md` boundary change letting `knowledge/` use `tools/mcp`.
- **Who fetches.** Only the worker fetches, never the API. The API validates the URL's text
  (`https`, no credentials, `validate_safe_url`), records the document and queues the job.
  Fetched content is untrusted like uploaded files: it is parsed, chunked, framed and taints the
  run.
- **How it fetches.** Through one client built on `security/egress.py` (`PublicOnlyBackend`,
  #395). It resolves the host once, refuses any non-public address and connects to the address
  it checked, for every redirect hop too. In addition it:
  - accepts `https` only, on the first URL and every redirect;
  - ignores proxy settings from the environment, which would otherwise make the address check
    a check of the proxy;
  - caps redirects, body size and total time.
  A URL from a user gets no loopback exception in development, unlike an operator-configured
  MCP URL (`tools/mcp/urls.py`). Tests replace the resolver instead.
- **Provenance.** A web document keeps `source_type = 'web'` and its URL in `source_ref`, with
  the fetch time and the content hash (`sha256`) of the fetched bytes, which are stored as its
  blob like an upload. A web citation names the URL and fetch time instead of a page. Every chunk
  maps to one fetched version; fetching again makes a new version.
- **Extraction (RAG-10.02).** `trafilatura` 2.3.1 (Apache-2.0) is a core dependency, since the
  worker runs from the API image. It adds `lxml`, `lxml-html-clean`, `justext`, `courlan`,
  `htmldate`, `dateparser`, `babel`, `pytz`, `tld` and `tzlocal`. `HtmlParser` keeps the main
  text as Markdown, without navigation, comments, links or images. `text/html` is a stored type
  for fetched pages only; an upload is never accepted as HTML.
- **Self-hosted chat model.** Its base URL follows the rule for
  `APP_KNOWLEDGE_EMBEDDING_BASE_URL` (`https` in production, set by the operator), not the
  public-only rule: such servers sit on private networks, and the operator, not a user, chooses
  the address.
- **Rejected:** fetching in the API process (the API would hold a route out and block on remote
  servers); a second, URL-text-only SSRF check (it cannot see DNS rebinding); a loopback
  exception for user URLs.

## Consequences

- One more process (`neuron-worker`) and one or two more containers (docling-serve; an embedding
  server in self-hosted profiles) to deploy, monitor and back up. Restore must cover blobs.
- The reference stack and CI move to the `pgvector/pgvector:pg16` image. Without
  `APP_KNOWLEDGE_ENABLED`, Neuron still runs on plain `postgres:16` as in v1.0.0.
- New public contracts are additive: `/v1/knowledge/*` routes, an optional `knowledge_base_ids`
  on `AgentRequest` (narrows, never widens) and optional `citations` fields. Stream protocol
  version 1 is unchanged.
- Estimated effort (not measured): Phase 1 7–10 engineer-weeks, Phases 0–2 13–18.
