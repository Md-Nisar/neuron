"""Index profiles as data (RAG-09.04, ADR 0014 amendment), before any re-index exists.

Search, ingestion, new bases and `setup` follow whichever profile is active, with the
configured model that embeds into it: the active one or the re-index one. A process with no
model for the active profile never compares vectors from two models.
"""

from __future__ import annotations

import dataclasses

import pytest
import structlog
from langchain_core.embeddings import Embeddings
from test_postgres_knowledge_api import _Connections
from test_postgres_knowledge_ingest import _document as _queued
from test_postgres_knowledge_ingest import setup  # noqa: F401
from test_postgres_knowledge_search import _A, _FAKE, _base, _document, _migrator
from test_postgres_knowledge_tables import _knowledge_db, _setup, worker  # noqa: F401
from test_postgres_roles import RoleDatabase, _rows, role_db, roles  # noqa: F401

from neuron_agent.config.settings import Settings
from neuron_agent.knowledge.ingest import Ingestor, _vector
from neuron_agent.knowledge.providers import EmbeddingProvider, FakeEmbeddings
from neuron_agent.knowledge.retrieval import Retriever
from neuron_agent.knowledge.service import KnowledgeBases
from neuron_agent.persistence.migrations import KnowledgeProfile
from neuron_agent.persistence.startup_checks import KNOWLEDGE_PROFILE_MISMATCH, StartupCheckError

pytestmark = [pytest.mark.integration, pytest.mark.postgres, pytest.mark.anyio]

_NEW = KnowledgeProfile("openai_compatible", "next-embed", 1024)


class _Other(FakeEmbeddings):
    """Another model's vector space: the same text lands elsewhere."""

    def embed_query(self, text: str) -> list[float]:
        return super().embed_query("other model: " + text)

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self.embed_query(text) for text in texts]


def _provider(embeddings: Embeddings, profile: KnowledgeProfile) -> EmbeddingProvider:
    return EmbeddingProvider(
        embeddings,
        embeddings,
        dimensions=profile.dimensions,
        locality="self_hosted",
        batch_size=8,
        max_retries=0,
        profile=profile,
    )


_OLD_MODEL = _provider(_FAKE, KnowledgeProfile())
_NEW_MODEL = _provider(_Other(1024), _NEW)


async def _new_profile(db: RoleDatabase, status: str = "building") -> None:
    await _migrator(
        db,
        "INSERT INTO knowledge.index_profiles (profile_id, provider, model, dimensions, chunker,"
        " status) VALUES (2, %s, %s, %s, 'neuron-headings-v1', %s)"
        " ON CONFLICT (profile_id) DO UPDATE SET status = excluded.status",
        _NEW.provider,
        _NEW.model,
        _NEW.dimensions,
        status,
    )


async def _activate_new_profile(db: RoleDatabase) -> None:
    """What a finished re-index leaves: profile 2 active, profile 1 retired, bases moved."""
    await _migrator(
        db, "UPDATE knowledge.index_profiles SET status = 'retired' WHERE profile_id = 1"
    )
    await _new_profile(db, "active")
    await _migrator(db, "UPDATE knowledge.bases SET profile_id = 2")


def _retriever(db: RoleDatabase, reindex: EmbeddingProvider | None) -> Retriever:
    settings = Settings(env="test").model_copy(update={"knowledge_enabled": True})
    return Retriever(
        settings,
        lambda: _Connections(db.app_dsn),  # type: ignore[arg-type,return-value]
        _OLD_MODEL,
        reindex=reindex,
    )


async def test_search_uses_the_active_profile_with_its_own_model(role_db: RoleDatabase) -> None:  # noqa: F811
    await _knowledge_db(role_db)
    kb = await _base(role_db, _A)
    old, new = await _document(role_db, kb, _A, ["old space", "new space"])
    # Profile 2, while it is built, holds only the second chunk, embedded by the new model.
    await _new_profile(role_db)
    await _migrator(
        role_db,
        "INSERT INTO knowledge.embeddings (chunk_id, profile_id, kb_id, embedding)"
        " VALUES (%s, 2, %s, %s)",
        new,
        kb,
        _vector(_Other(1024).embed_query("new space")),
    )
    before = await _retriever(role_db, _NEW_MODEL).search(_A, "old space", k=1, mode="dense")
    assert [p.chunk_id for p in before.passages] == [old]

    await _activate_new_profile(role_db)
    after = await _retriever(role_db, _NEW_MODEL).search(_A, "new space", k=5, mode="dense")
    # Profile 1's vectors are no longer searched, though they are still stored.
    assert [p.chunk_id for p in after.passages] == [new]


