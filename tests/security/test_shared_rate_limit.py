"""Shared rate limiting (#148): key derivation, the in-memory pre-limit, proxy keys, fail closed.

These run without a database, with stand-in limiters. The Postgres limiter itself, and the
two-process burst, are in `tests/integration/test_postgres_rate_limiter.py`.
"""

from __future__ import annotations

import hashlib
import hmac
import uuid
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from neuron_agent.api import main as api_main
from neuron_agent.errors.base import AuthenticationError, PersistenceError
from neuron_agent.schemas.agent import AgentResponse
from neuron_agent.security.auth import Principal, ip_rate_key, principal_owner_key
from neuron_agent.security.rate_limiter import (
    InMemoryTokenBucketRateLimiter,
    RateLimitDecision,
)

KEY = "k" * 32
BODY = {"message": "hi"}


class Recording:
    """A limiter that records each key it is asked about, in front of a real bucket."""

    def __init__(self, burst: int) -> None:
        self.keys: list[str] = []
        self._inner = InMemoryTokenBucketRateLimiter(
            capacity=burst, requests_per_window=1, window_seconds=3600
        )

    async def check(self, key: str) -> RateLimitDecision:
        self.keys.append(key)
        return await self._inner.check(key)


class Down:
    """A limiter whose database is unavailable."""

    calls = 0

    async def check(self, key: str) -> RateLimitDecision:
        self.calls += 1
        raise PersistenceError("rate limiter unavailable")


class Verifier:
    async def verify(self, authorization: str | None) -> Principal:
        if authorization is None:
            raise AuthenticationError()
        return Principal(
            issuer="https://issuer.example.test",
            subject="alice",
            scopes=frozenset({"agent:invoke"}),
            token_id=None,
            expires_at=datetime.now(UTC),
        )


@pytest.fixture
def invoked(monkeypatch: pytest.MonkeyPatch) -> list[object]:
    calls: list[object] = []

    async def invoke(_: object, *args: object, **__: object) -> AgentResponse:
        calls.append(args)
        return AgentResponse(
            request_id=str(uuid.uuid4()),
            thread_id=str(uuid.uuid4()),
            answer="ok",
            used_tools=[],
            confidence=1.0,
        )

    async def lifecycle() -> None:
        return None

    monkeypatch.setattr(
        api_main, "service", SimpleNamespace(invoke=invoke, startup=lifecycle, shutdown=lifecycle)
    )
    monkeypatch.setattr(api_main.settings, "identity_hash_key", SecretStr(KEY))
    return calls


