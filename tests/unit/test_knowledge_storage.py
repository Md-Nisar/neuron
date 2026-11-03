"""Knowledge storage foundation (RAG-01.01, ADR 0014): setting, setup check and start-up check.

No database here; `tests/integration/test_postgres_knowledge.py` runs the same paths on Postgres.
"""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import SecretStr, ValidationError
from tests.unit.test_production_feature_guards import jwt_settings
from tests.unit.test_startup_checks import _Conn

from neuron_agent.config.settings import Settings
from neuron_agent.persistence import cli, migrations
from neuron_agent.persistence.checkpointer import build_persistence
from neuron_agent.persistence.migrations import MIGRATIONS, Migration
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
    assert [(m.version, m.name, m.feature) for m in gated] == [
        (17, "knowledge_schema", "knowledge")
    ]
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
