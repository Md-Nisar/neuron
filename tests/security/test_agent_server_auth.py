"""Agent Server authentication and resource authorization tests."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from pydantic import SecretStr

from neuron_agent.errors.base import AuthenticationError
from neuron_agent.security import agent_server
from neuron_agent.security.auth import Principal, principal_owner_key

pytestmark = pytest.mark.anyio


def test_fastapi_and_agent_server_share_verifier_instance() -> None:
    from neuron_agent.api import main as api_main

    assert api_main.auth_verifier is agent_server.token_verifier


def _context(
    identity: str = "opaque-owner-a", permissions: frozenset[str] = frozenset()
) -> SimpleNamespace:
    return SimpleNamespace(user=SimpleNamespace(identity=identity, permissions=permissions))


async def test_authentication_returns_owner_key_and_permissions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    principal = Principal(
        issuer="https://issuer.example",
        subject="private-subject",
        scopes=frozenset({"agent:invoke", "threads:read"}),
        token_id=None,
        expires_at=datetime.now(UTC),
    )

    class Verifier:
        async def verify(self, authorization: str | None) -> Principal:
            assert authorization == "Bearer signed-token"
            return principal

    settings = SimpleNamespace(
        auth_mode="jwt",
        env="production",
        identity_hash_key=SecretStr("h" * 32),
    )
    monkeypatch.setattr(agent_server, "settings", settings)
    monkeypatch.setattr(agent_server, "token_verifier", Verifier())

    user = await agent_server.authenticate("Bearer signed-token")

    assert user["identity"] == principal_owner_key(principal, "h" * 32)
    assert user["identity"] != principal.subject
    assert set(user["permissions"]) == principal.scopes


async def test_invalid_token_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    class Verifier:
        async def verify(self, authorization: str | None) -> Principal:
            raise AuthenticationError()

    monkeypatch.setattr(
        agent_server,
        "settings",
        SimpleNamespace(auth_mode="jwt", env="production", identity_hash_key=SecretStr("h" * 32)),
    )
    monkeypatch.setattr(agent_server, "token_verifier", Verifier())

    with pytest.raises(agent_server.Auth.exceptions.HTTPException) as error:
        await agent_server.authenticate("Bearer invalid")

    assert error.value.status_code == 401


async def test_development_studio_access_is_explicit() -> None:
    original_settings = agent_server.settings
    try:
        agent_server.settings = SimpleNamespace(auth_mode="none", env="development")
        user = await agent_server.authenticate(None)
    finally:
        agent_server.settings = original_settings

    assert user["identity"] == "studio:development"
    assert user["is_authenticated"] is True


async def test_thread_create_stamps_authenticated_owner() -> None:
    value = {"metadata": {"client_field": "kept", "owner": "forged"}}

    filters = await agent_server.create_thread(
        _context(permissions=frozenset({"agent:invoke"})), value
    )

    assert value["metadata"] == {"client_field": "kept", "owner": "opaque-owner-a"}
    assert filters == {"owner": "opaque-owner-a"}


@pytest.mark.parametrize("handler", [agent_server.read_thread, agent_server.search_threads])
async def test_thread_read_and_search_are_owner_filtered(handler: object) -> None:
    result = await handler(  # type: ignore[operator]
        _context(permissions=frozenset({"threads:read"})), {}
    )

    assert result == {"owner": "opaque-owner-a"}


async def test_thread_run_requires_invoke_and_is_owner_filtered() -> None:
    result = await agent_server.create_thread_run(
        _context(permissions=frozenset({"agent:invoke"})), {"thread_id": "thread"}
    )

    assert result == {"owner": "opaque-owner-a"}


async def test_assistant_creation_requires_write_and_stamps_owner() -> None:
    value = {"metadata": None}

    result = await agent_server.create_assistant(
        _context(permissions=frozenset({"assistants:write"})), value
    )

    assert value["metadata"] == {"owner": "opaque-owner-a"}
    assert result == {"owner": "opaque-owner-a"}


async def test_missing_permission_is_denied() -> None:
    with pytest.raises(agent_server.Auth.exceptions.HTTPException) as error:
        await agent_server.create_thread(_context(), {})

    assert error.value.status_code == 403


async def test_unregistered_action_is_denied_by_global_handler() -> None:
    assert await agent_server.deny_unregistered_actions(_context(), {}) is False


def test_langgraph_json_registers_custom_auth() -> None:
    import json
    from pathlib import Path

    config = json.loads(Path("langgraph.json").read_text(encoding="utf-8"))

    assert config["graphs"]["main"] == "neuron_agent.graphs.main_graph:graph"
    assert config["auth"]["path"] == "neuron_agent.security.agent_server:auth"
