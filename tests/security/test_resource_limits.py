from __future__ import annotations

import asyncio
import json
import re
import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest
import structlog
from fastapi import Request
from fastapi.testclient import TestClient
from pydantic import SecretStr

from neuron_agent.api import main as api_main
from neuron_agent.config.settings import Settings
from neuron_agent.errors.base import (
    AgentExecutionError,
    ConcurrentRunsExceededError,
    QuotaExceededError,
)
from neuron_agent.graphs import main_graph
from neuron_agent.schemas.agent import AgentAnswer, AgentRequest, AgentResponse
from neuron_agent.security.auth import Principal, require_principal
from neuron_agent.security.rate_limiter import InMemoryTokenBucketRateLimiter
from neuron_agent.security.usage_budget import InMemoryRollingTokenBudget
from neuron_agent.services.agent_service import AgentService


def _principal(subject: str) -> Principal:
    return Principal(
        issuer="https://issuer.example.test",
        subject=subject,
        scopes=frozenset({"agent:invoke"}),
        token_id=None,
        expires_at=datetime.now(UTC),
    )


def _invoke_service() -> SimpleNamespace:
    async def invoke(_: object, **__: object) -> AgentResponse:
        return AgentResponse(
            request_id=str(uuid.uuid4()),
            thread_id=str(uuid.uuid4()),
            answer="ok",
            used_tools=[],
            confidence=1.0,
        )

    async def lifecycle() -> None:
        return None

    return SimpleNamespace(invoke=invoke, startup=lifecycle, shutdown=lifecycle)


