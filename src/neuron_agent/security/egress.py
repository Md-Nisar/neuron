# Copyright 2026 Md Nisar Ahmed
# SPDX-License-Identifier: Apache-2.0

"""Outbound connections that reach public addresses only (#364).

`validate_safe_url` reads the text of a URL; it cannot see where a name leads. This network
backend sits under an HTTP client and checks each connection as it is opened: it resolves the
host once, refuses the connection unless every resolved address is public, and connects to the
checked address rather than the name. A redirect to another host opens a new connection, so it
is checked the same way, and a DNS answer that changes after the check is never used.

`LimitedTransport` puts that backend under an httpx2 client with https on every hop, no proxy
from the environment and a cap on the bytes read. `fetch_public_https` is the one way ingestion
fetches a URL a user gave (ADR 0014, amendment "external sources").
"""

from __future__ import annotations

import asyncio
import ipaddress
import socket
from collections.abc import AsyncIterator, Iterable
from dataclasses import dataclass
from typing import cast

import httpcore2
import httpx2
from httpcore2 import AsyncNetworkBackend, AsyncNetworkStream

from neuron_agent.errors.base import AppError, AuthorizationError
from neuron_agent.security.input_policy import reject_non_public_address, validate_safe_url

SocketOption = (
    tuple[int, int, int] | tuple[int, int, bytes | bytearray] | tuple[int, int, None, int]
)


class NonPublicAddressError(httpcore2.ConnectError):
    """The host resolved to a non-public address, or to none; nothing was connected."""


async def resolve_public_address(host: str, port: int, *, timeout: float | None = None) -> str:
    """Resolve `host` once and return an address to connect to.

    Every address in the answer must be public, so a name with one private record is refused
    even if another record is public.
    """
    loop = asyncio.get_running_loop()
    try:
        async with asyncio.timeout(timeout):
            answers = await loop.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except TimeoutError:
        raise httpcore2.ConnectTimeout("the host name was not resolved in time") from None
    except OSError:
        # Not a refusal: the name may resolve later (a DNS outage), so nothing is decided here.
        raise httpcore2.ConnectError("the host name could not be resolved") from None
    addresses = [ipaddress.ip_address(str(answer[4][0])) for answer in answers]
    if not addresses:
        raise httpcore2.ConnectError("the host name could not be resolved")
    try:
        for address in addresses:
            reject_non_public_address(address)
    except AuthorizationError:
        raise NonPublicAddressError("the host resolves to a non-public address") from None
    return str(addresses[0])


class PublicOnlyBackend(AsyncNetworkBackend):
    """An httpcore2 network backend that opens TCP connections to checked public addresses.

    TLS still verifies the certificate against the URL's host name: httpcore2 passes the
    origin host as the server name, not the address connected to.
    """

    def __init__(self, inner: AsyncNetworkBackend | None = None) -> None:
        self._inner = inner or httpcore2.AnyIOBackend()

    async def connect_tcp(
        self,
        host: str,
        port: int,
        timeout: float | None = None,
        local_address: str | None = None,
        socket_options: Iterable[SocketOption] | None = None,
    ) -> AsyncNetworkStream:
        address = await resolve_public_address(host, port, timeout=timeout)
        return await self._inner.connect_tcp(
            address,
            port,
            timeout=timeout,
            local_address=local_address,
            socket_options=socket_options,
        )

    async def connect_unix_socket(
        self,
        path: str,
        timeout: float | None = None,
        socket_options: Iterable[SocketOption] | None = None,
    ) -> AsyncNetworkStream:
        raise NonPublicAddressError("unix sockets are not allowed")

    async def sleep(self, seconds: float) -> None:
        await self._inner.sleep(seconds)


class InsecureSchemeError(httpx2.ConnectError):
    """A request to a public address was not https; nothing was sent."""


class ResponseTooLargeError(Exception):
    """A server sent more bytes than the client reads; the connection is dropped."""


class _CountingStream(httpx2.AsyncByteStream):
    def __init__(self, inner: httpx2.AsyncByteStream, limit: int, error: type[Exception]) -> None:
        self._inner = inner
        self._limit = limit
        self._error = error

    async def __aiter__(self) -> AsyncIterator[bytes]:
        total = 0
        async for chunk in self._inner:
            total += len(chunk)
            if total > self._limit:
                raise self._error
            yield chunk

    async def aclose(self) -> None:
        await self._inner.aclose()


