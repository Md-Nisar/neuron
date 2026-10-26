"""Rate-limit key hygiene (#166): client address keys and separate IP/principal limiters."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from fastapi import Request
from fastapi.testclient import TestClient
from pydantic import SecretStr

from neuron_agent.api import main as api_main
from neuron_agent.errors.base import AuthenticationError
from neuron_agent.schemas.agent import AgentResponse
from neuron_agent.security.auth import Principal
from neuron_agent.security.rate_limiter import InMemoryTokenBucketRateLimiter


def _request(peer: str, *forwarded: bytes) -> Request:
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/",
            "headers": [(b"x-forwarded-for", line) for line in forwarded],
            "client": (peer, 1234),
            "server": ("test", 80),
        }
    )


@pytest.mark.parametrize(
    ("peer", "expected"),
    [
        ("2001:db8:1:2:aaaa:bbbb:cccc:dddd", "2001:db8:1:2::/64"),
        ("2001:db8:1:2::1", "2001:db8:1:2::/64"),
        ("2001:db8:1:3::1", "2001:db8:1:3::/64"),
        ("::ffff:192.0.2.5", "192.0.2.5"),
        ("192.0.2.5", "192.0.2.5"),
        ("fe80::1%eth0", "fe80::/64"),
    ],
)
def test_ipv6_is_keyed_by_64_and_mapped_ipv4_is_unmapped(peer: str, expected: str) -> None:
    assert api_main._client_ip(_request(peer)) == expected


def test_forwarded_addresses_get_the_same_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(api_main.settings, "trusted_proxies", ["10.0.0.0/8"])

    assert api_main._client_ip(_request("10.2.3.4", b"2001:db8:9:9::7")) == "2001:db8:9:9::/64"
    assert api_main._client_ip(_request("10.2.3.4", b"::ffff:203.0.113.8")) == "203.0.113.8"


def test_forwarded_for_lines_are_joined(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(api_main.settings, "trusted_proxies", ["10.0.0.0/8"])
    # A client-supplied first line must not hide the address the proxy appended last.
    request = _request("10.2.3.4", b"198.51.100.77", b"203.0.113.8, 10.1.1.1")

    assert api_main._client_ip(request) == "203.0.113.8"


@pytest.mark.parametrize(
    "bad",
    [
        b"x",
        b"203.0.113.8:",
        b"203.0.113.8:99999",
        b"203.0.113.8:44:44",
        b"[203.0.113.8]:443",
        b"[2001:db8::1",
        b"[2001:db8::1]:",
        b"[2001:db8::1]:x",
        b"[2001:db8::1]443",
        b"2001:db8::1]:443",
    ],
)
def test_unparseable_forwarded_entry_stops_the_walk_at_the_last_good_address(
    monkeypatch: pytest.MonkeyPatch, bad: bytes
) -> None:
    monkeypatch.setattr(api_main.settings, "trusted_proxies", ["10.0.0.0/8"])

    # Nothing left of the bad entry is believed, including the spoofable 198.51.100.77.
    assert api_main._client_ip(_request("10.2.3.4", b"198.51.100.77, " + bad)) == "10.2.3.4"
    # Pins "the last good address is the key": here that is the trusted hop 10.9.9.9 itself.
    assert api_main._client_ip(_request("10.2.3.4", b"198.51.100.77", bad + b", 10.9.9.9")) == (
        "10.9.9.9"
    )


@pytest.mark.parametrize(
    ("entry", "expected"),
    [
        (b"203.0.113.8", "203.0.113.8"),
        (b"203.0.113.8:4444", "203.0.113.8"),
        (b"2001:db8:9:9::7", "2001:db8:9:9::/64"),
        (b"[2001:db8:9:9::7]", "2001:db8:9:9::/64"),
        (b"[2001:db8:9:9::7]:443", "2001:db8:9:9::/64"),
        (b"[::ffff:203.0.113.8]:443", "203.0.113.8"),
    ],
)
def test_forwarded_entry_port_and_brackets_are_stripped(
    monkeypatch: pytest.MonkeyPatch, entry: bytes, expected: str
) -> None:
    monkeypatch.setattr(api_main.settings, "trusted_proxies", ["10.0.0.0/8"])

    assert api_main._client_ip(_request("10.2.3.4", b"198.51.100.77, " + entry)) == expected
    # A trusted hop with a port is still skipped, and the spoofed leftmost entry stays ignored.
    chain = b"198.51.100.77, " + entry + b", 10.1.1.1:8080"
    assert api_main._client_ip(_request("10.2.3.4", chain)) == expected


def test_forwarded_port_cannot_hide_a_spoofed_entry(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(api_main.settings, "trusted_proxies", ["10.0.0.0/8"])

    # Garbage right of a real client stops the walk at the trusted peer, not at the left entry.
    assert api_main._client_ip(_request("10.2.3.4", b"198.51.100.77:1, junk:1")) == "10.2.3.4"


def test_forwarded_for_is_ignored_without_trusted_proxies(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(api_main.settings, "trusted_proxies", [])

    assert api_main._client_ip(_request("10.2.3.4", b"203.0.113.8")) == "10.2.3.4"


def test_ip_and_principal_limiters_are_separate_instances() -> None:
    assert api_main.ip_rate_limiter is not api_main.principal_rate_limiter


def test_junk_ip_keys_cannot_evict_a_principal_bucket(monkeypatch: pytest.MonkeyPatch) -> None:
    def small() -> InMemoryTokenBucketRateLimiter:
        return InMemoryTokenBucketRateLimiter(
            capacity=1, requests_per_window=1, window_seconds=3600, max_buckets=3
        )

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

    monkeypatch.setattr(api_main.settings, "auth_mode", "jwt")
    monkeypatch.setattr(api_main.settings, "identity_hash_key", SecretStr("i" * 32))
    monkeypatch.setattr(api_main, "ip_rate_limiter", small())
    monkeypatch.setattr(api_main, "principal_rate_limiter", small())
    monkeypatch.setattr(api_main, "auth_verifier", Verifier())
    monkeypatch.setattr(
        api_main, "service", SimpleNamespace(invoke=invoke, startup=lifecycle, shutdown=lifecycle)
    )
    headers = {"Authorization": "Bearer token"}
    body = {"message": "hi"}

    with TestClient(api_main.app, client=("192.0.2.1", 5000)) as alice:
        assert alice.post("/v1/agent/invoke", json=body, headers=headers).status_code == 200
    for host in range(10):
        with TestClient(api_main.app, client=(f"198.51.100.{host}", 5000)) as junk:
            assert junk.post("/v1/agent/invoke", json=body).status_code == 401
    with TestClient(api_main.app, client=("192.0.2.1", 5000)) as alice:
        again = alice.post("/v1/agent/invoke", json=body, headers=headers)

    assert again.status_code == 429


def test_mapped_ipv4_trusted_proxy_peer_is_trusted(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(api_main.settings, "trusted_proxies", ["10.0.0.0/8"])

    assert api_main._client_ip(_request("::ffff:10.2.3.4", b"203.0.113.8")) == "203.0.113.8"


def test_mapped_ipv4_trusted_hop_in_forwarded_for_is_trusted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(api_main.settings, "trusted_proxies", ["10.0.0.0/8"])

    request = _request("10.2.3.4", b"198.51.100.77, 203.0.113.8, ::ffff:10.1.1.1")
    assert api_main._client_ip(request) == "203.0.113.8"


def test_empty_forwarded_entry_keeps_the_last_good_address(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(api_main.settings, "trusted_proxies", ["10.0.0.0/8"])

    assert api_main._client_ip(_request("10.2.3.4", b"203.0.113.8,")) == "10.2.3.4"
    assert api_main._client_ip(_request("10.2.3.4", b"203.0.113.8, ,10.9.9.9")) == "10.9.9.9"
