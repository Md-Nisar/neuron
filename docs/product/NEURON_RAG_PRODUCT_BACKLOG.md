# Neuron RAG product backlog (Knowledge Engine)

Status: **Draft for owner review**, 2026-11-02. No GitHub issues have been created from it yet.
Progress is tracked in [`RAG_IMPLEMENTATION_TRACKER.md`](RAG_IMPLEMENTATION_TRACKER.md).

## Sources and how this backlog was derived

The backlog consolidates the three research reports in `docs/research/rag/`:

| Report | Used for |
| --- | --- |
| `claude_neuron_consolidated_rag_research.md` | The baseline: architecture (§7), data model and query (§8), API, tools and citation contract (§9), security tests (§10), phases and KE-xxx backlog (§12), decision records K1–K8 (§13) |
| `chatgpt_neuron_consolidated_rag_research.md` | Lifecycle details (tombstones, `Idempotency-Key`, index profiles, reconciliation), the Phase 0 readiness list, risk register (§14–15) |
| `gemini_neuron_consolidated_rag_research.md` | `halfvec`, iterative HNSW scans, module placement, Phase 3–5 detail (§7) |

Where the reports disagree, this backlog follows the resolutions in §4 of the Claude report
(for example Procrastinate over an own job table, LangChain `Embeddings` over LiteLLM,
reranking off until evals show a gain). The research IDs `KE-xxx` (Claude) and `KN-xxx`
(ChatGPT, Gemini) collide and mean different things, so this backlog uses its own IDs and
lists the research ID each story came from.

Facts checked against the repository on 2026-11-03 (`main` at `89a3020`, after v1.0.0):

- `src/neuron_agent/knowledge/` does not exist; no RAG code has been written.
- #370 (MCP transport errors) is **fixed** in v1.0.0 (`CHANGELOG.md`). The research's KE-003 is done.
- #364 (SSRF: DNS resolution and redirect re-validation) and #366 (HTTPS-only fetch) are
  **fixed** on `main` by #395 (`89a3020`, listed under Unreleased in `CHANGELOG.md`) for MCP
  connections (`security/egress.py`). The research's KE-002 is only partly open: ingestion
  fetchers must reuse that control. That is story RAG-10.01, which blocks every story that fetches a URL.
- The reference stack uses `postgres:16` without pgvector (`docker-compose.reference.yml`).
- Permissions in `security/authorization.py` have no `knowledge:*` or `tools:search_knowledge` entry yet.

## Release scope (proposed, owner to confirm)

| Release | Phases | Epics | Outcome |
| --- | --- | --- | --- |
| **v1.1.0** "Personal Knowledge" | 0 and 1 | RAG-E00 to RAG-E08 | Private knowledge bases: upload, durable ingestion, hybrid retrieval, validated citations, delete, erase and export, Knowledge screen |
| v1.2.0 (proposed) | 2 | RAG-E09 | Rerank, re-index, role-shared knowledge bases, nightly retrieval gate, load test |
| Later, evidence-gated | 3, 4, 5 | RAG-E10 to RAG-E12 | External sources, specialised tools, platform features. Each needs measured evidence before it starts |

The research puts Phases 0–2 at 13–18 engineer-weeks (estimated, not measured), and Phase 1 alone at 7–10.

## Conventions

### IDs

- Epic: `RAG-Enn`, for example `RAG-E04`.
- Story: `RAG-nn.mm`, where `nn` is the epic number, for example `RAG-04.02`.
- IDs are never reused or renumbered. A dropped story keeps its ID and is marked `Dropped`.
- GitHub issue titles start with the ID in brackets: `[RAG-04.02] Knowledge agent tools`.
  The bracketed ID is what de-duplication matches on.

### Labels

| Label | Meaning | Exists today |
| --- | --- | --- |
| `epic`, `story` | Issue type | No, to create |
| `rag` | Part of this backlog | No, to create |
| `phase:0` … `phase:5` | Implementation phase | No, to create |
| `priority:p0`, `priority:p1`, `priority:p2` | Priority (P0 blocks the release of its phase) | Yes |
| `v1.1.0`, `v1.2.0` | Target release, as with earlier releases | No, to create |
| `security`, `frontend`, `testing`, `observability`, `documentation`, `deployment` | Area | Yes |

### Shared Definition of Done

Every story's Definition of Done includes these items, plus the story-specific items listed with it:

1. Every acceptance criterion is shown by a test that fails without the change.
2. `make format lint typecheck test security` passes; `make eval` passes where the story says so.
3. The PR stays under 400 changed lines, or is split; the PR template is filled in. Critical-tier
   paths (`security/`, `config/`, `tools/`, `prompts/`, `persistence/`, `api/`, `docs/decisions/`)
   get a `security-reviewer` run (`docs/AI_CODE_VERIFICATION.md`).
4. New dependencies are justified in the PR and pass the `new-dependencies` job.
5. No query text, chunk text, file names, file contents or vectors appear in logs, spans,
   metrics or audit events.
6. `CHANGELOG.md` (Unreleased) and the affected docs (`ARCHITECTURE.md`, `SECURITY.md`,
   `AGENTS.md`, `DEVELOPMENT.md`, ADRs) describe the change.
7. The issue checklist is ticked, the Project status is `Done`, and the tracker is updated.

### Module placement (from the research, to be confirmed by ADR 0014)

`src/neuron_agent/knowledge/` holds `service.py` (KnowledgeService), `authorization.py`,
`blobs.py`, `parsing.py`, `providers.py` (embedding and rerank), `chunking.py`, `retrieval.py`,
`citations.py`, `jobs.py` and `tools.py`. Routes stay in `api/`, migrations in
`persistence/migrations.py`, settings in `config/settings.py`, and the worker entrypoint is a
new console script `neuron-worker`.

---

## Epic summary

| Epic | Title | Phase | Release | Stories |
| --- | --- | --- | --- | --- |
| RAG-E00 | Readiness and decisions | 0 | v1.1.0 | 4 |
| RAG-E01 | Knowledge storage foundation | 1 | v1.1.0 | 3 |
| RAG-E02 | Durable ingestion pipeline | 1 | v1.1.0 | 5 |
| RAG-E03 | Knowledge API | 1 | v1.1.0 | 5 |
| RAG-E04 | Retrieval and agent tools | 1 | v1.1.0 | 4 |
| RAG-E05 | Server-validated citations | 1 | v1.1.0 | 2 |
| RAG-E06 | Knowledge in the web app | 1 | v1.1.0 | 2 |
| RAG-E07 | Data rights and lifecycle | 1 | v1.1.0 | 3 |
| RAG-E08 | Quality, security and release | 1 | v1.1.0 | 5 |
| RAG-E09 | Retrieval quality and sharing | 2 | v1.2.0 | 8 |
| RAG-E10 | External knowledge sources | 3 | later | 5 |
| RAG-E11 | Specialised knowledge tools | 4 | later | 5 |
| RAG-E12 | Platform and scale | 5 | later | 5 |

Total: 13 epics, 56 stories.

---

## RAG-E00 Readiness and decisions

**Phase 0 · v1.1.0 · P0.** Record the Knowledge Engine decisions and answer the open questions
with measurements before any production code lands.

Goal: ADR 0014 accepted, spike numbers recorded, eval and security datasets ready.
Exit gate: ADR accepted by the owner; the five open spike questions (Claude report §13) answered with numbers.
Out of scope: production code on `main`.

### RAG-00.01 ADR 0014: Knowledge Engine

- **Epic:** RAG-E00 · **Phase:** 0 · **Priority:** P0 · **Estimate:** 0.5 w · **Research:** KE-001, KN-001
- **Depends on:** none

**Story.** As the owner, I want the Knowledge Engine decisions recorded in an ADR, so that
later stories implement one agreed design. CLAUDE.md requires an ADR before retrieval, queues
or new persistence are added.

**Requirements**
- Records decisions K1–K8 (Claude report §13): in-process engine on Neuron Postgres with a
  `knowledge` schema and RLS; out-of-process parsing behind `DocumentParser`; per-profile
  `halfvec` embeddings with partial HNSW indexes; Procrastinate jobs (subject to the spike),
  with the document row as the public status; identity only from runtime `AuthorizationContext`;
  server-minted, run-validated citations; retrieved content taints the run; KB-level processing locality.
- Lists rejected alternatives with reasons (NVIDIA RAG as a service, a dedicated vector DB first,
  LiteLLM, LangMem, LLM-Guard as a boundary, `vector(2048)`).
- States the product scope of v1.1.0, the Agent Server limitation (knowledge tools are FastAPI-path only, like memory),
  and the measurable targets the release gate uses (recall@5, citation precision, zero cross-user results).
- Amends ADR 0001/0002/0005 where they forbid retrieval, queues or new persistence.

**Acceptance criteria**
- Given the ADR is merged, when a reader opens `docs/decisions/0014-knowledge-engine.md`, then it has status Accepted, the owner's decision date, and each of K1–K8 with rejected alternatives.
- Given ADR 0001/0002/0005 forbid retrieval or queues, when ADR 0014 is accepted, then each of them links to ADR 0014 as the amendment.
- Given the spike (RAG-00.02) is not finished, when the ADR is accepted, then the open questions are listed with "decided by the spike" and RAG-00.02 updates them.

**Technical tasks**
- [x] Write `docs/decisions/0014-knowledge-engine.md` from the research.
- [x] Add amendment notes to ADR 0001, 0002, 0005.
- [x] Add v1.1.0 to `docs/ROADMAP.md`.
- [x] Owner review and acceptance.

**Changes.** API: none. Database: none. UI: none. Docs: ADR 0014, ADR amendments, `docs/ROADMAP.md`.

**Security.** The ADR names the security boundary (authorisation inside the query, taint and approval, citation validation) and the threat model additions.

**Tests.** None (documentation). `pr-hygiene` and the docs checks pass.

**Definition of Done (additions).** ADR status Accepted with the owner's name and date.

### RAG-00.02 Phase 0 spike: parser, vectors, queue

- **Epic:** RAG-E00 · **Phase:** 0 · **Priority:** P0 · **Estimate:** 1–1.5 w · **Research:** KE-004, KN-004
- **Depends on:** RAG-00.01 (draft is enough), RAG-00.03 (corpus)

**Story.** As an engineer, I want measured answers to the open design questions, so that the
schema, index and queue choices are not guesses.

**Requirements**
- On a spike branch only (never merged to `main`), measure:
  1. Docling (docling-serve, CPU) quality on the corpus: tables, headings, scanned pages; pages per second and memory.
  2. Embedding dimensions: 2,048 versus 1,024 for `llama-nemotron-embed-1b-v2`, by recall@5.
  3. The allowed-chunk count at which HNSW with `hnsw.iterative_scan = relaxed_order` beats an exact scan.
  4. Procrastinate versus PGQueuer: recovery of a job from a killed worker, retries, graceful drain, under Neuron's pool settings and DB roles.
  5. NVIDIA API catalog terms, data handling and pricing for document processing, versus TEI as the default.
- Record the numbers, the hardware and the commands.

**Acceptance criteria**
- Given the spike ran, when the owner reads ADR 0014, then each of the five questions has a recorded answer with numbers or a cited source.
- Given a worker is killed mid-job in the queue test, when it restarts, then the chosen queue completes the job exactly once; if neither library passes, the ADR records the fallback (an own lease table).
- Given the exact-versus-HNSW measurement, when the threshold is chosen, then it is written as a default setting value for RAG-04.01.

