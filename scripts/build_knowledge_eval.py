# Copyright 2026 Md Nisar Ahmed
# SPDX-License-Identifier: Apache-2.0

"""Build the knowledge retrieval eval's data (RAG-08.01) in `tests/fixtures/knowledge/eval/`.

    uv run python scripts/build_knowledge_eval.py parse CORPUS REPLIES
    NVIDIA_API_KEY=... uv run python scripts/build_knowledge_eval.py embed

`parse` writes `parsed.json.gz`: every document of `knowledge_cases.json` as Neuron's parsers
return it. CORPUS holds the public documents, each checked against the dataset's SHA-256 (see
`tests/fixtures/knowledge/README.md`); the repository's own are found in that folder. REPLIES
holds a Docling reply per PDF or DOCX (`<id>.docling.json.gz`, written by
`tests/fixtures/knowledge/recorded/record.py`), which `DoclingServeParser` normalises as it does
docling-serve's. Run it again after a parser change.

`embed` chunks the parsed documents with Neuron's chunker and writes `vectors.json` and
`vectors.f16.gz`: the configured embedding model's vector of every chunk's passage (the text
ingestion embeds) and every case's question, keyed by SHA-256. Only missing vectors are
requested, and unused ones are dropped. Run it after a chunker or model change; the eval fails
until then.
"""

from __future__ import annotations

import asyncio
import gzip
import hashlib
import json
import struct
import sys
from pathlib import Path
from typing import Any

from neuron_agent.config.settings import Settings
from neuron_agent.knowledge.chunking import chunk_document
from neuron_agent.knowledge.docling_serve import DoclingServeParser
from neuron_agent.knowledge.ingest import _passage
from neuron_agent.knowledge.parsing import (
    MARKDOWN,
    TEXT,
    Limits,
    ParsedDocument,
    PlainTextParser,
    parse_document,
)
from neuron_agent.knowledge.providers import create_embedding_provider

FIXTURES = Path("tests/fixtures/knowledge")
DATASET = Path("tests/fixtures/knowledge_cases.json")
OUT = FIXTURES / "eval"
PARSED = OUT / "parsed.json.gz"
VECTORS_INDEX = OUT / "vectors.json"
VECTORS = OUT / "vectors.f16.gz"


def key(kind: str, text: str) -> str:
    """A vector's key: what was embedded, as a passage or as a query."""
    return hashlib.sha256(f"{kind}\0{text}".encode()).hexdigest()


def load_parsed() -> dict[str, ParsedDocument]:
    with gzip.open(PARSED, "rt", encoding="utf-8") as source:
        documents = json.load(source)["documents"]
    return {doc: ParsedDocument.model_validate(parsed) for doc, parsed in documents.items()}


def passages(parsed: dict[str, ParsedDocument], max_tokens: int) -> dict[str, list[Any]]:
    """Each document's chunks, as ingestion cuts them."""
    return {doc: chunk_document(document, max_tokens) for doc, document in parsed.items()}


def load_vectors() -> tuple[dict[str, Any], dict[str, tuple[float, ...]]]:
    """The index (model, dimensions, keys) and each key's vector."""
    index = json.loads(VECTORS_INDEX.read_text(encoding="utf-8"))
    data = gzip.decompress(VECTORS.read_bytes())
    width = index["dimensions"]
    size = 2 * width
    assert len(data) == size * len(index["keys"]), "vectors.f16.gz does not match vectors.json"
    return index, {
        k: struct.unpack(f"<{width}e", data[i * size : (i + 1) * size])
        for i, k in enumerate(index["keys"])
    }


def _write_vectors(model: str, dimensions: int, vectors: dict[str, tuple[float, ...]]) -> None:
    keys = sorted(vectors)
    body = b"".join(struct.pack(f"<{dimensions}e", *vectors[k]) for k in keys)
    VECTORS.write_bytes(gzip.compress(body, mtime=0))
    index = {"model": model, "dimensions": dimensions, "keys": keys}
    VECTORS_INDEX.write_text(json.dumps(index, indent=0) + "\n", encoding="utf-8")


async def parse(corpus: Path, replies: Path) -> None:
    dataset = json.loads(DATASET.read_text(encoding="utf-8"))
    limits = Limits.from_settings(Settings(env="test"))
    files = [p for p in [*corpus.iterdir(), *FIXTURES.rglob("*")] if p.is_file()]
    by_sha = {hashlib.sha256(p.read_bytes()).hexdigest(): p for p in files}
    documents: dict[str, Any] = {}
    for doc in dataset["documents"]:
        path = by_sha.get(doc["sha256"])
        if path is None:
            sys.exit(f"{doc['id']}: no file in {corpus} with the dataset's SHA-256")
        if doc["media_type"] in (TEXT, MARKDOWN):
            parsed = await parse_document(
                path.read_bytes(), doc["media_type"], limits, [PlainTextParser()]
            )
        else:
            reply = gzip.decompress((replies / f"{doc['id']}.docling.json.gz").read_bytes())
            parsed = DoclingServeParser._normalise(reply, limits)
        documents[doc["id"]] = parsed.model_dump(mode="json", exclude_none=True)
        print(f"{doc['id']}: {len(parsed.blocks)} blocks, {parsed.page_count} pages")
    OUT.mkdir(exist_ok=True)
    body = json.dumps({"dataset_version": dataset["version"], "documents": documents})
    PARSED.write_bytes(gzip.compress(body.encode(), mtime=0))


async def embed() -> None:
    settings = Settings(env="test").model_copy(update={"knowledge_embedding_provider": "nvidia"})
    provider = create_embedding_provider(settings)
    dataset = json.loads(DATASET.read_text(encoding="utf-8"))
    chunks = passages(load_parsed(), settings.knowledge_chunk_max_tokens)
    texts = {key("passage", t): t for cs in chunks.values() for t in map(_passage, cs)}
    questions = {key("query", c["question"]): c["question"] for c in dataset["cases"]}
    known: dict[str, tuple[float, ...]] = {}
    if VECTORS_INDEX.exists():
        index, known = load_vectors()
        if (index["model"], index["dimensions"]) != (
            settings.knowledge_embedding_model,
            settings.knowledge_embedding_dimensions,
        ):
            known = {}
    wanted = texts | questions
    vectors = {k: v for k, v in known.items() if k in wanted}
    missing = [k for k in texts if k not in vectors]
    print(f"{len(texts)} passages, {len(questions)} questions; embedding {len(missing)} passages")
    for start in range(0, len(missing), 256):
        batch = missing[start : start + 256]
        for k, vector in zip(
            batch, await provider.embed_documents([texts[k] for k in batch]), strict=True
        ):
            vectors[k] = tuple(vector)
    for k, question in questions.items():
        if k not in vectors:
            vectors[k] = tuple(await provider.embed_query(question))
    _write_vectors(
        settings.knowledge_embedding_model, settings.knowledge_embedding_dimensions, vectors
    )
    print(f"wrote {len(vectors)} vectors")


def main(argv: list[str]) -> None:
    if argv[:1] == ["parse"] and len(argv) == 3:
        asyncio.run(parse(Path(argv[1]), Path(argv[2])))
    elif argv == ["embed"]:
        asyncio.run(embed())
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main(sys.argv[1:])
