"""Dense, full-text and hybrid search compared on the eval corpus (RAG-04.01 AC5).

Opt-in: set `APP_KNOWLEDGE_EVAL_DIR` to a directory holding the corpus's public documents (each
checked against its SHA-256) and the spike's cached `nemotron-3.5-embed-1b` vectors at 1,024
dimensions (`passages.npy`, `queries.npy`, RAG-00.02). Chunks are the spike's (pages, or sections
of unpaginated documents, cut to 1,200 characters with 200 of overlap), so the vectors match;
`pdftotext` and `pandoc` rebuild them. Each answerable case searches as its own user, through
`Retriever` on Postgres as the app role. Results go to `retrieval_eval.json` in that directory
and are recorded in `docs/releases/v1.1.0-retrieval-eval.md`.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import struct
import subprocess  # nosec B404 - fixed local tools on test data
import uuid
from array import array
from pathlib import Path
from typing import Any

import psycopg
import pytest
from langchain_core.embeddings import Embeddings
from test_postgres_knowledge_api import _Connections
from test_postgres_knowledge_tables import _knowledge_db
from test_postgres_roles import RoleDatabase, role_db, roles  # noqa: F401

from neuron_agent.config.settings import Settings
from neuron_agent.knowledge.ingest import _vector
from neuron_agent.knowledge.providers import EmbeddingProvider
from neuron_agent.knowledge.retrieval import Retriever

pytestmark = [pytest.mark.integration, pytest.mark.postgres, pytest.mark.anyio]

_DIR = os.environ.get("APP_KNOWLEDGE_EVAL_DIR")
_FIXTURES = Path("tests/fixtures")
_SIZE, _STEP = 1_200, 1_000


def _npy(path: Path) -> list[list[float]]:
    """Rows of a 2-D little-endian float32 `.npy` file (version 1), without numpy."""
    data = path.read_bytes()
    (length,) = struct.unpack("<H", data[8:10])
    header = data[10 : 10 + length].decode("latin-1")
    rows, cols = map(int, re.findall(r"\d+", header.split("shape")[1])[:2])
    assert "'<f4'" in header and "False" in header
    values = array("f", data[10 + length :])
    return [list(values[i * cols : (i + 1) * cols]) for i in range(rows)]


def _tool(name: str) -> str:
    path = shutil.which(name)
    assert path, name
    return path


def _norm(text: str) -> str:
    text = text.replace("\xad", "").replace("ﬁ", "fi").replace("’", "'")
    return re.sub(r"\s+", " ", text).lower().strip()


def _units(doc: dict[str, Any], path: Path) -> list[tuple[str, str]]:
    """(locator, text): the page number for paginated documents, else the nearest heading."""
    if path.suffix == ".pdf":
        out = subprocess.run(  # noqa: S603
            [_tool("pdftotext"), "-layout", str(path), "-"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout
        return [(str(i + 1), page) for i, page in enumerate(out.split("\f"))]
    if path.suffix == ".docx":
        text = subprocess.run(  # noqa: S603
            [_tool("pandoc"), str(path), "-t", "markdown"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout
    else:
        text = path.read_text(encoding="utf-8")
    if "page_count" in doc:
        return [(str(i + 1), page) for i, page in enumerate(text.split("\f"))]
    units, head, lines = [], "", []
    for line in text.splitlines():
        if re.match(r"^(#{1,6} |\d+(\.\d+)*\.  \S)", line):
            units.append((head, "\n".join(lines)))
            head, lines = line.strip(), [line]
        else:
            lines.append(line)
    return [*units, (head, "\n".join(lines))]


def _chunks(dataset: dict[str, Any], corpus: Path) -> list[tuple[str, str, str]]:
    """(document, locator, text) in the spike's order, which the cached vectors follow."""
    files = [*corpus.glob("*"), *(_FIXTURES / "knowledge").rglob("*")]
    by_sha = {hashlib.sha256(p.read_bytes()).hexdigest(): p for p in files if p.is_file()}
    chunks = []
    for doc in dataset["documents"]:
        path = by_sha.get(doc["sha256"])
        if path is None or "scanned" in doc["classes"]:
            continue
        for locator, unit in _units(doc, path):
            text = re.sub(r"[ \t]+", " ", unit).strip()
            for i in range(0, max(1, len(text) - (_SIZE - _STEP)), _STEP):
                if text[i : i + _SIZE].strip():
                    chunks.append((doc["id"], locator, text[i : i + _SIZE]))
    return chunks


def _hit(case: dict[str, Any], chunk: tuple[str, str, str]) -> bool:
    for source in case["expected_sources"]:
        if source["document"] != chunk[0]:
            continue
        if chunk[1] in {str(p) for p in source.get("pages", [])}:
            return True
        sections = source.get("sections", [])
        if sections and (
            any(_norm(s) in _norm(chunk[1]) for s in sections)
            or _norm(case["evidence"]) in _norm(chunk[2])
        ):
            return True
    return False


