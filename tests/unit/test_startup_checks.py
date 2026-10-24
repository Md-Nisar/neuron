"""Database start-up checks (#139, ADR 0008 decisions 15 and 16) without a database."""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import SecretStr

from neuron_agent.config.settings import Settings
from neuron_agent.persistence.checkpointer import build_persistence
from neuron_agent.persistence.migrations import identity_check_value
from neuron_agent.persistence.startup_checks import (
    IDENTITY_KEY_MISMATCH,
    IDENTITY_KEY_UNRECORDED,
    TLS_REQUIRED,
    StartupCheckError,
    verify_identity_key,
    verify_tls,
)

pytestmark = pytest.mark.anyio


class _Cursor:
    def __init__(self, row: dict[str, Any] | None) -> None:
        self._row = row

    async def fetchone(self) -> dict[str, Any] | None:
        return self._row


class _Conn:
    def __init__(self, row: dict[str, Any] | None) -> None:
        self.row = row

    async def execute(self, _query: str, _params: Any = None) -> _Cursor:
        return _Cursor(self.row)


async def test_tls_passes_only_on_ssl_true() -> None:
    await verify_tls(_Conn({"ssl": True}))  # type: ignore[arg-type]
    for row in ({"ssl": False}, {"ssl": None}, None):
        with pytest.raises(StartupCheckError) as caught:
            await verify_tls(_Conn(row))  # type: ignore[arg-type]
        assert caught.value.code == TLS_REQUIRED


@pytest.mark.parametrize(
    ("status", "code"),
    [
        ("mismatch", IDENTITY_KEY_MISMATCH),
        ("unset", IDENTITY_KEY_UNRECORDED),
        (None, IDENTITY_KEY_MISMATCH),
    ],
)
async def test_identity_key_failures_carry_a_stable_code(status: str | None, code: str) -> None:
    with pytest.raises(StartupCheckError) as caught:
        await verify_identity_key(_Conn({"status": status}), "c" * 64)  # type: ignore[arg-type]
    assert caught.value.code == code
    assert "c" * 64 not in str(caught.value)
    await verify_identity_key(_Conn({"status": "match"}), "c" * 64)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("env", "tls", "role", "check"),
    [
        ("production", True, "neuron_app", True),
        ("staging", True, None, True),
        ("development", False, None, False),
        ("test", False, None, False),
    ],
)
def test_checks_are_set_for_staging_and_production_only(
    env: str, tls: bool, role: str | None, check: bool
) -> None:
    key = "k" * 40
    persistence = build_persistence(
        Settings.model_construct(
            env=env,
            checkpointer="postgres",
            limits_backend="memory",
            postgres_dsn=SecretStr("postgresql://app@localhost/db"),
            postgres_app_role="neuron_app",
            identity_hash_key=SecretStr(key),
        )
    )
    assert persistence.require_tls is tls
    assert persistence.app_role == role
    expected = identity_check_value(key) if check else None
    assert persistence.identity_check == expected
    assert key not in repr(persistence)
    assert expected is None or expected not in repr(persistence)
