"""Ingestion embeds a document in slices and keeps its vectors as float32 arrays (memory bound)."""

from __future__ import annotations

from array import array
from collections.abc import Sequence
from typing import Any, cast

import pytest

from neuron_agent.knowledge import ingest


class _Model:
    def __init__(self) -> None:
        self.calls: list[int] = []

    async def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        self.calls.append(len(texts))
        return [[float(len(text)), 0.5, -0.25] for text in texts]


@pytest.mark.anyio
async def test_a_large_document_is_embedded_in_slices_as_float32_arrays() -> None:
    model = _Model()
    passages = [f"p{i}" for i in range(ingest.EMBED_SLICE * 2 + 10)]

    vectors = await ingest.embed_passages(cast(Any, model), passages)

    assert model.calls == [ingest.EMBED_SLICE, ingest.EMBED_SLICE, 10]
    assert len(vectors) == len(passages)
    assert all(isinstance(v, array) and v.typecode == "f" for v in vectors)
    assert list(vectors[12]) == [3.0, 0.5, -0.25]  # in order, values kept
    assert ingest._vector(vectors[12]) == "[3.0,0.5,-0.25]"
