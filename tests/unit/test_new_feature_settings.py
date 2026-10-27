"""Staging and production refuse unsafe v0.7.0 configuration (#249, ADR 0009 decision 10).

Unit tests only: nothing here exercises a real staging or production deployment.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from pydantic import SecretStr, ValidationError
from tests.conftest import jwt_settings as _jwt_settings
from tests.unit.test_startup_checks import _Conn

from neuron_agent.agents.factory import build_registry
from neuron_agent.errors.base import ConfigurationError
from neuron_agent.persistence.checkpointer import build_persistence
from neuron_agent.persistence.startup_checks import (
    STORE_MISSING,
    STORE_NO_ACCESS,
    StartupCheckError,
    verify_store,
)
from neuron_agent.tools.registry import ToolSpec

pytestmark = pytest.mark.anyio

_PIN = "sha256:" + "a" * 64


def jwt_settings(**overrides: Any) -> Any:
    """The hardened test settings, with the provider key those environments require."""
    return _jwt_settings(openai_api_key=SecretStr("sk-test"), **overrides)


@pytest.mark.parametrize("env", ["staging", "production"])
@pytest.mark.parametrize("checkpointer", ["none"])
def test_memory_needs_the_postgres_checkpointer(env: str, checkpointer: str) -> None:
    with pytest.raises(ValidationError, match="APP_MEMORY_ENABLED needs APP_CHECKPOINTER=postgres"):
        jwt_settings(env=env, memory_enabled=True, checkpointer=checkpointer)


@pytest.mark.parametrize("env", ["staging", "production"])
def test_memory_is_accepted_with_postgres_and_off_by_default(env: str) -> None:
    on = jwt_settings(
        env=env,
        memory_enabled=True,
        checkpointer="postgres",
        postgres_dsn=SecretStr("postgresql://app@db.example.test/neuron?sslmode=verify-full"),
    )
    assert on.memory_enabled is True
    assert jwt_settings(env=env).memory_enabled is False


def test_memory_in_development_and_test_needs_nothing_special() -> None:
    assert jwt_settings(env="test", memory_enabled=True).memory_enabled is True
    assert jwt_settings(env="development", memory_enabled=True, checkpointer="none").memory_enabled


async def test_the_store_check_names_a_missing_table_and_a_role_without_access() -> None:
    await verify_store(_Conn({"present": True, "usable": True}))  # type: ignore[arg-type]
    with pytest.raises(StartupCheckError) as missing:
        await verify_store(_Conn({"present": False, "usable": False}))  # type: ignore[arg-type]
    with pytest.raises(StartupCheckError) as no_access:
        await verify_store(_Conn({"present": True, "usable": False}))  # type: ignore[arg-type]
    assert (missing.value.code, no_access.value.code) == (STORE_MISSING, STORE_NO_ACCESS)


@pytest.mark.parametrize(
    ("env", "memory", "expected"),
    [
        ("staging", True, True),
        ("production", True, True),
        ("production", False, False),
        ("test", True, False),
        ("development", True, False),
    ],
)
def test_the_store_check_runs_in_staging_and_production_with_memory_only(
    env: str, memory: bool, expected: bool
) -> None:
    extra: dict[str, Any] = {"checkpointer": "postgres"} if memory else {}
    if env in {"staging", "production"}:
        extra.setdefault(
            "postgres_dsn", SecretStr("postgresql://app@db.example.test/n?sslmode=verify-full")
        )
    if env in {"test", "development"}:
        extra["postgres_dsn"] = SecretStr("postgresql://app@localhost/n")
        extra["checkpointer"] = "postgres"
    settings = jwt_settings(env=env, memory_enabled=memory, **extra)
    assert build_persistence(settings).check_store is expected


def _file(tmp_path: Path, url: str, risk: str | None) -> Path:
    tool: dict[str, Any] = {"name": "do_it", "pin": _PIN}
    if risk:
        tool["risk"] = risk
    path = tmp_path / "mcp.json"
    path.write_text(
        json.dumps({"servers": [{"name": "units", "url": url, "auth": "none", "tools": [tool]}]}),
        encoding="utf-8",
    )
    return path


@pytest.mark.parametrize("env", ["staging", "production"])
async def test_an_http_mcp_server_stops_start_up_in_staging_and_production(
    env: str, tmp_path: Path
) -> None:
    settings = jwt_settings(
        env=env, mcp_servers=_file(tmp_path, "http://mcp.example.com/mcp", "read")
    )
    with pytest.raises(ConfigurationError, match="https"):
        await build_registry(settings)


@pytest.mark.parametrize("env", ["staging", "production"])
async def test_a_loopback_mcp_server_is_refused_there_too(env: str, tmp_path: Path) -> None:
    settings = jwt_settings(env=env, mcp_servers=_file(tmp_path, "http://127.0.0.1:9/mcp", "read"))
    with pytest.raises(ConfigurationError):
        await build_registry(settings)


@pytest.mark.parametrize("env", ["staging", "production"])
async def test_tools_that_need_approval_need_the_postgres_checkpointer(
    env: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from langchain_core.tools import tool

    @tool
    def mcp_units_do_it() -> str:
        """A tool that changes things."""
        return "done"

    async def discovered(*args: Any, **kwargs: Any) -> list[ToolSpec]:
        return [ToolSpec(mcp_units_do_it, "tools:mcp.units.do_it", "mutating", "mcp")]

    from neuron_agent.tools.mcp import client

    monkeypatch.setattr(client, "discover_mcp_specs", discovered)
    path = _file(tmp_path, "https://mcp.example.com/mcp", None)  # risk defaults to mutating

    without = jwt_settings(env=env, mcp_servers=path)  # checkpointer none
    with pytest.raises(ConfigurationError, match="APP_CHECKPOINTER=postgres"):
        await build_registry(without)

    with_postgres = jwt_settings(
        env=env,
        mcp_servers=path,
        checkpointer="postgres",
        postgres_dsn=SecretStr("postgresql://app@db.example.test/neuron?sslmode=verify-full"),
    )
    registry = await build_registry(with_postgres)
    assert registry is not None and [s.name for s in registry.mutating()] == ["mcp_units_do_it"]
