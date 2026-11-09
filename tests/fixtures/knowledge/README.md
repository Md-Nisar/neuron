# Knowledge eval corpus and security dataset

The labelled corpus for the Knowledge Engine (RAG-00.03, ADR 0014). The cases are in
`tests/fixtures/knowledge_cases.json`, their format in `knowledge_cases.schema.json`, and
`tests/unit/test_knowledge_cases.py` checks both in `make test`. Retrieval and security evals
(RAG-08.01, RAG-08.02) and the Phase 0 spike (RAG-00.02) use them.

## Documents

31 documents, two owners (`user_a`, `user_b`):

| Group | Files | Storage | Licence |
| --- | --- | --- | --- |
| 9 NIST publications (PDF, with tables) | — | URL and SHA-256 only | Public domain in the US (works of NIST) |
| 9 IETF RFCs (plain text) | — | URL and SHA-256 only | IETF Trust: RFCs may be reproduced in full |
| 3 project READMEs (Markdown, pinned to a tag) | — | URL and SHA-256 only | pgvector: PostgreSQL License; Procrastinate, Docling: MIT |
| Staff handbook (DOCX, tables) | `larkspur-handbook.docx` | In this folder | Apache-2.0, written for this repository |
| Maintenance log (PDF scanned to images, no text layer) | `greenhouse-log-scanned.pdf` | In this folder | Apache-2.0, written for this repository |
| ACL documents for the two users | `acl/` | In this folder | Apache-2.0, written for this repository |
| Prompt-injection documents | `injection/` | In this folder | Apache-2.0, written for this repository |

Public documents are not committed as files: they are large, and the dataset only needs to
identify them. What Neuron's parsers extract from them is committed, for the retrieval eval
(RAG-08.01, owner decision 2026-11-09): `eval/parsed.json.gz` holds every document's text as
blocks, with the pages and headings the parsers report, and `eval/vectors.*` the embeddings of
its chunks. Their licences allow it, and the notices are kept here: NIST publications are public
domain in the US; the IETF Trust lets RFCs be reproduced in full. The READMEs keep their
notices, from each project's licence at the pinned tag:

- pgvector (v0.8.0), PostgreSQL License: Portions Copyright (c) 1996-2024, PostgreSQL Global
  Development Group; Portions Copyright (c) 1994, The Regents of the University of California.
- Procrastinate (3.0.0), MIT License: Copyright (c) 2019-2021, PeopleDoc; Copyright (c)
  2021-2023, Joachim Jablon, Eric Lemoine.
- Docling (v2.15.0), MIT License: Copyright (c) 2024 International Business Machines.

Each licence permits copying provided the copyright and permission notices are kept; their full
texts are in `eval/licences/`. `scripts/build_knowledge_eval.py` rebuilds both files.

Fetch a document and check it before use, for example:

```bash
curl -sSLo nist-ai-100-1.pdf https://nvlpubs.nist.gov/nistpubs/ai/NIST.AI.100-1.pdf
sha256sum nist-ai-100-1.pdf   # must equal the dataset's sha256
```

Everything written for this repository is fictional. The corpus holds no personal or
confidential data, so it may be sent to a hosted embedding API.

## Conventions

- **Pages** are 1-based physical pages of the file, as a parser reports them, not printed
  page labels. A plain-text RFC's pages are separated by form feeds and match its `[Page N]` footers.
- Documents without pages (Markdown, DOCX, RFCs published without page breaks) are cited by
  **section**: the heading text exactly as it appears in the document.
- `expected_sources` lists every page or section that counts as a correct citation.
- `expected_keywords` pass when any one appears in the answer, ignoring case, as in `eval_cases.json`.
- `evidence` is a short quote from the expected page or section. When the dataset was written,
  each quote was checked against the text of the cited page, except for the scanned log, which
  has no text layer.

## Injection documents are inert data

The files in `injection/` carry instructions aimed at the model: white 4-point text in a PDF,
image alt text, a table cell and planted `cite_id`s. They exist to test that Neuron's controls
hold. **Never ingest them into a live environment's knowledge base.** Load them only into
test or evaluation knowledge bases.

## Rebuilding the generated files

`larkspur-handbook.docx`, `greenhouse-log-scanned.pdf` and `injection/hidden-text.pdf` are built
from `sources/` by `./build.sh`. It needs pandoc, LibreOffice, poppler-utils and Python with
Pillow, none of which are Neuron dependencies. The output is not byte-for-byte reproducible:
after a rebuild, update `sha256` and `size_bytes` in the dataset, which the unit test checks.