**Technical tasks**
- [x] Spike branch with a throwaway docker compose (pgvector, docling-serve, worker).
- [x] Ingest the corpus; record parse quality per document class.
- [x] Recall@5 at 2,048 and 1,024 dimensions.
- [x] Exact versus HNSW latency and recall by allowed-set size.
- [x] Queue fault-injection tests for both libraries.
- [x] Review provider terms; record the default production embedding provider.
- [x] Update ADR 0014's open questions.

**Changes.** API, database, UI: none on `main`. Docs: ADR 0014 updated; spike record in `docs/releases/v1.1.0-spike.md`.

**Security.** The corpus must not contain personal or confidential data. Hosted embedding calls send corpus text to the provider; use only public documents.

**Tests.** Spike scripts only; no tests on `main`.

**Definition of Done (additions).** Spike record merged as documentation; spike branch left unmerged.

### RAG-00.03 Labelled eval corpus and knowledge security dataset

- **Epic:** RAG-E00 · **Phase:** 0 · **Priority:** P0 · **Estimate:** 1 w · **Research:** KE-005, KN-023
- **Depends on:** RAG-00.01

**Story.** As an engineer, I want a labelled corpus with expected answers and adversarial cases,
so that retrieval quality and isolation can be measured from the first ingestion.

**Requirements**
- 30–100 public, licence-compatible documents (PDF, DOCX, Markdown, text), including tables and at least one scanned PDF.
- At least 50 answerable questions with the expected document and page, at least 10 unanswerable questions, ACL cases (two users), and prompt-injection documents (hidden text, alt text, table cell, fake `cite_id`).
- A JSON format that follows the `tests/fixtures/eval_cases.json` conventions and has a JSON schema.
- Licence and source recorded for each document.

**Acceptance criteria**
- Given the dataset, when its schema check runs in `make test`, then every case validates and references an existing document.
- Given the counts, when the dataset is reviewed, then it has ≥50 answerable, ≥10 unanswerable, ≥4 ACL and ≥4 injection cases.
- Given any document, when its licence is checked, then it allows redistribution in this repository, or the dataset stores only a download URL and checksum.

**Technical tasks**
- [x] Select documents; record licence, source URL and SHA-256.
- [x] Write `tests/fixtures/knowledge_cases.json` and `tests/fixtures/knowledge_cases.schema.json`.
- [x] Write injection and ACL fixtures.
- [x] Add the schema validation test.

**Changes.** API, database, UI: none. Files: `tests/fixtures/knowledge_cases*.json`, `tests/fixtures/knowledge/`.

**Security.** Injection documents are inert data; they must never be ingested by a live environment's default KB.

**Tests.** Unit test that validates the dataset against its schema.

**Definition of Done (additions).** Counts above met; licences recorded.

### RAG-00.04 Dependency and image plan

- **Epic:** RAG-E00 · **Phase:** 0 · **Priority:** P0 · **Estimate:** 0.5 w · **Research:** ChatGPT Phase 0 tasks
- **Depends on:** RAG-00.02

**Story.** As a maintainer, I want the new dependencies and images chosen and pinned up front,
so that the API image stays free of parser and ML weight.

**Requirements**
- Choose versions for `pgvector` (Python), the queue library, `docling-core`, the S3 client and the embedding clients; keep heavy parser dependencies out of the API.
- Decide how the worker gets its dependencies: an optional extra (`neuron-agent[worker]`) or the same lock with lazy imports; record the effect on image size.
- Pin `pgvector/pgvector:pg16` and the docling-serve image by digest, as the Dockerfile already does for its bases.
- Check each package against the `new-dependencies` rule (exists on PyPI, first release ≥90 days old) and licence (no AGPL/GPL in the runtime).

**Acceptance criteria**
- Given the plan, when `uv lock` resolves with the new dependencies on a branch, then there is no conflict with `openai>=3.6.0` and the API image size change is recorded.
- Given each new package, when it is checked, then its licence and first-release date are recorded in ADR 0014 or the PR.
- Given the plan is accepted, when RAG-01.01 and RAG-02.01 start, then they use the pinned versions and digests.

**Technical tasks**
- [x] Resolve the dependency set on a branch; record sizes.
- [x] Record licences and release dates.
- [x] Record image digests.

**Changes.** None on `main` except documentation.

**Security.** Supply chain: digest pins, licence review, no packages with only stale releases (research rejects packages last released in 2025).

**Tests.** None.

**Definition of Done (additions).** Plan recorded in ADR 0014.

---

## RAG-E01 Knowledge storage foundation

**Phase 1 · v1.1.0 · P0.** pgvector, the `knowledge` schema with RLS, and private blob storage.

Goal: Neuron Postgres can store knowledge bases, documents, chunks and embeddings with role grants and row-level security; original files are stored privately.
Exit gate: migrations run up from v1.0.0 on the reference stack; RLS denies rows outside the allowed KB set; blob keys cannot traverse paths.

### RAG-01.01 pgvector image, extension and startup check

- **Epic:** RAG-E01 · **Phase:** 1 · **Priority:** P0 · **Estimate:** 0.5 w · **Research:** KE-010, KN-010
- **Depends on:** RAG-00.01, RAG-00.04

**Story.** As an operator, I want Neuron to enable and check the pgvector extension, so that a
database without it fails clearly at startup instead of at the first search.