async def test_without_a_model_for_the_active_profile_search_is_text_only(
    role_db: RoleDatabase,  # noqa: F811
) -> None:
    await _knowledge_db(role_db)
    kb = await _base(role_db, _A)
    [chunk] = await _document(role_db, kb, _A, ["pump seven is serviced monthly"])
    await _activate_new_profile(role_db)
    with structlog.testing.capture_logs() as logs:
        dense = await _retriever(role_db, None).search(_A, "pump seven", k=5, mode="dense")
        hybrid = await _retriever(role_db, None).search(_A, "pump seven", k=5)
    assert (dense.status, dense.path) == ("no_relevant_results", "none")
    assert ([p.chunk_id for p in hybrid.passages], hybrid.path) == ([chunk], "none")
    assert {"event": "knowledge_profile_mismatch", "profile_id": 2} in [
        {k: log[k] for k in ("event", "profile_id") if k in log} for log in logs
    ]


async def test_ingestion_embeds_with_the_model_of_the_bases_profile(
    setup: tuple[RoleDatabase, Ingestor],  # noqa: F811
) -> None:
    db, ingestor = setup
    doc = await _queued(db, ingestor, processing="self_hosted")
    await _activate_new_profile(db)
    # Only the old model: retried, for the operator may still be moving the settings.
    with pytest.raises(Exception, match="knowledge_profile_mismatch"):
        await ingestor.ingest(doc, last_attempt=False)

    both = dataclasses.replace(ingestor, reindex=_NEW_MODEL)
    assert await both.ingest(doc) == "ready"
    rows = await _rows(
        db.migrator_dsn,
        "SELECT e.profile_id, e.embedding::text, c.text FROM knowledge.embeddings e"
        " JOIN knowledge.chunks c USING (chunk_id)",
    )
    assert [row[0] for row in rows] == [2] * len(rows) and rows
    for _, stored, text in rows:
        expected = _Other(1024).embed_query(text)
        got = [float(value) for value in stored.strip("[]").split(",")]
        # `halfvec` keeps about three significant digits.
        assert got == pytest.approx(expected, abs=1e-3)


async def test_a_new_base_takes_the_active_profile(role_db: RoleDatabase) -> None:  # noqa: F811
    await _knowledge_db(role_db)
    await _activate_new_profile(role_db)
    settings = Settings(env="test").model_copy(update={"knowledge_enabled": True})
    bases = KnowledgeBases(settings, lambda: _Connections(role_db.app_dsn))  # type: ignore[arg-type,return-value]
    created = await bases.create(_A, "Budget", "hosted")
    assert await _rows(
        role_db.migrator_dsn,
        "SELECT profile_id FROM knowledge.bases WHERE kb_id = %s",
        (created.kb_id,),
    ) == [(2,)]


async def test_setup_needs_a_model_for_the_active_profile_and_indexes_it(
    role_db: RoleDatabase,  # noqa: F811
) -> None:
    await _knowledge_db(role_db)
    await _activate_new_profile(role_db)
    with pytest.raises(StartupCheckError) as caught:
        await _setup(role_db, knowledge=True)
    assert caught.value.code == KNOWLEDGE_PROFILE_MISMATCH
    # Right after the swap: the new model is still the re-index one.
    await _setup(role_db, knowledge=True, knowledge_reindex_profile=_NEW)
    # Once the operator moves it into the main settings.
    await _setup(role_db, knowledge=True, knowledge_profile=_NEW)
    indexes = await _rows(
        role_db.migrator_dsn,
        "SELECT indexname FROM pg_indexes WHERE schemaname = 'knowledge'"
        " AND indexname LIKE 'embeddings_p%%_hnsw'",
    )
    # The retired profile's index stays until a re-index cleans it up.
    assert sorted(row[0] for row in indexes) == [
        "embeddings_p1_hnsw",
        "embeddings_p2_hnsw",
    ]
