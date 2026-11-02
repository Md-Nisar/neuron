# RAG implementation tracker

The single place that says what is really done in the Knowledge Engine work. Stories and their
acceptance criteria live in [`NEURON_RAG_PRODUCT_BACKLOG.md`](NEURON_RAG_PRODUCT_BACKLOG.md);
research in `docs/research/rag/`.

**Last verified:** 2026-11-03, against `main` at `89a3020` (after v1.0.0).
**Backlog status:** Draft, awaiting owner review. GitHub issues and the Project board have not been created.

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
| RAG-E00 | Readiness and decisions | 0 | v1.1.0 | 4 | 2 | 0 | 0 | 2 | RAG-00.02 |
| RAG-E01 | Knowledge storage foundation | 1 | v1.1.0 | 3 | 0 | 0 | 0 | 3 | RAG-01.01 (after E00) |
| RAG-E02 | Durable ingestion pipeline | 1 | v1.1.0 | 5 | 0 | 0 | 0 | 5 | RAG-02.03 (after E00) |
| RAG-E03 | Knowledge API | 1 | v1.1.0 | 5 | 0 | 0 | 0 | 5 | RAG-03.01 (after RAG-01.02) |
| RAG-E04 | Retrieval and agent tools | 1 | v1.1.0 | 4 | 0 | 0 | 0 | 4 | RAG-04.01 (after RAG-01.02, RAG-02.03) |
| RAG-E05 | Server-validated citations | 1 | v1.1.0 | 2 | 0 | 0 | 0 | 2 | RAG-05.01 (after RAG-04.02) |
| RAG-E06 | Knowledge in the web app | 1 | v1.1.0 | 2 | 0 | 0 | 0 | 2 | RAG-06.01 (after E03) |
| RAG-E07 | Data rights and lifecycle | 1 | v1.1.0 | 3 | 0 | 0 | 0 | 3 | RAG-07.01 (after RAG-03.03) |
| RAG-E08 | Quality, security and release | 1 | v1.1.0 | 5 | 0 | 0 | 0 | 5 | RAG-08.01 (after RAG-04.01, RAG-05.01) |
| RAG-E09 | Retrieval quality and sharing | 2 | v1.2.0 | 8 | 0 | 0 | 0 | 8 | RAG-09.02 (Phase 2) |
| RAG-E10 | External knowledge sources | 3 | later | 5 | 0 | 0 | 0 | 5 | RAG-10.01 (Phase 3) |
| RAG-E11 | Specialised knowledge tools | 4 | later | 5 | 0 | 0 | 0 | 5 | — (evidence-gated) |
| RAG-E12 | Platform and scale | 5 | later | 5 | 0 | 0 | 0 | 5 | — (evidence-gated) |
| **Total** | | | | **56** | **2** | **0** | **0** | **54** | **RAG-00.02** |

v1.1.0 scope (E00–E08): 33 stories, 2 done.

**Recommended next action:** the owner reviews and approves the backlog (scope, IDs, release
mapping). Then create the labels, issues and Project board, and start **RAG-00.01 ADR 0014**.

## GitHub synchronisation

