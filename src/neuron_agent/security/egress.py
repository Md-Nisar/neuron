# Copyright 2026 Md Nisar Ahmed
# SPDX-License-Identifier: Apache-2.0

"""Outbound connections that reach public addresses only (#364).

`validate_safe_url` reads the text of a URL; it cannot see where a name leads. This network
backend sits under an HTTP client and checks each connection as it is opened: it resolves the
host once, refuses the connection unless every resolved address is public, and connects to the
checked address rather than the name. A redirect to another host opens a new connection, so it
is checked the same way, and a DNS answer that changes after the check is never used.
"""

from __future__ import annotations

import asyncio
import ipaddress
import socket
from collections.abc import Iterable

import httpcore2
from httpcore2 import AsyncNetworkBackend, AsyncNetworkStream

from neuron_agent.errors.base import AuthorizationError
from neuron_agent.security.input_policy import reject_non_public_address

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
        raise NonPublicAddressError("the host name could not be resolved") from None
    addresses = [ipaddress.ip_address(str(answer[4][0])) for answer in answers]
    if not addresses:
        raise NonPublicAddressError("the host name could not be resolved")
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
