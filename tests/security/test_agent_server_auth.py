"""Agent Server authentication and resource authorization tests."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from pydantic import SecretStr

from neuron_agent.config.settings import Settings
from neuron_agent.errors.base import AuthenticationError
from neuron_agent.graphs import main_graph
from neuron_agent.models.factory import tool_authorization_middleware
from neuron_agent.schemas.agent import AgentAnswer
from neuron_agent.security import agent_server
from neuron_agent.security.auth import Principal, principal_owner_key
from neuron_agent.security.authorization import AuthorizationContext

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


# --- run authorization inside the graph (found by the v0.4.0 release gate, #63) ------


class _ContextRecordingAgent:
    """Answers "ok" and records the runtime context each run was given."""

    def __init__(self) -> None:
        self.contexts: list[object] = []

    async def ainvoke(self, inputs: dict, *, config: dict, context: object = None) -> dict:
        self.contexts.append(context)
        return {
            "messages": [*inputs["messages"], AIMessage(content="ok")],
            "structured_response": AgentAnswer(answer="ok", used_tools=[], confidence=1.0),
        }


@pytest.fixture
def recording_agent(monkeypatch: pytest.MonkeyPatch) -> _ContextRecordingAgent:
    agent = _ContextRecordingAgent()
    monkeypatch.setattr(main_graph, "build_agent", lambda settings: agent)
    return agent


_INPUT = {"messages": [HumanMessage(content="hi")]}


@pytest.mark.parametrize(
    "run_kwargs",
    [
        {"context": {"permissions": ["agent:invoke", "tools:calculator"]}},
        {"config": {"configurable": {"permissions": ["tools:calculator"]}}},
        {"context": {"permissions": ["tools:calculator"], "actor": "forged", "issuer_id": "x"}},
    ],
)
async def test_client_run_context_cannot_grant_permissions(
    recording_agent: _ContextRecordingAgent, run_kwargs: dict
) -> None:
    """Agent Server passes the client's `context` to the graph; it must carry no authority."""
    graph = main_graph.build_graph(Settings(env="test"))

    await graph.ainvoke(_INPUT, **run_kwargs)

    [authorization] = recording_agent.contexts
    assert isinstance(authorization, AuthorizationContext)
    assert authorization.permissions == frozenset()
    assert authorization.actor is None


async def test_agent_server_runs_use_the_authenticated_users_permissions(
    recording_agent: _ContextRecordingAgent,
) -> None:
    """Agent Server records the authenticated user in reserved, client-proof config keys."""
    graph = main_graph.build_graph(Settings(env="test", auth_mode="none"))
    owner = "a" * 64
    configurable = {
        "langgraph_auth_user_id": owner,
        "langgraph_auth_permissions": ["agent:invoke", "tools:calculator"],
    }

    await graph.ainvoke(
        _INPUT,
        config={"configurable": configurable},
        context={"permissions": ["threads:delete"]},  # ignored
    )

    [authorization] = recording_agent.contexts
    assert isinstance(authorization, AuthorizationContext)
    assert authorization.permissions == frozenset({"agent:invoke", "tools:calculator"})
    assert authorization.principal is None


async def test_agent_server_actor_is_the_owner_key_prefix_in_jwt_mode(
    recording_agent: _ContextRecordingAgent,
) -> None:
    settings = Settings(
        env="test",
        auth_mode="jwt",
        auth_issuer="https://issuer.example",
        auth_audience="neuron-api",
        auth_jwks_url="https://issuer.example/jwks.json",
        identity_hash_key=SecretStr("h" * 32),
        auth_issuer_id="primary",
    )
    graph = main_graph.build_graph(settings)
    configurable = {"langgraph_auth_user_id": "b" * 64, "langgraph_auth_permissions": []}

    await graph.ainvoke(_INPUT, config={"configurable": configurable})

    [authorization] = recording_agent.contexts
    assert isinstance(authorization, AuthorizationContext)
    assert (authorization.actor, authorization.issuer_id) == ("b" * 12, "primary")


async def test_agent_service_authorization_object_is_passed_through(
    recording_agent: _ContextRecordingAgent,
) -> None:
    """`AgentService` passes an `AuthorizationContext` object, which no HTTP client can send."""
    graph = main_graph.build_graph(Settings(env="test"))
    trusted = AuthorizationContext(frozenset({"tools:calculator"}), actor="actor")

    await graph.ainvoke(_INPUT, context=trusted)

    assert recording_agent.contexts == [trusted]


def test_agent_server_keeps_the_auth_keys_client_proof() -> None:
    """The fix relies on Agent Server stripping these keys from client requests."""
    from langgraph_api.validation import RESERVED_CONFIGURABLE_KEYS

    assert {"langgraph_auth_user_id", "langgraph_auth_permissions"} <= set(
        RESERVED_CONFIGURABLE_KEYS
    )


async def test_tool_middleware_grants_nothing_to_a_plain_dict_context() -> None:
    """A client-shaped context never authorizes a tool, even if it lists the permission."""
    middleware = tool_authorization_middleware()
    request = SimpleNamespace(
        tool_call={"name": "calculator", "args": {}, "id": "call-1"},
        runtime=SimpleNamespace(context={"permissions": ["tools:calculator"]}),
    )

    async def handler(_: object) -> str:
        raise AssertionError("the tool must not run")

    result = await middleware.awrap_tool_call(request, handler)
    assert isinstance(result, ToolMessage)
    assert result.status == "error"