def test_request_buckets_follow_principal_across_ips(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(api_main.settings, "auth_mode", "jwt")
    monkeypatch.setattr(api_main.settings, "identity_hash_key", SecretStr("i" * 32))
    monkeypatch.setattr(
        api_main,
        "rate_limiter",
        InMemoryTokenBucketRateLimiter(capacity=1, requests_per_window=1, window_seconds=60),
    )
    current = _principal("alice")

    class Verifier:
        async def verify(self, _: str | None) -> Principal:
            return current

    monkeypatch.setattr(api_main, "auth_verifier", Verifier())
    monkeypatch.setattr(api_main, "service", _invoke_service())
    try:
        with TestClient(api_main.app, client=("192.0.2.1", 5000)) as first_ip:
            assert first_ip.post("/v1/agent/invoke", json={"message": "one"}).status_code == 200
            current = _principal("bob")
            assert first_ip.post("/v1/agent/invoke", json={"message": "two"}).status_code == 200
        current = _principal("alice")
        with TestClient(api_main.app, client=("198.51.100.7", 5001)) as second_ip:
            limited = second_ip.post("/v1/agent/invoke", json={"message": "three"})
            assert limited.status_code == 429
            assert limited.json() == {"detail": "rate_limited"}
            assert limited.headers["retry-after"] == "60"
    finally:
        api_main.app.dependency_overrides.pop(require_principal, None)


def test_invalid_jwt_attempts_are_limited_before_verification(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from neuron_agent.errors.base import AuthenticationError

    monkeypatch.setattr(api_main.settings, "auth_mode", "jwt")
    monkeypatch.setattr(
        api_main,
        "rate_limiter",
        InMemoryTokenBucketRateLimiter(capacity=1, requests_per_window=1, window_seconds=60),
    )

    class RejectingVerifier:
        calls = 0

        async def verify(self, _: str | None) -> Principal:
            self.calls += 1
            raise AuthenticationError()

    verifier = RejectingVerifier()
    monkeypatch.setattr(api_main, "auth_verifier", verifier)
    with structlog.testing.capture_logs() as logs:
        with TestClient(api_main.app) as client:
            headers = {
                "Authorization": "Bearer eyJhbGciOiJub25lIn0.eyJzdWIiOiJzZW5zaXRpdmUifQ.signature"
            }
            first = client.post("/v1/agent/invoke", json={"message": "hi"}, headers=headers)
            second = client.post("/v1/agent/invoke", json={"message": "hi"}, headers=headers)

    assert first.status_code == 401
    assert second.status_code == 429
    assert second.headers["retry-after"] == "60"
    assert verifier.calls == 2
    rendered = json.dumps(logs)
    assert "eyJhbGciOiJub25lIn0.eyJzdWIiOiJzZW5zaXRpdmUifQ.signature" not in rendered
    assert not re.search(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", rendered)
    assert not re.search(r'"sub"\s*:', rendered)
    assert not re.search(r"\b(?:\d{1,3}\.){3}\d{1,3}\b", rendered)
    assert sum(entry.get("event") == "limit_exceeded" for entry in logs) == 1


def test_untrusted_forwarded_for_is_ignored(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(api_main.settings, "trusted_proxies", ["10.0.0.0/8"])
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/",
            "headers": [(b"x-forwarded-for", b"203.0.113.8")],
            "client": ("198.51.100.2", 1234),
            "server": ("test", 80),
        }
    )

    assert api_main._client_ip(request) == "198.51.100.2"


def test_forwarded_for_is_used_for_configured_proxy(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(api_main.settings, "trusted_proxies", ["10.0.0.0/8"])
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/",
            "headers": [(b"x-forwarded-for", b"203.0.113.8")],
            "client": ("10.2.3.4", 1234),
            "server": ("test", 80),
        }
    )

    assert api_main._client_ip(request) == "203.0.113.8"


@pytest.mark.anyio
async def test_per_user_run_cap_applies_across_invoke_and_stream(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class IdleAgent:
        async def ainvoke(self, *_: Any, **__: Any) -> dict[str, Any]:
            return {
                "messages": [],
                "structured_response": AgentAnswer(answer="ok", used_tools=[], confidence=1.0),
            }

    monkeypatch.setattr(main_graph, "build_agent", lambda _: IdleAgent())
    service = AgentService(_jwt_settings(max_concurrent_runs_per_user=1))
    first = await service.prepare(
        AgentRequest(message="stream"), streaming=True, principal=_principal("alice")
    )
    with pytest.raises(ConcurrentRunsExceededError):
        await service.prepare(AgentRequest(message="invoke"), principal=_principal("alice"))

    other = await service.prepare(AgentRequest(message="other"), principal=_principal("bob"))
    first.lease.release()
    other.lease.release()
    # A principal can start again after its prior run releases its lease.
    next_run = await service.prepare(AgentRequest(message="again"), principal=_principal("alice"))
    next_run.lease.release()


@pytest.mark.anyio
async def test_token_budget_charges_model_usage_and_recovers_after_window(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Clock:
        now = 100.0

        def __call__(self) -> float:
            return self.now

    clock = Clock()
    budget = InMemoryRollingTokenBudget(token_limit=5, window_seconds=10, clock=clock)

    class UsageAgent:
        calls = 0

        async def ainvoke(self, *_: Any, context: Any, **__: Any) -> dict[str, Any]:
            self.calls += 1
            context.usage.record({"input_tokens": 3, "output_tokens": 2, "total_tokens": 5})
            return {
                "messages": [],
                "structured_response": AgentAnswer(answer="ok", used_tools=[], confidence=1.0),
            }

    agent = UsageAgent()
    monkeypatch.setattr(main_graph, "build_agent", lambda _: agent)
    service = AgentService(
        _jwt_settings(user_token_budget=5, user_token_budget_window_seconds=10),
        token_budget=budget,
    )
    await service.invoke(AgentRequest(message="first"), principal=_principal("alice"))
    with pytest.raises(QuotaExceededError) as denied:
        await service.prepare(AgentRequest(message="blocked"), principal=_principal("alice"))
    assert denied.value.retry_after_seconds == 10
    assert agent.calls == 1

    clock.now += 10
    await service.invoke(AgentRequest(message="after expiry"), principal=_principal("alice"))
    assert agent.calls == 2


@pytest.mark.anyio
async def test_failed_run_usage_is_charged_to_the_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FailingUsageAgent:
        async def ainvoke(self, *_: Any, context: Any, **__: Any) -> dict[str, Any]:
            context.usage.record({"total_tokens": 4})
            raise RuntimeError("model failed after returning usage")

    monkeypatch.setattr(main_graph, "build_agent", lambda _: FailingUsageAgent())
    service = AgentService(_jwt_settings(user_token_budget=4))
    with pytest.raises(AgentExecutionError):
        await service.invoke(AgentRequest(message="fail"), principal=_principal("alice"))
    with pytest.raises(QuotaExceededError):
        await service.prepare(AgentRequest(message="blocked"), principal=_principal("alice"))


@pytest.mark.anyio
async def test_cancelled_run_usage_is_charged_to_the_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class CancellableUsageAgent:
        started = asyncio.Event()

        async def ainvoke(self, *_: Any, context: Any, **__: Any) -> dict[str, Any]:
            context.usage.record({"total_tokens": 4})
            self.started.set()
            await asyncio.Event().wait()
            return {}

    agent = CancellableUsageAgent()
    monkeypatch.setattr(main_graph, "build_agent", lambda _: agent)
    service = AgentService(_jwt_settings(user_token_budget=4))
    run = await service.prepare(
        AgentRequest(message="cancel"), streaming=True, principal=_principal("alice")
    )
    events = service.stream(run)
    assert (await anext(events)).event == "run_started"
    await agent.started.wait()
    await events.aclose()

    with pytest.raises(QuotaExceededError):
        await service.prepare(AgentRequest(message="blocked"), principal=_principal("alice"))


def test_quota_error_has_stable_http_status_and_retry_after() -> None:
    error = QuotaExceededError(23)
    response = api_main._http_error("quota_exceeded", error)

    assert response.status_code == 429
    assert response.detail == "quota_exceeded"
    assert response.headers == {"Retry-After": "23"}


def _jwt_settings(**overrides: Any) -> Settings:
    return Settings(
        env="test",
        auth_mode="jwt",
        auth_issuer="https://issuer.example.test",
        auth_audience="neuron-api",
        auth_jwks_url="https://issuer.example.test/jwks.json",
        identity_hash_key="h" * 32,
        openai_api_key=None,
        **overrides,
    )
