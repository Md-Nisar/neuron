"""Outbound connections resolve, check and pin their address (#364); fetches are https (#366)."""

from __future__ import annotations

import socket
from typing import Any

import httpcore2
import httpx2
import pytest
import structlog.testing

from neuron_agent.errors.base import ValidationAppError
from neuron_agent.security import egress
from neuron_agent.security.input_policy import validate_safe_url
from neuron_agent.tools.mcp import client as mcp_client
from neuron_agent.tools.mcp.urls import validate_mcp_url

pytestmark = pytest.mark.anyio

_PUBLIC = "93.184.215.14"


def _answer(*addresses: str) -> list[Any]:
    family = {4: socket.AF_INET, 6: socket.AF_INET6}
    return [(family[6 if ":" in a else 4], socket.SOCK_STREAM, 6, "", (a, 443)) for a in addresses]


class _FakeDns:
    """Each lookup of a name returns its next answer; every lookup is recorded."""

    def __init__(self) -> None:
        self.answers: dict[str, list[list[str]]] = {}
        self.seen: list[str] = []

    def getaddrinfo(self, host: str, *args: object, **kwargs: object) -> list[Any]:
        self.seen.append(host)
        return _answer(*self.answers[host].pop(0))


@pytest.fixture
def dns(monkeypatch: pytest.MonkeyPatch) -> _FakeDns:
    fake = _FakeDns()
    monkeypatch.setattr(socket, "getaddrinfo", fake.getaddrinfo)
    return fake


class _RecordingBackend(httpcore2.AsyncMockBackend):
    def __init__(self, buffer: list[bytes]) -> None:
        super().__init__(buffer)
        self.connected: list[str] = []

    async def connect_tcp(self, host: str, port: int, *args: Any, **kwargs: Any) -> Any:
        self.connected.append(host)
        return await super().connect_tcp(host, port, *args, **kwargs)


@pytest.mark.parametrize(
    "private",
    ["10.0.0.1", "169.254.169.254", "127.0.0.1", "::1", "::ffff:10.0.0.1", "fe80::1%eth0"],
)
async def test_a_name_that_resolves_to_a_non_public_address_is_refused(
    dns: _FakeDns, private: str
) -> None:
    dns.answers["metadata.example.com"] = [[private]]
    with pytest.raises(egress.NonPublicAddressError):
        await egress.resolve_public_address("metadata.example.com", 443)


async def test_one_private_record_among_public_ones_refuses_the_name(
    dns: _FakeDns,
) -> None:
    dns.answers["mixed.example.com"] = [[_PUBLIC, "10.0.0.1"]]
    with pytest.raises(egress.NonPublicAddressError):
        await egress.resolve_public_address("mixed.example.com", 443)


async def test_a_name_that_does_not_resolve_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail(*args: object, **kwargs: object) -> None:
        raise socket.gaierror("no such name")

    monkeypatch.setattr(socket, "getaddrinfo", fail)
    with pytest.raises(egress.NonPublicAddressError):
        await egress.resolve_public_address("nowhere.example.com", 443)


async def test_the_connection_goes_to_the_checked_address_not_a_new_answer(
    dns: _FakeDns,
) -> None:
    """DNS rebinding: the second answer (private) is never connected to."""
    dns.answers["rebind.example.com"] = [[_PUBLIC], ["127.0.0.1"]]
    inner = _RecordingBackend([b"HTTP/1.1 200 OK\r\nContent-Length: 0\r\n\r\n"])
    pool = httpcore2.AsyncConnectionPool(network_backend=egress.PublicOnlyBackend(inner))
    response = await pool.request("GET", "http://rebind.example.com/")
    assert response.status == 200
    assert inner.connected == [_PUBLIC]
    assert dns.seen == ["rebind.example.com"]


async def test_a_redirect_to_a_private_address_is_refused(
    dns: _FakeDns,
) -> None:
    dns.answers["public.example.com"] = [[_PUBLIC]]
    dns.answers["internal.example.com"] = [["10.0.0.5"]]
    inner = _RecordingBackend(
        [b"HTTP/1.1 307 Temporary Redirect\r\nLocation: https://internal.example.com/\r\n"
         b"Content-Length: 0\r\n\r\n"]
    )  # fmt: skip
    transport = mcp_client._LimitedTransport(1024, public_only=True)
    transport._pool = httpcore2.AsyncConnectionPool(network_backend=egress.PublicOnlyBackend(inner))
    async with httpx2.AsyncClient(transport=transport, follow_redirects=True) as http:
        with pytest.raises(httpx2.ConnectError):
            await http.get("https://public.example.com/")
    assert inner.connected == [_PUBLIC]


async def test_unix_sockets_are_refused() -> None:
    with pytest.raises(egress.NonPublicAddressError):
        await egress.PublicOnlyBackend().connect_unix_socket("/var/run/docker.sock")


async def test_an_mcp_server_name_that_resolves_to_loopback_is_never_contacted(
    dns: _FakeDns, monkeypatch: pytest.MonkeyPatch
) -> None:
    dns.answers["mcp.example.com"] = [["127.0.0.1"]]

    async def must_not_connect(*args: object, **kwargs: object) -> None:
        raise AssertionError("no connection may be opened")

    monkeypatch.setattr(httpcore2.AnyIOBackend, "connect_tcp", must_not_connect)
    with pytest.raises(Exception) as caught:
        await mcp_client.fetch_definitions(
            "https://mcp.example.com/mcp", token=None, env="production", timeout=5
        )
    assert not isinstance(caught.value, AssertionError)
    assert dns.seen == ["mcp.example.com"]


async def test_a_public_connection_is_never_plain_http(dns: _FakeDns) -> None:
    transport = mcp_client._LimitedTransport(1024, public_only=True)
    async with httpx2.AsyncClient(transport=transport) as http:
        with pytest.raises(httpx2.ConnectError):
            await http.get("http://public.example.com/")
    assert dns.seen == []


def test_plain_http_urls_are_refused_by_default() -> None:
    with pytest.raises(ValidationAppError, match="https"):
        validate_safe_url("http://example.com/")
    assert validate_safe_url("http://example.com/", allow_http=True) == "http://example.com/"


@pytest.mark.parametrize("env", ["staging", "production"])
def test_an_http_mcp_url_is_refused_outside_development(env: str) -> None:
    with pytest.raises(Exception, match="https"):
        validate_mcp_url("http://mcp.example.com/mcp", env=env)


def test_the_loopback_http_exception_is_logged() -> None:
    with structlog.testing.capture_logs() as logs:
        validate_mcp_url("http://127.0.0.1:8001/mcp", env="development")
    assert [entry["event"] for entry in logs] == ["mcp_plain_http_allowed"]
