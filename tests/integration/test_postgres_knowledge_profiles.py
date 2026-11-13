"""Index profiles as data (RAG-09.04, ADR 0014 amendment), before any re-index exists.

Search, ingestion, new bases and `setup` follow whichever profile is active, with the
configured model that embeds into it: the active one or the re-index one. A process with no
model for the active profile never compares vectors from two models.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Sequence

import psycopg
import pytest
import structlog
from langchain_core.embeddings import Embeddings
from test_postgres_knowledge_api import _Connections
from test_postgres_knowledge_ingest import _document as _queued
from test_postgres_knowledge_ingest import setup  # noqa: F401
from test_postgres_knowledge_search import _A, _FAKE, _base, _document, _migrator
from test_postgres_knowledge_tables import _knowledge_db, _setup, worker  # noqa: F401
from test_postgres_roles import RoleDatabase, _rows, role_db, roles  # noqa: F401

from neuron_agent.config.settings import ProcessingLocality, Settings
from neuron_agent.knowledge.chunking import estimate_tokens
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


def _provider(
    embeddings: Embeddings, profile: KnowledgeProfile, locality: ProcessingLocality = "self_hosted"
) -> EmbeddingProvider:
    return EmbeddingProvider(
        embeddings,
        embeddings,
        dimensions=profile.dimensions,
        locality=locality,
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
    stored = await _stored(db)
    assert list(stored) == [2]
    _assert_embedded_by(stored[2], _Other(1024))


async def _stored(db: RoleDatabase) -> dict[int, list[tuple[str, str]]]:
    """Each profile's stored vectors, with the passage each one embeds."""
    rows = await _rows(
        db.migrator_dsn,
        "SELECT e.profile_id, e.embedding::text, array_to_string(c.headings || c.text, E'\\n')"
        " FROM knowledge.embeddings e JOIN knowledge.chunks c USING (chunk_id)"
        " ORDER BY e.profile_id, c.ordinal",
    )
    stored: dict[int, list[tuple[str, str]]] = {}
    for profile_id, vector, passage in rows:
        stored.setdefault(profile_id, []).append((vector, passage))
    return stored


def _assert_embedded_by(rows: Sequence[tuple[str, str]], embeddings: Embeddings) -> None:
    assert rows
    for vector, passage in rows:
        got = [float(value) for value in vector.strip("[]").split(",")]
        # `halfvec` keeps about three significant digits.
        assert got == pytest.approx(embeddings.embed_query(passage), abs=1e-3)


async def test_during_a_reindex_an_upload_is_embedded_for_both_profiles(
    setup: tuple[RoleDatabase, Ingestor],  # noqa: F811
) -> None:
    db, ingestor = setup
    doc = await _queued(db, ingestor, processing="self_hosted")
    await _new_profile(db)
    # A worker not yet given the re-index model retries rather than skip the new profile.
    with pytest.raises(Exception, match="knowledge_profile_mismatch"):
        await ingestor.ingest(doc, last_attempt=False)

    assert await dataclasses.replace(ingestor, reindex=_NEW_MODEL).ingest(doc) == "ready"
    stored = await _stored(db)
    assert sorted(stored) == [1, 2]
    _assert_embedded_by(stored[1], _FAKE)
    _assert_embedded_by(stored[2], _Other(1024))
    # Both embeddings are charged to the document.
    once = sum(estimate_tokens(passage) for _, passage in stored[1])
    assert await _rows(
        db.migrator_dsn,
        "SELECT embedding_tokens FROM knowledge.documents WHERE doc_id = %s",
        (doc,),
    ) == [(2 * once,)]


async def test_a_base_whose_setting_forbids_the_new_model_gets_only_the_active_one(
    setup: tuple[RoleDatabase, Ingestor],  # noqa: F811
) -> None:
    """Its text never reaches a hosted re-index model; the re-index job refuses the base."""
    db, ingestor = setup
    doc = await _queued(db, ingestor, processing="self_hosted")
    await _new_profile(db)
    hosted = _provider(_Other(1024), _NEW, locality="hosted")
    assert await dataclasses.replace(ingestor, reindex=hosted).ingest(doc) == "ready"
    assert list(await _stored(db)) == [1]


async def test_ingestion_retries_if_the_profiles_change_while_it_embeds(
    setup: tuple[RoleDatabase, Ingestor],  # noqa: F811
) -> None:
    """A re-index that starts mid-embedding would leave the document without new vectors."""
    db, ingestor = setup
    doc = await _queued(db, ingestor, processing="self_hosted")

    class _Starting(EmbeddingProvider):
        async def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
            await _new_profile(db)
            return await super().embed_documents(texts)

    starting = dataclasses.replace(
        ingestor,
        embeddings=_Starting(
            _FAKE, _FAKE, dimensions=1024, locality="self_hosted", batch_size=8, max_retries=0
        ),
        reindex=_NEW_MODEL,
    )
    with pytest.raises(Exception, match="knowledge_profile_changed"):
        await starting.ingest(doc, last_attempt=False)
    assert await _stored(db) == {}

    assert await dataclasses.replace(ingestor, reindex=_NEW_MODEL).ingest(doc) == "ready"
    assert sorted(await _stored(db)) == [1, 2]


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
    # A retired profile is never searched again: setup drops its index.
    assert sorted(row[0] for row in indexes) == ["embeddings_p2_hnsw"]


@pytest.mark.parametrize("status", ["active", "building"])
async def test_the_database_holds_at_most_one_profile_per_status(
    role_db: RoleDatabase,  # noqa: F811
    status: str,
) -> None:
    """Two active rows would give a new base two profiles, and search an arbitrary one."""
    await _knowledge_db(role_db)
    if status == "building":  # profile 1 is the active one already
        await _new_profile(role_db)
    with pytest.raises(psycopg.errors.UniqueViolation):
        await _migrator(
            role_db,
            "INSERT INTO knowledge.index_profiles (profile_id, provider, model, dimensions,"
            " chunker, status) VALUES (3, 'fake', 'third', 8, 'neuron-headings-v1', %s)",
            status,
        )
