"""Knowledge storage foundation (RAG-01.01, ADR 0014): setting, setup check and start-up check.

No database here; `tests/integration/test_postgres_knowledge.py` runs the same paths on Postgres.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from pydantic import SecretStr, ValidationError
from tests.unit.test_production_feature_guards import jwt_settings
from tests.unit.test_startup_checks import _Conn

from neuron_agent.config.settings import Settings
from neuron_agent.persistence import cli, migrations
from neuron_agent.persistence.checkpointer import build_persistence, knowledge_profile
from neuron_agent.persistence.migrations import MIGRATIONS, KnowledgeProfile, Migration
from neuron_agent.persistence.roles import AppRoleError
from neuron_agent.persistence.startup_checks import (
    KNOWLEDGE_SCHEMA_MISSING,
    KNOWLEDGE_SCHEMA_UNTRUSTED,
    VECTOR_EXTENSION_MISSING,
    StartupCheckError,
    knowledge_problem,
    verify_knowledge,
)

pytestmark = pytest.mark.anyio

_DSN = SecretStr("postgresql://app@localhost/n")
# Settings only check the path; nothing is created there.
_ABSOLUTE_BLOB_ROOT = str(Path.cwd().resolve() / "var" / "knowledge-blobs")


def test_knowledge_is_off_by_default() -> None:
    assert Settings(env="test").knowledge_enabled is False


@pytest.mark.parametrize("checkpointer", ["memory", "none", "auto"])
def test_knowledge_needs_the_postgres_checkpointer(checkpointer: str) -> None:
    with pytest.raises(ValidationError, match="APP_KNOWLEDGE_ENABLED needs APP_CHECKPOINTER"):
        Settings(env="test", knowledge_enabled=True, checkpointer=checkpointer)
    Settings(env="test", knowledge_enabled=True, checkpointer="postgres", postgres_dsn=_DSN)


@pytest.mark.parametrize("env", ["staging", "production"])
def test_knowledge_with_nvidia_needs_its_key_in_staging_and_production(env: str) -> None:
    hardened: dict[str, Any] = {
        "env": env,
        "checkpointer": "postgres",
        "postgres_dsn": SecretStr("postgresql://app@db.example.test/n?sslmode=verify-full"),
        "knowledge_blob_local_allowed": True,
        "knowledge_blob_root": _ABSOLUTE_BLOB_ROOT,
    }
    with pytest.raises(ValidationError, match="needs NVIDIA_API_KEY"):
        jwt_settings(knowledge_enabled=True, **hardened)
    jwt_settings(knowledge_enabled=True, nvidia_api_key=SecretStr("nv-test"), **hardened)
    # Off, the key is not needed: deployments that never enable knowledge are unchanged.
    jwt_settings(knowledge_enabled=False, **hardened)


@pytest.mark.parametrize(
    ("env", "knowledge", "check"),
    [
        ("staging", True, True),
        ("production", True, True),
        ("production", False, False),
        ("development", True, False),
        ("test", True, False),
    ],
)
def test_the_start_up_check_runs_in_staging_and_production_with_knowledge_only(
    env: str, knowledge: bool, check: bool
) -> None:
    dsn = (
        SecretStr("postgresql://app@db.example.test/n?sslmode=verify-full")
        if env in {"staging", "production"}
        else _DSN
    )
    settings = jwt_settings(
        env=env,
        checkpointer="postgres",
        postgres_dsn=dsn,
        knowledge_enabled=knowledge,
        nvidia_api_key=SecretStr("nv-test"),
        knowledge_blob_local_allowed=True,
        knowledge_blob_root=_ABSOLUTE_BLOB_ROOT,
    )
    persistence = build_persistence(settings)
    assert persistence.check_knowledge is check
    # Readiness checks knowledge wherever it is on, development included.
    assert persistence.knowledge_enabled is knowledge


@pytest.mark.parametrize(
    ("row", "code"),
    [
        ({"vector": False, "schema": False}, VECTOR_EXTENSION_MISSING),
        ({"vector": False, "schema": True}, VECTOR_EXTENSION_MISSING),
        ({"vector": True, "schema": False}, KNOWLEDGE_SCHEMA_MISSING),
        (None, VECTOR_EXTENSION_MISSING),
    ],
)
async def test_a_missing_extension_or_schema_has_a_stable_code(
    row: dict[str, Any] | None, code: str
) -> None:
    assert await knowledge_problem(_Conn(row)) == code  # type: ignore[arg-type]
    with pytest.raises(StartupCheckError) as caught:
        await verify_knowledge(_Conn(row))  # type: ignore[arg-type]
    assert caught.value.code == code
    # The message names what is missing and how to fix it, never a DSN or host.
    assert ("vector extension" if code == VECTOR_EXTENSION_MISSING else "knowledge schema") in str(
        caught.value
    )


async def test_the_start_up_check_passes_with_both() -> None:
    row = {"vector": True, "schema": True, "can_create": False}
    assert await knowledge_problem(_Conn(row)) is None  # type: ignore[arg-type]
    await verify_knowledge(_Conn(row))  # type: ignore[arg-type]
    await verify_knowledge(_Conn(row), least_privilege=True)  # type: ignore[arg-type]


async def test_production_refuses_a_runtime_role_that_can_create_in_the_schema() -> None:
    row = {"vector": True, "schema": True, "can_create": True}
    # Development, test and staging's single-role profile allow it; readiness ignores it.
    await verify_knowledge(_Conn(row))  # type: ignore[arg-type]
    assert await knowledge_problem(_Conn(row)) is None  # type: ignore[arg-type]
    with pytest.raises(StartupCheckError) as caught:
        await verify_knowledge(_Conn(row), least_privilege=True)  # type: ignore[arg-type]
    assert caught.value.code == KNOWLEDGE_SCHEMA_UNTRUSTED


_READY = {
    "installed": True,
    "available": True,
    "superuser": False,
    "schema": True,
    "can_create_schema": False,
}


@pytest.mark.parametrize(
    ("changes", "code", "fragment"),
    [
        ({"installed": False, "available": False}, VECTOR_EXTENSION_MISSING, "not available"),
        ({"installed": False}, VECTOR_EXTENSION_MISSING, "CREATE EXTENSION vector"),
        ({"schema": False}, KNOWLEDGE_SCHEMA_MISSING, "CREATE SCHEMA knowledge AUTHORIZATION"),
    ],
)
async def test_setup_names_what_the_migration_role_cannot_create(
    changes: dict[str, Any], code: str, fragment: str
) -> None:
    with pytest.raises(StartupCheckError) as caught:
        await migrations._check_knowledge_prerequisites(_Conn({**_READY, **changes}))  # type: ignore[arg-type]
    assert caught.value.code == code
    assert fragment in str(caught.value)


@pytest.mark.parametrize(
    "changes",
    [
        {},  # the operator created both
        {"installed": False, "superuser": True, "schema": False, "can_create_schema": True},
        {"schema": False, "can_create_schema": True},
    ],
)
async def test_setup_proceeds_when_both_exist_or_can_be_created(changes: dict[str, Any]) -> None:
    await migrations._check_knowledge_prerequisites(_Conn({**_READY, **changes}))  # type: ignore[arg-type]


def test_the_knowledge_migration_is_feature_gated() -> None:
    gated = [m for m in MIGRATIONS if m.feature is not None]
    assert [m.version for m in gated] == list(range(17, 25))
    assert {m.feature for m in gated} == {"knowledge"}
    assert gated[0].name == "knowledge_schema"
    assert "CREATE EXTENSION IF NOT EXISTS vector" in gated[0].sql
    # `CREATE SCHEMA IF NOT EXISTS` checks the database privilege even when the schema exists.
    assert "CREATE SCHEMA knowledge" in gated[0].sql
    assert "CREATE SCHEMA IF NOT EXISTS" not in gated[0].sql
    assert Migration(version=1, name="x", sql="").feature is None


@pytest.mark.parametrize("enabled", [True, False])
def test_cli_setup_passes_the_knowledge_setting(
    monkeypatch: pytest.MonkeyPatch, enabled: bool
) -> None:
    seen: dict[str, object] = {}

    async def fake_run_setup(dsn: str, **kwargs: object) -> list[int]:
        seen.update(kwargs)
        return []

    monkeypatch.setattr(migrations, "run_setup", fake_run_setup)
    settings = Settings.model_construct(
        env="development",
        postgres_dsn=None,
        postgres_migration_dsn=SecretStr("postgresql://m:p@h/d"),
        identity_hash_key=None,
        knowledge_enabled=enabled,
    )
    cli._setup(settings, rotate_identity_key=False)
    assert seen["knowledge"] is enabled


def test_knowledge_grants_are_exact_and_revoke_first() -> None:
    statements = [
        s.as_string()
        for s in migrations.knowledge_grant_statements(
            {"app": "neuron_app", "worker": "neuron_worker"}, {"chunks", "grants"}
        )
    ]
    assert statements == [
        'GRANT USAGE ON SCHEMA "knowledge" TO "neuron_app"',
        'REVOKE ALL ON "knowledge"."grants" FROM "neuron_app"',
        'GRANT DELETE, INSERT, SELECT, UPDATE ON "knowledge"."grants" TO "neuron_app"',
        'REVOKE ALL ON "knowledge"."chunks" FROM "neuron_app"',
        'GRANT SELECT ON "knowledge"."chunks" TO "neuron_app"',
        'GRANT USAGE ON SCHEMA "knowledge" TO "neuron_worker"',
        'REVOKE ALL ON "knowledge"."grants" FROM "neuron_worker"',
        'REVOKE ALL ON "knowledge"."chunks" FROM "neuron_worker"',
        'GRANT DELETE, INSERT, SELECT ON "knowledge"."chunks" TO "neuron_worker"',
    ]


def test_the_profile_comes_from_the_embedding_settings() -> None:
    settings = Settings(
        env="test", knowledge_embedding_provider="fake", knowledge_embedding_dimensions=8
    )
    assert knowledge_profile(settings) == KnowledgeProfile(
        provider="fake", model="nvidia/nemotron-3.5-embed-1b", dimensions=8
    )


def test_the_worker_role_name_is_a_plain_unreserved_name() -> None:
    assert Settings(env="test").postgres_worker_role == "neuron_worker"
    for bad in ("pg_worker", "Worker", "a-b", 'x"; DROP'):
        with pytest.raises(ValidationError):
            Settings(env="test", postgres_worker_role=bad)


async def test_a_missing_worker_role_is_skipped_and_a_shared_one_refused() -> None:
    assert await migrations._resolve_worker_role(_Conn({"found": False}), "w", "m", "a") is None  # type: ignore[arg-type]
    assert await migrations._resolve_worker_role(_Conn({"found": True}), "w", "m", "a") == "w"  # type: ignore[arg-type]
    assert await migrations._resolve_worker_role(_Conn(None), None, "m", "a") is None  # type: ignore[arg-type]
    for shared in ("m", "a"):
        with pytest.raises(AppRoleError):
            await migrations._resolve_worker_role(_Conn(None), shared, "m", "a")  # type: ignore[arg-type]