class _Cached(Embeddings):
    def __init__(self, vectors: dict[str, list[float]]) -> None:
        self._vectors = vectors

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        raise NotImplementedError

    def embed_query(self, text: str) -> list[float]:
        return self._vectors[text]


@pytest.mark.skipif(not _DIR, reason="APP_KNOWLEDGE_EVAL_DIR is not set")
@pytest.mark.skipif(not (shutil.which("pdftotext") and shutil.which("pandoc")), reason="tools")
async def test_hybrid_is_the_default_only_if_it_matches_dense_recall(
    role_db: RoleDatabase,  # noqa: F811
) -> None:
    assert _DIR
    corpus = Path(_DIR)
    dataset = json.loads((_FIXTURES / "knowledge_cases.json").read_text(encoding="utf-8"))
    chunks = _chunks(dataset, corpus)
    passages, queries = _npy(corpus / "passages.npy"), _npy(corpus / "queries.npy")
    scanned = {d["id"] for d in dataset["documents"] if "scanned" in d["classes"]}
    cases = [
        c
        for c in dataset["cases"]
        if c["category"] == "answerable"
        and not any(s["document"] in scanned for s in c["expected_sources"])
    ]
    assert (len(chunks), len(cases)) == (len(passages), len(queries))

    await _knowledge_db(role_db)
    owners = {u: hashlib.sha256(u.encode()).hexdigest() for u in dataset["users"]}
    owner_of = {d["id"]: owners[d["owner"]] for d in dataset["documents"]}
    kbs = {owner: uuid.uuid4() for owner in owners.values()}
    docs = {name: uuid.uuid4() for name in {c[0] for c in chunks}}
    found: dict[uuid.UUID, tuple[str, str, str]] = {}
    async with await psycopg.AsyncConnection.connect(role_db.migrator_dsn, autocommit=True) as conn:
        for owner, kb in kbs.items():
            await conn.execute(
                "INSERT INTO knowledge.bases (kb_id, owner_key, name, profile_id)"
                " VALUES (%s, %s, 'eval', 1)",
                (kb, owner),
            )
            await conn.execute(
                "INSERT INTO knowledge.grants (kb_id, subject_type, subject, access, granted_by)"
                " VALUES (%s, 'owner', %s, 'admin', %s)",
                (kb, owner, owner),
            )
        for name, doc in docs.items():
            await conn.execute(
                "INSERT INTO knowledge.documents (doc_id, kb_id, uploaded_by, title, mime_type,"
                " size_bytes, sha256, blob_key, status) VALUES (%s, %s, %s, %s, 'text/plain', 1,"
                " %s, 'k', 'ready')",
                (doc, kbs[owner_of[name]], owner_of[name], name, uuid.uuid4().hex * 2),
            )
        async with conn.cursor() as cursor:
            rows = []
            for ordinal, (chunk, vector) in enumerate(zip(chunks, passages, strict=True)):
                chunk_id = uuid.uuid4()
                found[chunk_id] = chunk
                kb = kbs[owner_of[chunk[0]]]
                rows.append((chunk_id, docs[chunk[0]], kb, ordinal, chunk[2], _vector(vector)))
            await cursor.executemany(
                "WITH c AS (INSERT INTO knowledge.chunks (chunk_id, doc_id, kb_id, ordinal, text,"
                " token_count, ts_config) VALUES (%s, %s, %s, %s, %s, 1, 'simple')"
                " RETURNING chunk_id, kb_id) INSERT INTO knowledge.embeddings"
                " (chunk_id, profile_id, kb_id, embedding) SELECT chunk_id, 1, kb_id, %s FROM c",
                rows,
            )
        await conn.execute("ANALYZE")

    cached = _Cached({c["question"]: q for c, q in zip(cases, queries, strict=True)})
    settings = Settings(env="test").model_copy(update={"knowledge_enabled": True})
    retriever = Retriever(
        settings,
        lambda: _Connections(role_db.app_dsn),  # type: ignore[arg-type,return-value]
        EmbeddingProvider(
            cached, cached, dimensions=1024, locality="self_hosted", batch_size=8, max_retries=0
        ),
    )
    results: dict[str, dict[str, float]] = {}
    for mode in ("dense", "fts", "hybrid"):
        ranks = []
        for case in cases:
            result = await retriever.search(
                owners[case["as_user"]], case["question"], k=10, mode=mode
            )
            hits = [i for i, p in enumerate(result.passages) if _hit(case, found[p.chunk_id])]
            ranks.append(hits[0] + 1 if hits else None)
        results[mode] = {
            f"recall@{k}": round(sum(r is not None and r <= k for r in ranks) / len(cases), 3)
            for k in (1, 5, 10)
        } | {"mrr@10": round(sum(1 / r for r in ranks if r) / len(cases), 3)}
    (corpus / "retrieval_eval.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    hybrid_holds = results["hybrid"]["recall@5"] >= results["dense"]["recall@5"]
    assert settings.knowledge_search_mode == ("hybrid" if hybrid_holds else "dense"), results
