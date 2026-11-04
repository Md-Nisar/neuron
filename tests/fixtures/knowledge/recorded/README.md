# Recorded parser replies

The recorded fake for `DoclingServeParser` (RAG-02.02): unit tests replay these files instead
of calling docling-serve.

| File | Source | Recorded with |
| --- | --- | --- |
| `nist-cswp-29.docling.json.gz` | `nist-cswp-29` in `knowledge_cases.json` (SHA-256 checked) | docling 2.146.0, docling-core 2.105.0, CPU, 2026-11-04 |

Each file is the JSON docling-serve returns from `/v1/convert/file` with `to_formats=json`:
`status`, and the `DoclingDocument` under `document.json_content`. It was produced by
`record.py` with the Docling library that docling-serve wraps, using the options the parser
posts, because the docling-serve image (7.57 GB) did not fit the recording machine. The
structure matches the RAG-00.02 spike's docling-serve v1.38.2 run of the same file: 32 pages,
40 section headers, 4 tables.

To re-record after a docling-serve upgrade, download the PDF (see `../README.md`), check its
SHA-256, run `record.py` in an environment with Docling, and update the table above.
