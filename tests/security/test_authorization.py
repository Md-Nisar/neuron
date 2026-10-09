from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from langchain.agents.middleware import ModelRequest, ModelResponse
from langchain_core.language_models.fake_chat_models import FakeListChatModel
from langchain_core.messages import AIMessage
from langgraph.runtime import Runtime
from pydantic import SecretStr

from neuron_agent.api import main as api_main
from neuron_agent.schemas.agent import AgentResponse, ThreadHistoryResponse
from neuron_agent.security.auth import Principal, require_principal
from neuron_agent.security.authorization import AuthorizationContext, TokenUsageAccumulator
from neuron_agent.services.streaming import StreamEvent
from neuron_agent.tools import calculator, utc_now


def test_every_v1_route_declares_exactly_one_permission() -> None:
    routes = [
        route
        for route in api_main.app.routes
        if isinstance(route, APIRoute) and route.path.startswith("/v1/")
    ]
    assert routes
    for route in routes:
        permissions = [
            getattr(dependency.call, "required_permission", None)
            for dependency in route.dependant.dependencies
            if getattr(dependency.call, "required_permission", None) is not None
        ]
        assert len(permissions) == 1, f"{route.path} must declare exactly one permission"


def test_routes_without_required_permissions_return_insufficient_scope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(api_main.settings, "auth_mode", "jwt")
    monkeypatch.setattr(api_main.settings, "identity_hash_key", SecretStr("i" * 32))
    denied = Principal(
        issuer="https://issuer.test",
        subject="caller",
        scopes=frozenset(),
        token_id=None,
        expires_at=datetime.now(UTC),
    )
    api_main.app.dependency_overrides[require_principal] = lambda: denied
    requests = [
        ("POST", "/v1/agent/invoke", {"message": "hi"}, "agent:invoke"),
        ("POST", "/v1/agent/stream", {"message": "hi"}, "agent:invoke"),
        (
            "GET",
            "/v1/threads/00000000-0000-0000-0000-000000000001/messages",
            None,
            "threads:read",
        ),
        (
            "DELETE",
            "/v1/threads/00000000-0000-0000-0000-000000000001",
            None,
            "threads:delete",
        ),
    ]
    try:
        with TestClient(api_main.app) as client:
            for method, path, body, permission in requests:
                response = client.request(method, path, json=body)
                assert response.status_code == 403
                assert response.json() == {"detail": "authorization_error"}
                assert response.headers["www-authenticate"] == (
                    f'Bearer error="insufficient_scope", scope="{permission}"'
                )
    finally:
        api_main.app.dependency_overrides.pop(require_principal, None)


def test_each_route_succeeds_with_its_required_permission(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(api_main.settings, "auth_mode", "jwt")
    monkeypatch.setattr(api_main.settings, "identity_hash_key", SecretStr("i" * 32))
    principal = Principal(
        issuer="https://issuer.test",
        subject="caller",
        scopes=frozenset(),
        token_id=None,
        expires_at=datetime.now(UTC),
    )
    api_main.app.dependency_overrides[require_principal] = lambda: principal

    async def invoke(_: object, **__: object) -> AgentResponse:
        return AgentResponse(
            request_id="request",
            thread_id="00000000-0000-0000-0000-000000000001",
            answer="ok",
            used_tools=[],
            confidence=1.0,
        )

    async def prepare(*_: object, **__: object) -> object:
        return SimpleNamespace(
            request_id="request",
            thread_id="00000000-0000-0000-0000-000000000001",
            run_id="run",
            lease=SimpleNamespace(release=lambda: None),
        )

    async def stream(*_: object, **__: object):
        yield StreamEvent("done")

    async def history(*_: object, **__: object) -> ThreadHistoryResponse:
        return ThreadHistoryResponse(
            thread_id="00000000-0000-0000-0000-000000000001",
            messages=[],
            total=0,
            limit=50,
            offset=0,
        )

    async def delete(*_: object, **__: object) -> None:
        return None

    async def startup() -> None:
        return None

    async def shutdown() -> None:
        return None

    monkeypatch.setattr(
        api_main,
        "service",
        SimpleNamespace(
            invoke=invoke,
            prepare=prepare,
            stream=stream,
            get_history=history,
            delete_thread=delete,
            startup=startup,
            shutdown=shutdown,
        ),
    )
    routes = [
        ("POST", "/v1/agent/invoke", {"message": "hi"}, "agent:invoke"),
        ("POST", "/v1/agent/stream", {"message": "hi"}, "agent:invoke"),
        (
            "GET",
            "/v1/threads/00000000-0000-0000-0000-000000000001/messages",
            None,
            "threads:read",
        ),
        (
            "DELETE",
            "/v1/threads/00000000-0000-0000-0000-000000000001",
            None,
            "threads:delete",
        ),
    ]
    try:
        with TestClient(api_main.app) as client:
            for method, path, body, permission in routes:
                principal = Principal(
                    issuer="https://issuer.test",
                    subject="caller",
                    scopes=frozenset({permission}),
                    token_id=None,
                    expires_at=datetime.now(UTC),
                )
                response = client.request(method, path, json=body)
                assert 200 <= response.status_code < 300, response.text
    finally:
        api_main.app.dependency_overrides.pop(require_principal, None)


@pytest.mark.anyio
async def test_model_only_sees_tools_granted_to_the_run() -> None:
    from neuron_agent.models.factory import tool_authorization_middleware

    middleware = tool_authorization_middleware()
    usage = TokenUsageAccumulator()
    request = ModelRequest(
        model=FakeListChatModel(responses=["ok"]),
        messages=[],
        tools=[utc_now, calculator],
        runtime=Runtime(context=AuthorizationContext(frozenset(), usage=usage)),
    )
    offered: list[str] = []

    async def handler(filtered: ModelRequest[object]) -> ModelResponse:
        offered.extend(tool.name for tool in filtered.tools)
        return ModelResponse(
            result=[
                AIMessage(
                    content="ok",
                    usage_metadata={
                        "input_tokens": 2,
                        "output_tokens": 1,
                        "total_tokens": 3,
                    },
                )
            ]
        )

    await middleware.awrap_model_call(request, handler)
    assert offered == ["utc_now"]
    assert usage.total_tokens == 3


@pytest.mark.anyio
async def test_forced_tool_call_is_rechecked_at_execution() -> None:
    from neuron_agent.errors.base import AuthorizationError
    from neuron_agent.models.factory import tool_authorization_middleware

    middleware = tool_authorization_middleware()
    request = SimpleNamespace(
        tool_call={"name": "calculator", "args": {"expression": "1+1"}},
        runtime=SimpleNamespace(context=AuthorizationContext(frozenset())),
    )

    async def handler(_: object) -> str:
        return "executed"

    with pytest.raises(AuthorizationError):
        await middleware.awrap_tool_call(request, handler)
