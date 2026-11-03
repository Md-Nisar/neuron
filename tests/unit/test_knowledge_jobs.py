"""Job arguments are ids only (RAG-02.01; the Postgres side is in tests/integration)."""

from __future__ import annotations

from typing import Any

import pytest

from neuron_agent.knowledge import jobs

pytestmark = pytest.mark.anyio


@pytest.mark.parametrize("value", ["a document title", 7, b"bytes", None])
async def test_defer_refuses_anything_but_ids(value: Any) -> None:
    # Checked before the connection is touched: no text, file name or identity reaches a job.
    with pytest.raises(TypeError, match="ids only"):
        await jobs.defer(object(), jobs.Task.INGEST_DOCUMENT, doc_id=value)  # type: ignore[arg-type]