def _jwt(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(api_main.settings, "auth_mode", "jwt")
    monkeypatch.setattr(api_main, "auth_verifier", Verifier())


def test_ip_key_is_a_pseudonym_in_its_own_namespace_and_differs_from_the_owner_key() -> None:
    key = ip_rate_key("203.0.113.8", KEY)
    assert key.startswith("ip:") and "203.0.113.8" not in key and len(key) == 3 + 64
    assert key == ip_rate_key("203.0.113.8", KEY)  # stable, so replicas agree
    assert key != ip_rate_key("203.0.113.9", KEY)
    assert key != ip_rate_key("203.0.113.8", "j" * 32)  # keyed
    # The owner-key derivation (the identity key itself as the HMAC key) gives another value
    # for the same input: no owner key can be forged or confused with an IP key.
    owner_style = hmac.new(KEY.encode(), b"203.0.113.8", hashlib.sha256).hexdigest()
    assert key.removeprefix("ip:") != owner_style
    principal = Principal("iss", "sub", frozenset(), None, datetime.now(UTC))
    assert principal_owner_key(principal, KEY) != key.removeprefix("ip:")


def test_without_an_identity_key_the_address_is_the_key_in_process_memory_only() -> None:
    assert ip_rate_key("203.0.113.8", None) == "ip:203.0.113.8"


def test_two_ipv6_addresses_in_one_64_share_a_key(
    monkeypatch: pytest.MonkeyPatch, invoked: list[object]
) -> None:
    recorder = Recording(burst=10)
    monkeypatch.setattr(api_main, "ip_rate_limiter", recorder)
    for peer in ("2001:db8:1:2:aaaa:bbbb:cccc:dddd", "2001:db8:1:2::1", "2001:db8:1:3::1"):
        with TestClient(api_main.app, client=(peer, 5000)) as client:
            assert client.post("/v1/agent/invoke", json=BODY).status_code == 200
    first, second, other = recorder.keys
    assert first == second != other
    assert first == ip_rate_key("2001:db8:1:2::/64", KEY)


def test_a_request_through_the_proxy_is_keyed_by_the_real_client_not_a_spoofed_entry(
    monkeypatch: pytest.MonkeyPatch, invoked: list[object]
) -> None:
    monkeypatch.setattr(api_main.settings, "trusted_proxies", ["10.0.0.0/8"])
    recorder = Recording(burst=10)
    monkeypatch.setattr(api_main, "ip_rate_limiter", recorder)
    with TestClient(api_main.app, client=("10.2.3.4", 5000)) as client:
        for spoof in ("198.51.100.1", "198.51.100.2", "::1"):
            headers = {"X-Forwarded-For": f"{spoof}, 203.0.113.8"}
            assert client.post("/v1/agent/invoke", json=BODY, headers=headers).status_code == 200
    real = ip_rate_key("203.0.113.8", KEY)
    assert recorder.keys == [real, real, real]  # the leftmost entry decides nothing
    # A direct caller cannot choose its key with the header either.
    with TestClient(api_main.app, client=("192.0.2.7", 5000)) as direct:
        direct.post("/v1/agent/invoke", json=BODY, headers={"X-Forwarded-For": "203.0.113.8"})
    assert recorder.keys[-1] == ip_rate_key("192.0.2.7", KEY)


def test_an_unauthenticated_flood_is_stopped_by_the_pre_limit_before_the_shared_limiter(
    monkeypatch: pytest.MonkeyPatch, invoked: list[object]
) -> None:
    _jwt(monkeypatch)
    shared = Recording(burst=1000)  # never the one to refuse
    monkeypatch.setattr(api_main, "ip_rate_limiter", shared)
    monkeypatch.setattr(
        api_main,
        "ip_pre_limiter",
        InMemoryTokenBucketRateLimiter(capacity=3, requests_per_window=1, window_seconds=3600),
    )
    with TestClient(api_main.app, client=("192.0.2.9", 5000)) as client:
        statuses = [client.post("/v1/agent/invoke", json=BODY).status_code for _ in range(50)]
    assert statuses == [401] * 3 + [429] * 47
    assert len(shared.keys) == 3  # three writes, not fifty
    assert invoked == []


def test_a_flood_without_authentication_configured_is_also_pre_limited(
    monkeypatch: pytest.MonkeyPatch, invoked: list[object]
) -> None:
    shared = Recording(burst=1000)
    monkeypatch.setattr(api_main, "ip_rate_limiter", shared)
    monkeypatch.setattr(
        api_main,
        "ip_pre_limiter",
        InMemoryTokenBucketRateLimiter(capacity=2, requests_per_window=1, window_seconds=3600),
    )
    with TestClient(api_main.app, client=("192.0.2.9", 5000)) as client:
        statuses = [client.post("/v1/agent/invoke", json=BODY).status_code for _ in range(10)]
    assert statuses == [200] * 2 + [429] * 8
    assert len(shared.keys) == 2


def test_a_shared_limiter_failure_fails_closed_without_authentication(
    monkeypatch: pytest.MonkeyPatch, invoked: list[object]
) -> None:
    down = Down()
    monkeypatch.setattr(api_main, "ip_rate_limiter", down)
    with TestClient(api_main.app) as client:
        response = client.post("/v1/agent/invoke", json=BODY)
    assert (response.status_code, response.json()) == (503, {"detail": "internal_server_error"})
    assert down.calls == 1 and invoked == []


def test_a_shared_limiter_failure_fails_closed_for_a_failed_authentication(
    monkeypatch: pytest.MonkeyPatch, invoked: list[object]
) -> None:
    _jwt(monkeypatch)
    monkeypatch.setattr(api_main, "ip_rate_limiter", Down())
    with TestClient(api_main.app) as client:
        response = client.post("/v1/agent/invoke", json=BODY)  # no token
    assert response.status_code == 503 and invoked == []


def test_a_shared_limiter_failure_fails_closed_for_an_authenticated_caller(
    monkeypatch: pytest.MonkeyPatch, invoked: list[object]
) -> None:
    _jwt(monkeypatch)
    down = Down()
    monkeypatch.setattr(api_main, "principal_rate_limiter", down)
    with TestClient(api_main.app) as client:
        response = client.post("/v1/agent/invoke", json=BODY, headers={"Authorization": "Bearer t"})
    assert (response.status_code, response.json()) == (503, {"detail": "internal_server_error"})
    assert down.calls == 1 and invoked == []


def test_authenticated_callers_do_not_touch_the_ip_limiters(
    monkeypatch: pytest.MonkeyPatch, invoked: list[object]
) -> None:
    _jwt(monkeypatch)
    ip = Recording(burst=10)
    principal = Recording(burst=10)
    monkeypatch.setattr(api_main, "ip_rate_limiter", ip)
    monkeypatch.setattr(api_main, "ip_pre_limiter", Down())
    monkeypatch.setattr(api_main, "principal_rate_limiter", principal)
    with TestClient(api_main.app) as client:
        response = client.post("/v1/agent/invoke", json=BODY, headers={"Authorization": "Bearer t"})
    assert response.status_code == 200 and ip.keys == []
    assert principal.keys[0].startswith("principal:")