class LimitedTransport(httpx2.AsyncHTTPTransport):
    """Stops reading a response once it passes `limit` bytes, before it is held in memory.

    With `public_only`, every connection, a redirect's included, goes to a resolved and
    checked public address, and every request must be https (#366). No proxy from the
    environment is used: through a proxy, the address checked would be the proxy's.
    """

    too_large_error: type[Exception] = ResponseTooLargeError

    def __init__(
        self,
        limit: int,
        *,
        public_only: bool,
        network_backend: AsyncNetworkBackend | None = None,
    ) -> None:
        super().__init__(trust_env=False)
        if public_only:
            self._pool = httpcore2.AsyncConnectionPool(
                ssl_context=httpx2.create_ssl_context(trust_env=False),
                network_backend=PublicOnlyBackend(network_backend),
            )
        self._public_only = public_only
        self._limit = limit

    async def handle_async_request(self, request: httpx2.Request) -> httpx2.Response:
        if self._public_only and request.url.scheme != "https":
            # A redirect must not downgrade a public connection to plain http (#366).
            raise InsecureSchemeError("only https is allowed", request=request)
        # The count is of the bytes received. A compressed body would expand past it when it is
        # decoded, so no compression is asked for or accepted.
        request.headers["Accept-Encoding"] = "identity"
        response = await super().handle_async_request(request)
        if response.headers.get("content-encoding", "identity").lower() != "identity":
            await response.aclose()
            raise self.too_large_error
        declared = response.headers.get("content-length", "")
        if declared.isdigit() and int(declared) > self._limit:
            await response.aclose()
            raise self.too_large_error
        stream = cast("httpx2.AsyncByteStream", response.stream)
        return httpx2.Response(
            response.status_code,
            headers=response.headers,
            stream=_CountingStream(stream, self._limit, self.too_large_error),
            extensions=response.extensions,
        )


class FetchError(AppError):
    """A fetch was refused or failed; `code` is stable and safe to store and show."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class FetchedResponse:
    url: str
    content_type: str
    body: bytes


async def fetch_public_https(
    url: str,
    *,
    max_bytes: int,
    timeout: float,
    max_redirects: int = 5,
    network_backend: AsyncNetworkBackend | None = None,
) -> FetchedResponse:
    """GET a public https URL: every hop https and to a checked public address, at most
    `max_redirects` redirects, `max_bytes` read and `timeout` seconds in all.

    There is no loopback exception in any environment: the URL comes from a user.
    `network_backend` replaces the connection under the address check, for tests: it only
    ever receives an address that check has passed.
    """
    try:
        validate_safe_url(url)
    except AppError:
        raise FetchError("url_not_allowed") from None
    transport = LimitedTransport(max_bytes, public_only=True, network_backend=network_backend)
    try:
        async with (
            asyncio.timeout(timeout),
            httpx2.AsyncClient(
                transport=transport,
                follow_redirects=True,
                max_redirects=max_redirects,
                timeout=httpx2.Timeout(timeout),
                trust_env=False,
            ) as http,
        ):
            response = await http.get(url)
    except InsecureSchemeError:
        raise FetchError("url_not_allowed") from None
    except ResponseTooLargeError:
        raise FetchError("fetch_too_large") from None
    except (TimeoutError, httpx2.TimeoutException):
        raise FetchError("fetch_timeout") from None
    except httpx2.TooManyRedirects:
        raise FetchError("fetch_too_many_redirects") from None
    except httpx2.ConnectError as exc:
        # httpx2 wraps the backend's refusal; its cause says whether it was the address check.
        refused = isinstance(exc.__cause__, NonPublicAddressError)
        raise FetchError("url_not_allowed" if refused else "fetch_failed") from None
    except httpx2.HTTPError:
        raise FetchError("fetch_failed") from None
    if response.status_code != 200:
        raise FetchError("fetch_http_status")
    # The final URL came from a server's `Location`: keep no userinfo or fragment from it.
    final = response.url.copy_with(username=None, password=None, fragment=None)
    return FetchedResponse(
        url=str(final),
        content_type=response.headers.get("content-type", ""),
        body=response.content,
    )
