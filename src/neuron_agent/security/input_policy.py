# Copyright 2026 Md Nisar Ahmed
# SPDX-License-Identifier: Apache-2.0

"""Input and tool policy enforcement."""

from __future__ import annotations

import ipaddress
import re
import unicodedata
from collections.abc import Iterable
from urllib.parse import urlparse

from neuron_agent.errors.base import AuthorizationError, ValidationAppError
from neuron_agent.observability import metrics

HIGH_RISK_TOOL_NAMES = frozenset({"send_email", "write_file", "delete_record", "execute_payment"})

_ALLOWED_CONTROL_CHARS = frozenset({"\t", "\n", "\r"})


_UNSAFE_NAME_CHARS = re.compile(r"[^A-Za-z0-9_.-]")
MAX_AUDITED_TOOL_NAME_CHARS = 64


def audit_tool_name(tool_name: str, known_tools: Iterable[str]) -> str:
    """Return a tool name safe to log: known names as is, a model-chosen one bounded."""
    if tool_name in set(known_tools):
        return tool_name
    return _UNSAFE_NAME_CHARS.sub("?", tool_name)[:MAX_AUDITED_TOOL_NAME_CHARS] or "?"


def validate_user_message(message: str, *, max_chars: int) -> str:
    """Normalize and bound user-controlled text before it reaches the graph."""
    normalized = message.strip()
    if not normalized:
        metrics.record_policy_block("empty_message")
        raise ValidationAppError("message must not be empty")
    if len(normalized) > max_chars:
        metrics.record_policy_block("message_too_long")
        raise ValidationAppError(f"message exceeds {max_chars} characters")
    if any(
        unicodedata.category(char) == "Cc" and char not in _ALLOWED_CONTROL_CHARS
        for char in normalized
    ):
        metrics.record_policy_block("control_characters")
        raise ValidationAppError("message contains disallowed control characters")
    return normalized


def require_allowed_tool(tool_name: str, allowed_tools: Iterable[str]) -> None:
    """Enforce tool allow-list outside the model loop."""
    if tool_name not in set(allowed_tools):
        raise AuthorizationError(f"tool is not allowed: {tool_name}")
    if tool_name in HIGH_RISK_TOOL_NAMES:
        raise AuthorizationError(f"high-impact tool requires human approval: {tool_name}")


_NUMERIC_LABEL = re.compile(r"0[xX][0-9a-fA-F]*|[0-9]+")
_EMBEDDED_IPV4 = (ipaddress.ip_network("64:ff9b::/96"), ipaddress.ip_network("2002::/16"))


def _parse_ipv4_label_form(host: str) -> ipaddress.IPv4Address | None:
    """Read inet_aton-style IPv4 (1-4 parts; decimal, 0x hex, 0 octal).

    None when the host is a name; a host whose last label is numeric must be a
    valid address, as browsers and resolvers treat it, or it is rejected.
    """
    labels = host.split(".")
    if not _NUMERIC_LABEL.fullmatch(labels[-1]):
        return None
    invalid = ValidationAppError("URL host is not a valid address")
    if len(labels) > 4 or not all(_NUMERIC_LABEL.fullmatch(label) for label in labels):
        raise invalid
    try:
        parts = [
            int(label, 16 if label[:2] in {"0x", "0X"} else 8 if label[0] == "0" else 10)
            for label in labels
        ]
    except ValueError:  # "0x" with no digits, or an octal label containing 8 or 9
        raise invalid from None
    *head, last = parts
    if any(part > 255 for part in head) or last >= 256 ** (4 - len(head)):
        raise invalid
    value = last
    for position, part in enumerate(head):
        value += part << (8 * (3 - position))
    return ipaddress.IPv4Address(value)


def _reject_non_public(address: ipaddress.IPv4Address | ipaddress.IPv6Address) -> None:
    if isinstance(address, ipaddress.IPv6Address):
        if address.ipv4_mapped is not None:
            address = address.ipv4_mapped
        elif any(address in network for network in _EMBEDDED_IPV4):
            raise AuthorizationError("embedded IPv4 addresses are not allowed")
    if (
        address.is_loopback
        or address.is_private
        or address.is_link_local
        or address.is_multicast
        or address.is_reserved
        or address.is_unspecified
        or not address.is_global
    ):
        raise AuthorizationError("non-public network URLs are not allowed")


def validate_safe_url(url: str) -> str:
    """Reject URLs whose literal host is local, private or otherwise non-public.

    Checks the text of the URL only: scheme http or https, no userinfo, no
    whitespace, control characters or backslashes, and a host that is not
    ``localhost``, ``*.local`` or a loopback, private, link-local, multicast,
    reserved, unspecified or shared-space IP address. IPv4 is read the way
    ``inet_aton`` reads it (decimal, hex, octal, short forms), IPv6 may be
    IPv4-mapped, and a trailing dot is ignored. Returns ``url`` unchanged.

    This helper does no DNS resolution, so it cannot see where a *name* leads.
    A tool that fetches a URL must therefore, after calling it: resolve once,
    reject any resolved address that fails the same checks, connect to the checked
    IP (not the name again), and re-validate every redirect target the same way,
    or not follow redirects at all. See SECURITY.md.
    """
    if any(char.isspace() or char == "\\" or unicodedata.category(char) == "Cc" for char in url):
        raise ValidationAppError("URL contains disallowed characters")
    try:
        parsed = urlparse(url)
        parsed.port  # noqa: B018 - raises ValueError for a malformed port
        hostname = parsed.hostname
    except ValueError:
        raise ValidationAppError("URL is malformed") from None
    if parsed.scheme not in {"https", "http"}:
        raise ValidationAppError("URL scheme must be http or https")
    if "@" in parsed.netloc:
        raise ValidationAppError("URL must not include userinfo")
    if not hostname:
        raise ValidationAppError("URL must include a hostname")
    host = hostname.lower().rstrip(".")
    if not host:
        raise ValidationAppError("URL must include a hostname")
    if host == "localhost" or host.endswith(".localhost") or host.endswith(".local"):
        raise AuthorizationError("local network URLs are not allowed")
    address: ipaddress.IPv4Address | ipaddress.IPv6Address | None
    if ":" in host:
        if "%" in host:
            raise ValidationAppError("URL host is not a valid address")
        try:
            address = ipaddress.IPv6Address(host)
        except ValueError:
            raise ValidationAppError("URL host is not a valid address") from None
    else:
        address = _parse_ipv4_label_form(host)
    if address is not None:
        _reject_non_public(address)
    return url