| Item | State |
| --- | --- |
| Labels `epic`, `story`, `rag`, `phase:0`–`phase:5`, `v1.1.0`, `v1.2.0` | Created 2026-11-03 |
| Epic issues (13) | RAG-E00 created (#398); E01–E12 not created |
| Story issues (56) | RAG-00.01–00.04 created (#399–#402); the rest not created |
| GitHub Project board (fields: Status, Priority, Epic, Phase, Release) | Not created. Projects use the GraphQL API, which the Claude cloud session could not reach on 2026-11-02 (HTTP 403); the owner may need to create it or allow access |

### Issue map

Filled in when issues are created. The bracketed ID in the issue title is what de-duplication matches on.

| ID | Issue | Project status |
| --- | --- | --- |
| RAG-E00 | #398 | Not on a board |
| RAG-00.01 … RAG-00.04 | #399–#402 | Not on a board |
| RAG-E01 … RAG-E12 | — | — |

## Epic detail

### RAG-E00 Readiness and decisions

- **Stories:** 4 total · 2 done · 0 in progress · 0 blocked · 2 pending
- **Implemented functionality:** ADR 0014 Accepted 2026-11-02, amending ADR 0001, 0002 and 0005; v1.1.0 in `docs/ROADMAP.md` (RAG-00.01). Labelled corpus and security dataset: 31 documents, 64 answerable, 12 unanswerable, 5 ACL and 4 injection cases, schema-checked in `make test` (RAG-00.03).
- **Outstanding work:** spike (RAG-00.02); dependency and image plan (RAG-00.04).
- **Blockers and decisions:**
  - 2026-11-02: the owner accepted ADR 0014, including the v1.1.0 scope (E00–E08).
  - Decision 2026-11-02: the research's security prerequisites are not all done. #370 is fixed
    in v1.0.0; #364 (SSRF) and #366 (HTTPS-only) are fixed for MCP by #395 (unreleased, on `main`);
    ingestion fetchers must still reuse that control (RAG-10.01), which blocks web ingestion and `research_web` but not Phase 1 (Phase 1 makes no
    outbound fetches of user URLs).
- **Next recommended story:** RAG-00.02 (spike, on a branch never merged), which needs RAG-00.01 and RAG-00.03. RAG-00.02 needs RAG-00.03's corpus; RAG-00.04 needs RAG-00.02.

### RAG-E01 Knowledge storage foundation

- **Stories:** 3 total · 0 done · 0 in progress · 0 blocked · 3 pending
- **Implemented functionality:** none. The reference stack runs `postgres:16` without pgvector.
- **Outstanding work:** RAG-01.01, RAG-01.02, RAG-01.03.
- **Blockers and decisions:** needs ADR 0014 and the spike's dimension choice.
- **Next recommended story:** RAG-01.01 (RAG-01.03 can run in parallel).

### RAG-E02 Durable ingestion pipeline

- **Stories:** 5 total · 0 done · 0 in progress · 0 blocked · 5 pending
- **Implemented functionality:** none.
- **Outstanding work:** RAG-02.01 to RAG-02.05.
- **Blockers and decisions:** queue library chosen by the spike (Procrastinate, PGQueuer as fallback).
- **Next recommended story:** RAG-02.03 (depends only on ADR 0014), then RAG-02.01.

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
| RAG-00.02 | Phase 0 spike: parser, vectors, queue | 0 | P0 | Pending | #400 | — | — |
| RAG-00.03 | Labelled eval corpus and knowledge security dataset | 0 | P0 | Done | #401 | #404 | `tests/unit/test_knowledge_cases.py`: schema and references (AC1), counts (AC2), licence and source per document (AC3) |
| RAG-00.04 | Dependency and image plan | 0 | P0 | Pending | #402 | — | — |
| RAG-01.01 | pgvector image, extension and startup check | 1 | P0 | Pending | — | — | — |
| RAG-01.02 | Knowledge tables, role grants and row-level security | 1 | P0 | Pending | — | — | — |
| RAG-01.03 | BlobStore for original files | 1 | P0 | Pending | — | — | — |
| RAG-02.01 | Worker entrypoint and job queue | 1 | P0 | Pending | — | — | — |
| RAG-02.02 | Document parser adapters | 1 | P0 | Pending | — | — | — |
| RAG-02.03 | Embedding provider and processing locality | 1 | P0 | Pending | — | — | — |
| RAG-02.04 | Idempotent ingest task | 1 | P0 | Pending | — | — | — |
| RAG-02.05 | Ingestion quotas and embedding token accounting | 1 | P0 | Pending | — | — | — |
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
| 2026-11-02 | RAG-00.03: corpus, schema and test; Done when #404 merges | Claude session |
| 2026-11-02 | Owner accepted ADR 0014: RAG-00.01 Done when #403 merges | Claude session |
| 2026-11-02 | RAG-00.01: ADR 0014 written as Proposed; amendment notes in ADR 0001/0002/0005; v1.1.0 in the roadmap. Status Partial until the owner accepts | Claude session |
| 2026-11-03 | E00 review: #364/#366 are fixed (#395), not closed as not planned; eval fixture path moved to `tests/fixtures/`; E00 approved for issue creation | Claude session |
| 2026-11-02 | Backlog drafted from the three research reports; tracker created; all stories Pending; repository checked at `4d5a6b5` | Claude session |
