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
    with pytest.raises(httpcore2.ConnectError) as caught:
        await egress.resolve_public_address("nowhere.example.com", 443)
    # A lookup failure may be temporary, so it is not the address refusal.
    assert not isinstance(caught.value, egress.NonPublicAddressError)


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


# RAG-10.01: `fetch_public_https`, the ingestion fetcher (#578).

_OK = b"HTTP/1.1 200 OK\r\nContent-Type: text/html\r\nContent-Length: 5\r\n\r\nhello"


def _redirect(location: str) -> bytes:
    return (
        b"HTTP/1.1 302 Found\r\nLocation: " + location.encode() + b"\r\nContent-Length: 0\r\n\r\n"
    )


class _TlsFreeBackend(_RecordingBackend):
    """The mock stream has no TLS; the request still goes through the https code path."""

    async def connect_tcp(self, host: str, port: int, *args: Any, **kwargs: Any) -> Any:
        stream = await super().connect_tcp(host, port, *args, **kwargs)
        stream.start_tls = _no_tls.__get__(stream)
        return stream


async def _no_tls(self: Any, *args: Any, **kwargs: Any) -> Any:
    return self


async def _fetch(url: str, backend: Any, **kwargs: Any) -> egress.FetchedResponse:
    options: dict[str, Any] = {"max_bytes": 1024, "timeout": 5}
    return await egress.fetch_public_https(url, network_backend=backend, **options | kwargs)


async def test_a_public_page_is_fetched_from_its_checked_address(dns: _FakeDns) -> None:
    dns.answers["news.example.com"] = [[_PUBLIC]]
    backend = _TlsFreeBackend([_OK])
    fetched = await _fetch("https://news.example.com/a", backend)
    assert (fetched.body, fetched.content_type) == (b"hello", "text/html")
    assert backend.connected == [_PUBLIC]


@pytest.mark.parametrize("private", ["10.0.0.1", "169.254.169.254"])
async def test_ac1_a_name_resolving_to_a_private_or_metadata_address_is_refused(
    dns: _FakeDns, private: str
) -> None:
    dns.answers["internal.example.com"] = [[private]]
    backend = _TlsFreeBackend([_OK])
    with pytest.raises(egress.FetchError) as caught:
        await _fetch("https://internal.example.com/", backend)
    assert caught.value.code == "url_not_allowed"
    assert backend.connected == []


@pytest.mark.parametrize("literal", ["https://10.0.0.1/", "https://169.254.169.254/latest/"])
async def test_ac1_a_private_literal_address_is_refused_before_any_lookup(
    dns: _FakeDns, literal: str
) -> None:
    with pytest.raises(egress.FetchError, match="url_not_allowed"):
        await _fetch(literal, _TlsFreeBackend([]))
    assert dns.seen == []


async def test_ac2_a_redirect_to_a_private_address_is_refused(dns: _FakeDns) -> None:
    dns.answers["public.example.com"] = [[_PUBLIC]]
    dns.answers["internal.example.com"] = [["10.0.0.5"]]
    backend = _TlsFreeBackend([_redirect("https://internal.example.com/")])
    with pytest.raises(egress.FetchError) as caught:
        await _fetch("https://public.example.com/", backend)
    assert caught.value.code == "url_not_allowed"
    assert backend.connected == [_PUBLIC]


async def test_ac2_a_redirect_to_plain_http_is_refused(dns: _FakeDns) -> None:
    dns.answers["public.example.com"] = [[_PUBLIC]]
    backend = _TlsFreeBackend([_redirect("http://public.example.com/")])
    with pytest.raises(egress.FetchError, match="url_not_allowed"):
        await _fetch("https://public.example.com/", backend)
    assert backend.connected == [_PUBLIC]


async def test_ac3_a_dns_answer_that_changes_is_never_connected_to(dns: _FakeDns) -> None:
    dns.answers["rebind.example.com"] = [[_PUBLIC], ["127.0.0.1"]]
    backend = _TlsFreeBackend([_OK])
    await _fetch("https://rebind.example.com/", backend)
    assert backend.connected == [_PUBLIC]
    assert dns.seen == ["rebind.example.com"]


@pytest.mark.parametrize("env", ["development", "staging", "production"])
async def test_ac4_a_plain_http_url_is_refused_in_every_environment(
    dns: _FakeDns, monkeypatch: pytest.MonkeyPatch, env: str
) -> None:
    """A user's URL gets no development exception, unlike an operator's MCP URL."""
    monkeypatch.setenv("APP_ENV", env)
    for url in ("http://example.com/", "http://127.0.0.1:8001/"):
        with pytest.raises(egress.FetchError, match="url_not_allowed"):
            await _fetch(url, _TlsFreeBackend([]))
    assert dns.seen == []


async def test_proxy_settings_from_the_environment_are_ignored(
    dns: _FakeDns, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Through a proxy, the address checked would be the proxy's, not the page's."""
    monkeypatch.setenv("HTTPS_PROXY", "http://10.0.0.9:3128")
    monkeypatch.setenv("ALL_PROXY", "http://10.0.0.9:3128")
    dns.answers["news.example.com"] = [[_PUBLIC]]
    backend = _TlsFreeBackend([_OK])
    await _fetch("https://news.example.com/", backend)
    assert backend.connected == [_PUBLIC]


async def test_a_body_beyond_the_cap_is_refused(dns: _FakeDns) -> None:
    dns.answers["big.example.com"] = [[_PUBLIC]]
    with pytest.raises(egress.FetchError, match="fetch_too_large"):
        await _fetch("https://big.example.com/", _TlsFreeBackend([_OK]), max_bytes=4)


async def test_redirects_beyond_the_cap_are_refused(dns: _FakeDns) -> None:
    dns.answers["loop.example.com"] = [[_PUBLIC]] * 3
    hops = [_redirect("https://loop.example.com/") for _ in range(3)]
    with pytest.raises(egress.FetchError, match="fetch_too_many_redirects"):
        await _fetch("https://loop.example.com/", _TlsFreeBackend(hops), max_redirects=2)


async def test_a_non_200_answer_is_a_failure(dns: _FakeDns) -> None:
    dns.answers["gone.example.com"] = [[_PUBLIC]]
    gone = b"HTTP/1.1 404 Not Found\r\nContent-Length: 0\r\n\r\n"
    with pytest.raises(egress.FetchError, match="fetch_http_status"):
        await _fetch("https://gone.example.com/", _TlsFreeBackend([gone]))


async def test_a_name_that_does_not_resolve_is_a_failure_not_a_refusal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail(*args: object, **kwargs: object) -> None:
        raise socket.gaierror("temporary failure in name resolution")

    monkeypatch.setattr(socket, "getaddrinfo", fail)
    with pytest.raises(egress.FetchError, match="fetch_failed"):
        await _fetch("https://news.example.com/", _TlsFreeBackend([]))


async def test_the_final_url_keeps_no_userinfo_or_fragment(dns: _FakeDns) -> None:
    dns.answers["a.example.com"] = [[_PUBLIC]]
    dns.answers["b.example.com"] = [[_PUBLIC]]
    backend = _TlsFreeBackend([_redirect("https://user:secret@b.example.com/page#top"), _OK])
    fetched = await _fetch("https://a.example.com/", backend)
    assert fetched.url == "https://b.example.com/page"