**Requirements**
- A versioned migration in `persistence/migrations.py` creates the `vector` extension and the `knowledge` schema (run by the migrator role).
  - Spike finding (RAG-00.02): pgvector is not a trusted extension, so `neuron_migrator` gets "permission denied to create extension vector". A superuser or the operator creates it first (the reference stack's init script); the migration uses `IF NOT EXISTS` and the startup check names the missing extension. Parallel HNSW builds need `shm_size` above Docker's 64 MB default.
- Readiness and the startup checks (`persistence/startup_checks.py`) fail with a stable error code when knowledge is enabled and the extension is missing.
- The feature is behind a setting (`APP_KNOWLEDGE_ENABLED`, default off) until v1.1.0 is released.
- `docker-compose.reference.yml` and CI service containers use the pinned `pgvector/pgvector:pg16` image.
  - Pinned by RAG-00.04: `pgvector/pgvector:pg16@sha256:0dd3149a06e4579a0d70d8fef9945636cd514005e7237deb27f9b67886f8dc4f` (extension 0.8.7) and `pgvector` 0.5.1 in the `worker` extra (ADR 0014, "Dependencies and images").

**Acceptance criteria**
- Given a Postgres with pgvector, when `neuron-agent setup` (migrate) runs, then the `vector` extension and `knowledge` schema exist and the migration is recorded once.
- Given knowledge is enabled and the extension is missing, when the API starts in staging or production, then startup fails with a clear error naming the extension; `/health/ready` reports the failing check.
- Given knowledge is disabled, when Neuron starts on plain `postgres:16`, then it starts as in v1.0.0.

**Technical tasks**
- [ ] Migration for extension and schema.
- [ ] Startup and readiness check.
- [ ] `APP_KNOWLEDGE_ENABLED` setting in `config/settings.py`.
- [ ] Reference stack and CI images.
- [ ] Postgres integration tests.

**Changes.** API: readiness check only. Database: extension, schema. UI: none. Config: `APP_KNOWLEDGE_ENABLED`.

**Security.** Extension creation needs the migrator role; the app role gets no `CREATE` on the schema.

**Tests.** Postgres integration tests for the migration and the startup check; unit tests for the setting.

**Definition of Done (additions).** `DEVELOPMENT.md` documents the new image.

### RAG-01.02 Knowledge tables, role grants and row-level security

- **Epic:** RAG-E01 · **Phase:** 1 · **Priority:** P0 · **Estimate:** 1 w · **Research:** KE-011, KN-011
- **Depends on:** RAG-01.01, RAG-00.02 (dimensions)

**Story.** As a user, I want my knowledge stored so that no other user's query can read it,
even if application code has a bug.

**Requirements**
- Tables per the Claude report §8: `index_profiles`, `bases`, `grants` (owner row written at creation; role rows in Phase 2), `documents`, `chunks` (generated `tsvector`), `embeddings` (`halfvec`, per profile).
- Unique indexes: live `(kb_id, sha256)`; `(uploaded_by, idempotency_key)`.
- GIN index on `tsv`; `(profile_id, kb_id)` index; one partial HNSW expression index per profile with the dimension chosen by the spike.
- RLS on `chunks` and `embeddings` keyed on `current_setting('neuron.kb_ids')`; the app role does not own the tables; the worker role has only the rights it needs.
- `owner_key` stores the HMAC owner key, never a raw subject.
- Grants extended in `persistence/roles.py`.

**Acceptance criteria**
- Given rows for KBs A and B, when the app role queries `chunks` with `SET LOCAL neuron.kb_ids = 'A'`, then only A's rows return.
- Given no `neuron.kb_ids` is set, when the app role queries `chunks` or `embeddings`, then no rows return.
- Given a pooled connection that ran a transaction with `kb_ids = A`, when the next transaction on it sets nothing, then it sees no rows (setting is transaction-scoped).
- Given the role-grant tests, when they run, then the app role cannot `ALTER`, `DROP` or disable RLS on knowledge tables.
- Given a migration from a v1.0.0 database, when it runs, then existing tables are unchanged.

**Technical tasks**
- [ ] Migrations for tables and indexes (`CREATE INDEX CONCURRENTLY` where the migration style allows).
- [ ] RLS policies.
- [ ] Role grants in `roles.py`.
- [ ] Seed profile 1 from settings.
- [ ] Integration tests for RLS and grants.

**Changes.** API: none. Database: six tables, indexes, RLS policies, grants. UI: none.

**Security.** Defence in depth: SQL filters remain the primary control (RAG-04.01); RLS repeats them. Extends the existing grant tests.

**Tests.** Postgres integration tests: RLS by KB, unset setting, pooled-connection reuse, role privileges, upgrade from v1.0.0.

**Definition of Done (additions).** Schema documented in `ARCHITECTURE.md`; mutation testing (`mutmut`) covers the RLS-related code paths where it applies.

### RAG-01.03 BlobStore for original files

- **Epic:** RAG-E01 · **Phase:** 1 · **Priority:** P0 · **Estimate:** 0.5 w · **Research:** KE-012, KN-012
- **Depends on:** RAG-00.01

**Story.** As a user, I want my uploaded originals stored privately, so that only Neuron can
read them and a deleted file is really gone.

**Requirements**
- `BlobStore` protocol with `put` (streamed, returns key and SHA-256), `get`, `delete` (idempotent), `exists`.
- `LocalBlobStore` (volume) and `S3BlobStore` (S3-compatible); selected by settings.
- Write-once random keys (no user-controlled path parts); checksum verified on read.
- No public URLs; S3 bucket expected to be private with server-side encryption.

**Acceptance criteria**
- Given a file name containing `../` or an absolute path, when it is stored, then the key does not contain it and nothing is written outside the store root.
- Given a stored blob, when `get` reads bytes whose SHA-256 differs from the recorded one, then it raises a typed error.
- Given a key already deleted, when `delete` runs again, then it succeeds without error.
- Given staging or production, when the store is `local` without an explicit opt-in, then settings validation fails or warns as ADR 0014 decides.

**Technical tasks**
- [ ] `knowledge/blobs.py` protocol and two implementations.
- [ ] Settings: backend, root path, bucket, endpoint, credentials (secrets).
- [ ] Unit tests with a temp dir; S3 tests against a local S3-compatible server or a stub.

**Changes.** API: none. Database: none. UI: none. Config: `APP_KNOWLEDGE_BLOB_*`.

**Security.** Path traversal, key guessing (random keys), credentials as `SecretStr`, no public ACLs.

**Tests.** Unit tests for traversal, checksum mismatch, idempotent delete; S3 adapter contract test.

**Definition of Done (additions).** Settings documented in `.env.example`.

---

## RAG-E02 Durable ingestion pipeline

**Phase 1 · v1.1.0 · P0.** A worker that parses, chunks and embeds uploads, survives restarts and stays within quotas.

Goal: an uploaded document reaches `ready` or a sanitised `failed` state, exactly once, even if the worker is killed.
Exit gate: killed-worker test completes the job once; parser has no network egress; over-quota uploads are refused before work starts.

### RAG-02.01 Worker entrypoint and job queue

- **Epic:** RAG-E02 · **Phase:** 1 · **Priority:** P0 · **Estimate:** 1 w · **Research:** KE-013, KN-013
- **Depends on:** RAG-01.02, RAG-00.02 (queue choice)

**Story.** As an operator, I want a separate `neuron-worker` process with durable jobs, so that
long parsing work never blocks the API and survives restarts.

**Requirements**
- Console script `neuron-worker` in the same image; the chosen queue library's schema installed by Neuron's migrations.
  - RAG-00.04: "same image" is the same Dockerfile and lock with a `worker` build target that installs the `neuron-agent[worker]` extra (`procrastinate` 3.10.0, `pgvector` 0.5.1, `docling-core[chunking-openai]` 2.105.0, `obstore` 0.12.1); the API target stays without it. Procrastinate needs the stalled-job sweep from RAG-00.02.
- Tasks are registered by name; the document row stays the public status (no public job resource).
- Graceful drain on SIGTERM; health endpoint or file for container health checks.
- A separate DB pool and role for the worker.
- Jobs are enqueued in the same transaction as the document insert (outbox semantics).

**Acceptance criteria**
- Given a job is running, when the worker is killed with SIGKILL and restarted, then the job is retried and completes once.
- Given SIGTERM, when a job is running, then the worker finishes or releases it within the drain timeout and exits 0.
- Given the document insert transaction rolls back, when the worker polls, then no job exists for it.
- Given the worker is down, when the API is up, then the API still serves chat and `/health/ready` reports the worker state as ADR 0014 decides.

**Technical tasks**
- [ ] `knowledge/jobs.py` and the `neuron-worker` entrypoint.
- [ ] Queue schema migration.
- [ ] Drain, health, logging.
- [ ] Reference stack service.
- [ ] Fault-injection integration tests.

**Changes.** API: none. Database: queue tables. UI: none. Deployment: worker service in `docker-compose.reference.yml`.

**Security.** Worker role least privilege; jobs carry ids only, never document text or identity beyond the owner key.

**Tests.** Integration tests: kill and restart, drain, rollback leaves no job.

**Definition of Done (additions).** Runbook entry for the worker in the operations docs.

### RAG-02.02 Document parser adapters

- **Epic:** RAG-E02 · **Phase:** 1 · **Priority:** P0 · **Estimate:** 1 w · **Research:** KE-014, KN-014
- **Depends on:** RAG-02.01

**Story.** As a user, I want PDFs, Office files, Markdown and text parsed with their structure and
page numbers, so that answers can cite the right place.

**Requirements**
- `DocumentParser` protocol returning a validated, normalised document (text blocks, headings, page numbers, optional bounding boxes).
- `DoclingServeParser`: sends bytes (never a URL) to docling-serve with a timeout; parser container has no network egress.
- `PlainTextParser` for `.txt` and `.md` without docling-serve.
- Caps: bytes, pages, characters per page; encrypted PDFs, archives and macro files rejected.
- A recorded fake parser for CI.
- `parser_version` stored on the document.

**Acceptance criteria**
- Given a PDF from the corpus, when it is parsed, then headings and page numbers match the expected values in the dataset.
- Given the parser does not answer within the timeout, when ingestion runs, then the document ends `failed` with `error_code = parser_timeout` and the job is not retried forever.
- Given parser output that does not match the schema, when it is validated, then the document fails with `parser_output_invalid`.
- Given an encrypted PDF or a zip archive, when it is parsed, then it is refused with a stable error code.
- Given the reference stack, when the parser container tries an outbound connection, then it fails (no egress network).

**Technical tasks**
- [ ] `knowledge/parsing.py` protocol, adapters, output schema.
- [ ] docling-serve service on an internal network in the reference stack.
- [ ] Fixtures and recorded fake.

**Changes.** API: none. Database: none (uses document columns). UI: none. Deployment: docling-serve service.

**Security.** Untrusted file input: isolation, no egress, timeouts, caps, schema validation.

**Tests.** Unit tests with the fake; integration test against docling-serve in a nightly or opt-in job.

**Definition of Done (additions).** Supported formats listed in user docs.

### RAG-02.03 Embedding provider and processing locality

- **Epic:** RAG-E02 · **Phase:** 1 · **Priority:** P0 · **Estimate:** 0.5 w · **Research:** KE-015, KN-015
- **Depends on:** RAG-00.01

**Story.** As an operator, I want to choose where document text is embedded and forbid hosted
processing, so that private documents do not leave my boundary without consent.

**Requirements**
- `EmbeddingProvider` wrapping LangChain `Embeddings`: `nvidia`, `openai_compatible` (TEI, vLLM, OpenAI), `fake`.
- Batching, dimension check against the index profile, finite-value check, retry classification (retryable versus terminal).
- KB `processing` setting: `hosted` or `self_hosted`; an operator policy setting can forbid `hosted`.
- Staging and production settings validation refuses a hosted provider when policy is self-hosted only.
- No LiteLLM.

**Acceptance criteria**
- Given policy `self_hosted_only` and a hosted provider configured, when the app starts in staging or production, then settings validation fails with a clear message.
- Given a provider returns vectors of the wrong dimension, when they are checked, then the batch fails with `embedding_dimension_mismatch` and nothing is written.
- Given a 429 or 5xx from the provider, when embedding runs, then it is retried with backoff; a 400 is terminal.
- Given development without credentials, when tests run, then the fake provider is used and no network call is made.

**Technical tasks**
- [ ] `knowledge/providers.py`.
- [ ] Settings and validation.
- [ ] Unit tests with stubbed providers.

**Changes.** API: none. Database: `bases.processing`. UI: shown in RAG-06.01. Config: `APP_KNOWLEDGE_EMBEDDING_*`, `APP_KNOWLEDGE_PROCESSING_POLICY`.

**Security.** Data egress decision is explicit; API keys as secrets; provider errors sanitised.

**Tests.** Unit tests for validation, dimension mismatch, retry classification.

**Definition of Done (additions).** `SECURITY.md` describes data egress by profile.

### RAG-02.04 Idempotent ingest task

- **Epic:** RAG-E02 · **Phase:** 1 · **Priority:** P0 · **Estimate:** 1 w · **Research:** KE-016, KN-016
- **Depends on:** RAG-02.01, RAG-02.02, RAG-02.03, RAG-01.03

**Story.** As a user, I want an upload to become searchable once, with clear status, even if
something fails part way.

**Requirements**
- Task `ingest_document(doc_id)`: fetch blob, parse, chunk with docling-core `HybridChunker` (token limit from the index profile), embed in batches, write chunks and embeddings in one transaction, set `ready`.
- Status transitions `queued → parsing → embedding → ready | failed`, with `updated_at`.
- Idempotent by `(doc_id, profile_id)`: a re-run replaces the chunk set, never duplicates it.
- Terminal failures store a sanitised `error_code` (no exception text).
- A tombstoned document is skipped.

**Acceptance criteria**
- Given a document, when ingestion runs twice, then exactly one chunk set exists for the active profile.
- Given the worker dies after embedding but before commit, when the job is retried, then the result equals a clean run.
- Given a parser error, when the task ends, then status is `failed` with a stable `error_code`, and no chunks exist.
- Given the document was tombstoned while queued, when the task starts, then it does nothing and the purge job owns cleanup.

**Technical tasks**
- [ ] Task implementation and chunker wiring.
- [ ] Status machine with guarded updates.
- [ ] Integration tests with the fake parser and fake embeddings.

**Changes.** API: none. Database: writes to `documents`, `chunks`, `embeddings`. UI: none.

**Security.** Chunk text is never logged; error codes only.

**Tests.** Integration tests: double run, crash before commit, failure path, tombstone skip.

**Definition of Done (additions).** Status values documented for API clients.

### RAG-02.05 Ingestion quotas and embedding token accounting

- **Epic:** RAG-E02 · **Phase:** 1 · **Priority:** P0 · **Estimate:** 0.5 w · **Research:** KE-023, Claude gap 3
- **Depends on:** RAG-02.04, RAG-03.02 (the upload route its quotas apply to)

**Story.** As an operator, I want limits on what each user can ingest and a record of embedding
tokens, so that one large upload cannot cause unbounded spend.

**Requirements**
- Per-user quotas: total bytes, pages, documents, concurrent jobs; checked at enqueue.
- Embedding tokens recorded in the existing token ledger (`persistence/token_budget.py`) under a separate kind; not counted against the chat budget unless ADR 0014 says so.
- Quota errors use stable codes and HTTP 429 or 413 as appropriate.

**Acceptance criteria**
- Given a user at their byte quota, when they upload, then the API refuses before storing the blob and returns a stable error code; usage is unchanged.
- Given a document is ingested, when the ledger is read, then embedding tokens for that user are recorded under the embedding kind.
- Given the concurrent-job limit is reached, when another upload arrives, then it is queued or refused as ADR 0014 decides, and the behaviour is tested.

**Technical tasks**
- [ ] Quota settings and checks.
- [ ] Ledger kind for embeddings.
- [ ] Tests.

**Changes.** API: new error codes on upload. Database: ledger kind (migration if the ledger needs it). UI: quota error message in RAG-06.01.

**Security.** Denial-of-wallet protection; quota state is per owner key.

**Tests.** Unit and integration tests for each quota and for ledger entries.

**Definition of Done (additions).** Quotas documented in `.env.example` and `SECURITY.md`.

---

## RAG-E03 Knowledge API

**Phase 1 · v1.1.0 · P0.** `/v1/knowledge/*` routes for knowledge bases, documents, chunks, files and search.

Goal: the web app and tests can manage KBs and documents through authorised routes that follow Neuron conventions.
Exit gate: foreign or deleted ids return 404 everywhere; every route has scope and ownership tests.

### RAG-03.01 Knowledge base routes and permissions

- **Epic:** RAG-E03 · **Phase:** 1 · **Priority:** P0 · **Estimate:** 0.5 w · **Research:** KE-017, KN-017
- **Depends on:** RAG-01.02

**Story.** As a user, I want to create, list, rename and delete my knowledge bases.

**Requirements**
- Permissions `knowledge:read`, `knowledge:write` and `tools:search_knowledge` added to `security/authorization.py` and mapped from scopes/roles like existing permissions.
- `KnowledgeAuthorization.allowed_kbs(ctx)` resolves readable and writable KBs from the owner key (Phase 1: owner only).
- `GET /v1/knowledge/bases`, `POST /v1/knowledge/bases`, `PATCH /v1/knowledge/bases/{kb_id}`, `DELETE /v1/knowledge/bases/{kb_id}` (tombstone, `202`).
- Bodies use `extra="forbid"`; names 1–80 characters; a per-user KB limit.
- Audit events with ids and counts only.

**Acceptance criteria**
- Given user A owns KB 1, when user B calls `PATCH` or `DELETE` on KB 1, then the response is 404, the same as for a missing id.
- Given a token without `knowledge:write`, when it calls `POST /v1/knowledge/bases`, then the response is 403.
- Given a body with an unknown field, when it is posted, then the response is 422.
- Given a KB is deleted, when the owner lists KBs, then it is no longer listed and its purge job is queued.

**Technical tasks**
- [ ] Permissions and scope mapping.
- [ ] `knowledge/service.py` and `knowledge/authorization.py`.
- [ ] Routes and schemas in `api/` and `schemas/`.
- [ ] Audit events.
- [ ] Tests.

**Changes.** API: four routes, three permissions. Database: reads/writes `bases`, `grants`. UI: used by RAG-06.01.

**Security.** Uniform 404; no names of inaccessible KBs leak; `require_permission` dependency only.

**Tests.** Unit and security tests for each route: scope, ownership, validation.

**Definition of Done (additions).** OpenAPI snapshot updated; API docs list the routes.

### RAG-03.02 Document upload, list and status

- **Epic:** RAG-E03 · **Phase:** 1 · **Priority:** P0 · **Estimate:** 1 w · **Research:** KE-017, KN-017
- **Depends on:** RAG-03.01, RAG-01.03, RAG-02.01 (RAG-02.05 adds quotas to the upload afterwards; owner decision, 2026-11-04, #431)

**Story.** As a user, I want to upload documents to my knowledge base and see their processing status.

**Requirements**
- `POST /v1/knowledge/bases/{kb_id}/documents`: multipart, streamed to the BlobStore; MIME sniffing (not the client type); size cap; allowed types only; `Idempotency-Key` header; returns `202` with `doc_id` and `status_url`.
- Insert document (`queued`) and enqueue ingestion in the same transaction.
- Duplicate content (`kb_id`, `sha256`) returns the existing document.
- `GET /v1/knowledge/bases/{kb_id}/documents` (paginated, with status) and `GET /v1/knowledge/documents/{doc_id}` (metadata, status, stage, `error_code`).

**Acceptance criteria**
- Given a valid PDF, when it is uploaded, then the response is 202 with `doc_id` and the document is `queued`.
- Given the same `Idempotency-Key` is sent twice, when the second request arrives, then it returns the first `doc_id` and no second blob is stored.
- Given a file whose bytes are HTML but claims `application/pdf`, when it is uploaded, then the sniffed type decides and a disallowed type is refused with 415.
- Given a file over the size cap, when it is uploaded, then the response is 413 and nothing is stored.
- Given user B, when they request user A's document, then the response is 404.

**Technical tasks**
- [ ] Streaming multipart handling with limits.
- [ ] MIME sniffing.
- [ ] Idempotency handling.
- [ ] List and get routes.
- [ ] Tests.

**Changes.** API: three routes. Database: `documents`. UI: used by RAG-06.01.

**Security.** Untrusted upload: size before buffering, sniffed type, no file name in paths or logs.

**Tests.** Unit and security tests for each criterion; integration test for the transaction.

**Definition of Done (additions).** Upload limits documented.

### RAG-03.03 Tombstone delete and purge jobs

- **Epic:** RAG-E03 · **Phase:** 1 · **Priority:** P0 · **Estimate:** 0.5 w · **Research:** KE-017, ChatGPT lifecycle
- **Depends on:** RAG-03.02, RAG-02.01

**Story.** As a user, I want a deleted document to disappear from search immediately and be
removed completely soon after.

**Requirements**
- `DELETE /v1/knowledge/documents/{doc_id}` sets `deleted_at` and status `deleting`, returns `202`.
- A purge job removes chunks, embeddings and the blob; idempotent; retries on failure.
- KB delete tombstones the KB and all its documents and purges them.
- Retrieval never returns tombstoned documents (enforced in RAG-04.01).

**Acceptance criteria**
- Given a document is tombstoned, when a search runs before the purge finishes, then no chunk of it is returned.
- Given the purge job fails half way, when it is retried, then it completes without error and leaves no rows or blob.
- Given a document delete is requested twice, when the second arrives, then it returns 202 or 404 consistently and queues no second purge.

**Technical tasks**
- [ ] Delete route and tombstone update.
- [ ] Purge tasks for document and KB.
- [ ] Tests.

**Changes.** API: one route (KB delete in RAG-03.01). Database: tombstone columns, deletes. UI: delete actions in RAG-06.01.

**Security.** Deletion is a data-rights guarantee; audit records the delete with ids only.

**Tests.** Integration tests: search during purge, purge retry, double delete.

**Definition of Done (additions).** Deletion semantics in `SECURITY.md`.

### RAG-03.04 Chunk inspection and file download

- **Epic:** RAG-E03 · **Phase:** 1 · **Priority:** P0 · **Estimate:** 0.5 w · **Research:** Claude §9, gap 8
- **Depends on:** RAG-03.02

**Story.** As a user, I want to open the passage behind a citation and download my original file safely.

**Requirements**
- `GET /v1/knowledge/documents/{doc_id}/chunks/{chunk_id}` returns chunk text, headings, pages and neighbours on request; access re-checked on every call.
- `GET /v1/knowledge/documents/{doc_id}/file` streams the original with `Content-Disposition: attachment`, `X-Content-Type-Options: nosniff` and a safe content type; never inline.
- Previews render extracted text only, never original markup.

**Acceptance criteria**
- Given an uploaded HTML or SVG file, when it is downloaded, then the response is an attachment with `nosniff` and no script can run in Neuron's origin.
- Given access to a KB is lost, when the user fetches a chunk they saw earlier, then the response is 404.
- Given a chunk id from another document, when it is requested under this `doc_id`, then the response is 404.

**Technical tasks**
- [ ] Routes and response headers.
- [ ] Tests, including a browser check in `web/e2e` for no script execution.

**Changes.** API: two routes. Database: reads only. UI: used by RAG-06.02.

**Security.** Stored XSS prevention; per-request authorisation.

**Tests.** Security tests for headers, cross-document ids, revoked access.

**Definition of Done (additions).** None beyond the shared list.

### RAG-03.05 Knowledge search endpoint

- **Epic:** RAG-E03 · **Phase:** 1 · **Priority:** P1 · **Estimate:** 0.25 w · **Research:** Claude §9
- **Depends on:** RAG-04.01

**Story.** As a user or an eval run, I want to search my knowledge directly, through the same
authorisation path as the agent tool.

**Requirements**
- `POST /v1/knowledge/search` with `query` (≤500 characters), optional `kb_ids` (≤10), `limit` (≤10).
- Calls the same retriever and authorisation as `search_knowledge`.
- Rate-limited like other `/v1` routes.

**Acceptance criteria**
- Given `kb_ids` containing a foreign KB, when search runs, then that id is ignored as not found and no result from it is returned.
- Given a query over 500 characters, when it is posted, then the response is 422.
- Given the same query through the tool and the endpoint, when both run for the same user, then they return the same chunk ids.

**Technical tasks**
- [ ] Route and schema.
- [ ] Parity test with the tool.

**Changes.** API: one route. Database: reads. UI: optional use in RAG-06.01.

**Security.** Same authorisation path; no query text in logs.

**Tests.** Unit and security tests.

**Definition of Done (additions).** None beyond the shared list.

---

## RAG-E04 Retrieval and agent tools

**Phase 1 · v1.1.0 · P0.** Hybrid retrieval inside the authorised set, and the tools the agent uses to search.

Goal: the agent can search the caller's knowledge, gets only authorised and live content, and says so when nothing relevant is found.
Exit gate: zero cross-user results in the security suite; small-KB queries return the full k; outbound tools need approval after a search.

### RAG-04.01 Hybrid retriever with authorisation in the query

- **Epic:** RAG-E04 · **Phase:** 1 · **Priority:** P0 · **Estimate:** 1 w · **Research:** KE-018, KN-018, KN-030
- **Depends on:** RAG-01.02, RAG-02.03

**Story.** As a user, I want relevant passages from my documents, found by meaning and by exact
words, and never from anyone else's.

**Requirements**
- One transaction: `SET LOCAL neuron.kb_ids`, dense candidates (top 80) and FTS candidates (`websearch_to_tsquery`, top 80), both filtered by allowed KBs; fused with RRF (k = 60); joined to live documents (`status = 'ready' AND deleted_at IS NULL`).
- Exact scan when the allowed set is at or below the spike threshold (default 10,000 chunks, RAG-00.02), HNSW with `iterative_scan = relaxed_order` and `hnsw.ef_search = 100` above it. The planner does not choose HNSW for the filtered query by itself, so the code forces the chosen path and an `EXPLAIN` test checks it.
- Only the KB's active index profile is searched.
- Score floor below which the result is `no_relevant_results`.
- FTS config per KB (`simple` by default).

**Acceptance criteria**
- Given the same text in two users' KBs, when each searches, then each sees only their own chunk.
- Given a KB with fewer chunks than the HNSW threshold, when a search asks for k results and at least k exist, then k results return.
- Given a query matching an exact identifier only in text, when hybrid search runs, then the chunk is returned through the FTS path.
- Given a tombstoned or failed document, when search runs, then none of its chunks return.
- Given the eval corpus, when dense, FTS and hybrid are compared, then the numbers are recorded and hybrid is the default only if it is at least as good as dense on recall@5.

**Technical tasks**
- [ ] `knowledge/retrieval.py` with parameterised SQL.
- [ ] Exact/HNSW switch and settings.
- [ ] Integration tests on Postgres; eval comparison.

**Changes.** API: none directly. Database: reads; `EXPLAIN` checked. UI: none.

**Security.** Authorisation before ranking, in SQL, plus RLS; no string-built SQL.

**Tests.** Postgres integration tests for isolation, small KB, tombstones; eval comparison recorded.

**Definition of Done (additions).** Query plans recorded in the PR for both paths.

### RAG-04.02 Knowledge agent tools

- **Epic:** RAG-E04 · **Phase:** 1 · **Priority:** P0 · **Estimate:** 1 w · **Research:** KE-019, KN-019
- **Depends on:** RAG-04.01

**Story.** As a user, I want the assistant to search my knowledge when my question needs it.

**Requirements**
- Follow the `add-tool` skill.
- Tools `list_knowledge_bases`, `search_knowledge` (`query`, `kb_ids?`, `limit?`) and `get_document_excerpt` (`cite_id`, `window?` ≤2, only ids from this run), registered in `ToolRegistry` and allow-listed in `security/input_policy.py`.
- Identity only from `ToolRuntime.context` (`AuthorizationContext`), as in `memory/tools.py`; no identity in tool schemas.
- `search_knowledge` and `get_document_excerpt` have `taints_run=True`.
- Results framed as a JSON block with `<` escaped and the "data, not instructions" preamble (reuse the `render_notes()` pattern); 6,000-character cap; 5 calls per run.
- Tools exist on the FastAPI path only, not in the `langgraph.json` graph.
- Fixed error strings.

**Acceptance criteria**
- Given a run that called `search_knowledge`, when the model then calls an MCP or outbound tool, then the call requires approval.
- Given a token without `tools:search_knowledge`, when the model calls the tool, then `ToolAuthorizationMiddleware` refuses it.
- Given the tool schema, when it is inspected, then it has no user, owner or tenant field.
- Given a sixth search call in one run, when it is made, then it returns the fixed limit error.
- Given `get_document_excerpt` with a `cite_id` not returned in this run, when it is called, then it returns not found.
- Given the Agent Server graph, when its tools are listed, then knowledge tools are absent.

**Technical tasks**
- [ ] `knowledge/tools.py`.
- [ ] Registry, allow-list and permission wiring.
- [ ] Framing helper.
- [ ] Tests from the `add-tool` checklist (input contract, authorization, timeout, failure).

**Changes.** API: none. Database: reads. UI: none. Prompts: tool descriptions.

**Security.** Taint, approval, framing, scope; tool output is untrusted.

**Tests.** Unit, graph and security tests per the `add-tool` skill.

**Definition of Done (additions).** `AGENTS.md` and `SECURITY.md` list the tools and their risk.

### RAG-04.03 Abstention and grounding

- **Epic:** RAG-E04 · **Phase:** 1 · **Priority:** P0 · **Estimate:** 0.5 w · **Research:** Claude gap 6
- **Depends on:** RAG-04.02, RAG-05.01

**Story.** As a user, I want the assistant to tell me when my documents do not contain the
answer, instead of answering from general knowledge as if it were grounded.

**Requirements**
- `search_knowledge` returns an explicit `no_relevant_results` marker below the score floor.
- The system prompt (`prompts/system/main.md`, versioned) requires saying the knowledge does not contain the answer.
- The answer carries `grounded: false` when the search tool ran and no valid citation remains.

**Acceptance criteria**
- Given an unanswerable eval question, when the agent answers, then the answer says the documents do not contain it and `grounded` is false.
- Given an answerable question with a valid citation, when the agent answers, then `grounded` is true.
- Given no knowledge tool ran, when the agent answers, then `grounded` is absent or null, not false.

**Technical tasks**
- [ ] Marker in the tool.
- [ ] Prompt change with a version bump.
- [ ] `grounded` computation.
- [ ] Eval cases.

**Changes.** API: `grounded` field (with RAG-05.02). Database: none. UI: shown in RAG-06.02.

**Security.** Prompt changes are critical-tier; the security-reviewer agent runs.

**Tests.** Graph tests and eval cases for unanswerable questions.

**Definition of Done (additions).** Prompt version recorded in the changelog.

### RAG-04.04 Narrow a run to selected knowledge bases

- **Epic:** RAG-E04 · **Phase:** 1 · **Priority:** P1 · **Estimate:** 0.25 w · **Research:** Claude §9
- **Depends on:** RAG-04.02

**Story.** As a user, I want to pick which knowledge bases a question uses.

**Requirements**
- `AgentRequest` gains optional `knowledge_base_ids` (at most 10).
- The list narrows, and never widens, the caller's allowed set; it reaches tools through the runtime context, not graph state the client controls.

**Acceptance criteria**
- Given `knowledge_base_ids = [A]`, when the agent searches, then only KB A's chunks are returned even if the model passes `kb_ids = [B]` and the user owns B.
- Given a foreign id in the list, when the request is made, then it is ignored as not found (no error that confirms existence).
- Given 11 ids, when the request is made, then the response is 422.

**Technical tasks**
- [ ] Schema field.
- [ ] Context plumbing in `AgentService`.
- [ ] Tests.

**Changes.** API: optional request field (backwards compatible). Database: none. UI: KB picker in RAG-06.02.

**Security.** Narrow only; validated server-side.

**Tests.** Unit and graph tests.

**Definition of Done (additions).** OpenAPI and stream protocol docs updated.

---

## RAG-E05 Server-validated citations

**Phase 1 · v1.1.0 · P0.** Citations the model cannot fabricate, kept in history and sent to clients.

Goal: every citation in an answer points to a chunk a knowledge tool returned in the same run, and it survives thread reload.
Exit gate: fabricated `cite_id`s are dropped and counted; reloaded threads show the same citations; old clients still work.

### RAG-05.01 Citation minting and validation

- **Epic:** RAG-E05 · **Phase:** 1 · **Priority:** P0 · **Estimate:** 0.5 w · **Research:** KE-020, KN-020
- **Depends on:** RAG-04.02

**Story.** As a user, I want citations I can trust, so that every source shown really supports the answer's retrieval.

**Requirements**
- Knowledge tools mint opaque, per-run `cite_id`s for each returned chunk.
- `AgentAnswer` gains `citations: list[str]`.
- `_final_answer` (`graphs/main_graph.py`) keeps only `cite_id`s returned by a knowledge tool in this run, as it already recomputes `used_tools`; rejected ids are counted in a metric.
- Validated citations resolve to document id, chunk id, title, pages, headings and optional bounding box.

**Acceptance criteria**
- Given the model lists a `cite_id` that no tool returned, when the answer is finalised, then it is dropped and the rejection counter increases.
- Given a retrieved chunk contains text that looks like a `cite_id`, when the model copies it, then it is dropped.
- Given two valid citations, when the answer is finalised, then both resolve with title and pages.

**Technical tasks**
- [ ] `knowledge/citations.py`.
- [ ] Schema and `_final_answer` changes (follow `add-graph-node` if graph state changes).
- [ ] Metric.
- [ ] Tests.

**Changes.** API: via RAG-05.02. Database: none. UI: none.

**Security.** Model output is untrusted; validation is in code.

**Tests.** Graph tests for valid, forged and copied ids.

**Definition of Done (additions).** None beyond the shared list.

### RAG-05.02 Citation contract in API, stream and history

- **Epic:** RAG-E05 · **Phase:** 1 · **Priority:** P0 · **Estimate:** 0.5 w · **Research:** KE-020, KN-020
- **Depends on:** RAG-05.01

**Story.** As a web app user, I want citations to arrive with the answer and remain when I reopen the conversation.

**Requirements**
- Validated citations stamped in the final `AIMessage.additional_kwargs` next to `run_id` (tool messages are not persisted, ADR 0005).
- `AgentResponse`, the SSE `final` event and `ThreadMessage` carry optional `citations` with `citation_schema_version: 1` and `grounded`.
- No excerpt text stored on the answer; clients fetch it through RAG-03.04.
- Stream protocol version stays 1; the field is additive.

**Acceptance criteria**
- Given an answer with citations, when the thread is reloaded, then the same citations are returned in history.
- Given a client that ignores unknown fields, when it reads a v1 stream with citations, then it works unchanged (contract test against the current web client).
- Given a citation, when the stored message is inspected, then it contains no chunk text.

**Technical tasks**
- [ ] Stamping in the graph.
- [ ] Schemas for response, SSE event and thread messages.
- [ ] Stream protocol doc update.
- [ ] Contract tests.

**Changes.** API: additive fields in three payloads. Database: checkpoint message metadata. UI: consumed in RAG-06.02.

**Security.** Revoking access hides old excerpts because text is fetched per request.

**Tests.** Unit, graph and contract tests.

**Definition of Done (additions).** Stream protocol documentation updated.

---

## RAG-E06 Knowledge in the web app

**Phase 1 · v1.1.0 · P0.** Manage knowledge and read citations in the existing React app.

Goal: a user can create a KB, upload, watch status, ask a question and open the cited passage.
Exit gate: Playwright upload → ask → open citation passes; axe has no violations on the new screens.

### RAG-06.01 Knowledge screen

- **Epic:** RAG-E06 · **Phase:** 1 · **Priority:** P0 · **Estimate:** 1 w · **Research:** KE-021, KN-021
- **Depends on:** RAG-03.01, RAG-03.02, RAG-03.03

**Story.** As a user, I want a screen to manage my knowledge bases and documents.

**Requirements**
- New feature folder `web/src/features/knowledge`, using shadcn/ui and the existing sidebar layout.
- List, create, rename and delete KBs; upload by drop zone or file picker; per-document status with polling and error messages from `error_code`.
- Shows where content is processed (`hosted` or `self_hosted`) before the first upload.
- Quota errors shown clearly.
- Light and dark themes; keyboard accessible.

**Acceptance criteria**
- Given a signed-in user, when they create a KB and upload a PDF, then the document appears as queued and changes to ready without a page reload.
- Given a hosted-processing KB, when the user opens the upload dialog, then it states that content is sent to the configured provider.
- Given a failed document, when it is shown, then the message maps from `error_code` and contains no server internals.
- Given axe runs on the screen, when it checks both themes, then there are no violations.

**Technical tasks**
- [ ] API client functions and types.
- [ ] Screens and components.
- [ ] Unit tests (Vitest) and Playwright tests.

**Changes.** API: consumes RAG-03 routes. Database: none. UI: new screen and sidebar entry.

**Security.** No file content rendered as HTML; tokens handled as in the existing client.

**Tests.** Vitest component tests; Playwright flow; axe.

**Definition of Done (additions).** `make flows` coverage includes the new flows.

### RAG-06.02 Citation chips and source sheet

- **Epic:** RAG-E06 · **Phase:** 1 · **Priority:** P0 · **Estimate:** 0.5 w · **Research:** KE-021, KN-021
- **Depends on:** RAG-05.02, RAG-03.04, RAG-06.01

**Story.** As a user, I want to click a citation and read the passage it refers to.

**Requirements**
- Numbered citation chips under answers (streamed and reloaded).
- A source sheet that fetches the chunk through RAG-03.04 and shows title, pages, headings and text (as text, not HTML).
- A "not grounded" indicator when `grounded` is false.
- Optional KB picker in the composer (RAG-04.04).

**Acceptance criteria**
- Given an answer with citations, when the user clicks chip 1, then the sheet shows the passage from the cited page.
- Given access was lost, when the chip is clicked, then the sheet shows "source not available" and no text.
- Given a reloaded thread, when it renders, then the chips are the same as when it was streamed.
- Given Playwright runs upload → ask → open citation, when it finishes, then it passes in CI.

**Technical tasks**
- [ ] Chip and sheet components.
- [ ] Stream and history parsing.
- [ ] Tests.

**Changes.** API: consumes citation fields and chunk route. Database: none. UI: chat components.

**Security.** Chunk text rendered as plain text; no `dangerouslySetInnerHTML`.

**Tests.** Vitest and Playwright.

**Definition of Done (additions).** None beyond the shared list.

---

## RAG-E07 Data rights and lifecycle

**Phase 1 · v1.1.0 · P0.** Erase, export, orphan cleanup and restore cover knowledge.

Goal: knowledge data follows the same data-rights guarantees as threads and memories.
Exit gate: erase-everything removes all knowledge data and reports `complete` accurately; restore drill covers blobs.

### RAG-07.01 Erase and export include knowledge

- **Epic:** RAG-E07 · **Phase:** 1 · **Priority:** P0 · **Estimate:** 0.5 w · **Research:** KE-022, KN-022
- **Depends on:** RAG-03.03

**Story.** As a user, I want my knowledge included when I export or erase my data.

**Requirements**
- `GET /v1/me/export` lists KBs and documents (metadata, not file contents).
- `DELETE /v1/me/knowledge` (permission `threads:delete`, as the research proposes, or a new one ADR 0014 names) tombstones and purges all of the user's KBs, documents, chunks, embeddings, blobs, grants and queued jobs.
- The existing erase-everything flow includes knowledge and its `complete` flag reflects purge state.

**Acceptance criteria**
- Given a user with KBs, when they erase everything, then after the purge no row or blob with their owner key remains, and `complete` is true only then.
- Given a purge is still running, when erase-everything returns, then `complete` is false.
- Given export, when it runs, then KBs and documents are listed with ids, names, sizes and status.

**Technical tasks**
- [ ] Route and service changes.
- [ ] Export schema change.
- [ ] Web data-rights page update.
- [ ] Tests.

**Changes.** API: one route, export field. Database: deletes. UI: data-rights page (`web/src/features/data`).

**Security.** Data-rights guarantee; audit with counts only.

**Tests.** Integration tests across all tables and blobs.

**Definition of Done (additions).** Privacy docs updated.

### RAG-07.02 Orphan sweep and reconciliation

- **Epic:** RAG-E07 · **Phase:** 1 · **Priority:** P1 · **Estimate:** 0.5 w · **Research:** KE-022, ChatGPT KN-018
- **Depends on:** RAG-02.04, RAG-03.03

**Story.** As an operator, I want blobs, rows and jobs that drifted apart found and fixed automatically.

**Requirements**
- A periodic job finds blobs with no live document, documents stuck in a non-terminal status beyond a timeout, and tombstones whose purge did not finish.
- It deletes orphans after a grace period, re-queues stuck work a bounded number of times, and records counts as metrics.

**Acceptance criteria**
- Given a blob with no document older than the grace period, when the sweep runs, then the blob is deleted.
- Given a document stuck in `parsing` beyond the timeout, when the sweep runs, then it is re-queued, and after the retry limit it is set `failed` with `ingest_stalled`.
- Given a blob newer than the grace period, when the sweep runs, then it is kept.

**Technical tasks**
- [ ] Sweep task and schedule.
- [ ] Metrics.
- [ ] Tests.

**Changes.** API: none. Database: reads and deletes. UI: none.

**Security.** Never deletes inside the grace period, to avoid racing uploads.

**Tests.** Integration tests for each case.

**Definition of Done (additions).** Runbook entry.

### RAG-07.03 Backup and restore drill covers knowledge

- **Epic:** RAG-E07 · **Phase:** 1 · **Priority:** P1 · **Estimate:** 0.5 w · **Research:** Claude gap 9
- **Depends on:** RAG-07.02

**Story.** As an operator, I want the restore drill to prove that knowledge data restores consistently.

**Requirements**
- Extend the existing restore drill (`docs/releases/v0.9.0-gate/` procedure) to pgvector data and blobs.
- After restore, run the sweep and a search over a known document.

**Acceptance criteria**
- Given a backup taken after ingesting the corpus, when it is restored to a fresh stack, then a known question returns the expected citation.
- Given blobs and DB from different moments, when the sweep runs after restore, then orphans are reported and no live document points to a missing blob without being flagged.

**Technical tasks**
- [ ] Drill script changes.
- [ ] Record the run in the release evidence.

**Changes.** None to code beyond scripts. Docs: drill procedure.

**Security.** Backups contain user documents; the drill uses the public corpus only.

**Tests.** The drill itself, recorded as evidence.

**Definition of Done (additions).** Drill result recorded in the v1.1.0 verification record.

---

## RAG-E08 Quality, security and release

**Phase 1 · v1.1.0 · P0.** Measure quality, prove isolation, observe the system, and release v1.1.0.

Goal: v1.1.0 meets its exit gate with recorded evidence.
Exit gate (Claude report §12): zero cross-user results in the security suite; ≥90% of answerable eval questions cite a correct page; killed-worker job completes; existing tests green.

### RAG-08.01 Retrieval and citation eval harness

- **Epic:** RAG-E08 · **Phase:** 1 · **Priority:** P0 · **Estimate:** 1 w · **Research:** KE-005, KN-023
- **Depends on:** RAG-00.03, RAG-04.01, RAG-05.01

**Story.** As an engineer, I want retrieval and citation quality measured on every change, so that regressions are caught.

**Requirements**
- Deterministic metrics in Neuron's eval harness: recall@5, MRR, citation precision (cited page matches expected), abstention accuracy on unanswerable questions.
- Runs in `make eval` with the fake model where possible; the live-model part follows existing eval conventions.
- Baseline stored like existing eval baselines; Ragas only as an optional nightly signal.

**Acceptance criteria**
- Given the corpus is ingested, when `make eval` runs, then the four metrics are reported in the eval report schema.
- Given a change that lowers recall@5 below the baseline tolerance, when evals run, then they fail.
- Given the v1.1.0 gate, when evals run on the release commit, then ≥90% of answerable questions cite a correct page.
- Given an unanswerable question, when the live-model eval runs, then the answer says the documents do not contain it and `grounded` is false (carried from RAG-04.03 AC1).

**Technical tasks**
- [ ] Metric functions and tests.
- [ ] Harness integration and baseline.
- [ ] Report schema update.

**Changes.** API: none. Database: test data only. UI: none.

**Security.** Uses the public corpus only.

**Tests.** Unit tests for metrics; eval run.

**Definition of Done (additions).** Baseline committed; `docs/AI_CODE_VERIFICATION.md` or eval docs updated.

### RAG-08.02 Knowledge security test suite

- **Epic:** RAG-E08 · **Phase:** 1 · **Priority:** P0 · **Estimate:** 1 w · **Research:** Claude §10, ChatGPT security table
- **Depends on:** RAG-04.02, RAG-05.01, RAG-03.04, RAG-07.01

**Story.** As the owner, I want every isolation and injection risk tested, so that the release gate is evidence, not belief.

**Requirements**
- All twelve cases from the Claude report §10 in `tests/security/` and the security eval harness, including: foreign `kb_id`/`doc_id`; same text in two KBs; revoked access while a citation is open; delete during purge; hidden-instruction PDF; fake `cite_id`; exfiltration to MCP after search; worker killed during embedding; HTML/SVG download; zip bomb or 5,000-page PDF; erase-everything; hosted provider with self-hosted policy.
- Threat model updated (`docs/` threat model from v0.9.0).

**Acceptance criteria**
- Given the suite, when `make test` runs, then all twelve cases pass.
- Given any case is broken by a change (mutation check), when the suite runs, then at least one test fails.
- Given the threat model, when it is read, then knowledge assets, trust boundaries and these mitigations are listed.

**Technical tasks**
- [ ] Tests per case.
- [ ] Security eval cases in `evals/eval_security_cases.json`.
- [ ] Threat model update.

**Changes.** API, database, UI: none. Tests and docs only.

**Security.** This is the security gate for v1.1.0.

**Tests.** The suite itself.

**Definition of Done (additions).** `security-reviewer` agent run recorded on the PR.

### RAG-08.03 Knowledge telemetry and leak scan

- **Epic:** RAG-E08 · **Phase:** 1 · **Priority:** P1 · **Estimate:** 0.5 w · **Research:** ChatGPT KN-020
- **Depends on:** RAG-02.04, RAG-04.01

**Story.** As an operator, I want to see ingestion and search health without seeing anyone's content.

**Requirements**
- Names in `observability/semconv.py`; spans for upload, ingest stages and search; metrics for queue age, stage errors, ingest duration, search latency, results returned, citation rejections, pool saturation.
- The existing leak scan covers the new paths (no query, chunk text, file names or vectors).
- Alert and dashboard suggestions in the operations docs.

**Acceptance criteria**
- Given a search, when its span is exported, then it has ids, counts and timings and no query text.
- Given the leak scan test, when it runs over knowledge spans and logs, then it finds no content.
- Given a stuck queue, when queue age exceeds the threshold, then the documented alert would fire (metric exists and is documented).

**Technical tasks**
- [ ] Semconv names.
- [ ] Instrumentation.
- [ ] Leak scan extension.
- [ ] Docs.

**Changes.** API, database, UI: none. Observability only.

**Security.** Telemetry hygiene.

**Tests.** Unit tests for attributes; leak scan.

**Definition of Done (additions).** Operations docs list the metrics.

### RAG-08.04 Reference stack, documentation and runbooks

- **Epic:** RAG-E08 · **Phase:** 1 · **Priority:** P1 · **Estimate:** 0.5 w · **Research:** Claude §7 deployment profiles
- **Depends on:** RAG-02.01, RAG-02.02

**Story.** As a developer or operator, I want to run the whole knowledge stack locally and know how to operate it.

**Requirements**
- `docker-compose.reference.yml` lean profile: pgvector image, `neuron-worker`, docling-serve on an internal network, blob volume.
- `ARCHITECTURE.md`, `SECURITY.md`, `DEVELOPMENT.md`, `AGENTS.md` and `CLAUDE.md` describe the knowledge module and its rules.
- Runbooks: worker down, parser down, provider outage, stuck jobs, re-running a failed document.

**Acceptance criteria**
- Given a clean checkout, when `docker compose up --build` (`make up`) runs, then the whole local stack, web app included, starts and the upload → ask → cite flow works with the fake or development model (owner's direction on #485, 2026-11-06).
- Given the docs, when a reader looks for knowledge module boundaries, then `AGENTS.md` and `CLAUDE.md` state them.

**Technical tasks**
- [ ] Compose services.
- [ ] Docs and runbooks.

**Changes.** Deployment and docs only.

**Security.** Parser network isolation shown in the compose file.

**Tests.** Reference stack smoke check (existing mechanism).

**Definition of Done (additions).** None beyond the shared list.

### RAG-08.05 v1.1.0 release verification

- **Epic:** RAG-E08 · **Phase:** 1 · **Priority:** P0 · **Estimate:** 0.5 w · **Research:** Claude §12 Phase 1 gate
- **Depends on:** all other v1.1.0 stories

**Story.** As the owner, I want a release record that shows the v1.1.0 gate was met.

**Requirements**
- `docs/releases/v1.1.0-release-verification.md` in the format of the v1.0.0 record: exit criteria, evidence, quality gates, known issues.
- Version 1.1.0 in `pyproject.toml`, `uv.lock`, `Dockerfile`; CHANGELOG section that `check-release` accepts.
- Load figures for ingestion and search on the reference host (no comparison gate in Phase 1).

**Acceptance criteria**
- Given the release commit, when `python3 scripts/deploy_tools.py check-release --tag v1.1.0` runs, then it passes.
- Given the record, when the owner reads it, then each exit criterion is Met, Waived by the owner, or Not run, with evidence.

**Technical tasks**
- [ ] Run all gates and evals on the release commit.
- [ ] Write the record and CHANGELOG section.
- [ ] Owner sign-off; tag and GitHub Release.

**Changes.** Version files and docs.

**Security.** Security suite result is an exit criterion.

**Tests.** All gates.

**Definition of Done (additions).** Tag pushed; GitHub Release published; tracker shows E00–E08 complete.

---

## RAG-E09 Retrieval quality and sharing

**Phase 2 · v1.2.0 (proposed).** Better ranking, safe model changes, shared knowledge bases, and a regression gate.

Goal: measured quality gains and role-based sharing without weakening isolation.
Exit gate (Claude report §12): recall@5 and MRR at or above Phase 1 on the same set; a revoked role loses access on the next query; p95 search latency recorded.

### RAG-09.01 Optional reranker providers

- **Epic:** RAG-E09 · **Phase:** 2 · **Priority:** P1 · **Estimate:** 0.5 w · **Research:** KE-030, KN-031
- **Depends on:** RAG-04.01, RAG-08.01

**Story.** As a user, I want the most relevant passages first, when reranking proves it helps.

**Requirements**
- `Reranker` protocol: `nvidia`, `tei`, `fastembed` cross-encoder (CPU), `none` (default).
- Reranks the fused top 40 to the top 8 when enabled for a profile; timeout falls back to RRF order with `reranked: false`.
- Enabled by default only if the eval shows a gain; locality policy applies to hosted rerankers.

**Acceptance criteria**
- Given the reranker times out, when search runs, then results return in RRF order and the response records `reranked: false`.
- Given the eval, when reranking is compared with RRF, then the numbers are recorded and the default follows them.
- Given self-hosted policy, when a hosted reranker is configured, then settings validation fails in staging and production.

**Technical tasks**
- [ ] Protocol and adapters.
- [ ] Fallback and metrics.
- [ ] Eval comparison.

**Changes.** API: optional `reranked` in search output. Database: profile settings. UI: none.

**Security.** Data egress for hosted rerankers.

**Tests.** Unit tests for fallback; eval comparison.

**Definition of Done (additions).** Eval numbers in the PR.

### RAG-09.02 Keep verified roles in Principal

- **Epic:** RAG-E09 · **Phase:** 2 · **Priority:** P1 · **Estimate:** 0.5 w · **Research:** KE-031, KN-032
- **Depends on:** none (Phase 2 start)

**Story.** As an administrator, I want Neuron to keep users' verified roles, so that knowledge can be shared by role.

**Requirements**
- `Principal` and `AuthorizationContext` keep roles from the configured claim and issuer only (today roles are mapped to scopes and dropped, `security/auth.py`).
- Roles never come from request bodies or headers.
- ADR 0006 amended.

**Acceptance criteria**
- Given a token from an unconfigured issuer with a roles claim, when it is verified, then no roles are kept.
- Given a valid token, when the context is built, then roles equal the configured claim's values.
- Given a request body with a roles field, when it is sent, then it is rejected or ignored and has no effect.

**Technical tasks**
- [ ] Auth changes.
- [ ] ADR 0006 amendment.
- [ ] Security tests.

**Changes.** API: none. Database: none. UI: none.

**Security.** Critical-tier; `security-reviewer` run required.

**Tests.** Unit and security tests.

**Definition of Done (additions).** ADR 0006 amendment accepted.

### RAG-09.03 Grants API and UI

- **Epic:** RAG-E09 · **Phase:** 2 · **Priority:** P1 · **Estimate:** 1 w · **Research:** KE-032, KN-033
- **Depends on:** RAG-09.02

**Story.** As a KB owner, I want to share a knowledge base with a role and revoke it.

**Requirements**
- `PUT /v1/knowledge/bases/{kb_id}/grants` with `knowledge:admin` plus KB admin access; role grants `read`, `write`, `admin`.
- `allowed_kbs` includes role grants; audited.
- Grants editor in the Knowledge screen.

**Acceptance criteria**
- Given a role grant is revoked, when a member of that role searches or opens a citation, then the next request returns no result or 404.
- Given a user with read access, when they try to upload, then the response is 404 or 403 as ADR 0014 decides.
- Given a grant change, when the audit log is read, then it has the actor, KB id, role and access level, with no content.

**Technical tasks**
- [ ] Route, service and authorisation changes.
- [ ] UI editor.
- [ ] Tests.

**Changes.** API: one route, one permission. Database: `grants` role rows. UI: grants editor.

**Security.** Revocation takes effect on the next request; no caching of allowed sets across requests.

**Tests.** Security tests for revocation; Playwright for the editor.

**Definition of Done (additions).** None beyond the shared list.

### RAG-09.04 Re-index to a new index profile

- **Epic:** RAG-E09 · **Phase:** 2 · **Priority:** P1 · **Estimate:** 0.5 w · **Research:** KE-033, KN-034, ChatGPT KN-017
- **Depends on:** RAG-02.04

**Story.** As an operator, I want to change the embedding model without mixing vector spaces or stopping search.

**Requirements**
- A `reindex_kb` job builds embeddings for a new profile (`building`), then swaps the KB's active profile atomically and retires the old one.
- Search uses exactly one profile per KB at a time.
- A new partial HNSW index per profile.

**Acceptance criteria**
- Given a re-index is running, when a user searches, then results come from the old profile only.
- Given the re-index completes, when the swap runs, then the next search uses the new profile only.
- Given the re-index fails, when it stops, then the old profile stays active and the new one is cleaned up.

**Technical tasks**
- [ ] Job, swap and cleanup.
- [ ] Index creation per profile.
- [ ] Tests.

**Changes.** API: none (operator command). Database: profile rows and indexes. UI: none.

**Security.** None beyond data integrity.

**Tests.** Integration tests for during, after and failed re-index.

**Definition of Done (additions).** Runbook entry.

### RAG-09.05 Nightly retrieval regression gate

- **Epic:** RAG-E09 · **Phase:** 2 · **Priority:** P1 · **Estimate:** 0.5 w · **Research:** KE-034
- **Depends on:** RAG-08.01

**Story.** As a maintainer, I want a nightly run that fails when retrieval quality drops.

**Requirements**
- Nightly workflow (like the existing nightly model run) runs the knowledge eval with real embeddings.
- Fails on a recall@5 or citation-precision drop beyond tolerance; Ragas faithfulness as a non-blocking signal.

**Acceptance criteria**
- Given a baseline, when nightly recall@5 drops beyond tolerance, then the workflow fails and names the metric.
- Given Ragas is unavailable, when the nightly runs, then the gate still runs on deterministic metrics.

**Technical tasks**
- [ ] Workflow and baseline.
- [ ] Tolerance settings.

**Changes.** CI only.

**Security.** Workflow uses repository secrets as existing nightly jobs do.

**Tests.** The workflow on a branch.

**Definition of Done (additions).** None beyond the shared list.

### RAG-09.06 Load test for ingestion and search

- **Epic:** RAG-E09 · **Phase:** 2 · **Priority:** P1 · **Estimate:** 0.5 w · **Research:** KE-035, KN-035
- **Depends on:** RAG-04.01, RAG-02.04

**Story.** As an operator, I want ingestion throughput and search latency measured under load.

**Requirements**
- Locust scenarios in `loadtest/` for concurrent uploads and filtered hybrid search; fake parser and embeddings options.
- Results recorded with host details; contention with checkpoint traffic observed.

**Acceptance criteria**
- Given the reference stack, when `make load` runs the knowledge scenarios, then p50/p95 search latency and ingestion pages per minute are recorded.
- Given concurrent chat and search load, when it runs, then chat p95 change is recorded.

**Technical tasks**
- [ ] Scenarios and fixtures.
- [ ] Baseline file.

**Changes.** Load test code only.

**Security.** Public corpus only.

**Tests.** The load run, recorded.

**Definition of Done (additions).** Baseline committed.

### RAG-09.07 Link feedback to citations

- **Epic:** RAG-E09 · **Phase:** 2 · **Priority:** P2 · **Estimate:** 0.5 w · **Research:** Claude gap 10
- **Depends on:** RAG-05.02

**Story.** As a maintainer, I want a thumbs-down to mark the retrieved chunks for review, so that real failures improve the eval set.

**Requirements**
- Join `neuron_feedback` to the run's citation set; an operator report lists chunk ids with negative feedback; no text in telemetry.

**Acceptance criteria**
- Given a thumbs-down on an answer with citations, when the report runs, then it lists the cited chunk ids and the run id.
- Given the report, when it is inspected, then it contains no query or chunk text.

**Technical tasks**
- [ ] Query and report command.
- [ ] Tests.

**Changes.** Database: read join. API: none or an operator command. UI: none.

**Security.** Report is operator-only and content-free.

**Tests.** Integration test.

**Definition of Done (additions).** None beyond the shared list.

### RAG-09.08 Multilingual text search evaluation

- **Epic:** RAG-E09 · **Phase:** 2 · **Priority:** P2 · **Estimate:** 0.5 w · **Research:** Claude gap 7
- **Depends on:** RAG-08.01

**Story.** As a user writing in languages other than English, I want text search that works for my language.

**Requirements**
- Per-KB language setting choosing the FTS config; evaluate `pg_textsearch` BM25 against built-in FTS on a multilingual subset.
- Adopt `pg_textsearch` only if it wins and the custom image is accepted.

**Acceptance criteria**
- Given a KB with a language setting, when documents are ingested, then chunks use that FTS config.
- Given the evaluation, when it finishes, then the numbers and the decision are recorded in ADR 0014 or a new ADR.

**Technical tasks**
- [ ] Language setting.
- [ ] Multilingual eval subset.
- [ ] Comparison.

**Changes.** API: KB `language` field. Database: `ts_config`. UI: language selector.

**Security.** None specific.

**Tests.** Integration tests; eval comparison.

**Definition of Done (additions).** Decision recorded.

---

## RAG-E10 External knowledge sources

**Phase 3 · later, evidence-gated.** Bring in web pages, GitHub repositories and MCP sources.

Goal: knowledge from external sources with versioned provenance and safe egress.
Exit gate (Claude report §12): every chunk maps to a source version; private-range URLs are refused.
Start condition: a product requirement for each source, and RAG-10.01 done.

### RAG-10.01 Outbound URL safety for ingestion fetchers (extends #364 and #366)

- **Epic:** RAG-E10 · **Phase:** 3 · **Priority:** P0 (for this phase) · **Estimate:** 1 w · **Research:** KE-002, KN-002
- **Depends on:** none

**Story.** As the owner, I want every outbound fetch to resolve and re-check its destination and to use HTTPS, so that ingestion cannot reach internal services.

**Requirements**
- Reuse the egress control from #395 (`security/egress.py`): it resolves hostnames, refuses private, loopback, link-local and metadata addresses, re-validates every redirect and pins the resolved address (DNS rebinding). Extend it to the ingestion fetchers; do not write a second one.
- HTTPS-only for fetch tools and connectors; development exceptions as for MCP (`tools/mcp/urls.py`).
- #364 and #366 are closed (fixed for MCP by #395); this story covers the new fetch paths.

**Acceptance criteria**
- Given a hostname that resolves to `10.0.0.1` or `169.254.169.254`, when it is validated, then it is refused.
- Given a public URL that redirects to a private address, when it is fetched, then the redirect is refused.
- Given a DNS answer that changes between validation and connect, when the fetch runs, then it connects only to the validated address.
- Given an `http://` URL in staging or production, when it is validated, then it is refused.

**Technical tasks**
- [ ] Resolver and validation changes.
- [ ] Safe HTTP client wrapper.
- [ ] Security tests.

**Changes.** API: none. Database: none. UI: none.

**Security.** Critical-tier SSRF control.

**Tests.** Security tests per criterion.

**Definition of Done (additions).** `SECURITY.md` updated; #364, #366 and #395 referenced.

### RAG-10.02 Web page ingestion

- **Epic:** RAG-E10 · **Phase:** 3 · **Priority:** P2 · **Estimate:** 1 w · **Research:** Claude Phase 3, Trafilatura
- **Depends on:** RAG-10.01, RAG-02.04

**Story.** As a user, I want to add a web page to my knowledge base by URL.

**Requirements**
- Fetch through the safe client in the worker; extract with Trafilatura; store URL, fetch time and content hash as provenance; size and time caps.
- Crawl4AI only in a separate isolated worker for JavaScript pages (later).

**Acceptance criteria**
- Given a public article URL, when it is added, then it is ingested and its chunks cite the URL and fetch time.
- Given a private-range URL, when it is added, then it is refused with a stable error code.

**Technical tasks**
- [ ] Route or source type, task, extractor.
- [ ] Tests.

**Changes.** API: source creation by URL. Database: `source_type = web`, `source_ref`. UI: "add URL".

**Security.** SSRF control; fetched content is untrusted and taints runs.

**Tests.** Integration tests with a local test server; security tests.

**Definition of Done (additions).** None beyond the shared list.

### RAG-10.03 GitHub repository sync

- **Epic:** RAG-E10 · **Phase:** 3 · **Priority:** P2 · **Estimate:** 1.5 w · **Research:** Claude Phase 3, Gemini Phase 3
- **Depends on:** RAG-10.01, RAG-02.04

**Story.** As a developer, I want a repository indexed so that answers cite files at a commit.

**Requirements**
- Sync job with a read-only token; code-aware chunks (tree-sitter); provenance: repo, path, commit SHA, line range.
- Re-sync replaces chunks for changed files; deletion propagates.
- Per-user OAuth needs a token-vault ADR first; Phase 3 uses a service token.

**Acceptance criteria**
- Given a synced repo, when a chunk is cited, then the citation names the file, commit SHA and line range.
- Given a file is deleted upstream, when re-sync runs, then its chunks are removed.

**Technical tasks**
- [ ] Sync job and chunker.
- [ ] Token handling.
- [ ] Tests.

**Changes.** API: source creation. Database: `source_type = github`. UI: repo source form.

**Security.** Minimal token scope; repository content is untrusted.

**Tests.** Integration tests against fixtures.

**Definition of Done (additions).** Token handling documented.

### RAG-10.04 MCP document connectors

- **Epic:** RAG-E10 · **Phase:** 3 · **Priority:** P2 · **Estimate:** 1 w · **Research:** Claude Phase 3
- **Depends on:** RAG-02.04

**Story.** As a user, I want documents from an approved MCP server ingested into my knowledge base.

**Requirements**
- Use Neuron's pinned MCP client (ADR 0009), not FastMCP in-process; ingestion runs in the worker; schema pins apply.

**Acceptance criteria**
- Given an approved MCP server, when a sync runs, then its documents are ingested with server and resource provenance.
- Given a server whose tool schema changed from the pin, when sync runs, then it is refused.

**Technical tasks**
- [ ] Connector task.
- [ ] Tests with the reference MCP server.

**Changes.** API: source creation. Database: `source_type = mcp`. UI: connector form.

**Security.** Pinned schemas; content untrusted.

**Tests.** Integration tests with the in-repo reference server.

**Definition of Done (additions).** None beyond the shared list.

### RAG-10.05 OpenAI-compatible chat model provider

- **Epic:** RAG-E10 · **Phase:** 3 · **Priority:** P2 · **Estimate:** 0.5 w · **Research:** Claude and Gemini Phase 3
- **Depends on:** none

**Story.** As an operator, I want to point Neuron at a self-hosted OpenAI-compatible model (vLLM, SGLang), so that chat can stay local with `self_hosted` knowledge.

**Requirements**
- Add `openai_compatible` to `SUPPORTED_PROVIDERS` with a base URL setting validated by the URL policy; no API key required for loopback in development.

**Acceptance criteria**
- Given `APP_MODEL=openai_compatible:<model>` and a base URL, when the agent runs, then requests go to that URL.
- Given an `http` non-loopback base URL in production, when settings load, then validation fails.

**Technical tasks**
- [ ] Settings and factory changes.
- [ ] Tests.

**Changes.** Config and model factory.

**Security.** URL validation; key as secret.

**Tests.** Unit tests.

**Definition of Done (additions).** `.env.example` updated.

---

## RAG-E11 Specialised knowledge tools

**Phase 4 · later, evidence-gated.** Tools for tables, the web and repositories, and an optional retrieval subgraph.

Goal: each tool ships with eval cases and isolation; the subgraph is kept only if it beats the tool loop.
Start condition: a product requirement per tool; for mutating or outbound tools, approval and audit design.

### RAG-11.01 `query_table` over uploaded tables

- **Epic:** RAG-E11 · **Phase:** 4 · **Priority:** P2 · **Estimate:** 1.5 w · **Research:** Claude §9, Gemini Phase 4
- **Depends on:** RAG-04.02

**Story.** As a user, I want to ask questions about my CSV or spreadsheet that need calculation.

**Requirements**
- DuckDB with external access off; one `SELECT` checked by sqlglot; 5 s and 256 MB limits; ≤200 rows; `taints_run=True`; scope `tools:query_table`.

**Acceptance criteria**
- Given a non-`SELECT` statement or a file function, when it is submitted, then it is refused before execution.
- Given a query exceeding limits, when it runs, then it stops with a fixed error.

**Technical tasks**
- [ ] Tool, SQL checker, limits; `add-tool` checklist.

**Changes.** Tool and settings.

**Security.** No code execution; read-only SQL.

**Tests.** Security tests for refused SQL; eval cases.

**Definition of Done (additions).** Eval cases added.

### RAG-11.02 `research_web` tool

- **Epic:** RAG-E11 · **Phase:** 4 · **Priority:** P2 · **Estimate:** 1 w · **Research:** Claude §9
- **Depends on:** RAG-10.01

**Story.** As a user, I want the assistant to read a few web pages to answer a question.

**Requirements**
- `question`, `max_pages` ≤5; safe client; framed extracts with URLs; taints the run; after taint, requires approval (existing rule).

**Acceptance criteria**
- Given a tainted run, when `research_web` is called, then approval is required.
- Given a private-range URL in results, when it would be fetched, then it is refused.

**Technical tasks**
- [ ] Tool per `add-tool`; tests.

**Changes.** Tool and settings.

**Security.** Outbound; SSRF; untrusted content.

**Tests.** Security and eval tests.

**Definition of Done (additions).** None beyond the shared list.

### RAG-11.03 Mutating knowledge tools with approval

- **Epic:** RAG-E11 · **Phase:** 4 · **Priority:** P2 · **Estimate:** 1 w · **Research:** Claude §9
- **Depends on:** RAG-11.02, RAG-03.03

**Story.** As a user, I want to ask the assistant to save a page or delete a document, with my approval each time.

**Requirements**
- `save_to_knowledge` and `delete_document`; always require approval; idempotent; audited; removed from the deny-list only with the authorisation, idempotency and audit story ADR 0003 requires.

**Acceptance criteria**
- Given the model calls `delete_document`, when the run reaches it, then it pauses for approval and does nothing until approved.
- Given an approved save is retried, when it runs again, then no duplicate document is created.

**Technical tasks**
- [ ] Tools; ADR 0003 amendment; tests.

**Changes.** Tools; ADR.

**Security.** First mutating tools; critical-tier.

**Tests.** Approval harness cases.

**Definition of Done (additions).** ADR 0003 amendment accepted.

### RAG-11.04 `search_repository` tool

- **Epic:** RAG-E11 · **Phase:** 4 · **Priority:** P2 · **Estimate:** 1 w · **Research:** Claude Phase 4
- **Depends on:** RAG-10.03

**Story.** As a developer, I want exact symbol and path search over synced repositories.

**Requirements**
- Exact symbol and path lookup in addition to semantic search; results cite commit SHA and lines.

**Acceptance criteria**
- Given a symbol name, when the tool runs, then it returns its definition location at the synced commit.

**Technical tasks**
- [ ] Symbol index; tool; tests.

**Changes.** Tool; database index.

**Security.** Same authorisation as knowledge.

**Tests.** Eval cases.

**Definition of Done (additions).** None beyond the shared list.

### RAG-11.05 Optional plan-and-verify retrieval subgraph

- **Epic:** RAG-E11 · **Phase:** 4 · **Priority:** P2 · **Estimate:** 1.5 w · **Research:** Claude and ChatGPT Phase 4
- **Depends on:** RAG-08.01, RAG-09.05

**Story.** As a user with multi-step questions, I want the assistant to plan searches and check evidence, if that measurably helps.

**Requirements**
- New ADR (subgraphs are restricted by CLAUDE.md); `add-graph-node` skill; kept only if evals beat the tool loop.

**Acceptance criteria**
- Given the multi-hop eval subset, when the subgraph and the tool loop are compared, then the subgraph ships only if it wins on the agreed metrics within latency limits.

**Technical tasks**
- [ ] ADR; subgraph behind a flag; eval comparison.

**Changes.** Graph.

**Security.** Same tool gates apply inside the subgraph.

**Tests.** Graph tests; eval comparison.

**Definition of Done (additions).** ADR accepted.

---

## RAG-E12 Platform and scale

**Phase 5 · later, evidence-gated.** Each item needs a measured gain before it starts.

### RAG-12.01 Semantic recall over memory notes

- **Epic:** RAG-E12 · **Phase:** 5 · **Priority:** P2 · **Estimate:** 1 w · **Research:** Claude §4 (long-term memory)
- **Depends on:** RAG-02.03

**Story.** As a user, I want relevant memory notes recalled by meaning.

**Requirements**
- New ADR; semantic index over the existing notes store; no model-extracted memories (ADR 0009 decision 7); LangMem rejected.

**Acceptance criteria**
- Given a note phrased differently from the question, when recall runs, then it is found, and only the owner's notes are searched.

**Technical tasks**
- [ ] ADR; index; tests.

**Changes.** Memory store.

**Security.** Owner isolation as in memory today.

**Tests.** Integration and eval tests.

**Definition of Done (additions).** ADR accepted.

### RAG-12.02 Sandboxed code execution evaluation

- **Epic:** RAG-E12 · **Phase:** 5 · **Priority:** P2 · **Estimate:** 1.5 w · **Research:** Claude and Gemini Phase 5
- **Depends on:** RAG-11.01

**Story.** As a user, I want charts and analysis that need code, run safely, if a use case requires it.

**Requirements**
- Evaluate E2B or gVisor; behind approval; no execution in the agent process (CLAUDE.md forbids shell tools today).

**Acceptance criteria**
- Given the sandbox red-team suite, when it runs, then no escape, network or file access outside the sandbox succeeds.

**Technical tasks**
- [ ] ADR; prototype; red-team suite.

**Changes.** New service (if adopted).

**Security.** Highest risk item; owner approval required.

**Tests.** Red-team suite.

**Definition of Done (additions).** ADR accepted or item dropped.

### RAG-12.03 GraphRAG trial

- **Epic:** RAG-E12 · **Phase:** 5 · **Priority:** P2 · **Estimate:** 1.5 w · **Research:** Claude §11 (LightRAG, Graphiti)
- **Depends on:** RAG-08.01

**Story.** As a user with relationship questions, I want better multi-hop answers, if hybrid retrieval fails them.

**Requirements**
- Trial LightRAG or Graphiti on a multi-hop eval subset; adopt only on measured gain.

**Acceptance criteria**
- Given the multi-hop subset, when the trial runs, then the gain over hybrid retrieval is recorded and the decision follows it.

**Technical tasks**
- [ ] Eval subset; trial branch; record.

**Changes.** None unless adopted.

**Security.** Licence and data-flow review.

**Tests.** Eval comparison.

**Definition of Done (additions).** Decision recorded.

### RAG-12.04 External vector store benchmark

- **Epic:** RAG-E12 · **Phase:** 5 · **Priority:** P2 · **Estimate:** 1 w · **Research:** Claude §11 (Qdrant)
- **Depends on:** RAG-09.06

**Story.** As an operator at scale, I want to know when Postgres stops being enough for vectors.

**Requirements**
- Benchmark Postgres against Qdrant at the real chunk count; adopt only if Postgres misses p95 or recall targets.

**Acceptance criteria**
- Given the benchmark, when it finishes, then p95 and recall for both are recorded with the decision.

**Technical tasks**
- [ ] Benchmark harness; record.

**Changes.** None unless adopted.

**Security.** A second datastore needs its own ACL design; ADR required.

**Tests.** Benchmark.

**Definition of Done (additions).** Decision recorded.

### RAG-12.05 Organisation knowledge spaces

- **Epic:** RAG-E12 · **Phase:** 5 · **Priority:** P2 · **Estimate:** 2 w · **Research:** Claude §4 (tenant model)
- **Depends on:** RAG-09.03

**Story.** As an organisation administrator, I want knowledge spaces owned by the organisation rather than a person.

**Requirements**
- Only when the IdP supplies an organisation claim; org entity, membership and admin model; ADR required.

**Acceptance criteria**
- Given a user leaves the organisation (claim removed), when they search, then org spaces return nothing on the next request.

**Technical tasks**
- [ ] ADR; schema; authorisation; UI.

**Changes.** API, database, UI.

**Security.** New ownership model; critical-tier.

**Tests.** Security tests.

**Definition of Done (additions).** ADR accepted.
